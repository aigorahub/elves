"""Local run coordination. Board records are untrusted operator data."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterator

from .context import collect_secret_env_values, redact_structure, redact_text
from .storage import atomic_write_json, digest_key, directory_lock, guard_repo_path, read_json
from .subprocess_output import OutputLimitExceeded, run_bounded


SCHEMA = "elves-message-board-v2"
LEGACY_SCHEMA = "elves-message-board-v1"
BOARD_FILENAME = "message-board.jsonl"
ENTRY_PREFIXES = tuple(f'{{"schema":"{schema}",'.encode("ascii") for schema in (SCHEMA, LEGACY_SCHEMA))
# Bound each append and keep corrupt lines from filling a reader's line buffer.
MAX_LINE_BYTES = 16 * 1024
MAX_ENTRY_FILE_BYTES = 64 * 1024
POLL_SECONDS = 0.5
KIND_STATUSES = {
    "claim": ("in-progress",),
    "release": ("done",),
    "finding": ("blocking", "advisory"),
    "verdict": ("pass", "fail"),
    "handoff": ("ready", "blocked"),
    "question": ("open",),
    "status": ("in-progress", "done", "blocked", "failed"),
}
KINDS = tuple(KIND_STATUSES)
STATUSES = tuple(dict.fromkeys(status for choices in KIND_STATUSES.values() for status in choices))
TAGS = ("verified", "inferred", "not-verified")
REQUIRED_TAG_KINDS = ("finding", "verdict", "handoff", "status")
REQUIRED_SBAR_KINDS = ("finding", "handoff")
SBAR_FIELDS = ("situation", "background", "assessment", "recommendation")
CLOSED_QUESTION_NOTE = "Question closed."
HOSTS = ("claude", "codex", "grok", "omp", "other")
DRIVER_ROLES = ("driver", "lead")
ROLE_KINDS = {
    **dict.fromkeys(DRIVER_ROLES, KINDS),
    "worker": ("claim", "release", "handoff", "status", "question"),
    "reviewer": ("finding", "verdict", "status", "question"),
    "owner": ("status",),
}
ENTRY_KEYS = {"schema", "id", "time", "author", "kind", "body", "refs", "redacted"}
REF_KEYS = {"files", "commits", "pr", "entries"}
ENTRY_FILE_KEYS = {"sbar", "evidence", "body", "refs"}


class BoardError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _resolve_session_board(session_path: Path, session: dict) -> Path:
    run_id = session.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise BoardError("board_run_id_required", "The session must record a run_id.")
    try:
        result = run_bounded(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(session_path.parent),
            timeout=5,
            max_stdout=64 * 1024,
            max_stderr=64 * 1024,
        )
    except (OSError, OutputLimitExceeded, subprocess.TimeoutExpired) as exc:
        raise BoardError("board_git_unavailable", "Cannot locate the common Git directory.") from exc
    common = Path(os.fsdecode(result.stdout.removesuffix(b"\n")))
    if result.returncode or not common.is_absolute() or not common.is_dir():
        raise BoardError("board_git_unavailable", "Cannot locate the common Git directory.")
    common = common.resolve()
    path = guard_repo_path(
        common, common / "elves/runtime/board" / digest_key(run_id, prefix="run") / BOARD_FILENAME
    )
    if "message_board" in session and session["message_board"] != str(path):
        raise BoardError("board_session_conflict", "The session records a different board path.")
    return path


def initialize(session_path: Path) -> Path:
    session = read_json(session_path)
    path = _resolve_session_board(session_path, session)
    if "message_board" not in session:
        session["message_board"] = str(path)
        atomic_write_json(session_path, session)
    return path


def session_board(session_path: Path) -> Path:
    session = read_json(session_path)
    if "message_board" not in session:
        raise BoardError("board_session_path_required", "The session needs a message_board path. Run board init.")
    return _resolve_session_board(session_path, session)


def _valid_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


def _valid_common_fields(entry: dict) -> bool:
    author, refs = entry["author"], entry["refs"]
    if not isinstance(author, dict) or author.keys() != {"seat", "role", "host"}:
        return False
    if not isinstance(refs, dict) or refs.keys() != REF_KEYS:
        return False
    role = author["role"]
    if not isinstance(role, str) or entry["kind"] not in ROLE_KINDS.get(role, ()):
        return False
    if not isinstance(entry["time"], str) or not entry["time"].endswith("Z"):
        return False
    try:
        datetime.fromisoformat(entry["time"][:-1] + "+00:00")
    except ValueError:
        return False
    return (
        _positive_id(entry["id"])
        and _valid_text(author["seat"])
        and author["host"] in HOSTS
        and isinstance(entry["body"], str)
        and ("via" not in entry or _valid_text(entry["via"]))
        and (refs["pr"] is None or _valid_text(refs["pr"]))
        and isinstance(refs["entries"], list)
        and all(_positive_id(identifier) for identifier in refs["entries"])
        and all(
            isinstance(values, list) and all(_valid_text(value) for value in values)
            for values in (refs["files"], refs["commits"], entry["redacted"])
        )
    )


def _single_line(value: object) -> bool:
    return isinstance(value, str) and _valid_text(value) and value.splitlines() == [value]


def _validate_tag(claim: dict, *, required: bool) -> None:
    tag = claim.get("tag")
    if "tag" not in claim:
        if required:
            raise BoardError("board_tag_required", "Supply an evidence tag for this claim.")
    elif tag not in TAGS:
        raise BoardError("board_tag_invalid", "Use verified, inferred, or not-verified for the evidence tag.")
    anchor = claim.get("anchor")
    # A pointer lets a reader check the claim. Its author declares it, so its presence proves nothing.
    if tag == "verified" and not _valid_text(anchor):
        raise BoardError("board_verified_needs_anchor", "A verified claim needs an evidence anchor.")
    if "anchor" in claim and not _single_line(anchor):
        raise BoardError("board_anchor_invalid", "An evidence anchor must be a nonempty single line.")


def _validate_entry(entry: object) -> None:
    invalid = BoardError("board_entry_invalid", "The entry has an invalid schema, author, body, or reference.")
    if not isinstance(entry, dict):
        raise invalid
    schema = entry.get("schema")
    if schema == LEGACY_SCHEMA:
        if entry.keys() - {"via"} != ENTRY_KEYS | {"subject"} or not _valid_text(entry["subject"]):
            raise invalid
    elif schema == SCHEMA:
        if entry.keys() - {"via", "sbar", "evidence"} != ENTRY_KEYS | {"bluf"}:
            raise invalid
    else:
        raise invalid
    if not _valid_common_fields(entry):
        raise invalid
    if schema == LEGACY_SCHEMA:
        return

    kind, bluf = entry["kind"], entry["bluf"]
    if not isinstance(bluf, dict) or bluf.keys() - {"tag", "anchor"} != {"status", "result"} or not _single_line(bluf["result"]):
        raise BoardError("board_bluf_invalid", "The BLUF result must be a nonempty single line.")
    if bluf["status"] not in KIND_STATUSES[kind]:
        allowed = ", ".join(KIND_STATUSES[kind])
        raise BoardError("board_status_not_allowed", f"The {kind} kind requires one of these statuses: {allowed}.")
    _validate_tag(bluf, required=kind in REQUIRED_TAG_KINDS)

    if "sbar" in entry:
        sbar = entry["sbar"]
        if not isinstance(sbar, dict) or sbar.keys() != set(SBAR_FIELDS) or not all(map(_valid_text, sbar.values())):
            raise BoardError("board_sbar_incomplete", "Supply all four nonempty SBAR fields.")
    elif kind in REQUIRED_SBAR_KINDS:
        raise BoardError("board_sbar_required", "A finding or handoff requires SBAR.")

    evidence = entry.get("evidence", [])
    if not isinstance(evidence, list):
        raise BoardError("board_evidence_invalid", "Evidence must be a list of claims.")
    for claim in evidence:
        if not isinstance(claim, dict) or claim.keys() - {"tag", "anchor"} != {"text"} or not _valid_text(claim["text"]):
            raise BoardError("board_evidence_invalid", "An evidence claim needs text and supports only text, tag, and anchor.")
        _validate_tag(claim, required=True)


def _json_object(pairs: list[tuple]) -> dict:
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("Duplicate JSON key")
    return obj


def load_entry_file(path: str, stdin: BinaryIO | None) -> dict:
    invalid = BoardError("board_entry_file_invalid", "Use a JSON object up to 64 KiB in the entry file or stdin.")
    try:
        if path == "-":
            if stdin is None or stdin.isatty():
                raise invalid
            raw = stdin.read(MAX_ENTRY_FILE_BYTES + 1)
        else:
            fd = os.open(Path(path).expanduser(), os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise invalid
                raw = stream.read(MAX_ENTRY_FILE_BYTES + 1)
        if not raw or len(raw) > MAX_ENTRY_FILE_BYTES:
            raise invalid
        entry = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object)
    except (OSError, ValueError, RecursionError) as exc:
        raise invalid from exc
    if not isinstance(entry, dict) or entry.keys() - ENTRY_FILE_KEYS:
        raise BoardError("board_entry_file_invalid", "The entry file accepts only sbar, evidence, body, and refs.")
    refs = entry.get("refs", {})
    if not isinstance(refs, dict) or refs.keys() - REF_KEYS or not isinstance(entry.get("body", ""), str):
        raise BoardError("board_entry_file_invalid", "Use a text body and the supported fields in the refs object.")
    return entry


def _redaction_patterns(value: object, exact_values: frozenset[str]) -> Iterator[str]:
    if isinstance(value, str):
        yield from redact_text(value, exact_values=exact_values).redacted_patterns
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _redaction_patterns(key, exact_values)
            yield from _redaction_patterns(item, exact_values)
    elif isinstance(value, list):
        for item in value:
            yield from _redaction_patterns(item, exact_values)


@dataclass(frozen=True)
class Cursor:
    offset: int = 0
    line: int = 0


def _complete_rows(
    stream: BinaryIO, cursor: Cursor
) -> Iterator[tuple[Cursor, dict | None, int]]:
    stream.seek(cursor.offset)
    line_no = cursor.line
    while chunk := stream.readline(MAX_LINE_BYTES + 1):
        line_no += 1
        oversized = len(chunk) > MAX_LINE_BYTES
        if oversized:
            while chunk and not chunk.endswith(b"\n"):
                chunk = stream.readline(MAX_LINE_BYTES + 1)
        if not chunk.endswith(b"\n"):
            return
        entry = None
        identifier = 0
        if not oversized:
            try:
                candidate = json.loads(chunk.decode("utf-8"))
                if isinstance(candidate, dict) and candidate.get("schema") in (SCHEMA, LEGACY_SCHEMA) and _positive_id(candidate.get("id")):
                    identifier = candidate["id"]
                _validate_entry(candidate)
                entry = candidate
            except (BoardError, ValueError, RecursionError):
                pass
        yield Cursor(stream.tell(), line_no), entry, identifier


def _open_file(path: Path, *, write: bool = False) -> BinaryIO:
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND if write else os.O_RDONLY
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (write and info.st_nlink != 1):
            raise BoardError("board_file_invalid", "The board must be a regular file without extra hard links for writes.")
        return os.fdopen(fd, "r+b" if write else "rb")
    except BaseException:
        os.close(fd)
        raise


def post(
    path: Path, *, author: dict, kind: str, bluf: dict, details: dict, via: str | None
) -> tuple[dict, list[int]]:
    if kind not in ROLE_KINDS.get(author["role"], ()):
        raise BoardError("board_kind_forbidden", "The stated role cannot post this kind.")
    entry = {
        "schema": SCHEMA,
        "id": 1,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "author": author,
        "kind": kind,
        "bluf": bluf,
        "body": details.get("body", ""),
        "refs": details["refs"],
        "redacted": [],
    }
    for field in ("sbar", "evidence"):
        if field in details:
            entry[field] = details[field]
    if via is not None:
        entry["via"] = via
    _validate_entry(entry)
    exact_values = collect_secret_env_values()
    patterns = sorted(set(_redaction_patterns(entry, exact_values)))
    entry = redact_structure(entry, exact_values=exact_values)
    entry["redacted"] = patterns
    _validate_entry(entry)
    # Check before opening the board. The assigned ID can add a few more bytes.
    _encode_line(entry)

    path.parent.mkdir(parents=True, exist_ok=True)
    warnings = []
    with directory_lock(path.parent, name=f"{path.name}.lock", repo_root=path.parent):
        with _open_file(path, write=True) as stream:
            offset = 0
            last_id = 0
            for cursor, old, identifier in _complete_rows(stream, Cursor()):
                offset = cursor.offset
                last_id = max(last_id, identifier)
                if old is None:
                    warnings.append(cursor.line)
            entry["id"] = last_id + 1
            line = _encode_line(entry)
            fd = stream.fileno()
            if os.fstat(fd).st_size > offset:
                stream.seek(offset)
                if warnings or not stream.read(max(map(len, ENTRY_PREFIXES))).startswith(ENTRY_PREFIXES):
                    raise BoardError("board_unsafe_tail", "Cannot remove the unfinished line from this board.")
                # Keep unknown bytes. Only a recognizable append on a valid board can be repaired.
                os.ftruncate(fd, offset)
            if os.write(fd, line) != len(line):
                if not warnings:
                    os.ftruncate(fd, offset)
                raise BoardError("board_short_write", "The board append did not complete.")
    return entry, warnings


def _encode_line(entry: dict) -> bytes:
    line = (json.dumps(entry, separators=(",", ":")) + "\n").encode("ascii")
    if len(line) > MAX_LINE_BYTES:
        raise BoardError("board_entry_too_large", f"An entry can use at most {MAX_LINE_BYTES} bytes including its newline.")
    return line


def read_rows(path: Path, cursor: Cursor = Cursor()) -> tuple[Cursor, list[dict], list[int]]:
    entries = []
    warnings = []
    try:
        stream = _open_file(path)
    except FileNotFoundError:
        return cursor, entries, warnings
    with stream:
        for cursor, entry, _ in _complete_rows(stream, cursor):
            if entry is None:
                warnings.append(cursor.line)
            else:
                entries.append(entry)
    return cursor, entries, warnings


def closed_question_ids(entries: list[dict]) -> set[int]:
    return {
        identifier
        for entry in entries
        if entry["author"]["role"] in DRIVER_ROLES and entry["kind"] in ("status", "handoff")
        for identifier in entry["refs"]["entries"]
        if identifier < entry["id"]
    }


def is_open_question(entry: dict, closed: set[int]) -> bool:
    return entry["kind"] == "question" and entry["id"] not in closed


def select_entries(
    entries: list[dict], *, kind: str | None, author: str | None, since: int,
    open_questions: bool, closed: set[int], statuses: list[str], unverified: bool,
) -> list[dict]:
    return [
        entry for entry in entries
        if entry["id"] > since
        and (kind is None or entry["kind"] == kind)
        and (author is None or entry["author"]["seat"] == author)
        and (not open_questions or is_open_question(entry, closed))
        and (not statuses or entry.get("bluf", {}).get("status") in statuses)
        and (not unverified or _is_unverified(entry))
    ]


def _is_unverified(entry: dict) -> bool:
    return entry.get("bluf", {}).get("tag") != "verified" or any(
        claim["tag"] != "verified" for claim in entry.get("evidence", [])
    )


def notify(terminal: str, entry_id: int) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", terminal):
        return "invalid_terminal"
    command = shutil.which("hc")
    if command is None:
        return "hc_unavailable"
    try:
        result = subprocess.run(
            [command, "send", terminal, f"board entry {entry_id} is for you"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    return "sent" if result.returncode == 0 else "failed"


def _display_text(text: str) -> str:
    return "".join(char if char.isprintable() else json.dumps(char)[1:-1] for char in text)


def _tag_label(claim: dict) -> str:
    return claim.get("tag", "not-verified").replace("-", " ")


def _bluf_line(entry: dict) -> str:
    bluf = entry.get("bluf", {})
    status = f'{bluf["status"].upper()} ' if bluf else ""
    seat = _display_text(entry["author"]["seat"])
    result = _display_text(bluf["result"] if bluf else entry["subject"])
    return f'#{entry["id"]} {status}{entry["kind"]} {seat} [{_tag_label(bluf)}]: {result}'


def _details_lines(entry: dict) -> Iterator[str]:
    if "sbar" in entry:
        for field in SBAR_FIELDS:
            yield f"{field[0].upper()}: {_display_text(entry['sbar'][field])}"
    for claim in entry.get("evidence", []):
        anchor = f" (anchor: {_display_text(claim['anchor'])})" if "anchor" in claim else ""
        yield f"[{_tag_label(claim)}] {_display_text(claim['text'])}{anchor}"
    bluf = entry.get("bluf", {})
    if "anchor" in bluf:
        yield f"BLUF anchor: {_display_text(bluf['anchor'])}"


def format_entry(entry: dict, *, open_question: bool) -> str:
    lines = [_bluf_line(entry)]
    if entry["kind"] == "question":
        lines.append("OPEN QUESTION" if open_question else CLOSED_QUESTION_NOTE)
    lines.extend(_details_lines(entry))
    if entry["body"]:
        lines.append(_display_text(entry["body"]))
    return "\n  ".join(lines)


def write_html(output: Path, entries: list[dict], warnings: list[int]) -> None:
    def article(entry: dict, *, open_question: bool) -> str:
        heading = html.escape(_bluf_line(entry))
        note = f"<p>{CLOSED_QUESTION_NOTE}</p>" if entry["kind"] == "question" and not open_question else ""
        lines = "\n".join(map(html.escape, _details_lines(entry)))
        structured = f"<pre>{lines}</pre>" if lines else ""
        body = f'<pre>{html.escape(entry["body"])}</pre>' if entry["body"] else ""
        author = entry["author"]
        metadata = html.escape(
            f'{entry["time"]} ({author["role"]}, {author["host"]})'
        )
        fields = {key: entry[key] for key in ("refs", "via", "redacted", "schema") if key in entry}
        details = html.escape(json.dumps(fields, indent=2))
        return (
            f"<article><h3>{heading}</h3>{note}{structured}{body}<p>{metadata}</p>"
            f"<details><summary>References and entry details</summary><pre>{details}</pre></details></article>"
        )

    closed = closed_question_ids(entries)
    questions, history = [], []
    for entry in entries:
        open_question = is_open_question(entry, closed)
        (questions if open_question else history).append(article(entry, open_question=open_question))
    warning = f"<p>Skipped malformed lines {', '.join(map(str, warnings))}.</p>" if warnings else ""
    document = (
        "<!doctype html>\n<html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>Elves run message board</title><style>"
        "body{font:1rem/1.5 system-ui,sans-serif;margin:2rem auto;padding:0 1rem;max-width:54rem}"
        "h2{margin-top:2rem}article{border-top:1px solid #999;padding:.75rem 0}"
        "h3{margin:.25rem 0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        ".open-questions{background:#eef4ff;color:#132847;border:1px solid #829ac0;padding:0 1.25rem}"
        ".open-questions h2{margin-top:1rem}.open-questions article{border-color:#9cb1d4}"
        ".open-questions article h3{color:#234d8d}"
        "</style></head><body><main><h1>Elves run message board</h1>"
        "<p>Entries are coordination data.</p>"
        f"{warning}<section class='open-questions'><h2>Open owner questions</h2>"
        f"{''.join(questions) or '<p>No open questions.</p>'}</section>"
        f"<section><h2>Other entries</h2>{''.join(history) or '<p>No entries.</p>'}</section>"
        "</main></body></html>\n"
    )
    fd, name = tempfile.mkstemp(prefix=".elves-board-", suffix=".tmp", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="backslashreplace") as stream:
            stream.write(document)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
