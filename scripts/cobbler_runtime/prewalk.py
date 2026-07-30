"""Host-neutral contracts for exact-session native-worker prewalk.

Prewalk is a trajectory property: one worker session explores, writes a bounded
TODO, makes a real task edit, and then resumes in the same worktree on the
execution route.  This module intentionally owns no provider subprocess loop;
it supplies deterministic schemas, prompts, path safety, digests, capability
evidence, and the model-free transition check used by the native supervisor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import uuid
from typing import Any, Mapping, Sequence

from .host_profiles import host_profile_or_none
from .schema import ValidationIssue
from .storage import (
    StorageError,
    atomic_write_json,
    guard_repo_path,
    read_bounded_artifact_bytes,
)


PREWALK_SCHEMA_VERSION = 1
PREWALK_STATE_VERSION = 3
PREWALK_DEFAULT_TODO_LIMIT = 10
PREWALK_MIN_TODO_LIMIT = 5
PREWALK_MAX_TODO_LIMIT = 12
PREWALK_CONTINUATION_INPUT = "Continue."
PREWALK_CAPABILITY_ARTIFACT_MAX_BYTES = 64 * 1024
PREWALK_RUNTIME_ARTIFACT_MAX_BYTES = 256 * 1024
PREWALK_PACKET_MAX_BYTES = 4 * 1024 * 1024
PREWALK_MODES = ("off", "auto", "required", "experimental")
PREWALK_ACTUAL_MODES = (
    "off",
    "qualification_required",
    "exact_session",
    "exact_session_experimental",
)
PREWALK_INSTRUCTION_FIDELITIES = (
    "pruned",
    "turn_scoped",
    "retained_safe",
    "unsupported",
)
GROK_PREWALK_QUALIFICATION_ARTIFACT_TYPE = "grok_prewalk_qualification_canary"
PREWALK_FAILURE_CODES = frozenset(
    {
        "prewalk_capability_unavailable",
        "prewalk_exact_resume_unqualified",
        "prewalk_route_change_unqualified",
        "prewalk_session_id_missing",
        "prewalk_session_continuity_violation",
        "prewalk_worktree_continuity_violation",
        "prewalk_todo_missing",
        "prewalk_todo_invalid",
        "prewalk_todo_limit_exceeded",
        "prewalk_checkpoint_missing",
        "prewalk_checkpoint_invalid",
        "prewalk_meaningful_edit_missing",
        "prewalk_changed_path_forbidden",
        "prewalk_packet_replayed",
        "prewalk_instruction_pruning_unqualified",
        "prewalk_live_qualification_failed",
        "prewalk_guide_exit_before_checkpoint",
        "prewalk_execution_resume_failed",
        "prewalk_post_edit_cold_fallback_forbidden",
    }
)

_TODO_ID_RE = re.compile(r"PW-(\d{2})\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_BUILD_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}\Z")
_SAFE_RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_STAGING_ONLY_PREFIXES = (
    ".elves/",
    ".elves-session.json",
    "docs/plans/",
    "docs/elves/learnings.md",
    "docs/elves/survival-guide-",
    "docs/elves/execution-log-",
    "docs/elves/reports/",
)
_DRIVER_OWNED_PREFIXES = (
    ".elves-session.json",
    "docs/plans/",
    "docs/elves/learnings.md",
    "docs/elves/survival-guide-",
    "docs/elves/execution-log-",
    "docs/elves/reports/",
)


@dataclass(frozen=True)
class PrewalkPaths:
    root: str
    todo: str
    checkpoint: str
    session_identity: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PrewalkCapabilities:
    host: str
    transport: str
    installed_version: str | None = None
    installed_build_commit: str | None = None
    advertised_exact_resume: bool = False
    advertised_route_override_on_resume: bool = False
    behaviorally_verified_session_continuity: bool = False
    behaviorally_verified_instruction_pruning: bool = False
    worktree_binding_verified: bool = False
    stream_identity_verified: bool = False
    instruction_fidelity: str = "unsupported"
    evidence_source: str = "not_probed"
    model_calls_made: bool = False
    qualified_guide_model: str | None = None
    qualified_guide_effort: str | None = None
    qualified_execution_model: str | None = None
    qualified_execution_effort: str | None = None

    def qualified(self) -> bool:
        return bool(
            self.advertised_exact_resume
            and self.advertised_route_override_on_resume
            and self.behaviorally_verified_session_continuity
            and self.worktree_binding_verified
            and self.stream_identity_verified
            and self.instruction_fidelity == "retained_safe"
            and self.qualified_guide_effort is not None
            and self.qualified_execution_effort is not None
        )

    def experimental_eligible(self) -> bool:
        """Return whether an explicit operator may test the advertised lane.

        Experimental mode accepts qualification uncertainty only. The real
        worker supervisor still enforces exact session, worktree, stream,
        packet-count, transition, and authority checks.
        """
        return bool(
            self.advertised_exact_resume
            and self.advertised_route_override_on_resume
        )

    def route_matches(
        self,
        *,
        guide_model: str | None,
        guide_effort: str,
        execution_model: str | None,
        execution_effort: str,
    ) -> bool:
        if self.evidence_source == "deterministic_fixture":
            return True
        return bool(
            self.qualified_guide_model == guide_model
            and self.qualified_guide_effort == guide_effort
            and self.qualified_execution_model == execution_model
            and self.qualified_execution_effort == execution_effort
        )

    def unavailable_reason(self) -> str | None:
        if not self.advertised_exact_resume:
            return "prewalk_exact_resume_unqualified"
        if not self.advertised_route_override_on_resume:
            return "prewalk_route_change_unqualified"
        if not self.behaviorally_verified_session_continuity:
            return "prewalk_exact_resume_unqualified"
        if not self.worktree_binding_verified or not self.stream_identity_verified:
            return "prewalk_capability_unavailable"
        if self.instruction_fidelity != "retained_safe":
            return "prewalk_instruction_pruning_unqualified"
        return None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["qualified"] = self.qualified()
        payload["unavailable_reason"] = self.unavailable_reason()
        return payload


@dataclass(frozen=True)
class PrewalkTransitionEvidence:
    session_continuity: bool
    worktree_continuity: bool
    todo_valid: bool
    meaningful_edit_valid: bool
    first_edit_todo_id: str
    changed_paths: tuple[str, ...]
    diff_sha256: str
    task_complete: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_paths"] = list(self.changed_paths)
        return payload


def _run_key(run_id: str) -> str:
    value = run_id.strip()
    if not _SAFE_RUN_RE.fullmatch(value):
        raise ValidationIssue(
            "prewalk_checkpoint_invalid",
            "Prewalk run ids must be bounded safe identifiers",
            path="run_id",
        )
    readable = "".join(ch if ch.isalnum() else "_" for ch in value)[:24]
    return f"{readable}-{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def prewalk_paths(worktree: Path, run_id: str) -> PrewalkPaths:
    worktree_root = worktree.resolve(strict=True)
    try:
        root = guard_repo_path(
            worktree_root,
            worktree_root / ".elves" / "runtime" / "prewalk" / _run_key(run_id),
        )
    except StorageError as exc:
        raise ValidationIssue(
            "prewalk_worktree_continuity_violation",
            "Prewalk runtime path is not safely contained in the registered worktree",
            path=str(worktree),
        ) from exc
    return PrewalkPaths(
        root=str(root),
        todo=str(root / "todo.json"),
        checkpoint=str(root / "checkpoint.json"),
        session_identity=str(root / "session.json"),
    )


def _safe_runtime_path(
    path: Path, *, runtime_root: Path, worktree: Path, code: str
) -> Path:
    try:
        root = guard_repo_path(worktree, runtime_root)
        resolved = guard_repo_path(worktree, path)
    except StorageError as exc:
        raise ValidationIssue(
            code,
            "Prewalk artifact path has an unsafe worktree component",
            path=str(path),
        ) from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValidationIssue(code, "Prewalk artifact path escapes its runtime root", path=str(path)) from exc
    return resolved


def _read_bounded_regular_json(
    path: Path,
    *,
    runtime_root: Path | None,
    worktree: Path | None = None,
    missing_code: str,
    invalid_code: str,
    limit: int,
) -> dict[str, Any]:
    target = (
        _safe_runtime_path(
            path,
            runtime_root=runtime_root,
            worktree=worktree or runtime_root,
            code=invalid_code,
        )
        if runtime_root
        else path.resolve()
    )
    try:
        before = target.lstat()
    except FileNotFoundError as exc:
        raise ValidationIssue(missing_code, "Required prewalk artifact is missing", path=str(target)) from exc
    if not stat.S_ISREG(before.st_mode) or target.is_symlink():
        raise ValidationIssue(invalid_code, "Prewalk artifact must be a regular non-symlink file", path=str(target))
    if before.st_size > limit:
        raise ValidationIssue(invalid_code, "Prewalk artifact exceeds its bounded size", path=str(target))
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationIssue(invalid_code, "Prewalk artifact is not valid bounded JSON", path=str(target)) from exc
    if not isinstance(data, dict):
        raise ValidationIssue(invalid_code, "Prewalk artifact must be a JSON object", path=str(target))
    return data


def _required_text(value: object, *, path: str, code: str, max_chars: int = 2_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_chars:
        raise ValidationIssue(code, "Required prewalk text is missing or unbounded", path=path)
    return value.strip()


def _rfc3339(value: object, *, path: str, code: str) -> str:
    text = _required_text(value, path=path, code=code, max_chars=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationIssue(code, "Expected an RFC3339 timestamp", path=path) from exc
    if parsed.tzinfo is None:
        raise ValidationIssue(code, "Prewalk timestamps require an explicit timezone", path=path)
    return text


def _todo_limit(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not PREWALK_MIN_TODO_LIMIT <= value <= PREWALK_MAX_TODO_LIMIT:
        raise ValidationIssue(
            "prewalk_todo_limit_exceeded",
            f"Prewalk TODO limit must be between {PREWALK_MIN_TODO_LIMIT} and {PREWALK_MAX_TODO_LIMIT}",
            path="todo_limit",
        )
    return value


def validate_todo_artifact(
    data: Mapping[str, Any],
    *,
    run_id: str,
    session_id: str,
    todo_limit: int = PREWALK_DEFAULT_TODO_LIMIT,
    allow_all_complete: bool = False,
) -> dict[str, Any]:
    """Validate and normalize the durable cross-host TODO contract."""
    limit = _todo_limit(todo_limit)
    code = "prewalk_todo_invalid"
    if data.get("schema_version") != PREWALK_SCHEMA_VERSION:
        raise ValidationIssue(code, "Unsupported prewalk TODO schema", path="schema_version")
    if data.get("run_id") != run_id:
        raise ValidationIssue(code, "Prewalk TODO run identity does not match", path="run_id")
    if data.get("session_id") != session_id:
        raise ValidationIssue(code, "Prewalk TODO session identity does not match", path="session_id")
    _rfc3339(data.get("created_at"), path="created_at", code=code)
    _rfc3339(data.get("updated_at"), path="updated_at", code=code)
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationIssue(code, "Prewalk TODO must contain at least one item", path="items")
    if len(items) > limit:
        raise ValidationIssue(
            "prewalk_todo_limit_exceeded",
            f"Prewalk TODO has {len(items)} items; configured limit is {limit}",
            path="items",
        )
    active = 0
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items, start=1):
        path = f"items[{index - 1}]"
        if not isinstance(raw, Mapping):
            raise ValidationIssue(code, "Prewalk TODO items must be objects", path=path)
        item_id = _required_text(raw.get("id"), path=f"{path}.id", code=code, max_chars=16)
        match = _TODO_ID_RE.fullmatch(item_id)
        if match is None or int(match.group(1)) != index or item_id in seen:
            raise ValidationIssue(code, "Prewalk TODO ids must be unique ordered PW-01 identifiers", path=f"{path}.id")
        seen.add(item_id)
        status_value = raw.get("status")
        if status_value not in {"pending", "in_progress", "complete"}:
            raise ValidationIssue(code, "Invalid prewalk TODO status", path=f"{path}.status")
        if status_value == "in_progress":
            active += 1
        normalized.append(
            {
                "id": item_id,
                "description": _required_text(raw.get("description"), path=f"{path}.description", code=code),
                "acceptance": _required_text(raw.get("acceptance"), path=f"{path}.acceptance", code=code),
                "validation": _required_text(raw.get("validation"), path=f"{path}.validation", code=code),
                "status": str(status_value),
            }
        )
    if active > 1:
        raise ValidationIssue(code, "At most one prewalk TODO item may be in progress", path="items")
    if all(item["status"] == "complete" for item in normalized) and not allow_all_complete:
        raise ValidationIssue(code, "An all-complete TODO requires an explicit task-complete checkpoint", path="items")
    result = dict(data)
    result["items"] = normalized
    return result


def _safe_repo_path(value: object, *, path: str, code: str) -> str:
    text = _required_text(value, path=path, code=code, max_chars=1_000).replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or text.startswith(".git/") or text == ".git" or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValidationIssue(code, "Prewalk changed paths must be safe repository-relative paths", path=path)
    return pure.as_posix()


def validate_checkpoint_artifact(
    data: Mapping[str, Any],
    *,
    run_id: str,
    session_id: str,
    todo: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a first-edit or task-complete checkpoint against its TODO."""
    code = "prewalk_checkpoint_invalid"
    if data.get("schema_version") != PREWALK_SCHEMA_VERSION:
        raise ValidationIssue(code, "Unsupported prewalk checkpoint schema", path="schema_version")
    if data.get("run_id") != run_id or data.get("session_id") != session_id:
        raise ValidationIssue(code, "Prewalk checkpoint identity does not match the run/session", path="session_id")
    kind = data.get("kind")
    if kind not in {"first_meaningful_edit", "task_complete"}:
        raise ValidationIssue(code, "Unknown prewalk checkpoint kind", path="kind")
    todo_id = _required_text(data.get("todo_id"), path="todo_id", code=code, max_chars=16)
    items = {str(item.get("id")): item for item in todo.get("items", []) if isinstance(item, Mapping)}
    if todo_id not in items:
        raise ValidationIssue(code, "Checkpoint references a missing TODO item", path="todo_id")
    changed = data.get("changed_paths")
    if not isinstance(changed, list) or not changed or len(changed) > 100:
        raise ValidationIssue(code, "Checkpoint changed_paths must be a non-empty bounded list", path="changed_paths")
    normalized_paths = [
        _safe_repo_path(value, path=f"changed_paths[{index}]", code=code)
        for index, value in enumerate(changed)
    ]
    if len(set(normalized_paths)) != len(normalized_paths):
        raise ValidationIssue(code, "Checkpoint changed_paths must be unique", path="changed_paths")
    _required_text(data.get("summary"), path="summary", code=code, max_chars=500)
    attempts = data.get("validation_attempted")
    if not isinstance(attempts, list) or len(attempts) > 20:
        raise ValidationIssue(code, "validation_attempted must be a bounded list", path="validation_attempted")
    normalized_attempts: list[dict[str, Any]] = []
    for index, raw in enumerate(attempts):
        if not isinstance(raw, Mapping):
            raise ValidationIssue(code, "Validation attempts must be objects", path=f"validation_attempted[{index}]")
        exit_code = raw.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise ValidationIssue(code, "Validation attempt exit_code must be an integer", path=f"validation_attempted[{index}].exit_code")
        normalized_attempts.append(
            {
                "command": _required_text(raw.get("command"), path=f"validation_attempted[{index}].command", code=code, max_chars=1_000),
                "exit_code": exit_code,
            }
        )
    if data.get("ready_for_execution_model") is not True:
        raise ValidationIssue(code, "Checkpoint must explicitly declare readiness", path="ready_for_execution_model")
    _rfc3339(data.get("created_at"), path="created_at", code=code)
    if kind == "first_meaningful_edit" and items[todo_id].get("status") == "pending":
        raise ValidationIssue(code, "First-edit TODO item may not remain pending", path="todo_id")
    if kind == "task_complete" and any(item.get("status") != "complete" for item in items.values()):
        raise ValidationIssue(code, "Task-complete checkpoint requires every TODO item complete", path="kind")
    result = dict(data)
    result["changed_paths"] = normalized_paths
    result["validation_attempted"] = normalized_attempts
    return result


