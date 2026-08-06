"""Worktree fingerprinting and the futile re-drive guard (v2.24).

Design adapted, with attribution and without vendored code, from the gate
staleness snapshot in PrimeIntellect-ai/prime-agent (MIT): a failed quality
gate there is never rerun against a byte-identical workspace. The Elves
version applies the same idea to the substantive-failure re-drive loop: a
re-drive candidate whose worktree fingerprint is identical to the previous
substantive failure of the same batch, with the same failure class, is
classified ``redrive_futile:workspace_unchanged``. The classification still
consumes one unit of the re-drive budget, the identical packet must not be
relaunched, and the driver escalates along the existing ladder (split the
batch / host-native takeover / hard stop).

Fail-closed asymmetry (locked product decision): any capture error and any
over-cap tree degrade to ``changed`` — a fingerprint failure can never
manufacture futility. Transient provider failures never reach this guard;
their escalating-backoff retries stay budget-exempt.

The fingerprint is content-addressed and mtime-independent:

- ``git status --porcelain=v1 -z -uall --no-renames`` (operational paths
  excluded) digested as the tree-shape component;
- ``git diff --binary HEAD`` digested as the tracked-change component;
- untracked file contents and symlink targets digested individually in
  sorted order, subject to a total byte cap.

State lives under ``.elves/runtime/redrive/`` in the run worktree: one JSON
document per batch plus a bounded append-only ``events.jsonl``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FINGERPRINT_SCHEMA = 1
DEFAULT_EXCLUDE_PREFIXES: tuple[str, ...] = (".elves/runtime/",)
DEFAULT_BYTE_CAP = 64 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 120
EVENTS_FILE_NAME = "events.jsonl"
EVENTS_MAX_RECORDS = 200
EVENTS_MAX_BYTES = 256 * 1024

FUTILE_CLASSIFICATION = "redrive_futile:workspace_unchanged"


class FingerprintError(RuntimeError):
    """Raised only for programming errors; capture failures are data, not raises."""


@dataclass(frozen=True)
class WorktreeFingerprint:
    """Content-addressed snapshot of a worktree's material state."""

    schema: int = FINGERPRINT_SCHEMA
    status_digest: str = ""
    diff_digest: str = ""
    untracked_digest: str = ""
    bytes_hashed: int = 0
    over_cap: bool = False
    error: str | None = None

    @property
    def comparable(self) -> bool:
        return self.error is None and not self.over_cap

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status_digest": self.status_digest,
            "diff_digest": self.diff_digest,
            "untracked_digest": self.untracked_digest,
            "bytes_hashed": self.bytes_hashed,
            "over_cap": self.over_cap,
            "error": self.error,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "WorktreeFingerprint":
        return WorktreeFingerprint(
            schema=int(raw.get("schema", FINGERPRINT_SCHEMA)),
            status_digest=str(raw.get("status_digest", "")),
            diff_digest=str(raw.get("diff_digest", "")),
            untracked_digest=str(raw.get("untracked_digest", "")),
            bytes_hashed=int(raw.get("bytes_hashed", 0)),
            over_cap=bool(raw.get("over_cap", False)),
            error=raw.get("error"),
        )


def _run_git(repo_root: Path, args: list[str]) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise FingerprintError(f"git {args[0]} failed: {detail or completed.returncode}")
    return completed.stdout


def _excluded(path: str, exclude_prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) for prefix in exclude_prefixes)


