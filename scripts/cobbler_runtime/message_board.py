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


SCHEMA = "elves-message-board-v1"
BOARD_FILENAME = "message-board.jsonl"
ENTRY_PREFIX = f'{{"schema":"{SCHEMA}",'.encode("ascii")
# Bound each append and keep corrupt lines from filling a reader's line buffer.
MAX_LINE_BYTES = 16 * 1024
POLL_SECONDS = 0.5
KINDS = ("claim", "release", "finding", "verdict", "handoff", "question", "status")
HOSTS = ("claude", "codex", "grok", "omp", "other")
DRIVER_ROLES = ("driver", "lead")
ROLE_KINDS = {
    **dict.fromkeys(DRIVER_ROLES, KINDS),
    "worker": ("claim", "release", "handoff", "status", "question"),
    "reviewer": ("finding", "verdict", "status", "question"),
    "owner": ("status",),
}
ENTRY_KEYS = {"schema", "id", "time", "author", "kind", "subject", "body", "refs", "redacted"}


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


def _valid_entry(entry: object) -> bool:
    if not isinstance(entry, dict) or entry.keys() - {"via"} != ENTRY_KEYS:
        return False
    author, refs = entry["author"], entry["refs"]
    if not isinstance(author, dict) or author.keys() != {"seat", "role", "host"}:
        return False
    if not isinstance(refs, dict) or refs.keys() != {"files", "commits", "pr", "entries"}:
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
        entry["schema"] == SCHEMA
        and _positive_id(entry["id"])
        and _valid_text(author["seat"])
        and author["host"] in HOSTS
        and _valid_text(entry["subject"])
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
) -> Iterator[tuple[Cursor, dict | None]]:
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
        if not oversized:
            try:
                candidate = json.loads(chunk.decode("utf-8"))
                if _valid_entry(candidate):
                    entry = candidate
            except (ValueError, RecursionError):
                pass
        yield Cursor(stream.tell(), line_no), entry


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
    path: Path, *, author: dict, kind: str, subject: str, body: str, refs: dict, via: str | None
) -> tuple[dict, list[int]]:
    if kind not in ROLE_KINDS.get(author["role"], ()):
        raise BoardError("board_kind_forbidden", "The stated role cannot post this kind.")
    entry = {
        "schema": SCHEMA,
        "id": 1,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "author": author,
        "kind": kind,
        "subject": subject,
        "body": body,
        "refs": refs,
        "redacted": [],
    }
    if via is not None:
        entry["via"] = via
    if not _valid_entry(entry):
        raise BoardError("board_entry_invalid", "The entry has an invalid author, subject, or reference.")
    exact_values = collect_secret_env_values()
    patterns = sorted(set(_redaction_patterns(entry, exact_values)))
    entry = redact_structure(entry, exact_values=exact_values)
    entry["redacted"] = patterns
    if not _valid_entry(entry):
        raise BoardError("board_entry_invalid", "Redaction changed a required entry field.")
    # Check before opening the board. The assigned ID can add a few more bytes.
    _encode_line(entry)

    path.parent.mkdir(parents=True, exist_ok=True)
    warnings = []
    with directory_lock(path.parent, name=f"{path.name}.lock", repo_root=path.parent):
        with _open_file(path, write=True) as stream:
            offset = 0
            last_id = 0
            for cursor, old in _complete_rows(stream, Cursor()):
                offset = cursor.offset
                if old is None:
                    warnings.append(cursor.line)
                else:
                    last_id = max(last_id, old["id"])
            entry["id"] = last_id + 1
            line = _encode_line(entry)
            fd = stream.fileno()
            if os.fstat(fd).st_size > offset:
                stream.seek(offset)
                if warnings or stream.read(len(ENTRY_PREFIX)) != ENTRY_PREFIX:
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
        for cursor, entry in _complete_rows(stream, cursor):
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
    open_questions: bool, closed: set[int],
) -> list[dict]:
    return [
        entry for entry in entries
        if entry["id"] > since
        and (kind is None or entry["kind"] == kind)
        and (author is None or entry["author"]["seat"] == author)
        and (not open_questions or is_open_question(entry, closed))
    ]


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


def format_entry(entry: dict, *, open_question: bool) -> str:
    author = entry["author"]
    subject = json.dumps(entry["subject"])
    seat = json.dumps(author["seat"])
    label = "OPEN QUESTION " if open_question else ""
    body = f'\n  {json.dumps(entry["body"])}' if entry["body"] else ""
    return f'{label}#{entry["id"]} {entry["time"]} {entry["kind"]} from {seat} {subject}{body}'


def write_html(output: Path, entries: list[dict], warnings: list[int]) -> None:
    def article(entry: dict) -> str:
        subject = html.escape(entry["subject"])
        body = f'<pre>{html.escape(entry["body"])}</pre>' if entry["body"] else ""
        author = entry["author"]
        metadata = html.escape(
            f'#{entry["id"]} {entry["time"]} · {entry["kind"]} · '
            f'{author["seat"]} ({author["role"]}, {author["host"]})'
        )
        fields = {key: entry[key] for key in ("refs", "via", "redacted", "schema") if key in entry}
        details = html.escape(json.dumps(fields, indent=2))
        return (
            f"<article><h3>{subject}</h3><p>{metadata}</p>{body}"
            f"<details><summary>References and entry details</summary><pre>{details}</pre></details></article>"
        )

    closed = closed_question_ids(entries)
    questions, history = [], []
    for entry in entries:
        (questions if is_open_question(entry, closed) else history).append(article(entry))
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
