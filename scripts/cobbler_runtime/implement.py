"""Lane A (fast) implementer operator helpers.

Host-owned commands for prepare / launch argv / gate / resume-batch / status.
Prints argv by default. Legacy --exec requests fail closed before spawn unless a
qualified recursive process boundary exists; none is currently available on the
supported Linux or macOS direct paths. Network is never required for prepare/status.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import re
import secrets
import selectors
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .acceptance import normalize_batch_id
from .adapters import reject_fugu_implementation_route
from .context import collect_secret_env_values, redact_text
from .executables import resolve_executable_for_launch
from .isolation import _managed_implement_env
from .schema import AMBIGUOUS_SESSION_TOKENS, ValidationIssue
from .storage import (
    StorageError,
    atomic_write_json,
    ensure_private_dir as ensure_storage_dir,
    list_repo_store_files,
    read_json,
)

DEFAULT_MODEL = "auto"
DEFAULT_PERMISSION_MODE = "auto"
DEFAULT_LANE = "fast"
DEFAULT_GIT_MODE = "branch_progress"
DEFAULT_EXECUTABLE = "grok"
# Generic/non-Grok adapters retain their existing balanced default. Grok Build
# delegation explicitly uses its highest supported effort by default.
DEFAULT_EFFORT = "medium"
GROK_DEFAULT_EFFORT = "high"
FORBIDDEN_DEFAULT_PERMISSION = "dontAsk"
# Required for unattended headless tool use. Grok Build 0.2.101 gives an explicit
# --permission-mode precedence over yolo, so trusted launches emit --always-approve alone.

GROK_LIVE_DEFAULT = DEFAULT_MODEL


def require_exact_grok_session_uuid(session_id: str) -> str:
    """Require the canonical UUID grammar accepted by installed Grok Build."""
    value = str(session_id or "").strip()
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationIssue(
            "invalid_grok_session_uuid",
            "Grok session identity must be an exact canonical UUID",
        ) from exc
    canonical = str(parsed)
    if value != canonical:
        raise ValidationIssue(
            "invalid_grok_session_uuid",
            "Grok session identity must use canonical lowercase UUID grammar",
        )
    return canonical


def _require_nonnegative_batch(batch: Any) -> int:
    normalized = normalize_batch_id(batch)
    if normalized is None:
        raise ValidationIssue(
            "implement_batch_invalid",
            "Batch must be B0, B1+, or an unambiguous non-negative integer",
        )
    return normalized

RUNTIME_REL = Path(".elves") / "runtime" / "implement"
STATE_NAME = "state.json"
GATES_DIRNAME = "gates"
DONE_DIRNAME = "done"
PACKETS_REL = Path(".elves") / "runtime" / "packets"
MAX_DONE_REPORT_BYTES = 256 * 1024
MAX_STATE_BYTES = 256 * 1024

# ``implement --exec`` is a compatibility convenience, so keep its driver-facing
# output small even when a provider is extremely chatty. The larger private
# rolling window lets redaction run before the legacy 4,000-character tail is
# selected; bytes before that window are digested and discarded as they arrive.
_EXEC_TIMEOUT_SECONDS = 60 * 60
_EXEC_TERM_GRACE_SECONDS = 5.0
_EXEC_KILL_GRACE_SECONDS = 5.0
_EXEC_SELECTOR_POLL_SECONDS = 0.05
_EXEC_READ_CHUNK_BYTES = 64 * 1024
_EXEC_CAPTURE_WINDOW_BYTES = 512 * 1024
_EXEC_OUTPUT_TAIL_CHARS = 4000
_EXEC_OUTPUT_SUMMARY_CHARS = 500
_EXEC_SUPERVISION_ENV = "ELVES_IMPLEMENT_SUPERVISION_MARKER"
# Marker inheritance makes a final scan sufficient for ordinary setsid/double-
# fork escapes. A sparse background scan additionally learns descendants that
# later sanitize their environment without imposing ps(1) churn on hour-long runs.
_EXEC_DESCENDANT_SCAN_SECONDS = 5.0
_EXEC_DESCENDANT_VERIFY_SECONDS = 0.05

_GATE_SECRET_FIELD_RE = re.compile(
    r"(?i)(?:api[_-]?key|[A-Za-z0-9_-]*token|jwt|bearer|authorization|auth|"
    r"password|passwd|secret|credentials?|cookie|private[_-]?key)"
    r"(?:_value|_header)?$"
)

_RAN_RE = re.compile(r"^Ran\s+(\d+)\s+tests?\b", re.MULTILINE)
_FAIL_RE = re.compile(
    r"FAILED\s*\((?:[^)]*failures=(\d+))?[^)]*(?:errors=(\d+))?[^)]*\)"
)
_SKIP_RE = re.compile(r"(?:skipped=(\d+)|OK\s*\([^)]*skipped=(\d+))", re.IGNORECASE)


class _RollingCapture:
    """Digest an arbitrary byte stream while retaining only a bounded suffix."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(0, int(max_bytes))
        self.total_bytes = 0
        self.digest = hashlib.sha256()
        self.tail = bytearray()

    def add(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.total_bytes += len(chunk)
        self.digest.update(chunk)
        if self.max_bytes <= 0:
            return
        self.tail.extend(chunk)
        overflow = len(self.tail) - self.max_bytes
        if overflow > 0:
            del self.tail[:overflow]

    def text(self) -> str:
        return bytes(self.tail).decode("utf-8", errors="replace")

    def digest_prefix(self) -> str:
        return self.digest.hexdigest()[:16]


@dataclass(frozen=True)
class _BoundedProcessResult:
    exit_code: int
    timed_out: bool
    stdout_window: str
    stderr_window: str
    stdout_digest: str
    stderr_digest: str
    stdout_bytes: int
    stderr_bytes: int


@dataclass(frozen=True)
class _ImplementProcessRecord:
    pid: int
    ppid: int
    pgid: int
    start_identity: str
    darwin_audit_token: tuple[int, ...] | None = None
    marker_present: bool = False
    zombie: bool = False


class _DarwinBsdInfo(ctypes.Structure):
    """Native ``proc_bsdinfo`` prefix through microsecond start identity."""

    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


class _DarwinUniqueIdentifierInfo(ctypes.Structure):
    """libproc process unique ID plus the current exec-generation PID version."""

    _fields_ = [
        ("p_uuid", ctypes.c_ubyte * 16),
        ("p_uniqueid", ctypes.c_uint64),
        ("p_puniqueid", ctypes.c_uint64),
        ("p_idversion", ctypes.c_int32),
        ("p_orig_ppidversion", ctypes.c_int32),
        ("p_reserve2", ctypes.c_uint64),
        ("p_reserve3", ctypes.c_uint64),
    ]


class _DarwinBsdInfoWithUniqueId(ctypes.Structure):
    _fields_ = [
        ("pbsd", _DarwinBsdInfo),
        ("p_uniqidentifier", _DarwinUniqueIdentifierInfo),
    ]


class _DarwinAuditToken(ctypes.Structure):
    _fields_ = [("val", ctypes.c_uint32 * 8)]


@lru_cache(maxsize=1)
def _darwin_proc_pidinfo() -> Any:
    try:
        library = ctypes.CDLL(None, use_errno=True)
        function = library.proc_pidinfo
    except (AttributeError, OSError) as exc:
        raise ValidationIssue(
            "implement_supervision_unavailable",
            f"Darwin proc_pidinfo is unavailable: {type(exc).__name__}",
        ) from exc
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    function.restype = ctypes.c_int
    return function


@lru_cache(maxsize=1)
def _darwin_proc_signal_with_audittoken() -> Any:
    try:
        library = ctypes.CDLL(None, use_errno=True)
        function = library.proc_signal_with_audittoken
    except (AttributeError, OSError) as exc:
        raise ValidationIssue(
            "implement_supervision_unavailable",
            "Darwin generation-bound signaling is unavailable: "
            f"{type(exc).__name__}",
        ) from exc
    function.argtypes = (ctypes.POINTER(_DarwinAuditToken), ctypes.c_int)
    function.restype = ctypes.c_int
    return function


def _darwin_audit_token(pid: int, pid_version: int) -> tuple[int, ...]:
    values = [0] * 8
    values[5] = int(pid) & 0xFFFFFFFF
    values[7] = int(pid_version) & 0xFFFFFFFF
    return tuple(values)


def _darwin_signal_audit_token(
    audit_token: tuple[int, ...] | None,
    signum: int,
) -> bool:
    """Atomically signal one Darwin PID generation, never a reused PID."""
    if audit_token is None or len(audit_token) != 8:
        raise ValidationIssue(
            "implement_supervision_identity_failed",
            "Darwin process identity is missing its audit token",
        )
    token = _DarwinAuditToken()
    for index, value in enumerate(audit_token):
        token.val[index] = int(value) & 0xFFFFFFFF
    result = int(
        _darwin_proc_signal_with_audittoken()(ctypes.byref(token), int(signum))
    )
    if result == 0:
        return True
    if result == errno.ESRCH:
        return False
    raise ValidationIssue(
        "implement_descendant_signal_failed",
        "Cannot signal Darwin process generation: "
        f"{os.strerror(result) if result > 0 else f'error {result}'}",
    )


def _linux_process_record(
    pid: int,
    *,
    marker: str | None = None,
) -> _ImplementProcessRecord | None:
    stat_path = Path(f"/proc/{int(pid)}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return None
    except OSError as exc:
        raise ValidationIssue(
            "implement_supervision_identity_failed",
            f"Cannot inspect Linux pid {pid}: {type(exc).__name__}: {exc}",
        ) from exc
    close_paren = raw.rfind(")")
    fields = raw[close_paren + 2 :].split() if close_paren >= 0 else []
    if len(fields) < 20:
        raise ValidationIssue(
            "implement_supervision_identity_failed",
            f"Linux returned an incomplete process identity for pid {pid}",
        )
    try:
        state = fields[0]
        ppid = int(fields[1])
        pgid = int(fields[2])
        start_ticks = fields[19]
    except (IndexError, ValueError) as exc:
        raise ValidationIssue(
            "implement_supervision_identity_failed",
            f"Linux returned a malformed process identity for pid {pid}",
        ) from exc
    marker_present = False
    if marker:
        expected = f"{_EXEC_SUPERVISION_ENV}={marker}".encode("utf-8")
        try:
            environment = Path(f"/proc/{int(pid)}/environ").read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            environment = b""
        except PermissionError as exc:
            try:
                owner_uid = stat_path.stat().st_uid
            except (FileNotFoundError, ProcessLookupError):
                environment = b""
            except OSError as stat_exc:
                raise ValidationIssue(
                    "implement_supervision_scan_failed",
                    "Cannot identify an environment-inaccessible Linux pid "
                    f"{pid}: {type(stat_exc).__name__}: {stat_exc}",
                ) from stat_exc
            else:
                if owner_uid == os.geteuid():
                    # A same-UID worker descendant can become non-dumpable. If
                    # its environment is unreadable, marker-based recursive
                    # absence cannot be proved and cleanup must fail closed.
                    raise ValidationIssue(
                        "implement_supervision_scan_failed",
                        f"Cannot inspect same-UID Linux environment for pid {pid}",
                    ) from exc
                environment = b""
        except OSError as exc:
            raise ValidationIssue(
                "implement_supervision_scan_failed",
                f"Cannot inspect Linux environment for pid {pid}: {type(exc).__name__}",
            ) from exc
        marker_present = expected in environment.split(b"\0")
    return _ImplementProcessRecord(
        pid=int(pid),
        ppid=ppid,
        pgid=pgid,
        start_identity=start_ticks,
        marker_present=marker_present,
        zombie=state in {"Z", "X", "x"},
    )


def _darwin_process_record(
    pid: int,
    *,
    marker_present: bool = False,
) -> _ImplementProcessRecord | None:
    function = _darwin_proc_pidinfo()
    info = _DarwinBsdInfoWithUniqueId()
    ctypes.set_errno(0)
    size = function(
        int(pid),
        18,  # PROC_PIDT_BSDINFOWITHUNIQID
        0,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if size <= 0:
        error_number = ctypes.get_errno()
        if error_number not in {0, errno.ESRCH}:
            raise ValidationIssue(
                "implement_supervision_identity_failed",
                f"Darwin cannot inspect pid {pid}: {os.strerror(error_number)}",
            )
        return None
    if size < ctypes.sizeof(info) or int(info.pbsd.pbi_pid) != int(pid):
        raise ValidationIssue(
            "implement_supervision_identity_failed",
            f"Darwin returned an incomplete process identity for pid {pid}",
        )
    unique_id = int(info.p_uniqidentifier.p_uniqueid)
    pid_version = int(info.p_uniqidentifier.p_idversion)
    return _ImplementProcessRecord(
        pid=int(info.pbsd.pbi_pid),
        ppid=int(info.pbsd.pbi_ppid),
        pgid=int(info.pbsd.pbi_pgid),
        start_identity=(
            f"{int(info.pbsd.pbi_start_tvsec)}:"
            f"{int(info.pbsd.pbi_start_tvusec)}:{unique_id}"
        ),
        darwin_audit_token=_darwin_audit_token(pid, pid_version),
        marker_present=marker_present,
        zombie=int(info.pbsd.pbi_status) == 5,  # SZOMB
    )


def _native_process_record(pid: int) -> _ImplementProcessRecord | None:
    if sys.platform.startswith("linux"):
        return _linux_process_record(pid)
    if sys.platform == "darwin":
        return _darwin_process_record(pid)
    raise ValidationIssue(
        "implement_supervision_unavailable",
        f"Implementer process cleanup is unsupported on {sys.platform}",
    )


def _require_implement_supervision_capability() -> None:
    """Require a qualified recursive boundary for the bounded worker lane."""
    if sys.platform.startswith("linux"):
        raise ValidationIssue(
            "implement_recursive_containment_unavailable",
            "The legacy bounded implementer has no qualified PID namespace or "
            "cgroup boundary on Linux; use the separate trusted full-run route",
        )

    if sys.platform == "darwin":
        raise ValidationIssue(
            "implement_recursive_containment_unavailable",
            "Darwin has no qualified recursive bounded-implementer process "
            "boundary; use the separate trusted full-run launch path or a "
            "qualified isolated platform",
        )

    raise ValidationIssue(
        "implement_supervision_unavailable",
        f"Implementer process cleanup is unsupported on {sys.platform}",
    )


def _darwin_marker_matches_identity(
    pid: int,
    *,
    expected_start_identity: str,
    marker: str,
) -> bool:
    """Bind ps(1)'s environment view to one native Darwin process generation."""
    before = _darwin_process_record(pid)
    if before is None or before.start_identity != expected_start_identity:
        return False
    try:
        proc = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationIssue(
            "implement_supervision_scan_failed",
            f"Cannot verify Darwin marker for pid {pid}: {type(exc).__name__}: {exc}",
        ) from exc
    after = _darwin_process_record(pid)
    if (
        after is None
        or after.start_identity != expected_start_identity
        or before.start_identity != after.start_identity
    ):
        return False
    if proc.returncode != 0:
        raise ValidationIssue(
            "implement_supervision_scan_failed",
            f"Darwin marker verification exited {proc.returncode} for pid {pid}",
        )
    token_marker = f"{_EXEC_SUPERVISION_ENV}={marker}"
    return token_marker in proc.stdout


def _scan_implement_processes(
    marker: str,
    *,
    known_pids: set[int] | None = None,
) -> dict[int, _ImplementProcessRecord]:
    records: dict[int, _ImplementProcessRecord] = {}
    known = known_pids or set()
    if sys.platform.startswith("linux"):
        proc_root = Path("/proc")
        try:
            entries = tuple(proc_root.iterdir())
        except OSError as exc:
            raise ValidationIssue(
                "implement_supervision_scan_failed",
                f"Cannot enumerate Linux processes: {type(exc).__name__}: {exc}",
            ) from exc
        for entry in entries:
            if not entry.name.isdigit():
                continue
            record = _linux_process_record(int(entry.name), marker=marker)
            if record is not None:
                records[record.pid] = record
        return records

    if sys.platform == "darwin":
        try:
            proc = subprocess.run(
                ["/bin/ps", "-axo", "pid=,ppid=,pgid=,command="],
                capture_output=True,
                text=True,
                check=False,
                timeout=2.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValidationIssue(
                "implement_supervision_scan_failed",
                f"Cannot enumerate Darwin processes: {type(exc).__name__}: {exc}",
            ) from exc
        if proc.returncode != 0:
            raise ValidationIssue(
                "implement_supervision_scan_failed",
                f"Darwin ps exited {proc.returncode}",
            )
        token_marker = f"{_EXEC_SUPERVISION_ENV}={marker}"
        for raw_line in proc.stdout.splitlines():
            fields = raw_line.strip().split(None, 3)
            if len(fields) < 3:
                continue
            try:
                pid = int(fields[0])
            except ValueError:
                continue
            command = fields[3] if len(fields) == 4 else ""
            marker_candidate = token_marker in command
            try:
                record = _darwin_process_record(
                    pid,
                    marker_present=False,
                )
            except ValidationIssue:
                if marker_candidate or pid in known:
                    raise
                continue
            if record is not None and marker_candidate:
                marker_present = _darwin_marker_matches_identity(
                    pid,
                    expected_start_identity=record.start_identity,
                    marker=marker,
                )
                record = _ImplementProcessRecord(
                    pid=record.pid,
                    ppid=record.ppid,
                    pgid=record.pgid,
                    start_identity=record.start_identity,
                    darwin_audit_token=record.darwin_audit_token,
                    marker_present=marker_present,
                    zombie=record.zombie,
                )
            if record is not None:
                records[record.pid] = record
        return records

    raise ValidationIssue(
        "implement_supervision_unavailable",
        f"Implementer process cleanup is unsupported on {sys.platform}",
    )


@dataclass
class _ImplementDescendantSupervisor:
    marker: str
    root_pid: int
    known_pids: dict[int, _ImplementProcessRecord] = field(default_factory=dict)

    def attach(self) -> None:
        root = _native_process_record(self.root_pid)
        if root is not None:
            self.known_pids[root.pid] = root
        self.scan()
        if not self.known_pids:
            raise ValidationIssue(
                "implement_supervision_identity_failed",
                "Cannot bind the implementer launch to a stable process identity",
            )

    def scan(self) -> dict[int, _ImplementProcessRecord]:
        records = _scan_implement_processes(
            self.marker,
            known_pids=set(self.known_pids),
        )
        live_known = {
            pid
            for pid, identity in self.known_pids.items()
            if (record := records.get(pid)) is not None
            and record.start_identity == identity.start_identity
        }
        # PID version rotates on exec, but unique ID does not. Refresh the
        # record for every stable known generation so its audit token is always
        # the current one even if the worker removed its marker during exec.
        for pid in live_known:
            self.known_pids[pid] = records[pid]
        discovered = {
            pid for pid, record in records.items() if record.marker_present
        }
        changed = True
        while changed:
            before = len(discovered)
            discovered.update(
                record.pid
                for record in records.values()
                if record.ppid in discovered or record.ppid in live_known
            )
            changed = len(discovered) != before
        for pid in discovered:
            self.known_pids[pid] = records[pid]
        return records

    def alive(self) -> dict[int, _ImplementProcessRecord]:
        records = self.scan()
        return {
            pid: identity
            for pid, identity in self.known_pids.items()
            if pid != os.getpid()
            and (record := records.get(pid)) is not None
            and record.start_identity == identity.start_identity
            and not record.zombie
        }

    def root_exited(self) -> bool:
        """Observe leader exit without reaping, so its PID/PGID stay pinned."""
        expected = self.known_pids.get(self.root_pid)
        if expected is None:
            raise ValidationIssue(
                "implement_supervision_identity_failed",
                "Implementer root has no stable process identity",
            )
        current = _native_process_record(self.root_pid)
        if current is None:
            # Darwin's libproc may stop returning a zombie even though this
            # Popen has deliberately not called wait()/poll(). The unreaped
            # child still pins its PID/PGID, so absence here means exit.
            return True
        if current.start_identity != expected.start_identity:
            raise ValidationIssue(
                "implement_supervision_identity_failed",
                "Implementer root identity disappeared before it was reaped",
            )
        return current.zombie

    def signal_identity(
        self,
        pid: int,
        identity: _ImplementProcessRecord,
        signum: int,
    ) -> bool:
        if sys.platform.startswith("linux"):
            if not (
                hasattr(os, "pidfd_open")
                and hasattr(signal, "pidfd_send_signal")
            ):
                raise ValidationIssue(
                    "implement_pidfd_unavailable",
                    "Linux recursive cleanup requires kernel-bound pidfd signaling",
                )
            try:
                pidfd = os.pidfd_open(pid, 0)
            except ProcessLookupError:
                return False
            except OSError as exc:
                raise ValidationIssue(
                    "implement_pidfd_unavailable",
                    f"Cannot bind Linux pid {pid}: {type(exc).__name__}: {exc}",
                ) from exc
            try:
                current = _native_process_record(pid)
                if (
                    current is None
                    or current.zombie
                    or current.start_identity != identity.start_identity
                ):
                    return False
                try:
                    signal.pidfd_send_signal(pidfd, signum)
                    return True
                except ProcessLookupError:
                    return False
                except OSError as exc:
                    raise ValidationIssue(
                        "implement_descendant_signal_failed",
                        f"Cannot signal Linux pid {pid}: {type(exc).__name__}: {exc}",
                    ) from exc
            finally:
                os.close(pidfd)

        if sys.platform == "darwin":
            current = _native_process_record(pid)
            if (
                current is None
                or current.zombie
                or current.start_identity != identity.start_identity
            ):
                # Never redirect a signal after PID reuse or identity mismatch.
                return False
            # The kernel resolves the audit token's PID version and takes a proc
            # reference before signaling. A reuse after the check above therefore
            # returns ESRCH instead of redirecting the signal to the replacement.
            return _darwin_signal_audit_token(current.darwin_audit_token, signum)

        raise ValidationIssue(
            "implement_supervision_unavailable",
            f"Implementer process cleanup is unsupported on {sys.platform}",
        )

    def terminate_known_descendants(
        self,
        *,
        term_grace_seconds: float,
        kill_grace_seconds: float,
    ) -> None:
        alive = self.alive()
        for pid, identity in sorted(alive.items(), reverse=True):
            self.signal_identity(pid, identity, signal.SIGTERM)

        term_deadline = time.monotonic() + max(0.0, term_grace_seconds)
        while alive and time.monotonic() < term_deadline:
            time.sleep(_EXEC_DESCENDANT_VERIFY_SECONDS)
            alive = self.alive()

        for pid, identity in sorted(alive.items(), reverse=True):
            self.signal_identity(pid, identity, signal.SIGKILL)

        kill_deadline = time.monotonic() + max(0.05, kill_grace_seconds)
        while True:
            alive = self.alive()
            if not alive:
                return
            if time.monotonic() >= kill_deadline:
                raise ValidationIssue(
                    "implement_descendant_cleanup_failed",
                    "Implementer cleanup could not prove known descendant absence: "
                    + ", ".join(str(pid) for pid in sorted(alive)),
                )
            for pid, identity in sorted(alive.items(), reverse=True):
                self.signal_identity(pid, identity, signal.SIGKILL)
            time.sleep(_EXEC_DESCENDANT_VERIFY_SECONDS)


@dataclass
class ImplementState:
    """Persisted implementer metadata under .elves/runtime/implement/."""

    lane: str = DEFAULT_LANE
    git_mode: str = DEFAULT_GIT_MODE
    adapter: str = "grok-build"
    model: str = DEFAULT_MODEL
    permission_mode: str = DEFAULT_PERMISSION_MODE
    worktree: str = ""
    branch: str | None = None
    session_id: str | None = None
    executable: str = DEFAULT_EXECUTABLE
    subagents: bool = True
    created_at: str = ""
    updated_at: str = ""
    last_batch: int | None = None
    last_packet: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImplementState:
        known = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def implement_root(repo_root: Path) -> Path:
    return Path(repo_root).resolve() / RUNTIME_REL


def state_path(repo_root: Path) -> Path:
    return implement_root(repo_root) / STATE_NAME


def gates_dir(repo_root: Path) -> Path:
    return implement_root(repo_root) / GATES_DIRNAME


def done_dir(repo_root: Path) -> Path:
    return implement_root(repo_root) / DONE_DIRNAME


def _runtime_directory_paths(repo_root: Path) -> tuple[Path, ...]:
    base = Path(repo_root).resolve()
    return (
        base / ".elves",
        base / ".elves" / "runtime",
        implement_root(base),
        gates_dir(base),
        done_dir(base),
    )


def _storage_issue(
    exc: StorageError,
    *,
    path: Path,
    operation: str,
) -> ValidationIssue:
    if exc.code in {"symlink_component", "symlink_leaf", "unsafe_store_leaf"}:
        code = "implement_runtime_symlink"
        message = "Implement runtime components must not be symbolic links"
    elif exc.code == "unsafe_link_count":
        code = "implement_runtime_hardlink"
        message = "Implement runtime files must have exactly one hard link"
    elif exc.code in {
        "non_directory_component",
        "unsafe_file_type",
        "unsafe_path_component",
    }:
        code = "implement_runtime_component_invalid"
        message = "Implement runtime component has an unexpected file type"
    else:
        code = "implement_runtime_storage_error"
        message = f"Unable to {operation} implement runtime storage ({exc.code})"
    return ValidationIssue(code, message, path=str(path))


def _write_private_json(
    repo_root: Path,
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    """Atomically replace one JSON leaf through the repo-root descriptor boundary."""
    try:
        atomic_write_json(path, payload, repo_root=Path(repo_root))
    except StorageError as exc:
        raise _storage_issue(exc, path=path, operation="write") from exc


def ensure_implement_dirs(repo_root: Path) -> Path:
    """Create implement runtime tree with mode 0700. No network."""
    root = implement_root(repo_root)
    # Ensure parent .elves/runtime chain exists and is private when we create it.
    for part in _runtime_directory_paths(repo_root):
        try:
            ensure_storage_dir(part, repo_root=Path(repo_root), mode=0o700)
        except StorageError as exc:
            raise _storage_issue(exc, path=part, operation="create") from exc
    return root


def load_state(repo_root: Path) -> ImplementState | None:
    path = state_path(repo_root)
    try:
        data = read_json(
            path,
            repo_root=Path(repo_root),
            max_bytes=MAX_STATE_BYTES,
        )
    except StorageError as exc:
        if exc.code == "not_found":
            return None
        if exc.code == "record_too_large":
            raise ValidationIssue(
                "implement_state_invalid",
                f"Implement state exceeds {MAX_STATE_BYTES} bytes",
                path=str(path),
            ) from exc
        if exc.code == "invalid_utf8":
            raise ValidationIssue(
                "implement_state_invalid",
                "Implement state is not valid UTF-8",
                path=str(path),
            ) from exc
        if exc.code == "malformed_json":
            message = (
                f"Implement state is not a JSON object: {path}"
                if "JSON object required" in exc.message
                else f"Implement state is not valid JSON: {path}"
            )
            raise ValidationIssue(
                "implement_state_invalid",
                message,
                path=str(path),
            ) from exc
        raise _storage_issue(exc, path=path, operation="read") from exc
    try:
        return ImplementState.from_dict(data)
    except (TypeError, ValueError, KeyError) as exc:
        raise ValidationIssue(
            "implement_state_invalid",
            f"Implement state has invalid fields: {path} ({exc})",
            path=str(path),
        ) from exc


def save_state(repo_root: Path, state: ImplementState) -> Path:
    ensure_implement_dirs(repo_root)
    path = state_path(repo_root)
    state.updated_at = _utc_now()
    _write_private_json(repo_root, path, state.to_dict())
    return path


def prepare_implement(
    repo_root: Path,
    *,
    worktree: str | Path | None = None,
    model: str = GROK_LIVE_DEFAULT,
    session_id: str | None = None,
    branch: str | None = None,
    lane: str = DEFAULT_LANE,
    git_mode: str = DEFAULT_GIT_MODE,
    permission_mode: str = DEFAULT_PERMISSION_MODE,
    executable: str = DEFAULT_EXECUTABLE,
    adapter: str = "grok-build",
) -> dict[str, Any]:
    """Record implementer metadata. Creates dirs mode 0700. No network."""
    wt = str(Path(worktree).expanduser().resolve()) if worktree else str(Path(repo_root).resolve())
    mode = (permission_mode or DEFAULT_PERMISSION_MODE).strip()
    if not mode:
        mode = DEFAULT_PERMISSION_MODE
    adapter_name = (adapter or "grok-build").strip().lower() or "grok-build"
    if adapter_name in {"opencode", "opencode-labor"}:
        adapter_name = "opencode-cli"
    reject_fugu_implementation_route(
        adapter_name,
        executable,
        requested_model=model,
    )
    is_opencode = adapter_name == "opencode-cli"
    is_devin = adapter_name == "devin-cli"
    is_omp = adapter_name == "omp-cli"
    if mode == FORBIDDEN_DEFAULT_PERMISSION and not is_opencode:
        # Explicit dontAsk is allowed only if the operator forces it; prepare still
        # warns by refusing to treat it as the lane default — block as product rule.
        raise ValidationIssue(
            "implement_dontask_forbidden",
            "permission_mode=dontAsk is forbidden for Lane A prepare (use auto or acceptEdits)",
            hint="Default is auto; never default headless to dontAsk",
        )

    existing = load_state(repo_root)
    now = _utc_now()
    default_model = (
        "openrouter/qwen/qwen3-max" if is_opencode else
        "swe-1-7-lightning" if is_devin else
        "google/gemini-2.5-flash" if is_omp else
        GROK_LIVE_DEFAULT
    )
    default_exe = (
        "opencode" if is_opencode else
        "devin" if is_devin else
        "omp" if is_omp else
        DEFAULT_EXECUTABLE
    )
    raw_model = (model or "").strip() or default_model
    resolved_model, _resolved_effort, alias_notes = resolve_implement_model(
        raw_model, adapter=adapter_name
    )
    model_value = resolved_model
    exe_value = (executable or "").strip() or default_exe
    default_note = {
        "opencode-cli": "OpenCode implement labor (Claude Code–like agent; OpenRouter/other models)",
        "devin-cli": "Devin CLI implement labor (SWE-1.7 Lightning; exact --resume only)",
        "omp-cli": "Oh My Pi (omp) implement labor; exact --resume only; run-scoped --profile",
    }.get(adapter_name, "Lane A fast implementer (default for optional Grok Build)")
    session_note = {
        "opencode-cli": "OpenCode: exact --session preferred; never bare --continue; use --auto carefully",
        "devin-cli": "Devin: host captures provider session id; never bare --continue/-c; never --cwd",
        "omp-cli": "OMP: host captures session from NDJSON; never --continue/-c; never omp --prewalk",
    }.get(adapter_name, "Never pass --no-subagents; never default permission to dontAsk")
    state = ImplementState(
        lane=(lane or DEFAULT_LANE).strip() or DEFAULT_LANE,
        git_mode=(git_mode or DEFAULT_GIT_MODE).strip() or DEFAULT_GIT_MODE,
        adapter=adapter_name,
        model=model_value,
        permission_mode=mode,
        worktree=wt,
        branch=branch,
        session_id=(session_id.strip() if session_id else None)
        or (existing.session_id if existing else None),
        executable=exe_value,
        subagents=True,
        created_at=existing.created_at if existing and existing.created_at else now,
        updated_at=now,
        last_batch=existing.last_batch if existing else None,
        last_packet=existing.last_packet if existing else None,
        notes=[
            default_note,
            "Host/human launches; CLI prints argv unless --exec",
            session_note,
            *alias_notes,
        ],
    )
    path = save_state(repo_root, state)
    return {
        "ok": True,
        "action": "prepare",
        "repo_root": str(Path(repo_root).resolve()),
        "runtime_dir": str(implement_root(repo_root)),
        "state_path": str(path),
        "state": state.to_dict(),
        "mutated_repo": False,
        "model_calls_made": False,
        "network_required": False,
    }


def _normalize_permission(mode: str | None) -> str:
    value = (mode or DEFAULT_PERMISSION_MODE).strip() or DEFAULT_PERMISSION_MODE
    if value == FORBIDDEN_DEFAULT_PERMISSION:
        raise ValidationIssue(
            "implement_dontask_forbidden",
            "permission_mode=dontAsk is forbidden for Lane A launch defaults",
            hint="Use auto or acceptEdits; never default to dontAsk",
        )
    return value


def _normalize_devin_permission(mode: str | None) -> str:
    """Map Elves permission-mode vocabulary to Devin CLI modes.

    Devin CLI modes are ``auto``, ``accept-edits``, ``smart``, and ``dangerous``.
    Elves ``auto`` means unattended worker, so it normalizes to ``dangerous``
    (auto-approve all tools) for headless implement. ``acceptEdits`` maps to
    ``accept-edits``; ``bypass`` and ``dangerous`` map to ``dangerous``.
    ``normal`` is accepted as ``auto`` (read-only tools only) but will not
    complete unattended edits.
    """
    value = (mode or DEFAULT_PERMISSION_MODE).strip() or DEFAULT_PERMISSION_MODE
    if value == FORBIDDEN_DEFAULT_PERMISSION:
        raise ValidationIssue(
            "implement_dontask_forbidden",
            "permission_mode=dontAsk is forbidden for Devin CLI",
            hint="Use auto, acceptEdits, smart, or dangerous",
        )
    mapping = {
        "auto": "dangerous",
        "dangerous": "dangerous",
        "bypass": "dangerous",
        "acceptedits": "accept-edits",
        "accept-edits": "accept-edits",
        "smart": "smart",
        "normal": "auto",
    }
    normalized = mapping.get(value.lower())
    if normalized is None:
        raise ValidationIssue(
            "implement_devin_permission_unsupported",
            f"Devin CLI does not support permission-mode `{value}`",
            hint="Use auto, acceptEdits, smart, or dangerous",
        )
    return normalized


def resolve_implement_model(
    model: str | None,
    *,
    effort: str | None = None,
    adapter: str = "grok-build",
) -> tuple[str, str | None, list[str]]:
    """Resolve operator model input to (model_id, effort_or_None, notes).

    Grok values remain exact live-catalog identifiers (or ``auto`` for the
    parsed live default); no hardcoded alias may invent an unavailable model.
    OpenCode ids pass through unchanged. Devin defaults to
    ``swe-1-7-lightning``.
    """
    notes: list[str] = []
    adapter_name = (adapter or "grok-build").strip().lower() or "grok-build"
    explicit_effort = (effort or "").strip() or None
    raw = (model or "").strip()
    if not raw:
        if adapter_name == "devin-cli":
            return "swe-1-7-lightning", explicit_effort or DEFAULT_EFFORT, notes
        if adapter_name == "omp-cli":
            return "google/gemini-2.5-flash", explicit_effort or "high", notes
        if adapter_name in {"opencode-cli", "opencode-labor", "opencode"}:
            return "openrouter/qwen/qwen3-max", explicit_effort, notes
        return GROK_LIVE_DEFAULT, explicit_effort or GROK_DEFAULT_EFFORT, notes

    if adapter_name == "devin-cli":
        return raw, explicit_effort or DEFAULT_EFFORT, notes

    if adapter_name == "omp-cli":
        return raw, explicit_effort or "high", notes

    if adapter_name in {"opencode-cli", "opencode-labor", "opencode"}:
        return raw, explicit_effort, notes

    return raw, explicit_effort or GROK_DEFAULT_EFFORT, notes



def _map_omp_thinking(effort: str | None) -> str:
    """Map Elves effort vocabulary onto omp --thinking levels."""
    value = (effort or "high").strip().lower() or "high"
    allowed = {
        "off",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "auto",
    }
    if value in allowed:
        return value
    # common elves effort aliases
    aliases = {
        "extra-high": "xhigh",
        "extra_high": "xhigh",
        "ultrathink": "max",
        "ultra": "max",
    }
    return aliases.get(value, "high")


def _build_omp_launch_argv(
    *,
    session_id: str,
    packet_path: Path,
    cwd_path: Path,
    model: str | None,
    executable: str,
    create: bool,
    effort: str | None,
    yolo: bool,
    profile: str | None = None,
) -> list[str]:
    """Build Oh My Pi (omp) implement argv for trusted full-run.

    Create captures session id from NDJSON (no --session-id). Resume uses exact
    ``--resume <uuid>`` only. Never ``--continue`` / ``-c`` / omp ``--prewalk``.
    """
    exe_hint = (executable or "omp").strip() or "omp"
    exe = resolve_executable_for_launch(exe_hint) or exe_hint
    model_name, effort_name, _notes = resolve_implement_model(
        model, effort=effort, adapter="omp-cli"
    )
    thinking = _map_omp_thinking(effort_name)
    run_profile = (profile or "").strip() or "elves-omp-full-run"
    approval = "yolo" if yolo else "write"

    argv: list[str] = [
        exe,
        "--mode",
        "json",
        "--cwd",
        str(cwd_path),
        "--profile",
        run_profile,
        "--model",
        model_name,
        "--thinking",
        thinking,
        "--approval-mode",
        approval,
    ]
    if not create:
        if not session_id:
            raise ValidationIssue(
                "missing_session_id",
                "OMP resume requires an exact captured provider session uuid",
            )
        if session_id.strip().lower() in AMBIGUOUS_SESSION_TOKENS:
            raise ValidationIssue(
                "ambiguous_session_id",
                f"Session id `{session_id}` is ambiguous and forbidden for OMP resume",
            )
        argv.extend(["--resume", session_id.strip()])
    # Packet path must be a bare argv element so the full-run supervisor can
    # rebind the staged packet snapshot (count(path)==1). omp loads file
    # contents via --append-system-prompt <path>.
    argv.extend(["--append-system-prompt", str(packet_path)])
    argv.append(
        "Implement the Elves worker packet appended to the system prompt. "
        "Follow owned/forbidden surfaces; commit on the assigned feature branch only; "
        "never merge or open PRs."
    )

    if "-c" in argv or "--continue" in argv:
        raise ValidationIssue(
            "ambiguous_session_flag",
            "OMP implement launch must not use bare --continue/-c",
        )
    if "--prewalk" in argv:
        raise ValidationIssue(
            "omp_prewalk_forbidden",
            "omp --prewalk is not Elves prewalk and is forbidden on this lane",
        )
    if "--resume" in argv:
        idx = argv.index("--resume")
        if idx + 1 >= len(argv) or argv[idx + 1].startswith("-"):
            raise ValidationIssue(
                "ambiguous_session_flag",
                "OMP --resume requires an exact session id",
            )
    return argv


def _build_devin_launch_argv(
    *,
    session_id: str,
    packet_path: Path,
    cwd_path: Path,
    model: str | None,
    permission_mode: str,
    executable: str,
    create: bool,
    effort: str | None,
    export_path: str | None,
) -> list[str]:
    """Build Devin CLI implement argv for Lane A / full-run worker.

    The returned argv always includes ``--print`` so the real CLI runs in
    non-interactive mode and the background supervisor does not block on the TUI.
    """
    exe_hint = (executable or "devin").strip() or "devin"
    exe = resolve_executable_for_launch(exe_hint) or exe_hint
    model_name, _effort_name, _alias_notes = resolve_implement_model(
        model, effort=effort, adapter="devin-cli"
    )
    perm = _normalize_devin_permission(permission_mode)

    argv = [exe]
    if not create:
        if not session_id:
            raise ValidationIssue(
                "missing_session_id",
                "Devin resume requires an exact captured provider session id",
            )
        argv.extend(["--resume", session_id])
    # Devin does not accept a pre-allocated session id on create; the host captures
    # the provider UUID from `devin list --format json` after launch.
    argv.extend(["--prompt-file", str(packet_path)])
    # --print is the real non-interactive transport. Without it, devin starts its
    # interactive TUI and the background supervisor may hang.
    argv.append("--print")
    argv.extend(["--model", model_name])
    argv.extend(["--permission-mode", perm])
    if export_path:
        argv.extend(["--export", export_path])

    # Product invariants: no ambiguous session flags.
    if "-c" in argv or "--continue" in argv:
        raise ValidationIssue(
            "ambiguous_session_flag",
            "Devin implement launch must not use bare --continue/-c",
        )
    if "--resume" in argv:
        idx = argv.index("--resume")
        if idx + 1 >= len(argv) or argv[idx + 1].startswith("-"):
            raise ValidationIssue(
                "ambiguous_session_flag",
                "Devin --resume requires an exact session id",
            )
    # working directory is enforced via Popen cwd, not a --cwd flag.
    if "--cwd" in argv:
        raise ValidationIssue(
            "implement_devin_unsupported_flag",
            "Devin CLI does not support --cwd; use Popen cwd instead",
        )
    return argv


def humanize_grok_failure(
    *,
    stderr: str | None = None,
    stdout: str | None = None,
    message: str | None = None,
    exit_code: int | None = None,
) -> str:
    """Map noisy Grok CLI / Rust dumps to a short operator message.

    Failure-mapping approach adapted from stdevMac/grok-in-claude and
    grok-in-codex ``humanizeGrokFailure`` (Apache-2.0); wording is Elves-owned.
    """
    parts = [message, stderr, stdout]
    blob = "\n".join(str(p).strip() for p in parts if p and str(p).strip())
    if not blob:
        if exit_code is not None and exit_code != 0:
            return f"Grok exited with code {exit_code}."
        return "Grok failed with no error details."

    compact = re.sub(r"\s+", " ", blob).strip()

    if re.search(r"RequirementError", blob, re.I) and re.search(
        r"run_terminal_cmd|background|--tools", blob, re.I
    ):
        return (
            "Grok CLI rejected the tool configuration while creating a session. "
            "On Grok Build ~0.2.93 prefer default tools + `--disallowed-tools` denylists "
            "for read-only/media modes; avoid `--tools` allowlists. "
            "Lane A implement still uses the default toolset + `--yolo`."
        )

    if re.search(r"RequirementError", blob, re.I):
        brief_match = re.search(r"RequirementError[:\s{]*([^}\n]{10,200})", blob, re.I)
        brief = (brief_match.group(1).strip() if brief_match else compact[:180])
        return (
            f"Grok CLI requirement error: {brief}. "
            "Check `grok version`, auth (`grok login`), and plan features."
        )

    if re.search(r"not logged in|unauthori[sz]ed|authentication required|auth.*fail", blob, re.I):
        return "Grok is not authenticated. Run `grok login`."

    if re.search(r"command not found|No such file or directory.*grok|Grok CLI not found", blob, re.I):
        return "Grok CLI not found. Install Grok Build and ensure `grok` is on PATH."

    if re.search(r"rate.?limit|too many requests|\b429\b", blob, re.I):
        return "Grok rate-limited the request. Wait and retry."

    if re.search(r"model .+ not found|unknown model|invalid model", blob, re.I):
        return (
            "Grok rejected the model id. Use a valid live-catalog model "
            "(e.g. `grok-4.5`) or omit --model for the preferred worker default."
        )

    first_useful = None
    for line in blob.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\[stderr\]", line, re.I):
            continue
        if re.match(r"^thread '", line, re.I):
            continue
        if len(line) >= 400:
            continue
        first_useful = line
        break
    if not first_useful:
        first_useful = compact[:280]

    if exit_code is not None and exit_code != 0:
        return f"Grok failed (exit {exit_code}): {first_useful}"
    return first_useful



def detect_native_grok_goal(
    executable: str = "grok",
    *,
    help_text: str | None = None,
) -> dict[str, object]:
    """Detect advertised headless goal syntax without claiming behavioral qualification.

    Installed Grok may expose `/goal` as a TUI skill without a public headless
    ``--goal`` flag. Help output is advertisement evidence only; a separate
    recorded behavioral probe must qualify goal-mode execution.
    """
    import re
    import shutil
    import subprocess
    import tempfile

    text = help_text
    if text is None:
        resolved = shutil.which(executable) or executable
        try:
            with tempfile.TemporaryDirectory(prefix="elves-grok-goal-probe-") as tmp:
                probe_env = {
                    "HOME": tmp,
                    "GROK_HOME": str(Path(tmp) / "grok"),
                    "XDG_CONFIG_HOME": str(Path(tmp) / "config"),
                    "XDG_CACHE_HOME": str(Path(tmp) / "cache"),
                    "XDG_DATA_HOME": str(Path(tmp) / "data"),
                    "PATH": os.environ.get("PATH") or os.defpath,
                    "LANG": os.environ.get("LANG") or "C.UTF-8",
                }
                proc = subprocess.run(
                    [resolved, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                    env=probe_env,
                )
            text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except (OSError, subprocess.TimeoutExpired):
            text = ""
    lower = text.lower()
    # Public headless flag (preferred).
    has_goal_flag = bool(re.search(r"--goal\s+<[^>]+>", lower))
    # Explicit noninteractive goal subcommand (not TUI-only /goal mention).
    has_goal_subcommand = bool(
        re.search(r"(?m)^\s*goal\s+", text)
        and "noninteractive" in lower
    )
    # TUI skill mention alone is not headless native goal.
    tui_only = ("/goal" in lower or "goal mode" in lower) and not (
        has_goal_flag or has_goal_subcommand
    )
    if has_goal_flag:
        return {
            "advertised_headless_entrypoint": True,
            "goal_mode_behaviorally_verified": False,
            "native_goal": False,
            "mode": "advertised_headless_entrypoint",
            "fallback": "packet_prompt_headless",
            "detail": "Installed Grok advertises a headless goal entrypoint; behavior is unverified",
            "tui_goal_mentioned": "/goal" in lower or "goal mode" in lower,
        }
    return {
        "advertised_headless_entrypoint": has_goal_subcommand,
        "goal_mode_behaviorally_verified": False,
        "native_goal": False,
        "mode": "headless_compatible_fallback",
        "fallback": "packet_prompt_headless",
        "detail": (
            "No public headless --goal flag; use compatible headless prompt/packet "
            "launch without claiming native goal orchestration"
            + ("; TUI /goal is present but not a headless API" if tui_only else "")
            + (
                "; an advertised goal subcommand is not used without a packet-path contract"
                if has_goal_subcommand
                else ""
            )
        ),
        "tui_goal_mentioned": tui_only or ("/goal" in lower),
    }


def resolve_phase_route(
    *,
    phase: str,
    requested_model: str | None = None,
    requested_effort: str | None = None,
    capability_available: bool = True,
    host: str = "native",
) -> dict[str, object]:
    """Record requested/actual/fallback for phase model + reasoning effort."""
    requested = {
        "phase": phase,
        "model": requested_model,
        "effort": requested_effort,
        "host": host,
    }
    if capability_available and (requested_model or requested_effort):
        return {
            "requested_route": requested,
            "actual_route": {
                "phase": phase,
                "model": requested_model,
                "effort": requested_effort,
                "host": host,
            },
            "fallback_reason": None,
        }
    return {
        "requested_route": requested,
        "actual_route": {
            "phase": phase,
            "model": None,
            "effort": None,
            "host": "native",
            "route": "host-native",
        },
        "fallback_reason": "capability_missing_or_unconfigured; native fallback",
    }


def optional_media_capabilities(
    *,
    image_available: bool | None = None,
    video_available: bool | None = None,
) -> dict[str, object]:
    """Grok image/video are optional discoverable capabilities."""
    def _one(name: str, available: bool | None) -> dict[str, object]:
        if available is True:
            status = "available"
            detail = f"{name} generation capability present"
        elif available is False:
            status = "unavailable"
            detail = f"{name} unavailable on this tier; graceful no-op fallback"
        else:
            status = "unknown"
            detail = f"{name} not probed; treat as optional non-fatal"
        return {
            "name": name,
            "status": status,
            "required": False,
            "default_report_format": False,
            "bounded_ownership": "worker_artifact_host_review",
            "detail": detail,
        }

    return {
        "image": _one("image", image_available),
        "video": _one("video", video_available),
        "policy": "optional_non_fatal_unavailable_tier_fallback",
    }


def build_launch_argv(
    *,
    session_id: str | None = None,
    packet: str | Path,
    cwd: str | Path,
    model: str | None = None,
    permission_mode: str = DEFAULT_PERMISSION_MODE,
    executable: str | None = None,
    create: bool = False,
    effort: str | None = None,
    yolo: bool = True,
    max_turns: int | None = 80,
    output_format: str | None = "json",
    adapter: str = "grok-build",
    check: bool = False,
    native_goal: bool = False,
    export_path: str | None = None,
) -> list[str]:
    """Build headless implementer argv for Grok Build (Lane A), OpenCode, or Devin.

    Grok Build dogfood (0.2.93–0.2.101):
    - ``--prompt-file`` or ``-p`` both trigger headless multi-turn with tools.
    - ``--yolo`` / ``--always-approve`` alone is required for unattended edits;
      do not combine it with an explicit ``--permission-mode auto``.
    - Exact session id only; never bare continue.
    - Optional ``--check`` asks Grok to verify before returning (CLI flag).

    OpenCode (opencode.ai):
    - ``opencode run`` with packet contents as message; ``--auto`` for unattended tools.
    - Model format ``provider/model`` (often via OpenRouter).
    - Exact ``--session <id>`` only (never bare ``--continue``).

    Devin CLI:
    - ``--prompt-file`` for non-interactive initial prompt.
    - ``--print`` is required so the real CLI runs in non-interactive mode and
      the background supervisor does not block on the interactive TUI.
    - Exact ``--resume <id>`` only (never ``--continue`` / bare ``--resume``).
    - ``--model`` pins the model; default ``swe-1-7-lightning``.
    - ``--permission-mode`` is explicit; Elves ``auto`` maps to ``dangerous`` for
      unattended execution.
    - ``--export <path>`` is optional ATIF export.
    """
    packet_path = Path(packet).expanduser().resolve()
    if not packet_path.is_file():
        raise ValidationIssue(
            "packet_missing",
            f"Packet file not found: {packet_path}",
        )
    cwd_path = Path(cwd).expanduser().resolve()
    adapter_name = (adapter or "grok-build").strip().lower()
    reject_fugu_implementation_route(
        adapter_name,
        executable,
        requested_model=model,
    )
    sid = (session_id or "").strip()
    if sid.lower() in AMBIGUOUS_SESSION_TOKENS:
        raise ValidationIssue(
            "ambiguous_session_id",
            f"Session id `{sid}` is ambiguous and forbidden for implement launch",
            hint="Use an exact UUID/session id from the registry",
        )

    if adapter_name == "devin-cli":
        return _build_devin_launch_argv(
            session_id=sid,
            packet_path=packet_path,
            cwd_path=cwd_path,
            model=model,
            permission_mode=permission_mode,
            executable=executable,
            create=create,
            effort=effort,
            export_path=export_path,
        )

    if adapter_name == "omp-cli":
        return _build_omp_launch_argv(
            session_id=sid,
            packet_path=packet_path,
            cwd_path=cwd_path,
            model=model,
            executable=executable or "omp",
            create=create,
            effort=effort,
            yolo=yolo,
        )

    if adapter_name in {"opencode-cli", "opencode-labor", "opencode"}:
        # Attach packet via --file to avoid ARG_MAX (do not stuff full packet into argv).
        exe_hint = (executable or "opencode").strip() or "opencode"
        exe = resolve_executable_for_launch(exe_hint) or exe_hint
        model_name, _, _ = resolve_implement_model(model, adapter=adapter_name)
        message = (
            "Implement the attached task packet. Follow host packet constraints; "
            "prefer exact session continuity; do not invent secrets."
        )
        argv: list[str] = [
            exe,
            "run",
            # OpenCode parses the first positional after `run` as the message. Keep it
            # before --file flags; a trailing message can be consumed as another file.
            message,
            "--dir",
            str(cwd_path),
            "--file",
            str(packet_path),
        ]
        if sid:
            argv.extend(["--session", sid])
        if model_name:
            argv.extend(["--model", model_name])
        if yolo:
            argv.append("--auto")
        if "-c" in argv or "--continue" in argv:
            raise ValidationIssue(
                "ambiguous_session_flag",
                "OpenCode implement launch must not use bare --continue",
            )
        return argv

    # Default: Grok Build Lane A
    if sid:
        sid = require_exact_grok_session_uuid(sid)
    perm = _normalize_permission(permission_mode)
    exe_hint = (executable or DEFAULT_EXECUTABLE).strip() or DEFAULT_EXECUTABLE
    exe = resolve_executable_for_launch(exe_hint) or exe_hint
    model_name, effort_name, _alias_notes = resolve_implement_model(
        model, effort=effort, adapter="grok-build"
    )
    effort_name = (
        effort_name or GROK_DEFAULT_EFFORT
    ).strip() or GROK_DEFAULT_EFFORT

    argv = [exe]
    if create:
        if not sid:
            raise ValidationIssue(
                "missing_session_id",
                "create=True requires an exact new session UUID",
            )
        argv.extend(["--session-id", sid])
    elif sid:
        argv.extend(["--resume", sid])
    # Goal mode is a behaviorally-proven `/goal ...` slash command stored in a
    # private prompt file. The installed CLI has no public `--goal` flag.
    argv.extend(["--prompt-file", str(packet_path)])
    argv.extend(["--cwd", str(cwd_path), "--model", model_name])
    # Grok Build gives an explicit --permission-mode precedence over
    # --always-approve. In 0.2.101, combining `auto` with yolo disables both
    # unattended paths and the first headless permission prompt is cancelled.
    # Keep the explicit mode for non-yolo/restricted launches; the trusted
    # implementation lane uses the unambiguous --always-approve surface alone.
    if not (yolo and perm == DEFAULT_PERMISSION_MODE):
        argv.extend(["--permission-mode", perm])
    argv.extend(["--effort", effort_name])
    if yolo:
        argv.append("--always-approve")
    if check:
        # Grok CLI post-work verification flag (also used by community companions).
        argv.append("--check")
    if max_turns is not None and int(max_turns) > 0:
        argv.extend(["--max-turns", str(int(max_turns))])
    if output_format:
        argv.extend(["--output-format", str(output_format)])
    # Product invariants: no crippling flags.
    joined = " ".join(argv)
    if "--no-subagents" in argv or "--no-subagents" in joined:
        raise ValidationIssue(
            "implement_no_subagents_forbidden",
            "Lane A launch argv must not include --no-subagents",
        )
    if FORBIDDEN_DEFAULT_PERMISSION in argv:
        raise ValidationIssue(
            "implement_dontask_forbidden",
            "Lane A launch argv must not use permission-mode dontAsk",
        )
    if "-p" in argv or "--single" in argv:
        raise ValidationIssue(
            "implement_prompt_conflict",
            "Lane A launch uses --prompt-file only; do not also pass -p/--single",
        )
    return argv


def _close_selector_stream(selector: selectors.BaseSelector, fileobj: Any) -> None:
    try:
        selector.unregister(fileobj)
    except (KeyError, OSError, ValueError):
        pass
    try:
        fileobj.close()
    except OSError:
        pass


def _close_selector_streams(selector: selectors.BaseSelector) -> None:
    for key in list(selector.get_map().values()):
        _close_selector_stream(selector, key.fileobj)


def _drain_selector_once(
    selector: selectors.BaseSelector,
    *,
    timeout_seconds: float,
) -> None:
    for key, _mask in selector.select(max(0.0, timeout_seconds)):
        capture = key.data
        try:
            chunk = os.read(key.fd, _EXEC_READ_CHUNK_BYTES)
        except BlockingIOError:
            continue
        except OSError as exc:
            if exc.errno in {errno.EBADF, errno.EIO}:
                _close_selector_stream(selector, key.fileobj)
                continue
            raise
        if chunk:
            capture.add(chunk)
        else:
            _close_selector_stream(selector, key.fileobj)


def _drain_selector_until(
    selector: selectors.BaseSelector,
    *,
    deadline: float,
) -> None:
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        _drain_selector_once(
            selector,
            timeout_seconds=min(_EXEC_SELECTOR_POLL_SECONDS, remaining),
        )


def _signal_process_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except OSError as exc:
        # Darwin can report EPERM, rather than ESRCH, when the leader remains an
        # unreaped zombie but TERM already removed the group's last signalable
        # member. The pinned leader prevents identity reuse, so ignoring either
        # result cannot redirect this cleanup signal toward an unrelated launch.
        if exc.errno not in {errno.ESRCH, errno.EPERM}:
            raise


def _terminate_and_reap_process_group(
    proc: subprocess.Popen[bytes],
    *,
    pgid: int,
    selector: selectors.BaseSelector,
    supervisor: _ImplementDescendantSupervisor,
    term_grace_seconds: float,
    kill_grace_seconds: float,
) -> None:
    """Terminate the launch session while its unreaped leader pins PID/PGID identity."""
    cleanup_error: ValidationIssue | None = None
    _signal_process_group(pgid, signal.SIGTERM)
    _drain_selector_until(
        selector,
        deadline=time.monotonic() + max(0.0, term_grace_seconds),
    )

    # Always escalate before wait()/reap. Until then the direct session leader
    # pins its numeric PID/PGID, so the stored group identifier cannot be reused
    # by an unrelated launch between TERM and KILL.
    _signal_process_group(pgid, signal.SIGKILL)
    _drain_selector_until(
        selector,
        deadline=time.monotonic() + max(0.0, kill_grace_seconds),
    )
    try:
        # The process-group signals cover ordinary children while the unreaped
        # leader pins the PGID. Stable per-process supervision additionally
        # cleans descendants observed by the trusted-lane ancestry scan.
        supervisor.terminate_known_descendants(
            term_grace_seconds=term_grace_seconds,
            kill_grace_seconds=kill_grace_seconds,
        )
    except ValidationIssue as exc:
        cleanup_error = exc
    # A descendant that inherited a pipe must never make cleanup perform another
    # unbounded communicate(). Closing our nonblocking readers is deterministic;
    # the killed launch group then observes EPIPE if anything races a final write.
    _close_selector_streams(selector)

    wait_timeout = max(0.05, kill_grace_seconds)
    try:
        proc.wait(timeout=wait_timeout)
    except subprocess.TimeoutExpired:
        # The direct child is still unreaped, so Popen.kill() cannot target a
        # reused PID. This is a final direct-process fallback, not group discovery.
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired as exc:
            raise ValidationIssue(
                "implement_timeout_cleanup_failed",
                "Timed-out implementer could not be reaped after SIGKILL",
            ) from exc
    try:
        supervisor.terminate_known_descendants(
            term_grace_seconds=0.0,
            kill_grace_seconds=kill_grace_seconds,
        )
    except ValidationIssue as exc:
        cleanup_error = cleanup_error or exc
    if cleanup_error is not None:
        raise cleanup_error


def _execute_bounded_process(
    argv: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: float = _EXEC_TIMEOUT_SECONDS,
    term_grace_seconds: float = _EXEC_TERM_GRACE_SECONDS,
    kill_grace_seconds: float = _EXEC_KILL_GRACE_SECONDS,
    capture_window_bytes: int = _EXEC_CAPTURE_WINDOW_BYTES,
) -> _BoundedProcessResult:
    """Run one bounded implementation leader on a qualified platform."""
    _require_implement_supervision_capability()
    supervision_marker = secrets.token_hex(24)
    launch_env = dict(env)
    launch_env[_EXEC_SUPERVISION_ENV] = supervision_marker
    supervisor = _ImplementDescendantSupervisor(
        marker=supervision_marker,
        root_pid=0,
    )
    stdout_capture = _RollingCapture(capture_window_bytes)
    stderr_capture = _RollingCapture(capture_window_bytes)
    selector = selectors.DefaultSelector()
    proc: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    timed_out = False
    completed = False
    cleanup_completed = False
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=launch_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            start_new_session=True,
        )
        # Enter this process-owned try before any post-launch allocation or
        # inspection. start_new_session makes PID == PGID, and the unreaped child
        # pins both numeric identities until cleanup finishes.
        pgid = int(proc.pid)
        supervisor.root_pid = pgid
        supervisor.attach()
        if proc.stdout is None or proc.stderr is None:  # pragma: no cover - Popen contract
            raise OSError("bounded implement capture requires stdout/stderr pipes")
        for stream, capture in (
            (proc.stdout, stdout_capture),
            (proc.stderr, stderr_capture),
        ):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, capture)

        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        next_descendant_scan = time.monotonic() + _EXEC_DESCENDANT_SCAN_SECONDS
        leader_exited = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            # Native process state reports SZOMB/Z without wait()/poll(), so the
            # leader remains unreaped and continues pinning its PID and PGID while
            # descendants that inherited stdout/stderr are contained.
            if supervisor.root_exited():
                leader_exited = True
                break
            if selector.get_map():
                _drain_selector_once(
                    selector,
                    timeout_seconds=min(_EXEC_SELECTOR_POLL_SECONDS, remaining),
                )
            else:
                time.sleep(min(_EXEC_SELECTOR_POLL_SECONDS, remaining))
            if time.monotonic() >= next_descendant_scan:
                supervisor.scan()
                next_descendant_scan = (
                    time.monotonic() + _EXEC_DESCENDANT_SCAN_SECONDS
                )

        if leader_exited:
            # Capture descendants while their unreaped parent still pins the
            # launch generation. This includes children that retained pipes.
            supervisor.scan()

        if timed_out or leader_exited:
            _terminate_and_reap_process_group(
                proc,
                pgid=pgid,
                selector=selector,
                supervisor=supervisor,
                term_grace_seconds=term_grace_seconds,
                kill_grace_seconds=kill_grace_seconds,
            )
            cleanup_completed = True
            completed = True
        else:  # pragma: no cover - loop exits only for timeout or leader exit
            raise ValidationIssue(
                "implement_supervision_identity_failed",
                "Bounded implementer exited without an observable leader state",
            )

        return _BoundedProcessResult(
            exit_code=124 if timed_out else int(proc.returncode or 0),
            timed_out=timed_out,
            stdout_window=stdout_capture.text(),
            stderr_window=stderr_capture.text(),
            stdout_digest=stdout_capture.digest_prefix(),
            stderr_digest=stderr_capture.digest_prefix(),
            stdout_bytes=stdout_capture.total_bytes,
            stderr_bytes=stderr_capture.total_bytes,
        )
    except BaseException:
        if (
            proc is not None
            and pgid is not None
            and not completed
            and not cleanup_completed
        ):
            try:
                _terminate_and_reap_process_group(
                    proc,
                    pgid=pgid,
                    selector=selector,
                    supervisor=supervisor,
                    term_grace_seconds=term_grace_seconds,
                    kill_grace_seconds=kill_grace_seconds,
                )
                cleanup_completed = True
            except BaseException as cleanup_error:
                # The structured retry did not prove absence. Make one bounded
                # best-effort kill/reap pass, but never promote that effort into
                # proof or return a normal execution result.
                # Do not poll here: poll() may reap a naturally exited leader,
                # releasing the numeric PID/PGID before same-group children are
                # signaled. ``returncode is None`` preserves the pinned identity.
                if proc.returncode is None:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        try:
                            proc.kill()
                        except (OSError, ProcessLookupError):
                            pass
                    try:
                        proc.wait(timeout=max(0.05, kill_grace_seconds))
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                try:
                    supervisor.terminate_known_descendants(
                        term_grace_seconds=0.0,
                        kill_grace_seconds=kill_grace_seconds,
                    )
                except BaseException:
                    pass
                raise ValidationIssue(
                    "implement_cleanup_failed",
                    "Bounded implementer cleanup failed and recursive absence "
                    "remained unproved",
                ) from cleanup_error
        raise
    finally:
        _close_selector_streams(selector)
        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        selector.close()


def launch_payload(
    repo_root: Path,
    *,
    session_id: str | None = None,
    packet: str | Path,
    cwd: str | Path | None = None,
    model: str | None = None,
    permission_mode: str | None = None,
    executable: str | None = None,
    create: bool = False,
    batch: int | None = None,
    exec_process: bool = False,
    effort: str | None = None,
    check: bool = False,
) -> dict[str, Any]:
    """Build (and optionally exec) Lane A launch argv. Default is print-only."""
    normalized_batch = (
        _require_nonnegative_batch(batch) if batch is not None else None
    )
    state = load_state(repo_root)
    sid = (session_id or (state.session_id if state else None) or "").strip()
    adapter_name = (state.adapter if state else "grok-build") or "grok-build"
    # OpenCode and Devin may start without a pre-allocated session id (host captures after first run).
    if not sid and adapter_name not in {
        "opencode-cli", "opencode-labor", "opencode", "devin-cli", "omp-cli"
    }:
        raise ValidationIssue(
            "missing_session_id",
            "session_id required (pass --session-id or run prepare first)",
        )
    worktree = cwd or (state.worktree if state else None) or str(Path(repo_root).resolve())
    is_opencode = adapter_name in {"opencode-cli", "opencode-labor", "opencode"}
    is_devin = adapter_name == "devin-cli"
    raw_model = model or (state.model if state else None) or (
        "openrouter/qwen/qwen3-max" if is_opencode else
        "swe-1-7-lightning" if is_devin else
        GROK_LIVE_DEFAULT
    )
    if not is_opencode and not is_devin:
        from .worker_routing import (  # noqa: PLC0415
            GROK_RETIRED_COMPOSER_MODEL,
            probe_grok_capabilities,
            select_preferred_grok_worker_model,
        )

        probe_executable = (
            executable
            or (state.executable if state else None)
            or DEFAULT_EXECUTABLE
        )
        capabilities = probe_grok_capabilities(probe_executable)
        unavailable = capabilities.core_launch_unavailable_reason(
            create=bool(create),
            check=bool(check),
        )
        if unavailable:
            raise ValidationIssue(
                "grok_launch_capability_unavailable",
                "Installed Grok Build lacks a required bounded-launch capability",
                hint=unavailable,
            )
        if not capabilities.authenticated or not capabilities.models:
            catalog = capabilities.capability("model_catalog")
            raise ValidationIssue(
                "grok_live_catalog_unavailable",
                "Legacy Grok launch requires an authenticated live model catalog",
                hint=(catalog.reason if catalog else "model_catalog_not_probed"),
            )
        requested = str(raw_model).strip()
        if requested in {"", GROK_LIVE_DEFAULT, "auto"}:
            selected = select_preferred_grok_worker_model(capabilities)
            if not selected:
                if capabilities.default_model == GROK_RETIRED_COMPOSER_MODEL:
                    raise ValidationIssue(
                        "grok_model_retired",
                        f"Grok model `{GROK_RETIRED_COMPOSER_MODEL}` is retired; "
                        "use grok-4.5 when the live catalog offers it",
                    )
                raise ValidationIssue(
                    "grok_model_not_in_live_catalog",
                    "No usable Grok worker model in the authenticated live catalog",
                )
            requested = selected
        elif requested == GROK_RETIRED_COMPOSER_MODEL:
            raise ValidationIssue(
                "grok_model_retired",
                f"Grok model `{requested}` is retired; use grok-4.5",
            )
        elif requested not in capabilities.models:
            raise ValidationIssue(
                "grok_model_not_in_live_catalog",
                f"Requested Grok model `{requested or raw_model}` is absent from the authenticated live catalog",
            )
        raw_model = requested
    model_name, effort_name, alias_notes = resolve_implement_model(
        raw_model, effort=effort, adapter=adapter_name
    )
    perm = permission_mode or (state.permission_mode if state else None) or DEFAULT_PERMISSION_MODE
    exe = executable or (state.executable if state else None) or (
        "opencode" if is_opencode else
        "devin" if is_devin else
        DEFAULT_EXECUTABLE
    )

    argv = build_launch_argv(
        session_id=sid or None,
        packet=packet,
        cwd=worktree,
        # Pass raw model so aliases resolve once (deep → high effort).
        model=raw_model,
        permission_mode=perm,
        executable=exe,
        create=create,
        effort=effort,
        yolo=True,
        max_turns=80,
        output_format="json",
        adapter=adapter_name,
        check=bool(check) and not is_opencode,
    )

    # Persist last launch pointers for status/resume. Store resolved model id.
    persist_model = model_name if not is_opencode else (model or model_name)
    if state is None:
        state = ImplementState(
            worktree=str(Path(worktree).expanduser().resolve()),
            adapter=adapter_name,
            model=persist_model,
            permission_mode=perm if is_opencode else _normalize_permission(perm),
            session_id=sid or None,
            executable=exe,
            created_at=_utc_now(),
        )
    else:
        state.session_id = sid or state.session_id
        state.worktree = str(Path(worktree).expanduser().resolve())
        state.model = persist_model
        state.adapter = adapter_name
        state.permission_mode = perm if is_opencode else _normalize_permission(perm)
        state.executable = exe
    state.last_packet = str(Path(packet).expanduser().resolve())
    if normalized_batch is not None:
        state.last_batch = normalized_batch
    save_state(repo_root, state)

    notes = [
        "Default is print-only; legacy --exec requires a qualified recursive boundary",
        "Grok Lane A: never dontAsk / no --no-subagents",
        "OpenCode labor: opencode run --auto; exact --session preferred; OpenRouter provider/model",
    ]
    notes.extend(alias_notes)
    if check and not is_opencode:
        notes.append("Grok --check enabled (post-work verification; higher latency/cost)")

    payload: dict[str, Any] = {
        "ok": True,
        "action": "launch",
        "session_id": sid or None,
        "adapter": adapter_name,
        "argv": argv,
        "argv_joined": " ".join(argv),
        "cwd": str(Path(worktree).expanduser().resolve()),
        "packet": str(Path(packet).expanduser().resolve()),
        "model": model_name if not is_opencode else raw_model,
        "effort": effort_name if not is_opencode else None,
        "check": bool(check) and not is_opencode,
        "permission_mode": perm if is_opencode else _normalize_permission(perm),
        "create": create,
        "launched": False,
        "mutated_repo": False,
        "model_calls_made": False,
        "notes": notes,
    }

    if exec_process:
        # Optional operator convenience; not the default host path.
        # Minimal adapter-specific environment + named credential grants only.
        grant_names = [
            "XAI_API_KEY",
            "GROK_API_KEY",
        ]
        if is_opencode:
            grant_names.extend(["OPENROUTER_API_KEY", "OPENAI_API_KEY"])
        grants = {
            name: os.environ[name]
            for name in grant_names
            if name in os.environ and os.environ[name]
        }
        exact_grants = set(grants.values())
        with _managed_implement_env(
            adapter=adapter_name,
            worktree=Path(worktree),
            credential_grants=grants,
        ) as child_env:
            try:
                result = _execute_bounded_process(
                    argv,
                    cwd=Path(worktree).expanduser().resolve(),
                    env=child_env,
                )
            except OSError as exc:
                message = redact_text(
                    f"Unable to spawn implementer argv {argv!r}: {exc}",
                    exact_values=exact_grants,
                ).text
                raise ValidationIssue(
                    "implement_launch_spawn_failed",
                    message,
                    path=str(worktree),
                ) from exc
            payload["launched"] = True
            payload["model_calls_made"] = True
            payload["exit_code"] = int(result.exit_code)
            payload["ok"] = not result.timed_out and result.exit_code == 0
            # Redact the bounded rolling window before selecting legacy tails. A
            # cutoff therefore cannot retain a partial exact grant merely because
            # truncation happened first.
            stdout_redacted = redact_text(
                result.stdout_window, exact_values=exact_grants
            ).text
            stderr_redacted = redact_text(
                result.stderr_window, exact_values=exact_grants
            ).text
            stdout_tail = stdout_redacted[-_EXEC_OUTPUT_TAIL_CHARS:]
            stderr_tail = stderr_redacted[-_EXEC_OUTPUT_TAIL_CHARS:]
            payload["stdout_digest"] = result.stdout_digest
            payload["stderr_digest"] = result.stderr_digest
            payload["stdout_summary"] = stdout_tail[-_EXEC_OUTPUT_SUMMARY_CHARS:]
            payload["stderr_summary"] = stderr_tail[-_EXEC_OUTPUT_SUMMARY_CHARS:]
            payload["stdout_tail"] = stdout_tail
            payload["stderr_tail"] = stderr_tail
            payload["credential_grant_names_present"] = sorted(grants.keys())
            if result.timed_out:
                payload["error_human"] = (
                    "implement --exec timed out; process group terminated"
                )
            elif not payload["ok"] and not is_opencode:
                payload["error_human"] = humanize_grok_failure(
                    stderr=stderr_redacted,
                    stdout=stdout_redacted,
                    exit_code=int(result.exit_code),
                )
            return payload

    return payload


def resume_batch_payload(
    repo_root: Path,
    *,
    batch: int,
    packet: str | Path,
    session_id: str | None = None,
    cwd: str | Path | None = None,
    model: str | None = None,
    permission_mode: str | None = None,
    executable: str | None = None,
    exec_process: bool = False,
    effort: str | None = None,
    check: bool = False,
) -> dict[str, Any]:
    """Print launch argv for the next batch packet (same session, resume)."""
    normalized_batch = _require_nonnegative_batch(batch)
    payload = launch_payload(
        repo_root,
        session_id=session_id,
        packet=packet,
        cwd=cwd,
        model=model,
        permission_mode=permission_mode,
        executable=executable,
        create=False,
        batch=normalized_batch,
        exec_process=exec_process,
        effort=effort,
        check=check,
    )
    payload["action"] = "resume-batch"
    payload["batch"] = normalized_batch
    return payload


def _git_rev_parse(
    cwd: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            env=dict(env) if env is not None else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    tip = (result.stdout or "").strip()
    return tip or None


def parse_unittest_output(text: str) -> dict[str, int]:
    """Parse `unittest` summary lines into counts."""
    ran_match = _RAN_RE.search(text or "")
    total = int(ran_match.group(1)) if ran_match else 0
    failures = 0
    errors = 0
    skipped = 0
    fail_match = _FAIL_RE.search(text or "")
    if fail_match:
        if fail_match.group(1):
            failures = int(fail_match.group(1))
        if fail_match.group(2):
            errors = int(fail_match.group(2))
    # Also handle "FAILED (failures=1)" without errors= and "OK (skipped=N)"
    alt_fail = re.search(r"failures=(\d+)", text or "")
    alt_err = re.search(r"errors=(\d+)", text or "")
    if alt_fail:
        failures = int(alt_fail.group(1))
    if alt_err:
        errors = int(alt_err.group(1))
    skip_match = re.search(r"skipped=(\d+)", text or "", re.IGNORECASE)
    if skip_match:
        skipped = int(skip_match.group(1))
    failed = failures + errors
    passed = max(total - failed - skipped, 0)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def _read_done_report(
    repo_root: Path,
    path: Path,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Read one optional done report through a bounded, no-symlink boundary."""
    try:
        payload = read_json(
            path,
            repo_root=Path(repo_root),
            max_bytes=MAX_DONE_REPORT_BYTES,
        )
    except StorageError as exc:
        if exc.code == "not_found":
            return False, None, None
        if exc.code == "record_too_large":
            return (
                True,
                None,
                f"done report exceeds {MAX_DONE_REPORT_BYTES} byte limit",
            )
        if exc.code == "invalid_utf8":
            return True, None, "done report is not valid UTF-8"
        if exc.code == "malformed_json":
            if "JSON object required" in exc.message:
                return True, None, "done report must be a JSON object"
            return True, None, "done report is not valid JSON"
        raise _storage_issue(exc, path=path, operation="read") from exc
    return True, payload, None


def _done_report_confidence_warnings(report: Mapping[str, Any]) -> list[str]:
    """Validate the optional worker confidence signal on a legacy done report.

    Absent fields are valid; an empty `unsure_about` list is a valid, complete
    answer. Warnings match the legacy gate's non-fatal dogfood posture; the
    signal is review triage only, never authority.
    """
    from .provider_auth import (  # noqa: PLC0415 - keep gate import surface lazy
        CONFIDENCE_LEVELS,
        MAX_UNSURE_ABOUT_ITEM_CHARS,
        MAX_UNSURE_ABOUT_ITEMS,
    )

    warnings: list[str] = []
    if "confidence" in report and report.get("confidence") not in CONFIDENCE_LEVELS:
        warnings.append(
            "done report confidence must be one of high, medium, low"
        )
    if "unsure_about" not in report:
        return warnings
    unsure = report.get("unsure_about")
    if not isinstance(unsure, list):
        warnings.append("done report unsure_about must be a list")
        return warnings
    if len(unsure) > MAX_UNSURE_ABOUT_ITEMS:
        warnings.append(
            f"done report unsure_about exceeds {MAX_UNSURE_ABOUT_ITEMS} items"
        )
    if any(not isinstance(item, str) or not item.strip() for item in unsure):
        warnings.append(
            "done report unsure_about items must be non-empty strings"
        )
    if any(
        isinstance(item, str) and len(item) > MAX_UNSURE_ABOUT_ITEM_CHARS
        for item in unsure
    ):
        warnings.append(
            f"done report unsure_about item exceeds {MAX_UNSURE_ABOUT_ITEM_CHARS} chars"
        )
    return warnings


def _redact_gate_record_in_place(
    record: dict[str, Any],
    *,
    exact_secret_values: frozenset[str],
) -> None:
    def redact_gate_value(value: Any) -> Any:
        if isinstance(value, str):
            return redact_text(value, exact_values=exact_secret_values).text
        if isinstance(value, Mapping):
            redacted_mapping: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                raw_key = str(key)
                redacted_key = redact_text(
                    raw_key,
                    exact_values=exact_secret_values,
                ).text
                semantic_secret_field = bool(_GATE_SECRET_FIELD_RE.search(raw_key))
                key_contains_secret = redacted_key != raw_key
                if semantic_secret_field:
                    redacted_key = "[REDACTED:secret_field_name]"
                if redacted_key in redacted_mapping:
                    # Redaction must never collapse two source fields and silently
                    # discard one. Preserve cardinality without restoring the key.
                    base_key = redacted_key
                    suffix = index
                    while f"{base_key}#{suffix}" in redacted_mapping:
                        suffix += 1
                    redacted_key = f"{base_key}#{suffix}"
                redacted_mapping[redacted_key] = (
                    "[REDACTED:secret_field]"
                    if semantic_secret_field or key_contains_secret
                    else redact_gate_value(item)
                )
            return redacted_mapping
        if isinstance(value, list):
            return [redact_gate_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(redact_gate_value(item) for item in value)
        return value

    redacted = redact_gate_value(record)
    if not isinstance(redacted, dict):  # pragma: no cover - mapping contract
        raise ValidationIssue(
            "implement_gate_record_invalid",
            "Gate record redaction did not preserve object shape",
        )
    # Keep the public handler's literal output shape visible to the compatibility
    # analyzer while sanitizing every nested value before persistence or return.
    record.clear()
    record.update(redacted)


def run_gate(
    repo_root: Path,
    *,
    batch: int,
    focused: bool = False,
    test_command: list[str] | None = None,
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    """Run tests, record tip + counts under gates/batch-N.json. Non-zero on fail."""
    batch = _require_nonnegative_batch(batch)
    ensure_implement_dirs(repo_root)
    work_cwd = Path(cwd).expanduser().resolve() if cwd else Path(repo_root).resolve()
    # Exact parent secrets for output redaction only — never child inheritance.
    exact_secret_values = collect_secret_env_values()

    if test_command:
        cmd = list(test_command)
    elif focused:
        cmd = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_cobbler_agents_implement.py",
        ]
    else:
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]

    with _managed_implement_env(
        adapter="gate",
        worktree=work_cwd,
    ) as gate_env:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(work_cwd),
                env=gate_env,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            message = redact_text(
                f"Unable to run gate command {cmd!r} in {work_cwd}: {exc}",
                exact_values=exact_secret_values,
            ).text
            raise ValidationIssue(
                "implement_gate_spawn_failed",
                message,
                path=redact_text(
                    str(work_cwd), exact_values=exact_secret_values
                ).text,
            ) from exc
        combined = (proc.stdout or "") + (
            "\n" + proc.stderr if proc.stderr else ""
        )
        counts = parse_unittest_output(combined)
        tip = _git_rev_parse(work_cwd, env=gate_env)

    # Redact before truncation so a tail boundary cannot retain a partial exact
    # secret that no longer matches the complete value.
    stdout_redacted = redact_text(
        proc.stdout or "", exact_values=exact_secret_values
    ).text
    stderr_redacted = redact_text(
        proc.stderr or "", exact_values=exact_secret_values
    ).text

    warnings: list[str] = []
    done_path = done_dir(repo_root) / f"batch-{int(batch)}.json"
    done_present, done_report, done_warning = _read_done_report(
        repo_root,
        done_path,
    )
    if done_warning:
        warnings.append(done_warning)
    if done_report is not None:
        warnings.extend(_done_report_confidence_warnings(done_report))
    if not done_present:
        warnings.append(
            f"done report missing (non-fatal for dogfood): {done_path}"
        )

    gate_path = gates_dir(repo_root) / f"batch-{int(batch)}.json"
    record = {
        "ok": proc.returncode == 0 and counts["failed"] == 0,
        "action": "gate",
        "batch": int(batch),
        "tip": tip,
        "tests": counts,
        "exit_code": int(proc.returncode),
        "command": cmd,
        "focused": focused,
        "cwd": str(work_cwd),
        "done_report_path": str(done_path),
        "done_report_present": done_present,
        "done_report": done_report,
        "warnings": warnings,
        "stdout_tail": stdout_redacted[-2000:],
        "stderr_tail": stderr_redacted[-2000:],
        "recorded_at": _utc_now(),
        "mutated_repo": False,
        "model_calls_made": False,
        "gate_path": str(gate_path),
    }
    _redact_gate_record_in_place(
        record,
        exact_secret_values=exact_secret_values,
    )
    try:
        _write_private_json(repo_root, gate_path, record)
    except ValidationIssue as exc:
        if exc.code in {
            "implement_runtime_symlink",
            "implement_runtime_hardlink",
            "implement_runtime_component_invalid",
        }:
            raise
        message = redact_text(
            f"Unable to persist gate record: {exc.code}",
            exact_values=exact_secret_values,
        ).text
        raise ValidationIssue(
            "implement_gate_write_failed",
            message,
            path=redact_text(
                str(gate_path), exact_values=exact_secret_values
            ).text,
        ) from exc

    state = load_state(repo_root)
    if state is not None:
        state.last_batch = int(batch)
        save_state(repo_root, state)

    return record


def status_payload(repo_root: Path) -> dict[str, Any]:
    """Show implement runtime state if present."""
    root = implement_root(repo_root)
    state = load_state(repo_root)
    try:
        gate_files = [
            path
            for path in list_repo_store_files(
                Path(repo_root),
                gates_dir(repo_root),
                suffix=".json",
            )
            if path.name.startswith("batch-")
        ]
        done_files = [
            path
            for path in list_repo_store_files(
                Path(repo_root),
                done_dir(repo_root),
                suffix=".json",
            )
            if path.name.startswith("batch-")
        ]
    except StorageError as exc:
        raise _storage_issue(exc, path=root, operation="list") from exc
    return {
        "ok": True,
        "action": "status",
        "present": state is not None,
        "repo_root": str(Path(repo_root).resolve()),
        "runtime_dir": str(root),
        "state": state.to_dict() if state else None,
        "gates": [str(p) for p in gate_files],
        "done_reports": [str(p) for p in done_files],
        "mutated_repo": False,
        "model_calls_made": False,
    }