def load_and_validate_transition_artifacts(
    *,
    paths: PrewalkPaths,
    run_id: str,
    session_id: str,
    todo_limit: int,
    worktree: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(paths.root)
    raw_checkpoint = _read_bounded_regular_json(
        Path(paths.checkpoint),
        runtime_root=root,
        worktree=worktree,
        missing_code="prewalk_checkpoint_missing",
        invalid_code="prewalk_checkpoint_invalid",
        limit=PREWALK_RUNTIME_ARTIFACT_MAX_BYTES,
    )
    allow_complete = raw_checkpoint.get("kind") == "task_complete"
    raw_todo = _read_bounded_regular_json(
        Path(paths.todo),
        runtime_root=root,
        worktree=worktree,
        missing_code="prewalk_todo_missing",
        invalid_code="prewalk_todo_invalid",
        limit=PREWALK_RUNTIME_ARTIFACT_MAX_BYTES,
    )
    todo = validate_todo_artifact(
        raw_todo,
        run_id=run_id,
        session_id=session_id,
        todo_limit=todo_limit,
        allow_all_complete=allow_complete,
    )
    checkpoint = validate_checkpoint_artifact(
        raw_checkpoint,
        run_id=run_id,
        session_id=session_id,
        todo=todo,
    )
    return todo, checkpoint


def _run_git(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(worktree), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationIssue("prewalk_worktree_continuity_violation", "Unable to inspect the registered prewalk worktree") from exc


def observed_changed_paths(worktree: Path, start_head: str) -> tuple[str, ...]:
    diff = _run_git(worktree, "diff", "--name-only", "--no-renames", "-z", start_head, "--")
    untracked = _run_git(worktree, "ls-files", "--others", "--exclude-standard", "-z")
    if diff.returncode != 0 or untracked.returncode != 0:
        raise ValidationIssue("prewalk_worktree_continuity_violation", "Unable to derive the prewalk worktree delta")
    raw = [value for value in (diff.stdout + untracked.stdout).split("\0") if value]
    normalized = {_safe_repo_path(value, path="changed_paths", code="prewalk_changed_path_forbidden") for value in raw}
    return tuple(sorted(normalized))


def _path_matches(path: str, prefixes: Sequence[str]) -> bool:
    for raw in prefixes:
        prefix = raw.replace("\\", "/")
        while prefix.startswith("./"):
            prefix = prefix[2:]
        normalized = prefix.rstrip("/")
        if prefix.endswith("/") and (path == normalized or path.startswith(normalized + "/")):
            return True
        if prefix.endswith("-") and path.startswith(prefix):
            return True
        if not prefix.endswith(("/", "-")) and path == normalized:
            return True
    return False


def _diff_digest(worktree: Path, start_head: str, changed_paths: Sequence[str]) -> str:
    digest = hashlib.sha256()
    diff = _run_git(worktree, "diff", "--binary", start_head, "--", *changed_paths)
    if diff.returncode != 0:
        raise ValidationIssue("prewalk_worktree_continuity_violation", "Unable to hash the prewalk delta")
    digest.update(diff.stdout.encode("utf-8", errors="replace"))
    for path in changed_paths:
        target = worktree / path
        if target.is_symlink():
            raise ValidationIssue(
                "prewalk_changed_path_forbidden",
                "Prewalk changes may not use symlink targets",
                path=path,
            )
        if target.is_file() and _run_git(worktree, "ls-files", "--error-unmatch", "--", path).returncode != 0:
            digest.update(path.encode())
            try:
                digest.update(target.read_bytes())
            except OSError as exc:
                raise ValidationIssue("prewalk_worktree_continuity_violation", "Unable to hash an untracked prewalk edit", path=path) from exc
    return digest.hexdigest()


def validate_meaningful_edit(
    *,
    worktree: Path,
    start_head: str,
    assigned_branch: str,
    todo: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    starting_worktree_clean: bool,
    forbidden_paths: Sequence[str] = (),
    authority_errors: Sequence[str] = (),
) -> PrewalkTransitionEvidence:
    """Prove the edit boundary without judging whether the edit is correct."""
    root = worktree.resolve()
    top = _run_git(root, "rev-parse", "--show-toplevel")
    branch = _run_git(root, "branch", "--show-current")
    ancestor = _run_git(root, "merge-base", "--is-ancestor", start_head, "HEAD")
    if (
        not starting_worktree_clean
        or top.returncode != 0
        or Path(top.stdout.strip()).resolve() != root
        or branch.returncode != 0
        or branch.stdout.strip() != assigned_branch
        or ancestor.returncode != 0
    ):
        raise ValidationIssue(
            "prewalk_worktree_continuity_violation",
            "Prewalk worktree, branch, clean start, or ancestry no longer matches staging",
            path=str(root),
        )
    if authority_errors:
        raise ValidationIssue(
            "prewalk_changed_path_forbidden",
            "Prewalk guide changed Git authority or a protected surface",
            hint="; ".join(str(item) for item in authority_errors[:3]),
        )
    changed = observed_changed_paths(root, start_head)
    if not changed:
        raise ValidationIssue("prewalk_meaningful_edit_missing", "Guide phase produced no repository edit")
    for path in changed:
        target = root / path
        if target.is_symlink():
            raise ValidationIssue(
                "prewalk_changed_path_forbidden",
                "Guide phase changed a symlink target",
                path=path,
            )
        try:
            target.resolve().relative_to(root)
        except ValueError as exc:
            raise ValidationIssue(
                "prewalk_changed_path_forbidden",
                "Guide phase changed a path that resolves outside the worktree",
                path=path,
            ) from exc
    if any(_path_matches(path, _DRIVER_OWNED_PREFIXES) for path in changed):
        raise ValidationIssue(
            "prewalk_changed_path_forbidden",
            "Guide phase changed driver-owned canonical run memory",
        )
    if any(_path_matches(path, forbidden_paths) for path in changed):
        raise ValidationIssue("prewalk_changed_path_forbidden", "Guide phase changed a forbidden surface")
    meaningful = tuple(path for path in changed if not _path_matches(path, _STAGING_ONLY_PREFIXES))
    if not meaningful:
        raise ValidationIssue("prewalk_meaningful_edit_missing", "Guide phase changed only runtime or staging memory")
    declared = tuple(str(value) for value in checkpoint.get("changed_paths", ()))
    if not declared or not set(declared).issubset(changed) or not set(declared).intersection(meaningful):
        raise ValidationIssue(
            "prewalk_checkpoint_invalid",
            "Checkpoint changed paths must be an observed subset containing a meaningful edit",
            path="changed_paths",
        )
    log = _run_git(root, "log", "--format=%s", f"{start_head}..HEAD")
    if log.returncode != 0:
        raise ValidationIssue("prewalk_worktree_continuity_violation", "Unable to inspect guide commits")
    if any("· Close]" in subject for subject in log.stdout.splitlines()):
        raise ValidationIssue("prewalk_checkpoint_invalid", "Guide phase may not create a Close commit at transition")
    todo_id = str(checkpoint.get("todo_id") or "")
    return PrewalkTransitionEvidence(
        session_continuity=True,
        worktree_continuity=True,
        todo_valid=True,
        meaningful_edit_valid=True,
        first_edit_todo_id=todo_id,
        changed_paths=changed,
        diff_sha256=_diff_digest(root, start_head, changed),
        task_complete=checkpoint.get("kind") == "task_complete",
    )


def packet_digest(path: Path) -> str:
    target = path.resolve(strict=True)
    metadata = target.stat()
    if path.is_symlink() or not target.is_file() or metadata.st_size > PREWALK_PACKET_MAX_BYTES:
        raise ValidationIssue("prewalk_packet_replayed", "Worker packet must be one bounded regular file", path=str(target))
    return hashlib.sha256(target.read_bytes()).hexdigest()


def guide_prompt(*, run_id: str, paths: PrewalkPaths, todo_limit: int) -> str:
    limit = _todo_limit(todo_limit)
    return f"""Begin the implementation task directly.

This is the guide turn for exact-session Elves prewalk run `{run_id}`. Explore the repository
deeply enough to understand relevant behavior, abstractions, tests, and constraints. Do not stop
after orientation and do not produce a read-only plan.

Before editing, create at most {limit} concrete TODO items. Every item needs an observable
acceptance condition and its own validation step. Use the host TODO mechanism when available and
mirror the list to `{paths.todo}` using the Elves prewalk TODO schema. Read the exact session id
from `{paths.session_identity}` before writing the TODO or checkpoint.

Then make the first meaningful task edit. It may be a deliberately failing test when the TODO says
so. Update that TODO item to in_progress or complete, write the first_meaningful_edit checkpoint to
`{paths.checkpoint}`, and end this guide turn immediately. Do not create a Close commit and do not
claim task completion unless every TODO item is truly complete. If the whole task is atomic, write
a task_complete checkpoint instead.

On the later exact-session continuation, complete the remaining TODO items and their validations,
update the same TODO artifact, replace the checkpoint with an explicit task_complete checkpoint,
and satisfy the normal worker completion contract. The next input will be only `Continue.`.

The task packet follows and is sent exactly once:

"""


def recovery_prompt() -> str:
    return (
        "Continue the same prewalk guide turn after the transport interruption. "
        "Do not reread or request the task packet. Finish the bounded TODO and first meaningful "
        "edit checkpoint, then end this turn."
    )


def write_session_identity(
    path: Path, *, worktree: Path, run_id: str, session_id: str
) -> None:
    payload = {"schema_version": PREWALK_SCHEMA_VERSION, "run_id": run_id, "session_id": session_id}
    try:
        atomic_write_json(path, payload, mode=0o600, repo_root=worktree)
    except StorageError as exc:
        raise ValidationIssue(
            "prewalk_worktree_continuity_violation",
            "Prewalk session identity path is unsafe",
            path=str(path),
        ) from exc


def fixture_prewalk_capabilities(host: str = "fixture") -> PrewalkCapabilities:
    return PrewalkCapabilities(
        host=host,
        transport="fixture_process",
        installed_version="fixture-v1",
        advertised_exact_resume=True,
        advertised_route_override_on_resume=True,
        behaviorally_verified_session_continuity=True,
        behaviorally_verified_instruction_pruning=False,
        worktree_binding_verified=True,
        stream_identity_verified=True,
        instruction_fidelity="retained_safe",
        evidence_source="deterministic_fixture",
        model_calls_made=False,
        qualified_guide_model="guide-model",
        qualified_guide_effort="high",
        qualified_execution_model="execution-model",
        qualified_execution_effort="low",
    )


def advertised_prewalk_capabilities(
    *, host: str, version: str | None, create_help: str, resume_help: str
) -> PrewalkCapabilities:
    profile = host_profile_or_none(host)
    if profile is None or profile.help_grammar is None:
        raise ValidationIssue("prewalk_capability_unavailable", f"Unsupported prewalk host `{host}`")
    exact, route = profile.help_grammar(create_help, resume_help)
    return PrewalkCapabilities(
        host=profile.capability_host,
        transport=profile.transport,
        installed_version=version,
        advertised_exact_resume=exact,
        advertised_route_override_on_resume=route,
        instruction_fidelity="unsupported",
        evidence_source="installed_help_only",
        model_calls_made=False,
    )


def probe_installed_prewalk_capabilities(
    host: str,
    *,
    behavioral_evidence: Path | None = None,
    runner: Any = subprocess.run,
) -> PrewalkCapabilities:
    """Read installed help/version only; never launch an inference turn."""
    profile = host_profile_or_none(host)
    if profile is None or profile.executable is None or profile.help_grammar is None:
        raise ValidationIssue("prewalk_capability_unavailable", f"Unsupported prewalk host `{host}`")
    located = shutil.which(profile.executable)
    if not located:
        return PrewalkCapabilities(
            host=profile.capability_host,
            transport=profile.transport,
            evidence_source="installed_binary_missing",
        )

    def invoke(argv: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return runner(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(argv, 1, "", type(exc).__name__)

    version_result = invoke([located, *profile.version_argv])
    version_text = (
        version_result.stdout + version_result.stderr
        if version_result.returncode == 0
        else ""
    )
    version_match = re.search(r"\d+\.\d+(?:\.\d+)?", version_text)
    version = version_match.group(0) if version_match else None
    create_result = invoke([located, *profile.create_help_argv])
    resume_result = (
        create_result
        if profile.resume_help_argv == profile.create_help_argv
        else invoke([located, *profile.resume_help_argv])
    )
    advertised = advertised_prewalk_capabilities(
        host=profile.capability_host,
        version=version,
        create_help=(
            (create_result.stdout + create_result.stderr)[:PREWALK_RUNTIME_ARTIFACT_MAX_BYTES]
            if create_result.returncode == 0
            else ""
        ),
        resume_help=(
            (resume_result.stdout + resume_result.stderr)[:PREWALK_RUNTIME_ARTIFACT_MAX_BYTES]
            if resume_result.returncode == 0
            else ""
        ),
    )
    build_match = re.search(r"\(([0-9a-f]{7,40})\)", version_text, re.I)
    advertised = replace(
        advertised,
        installed_build_commit=(
            build_match.group(1).lower() if build_match else None
        ),
    )
    if behavioral_evidence is None:
        return advertised
    if profile.capability_host == "grok":
        if version is None:
            raise ValidationIssue(
                "prewalk_capability_unavailable",
                "Behavioral qualification requires an exact bounded installed version",
                path="installed_version",
            )
        # Bind the artifact to the installed build commit when the version
        # output publishes one (same `(hex)` grammar the goal canary binds).
        return load_grok_prewalk_qualification(
            behavioral_evidence,
            installed_version=version,
            installed_build_commit=(
                build_match.group(1).lower() if build_match else None
            ),
            advertised=advertised,
        )
    return load_prewalk_capability_evidence(
        behavioral_evidence,
        host=profile.capability_host,
        installed_version=version,
        advertised=advertised,
    )


def experimental_prewalk_capabilities(
    advertised: PrewalkCapabilities,
    *,
    guide_model: str,
    guide_effort: str,
    execution_model: str,
    execution_effort: str,
) -> PrewalkCapabilities:
    """Bind an explicit experimental request to one advertised route pair."""
    if not advertised.experimental_eligible():
        raise ValidationIssue(
            advertised.unavailable_reason() or "prewalk_capability_unavailable",
            "Experimental prewalk still requires advertised exact resume and route override",
        )
    return replace(
        advertised,
        evidence_source="explicit_experimental_request",
        qualified_guide_model=guide_model,
        qualified_guide_effort=guide_effort,
        qualified_execution_model=execution_model,
        qualified_execution_effort=execution_effort,
    )


def _qualification_phase_routes(
    data: Mapping[str, Any],
) -> dict[str, tuple[str | None, str]]:
    """Validate the guide/execution route bindings shared by evidence loaders."""
    routes: dict[str, tuple[str | None, str]] = {}
    for role in ("guide", "execution"):
        route = data.get(f"{role}_route")
        if not isinstance(route, Mapping):
            raise ValidationIssue(
                "prewalk_route_change_unqualified",
                "Qualification must bind both requested phase routes",
                path=f"{role}_route",
            )
        model = route.get("model")
        if model is not None:
            model = _required_text(
                model,
                path=f"{role}_route.model",
                code="prewalk_route_change_unqualified",
                max_chars=200,
            )
        effort = route.get("effort")
        if effort not in {"low", "medium", "high"}:
            raise ValidationIssue(
                "prewalk_route_change_unqualified",
                "Qualification phase effort must be low, medium, or high",
                path=f"{role}_route.effort",
            )
        routes[role] = (model, str(effort))
    return routes


def load_prewalk_capability_evidence(
    path: Path,
    *,
    host: str,
    installed_version: str | None,
    advertised: PrewalkCapabilities,
) -> PrewalkCapabilities:
    if (
        not isinstance(installed_version, str)
        or not installed_version.strip()
        or len(installed_version) > 128
    ):
        raise ValidationIssue(
            "prewalk_capability_unavailable",
            "Behavioral qualification requires an exact bounded installed version",
            path="installed_version",
        )
    installed_version = installed_version.strip()
    # fd-bound read (shared with the goal-canary and qualification loaders):
    # a symlinked, irregular, group/other-writable, or oversized evidence
    # artifact is rejected on the descriptor actually read.
    target = Path(path).expanduser()
    try:
        raw = read_bounded_artifact_bytes(
            target, max_bytes=PREWALK_CAPABILITY_ARTIFACT_MAX_BYTES
        )
    except OSError as exc:
        raise ValidationIssue(
            "prewalk_capability_unavailable",
            "Required prewalk artifact is missing",
            path=str(target),
        ) from exc
    except ValueError as exc:
        message = {
            "artifact_writable_by_others": (
                "Prewalk artifact must not be group/other-writable"
            ),
            "artifact_too_large": "Prewalk artifact exceeds its bounded size",
        }.get(str(exc), "Prewalk artifact must be a regular non-symlink file")
        raise ValidationIssue(
            "prewalk_capability_unavailable", message, path=str(target)
        ) from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationIssue(
            "prewalk_capability_unavailable",
            "Prewalk artifact is not valid bounded JSON",
            path=str(target),
        ) from exc
    if not isinstance(data, dict):
        raise ValidationIssue(
            "prewalk_capability_unavailable",
            "Prewalk artifact must be a JSON object",
            path=str(target),
        )
    expected_host = host.strip().lower().replace("-code", "")
    required = {
        "artifact_type": "native_prewalk_behavioral_qualification",
        "schema_version": 1,
        "host": expected_host,
        "transport": advertised.transport,
        "installed_version": installed_version,
        "create_exit_code": 0,
        "resume_exit_code": 0,
        "same_session_id": True,
        "same_worktree": True,
        "unique_guide_fact_observed": True,
        "packet_replayed": False,
        "stream_identity_verified": True,
    }
    for key, expected in required.items():
        if data.get(key) != expected:
            raise ValidationIssue(
                "prewalk_capability_unavailable",
                "Behavioral prewalk qualification does not match the installed host",
                path=key,
            )
    fidelity = data.get("instruction_fidelity")
    if fidelity not in PREWALK_INSTRUCTION_FIDELITIES or fidelity == "unsupported":
        raise ValidationIssue("prewalk_instruction_pruning_unqualified", "Qualification must report usable instruction fidelity")
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip() or session_id.startswith("-"):
        raise ValidationIssue("prewalk_session_id_missing", "Qualification lacks an exact safe session id")
    for digest_key in ("guide_prompt_sha256", "continuation_sha256"):
        if not isinstance(data.get(digest_key), str) or not _SHA256_RE.fullmatch(str(data[digest_key])):
            raise ValidationIssue("prewalk_capability_unavailable", "Qualification digest is malformed", path=digest_key)
    expected_continuation_digest = hashlib.sha256(
        PREWALK_CONTINUATION_INPUT.encode("utf-8")
    ).hexdigest()
    if data.get("continuation_sha256") != expected_continuation_digest:
        raise ValidationIssue(
            "prewalk_capability_unavailable",
            "Qualification did not prove the canonical minimal continuation input",
            path="continuation_sha256",
        )
    routes = _qualification_phase_routes(data)
    model_calls_made = data.get("model_calls_made")
    if model_calls_made is not True:
        raise ValidationIssue(
            "prewalk_capability_unavailable",
            "Live behavioral qualification must report its model calls",
            path="model_calls_made",
        )
    return PrewalkCapabilities(
        host=advertised.host,
        transport=advertised.transport,
        installed_version=installed_version,
        advertised_exact_resume=advertised.advertised_exact_resume,
        advertised_route_override_on_resume=advertised.advertised_route_override_on_resume,
        behaviorally_verified_session_continuity=True,
        behaviorally_verified_instruction_pruning=fidelity == "pruned",
        worktree_binding_verified=True,
        stream_identity_verified=True,
        instruction_fidelity=str(fidelity),
        evidence_source=str(path.resolve()),
        model_calls_made=model_calls_made,
        qualified_guide_model=routes["guide"][0],
        qualified_guide_effort=routes["guide"][1],
        qualified_execution_model=routes["execution"][0],
        qualified_execution_effort=routes["execution"][1],
    )


_GROK_QUALIFICATION_REQUIRED_FIELDS = frozenset(
    {
        "artifact_type",
        "schema_version",
        "host",
        "transport",
        "installed_version",
        "installed_build_commit",
        "session_id",
        "guide_route",
        "execution_route",
        "create_exit_code",
        "resume_exit_code",
        "same_session_id",
        "same_worktree",
        "stream_identity_verified",
        "unique_guide_fact_observed",
        "packet_replayed",
        "model_calls_made",
        "instruction_fidelity",
    }
)


def _read_qualification_artifact_json(
    target: Path, *, limit: int, code: str
) -> dict[str, Any]:
    """Read one bounded regular JSON artifact with checks bound to the read fd.

    Mirrors the goal-canary reader: O_NOFOLLOW open, fstat identity match
    against the pre-open lstat, and mode/size checks on the descriptor
    actually read, so a check-to-read swap cannot bypass the symlink,
    writability, or size bounds.
    """
    try:
        raw = read_bounded_artifact_bytes(target, max_bytes=limit)
    except OSError as exc:
        raise ValidationIssue(
            code, "Grok prewalk qualification artifact is missing", path=str(target)
        ) from exc
    except ValueError as exc:
        message = {
            "artifact_writable_by_others": (
                "Grok prewalk qualification must not be group/other-writable"
            ),
            "artifact_too_large": (
                "Grok prewalk qualification artifact is too large"
            ),
        }.get(
            str(exc),
            "Grok prewalk qualification must be a regular non-symlink file",
        )
        raise ValidationIssue(code, message, path=str(target)) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationIssue(
            code,
            "Grok prewalk qualification artifact must be valid JSON",
            path=str(target),
        ) from exc
    if not isinstance(payload, dict):
        raise ValidationIssue(
            code,
            "Grok prewalk qualification artifact must be one JSON object",
            path=str(target),
        )
    return payload


def load_grok_prewalk_qualification(
    path: Path,
    *,
    installed_version: str | None = None,
    installed_build_commit: str | None = None,
    advertised: PrewalkCapabilities | None = None,
) -> PrewalkCapabilities:
    """Validate one bounded grok prewalk qualification artifact, fail closed.

    The artifact is operator-recorded live-canary evidence (this loader never
    fabricates or launches anything). It must be a bounded (<= 64 KiB) regular
    non-symlink file that is not group/other-writable, carry exactly the
    required fields, and bind host ``grok`` and transport ``grok_build`` with
    the exact installed version and build commit, one canonical session UUID,
    both phase routes, successful create/resume exits, the same-worktree/
    session/stream continuity facts, guide-only fact retention, no packet
    replay, model-call provenance, and an explicit instruction fidelity.
    ``retained_safe`` is the only activating fidelity: ``pruned`` and
    ``turn_scoped`` load as recorded, non-activating evidence (mirroring
    ``PrewalkCapabilities.qualified()``). ``evidence_source`` is always the
    resolved artifact path — never a fixture token.

    ``installed_version``/``installed_build_commit`` bind the artifact to a
    probed installed binary when supplied; standalone loads (no installed
    grok) still require both facts inside the artifact itself.
    """
    code = "prewalk_capability_unavailable"
    target = Path(path)
    data = _read_qualification_artifact_json(
        target, limit=PREWALK_CAPABILITY_ARTIFACT_MAX_BYTES, code=code
    )
    if set(data) != _GROK_QUALIFICATION_REQUIRED_FIELDS:
        raise ValidationIssue(
            code,
            "Grok prewalk qualification must carry exactly the required fields",
            path="fields",
        )
    exact: dict[str, Any] = {
        "artifact_type": GROK_PREWALK_QUALIFICATION_ARTIFACT_TYPE,
        "schema_version": 1,
        "host": "grok",
        "transport": "grok_build",
        "create_exit_code": 0,
        "resume_exit_code": 0,
        "same_session_id": True,
        "same_worktree": True,
        "stream_identity_verified": True,
        "unique_guide_fact_observed": True,
        "packet_replayed": False,
        "model_calls_made": True,
    }
    for key, expected in exact.items():
        value = data.get(key)
        if isinstance(expected, bool):
            matched = value is expected
        elif isinstance(expected, int):
            matched = (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value == expected
            )
        else:
            matched = value == expected
        if not matched:
            raise ValidationIssue(
                code,
                "Grok prewalk qualification does not bind the grok transport facts",
                path=key,
            )
    version = _required_text(
        data.get("installed_version"), path="installed_version", code=code, max_chars=128
    )
    if installed_version is not None and version != installed_version.strip():
        raise ValidationIssue(
            code,
            "Grok prewalk qualification does not match the installed grok version",
            path="installed_version",
        )
    build = _required_text(
        data.get("installed_build_commit"),
        path="installed_build_commit",
        code=code,
        max_chars=64,
    ).lower()
    if not _BUILD_COMMIT_RE.fullmatch(build):
        raise ValidationIssue(
            code,
            "Grok prewalk qualification build commit is malformed",
            path="installed_build_commit",
        )
    if (
        installed_build_commit is not None
        and build != installed_build_commit.strip().lower()
    ):
        raise ValidationIssue(
            code,
            "Grok prewalk qualification does not match the installed grok build",
            path="installed_build_commit",
        )
    session_value = data.get("session_id")
    try:
        canonical_session = str(uuid.UUID(str(session_value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationIssue(
            "prewalk_session_id_missing",
            "Grok prewalk qualification requires one canonical session UUID",
            path="session_id",
        ) from exc
    if canonical_session != session_value:
        raise ValidationIssue(
            "prewalk_session_id_missing",
            "Grok prewalk qualification session id must be the canonical UUID form",
            path="session_id",
        )
    fidelity = data.get("instruction_fidelity")
    if fidelity not in PREWALK_INSTRUCTION_FIDELITIES or fidelity == "unsupported":
        raise ValidationIssue(
            "prewalk_instruction_pruning_unqualified",
            "Grok prewalk qualification must report an observed instruction fidelity",
            path="instruction_fidelity",
        )
    routes = _qualification_phase_routes(data)
    return PrewalkCapabilities(
        host="grok",
        transport="grok_build",
        installed_version=version,
        advertised_exact_resume=(
            advertised.advertised_exact_resume if advertised is not None else True
        ),
        advertised_route_override_on_resume=(
            advertised.advertised_route_override_on_resume
            if advertised is not None
            else True
        ),
        behaviorally_verified_session_continuity=True,
        behaviorally_verified_instruction_pruning=fidelity == "pruned",
        worktree_binding_verified=True,
        stream_identity_verified=True,
        instruction_fidelity=str(fidelity),
        evidence_source=str(target.resolve()),
        model_calls_made=True,
        qualified_guide_model=routes["guide"][0],
        qualified_guide_effort=routes["guide"][1],
        qualified_execution_model=routes["execution"][0],
        qualified_execution_effort=routes["execution"][1],
    )
