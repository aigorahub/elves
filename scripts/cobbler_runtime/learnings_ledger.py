"""Learnings ledger: typed edits, history, rollback, digest (v2.24).

Design adapted, with attribution and without vendored code, from the
edit-proposal shape of prime-agent's /refine continual harness
(PrimeIntellect-ai/prime-agent, MIT): create/update/delete edits with recorded
before/after snapshots, an append-only refinement history, and inverse-edit
rollback. The Elves version applies that lifecycle to the markdown learnings
file without changing its human-readable format:

- the ledger manages only id-tagged entries (``- [L<n>] ...``);
- freehand content — including legacy ``- [YYYY-MM-DD]`` bullets — is
  byte-preserved and never reflowed, reordered, or "cleaned up";
- ``retire`` moves an entry under ``## Retired Learnings`` (never deletes),
  matching the template's retire-don't-delete semantics;
- every applied edit appends a history row with before/after to a tracked
  ``<name>-history.jsonl`` sidecar (caps enforced loudly), and rollback builds
  the inverse edit from those snapshots with ``rollback_of`` provenance;
- a bounded digest block is regenerated only between its HTML-comment markers.

Edit verbs refuse on an id-less file with a ``migrate`` hint; ``migrate`` is
explicit, idempotent, and never automatic.
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import itertools
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Millisecond timestamps collide for consecutive applies in the same process;
# record ids must stay unique or rollback provenance dedup conflates edits.
_RECORD_SEQ = itertools.count()

LEDGER_SCHEMA = 1
ENTRY_RE = re.compile(r"^- \[L(\d+)\] (.*)$")
FREEHAND_BULLET_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] ")
HEADING_RE = re.compile(r"^## (.+?)\s*$")
RETIRED_HEADING = "Retired Learnings"
DIGEST_HEADING = "Digest"
META_HEADINGS = frozenset(
    {RETIRED_HEADING, DIGEST_HEADING, "Promotion Rules", "Promotion Destinations"}
)
DIGEST_BEGIN = "<!-- elves:learnings-digest:begin -->"
DIGEST_END = "<!-- elves:learnings-digest:end -->"
DIGEST_MAX_ENTRIES = 40
DIGEST_MAX_LINE_CHARS = 120
HISTORY_MAX_RECORDS = 500
HISTORY_MAX_BYTES = 256 * 1024
VALID_ACTIONS = ("create", "update", "retire")


class LedgerError(RuntimeError):
    """A refused ledger operation. The target file is never modified."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Entry:
    entry_id: int
    line_index: int
    text: str
    section: str
    retired: bool


@dataclass(frozen=True)
class ParsedDoc:
    lines: list[str]
    entries: dict[int, Entry]
    sections: list[str]
    freehand_count: int
    trailing_newline: bool


def history_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}-history.jsonl")


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def parse_text(text: str) -> ParsedDoc:
    lines = text.split("\n")
    trailing_newline = text.endswith("\n")
    if trailing_newline:
        lines = lines[:-1]
    entries: dict[int, Entry] = {}
    sections: list[str] = []
    current_section = ""
    freehand = 0
    in_digest = False
    for index, line in enumerate(lines):
        if line == DIGEST_BEGIN:
            in_digest = True
            continue
        if line == DIGEST_END:
            in_digest = False
            continue
        if in_digest:
            # Digest lines mirror real entries; they are generated output,
            # never entries themselves.
            continue
        heading = HEADING_RE.match(line)
        if heading:
            current_section = heading.group(1)
            sections.append(current_section)
            continue
        match = ENTRY_RE.match(line)
        if match:
            entry_id = int(match.group(1))
            if entry_id in entries:
                raise LedgerError(
                    "learnings_duplicate_id",
                    f"duplicate learning id L{entry_id} at lines "
                    f"{entries[entry_id].line_index + 1} and {index + 1}",
                )
            entries[entry_id] = Entry(
                entry_id=entry_id,
                line_index=index,
                text=match.group(2),
                section=current_section,
                retired=current_section == RETIRED_HEADING,
            )
            continue
        if FREEHAND_BULLET_RE.match(line):
            freehand += 1
    return ParsedDoc(
        lines=lines,
        entries=entries,
        sections=sections,
        freehand_count=freehand,
        trailing_newline=trailing_newline,
    )


