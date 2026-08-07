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
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

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
_INFRA_BLOCKER_MARKERS = (
    "credential",
    "auth",
    "oauth",
    "network",
    "timeout",
    "rate limit",
    "unavailable",
    "storage",
    "git remote",
    "origin",
    "supervisor disappeared",
    "process group",
    "provider cancelled",
    "provider limit",
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


def _normalize_calibration_confidence(confidence: str | None) -> str:
    """Return a locked calibration confidence token (level or ``missing``)."""
    if confidence is None or confidence == "missing":
        return "missing"
    if confidence in CONFIDENCE_LEVELS:
        return confidence
    return "missing"


def _parse_calibration_lines(raw: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
    return rows


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
    usage: Mapping[str, Any] | None = None,
) -> None:
    """Append one bounded calibration record (gitignored runtime file).

    Locking is required when ``fcntl`` is available. The live file is replaced
    atomically after cap enforcement so concurrent readers never observe a
    truncated mid-rewrite body.
    """
    if outcome not in OUTCOME_CATEGORIES:
        raise ValueError(f"invalid outcome category: {outcome}")
    conf = _normalize_calibration_confidence(confidence)
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
    if usage:
        # Additive optional field (readers tolerate absence): bounded observed
        # counts only — never invented, never quota.
        bounded_usage: dict[str, Any] = {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                bounded_usage[key] = value
        cost = usage.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
            bounded_usage["cost_usd"] = round(float(cost), 4)
        if bounded_usage:
            record["usage"] = bounded_usage
    path = calibration_path(repo_root)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"

    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_handle = open(lock_path, "a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            # Platforms without fcntl still perform the atomic replace; the
            # lock file is best-effort there only.
            pass
        except OSError as exc:
            raise OSError(f"calibration store lock failed: {exc}") from exc

        existing: list[dict[str, Any]] = []
        if path.is_file():
            try:
                existing = _parse_calibration_lines(path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise OSError(f"calibration store read failed: {exc}") from exc
        existing.append(record)
        # Enforce both record count and serialized byte caps.
        while existing and (
            len(existing) > MAX_CALIBRATION_RECORDS
            or sum(len(json.dumps(row, sort_keys=True)) + 1 for row in existing)
            > MAX_CALIBRATION_FILE_BYTES
        ):
            existing = existing[1:]
        body = "".join(json.dumps(row, sort_keys=True) + "\n" for row in existing)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".calibration-",
            suffix=".jsonl.tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(body)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    finally:
        try:
            import fcntl

            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        lock_handle.close()


def load_calibration_records(repo_root: Path) -> list[dict[str, Any]]:
    path = calibration_path(repo_root)
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = _parse_calibration_lines(raw)
    return rows[-MAX_CALIBRATION_RECORDS:]


def calibration_trend_summary(
    repo_root: Path,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Bounded non-authoritative calibration trend for review triage only."""
    rows = load_calibration_records(repo_root)[-max(1, min(limit, 200)) :]
    by_outcome: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    high_product_blockers = 0
    for row in rows:
        outcome = str(row.get("outcome") or "unknown")
        conf = str(row.get("confidence") or "missing")
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        by_confidence[conf] = by_confidence.get(conf, 0) + 1
        if (
            conf == "high"
            and outcome == "terminal_blocker_product"
        ):
            high_product_blockers += 1
    return {
        "schema": "elves-calibration-trend-v1",
        "authority": "triage_only",
        "sample_size": len(rows),
        "by_outcome": by_outcome,
        "by_confidence": by_confidence,
        # High confidence that still ended as a product blocker is a triage
        # hint only; it never changes landing or review authority.
        "high_confidence_product_blockers": high_product_blockers,
    }


def outcome_category_for_status(
    status: str,
    *,
    blocker: str | None = None,
) -> str | None:
    """Map a terminal full-run status to a locked calibration outcome."""
    normalized = (status or "").strip().lower()
    if normalized == "complete":
        return "landed_clean"
    if normalized == "stopped":
        return "abandoned"
    if normalized in {"blocked", "failed"}:
        text = (blocker or "").lower()
        if any(marker in text for marker in _INFRA_BLOCKER_MARKERS):
            return "terminal_blocker_infra"
        return "terminal_blocker_product"
    return None


def host_label_for_adapter(adapter: str) -> str:
    name = (adapter or "").strip().lower()
    if name in {"claude", "claude-code"}:
        return "claude"
    if name in {"codex", "codex-cli"}:
        return "codex"
    if name in {"grok", "grok-build"}:
        return "grok"
    if name in {"devin", "devin-cli"}:
        return "devin"
    if name == "fixture":
        return "fixture"
    return name or "unknown"


def write_sidecars_from_report(
    repo_root: Path,
    report: Mapping[str, Any],
) -> list[Path]:
    """Write sidecars for report batches that carry a confidence signal."""
    written: list[Path] = []
    batches = report.get("batches")
    if not isinstance(batches, list):
        return written
    for index, item in enumerate(batches, 1):
        if not isinstance(item, Mapping):
            continue
        confidence = item.get("confidence")
        if confidence not in CONFIDENCE_LEVELS and "unsure_about" not in item:
            continue
        raw_id = item.get("id")
        key = str(raw_id or f"batch-{index}").strip() or f"batch-{index}"
        unsure = item.get("unsure_about")
        payload = {
            "confidence": confidence if confidence in CONFIDENCE_LEVELS else None,
            "unsure_about": list(unsure)[:12] if isinstance(unsure, list) else [],
            "has_confidence": confidence in CONFIDENCE_LEVELS,
            "has_unsure_answer": isinstance(unsure, list) or "unsure_about" in item,
            "source": "report",
        }
        written.append(
            write_confidence_sidecar(repo_root, key=key, payload=payload)
        )
    return written


def write_sidecars_from_commit_messages(
    repo_root: Path,
    commits: Sequence[Mapping[str, Any]] | Sequence[str],
) -> list[Path]:
    """Parse Confidence trailers from commit subjects/bodies and write sidecars."""
    written: list[Path] = []
    for index, item in enumerate(commits, 1):
        if isinstance(item, Mapping):
            message = str(item.get("message") or item.get("subject") or "")
            key = str(item.get("sha") or item.get("id") or f"commit-{index}")[:80]
        else:
            message = str(item)
            key = f"commit-{index}"
        parsed = parse_confidence_trailer(message)
        if parsed is None:
            continue
        written.append(
            write_confidence_sidecar(repo_root, key=key, payload=parsed)
        )
    return written


def record_terminal_calibration(
    repo_root: Path,
    *,
    run_id: str,
    adapter: str,
    model: str,
    effort: str,
    status: str,
    blocker: str | None = None,
    confidence: str | None = None,
) -> bool:
    """Append one calibration row for a terminal outcome. Idempotent per run_id.

    Returns True when a new record was written.
    """
    outcome = outcome_category_for_status(status, blocker=blocker)
    if outcome is None:
        return False
    existing = load_calibration_records(repo_root)
    if any(str(row.get("run_id") or "") == str(run_id) for row in existing):
        return False
    host = host_label_for_adapter(adapter)
    append_calibration_record(
        repo_root,
        run_id=run_id,
        host=host,
        provider="native" if host in {"claude", "codex", "grok"} else host,
        model=model or "unknown",
        effort=effort or "unknown",
        confidence=confidence,
        outcome=outcome,
    )
    return True


def latest_confidence_from_sidecars(repo_root: Path) -> str | None:
    """Best-effort lowest confidence across written sidecars for calibration."""
    directory = confidence_runtime_dir(repo_root)
    if not directory.is_dir():
        return None
    rank = {"low": 0, "medium": 1, "high": 2}
    best: str | None = None
    for path in sorted(directory.glob("*.json")):
        data = read_confidence_sidecar(repo_root, path.stem)
        if not isinstance(data, dict):
            continue
        conf = data.get("confidence")
        if conf not in CONFIDENCE_LEVELS:
            continue
        if best is None or rank[str(conf)] < rank[best]:
            best = str(conf)
    return best