def _hash_untracked(
    repo_root: Path,
    paths: list[str],
    byte_cap: int,
) -> tuple[str, int, bool]:
    hasher = hashlib.sha256()
    total = 0
    over_cap = False
    for rel in sorted(paths):
        hasher.update(rel.encode("utf-8", "surrogateescape"))
        hasher.update(b"\0")
        absolute = repo_root / rel
        try:
            if absolute.is_symlink():
                target = os.readlink(absolute)
                hasher.update(b"symlink:")
                hasher.update(target.encode("utf-8", "surrogateescape"))
                continue
            with open(absolute, "rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > byte_cap:
                        over_cap = True
                        break
                    hasher.update(chunk)
        except OSError:
            # A file that disappears or refuses reads mid-capture is material
            # state we cannot attest; mark it distinctly so the fingerprint
            # differs from a clean capture of the same tree.
            hasher.update(b"unreadable")
        if over_cap:
            break
    return hasher.hexdigest(), total, over_cap


def capture(
    repo_root: Path | str,
    *,
    exclude_prefixes: tuple[str, ...] = DEFAULT_EXCLUDE_PREFIXES,
    byte_cap: int = DEFAULT_BYTE_CAP,
) -> WorktreeFingerprint:
    """Capture a fingerprint. Never raises for environmental failures."""

    root = Path(repo_root)
    try:
        status_raw = _run_git(
            root,
            ["status", "--porcelain=v1", "-z", "-uall", "--no-renames"],
        )
        entries = [item for item in status_raw.split(b"\0") if item]
        kept: list[bytes] = []
        untracked: list[str] = []
        for entry in entries:
            if len(entry) < 4:
                continue
            code = entry[:2].decode("utf-8", "replace")
            rel = entry[3:].decode("utf-8", "surrogateescape")
            if _excluded(rel, exclude_prefixes):
                continue
            kept.append(entry)
            if code == "??":
                untracked.append(rel)
        status_digest = hashlib.sha256(b"\0".join(sorted(kept))).hexdigest()

        diff_raw = _run_git(root, ["diff", "--binary", "HEAD"])
        diff_digest = hashlib.sha256(diff_raw).hexdigest()
        bytes_hashed = len(diff_raw)
        over_cap = bytes_hashed > byte_cap

        untracked_digest = ""
        if not over_cap:
            untracked_digest, untracked_bytes, over_cap = _hash_untracked(
                root, untracked, byte_cap - bytes_hashed
            )
            bytes_hashed += untracked_bytes

        return WorktreeFingerprint(
            status_digest=status_digest,
            diff_digest=diff_digest,
            untracked_digest=untracked_digest,
            bytes_hashed=bytes_hashed,
            over_cap=over_cap,
        )
    except (FingerprintError, subprocess.TimeoutExpired, OSError) as exc:
        return WorktreeFingerprint(error=str(exc))


def compare(a: WorktreeFingerprint, b: WorktreeFingerprint) -> str:
    """Return ``identical``, ``changed``, or ``unavailable``.

    ``unavailable`` is deliberately never futile: callers must treat it
    exactly like ``changed`` when deciding whether a re-drive may relaunch.
    """

    if not a.comparable or not b.comparable:
        return "unavailable"
    if (
        a.status_digest == b.status_digest
        and a.diff_digest == b.diff_digest
        and a.untracked_digest == b.untracked_digest
    ):
        return "identical"
    return "changed"


# --- Futile re-drive guard state -------------------------------------------


@dataclass
class RedriveDecision:
    batch: str
    classification: str
    comparison: str
    attempts_used: int
    budget: int
    budget_remaining: int
    relaunch_identical_forbidden: bool
    escalation_required: bool
    failure_class: str
    log_snippet: str = ""
    gap_packet_line: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch": self.batch,
            "classification": self.classification,
            "comparison": self.comparison,
            "attempts_used": self.attempts_used,
            "budget": self.budget,
            "budget_remaining": self.budget_remaining,
            "relaunch_identical_forbidden": self.relaunch_identical_forbidden,
            "escalation_required": self.escalation_required,
            "failure_class": self.failure_class,
            "log_snippet": self.log_snippet,
            "gap_packet_line": self.gap_packet_line,
        }


def _redrive_dir(repo_root: Path) -> Path:
    return Path(repo_root) / ".elves" / "runtime" / "redrive"


def _state_path(repo_root: Path, batch: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in batch)
    return _redrive_dir(repo_root) / f"{safe}.json"


