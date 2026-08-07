"""External lane isolation: disposable policy-filtered snapshots + optional FS sandbox.

Creates a disposable work directory containing policy-admitted source files with isolated
HOME/TMP/XDG. Callers choose whether safe non-ignored untracked files are relevant; immutable
credential, instruction, file-type, and repository-boundary checks remain host-owned. Adapter argv
must target the snapshot (not the host repo).
Where available, a platform filesystem sandbox (sandbox-exec / bwrap) blocks
absolute host-home and sibling paths; otherwise optional external attempts are
skipped and required routes block.
"""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import json
import os
import secrets
import shlex
import shutil
import stat
import subprocess
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

from .context import (
    SECRET_FILE_GLOBS,
    SECRET_FILE_NAMES,
    validate_credential_grant_names,
)
from .schema import ELVES_SESSION_BASENAME, ValidationIssue


INSTRUCTION_BASENAMES: frozenset[str] = frozenset(
    {
        "AGENTS.md",
        "AGENTS.override.md",
        "CLAUDE.md",
        "CLAUDE.local.md",
        "Claude.md",
        "GEMINI.md",
        "SKILL.md",
        "CONSTITUTION.md",
        ".cursorrules",
        ".cursor",
        ".claude",
        ".codex",
        ".grok",
        ".gemini",
        ".opencode",
        ".antigravity",
        ".agy",
        ".agent",
    }
)

# Project-local files which supported providers may auto-load as instructions.
# They are never left at an active path in the disposable checkout.
INSTRUCTION_RELATIVE_PATHS: frozenset[str] = frozenset(
    {
        ".github/copilot-instructions.md",
    }
)
INSTRUCTION_RELATIVE_PREFIXES: tuple[str, ...] = (
    ".github/instructions/",
    ".github/prompts/",
    ".github/agents/",
)

# These files can execute commands, register MCP servers, or load credentials.
# Renaming them to inert evidence is insufficient: they stay absent even when
# prose instructions were explicitly requested as data.
EXECUTABLE_AGENT_CONFIG_NAMES: frozenset[str] = frozenset(
    {
        ".mcp.json",
        "opencode.json",
        "opencode.jsonc",
    }
)
EXECUTABLE_AGENT_CONFIG_PATHS: frozenset[str] = frozenset(
    {
        ".vscode/mcp.json",
    }
)
EXECUTABLE_AGENT_CONFIG_PREFIXES: tuple[str, ...] = (
    ".claude/",
    ".codex/",
    ".grok/",
    ".gemini/",
    ".opencode/",
    ".antigravity/",
    ".agy/",
    ".agent/",
)

PROTECTED_AGENT_CONFIG_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".claude",
        ".codex",
        ".grok",
        ".gemini",
        ".opencode",
        ".antigravity",
        ".agy",
        ".agent",
    }
)

_SANDBOX_BACKEND_CANDIDATES: tuple[tuple[str, Path], ...] = (
    ("sandbox-exec", Path("/usr/bin/sandbox-exec")),
    ("bwrap", Path("/usr/bin/bwrap")),
)
_SANDBOX_PROBE_TIMEOUT_SECONDS = 5.0
_MACOS_SUPERVISOR_CANDIDATES: tuple[Path, ...] = (
    Path("/bin/ps"),
    Path("/usr/bin/ps"),
)
# Read-only lanes commonly need Git/search, while the official codex-fugu
# launcher resolves and execs the real Codex binary after the outer launcher
# has entered the filesystem sandbox.  Every entry is resolved to one exact
# executable (and a narrowly inferred runtime root when required); this is not
# a PATH-wide read grant.
_SANDBOX_CHILD_TOOL_NAMES: tuple[str, ...] = ("git", "rg", "codex")
# Compatibility seam used by macOS sandbox regression fixtures.
_MACOS_CHILD_TOOL_NAMES: tuple[str, ...] = _SANDBOX_CHILD_TOOL_NAMES

DEFAULT_EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".elves",
        ".env",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".worktrees",
        "worktrees",
        ".aws",
        ".ssh",
        ".gnupg",
    }
)

DEFAULT_EXCLUDED_FILE_NAMES: frozenset[str] = frozenset(SECRET_FILE_NAMES) | frozenset(
    {
        ELVES_SESSION_BASENAME,
    }
)

DEFAULT_EXCLUDED_FILE_GLOBS: tuple[str, ...] = SECRET_FILE_GLOBS

DEFAULT_CONTEXT_MAX_FILES = 20_000
DEFAULT_CONTEXT_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_CONTEXT_MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_CONTEXT_DIAGNOSTICS = 200
DEFAULT_HANDOFF_MAX_FILES = 2_000
DEFAULT_HANDOFF_MAX_BYTES = 64 * 1024 * 1024
_INTERNAL_SNAPSHOT_PREFIXES: tuple[str, ...] = (
    "_elves_context/",
    "_elves_review/",
    "_instruction_evidence/",
    "_elves_transport/",
)

# Argv flags that embed a repo/cwd path which must point at the snapshot.
_REPO_PATH_FLAGS: frozenset[str] = frozenset(
    {
        "--cd",
        "-C",
        "--cwd",
        "--repo-root",
        "--repo",
        "--dir",
        "--project",
        "--workspace",
    }
)


@dataclass
class IsolationSpec:
    repo_root: Path
    lane_id: str
    include_instructions_as_data: bool = False
    extra_exclude_globs: tuple[str, ...] = ()
    include_untracked: bool = False
    include_paths: tuple[str, ...] = ()
    max_context_files: int = DEFAULT_CONTEXT_MAX_FILES
    max_context_bytes: int = DEFAULT_CONTEXT_MAX_BYTES
    max_context_file_bytes: int = DEFAULT_CONTEXT_MAX_FILE_BYTES
    snapshot_writable: bool = False
    credential_grants: dict[str, str] = field(default_factory=dict)
    base_env: dict[str, str] = field(default_factory=dict)
    require_fs_sandbox: bool = False
    qualified_backend: QualifiedSandboxBackend | None = None


@dataclass(frozen=True)
class QualifiedSandboxBackend:
    """A system-owned, non-writable sandbox executable selected by the host."""

    name: str
    executable: Path


@dataclass
class IsolatedLane:
    lane_id: str
    root: Path
    snapshot: Path
    home: Path
    tmp: Path
    xdg_config: Path
    xdg_cache: Path
    xdg_data: Path
    env: dict[str, str]
    tracked_file_count: int
    untracked_file_count: int = 0
    context_bytes: int = 0
    context_diagnostics: list[dict[str, str]] = field(default_factory=list)
    context_manifest_path: str | None = None
    snapshot_writable: bool = False
    instruction_data_files: list[str] = field(default_factory=list)
    sandbox_backend: str | None = None  # sandbox-exec | bwrap | none
    sandbox_executable: str | None = None
    sandbox_profile_path: str | None = None
    process_containment: str | None = None  # host-supervised | pid-namespace | none
    supervisor_executable: str | None = None
    supervision_token: str | None = None

    def cleanup(self) -> None:
        _remove_tree_strict(self.root)


@dataclass(frozen=True)
class SnapshotFileRecord:
    sha256: str
    size: int
    mode: int


@dataclass(frozen=True)
class SnapshotState:
    files: Mapping[str, SnapshotFileRecord]
    directories: frozenset[str]


def _git_tracked_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        files: list[str] = []
        for item in result.stdout.split(b"\0"):
            if not item:
                continue
            files.append(os.fsdecode(item))
        return files
    # External isolation is Git-enumerated rather than a raw filesystem walk.
    # Callers may separately opt into Git's non-ignored untracked set without
    # risking nested ignored credentials such as .aws/credentials.
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    raise ValidationIssue(
        "isolation_git_ls_files_failed",
        "Unable to list tracked files for isolation snapshot"
        + (f": {stderr}" if stderr else ""),
        path=str(repo_root),
    )


def _git_untracked_nonignored_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [os.fsdecode(item) for item in result.stdout.split(b"\0") if item]
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    raise ValidationIssue(
        "isolation_git_untracked_files_failed",
        "Unable to list non-ignored untracked files for isolation snapshot"
        + (f": {stderr}" if stderr else ""),
        path=str(repo_root),
    )


