"""Native-lane confidence sidecar and cross-run calibration (triage only).

Machine-readable confidence for Claude/Codex native workers lives under
``.elves/runtime/confidence/``. Calibration history is a bounded gitignored JSONL
under ``.elves/runtime/confidence-calibration.jsonl``. Neither surface grants
landing or merge authority.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping

CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})
CALIBRATION_SCHEMA_VERSION = 1
MAX_CALIBRATION_RECORDS = 500
MAX_CALIBRATION_FILE_BYTES = 512 * 1024
OUTCOME_CATEGORIES = frozenset(
    {
        "landed_clean",
        "terminal_blocker_product",
        "terminal_blocker_infra",
        "abandoned",
    }
)
_CONFIDENCE_TRAILER_RE = re.compile(
    r"^Confidence:\s*(high|medium|low)"
    r"(?:\s*[—-]\s*unsure:\s*(.+))?$",
    re.IGNORECASE | re.MULTILINE,
)


def confidence_runtime_dir(repo_root: Path) -> Path:
    return Path(repo_root).resolve() / ".elves" / "runtime" / "confidence"


def calibration_path(repo_root: Path) -> Path:
    return Path(repo_root).resolve() / ".elves" / "runtime" / "confidence-calibration.jsonl"


def parse_confidence_trailer(message: str) -> dict[str, Any] | None:
    """Parse a git commit Confidence trailer into a sidecar-shaped dict."""
    if not message:
        return None
    match = _CONFIDENCE_TRAILER_RE.search(message)
    if not match:
        return None
    level = match.group(1).lower()
    if level not in CONFIDENCE_LEVELS:
        return None
    unsure_raw = (match.group(2) or "").strip()
    unsure: list[str] = []
    if unsure_raw:
        unsure = [part.strip() for part in unsure_raw.split(";") if part.strip()][:12]
    return {
        "schema": "elves-confidence-sidecar-v1",
        "confidence": level,
        "unsure_about": unsure,
        "has_confidence": True,
        "has_unsure_answer": True,
        "source": "commit_trailer",
    }


def write_confidence_sidecar(
    repo_root: Path,
    *,
    key: str,
    payload: Mapping[str, Any],
) -> Path:
    """Write one bounded sidecar JSON file. Returns the path written."""
    safe_key = re.sub(r"[^A-Za-z0-9._-]+", "_", (key or "batch").strip())[:80] or "batch"
    directory = confidence_runtime_dir(repo_root)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = directory / f"{safe_key}.json"
    body = {
        "schema": "elves-confidence-sidecar-v1",
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "key": safe_key,
        "confidence": payload.get("confidence")
        if payload.get("confidence") in CONFIDENCE_LEVELS
        else None,
        "unsure_about": list(payload.get("unsure_about") or [])[:12],
        "has_confidence": bool(payload.get("has_confidence")),
        "has_unsure_answer": bool(payload.get("has_unsure_answer")),
        "source": str(payload.get("source") or "unknown")[:64],
        "authority": "triage_only",
    }
    raw = json.dumps(body, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(raw, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return path


def read_confidence_sidecar(repo_root: Path, key: str) -> dict[str, Any] | None:
    safe_key = re.sub(r"[^A-Za-z0-9._-]+", "_", (key or "batch").strip())[:80] or "batch"
    path = confidence_runtime_dir(repo_root) / f"{safe_key}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def append_calibration_record(
    repo_root: Path,
    *,
    run_id: str,
    host: str,
    provider: str,
    model: str,
    effort: str,
    confidence: str | None,
    outcome: str,
) -> None:
    """Append one bounded calibration record (gitignored runtime file)."""
    if outcome not in OUTCOME_CATEGORIES:
        raise ValueError(f"invalid outcome category: {outcome}")
    conf: str | None
    if confidence is None or confidence == "missing":
        conf = None
    elif confidence in CONFIDENCE_LEVELS:
        conf = confidence
    else:
        conf = None
    record = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": str(run_id)[:128],
        "host": str(host)[:64],
        "provider": str(provider)[:64],
        "model": str(model)[:128],
        "effort": str(effort)[:32],
        "confidence": conf,
        "outcome": outcome,
    }
    path = calibration_path(repo_root)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    # Best-effort locked append with size cap.
    with open(path, "a+", encoding="utf-8") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        handle.seek(0, os.SEEK_END)
        if handle.tell() + len(line) > MAX_CALIBRATION_FILE_BYTES:
            handle.seek(0)
            existing = handle.readlines()
            keep = existing[-(MAX_CALIBRATION_RECORDS - 1) :]
            handle.seek(0)
            handle.truncate()
            handle.writelines(keep)
        handle.write(line)
        handle.flush()


def load_calibration_records(repo_root: Path) -> list[dict[str, Any]]:
    path = calibration_path(repo_root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-MAX_CALIBRATION_RECORDS:]
