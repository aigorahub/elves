"""Single external writer lease: exclusivity, preflight, and write packets.

Exactly one live writer lease may exist. The host owns branch commits, push, PR,
and run memory. Workers may only edit/test (and optionally create detached
handoff commits) inside a verified detached worktree under an issued lease.

Lease state lives under ignored `.elves/runtime/leases/` and must not be
committed as product artifacts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import reject_fugu_implementation_route
from .context import redact_structure, redact_text
from .schema import ELVES_SESSION_BASENAME, ValidationIssue
from .storage import (
    StorageError,
    assert_embedded_id,
    atomic_write_json,
    directory_lock,
    ensure_private_dir,
    guard_repo_path,
    list_repo_store_files,
    qualify_write_evidence,
    read_json,
    record_filename,
    repo_regular_file_exists,
    snapshot_path as storage_snapshot_path,
)


_GIT_EXECUTABLE = shutil.which("git", path=os.defpath) or "/usr/bin/git"


def host_qualification_evidence(
    *,
    adapter: str,
    model: str,
    profile: str | None = None,
    version: str = "0.2.93",
    sandbox: str = "devbox",
    worktree: str,
    cwd: str,
    parent: str,
    source_head: str,
    session_id: str,
    capabilities: Mapping[str, Any] | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Build a host-issued qualification record (test and host helpers)."""
    return {
        "adapter": adapter,
        "model": model,
        "profile": profile or adapter,
        "version": version,
        "sandbox": sandbox,
        "worktree": worktree,
        "cwd": cwd,
        "parent": parent,
        "source_head": source_head,
        "session_id": session_id,
        "capabilities": dict(capabilities or {"write": True}),
        "evidence_kind": "host_observed",
        "observed_at": observed_at or _utc_now(),
        "host_observed": True,
        "stale": False,
        "preference_declared": False,
    }


class LeaseState(str, Enum):
    PREPARED = "prepared"
    ACTIVE = "active"
    AUDITING = "auditing"
    AUDITED_PASS = "audited_pass"
    EXPORTED = "exported"
    APPLY_CHECKED = "apply_checked"
    INTEGRATED = "integrated"
    CLOSED = "closed"
    REJECTED = "rejected"


LIVE_LEASE_STATES: frozenset[LeaseState] = frozenset(
    {
        LeaseState.PREPARED,
        LeaseState.ACTIVE,
        LeaseState.AUDITING,
        LeaseState.AUDITED_PASS,
        LeaseState.EXPORTED,
        LeaseState.APPLY_CHECKED,
    }
)

# Explicit compare-and-swap lifecycle. Rejected is terminal.
_ALLOWED_LEASE_TRANSITIONS: dict[LeaseState, frozenset[LeaseState]] = {
    LeaseState.PREPARED: frozenset(
        {LeaseState.PREPARED, LeaseState.ACTIVE, LeaseState.REJECTED, LeaseState.CLOSED}
    ),
    LeaseState.ACTIVE: frozenset(
        {LeaseState.ACTIVE, LeaseState.AUDITING, LeaseState.REJECTED, LeaseState.CLOSED}
    ),
    LeaseState.AUDITING: frozenset(
        {
            LeaseState.AUDITING,
            LeaseState.AUDITED_PASS,
            LeaseState.REJECTED,
            LeaseState.CLOSED,
        }
    ),
    LeaseState.AUDITED_PASS: frozenset(
        {LeaseState.AUDITED_PASS, LeaseState.EXPORTED, LeaseState.REJECTED, LeaseState.CLOSED}
    ),
    LeaseState.EXPORTED: frozenset(
        {
            LeaseState.EXPORTED,
            LeaseState.APPLY_CHECKED,
            LeaseState.REJECTED,
            LeaseState.CLOSED,
        }
    ),
    LeaseState.APPLY_CHECKED: frozenset(
        {
            LeaseState.APPLY_CHECKED,
            LeaseState.INTEGRATED,
            LeaseState.REJECTED,
            LeaseState.CLOSED,
        }
    ),
    LeaseState.INTEGRATED: frozenset({LeaseState.INTEGRATED, LeaseState.CLOSED}),
    LeaseState.CLOSED: frozenset({LeaseState.CLOSED}),
    LeaseState.REJECTED: frozenset({LeaseState.REJECTED}),
}


def transition_lease_state(current: LeaseState, target: LeaseState) -> LeaseState:
    allowed = _ALLOWED_LEASE_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ValidationIssue(
            "invalid_lease_transition",
            f"Cannot transition lease from `{current.value}` to `{target.value}`",
            path="lease.state",
            hint=f"Allowed from {current.value}: {', '.join(sorted(s.value for s in allowed))}",
        )
    return target

# Git actions a qualified detached writer may use when the lease permits commits.
DEFAULT_PERMITTED_GIT_ACTIONS: tuple[str, ...] = (
    "status",
    "diff",
    "log",
    "show",
    "rev-parse",
    "add",
    "commit",  # detached handoff only when lease.detached_commits_permitted
    "cat-file",
)

DEFAULT_FORBIDDEN_GIT_ACTIONS: tuple[str, ...] = (
    "push",
    "fetch",  # network; host owns remotes
    "pull",
    "checkout",
    "switch",
    "branch",
    "tag",
    "merge",
    "rebase",
    "cherry-pick",
    "reset",
    "clean",
    "remote",
    "config",
    "update-ref",
    "symbolic-ref",
    "worktree",
)

DEFAULT_FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    ".git/",
    ".elves/",
    "docs/elves/",
    "docs/plans/",
    ELVES_SESSION_BASENAME,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def leases_root(repo_root: Path) -> Path:
    repo = Path(repo_root).expanduser().resolve()
    return guard_repo_path(repo, repo / ".elves" / "runtime" / "leases")


def ensure_leases_dir(repo_root: Path) -> Path:
    repo = Path(repo_root).expanduser().resolve()
    return ensure_private_dir(
        leases_root(repo),
        mode=stat.S_IRWXU,
        repo_root=repo,
    )


def hardened_git_env(
    *,
    work_tree: Path | None = None,
    git_dir: Path | None = None,
    common_dir: Path | None = None,
) -> dict[str, str]:
    """Return the minimal non-interactive Git environment used after workers.

    Callers that already hold descriptor-validated repository authority pass all
    three paths.  Doing so prevents Git from rediscovering a swapped ``.git``
    locator from ``cwd``.  Replacement refs and optional index refreshes are
    disabled for both bound and host-only calls.
    """
    if any(value is not None for value in (work_tree, git_dir, common_dir)) and (
        work_tree is None or git_dir is None or common_dir is None
    ):
        raise ValueError(
            "work_tree, git_dir, and common_dir must be supplied together"
        )
    env = {
        "PATH": os.defpath,
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": "/nonexistent",
        "XDG_CONFIG_HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/usr/bin/false",
        "SSH_ASKPASS": "/usr/bin/false",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_ATTR_NOSYSTEM": "1",
    }
    overrides = {
        "core.hooksPath": os.devnull,
        "core.fsmonitor": "false",
        "core.askPass": "/usr/bin/false",
        "credential.helper": "",
        "diff.external": "",
        "core.attributesFile": os.devnull,
        "core.excludesFile": os.devnull,
        "interactive.diffFilter": "",
    }
    env["GIT_CONFIG_COUNT"] = str(len(overrides))
    for index, (key, value) in enumerate(overrides.items()):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    if work_tree is not None and git_dir is not None and common_dir is not None:
        env.update(
            {
                "GIT_WORK_TREE": str(Path(work_tree)),
                "GIT_DIR": str(Path(git_dir)),
                "GIT_COMMON_DIR": str(Path(common_dir)),
            }
        )
    return env


# Default bound for supervisor-path git subprocesses. Matches the existing
# 30-second native-worker git hardening (native_worker.py terminalizes a hung
# git as `native_worker_git_timeout`): a wedged git must surface as
# subprocess.TimeoutExpired the caller can handle instead of stalling a
# supervisor forever. Callers may still pass an explicit override, e.g.
# git_contract's 15-second remote-refs probe.
DEFAULT_GIT_TIMEOUT_SECONDS: float = 30.0