def _load_state(repo_root: Path, batch: str) -> dict[str, Any]:
    path = _state_path(Path(repo_root), batch)
    if not path.is_file():
        return {"schema": 1, "batch": batch, "attempts_used": 0, "last_failure": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": 1, "batch": batch, "attempts_used": 0, "last_failure": None}


def _save_state(repo_root: Path, batch: str, state: dict[str, Any]) -> Path:
    path = _state_path(Path(repo_root), batch)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _append_event(repo_root: Path, record: dict[str, Any]) -> None:
    directory = _redrive_dir(Path(repo_root))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / EVENTS_FILE_NAME
    line = json.dumps(record, sort_keys=True)
    with open(path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if path.stat().st_size <= EVENTS_MAX_BYTES:
                handle.write(line + "\n")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def record_failure(
    repo_root: Path | str,
    *,
    batch: str,
    failure_class: str,
    fingerprint: WorktreeFingerprint | None = None,
) -> dict[str, Any]:
    """Record a substantive failure's fingerprint for later evaluation."""

    root = Path(repo_root)
    current = fingerprint if fingerprint is not None else capture(root)
    state = _load_state(root, batch)
    state["last_failure"] = {
        "failure_class": failure_class,
        "fingerprint": current.to_dict(),
    }
    _save_state(root, batch, state)
    _append_event(
        root,
        {
            "event": "failure_recorded",
            "batch": batch,
            "failure_class": failure_class,
            "fingerprint_comparable": current.comparable,
        },
    )
    return {"recorded": True, "batch": batch, "fingerprint": current.to_dict()}


def evaluate_redrive(
    repo_root: Path | str,
    *,
    batch: str,
    failure_class: str,
    budget: int,
    fingerprint: WorktreeFingerprint | None = None,
) -> RedriveDecision:
    """Classify the next re-drive candidate for ``batch``.

    Every evaluation of a substantive failure consumes one attempt. A futile
    classification (identical tree, same failure class) forbids relaunching
    the identical packet and requires escalation regardless of remaining
    budget; a changed/unavailable tree allows a normal re-drive while budget
    remains.
    """

    root = Path(repo_root)
    current = fingerprint if fingerprint is not None else capture(root)
    state = _load_state(root, batch)
    previous = state.get("last_failure") or {}
    previous_fp = (
        WorktreeFingerprint.from_dict(previous.get("fingerprint", {}))
        if previous.get("fingerprint")
        else None
    )

    if previous_fp is None:
        comparison = "no_prior_failure"
    else:
        comparison = compare(previous_fp, current)

    same_class = bool(previous) and previous.get("failure_class") == failure_class
    futile = comparison == "identical" and same_class

    attempts = int(state.get("attempts_used", 0)) + 1
    state["attempts_used"] = attempts
    state["last_failure"] = {
        "failure_class": failure_class,
        "fingerprint": current.to_dict(),
    }
    _save_state(root, batch, state)

    budget_remaining = max(0, budget - attempts)
    classification = FUTILE_CLASSIFICATION if futile else f"redrive_allowed:{comparison}"
    escalation = futile or attempts >= budget

    if futile:
        gap_line = (
            "workspace unchanged since the previous failed attempt — do not repeat "
            "the previous approach"
        )
    else:
        gap_line = (
            "workspace changed since the previous failed attempt (comparison: "
            f"{comparison}) — state exactly what changed before relaunching"
        )

    snippet = (
        f"Re-drive check ({batch}): {classification}; attempts {attempts}/{budget}; "
        f"identical relaunch {'forbidden' if futile else 'not applicable'}; "
        f"escalation {'required' if escalation else 'not required'}."
    )

    decision = RedriveDecision(
        batch=batch,
        classification=classification,
        comparison=comparison,
        attempts_used=attempts,
        budget=budget,
        budget_remaining=budget_remaining,
        relaunch_identical_forbidden=futile,
        escalation_required=escalation,
        failure_class=failure_class,
        log_snippet=snippet,
        gap_packet_line=gap_line,
    )
    _append_event(root, {"event": "redrive_evaluated", **decision.to_dict()})
    return decision


def guard_status(repo_root: Path | str, *, batch: str) -> dict[str, Any]:
    """Read-only view of the guard state for ``batch``."""

    state = _load_state(Path(repo_root), batch)
    return {
        "batch": batch,
        "attempts_used": int(state.get("attempts_used", 0)),
        "has_prior_failure": bool(state.get("last_failure")),
    }
