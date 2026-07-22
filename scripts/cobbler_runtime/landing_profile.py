"""Deterministic evaluation for tracked project landing profiles.

Schema v1 is deliberately declarative.  Profiles select changed paths and emit
post-merge checklist items; they never supply executable content.  The thin
``scripts/landing_profile.py`` CLI delegates to this module.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


PROFILE_RELATIVE_PATH = Path(".elves/landing-profile.json")
MAX_PROFILE_BYTES = 64 * 1024
MAX_CHECKS = 64
MAX_PATTERNS_PER_CHECK = 64
MAX_STRING_CHARS = 512
MAX_JSON_DEPTH = 32
MAX_CHANGED_PATHS = 10_000
MAX_GIT_OUTPUT_BYTES = 1024 * 1024
GIT_TIMEOUT_SECONDS = 30
PROFILE_SCHEMA_VERSION = 1

_CHECK_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_EXACT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_EXECUTABLE_PROFILE_KEYS = frozenset(
    {"argv", "command", "cwd", "env", "executable", "shell", "timeout_seconds"}
)


@dataclass(frozen=True)
class ProfileDiagnostic:
    """A stable, repository-path-independent profile diagnostic."""

    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileLoadResult:
    """Result of the descriptor-bound profile loading boundary."""

    status: Literal["missing", "loaded", "invalid"]
    profile: dict[str, Any] | None = None
    content_sha256: str | None = None
    size_bytes: int = 0
    diagnostic: ProfileDiagnostic | None = None

    @property
    def ok(self) -> bool:
        return self.status != "invalid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "profile": self.profile,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "diagnostic": (
                self.diagnostic.to_dict() if self.diagnostic is not None else None
            ),
        }


class _DuplicateKeyError(ValueError):
    pass


def _invalid(code: str, message: str, *, size_bytes: int = 0) -> ProfileLoadResult:
    return ProfileLoadResult(
        status="invalid",
        size_bytes=size_bytes,
        diagnostic=ProfileDiagnostic(code=code, message=message),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _json_depth_within_bound(value: Any) -> bool:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            return False
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return True


def _read_bounded_profile(
    path: Path,
    before: os.stat_result,
    parent_before: os.stat_result,
) -> bytes | ProfileLoadResult:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    supports_dir_fd = getattr(os, "supports_dir_fd", frozenset())
    if (
        not isinstance(nofollow, int)
        or not isinstance(directory, int)
        or not nofollow
        or not directory
        or os.open not in supports_dir_fd
    ):
        return _invalid(
            "profile_secure_open_unsupported",
            "Landing profile secure no-follow opening is unsupported on this platform.",
        )

    common_flags = getattr(os, "O_CLOEXEC", 0) | nofollow
    parent_flags = os.O_RDONLY | common_flags | directory
    parent_descriptor: int | None = None
    descriptor: int | None = None
    try:
        parent_descriptor = os.open(path.parent, parent_flags)
        opened_parent = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(opened_parent.st_mode)
            or (opened_parent.st_dev, opened_parent.st_ino)
            != (parent_before.st_dev, parent_before.st_ino)
        ):
            os.close(parent_descriptor)
            parent_descriptor = None
            return _invalid(
                "profile_parent_changed_during_open",
                "Landing profile directory changed while it was being opened.",
            )
        descriptor = os.open(
            path.name,
            os.O_RDONLY | common_flags,
            dir_fd=parent_descriptor,
        )
    except (TypeError, NotImplementedError):
        if parent_descriptor is not None:
            os.close(parent_descriptor)
            parent_descriptor = None
        return _invalid(
            "profile_secure_open_unsupported",
            "Landing profile secure no-follow opening is unsupported on this platform.",
        )
    except OSError as exc:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
            parent_descriptor = None
        unsupported_errors = {
            errno.EINVAL,
            errno.ENOSYS,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if exc.errno in unsupported_errors:
            return _invalid(
                "profile_secure_open_unsupported",
                "Landing profile secure no-follow opening is unsupported on this platform.",
            )
        return _invalid(
            "profile_open_failed",
            "Landing profile could not be opened as a regular non-symlink file.",
        )

    try:
        assert descriptor is not None
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            return _invalid(
                "profile_not_regular",
                "Landing profile must be a regular file.",
            )
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            return _invalid(
                "profile_changed_during_open",
                "Landing profile changed while it was being opened.",
            )
        if opened.st_size > MAX_PROFILE_BYTES:
            return _invalid(
                "profile_too_large",
                f"Landing profile exceeds the {MAX_PROFILE_BYTES}-byte limit.",
                size_bytes=opened.st_size,
            )

        chunks: list[bytes] = []
        remaining = MAX_PROFILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 16 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > MAX_PROFILE_BYTES:
            return _invalid(
                "profile_too_large",
                f"Landing profile exceeds the {MAX_PROFILE_BYTES}-byte limit.",
                size_bytes=len(payload),
            )

        after = os.fstat(descriptor)
        identity_before = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if identity_after != identity_before or len(payload) != after.st_size:
            return _invalid(
                "profile_changed_during_read",
                "Landing profile changed while it was being read.",
                size_bytes=len(payload),
            )
        return payload
    except OSError:
        return _invalid(
            "profile_read_failed",
            "Landing profile could not be read safely.",
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def load_landing_profile(repo_root: Path) -> ProfileLoadResult:
    """Load the fixed landing-profile path without following symlinks.

    This function validates only the filesystem and JSON boundary. Schema-v1
    validation is a separate pure step so callers can distinguish missing,
    unsafe/malformed, and syntactically loaded profiles deterministically.
    """

    root = Path(repo_root)
    profile_parent = root / PROFILE_RELATIVE_PATH.parent
    profile_path = root / PROFILE_RELATIVE_PATH

    try:
        parent_info = profile_parent.lstat()
    except FileNotFoundError:
        return ProfileLoadResult(status="missing")
    except OSError:
        return _invalid(
            "profile_parent_unreadable",
            "Landing profile directory could not be inspected safely.",
        )
    if stat.S_ISLNK(parent_info.st_mode):
        return _invalid(
            "profile_parent_symlink",
            "Landing profile directory must not be a symlink.",
        )
    if not stat.S_ISDIR(parent_info.st_mode):
        return _invalid(
            "profile_parent_not_directory",
            "Landing profile parent must be a directory.",
        )

    try:
        profile_info = profile_path.lstat()
    except FileNotFoundError:
        return ProfileLoadResult(status="missing")
    except OSError:
        return _invalid(
            "profile_unreadable",
            "Landing profile could not be inspected safely.",
        )
    if stat.S_ISLNK(profile_info.st_mode):
        return _invalid(
            "profile_symlink",
            "Landing profile must not be a symlink.",
        )
    if not stat.S_ISREG(profile_info.st_mode):
        return _invalid(
            "profile_not_regular",
            "Landing profile must be a regular file.",
        )
    if profile_info.st_size > MAX_PROFILE_BYTES:
        return _invalid(
            "profile_too_large",
            f"Landing profile exceeds the {MAX_PROFILE_BYTES}-byte limit.",
            size_bytes=profile_info.st_size,
        )

    payload = _read_bounded_profile(profile_path, profile_info, parent_info)
    if isinstance(payload, ProfileLoadResult):
        return payload
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _invalid(
            "profile_invalid_utf8",
            "Landing profile must be valid UTF-8.",
            size_bytes=len(payload),
        )
    try:
        parsed = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError:
        return _invalid(
            "profile_duplicate_key",
            "Landing profile contains a duplicate JSON key.",
            size_bytes=len(payload),
        )
    except (json.JSONDecodeError, RecursionError, ValueError):
        return _invalid(
            "profile_invalid_json",
            "Landing profile must contain valid JSON.",
            size_bytes=len(payload),
        )
    if not isinstance(parsed, dict):
        return _invalid(
            "profile_root_not_object",
            "Landing profile JSON root must be an object.",
            size_bytes=len(payload),
        )
    if not _json_depth_within_bound(parsed):
        return _invalid(
            "profile_json_too_deep",
            f"Landing profile exceeds the maximum JSON depth of {MAX_JSON_DEPTH}.",
            size_bytes=len(payload),
        )

    return ProfileLoadResult(
        status="loaded",
        profile=parsed,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


@dataclass(frozen=True)
class ProfileCondition:
    kind: Literal["always", "any_path_glob"]
    patterns: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.patterns:
            payload["patterns"] = list(self.patterns)
        return payload


@dataclass(frozen=True)
class ProfileCheck:
    id: str
    kind: Literal["path_touched", "post_merge_checklist"]
    condition: ProfileCondition
    severity: Literal["blocking", "advisory"] | None = None
    paths: tuple[str, ...] = ()
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "when": self.condition.to_dict(),
        }
        if self.severity is not None:
            payload["severity"] = self.severity
        if self.paths:
            payload["paths"] = list(self.paths)
        if self.description is not None:
            payload["description"] = self.description
        return payload


@dataclass(frozen=True)
class ValidatedProfile:
    schema_version: int
    checks: tuple[ProfileCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class CheckOutcome:
    id: str
    kind: str
    status: Literal["passed", "failed", "skipped", "applicable"]
    severity: str | None = None
    code: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
        }
        if self.severity is not None:
            payload["severity"] = self.severity
        if self.code is not None:
            payload["code"] = self.code
        if self.message is not None:
            payload["message"] = self.message
        return payload


@dataclass(frozen=True)
class ProjectLandingResult:
    status: Literal["missing", "invalid", "passed", "failed"]
    green: bool
    profile_present: bool
    head: str | None = None
    base_commit: str | None = None
    merge_base: str | None = None
    profile_content_sha256: str | None = None
    digest: str | None = None
    changed_paths: tuple[str, ...] = ()
    checks: tuple[CheckOutcome, ...] = ()
    diagnostics: tuple[ProfileDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "status": self.status,
            "green": self.green,
            "profile_present": self.profile_present,
            "head": self.head,
            "base_commit": self.base_commit,
            "merge_base": self.merge_base,
            "profile_content_sha256": self.profile_content_sha256,
            "digest": self.digest,
            "changed_paths": list(self.changed_paths),
            "checks": [check.to_dict() for check in self.checks],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


def _schema_diagnostic(code: str, message: str) -> tuple[ProfileDiagnostic, ...]:
    return (ProfileDiagnostic(code=code, message=message),)


def _safe_string(value: Any, *, label: str) -> tuple[str | None, ProfileDiagnostic | None]:
    if not isinstance(value, str) or not value:
        return None, ProfileDiagnostic(
            "profile_schema_invalid",
            f"{label} must be a non-empty string.",
        )
    if len(value) > MAX_STRING_CHARS:
        return None, ProfileDiagnostic(
            "profile_string_too_long",
            f"{label} exceeds the {MAX_STRING_CHARS}-character limit.",
        )
    if any(ord(char) < 32 and char not in "\t" for char in value):
        return None, ProfileDiagnostic(
            "profile_string_control_character",
            f"{label} contains a forbidden control character.",
        )
    return value, None


def _safe_glob(value: Any, *, label: str) -> tuple[str | None, ProfileDiagnostic | None]:
    pattern, issue = _safe_string(value, label=label)
    if issue is not None or pattern is None:
        return None, issue
    if (
        pattern.startswith(("/", "~"))
        or "\\" in pattern
        or any(part == ".." for part in pattern.split("/"))
    ):
        return None, ProfileDiagnostic(
            "profile_path_unsafe",
            f"{label} must be a repository-relative forward-slash glob without '..'.",
        )
    return pattern, None


def _parse_string_list(
    value: Any,
    *,
    label: str,
    glob: bool = False,
) -> tuple[tuple[str, ...] | None, ProfileDiagnostic | None]:
    if not isinstance(value, list) or not value:
        return None, ProfileDiagnostic(
            "profile_schema_invalid",
            f"{label} must be a non-empty array.",
        )
    if len(value) > MAX_PATTERNS_PER_CHECK:
        return None, ProfileDiagnostic(
            "profile_array_too_large",
            f"{label} exceeds the {MAX_PATTERNS_PER_CHECK}-item limit.",
        )
    parsed: list[str] = []
    for index, item in enumerate(value):
        parser = _safe_glob if glob else _safe_string
        text, issue = parser(item, label=f"{label}[{index}]")
        if issue is not None or text is None:
            return None, issue
        parsed.append(text)
    return tuple(parsed), None


def _parse_condition(
    value: Any,
    *,
    label: str,
) -> tuple[ProfileCondition | None, ProfileDiagnostic | None]:
    if not isinstance(value, dict):
        return None, ProfileDiagnostic(
            "profile_schema_invalid",
            f"{label} must be an object.",
        )
    kind = value.get("kind")
    if kind == "always":
        if set(value) != {"kind"}:
            return None, ProfileDiagnostic(
                "profile_unsupported_key",
                f"{label} kind 'always' supports only the 'kind' key.",
            )
        return ProfileCondition(kind="always"), None
    if kind == "any_path_glob":
        if set(value) != {"kind", "patterns"}:
            return None, ProfileDiagnostic(
                "profile_unsupported_key",
                f"{label} kind 'any_path_glob' supports only 'kind' and 'patterns'.",
            )
        patterns, issue = _parse_string_list(
            value.get("patterns"),
            label=f"{label}.patterns",
            glob=True,
        )
        if issue is not None or patterns is None:
            return None, issue
        return ProfileCondition(kind="any_path_glob", patterns=patterns), None
    return None, ProfileDiagnostic(
        "profile_condition_unsupported",
        f"{label}.kind must be 'always' or 'any_path_glob'.",
    )


def _parse_check(
    value: Any,
    *,
    index: int,
) -> tuple[ProfileCheck | None, ProfileDiagnostic | None]:
    label = f"checks[{index}]"
    if not isinstance(value, dict):
        return None, ProfileDiagnostic(
            "profile_schema_invalid",
            f"{label} must be an object.",
        )
    kind = value.get("kind")
    if kind == "command" or _EXECUTABLE_PROFILE_KEYS.intersection(value):
        return None, ProfileDiagnostic(
            "profile_executable_check_unsupported",
            "Landing profile schema v1 does not support executable checks.",
        )
    check_id, issue = _safe_string(value.get("id"), label=f"{label}.id")
    if issue is not None or check_id is None:
        return None, issue
    if _CHECK_ID_RE.fullmatch(check_id) is None:
        return None, ProfileDiagnostic(
            "profile_check_id_invalid",
            f"{label}.id must match {_CHECK_ID_RE.pattern!r}.",
        )
    if kind not in {"path_touched", "post_merge_checklist"}:
        return None, ProfileDiagnostic(
            "profile_check_kind_unsupported",
            f"{label}.kind is unsupported.",
        )
    condition, issue = _parse_condition(value.get("when"), label=f"{label}.when")
    if issue is not None or condition is None:
        return None, issue

    if kind == "path_touched":
        allowed = {"id", "kind", "severity", "when", "paths"}
        if set(value) - allowed:
            return None, ProfileDiagnostic(
                "profile_unsupported_key",
                f"{label} contains unsupported keys.",
            )
        severity = value.get("severity")
        if severity not in {"blocking", "advisory"}:
            return None, ProfileDiagnostic(
                "profile_severity_invalid",
                f"{label}.severity must be 'blocking' or 'advisory'.",
            )
        paths, issue = _parse_string_list(
            value.get("paths"),
            label=f"{label}.paths",
            glob=True,
        )
        if issue is not None or paths is None:
            return None, issue
        return (
            ProfileCheck(
                id=check_id,
                kind="path_touched",
                condition=condition,
                severity=severity,
                paths=paths,
            ),
            None,
        )

    allowed = {"id", "kind", "when", "description"}
    if set(value) - allowed:
        return None, ProfileDiagnostic(
            "profile_unsupported_key",
            f"{label} contains unsupported keys.",
        )
    description, issue = _safe_string(
        value.get("description"), label=f"{label}.description"
    )
    if issue is not None or description is None:
        return None, issue
    return (
        ProfileCheck(
            id=check_id,
            kind="post_merge_checklist",
            condition=condition,
            description=description,
        ),
        None,
    )


def validate_landing_profile(
    profile: Mapping[str, Any],
) -> tuple[ValidatedProfile | None, tuple[ProfileDiagnostic, ...]]:
    """Validate the deliberately small, extension-hostile schema v1."""

    if set(profile) != {"schema_version", "checks"}:
        return None, _schema_diagnostic(
            "profile_unsupported_key",
            "Landing profile top-level keys are invalid.",
        )
    raw_schema_version = profile.get("schema_version")
    if (
        isinstance(raw_schema_version, bool)
        or not isinstance(raw_schema_version, int)
        or raw_schema_version != PROFILE_SCHEMA_VERSION
    ):
        return None, _schema_diagnostic(
            "profile_schema_version_unsupported",
            f"Landing profile schema_version must be {PROFILE_SCHEMA_VERSION}.",
        )
    raw_checks = profile.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        return None, _schema_diagnostic(
            "profile_schema_invalid",
            "Landing profile checks must be a non-empty array.",
        )
    if len(raw_checks) > MAX_CHECKS:
        return None, _schema_diagnostic(
            "profile_checks_too_large",
            f"Landing profile exceeds the {MAX_CHECKS}-check limit.",
        )
    checks: list[ProfileCheck] = []
    seen: set[str] = set()
    for index, raw_check in enumerate(raw_checks):
        check, issue = _parse_check(raw_check, index=index)
        if issue is not None or check is None:
            return None, (issue,) if issue is not None else ()
        if check.id in seen:
            return None, _schema_diagnostic(
                "profile_check_id_duplicate",
                f"Landing profile check id {check.id!r} is duplicated.",
            )
        seen.add(check.id)
        checks.append(check)
    return ValidatedProfile(PROFILE_SCHEMA_VERSION, tuple(checks)), ()


def _glob_regex(pattern: str) -> re.Pattern[str]:
    pieces = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    pieces.append("(?:.*/)?")
                    index += 1
                else:
                    pieces.append(".*")
                continue
            pieces.append("[^/]*")
        elif char == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(char))
        index += 1
    pieces.append("$")
    return re.compile("".join(pieces))


def path_matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(_glob_regex(pattern).fullmatch(path) is not None for pattern in patterns)


@dataclass(frozen=True)
class _BoundedGitResult:
    returncode: int
    output: bytes
    output_truncated: bool


def _kill_fixed_git(process: subprocess.Popen[bytes]) -> None:
    """Best-effort cross-platform cleanup for one fixed-argv local Git call."""

    try:
        process.kill()
    except OSError:
        pass


def _run_git(
    repo_root: Path,
    *args: str,
    output_limit: int = MAX_GIT_OUTPUT_BYTES,
) -> _BoundedGitResult:
    """Run an internal fixed-argv local Git identity query with bounded output."""

    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    try:
        process = subprocess.Popen(
            ["git", "-c", "credential.helper=", *args],
            cwd=str(repo_root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
        )
    except OSError as exc:
        message = f"git launch failed: {type(exc).__name__}".encode("utf-8")
        return _BoundedGitResult(127, message, False)

    captured = bytearray()
    total_bytes = 0

    def drain() -> None:
        nonlocal total_bytes
        assert process.stdout is not None
        while True:
            try:
                chunk = process.stdout.read(8192)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            total_bytes += len(chunk)
            remaining = output_limit - len(captured)
            if remaining > 0:
                captured.extend(chunk[:remaining])

    reader = threading.Thread(target=drain, name="landing-profile-fixed-git", daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=GIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_fixed_git(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    reader.join(timeout=5)
    if reader.is_alive():
        _kill_fixed_git(process)
        if process.stdout is not None:
            process.stdout.close()
        reader.join(timeout=1)
    elif process.stdout is not None:
        process.stdout.close()
    return _BoundedGitResult(
        124 if timed_out else int(process.returncode or 0),
        bytes(captured),
        total_bytes > output_limit,
    )


def _resolve_commit(repo_root: Path, ref: str) -> str | None:
    result = _run_git(repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if result.returncode != 0 or result.output_truncated:
        return None
    resolved = result.output.decode("ascii", errors="ignore").strip().lower()
    return resolved if _EXACT_COMMIT_RE.fullmatch(resolved) is not None else None


def _condition_applies(condition: ProfileCondition, changed_paths: Sequence[str]) -> bool:
    if condition.kind == "always":
        return True
    return any(path_matches_any(path, condition.patterns) for path in changed_paths)


def _normalized_digest_payload(
    *,
    profile_content_sha256: str,
    head: str,
    base_commit: str,
    merge_base: str,
    checks: Sequence[CheckOutcome],
) -> dict[str, Any]:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_content_sha256": profile_content_sha256,
        "head": head,
        "base_commit": base_commit,
        "merge_base": merge_base,
        "outcomes": [check.to_dict() for check in checks],
    }


def _result_digest(**kwargs: Any) -> str:
    material = json.dumps(
        _normalized_digest_payload(**kwargs),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def evaluate_landing_profile(
    repo_root: Path,
    *,
    base_ref: str = "origin/main",
    expected_head: str | None = None,
) -> ProjectLandingResult:
    """Evaluate the tracked profile at the exact current HEAD.

    Missing profiles are neutral. Every present profile must match the ordinary
    tracked bytes at ``HEAD``. Profiles never provide executable content.
    """

    root = Path(repo_root).resolve()
    loaded = load_landing_profile(root)
    if loaded.status == "missing":
        return ProjectLandingResult("missing", True, False)
    if loaded.status == "invalid":
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            diagnostics=((loaded.diagnostic,) if loaded.diagnostic is not None else ()),
        )
    assert loaded.profile is not None and loaded.content_sha256 is not None
    profile, issues = validate_landing_profile(loaded.profile)
    if profile is None:
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=issues,
        )

    head = _resolve_commit(root, "HEAD")
    if head is None:
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=_schema_diagnostic(
                "profile_head_unresolved",
                "Landing profile requires HEAD to resolve to an exact commit.",
            ),
        )
    if expected_head is not None and expected_head.lower() != head:
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            head=head,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=_schema_diagnostic(
                "profile_head_mismatch",
                "Landing profile HEAD does not match the expected exact commit.",
            ),
        )
    base_commit = _resolve_commit(root, base_ref)
    if base_commit is None:
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            head=head,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=_schema_diagnostic(
                "profile_base_unresolved",
                "Landing profile base must resolve to an exact commit.",
            ),
        )

    committed = _run_git(root, "cat-file", "blob", f"{head}:{PROFILE_RELATIVE_PATH.as_posix()}")
    if committed.returncode != 0 or committed.output_truncated:
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            head=head,
            base_commit=base_commit,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=_schema_diagnostic(
                "profile_not_tracked_at_head",
                "Landing profile must be tracked and committed at the exact HEAD.",
            ),
        )
    if hashlib.sha256(committed.output).hexdigest() != loaded.content_sha256:
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            head=head,
            base_commit=base_commit,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=_schema_diagnostic(
                "profile_differs_from_head",
                "Landing profile bytes must match the profile committed at exact HEAD.",
            ),
        )

    merge = _run_git(root, "merge-base", head, base_commit)
    merge_base = merge.output.decode("ascii", errors="ignore").strip().lower()
    if (
        merge.returncode != 0
        or merge.output_truncated
        or _EXACT_COMMIT_RE.fullmatch(merge_base) is None
    ):
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            head=head,
            base_commit=base_commit,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=_schema_diagnostic(
                "profile_merge_base_unresolved",
                "Landing profile merge base could not be resolved exactly.",
            ),
        )
    changed = _run_git(root, "diff", "--name-only", "-z", merge_base, head, "--")
    if changed.returncode != 0 or changed.output_truncated:
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            head=head,
            base_commit=base_commit,
            merge_base=merge_base,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=_schema_diagnostic(
                "profile_diff_unavailable",
                "Landing profile changed-path delta could not be read within bounds.",
            ),
        )
    try:
        changed_paths = tuple(
            sorted(
                path.decode("utf-8", errors="strict")
                for path in changed.output.split(b"\0")
                if path
            )
        )
    except UnicodeDecodeError:
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            head=head,
            base_commit=base_commit,
            merge_base=merge_base,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=_schema_diagnostic(
                "profile_diff_invalid_utf8",
                "Landing profile changed paths must be valid UTF-8.",
            ),
        )
    if len(changed_paths) > MAX_CHANGED_PATHS or any(
        len(path) > MAX_STRING_CHARS or path.startswith("/") or "\0" in path
        for path in changed_paths
    ):
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            head=head,
            base_commit=base_commit,
            merge_base=merge_base,
            profile_content_sha256=loaded.content_sha256,
            diagnostics=_schema_diagnostic(
                "profile_diff_out_of_bounds",
                "Landing profile changed-path delta exceeds safe bounds.",
            ),
        )

    outcomes: list[CheckOutcome] = []
    for check in profile.checks:
        applies = _condition_applies(check.condition, changed_paths)
        if not applies:
            outcomes.append(
                CheckOutcome(
                    id=check.id,
                    kind=check.kind,
                    severity=check.severity,
                    status="skipped",
                    code="condition_not_met",
                )
            )
            continue
        if check.kind == "post_merge_checklist":
            outcomes.append(
                CheckOutcome(
                    id=check.id,
                    kind=check.kind,
                    status="applicable",
                    code="declarative_only",
                    message=check.description,
                )
            )
            continue
        if check.kind == "path_touched":
            touched = any(path_matches_any(path, check.paths) for path in changed_paths)
            outcomes.append(
                CheckOutcome(
                    id=check.id,
                    kind=check.kind,
                    severity=check.severity,
                    status="passed" if touched else "failed",
                    code="required_path_touched" if touched else "required_path_not_touched",
                )
            )
            continue

    current_head = _resolve_commit(root, "HEAD")
    if current_head != head:
        return ProjectLandingResult(
            "invalid",
            False,
            True,
            head=head,
            base_commit=base_commit,
            merge_base=merge_base,
            profile_content_sha256=loaded.content_sha256,
            changed_paths=changed_paths,
            checks=tuple(outcomes),
            diagnostics=_schema_diagnostic(
                "profile_head_changed",
                "Repository HEAD changed while project landing checks were running.",
            ),
        )
    blocking_failed = any(
        outcome.status == "failed" and outcome.severity == "blocking"
        for outcome in outcomes
    )
    digest = _result_digest(
        profile_content_sha256=loaded.content_sha256,
        head=head,
        base_commit=base_commit,
        merge_base=merge_base,
        checks=outcomes,
    )
    return ProjectLandingResult(
        "failed" if blocking_failed else "passed",
        not blocking_failed,
        True,
        head=head,
        base_commit=base_commit,
        merge_base=merge_base,
        profile_content_sha256=loaded.content_sha256,
        digest=digest,
        changed_paths=changed_paths,
        checks=tuple(outcomes),
    )