def run_git(
    cwd: Path,
    args: Sequence[str],
    *,
    check: bool = True,
    text: bool = True,
    env: Mapping[str, str] | None = None,
    timeout: float | None = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run git with argv only (shell=False), stdin closed, bounded by default."""
    cmd = [_GIT_EXECUTABLE, *args]
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=text,
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise ValidationIssue(
            "git_command_failed",
            f"git {' '.join(args)} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()}",
            path=str(cwd),
        )
    return result


@dataclass
class WriterLease:
    """One-writer lease contract and live state."""

    lease_id: str
    host_checkout: str
    worker_checkout: str
    session_id: str
    base_head: str
    adapter: str
    profile: str
    revision: int = 0
    sandbox_profile: str = "devbox"
    qualification_digest: str | None = None
    audit_evidence_digest: str | None = None
    apply_check_evidence_digest: str | None = None
    credential_grant_names: list[str] = field(default_factory=list)
    credential_grant_context_digest: str | None = None
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_path_prefixes: list[str] = field(
        default_factory=lambda: list(DEFAULT_FORBIDDEN_PATH_PREFIXES)
    )
    permitted_git_actions: list[str] = field(
        default_factory=lambda: list(DEFAULT_PERMITTED_GIT_ACTIONS)
    )
    forbidden_git_actions: list[str] = field(
        default_factory=lambda: list(DEFAULT_FORBIDDEN_GIT_ACTIONS)
    )
    detached_commits_permitted: bool = True
    require_detached: bool = True
    state: LeaseState = LeaseState.PREPARED
    created_at: str | None = None
    updated_at: str | None = None
    pre_status: str | None = None
    pre_refs_digest: str | None = None
    notes: str = ""
    rejection_reason: str | None = None
    worker_tip: str | None = None
    integrated_tip: str | None = None
    exported_patch_dir: str | None = None
    # Negative fixture: workspace sandbox cannot be assumed commit-capable.
    workspace_sandbox_commit_capable: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WriterLease:
        if not isinstance(data, Mapping):
            raise TypeError("lease record must be a mapping")
        required_strings = (
            "lease_id",
            "host_checkout",
            "worker_checkout",
            "session_id",
            "base_head",
            "adapter",
            "profile",
        )
        for field_name in required_strings:
            value = data.get(field_name)
            if not isinstance(value, str) or not value:
                raise TypeError(f"{field_name} must be a non-empty string")
        optional_strings = (
            "sandbox_profile",
            "qualification_digest",
            "audit_evidence_digest",
            "apply_check_evidence_digest",
            "credential_grant_context_digest",
            "state",
            "created_at",
            "updated_at",
            "pre_status",
            "pre_refs_digest",
            "notes",
            "rejection_reason",
            "worker_tip",
            "integrated_tip",
            "exported_patch_dir",
        )
        for field_name in optional_strings:
            value = data.get(field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string or null")
        sandbox_profile = data.get("sandbox_profile", "devbox")
        if not isinstance(sandbox_profile, str) or not sandbox_profile:
            raise TypeError("sandbox_profile must be a non-empty string")
        list_fields = (
            "credential_grant_names",
            "allowed_paths",
            "forbidden_path_prefixes",
            "permitted_git_actions",
            "forbidden_git_actions",
        )
        for field_name in list_fields:
            value = data.get(field_name)
            if field_name in data and (
                not isinstance(value, list)
                or not all(isinstance(item, str) for item in value)
            ):
                raise TypeError(f"{field_name} must be a string list")
        for field_name in (
            "detached_commits_permitted",
            "require_detached",
            "workspace_sandbox_commit_capable",
        ):
            value = data.get(field_name)
            if field_name in data and not isinstance(value, bool):
                raise TypeError(f"{field_name} must be a boolean")
        revision_raw = data.get("revision", 0)
        if (
            not isinstance(revision_raw, int)
            or isinstance(revision_raw, bool)
            or revision_raw < 0
        ):
            raise TypeError("revision must be a non-negative integer")
        state_raw = data.get("state", LeaseState.PREPARED.value)
        if not isinstance(state_raw, str) or not state_raw:
            raise TypeError("state must be a non-empty string")
        return cls(
            lease_id=str(data["lease_id"]),
            host_checkout=str(data["host_checkout"]),
            worker_checkout=str(data["worker_checkout"]),
            session_id=str(data["session_id"]),
            base_head=str(data["base_head"]),
            adapter=str(data["adapter"]),
            profile=str(data["profile"]),
            revision=revision_raw,
            sandbox_profile=sandbox_profile,
            qualification_digest=data.get("qualification_digest"),
            audit_evidence_digest=data.get("audit_evidence_digest"),
            apply_check_evidence_digest=data.get("apply_check_evidence_digest"),
            credential_grant_names=list(data.get("credential_grant_names", [])),
            credential_grant_context_digest=data.get(
                "credential_grant_context_digest"
            ),
            allowed_paths=list(data.get("allowed_paths", [])),
            forbidden_path_prefixes=list(
                data.get("forbidden_path_prefixes", DEFAULT_FORBIDDEN_PATH_PREFIXES)
            ),
            permitted_git_actions=list(
                data.get("permitted_git_actions", DEFAULT_PERMITTED_GIT_ACTIONS)
            ),
            forbidden_git_actions=list(
                data.get("forbidden_git_actions", DEFAULT_FORBIDDEN_GIT_ACTIONS)
            ),
            detached_commits_permitted=bool(data.get("detached_commits_permitted", True)),
            require_detached=bool(data.get("require_detached", True)),
            state=LeaseState(state_raw),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            pre_status=data.get("pre_status"),
            pre_refs_digest=data.get("pre_refs_digest"),
            notes=str(data.get("notes") or ""),
            rejection_reason=data.get("rejection_reason"),
            worker_tip=data.get("worker_tip"),
            integrated_tip=data.get("integrated_tip"),
            exported_patch_dir=data.get("exported_patch_dir"),
            workspace_sandbox_commit_capable=bool(
                data.get("workspace_sandbox_commit_capable", False)
            ),
        )


_LEASE_PARSE_ERRORS = (
    AttributeError,
    KeyError,
    OverflowError,
    RecursionError,
    TypeError,
    ValueError,
)


def _lease_error_category(exc: BaseException) -> str:
    """Return a stable diagnostic category without record-controlled text."""
    if isinstance(exc, StorageError):
        return f"storage:{exc.code}"
    return f"schema:{type(exc).__name__}"


def build_write_task_packet(lease: WriterLease, *, task: str, contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Coordinator packet for a bounded worker turn (host-owned synthesis later)."""
    packet = {
        "lease_id": lease.lease_id,
        "session_id": lease.session_id,
        "task": task,
        "worker_checkout": lease.worker_checkout,
        "base_head": lease.base_head,
        "allowed_paths": list(lease.allowed_paths),
        "forbidden_path_prefixes": list(lease.forbidden_path_prefixes),
        "permitted_git_actions": list(lease.permitted_git_actions),
        "forbidden_git_actions": list(lease.forbidden_git_actions),
        "detached_commits_permitted": lease.detached_commits_permitted,
        "sandbox_profile": lease.sandbox_profile,
        "denials": {
            "branch": True,
            "tag": True,
            "ref_mutation": True,
            "push": True,
            "pr": True,
            "run_memory": True,
            "credentials": True,
            "checkout_other_worktree": True,
            "headless_worktree_resume_as_isolation": lease.adapter == "grok-build",
        },
        "contract": dict(contract or {}),
        "notes": [
            "Host owns branch commits, push, PR, and run memory",
            "Detached commits are untrusted handoff boundaries only when permitted",
            "Never bare-cherry-pick worker commits onto the owned branch",
        ],
    }
    redacted = redact_structure(packet)
    return dict(redacted) if isinstance(redacted, Mapping) else packet


def normalize_repo_rel_path(rel_path: str) -> str:
    """Normalize a repository-relative path without stripping leading dots.

    ``str.lstrip("./")`` is unsafe: it treats the argument as a *set* of
    characters, so ``.elves/secret.json`` becomes ``elves/secret.json`` and can
    escape forbidden-prefix checks. Only strip explicit ``./`` segments.
    """
    if rel_path is None:
        raise ValidationIssue(
            "invalid_path",
            "Path is required",
            path="lease.path",
        )
    text = str(rel_path).replace("\\", "/").strip()
    if not text or text in {".", ".."}:
        raise ValidationIssue(
            "invalid_path",
            f"Path `{rel_path}` is empty or not repository-relative",
            path="lease.path",
        )
    if text.startswith("/") or re_is_absolute_drive(text):
        raise ValidationIssue(
            "absolute_path_forbidden",
            f"Absolute path `{rel_path}` is not allowed in a writer lease",
            path="lease.path",
        )
    while text.startswith("./"):
        text = text[2:]
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValidationIssue(
                "path_escape",
                f"Path `{rel_path}` contains `..` segments",
                path="lease.path",
            )
        parts.append(part)
    if not parts:
        raise ValidationIssue(
            "invalid_path",
            f"Path `{rel_path}` resolves empty",
            path="lease.path",
        )
    return "/".join(parts)


def re_is_absolute_drive(text: str) -> bool:
    """True for Windows-style drive paths like ``C:/foo``."""
    return len(text) >= 2 and text[0].isalpha() and text[1] == ":"


def is_path_allowed(rel_path: str, lease: WriterLease) -> bool:
    """Return True if a repo-relative path is within lease scope.

    Empty allow-lists fail closed (nothing is permitted). Forbidden prefixes are
    checked against a safe normalization that preserves leading dots in names
    like ``.elves/``.
    """
    try:
        normalized = normalize_repo_rel_path(rel_path)
    except ValidationIssue:
        return False

    for prefix in lease.forbidden_path_prefixes:
        p = str(prefix).replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        p_stripped = p.rstrip("/")
        if not p_stripped:
            continue
        if normalized == p_stripped or normalized.startswith(p_stripped + "/"):
            return False
        # Exact file forbids such as the session basename (ELVES_SESSION_BASENAME).
        if not p.endswith("/") and normalized == p:
            return False

    if not lease.allowed_paths:
        return False

    for allowed in lease.allowed_paths:
        try:
            a = normalize_repo_rel_path(allowed.rstrip("/")) if allowed not in {".", "./"} else ""
        except ValidationIssue:
            continue
        if allowed in {".", "./"} or a == "":
            # Explicit whole-repo allow only when non-forbidden.
            return True
        if normalized == a or normalized.startswith(a + "/"):
            return True
        if str(allowed).replace("\\", "/").endswith("/") and (
            normalized == a or normalized.startswith(a + "/")
        ):
            return True
    return False


def _git_symbolic_head(cwd: Path) -> str | None:
    result = run_git(
        cwd,
        ["symbolic-ref", "-q", "HEAD"],
        check=False,
        env=hardened_git_env(),
    )
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def _git_head(
    cwd: Path,
    *,
    git_dir: Path | None = None,
    common_dir: Path | None = None,
) -> str:
    return run_git(
        cwd,
        ["rev-parse", "HEAD"],
        env=hardened_git_env(
            work_tree=cwd if git_dir is not None else None,
            git_dir=git_dir,
            common_dir=common_dir,
        ),
    ).stdout.strip()


def _git_status_porcelain(
    cwd: Path,
    *,
    git_dir: Path | None = None,
    common_dir: Path | None = None,
) -> str:
    return run_git(
        cwd,
        ["status", "--porcelain", "--ignore-submodules=all"],
        env=hardened_git_env(
            work_tree=cwd if git_dir is not None else None,
            git_dir=git_dir,
            common_dir=common_dir,
        ),
    ).stdout


def _worktree_list_porcelain(cwd: Path) -> str:
    return run_git(
        cwd,
        ["worktree", "list", "--porcelain"],
        env=hardened_git_env(),
    ).stdout


def _git_common_dir(cwd: Path) -> Path:
    raw = run_git(
        cwd,
        ["rev-parse", "--git-common-dir"],
        env=hardened_git_env(),
    ).stdout.strip()
    path = Path(raw)
    if not path.is_absolute():
        path = Path(cwd) / path
    return path.resolve()


def worktree_is_registered(worker_checkout: Path, *, git_cwd: Path | None = None) -> bool:
    """True when worker path appears in git worktree list --porcelain."""
    root = git_cwd or worker_checkout
    text = _worktree_list_porcelain(root)
    target = str(worker_checkout.resolve())
    for line in text.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree ") :].strip()
            try:
                if Path(path).resolve() == Path(target).resolve():
                    return True
            except OSError:
                if path == target:
                    return True
    # Single-checkout repos: the main worktree is the repo root itself.
    try:
        if worker_checkout.resolve() == Path(root).resolve():
            return True
    except OSError:
        pass
    return False


def preflight_worker_checkout(
    *,
    worker_checkout: Path,
    base_head: str,
    require_detached: bool = True,
    require_clean: bool = True,
    require_registered: bool = True,
    registration_cwd: Path | None = None,
) -> dict[str, Any]:
    """Fail closed unless worker checkout matches lease preconditions."""
    worker = Path(worker_checkout)
    if not worker.is_dir():
        raise ValidationIssue(
            "worker_checkout_missing",
            f"Worker checkout does not exist: {worker}",
        )
    head = _git_head(worker)
    status = _git_status_porcelain(worker)
    symbolic = _git_symbolic_head(worker)
    detached = symbolic is None
    registered = worktree_is_registered(worker, git_cwd=registration_cwd)

    if require_registered and not registered:
        raise ValidationIssue(
            "worker_unregistered",
            f"Worker checkout is not a registered git worktree: {worker}",
            hint="Expand/canonicalize path and verify git worktree list --porcelain",
        )
    if require_clean and status.strip():
        raise ValidationIssue(
            "worker_dirty",
            "Worker checkout is dirty; refuse lease until clean",
            path=str(worker),
            hint=status.strip()[:400],
        )
    if require_detached and not detached:
        raise ValidationIssue(
            "worker_not_detached",
            f"Worker checkout is branch-attached ({symbolic}); detached HEAD required",
            path=str(worker),
        )
    if head != base_head:
        raise ValidationIssue(
            "worker_head_mismatch",
            f"Worker HEAD `{head}` does not match lease base `{base_head}`",
            path=str(worker),
        )
    return {
        "head": head,
        "detached": detached,
        "symbolic_ref": symbolic,
        "status_porcelain": status,
        "registered": registered,
        "clean": not bool(status.strip()),
    }


def refs_digest(cwd: Path) -> str:
    """Stable digest of refs for pre/post comparison (no network)."""
    import hashlib

    result = run_git(
        cwd,
        ["for-each-ref", "--format=%(refname) %(objectname)"],
        env=hardened_git_env(),
    )
    material = "\n".join(sorted((result.stdout or "").splitlines()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class LeaseStore:
    """Disk-backed exclusive writer lease store."""

    def __init__(self, repo_root: Path, *, create: bool = True) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self._create = create
        if create:
            self.root = ensure_leases_dir(self.repo_root)
        else:
            self.root = leases_root(self.repo_root)
        self.malformed_records: list[dict[str, str]] = []

    @classmethod
    def open_readonly(cls, repo_root: Path) -> "LeaseStore":
        return cls(Path(repo_root), create=False)

    def _path(self, lease_id: str) -> Path:
        return self.root / record_filename(lease_id, prefix="lease")

    def _legacy_path(self, lease_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in lease_id)
        return self.root / f"{safe}.json"

    def _read_candidate(self, *paths: Path) -> tuple[Path, dict[str, Any]] | None:
        for path in paths:
            try:
                return path, read_json(path, repo_root=self.repo_root)
            except StorageError as exc:
                if exc.code == "not_found":
                    continue
                raise ValidationIssue(
                    "lease_storage_unsafe",
                    f"Unsafe lease store path ({exc.code})",
                    path=str(self.root),
                ) from exc
        return None

    def list_leases(self) -> list[WriterLease]:
        leases: list[WriterLease] = []
        seen_ids: set[str] = set()
        self.malformed_records = []
        try:
            paths = list_repo_store_files(self.repo_root, self.root, suffix=".json")
        except StorageError as exc:
            self.malformed_records.append(
                {"path": str(self.root), "error": _lease_error_category(exc)}
            )
            return leases
        for path in paths:
            if path.name in {"index.json", "store.lock"}:
                continue
            try:
                data = read_json(path, repo_root=self.repo_root)
                lease = WriterLease.from_dict(data)
                assert_embedded_id(data, lease.lease_id, id_field="lease_id")
                expected_names = {
                    record_filename(lease.lease_id, prefix="lease"),
                    self._legacy_path(lease.lease_id).name,
                }
                if path.name not in expected_names:
                    raise StorageError(
                        "record_filename_mismatch",
                        "Lease record filename does not match its embedded identity",
                    )
                if lease.lease_id in seen_ids:
                    raise StorageError(
                        "duplicate_record_id",
                        "Duplicate lease record identity",
                    )
                seen_ids.add(lease.lease_id)
                leases.append(lease)
            except (
                OSError,
                AttributeError,
                KeyError,
                OverflowError,
                RecursionError,
                TypeError,
                ValueError,
                StorageError,
            ) as exc:
                self.malformed_records.append(
                    {"path": str(self.root), "error": _lease_error_category(exc)}
                )
        return leases

    def list_leases_strict(self) -> list[WriterLease]:
        leases = self.list_leases()
        if self.malformed_records:
            categories = ", ".join(
                sorted({item["error"] for item in self.malformed_records})
            )
            raise ValidationIssue(
                "lease_record_malformed",
                "Malformed lease records block operations "
                f"({len(self.malformed_records)} record(s); categories: {categories})",
                path=str(self.root),
            )
        return leases

    def live_leases(self) -> list[WriterLease]:
        return [lease for lease in self.list_leases_strict() if lease.state in LIVE_LEASE_STATES]

    def get(self, lease_id: str) -> WriterLease:
        path = self._path(lease_id)
        legacy = self._legacy_path(lease_id)
        canonical_loaded = self._read_candidate(path)
        legacy_loaded = self._read_candidate(legacy)
        if canonical_loaded is not None and legacy_loaded is not None:
            raise ValidationIssue(
                "lease_record_ambiguous",
                "Multiple lease records claim the same exact identity",
                path=str(self.root),
            )
        loaded = canonical_loaded or legacy_loaded
        if loaded is None:
            raise ValidationIssue(
                "lease_not_found",
                "No lease record for the requested exact id",
                path=str(self.root),
            )
        chosen, data = loaded
        if legacy_loaded is not None:
            raise ValidationIssue(
                "lease_legacy_read_only",
                "Legacy lease records are inventory-only until explicitly migrated",
                path=str(self.root),
            )
        try:
            assert_embedded_id(data, lease_id, id_field="lease_id")
        except StorageError as exc:
            raise ValidationIssue(
                "lease_embedded_id_mismatch",
                "Lease record embedded id does not match the requested exact identity",
                path=str(self.root),
            ) from exc
        try:
            return WriterLease.from_dict(data)
        except _LEASE_PARSE_ERRORS as exc:
            raise ValidationIssue(
                "lease_record_malformed",
                f"Lease record is malformed ({_lease_error_category(exc)})",
                path=str(self.root),
            ) from exc

    def save(self, lease: WriterLease, *, expected_revision: int | None = None) -> WriterLease:
        if not self._create:
            raise ValidationIssue(
                "lease_store_read_only",
                "Lease store was opened read-only; refusing mutation",
                path=str(self.root),
            )
        self.root = ensure_leases_dir(self.repo_root)
        with directory_lock(self.root, repo_root=self.repo_root):
            # Authority-store corruption or aliases block every transition.
            self.list_leases_strict()
            try:
                WriterLease.from_dict(lease.to_dict())
            except _LEASE_PARSE_ERRORS as exc:
                raise ValidationIssue(
                    "lease_record_malformed",
                    f"Lease record cannot be saved ({_lease_error_category(exc)})",
                    path=str(self.root),
                ) from exc
            path = self._path(lease.lease_id)
            legacy = self._legacy_path(lease.lease_id)
            canonical_loaded = self._read_candidate(path)
            legacy_loaded = self._read_candidate(legacy)
            if legacy_loaded is not None:
                raise ValidationIssue(
                    "lease_legacy_read_only",
                    "Legacy lease records are read-only until explicitly migrated",
                    path=str(self.root),
                )
            current = canonical_loaded[1] if canonical_loaded is not None else None
            if current is not None:
                try:
                    current_rev = int(current.get("revision") or 0)
                except (TypeError, ValueError) as exc:
                    raise ValidationIssue(
                        "lease_record_malformed",
                        "Cannot CAS-save over a malformed lease record",
                        path=str(self.root),
                    ) from exc
                if expected_revision is not None and current_rev != int(expected_revision):
                    raise ValidationIssue(
                        "lease_revision_conflict",
                        f"Stale lease write: expected revision {expected_revision}, "
                        f"disk has {current_rev}",
                        path=str(path),
                    )
                if int(lease.revision or 0) != current_rev:
                    raise ValidationIssue(
                        "lease_revision_conflict",
                        f"Stale lease write: in-memory revision {lease.revision} "
                        f"!= disk {current_rev}",
                        path=str(path),
                    )
                next_revision = current_rev + 1
            else:
                if expected_revision is not None or int(lease.revision or 0) != 0:
                    raise ValidationIssue(
                        "lease_revision_conflict",
                        "New lease records must begin at unpublished revision zero",
                        path=str(path),
                    )
                next_revision = 1
            lease.revision = next_revision
            lease.updated_at = _utc_now()
            if not lease.created_at:
                lease.created_at = lease.updated_at
            atomic_write_json(
                path,
                lease.to_dict(),
                mode=stat.S_IRUSR | stat.S_IWUSR,
                repo_root=self.repo_root,
            )
            return lease

    def snapshot_dir(self, lease_id: str) -> Path:
        return storage_snapshot_path(
            self.root,
            lease_id,
            kind="lease",
            repo_root=self.repo_root,
        )

    def prepare(
        self,
        *,
        lease_id: str,
        host_checkout: Path,
        worker_checkout: Path,
        session_id: str,
        base_head: str,
        adapter: str,
        profile: str,
        allowed_paths: Sequence[str] | None = None,
        sandbox_profile: str = "devbox",
        detached_commits_permitted: bool = True,
        require_detached: bool = True,
        write_profile_qualified: bool = True,
        used_headless_worktree_resume: bool = False,
        grok_version: str | None = None,
        notes: str = "",
        qualification_evidence: Mapping[str, Any] | None = None,
        credential_grant_names: Sequence[str] | None = None,
        credential_grant_context_digest: str | None = None,
    ) -> WriterLease:
        """Create the sole live lease after worker preflight and profile checks."""
        reject_fugu_implementation_route(
            adapter,
            profile,
            requested_model=(
                str((qualification_evidence or {}).get("model") or "") or None
            ),
            environment=os.environ,
        )
        host_path = Path(host_checkout).resolve()
        worker_path = Path(worker_checkout).resolve()
        if host_path == worker_path:
            raise ValidationIssue(
                "worker_checkout_not_isolated",
                "Host and worker checkout must be distinct registered worktrees",
                path=str(worker_path),
            )
        if _git_common_dir(host_path) != _git_common_dir(worker_path):
            raise ValidationIssue(
                "worker_checkout_wrong_repository",
                "Worker checkout is not a linked worktree of the host repository",
                path=str(worker_path),
            )
        if not write_profile_qualified:
            raise ValidationIssue(
                "write_profile_unqualified",
                f"Write profile `{profile}` is not qualified for isolated write",
            )
        # Host-issued observed qualification is required (not optional).
        if qualification_evidence is None:
            raise ValidationIssue(
                "write_qualification_required",
                "Writer lease prepare requires host-issued qualification evidence",
                path="lease.qualification_evidence",
                hint="Pass --qualification-file or --qualification-id from host-owned evidence",
            )
        ok, reasons = qualify_write_evidence(qualification_evidence)
        if not ok:
            raise ValidationIssue(
                "write_qualification_failed",
                "Write qualification evidence failed closed: " + ", ".join(reasons),
                path="lease.qualification_evidence",
            )
        # Exact registered session required; compare every qualification field.
        evidence_session = str(qualification_evidence.get("session_id") or "")
        if not evidence_session:
            raise ValidationIssue(
                "write_qualification_session_required",
                "Qualification evidence requires registered session_id",
            )
        if evidence_session != session_id:
            raise ValidationIssue(
                "write_qualification_session_mismatch",
                f"Qualification session `{evidence_session}` != lease session `{session_id}`",
            )
        if str(qualification_evidence.get("profile") or "") != str(profile):
            raise ValidationIssue(
                "write_qualification_profile_mismatch",
                f"Lease profile `{profile}` != qualification profile "
                f"`{qualification_evidence.get('profile')}`",
            )
        field_pairs = (
            ("adapter", adapter),
            ("sandbox", sandbox_profile),
            ("worktree", str(Path(worker_checkout).resolve())),
            ("cwd", str(Path(worker_checkout).resolve())),
            ("source_head", base_head),
        )
        for field_name, expected in field_pairs:
            observed = qualification_evidence.get(field_name)
            if observed is None or observed == "":
                raise ValidationIssue(
                    "write_qualification_field_missing",
                    f"Qualification missing field `{field_name}`",
                )
            if field_name in {"worktree", "cwd"}:
                try:
                    if Path(str(observed)).resolve() != Path(str(expected)).resolve():
                        raise ValidationIssue(
                            f"write_qualification_{field_name}_mismatch",
                            f"Qualification {field_name} does not match lease",
                        )
                except OSError as exc:
                    raise ValidationIssue(
                        f"write_qualification_{field_name}_unreadable",
                        f"Cannot resolve qualification {field_name}: {exc}",
                    ) from exc
            elif str(observed) != str(expected):
                # model/profile/version compared when evidence carries them
                if field_name == "sandbox" and str(observed).lower() != str(expected).lower():
                    raise ValidationIssue(
                        "write_qualification_sandbox_mismatch",
                        f"sandbox_profile `{expected}` != evidence sandbox `{observed}`",
                    )
                elif field_name != "sandbox":
                    raise ValidationIssue(
                        f"write_qualification_{field_name}_mismatch",
                        f"Qualification {field_name} does not match lease",
                    )
        if str(qualification_evidence.get("adapter") or "") != adapter:
            raise ValidationIssue(
                "write_qualification_adapter_mismatch",
                "Qualification adapter does not match lease adapter",
            )
        if grok_version is not None and str(
            qualification_evidence.get("version") or ""
        ) != str(grok_version):
            raise ValidationIssue(
                "write_qualification_version_mismatch",
                "Qualification tool version does not match the requested writer version",
            )
        # sandbox_profile must equal evidence sandbox and be in supported enum.
        from .storage import SUPPORTED_SANDBOX_PROFILES  # noqa: PLC0415

        if str(sandbox_profile).strip().lower() not in SUPPORTED_SANDBOX_PROFILES:
            raise ValidationIssue(
                "write_qualification_sandbox_unsupported",
                f"sandbox_profile `{sandbox_profile}` not in supported enum; "
                "arbitrary strings cannot enable detached commits",
            )
        # Require the exact registered session and compare every identity field;
        # mere existence never grants write authority.
        try:
            from .sessions import SessionLifecycle, SessionRegistry  # noqa: PLC0415

            registry = SessionRegistry(Path(host_checkout))
            try:
                registered = registry.get(session_id)
            except ValidationIssue as issue:
                raise ValidationIssue(
                    "write_qualification_session_unregistered",
                    f"Lease requires registered exact session `{session_id}`: {issue.message}",
                ) from issue

            if registered.lifecycle != SessionLifecycle.ACTIVE:
                raise ValidationIssue(
                    "write_qualification_session_inactive",
                    "Writer lease requires an exact ACTIVE registered session "
                    f"(have {registered.lifecycle.value})",
                )
            if (
                registered.write_reuse_blocked
                or registered.pending_context_digest
                or registered.pending_source_head
                or registered.rehydration_reason
            ):
                raise ValidationIssue(
                    "write_qualification_session_blocked",
                    "Writer lease refused: session has write-reuse or pending rehydration state",
                )

            registered_model = registered.actual_model or registered.requested_model
            identity_pairs = (
                ("adapter", registered.harness, qualification_evidence.get("adapter")),
                ("profile", registered.profile, qualification_evidence.get("profile")),
                ("model", registered_model, qualification_evidence.get("model")),
                ("parent", registered.parent_id, qualification_evidence.get("parent")),
                ("source_head", registered.source_head, qualification_evidence.get("source_head")),
            )
            for field_name, registered_value, observed_value in identity_pairs:
                if str(registered_value or "") != str(observed_value or ""):
                    raise ValidationIssue(
                        f"write_qualification_registered_{field_name}_mismatch",
                        f"Qualification {field_name} does not match registered session",
                    )
            for field_name, registered_value, observed_value in (
                ("cwd", registered.cwd, qualification_evidence.get("cwd")),
                ("worktree", registered.worktree, qualification_evidence.get("worktree")),
            ):
                if not registered_value or not observed_value or Path(
                    str(registered_value)
                ).resolve() != Path(str(observed_value)).resolve():
                    raise ValidationIssue(
                        f"write_qualification_registered_{field_name}_mismatch",
                        f"Qualification {field_name} does not match registered session",
                    )
        except ValidationIssue:
            raise
        except Exception as exc:  # noqa: PLC0415, BLE001
            raise ValidationIssue(
                "write_qualification_registry_unavailable",
                f"Cannot verify registered session identity: {exc}",
            ) from exc
        import hashlib

        from .audit import normalize_worker_credential_grant_names  # noqa: PLC0415

        normalized_grant_names = normalize_worker_credential_grant_names(
            credential_grant_names
        )
        if credential_grant_context_digest is not None and (
            len(credential_grant_context_digest) != 64
            or credential_grant_context_digest.lower() != credential_grant_context_digest
            or any(
                char not in "0123456789abcdef"
                for char in credential_grant_context_digest
            )
        ):
            raise ValidationIssue(
                "worker_credential_context_digest_invalid",
                "Worker credential context digest must be canonical SHA-256",
            )
        if normalized_grant_names and credential_grant_context_digest is None:
            raise ValidationIssue(
                "worker_credential_context_required",
                "Named worker credential grants require private prepare-time authority",
            )

        qual_digest = hashlib.sha256(
            json.dumps(dict(qualification_evidence), sort_keys=True).encode("utf-8")
        ).hexdigest()
        if used_headless_worktree_resume and adapter == "grok-build":
            from .sessions import assert_grok_worktree_isolation

            assert_grok_worktree_isolation(
                version=grok_version,
                cwd_verified=True,
                worktree_registered=True,
                used_headless_worktree_resume=True,
            )

        record_path = self._path(lease_id)
        legacy_path = self._legacy_path(lease_id)
        qualification_path = self.snapshot_dir(lease_id) / "qualification.json"
        # Fail before lock creation or evidence publication when any authority
        # leaf has already been replaced by a symlink/non-regular file.
        repo_regular_file_exists(self.repo_root, record_path)
        repo_regular_file_exists(self.repo_root, legacy_path)
        repo_regular_file_exists(self.repo_root, qualification_path)
        with directory_lock(self.root, repo_root=self.repo_root):
            # Lease IDs are authority identities. Once published, including in a
            # terminal state, they are immutable and never reusable.
            if repo_regular_file_exists(
                self.repo_root, record_path
            ) or repo_regular_file_exists(self.repo_root, legacy_path):
                raise ValidationIssue(
                    "lease_id_immutable",
                    f"Lease id `{lease_id}` was already published and cannot be reused",
                    path=str(self._path(lease_id)),
                )
            # Malformed records block exclusivity checks rather than disappearing.
            live = [
                lease
                for lease in self.list_leases_strict()
                if lease.state in LIVE_LEASE_STATES
            ]
            if live:
                raise ValidationIssue(
                    "lease_exclusivity",
                    f"A live writer lease already exists: {live[0].lease_id} ({live[0].state.value})",
                    hint="Only one external writer lease may be active at a time",
                )

            paths = list(allowed_paths or [])
            if not paths:
                raise ValidationIssue(
                    "empty_path_allowlist",
                    "Writer leases require a non-empty explicit allowed_paths list",
                    hint="Refuse broad empty allow-lists; name product paths the worker may touch",
                )
            for rel in paths:
                normalize_repo_rel_path(rel)

            pre = preflight_worker_checkout(
                worker_checkout=Path(worker_checkout),
                base_head=base_head,
                require_detached=require_detached,
                require_clean=True,
                require_registered=True,
                registration_cwd=Path(host_checkout),
            )
            digest = refs_digest(Path(worker_checkout))
            workspace_capable = sandbox_profile != "workspace"
            lease = WriterLease(
                lease_id=lease_id,
                host_checkout=str(Path(host_checkout).resolve()),
                worker_checkout=str(Path(worker_checkout).resolve()),
                session_id=session_id,
                base_head=base_head,
                adapter=adapter,
                profile=profile,
                sandbox_profile=sandbox_profile,
                allowed_paths=paths,
                detached_commits_permitted=detached_commits_permitted and workspace_capable,
                require_detached=require_detached,
                state=LeaseState.PREPARED,
                pre_status=pre["status_porcelain"],
                pre_refs_digest=digest,
                notes=notes,
                worker_tip=pre["head"],
                workspace_sandbox_commit_capable=workspace_capable,
                qualification_digest=qual_digest,
                credential_grant_names=normalized_grant_names,
                credential_grant_context_digest=credential_grant_context_digest,
            )
            if sandbox_profile == "workspace":
                lease.notes = (
                    lease.notes + "\nworkspace sandbox: commits not assumed capable; "
                    "detached_commits_permitted forced false"
                ).strip()
                lease.detached_commits_permitted = False
            lease.updated_at = _utc_now()
            lease.created_at = lease.updated_at
            # Revision zero is reserved for unpublished/create-race objects and
            # is never a valid implicit-CAS update token.
            lease.revision = 1
            qualification_dir = self.snapshot_dir(lease.lease_id)
            ensure_private_dir(qualification_dir, repo_root=self.repo_root)
            atomic_write_json(
                qualification_dir / "qualification.json",
                dict(qualification_evidence),
                mode=stat.S_IRUSR | stat.S_IWUSR,
                repo_root=self.repo_root,
            )
            # Publish the authority-bearing lease record last. A crash may leave
            # inert qualification evidence, never a live lease without evidence.
            path = self._path(lease.lease_id)
            atomic_write_json(
                path,
                lease.to_dict(),
                mode=stat.S_IRUSR | stat.S_IWUSR,
                repo_root=self.repo_root,
            )
            return lease

    def activate(self, lease_id: str) -> WriterLease:
        lease = self.get(lease_id)
        lease.state = transition_lease_state(lease.state, LeaseState.ACTIVE)
        return self.save(lease)

    def mark_auditing(self, lease_id: str) -> WriterLease:
        lease = self.get(lease_id)
        lease.state = transition_lease_state(lease.state, LeaseState.AUDITING)
        return self.save(lease)

    @staticmethod
    def _canonical_evidence_digest(evidence: Mapping[str, Any]) -> str:
        canonical = {
            key: value
            for key, value in evidence.items()
            if key != "evidence_digest"
        }
        try:
            payload = json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValidationIssue(
                "audit_evidence_malformed",
                "Audit evidence must be canonical JSON data",
            ) from exc
        return hashlib.sha256(payload).hexdigest()

    def _validate_audit_evidence(
        self,
        lease: WriterLease,
        evidence: Mapping[str, Any],
        *,
        require_live_authority: bool = False,
        allow_shared_refs_changed: bool = False,
        allow_refreshed_tip: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Bind audit evidence to the live, clean detached commit chain."""
        if require_live_authority:
            # Runtime import avoids the leases <-> audit module import cycle.
            from .audit import _is_verified_audit_evidence  # noqa: PLC0415

            if not _is_verified_audit_evidence(evidence):
                raise ValidationIssue(
                    "audit_evidence_unverified",
                    "Audit promotion requires the live result of audit_lease_turn",
                )
        required_fields = {
            "ok",
            "lease_id",
            "worker_tip",
            "base_head",
            "commit_chain",
            "audited_git_surfaces",
            "patch_transport_digests",
            "evidence_digest",
        }
        missing = sorted(required_fields - set(evidence))
        if missing:
            raise ValidationIssue(
                "audit_evidence_incomplete",
                "Audit evidence missing fields: " + ", ".join(missing),
            )
        if evidence.get("ok") is not True:
            raise ValidationIssue(
                "audit_evidence_not_ok",
                "Cannot trust audit evidence when evidence.ok is not exactly true",
            )
        if str(evidence.get("lease_id") or "") != lease.lease_id:
            raise ValidationIssue(
                "audit_evidence_lease_mismatch",
                "Audit evidence lease_id does not match store lease",
            )
        if str(evidence.get("base_head") or "") != lease.base_head:
            raise ValidationIssue(
                "audit_evidence_base_mismatch",
                "Audit evidence base_head does not match store lease",
            )

        supplied_digest = str(evidence.get("evidence_digest") or "")
        if (
            len(supplied_digest) != 64
            or supplied_digest.lower() != supplied_digest
            or any(char not in "0123456789abcdef" for char in supplied_digest)
        ):
            raise ValidationIssue(
                "audit_evidence_digest_missing",
                "Audit evidence requires a canonical lowercase SHA-256 digest",
            )
        expected_digest = self._canonical_evidence_digest(evidence)
        if supplied_digest != expected_digest:
            raise ValidationIssue(
                "audit_evidence_digest_mismatch",
                "Audit evidence digest does not match its canonical payload",
            )

        # Runtime import avoids the leases <-> audit module import cycle.  The
        # descriptor-only assertion must run before *any* post-worker Git
        # command so a swapped locator or executable config cannot observe the
        # host environment before rejection.
        from .audit import (  # noqa: PLC0415
            assert_audited_git_surfaces,
            list_commit_chain,
            snapshot_git_authority,
            snapshot_ref_storage,
            validated_patch_transport_digests,
        )

        worker = Path(lease.worker_checkout)
        recovered_ref_delta = False
        strict_surface_issue: ValidationIssue | None = None
        try:
            live_surfaces = assert_audited_git_surfaces(
                worker,
                evidence,
                allow_shared_refs_changed=allow_shared_refs_changed,
            )
        except ValidationIssue as issue:
            if allow_refreshed_tip is None or not allow_shared_refs_changed:
                raise
            strict_surface_issue = issue

            # A process may die after the detached HEAD update succeeds but
            # before the caller closes the already-INTEGRATED lease.  Permit
            # exactly that descriptor delta for recovery: all worktree ref
            # storage other than HEAD must still match the sealed snapshot.
            expected_surfaces = evidence["audited_git_surfaces"]
            current_authority = snapshot_git_authority(worker)
            if current_authority != expected_surfaces["authority"]:
                raise issue
            trusted_worker = Path(str(current_authority["worker_checkout"]))
            trusted_git_dir = Path(str(current_authority["git_dir"]))
            trusted_common_dir = Path(str(current_authority["common_dir"]))
            current_refs = snapshot_ref_storage(
                trusted_git_dir,
                trusted_common_dir,
            )
            expected_refs = expected_surfaces["ref_storage"]
            try:
                current_worktree_refs = current_refs["worktree"]
                expected_worktree_refs = expected_refs["worktree"]
                current_head_descriptor = current_worktree_refs["pseudorefs"]["HEAD"]
                expected_head_descriptor = expected_worktree_refs["pseudorefs"]["HEAD"]
            except (KeyError, TypeError) as exc:
                raise ValidationIssue(
                    "audit_evidence_git_surfaces_malformed",
                    "Audit worktree ref authority is not canonical",
                ) from exc
            normalized_worktree_refs = copy.deepcopy(current_worktree_refs)
            normalized_worktree_refs["pseudorefs"]["HEAD"] = copy.deepcopy(
                expected_head_descriptor
            )
            if (
                current_head_descriptor == expected_head_descriptor
                or normalized_worktree_refs != expected_worktree_refs
            ):
                raise issue

            recovery_evidence = copy.deepcopy(dict(evidence))
            recovery_surfaces = recovery_evidence["audited_git_surfaces"]
            recovery_refs = recovery_surfaces["ref_storage"]
            recovery_refs["worktree"] = copy.deepcopy(current_worktree_refs)
            live_surfaces = assert_audited_git_surfaces(
                worker,
                recovery_evidence,
                allow_shared_refs_changed=True,
            )
            recovered_ref_delta = True
        authority = live_surfaces["authority"]
        trusted_worker = Path(str(authority["worker_checkout"]))
        trusted_git_dir = Path(str(authority["git_dir"]))
        trusted_common_dir = Path(str(authority["common_dir"]))
        live_tip = _git_head(
            trusted_worker,
            git_dir=trusted_git_dir,
            common_dir=trusted_common_dir,
        )
        audited_tip = str(evidence.get("worker_tip") or "")
        recovered_refresh = (
            recovered_ref_delta
            and allow_refreshed_tip is not None
            and live_tip == allow_refreshed_tip
        )
        if live_tip != audited_tip and not recovered_refresh:
            raise ValidationIssue(
                "audit_evidence_tip_mismatch",
                "Worker HEAD matches neither the audited tip nor the recorded refresh tip",
            )
        if recovered_ref_delta and not recovered_refresh:
            # A rewritten HEAD that still names the old audit tip is not a
            # crash-recovery condition; preserve the original strict failure.
            assert strict_surface_issue is not None
            raise strict_surface_issue
        status = _git_status_porcelain(
            trusted_worker,
            git_dir=trusted_git_dir,
            common_dir=trusted_common_dir,
        )
        if status.strip():
            raise ValidationIssue(
                "audit_evidence_worker_dirty",
                "Worker checkout changed after audit; refuse proof promotion",
                hint=redact_text(status.strip()).text[:400],
            )

        live_commit_chain = list_commit_chain(
            trusted_worker,
            lease.base_head,
            audited_tip,
            git_dir=trusted_git_dir,
            common_dir=trusted_common_dir,
        )
        live_chain = [commit.to_dict() for commit in live_commit_chain]
        supplied_chain = evidence.get("commit_chain")
        if not isinstance(supplied_chain, list) or supplied_chain != live_chain:
            raise ValidationIssue(
                "audit_evidence_commit_chain_mismatch",
                "Audit evidence commit_chain does not match the live worker history",
            )
        validated_patch_transport_digests(evidence, live_commit_chain)
        if recovered_refresh:
            if (
                not supplied_chain
                or not isinstance(supplied_chain[-1], dict)
                or not isinstance(supplied_chain[-1].get("tree"), str)
            ):
                raise ValidationIssue(
                    "integration_audited_tree_missing",
                    "Persisted audit evidence lacks a final candidate tree",
                )
            refresh_env = hardened_git_env(
                work_tree=trusted_worker,
                git_dir=trusted_git_dir,
                common_dir=trusted_common_dir,
            )
            ancestry = run_git(
                trusted_worker,
                ["merge-base", "--is-ancestor", lease.base_head, live_tip],
                check=False,
                env=refresh_env,
            )
            if ancestry.returncode != 0:
                raise ValidationIssue(
                    "refresh_not_descendant",
                    "Recorded refresh tip is no longer a descendant of the audited base",
                )
            refreshed_tree = run_git(
                trusted_worker,
                ["rev-parse", f"{live_tip}^{{tree}}"],
                env=refresh_env,
            ).stdout.strip()
            if refreshed_tree != supplied_chain[-1]["tree"]:
                raise ValidationIssue(
                    "refresh_tree_mismatch",
                    "Recorded refresh tip no longer matches the sealed audited tree",
                )
            assert_audited_git_surfaces(
                trusted_worker,
                recovery_evidence,
                allow_shared_refs_changed=True,
            )
        else:
            assert_audited_git_surfaces(
                trusted_worker,
                evidence,
                allow_shared_refs_changed=allow_shared_refs_changed,
            )
        return dict(evidence), supplied_digest

    def _read_verified_audit_evidence(
        self,
        lease: WriterLease,
        *,
        allow_shared_refs_changed: bool = False,
        allow_refreshed_tip: str | None = None,
    ) -> dict[str, Any]:
        evidence_path = self.snapshot_dir(lease.lease_id) / "audit_evidence.json"
        try:
            evidence = read_json(evidence_path, repo_root=self.repo_root)
        except StorageError as exc:
            raise ValidationIssue(
                "audit_evidence_unavailable",
                "Persisted audit evidence is missing or unsafe",
                path=str(evidence_path),
            ) from exc
        verified, digest = self._validate_audit_evidence(
            lease,
            evidence,
            allow_shared_refs_changed=allow_shared_refs_changed,
            allow_refreshed_tip=allow_refreshed_tip,
        )
        if digest != str(lease.audit_evidence_digest or ""):
            raise ValidationIssue(
                "audit_evidence_lease_digest_mismatch",
                "Persisted audit evidence digest does not match the lease authority",
            )
        return verified

    def mark_audited_pass(
        self,
        lease_id: str,
        *,
        evidence: Mapping[str, Any] | None = None,
    ) -> WriterLease:
        """Record immutable audit success. Requires proof evidence; never bare promote."""
        if evidence is None or not isinstance(evidence, Mapping):
            raise ValidationIssue(
                "audit_evidence_required",
                "mark_audited_pass requires a complete audit evidence object",
                path=f"leases.{lease_id}",
            )
        lease = self.get(lease_id)
        verified, evidence_digest = self._validate_audit_evidence(
            lease,
            evidence,
            require_live_authority=True,
        )
        lease.state = transition_lease_state(lease.state, LeaseState.AUDITED_PASS)
        lease.worker_tip = str(verified["worker_tip"])
        lease.audit_evidence_digest = evidence_digest
        # Persist evidence under store-owned snapshot path.
        evidence_dir = self.snapshot_dir(lease_id)
        ensure_private_dir(evidence_dir, repo_root=self.repo_root)
        atomic_write_json(
            evidence_dir / "audit_evidence.json",
            verified,
            repo_root=self.repo_root,
        )
        return self.save(lease)

    def mark_exported(self, lease_id: str, patch_dir: str) -> WriterLease:
        lease = self.get(lease_id)
        # Export is legal only from AUDITED_PASS — never implicitly promote.
        if lease.state != LeaseState.AUDITED_PASS and lease.state != LeaseState.EXPORTED:
            raise ValidationIssue(
                "export_requires_audited_pass",
                f"Export refused from state `{lease.state.value}`; require audited_pass",
                path=f"leases.{lease_id}.state",
            )
        self._read_verified_audit_evidence(lease)
        candidate = Path(patch_dir).expanduser()
        # Verify the caller-visible path first so a symlink leaf is rejected,
        # then persist only the canonical real directory identity.
        from .audit import verify_patch_manifest  # noqa: PLC0415

        verify_patch_manifest(lease, output_dir=candidate)
        try:
            canonical_patch_dir = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValidationIssue(
                "patch_manifest_dir_missing",
                "Patch export directory cannot be resolved",
                path=str(candidate),
            ) from exc
        if (
            lease.state == LeaseState.EXPORTED
            and lease.exported_patch_dir
            and Path(lease.exported_patch_dir) != canonical_patch_dir
        ):
            raise ValidationIssue(
                "export_path_immutable",
                "An exported lease cannot be rebound to a different patch directory",
            )
        lease.state = transition_lease_state(lease.state, LeaseState.EXPORTED)
        lease.exported_patch_dir = str(canonical_patch_dir)
        return self.save(lease)

    def mark_apply_checked(
        self,
        lease_id: str,
        *,
        evidence: Mapping[str, Any] | None = None,
    ) -> WriterLease:
        lease = self.get(lease_id)
        if lease.state != LeaseState.EXPORTED:
            raise ValidationIssue(
                "apply_check_requires_exported",
                f"Apply-check refused from state `{lease.state.value}`; require exported",
            )
        from .audit import (  # noqa: PLC0415
            _read_verified_patch_bundle,
            _is_verified_host_apply_evidence,
        )

        if evidence is None or not isinstance(evidence, Mapping):
            raise ValidationIssue(
                "apply_check_evidence_required",
                "Apply-check promotion requires immutable host evidence",
            )
        if not _is_verified_host_apply_evidence(evidence):
            raise ValidationIssue(
                "apply_check_evidence_unverified",
                "Apply-check promotion requires the live result of host_apply_check",
            )
        audited_evidence = self._read_verified_audit_evidence(lease)
        if not lease.exported_patch_dir:
            raise ValidationIssue(
                "apply_check_export_path_missing",
                "Apply-check promotion requires the persisted export path",
            )
        try:
            manifest_dir = Path(lease.exported_patch_dir).resolve(strict=True)
        except OSError as exc:
            raise ValidationIssue(
                "patch_manifest_dir_missing",
                "Persisted patch export directory is unavailable",
                path=str(lease.exported_patch_dir),
            ) from exc
        bundle = _read_verified_patch_bundle(lease, output_dir=manifest_dir)
        manifest = bundle.manifest
        expected = {
            "ok": True,
            "manifest_verified": True,
            "lease_id": lease.lease_id,
            "base_head": lease.base_head,
            "worker_tip": lease.worker_tip,
            "audit_evidence_digest": lease.audit_evidence_digest,
            "host_head": lease.base_head,
            "cumulative": True,
            "disposable": True,
        }
        for field_name, expected_value in expected.items():
            if evidence.get(field_name) != expected_value:
                raise ValidationIssue(
                    "apply_check_evidence_mismatch",
                    f"Apply-check evidence `{field_name}` does not match the lease",
                )
        audited_chain = audited_evidence.get("commit_chain")
        if (
            not isinstance(audited_chain, list)
            or not audited_chain
            or not isinstance(audited_chain[-1], dict)
        ):
            raise ValidationIssue(
                "apply_check_evidence_mismatch",
                "Persisted audit evidence lacks the final candidate tree",
            )
        expected_worker_tree = str(audited_chain[-1].get("tree") or "")
        if (
            not expected_worker_tree
            or evidence.get("expected_worker_tree") != expected_worker_tree
            or evidence.get("resulting_tree") != expected_worker_tree
        ):
            raise ValidationIssue(
                "apply_check_evidence_mismatch",
                "Apply-check result is not bound to the audited candidate tree",
            )
        expected_transport_authority_digest = hashlib.sha256(
            json.dumps(
                audited_evidence.get("patch_transport_digests"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if evidence.get(
            "patch_transport_authority_digest"
        ) != expected_transport_authority_digest:
            raise ValidationIssue(
                "apply_check_evidence_mismatch",
                "Apply-check result is not bound to audited patch transports",
            )
        checked = evidence.get("checked")
        manifest_digest = str(evidence.get("manifest_digest") or "")
        expected_checked = [name for name, _data in bundle.patches]
        if not isinstance(checked, list) or checked != expected_checked or not checked:
            raise ValidationIssue(
                "apply_check_evidence_mismatch",
                "Apply-check evidence does not match the verified ordered patch list",
            )
        if manifest_digest != str(manifest.get("manifest_digest") or ""):
            raise ValidationIssue(
                "apply_check_evidence_mismatch",
                "Apply-check evidence manifest digest does not match persisted proof",
            )
        canonical = dict(evidence)
        evidence_digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        evidence_dir = self.snapshot_dir(lease_id)
        ensure_private_dir(evidence_dir, repo_root=self.repo_root)
        atomic_write_json(
            evidence_dir / "apply_check_evidence.json",
            canonical,
            repo_root=self.repo_root,
        )
        lease.state = transition_lease_state(lease.state, LeaseState.APPLY_CHECKED)
        lease.apply_check_evidence_digest = evidence_digest
        return self.save(lease)

    def mark_integrated(self, lease_id: str, *, new_tip: str) -> WriterLease:
        """Verify host integration before recording the terminal integration state."""
        lease = self.get(lease_id)
        if lease.state not in {LeaseState.APPLY_CHECKED, LeaseState.INTEGRATED}:
            raise ValidationIssue(
                "integrate_requires_apply_checked",
                f"Integration refused from `{lease.state.value}`; require apply_checked",
                path=f"leases.{lease_id}.state",
            )
        from .audit import snapshot_git_authority  # noqa: PLC0415

        audited_evidence = self._read_verified_audit_evidence(
            lease,
            allow_shared_refs_changed=True,
        )
        audited_chain = audited_evidence.get("commit_chain")
        if (
            not isinstance(audited_chain, list)
            or not audited_chain
            or not isinstance(audited_chain[-1], dict)
            or not isinstance(audited_chain[-1].get("tree"), str)
        ):
            raise ValidationIssue(
                "integration_audited_tree_missing",
                "Persisted audit evidence lacks a final candidate tree",
            )
        expected_tree = str(audited_chain[-1]["tree"])
        host_authority = snapshot_git_authority(Path(lease.host_checkout))
        host = Path(str(host_authority["worker_checkout"]))
        host_git_dir = Path(str(host_authority["git_dir"]))
        host_common_dir = Path(str(host_authority["common_dir"]))
        worker_surfaces = audited_evidence["audited_git_surfaces"]
        worker_authority = worker_surfaces["authority"]
        worker = Path(str(worker_authority["worker_checkout"]))
        worker_git_dir = Path(str(worker_authority["git_dir"]))
        worker_common_dir = Path(str(worker_authority["common_dir"]))
        host_status = _git_status_porcelain(
            host,
            git_dir=host_git_dir,
            common_dir=host_common_dir,
        )
        worker_status = _git_status_porcelain(
            worker,
            git_dir=worker_git_dir,
            common_dir=worker_common_dir,
        )
        if host_status.strip():
            raise ValidationIssue(
                "host_dirty_on_integrate",
                "Host checkout must be clean before integration can be recorded",
                hint=host_status.strip()[:400],
            )
        if worker_status.strip():
            raise ValidationIssue(
                "worker_dirty_on_integrate",
                "Worker checkout must be clean before integration can be recorded",
                hint=worker_status.strip()[:400],
            )
        host_head = _git_head(
            host,
            git_dir=host_git_dir,
            common_dir=host_common_dir,
        )
        if host_head != new_tip:
            raise ValidationIssue(
                "integration_host_tip_mismatch",
                f"Host HEAD `{host_head}` != requested integrated tip `{new_tip}`",
            )
        ancestry = run_git(
            host,
            ["merge-base", "--is-ancestor", lease.base_head, new_tip],
            check=False,
            env=hardened_git_env(
                work_tree=host,
                git_dir=host_git_dir,
                common_dir=host_common_dir,
            ),
        )
        if ancestry.returncode != 0:
            raise ValidationIssue(
                "integration_not_descendant",
                f"Integrated tip `{new_tip}` is not a descendant of base `{lease.base_head}`",
            )
        audited_tip = str(lease.worker_tip or "")
        if not audited_tip:
            raise ValidationIssue(
                "integration_audited_tip_missing",
                "Lease has no audited worker tip to compare with host integration",
            )
        if _git_head(
            worker,
            git_dir=worker_git_dir,
            common_dir=worker_common_dir,
        ) != audited_tip:
            raise ValidationIssue(
                "integration_worker_tip_mismatch",
                "Worker HEAD no longer matches the audited worker tip",
            )
        host_tree = run_git(
            host,
            ["rev-parse", f"{new_tip}^{{tree}}"],
            check=True,
            env=hardened_git_env(
                work_tree=host,
                git_dir=host_git_dir,
                common_dir=host_common_dir,
            ),
        ).stdout.strip()
        if host_tree != expected_tree:
            raise ValidationIssue(
                "integration_tree_mismatch",
                "Host integrated tree does not match the sealed audited tree",
            )
        lease.state = transition_lease_state(lease.state, LeaseState.INTEGRATED)
        lease.integrated_tip = new_tip
        return self.save(lease)

    def reject(self, lease_id: str, reason: str) -> WriterLease:
        lease = self.get(lease_id)
        lease.state = transition_lease_state(lease.state, LeaseState.REJECTED)
        lease.rejection_reason = redact_text(str(reason)).text
        return self.save(lease)

    def close(self, lease_id: str) -> WriterLease:
        lease = self.get(lease_id)
        # Closing is allowed from most non-rejected live/terminal success states.
        if lease.state == LeaseState.REJECTED:
            raise ValidationIssue(
                "invalid_lease_transition",
                "Rejected leases are terminal and cannot be closed into a success path",
            )
        if lease.state != LeaseState.CLOSED:
            # Prefer explicit close transition when allowed; otherwise go via integrate/reject.
            try:
                lease.state = transition_lease_state(lease.state, LeaseState.CLOSED)
            except ValidationIssue:
                # From exported/apply_checked, require integrate first.
                raise
        return self.save(lease)

    def refresh_worker_to_tip(
        self,
        lease_id: str,
        *,
        new_tip: str,
    ) -> dict[str, Any]:
        """After export+integration, move clean detached worker HEAD to new tip.

        Refuses dirty/ambiguous state. Does not delete worktrees or sessions.
        """
        lease = self.get(lease_id)
        if lease.state != LeaseState.INTEGRATED:
            raise ValidationIssue(
                "invalid_lease_state",
                "Worker refresh requires the integrated state "
                f"(have {lease.state.value})",
            )
        if not lease.integrated_tip or new_tip != lease.integrated_tip:
            raise ValidationIssue(
                "refresh_tip_mismatch",
                "Worker refresh tip must match the recorded integrated host tip",
            )
        audited_evidence = self._read_verified_audit_evidence(
            lease,
            allow_shared_refs_changed=True,
            allow_refreshed_tip=new_tip,
        )
        authority = audited_evidence["audited_git_surfaces"]["authority"]
        worker = Path(str(authority["worker_checkout"]))
        git_dir = Path(str(authority["git_dir"]))
        common_dir = Path(str(authority["common_dir"]))
        status = _git_status_porcelain(
            worker,
            git_dir=git_dir,
            common_dir=common_dir,
        )
        if status.strip():
            raise ValidationIssue(
                "worker_dirty_on_refresh",
                "Refuse refresh: worker checkout is dirty or ambiguous",
                hint=status.strip()[:400],
            )
        before_head = _git_head(
            worker,
            git_dir=git_dir,
            common_dir=common_dir,
        )
        if before_head != new_tip:
            run_git(
                worker,
                ["update-ref", "HEAD", new_tip],
                env=hardened_git_env(
                    work_tree=worker,
                    git_dir=git_dir,
                    common_dir=common_dir,
                ),
            )
        # Detached HEAD stays detached; verify.
        head = _git_head(worker, git_dir=git_dir, common_dir=common_dir)
        if head != new_tip:
            raise ValidationIssue(
                "refresh_head_mismatch",
                f"After refresh HEAD `{head}` != requested tip `{new_tip}`",
            )
        self._read_verified_audit_evidence(
            lease,
            allow_shared_refs_changed=True,
            allow_refreshed_tip=new_tip,
        )
        # base_head and worker_tip remain the immutable audit-proof binding.
        # The durable INTEGRATED state + integrated_tip are enough to recover
        # if the caller dies after update-ref and before close succeeds.
        return {
            "lease_id": lease.lease_id,
            "worker_tip": head,
            "clean": True,
            "already_current": before_head == new_tip,
        }
