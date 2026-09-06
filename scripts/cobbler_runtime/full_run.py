"""Full-run supervisor for trusted delegated implementers (Lane A / Grok Build).

Uses adapter-aware ``implement.build_launch_argv`` for real Grok create/resume.
Fixture mode is explicit (``adapter=fixture``) for unit tests only.

Artifacts live under digest-keyed private paths. Worker events enrich telemetry;
liveness also comes from process fingerprint + observed feature-branch HEAD.
A worker report is evidence only — never merge authority.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import hashlib
import hmac
import json
import math
import mmap
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .acceptance import (
    STABLE_ACCEPTANCE_ID_RE,
    normalize_batch_id,
    parse_plan_acceptance_contract,
    parse_markdown_acceptance_rows,
    validate_contract_mapping,
)
from .adapters import reject_fugu_implementation_route
from .context import redact_text, validate_credential_grant_names
from .delegated_git import (
    DelegatedGitContract,
    assert_action_allowed,
    assert_descendant,
    assert_feature_branch,
    reconcile_worker_report,
)
from .implement import (
    DEFAULT_EFFORT,
    DEFAULT_EXECUTABLE,
    DEFAULT_MODEL,
    DEFAULT_PERMISSION_MODE,
    GROK_DEFAULT_EFFORT,
    build_launch_argv,
    detect_native_grok_goal,
)
from .leases import run_git, worktree_is_registered
from .provider_auth import (
    _MATERIAL_CHANGE_KINDS,
    CONFIDENCE_LEVELS,
    EVENT_TYPES,
    MAX_UNSURE_ABOUT_ITEM_CHARS,
    MAX_UNSURE_ABOUT_ITEMS,
    DEVIN_CONFIG_FILE_NAME,
    DEVIN_CREDENTIALS_FILE_NAME,
    GROK_AUTH_FILE_NAME,
    GROK_AUTH_PATH_MIN_VERSION,
    GROK_HOME_REL,
    MAX_DEVIN_AUTH_BYTES,
    MAX_GROK_AUTH_BYTES,
    MAX_GROK_EXECUTABLE_PROBE_BYTES,
    NON_SECRET_ESSENTIALS,
    STOP_REQUEST_NAME,
    WORKER_EVENT_CONTRACT,
    _DARWIN_ACL_EXTENDED_ALLOW,
    _DARWIN_ACL_EXTENDED_DENY,
    _DARWIN_ACL_FIRST_ENTRY,
    _DARWIN_ACL_NEXT_ENTRY,
    _DARWIN_ACL_TYPE_EXTENDED,
    _FULL_RUN_SECRET_KEY_RE,
    _GITHUB_PUSH_AUTH_STRATEGIES,
    _GROK_VERSION_RE,
    _MACH_O_MAGICS,
    _SHA256_RE,
    _assert_grok_auth_path_capability,
    _assert_no_darwin_extended_allow_acl,
    _assert_stable_grok_executable,
    _bind_state_grok_executable,
    _cleanup_refused_launch,
    _configure_devin_auth,
    _configure_grok_auth,
    _contains_persisted_credential_grant,
    _credential_grant_digest,
    _credential_grant_metadata_mac,
    _darwin_acl_api,
    _descendant_supervision_marker,
    _devin_auth_source_files,
    _executable_advertises_grok_auth_path,
    _grok_auth_directory_identity,
    _grok_auth_source,
    _grok_executable_identity,
    _isolated_grok_capability_probe_env,
    _launch_evidence_context,
    _launch_grants_verified,
    _native_executable_format,
    _oauth_secret_values,
    _open_verified_grok_auth_parent_chain,
    _open_verified_owner_parent_chain_fds,
    _persisted_grant_metadata_valid,
    _project_devin_auth,
    _read_and_validate_devin_auth,
    _read_grok_auth_path,
    _read_host_devin_file,
    _read_host_grok_auth,
    _redact_persisted_credential_grants,
    _remove_failed_launch_artifacts,
    _resolve_grok_executable,
    _resolve_shared_oauth_grok_executable,
    _revalidate_shared_grok_auth,
    _shared_oauth_grok_executable_identity,
    _state_secret_values,
    _stop_request_authority,
    _supervision_secret,
    _text_contains_persisted_credential_grant,
    _validate_devin_file_content,
    _write_supervisor_stop_request,
    build_full_run_env,
)
from .git_contract import (
    _assert_clean_worktree,
    _assert_origin_binding,
    _canonical_origin_url,
    _feature_remote_tip,
    _git_branch,
    _git_common_dir,
    _git_head,
    _github_provider_managed_ref,
    _host_ephemeral_ref,
    _is_ancestor,
    _origin_config_digest,
    _origin_present,
    _remote_refs,
    snapshot_protected_refs,
    verify_protected_refs_unchanged,
)
from .schema import AMBIGUOUS_SESSION_TOKENS, ELVES_SESSION_BASENAME, ValidationIssue
from .toml_compat import loads as _load_toml
from .storage import (
    StorageError,
    _assert_directory_fd_identity,
    _open_repo_directory,
    assert_embedded_id,
    atomic_write_json,
    directory_lock,
    digest_key,
    ensure_private_dir,
    guard_repo_path,
    move_repo_regular_file,
    open_repo_text,
    read_json,
    read_repo_regular_bytes,
    read_repo_text_tail,
    repo_regular_file_exists,
)

FULL_RUN_REL = Path(".elves") / "runtime" / "implement" / "full-run"
TERMINAL_EVENT_TYPES = frozenset({"run_complete", "blocked"})


def _terminal_event_types_present(
    events_path: Path,
    *,
    repo_root: Path,
) -> frozenset[str]:
    """Return terminal event types already present in a full-run events log.

    Used only for fail-closed resume-prepare / resume-launch: a log that already
    carries ``run_complete`` or ``blocked`` must not be rebuilt with a new
    ``run_started``.

    Only a proven-absent log is treated as non-terminal. Unreadable, oversized,
    non-regular, or otherwise unverifiable logs raise
    ``full_run_resume_event_log_unverifiable`` so callers refuse before any write.
    """
    try:
        exists = repo_regular_file_exists(repo_root, events_path)
    except StorageError as exc:
        raise ValidationIssue(
            "full_run_resume_event_log_unverifiable",
            f"Cannot verify terminal events: event log path is unsafe ({exc.code})",
            path=str(events_path),
            hint="Start a new session_id; do not rebuild a session whose event log cannot be verified",
        ) from exc
    if not exists:
        return frozenset()
    try:
        raw = _read_bounded_regular_bytes(
            events_path,
            max_bytes=MAX_EVENT_FILE_BYTES,
            label="event log",
            repo_root=repo_root,
        )
    except StorageError as exc:
        raise ValidationIssue(
            "full_run_resume_event_log_unverifiable",
            f"Cannot verify terminal events: {exc}",
            path=str(events_path),
            hint="Start a new session_id; do not rebuild a session whose event log cannot be verified",
        ) from exc
    except OSError as exc:
        raise ValidationIssue(
            "full_run_resume_event_log_unverifiable",
            f"Cannot verify terminal events: {type(exc).__name__}",
            path=str(events_path),
            hint="Start a new session_id; do not rebuild a session whose event log cannot be verified",
        ) from exc
    found: set[str] = set()
    for raw_line in raw.splitlines():
        if not raw_line or len(raw_line) > MAX_EVENT_LINE_BYTES:
            continue
        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if isinstance(etype, str) and etype in TERMINAL_EVENT_TYPES:
            found.add(etype)
    return frozenset(found)


DEFAULT_STALE_SECONDS = 300
# Darwin process-group reaping is slower under CI load; give the exact recorded
# supervisor a little longer to leave the group before failing closed.
EXIT_RECORD_SETTLE_SECONDS = 0.75 if sys.platform == "darwin" else 0.25
# aigorahub/elves#263: the supervision canary used to share one 0.75s wall
# budget for hang detection and capability proof. Scale the observe window to
# the first scan's cost so a loaded Darwin `ps e` cannot fail a working
# supervisor. Floor keeps the original budget; ceiling bounds a hang.
SUPERVISION_CANARY_FLOOR_SECONDS = 0.75
SUPERVISION_CANARY_CEILING_SECONDS = 8.0
SUPERVISION_CANARY_SCAN_MULTIPLE = 4.0
SUPERVISION_CANARY_POLL_SECONDS = 0.03
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_REPORT_STATUSES = frozenset({"running", "complete", "blocked", "failed", "stopped"})
_ACCEPTANCE_ID_RE = STABLE_ACCEPTANCE_ID_RE
_HIGH_RISK_CHECKPOINT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MATERIAL_CHANGE_ID_RE = _HIGH_RISK_CHECKPOINT_ID_RE
_HIGH_RISK_CHECKPOINT_DEFINITION_RE = re.compile(
    r"(?im)^\s*[-*]\s+high-risk\s+checkpoint\s*:\s*"
    r"(?P<id>[A-Za-z0-9][A-Za-z0-9._-]{0,63})\s*$"
)
_ENV_GRANT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FULL_RUN_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])"
    r"(?:api[_-]?key|[A-Za-z0-9_-]*token|jwt|bearer|authorization|auth|"
    r"password|passwd|secret|credential|cookie|private[_-]?key)"
    r"[\"']?\s*[:=]\s*(?:bearer\s+)?[\"']?[^\s,;\"'}]{8,}[\"']?"
)
_PEM_BOUNDARY_RE = re.compile(r"-----\s*(?:BEGIN|END)\s+[A-Z0-9 ]*PRIVATE KEY\s*-----", re.I)
MAX_PACKET_BYTES = 1024 * 1024
MAX_EVENT_FILE_BYTES = 1024 * 1024
MAX_EVENT_LINES = 2000
MAX_EVENT_LINE_BYTES = 64 * 1024
MAX_HIGH_RISK_CHECKPOINTS = 64
MAX_REPORT_BYTES = 512 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20_000
MAX_JSON_KEYS = 5_000
MAX_JSON_STRING_CHARS = 64 * 1024
MAX_JSON_KEY_CHARS = 512
MAX_JSON_TOTAL_STRING_CHARS = MAX_REPORT_BYTES
MAX_JSON_INTEGER_BITS = 256
MAX_JSON_NUMBER_CHARS = 128
MAX_TRANSCRIPT_TAIL_BYTES = 256 * 1024
MAX_TRANSCRIPT_LINE_CHARS = 1000
MAX_REVIEW_CONFIDENCE_ROWS = 256
MAX_REVIEW_CONFIDENCE_PROMPT_CHARS = 128 * 1024
MAX_REVIEW_CONFIDENCE_LABEL_CHARS = 160
MAX_REVIEW_CONFIDENCE_RESERVATION_CHARS = 320
MAX_GROK_STREAM_RECORD_BYTES = 1024 * 1024
GROK_STREAM_READ_CHUNK_BYTES = 256 * 1024
MAX_EVENT_FUTURE_SKEW_SECONDS = 300
MAX_STOP_REQUEST_BYTES = 4096
MAX_GITHUB_TOKEN_BYTES = 64 * 1024
MAX_GIT_IDENTITY_BYTES = 4096
DEVIN_HOST_EVENT_TYPES = frozenset(
    {"devin_session_captured", "devin_capture_failed"}
)
_GITHUB_PUSH_TOKEN_NAMES = ("GH_TOKEN", "GITHUB_TOKEN")
_GITHUB_CREDENTIAL_HELPER = (
    "!f() { test \"$1\" = get || exit 0; "
    "printf 'username=%s\\npassword=%s\\n' x-access-token "
    "\"${GH_TOKEN:-${GITHUB_TOKEN:-}}\"; }; f"
)

# Named non-secret essentials preserved for a usable Grok process. Home, temp,
# XDG, and proxy controls are deliberately absent: they either cross the
# isolation boundary or may embed opaque credentials.

# Credential grants are explicit by name (values never appear as argv KEY=VALUE).
# In particular, do not leak unrelated OPENAI/GROK variables into a Grok run.
DEFAULT_CREDENTIAL_GRANT_NAMES: frozenset[str] = frozenset()

STATUS_KEYS = frozenset(
    {
        "ok",
        "session_id",
        "state",
        "batch",
        "head",
        "branch",
        "heartbeat_at",
        "pid",
        "pgid",
        "next_action",
        "blocker",
        "driver_contract",
        "driver_monitor_mode",
        "poll_after_seconds",
        "user_heartbeat_seconds",
        "chat_update_policy",
        "chat_update_recommended",
        "unchanged_healthy_poll_silent",
        "material_transition",
        "monitor_depth",
        "remote_all_ref_audit",
        "goal_launch_mode",
        "report_provenance",
        "wake_conditions",
        "planned_high_risk_checkpoints",
        "pending_high_risk_checkpoint",
        "acknowledged_high_risk_checkpoints",
        "check_summary",
        "report_path",
        "events_path",
        "transcript_private",
        "adapter",
        "fingerprint_ok",
        "review_context",
        "merge_authority",
    }
)


def _normalize_credential_grant_names(
    names: Sequence[str] | None,
) -> list[str]:
    """Return deterministic environment-name grants without ever echoing bad input."""
    if names is None:
        return sorted(DEFAULT_CREDENTIAL_GRANT_NAMES)
    if isinstance(names, (str, bytes)) or not isinstance(names, Sequence):
        raise ValidationIssue(
            "full_run_credential_grant_name_invalid",
            "Credential grants must be supplied as a sequence of environment names",
            hint="Use ['XAI_API_KEY'] in Python or --grant-env XAI_API_KEY in the CLI",
        )
    normalized: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not _ENV_GRANT_NAME_RE.fullmatch(name):
            raise ValidationIssue(
                "full_run_credential_grant_name_invalid",
                "Credential grants must be environment variable names only",
                hint="Use --grant-env XAI_API_KEY, never KEY=VALUE",
            )
        normalized.add(name)
    ordered = sorted(normalized)
    validate_credential_grant_names(
        ordered,
        code="full_run_isolation_control_grant_forbidden",
        path="credential_grant_names",
    )
    return ordered


def _normalize_persisted_credential_grant_names(
    value: Any,
) -> tuple[bool, list[str]]:
    """Parse one persisted grant-name field without trusting JSON field types.

    Persisted launch evidence is canonical only as a sorted, duplicate-free JSON
    array.  Corrupt scalar/string values must make evidence unavailable, never
    escape as a raw iteration ``TypeError`` from a public monitor or log call.
    """
    if not isinstance(value, list):
        return False, []
    try:
        normalized = _normalize_credential_grant_names(value)
    except ValidationIssue:
        return False, []
    return value == normalized, normalized


class _PreTransferHandoffError(ValidationIssue):
    """The staged supervisor was killed before provider start became possible."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(
            "full_run_supervision_secret_handoff_not_transferred",
            "Supervisor start capability was not transferred",
            hint="The staged child was killed and reaped before provider spawn",
        )
        self.cause_type = type(cause).__name__


def _redact_full_run_text(
    value: str,
    *,
    exact_values: frozenset[str] | set[str] | tuple[str, ...] | None = None,
) -> str:
    """Apply shared token redaction plus full-run credential assignments."""
    shared = redact_text(value, exact_values=exact_values).text
    return _FULL_RUN_SECRET_ASSIGNMENT_RE.sub(
        "[REDACTED:credential_assignment]", shared
    )


def _collision_safe_mapping_keys(desired_keys: Sequence[str]) -> list[str]:
    """Allocate deterministic redacted keys without shadowing real key names.

    The full set of primary names is reserved before suffixes are allocated.
    Otherwise a generated ``#N`` name can overwrite a later, pre-existing key
    with that exact suffix and silently discard evidence.
    """
    reserved = set(desired_keys)
    used: set[str] = set()
    allocated: list[str] = []
    for desired in desired_keys:
        candidate = desired
        if candidate in used:
            suffix = 1
            while True:
                candidate = f"{desired}#{suffix}"
                if candidate not in used and candidate not in reserved:
                    break
                suffix += 1
        used.add(candidate)
        allocated.append(candidate)
    return allocated


def _redact_full_run_structure(
    value: Any,
    *,
    exact_values: frozenset[str] | set[str] | tuple[str, ...] | None = None,
) -> Any:
    """Recursively redact keys and values before any driver-visible serialization."""
    if isinstance(value, str):
        return _redact_full_run_text(value, exact_values=exact_values)
    if isinstance(value, Mapping):
        rows: list[tuple[str, Any, bool]] = []
        desired_keys: list[str] = []
        for key, item in value.items():
            raw_key = str(key)
            redacted_key = _redact_full_run_text(
                raw_key,
                exact_values=exact_values,
            )
            secret_field = bool(_FULL_RUN_SECRET_KEY_RE.search(raw_key))
            if secret_field:
                redacted_key = "[REDACTED:secret_field_name]"
            rows.append((redacted_key, item, secret_field))
            desired_keys.append(redacted_key)
        redacted_mapping: dict[str, Any] = {}
        allocated_keys = _collision_safe_mapping_keys(desired_keys)
        for redacted_key, (_desired, item, secret_field) in zip(
            allocated_keys, rows
        ):
            redacted_mapping[redacted_key] = (
                "[REDACTED:secret_field]"
                if secret_field
                else _redact_full_run_structure(item, exact_values=exact_values)
            )
        return redacted_mapping
    if isinstance(value, list):
        return [
            _redact_full_run_structure(item, exact_values=exact_values)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _redact_full_run_structure(item, exact_values=exact_values)
            for item in value
        )
    return value


def _redact_full_run_mapping_in_place(
    value: dict[str, Any],
    *,
    exact_values: frozenset[str] | set[str] | tuple[str, ...] | None = None,
) -> None:
    """Sanitize values without obscuring a public function's static output shape."""
    redacted = _redact_full_run_structure(value, exact_values=exact_values)
    value.clear()
    value.update(redacted)


def _contains_full_run_secret(
    value: Any,
    *,
    exact_values: frozenset[str] | set[str] | tuple[str, ...] | None = None,
    credential_grant_state: "FullRunState | None" = None,
) -> bool:
    if _redact_full_run_structure(value, exact_values=exact_values) != value:
        return True
    return bool(
        credential_grant_state
        and _contains_persisted_credential_grant(value, credential_grant_state)
    )