def _normalize_include_paths(repo_root: Path, paths: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_value in paths:
        raw = str(raw_value).strip()
        if not raw:
            raise ValidationIssue(
                "invalid_isolation_include_path",
                "Isolation include paths must not be empty",
            )
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve(strict=False).relative_to(repo_root)
            except (OSError, ValueError) as exc:
                raise ValidationIssue(
                    "isolation_include_path_escape",
                    f"Isolation include path is outside the repository: {raw!r}",
                    path=raw,
                ) from exc
        normalized_value = candidate.as_posix()
        while normalized_value.startswith("./"):
            normalized_value = normalized_value[2:]
        posix = PurePosixPath(normalized_value)
        if (
            not normalized_value
            or normalized_value == "."
            or posix.is_absolute()
            or ".." in posix.parts
            or normalized_value != posix.as_posix()
        ):
            raise ValidationIssue(
                "invalid_isolation_include_path",
                f"Isolation include path must name one normalized repository file: {raw!r}",
                path=raw,
            )
        if normalized_value not in normalized:
            normalized.append(normalized_value)
    return tuple(normalized)


def _git_path_is_ignored(repo_root: Path, rel: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "check-ignore", "-q", "--no-index", "--", rel],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    raise ValidationIssue(
        "isolation_git_check_ignore_failed",
        f"Unable to determine whether requested context is ignored: {rel}"
        + (f": {stderr}" if stderr else ""),
        path=str(repo_root / rel),
    )


def preflight_requested_includes(
    repo_root: Path,
    include_paths: Sequence[str],
    *,
    include_instructions_as_data: bool = False,
    extra_exclude_globs: Sequence[str] = (),
) -> tuple[str, ...]:
    """Validate host ``--include`` paths before snapshot construction or provider launch.

    Returns the normalized repository-relative paths that would be treated as
    requested context. Raises :class:`ValidationIssue` with actionable codes and
    hints so hosts can fix bad includes without paying isolation or provider cost.
    """
    if not include_paths:
        return ()
    root = repo_root.resolve()
    extra_globs = _normalize_extra_exclude_globs(extra_exclude_globs)
    tracked = set(_git_tracked_files(root))
    untracked = set(_git_untracked_nonignored_files(root))
    requested = _normalize_include_paths(root, include_paths)
    for rel in requested:
        if (
            _should_exclude(rel, extra_globs=extra_globs)
            or _is_executable_agent_config(rel)
            or _is_internal_snapshot_path(rel)
            or (_is_instruction_surface(rel) and not include_instructions_as_data)
        ):
            raise ValidationIssue(
                "isolation_requested_path_forbidden",
                f"Requested context is excluded by immutable safety policy: {rel}",
                path=str(root / rel),
                hint=(
                    "Do not --include credentials, .env* / *.env names, executable "
                    "agent config, or other policy-blocked paths. Use default "
                    "admitted snapshot context or a policy-safe source file."
                ),
            )
        if rel in tracked or rel in untracked:
            continue
        if _git_path_is_ignored(root, rel):
            raise ValidationIssue(
                "isolation_requested_path_ignored",
                f"Requested context is ignored and cannot be admitted: {rel}",
                path=str(root / rel),
                hint=(
                    "Gitignored paths fail closed before Fugu launches. Move the "
                    "note to a non-ignored path (for example a repo-root untracked "
                    "file) or drop --include and rely on the default admitted snapshot."
                ),
            )
        try:
            info = (root / rel).lstat()
        except OSError as exc:
            raise ValidationIssue(
                "isolation_requested_path_missing",
                f"Requested context file is missing or unreadable: {rel}",
                path=str(root / rel),
                hint=(
                    "Pass an existing repository-relative file path to --include, "
                    "or omit --include when the default snapshot already has the file."
                ),
            ) from exc
        if stat.S_ISDIR(info.st_mode):
            raise ValidationIssue(
                "isolation_requested_path_directory",
                f"Requested context must name one file, not a directory: {rel}",
                path=str(root / rel),
                hint="--include accepts one file path per flag, not a directory tree.",
            )
    return requested


def _normalize_extra_exclude_globs(patterns: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in patterns:
        pattern = str(raw).strip().replace("\\", "/")
        while pattern.startswith("./"):
            pattern = pattern[2:]
        parts = PurePosixPath(pattern).parts
        if not pattern or pattern.startswith("/") or ".." in parts:
            raise ValidationIssue(
                "invalid_isolation_exclude_glob",
                f"Isolation exclude glob must be a normalized relative pattern: {raw!r}",
            )
        normalized_pattern = PurePosixPath(pattern).as_posix()
        if normalized_pattern == ".":
            raise ValidationIssue(
                "invalid_isolation_exclude_glob",
                f"Isolation exclude glob may not select the repository root: {raw!r}",
            )
        normalized.append(normalized_pattern)
    return tuple(normalized)


def _matches_extra_exclude(rel: str, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatchcase(rel, pattern) or PurePosixPath(rel).match(pattern):
            return True
        if pattern.endswith("/**") and rel.startswith(pattern[:-3].rstrip("/") + "/"):
            return True
    return False


def _should_exclude(rel: str, *, extra_globs: Sequence[str] = ()) -> bool:
    parts = Path(rel).parts
    if any(part in DEFAULT_EXCLUDED_DIR_NAMES for part in parts):
        return True
    name = Path(rel).name
    if name in DEFAULT_EXCLUDED_FILE_NAMES:
        return True
    if any(fnmatch.fnmatchcase(name.lower(), pattern) for pattern in DEFAULT_EXCLUDED_FILE_GLOBS):
        return True
    if rel.startswith(".elves/") or rel.startswith(".git/"):
        return True
    if _matches_extra_exclude(rel, extra_globs):
        return True
    return False


def _is_internal_snapshot_path(rel: str) -> bool:
    return any(
        rel == prefix.rstrip("/") or rel.startswith(prefix)
        for prefix in _INTERNAL_SNAPSHOT_PREFIXES
    )


def source_path_allowed_at_original_location(
    rel: str,
    *,
    extra_exclude_globs: Sequence[str] = (),
) -> bool:
    """Return whether a tracked path may appear at its original snapshot location.

    This policy-only check deliberately does not require the current worktree
    entry to exist. Review transports use it for deletion patches, where there
    is no file left to realize in the snapshot. Snapshot creation still applies
    its regular-file, symlink, and descriptor checks before copying content.
    """
    normalized = str(rel).replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if (
        not normalized
        or normalized.startswith("/")
        or normalized != PurePosixPath(normalized).as_posix()
        or ".." in parts
    ):
        return False
    patterns = _normalize_extra_exclude_globs(extra_exclude_globs)
    return not (
        _should_exclude(normalized, extra_globs=patterns)
        or _is_executable_agent_config(normalized)
        or _is_instruction_surface(normalized)
    )


def _is_instruction_surface(rel: str) -> bool:
    rel = PurePosixPath(rel).as_posix()
    path = PurePosixPath(rel)
    if path.name in INSTRUCTION_BASENAMES:
        return True
    if any(part in INSTRUCTION_BASENAMES for part in path.parts):
        return True
    if rel in INSTRUCTION_RELATIVE_PATHS:
        return True
    if any(rel.startswith(prefix) for prefix in INSTRUCTION_RELATIVE_PREFIXES):
        return True
    return False


def _is_executable_agent_config(rel: str) -> bool:
    rel = PurePosixPath(rel).as_posix()
    path = PurePosixPath(rel)
    if path.name in EXECUTABLE_AGENT_CONFIG_NAMES:
        return True
    if any(part in PROTECTED_AGENT_CONFIG_DIR_NAMES for part in path.parts[:-1]):
        return True
    if rel in EXECUTABLE_AGENT_CONFIG_PATHS or path.parts[-2:] == (".vscode", "mcp.json"):
        return True
    return any(rel.startswith(prefix) for prefix in EXECUTABLE_AGENT_CONFIG_PREFIXES)


def _rmtree_onerror(function: Any, path: str, _exc_info: Any) -> None:
    """Make a hostile read-only tree owner-writable, then retry deletion."""
    target = Path(path)
    try:
        target.parent.chmod(0o700)
        if target.is_symlink():
            target.unlink(missing_ok=True)
            return
        target.chmod(0o700)
    except OSError:
        try:
            target.parent.chmod(0o700)
        except OSError:
            pass
    result = function(path)
    close = getattr(result, "close", None)
    if callable(close):
        close()


def _make_tree_owner_writable(root: Path) -> None:
    if root.is_symlink():
        return
    try:
        root.chmod(0o700)
    except OSError:
        pass
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        try:
            current_path.chmod(0o700)
        except OSError:
            pass
        for name in directories:
            child = current_path / name
            if not child.is_symlink():
                try:
                    child.chmod(0o700)
                except OSError:
                    pass
        for name in files:
            child = current_path / name
            if not child.is_symlink():
                try:
                    child.chmod(0o600)
                except OSError:
                    pass


def _remove_tree_strict(root: Path) -> None:
    """Remove an isolation tree or fail closed when any residue remains."""
    path = Path(root)
    if not path.exists() and not path.is_symlink():
        return
    try:
        _make_tree_owner_writable(path)
        shutil.rmtree(path, onerror=_rmtree_onerror)
    except OSError as exc:
        try:
            _make_tree_owner_writable(path)
            shutil.rmtree(path, onerror=_rmtree_onerror)
        except OSError as retry_exc:
            raise ValidationIssue(
                "isolation_cleanup_failed",
                f"Isolation cleanup failed and may have left residue: {retry_exc}",
                path=str(path),
            ) from exc
    if path.exists() or path.is_symlink():
        raise ValidationIssue(
            "isolation_cleanup_failed",
            "Isolation cleanup returned with residue still present",
            path=str(path),
        )


def _open_tracked_regular_fd(
    repo_root: Path,
    rel: str,
) -> tuple[int, os.stat_result] | None:
    """Open a tracked file beneath a repo fd without following any component."""
    posix = PurePosixPath(rel)
    if not rel or posix.is_absolute() or ".." in posix.parts:
        raise ValidationIssue(
            "isolation_tracked_path_escape",
            f"Tracked path escapes repository: {rel!r}",
            path=str(repo_root),
        )
    src = repo_root.joinpath(*posix.parts)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptors: list[int] = []
    source_fd: int | None = None
    try:
        current = os.open(repo_root, directory_flags)
        descriptors.append(current)
        for part in posix.parts[:-1]:
            current = os.open(part, directory_flags, dir_fd=current)
            descriptors.append(current)
        source_fd = os.open(posix.parts[-1], file_flags, dir_fd=current)
        info = os.fstat(source_fd)
    except FileNotFoundError:
        if source_fd is not None:
            os.close(source_fd)
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        return None
    except OSError as exc:
        if source_fd is not None:
            os.close(source_fd)
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        code = (
            "isolation_tracked_symlink"
            if exc.errno in {errno.ELOOP, errno.EMLINK}
            else "isolation_tracked_open_failed"
        )
        raise ValidationIssue(
            code,
            f"Cannot safely open tracked path {rel}: {exc}",
            path=str(src),
        ) from exc
    for descriptor in reversed(descriptors):
        os.close(descriptor)
    assert source_fd is not None
    if stat.S_ISDIR(info.st_mode):
        os.close(source_fd)
        # Gitlinks/submodules have no file body in the parent index.
        return None
    if not stat.S_ISREG(info.st_mode):
        os.close(source_fd)
        raise ValidationIssue(
            "isolation_tracked_nonregular",
            f"Tracked path is not a regular file: {rel}",
            path=str(src),
        )
    if info.st_uid != os.geteuid():
        os.close(source_fd)
        raise ValidationIssue(
            "isolation_tracked_owner",
            f"Context path is not owned by the current user: {rel}",
            path=str(src),
        )
    if info.st_nlink != 1:
        os.close(source_fd)
        raise ValidationIssue(
            "isolation_tracked_hardlink",
            f"Tracked path must have exactly one hard link: {rel}",
            path=str(src),
        )
    return source_fd, info


def _copy_tracked_regular_file(
    repo_root: Path,
    rel: str,
    destination: Path,
    *,
    max_file_bytes: int = DEFAULT_CONTEXT_MAX_FILE_BYTES,
) -> bool:
    opened = _open_tracked_regular_fd(repo_root, rel)
    if opened is None:
        return False
    source_fd, source_info = opened
    if source_info.st_size > max_file_bytes:
        os.close(source_fd)
        raise ValidationIssue(
            "isolation_context_file_too_large",
            f"Context file exceeds the {max_file_bytes}-byte per-file limit: {rel}",
            path=str(repo_root / rel),
        )
    try:
        with os.fdopen(source_fd, "rb", closefd=True) as source, destination.open("xb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            os.fchmod(target.fileno(), stat.S_IMODE(source_info.st_mode) & 0o777)
    except OSError as exc:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValidationIssue(
            "isolation_tracked_copy_failed",
            f"Cannot copy tracked path {rel} into the isolated snapshot: {exc}",
            path=str(destination),
        ) from exc
    return True


def _snapshot_file_records(
    root: Path,
    *,
    max_files: int,
    max_bytes: int,
    max_file_bytes: int,
    forbidden_values: Sequence[str] = (),
) -> SnapshotState:
    if max_files <= 0 or max_bytes <= 0 or max_file_bytes <= 0:
        raise ValidationIssue(
            "invalid_isolation_handoff_limits",
            "Isolation handoff file and byte limits must be positive",
        )
    records: dict[str, SnapshotFileRecord] = {}
    directory_paths: set[str] = set()
    total_bytes = 0
    forbidden = tuple(
        value.encode("utf-8") for value in forbidden_values if isinstance(value, str) and value
    )
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        directories.sort()
        files.sort()
        current_path = Path(current)
        for name in directories:
            directory = current_path / name
            try:
                info = directory.lstat()
            except OSError as exc:
                raise ValidationIssue(
                    "isolation_handoff_directory_unreadable",
                    f"Cannot audit isolated output directory: {directory}",
                    path=str(directory),
                ) from exc
            if directory.is_symlink() or not stat.S_ISDIR(info.st_mode):
                raise ValidationIssue(
                    "isolation_handoff_nonregular",
                    f"Isolated output contains a symlink or special directory: {directory}",
                    path=str(directory),
                )
            if info.st_uid != os.geteuid():
                raise ValidationIssue(
                    "isolation_handoff_owner",
                    f"Isolated output directory is not owned by the current user: {directory}",
                    path=str(directory),
                )
            directory_paths.add(directory.relative_to(root).as_posix())
            if len(directory_paths) > max_files:
                raise ValidationIssue(
                    "isolation_handoff_directory_limit",
                    f"Isolated output exceeds the {max_files}-directory limit",
                    path=str(root),
                )
        for name in files:
            path = current_path / name
            rel = path.relative_to(root).as_posix()
            opened = _open_tracked_regular_fd(root, rel)
            if opened is None:
                raise ValidationIssue(
                    "isolation_handoff_missing",
                    f"Isolated output disappeared during audit: {rel}",
                    path=str(path),
                )
            descriptor, info = opened
            try:
                if info.st_size > max_file_bytes:
                    raise ValidationIssue(
                        "isolation_handoff_file_too_large",
                        f"Isolated output exceeds the {max_file_bytes}-byte per-file limit: {rel}",
                        path=str(path),
                    )
                with os.fdopen(descriptor, "rb", closefd=True) as source:
                    descriptor = -1
                    data = source.read(max_file_bytes + 1)
                if len(data) != info.st_size:
                    raise ValidationIssue(
                        "isolation_handoff_file_changed",
                        f"Isolated output changed while it was audited: {rel}",
                        path=str(path),
                    )
                if any(value in data for value in forbidden):
                    raise ValidationIssue(
                        "isolation_handoff_credential",
                        f"Isolated output contains a granted credential value: {rel}",
                        path=str(path),
                    )
                records[rel] = SnapshotFileRecord(
                    sha256=hashlib.sha256(data).hexdigest(),
                    size=len(data),
                    mode=stat.S_IMODE(info.st_mode),
                )
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            if len(records) > max_files:
                raise ValidationIssue(
                    "isolation_handoff_file_limit",
                    f"Isolated output exceeds the {max_files}-file limit",
                    path=str(root),
                )
            total_bytes += info.st_size
            if total_bytes > max_bytes:
                raise ValidationIssue(
                    "isolation_handoff_byte_limit",
                    f"Isolated output exceeds the {max_bytes}-byte total limit",
                    path=str(root),
                )
    return SnapshotState(files=records, directories=frozenset(directory_paths))


def capture_snapshot_state(
    lane: IsolatedLane,
) -> SnapshotState:
    """Capture a bounded digest-only baseline before an isolated writer starts."""
    return _snapshot_file_records(
        lane.snapshot,
        max_files=DEFAULT_CONTEXT_MAX_FILES,
        max_bytes=DEFAULT_CONTEXT_MAX_BYTES,
        max_file_bytes=DEFAULT_CONTEXT_MAX_FILE_BYTES,
    )


def provider_writable_tree_usage(
    roots: Sequence[Path],
) -> tuple[int, int, tuple[str, int] | None]:
    """Audit live provider-writable trees without following any link generation.

    Temporary directories may disappear or be atomically replaced between
    enumeration and descent. Those stale generations are benign; every opened
    generation is still validated by descriptor for type and ownership.
    """

    entries = 0
    total_bytes = 0
    largest: tuple[str, int] | None = None
    expected_uid = os.geteuid()
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )

    def audit_error(exc: OSError, path: Path) -> ValidationIssue:
        return ValidationIssue(
            "fugu_runtime_monitor_failed",
            f"Cannot audit provider-writable runtime state: {exc}",
            path=str(path),
        )

    def inspect_entry(
        path: Path,
        root: Path,
        info: os.stat_result,
    ) -> None:
        nonlocal entries, total_bytes, largest
        if info.st_uid != expected_uid:
            raise ValidationIssue(
                "fugu_runtime_owner",
                "Provider-writable runtime entry is not owned by the current user",
                path=str(path),
            )
        entries += 1
        if stat.S_ISREG(info.st_mode):
            total_bytes += info.st_size
            try:
                display = path.relative_to(root).as_posix()
            except ValueError:
                display = str(path)
            candidate = (f"{root.name}/{display}", info.st_size)
            if largest is None or candidate[1] > largest[1]:
                largest = candidate
            return
        if stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return
        raise ValidationIssue(
            "fugu_runtime_type",
            "Provider-writable runtime entry has an unsupported file type",
            path=str(path),
        )

    def scan_directory(
        descriptor: int,
        *,
        root: Path,
        relative: PurePosixPath,
    ) -> None:
        try:
            with os.scandir(descriptor) as iterator:
                children = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise audit_error(exc, root.joinpath(*relative.parts)) from exc

        for child in children:
            child_relative = relative / child.name
            child_path = root.joinpath(*child_relative.parts)
            try:
                info = child.stat(follow_symlinks=False)
            except OSError as exc:
                if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
                    continue
                raise audit_error(exc, child_path) from exc
            inspect_entry(child_path, root, info)
            if not stat.S_ISDIR(info.st_mode):
                continue
            try:
                child_descriptor = os.open(
                    child.name,
                    directory_flags,
                    dir_fd=descriptor,
                )
            except OSError as exc:
                if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
                    # The enumerated directory generation was removed or
                    # replaced before descent. O_NOFOLLOW guarantees that a
                    # replacement link was not traversed.
                    continue
                raise audit_error(exc, child_path) from exc
            try:
                opened = os.fstat(child_descriptor)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or opened.st_uid != expected_uid
                ):
                    raise ValidationIssue(
                        "fugu_runtime_directory",
                        "Provider-writable runtime directory generation is unsafe",
                        path=str(child_path),
                    )
                scan_directory(
                    child_descriptor,
                    root=root,
                    relative=child_relative,
                )
            finally:
                os.close(child_descriptor)

    for raw_root in roots:
        root = Path(raw_root)
        try:
            descriptor = os.open(root, directory_flags)
        except OSError as exc:
            raise audit_error(exc, root) from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != expected_uid:
                raise ValidationIssue(
                    "fugu_runtime_directory",
                    "Provider-writable runtime root is unsafe",
                    path=str(root),
                )
            scan_directory(descriptor, root=root, relative=PurePosixPath())
        finally:
            os.close(descriptor)
    return entries, total_bytes, largest


def _handoff_path_forbidden(rel: str) -> bool:
    return (
        _is_internal_snapshot_path(rel)
        or _should_exclude(rel)
        or _is_executable_agent_config(rel)
        or _is_instruction_surface(rel)
    )


def _handoff_mode_is_safe(mode: int) -> bool:
    special_bits = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX
    return not mode & special_bits and not mode & 0o022


def export_snapshot_handoff(
    lane: IsolatedLane,
    baseline: SnapshotState,
    *,
    metadata: Mapping[str, Any] | None = None,
    forbidden_values: Sequence[str] = (),
    max_files: int = DEFAULT_HANDOFF_MAX_FILES,
    max_bytes: int = DEFAULT_HANDOFF_MAX_BYTES,
    max_file_bytes: int = DEFAULT_CONTEXT_MAX_FILE_BYTES,
) -> Path:
    """Audit isolated writes and export inert files without touching the host checkout."""
    if not lane.snapshot_writable:
        raise ValidationIssue(
            "isolation_handoff_read_only",
            "Cannot export a write handoff from a read-only isolated lane",
            path=str(lane.snapshot),
        )
    after = _snapshot_file_records(
        lane.snapshot,
        max_files=DEFAULT_CONTEXT_MAX_FILES,
        max_bytes=DEFAULT_CONTEXT_MAX_BYTES,
        max_file_bytes=max_file_bytes,
        forbidden_values=forbidden_values,
    )
    for rel in sorted(after.directories - baseline.directories):
        if _handoff_path_forbidden(rel):
            raise ValidationIssue(
                "isolation_handoff_forbidden_path",
                f"Isolated output created a protected or excluded directory: {rel}",
                path=str(lane.snapshot / rel),
            )
    changed_paths = sorted(
        rel
        for rel in set(baseline.files) | set(after.files)
        if baseline.files.get(rel) != after.files.get(rel)
    )
    if len(changed_paths) > max_files:
        raise ValidationIssue(
            "isolation_handoff_change_file_limit",
            f"Isolated handoff exceeds the {max_files}-changed-file limit",
            path=str(lane.snapshot),
        )
    changed_bytes = sum(
        after.files[rel].size for rel in changed_paths if rel in after.files
    )
    if changed_bytes > max_bytes:
        raise ValidationIssue(
            "isolation_handoff_change_byte_limit",
            f"Isolated handoff exceeds the {max_bytes}-changed-byte limit",
            path=str(lane.snapshot),
        )
    for rel in changed_paths:
        if _handoff_path_forbidden(rel):
            raise ValidationIssue(
                "isolation_handoff_forbidden_path",
                f"Isolated output changed a protected or excluded path: {rel}",
                path=str(lane.snapshot / rel),
            )
        current = after.files.get(rel)
        if current is not None and not _handoff_mode_is_safe(current.mode):
            raise ValidationIssue(
                "isolation_handoff_unsafe_mode",
                f"Isolated output has unsafe permission bits: {rel}",
                path=str(lane.snapshot / rel),
            )

    handoff_parent = Path("/tmp").resolve()
    if not handoff_parent.is_dir():
        raise ValidationIssue(
            "isolation_handoff_parent",
            "The fixed system temporary handoff directory is unavailable",
            path=str(handoff_parent),
        )
    destination = Path(
        tempfile.mkdtemp(prefix="elves-fugu-handoff-", dir=str(handoff_parent))
    ).resolve()
    try:
        destination.chmod(0o700)
        files_root = destination / "files"
        files_root.mkdir(mode=0o700)
        changes: list[dict[str, Any]] = []
        for rel in changed_paths:
            before = baseline.files.get(rel)
            current = after.files.get(rel)
            status = "added" if before is None else "deleted" if current is None else "modified"
            item: dict[str, Any] = {
                "path": rel,
                "status": status,
                "before_sha256": before.sha256 if before else None,
                "before_bytes": before.size if before else None,
                "before_mode": before.mode if before else None,
                "after_sha256": current.sha256 if current else None,
                "after_bytes": current.size if current else None,
                "after_mode": current.mode if current else None,
                "export_mode": (
                    0o700 if current is not None and current.mode & 0o111 else 0o600
                )
                if current is not None
                else None,
            }
            changes.append(item)
            if current is None:
                continue
            source = lane.snapshot.joinpath(*PurePosixPath(rel).parts)
            target = files_root.joinpath(*PurePosixPath(rel).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.parent.chmod(0o700)
            opened = _open_tracked_regular_fd(lane.snapshot, rel)
            if opened is None:
                raise ValidationIssue(
                    "isolation_handoff_missing",
                    f"Isolated output disappeared during export: {rel}",
                    path=str(source),
                )
            descriptor, info = opened
            try:
                with os.fdopen(descriptor, "rb", closefd=True) as input_file:
                    descriptor = -1
                    data = input_file.read(max_file_bytes + 1)
                if (
                    len(data) != info.st_size
                    or hashlib.sha256(data).hexdigest() != current.sha256
                    or stat.S_IMODE(info.st_mode) != current.mode
                ):
                    raise ValidationIssue(
                        "isolation_handoff_file_changed",
                        f"Isolated output changed while it was exported: {rel}",
                        path=str(source),
                    )
                with target.open("xb") as output_file:
                    output_file.write(data)
                    os.fchmod(output_file.fileno(), item["export_mode"])
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

        manifest = {
            "schema_version": 1,
            "kind": "elves-fugu-isolated-write-handoff",
            "automatically_applied": False,
            "changed_files": len(changes),
            "changed_bytes": changed_bytes,
            "metadata": dict(metadata or {}),
            "changes": changes,
        }
        manifest_path = destination / "manifest.json"
        with manifest_path.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            os.fchmod(handle.fileno(), 0o600)
        return destination
    except BaseException as original:
        try:
            _remove_tree_strict(destination)
        except ValidationIssue as cleanup_issue:
            raise cleanup_issue from original
        raise


def build_isolated_env(
    lane: IsolatedLane,
    *,
    credential_grants: Mapping[str, str] | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    grants = dict(credential_grants or {})
    validate_credential_grant_names(grants, path="credential_grants")
    env: dict[str, str] = {
        "HOME": str(lane.home.resolve()),
        "TMPDIR": str(lane.tmp.resolve()),
        "TMP": str(lane.tmp.resolve()),
        "TEMP": str(lane.tmp.resolve()),
        "XDG_CONFIG_HOME": str(lane.xdg_config.resolve()),
        "XDG_CACHE_HOME": str(lane.xdg_cache.resolve()),
        "XDG_DATA_HOME": str(lane.xdg_data.resolve()),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": (base_env or {}).get("PATH") or os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": (base_env or {}).get("LANG") or "C.UTF-8",
        "ELVES_ISOLATED_SNAPSHOT": str(lane.snapshot.resolve()),
    }
    for key, value in grants.items():
        env[str(key)] = str(value)
    if lane.supervision_token:
        # Reserved host marker: credential grants may never replace it.
        env["ELVES_ISOLATION_MARKER"] = lane.supervision_token
    return env


def create_tracked_snapshot(spec: IsolationSpec) -> IsolatedLane:
    validate_credential_grant_names(
        spec.credential_grants,
        path="IsolationSpec.credential_grants",
    )
    repo_root = Path(spec.repo_root).resolve()
    if (
        spec.max_context_files <= 0
        or spec.max_context_bytes <= 0
        or spec.max_context_file_bytes <= 0
    ):
        raise ValidationIssue(
            "invalid_isolation_context_limits",
            "Isolation context file and byte limits must be positive",
        )
    lane_digest = hashlib.sha256(str(spec.lane_id).encode("utf-8")).hexdigest()[:12]
    parent = Path(tempfile.mkdtemp(prefix=f"elves-iso-{lane_digest}-")).resolve()
    try:
        try:
            parent.chmod(0o700)
        except OSError:
            pass
        snapshot = parent / "snapshot"
        home = parent / "home"
        tmp = parent / "tmp"
        xdg_config = parent / "xdg-config"
        xdg_cache = parent / "xdg-cache"
        xdg_data = parent / "xdg-data"
        for path in (snapshot, home, tmp, xdg_config, xdg_cache, xdg_data):
            path.mkdir(parents=True, exist_ok=True)
            try:
                path.chmod(0o700)
            except OSError:
                pass

        extra_globs = _normalize_extra_exclude_globs(spec.extra_exclude_globs)
        tracked = _git_tracked_files(repo_root)
        tracked_set = set(tracked)
        untracked = (
            _git_untracked_nonignored_files(repo_root) if spec.include_untracked else []
        )
        requested = preflight_requested_includes(
            repo_root,
            spec.include_paths,
            include_instructions_as_data=spec.include_instructions_as_data,
            extra_exclude_globs=extra_globs,
        )
        requested_set = set(requested)
        for rel in requested:
            if rel in tracked_set or rel in untracked:
                continue
            # preflight_requested_includes already proved these are non-ignored,
            # non-directory files that should join the untracked candidate list.
            untracked.append(rel)
        candidates = [(rel, True) for rel in tracked]
        candidates.extend((rel, False) for rel in untracked if rel not in tracked_set)
        instruction_data: list[str] = []
        diagnostics: list[dict[str, str]] = []
        diagnostics_total = 0

        def record_diagnostic(rel: str, reason: str) -> None:
            nonlocal diagnostics_total
            diagnostics_total += 1
            if len(diagnostics) < MAX_CONTEXT_DIAGNOSTICS:
                diagnostics.append(
                    {"path": rel, "status": "excluded", "reason": reason}
                )

        count = 0
        untracked_count = 0
        copied_count = 0
        total_bytes = 0
        admitted_requested: set[str] = set()
        for rel, is_tracked in candidates:
            if _is_internal_snapshot_path(rel):
                record_diagnostic(rel, "internal_namespace")
                continue
            if _should_exclude(rel, extra_globs=extra_globs):
                record_diagnostic(rel, "policy")
                continue
            if _is_executable_agent_config(rel):
                record_diagnostic(rel, "executable_agent_config")
                continue
            if _is_instruction_surface(rel):
                if not spec.include_instructions_as_data:
                    record_diagnostic(rel, "instruction_surface")
                    continue
                inert = snapshot / "_instruction_evidence" / f"{rel.replace('/', '__')}.txt"
                inert.parent.mkdir(parents=True, exist_ok=True)
                if not _copy_tracked_regular_file(
                    repo_root,
                    rel,
                    inert,
                    max_file_bytes=spec.max_context_file_bytes,
                ):
                    if rel in requested_set:
                        raise ValidationIssue(
                            "isolation_requested_path_unavailable",
                            f"Requested context disappeared before admission: {rel}",
                            path=str(repo_root / rel),
                        )
                    continue
                inert_size = inert.stat().st_size
                total_bytes += inert_size
                copied_count += 1
                if copied_count > spec.max_context_files:
                    raise ValidationIssue(
                        "isolation_context_file_limit",
                        f"Context exceeds the {spec.max_context_files}-file limit",
                        path=str(repo_root),
                    )
                if total_bytes > spec.max_context_bytes:
                    raise ValidationIssue(
                        "isolation_context_byte_limit",
                        f"Context exceeds the {spec.max_context_bytes}-byte total limit",
                        path=str(repo_root),
                    )
                try:
                    inert.chmod(0o600)
                except OSError:
                    pass
                instruction_data.append(str(inert.relative_to(snapshot)))
                if rel in requested_set:
                    admitted_requested.add(rel)
                continue
            dest = snapshot.joinpath(*PurePosixPath(rel).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not _copy_tracked_regular_file(
                repo_root,
                rel,
                dest,
                max_file_bytes=spec.max_context_file_bytes,
            ):
                if rel in requested_set:
                    raise ValidationIssue(
                        "isolation_requested_path_unavailable",
                        f"Requested context disappeared before admission: {rel}",
                        path=str(repo_root / rel),
                    )
                continue
            total_bytes += dest.stat().st_size
            count += 1
            copied_count += 1
            if not is_tracked:
                untracked_count += 1
            if rel in requested_set:
                admitted_requested.add(rel)
            if copied_count > spec.max_context_files:
                raise ValidationIssue(
                    "isolation_context_file_limit",
                    f"Context exceeds the {spec.max_context_files}-file limit",
                    path=str(repo_root),
                )
            if total_bytes > spec.max_context_bytes:
                raise ValidationIssue(
                    "isolation_context_byte_limit",
                    f"Context exceeds the {spec.max_context_bytes}-byte total limit",
                    path=str(repo_root),
                )

        missing_requested = sorted(requested_set - admitted_requested)
        if missing_requested:
            rel = missing_requested[0]
            raise ValidationIssue(
                "isolation_requested_path_unavailable",
                f"Requested context was not admitted into the snapshot: {rel}",
                path=str(repo_root / rel),
            )

        context_dir = snapshot / "_elves_context"
        context_dir.mkdir(mode=0o700)
        context_manifest = context_dir / "manifest.json"
        context_manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "tracked_files": count - untracked_count,
                    "untracked_files": untracked_count,
                    "instruction_files": len(instruction_data),
                    "context_bytes": total_bytes,
                    "diagnostics": diagnostics,
                    "diagnostics_truncated": diagnostics_total > len(diagnostics),
                    "requested_paths": list(requested),
                    "admitted_requested_paths": sorted(admitted_requested),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        context_manifest.chmod(0o600)

        lane = IsolatedLane(
            lane_id=spec.lane_id,
            root=parent,
            snapshot=snapshot,
            home=home,
            tmp=tmp,
            xdg_config=xdg_config,
            xdg_cache=xdg_cache,
            xdg_data=xdg_data,
            env={},
            tracked_file_count=count - untracked_count,
            untracked_file_count=untracked_count,
            context_bytes=total_bytes,
            context_diagnostics=diagnostics,
            context_manifest_path=str(context_manifest.relative_to(snapshot)),
            snapshot_writable=spec.snapshot_writable,
            instruction_data_files=instruction_data,
            supervision_token=secrets.token_hex(24),
        )
        lane.env = build_isolated_env(
            lane,
            credential_grants=spec.credential_grants,
            base_env=spec.base_env,
        )
        if spec.require_fs_sandbox:
            backend, profile_path = prepare_fs_sandbox(
                lane,
                required=True,
                qualified_backend=spec.qualified_backend,
            )
            lane.sandbox_backend = backend
            lane.sandbox_profile_path = profile_path
            lane.process_containment = (
                "host-supervised" if backend == "sandbox-exec" else "pid-namespace"
            )
        else:
            lane.sandbox_backend = None
            lane.sandbox_profile_path = None
            lane.process_containment = None
        return lane
    except BaseException as original:
        try:
            _remove_tree_strict(parent)
        except ValidationIssue as cleanup_issue:
            raise cleanup_issue from original
        raise


def copy_isolated_transport_inputs(
    lane: IsolatedLane,
    *,
    packet_path: Path,
    prompt_path: Path,
) -> tuple[Path, Path]:
    """Copy host-owned packet/prompt artifacts into the readable snapshot."""
    transport = lane.snapshot / "_elves_transport"
    transport.mkdir(parents=True, exist_ok=True)
    destinations: list[Path] = []
    for source, name in ((Path(packet_path), "packet.json"), (Path(prompt_path), "prompt.txt")):
        if source.is_symlink() or not source.is_file():
            raise ValidationIssue(
                "isolation_transport_input_invalid",
                f"Isolation transport input must be a regular non-symlink file: {source}",
                path=str(source),
            )
        destination = transport / name
        shutil.copy2(source, destination, follow_symlinks=False)
        try:
            destination.chmod(0o600)
        except OSError:
            pass
        destinations.append(destination)
    return destinations[0], destinations[1]


def _qualified_system_executable(
    path: Path,
    *,
    exact_path_required: bool,
) -> Path | None:
    """Qualify a fixed system executable without consulting caller-controlled PATH."""
    candidate = Path(path)
    if not candidate.is_absolute():
        return None
    try:
        if candidate.is_symlink() and exact_path_required:
            return None
        resolved = candidate.resolve(strict=True)
        info = resolved.stat()
    except (OSError, RuntimeError):
        return None
    if exact_path_required and resolved != candidate:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        return None
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return None
    if not os.access(resolved, os.X_OK):
        return None
    return resolved


def resolve_fs_sandbox_backend() -> QualifiedSandboxBackend | None:
    """Resolve one trusted and usable sandbox backend; never trust PATH."""
    for name, candidate in _SANDBOX_BACKEND_CANDIDATES:
        executable = _qualified_system_executable(
            candidate,
            exact_path_required=True,
        )
        if executable is not None and _probe_fs_sandbox_backend(name, executable):
            return QualifiedSandboxBackend(name=name, executable=executable)
    return None


def detect_fs_sandbox_backend() -> str | None:
    """Compatibility probe returning the trusted backend's public name."""
    backend = resolve_fs_sandbox_backend()
    return backend.name if backend is not None else None


def _validate_qualified_backend(
    backend: QualifiedSandboxBackend,
) -> QualifiedSandboxBackend:
    expected = dict(_SANDBOX_BACKEND_CANDIDATES).get(backend.name)
    if expected is None or Path(backend.executable) != expected:
        raise ValidationIssue(
            "isolation_sandbox_untrusted",
            "Sandbox backend must be a fixed supported /usr/bin executable",
            path=str(backend.executable),
        )
    qualified = _qualified_system_executable(expected, exact_path_required=True)
    if qualified is None:
        raise ValidationIssue(
            "isolation_sandbox_untrusted",
            "Sandbox backend is not root-owned, executable, and non-writable",
            path=str(expected),
        )
    return QualifiedSandboxBackend(name=backend.name, executable=qualified)


def _resolve_macos_supervisor() -> Path | None:
    for candidate in _MACOS_SUPERVISOR_CANDIDATES:
        executable = _qualified_system_executable(
            candidate,
            exact_path_required=False,
        )
        if executable is not None and executable.parts[:3] in {
            ("/", "usr", "bin"),
            ("/", "bin", "ps"),
        }:
            return executable
    return None


def _sbpl_string(value: str | Path) -> str:
    """Quote one SBPL string safely, including unusual filesystem names."""
    raw = str(value)
    if "\0" in raw:
        raise ValidationIssue(
            "isolation_sandbox_profile_invalid_path",
            "NUL is not valid in a sandbox profile path",
        )
    escaped = (
        raw.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _sbpl_rule(action: str, match: str, path: str | Path) -> str:
    return f"({action} ({match} {_sbpl_string(path)}))"


@lru_cache(maxsize=4)
def _probe_fs_sandbox_backend(name: str, executable: Path) -> bool:
    """Prove that a statically qualified backend can launch and enforce policy.

    Package presence is insufficient: Linux CI and some containers install
    bubblewrap while denying the user namespaces it needs. Keep this bounded,
    independent of caller-controlled environment variables, and cached for the
    process lifetime.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="elves-sandbox-probe-") as raw_root:
            root = Path(raw_root)
            home = root / "home"
            tmp = root / "tmp"
            home.mkdir()
            tmp.mkdir()
            probe_env = {
                "HOME": str(home),
                "TMPDIR": str(tmp),
                "TMP": str(tmp),
                "TEMP": str(tmp),
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
            }
            sentinel = root / "must-not-read.txt"
            sentinel.write_text("sandbox probe\n", encoding="utf-8")
            # macOS exposes /var through /private/var; policy literals must use
            # the canonical path seen by the kernel.
            canonical_sentinel = sentinel.resolve()

            if name == "sandbox-exec":
                allow_result = subprocess.run(
                    [
                        str(executable),
                        "-p",
                        "(version 1)\n(allow default)\n",
                        "/bin/cat",
                        str(sentinel),
                    ],
                    env=probe_env,
                    capture_output=True,
                    check=False,
                    timeout=_SANDBOX_PROBE_TIMEOUT_SECONDS,
                )
                if (
                    allow_result.returncode != 0
                    or allow_result.stdout != b"sandbox probe\n"
                ):
                    return False

                deny_profile = (
                    "(version 1)\n"
                    "(allow default)\n"
                    f"(deny file-read* (literal {_sbpl_string(canonical_sentinel)}))\n"
                )
                deny_result = subprocess.run(
                    [
                        str(executable),
                        "-p",
                        deny_profile,
                        "/bin/cat",
                        str(sentinel),
                    ],
                    env=probe_env,
                    capture_output=True,
                    check=False,
                    timeout=_SANDBOX_PROBE_TIMEOUT_SECONDS,
                )
                return deny_result.returncode != 0

            if name == "bwrap":
                result = subprocess.run(
                    [
                        str(executable),
                        "--die-with-parent",
                        "--unshare-all",
                        "--share-net",
                        "--ro-bind",
                        "/usr",
                        "/usr",
                        "--ro-bind",
                        "/bin",
                        "/bin",
                        "--ro-bind-try",
                        "/lib",
                        "/lib",
                        "--ro-bind-try",
                        "/lib64",
                        "/lib64",
                        "--dev",
                        "/dev",
                        "--proc",
                        "/proc",
                        "--chdir",
                        "/",
                        "/usr/bin/test",
                        "!",
                        "-e",
                        str(canonical_sentinel),
                    ],
                    env=probe_env,
                    capture_output=True,
                    check=False,
                    timeout=_SANDBOX_PROBE_TIMEOUT_SECONDS,
                )
                return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    return False


def prepare_fs_sandbox(
    lane: IsolatedLane,
    *,
    required: bool = False,
    qualified_backend: QualifiedSandboxBackend | None = None,
) -> tuple[str | None, str | None]:
    """Create platform sandbox profile if a backend exists.

    A cwd snapshot alone is not an OS boundary against absolute paths. When no
    qualified backend is available: optional routes get (None, None) and callers
    must skip the external attempt; required routes raise.
    """
    selected = qualified_backend or resolve_fs_sandbox_backend()
    if selected is None:
        if required:
            raise ValidationIssue(
                "isolation_sandbox_unavailable",
                "Required filesystem sandbox backend not available "
                "(need sandbox-exec on macOS or bwrap on Linux)",
                path=str(lane.root),
            )
        return None, None

    selected = _validate_qualified_backend(selected)
    if not _probe_fs_sandbox_backend(selected.name, selected.executable):
        if required:
            raise ValidationIssue(
                "isolation_sandbox_unusable",
                "Required filesystem sandbox backend failed its capability probe",
                path=str(selected.executable),
            )
        return None, None
    backend = selected.name
    lane.sandbox_executable = str(selected.executable)

    if backend == "sandbox-exec":
        # Keep process/network primitives available, but make filesystem access
        # deny-by-default. Explicitly allow the isolated tree and system/runtime
        # roots; wrap_argv_with_sandbox adds the exact executable location.
        snapshot = lane.snapshot.resolve()
        lane_tmp = lane.tmp.resolve()
        lane_home = lane.home.resolve()
        xdg_config = lane.xdg_config.resolve()
        xdg_cache = lane.xdg_cache.resolve()
        xdg_data = lane.xdg_data.resolve()
        supervisor = _resolve_macos_supervisor()
        if supervisor is None:
            raise ValidationIssue(
                "isolation_supervisor_unavailable",
                "macOS descendant supervision requires a trusted system ps executable",
            )
        lane.supervisor_executable = str(supervisor)
        profile_lines = [
            "(version 1)",
            "(allow default)",
            "(deny file-read*)",
            "(deny file-write*)",
            _sbpl_rule("allow file-read*", "literal", "/"),
        ]
        # realpath(3), canonicalize(), and getcwd(3) must stat every ancestor
        # between `/` and an allowed sandbox-owned path. Grant only metadata on
        # those exact parents: omitting this makes real Codex/Grok launchers
        # unable to canonicalize HOME/CODEX_HOME, while granting file-read*
        # would expose unrelated sibling contents under the host temp tree.
        sandbox_metadata_ancestors: set[Path] = set()
        sandbox_symlink_aliases: set[Path] = set()
        lexical_sandbox_paths = (
            lane.snapshot.absolute(),
            lane.tmp.absolute(),
            lane.home.absolute(),
            lane.xdg_config.absolute(),
            lane.xdg_cache.absolute(),
            lane.xdg_data.absolute(),
        )
        for lexical in lexical_sandbox_paths:
            sandbox_symlink_aliases.update(_symlink_path_components(lexical))
        for approved in (
            snapshot,
            lane_tmp,
            lane_home,
            xdg_config,
            xdg_cache,
            xdg_data,
        ):
            sandbox_metadata_ancestors.update(
                parent for parent in approved.parents if parent != Path("/")
            )
        for ancestor in sorted(
            sandbox_metadata_ancestors | sandbox_symlink_aliases,
            key=str,
        ):
            profile_lines.append(
                _sbpl_rule("allow file-read-metadata", "literal", ancestor)
            )
        for system_root in (
            "/System",
            "/usr",
            "/bin",
            "/sbin",
            "/Library",
            "/dev",
            "/etc",
            "/private/etc",
            "/private/var/db",
        ):
            profile_lines.append(_sbpl_rule("allow file-read*", "subpath", system_root))
        # Native macOS runtimes canonicalize temp/cache/socket locations below
        # /var even when all writable state is redirected into the lane. Allow
        # traversal metadata only; host file contents remain denied.
        for metadata_root in ("/var", "/private/var"):
            profile_lines.append(
                _sbpl_rule("allow file-read-metadata", "subpath", metadata_root)
            )
        profile_lines.extend(
            [
                _sbpl_rule("allow file-write*", "subpath", "/dev"),
                _sbpl_rule("allow file-write*", "subpath", lane_tmp),
                _sbpl_rule("allow file-write*", "subpath", lane_home),
                _sbpl_rule("allow file-write*", "subpath", xdg_config),
                _sbpl_rule("allow file-write*", "subpath", xdg_cache),
                _sbpl_rule("allow file-write*", "subpath", xdg_data),
                _sbpl_rule("allow file-read*", "subpath", snapshot),
                _sbpl_rule("allow file-read*", "subpath", lane_home),
                _sbpl_rule("allow file-read*", "subpath", lane_tmp),
                ";; ELVES_EXECUTABLE_ALLOWLIST",
            ]
        )
        if lane.snapshot_writable:
            profile_lines.insert(
                -1,
                _sbpl_rule("allow file-write*", "subpath", snapshot),
            )
        profile = "\n".join(profile_lines) + "\n"
        path = lane.root / "sandbox.sb"
        path.write_text(profile, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return "sandbox-exec", str(path)

    # bwrap: bind snapshot read-only, tmp/home writable; no host home.
    return "bwrap", None


def _resolved_executable_paths(command: str, *, search_path: str | None) -> list[Path]:
    """Resolve only the selected executable and its symlink target."""
    found = shutil.which(command, path=search_path)
    executable = Path(found or command).expanduser()
    paths: list[Path] = []
    for candidate in (executable,):
        try:
            if candidate.exists() or candidate.is_symlink():
                paths.append(candidate.absolute())
            resolved = candidate.resolve(strict=True)
            if resolved not in paths:
                paths.append(resolved)
        except (OSError, RuntimeError):
            continue
    return paths


def _narrow_runtime_root(path: Path) -> Path | None:
    """Infer only a known package/runtime root from a canonical executable."""
    parts = path.parts
    markers = (
        ("pipx", "venvs"),
        ("uv", "tools"),
    )
    for first, second in markers:
        for index in range(len(parts) - 2):
            if parts[index : index + 2] == (first, second):
                return Path(*parts[: index + 3])
    if "Cellar" in parts:
        index = parts.index("Cellar")
        if len(parts) >= index + 3:
            return Path(*parts[: index + 3])
    if "Contents" in parts and "Developer" in parts:
        developer_index = parts.index("Developer")
        if developer_index > parts.index("Contents"):
            return Path(*parts[: developer_index + 1])
    if "node_modules" in parts:
        index = parts.index("node_modules")
        package_end = index + 2
        if len(parts) > index + 1 and parts[index + 1].startswith("@"):
            package_end += 1
        return Path(*parts[:package_end])
    if "hostedtoolcache" in parts and "bin" in parts:
        # GitHub Actions: /opt/hostedtoolcache/Python/<ver>/<arch>/bin/python.
        # The sibling lib/ tree is part of the interpreter runtime.
        bin_index = len(parts) - 1 - tuple(reversed(parts)).index("bin")
        return Path(*parts[:bin_index])
    standalone_marker = (".codex", "packages", "standalone", "releases")
    for index in range(len(parts) - len(standalone_marker)):
        if parts[index : index + len(standalone_marker)] == standalone_marker:
            release_index = index + len(standalone_marker)
            if len(parts) > release_index:
                # One immutable, versioned Codex distribution. The binary
                # reads adjacent package metadata and sibling launch helpers.
                return Path(*parts[: release_index + 1])
    if ".pyenv" in parts and "versions" in parts and "bin" in parts:
        bin_index = len(parts) - 1 - tuple(reversed(parts)).index("bin")
        return Path(*parts[:bin_index])
    if "uv" in parts and "python" in parts and "bin" in parts:
        # uv-managed interpreter installs:
        # .../uv/python/cpython-<ver>-<platform>/bin/python3.x. One immutable
        # versioned interpreter distribution whose sibling lib/ tree is the
        # runtime, exactly like the pyenv/asdf cases above.
        uv_index = parts.index("uv")
        if len(parts) > uv_index + 1 and parts[uv_index + 1] == "python":
            bin_index = len(parts) - 1 - tuple(reversed(parts)).index("bin")
            if bin_index > uv_index + 2:
                return Path(*parts[:bin_index])
    if ".asdf" in parts and "installs" in parts and "bin" in parts:
        bin_index = len(parts) - 1 - tuple(reversed(parts)).index("bin")
        return Path(*parts[:bin_index])
    return None


def _validated_runtime_mount(path: Path, *, executable: Path) -> Path:
    """Canonicalize a mount and reject HOME/ancestor or symlink widening."""
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValidationIssue(
            "isolation_runtime_mount_invalid",
            f"Cannot resolve runtime mount: {exc}",
            path=str(path),
        ) from exc
    if resolved != path:
        raise ValidationIssue(
            "isolation_runtime_mount_symlink",
            "Runtime mount must already be canonical; refusing a widening symlink",
            path=str(path),
        )
    home = Path.home().resolve()
    if resolved == home or resolved in home.parents:
        raise ValidationIssue(
            "isolation_runtime_mount_home",
            "Refusing to mount HOME or one of its ancestors",
            path=str(resolved),
        )
    if resolved != executable and resolved not in executable.parents:
        raise ValidationIssue(
            "isolation_runtime_mount_unrelated",
            "Runtime mount does not contain its qualified executable",
            path=str(resolved),
        )
    return resolved


def _resolve_command_executable(command: str, lane: IsolatedLane) -> Path:
    found = shutil.which(command, path=lane.env.get("PATH"))
    candidate = Path(found or command).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
        info = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise ValidationIssue(
            "launch_executable_not_found",
            f"Cannot resolve launch executable: {exc}",
            path=str(candidate),
        ) from exc
    if not stat.S_ISREG(info.st_mode) or not os.access(resolved, os.X_OK):
        raise ValidationIssue(
            "launch_executable_invalid",
            "Launch executable must be a regular executable file",
            path=str(resolved),
        )
    return resolved


def _literal_command_executable(command: str, lane: IsolatedLane) -> Path:
    found = shutil.which(command, path=lane.env.get("PATH"))
    return Path(found or command).expanduser().absolute()


def _symlink_path_components(path: Path) -> list[Path]:
    components: list[Path] = []
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor = cursor / part
        try:
            if cursor.is_symlink():
                components.append(cursor)
        except OSError:
            continue
    return components


def _shebang_interpreter(path: Path, lane: IsolatedLane) -> Path | None:
    try:
        with path.open("rb") as handle:
            first_line = handle.readline(4096)
    except OSError:
        return None
    if not first_line.startswith(b"#!"):
        return None
    try:
        words = shlex.split(first_line[2:].decode("utf-8", errors="strict").strip())
    except (UnicodeDecodeError, ValueError):
        return None
    if not words:
        return None
    interpreter = words[0]
    if Path(interpreter).name == "env":
        candidates = [word for word in words[1:] if not word.startswith("-")]
        if not candidates:
            return None
        interpreter = candidates[0]
    try:
        return _resolve_command_executable(interpreter, lane)
    except ValidationIssue:
        return None


def _bwrap_user_executable_roots(executable: Path, lane: IsolatedLane) -> list[Path]:
    system_roots = tuple(Path(path) for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"))
    roots: list[Path] = []
    pending = [executable]
    interpreter = _shebang_interpreter(executable, lane)
    if interpreter is not None and interpreter != executable:
        pending.append(interpreter)
    for qualified in pending:
        if qualified == lane.snapshot or lane.snapshot in qualified.parents:
            continue
        if any(qualified == root or root in qualified.parents for root in system_roots):
            continue
        inferred = _narrow_runtime_root(qualified)
        mount = inferred if inferred is not None else qualified
        mount = _validated_runtime_mount(mount, executable=qualified)
        if mount not in roots:
            roots.append(mount)
    return roots


def _bwrap_system_runtime_paths() -> list[Path]:
    """Bind narrowly scoped resolver/loader data; never the whole /etc or /run."""
    candidates = (
        "/etc/ld.so.cache",
        "/etc/ld.so.conf",
        "/etc/ld.so.conf.d",
        "/etc/ssl",
        "/etc/ca-certificates",
        "/etc/resolv.conf",
        "/etc/hosts",
        "/etc/nsswitch.conf",
        "/etc/passwd",
        "/etc/group",
        "/etc/localtime",
        "/etc/gai.conf",
    )
    paths: list[Path] = []
    for raw in candidates:
        path = Path(raw)
        if not (path.exists() or path.is_symlink()):
            continue
        if path not in paths:
            paths.append(path)
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved not in paths:
            paths.append(resolved)
    return paths


def _bwrap_bind_args(
    *,
    runtime_paths: Sequence[Path],
    executable_roots: Sequence[Path],
) -> list[str]:
    """Create empty destination parents, then mount only approved paths."""
    mounted_system_roots = tuple(
        Path(path) for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64")
    )
    directories: list[Path] = []
    for path in (*runtime_paths, *executable_roots):
        for parent in reversed(path.parents):
            if parent == Path("/"):
                continue
            if any(
                parent == root or root in parent.parents
                for root in mounted_system_roots
            ):
                continue
            if parent not in directories:
                directories.append(parent)
    args: list[str] = []
    for directory in directories:
        args.extend(["--dir", str(directory)])
    for path in runtime_paths:
        args.extend(["--ro-bind-try", str(path), str(path)])
    for root in executable_roots:
        args.extend(["--ro-bind", str(root), str(root)])
    return args


def _prepend_executable_dirs(lane: IsolatedLane, executables: Sequence[Path]) -> None:
    existing = [part for part in lane.env.get("PATH", "").split(os.pathsep) if part]
    prefixes: list[str] = []
    for executable in executables:
        parent = str(executable.parent)
        if parent not in prefixes and parent not in existing:
            prefixes.append(parent)
    lane.env["PATH"] = os.pathsep.join([*prefixes, *existing])


@lru_cache(maxsize=64)
def _macos_dynamic_dependencies(executables: tuple[Path, ...]) -> tuple[Path, ...]:
    """Resolve only system or recognized package-runtime Mach-O dependencies."""
    otool = _qualified_system_executable(
        Path("/usr/bin/otool"),
        exact_path_required=True,
    )
    if otool is None:
        return []
    dependencies: list[Path] = []
    pending = list(executables)
    inspected: set[Path] = set()
    while pending and len(inspected) < 64:
        executable = pending.pop(0)
        if executable in inspected:
            continue
        inspected.add(executable)
        result = subprocess.run(
            [str(otool), "-L", str(executable)],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines()[1:]:
            raw = line.strip().split(" (", 1)[0]
            if not raw.startswith("/"):
                continue
            literal_dependency = Path(raw)
            try:
                dependency = literal_dependency.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            system_roots = tuple(
                Path(path) for path in ("/System", "/usr", "/bin", "/sbin", "/Library")
            )
            is_system = any(
                dependency == root or root in dependency.parents for root in system_roots
            )
            if not is_system:
                inferred = _narrow_runtime_root(dependency)
                if inferred is None:
                    # A Mach-O load command is attacker-controlled input. Never
                    # turn an arbitrary absolute path into a sandbox read grant.
                    continue
                try:
                    _validated_runtime_mount(inferred, executable=dependency)
                except ValidationIssue:
                    continue
            if literal_dependency != dependency and literal_dependency not in dependencies:
                dependencies.append(literal_dependency)
            if dependency not in dependencies:
                dependencies.append(dependency)
                pending.append(dependency)
    return tuple(dependencies)


@lru_cache(maxsize=16)
def _macos_xcrun_tool(name: str) -> Path | None:
    xcrun = _qualified_system_executable(
        Path("/usr/bin/xcrun"),
        exact_path_required=True,
    )
    if xcrun is None:
        return None
    result = subprocess.run(
        [str(xcrun), "--find", name],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw.startswith("/"):
        return None
    try:
        executable = Path(raw).resolve(strict=True)
        info = executable.stat()
    except (OSError, RuntimeError):
        return None
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not os.access(executable, os.X_OK)
    ):
        return None
    return executable


def _macos_executable_access(
    executable: Path,
    lane: IsolatedLane,
    *,
    literal_executable: Path,
) -> tuple[list[Path], list[Path]]:
    """Return exact executable files and narrow runtime roots for SBPL."""
    system_roots = tuple(Path(path) for path in ("/System", "/usr", "/bin", "/sbin", "/Library"))
    exact_files: list[Path] = [
        *dict.fromkeys(
            [literal_executable, *_symlink_path_components(literal_executable)]
        )
    ]
    runtime_roots: list[Path] = []
    executables = [executable]
    interpreter = _shebang_interpreter(executable, lane)
    if interpreter is not None and interpreter not in executables:
        executables.append(interpreter)
    for child_name in _MACOS_CHILD_TOOL_NAMES:
        try:
            literal_child = _literal_command_executable(child_name, lane)
            child = _resolve_command_executable(child_name, lane)
        except ValidationIssue:
            continue
        for alias in (literal_child, *_symlink_path_components(literal_child)):
            if alias not in exact_files:
                exact_files.append(alias)
        if child not in executables:
            executables.append(child)
        xcrun_child = _macos_xcrun_tool(child_name)
        if xcrun_child is not None and xcrun_child not in executables:
            executables.append(xcrun_child)
    _prepend_executable_dirs(lane, executables)
    all_runtime_files = [
        *executables,
        *_macos_dynamic_dependencies(tuple(executables)),
    ]
    for qualified in all_runtime_files:
        if qualified == lane.snapshot or lane.snapshot in qualified.parents:
            continue
        try:
            canonical = qualified.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if canonical != qualified:
            # A load-command alias is needed only as an exact traversal/file
            # allowance. Never infer a broad runtime root from attacker-chosen
            # lexical components such as `.../Cellar/...` in that alias.
            for alias in (qualified, *_symlink_path_components(qualified)):
                if alias not in exact_files:
                    exact_files.append(alias)
            continue
        if any(qualified == root or root in qualified.parents for root in system_roots):
            continue
        inferred = _narrow_runtime_root(qualified)
        if inferred is None:
            if qualified not in exact_files:
                exact_files.append(qualified)
            continue
        runtime = _validated_runtime_mount(inferred, executable=qualified)
        if runtime not in runtime_roots:
            runtime_roots.append(runtime)
    return exact_files, runtime_roots


def wrap_argv_with_sandbox(
    argv: Sequence[str],
    lane: IsolatedLane,
    *,
    mount_proc: bool = True,
) -> list[str]:
    """Prefix argv with sandbox backend when configured.

    Credential-bearing processes may set ``mount_proc=False`` so their
    model-directed descendants cannot inspect the parent environment through a
    fresh procfs. The default remains enabled for existing supervised routes
    that require process discovery inside the namespace.
    """
    cmd = list(argv)
    if not cmd:
        raise ValidationIssue("empty_command", "empty command")
    literal_executable = _literal_command_executable(cmd[0], lane)
    qualified_executable = _resolve_command_executable(cmd[0], lane)
    cmd[0] = str(qualified_executable)
    if lane.sandbox_backend == "sandbox-exec" and lane.sandbox_profile_path:
        if not lane.sandbox_executable:
            raise ValidationIssue(
                "isolation_sandbox_unqualified",
                "sandbox-exec launch is missing its qualified absolute executable",
            )
        profile_path = Path(lane.sandbox_profile_path)
        executable_rules: list[str] = []
        exact_files, runtime_roots = _macos_executable_access(
            qualified_executable,
            lane,
            literal_executable=literal_executable,
        )
        for candidate in sorted(exact_files, key=str):
            executable_rules.append(_sbpl_rule("allow file-read*", "literal", candidate))
        for runtime in sorted(runtime_roots, key=str):
            executable_rules.append(_sbpl_rule("allow file-read*", "subpath", runtime))
        # Deep allowlisted Homebrew/user runtimes still need metadata-only
        # traversal of their ancestors for realpath(3). Never grant ancestor
        # contents or blanket /opt/HOME reads.
        metadata_ancestors: set[Path] = set()
        for approved in (*exact_files, *runtime_roots):
            metadata_ancestors.update(
                parent for parent in approved.parents if parent != Path("/")
            )
        for ancestor in sorted(metadata_ancestors, key=str):
            executable_rules.append(
                _sbpl_rule("allow file-read-metadata", "literal", ancestor)
            )
        try:
            profile = profile_path.read_text(encoding="utf-8")
            marker = ";; ELVES_EXECUTABLE_ALLOWLIST"
            profile = profile.replace(marker, "\n".join(executable_rules) + "\n" + marker)
            profile_path.write_text(profile, encoding="utf-8")
        except OSError as exc:
            raise ValidationIssue(
                "isolation_sandbox_profile_update_failed",
                f"Cannot bind executable into sandbox profile: {exc}",
                path=str(profile_path),
            ) from exc
        return [lane.sandbox_executable, "-f", lane.sandbox_profile_path, *cmd]
    if lane.sandbox_backend == "bwrap":
        if not lane.sandbox_executable:
            raise ValidationIssue(
                "isolation_sandbox_unqualified",
                "bwrap launch is missing its qualified absolute executable",
            )
        runtime_paths = _bwrap_system_runtime_paths()
        interpreter = _shebang_interpreter(qualified_executable, lane)
        if interpreter is not None:
            _prepend_executable_dirs(lane, [interpreter])
        child_executables: list[Path] = []
        for child_name in _SANDBOX_CHILD_TOOL_NAMES:
            try:
                child = _resolve_command_executable(child_name, lane)
            except ValidationIssue:
                continue
            if child not in child_executables:
                child_executables.append(child)
        _prepend_executable_dirs(lane, child_executables)
        executable_roots = _bwrap_user_executable_roots(qualified_executable, lane)
        for child in child_executables:
            for root in _bwrap_user_executable_roots(child, lane):
                if root not in executable_roots:
                    executable_roots.append(root)
        return [
            lane.sandbox_executable,
            "--die-with-parent",
            "--unshare-all",
            "--share-net",
            "--bind" if lane.snapshot_writable else "--ro-bind",
            str(lane.snapshot),
            str(lane.snapshot),
            "--bind",
            str(lane.tmp),
            str(lane.tmp),
            "--bind",
            str(lane.home),
            str(lane.home),
            "--bind",
            str(lane.xdg_config),
            str(lane.xdg_config),
            "--bind",
            str(lane.xdg_cache),
            str(lane.xdg_cache),
            "--bind",
            str(lane.xdg_data),
            str(lane.xdg_data),
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind-try",
            "/lib",
            "/lib",
            "--ro-bind-try",
            "/lib64",
            "/lib64",
            *_bwrap_bind_args(
                runtime_paths=runtime_paths,
                executable_roots=executable_roots,
            ),
            "--dev",
            "/dev",
            *(["--proc", "/proc"] if mount_proc else []),
            "--chdir",
            str(lane.snapshot),
            *cmd,
        ]
    return cmd


def rewrite_argv_repo_paths(
    argv: Sequence[str],
    *,
    original_repo: Path,
    snapshot: Path,
) -> list[str]:
    """Rewrite --cd/--cwd/--repo-root and absolute original-repo paths to the snapshot.

    Must run after the snapshot exists and before launch. Ensures built-in adapters
    like Codex ``--cd`` point at the disposable snapshot, not the host checkout.
    """
    orig = Path(original_repo).resolve()
    snap = Path(snapshot).resolve()
    out: list[str] = []
    i = 0
    tokens = list(argv)
    while i < len(tokens):
        tok = tokens[i]
        # --flag=value form
        if "=" in tok and tok.startswith("-"):
            flag, val = tok.split("=", 1)
            if flag in _REPO_PATH_FLAGS:
                out.append(f"{flag}={_map_path(val, orig, snap)}")
            else:
                out.append(tok)
            i += 1
            continue
        if tok in _REPO_PATH_FLAGS and i + 1 < len(tokens):
            out.append(tok)
            out.append(_map_path(tokens[i + 1], orig, snap))
            i += 2
            continue
        if tok in {".", "./"} or _absolute_path_under_repo(tok, orig):
            out.append(_map_path(tok, orig, snap))
        else:
            out.append(tok)
        i += 1
    return out


def _absolute_path_under_repo(value: str, repo: Path) -> bool:
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            return False
        resolved = path.resolve()
        return resolved == repo or repo in resolved.parents
    except (OSError, RuntimeError, ValueError):
        return False


def _map_path(value: str, original_repo: Path, snapshot: Path) -> str:
    try:
        path = Path(value).expanduser()
        if value in {".", "./"}:
            return str(snapshot)
        if path.is_absolute():
            resolved = path.resolve()
            orig = original_repo.resolve()
            if resolved == orig:
                return str(snapshot)
            if orig in resolved.parents or str(resolved).startswith(str(orig) + os.sep):
                rel = resolved.relative_to(orig)
                return str(snapshot / rel)
            return value
        # relative path — resolve against snapshot
        return str((snapshot / path).resolve())
    except (OSError, RuntimeError, ValueError):
        return value


@contextmanager
def isolated_lane(spec: IsolationSpec) -> Iterator[IsolatedLane]:
    lane = create_tracked_snapshot(spec)
    try:
        yield lane
    finally:
        lane.cleanup()


def implement_min_env(
    *,
    adapter: str,
    worktree: Path,
    credential_grants: Mapping[str, str] | None = None,
    home: Path | None = None,
    tmp: Path | None = None,
) -> dict[str, str]:
    grants = dict(credential_grants or {})
    validate_credential_grant_names(grants, path="credential_grants")
    home_path = home or Path(tempfile.mkdtemp(prefix="elves-impl-home-"))
    tmp_path = tmp or Path(tempfile.mkdtemp(prefix="elves-impl-tmp-"))
    for path in (home_path, tmp_path):
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError:
            pass
    env = {
        "HOME": str(home_path),
        "TMPDIR": str(tmp_path),
        "TMP": str(tmp_path),
        "TEMP": str(tmp_path),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "ELVES_IMPLEMENT_ADAPTER": adapter,
        "ELVES_IMPLEMENT_WORKTREE": str(Path(worktree).resolve()),
    }
    for key, value in grants.items():
        env[str(key)] = str(value)
    return env


@contextmanager
def _managed_implement_env(
    *,
    adapter: str,
    worktree: Path,
    credential_grants: Mapping[str, str] | None = None,
    home: Path | None = None,
    tmp: Path | None = None,
) -> Iterator[dict[str, str]]:
    """Yield a minimal env and remove only directories allocated by this scope.

    ``implement_min_env`` remains the compatibility constructor.  This scoped
    wrapper gives launch/gate callers explicit ownership semantics: omitted
    HOME/TMP paths are temporary and cleaned on every exit, while caller-owned
    paths are never registered with the cleanup stack.
    """
    with ExitStack() as stack:
        home_path = Path(home) if home is not None else Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="elves-impl-home-"))
        )
        tmp_path = Path(tmp) if tmp is not None else Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="elves-impl-tmp-"))
        )
        yield implement_min_env(
            adapter=adapter,
            worktree=worktree,
            credential_grants=credential_grants,
            home=home_path,
            tmp=tmp_path,
        )


def assert_no_host_secrets(env: Mapping[str, str], *, forbidden_keys: Sequence[str]) -> list[str]:
    return [key for key in forbidden_keys if key in env]