def _read_doc(path: Path) -> tuple[str, ParsedDoc]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LedgerError("learnings_unreadable", f"cannot read {path}: {exc}") from exc
    return text, parse_text(text)


def validate_file(path: Path) -> dict[str, Any]:
    text, doc = _read_doc(path)
    return {
        "path": str(path),
        "parse_ok": True,
        "managed_count": len(doc.entries),
        "freehand_count": doc.freehand_count,
        "retired_count": sum(1 for e in doc.entries.values() if e.retired),
        "sections": doc.sections,
        "legacy_mode": not doc.entries,
        "history_path": str(history_path(path)),
        "history_records": _history_record_count(path),
    }


def _body_index(lines: list[str], absolute: int) -> int:
    """Digest-invariant coordinate for a line: digest interior excluded.

    The digest block is the only region whose length changes as entries come
    and go, so positions counted outside it stay valid across regenerations —
    which is what makes rollback byte-identical for mid-section entries.
    """

    body = 0
    in_digest = False
    for index, line in enumerate(lines):
        if index == absolute:
            return body
        if line == DIGEST_BEGIN:
            in_digest = True
            body += 1
            continue
        if line == DIGEST_END:
            in_digest = False
            body += 1
            continue
        if not in_digest:
            body += 1
    return body


def _absolute_index(lines: list[str], body_target: int) -> int:
    body = 0
    in_digest = False
    for index, line in enumerate(lines):
        if not in_digest and body == body_target:
            return index
        if line == DIGEST_BEGIN:
            in_digest = True
            body += 1
            continue
        if line == DIGEST_END:
            in_digest = False
            body += 1
            continue
        if not in_digest:
            body += 1
    return len(lines)