def _read_bounded_regular_bytes(
    path: Path,
    *,
    max_bytes: int,
    label: str,
    repo_root: Path | None = None,
) -> bytes:
    """Read one regular non-symlink file with an exact byte ceiling."""
    candidate = Path(path)
    if repo_root is not None:
        try:
            return read_repo_regular_bytes(
                Path(repo_root), candidate, max_bytes=max_bytes
            )
        except StorageError as exc:
            raise StorageError(exc.code, f"{label}: {exc.message}") from exc
    try:
        before = candidate.lstat()
    except FileNotFoundError as exc:
        raise StorageError(f"{label}_missing", f"{label} is missing: {candidate}") from exc
    except OSError as exc:
        raise StorageError(
            f"{label}_unavailable", f"{label} metadata is unavailable: {type(exc).__name__}"
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        raise StorageError(
            f"{label}_not_regular", f"{label} must be a regular non-symlink file"
        )
    if before.st_size > max_bytes:
        raise StorageError(
            f"{label}_too_large", f"{label} exceeds {max_bytes} byte limit"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as exc:
        raise StorageError(
            f"{label}_unavailable", f"{label} cannot be opened safely: {type(exc).__name__}"
        ) from exc
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            raise StorageError(
                f"{label}_identity_changed", f"{label} changed identity while opening"
            )
        if opened.st_size > max_bytes:
            raise StorageError(
                f"{label}_too_large", f"{label} exceeds {max_bytes} byte limit"
            )
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise StorageError(
                f"{label}_too_large", f"{label} exceeds {max_bytes} byte limit"
            )
        return raw
    finally:
        os.close(fd)


def _bounded_json_int(raw: str) -> int:
    digits = raw[1:] if raw.startswith("-") else raw
    if len(digits) > MAX_JSON_NUMBER_CHARS:
        raise ValueError("JSON integer token exceeds the numeric budget")
    value = int(raw)
    if value.bit_length() > MAX_JSON_INTEGER_BITS:
        raise ValueError("JSON integer exceeds the numeric budget")
    return value


def _bounded_json_float(raw: str) -> float:
    if len(raw) > MAX_JSON_NUMBER_CHARS:
        raise ValueError("JSON number token exceeds the numeric budget")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("JSON number must be finite")
    return value


def _reject_json_constant(_raw: str) -> Any:
    raise ValueError("non-standard JSON constants are forbidden")


def _bounded_json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(pairs) > MAX_JSON_KEYS:
        raise ValueError("JSON object exceeds the key budget")
    value: dict[str, Any] = {}
    for key, child in pairs:
        if len(key) > MAX_JSON_KEY_CHARS:
            raise ValueError("JSON key exceeds the character budget")
        if key in value:
            raise ValueError("duplicate JSON object keys are forbidden")
        value[key] = child
    return value


def _loads_bounded_json(text: str, *, label: str) -> Any:
    """Parse standard JSON while bounding numeric work before conversion."""
    del label  # Kept in the signature so callers cannot forget the evidence surface.
    return json.loads(
        text,
        parse_int=_bounded_json_int,
        parse_float=_bounded_json_float,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_bounded_json_object_pairs,
    )


def _assert_bounded_json_structure(value: Any, *, label: str) -> None:
    """Iteratively bound JSON structure before recursive scans/redaction.

    Byte ceilings alone do not bound parser recursion, node fan-out, or the
    substring work performed by exact-secret detection. This validator runs
    before any recursive evidence handling and deliberately avoids recursion.
    """
    stack: list[tuple[Any, int]] = [(value, 0)]
    node_count = 0
    key_count = 0
    total_string_chars = 0
    while stack:
        item, depth = stack.pop()
        node_count += 1
        if node_count > MAX_JSON_NODES:
            raise StorageError(
                f"{label}_structure",
                f"{label} exceeds the {MAX_JSON_NODES} node budget",
            )
        if depth > MAX_JSON_DEPTH:
            raise StorageError(
                f"{label}_structure",
                f"{label} exceeds the {MAX_JSON_DEPTH} level depth budget",
            )
        if isinstance(item, str):
            if len(item) > MAX_JSON_STRING_CHARS:
                raise StorageError(
                    f"{label}_structure",
                    f"{label} contains a string exceeding the character budget",
                )
            total_string_chars += len(item)
        elif isinstance(item, Mapping):
            key_count += len(item)
            if key_count > MAX_JSON_KEYS:
                raise StorageError(
                    f"{label}_structure",
                    f"{label} exceeds the {MAX_JSON_KEYS} key budget",
                )
            for key, child in item.items():
                if not isinstance(key, str):
                    raise StorageError(
                        f"{label}_structure",
                        f"{label} contains a non-string object key",
                    )
                if len(key) > MAX_JSON_KEY_CHARS:
                    raise StorageError(
                        f"{label}_structure",
                        f"{label} contains a key exceeding the character budget",
                    )
                total_string_chars += len(key)
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, bool) or item is None:
            pass
        elif isinstance(item, int):
            if item.bit_length() > MAX_JSON_INTEGER_BITS:
                raise StorageError(
                    f"{label}_structure",
                    f"{label} contains an integer exceeding the numeric budget",
                )
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise StorageError(
                    f"{label}_structure",
                    f"{label} contains a non-finite number",
                )
        else:
            raise StorageError(
                f"{label}_structure",
                f"{label} contains a non-JSON value",
            )
        if total_string_chars > MAX_JSON_TOTAL_STRING_CHARS:
            raise StorageError(
                f"{label}_structure",
                f"{label} exceeds the total string character budget",
            )


def _read_bounded_json_object(
    path: Path,
    *,
    max_bytes: int = MAX_REPORT_BYTES,
    label: str = "JSON artifact",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    raw = _read_bounded_regular_bytes(
        path,
        max_bytes=max_bytes,
        label=label,
        repo_root=repo_root,
    )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StorageError(
            f"{label}_encoding", f"{label} must be valid UTF-8"
        ) from exc
    try:
        value = _loads_bounded_json(text, label=label)
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise StorageError(
            f"{label}_malformed",
            f"{label} must contain one bounded valid JSON object",
        ) from exc
    if not isinstance(value, dict):
        raise StorageError(
            f"{label}_malformed", f"{label} must contain one JSON object"
        )
    _assert_bounded_json_structure(value, label=label)
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def full_run_root(repo_root: Path, session_id: str) -> Path:
    """Digest-keyed collision-free runtime directory (not raw session path)."""
    key = digest_key(session_id, prefix="fullrun")
    repo = Path(repo_root).expanduser().resolve(strict=True)
    return guard_repo_path(repo, repo / FULL_RUN_REL / key)


_FULL_RUN_LOCK_LOCAL = threading.local()
_FULL_RUN_THREAD_LOCKS: dict[str, threading.RLock] = {}
_FULL_RUN_THREAD_LOCKS_GUARD = threading.Lock()


@contextmanager
def _full_run_lock(repo_root: Path, session_id: str):
    """Cross-process per-session lock with same-thread reentrancy."""
    repo = Path(repo_root).expanduser().resolve(strict=True)
    root = full_run_root(repo, session_id)
    lock_key = str(guard_repo_path(repo, root / "run.lock"))
    held = getattr(_FULL_RUN_LOCK_LOCAL, "held", None)
    if held is None:
        held = set()
        _FULL_RUN_LOCK_LOCAL.held = held
    if lock_key in held:
        yield
        return
    with _FULL_RUN_THREAD_LOCKS_GUARD:
        thread_lock = _FULL_RUN_THREAD_LOCKS.setdefault(lock_key, threading.RLock())
    with thread_lock:
        with directory_lock(
            root,
            name="run.lock",
            timeout=30.0,
            repo_root=repo,
        ):
            held.add(lock_key)
            try:
                yield
            finally:
                held.remove(lock_key)


def _locked_full_run(func):
    """Serialize public full-run mutations without changing their signatures."""
    @wraps(func)
    def wrapper(repo_root: Path, *args: Any, **kwargs: Any):
        session_id = kwargs.get("session_id")
        # Let the wrapped validator produce the stable missing-ID issue.
        if not session_id:
            return func(repo_root, *args, **kwargs)
        with _full_run_lock(Path(repo_root), str(session_id)):
            return func(repo_root, *args, **kwargs)

    return wrapper


def _expected_run_id(session_id: str) -> str:
    return f"full-run-{digest_key(session_id, prefix='run')}"


def _is_sha1(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA1_RE.fullmatch(value))


def _is_utc_iso8601(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    offset = parsed.utcoffset()
    return offset is not None and offset.total_seconds() == 0


def _latest_utc_iso8601(current: str | None, candidate: Any) -> str | None:
    """Return the later valid UTC timestamp without letting old events rewind activity."""
    if not _is_utc_iso8601(candidate):
        return current
    candidate_text = str(candidate)
    candidate_dt = datetime.fromisoformat(candidate_text.replace("Z", "+00:00"))
    if (
        candidate_dt - datetime.now(timezone.utc)
    ).total_seconds() > MAX_EVENT_FUTURE_SKEW_SECONDS:
        return current
    if not current or not _is_utc_iso8601(current):
        return candidate_text
    current_dt = datetime.fromisoformat(current.replace("Z", "+00:00"))
    return candidate_text if candidate_dt > current_dt else current


_SUMMARY_SECRET_NEEDLES = ("api_key=", "bearer ", "authorization:", "-----begin")


def _validate_confidence_fields(
    container: Mapping[str, Any],
    errors: list[str],
    *,
    prefix: str = "",
    allow_projected_unsure_count: bool = False,
) -> None:
    """Validate the optional worker confidence signal when present.

    Absent fields are always valid (backward compatible), and an empty
    `unsure_about` list is a valid, complete answer. The signal is review
    triage only, never authority: it does not skip gates or waive review.
    `unsure_about_count` without the list is legitimate only as the host-side
    shared-OAuth projection of a hidden list; a worker-supplied bare count is
    rejected unless the caller is validating that projection.
    """
    if (
        "confidence" in container
        and container.get("confidence") not in CONFIDENCE_LEVELS
    ):
        errors.append(f"{prefix}confidence must be one of high, medium, low")
    if "unsure_about_count" in container:
        projected_count = container.get("unsure_about_count")
        if not allow_projected_unsure_count and not isinstance(
            container.get("unsure_about"), list
        ):
            errors.append(
                f"{prefix}unsure_about_count without unsure_about is only valid "
                "on the shared-OAuth projection"
            )
        elif (
            not isinstance(projected_count, int)
            or isinstance(projected_count, bool)
            or not 0 <= projected_count <= MAX_UNSURE_ABOUT_ITEMS
        ):
            errors.append(
                f"{prefix}unsure_about_count must be an integer between 0 and "
                f"{MAX_UNSURE_ABOUT_ITEMS}"
            )
    if "unsure_about" not in container:
        return
    unsure = container.get("unsure_about")
    if not isinstance(unsure, list):
        errors.append(f"{prefix}unsure_about must be a list")
        return
    if len(unsure) > MAX_UNSURE_ABOUT_ITEMS:
        errors.append(
            f"{prefix}unsure_about exceeds {MAX_UNSURE_ABOUT_ITEMS} items"
        )
    if any(not isinstance(item, str) or not item.strip() for item in unsure):
        errors.append(f"{prefix}unsure_about items must be non-empty strings")
    if any(
        isinstance(item, str) and len(item) > MAX_UNSURE_ABOUT_ITEM_CHARS
        for item in unsure
    ):
        errors.append(
            f"{prefix}unsure_about item exceeds {MAX_UNSURE_ABOUT_ITEM_CHARS} chars"
        )
    lowered_items = " ".join(
        item.lower() for item in unsure if isinstance(item, str)
    )
    if any(needle in lowered_items for needle in _SUMMARY_SECRET_NEEDLES):
        errors.append(f"{prefix}unsure_about contains secret-shaped content")


def _project_confidence_signal(
    container: Mapping[str, Any],
    *,
    transform=None,
) -> dict[str, Any]:
    """Project a confidence signal's fields under the one shared bound set.

    Returns ``confidence`` (enum member or None), ``unsure_about`` (bounded
    list when a list was supplied, else None) and ``unsure_about_count``
    (list length, else a bounded projected count, else None). Every consumer
    of the worker confidence signal must route through this helper so the
    routes cannot diverge. ``transform`` (e.g. redaction) applies to each
    retained item.
    """

    confidence_value = container.get("confidence")
    confidence = (
        str(confidence_value) if confidence_value in CONFIDENCE_LEVELS else None
    )
    unsure = container.get("unsure_about")
    if isinstance(unsure, list):
        items = [
            transform(item[:MAX_UNSURE_ABOUT_ITEM_CHARS])
            if transform is not None
            else str(item)[:MAX_UNSURE_ABOUT_ITEM_CHARS]
            for item in unsure[:MAX_UNSURE_ABOUT_ITEMS]
            if isinstance(item, str) and item.strip()
        ]
        return {
            "confidence": confidence,
            "unsure_about": items,
            "unsure_about_count": len(items),
        }
    projected_count = container.get("unsure_about_count")
    count = (
        projected_count
        if isinstance(projected_count, int)
        and not isinstance(projected_count, bool)
        and 0 <= projected_count <= MAX_UNSURE_ABOUT_ITEMS
        else None
    )
    return {
        "confidence": confidence,
        "unsure_about": None,
        "unsure_about_count": count,
    }


def _confidence_candidate(
    container: Mapping[str, Any],
    *,
    source: str,
    hide_free_text: bool,
) -> dict[str, Any] | None:
    """Project one already-validated confidence signal for review triage."""

    has_confidence = "confidence" in container
    has_unsure = "unsure_about" in container or "unsure_about_count" in container
    if not has_confidence and not has_unsure:
        return None
    signal = _project_confidence_signal(container)
    unsure_items = None if hide_free_text else signal["unsure_about"]
    unsure_count = signal["unsure_about_count"]
    return {
        "source": source,
        "confidence": signal["confidence"],
        "has_confidence": has_confidence,
        "has_unsure_answer": has_unsure,
        "unsure_about": unsure_items,
        "unsure_about_count": unsure_count,
        "free_text_hidden": bool(
            hide_free_text and has_unsure and unsure_count is not None and unsure_count > 0
        ),
    }


def _batch_number_from_label(label: str) -> int | None:
    match = re.search(r"(?i)(?:^|[^a-z0-9])batch[-_ ]?(\d+)(?:$|[^0-9])", label)
    if match is None:
        return None
    return int(match.group(1))


def build_worker_confidence_review_context(
    *,
    session_id: str,
    branch: str,
    final_head: str,
    report: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    shared_oauth: bool = False,
    event_evidence_partial: bool = False,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Build the exact bounded confidence block a final reviewer must receive.

    Inputs must already have passed the full-run report/event validators. The
    output guides attention only: baseline review remains mandatory, high
    confidence never suppresses a check, and missing data is called out rather
    than being conflated with an asserted-clean empty list. Optional
    ``repo_root`` also folds native-lane confidence sidecars under
    ``.elves/runtime/confidence/`` (triage only).
    """

    candidates: dict[str, list[dict[str, Any]]] = {}
    ordered_labels: list[str] = []
    report_label_by_number: dict[int, str] = {}

    def remember(label: str, candidate: dict[str, Any] | None) -> None:
        if label not in ordered_labels:
            ordered_labels.append(label)
        if candidate is not None:
            candidates.setdefault(label, []).append(candidate)

    batches = report.get("batches")
    if isinstance(batches, list):
        for index, item in enumerate(batches, 1):
            if not isinstance(item, Mapping):
                continue
            raw_id = item.get("id")
            base_label = (
                str(raw_id or f"batch-{index}").strip() or f"batch-{index}"
            )
            label = (
                base_label
                if base_label not in ordered_labels
                else f"{base_label} (report row {index})"
            )
            # Canonical parser first (handles B0/B1 and honors a parsed 0);
            # regex spelling fallback second; positional row number last, and
            # only when nothing parsed — `or` would swallow a legitimate 0.
            batch_number = normalize_batch_id(base_label)
            if batch_number is None:
                batch_number = _batch_number_from_label(base_label)
            if batch_number is None:
                batch_number = index
            report_label_by_number.setdefault(batch_number, label)
            remember(
                label,
                _confidence_candidate(
                    item,
                    source="report",
                    hide_free_text=shared_oauth,
                ),
            )

    for event in events:
        if event.get("type") not in {"batch_complete", "run_complete"}:
            continue
        batch_value = event.get("batch")
        if event.get("type") == "run_complete":
            label = "run-complete"
        elif isinstance(batch_value, int) and not isinstance(batch_value, bool):
            label = report_label_by_number.get(batch_value, f"batch-{batch_value}")
        else:
            label = "batch-unknown"
        candidate = _confidence_candidate(
            event,
            source="event",
            # Shared-OAuth events have already projected the list to a count,
            # but keep this true so a direct validated caller cannot
            # accidentally re-expose worker free text on that route.
            hide_free_text=shared_oauth,
        )
        if candidate is not None:
            remember(label, candidate)

    if repo_root is not None:
        try:
            from .confidence_sidecar import (  # noqa: PLC0415
                confidence_runtime_dir,
                read_confidence_sidecar,
            )

            conf_dir = confidence_runtime_dir(Path(repo_root))
            if conf_dir.is_dir():
                for path in sorted(conf_dir.glob("*.json")):
                    data = read_confidence_sidecar(Path(repo_root), path.stem)
                    if not isinstance(data, Mapping):
                        continue
                    label = str(data.get("key") or path.stem)
                    candidate = _confidence_candidate(
                        data,
                        source="sidecar",
                        hide_free_text=shared_oauth,
                    )
                    if candidate is not None:
                        remember(label, candidate)
        except Exception:
            pass

    omitted_signal_rows = max(0, len(ordered_labels) - MAX_REVIEW_CONFIDENCE_ROWS)
    ordered_labels = ordered_labels[:MAX_REVIEW_CONFIDENCE_ROWS]

    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    rows: list[dict[str, Any]] = []
    priority_areas: list[str] = []
    lowest_confidence: str | None = None
    for label in ordered_labels:
        source_rows = candidates.get(label, [])
        confidence_values = [
            str(row["confidence"])
            for row in source_rows
            if row.get("confidence") in CONFIDENCE_LEVELS
        ]
        confidence = (
            min(confidence_values, key=lambda value: confidence_rank[value])
            if confidence_values
            else None
        )
        if confidence is not None and (
            lowest_confidence is None
            or confidence_rank[confidence] < confidence_rank[lowest_confidence]
        ):
            lowest_confidence = confidence

        unsure_items: list[str] = []
        for source_row in source_rows:
            for item in source_row.get("unsure_about") or []:
                if item not in unsure_items:
                    unsure_items.append(item)
                if item not in priority_areas:
                    priority_areas.append(item)
        unsure_counts = [
            int(row["unsure_about_count"])
            for row in source_rows
            if isinstance(row.get("unsure_about_count"), int)
            and not isinstance(row.get("unsure_about_count"), bool)
        ]
        unsure_count = max(unsure_counts) if unsure_counts else None
        has_confidence = any(row.get("has_confidence") for row in source_rows)
        has_unsure_answer = any(row.get("has_unsure_answer") for row in source_rows)
        if has_confidence and has_unsure_answer:
            signal_status = "complete"
        elif has_confidence or has_unsure_answer:
            signal_status = "partial"
        else:
            signal_status = "missing"
        distinct_counts = set(unsure_counts)
        # Order-insensitive: identical reservation sets reported in a
        # different order are agreement, not a conflict.
        distinct_item_sets = {
            frozenset(row.get("unsure_about") or [])
            for row in source_rows
            if row.get("unsure_about") is not None
        }
        signal_conflict = bool(
            len(set(confidence_values)) > 1
            or len(distinct_counts) > 1
            or len(distinct_item_sets) > 1
        )
        if signal_conflict:
            conflict_area = f"{label}: reconcile conflicting worker confidence signals"
            if conflict_area not in priority_areas:
                priority_areas.append(conflict_area)

        if confidence == "low" or (unsure_count or 0) > 0 or signal_conflict:
            attention = "deep"
        elif confidence == "medium" or signal_status == "partial":
            attention = "focused"
        else:
            attention = "baseline"
        rows.append(
            {
                "batch": label,
                "confidence": confidence,
                "unsure_about": unsure_items if not shared_oauth else None,
                "unsure_about_count": unsure_count,
                "signal_status": signal_status,
                "signal_conflict": signal_conflict,
                "sources": sorted({str(row["source"]) for row in source_rows}),
                "free_text_hidden": any(
                    bool(row.get("free_text_hidden")) for row in source_rows
                ),
                "attention": attention,
            }
        )

    if not rows or all(row["signal_status"] == "missing" for row in rows):
        overall_status = "absent"
    elif omitted_signal_rows or any(
        row["signal_status"] != "complete" for row in rows
    ):
        overall_status = "partial"
    else:
        overall_status = "present"

    header_lines = [
        "## Worker confidence triage (machine-produced; attach verbatim)",
        "Session: "
        f"{session_id[:MAX_REVIEW_CONFIDENCE_LABEL_CHARS]} | Branch: "
        f"{branch[:MAX_REVIEW_CONFIDENCE_LABEL_CHARS]} | Final head: "
        f"{final_head[:MAX_REVIEW_CONFIDENCE_LABEL_CHARS]}",
    ]
    if overall_status == "absent" and event_evidence_partial:
        header_lines.append(
            "- Worker confidence event evidence was partial or discarded during "
            "salvage; treat signals as unknown rather than unreported. Perform "
            "the full baseline review."
        )
    elif overall_status == "absent":
        header_lines.append(
            "- No worker confidence signal was reported. Perform the full baseline review; "
            "absence is not evidence of safety."
        )
    elif event_evidence_partial:
        header_lines.append(
            "- Some worker confidence event evidence was partial or discarded "
            "during salvage; the rows below may be incomplete. Missing signals "
            "are unknown, never asserted-clean."
        )
    if omitted_signal_rows:
        header_lines.append(
            f"- {omitted_signal_rows} confidence row(s) exceeded the display bound. "
            "Perform full baseline review for every omitted row; omission is not evidence of safety."
        )
    row_lines: list[str] = []
    for row in rows:
        display_label = str(row["batch"])
        if len(display_label) > MAX_REVIEW_CONFIDENCE_LABEL_CHARS:
            display_label = (
                display_label[: MAX_REVIEW_CONFIDENCE_LABEL_CHARS - 3] + "..."
            )
        confidence_text = row["confidence"] or "not reported"
        if row["unsure_about"]:
            reservation_text = "; ".join(row["unsure_about"])
        elif row["unsure_about_count"] is None:
            reservation_text = "unsure_about not reported"
        elif row["unsure_about_count"] == 0:
            reservation_text = "worker asserted no reservations"
        elif row["free_text_hidden"]:
            reservation_text = (
                f"{row['unsure_about_count']} reservation(s); text hidden by shared-OAuth safety"
            )
        else:
            reservation_text = f"{row['unsure_about_count']} reservation(s)"
        if len(reservation_text) > MAX_REVIEW_CONFIDENCE_RESERVATION_CHARS:
            items = row["unsure_about"] or []
            hidden_items = 0
            if items:
                # Count the reservations that will not appear in full so the
                # truncation states what it hid instead of a bare ellipsis.
                consumed = 0
                shown = 0
                for position, item in enumerate(items):
                    consumed += (2 if position else 0) + len(item)
                    if consumed > MAX_REVIEW_CONFIDENCE_RESERVATION_CHARS - 40:
                        break
                    shown = position + 1
                hidden_items = len(items) - shown
            suffix = (
                f"... (+{hidden_items} of {len(items)} reservation(s) hidden)"
                if hidden_items
                else "..."
            )
            reservation_text = (
                reservation_text[
                    : MAX_REVIEW_CONFIDENCE_RESERVATION_CHARS - len(suffix)
                ]
                + suffix
            )
        conflict_text = "; CONFLICTING SOURCES" if row["signal_conflict"] else ""
        row_lines.append(
            f"- [{str(row['attention']).upper()}] {display_label}: confidence "
            f"{confidence_text}; {reservation_text}{conflict_text}."
        )
    footer_lines = [
        "Review rules:",
        "- Perform baseline review for every batch regardless of confidence.",
        "- Deep-review every low-confidence, flagged, hidden-reservation, or conflicting area.",
        "- Treat partial or missing signals as absent triage data, never as proof.",
        "- Confidence cannot skip gates, waive review, or change acceptance requirements.",
    ]
    review_prompt_block = "\n".join(header_lines + row_lines + footer_lines)
    # The per-row display bounds keep ordinary output well below this ceiling.
    # If pathological but valid identifiers still reach it, keep the
    # highest-attention rows that fit, say how many rows were dropped, and
    # preserve the mandatory policy — optional triage metadata never becomes a
    # completion gate.
    if len(review_prompt_block) > MAX_REVIEW_CONFIDENCE_PROMPT_CHARS:
        attention_rank = {"deep": 0, "focused": 1, "baseline": 2}
        prioritized = sorted(
            range(len(row_lines)),
            key=lambda position: (
                attention_rank.get(str(rows[position]["attention"]), 3),
                position,
            ),
        )
        dropped_line_bound = len(
            f"- {len(row_lines)} lower-attention confidence row(s) dropped to fit "
            "the display bound. Perform full baseline review for every dropped row; "
            "omission is not evidence of safety."
        )
        budget = (
            MAX_REVIEW_CONFIDENCE_PROMPT_CHARS
            - len("\n".join(header_lines + footer_lines))
            - dropped_line_bound
            - 2
        )
        kept: set[int] = set()
        for position in prioritized:
            cost = len(row_lines[position]) + 1
            if cost > budget:
                continue
            budget -= cost
            kept.add(position)
        dropped_rows = len(row_lines) - len(kept)
        kept_lines = [
            line
            for position, line in enumerate(row_lines)
            if position in kept
        ]
        dropped_line = (
            f"- {dropped_rows} lower-attention confidence row(s) dropped to fit "
            "the display bound. Perform full baseline review for every dropped row; "
            "omission is not evidence of safety."
        )
        review_prompt_block = "\n".join(
            header_lines + kept_lines + [dropped_line] + footer_lines
        )
    calibration_trend: dict[str, Any] | None = None
    if repo_root is not None:
        try:
            from .confidence_sidecar import (  # noqa: PLC0415
                calibration_trend_summary,
            )

            calibration_trend = calibration_trend_summary(Path(repo_root))
        except Exception:
            calibration_trend = None
    trend_lines: list[str] = []
    if calibration_trend and int(calibration_trend.get("sample_size") or 0) > 0:
        trend_lines = [
            "Cross-run calibration trend (triage only; never authority):",
            f"- sample_size={calibration_trend.get('sample_size')}; "
            f"high_confidence_product_blockers="
            f"{calibration_trend.get('high_confidence_product_blockers')}",
        ]
    if trend_lines:
        # Insert before the mandatory review rules footer.
        prompt_parts = review_prompt_block.split("Review rules:")
        if len(prompt_parts) == 2:
            review_prompt_block = (
                prompt_parts[0]
                + "\n".join(trend_lines)
                + "\nReview rules:"
                + prompt_parts[1]
            )
    return {
        "schema": "elves-worker-confidence-review-v1",
        "session_id": session_id,
        "branch": branch,
        "final_head": final_head,
        "signal_status": overall_status,
        "event_evidence_partial": bool(event_evidence_partial),
        "lowest_confidence": lowest_confidence,
        "signals": rows,
        "omitted_signal_rows": omitted_signal_rows,
        "priority_areas": priority_areas,
        "calibration_trend": calibration_trend,
        "review_policy": {
            "baseline_review_required": True,
            "confidence_can_reduce_scope": False,
            "flagged_areas_require_deeper_pass": True,
            "missing_signal_falls_back_to_full_review": True,
        },
        "review_prompt_block": review_prompt_block,
        "merge_authority": False,
    }


def validate_event(
    event: Mapping[str, Any],
    *,
    expected_session_id: str | None = None,
    expected_branch: str | None = None,
    expected_start_head: str | None = None,
    seen_terminal: bool = False,
    expected_high_risk_checkpoints: Sequence[str] | None = None,
    seen_high_risk_checkpoints: Sequence[str] | None = None,
    exact_secret_values: frozenset[str] | set[str] | tuple[str, ...] | None = None,
    credential_grant_state: "FullRunState | None" = None,
    allow_projected_unsure_count: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        _assert_bounded_json_structure(event, label="event")
    except StorageError as exc:
        return [exc.message]
    secret_detected = _contains_full_run_secret(
        event,
        exact_values=exact_secret_values,
        credential_grant_state=credential_grant_state,
    )
    if secret_detected:
        errors.append("event contains secret-shaped content")
    for key in ("timestamp", "session_id", "branch", "head", "batch", "type", "summary"):
        if key not in event:
            errors.append(f"missing event field: {key}")
    timestamp = event.get("timestamp")
    if not _is_utc_iso8601(timestamp):
        errors.append("timestamp must be a UTC ISO-8601 string")
    else:
        parsed_timestamp = datetime.fromisoformat(
            str(timestamp).replace("Z", "+00:00")
        )
        if (
            parsed_timestamp - datetime.now(timezone.utc)
        ).total_seconds() > MAX_EVENT_FUTURE_SKEW_SECONDS:
            errors.append("timestamp exceeds allowed future clock skew")
    for key in ("session_id", "branch", "type", "summary"):
        if key in event and not isinstance(event.get(key), str):
            errors.append(f"{key} must be a string")
    for key in ("session_id", "branch"):
        if isinstance(event.get(key), str) and not event.get(key).strip():
            errors.append(f"{key} must be nonempty")
    if "head" in event and not _is_sha1(event.get("head")):
        errors.append("head must be an exact 40-character commit SHA")
    batch = event.get("batch")
    if isinstance(batch, bool) or not isinstance(batch, int) or batch < 0:
        errors.append("batch must be a non-boolean integer >= 0")
    etype = event.get("type")
    if etype not in EVENT_TYPES:
        errors.append("invalid event type")
    checkpoint_id = event.get("checkpoint_id")
    if etype == "high_risk_checkpoint":
        if (
            not isinstance(checkpoint_id, str)
            or not _HIGH_RISK_CHECKPOINT_ID_RE.fullmatch(checkpoint_id)
        ):
            errors.append("high-risk checkpoint event requires a stable checkpoint_id")
        else:
            if (
                expected_high_risk_checkpoints is not None
                and checkpoint_id not in expected_high_risk_checkpoints
            ):
                errors.append("high-risk checkpoint was not staged in the packet")
            if (
                seen_high_risk_checkpoints is not None
                and checkpoint_id in seen_high_risk_checkpoints
            ):
                errors.append("high-risk checkpoint event is duplicated")
    elif checkpoint_id is not None:
        errors.append("checkpoint_id is only valid on high-risk checkpoint events")
    change_id = event.get("change_id")
    change_kind = event.get("change_kind")
    if etype == "material_scope_or_assumption_change":
        if (
            not isinstance(change_id, str)
            or not _MATERIAL_CHANGE_ID_RE.fullmatch(change_id)
        ):
            errors.append("material change event requires a stable change_id")
        if change_kind not in _MATERIAL_CHANGE_KINDS:
            errors.append("material change event requires change_kind scope or assumption")
    else:
        if change_id is not None:
            errors.append("change_id is only valid on material change events")
        if change_kind is not None:
            errors.append("change_kind is only valid on material change events")
    summary_value = event.get("summary")
    summary = summary_value if isinstance(summary_value, str) else ""
    if len(summary) > 500:
        errors.append("summary exceeds 500 chars")
    lowered = summary.lower()
    if not secret_detected and any(
        needle in lowered for needle in _SUMMARY_SECRET_NEEDLES
    ):
        errors.append("event contains secret-shaped content")
    _validate_confidence_fields(
        event,
        errors,
        allow_projected_unsure_count=allow_projected_unsure_count,
    )
    if expected_session_id and event.get("session_id") != expected_session_id:
        errors.append("event session_id mismatch")
    if expected_branch and event.get("branch") != expected_branch:
        errors.append("event branch mismatch")
    # Provider-session discovery is host-owned transport evidence. A very fast
    # Devin process can write its terminal event before the parked monitor gets
    # its first chance to bind the provider UUID, so these two informational
    # host events may legitimately follow the worker terminal event. All worker
    # lifecycle events remain forbidden after terminal.
    if seen_terminal and etype not in DEVIN_HOST_EVENT_TYPES:
        errors.append("event appears after terminal event")
    return errors


def validate_run_report(
    report: Mapping[str, Any],
    *,
    expected_session_id: str | None = None,
    expected_branch: str | None = None,
    expected_start_head: str | None = None,
    require_complete_acceptance: bool = False,
    expected_run_id: str | None = None,
    expected_attempt: int | None = None,
    expected_acceptance_criteria: Mapping[str, str] | None = None,
    exact_secret_values: frozenset[str] | set[str] | tuple[str, ...] | None = None,
    credential_grant_state: "FullRunState | None" = None,
) -> list[str]:
    errors: list[str] = []
    try:
        _assert_bounded_json_structure(report, label="run report")
    except StorageError as exc:
        return [exc.message]
    if _contains_full_run_secret(
        report,
        exact_values=exact_secret_values,
        credential_grant_state=credential_grant_state,
    ):
        errors.append("report contains secret-shaped content")
    required = (
        "run_id",
        "attempt",
        "session_id",
        "branch",
        "start_head",
        "final_head",
        "status",
        "batches",
        "acceptance",
        "commits",
    )
    for key in required:
        if key not in report:
            errors.append(f"missing report field: {key}")
    for key in ("run_id", "session_id", "branch", "start_head", "final_head", "status"):
        if key in report and not isinstance(report.get(key), str):
            errors.append(f"{key} must be a string")
    for key in ("run_id", "session_id", "branch"):
        if isinstance(report.get(key), str) and not report.get(key).strip():
            errors.append(f"{key} must be nonempty")
    if "start_head" in report and not _is_sha1(report.get("start_head")):
        errors.append("start_head must be an exact 40-character commit SHA")
    final_head_value = report.get("final_head")
    if final_head_value and not _is_sha1(final_head_value):
        errors.append("final_head must be empty or an exact 40-character commit SHA")
    status = report.get("status")
    if status not in _REPORT_STATUSES:
        errors.append("invalid report status")
    if expected_session_id and report.get("session_id") != expected_session_id:
        errors.append("report session_id mismatch")
    if expected_branch and report.get("branch") != expected_branch:
        errors.append("report branch mismatch")
    if expected_start_head and report.get("start_head") != expected_start_head:
        errors.append("report start_head mismatch")
    if expected_run_id and report.get("run_id") != expected_run_id:
        errors.append("report run_id mismatch")
    attempt = report.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        errors.append("attempt must be a non-boolean integer >= 1")
    if expected_attempt is not None and report.get("attempt") != expected_attempt:
        errors.append("report attempt mismatch")
    # List-typed evidence surfaces must actually be lists.
    for list_key in ("batches", "acceptance", "commits", "blockers", "docs_changed", "remaining_risks"):
        if list_key in report and report[list_key] is not None and not isinstance(
            report[list_key], list
        ):
            errors.append(f"{list_key} must be a list")
    final_head = str(report.get("final_head") or "").strip()
    if status == "complete" and not final_head:
        errors.append("complete report requires nonempty final_head")
    if status == "complete":
        for key in ("batches", "commits"):
            value = report.get(key)
            if not isinstance(value, list) or not value:
                errors.append(f"complete report requires non-empty {key}")
        for key in ("blockers", "remaining_risks"):
            value = report.get(key)
            if value:
                errors.append(f"complete report requires empty {key}")
    batches = report.get("batches")
    if isinstance(batches, list):
        for i, item in enumerate(batches):
            if not isinstance(item, dict):
                errors.append(f"batches[{i}] must be an object")
                continue
            if status == "complete":
                for field_name in ("id", "status", "evidence"):
                    if field_name not in item:
                        errors.append(f"batches[{i}] missing {field_name}")
            batch_id = item.get("id")
            batch_status = item.get("status")
            batch_evidence = item.get("evidence")
            if "id" in item and (
                not isinstance(batch_id, str) or not batch_id.strip()
            ):
                errors.append(f"batches[{i}].id must be a nonempty string")
            if "status" in item and (
                not isinstance(batch_status, str) or not batch_status.strip()
            ):
                errors.append(f"batches[{i}].status must be a nonempty string")
            if "evidence" in item and not isinstance(batch_evidence, str):
                errors.append(f"batches[{i}].evidence must be a string")
            _validate_confidence_fields(item, errors, prefix=f"batches[{i}].")
            if status == "complete":
                if batch_status != "complete":
                    errors.append(f"batches[{i}].status must be complete")
                if not isinstance(batch_evidence, str) or not batch_evidence.strip():
                    errors.append(f"batches[{i}].evidence must be nonempty")
    commits = report.get("commits")
    if isinstance(commits, list):
        for i, item in enumerate(commits):
            if isinstance(item, str):
                if not _is_sha1(item):
                    errors.append(f"commits[{i}] must be an exact 40-character SHA")
                continue
            if not isinstance(item, dict):
                errors.append(f"commits[{i}] must be a SHA string or object")
                continue
            sha = item.get("sha")
            subject = item.get("subject")
            if not _is_sha1(sha):
                errors.append(f"commits[{i}].sha must be an exact 40-character SHA")
            if not isinstance(subject, str) or not subject.strip():
                errors.append(f"commits[{i}].subject must be a nonempty string")
    acceptance = report.get("acceptance")
    if acceptance is not None and not isinstance(acceptance, list):
        errors.append("acceptance must be a list")
    elif isinstance(acceptance, list):
        if status == "complete" and not acceptance:
            errors.append("complete report requires non-empty acceptance")
        seen_ids: set[str] = set()
        for i, item in enumerate(acceptance):
            if not isinstance(item, dict):
                errors.append(f"acceptance[{i}] must be an object")
                continue
            for field_name in ("id", "criterion", "met", "evidence"):
                if field_name not in item:
                    errors.append(f"acceptance[{i}] missing {field_name}")
            aid = str(item.get("id") or "").strip()
            criterion = str(item.get("criterion") or "").strip()
            if "id" in item and not isinstance(item.get("id"), str):
                errors.append(f"acceptance[{i}].id must be a string")
            if "criterion" in item and not isinstance(item.get("criterion"), str):
                errors.append(f"acceptance[{i}].criterion must be a string")
            if "met" in item and not isinstance(item.get("met"), bool):
                errors.append(f"acceptance[{i}].met must be a boolean")
            if "evidence" in item and not isinstance(item.get("evidence"), str):
                errors.append(f"acceptance[{i}].evidence must be a string")
            if status == "complete" and not aid:
                errors.append(f"acceptance[{i}] requires nonempty exact id")
            if status == "complete" and not criterion:
                errors.append(f"acceptance[{i}] requires nonempty criterion")
            if status == "complete" and item.get("met") is not True:
                errors.append(f"acceptance[{i}] must be met for complete report")
            if status == "complete" and not item.get("evidence"):
                errors.append(f"acceptance[{i}] requires evidence for complete report")
            if aid:
                if aid in seen_ids:
                    errors.append("duplicate acceptance id")
                seen_ids.add(aid)
            if item.get("met") is True and not item.get("evidence"):
                errors.append(f"acceptance[{i}] met without evidence")
        if status == "complete" and expected_acceptance_criteria is not None:
            observed_criteria = {
                str(item.get("id")): item.get("criterion")
                for item in acceptance
                if isinstance(item, Mapping) and isinstance(item.get("id"), str)
            }
            if set(observed_criteria) != set(expected_acceptance_criteria):
                errors.append(
                    "report acceptance ids do not exactly match staged criteria"
                )
            for acceptance_id in sorted(
                set(observed_criteria) & set(expected_acceptance_criteria)
            ):
                if observed_criteria[acceptance_id] != expected_acceptance_criteria[acceptance_id]:
                    errors.append(
                        f"report acceptance criterion text mismatch for {acceptance_id}"
                    )
    return errors


@dataclass
class ProcessFingerprint:
    pid: int
    pgid: int | None
    start_time: str | None
    executable: str | None
    session_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProcessFingerprint":
        if not isinstance(data, Mapping):
            raise TypeError("process fingerprint must be a mapping")
        pid = data.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise TypeError("process fingerprint pid must be a positive integer")
        pgid = data.get("pgid")
        if pgid is not None and (
            not isinstance(pgid, int) or isinstance(pgid, bool) or pgid <= 0
        ):
            raise TypeError("process fingerprint pgid must be a positive integer or null")
        for field_name in ("start_time", "executable", "session_id"):
            value = data.get(field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"process fingerprint {field_name} must be a string or null")
        return cls(
            pid=pid,
            pgid=pgid,
            start_time=data.get("start_time"),
            executable=data.get("executable"),
            session_id=str(data.get("session_id") or ""),
        )


@dataclass
class FullRunState:
    session_id: str
    branch: str
    start_head: str
    worktree: str
    # ``packet_path`` remains the immutable source location staged by the host.
    # The provider consumes only ``staged_packet_path``, a private copy whose
    # bytes and parsed acceptance contract are bound below at prepare time.
    packet_path: str
    staged_packet_path: str | None = None
    staged_packet_identity: dict[str, Any] | None = None
    packet_sha256: str | None = None
    packet_size: int | None = None
    goal_prompt_path: str | None = None
    goal_prompt_identity: dict[str, Any] | None = None
    goal_prompt_sha256: str | None = None
    goal_prompt_size: int | None = None
    # Private artifact locator is revalidated on every create/resume launch.
    # goal_behavioral_evidence is the safe normalized proof id only.
    goal_behavioral_artifact_path: str | None = None
    goal_behavioral_evidence: str | None = None
    packet_contract_sha256: str | None = None
    acceptance_criteria: dict[str, str] = field(default_factory=dict)
    acceptance_plan_path: str | None = None
    acceptance_plan_sha256: str | None = None
    acceptance_session_path: str | None = None
    acceptance_session_sha256: str | None = None
    acceptance_contract_sha256: str | None = None
    # Packet-bound driver wake gates. Worker events may only name staged IDs;
    # acknowledgements are host-owned and one-shot within an attempt.
    planned_high_risk_checkpoints: list[str] = field(default_factory=list)
    acknowledged_high_risk_checkpoints: list[str] = field(default_factory=list)
    pending_high_risk_checkpoint: str | None = None
    adapter: str = "grok-build"
    model: str = "auto"
    permission_mode: str = DEFAULT_PERMISSION_MODE
    effort: str = GROK_DEFAULT_EFFORT
    # Whether the persisted effort was explicitly requested by the operator;
    # a flagless resume prepare preserves an explicit value.
    effort_explicit: bool = False
    executable: str = DEFAULT_EXECUTABLE
    create_session: bool = True
    check: bool = False
    max_turns: int = 80
    output_format: str = "json"
    yolo: bool = True
    credential_grant_names: list[str] = field(
        default_factory=lambda: sorted(DEFAULT_CREDENTIAL_GRANT_NAMES)
    )
    credential_granted_names: list[str] = field(default_factory=list)
    credential_grant_digests: dict[str, str] = field(default_factory=dict)
    credential_grant_lengths: dict[str, int] = field(default_factory=dict)
    credential_grant_metadata_mac: str | None = None
    grok_auth_strategy: str | None = None
    github_push_auth_strategy: str | None = None
    # Private state only. The leaf inode is deliberately excluded because Grok
    # atomically replaces auth.json when rotating refresh tokens. Binding the
    # canonical path and safe parent identity survives those legitimate writes.
    grok_auth_path_identity: dict[str, Any] | None = None
    # Exact resolved provider identity proven during auth/capability preflight
    # and rechecked by the child supervisor immediately before process spawn.
    grok_executable_identity: dict[str, Any] | None = None
    devin_auth_strategy: str | None = None
    # Private state only. Binds the canonical source path identity for Devin CLI
    # config and credentials. Raw credential bytes are never stored here.
    devin_auth_identity: dict[str, Any] | None = None
    status: str = "pending"
    batch: int | None = None
    head: str | None = None
    pid: int | None = None
    pgid: int | None = None
    fingerprint: dict[str, Any] | None = None
    heartbeat_at: str | None = None
    launched_at: str | None = None
    completed_at: str | None = None
    blocker: str | None = None
    next_action: str | None = None
    # ``driver_monitor_mode`` is canonical. ``driver_contract`` remains a
    # compatibility alias and must carry the same machine value.
    driver_monitor_mode: str = "parked_monitor"
    driver_contract: str = "parked_monitor"
    notes: list[str] = field(default_factory=list)
    last_argv: list[str] = field(default_factory=list)
    # Fixture-only: path to python fixture script (never masquerades as Grok).
    fixture_script: str | None = None
    # Protected base/remote refs snapped at prepare; verified unchanged at finalization.
    # Trusted Lane A is policy trust, not an OS Git sandbox — movement still blocks readiness.
    protected_refs: dict[str, str] = field(default_factory=dict)
    launch_start_head: str | None = None
    origin_url: str | None = None
    origin_config_digest: str | None = None
    initial_remote_feature_tip: str | None = None
    acceptance_ids: list[str] = field(default_factory=list)
    attempt: int = 1
    supervision_token: str | None = None
    supervisor_executable: str | None = None
    supervision_canary_passed: bool = False
    closed_process_identity: dict[str, Any] | None = None
    interruption_evidence: dict[str, Any] | None = None
    process_history: list[dict[str, Any]] = field(default_factory=list)
    exit_code: int | None = None
    exit_sidecar_pid: int | None = None
    # Bounded monitor cache: event file size/digest and last remote-audit stamp.
    # Used so unchanged healthy polls stay incremental.
    monitor_cache: dict[str, Any] = field(default_factory=dict)
    # advertised_headless_entrypoint | headless_compatible_fallback | fixture | devin_prompt_file | unknown
    goal_launch_mode: str | None = None
    goal_entrypoint_advertised: bool = False
    goal_mode_behaviorally_verified: bool = False
    report_provenance: str | None = None
    # Devin CLI: exact provider session id captured from `devin list --format json`.
    provider_session_id: str | None = None
    # Absolute path to the full-run runtime directory (used for ATIF export, etc.).
    runtime_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FullRunState":
        if not isinstance(data, Mapping):
            raise TypeError("full-run state must be a mapping")
        required_strings = (
            "session_id",
            "branch",
            "start_head",
            "worktree",
            "packet_path",
        )
        for field_name in required_strings:
            value = data.get(field_name)
            if not isinstance(value, str) or not value:
                raise TypeError(f"{field_name} must be a non-empty string")
        nullable_strings = (
            "staged_packet_path",
            "packet_sha256",
            "goal_prompt_path",
            "goal_prompt_sha256",
            "goal_behavioral_artifact_path",
            "goal_behavioral_evidence",
            "packet_contract_sha256",
            "acceptance_plan_path",
            "acceptance_plan_sha256",
            "acceptance_session_path",
            "acceptance_session_sha256",
            "acceptance_contract_sha256",
            "credential_grant_metadata_mac",
            "grok_auth_strategy",
            "devin_auth_strategy",
            "github_push_auth_strategy",
            "head",
            "heartbeat_at",
            "launched_at",
            "completed_at",
            "blocker",
            "next_action",
            "fixture_script",
            "launch_start_head",
            "origin_url",
            "origin_config_digest",
            "initial_remote_feature_tip",
            "supervision_token",
            "supervisor_executable",
            "pending_high_risk_checkpoint",
            "goal_launch_mode",
            "report_provenance",
            "provider_session_id",
            "runtime_dir",
        )
        for field_name in nullable_strings:
            value = data.get(field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string or null")
        default_string_fields = (
            "adapter",
            "model",
            "permission_mode",
            "effort",
            "executable",
            "output_format",
            "status",
            "driver_monitor_mode",
            "driver_contract",
        )
        for field_name in default_string_fields:
            value = data.get(field_name)
            if field_name in data and (not isinstance(value, str) or not value):
                raise TypeError(f"{field_name} must be a non-empty string")
        for field_name in (
            "create_session", "check", "yolo", "effort_explicit",
            "supervision_canary_passed",
            "goal_entrypoint_advertised", "goal_mode_behaviorally_verified",
        ):
            value = data.get(field_name)
            if field_name in data and not isinstance(value, bool):
                raise TypeError(f"{field_name} must be a boolean")
        for field_name in ("max_turns", "attempt"):
            value = data.get(field_name)
            if field_name in data and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise TypeError(f"{field_name} must be a positive integer")
        for field_name in ("packet_size", "goal_prompt_size", "batch"):
            value = data.get(field_name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise TypeError(f"{field_name} must be a non-negative integer or null")
        for field_name in ("pid", "pgid", "exit_sidecar_pid"):
            value = data.get(field_name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise TypeError(f"{field_name} must be a positive integer or null")
        exit_code = data.get("exit_code")
        if exit_code is not None and (
            not isinstance(exit_code, int) or isinstance(exit_code, bool)
        ):
            raise TypeError("exit_code must be an integer or null")
        nullable_mapping_fields = (
            "staged_packet_identity",
            "goal_prompt_identity",
            "grok_auth_path_identity",
            "grok_executable_identity",
            "devin_auth_identity",
            "fingerprint",
            "closed_process_identity",
            "interruption_evidence",
        )
        for field_name in nullable_mapping_fields:
            value = data.get(field_name)
            if value is not None and not isinstance(value, Mapping):
                raise TypeError(f"{field_name} must be a mapping or null")
        default_mapping_fields = (
            "acceptance_criteria",
            "credential_grant_digests",
            "credential_grant_lengths",
            "protected_refs",
            "monitor_cache",
        )
        for field_name in default_mapping_fields:
            value = data.get(field_name)
            if field_name in data and not isinstance(value, Mapping):
                raise TypeError(f"{field_name} must be a mapping")
        string_list_fields = (
            "credential_grant_names",
            "credential_granted_names",
            "notes",
            "last_argv",
            "acceptance_ids",
            "planned_high_risk_checkpoints",
            "acknowledged_high_risk_checkpoints",
        )
        for field_name in string_list_fields:
            value = data.get(field_name)
            if field_name in data and (
                not isinstance(value, list)
                or not all(isinstance(item, str) for item in value)
            ):
                raise TypeError(f"{field_name} must be a string list")
        process_history = data.get("process_history")
        if "process_history" in data and (
            not isinstance(process_history, list)
            or not all(isinstance(item, Mapping) for item in process_history)
        ):
            raise TypeError("process_history must be a list of mappings")
        for field_name in (
            "acceptance_criteria",
            "credential_grant_digests",
            "protected_refs",
        ):
            value = data.get(field_name)
            if value is not None and not all(
                isinstance(key, str) and isinstance(item, str)
                for key, item in value.items()
            ):
                raise TypeError(f"{field_name} must be a string mapping")
        grant_lengths = data.get("credential_grant_lengths")
        if grant_lengths is not None and not all(
            isinstance(key, str)
            and isinstance(item, int)
            and not isinstance(item, bool)
            and item >= 0
            for key, item in grant_lengths.items()
        ):
            raise TypeError("credential_grant_lengths must map strings to non-negative integers")
        planned_checkpoints = data.get("planned_high_risk_checkpoints", [])
        acknowledged_checkpoints = data.get(
            "acknowledged_high_risk_checkpoints", []
        )
        pending_checkpoint = data.get("pending_high_risk_checkpoint")
        for label, values in (
            ("planned_high_risk_checkpoints", planned_checkpoints),
            ("acknowledged_high_risk_checkpoints", acknowledged_checkpoints),
        ):
            if (
                not isinstance(values, list)
                or len(values) > MAX_HIGH_RISK_CHECKPOINTS
                or len(values) != len(set(values))
                or any(
                    not isinstance(item, str)
                    or not _HIGH_RISK_CHECKPOINT_ID_RE.fullmatch(item)
                    for item in values
                )
            ):
                raise TypeError(f"{label} must contain unique checkpoint ids")
        if not set(acknowledged_checkpoints).issubset(set(planned_checkpoints)):
            raise TypeError("acknowledged checkpoints must be planned")
        if pending_checkpoint is not None and (
            not isinstance(pending_checkpoint, str)
            or pending_checkpoint not in planned_checkpoints
            or pending_checkpoint in acknowledged_checkpoints
        ):
            raise TypeError("pending checkpoint must be planned and unacknowledged")
        github_push_auth_strategy = data.get("github_push_auth_strategy")
        if (
            github_push_auth_strategy is not None
            and github_push_auth_strategy not in _GITHUB_PUSH_AUTH_STRATEGIES
        ):
            raise TypeError("github_push_auth_strategy is invalid")
        fingerprint = data.get("fingerprint")
        if fingerprint is not None:
            parsed_fingerprint = ProcessFingerprint.from_dict(fingerprint)
            if parsed_fingerprint.session_id != data["session_id"]:
                raise TypeError("process fingerprint session identity mismatch")
        known = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in data.items() if k in known}
        state = cls(**filtered)  # type: ignore[arg-type]
        state.driver_monitor_mode = "parked_monitor"
        state.driver_contract = state.driver_monitor_mode
        if state.launch_start_head is None:
            state.launch_start_head = state.start_head
        return state


def _process_start_time(pid: int) -> str | None:
    """Best-effort process start fingerprint (macOS/Linux)."""
    # Linux /proc start ticks are precise enough to distinguish rapid PID reuse;
    # prefer them over ps(1)'s second-granularity lstart rendering.
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        if stat_path.is_file():
            fields = stat_path.read_text().split()
            if len(fields) >= 22:
                return fields[21]
    except OSError:
        pass
    try:
        # macOS: ps -o lstart= -p PID
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except OSError:
        pass
    return None


def _darwin_proc_pidpath(pid: int) -> str | None:
    """Return the kernel-reported absolute path for a live Darwin process."""
    if sys.platform != "darwin" or pid <= 0:
        return None
    try:
        lib_name = ctypes.util.find_library("c")
        if not lib_name:
            return None
        lib = ctypes.CDLL(lib_name, use_errno=True)
        buf = ctypes.create_string_buffer(4096)
        # int proc_pidpath(int pid, void *buffer, uint32_t buffersize);
        proc_pidpath = getattr(lib, "proc_pidpath", None)
        if proc_pidpath is None:
            return None
        proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        proc_pidpath.restype = ctypes.c_int
        written = int(proc_pidpath(int(pid), buf, ctypes.c_uint32(len(buf))))
        if written <= 0:
            return None
        path = buf.value.decode("utf-8", errors="surrogateescape").strip()
        return path or None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _normalize_executable_path(path: str | None) -> str | None:
    """Normalize process paths so capture/verify comparisons stay stable.

    On macOS, ``sys.executable`` often points at a framework ``bin/pythonX.Y``
    shim while ``proc_pidpath``/``ps`` report the nested
    ``Python.app/Contents/MacOS/Python`` binary. Treat those as the same identity
    when they resolve under the same framework version root.
    """
    if not path:
        return None
    try:
        text = str(Path(str(path)).expanduser())
    except (OSError, RuntimeError, TypeError, ValueError):
        text = str(path)
    try:
        resolved = str(Path(text).resolve())
    except OSError:
        resolved = text
    # Collapse .../Python.framework/Versions/X/bin/python* and
    # .../Python.framework/Versions/X/Resources/Python.app/Contents/MacOS/Python
    # to the shared framework version directory when present.
    marker = "/Python.framework/Versions/"
    if marker in resolved:
        head, tail = resolved.split(marker, 1)
        version = tail.split("/", 1)[0]
        if version:
            return f"{head}{marker}{version}"
    return resolved


def _process_executable(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        pass
    # Prefer the kernel path on Darwin. ``ps -o command=`` is only a fallback and
    # can disagree with ``sys.executable`` (framework shim vs Python.app binary).
    darwin_path = _darwin_proc_pidpath(pid)
    if darwin_path:
        return darwin_path
    try:
        result = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split()[0]
    except OSError:
        pass
    return None


def capture_fingerprint(
    *,
    pid: int,
    pgid: int | None,
    session_id: str,
    executable_hint: str | None = None,
) -> ProcessFingerprint:
    # Brief retry so Darwin proc_pidpath/ps can observe a just-spawned child
    # before we fall back to the launcher's sys.executable hint.
    executable = _process_executable(pid)
    if not executable:
        for _ in range(5):
            time.sleep(0.02)
            executable = _process_executable(pid)
            if executable:
                break
    if not executable and executable_hint:
        executable = str(executable_hint)
    return ProcessFingerprint(
        pid=pid,
        pgid=pgid,
        start_time=_process_start_time(pid),
        executable=executable,
        session_id=session_id,
    )


def verify_fingerprint(
    fp: ProcessFingerprint | Mapping[str, Any],
    *,
    expected_session_id: str | None = None,
) -> tuple[bool, str]:
    if isinstance(fp, Mapping):
        try:
            fp = ProcessFingerprint.from_dict(fp)
        except (KeyError, TypeError, ValueError) as exc:
            return False, f"invalid fingerprint: {exc}"
    if fp.pid <= 0:
        return False, "invalid pid"
    if not str(fp.session_id or "").strip():
        return False, "session_id missing on fingerprint"
    if expected_session_id and str(fp.session_id) != str(expected_session_id):
        return False, "session_id mismatch on fingerprint"
    if not fp.start_time:
        return False, "process start_time missing from fingerprint"
    if not fp.executable:
        return False, "process executable missing from fingerprint"
    if fp.pgid is None:
        return False, "process pgid missing from fingerprint"
    try:
        os.kill(fp.pid, 0)
    except ProcessLookupError:
        return False, "pid not alive"
    except PermissionError:
        # Alive but not owned — still verify start time if possible.
        pass
    current_start = _process_start_time(fp.pid)
    if not current_start:
        return False, "live process start_time unreadable"
    if current_start != fp.start_time:
        return False, "pid start_time mismatch (reused PID)"
    current_exe = _process_executable(fp.pid)
    if not current_exe:
        return False, "live process executable unreadable"
    # Compare the observed command identity exactly when possible. Resolving only
    # basenames would accept a reused PID running a different same-named binary.
    # Darwin framework shims are normalized to the shared Versions/X root so a
    # launcher hint of bin/pythonX.Y still matches Python.app/Contents/MacOS/Python.
    expected_exe = _normalize_executable_path(fp.executable)
    observed_exe = _normalize_executable_path(current_exe)
    if not expected_exe or not observed_exe or expected_exe != observed_exe:
        return False, "pid executable mismatch"
    # PGID membership: stored pgid must match live process group of the PID.
    if fp.pgid is not None:
        try:
            live_pgid = os.getpgid(fp.pid)
            if int(live_pgid) != int(fp.pgid):
                return False, "pgid membership mismatch"
        except OSError:
            return False, "pgid membership unreadable"
    return True, "ok"


def _signal_verified_supervisor(
    fingerprint: Mapping[str, Any],
    *,
    expected_session_id: str,
    signum: int,
) -> bool:
    """Signal only through a kernel-bound pidfd; numeric PID signaling is forbidden."""
    if not (
        sys.platform.startswith("linux")
        and hasattr(os, "pidfd_open")
        and hasattr(signal, "pidfd_send_signal")
    ):
        raise ValidationIssue(
            "full_run_atomic_signal_unavailable",
            "This platform has no kernel-bound process signal handle; use the private supervisor stop request",
        )
    try:
        pid = int(fingerprint.get("pid") or 0)
    except (TypeError, ValueError) as exc:
        raise ValidationIssue(
            "full_run_fingerprint_mismatch",
            "Refusing signal: supervisor fingerprint PID is invalid",
        ) from exc
    if pid <= 0:
        raise ValidationIssue(
            "full_run_fingerprint_mismatch",
            "Refusing signal: supervisor fingerprint PID is invalid",
        )

    ok, reason = verify_fingerprint(
        fingerprint,
        expected_session_id=expected_session_id,
    )
    if not ok:
        if reason == "pid not alive":
            return False
        raise ValidationIssue(
            "full_run_fingerprint_mismatch",
            f"Refusing signal: {reason}",
            hint="PID may have been reused; investigate before signaling",
        )

    pidfd: int | None = None
    try:
        try:
            pidfd = os.pidfd_open(pid, 0)
        except ProcessLookupError:
            return False
        except OSError as exc:
            raise ValidationIssue(
                "full_run_pidfd_unavailable",
                f"Cannot bind the live supervisor process handle: {type(exc).__name__}",
            ) from exc

        # Revalidate after acquiring the kernel-bound handle. This rejects reuse
        # between the first liveness probe and the signal operation.
        ok, reason = verify_fingerprint(
            fingerprint,
            expected_session_id=expected_session_id,
        )
        if not ok:
            if reason == "pid not alive":
                return False
            raise ValidationIssue(
                "full_run_fingerprint_mismatch",
                f"Refusing signal after identity recheck: {reason}",
                hint="PID may have been reused; investigate before signaling",
            )

        try:
            signal.pidfd_send_signal(pidfd, signum)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError) as exc:
            raise ValidationIssue(
                "full_run_signal_failed",
                f"Unable to signal the verified supervisor: {type(exc).__name__}",
            ) from exc
        return True
    finally:
        if pidfd is not None:
            os.close(pidfd)


def read_exit_record(
    root: Path,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any] | None:
    """Host-owned exit sidecar record written after the provider process exits."""
    path = Path(root) / "exit_record.json"
    if repo_root is not None:
        if not repo_regular_file_exists(Path(repo_root), path):
            return None
    elif not path.exists() and not path.is_symlink():
        return None
    # Malformed data is materially different from an absent record: callers
    # must wake/fail instead of parking forever after a corrupted provider exit.
    return _read_bounded_json_object(
        path,
        label="exit record",
        repo_root=repo_root,
    )


def _validate_exit_record(
    record: Mapping[str, Any],
    state: FullRunState,
) -> list[str]:
    """Validate the durable record against launcher-owned supervisor identity."""
    errors: list[str] = []
    if str(record.get("session_id") or "") != state.session_id:
        errors.append("exit record session_id mismatch")
    try:
        if int(record.get("pid") or 0) != int(state.pid or 0):
            errors.append("exit record pid mismatch")
    except (TypeError, ValueError):
        errors.append("exit record pid invalid")
    try:
        if int(record.get("pgid") or 0) != int(state.pgid or 0):
            errors.append("exit record pgid mismatch")
    except (TypeError, ValueError):
        errors.append("exit record pgid invalid")

    expected_provider = str((state.last_argv or [state.executable])[0] or "")
    if str(record.get("provider_executable") or "") != expected_provider:
        errors.append("exit record provider executable mismatch")

    exit_code = record.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        errors.append("exit record requires an integer exit_code")
    if record.get("attempt") != state.attempt:
        errors.append("exit record attempt mismatch")
    if record.get("supervision_marker") != _descendant_supervision_marker(state):
        errors.append("exit record supervision marker mismatch")
    if record.get("descendants_absent") is not True:
        errors.append("exit record does not prove recursive descendant absence")
    if record.get("supervision_error") not in {None, ""}:
        errors.append("exit record reports recursive supervision failure")

    observed_fp = record.get("fingerprint")
    expected_fp = state.fingerprint or {}
    if not isinstance(observed_fp, Mapping):
        errors.append("exit record fingerprint missing")
    else:
        for field_name in ("pid", "pgid", "start_time", "executable", "session_id"):
            if observed_fp.get(field_name) != expected_fp.get(field_name):
                errors.append(f"exit record fingerprint {field_name} mismatch")
    return errors


def _reap_supervisor_if_child(pid: int | None) -> None:
    """Best-effort in-process reap; separate monitor CLIs are not the parent."""
    if not pid:
        return
    try:
        os.waitpid(int(pid), os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def write_exit_record(
    root: Path,
    record: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
) -> Path:
    path = Path(root) / "exit_record.json"
    payload = dict(record)
    payload.setdefault("completed_at", _utc_now())
    atomic_write_json(path, payload, repo_root=repo_root)
    return path


# The supervisor program lives in provider_supervisor.py as a real module; the
# child still receives its exact source text (byte-identical) via `-c`.
_PROVIDER_SUPERVISOR_PATH = Path(__file__).resolve().parent.parent / "provider_supervisor.py"


def _provider_supervisor_script() -> str:
    source = _PROVIDER_SUPERVISOR_PATH.read_text(encoding="utf-8")
    marker = '\n"""\n\n'
    index = source.find(marker)
    if index < 0:
        raise ValidationIssue(
            "full_run_supervisor_source_invalid",
            "provider_supervisor.py must start with its module docstring",
            path=str(_PROVIDER_SUPERVISOR_PATH),
        )
    # The pre-extraction literal began with a newline (r""" opened, then \n);
    # preserve it so child tracebacks keep their historical line numbers.
    return "\n" + source[index + len(marker):]



def _provider_supervisor_argv(
    *,
    root: Path,
    session_id: str,
    provider_argv: Sequence[str],
    attempt: int,
    supervisor_executable: str,
    staged_packet_path: str,
    staged_packet_identity: Mapping[str, Any],
    packet_sha256: str,
    packet_size: int,
    provider_executable_identity: Mapping[str, Any] | None = None,
) -> list[str]:
    """Build a parent supervisor without putting its signaling token on argv."""
    return [
        sys.executable,
        "-c",
        _provider_supervisor_script(),
        str(root / "exit_record.json"),
        str(root / "supervisor.fingerprint.json"),
        session_id,
        json.dumps(list(provider_argv)),
        str(attempt),
        supervisor_executable,
        str(MAX_STOP_REQUEST_BYTES),
        json.dumps(dict(provider_executable_identity or {}), sort_keys=True),
        staged_packet_path,
        json.dumps(dict(staged_packet_identity), sort_keys=True),
        packet_sha256,
        str(packet_size),
        str(MAX_PACKET_BYTES),
    ]


def _handoff_supervision_secret(
    proc: subprocess.Popen[bytes],
    state: FullRunState,
) -> None:
    """Release a staged supervisor with one bounded secret, never a partial payload."""
    stream = proc.stdin
    if stream is None:
        try:
            proc.kill()
            proc.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise _PreTransferHandoffError(
            RuntimeError("supervisor stdin channel missing")
        )
    try:
        payload = (_supervision_secret(state) + "\n").encode("ascii")
        descriptor = stream.fileno()
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short supervision secret write")
            offset += written
    except BaseException as exc:
        # Until the complete payload and EOF arrive, the child is blocked before
        # provider spawn. Kill and reap that exact child before closing the pipe.
        try:
            proc.kill()
        except OSError:
            pass
        try:
            stream.close()
        except OSError:
            pass
        finally:
            proc.stdin = None
        try:
            proc.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise _PreTransferHandoffError(exc) from exc
    try:
        # EOF is the commit point: only after the complete fixed-size payload is
        # written can closing stdin release the child into provider spawn.
        stream.close()
    except OSError:
        # Close/EOF delivery is ambiguous. Preserve durable ownership so monitor
        # or stop can observe whichever side of the commit point occurred.
        pass
    finally:
        proc.stdin = None


def _origin_push_auth_kind(origin_url: str) -> str:
    """Classify the one supported authenticated push boundary.

    Local/file remotes need no credential projection and remain useful for
    deterministic tests. GitHub HTTPS receives an explicit token-backed helper.
    Every other network transport fails closed because the isolated worker has
    neither host SSH-agent access nor host Git credential configuration.
    """
    raw = str(origin_url or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme == "https" and (parsed.hostname or "").lower() == "github.com":
        return "github_https"
    if parsed.scheme == "file":
        return "local"
    if not parsed.scheme and not re.match(r"^[^/@:]+@[^/:]+:", raw):
        return "local"
    return "unsupported"


def _read_host_git_identity_value(
    worktree: Path,
    key: str,
    *,
    parent_env: Mapping[str, str] | None = None,
) -> str:
    """Resolve one explicit host Git identity field without allowing guessing."""
    parent = dict(parent_env if parent_env is not None else os.environ)
    try:
        result = run_git(
            worktree,
            ["config", "--get", key],
            check=False,
            text=False,
            env=parent,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationIssue(
            "full_run_git_identity_unavailable",
            "Cannot resolve an explicit Git commit identity for the isolated worker",
        ) from exc
    raw = bytes(result.stdout or b"")
    value = raw.strip()
    if (
        result.returncode != 0
        or not value
        or len(raw) > MAX_GIT_IDENTITY_BYTES
        or any(byte < 32 or byte == 127 for byte in value)
    ):
        raise ValidationIssue(
            "full_run_git_identity_unavailable",
            "Trusted branch progress requires explicit Git user.name and user.email values",
            hint="Configure Git user.name and user.email before launching the worker",
        )
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationIssue(
            "full_run_git_identity_unavailable",
            "Configured Git commit identity has an invalid encoding",
        ) from exc
    if "<" in decoded or ">" in decoded:
        raise ValidationIssue(
            "full_run_git_identity_invalid",
            "Configured Git commit identity contains forbidden delimiters",
        )
    return decoded


def _configure_git_commit_identity(
    state: FullRunState,
    launch_env: dict[str, str],
    *,
    parent_env: Mapping[str, str] | None = None,
) -> None:
    """Bind the host's explicit author identity into an otherwise isolated env."""
    worktree = Path(state.worktree)
    name = _read_host_git_identity_value(
        worktree,
        "user.name",
        parent_env=parent_env,
    )
    email = _read_host_git_identity_value(
        worktree,
        "user.email",
        parent_env=parent_env,
    )
    launch_env["GIT_AUTHOR_NAME"] = name
    launch_env["GIT_AUTHOR_EMAIL"] = email
    launch_env["GIT_COMMITTER_NAME"] = name
    launch_env["GIT_COMMITTER_EMAIL"] = email


def _read_host_github_token(
    parent_env: Mapping[str, str] | None = None,
) -> str:
    """Read one host gh token privately; never include its bytes in diagnostics."""
    parent = dict(parent_env if parent_env is not None else os.environ)
    executable = shutil.which("gh", path=parent.get("PATH"))
    if not executable:
        raise ValidationIssue(
            "full_run_github_push_auth_unavailable",
            "Explicit GitHub push projection requires an authenticated gh CLI",
            hint="Run `gh auth login`, or explicitly grant GH_TOKEN/GITHUB_TOKEN by name",
        )
    try:
        result = subprocess.run(
            [executable, "auth", "token", "--hostname", "github.com"],
            env=parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationIssue(
            "full_run_github_push_auth_unavailable",
            "Host GitHub credential lookup failed",
        ) from exc
    raw = bytes(result.stdout or b"")
    token = raw.strip()
    if (
        result.returncode != 0
        or not token
        or len(raw) > MAX_GITHUB_TOKEN_BYTES
        or any(byte <= 32 or byte == 127 for byte in token)
    ):
        raise ValidationIssue(
            "full_run_github_push_auth_unavailable",
            "Host gh CLI did not return one bounded noninteractive credential",
            hint="Run `gh auth status --hostname github.com` before launching",
        )
    try:
        return token.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationIssue(
            "full_run_github_push_auth_unavailable",
            "Host gh CLI returned an invalid credential encoding",
        ) from exc


def _configure_github_push_auth(
    state: FullRunState,
    launch_env: dict[str, str],
    *,
    grant_github_push: bool,
    parent_env: Mapping[str, str] | None = None,
) -> None:
    """Project one explicit GitHub HTTPS push capability into isolated Lane A."""
    kind = _origin_push_auth_kind(str(state.origin_url or ""))
    if kind == "local":
        if state.github_push_auth_strategy is not None:
            raise ValidationIssue(
                "full_run_github_push_auth_strategy_changed",
                "Resume origin no longer matches the staged GitHub push strategy",
            )
        if grant_github_push:
            raise ValidationIssue(
                "full_run_github_push_auth_not_applicable",
                "GitHub push projection is only valid for a GitHub HTTPS origin",
            )
        return
    if kind != "github_https":
        raise ValidationIssue(
            "full_run_git_push_transport_unsupported",
            "Isolated branch-progress pushes support local remotes or GitHub HTTPS only",
            hint="Use a non-credentialed https://github.com origin for delegated GitHub pushes",
        )

    present_names = [
        name for name in _GITHUB_PUSH_TOKEN_NAMES if launch_env.get(name)
    ]
    strategy = state.github_push_auth_strategy
    if strategy is not None and strategy not in _GITHUB_PUSH_AUTH_STRATEGIES:
        raise ValidationIssue(
            "full_run_github_push_auth_strategy_changed",
            "Persisted GitHub push strategy is invalid",
        )

    if strategy == "host_gh_token":
        token = _read_host_github_token(parent_env)
        launch_env.pop("GITHUB_TOKEN", None)
        launch_env["GH_TOKEN"] = token
        state.credential_grant_names = sorted(
            {*state.credential_grant_names, "GH_TOKEN"}
        )
    elif strategy in {"env_gh_token", "env_github_token"}:
        if grant_github_push:
            raise ValidationIssue(
                "full_run_github_push_auth_strategy_changed",
                "Resume must preserve the explicitly granted GitHub token strategy",
            )
        expected_name = (
            "GH_TOKEN" if strategy == "env_gh_token" else "GITHUB_TOKEN"
        )
        if present_names != [expected_name]:
            raise ValidationIssue(
                "full_run_github_push_auth_required",
                "Resume requires the exact originally granted GitHub token name",
            )
    elif grant_github_push:
        if present_names:
            raise ValidationIssue(
                "full_run_github_push_auth_ambiguous",
                "Choose host gh projection or one explicit GitHub token grant, not both",
            )
        token = _read_host_github_token(parent_env)
        launch_env["GH_TOKEN"] = token
        state.credential_grant_names = sorted(
            {*state.credential_grant_names, "GH_TOKEN"}
        )
        state.github_push_auth_strategy = "host_gh_token"
    else:
        if len(present_names) != 1:
            raise ValidationIssue(
                (
                    "full_run_github_push_auth_ambiguous"
                    if present_names
                    else "full_run_github_push_auth_required"
                ),
                "GitHub HTTPS branch progress requires one explicit push credential route",
                hint=(
                    "Use --grant-github-push for host gh auth, or grant exactly one "
                    "of GH_TOKEN/GITHUB_TOKEN by name"
                ),
            )
        state.github_push_auth_strategy = (
            "env_gh_token"
            if present_names[0] == "GH_TOKEN"
            else "env_github_token"
        )

    # Reset any inherited/repository helper chain, then install one helper that
    # reads the token only from the private child environment. The helper text
    # contains no credential value and terminal prompting is disabled.
    launch_env["GIT_TERMINAL_PROMPT"] = "0"
    launch_env["GIT_CONFIG_COUNT"] = "2"
    launch_env["GIT_CONFIG_KEY_0"] = "credential.https://github.com.helper"
    launch_env["GIT_CONFIG_VALUE_0"] = ""
    launch_env["GIT_CONFIG_KEY_1"] = "credential.https://github.com.helper"
    launch_env["GIT_CONFIG_VALUE_1"] = _GITHUB_CREDENTIAL_HELPER


def _read_full_run_packet(packet_path: Path) -> bytes:
    """Read one exact packet candidate through the bounded no-follow reader."""
    try:
        return _read_bounded_regular_bytes(
            packet_path,
            max_bytes=MAX_PACKET_BYTES,
            label="full-run packet",
        )
    except StorageError as exc:
        raise ValidationIssue("full_run_packet_unreadable", exc.message) from exc


def _acceptance_criteria_from_packet(
    raw: bytes,
    *,
    packet_path: Path,
) -> list[tuple[str, str]]:
    """Parse canonical acceptance definitions from the exact staged bytes.

    Outer whitespace is syntax and is stripped once. The resulting criterion
    text is the exact report contract; workers may not swap or paraphrase it.
    A list is retained here so duplicate IDs remain observable to prepare.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationIssue(
            "full_run_packet_encoding",
            "Full-run packet must be valid UTF-8",
            path=str(packet_path),
        ) from exc
    if packet_path.suffix.lower() == ".json":
        try:
            payload = _loads_bounded_json(text, label="JSON full-run packet")
            _assert_bounded_json_structure(payload, label="JSON full-run packet")
        except (
            StorageError,
            json.JSONDecodeError,
            ValueError,
            RecursionError,
        ) as exc:
            raise ValidationIssue(
                "full_run_packet_invalid_json",
                "JSON full-run packet must contain one bounded valid object",
                path=str(packet_path),
            ) from exc
        if not isinstance(payload, Mapping):
            raise ValidationIssue(
                "full_run_packet_invalid_json",
                "JSON full-run packet must contain one object",
                path=str(packet_path),
            )
        rows = payload.get("acceptance")
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise ValidationIssue(
                "full_run_acceptance_invalid",
                "JSON packet acceptance must be an array of definition objects",
                path=str(packet_path),
            )
        criteria: list[tuple[str, str]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ValidationIssue(
                    "full_run_acceptance_invalid",
                    f"JSON packet acceptance[{index}] must be an object",
                    path=str(packet_path),
                )
            acceptance_id = row.get("id")
            criterion = row.get("criterion")
            if (
                not isinstance(acceptance_id, str)
                or not _ACCEPTANCE_ID_RE.fullmatch(acceptance_id.strip())
                or not isinstance(criterion, str)
                or not criterion.strip()
            ):
                raise ValidationIssue(
                    "full_run_acceptance_invalid",
                    f"JSON packet acceptance[{index}] requires a stable id and nonempty criterion",
                    path=str(packet_path),
                )
            criteria.append((acceptance_id.strip(), criterion.strip()))
        return criteria
    # Count only canonical definition rows. Inline references and the required
    # report example may repeat ids without defining a second criterion.
    rows, syntax_issues = parse_markdown_acceptance_rows(
        text,
        require_checkbox=False,
    )
    if syntax_issues:
        issue = syntax_issues[0]
        raise ValidationIssue(
            "full_run_acceptance_syntax",
            issue.message,
            path=str(packet_path),
            hint=issue.message,
        )
    return [(row.id, row.criterion) for row in rows]


def _staged_acceptance_criteria(packet_path: Path) -> list[tuple[str, str]]:
    """Read and parse one packet without splitting identity from content."""
    return _acceptance_criteria_from_packet(
        _read_full_run_packet(packet_path),
        packet_path=packet_path,
    )


def _staged_acceptance_ids(packet_path: Path) -> list[str]:
    """Compatibility projection for callers that only need stable IDs."""
    return [item[0] for item in _staged_acceptance_criteria(packet_path)]


def _resolve_acceptance_contract_path(
    repo_root: Path,
    raw: str | Path,
    *,
    base: Path,
    label: str,
) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root)
    except (OSError, ValueError) as exc:
        raise ValidationIssue(
            "full_run_acceptance_contract_path_invalid",
            f"{label} must be an existing file inside the repository",
            path=str(candidate),
        ) from exc
    if not resolved.is_file():
        raise ValidationIssue(
            "full_run_acceptance_contract_path_invalid",
            f"{label} must be a regular file",
            path=str(resolved),
        )
    return resolved


def _acceptance_contract_binding(
    repo_root: Path,
    *,
    session_path: str | Path,
    plan_path: str | Path | None,
    packet_rows: Sequence[tuple[str, str]],
) -> dict[str, str]:
    """Bind the canonical plan, session, and packet before worker launch."""

    repo = Path(repo_root).expanduser().resolve(strict=True)
    session = _resolve_acceptance_contract_path(
        repo,
        session_path,
        base=repo,
        label="Elves session",
    )
    try:
        session_raw = _read_bounded_regular_bytes(
            session,
            max_bytes=MAX_PACKET_BYTES,
            label="Elves session",
            repo_root=repo,
        )
        session_data = _loads_bounded_json(
            session_raw.decode("utf-8"),
            label="Elves session",
        )
        _assert_bounded_json_structure(session_data, label="Elves session")
    except (
        StorageError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        message = exc.message if isinstance(exc, StorageError) else str(exc)
        raise ValidationIssue(
            "full_run_acceptance_session_invalid",
            f"Elves session is not bounded valid JSON: {message}",
            path=str(session),
        ) from exc
    if not isinstance(session_data, Mapping):
        raise ValidationIssue(
            "full_run_acceptance_session_invalid",
            "Elves session must contain one JSON object",
            path=str(session),
        )
    recorded_plan = session_data.get("plan_path")
    if not isinstance(recorded_plan, str) or not recorded_plan.strip():
        raise ValidationIssue(
            "full_run_acceptance_plan_missing",
            "Elves session must record a non-empty plan_path before full-run prepare",
            path=str(session),
        )
    authoritative_plan = _resolve_acceptance_contract_path(
        repo,
        recorded_plan,
        base=repo,
        label="authoritative plan",
    )
    if plan_path is not None:
        explicit_plan = _resolve_acceptance_contract_path(
            repo,
            plan_path,
            base=repo,
            label="explicit plan",
        )
        if explicit_plan != authoritative_plan:
            raise ValidationIssue(
                "full_run_acceptance_plan_mismatch",
                "Explicit plan does not match session plan_path",
                path=str(explicit_plan),
            )
    try:
        plan_raw = _read_bounded_regular_bytes(
            authoritative_plan,
            max_bytes=MAX_PACKET_BYTES,
            label="authoritative plan",
            repo_root=repo,
        )
        plan_text = plan_raw.decode("utf-8")
    except (StorageError, UnicodeDecodeError) as exc:
        message = exc.message if isinstance(exc, StorageError) else str(exc)
        raise ValidationIssue(
            "full_run_acceptance_plan_invalid",
            f"Authoritative plan is not bounded UTF-8 text: {message}",
            path=str(authoritative_plan),
        ) from exc
    contract = parse_plan_acceptance_contract(plan_text)
    if contract.issues:
        first = contract.issues[0]
        raise ValidationIssue(
            "full_run_acceptance_contract_invalid",
            first.message,
            path=str(authoritative_plan),
            hint=first.message,
        )
    if not contract.rows:
        raise ValidationIssue(
            "full_run_acceptance_contract_invalid",
            "Production full-run requires stable B#-A#/M-A# rows in the authoritative plan",
            path=str(authoritative_plan),
        )
    mapping_issues = validate_contract_mapping(
        contract.rows,
        session_data,
        plan_batch_ids=contract.batch_ids,
        packet_rows=packet_rows,
    )
    if mapping_issues:
        first = mapping_issues[0]
        raise ValidationIssue(
            "full_run_acceptance_contract_mismatch",
            first.message,
            path=str(session),
            hint=(
                "Run the active Elves skill's `acceptance_contract.py sync-session "
                f"--repo-root {repo} --session {session} --write`, then update the "
                "packet from the same plan rows."
            ),
        )
    canonical_rows = {row.id: row.criterion for row in contract.rows}
    digest_payload = json.dumps(
        {
            "plan": str(authoritative_plan),
            "plan_sha256": hashlib.sha256(plan_raw).hexdigest(),
            "session": str(session),
            "session_sha256": hashlib.sha256(session_raw).hexdigest(),
            "acceptance": canonical_rows,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "plan_path": str(authoritative_plan),
        "plan_sha256": hashlib.sha256(plan_raw).hexdigest(),
        "session_path": str(session),
        "session_sha256": hashlib.sha256(session_raw).hexdigest(),
        "contract_sha256": hashlib.sha256(digest_payload).hexdigest(),
    }


def _high_risk_checkpoints_from_packet(
    raw: bytes,
    *,
    packet_path: Path,
) -> list[str]:
    """Parse explicitly staged checkpoint IDs from the exact packet bytes."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationIssue(
            "full_run_packet_encoding",
            "Full-run packet must be valid UTF-8",
            path=str(packet_path),
        ) from exc
    if packet_path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationIssue(
                "full_run_packet_invalid_json",
                "JSON full-run packet must contain one valid object",
                path=str(packet_path),
            ) from exc
        rows = payload.get("high_risk_checkpoints", []) if isinstance(payload, Mapping) else []
        if not isinstance(rows, list) or any(
            not isinstance(item, str)
            or not _HIGH_RISK_CHECKPOINT_ID_RE.fullmatch(item)
            for item in rows
        ):
            raise ValidationIssue(
                "full_run_high_risk_checkpoints_invalid",
                "JSON packet high_risk_checkpoints must be an array of stable IDs",
                path=str(packet_path),
            )
        return list(rows)
    return [
        match.group("id")
        for match in _HIGH_RISK_CHECKPOINT_DEFINITION_RE.finditer(text)
    ]


def _packet_contract_digest(
    *,
    source_path: str,
    staged_packet_identity: Mapping[str, Any],
    packet_sha256: str,
    packet_size: int,
    acceptance_criteria: Mapping[str, str],
    high_risk_checkpoints: Sequence[str],
) -> str:
    payload = {
        "source_path": source_path,
        "staged_packet_identity": dict(staged_packet_identity),
        "packet_sha256": packet_sha256,
        "packet_size": packet_size,
        "acceptance_criteria": dict(sorted(acceptance_criteria.items())),
        "high_risk_checkpoints": sorted(high_risk_checkpoints),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _private_staged_packet_path(root: Path, source_path: Path) -> Path:
    suffix = ".json" if source_path.suffix.lower() == ".json" else ".md"
    return root / f"staged-packet{suffix}"


_STAGED_PACKET_IDENTITY_KEYS = frozenset(
    {
        "path",
        "dev",
        "ino",
        "uid",
        "mode",
        "nlink",
        "size",
        "mtime_ns",
        "ctime_ns",
    }
)


def _private_staged_packet_identity(packet_path: Path) -> dict[str, Any]:
    """Return the exact private staged-packet identity without following links."""
    candidate = Path(packet_path)
    try:
        info = candidate.lstat()
    except OSError as exc:
        raise ValidationIssue(
            "full_run_staged_packet_changed",
            "Host-private staged packet copy is missing or unavailable",
            path=str(candidate),
        ) from exc
    if (
        not candidate.is_absolute()
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise ValidationIssue(
            "full_run_staged_packet_changed",
            "Host-private staged packet copy no longer has its private regular-file identity",
            path=str(candidate),
        )
    return {
        "path": str(candidate),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "uid": int(info.st_uid),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "nlink": int(info.st_nlink),
        "size": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def _write_private_packet_copy(
    repo_root: Path,
    destination: Path,
    raw: bytes,
) -> None:
    """Write the already-validated UTF-8 packet into host-private runtime state."""
    text = raw.decode("utf-8")
    try:
        with open_repo_text(
            repo_root,
            destination,
            mode="w",
            permissions=0o600,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except StorageError as exc:
        raise ValidationIssue(
            "full_run_staged_packet_write_failed",
            "Cannot persist the host-private staged packet copy",
            path=str(destination),
        ) from exc


def _prepare_goal_prompt(repo_root: Path, root: Path, state: FullRunState) -> Path:
    """Create a private goal command; resume never resets the existing objective."""
    staged = _revalidate_staged_packet_binding(repo_root, state)
    packet_raw = _read_private_packet_copy(repo_root, staged)
    goal_raw = b"/goal " + packet_raw if state.create_session else b"/goal resume\n"
    if len(goal_raw) > MAX_PACKET_BYTES:
        raise ValidationIssue(
            "full_run_goal_prompt_too_large",
            "Goal command plus staged packet exceeds the packet byte limit",
        )
    goal_path = root / "goal-prompt.md"
    _write_private_packet_copy(repo_root, goal_path, goal_raw)
    observed = _read_private_packet_copy(repo_root, goal_path)
    if observed != goal_raw:
        raise ValidationIssue(
            "full_run_goal_prompt_changed",
            "Private goal prompt does not match the packet-backed objective",
        )
    state.goal_prompt_path = str(goal_path)
    state.goal_prompt_identity = _private_staged_packet_identity(goal_path)
    state.goal_prompt_sha256 = hashlib.sha256(goal_raw).hexdigest()
    state.goal_prompt_size = len(goal_raw)
    return goal_path


def _read_private_packet_copy(repo_root: Path, packet_path: Path) -> bytes:
    _private_staged_packet_identity(packet_path)
    try:
        return _read_bounded_regular_bytes(
            packet_path,
            max_bytes=MAX_PACKET_BYTES,
            label="staged full-run packet",
            repo_root=repo_root,
        )
    except StorageError as exc:
        raise ValidationIssue(
            "full_run_staged_packet_changed",
            "Host-private staged packet copy cannot be revalidated",
            path=str(packet_path),
        ) from exc


def _revalidate_staged_packet_binding(
    repo_root: Path,
    state: FullRunState,
) -> Path:
    """Bind launch/reconciliation to the exact source, copy, and criteria.

    States prepared before packet binding was introduced intentionally fail
    closed here. They remain readable for diagnosis and stop operations.
    """
    source_path = Path(state.packet_path)
    expected_staged_path = _private_staged_packet_path(
        full_run_root(repo_root, state.session_id), source_path
    )
    staged_path = Path(state.staged_packet_path or "")
    criteria = state.acceptance_criteria
    checkpoints = state.planned_high_risk_checkpoints
    staged_identity = state.staged_packet_identity
    if (
        not state.staged_packet_path
        or staged_path != expected_staged_path
        or not isinstance(staged_identity, dict)
        or set(staged_identity) != _STAGED_PACKET_IDENTITY_KEYS
        or staged_identity.get("path") != str(staged_path)
        or any(
            isinstance(staged_identity.get(key), bool)
            or not isinstance(staged_identity.get(key), int)
            for key in _STAGED_PACKET_IDENTITY_KEYS - {"path"}
        )
        or not isinstance(state.packet_sha256, str)
        or not _SHA256_RE.fullmatch(state.packet_sha256)
        or isinstance(state.packet_size, bool)
        or not isinstance(state.packet_size, int)
        or state.packet_size < 0
        or not isinstance(state.packet_contract_sha256, str)
        or not _SHA256_RE.fullmatch(state.packet_contract_sha256)
        or not isinstance(criteria, dict)
        or any(
            not isinstance(key, str)
            or not _ACCEPTANCE_ID_RE.fullmatch(key)
            or not isinstance(value, str)
            or not value
            for key, value in criteria.items()
        )
        or not isinstance(state.acceptance_ids, list)
        or any(not isinstance(item, str) for item in state.acceptance_ids)
        or sorted(state.acceptance_ids) != sorted(criteria)
        or not isinstance(checkpoints, list)
        or len(checkpoints) > MAX_HIGH_RISK_CHECKPOINTS
        or len(checkpoints) != len(set(checkpoints))
        or any(
            not isinstance(item, str)
            or not _HIGH_RISK_CHECKPOINT_ID_RE.fullmatch(item)
            for item in checkpoints
        )
    ):
        raise ValidationIssue(
            "full_run_packet_binding_missing",
            "Full-run state lacks a complete immutable staged-packet binding",
            hint="Prepare a fresh full-run session before launch or reconciliation",
        )

    expected_contract_digest = _packet_contract_digest(
        source_path=str(source_path),
        staged_packet_identity=staged_identity,
        packet_sha256=state.packet_sha256,
        packet_size=state.packet_size,
        acceptance_criteria=criteria,
        high_risk_checkpoints=checkpoints,
    )
    if not hmac.compare_digest(
        expected_contract_digest,
        state.packet_contract_sha256,
    ):
        raise ValidationIssue(
            "full_run_packet_binding_changed",
            "Staged packet contract metadata changed after preparation",
        )

    source_raw = _read_full_run_packet(source_path)
    source_digest = hashlib.sha256(source_raw).hexdigest()
    if (
        len(source_raw) != state.packet_size
        or not hmac.compare_digest(source_digest, state.packet_sha256)
    ):
        raise ValidationIssue(
            "full_run_packet_source_changed",
            "Full-run source packet content changed after preparation",
            path=str(source_path),
        )

    staged_raw = _read_private_packet_copy(repo_root, staged_path)
    observed_staged_identity = _private_staged_packet_identity(staged_path)
    if observed_staged_identity != staged_identity:
        raise ValidationIssue(
            "full_run_staged_packet_changed",
            "Host-private staged packet identity changed after preparation",
            path=str(staged_path),
        )
    staged_digest = hashlib.sha256(staged_raw).hexdigest()
    if (
        len(staged_raw) != state.packet_size
        or not hmac.compare_digest(staged_digest, state.packet_sha256)
        or not hmac.compare_digest(staged_digest, source_digest)
    ):
        raise ValidationIssue(
            "full_run_staged_packet_changed",
            "Host-private staged packet content changed after preparation",
            path=str(staged_path),
        )

    parsed_rows = _acceptance_criteria_from_packet(
        staged_raw,
        packet_path=source_path,
    )
    parsed_ids = [item[0] for item in parsed_rows]
    if len(set(parsed_ids)) != len(parsed_ids) or dict(parsed_rows) != criteria:
        raise ValidationIssue(
            "full_run_packet_binding_changed",
            "Staged packet acceptance contract no longer matches prepared state",
        )
    binding_values = (
        state.acceptance_plan_path,
        state.acceptance_plan_sha256,
        state.acceptance_session_path,
        state.acceptance_session_sha256,
        state.acceptance_contract_sha256,
    )
    if state.adapter != "fixture" and not any(
        value is not None for value in binding_values
    ):
        raise ValidationIssue(
            "full_run_acceptance_contract_binding_missing",
            "Production full-run state lacks the required plan/session acceptance binding",
            hint="Prepare a fresh full-run session from the canonical Elves session before launch or reconciliation",
        )
    if any(value is not None for value in binding_values):
        if any(
            not isinstance(value, str) or not value
            for value in binding_values
        ):
            raise ValidationIssue(
                "full_run_acceptance_contract_binding_missing",
                "Prepared plan/session acceptance binding is incomplete",
            )
        observed_binding = _acceptance_contract_binding(
            repo_root,
            session_path=state.acceptance_session_path or "",
            plan_path=state.acceptance_plan_path,
            packet_rows=parsed_rows,
        )
        expected_binding = {
            "plan_path": state.acceptance_plan_path,
            "plan_sha256": state.acceptance_plan_sha256,
            "session_path": state.acceptance_session_path,
            "session_sha256": state.acceptance_session_sha256,
            "contract_sha256": state.acceptance_contract_sha256,
        }
        if observed_binding != expected_binding:
            raise ValidationIssue(
                "full_run_acceptance_contract_changed",
                "Plan/session/packet Acceptance contract changed after preparation",
                hint="Re-run full-run-prepare after reconciling the canonical session.",
            )
    parsed_checkpoints = _high_risk_checkpoints_from_packet(
        staged_raw,
        packet_path=source_path,
    )
    if (
        len(parsed_checkpoints) != len(set(parsed_checkpoints))
        or sorted(parsed_checkpoints) != sorted(checkpoints)
    ):
        raise ValidationIssue(
            "full_run_packet_binding_changed",
            "Staged packet checkpoint contract no longer matches prepared state",
        )
    return staged_path


_PROC_SCAN_SKIP_ERRNOS = frozenset(
    {errno.EACCES, errno.EPERM, errno.ENOENT, errno.ESRCH}
)


def _qualified_process_supervisor() -> Path:
    """Return the trusted platform process-inspection backend.

    Linux uses procfs directly because GNU and BSD ``ps`` intentionally have
    incompatible environment-display syntax.  macOS retains a root-owned BSD
    ``ps`` binary.  Unsupported platforms fail closed instead of guessing a
    mixed command line.
    """
    if sys.platform.startswith("linux"):
        candidate = Path("/proc")
        try:
            info = candidate.lstat()
        except OSError as exc:
            raise ValidationIssue(
                "full_run_supervision_unavailable",
                f"Production full-run requires trusted Linux procfs: {exc}",
            ) from exc
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or (info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
            or candidate.resolve() != candidate
            or not (candidate / "self" / "environ").exists()
            or not (candidate / "self" / "stat").exists()
        ):
            raise ValidationIssue(
                "full_run_supervision_unavailable",
                "Production full-run requires a root-owned, non-writable /proc",
            )
        return candidate
    if sys.platform != "darwin":
        raise ValidationIssue(
            "full_run_supervision_unavailable",
            f"Recursive process supervision is unsupported on {sys.platform}",
        )
    for candidate in (Path("/bin/ps"), Path("/usr/bin/ps")):
        try:
            info = candidate.stat()
        except OSError:
            continue
        if (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == 0
            and not (info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
            and os.access(candidate, os.X_OK)
        ):
            return candidate.resolve()
    raise ValidationIssue(
        "full_run_supervision_unavailable",
        "Production full-run requires a trusted system BSD ps for recursive supervision",
    )


def _linux_proc_state(proc_dir: Path) -> str | None:
    """Read one Linux proc stat state, tolerating normal exit/permission races."""
    try:
        raw = (proc_dir / "stat").read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        if exc.errno in _PROC_SCAN_SKIP_ERRNOS:
            return None
        raise ValidationIssue(
            "full_run_supervision_scan_failed",
            f"Cannot inspect {proc_dir}/stat: {exc}",
        ) from exc
    close = raw.rfind(")")
    fields = raw[close + 1 :].strip().split() if close >= 0 else []
    if not fields:
        raise ValidationIssue(
            "full_run_supervision_scan_failed",
            f"Malformed process stat record at {proc_dir}/stat",
        )
    return fields[0]


def _scan_linux_proc_supervision_pids(proc_root: Path, marker_value: str) -> set[int]:
    marker = f"ELVES_FULL_RUN_SUPERVISION_MARKER={marker_value}".encode("utf-8")
    try:
        entries = list(os.scandir(proc_root))
    except OSError as exc:
        raise ValidationIssue(
            "full_run_supervision_scan_failed",
            f"Cannot enumerate trusted procfs: {exc}",
        ) from exc
    found: set[int] = set()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid <= 0 or pid == os.getpid():
            continue
        proc_dir = proc_root / entry.name
        state = _linux_proc_state(proc_dir)
        if state is None or state == "Z":
            continue
        try:
            environ = (proc_dir / "environ").read_bytes()
        except OSError as exc:
            # hidepid/ptrace policy and ordinary process-exit races are expected.
            # The same-UID canary proves our own supervision domain is readable.
            if exc.errno in _PROC_SCAN_SKIP_ERRNOS:
                continue
            raise ValidationIssue(
                "full_run_supervision_scan_failed",
                f"Cannot inspect {proc_dir}/environ: {exc}",
            ) from exc
        if marker in environ.split(b"\0"):
            found.add(pid)
    return found


def _scan_bsd_ps_supervision_pids(executable: Path, marker_value: str) -> set[int]:
    marker = f"ELVES_FULL_RUN_SUPERVISION_MARKER={marker_value}"
    try:
        result = subprocess.run(
            [str(executable), "e", "-axo", "pid=,ppid=,pgid=,command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationIssue(
            "full_run_supervision_scan_failed", f"Recursive process scan failed: {exc}"
        ) from exc
    if result.returncode != 0:
        raise ValidationIssue(
            "full_run_supervision_scan_failed",
            (result.stderr or "trusted ps scan failed").strip(),
        )
    found: set[int] = set()
    for row in result.stdout.splitlines():
        fields = row.strip().split(None, 3)
        if len(fields) < 4 or marker not in fields[3].split():
            continue
        try:
            pid = int(fields[0])
        except ValueError:
            continue
        if pid != os.getpid():
            found.add(pid)
    return found


def _scan_supervision_pids(executable: str | Path, marker_value: str) -> set[int]:
    if not re.fullmatch(r"[0-9a-f]{64}", str(marker_value or "")):
        raise ValidationIssue(
            "full_run_supervision_scan_failed",
            "Recursive supervision marker is missing or malformed",
        )
    qualified = _qualified_process_supervisor()
    observed = Path(executable).resolve()
    if observed != qualified:
        raise ValidationIssue(
            "full_run_supervision_executable_changed",
            "Recorded recursive supervision backend is not currently qualified",
        )
    if sys.platform.startswith("linux"):
        return _scan_linux_proc_supervision_pids(qualified, marker_value)
    return _scan_bsd_ps_supervision_pids(qualified, marker_value)


def _supervision_canary_budget(first_scan_seconds: float) -> float:
    """Wall budget from the first completed scan, clamped to floor/ceiling."""

    cost = max(0.0, float(first_scan_seconds))
    return min(
        SUPERVISION_CANARY_CEILING_SECONDS,
        max(
            SUPERVISION_CANARY_FLOOR_SECONDS,
            cost * SUPERVISION_CANARY_SCAN_MULTIPLE,
        ),
    )


def _observe_supervision_canary(executable: Path) -> bool:
    """One canary attempt. Distinguishes scan timeout from a completed miss."""

    marker_value = secrets.token_hex(32)
    # The canary needs only process discovery, not provider/user state.  On
    # Darwin the qualified `ps e` backend necessarily observes its environment,
    # so inheriting the host environment would copy every credential into both
    # the child and the scan buffer.
    env = {
        name: os.environ[name]
        for name in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
        if os.environ.get(name)
    }
    env.setdefault("PATH", os.defpath)
    env["ELVES_FULL_RUN_SUPERVISION_MARKER"] = marker_value
    child_sleep = SUPERVISION_CANARY_CEILING_SECONDS + 1.0
    proc = subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({child_sleep:.3f})"],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        started = time.monotonic()
        scan_started = time.monotonic()
        pids = _scan_supervision_pids(executable, marker_value)
        first_scan = time.monotonic() - scan_started
        deadline = started + _supervision_canary_budget(first_scan)
        completed_scans = 1
        if proc.pid in pids:
            return True
        while time.monotonic() < deadline:
            time.sleep(SUPERVISION_CANARY_POLL_SECONDS)
            if time.monotonic() >= deadline:
                break
            pids = _scan_supervision_pids(executable, marker_value)
            completed_scans += 1
            if proc.pid in pids:
                return True
        if completed_scans >= 2:
            raise ValidationIssue(
                "full_run_supervision_canary_failed",
                "Trusted recursive supervisor completed its marker scan and the canary was absent",
            )
        raise ValidationIssue(
            "full_run_supervision_canary_timeout",
            "Trusted recursive supervisor timed out before it could observe its marker canary",
        )
    finally:
        try:
            # This is our unreaped direct child; its PID cannot be reused until
            # wait(), so the Popen handle is a stronger identity than its PGID.
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _run_supervision_canary(executable: Path) -> bool:
    try:
        return _observe_supervision_canary(executable)
    except ValidationIssue as exc:
        if exc.code != "full_run_supervision_canary_timeout":
            raise
        return _observe_supervision_canary(executable)


def _protected_branch_names(repo_root: Path) -> set[str]:
    names = {"main", "master"}
    for args in (
        ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        ["config", "--get", "init.defaultBranch"],
    ):
        result = run_git(
            repo_root,
            args,
            check=False,
        )
        value = result.stdout.strip()
        if result.returncode == 0 and value:
            names.add(value.removeprefix("origin/"))
    return names


def _validate_full_run_git_contract(
    repo_root: Path,
    *,
    worktree: str | Path,
    branch: str,
    start_head: str,
    packet_path: str | Path,
    adapter: str = "grok-build",
    expected_current_head: str | None = None,
    prepare_phase: bool = False,
) -> dict[str, Any]:
    """Fail before model launch unless the staged Git/worktree contract is exact."""
    repo = Path(repo_root).resolve()
    worker = Path(worktree).expanduser().resolve()
    packet_input = Path(packet_path).expanduser()
    packet = packet_input.resolve()
    if not worker.is_dir():
        raise ValidationIssue(
            "full_run_worktree_missing",
            f"Full-run worktree does not exist: {worker}",
        )
    try:
        packet_info = packet_input.lstat()
    except OSError as exc:
        raise ValidationIssue(
            "full_run_packet_missing",
            f"Full-run packet is not readable: {packet}",
        ) from exc
    if not stat.S_ISREG(packet_info.st_mode):
        raise ValidationIssue(
            "full_run_packet_not_regular",
            f"Full-run packet must be a regular non-symlink file: {packet}",
        )
    if packet_info.st_size > MAX_PACKET_BYTES:
        raise ValidationIssue(
            "full_run_packet_too_large",
            f"Full-run packet exceeds {MAX_PACKET_BYTES} byte limit",
            path=str(packet),
        )
    if not worktree_is_registered(worker, git_cwd=repo):
        raise ValidationIssue(
            "full_run_worktree_unregistered",
            f"Full-run worktree is not registered in the staged repository: {worker}",
        )
    repo_common = _git_common_dir(repo)
    worker_common = _git_common_dir(worker)
    if repo_common is None or worker_common is None or repo_common != worker_common:
        raise ValidationIssue(
            "full_run_worktree_wrong_repository",
            "Full-run worktree is not linked to the staged repository",
        )
    current_branch = _git_branch(worker)
    if not current_branch or current_branch != branch:
        raise ValidationIssue(
            "full_run_branch_mismatch",
            f"Worktree branch `{current_branch}` != staged feature branch `{branch}`",
        )
    if branch in _protected_branch_names(repo):
        raise ValidationIssue(
            "full_run_protected_branch",
            f"Refusing delegated full-run on protected/default branch `{branch}`",
        )
    current_head = _git_head(worker)
    required_head = expected_current_head or start_head
    if not current_head or current_head != required_head:
        raise ValidationIssue(
            "full_run_start_head_mismatch",
            f"Worktree HEAD `{current_head}` != required checkpoint `{required_head}`",
        )
    commit = run_git(
        worker,
        ["rev-parse", "--verify", f"{start_head}^{{commit}}"],
        check=False,
    )
    if commit.returncode != 0 or commit.stdout.strip() != start_head:
        raise ValidationIssue(
            "full_run_start_head_invalid",
            f"Staged start HEAD is not an exact commit: `{start_head}`",
        )
    metadata: dict[str, Any] = {}
    if adapter != "fixture":
        _assert_clean_worktree(worker)
        origin_url = _canonical_origin_url(repo)
        origin_digest = _origin_config_digest(repo)
        remote_tip = _feature_remote_tip(repo, branch)
        if prepare_phase and remote_tip is not None and remote_tip != start_head:
            raise ValidationIssue(
                "full_run_remote_feature_unsafe_start",
                "Existing origin feature branch must equal the staged safe start HEAD",
            )
        metadata.update(
            origin_url=origin_url,
            origin_config_digest=origin_digest,
            remote_feature_tip=remote_tip,
        )
    return metadata


def resolve_worker_effort(
    adapter: str | None,
    effort: str | None,
) -> tuple[str, bool]:
    """Resolve the worker effort under the one normalized default authority.

    Returns ``(resolved_effort, effort_explicit)``. The adapter name is
    normalized before default selection so a mixed-case ``Grok-Build`` still
    resolves the grok default; callers must pass ``effort=None`` whenever the
    operator did not explicitly request a value.
    """

    adapter_name = (adapter or "grok-build").strip().lower()
    explicit_effort = (effort or "").strip().lower() or None
    if explicit_effort is not None:
        return explicit_effort, True
    return (
        GROK_DEFAULT_EFFORT if adapter_name == "grok-build" else DEFAULT_EFFORT,
        False,
    )


@_locked_full_run
def prepare_full_run(
    repo_root: Path,
    *,
    session_id: str,
    branch: str,
    start_head: str,
    worktree: str | Path,
    packet_path: str | Path,
    session_path: str | Path | None = None,
    plan_path: str | Path | None = None,
    adapter: str = "grok-build",
    model: str | None = None,
    permission_mode: str = DEFAULT_PERMISSION_MODE,
    effort: str | None = None,
    executable: str | None = None,
    create: bool = True,
    check: bool = False,
    max_turns: int = 80,
    fixture_script: str | Path | None = None,
    credential_grant_names: Sequence[str] | None = None,
    goal_behavioral_evidence: str | None = None,
    allow_overwrite: bool = False,
) -> dict[str, Any]:
    """Create private full-run artifact tree for one exact session."""
    from .teams import checkpoint_guard
    checkpoint_guard(repo_root, "after-staging")
    sid = (session_id or "").strip()
    normalized_grant_names = _normalize_credential_grant_names(
        credential_grant_names
    )
    if not sid or sid.lower() in AMBIGUOUS_SESSION_TOKENS:
        raise ValidationIssue(
            "full_run_session_required",
            "Exact session_id is required for full-run prepare",
            path="full_run.session_id",
        )
    # Reject traversal/collision-prone raw path embedding (digest key already safe).
    if any(ch in sid for ch in ("/", "\\", "\0")) or ".." in sid:
        # Still allowed as session ids abstractly, but we use digest paths only.
        pass

    adapter_name = (adapter or "grok-build").strip().lower()
    if adapter_name != "fixture":
        reject_fugu_implementation_route(
            adapter_name,
            executable,
            requested_model=model,
        )
    # Single default authority for worker effort: an explicit request wins,
    # otherwise the normalized adapter name picks the default. Explicitness is
    # persisted so a flagless resume keeps the originally requested value.
    explicit_effort = (effort or "").strip().lower() or None
    del effort
    if adapter_name == "fixture" and not fixture_script:
        raise ValidationIssue(
            "fixture_script_required",
            "adapter=fixture requires --fixture-script (explicit test mode only)",
        )
    if adapter_name != "fixture" and fixture_script:
        raise ValidationIssue(
            "fixture_script_only_for_fixture_adapter",
            "fixture_script is only valid with adapter=fixture",
        )
    if adapter_name == "devin-cli" and (
        not model or model in {DEFAULT_MODEL, "auto"}
    ):
        model = "swe-1-7-lightning"
    elif adapter_name == "omp-cli" and (
        not model or model in {DEFAULT_MODEL, "auto"}
    ):
        model = "google/gemini-2.5-flash"
    elif not model:
        model = "auto" if adapter_name == "grok-build" else DEFAULT_MODEL

    git_metadata = _validate_full_run_git_contract(
        Path(repo_root),
        worktree=worktree,
        branch=branch,
        start_head=start_head,
        packet_path=packet_path,
        adapter=adapter_name,
        prepare_phase=True,
    )

    packet_source = Path(packet_path).expanduser().resolve()
    packet_raw = _read_full_run_packet(Path(packet_path).expanduser())
    staged_acceptance_rows = _acceptance_criteria_from_packet(
        packet_raw,
        packet_path=packet_source,
    )
    staged_high_risk_checkpoints = _high_risk_checkpoints_from_packet(
        packet_raw,
        packet_path=packet_source,
    )
    staged_acceptance_ids = [item[0] for item in staged_acceptance_rows]
    duplicate_ids = sorted(
        {
            item
            for item in staged_acceptance_ids
            if staged_acceptance_ids.count(item) > 1
        }
    )
    if duplicate_ids:
        raise ValidationIssue(
            "full_run_acceptance_ids_duplicate",
            "Full-run packet contains duplicate stable acceptance definitions",
            path=str(packet_path),
        )
    if (
        len(staged_high_risk_checkpoints) > MAX_HIGH_RISK_CHECKPOINTS
        or len(staged_high_risk_checkpoints)
        != len(set(staged_high_risk_checkpoints))
    ):
        raise ValidationIssue(
            "full_run_high_risk_checkpoints_invalid",
            "Full-run packet checkpoints must be unique and within the bounded limit",
            path=str(packet_path),
        )
    if adapter_name != "fixture":
        if not staged_acceptance_ids:
            raise ValidationIssue(
                "full_run_acceptance_ids_required",
                "Production full-run packet requires canonical B#-A#/M-A# acceptance definition rows",
                path=str(packet_path),
            )

        if session_path is None:
            default_session = Path(repo_root).expanduser().resolve() / ELVES_SESSION_BASENAME
            if default_session.is_file():
                session_path = default_session
            else:
                raise ValidationIssue(
                    "full_run_acceptance_session_required",
                    "Production full-run prepare requires a canonical Elves session so plan/session/packet Acceptance can be reconciled before launch",
                    path=str(default_session),
                )

    if plan_path is not None and session_path is None:
        raise ValidationIssue(
            "full_run_acceptance_session_required",
            "--plan is an equality assertion and requires the canonical --session",
            path=str(plan_path),
        )
    acceptance_binding: dict[str, str] | None = None
    if session_path is not None:
        acceptance_binding = _acceptance_contract_binding(
            Path(repo_root),
            session_path=session_path,
            plan_path=plan_path,
            packet_rows=staged_acceptance_rows,
        )

    root = full_run_root(repo_root, sid)
    state_path = root / "state.json"
    prior_state_data: Mapping[str, Any] | None = None
    if repo_regular_file_exists(Path(repo_root), state_path) and not allow_overwrite:
        existing = read_json(state_path, repo_root=Path(repo_root))
        if existing.get("session_id") != sid:
            raise ValidationIssue(
                "full_run_collision",
                "Digest path occupied by a different session_id",
                path=str(state_path),
            )
        if create:
            raise ValidationIssue(
                "full_run_already_prepared",
                f"Full-run state already exists for session `{sid}`",
                path=str(state_path),
                hint="Pass a new session or stop the existing run first",
            )
        # Resume prepare over the same session rebuilds the state tree; it is
        # only safe once the prior supervised process is provably closed.
        if existing.get("pid") is not None or existing.get("status") == "healthy":
            raise ValidationIssue(
                "full_run_resume_prepare_live",
                "Refusing resume prepare while the existing run may be live",
                path=str(state_path),
                hint="Stop the existing run first",
            )
        # Terminally-evented sessions must not be rebuilt: appending run_started
        # after run_complete/blocked makes every later event fail ordering.
        terminal_types = _terminal_event_types_present(
            root / "events.jsonl",
            repo_root=Path(repo_root),
        )
        if terminal_types:
            raise ValidationIssue(
                "full_run_resume_prepare_terminal",
                "Refusing resume prepare over a session whose event log is already "
                f"terminal ({', '.join(sorted(terminal_types))})",
                path=str(root / "events.jsonl"),
                hint="Start a new session_id; do not rebuild a completed or blocked run",
            )
        prior_state_data = existing
    if not create and explicit_effort is None and prior_state_data is not None:
        prior_effort = str(prior_state_data.get("effort") or "").strip().lower()
        if prior_effort and bool(prior_state_data.get("effort_explicit")):
            # A flagless resume keeps an originally-explicit effort instead of
            # silently flipping to the current adapter default.
            explicit_effort = prior_effort
    resolved_effort, effort_explicit = resolve_worker_effort(
        adapter_name, explicit_effort
    )

    ensure_private_dir(root, repo_root=Path(repo_root))
    ensure_private_dir(root / "worker-home", repo_root=Path(repo_root))
    ensure_private_dir(root / "worker-tmp", repo_root=Path(repo_root))
    staged_packet_path = _private_staged_packet_path(root, packet_source)
    _write_private_packet_copy(Path(repo_root), staged_packet_path, packet_raw)
    staged_packet_raw = _read_private_packet_copy(
        Path(repo_root), staged_packet_path
    )
    if staged_packet_raw != packet_raw:
        raise ValidationIssue(
            "full_run_staged_packet_changed",
            "Host-private staged packet copy does not match its source",
            path=str(staged_packet_path),
        )
    staged_packet_identity = _private_staged_packet_identity(staged_packet_path)
    packet_sha256 = hashlib.sha256(packet_raw).hexdigest()
    acceptance_criteria = dict(staged_acceptance_rows)
    packet_contract_sha256 = _packet_contract_digest(
        source_path=str(packet_source),
        staged_packet_identity=staged_packet_identity,
        packet_sha256=packet_sha256,
        packet_size=len(packet_raw),
        acceptance_criteria=acceptance_criteria,
        high_risk_checkpoints=staged_high_risk_checkpoints,
    )

    if adapter_name == "fixture":
        exe = sys.executable
    else:
        if adapter_name == "devin-cli":
            default_exe = "devin"
        elif adapter_name == "omp-cli":
            default_exe = "omp"
        else:
            default_exe = DEFAULT_EXECUTABLE
        exe = (executable or "").strip() or default_exe
    if adapter_name == "devin-cli" and model == DEFAULT_MODEL:
        model = "swe-1-7-lightning"
    if adapter_name == "omp-cli" and model in {DEFAULT_MODEL, "auto", ""}:
        model = "google/gemini-2.5-flash"
    qualified_supervisor = _qualified_process_supervisor()
    supervisor_executable: str | None = str(qualified_supervisor)
    supervision_token: str | None = secrets.token_hex(24)
    supervision_canary_passed = False
    if adapter_name != "fixture":
        supervision_canary_passed = _run_supervision_canary(qualified_supervisor)

    state = FullRunState(
        session_id=sid,
        branch=branch,
        start_head=start_head,
        worktree=str(Path(worktree).expanduser().resolve()),
        packet_path=str(packet_source),
        staged_packet_path=str(staged_packet_path),
        staged_packet_identity=staged_packet_identity,
        packet_sha256=packet_sha256,
        packet_size=len(packet_raw),
        packet_contract_sha256=packet_contract_sha256,
        acceptance_criteria=acceptance_criteria,
        acceptance_plan_path=(
            acceptance_binding.get("plan_path") if acceptance_binding else None
        ),
        acceptance_plan_sha256=(
            acceptance_binding.get("plan_sha256") if acceptance_binding else None
        ),
        acceptance_session_path=(
            acceptance_binding.get("session_path") if acceptance_binding else None
        ),
        acceptance_session_sha256=(
            acceptance_binding.get("session_sha256") if acceptance_binding else None
        ),
        acceptance_contract_sha256=(
            acceptance_binding.get("contract_sha256") if acceptance_binding else None
        ),
        planned_high_risk_checkpoints=sorted(staged_high_risk_checkpoints),
        adapter=adapter_name,
        model=model,
        permission_mode=permission_mode,
        effort=resolved_effort,
        effort_explicit=effort_explicit,
        executable=exe,
        create_session=bool(create),
        check=bool(check),
        max_turns=int(max_turns),
        status="pending",
        head=start_head,
        next_action="launch",
        credential_grant_names=normalized_grant_names,
        fixture_script=str(Path(fixture_script).resolve()) if fixture_script else None,
        protected_refs=snapshot_protected_refs(
            Path(repo_root), feature_branch=branch
        ),
        launch_start_head=start_head,
        origin_url=git_metadata.get("origin_url"),
        origin_config_digest=git_metadata.get("origin_config_digest"),
        initial_remote_feature_tip=git_metadata.get("remote_feature_tip"),
        acceptance_ids=sorted(staged_acceptance_ids),
        supervisor_executable=supervisor_executable,
        supervision_token=supervision_token,
        supervision_canary_passed=supervision_canary_passed,
        runtime_dir=str(root),
        provider_session_id=None,
        output_format="streaming-json" if adapter_name == "grok-build" else "json",
        goal_behavioral_artifact_path=(
            str(Path(str(goal_behavioral_evidence).strip()).expanduser().resolve())
            if goal_behavioral_evidence
            else None
        ),
        goal_behavioral_evidence=None,
        notes=[
            "Trusted full-run supervisor prepared; host parks after launch",
            f"adapter={adapter_name}",
            "Worker report is evidence only; never merge authority",
            "Trusted Lane A is policy trust, not an OS Git sandbox; protected-ref movement blocks readiness",
        ],
    )
    atomic_write_json(state_path, state.to_dict(), repo_root=Path(repo_root))
    for name in ("events.jsonl", "transcript.log"):
        path = root / name
        if not repo_regular_file_exists(Path(repo_root), path):
            with open_repo_text(Path(repo_root), path, mode="w"):
                pass
    report = _running_report(state, final_head=start_head)
    errs = validate_run_report(
        report,
        expected_session_id=sid,
        expected_branch=branch,
        expected_start_head=start_head,
        expected_attempt=state.attempt,
    )
    if errs:
        raise ValidationIssue("full_run_report_invalid", "; ".join(errs))
    report_path = root / "report.json"
    atomic_write_json(report_path, report, repo_root=Path(repo_root))
    _append_event(
        root / "events.jsonl",
        {
            "timestamp": _utc_now(),
            "session_id": sid,
            "branch": branch,
            "head": start_head,
            "batch": 0,
            "type": "run_started",
            "summary": "Full-run supervisor prepared",
        },
        expected_session_id=sid,
        expected_branch=branch,
        repo_root=Path(repo_root),
    )
    public_state = state.to_dict()
    # This is the host-only stop capability used to derive the public descendant
    # marker. It is not operator telemetry; retain it only in private state.
    public_state.pop("supervision_token", None)
    public_state.pop("goal_behavioral_artifact_path", None)
    return {
        "ok": True,
        "action": "full_run_prepare",
        "session_id": sid,
        "runtime_dir": str(root),
        "state_path": str(state_path),
        "events_path": str(root / "events.jsonl"),
        "report_path": str(report_path),
        "transcript_path": str(root / "transcript.log"),
        "state": public_state,
        "driver_contract": "parked_monitor",
        "driver_monitor_mode": "parked_monitor",
        "model_calls_made": False,
        "merge_authority": False,
    }


def _append_event(
    events_path: Path,
    event: Mapping[str, Any],
    *,
    repo_root: Path,
    expected_session_id: str | None = None,
    expected_branch: str | None = None,
    expected_high_risk_checkpoints: Sequence[str] | None = None,
    seen_terminal: bool = False,
) -> None:
    errors = validate_event(
        event,
        expected_session_id=expected_session_id,
        expected_branch=expected_branch,
        expected_high_risk_checkpoints=expected_high_risk_checkpoints,
        seen_terminal=seen_terminal,
    )
    if errors:
        raise ValidationIssue("full_run_event_invalid", "; ".join(errors))
    payload = json.dumps(dict(event), separators=(",", ":")) + "\n"
    with open_repo_text(repo_root, events_path, mode="a") as handle:
        handle.write(payload)


def load_state(repo_root: Path, session_id: str) -> FullRunState:
    root = full_run_root(repo_root, session_id)
    path = root / "state.json"
    try:
        exists = repo_regular_file_exists(Path(repo_root), path)
    except StorageError as exc:
        raise ValidationIssue(
            "full_run_state_storage_unsafe",
            f"Full-run state storage is unsafe ({exc.code})",
            path=str(root),
        ) from exc
    if not exists:
        raise ValidationIssue(
            "full_run_not_found",
            "No full-run state for the requested exact session",
            path=str(root),
        )
    try:
        data = read_json(path, repo_root=Path(repo_root))
    except StorageError as exc:
        raise ValidationIssue(
            "full_run_state_storage_unsafe",
            f"Full-run state could not be read safely ({exc.code})",
            path=str(root),
        ) from exc
    try:
        assert_embedded_id(data, session_id, id_field="session_id")
    except StorageError as exc:
        raise ValidationIssue(
            "full_run_embedded_id_mismatch",
            "Full-run state embedded id does not match the requested exact session",
            path=str(root),
        ) from exc
    try:
        return FullRunState.from_dict(data)
    except (
        AttributeError,
        KeyError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValidationIssue(
            "full_run_state_malformed",
            f"Full-run state schema is malformed ({type(exc).__name__})",
            path=str(root),
        ) from exc


def save_state(repo_root: Path, state: FullRunState) -> Path:
    root = full_run_root(repo_root, state.session_id)
    ensure_private_dir(root, repo_root=Path(repo_root))
    path = root / "state.json"
    atomic_write_json(path, state.to_dict(), repo_root=Path(repo_root))
    return path


def build_full_run_argv(state: FullRunState) -> list[str]:
    """Adapter-aware argv. Fixture mode uses explicit python + script + packet."""
    reject_fugu_implementation_route(
        state.adapter,
        state.executable,
        requested_model=state.model,
    )
    launch_packet = (
        state.goal_prompt_path
        if state.goal_mode_behaviorally_verified and state.goal_prompt_path
        else state.staged_packet_path or state.packet_path
    )
    if state.adapter == "fixture":
        if Path(state.executable).resolve() != Path(sys.executable).resolve():
            raise ValidationIssue(
                "fixture_executable_invalid",
                "Persisted fixture state must use the current Python executable",
            )
        if not state.fixture_script:
            raise ValidationIssue(
                "fixture_script_required",
                "fixture adapter requires fixture_script in state",
            )
        state.goal_launch_mode = "fixture"
        return [state.executable, state.fixture_script, launch_packet]
    if state.adapter == "devin-cli":
        state.goal_launch_mode = "devin_prompt_file"
        export_path = None
        if state.runtime_dir:
            export_path = str(Path(state.runtime_dir) / "devin-export.atif")
        return build_launch_argv(
            session_id=state.provider_session_id or None,
            packet=launch_packet,
            cwd=state.worktree,
            model=state.model,
            permission_mode=state.permission_mode,
            executable=state.executable,
            create=bool(state.create_session),
            effort=state.effort,
            yolo=bool(state.yolo),
            max_turns=state.max_turns,
            output_format=None,
            adapter="devin-cli",
            check=False,
            export_path=export_path,
        )
    if state.adapter == "omp-cli":
        state.goal_launch_mode = "omp_json_stream"
        return build_launch_argv(
            session_id=state.provider_session_id or None,
            packet=launch_packet,
            cwd=state.worktree,
            model=state.model,
            permission_mode=state.permission_mode,
            executable=state.executable,
            create=bool(state.create_session),
            effort=state.effort,
            yolo=bool(state.yolo),
            max_turns=state.max_turns,
            output_format=None,
            adapter="omp-cli",
            check=False,
        )
    detection = detect_native_grok_goal(state.executable)
    # Record actual capability; do not invent flags. Headless packet launch is
    # the compatible fallback when no public --goal entrypoint exists.
    state.goal_entrypoint_advertised = bool(
        detection.get("advertised_headless_entrypoint")
    )
    if state.goal_mode_behaviorally_verified and state.goal_prompt_path:
        state.goal_launch_mode = "headless_slash_goal"
    else:
        state.goal_launch_mode = "headless_compatible_fallback"
    return build_launch_argv(
        session_id=state.session_id,
        packet=launch_packet,
        cwd=state.worktree,
        model=state.model,
        permission_mode=state.permission_mode,
        executable=state.executable,
        create=bool(state.create_session),
        effort=state.effort,
        yolo=bool(state.yolo),
        max_turns=state.max_turns,
        output_format=state.output_format,
        adapter=state.adapter,
        check=bool(state.check),
        native_goal=state.goal_mode_behaviorally_verified,
    )


def _running_report(state: FullRunState, *, final_head: str) -> dict[str, Any]:
    return {
        "run_id": _expected_run_id(state.session_id),
        "session_id": state.session_id,
        "branch": state.branch,
        "start_head": state.start_head,
        "final_head": final_head,
        "status": "running",
        "batches": [],
        "acceptance": [],
        "commits": [],
        "blockers": [],
        "merge_authority": False,
        "docs_changed": [],
        "tests": {},
        "security_notes": ["transcript private; status bounded; no merge authority"],
        "remaining_risks": [],
        "attempt": state.attempt,
    }


def _archive_and_reset_resume_attempt(
    repo_root: Path,
    state: FullRunState,
    *,
    checkpoint_head: str,
) -> None:
    root = full_run_root(repo_root, state.session_id)
    archive = root / "attempts" / f"attempt-{state.attempt:04d}"
    try:
        archive.lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValidationIssue(
            "full_run_attempt_archive_exists",
            f"Attempt archive already exists: {archive}",
        )
    ensure_private_dir(archive, repo_root=Path(repo_root))
    atomic_write_json(
        archive / "state.json",
        state.to_dict(),
        repo_root=Path(repo_root),
    )
    for name in (
        "events.jsonl",
        "report.json",
        "exit_record.json",
        "supervisor.fingerprint.json",
        "worker.fingerprint.json",
        "worker.pid",
        "worker.pgid",
        "transcript.log",
        STOP_REQUEST_NAME,
    ):
        source = root / name
        if repo_regular_file_exists(Path(repo_root), source):
            move_repo_regular_file(
                Path(repo_root),
                source,
                archive / name,
                replace=False,
            )

    state.attempt += 1
    state.supervision_token = secrets.token_hex(24)
    state.credential_granted_names = []
    state.credential_grant_digests = {}
    state.credential_grant_lengths = {}
    state.credential_grant_metadata_mac = None
    state.acknowledged_high_risk_checkpoints = []
    state.pending_high_risk_checkpoint = None
    state.closed_process_identity = None
    state.interruption_evidence = None
    state.pid = None
    state.pgid = None
    state.fingerprint = None
    state.exit_code = None
    state.exit_sidecar_pid = None
    state.status = "pending"
    state.blocker = None
    state.completed_at = None
    state.launched_at = None
    state.heartbeat_at = None
    state.next_action = "launch"
    state.head = checkpoint_head
    state.create_session = False
    with open_repo_text(Path(repo_root), root / "events.jsonl", mode="w"):
        pass
    with open_repo_text(Path(repo_root), root / "transcript.log", mode="w"):
        pass
    atomic_write_json(
        root / "report.json",
        _running_report(state, final_head=checkpoint_head),
        repo_root=Path(repo_root),
    )
    _append_event(
        root / "events.jsonl",
        {
            "timestamp": _utc_now(),
            "session_id": state.session_id,
            "branch": state.branch,
            "head": checkpoint_head,
            "batch": state.batch or 0,
            "type": "run_started",
            "summary": f"Full-run resume attempt {state.attempt} prepared",
        },
        expected_session_id=state.session_id,
        expected_branch=state.branch,
        repo_root=Path(repo_root),
    )


def _capture_devin_session_id(
    state: FullRunState,
    root: Path,
    repo_root: Path,
    launch_env: Mapping[str, str],
) -> str | None:
    """Capture the exact Devin provider session id for the current worktree.

    Runs ``devin list --format json`` using the exact isolated worker env
    (XDG_CONFIG_HOME/XDG_DATA_HOME), filters to the current working_directory,
    and either requires exactly one matching session or cross-checks the
    transport-authored ATIF export's top-level ``session_id``. Rejects
    zero/multiple/mismatched candidates with a bounded diagnostic event.
    """
    exe = (state.executable or "devin").strip() or "devin"
    worktree = Path(state.worktree).expanduser().resolve()
    argv = [exe, "list", "--format", "json"]
    events_path = root / "events.jsonl"

    def _event(summary: str, etype: str = "devin_capture_failed", **extra: Any) -> None:
        _append_event(
            events_path,
            {
                "timestamp": _utc_now(),
                "session_id": state.session_id,
                "branch": state.branch,
                # Discovery can happen after a fast worker has committed but
                # before monitor state has absorbed the new tip. Bind the host
                # event to the live feature tip so event ancestry cannot appear
                # to regress solely because the parked monitor woke late.
                "head": _git_head(worktree) or state.head or state.start_head,
                "batch": state.batch or 0,
                "type": etype,
                "summary": summary,
                **extra,
            },
            expected_session_id=state.session_id,
            expected_branch=state.branch,
            repo_root=repo_root,
        )

    try:
        result = subprocess.run(
            argv,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=15,
            env=dict(launch_env),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _event(f"devin list failed: {type(exc).__name__}")
        return None
    if result.returncode != 0:
        _event(f"devin list exited {result.returncode}")
        return None
    try:
        sessions = json.loads(result.stdout)
    except json.JSONDecodeError:
        _event("devin list returned invalid JSON")
        return None
    if not isinstance(sessions, list):
        _event("devin list returned non-list")
        return None

    candidates = [
        s
        for s in sessions
        if isinstance(s, dict)
        and s.get("working_directory")
        and Path(str(s["working_directory"])).expanduser().resolve() == worktree
        and isinstance(s.get("id"), (str, int))
    ]

    export_path = Path(state.runtime_dir or root) / "devin-export.atif"
    atif_session_id: str | None = None
    if export_path.is_file():
        try:
            atif = json.loads(export_path.read_text(encoding="utf-8"))
            if isinstance(atif, Mapping):
                atif_session_id = str(atif.get("session_id") or "").strip() or None
        except (OSError, json.JSONDecodeError):
            pass

    if atif_session_id:
        matching = [c for c in candidates if str(c.get("id")) == atif_session_id]
        if len(matching) == 1:
            selected = matching[0]
            _event(
                "Devin session captured via ATIF cross-check",
                etype="devin_session_captured",
                provider_session_id=str(selected["id"]),
                candidate_count=1,
            )
            return str(selected["id"])
        if not candidates:
            # The worker exited before the first listing; the ATIF export in the
            # private runtime directory is bound to this full-run attempt.
            _event(
                "Devin session captured from ATIF after fast worker exit",
                etype="devin_session_captured",
                provider_session_id=atif_session_id,
                candidate_count=0,
            )
            return atif_session_id
        _event(
            "ATIF session_id does not match isolated listing",
            expected_session_id=atif_session_id,
            candidate_count=len(candidates),
        )
        return None

    if len(candidates) == 1:
        selected = candidates[0]
        _event(
            "Devin session captured from isolated listing",
            etype="devin_session_captured",
            provider_session_id=str(selected["id"]),
            candidate_count=1,
        )
        return str(selected["id"])
    _event(
        f"Expected exactly one Devin session for worktree, found {len(candidates)}",
        candidate_count=len(candidates),
    )
    return None


def _prepare_resume_attempt(repo_root: Path, state: FullRunState) -> str:
    supported_adapters = {"fixture", "grok-build", "devin-cli", "omp-cli"}
    if state.adapter not in supported_adapters:
        raise ValidationIssue(
            "full_run_resume_adapter_unsupported",
            "Production full-run resume requires a supported production adapter",
        )
    if state.adapter == "grok-build" and state.grok_auth_strategy == "oauth_shared_file":
        # Validate the canonical refresh-token authority before archiving or
        # incrementing the prior attempt. Token bytes may rotate; path identity
        # and owner-private storage may not.
        _revalidate_shared_grok_auth(state)
    if state.adapter == "devin-cli" and not state.provider_session_id:
        raise ValidationIssue(
            "full_run_devin_resume_missing_provider_session",
            "Devin full-run resume requires a captured provider session id",
        )
    if state.adapter == "omp-cli" and not state.provider_session_id:
        raise ValidationIssue(
            "full_run_omp_resume_missing_provider_session",
            "OMP full-run resume requires a captured provider session id",
        )
    if state.launch_start_head != state.start_head:
        raise ValidationIssue(
            "full_run_start_head_mutated",
            "Immutable launch start no longer matches staged start_head",
        )
    closed = state.closed_process_identity
    interruption = state.interruption_evidence
    if not isinstance(closed, Mapping) or not isinstance(interruption, Mapping):
        raise ValidationIssue(
            "full_run_resume_unauthenticated",
            "Resume requires a capability-authenticated prior interruption and closed identity",
        )
    if (
        interruption.get("authority") != "host_stop"
        or interruption.get("closed_identity_digest") != closed.get("identity_digest")
        or interruption.get("attempt") != state.attempt
    ):
        raise ValidationIssue(
            "full_run_resume_unauthenticated",
            "Resume interruption evidence does not bind the prior attempt identity",
        )
    if state.pid is not None or state.pgid is not None or state.fingerprint is not None:
        raise ValidationIssue(
            "full_run_resume_identity_not_retired",
            "Resume requires prior PID/PGID/fingerprint retirement",
        )
    lingering = _supervised_alive(state)
    if lingering:
        raise ValidationIssue(
            "full_run_resume_process_alive",
            f"Prior supervised descendants still live: {sorted(lingering)}",
        )
    checkpoint = _git_head(Path(state.worktree))
    if not checkpoint or not _is_ancestor(Path(state.worktree), state.start_head, checkpoint):
        raise ValidationIssue(
            "full_run_resume_checkpoint_invalid",
            "Resume checkpoint must be an exact descendant of immutable start_head",
        )
    _validate_full_run_git_contract(
        repo_root,
        worktree=state.worktree,
        branch=state.branch,
        start_head=state.start_head,
        packet_path=state.packet_path,
        adapter=state.adapter,
        expected_current_head=checkpoint,
    )
    if state.adapter != "fixture":
        _assert_origin_binding(repo_root, state, expected_feature_tip=checkpoint)
        if not state.supervisor_executable or not state.supervision_canary_passed:
            raise ValidationIssue(
                "full_run_supervision_unavailable",
                "Resume requires the original qualified recursive supervision domain",
            )
        state.supervision_canary_passed = _run_supervision_canary(
            Path(state.supervisor_executable)
        )
    root = full_run_root(repo_root, state.session_id)
    terminal_types = _terminal_event_types_present(
        root / "events.jsonl",
        repo_root=Path(repo_root),
    )
    if terminal_types:
        raise ValidationIssue(
            "full_run_resume_prepare_terminal",
            "Refusing resume launch over a session whose event log is already "
            f"terminal ({', '.join(sorted(terminal_types))})",
            path=str(root / "events.jsonl"),
            hint="Start a new session_id; do not rebuild a completed or blocked run",
        )
    _archive_and_reset_resume_attempt(repo_root, state, checkpoint_head=checkpoint)
    return checkpoint


@_locked_full_run
def launch_full_run(
    repo_root: Path,
    *,
    session_id: str,
    background: bool = True,
    credential_grant_names: Sequence[str] | None = None,
    grant_grok_auth: bool = False,
    grant_devin_auth: bool = False,
    grant_github_push: bool = False,
    resume: bool = False,
) -> dict[str, Any]:
    """Background-launch Grok (or explicit fixture) for one exact session.

    Never accepts KEY=VALUE secrets on argv. Credential grants are by name only.
    """
    del background  # always non-blocking Popen
    state = load_state(repo_root, session_id)
    root = full_run_root(repo_root, session_id)
    if resume:
        _revalidate_staged_packet_binding(Path(repo_root), state)
        _prepare_resume_attempt(Path(repo_root), state)
        save_state(repo_root, state)
    elif state.status in {"complete", "stopped", "blocked", "failed"}:
        raise ValidationIssue(
            "full_run_terminal",
            f"Cannot launch terminal full-run session `{session_id}` ({state.status})",
        )
    elif state.launched_at or state.closed_process_identity:
        raise ValidationIssue(
            "full_run_already_running" if state.status == "healthy" else "full_run_relaunch_requires_resume",
            "A prepared attempt may launch once; authenticated resume is required afterward",
        )

    if state.fingerprint:
        ok, reason = verify_fingerprint(
            state.fingerprint, expected_session_id=session_id
        )
        pid_alive = bool(state.pid and _pid_alive(int(state.pid)))
        group_alive = _process_group_alive(state.pgid)
        supervised = _supervised_alive(state)
        if ok or pid_alive or group_alive or supervised:
            raise ValidationIssue(
                "full_run_already_running",
                f"Full-run session `{session_id}` retains a live or unverifiable process identity",
            )
        raise ValidationIssue(
            "full_run_relaunch_unauthenticated",
            f"Recorded process is dead but has no authenticated resume transition: {reason}",
        )

    # This is intentionally the last packet source used before launch. The
    # worker consumes only the private staged copy; source or copy drift blocks
    # before credential setup and before any supervisor/provider spawn.
    _revalidate_staged_packet_binding(Path(repo_root), state)
    _validate_full_run_git_contract(
        Path(repo_root),
        worktree=state.worktree,
        branch=state.branch,
        start_head=state.start_head,
        packet_path=state.packet_path,
        adapter=state.adapter,
        expected_current_head=state.head or state.start_head,
    )
    if state.launch_start_head != state.start_head:
        raise ValidationIssue(
            "full_run_start_head_mutated",
            "Immutable launch start no longer matches staged start_head",
        )
    if state.adapter != "fixture":
        expected_remote = (
            state.head if resume else state.initial_remote_feature_tip
        )
        _assert_origin_binding(Path(repo_root), state, expected_feature_tip=expected_remote)
        if not state.supervision_canary_passed:
            raise ValidationIssue(
                "full_run_supervision_canary_failed",
                "Production launch requires a successful recursive-supervision canary",
            )

    effective_grant_names = _normalize_credential_grant_names(
        state.credential_grant_names
        if credential_grant_names is None
        else credential_grant_names
    )
    state.credential_grant_names = effective_grant_names
    parent_env = dict(os.environ)
    launch_env = build_full_run_env(
        state=state,
        root=root,
        parent_env=parent_env,
        credential_grant_names=effective_grant_names,
    )
    granted_names: list[str] = []

    transcript = root / "transcript.log"
    for isolated_dir in (
        root / "worker-home",
        root / "worker-home" / ".config",
        root / "worker-home" / ".cache",
        root / "worker-home" / ".local",
        root / "worker-home" / ".local" / "share",
        root / GROK_HOME_REL,
        root / "worker-tmp",
        root / "worker-tmp" / "runtime",
    ):
        ensure_private_dir(isolated_dir, repo_root=Path(repo_root))
    for stale_path in (
        root / "exit_record.json",
        root / "supervisor.fingerprint.json",
        root / STOP_REQUEST_NAME,
    ):
        if repo_regular_file_exists(Path(repo_root), stale_path):
            raise ValidationIssue(
                "full_run_stale_exit_artifact",
                "Refusing launch while an unarchived supervisor artifact exists",
                path=str(stale_path),
            )
    if not state.supervisor_executable or not state.supervision_token:
        raise ValidationIssue(
            "full_run_supervision_unavailable",
            "Launch is missing its host-owned recursive supervision identity",
        )
    # Shared OAuth is configured only after every non-secret preflight passes.
    # The provider still receives an isolated HOME/GROK_HOME; only Grok's native
    # auth path points at the one validated canonical refresh-token authority.
    proc: subprocess.Popen[bytes] | None = None
    try:
        if state.adapter != "fixture":
            _configure_git_commit_identity(
                state,
                launch_env,
                parent_env=parent_env,
            )
            _configure_github_push_auth(
                state,
                launch_env,
                grant_github_push=grant_github_push,
                parent_env=parent_env,
            )
        elif grant_github_push:
            raise ValidationIssue(
                "full_run_github_push_auth_not_applicable",
                "GitHub push projection is unavailable in explicit fixture mode",
            )
        if state.adapter == "grok-build":
            _configure_grok_auth(
                Path(repo_root),
                root,
                state,
                launch_env,
                grant_grok_auth=grant_grok_auth,
            )
        if state.adapter == "devin-cli":
            _configure_devin_auth(
                Path(repo_root),
                root,
                state,
                launch_env,
                grant_devin_auth=grant_devin_auth,
                parent_env=parent_env,
            )

        if state.adapter == "grok-build":
            from .worker_routing import (  # noqa: PLC0415
                GROK_RETIRED_COMPOSER_MODEL,
                probe_grok_capabilities,
                select_preferred_grok_worker_model,
            )

            grok_capabilities = probe_grok_capabilities(
                state.executable,
                goal_auth_path=(
                    Path(launch_env["GROK_AUTH_PATH"])
                    if launch_env.get("GROK_AUTH_PATH")
                    else None
                ),
                goal_api_key=launch_env.get("XAI_API_KEY"),
                command_env=launch_env,
                goal_behavioral_evidence=state.goal_behavioral_artifact_path,
            )
            core_unavailable = grok_capabilities.core_launch_unavailable_reason(
                create=not resume,
                check=bool(state.check),
            )
            if core_unavailable:
                raise ValidationIssue(
                    "grok_launch_capability_unavailable",
                    "Installed Grok Build lacks a required noninteractive launch capability",
                    hint=core_unavailable,
                )
            if not grok_capabilities.authenticated or not grok_capabilities.models:
                catalog = grok_capabilities.capability("model_catalog")
                raise ValidationIssue(
                    "grok_live_catalog_unavailable",
                    "Grok launch requires an authenticated live model catalog",
                    hint=(catalog.reason if catalog is not None else "model_catalog_not_probed"),
                )
            requested_model = str(state.model or "").strip()
            if requested_model in {"", "auto"}:
                selected = select_preferred_grok_worker_model(grok_capabilities)
                if not selected:
                    if grok_capabilities.default_model == GROK_RETIRED_COMPOSER_MODEL:
                        raise ValidationIssue(
                            "grok_model_retired",
                            f"Grok model `{GROK_RETIRED_COMPOSER_MODEL}` is retired; "
                            "use grok-4.5 when the live catalog offers it",
                        )
                    raise ValidationIssue(
                        "grok_live_default_model_unavailable",
                        "Grok live catalog did not identify a usable worker model",
                    )
                state.model = selected
            elif requested_model == GROK_RETIRED_COMPOSER_MODEL:
                raise ValidationIssue(
                    "grok_model_retired",
                    f"Grok model `{requested_model}` is retired; use grok-4.5",
                )
            elif requested_model not in grok_capabilities.models:
                raise ValidationIssue(
                    "grok_model_not_in_live_catalog",
                    f"Requested Grok model `{requested_model}` is absent from the authenticated live catalog",
                )
            state.goal_mode_behaviorally_verified = (
                grok_capabilities.goal_mode_behaviorally_verified
            )
            state.goal_entrypoint_advertised = (
                grok_capabilities.goal_entrypoint_advertised
            )
            state.goal_behavioral_evidence = (
                grok_capabilities.goal_behavioral_evidence
            )
            if state.goal_mode_behaviorally_verified:
                _prepare_goal_prompt(Path(repo_root), root, state)
                state.notes.append(
                    "goal_behavioral_evidence="
                    f"{grok_capabilities.goal_behavioral_evidence or 'verified'}"
                )
            else:
                state.goal_prompt_path = None
                state.goal_prompt_identity = None
                state.goal_prompt_sha256 = None
                state.goal_prompt_size = None
                goal_evidence = grok_capabilities.capability("goal_behavior")
                state.notes.append(
                    "goal_fallback="
                    f"{goal_evidence.reason if goal_evidence is not None else 'not_probed'}"
                )

        # Never return credential values. Names are strict environment
        # identifiers and cannot smuggle KEY=VALUE material into state/output.
        # This snapshot occurs only after both explicit auth routes have added
        # any derived launch-scoped grant.
        granted_names = sorted(
            name
            for name in state.credential_grant_names
            if name in launch_env and launch_env[name]
        )
        state.credential_granted_names = list(granted_names)
        state.credential_grant_digests = {
            name: _credential_grant_digest(state, name, launch_env[name])
            for name in granted_names
        }
        state.credential_grant_lengths = {
            name: len(launch_env[name]) for name in granted_names
        }
        state.credential_grant_metadata_mac = (
            _credential_grant_metadata_mac(state) if granted_names else None
        )

        # Recheck at the final provider-argv boundary as well as during launch
        # preflight, closing the host-side window while auth/capability probes
        # ran. No provider process exists yet.
        _revalidate_staged_packet_binding(Path(repo_root), state)
        # Build argv only after Grok auth selection has resolved and bound the
        # exact executable. The supervisor receives that same path plus the
        # identity it must recheck immediately before provider spawn.
        reject_fugu_implementation_route(
            state.adapter,
            state.executable,
            requested_model=state.model,
            environment=launch_env,
        )
        provider_argv = build_full_run_argv(state)
        if resume and state.adapter != "fixture":
            try:
                resume_index = provider_argv.index("--resume")
            except ValueError as exc:
                raise ValidationIssue(
                    "full_run_resume_argv_ambiguous",
                    "resume argv must contain exact --resume <session-id>",
                ) from exc
            expected_resume_id = (
                state.provider_session_id
                if state.adapter in {"devin-cli", "omp-cli"}
                else state.session_id
            )
            if (
                resume_index + 1 >= len(provider_argv)
                or provider_argv[resume_index + 1] != expected_resume_id
                or "--session-id" in provider_argv
            ):
                raise ValidationIssue(
                    "full_run_resume_argv_ambiguous",
                    "resume argv is not bound to the exact captured session id",
                )
        state.last_argv = list(provider_argv)
        selected_packet_identity = (
            state.goal_prompt_identity
            if state.goal_mode_behaviorally_verified
            else state.staged_packet_identity
        )
        selected_packet_sha256 = (
            state.goal_prompt_sha256
            if state.goal_mode_behaviorally_verified
            else state.packet_sha256
        )
        selected_packet_size = (
            state.goal_prompt_size
            if state.goal_mode_behaviorally_verified
            else state.packet_size
        )
        supervisor_argv = _provider_supervisor_argv(
            root=root,
            session_id=session_id,
            provider_argv=provider_argv,
            attempt=state.attempt,
            supervisor_executable=state.supervisor_executable,
            staged_packet_path=str(
                state.goal_prompt_path
                if state.goal_mode_behaviorally_verified
                else state.staged_packet_path
            ),
            staged_packet_identity=dict(selected_packet_identity or {}),
            packet_sha256=str(selected_packet_sha256),
            packet_size=int(selected_packet_size or 0),
            provider_executable_identity=(
                state.grok_executable_identity
                if state.adapter == "grok-build"
                else None
            ),
        )

        # Open transcript for inheritance, then close the parent descriptor so
        # separate CLI invocations do not retain handles or ResourceWarnings.
        with open_repo_text(Path(repo_root), transcript, mode="a") as stdout_handle:
            proc = subprocess.Popen(
                supervisor_argv,
                cwd=state.worktree if state.adapter != "fixture" else state.worktree,
                env=launch_env,
                stdout=stdout_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
            )

        pgid = os.getpgid(proc.pid) if hasattr(os, "getpgid") else proc.pid
        # Brief settle so Darwin proc_pidpath/ps can observe the blocked
        # supervisor identity before capture falls back to sys.executable.
        time.sleep(0.1 if sys.platform == "darwin" else 0.05)
        fp = capture_fingerprint(
            pid=proc.pid,
            pgid=pgid,
            session_id=session_id,
            executable_hint=sys.executable,
        )
        state.pid = proc.pid
        state.pgid = pgid
        state.fingerprint = fp.to_dict()
        state.status = "healthy"
        state.launched_at = _utc_now()
        state.heartbeat_at = state.launched_at
        state.next_action = "parked_monitor"
        if resume:
            state.create_session = False
        state.exit_sidecar_pid = proc.pid
        state.exit_code = None

        # The supervisor is still blocked before provider spawn. Publish every
        # launcher-owned identity and state artifact before releasing it.
        atomic_write_json(
            root / "supervisor.fingerprint.json",
            fp.to_dict(),
            repo_root=Path(repo_root),
        )
        with open_repo_text(Path(repo_root), root / "worker.pid", mode="w") as handle:
            handle.write(str(proc.pid) + "\n")
        with open_repo_text(Path(repo_root), root / "worker.pgid", mode="w") as handle:
            handle.write(str(pgid) + "\n")
        atomic_write_json(
            root / "worker.fingerprint.json",
            fp.to_dict(),
            repo_root=Path(repo_root),
        )
        _append_event(
            root / "events.jsonl",
            {
                "timestamp": state.launched_at,
                "session_id": session_id,
                "branch": state.branch,
                "head": state.head or state.start_head,
                "batch": state.batch or 0,
                "type": "heartbeat",
                "summary": "Worker launch staged in background supervisor",
            },
            expected_session_id=session_id,
            expected_branch=state.branch,
            expected_high_risk_checkpoints=state.planned_high_risk_checkpoints,
            repo_root=Path(repo_root),
        )
        save_state(repo_root, state)

    except BaseException as launch_error:
        _cleanup_refused_launch(
            Path(repo_root),
            root,
            state,
            proc,
            cause=launch_error,
        )
        raise

    assert proc is not None
    # Durable state and stop authority now exist. Invoke the irreversible
    # ownership transfer outside refused-launch cleanup: an asynchronous
    # exception at or after the complete handoff must never erase the only
    # identity capable of stopping a provider that may already have started.
    try:
        _handoff_supervision_secret(proc, state)
    except _PreTransferHandoffError as handoff_error:
        _cleanup_refused_launch(
            Path(repo_root),
            root,
            state,
            proc,
            cause=handoff_error,
        )
        raise
    except BaseException:
        # State, fingerprint, and stop capability remain durable. Detach only
        # this local Popen wrapper so propagation cannot emit a misleading
        # ResourceWarning or close over lifecycle ownership.
        try:
            proc.stdout = None
            proc.stderr = None
            proc.stdin = None
            if proc.returncode is None:
                proc.returncode = 0
        except Exception:  # noqa: BLE001
            pass
        raise
    # Drop Popen without waiting: the durable fingerprint and supervisor exit
    # record now own lifecycle tracking. Suppress intentional detach warnings.
    try:
        proc.stdout = None
        proc.stderr = None
        proc.stdin = None
        if proc.returncode is None:
            proc.returncode = 0
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "action": "full_run_launch",
        "session_id": session_id,
        "pid": proc.pid,
        "pgid": pgid,
        "status": state.status,
        "driver_contract": "parked_monitor",
        "driver_monitor_mode": "parked_monitor",
        "returned_promptly": True,
        "argv": provider_argv,
        "adapter": state.adapter,
        "credential_grant_names_present": granted_names,
        "grok_auth_strategy": state.grok_auth_strategy,
        "github_push_auth_strategy": state.github_push_auth_strategy,
        "model_calls_made": state.adapter != "fixture",
        "merge_authority": False,
    }


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        waited, _status = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return False
    except (ChildProcessError, OSError):
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group_alive(pgid: int | None) -> bool:
    if not pgid:
        return False
    try:
        os.killpg(int(pgid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _settle_recorded_supervisor_exit(
    pid: int | None,
    pgid: int | None,
    *,
    timeout_seconds: float = EXIT_RECORD_SETTLE_SECONDS,
) -> tuple[bool, bool]:
    """Bridge the host-sidecar write/exit race without accepting live groups.

    The launcher-owned supervisor must write its durable exit record immediately
    before it exits.  A monitor can therefore observe a valid record during that
    tiny interval.  Give the exact recorded supervisor a bounded chance to reap;
    a provider or descendant group that remains alive after the window is still
    classified as premature and fails closed.
    """
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        _reap_supervisor_if_child(pid)
        pid_alive = bool(pid and _pid_alive(pid))
        group_alive = _process_group_alive(pgid)
        if not pid_alive and not group_alive:
            return False, False
        if time.monotonic() >= deadline:
            return pid_alive, group_alive
        time.sleep(0.01)


def _supervised_alive(state: FullRunState) -> set[int]:
    if not state.supervisor_executable or not state.supervision_token:
        if state.adapter == "fixture":
            return set()
        raise ValidationIssue(
            "full_run_supervision_unavailable",
            "Production run is missing its host-owned recursive supervisor identity",
        )
    qualified = _qualified_process_supervisor()
    if Path(state.supervisor_executable).resolve() != qualified:
        raise ValidationIssue(
            "full_run_supervision_executable_changed",
            "Recorded recursive supervisor is not the currently qualified system executable",
        )
    return _scan_supervision_pids(qualified, _descendant_supervision_marker(state))


def _identity_digest(identity: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(identity), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _retire_process_identity(
    state: FullRunState,
    *,
    reason: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Move authenticated active IDs into closed history and erase signal targets."""
    identity = {
        "pid": state.pid,
        "pgid": state.pgid,
        "fingerprint": dict(state.fingerprint or {}),
        "attempt": state.attempt,
        "exit_code": state.exit_code,
        "closed_at": _utc_now(),
        "reason": reason,
        "evidence": dict(evidence),
    }
    identity["identity_digest"] = _identity_digest(identity)
    state.closed_process_identity = identity
    state.process_history.append(dict(identity))
    state.pid = None
    state.pgid = None
    state.fingerprint = None
    state.exit_sidecar_pid = None
    return identity


def _record_interruption(
    state: FullRunState,
    *,
    closed_identity: Mapping[str, Any],
    reason: str,
) -> None:
    state.interruption_evidence = {
        "session_id": state.session_id,
        "attempt": state.attempt,
        "closed_identity_digest": closed_identity.get("identity_digest"),
        "recorded_at": _utc_now(),
        "reason": reason,
        "authority": "host_stop",
    }


def _read_events(
    events_path: Path,
    *,
    expected_session_id: str,
    expected_branch: str,
    expected_high_risk_checkpoints: Sequence[str] | None = None,
    exact_secret_values: frozenset[str] | set[str] | tuple[str, ...] | None = None,
    credential_grant_state: FullRunState | None = None,
    shared_oauth_safe_projection: bool = False,
    allow_partial_final: bool = False,
    repo_root: Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if repo_root is not None:
        try:
            if not repo_regular_file_exists(repo_root, events_path):
                return [], []
        except StorageError as exc:
            return [], [exc.message]
    elif not events_path.exists() and not events_path.is_symlink():
        return [], []
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_terminal = False
    seen_high_risk_checkpoints: set[str] = set()
    try:
        raw = _read_bounded_regular_bytes(
            events_path,
            max_bytes=MAX_EVENT_FILE_BYTES,
            label="event log",
            repo_root=repo_root,
        )
    except StorageError as exc:
        return [], [exc.message]

    complete_final = not raw or raw.endswith(b"\n")
    raw_lines = raw.splitlines()
    if not complete_final and raw_lines:
        if allow_partial_final:
            raw_lines = raw_lines[:-1]
        else:
            errors.append("final event record is incomplete")
            raw_lines = raw_lines[:-1]
    if len(raw_lines) > MAX_EVENT_LINES:
        return [], [f"event log exceeds {MAX_EVENT_LINES} line limit"]

    for line_no, raw_line in enumerate(raw_lines, 1):
        if len(raw_line) > MAX_EVENT_LINE_BYTES:
            errors.append(f"line {line_no}: event exceeds line-size limit")
            continue
        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            errors.append(f"line {line_no}: event must be UTF-8")
            continue
        if not line:
            continue
        try:
            event = _loads_bounded_json(line, label="event")
        except (json.JSONDecodeError, ValueError, RecursionError):
            errors.append(f"line {line_no}: malformed or over-budget json")
            continue
        if not isinstance(event, dict):
            errors.append(f"line {line_no}: event must be object")
            continue
        try:
            _assert_bounded_json_structure(event, label="event")
        except StorageError as exc:
            errors.append(f"line {line_no}: {exc.message}")
            continue
        if credential_grant_state and _contains_persisted_credential_grant(
            event, credential_grant_state
        ):
            errors.append(f"line {line_no}: event contains secret-shaped content")
            continue
        if shared_oauth_safe_projection:
            # Validate the original confidence fields before removing OAuth
            # worker free text. Projecting first would let malformed or
            # secret-shaped unsure_about values bypass the fail-closed event
            # contract and could conflate an invalid list with asserted-clean.
            confidence_errors: list[str] = []
            _validate_confidence_fields(event, confidence_errors)
            if "unsure_about" in event and _contains_full_run_secret(
                {"unsure_about": event.get("unsure_about")},
                exact_values=exact_secret_values,
                credential_grant_state=credential_grant_state,
            ):
                if not any("secret-shaped" in item for item in confidence_errors):
                    confidence_errors.append(
                        "unsure_about contains secret-shaped content"
                    )
            if confidence_errors:
                errors.extend(
                    f"line {line_no}: {error}" for error in confidence_errors
                )
                continue
        validation_event = event
        if shared_oauth_safe_projection:
            validation_event = {
                key: event[key]
                for key in _SHARED_OAUTH_PUBLIC_EVENT_FIELDS
                if key in event
            }
            # Presence remains part of the schema, but OAuth worker free text
            # is neither trusted nor retained after token rotation.
            if "summary" in event:
                validation_event["summary"] = "shared OAuth event"
            # unsure_about free text is likewise hidden on this route, but
            # suppression must never read as the worker's asserted-clean empty
            # list: project a bounded derived count so consumers can tell
            # "reservations existed" apart from "asserted none".
            if isinstance(event.get("unsure_about"), list):
                validation_event["unsure_about_count"] = _project_confidence_signal(
                    event
                )["unsure_about_count"]
        verrs = validate_event(
            validation_event,
            allow_projected_unsure_count=shared_oauth_safe_projection,
            expected_session_id=expected_session_id,
            expected_branch=expected_branch,
            seen_terminal=seen_terminal,
            expected_high_risk_checkpoints=expected_high_risk_checkpoints,
            seen_high_risk_checkpoints=tuple(seen_high_risk_checkpoints),
            exact_secret_values=exact_secret_values,
            credential_grant_state=credential_grant_state,
        )
        if verrs:
            errors.extend(f"line {line_no}: {e}" for e in verrs)
            continue
        if event.get("type") in TERMINAL_EVENT_TYPES:
            seen_terminal = True
        if event.get("type") == "high_risk_checkpoint":
            seen_high_risk_checkpoints.add(str(event.get("checkpoint_id")))
        rows.append(
            {
                key: value
                for key, value in validation_event.items()
                if key != "summary"
            }
            if shared_oauth_safe_projection
            else event
        )
    return rows, errors


def _event_log_signature(repo_root: Path, events_path: Path) -> dict[str, Any]:
    """Return a cheap identity for an append-only event log.

    A matching signature lets an ordinary healthy poll reuse the already
    validated structural summary. Terminal, checkpoint-ack, and forced-full
    paths still re-read and validate the complete log.
    """
    candidate = guard_repo_path(repo_root, events_path)
    try:
        info = candidate.lstat()
    except FileNotFoundError:
        return {"exists": False}
    except OSError as exc:
        raise StorageError(
            "event_log_unavailable",
            f"event log metadata is unavailable: {type(exc).__name__}",
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise StorageError(
            "event_log_not_regular",
            "event log must be a regular non-symlink file",
        )
    if info.st_size > MAX_EVENT_FILE_BYTES:
        raise StorageError(
            "event_log_too_large",
            f"event log exceeds {MAX_EVENT_FILE_BYTES} byte limit",
        )
    return {
        "exists": True,
        "dev": info.st_dev,
        "ino": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


_SHARED_OAUTH_PUBLIC_EVENT_FIELDS: tuple[str, ...] = (
    "timestamp",
    "session_id",
    "branch",
    "head",
    "batch",
    "type",
    "checkpoint_id",
    "change_id",
    "change_kind",
    # Closed three-value enum, no free text: safe to project and lets
    # malformed confidence fail closed on the shared-OAuth route too.
    "confidence",
)


def _driver_visible_events(
    events: Sequence[Mapping[str, Any]],
    *,
    shared_oauth: bool,
) -> list[dict[str, Any]]:
    """Project OAuth events onto validated structural fields only.

    Free-text summaries cannot be safely redacted after a refresh-token
    rotation because a prior opaque value is intentionally no longer stored.
    """
    if not shared_oauth:
        return [dict(event) for event in events]
    return [
        {
            key: event[key]
            for key in _SHARED_OAUTH_PUBLIC_EVENT_FIELDS
            if key in event
        }
        for event in events
    ]


def format_follow_stream_line(
    event: Mapping[str, Any],
    *,
    shared_oauth: bool = False,
) -> str:
    """Format one sanitized human-readable follow-mode line (no model inference)."""
    etype = str(event.get("type") or "event")
    ts = str(event.get("timestamp") or "")
    batch = event.get("batch")
    head = str(event.get("head") or "")
    short_head = head[:12] if head else "-"
    batch_s = f"b{batch}" if batch is not None else "b?"
    if shared_oauth:
        # Never include free-text summary under shared OAuth.
        return f"{ts} [{batch_s}] {etype} @ {short_head}"
    summary = str(event.get("summary") or "").strip()
    if len(summary) > 200:
        summary = summary[:197] + "..."
    if summary:
        return f"{ts} [{batch_s}] {etype} @ {short_head} — {summary}"
    return f"{ts} [{batch_s}] {etype} @ {short_head}"


_GROK_STREAM_USAGE_KEYS = frozenset(
    {
        "inputTokens",
        "outputTokens",
        "cacheReadTokens",
        "cacheWriteTokens",
        "totalTokens",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "total_tokens",
    }
)


def decode_grok_streaming_event(
    line: str,
    *,
    shared_oauth: bool = False,
    exact_values: Sequence[str] = (),
    expected_session_id: str | None = None,
    credential_grant_state: FullRunState | None = None,
    force_redact_provider_fields: bool = False,
) -> dict[str, Any] | None:
    """Decode one Grok JSONL record into a bounded, sanitized follow record."""
    if (
        not isinstance(line, str)
        or not line.strip()
        or len(line.encode("utf-8")) > MAX_GROK_STREAM_RECORD_BYTES
    ):
        return None
    if credential_grant_state is not None and not _persisted_grant_metadata_valid(
        credential_grant_state
    ):
        raise ValidationIssue(
            "grok_follow_redaction_context_unverified",
            "Persisted launch credential evidence cannot be verified for follow mode",
        )
    expected_uuid: str | None = None
    if expected_session_id is not None:
        try:
            expected_uuid = str(uuid.UUID(str(expected_session_id)))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValidationIssue(
                "grok_follow_requested_session_invalid",
                "Requested Grok follow identity is not an exact UUID",
            ) from exc
        if expected_uuid != str(expected_session_id):
            raise ValidationIssue(
                "grok_follow_requested_session_invalid",
                "Requested Grok follow identity is not a canonical UUID",
            )
    try:
        raw = _loads_bounded_json(line, label="Grok streaming event")
        _assert_bounded_json_structure(raw, label="Grok streaming event")
    except (TypeError, ValueError, RecursionError, StorageError, json.JSONDecodeError):
        return None
    if not isinstance(raw, Mapping):
        return None
    raw_type = str(raw.get("type") or "unknown")
    session_id = raw.get("sessionId", raw.get("session_id"))
    stop_reason = raw.get("stopReason", raw.get("stop_reason"))
    error_code = raw.get("code", raw.get("errorType", raw.get("error_type")))
    content = raw.get("data", raw.get("message", ""))
    provider_secret_detected = bool(
        force_redact_provider_fields
        or _contains_full_run_secret(
            raw,
            exact_values=tuple(exact_values),
            credential_grant_state=credential_grant_state,
        )
    )
    event_type = (
        raw_type
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", raw_type)
        else "unknown"
    )
    known = event_type in {"text", "thought", "end", "error", "usage"}
    record: dict[str, Any] = {
        "event_type": event_type if known else "unknown",
        "unknown_event_type": (
            None if known or provider_secret_detected else event_type
        ),
        "terminal": event_type in {"end", "error"},
    }
    if session_id is not None:
        try:
            streamed_uuid = str(uuid.UUID(str(session_id)))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValidationIssue(
                "grok_stream_session_identity_invalid",
                "Grok stream reported a non-UUID session identity",
            ) from exc
        if streamed_uuid != str(session_id) or (
            expected_uuid is not None and streamed_uuid != expected_uuid
        ):
            raise ValidationIssue(
                "grok_stream_session_identity_mismatch",
                "Grok stream session identity differs from the requested UUID",
            )
        # When redacting a provider record, retain only the host-bound identity.
        # A provider-supplied UUID can itself be credential-shaped data.
        if not provider_secret_detected:
            record["session_id"] = expected_uuid or streamed_uuid
    if (
        not provider_secret_detected
        and isinstance(stop_reason, str)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", stop_reason)
    ):
        record["stop_reason"] = stop_reason
    usage_source = raw.get("usage") if isinstance(raw.get("usage"), Mapping) else raw
    usage = {
        str(key): value
        for key, value in usage_source.items()
        if key in _GROK_STREAM_USAGE_KEYS
        and not isinstance(value, bool)
        and isinstance(value, (int, float))
        and value >= 0
    }
    if usage:
        record["usage"] = usage
    if (
        event_type == "error"
        and not provider_secret_detected
        and isinstance(error_code, str)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", error_code)
    ):
        record["error_type"] = error_code
    if provider_secret_detected:
        record["summary"] = "[REDACTED:credential_grant]"
    elif not shared_oauth and event_type in {"text", "error"}:
        if isinstance(content, str) and content:
            cleaned = _redact_full_run_text(content, exact_values=exact_values).strip()
            if cleaned:
                record["summary"] = cleaned[:197] + "..." if len(cleaned) > 200 else cleaned
    elif event_type == "thought":
        record["summary"] = "reasoning activity"
    return record


def _grok_stream_provider_text(line: str) -> str:
    """Return only provider-controlled strings that the follow formatter may expose."""
    if (
        not isinstance(line, str)
        or not line.strip()
        or len(line.encode("utf-8")) > MAX_GROK_STREAM_RECORD_BYTES
    ):
        return ""
    try:
        raw = _loads_bounded_json(line, label="Grok streaming event")
        _assert_bounded_json_structure(raw, label="Grok streaming event")
    except (TypeError, ValueError, RecursionError, StorageError, json.JSONDecodeError):
        return ""
    if not isinstance(raw, Mapping):
        return ""
    raw_type = str(raw.get("type") or "unknown")
    fragments: list[str] = []
    if raw_type not in {"text", "thought", "end", "error", "usage"}:
        fragments.append(raw_type)
    session_id = raw.get("sessionId", raw.get("session_id"))
    if isinstance(session_id, str):
        fragments.append(session_id)
    stop_reason = raw.get("stopReason", raw.get("stop_reason"))
    if isinstance(stop_reason, str):
        fragments.append(stop_reason)
    if raw_type == "error":
        code = raw.get("code", raw.get("errorType", raw.get("error_type")))
        if isinstance(code, str):
            fragments.append(code)
    if raw_type in {"text", "error"}:
        content = raw.get("data", raw.get("message", ""))
        if isinstance(content, str):
            fragments.append(content)
    return "".join(fragments)


@dataclass
class GrokStreamingRedactionState:
    """Quarantine enough provider text to catch credentials split across events."""

    pending: list[tuple[str, bool]] = field(default_factory=list)


def _grok_stream_credential_lengths(
    *,
    exact_values: Sequence[str],
    credential_grant_state: FullRunState | None,
) -> tuple[int, ...]:
    lengths = {
        len(value)
        for value in exact_values
        if isinstance(value, str) and value
    }
    if credential_grant_state is not None:
        if not _persisted_grant_metadata_valid(credential_grant_state):
            raise ValidationIssue(
                "grok_follow_redaction_context_unverified",
                "Persisted launch credential evidence cannot be verified for follow mode",
            )
        lengths.update(
            length
            for length in credential_grant_state.credential_grant_lengths.values()
            if isinstance(length, int) and not isinstance(length, bool) and length > 0
        )
    return tuple(sorted(lengths))


def _grok_stream_credential_record_indexes(
    fragments: Sequence[str],
    *,
    exact_values: Sequence[str],
    credential_grant_state: FullRunState | None,
) -> set[int]:
    """Locate records participating in an exact or HMAC-backed credential match."""
    text = "".join(fragments)
    if not text:
        return set()
    ranges: list[tuple[int, int]] = []
    for value in exact_values:
        if not isinstance(value, str) or not value:
            continue
        start = 0
        while (match := text.find(value, start)) >= 0:
            ranges.append((match, match + len(value)))
            start = match + 1
    if credential_grant_state is not None:
        for name in credential_grant_state.credential_granted_names:
            length = credential_grant_state.credential_grant_lengths[name]
            expected = credential_grant_state.credential_grant_digests[name]
            if length <= 0 or len(text) < length:
                continue
            for start in range(0, len(text) - length + 1):
                candidate = text[start : start + length]
                if hmac.compare_digest(
                    _credential_grant_digest(
                        credential_grant_state, name, candidate
                    ),
                    expected,
                ):
                    ranges.append((start, start + length))
    fragment_ranges: list[tuple[int, int]] = []
    offset = 0
    for fragment in fragments:
        end = offset + len(fragment)
        fragment_ranges.append((offset, end))
        offset = end
    affected: set[int] = set()
    for match_start, match_end in ranges:
        participants = {
            index
            for index, (fragment_start, fragment_end) in enumerate(fragment_ranges)
            if fragment_start < match_end and fragment_end > match_start
        }
        # Provider-controlled fields are concatenated in display order. This
        # catches both adjacent JSONL chunks and a credential divided among
        # multiple metadata fields inside one record.
        affected.update(participants)
    return affected


def format_grok_streaming_follow_line(record: Mapping[str, Any]) -> str:
    """Format a sanitized Grok stream record without exposing raw JSON."""
    event_type = str(record.get("event_type") or "unknown")
    if event_type == "unknown" and record.get("unknown_event_type"):
        event_type = f"unknown[{record['unknown_event_type']}]"
    parts = [f"grok:{event_type}"]
    if record.get("session_id"):
        parts.append(f"session={record['session_id']}")
    if record.get("stop_reason"):
        parts.append(f"stop={record['stop_reason']}")
    if record.get("error_type"):
        parts.append(f"error={record['error_type']}")
    usage = record.get("usage")
    if isinstance(usage, Mapping) and usage:
        parts.append(
            "usage=" + ",".join(f"{key}:{usage[key]}" for key in sorted(usage))
        )
    if record.get("terminal"):
        parts.append("terminal")
    summary = str(record.get("summary") or "").strip()
    return " ".join(parts) + (f" — {summary}" if summary else "")


def grok_streaming_follow_lines(
    raw_lines: Sequence[str],
    *,
    shared_oauth: bool = False,
    exact_values: Sequence[str] = (),
    already_seen: int = 0,
    expected_session_id: str | None = None,
    credential_grant_state: FullRunState | None = None,
    redaction_state: GrokStreamingRedactionState | None = None,
) -> tuple[list[str], int]:
    """Return sanitized Grok JSONL follow lines with cross-event credential quarantine.

    Incremental callers pass one persistent ``redaction_state``. The function
    withholds at most one credential-length suffix, so a token split across two
    streaming text chunks is detected before either fragment becomes visible.
    One-shot callers are flushed after scanning the complete supplied sequence.
    """
    cursor = max(0, int(already_seen))
    selected_lines = list(raw_lines)[cursor:]
    state = redaction_state or GrokStreamingRedactionState()
    combined = [*state.pending, *((line, False) for line in selected_lines)]
    lengths = _grok_stream_credential_lengths(
        exact_values=exact_values,
        credential_grant_state=credential_grant_state,
    )
    provider_fragments = [
        _grok_stream_provider_text(line) for line, _force in combined
    ]
    affected_records = _grok_stream_credential_record_indexes(
        provider_fragments,
        exact_values=exact_values,
        credential_grant_state=credential_grant_state,
    )
    combined = [
        (line, force_redact or index in affected_records)
        for index, (line, force_redact) in enumerate(combined)
    ]

    terminal_seen = False
    for line, _force in combined:
        try:
            raw = _loads_bounded_json(line, label="Grok streaming event")
        except (TypeError, ValueError, RecursionError, StorageError, json.JSONDecodeError):
            continue
        if isinstance(raw, Mapping) and raw.get("type") in {"end", "error"}:
            terminal_seen = True
            break

    # A generic monitor transition is not proof that no adjacent provider chunk
    # remains. Persistent followers release their quarantine only after an
    # actual terminal stream record; otherwise a transition between two token
    # fragments could expose both halves over successive polls.
    should_flush = bool(terminal_seen or redaction_state is None)
    keep_start = len(combined)
    if combined and lengths and not should_flush:
        quarantine_chars = max(lengths) - 1
        accumulated = 0
        for index in range(len(combined) - 1, -1, -1):
            fragment = _grok_stream_provider_text(combined[index][0])
            if not fragment:
                continue
            keep_start = index
            accumulated += len(fragment)
            if accumulated >= quarantine_chars:
                break
    released = combined if should_flush or not lengths else combined[:keep_start]
    state.pending = [] if should_flush or not lengths else combined[keep_start:]

    decoded: list[dict[str, Any]] = []
    for line, force_redact in released:
        record = decode_grok_streaming_event(
            line,
            shared_oauth=shared_oauth,
            exact_values=exact_values,
            expected_session_id=expected_session_id,
            credential_grant_state=credential_grant_state,
            force_redact_provider_fields=force_redact,
        )
        if record is not None:
            decoded.append(record)
    decoded_total = sum(
        1
        for line in selected_lines
        if decode_grok_streaming_event(
            line,
            shared_oauth=shared_oauth,
            exact_values=exact_values,
            expected_session_id=expected_session_id,
            credential_grant_state=credential_grant_state,
        )
        is not None
    )
    return [format_grok_streaming_follow_line(item) for item in decoded], cursor + decoded_total


def classify_grok_terminal_records(
    raw_lines: Sequence[str],
    *,
    expected_session_id: str,
    exact_values: Sequence[str] = (),
    credential_grant_state: FullRunState | None = None,
) -> dict[str, str] | None:
    """Classify a bounded Grok terminal stream without exposing provider text."""
    max_turns_seen = False
    terminal_failure: dict[str, str] | None = None
    for line in raw_lines:
        try:
            raw = _loads_bounded_json(line, label="Grok streaming event")
            _assert_bounded_json_structure(raw, label="Grok streaming event")
        except (TypeError, ValueError, RecursionError, StorageError, json.JSONDecodeError):
            continue
        if not isinstance(raw, Mapping):
            continue
        if raw.get("type") == "max_turns_reached":
            max_turns_seen = True
            continue
        record = decode_grok_streaming_event(
            line,
            shared_oauth=True,
            exact_values=exact_values,
            expected_session_id=expected_session_id,
            credential_grant_state=credential_grant_state,
        )
        if not record or not record.get("terminal"):
            continue
        event_type = str(record.get("event_type") or "")
        if event_type == "error":
            terminal_failure = {"code": "grok_provider_error"}
            if record.get("error_type"):
                terminal_failure["error_type"] = str(record["error_type"])
            continue
        stop_reason = str(record.get("stop_reason") or "")
        normalized = stop_reason.casefold().replace("_", "")
        if normalized in {"cancelled", "canceled"}:
            terminal_failure = {
                "code": (
                    "grok_max_turns_reached"
                    if max_turns_seen
                    else "grok_provider_cancelled"
                ),
                "stop_reason": stop_reason,
            }
        elif normalized == "refusal":
            terminal_failure = {
                "code": "grok_provider_refusal",
                "stop_reason": stop_reason,
            }
        else:
            terminal_failure = None
    return terminal_failure


def _grok_terminal_failure(
    repo_root: Path,
    state: FullRunState,
    *,
    exact_values: Sequence[str],
) -> dict[str, str] | None:
    """Read only the bounded structural tail needed for terminal classification."""
    if state.adapter != "grok-build":
        return None
    transcript = full_run_root(repo_root, state.session_id) / "transcript.log"
    return classify_grok_terminal_records(
        _bounded_text_tail(transcript, lines=64, repo_root=repo_root),
        expected_session_id=state.session_id,
        exact_values=exact_values,
        credential_grant_state=state,
    )


@dataclass
class GrokTranscriptCursor:
    """Byte-accurate cursor for an append-only or atomically rotated JSONL transcript."""

    dev: int | None = None
    ino: int | None = None
    offset: int = 0
    partial: bytes = b""


def _read_grok_transcript_records(
    repo_root: Path,
    path: Path,
    cursor: GrokTranscriptCursor,
) -> tuple[list[str], GrokTranscriptCursor]:
    """Read every newly appended complete JSONL record without rolling-tail loss."""
    candidate = guard_repo_path(repo_root, path)
    try:
        before = candidate.lstat()
    except FileNotFoundError:
        return [], cursor
    except OSError as exc:
        raise ValidationIssue(
            "grok_follow_transcript_unavailable",
            f"Grok transcript metadata is unavailable ({type(exc).__name__})",
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        raise ValidationIssue(
            "grok_follow_transcript_unsafe",
            "Grok transcript is not a regular file",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(candidate, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ValidationIssue(
                "grok_follow_transcript_identity_changed",
                "Grok transcript changed identity while opening",
            )
        same_identity = (cursor.dev, cursor.ino) == (opened.st_dev, opened.st_ino)
        offset = cursor.offset if same_identity and opened.st_size >= cursor.offset else 0
        partial = cursor.partial if same_identity and offset else b""
        os.lseek(descriptor, offset, os.SEEK_SET)
        records: list[str] = []
        while True:
            chunk = os.read(descriptor, GROK_STREAM_READ_CHUNK_BYTES)
            if not chunk:
                break
            offset += len(chunk)
            buffered = partial + chunk
            pieces = buffered.split(b"\n")
            partial = pieces.pop()
            for raw in pieces:
                if not raw.strip():
                    continue
                if len(raw) > MAX_GROK_STREAM_RECORD_BYTES:
                    raise ValidationIssue(
                        "grok_follow_record_too_large",
                        "Grok streaming JSONL record exceeds the safe byte limit",
                    )
                try:
                    records.append(raw.decode("utf-8", errors="strict"))
                except UnicodeDecodeError as exc:
                    raise ValidationIssue(
                        "grok_follow_record_invalid_utf8",
                        "Grok streaming JSONL record is not valid UTF-8",
                    ) from exc
            if len(partial) > MAX_GROK_STREAM_RECORD_BYTES:
                raise ValidationIssue(
                    "grok_follow_record_too_large",
                    "Partial Grok streaming JSONL record exceeds the safe byte limit",
                )
        after = candidate.lstat()
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValidationIssue(
                "grok_follow_transcript_identity_changed",
                "Grok transcript rotated while it was being read",
            )
        return records, GrokTranscriptCursor(
            dev=int(opened.st_dev),
            ino=int(opened.st_ino),
            offset=offset,
            partial=partial,
        )
    except ValidationIssue:
        raise
    except OSError as exc:
        raise ValidationIssue(
            "grok_follow_transcript_unavailable",
            f"Grok transcript cannot be read safely ({type(exc).__name__})",
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def follow_stream_lines(
    events: Sequence[Mapping[str, Any]],
    *,
    shared_oauth: bool = False,
    already_seen: int = 0,
) -> tuple[list[str], int]:
    """Return new follow lines since ``already_seen`` and the new cursor."""
    visible = _driver_visible_events(events, shared_oauth=shared_oauth)
    cursor = max(0, int(already_seen))
    new_events = visible[cursor:]
    lines = [
        format_follow_stream_line(ev, shared_oauth=shared_oauth) for ev in new_events
    ]
    return lines, len(visible)


def _all_follow_events(repo_root: Path, state: "FullRunState") -> list[dict[str, Any]]:
    """Read the validated event sequence for an absolute follow cursor.

    ``full-run-logs`` intentionally exposes only a bounded diagnostic tail.
    Follow mode must not use that rolling window as an index: once more than
    the tail size arrives between polls, a relative cursor silently skips
    events. The validated log is already capped at ``MAX_EVENT_LINES``, so an
    absolute cursor over the complete sequence remains bounded and lossless.
    """
    launch_grants_verified, exact_secret_values = _launch_evidence_context(state)
    if not launch_grants_verified:
        return []
    events, errors = _read_events(
        full_run_root(repo_root, state.session_id) / "events.jsonl",
        expected_session_id=state.session_id,
        expected_branch=state.branch,
        expected_high_risk_checkpoints=state.planned_high_risk_checkpoints,
        exact_secret_values=exact_secret_values,
        credential_grant_state=state,
        shared_oauth_safe_projection=(state.grok_auth_strategy == "oauth_shared_file"),
        allow_partial_final=bool(state.pid or state.pgid),
        repo_root=repo_root,
    )
    if errors:
        return []
    return _driver_visible_events(
        events,
        shared_oauth=state.grok_auth_strategy == "oauth_shared_file",
    )


# Follow mode is a deterministic stream, never a model-based watcher.
FOLLOW_MODE_MODEL_INFERENCE = False
FOLLOW_MODE_REPLACES_TIMED_CHAT = True


def _driver_visible_blocker(state: FullRunState) -> str | None:
    """Return a categorical OAuth blocker without echoing worker free text."""
    if not state.blocker or state.grok_auth_strategy != "oauth_shared_file":
        return state.blocker
    categories = {
        "driver_wake_blocker": "shared OAuth worker reported a blocked state",
        "driver_wake_safety_tripwire": "shared OAuth run triggered a safety tripwire",
        "driver_wake_stale_heartbeat": "shared OAuth worker heartbeat became stale",
        "driver_wake_provider_cancelled": "Grok provider cancelled before completion",
        "driver_wake_provider_limit": "Grok provider reached its configured turn limit",
        "driver_wake_error": "shared OAuth run requires driver error review",
        "stopped": "shared OAuth run was stopped",
    }
    return categories.get(
        str(state.next_action or ""),
        "shared OAuth run requires driver review",
    )


def _bounded_text_tail(
    path: Path,
    *,
    lines: int,
    repo_root: Path | None = None,
) -> list[str]:
    """Read a bounded suffix without loading a worker transcript wholesale."""
    if lines <= 0:
        return []
    if repo_root is not None:
        try:
            tail = read_repo_text_tail(
                repo_root,
                path,
                max_bytes=MAX_TRANSCRIPT_TAIL_BYTES,
                max_lines=lines,
            )
        except StorageError as exc:
            if exc.code == "not_found":
                return []
            raise
        return [line[-MAX_TRANSCRIPT_LINE_CHARS:] for line in tail]
    if not path.exists() and not path.is_symlink():
        return []
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise StorageError(
                "transcript_not_regular",
                "transcript must be a regular non-symlink file",
            )
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            raise StorageError(
                "transcript_identity_changed",
                "transcript changed identity while opening",
            )
        size = opened.st_size
        start = max(0, size - MAX_TRANSCRIPT_TAIL_BYTES)
        with os.fdopen(fd, "rb", closefd=False) as handle:
            handle.seek(start)
            raw = handle.read(MAX_TRANSCRIPT_TAIL_BYTES)
    except StorageError:
        raise
    except OSError as exc:
        raise StorageError(
            "transcript_unavailable",
            f"transcript cannot be read safely: {type(exc).__name__}",
        ) from exc
    finally:
        if "fd" in locals():
            try:
                os.close(fd)
            except OSError:
                pass
    chunks = raw.splitlines()
    # A nonzero seek can begin in the middle of a line. Discard that fragment;
    # callers receive fewer lines rather than an unbounded backward scan.
    if start and chunks:
        chunks = chunks[1:]
    tail = chunks[-lines:]
    return [
        chunk[-MAX_TRANSCRIPT_LINE_CHARS:].decode("utf-8", errors="replace")
        for chunk in tail
    ]


def _git_commit_chain(cwd: Path, start_head: str, final_head: str) -> list[str]:
    result = run_git(
        cwd,
        ["rev-list", "--reverse", f"{start_head}..{final_head}"],
        check=False,
    )
    if result.returncode != 0:
        raise ValidationIssue(
            "full_run_commit_chain_unavailable",
            (result.stderr or result.stdout or "git rev-list failed").strip(),
        )
    return [row.strip() for row in result.stdout.splitlines() if row.strip()]


def _report_commit_shas(report: Mapping[str, Any]) -> list[str]:
    shas: list[str] = []
    for item in report.get("commits") or []:
        shas.append(str(item.get("sha")) if isinstance(item, Mapping) else str(item))
    return shas


def _validate_git_bound_evidence(
    state: FullRunState,
    report: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    observed_head: str | None,
) -> list[str]:
    if state.adapter == "fixture":
        return []
    errors: list[str] = []
    worktree = Path(state.worktree)
    previous = state.start_head
    if observed_head:
        for index, event in enumerate(events):
            head = str(event.get("head") or "")
            if not (
                _is_ancestor(worktree, state.start_head, head)
                and _is_ancestor(worktree, head, observed_head)
            ):
                errors.append(f"event[{index}] head is outside observed feature ancestry")
                continue
            if not _is_ancestor(worktree, previous, head):
                errors.append(f"event[{index}] head regresses from prior observed event")
            previous = head
    if report.get("status") == "complete":
        final_head = str(report.get("final_head") or "")
        try:
            expected_chain = _git_commit_chain(worktree, state.start_head, final_head)
        except ValidationIssue as issue:
            errors.append(issue.message)
        else:
            if _report_commit_shas(report) != expected_chain:
                errors.append("report commits do not exactly equal start_head..final_head chain")
        if not state.acceptance_criteria:
            errors.append("staged acceptance criterion binding is missing")
        else:
            observed_criteria = {
                str(item.get("id") or ""): item.get("criterion")
                for item in report.get("acceptance") or []
                if isinstance(item, Mapping)
            }
            if set(observed_criteria) != set(state.acceptance_criteria):
                errors.append("report acceptance ids do not exactly match staged criteria")
            elif any(
                observed_criteria[acceptance_id]
                != state.acceptance_criteria[acceptance_id]
                for acceptance_id in state.acceptance_criteria
            ):
                errors.append(
                    "report acceptance criterion text does not exactly match staged criteria"
                )
        try:
            _assert_clean_worktree(worktree)
        except ValidationIssue as issue:
            errors.append(issue.message)
    return errors


@_locked_full_run
def stop_full_run(
    repo_root: Path,
    *,
    session_id: str,
    grace_seconds: float = 1.0,
) -> dict[str, Any]:
    """Terminate only the exact fingerprinted supervisor identity."""
    state = load_state(repo_root, session_id)
    root = full_run_root(repo_root, session_id)
    if (
        state.closed_process_identity
        and state.pid is None
        and state.pgid is None
        and state.fingerprint is None
    ):
        if state.interruption_evidence is None and state.status != "complete":
            _record_interruption(
                state,
                closed_identity=state.closed_process_identity,
                reason="host acknowledged authenticated closed attempt",
            )
            save_state(repo_root, state)
        return {
            "ok": True,
            "action": "full_run_stop",
            "session_id": session_id,
            "signaled": False,
            "still_alive": False,
            "status": state.status,
            "reason": "process identity already retired",
            "fingerprint_verified": True,
        }
    pid = int(state.pid or 0)
    pgid = state.pgid
    completed_record: dict[str, Any] | None = None
    exit_record_errors: list[str] = []
    try:
        candidate_record = read_exit_record(root, repo_root=Path(repo_root))
    except StorageError as exc:
        candidate_record = None
        exit_record_errors.append(exc.message)
    if candidate_record is not None:
        exit_record_errors.extend(_validate_exit_record(candidate_record, state))
        if not exit_record_errors:
            completed_record = candidate_record

    # A sidecar is completion evidence only after its exact supervisor PID and
    # marker-bound descendants are dead. Never probe a reusable numeric PGID.
    if completed_record is not None:
        _reap_supervisor_if_child(state.pid)
        pid_alive = bool(pid and _pid_alive(pid))
        supervised_pids = _supervised_alive(state)
        if not pid_alive and not supervised_pids:
            state.exit_code = int(completed_record["exit_code"])
            if state.status not in {"complete", "failed", "blocked", "stopped"}:
                state.status = "stopped"
                state.next_action = "stopped"
                state.completed_at = state.completed_at or _utc_now()
            closed = _retire_process_identity(
                state,
                reason="host_stop_after_validated_exit",
                evidence=completed_record,
            )
            _record_interruption(
                state, closed_identity=closed, reason="host acknowledged prior exit"
            )
            save_state(repo_root, state)
            return {
                "ok": True,
                "action": "full_run_stop",
                "session_id": session_id,
                "signaled": False,
                "still_alive": False,
                "status": state.status,
                "reason": "supervisor domain already exited with a validated record",
                "fingerprint_verified": True,
            }

    pid_alive = bool(pid and _pid_alive(pid))
    supervised_pids = _supervised_alive(state)
    if not pid_alive and not supervised_pids:
        if (
            state.fingerprint
            and completed_record is None
            and state.status not in {"stopped", "complete", "failed", "blocked"}
        ):
            raise ValidationIssue(
                "full_run_fingerprint_mismatch",
                "Recorded supervisor disappeared without a validated exit record",
            )
        if state.status not in {"complete", "failed", "blocked"}:
            state.status = "stopped"
            state.next_action = "stopped"
            state.completed_at = state.completed_at or _utc_now()
            save_state(repo_root, state)
        return {
            "ok": True,
            "action": "full_run_stop",
            "session_id": session_id,
            "signaled": False,
            "still_alive": False,
            "status": state.status,
            "reason": "no live supervisor identity or marker-bound descendants",
            "fingerprint_verified": bool(completed_record),
            "exit_record_errors": exit_record_errors,
        }

    fingerprint_verified = False
    if pid_alive and state.fingerprint:
        ok, reason = verify_fingerprint(
            state.fingerprint, expected_session_id=session_id
        )
        if not ok:
            raise ValidationIssue(
                "full_run_fingerprint_mismatch",
                f"Refusing stop: {reason}",
                path=str(root / "worker.fingerprint.json"),
                hint="PID may have been reused; investigate before signaling",
            )
        fingerprint_verified = True
    elif pid_alive:
        raise ValidationIssue(
            "full_run_fingerprint_missing",
            "Refusing stop: live supervisor PID has no exact fingerprint",
        )
    elif supervised_pids:
        # Never signal cached descendant PIDs or a reusable numeric PGID from the
        # host. Recursive cleanup is owned by the still-fingerprinted supervisor;
        # once it is gone, surviving descendants are a wake-worthy failure that
        # requires operator inspection rather than risking an unrelated process.
        raise ValidationIssue(
            "full_run_supervisor_missing_with_descendants",
            "Refusing direct descendant signaling after the supervisor identity disappeared",
        )

    signaled = False
    if pid_alive and state.fingerprint:
        _write_supervisor_stop_request(Path(repo_root), root, state)
        # Compatibility field: true now means the capability-authenticated supervisor stop
        # channel was engaged, not that a reusable numeric PID/PGID was signaled.
        signaled = True

    # The embedded supervisor may need to terminate a provider plus recursively
    # discovered descendants before it publishes the exit record. Give that
    # identity-bound cleanup a small floor even when callers request zero grace.
    deadline = time.monotonic() + min(max(grace_seconds, 2.5), 5.0)
    while time.monotonic() < deadline:
        if (
            not bool(pid and _pid_alive(pid))
            and not _supervised_alive(state)
        ):
            break
        time.sleep(0.05)

    pid_alive = bool(pid and _pid_alive(pid))
    supervised_pids = _supervised_alive(state)
    still_alive = pid_alive or bool(supervised_pids)
    if still_alive:
        # A Linux pidfd can safely nudge a supervisor that did not consume its
        # request. Platforms without a kernel-bound process handle fail closed;
        # never fall back to a reusable numeric PID or PGID, and never SIGKILL
        # the supervisor out from under still-live descendants.
        if pid_alive and state.fingerprint and sys.platform.startswith("linux"):
            _signal_verified_supervisor(
                state.fingerprint,
                expected_session_id=session_id,
                signum=signal.SIGTERM,
            )
        retry_deadline = time.monotonic() + 1.0
        while time.monotonic() < retry_deadline:
            if (
                not bool(pid and _pid_alive(pid))
                and not _supervised_alive(state)
            ):
                break
            time.sleep(0.05)
        still_alive = (
            bool(pid and _pid_alive(pid))
            or bool(_supervised_alive(state))
        )

    state.status = "failed" if still_alive else "stopped"
    state.next_action = "driver_wake_error" if still_alive else "stopped"
    if still_alive:
        state.blocker = (
            "supervised process domain remains alive after capability-authenticated stop request"
        )
    state.completed_at = _utc_now()
    if not still_alive:
        evidence = completed_record or {
            "authority": "host_stop",
            "stop_request_delivered": signaled,
            "observed_pid_dead": True,
            "observed_descendants_absent": True,
        }
        closed = _retire_process_identity(
            state,
            reason="host_authenticated_interruption",
            evidence=evidence,
        )
        _record_interruption(
            state, closed_identity=closed, reason="host stop observed full domain exit"
        )
    save_state(repo_root, state)
    _append_event(
        root / "events.jsonl",
        {
            "timestamp": state.completed_at,
            "session_id": session_id,
            "branch": state.branch,
            "head": state.head or state.start_head,
            "batch": state.batch or 0,
            "type": "heartbeat",
            "summary": "Capability-authenticated supervisor stop requested through private runtime channel",
        },
        expected_session_id=session_id,
        expected_branch=state.branch,
        expected_high_risk_checkpoints=state.planned_high_risk_checkpoints,
        repo_root=Path(repo_root),
    )
    return {
        "ok": not still_alive,
        "action": "full_run_stop",
        "session_id": session_id,
        "signaled": signaled,
        "still_alive": still_alive,
        "status": state.status,
        "fingerprint_verified": fingerprint_verified,
        "exit_record_errors": exit_record_errors,
    }


def logs_full_run(
    repo_root: Path,
    *,
    session_id: str,
    raw_tail: bool = False,
    tail_lines: int = 40,
) -> dict[str, Any]:
    bounded_tail = min(100, max(0, int(tail_lines)))
    root = full_run_root(repo_root, session_id)
    state = load_state(repo_root, session_id)
    launch_grants_verified, exact_secret_values = _launch_evidence_context(state)
    if launch_grants_verified:
        events, errors = _read_events(
            root / "events.jsonl",
            expected_session_id=session_id,
            expected_branch=state.branch,
            expected_high_risk_checkpoints=state.planned_high_risk_checkpoints,
            exact_secret_values=exact_secret_values,
            credential_grant_state=state,
            shared_oauth_safe_projection=(
                state.grok_auth_strategy == "oauth_shared_file"
            ),
            allow_partial_final=bool(state.pid or state.pgid),
            repo_root=Path(repo_root),
        )
    else:
        events, errors = [], [
            "launch credential context cannot be verified for worker logs"
        ]
    visible_events = _driver_visible_events(
        events[-bounded_tail:] if bounded_tail else [],
        shared_oauth=state.grok_auth_strategy == "oauth_shared_file",
    )
    payload: dict[str, Any] = {
        "ok": not errors,
        "session_id": session_id,
        "events_tail": visible_events,
        "event_errors": errors[-20:],
        "transcript_included": False,
        "merge_authority": False,
    }
    if raw_tail and state.grok_auth_strategy == "oauth_shared_file":
        payload["transcript_error"] = (
            "raw transcript unavailable for shared OAuth runs"
        )
    elif raw_tail and not launch_grants_verified:
        payload["transcript_error"] = (
            "raw transcript unavailable: launch credential context cannot be verified"
        )
    elif raw_tail:
        transcript = root / "transcript.log"
        try:
            transcript_exists = repo_regular_file_exists(Path(repo_root), transcript)
        except StorageError as exc:
            payload["transcript_error"] = exc.message
            transcript_exists = False
        if transcript_exists:
            try:
                raw_lines = _bounded_text_tail(
                    transcript,
                    lines=bounded_tail,
                    repo_root=Path(repo_root),
                )
            except StorageError as exc:
                payload["transcript_error"] = exc.message
                raw_lines = []
            raw_window = "\n".join(raw_lines)
            if _PEM_BOUNDARY_RE.search(raw_window):
                payload["transcript_tail"] = ["[REDACTED:pem_block]"]
            elif _text_contains_persisted_credential_grant(raw_window, state):
                payload["transcript_tail"] = ["[REDACTED:credential_grant]"]
            else:
                redacted_window = _redact_full_run_text(
                    raw_window, exact_values=exact_secret_values
                )
                payload["transcript_tail"] = [
                    line[-MAX_TRANSCRIPT_LINE_CHARS:]
                    for line in redacted_window.splitlines()
                ]
            payload["transcript_included"] = True
    _redact_full_run_mapping_in_place(payload, exact_values=exact_secret_values)
    return payload


def write_report(repo_root: Path, session_id: str, report: Mapping[str, Any]) -> Path:
    state = load_state(repo_root, session_id)
    _revalidate_staged_packet_binding(Path(repo_root), state)
    launch_grants_verified, exact_secret_values = _launch_evidence_context(state)
    if not launch_grants_verified:
        raise ValidationIssue(
            "full_run_credential_context_unverified",
            "Cannot accept worker report without the exact launch credential context",
        )
    errors = validate_run_report(
        report,
        expected_session_id=session_id,
        expected_branch=state.branch,
        expected_start_head=state.start_head,
        require_complete_acceptance=report.get("status") == "complete",
        expected_run_id=_expected_run_id(session_id),
        expected_attempt=state.attempt,
        expected_acceptance_criteria=(
            state.acceptance_criteria if state.adapter != "fixture" else None
        ),
        exact_secret_values=exact_secret_values,
        credential_grant_state=state,
    )
    if errors:
        raise ValidationIssue("full_run_report_invalid", "; ".join(errors))
    # Reports never grant merge authority.
    payload = dict(report)
    payload["merge_authority"] = False
    path = full_run_root(repo_root, session_id) / "report.json"
    atomic_write_json(path, payload, repo_root=Path(repo_root))
    # Native confidence sidecars are triage-only; failures here must not block
    # accepting an otherwise valid report.
    try:
        from .confidence_sidecar import (  # noqa: PLC0415
            write_sidecars_from_commit_messages,
            write_sidecars_from_report,
        )

        write_sidecars_from_report(Path(repo_root), payload)
        commits = payload.get("commits")
        if isinstance(commits, list):
            write_sidecars_from_commit_messages(Path(repo_root), commits)
    except Exception:
        pass
    return path

@_locked_full_run
def reconstruct_missing_report(
    repo_root: Path,
    *,
    session_id: str,
    host_tests_pass: bool,
    available_facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Host reconstruction after clean exit without a valid worker report.

    Only independently provable fields are filled. Provenance is always
    ``host_reconstructed``. Untrusted writer handoffs are refused.
    """
    # Lazy on purpose: risk_policy imports full_run at module level (real cycle).
    from .risk_policy import (  # noqa: PLC0415
        build_reconstructed_report,
        plan_host_reconstruction,
    )

    state = load_state(repo_root, session_id)
    worktree = Path(state.worktree)
    try:
        protected_errors = verify_protected_refs_unchanged(
            Path(repo_root),
            state.protected_refs or {},
            feature_branch=state.branch,
            include_remote=True,
        )
    except ValidationIssue as issue:
        protected_errors = [issue.message]
    origin_ok = True
    try:
        if (
            _canonical_origin_url(Path(repo_root)) != state.origin_url
            or _origin_config_digest(Path(repo_root)) != state.origin_config_digest
        ):
            origin_ok = False
    except ValidationIssue:
        origin_ok = False
    try:
        _assert_clean_worktree(worktree)
        clean_worktree = True
    except ValidationIssue:
        clean_worktree = False
    tip = _git_head(worktree) or ""
    ancestry_ok = bool(
        tip and state.start_head and _is_ancestor(worktree, state.start_head, tip)
    )
    commits = _git_commit_chain(worktree, state.start_head, tip) if ancestry_ok else []
    if ancestry_ok and not commits:
        return {
            "ok": False,
            "session_id": session_id,
            "next_action": "driver_wake_error",
            "refused_reasons": ["no_feature_branch_progress"],
            "provenance": "host_reconstructed",
        }
    commit_rows: list[dict[str, str]] = []
    for sha in commits:
        subject_result = run_git(
            worktree,
            ["show", "-s", "--format=%s", sha],
            check=False,
        )
        if subject_result.returncode != 0:
            return {
                "ok": False,
                "session_id": session_id,
                "next_action": "driver_wake_error",
                "refused_reasons": ["commit_subject_unavailable"],
                "provenance": "host_reconstructed",
            }
        commit_rows.append(
            {"sha": sha, "subject": (subject_result.stdout or "").strip()}
        )
    acceptance_rows = [
        {
            "id": aid,
            "criterion": crit,
            "met": True,
            "evidence": "host verified from exact staged contract, Git progress, and tests",
        }
        for aid, crit in (state.acceptance_criteria or {}).items()
    ]
    batch_ids = sorted(
        {
            aid.split("-A", 1)[0]
            for aid in state.acceptance_criteria
            if "-A" in aid and not aid.startswith("M-")
        }
    ) or ["full-run"]
    default_facts: dict[str, Any] = {
        "run_id": _expected_run_id(session_id),
        "session_id": session_id,
        "branch": state.branch,
        "start_head": state.start_head,
        "final_head": tip,
        "status": "complete",
        "commits": commit_rows,
        "acceptance": acceptance_rows,
        "batches": [
            {
                "id": batch_id,
                "status": "complete",
                "evidence": "host reconstructed from exact Git ancestry and acceptance proof",
            }
            for batch_id in batch_ids
        ],
        "blockers": [],
        "remaining_risks": [],
        "docs_changed": [],
        "tests": {"host_reconstructed": True},
        "security_notes": [
            "provenance host_reconstructed; worker-only claims unknown"
        ],
    }
    facts = dict(default_facts)
    facts.update(dict(available_facts or {}))
    # Identity and Git evidence are host-derived, never caller-overridable.
    facts.update(
        {
            "run_id": _expected_run_id(session_id),
            "session_id": session_id,
            "branch": state.branch,
            "start_head": state.start_head,
            "final_head": tip,
            "status": "complete",
            "commits": commit_rows,
        }
    )
    plan = plan_host_reconstruction(
        clean_exit=state.exit_code == 0,
        ancestry_ok=ancestry_ok,
        clean_worktree=clean_worktree,
        protected_refs_ok=not protected_errors,
        origin_ok=origin_ok,
        acceptance_bound=bool(state.acceptance_criteria),
        checkpoints_satisfied=not state.planned_high_risk_checkpoints
        or set(state.planned_high_risk_checkpoints).issubset(
            set(state.acknowledged_high_risk_checkpoints)
        ),
        host_tests_pass=host_tests_pass,
        untrusted_writer=False,
        missing_security_evidence=bool(protected_errors),
        available_facts=facts,
    )
    if not plan.allowed:
        return {
            "ok": False,
            "session_id": session_id,
            "next_action": "driver_wake_error",
            "refused_reasons": list(plan.refused_reasons),
            "provenance": "host_reconstructed",
        }
    report = build_reconstructed_report(plan, facts=facts)
    # Ensure required complete-report keys.
    report.setdefault("run_id", _expected_run_id(session_id))
    report.setdefault("session_id", session_id)
    report.setdefault("branch", state.branch)
    report.setdefault("start_head", state.start_head)
    report.setdefault("final_head", tip)
    report.setdefault("status", "complete")
    report.setdefault("attempt", state.attempt)
    report.setdefault("batches", default_facts["batches"])
    report.setdefault("commits", commit_rows)
    report.setdefault("blockers", [])
    report.setdefault("docs_changed", [])
    report.setdefault("tests", {"host_reconstructed": True})
    report.setdefault(
        "security_notes",
        ["provenance host_reconstructed; worker-only claims unknown"],
    )
    if "acceptance" not in report:
        report["acceptance"] = [
            {
                "id": aid,
                "criterion": crit,
                "met": True,
                "evidence": "host_reconstructed_from_git_and_session",
            }
            for aid, crit in (state.acceptance_criteria or {}).items()
        ]
    report["provenance"] = "host_reconstructed"
    report["merge_authority"] = False
    write_report(repo_root, session_id, report)
    launch_grants_verified, exact_secret_values = _launch_evidence_context(state)
    review_events: list[dict[str, Any]] = []
    if launch_grants_verified:
        candidate_events, confidence_event_errors = _read_events(
            full_run_root(repo_root, session_id) / "events.jsonl",
            expected_session_id=session_id,
            expected_branch=state.branch,
            expected_high_risk_checkpoints=state.planned_high_risk_checkpoints,
            exact_secret_values=exact_secret_values,
            credential_grant_state=state,
            shared_oauth_safe_projection=(
                state.grok_auth_strategy == "oauth_shared_file"
            ),
            # Strict per-line validation still runs (allow_partial_final=False
            # records the torn-final-line error), but reconstruction runs after
            # a crash where a torn final line is the expected state: the valid
            # earlier events are salvaged below instead of being discarded
            # wholesale, and the recorded errors mark the evidence as partial.
            # The live monitor and reconcile paths keep their strict handling.
            allow_partial_final=False,
            repo_root=Path(repo_root),
        )
        # Optional triage metadata cannot turn an otherwise permitted host
        # reconstruction into a completion failure. Per-line salvage keeps the
        # valid events; any invalid lines are reported honestly as partial
        # evidence instead of claiming no signal was reported.
        review_events = candidate_events
        review_events_partial = bool(confidence_event_errors)
    else:
        review_events_partial = False
    review_context = build_worker_confidence_review_context(
        session_id=session_id,
        branch=state.branch,
        final_head=tip,
        report=report,
        events=review_events,
        shared_oauth=state.grok_auth_strategy == "oauth_shared_file",
        event_evidence_partial=review_events_partial,
    )
    if launch_grants_verified:
        _redact_full_run_mapping_in_place(
            review_context, exact_values=exact_secret_values
        )
    state.report_provenance = "host_reconstructed"
    state.status = "complete"
    state.next_action = "final_readiness"
    state.head = tip
    state.completed_at = state.completed_at or _utc_now()
    state.blocker = None
    try:
        from .confidence_sidecar import (  # noqa: PLC0415
            latest_confidence_from_sidecars,
            record_terminal_calibration,
            write_sidecars_from_commit_messages,
        )

        write_sidecars_from_commit_messages(Path(repo_root), commit_rows)
        record_terminal_calibration(
            Path(repo_root),
            run_id=_expected_run_id(session_id),
            adapter=str(state.adapter or ""),
            model=str(state.model or ""),
            effort=str(state.effort or ""),
            status="complete",
            confidence=latest_confidence_from_sidecars(Path(repo_root)),
        )
    except Exception:
        pass
    save_state(repo_root, state)
    return {
        "ok": True,
        "session_id": session_id,
        "next_action": "final_readiness",
        "provenance": "host_reconstructed",
        "report": report,
        "review_context": review_context,
        "unknown_fields": list(plan.unknown_fields),
    }


def reconcile_full_run_with_git(
    repo_root: Path,
    *,
    session_id: str,
) -> dict[str, Any]:
    """Verify feature-branch advance and report heads at the supervisor boundary."""

    state = load_state(repo_root, session_id)
    _revalidate_staged_packet_binding(Path(repo_root), state)
    launch_grants_verified, exact_secret_values = _launch_evidence_context(state)
    if not launch_grants_verified:
        raise ValidationIssue(
            "full_run_credential_context_unverified",
            "Cannot reconcile worker evidence without the exact launch credential context",
        )
    worktree = Path(state.worktree)
    if state.launch_start_head != state.start_head:
        raise ValidationIssue(
            "full_run_start_head_mutated",
            "Immutable launch start no longer matches staged start_head",
        )
    assert_feature_branch(worktree, state.branch)
    tip = assert_descendant(worktree, ancestor=state.start_head)
    _assert_clean_worktree(worktree)
    contract = DelegatedGitContract(
        feature_branch=state.branch,
        base_branch="main",
        start_head=state.start_head,
        session_id=session_id,
        run_id=_expected_run_id(session_id),
    )
    # Protected actions remain forbidden at policy boundary.
    for action in ("merge", "tag", "force_push", "change_base"):
        try:
            assert_action_allowed(contract, action)
            raise ValidationIssue(
                "delegated_git_policy_broken",
                f"Protected action `{action}` was unexpectedly allowed",
            )
        except ValidationIssue as issue:
            if issue.code not in {"delegated_git_protected", "delegated_git_forbidden"}:
                raise

    report_path = full_run_root(repo_root, session_id) / "report.json"
    report: dict[str, Any] = {}
    try:
        report_exists = repo_regular_file_exists(Path(repo_root), report_path)
    except StorageError as exc:
        raise ValidationIssue("full_run_report_invalid", exc.message) from exc
    if report_exists:
        try:
            report = _read_bounded_json_object(
                report_path,
                label="run report",
                repo_root=Path(repo_root),
            )
        except StorageError as exc:
            raise ValidationIssue("full_run_report_invalid", exc.message) from exc
        errs = validate_run_report(
            report,
            expected_session_id=session_id,
            expected_branch=state.branch,
            expected_start_head=state.start_head,
            require_complete_acceptance=report.get("status") == "complete",
            expected_run_id=_expected_run_id(session_id),
            expected_attempt=state.attempt,
            expected_acceptance_criteria=(
                state.acceptance_criteria if state.adapter != "fixture" else None
            ),
            exact_secret_values=exact_secret_values,
            credential_grant_state=state,
        )
        redacted_report = _redact_full_run_structure(
            _redact_persisted_credential_grants(report, state),
            exact_values=exact_secret_values,
        )
        if redacted_report != report:
            atomic_write_json(
                report_path,
                redacted_report,
                repo_root=Path(repo_root),
            )
        if errs:
            raise ValidationIssue("full_run_report_invalid", "; ".join(errs))
    if not report or report.get("status") != "complete":
        raise ValidationIssue(
            "full_run_report_incomplete",
            "Final Git reconciliation requires a validated complete report",
        )
    if str(report.get("final_head") or "") != tip:
        raise ValidationIssue(
            "full_run_report_head_mismatch",
            "Complete report final_head does not equal the local feature tip",
        )
    events, event_errors = _read_events(
        full_run_root(repo_root, session_id) / "events.jsonl",
        expected_session_id=session_id,
        expected_branch=state.branch,
        expected_high_risk_checkpoints=state.planned_high_risk_checkpoints,
        exact_secret_values=exact_secret_values,
        credential_grant_state=state,
        shared_oauth_safe_projection=(
            state.grok_auth_strategy == "oauth_shared_file"
        ),
        allow_partial_final=False,
        repo_root=Path(repo_root),
    )
    observed_high_risk_checkpoints = {
        str(event.get("checkpoint_id"))
        for event in events
        if event.get("type") == "high_risk_checkpoint"
    }
    missing_high_risk_checkpoints = set(state.planned_high_risk_checkpoints) - (
        observed_high_risk_checkpoints
    )
    unacknowledged_high_risk_checkpoints = set(
        state.planned_high_risk_checkpoints
    ) - set(state.acknowledged_high_risk_checkpoints)
    if (
        missing_high_risk_checkpoints
        or unacknowledged_high_risk_checkpoints
        or state.pending_high_risk_checkpoint is not None
    ):
        raise ValidationIssue(
            "full_run_checkpoint_incomplete",
            "Final Git reconciliation requires every planned high-risk checkpoint "
            "to be emitted and explicitly acknowledged",
        )
    evidence_errors = event_errors + _validate_git_bound_evidence(
        state, report, events, tip
    )
    if evidence_errors:
        raise ValidationIssue(
            "full_run_git_evidence_mismatch", "; ".join(evidence_errors[:6])
        )
    review_context = build_worker_confidence_review_context(
        session_id=session_id,
        branch=state.branch,
        final_head=tip,
        report=report,
        events=events,
        shared_oauth=state.grok_auth_strategy == "oauth_shared_file",
    )

    host_state = {
        "merge_on_green": False,
        "stop_allowed": False,
        "run_mode": "finite",
        "pr_number": None,
        "driver_monitor_mode": "parked_monitor",
    }
    if report:
        merged = reconcile_worker_report(
            host_state,
            report,
            expected_session_id=session_id,
            expected_branch=state.branch,
            expected_start_head=state.start_head,
        )
    else:
        merged = dict(host_state)
        merged["final_head"] = tip
    # Host controls preserved
    if merged.get("merge_on_green") is not False:
        raise ValidationIssue(
            "report_reconciliation_failed",
            "Host merge_on_green control was not preserved",
        )
    # Protected refs must be unchanged (policy trust — not OS Git sandbox).
    protected_errors = verify_protected_refs_unchanged(
        Path(repo_root),
        state.protected_refs or {},
        feature_branch=state.branch,
    )
    if protected_errors:
        raise ValidationIssue(
            "protected_ref_moved",
            "; ".join(protected_errors),
        )
    # Local + remote feature head / ancestry when remotes are present.
    local_head = tip
    remote_head = _assert_origin_binding(
        Path(repo_root), state, expected_feature_tip=local_head
    )
    if not remote_head or not _is_ancestor(worktree, state.start_head, remote_head):
        raise ValidationIssue(
            "full_run_remote_feature_ancestry",
            "Origin feature tip must be an exact descendant of immutable start_head",
        )
    return {
        "ok": True,
        "session_id": session_id,
        "branch": state.branch,
        "start_head": state.start_head,
        "final_head": tip,
        "local_feature_head": local_head,
        "remote_feature_head": remote_head,
        "protected_refs_ok": True,
        "merged_host_state": {
            k: merged.get(k)
            for k in ("merge_on_green", "stop_allowed", "driver_monitor_mode", "final_head")
        },
        "review_context": review_context,
        "merge_authority": False,
        "policy_trust_not_os_git_sandbox": True,
    }


def __getattr__(name: str):
    """Lazy re-export for extracted monitor/await entrypoints (#92)."""
    if name in {"monitor_full_run", "await_full_run"}:
        from . import full_run_monitor as _lifecycle

        return getattr(_lifecycle, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | {"monitor_full_run", "await_full_run"})