def _history_record_count(path: Path) -> int:
    hist = history_path(path)
    if not hist.is_file():
        return 0
    try:
        return sum(1 for line in hist.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _history_capacity_check(path: Path, rows_needed: int) -> None:
    """Refuse BEFORE any mutation when the history cannot take every row.

    Checking capacity up front keeps refuse-don't-destroy exact on the cap
    path: no phantom rows for edits that never applied, and no applied edit
    without its provenance row.
    """

    hist = history_path(path)
    if not hist.is_file():
        return
    size = hist.stat().st_size
    if (
        size > HISTORY_MAX_BYTES
        or _history_record_count(path) + rows_needed > HISTORY_MAX_RECORDS
    ):
        raise LedgerError(
            "learnings_history_full",
            f"{hist} cannot take {rows_needed} more row(s) within its cap "
            f"({HISTORY_MAX_RECORDS} records / {HISTORY_MAX_BYTES} bytes); "
            "archive it explicitly before more edits",
        )


def _append_history_rows(path: Path, records: list[dict[str, Any]]) -> None:
    """All-or-nothing append of every row under one lock."""

    hist = history_path(path)
    body = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    with open(hist, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(body)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _render_created_line(
    entry_id: int, text: str, evidence: str, expect: str | None
) -> str:
    today = _dt.date.today().isoformat()
    suffix = f" (evidence: {evidence})"
    if expect:
        suffix += f" (expect: {expect})"
    return f"- [L{entry_id}] [{today}] {text}{suffix}"


def _section_insert_index(doc: ParsedDoc, section: str) -> int:
    """Index AFTER the last content line of ``section`` (before next heading)."""

    in_section = False
    heading_index = None
    last_content = None
    boundary = len(doc.lines)
    for index, line in enumerate(doc.lines):
        heading = HEADING_RE.match(line)
        if heading:
            if in_section:
                boundary = index
                break
            in_section = heading.group(1) == section
            if in_section:
                heading_index = index
            continue
        if in_section and line.strip():
            last_content = index
    if heading_index is None:
        raise LedgerError(
            "learnings_section_missing", f"heading `## {section}` not found"
        )
    if last_content is not None:
        return last_content + 1
    # Empty section: insert after exactly one blank line so the canonical
    # `## Heading\n\n- entry` shape round-trips byte-for-byte.
    candidate = heading_index + 1
    if candidate < boundary and not doc.lines[candidate].strip():
        candidate += 1
    return candidate


def _serialize(lines: list[str], trailing_newline: bool) -> str:
    text = "\n".join(lines)
    if trailing_newline:
        text += "\n"
    return text


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _regenerate_digest(lines: list[str]) -> list[str]:
    """Regenerate the digest strictly between its markers, if present."""

    try:
        begin = lines.index(DIGEST_BEGIN)
        end = lines.index(DIGEST_END)
    except ValueError:
        return lines
    if end < begin:
        raise LedgerError("learnings_digest_markers_invalid", "digest end precedes begin")
    doc = parse_text(_serialize(lines, True))
    active = [e for e in sorted(doc.entries.values(), key=lambda e: e.entry_id) if not e.retired]
    digest_lines = []
    for entry in active[:DIGEST_MAX_ENTRIES]:
        body = f"- [L{entry.entry_id}] {entry.text}"
        if len(body) > DIGEST_MAX_LINE_CHARS:
            body = body[: DIGEST_MAX_LINE_CHARS - 1] + "…"
        digest_lines.append(body)
    if len(active) > DIGEST_MAX_ENTRIES:
        digest_lines.append(
            f"- … {len(active) - DIGEST_MAX_ENTRIES} more active learnings (read the sections below)"
        )
    return lines[: begin + 1] + digest_lines + lines[end:]


def ensure_digest_block(lines: list[str]) -> list[str]:
    """Insert an empty digest section after the first `---` if none exists."""

    if DIGEST_BEGIN in lines:
        return lines
    try:
        anchor = lines.index("---") + 1
    except ValueError:
        # aigorahub/elves#249: no separator — place the digest right after the
        # title/intro block (before the first `##` section) instead of at EOF.
        anchor = next(
            (i for i, line in enumerate(lines) if line.startswith("## ")),
            len(lines),
        )
    block = ["", f"## {DIGEST_HEADING}", "", DIGEST_BEGIN, DIGEST_END]
    return lines[:anchor] + block + lines[anchor:]


def _validate_edit(edit: dict[str, Any], doc: ParsedDoc) -> None:
    action = edit.get("action")
    if action not in VALID_ACTIONS:
        raise LedgerError(
            "learnings_edit_invalid", f"action must be one of {VALID_ACTIONS}, got {action!r}"
        )
    if action == "create":
        if not str(edit.get("text", "")).strip():
            raise LedgerError("learnings_edit_invalid", "create requires non-empty `text`")
        if not str(edit.get("evidence", "")).strip():
            raise LedgerError(
                "learnings_evidence_required",
                "create requires a non-empty `evidence` pointer "
                "(execution-log entry or commit)",
            )
        section = str(edit.get("category", "")).lstrip("# ").strip()
        if not section:
            raise LedgerError("learnings_edit_invalid", "create requires `category`")
        if section in META_HEADINGS:
            raise LedgerError(
                "learnings_edit_invalid", f"cannot create entries under `## {section}`"
            )
    else:
        raw_id = str(edit.get("id", ""))
        if not re.fullmatch(r"L\d+", raw_id):
            raise LedgerError(
                "learnings_edit_invalid", f"{action} requires `id` like `L3`, got {raw_id!r}"
            )
        entry_id = int(raw_id[1:])
        if entry_id not in doc.entries:
            raise LedgerError(
                "learnings_unknown_id", f"no learning with id L{entry_id} exists"
            )
        if action == "update" and not str(edit.get("text", "")).strip():
            raise LedgerError("learnings_edit_invalid", "update requires non-empty `text`")
        if action == "retire" and doc.entries[entry_id].retired:
            raise LedgerError(
                "learnings_edit_invalid", f"L{entry_id} is already retired"
            )
        if not str(edit.get("reason", "")).strip():
            raise LedgerError(
                "learnings_edit_invalid", f"{action} requires a non-empty `reason`"
            )


def apply_edits(
    path: Path,
    edits: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    _rollback_of: str | None = None,
) -> dict[str, Any]:
    """Apply typed edits atomically under a lock; refuse rather than destroy."""

    if not edits:
        raise LedgerError("learnings_edit_invalid", "no edits supplied")
    lock = _lock_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            original_text, doc = _read_doc(path)
            if not doc.entries and not _rollback_of:
                has_managed_target = any(e.get("action") != "create" for e in edits)
                if has_managed_target:
                    raise LedgerError(
                        "learnings_legacy_mode",
                        f"{path.name} has no id-tagged entries; run "
                        "`learnings migrate` first (explicit, idempotent, never automatic)",
                    )
            applied: list[dict[str, Any]] = []
            lines = list(doc.lines)
            for edit in edits:
                doc = parse_text(_serialize(lines, doc.trailing_newline))
                _validate_edit(edit, doc)
                action = edit["action"]
                if action == "create":
                    given_id = edit.get("id")
                    if given_id is not None:
                        entry_id = int(str(given_id)[1:])
                        if entry_id in doc.entries:
                            raise LedgerError(
                                "learnings_duplicate_id", f"id L{entry_id} already exists"
                            )
                    else:
                        entry_id = max(doc.entries, default=0) + 1
                    section = str(edit["category"]).lstrip("# ").strip()
                    line = _render_created_line(
                        entry_id,
                        str(edit["text"]).strip(),
                        str(edit["evidence"]).strip(),
                        str(edit.get("expect", "")).strip() or None,
                    )
                    insert_at = _section_insert_index(doc, section)
                    lines.insert(insert_at, line)
                    applied.append(
                        {
                            "action": "create",
                            "id": f"L{entry_id}",
                            "before": None,
                            "after": {"line": line, "section": section},
                        }
                    )
                elif action == "update":
                    entry = doc.entries[int(str(edit["id"])[1:])]
                    before_line = lines[entry.line_index]
                    before_body = _body_index(lines, entry.line_index)
                    new_line = f"- [L{entry.entry_id}] {str(edit['text']).strip()}"
                    lines[entry.line_index] = new_line
                    applied.append(
                        {
                            "action": "update",
                            "id": f"L{entry.entry_id}",
                            "before": {
                                "line": before_line,
                                "section": entry.section,
                                "line_index": before_body,
                            },
                            "after": {"line": new_line, "section": entry.section},
                        }
                    )
                else:  # retire
                    entry = doc.entries[int(str(edit["id"])[1:])]
                    before_line = lines[entry.line_index]
                    before_body = _body_index(lines, entry.line_index)
                    retired_line = (
                        f"- [L{entry.entry_id}] {entry.text} -> retired because "
                        f"{str(edit['reason']).strip()}"
                    )
                    del lines[entry.line_index]
                    doc_after_delete = parse_text(_serialize(lines, doc.trailing_newline))
                    insert_at = _section_insert_index(doc_after_delete, RETIRED_HEADING)
                    lines.insert(insert_at, retired_line)
                    applied.append(
                        {
                            "action": "retire",
                            "id": f"L{entry.entry_id}",
                            "before": {
                                "line": before_line,
                                "section": entry.section,
                                "line_index": before_body,
                            },
                            "after": {"line": retired_line, "section": RETIRED_HEADING},
                        }
                    )
            lines = _regenerate_digest(lines)
            new_text = _serialize(lines, doc.trailing_newline)
            _history_capacity_check(path, len(applied))
            record_id = f"h{int(time.time() * 1000)}-{os.getpid()}-{next(_RECORD_SEQ)}"
            rows = []
            for index, item in enumerate(applied):
                source = edits[index]
                rows.append(
                    {
                        "schema": LEDGER_SCHEMA,
                        "record_id": f"{record_id}-{index}",
                        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                        "run_id": run_id,
                        "rollback_of": _rollback_of,
                        "reason": str(source.get("reason", "")).strip(),
                        "evidence": str(source.get("evidence", "")).strip(),
                        "expect": str(source.get("expect", "")).strip(),
                        **item,
                    }
                )
            _atomic_write(path, new_text)
            _append_history_rows(path, rows)
            return {
                "applied": len(applied),
                "ids": [item["id"] for item in applied],
                "original_bytes": len(original_text),
                "new_bytes": len(new_text),
            }
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _remove_exact_line(lines: list[str], line: str, code: str) -> None:
    """Remove the first verbatim occurrence OUTSIDE the digest block."""

    in_digest = False
    for index, candidate in enumerate(lines):
        if candidate == DIGEST_BEGIN:
            in_digest = True
            continue
        if candidate == DIGEST_END:
            in_digest = False
            continue
        if not in_digest and candidate == line:
            del lines[index]
            return
    raise LedgerError(
        code,
        "the line recorded in history no longer exists verbatim; "
        "resolve manually instead of forcing a rollback",
    )


def rollback_last(path: Path, *, run_id: str | None = None) -> dict[str, Any]:
    """Invert the most recent non-rollback history row, with provenance."""

    hist = history_path(path)
    if not hist.is_file():
        raise LedgerError("learnings_history_missing", f"{hist} does not exist")
    rows = [
        json.loads(line)
        for line in hist.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rolled_back = {row.get("rollback_of") for row in rows if row.get("rollback_of")}
    target = None
    for row in reversed(rows):
        if row.get("rollback_of"):
            continue
        if row.get("record_id") in rolled_back:
            continue
        target = row
        break
    if target is None:
        raise LedgerError("learnings_history_empty", "nothing left to roll back")

    lock = _lock_path(path)
    with open(lock, "w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            _history_capacity_check(path, 1)
            text, doc = _read_doc(path)
            lines = list(doc.lines)
            after = target.get("after") or {}
            before = target.get("before") or None
            if after.get("line"):
                _remove_exact_line(lines, after["line"], "learnings_rollback_conflict")
            if before and before.get("line"):
                if before.get("line_index") is not None:
                    # Digest-invariant positional restore: the entry returns
                    # to its exact original spot, so an apply→rollback pair is
                    # byte-identical even for mid-section entries.
                    insert_at = _absolute_index(lines, int(before["line_index"]))
                else:
                    # Legacy history rows (no recorded position): section-end
                    # append, content-identical only.
                    doc_now = parse_text(_serialize(lines, doc.trailing_newline))
                    insert_at = _section_insert_index(doc_now, before["section"])
                lines.insert(insert_at, before["line"])
            lines = _regenerate_digest(lines)
            _atomic_write(path, _serialize(lines, doc.trailing_newline))
            _append_history_rows(
                path,
                [
                    {
                        "schema": LEDGER_SCHEMA,
                        "record_id": f"h{int(time.time() * 1000)}-{os.getpid()}-{next(_RECORD_SEQ)}-rb",
                        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                        "run_id": run_id,
                        "rollback_of": target["record_id"],
                        "action": f"rollback:{target['action']}",
                        "id": target.get("id"),
                        "before": after or None,
                        "after": before,
                        "reason": f"inverse of {target['record_id']}",
                        "evidence": "",
                        "expect": "",
                    }
                ],
            )
            return {"rolled_back": target["record_id"], "id": target.get("id")}
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def regenerate_digest_file(path: Path) -> dict[str, Any]:
    lock = _lock_path(path)
    with open(lock, "w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            _, doc = _read_doc(path)
            lines = ensure_digest_block(list(doc.lines))
            lines = _regenerate_digest(lines)
            _atomic_write(path, _serialize(lines, doc.trailing_newline))
            active = sum(1 for e in parse_text(_serialize(lines, True)).entries.values() if not e.retired)
            return {"digest_entries": min(active, DIGEST_MAX_ENTRIES), "active": active}
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def migrate_file(path: Path) -> dict[str, Any]:
    """Assign ids to freehand dated bullets under active category headings."""

    lock = _lock_path(path)
    with open(lock, "w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            _, doc = _read_doc(path)
            lines = list(doc.lines)
            next_id = max(doc.entries, default=0) + 1
            assigned = 0
            current_section = ""
            for index, line in enumerate(lines):
                heading = HEADING_RE.match(line)
                if heading:
                    current_section = heading.group(1)
                    continue
                if current_section in META_HEADINGS or not current_section:
                    continue
                if ENTRY_RE.match(line):
                    continue
                if FREEHAND_BULLET_RE.match(line):
                    lines[index] = f"- [L{next_id}] {line[2:]}"
                    next_id += 1
                    assigned += 1
            if assigned:
                lines = _regenerate_digest(lines)
                _atomic_write(path, _serialize(lines, doc.trailing_newline))
            return {"assigned": assigned, "next_id": next_id}
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
