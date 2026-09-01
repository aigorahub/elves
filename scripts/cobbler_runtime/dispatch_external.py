"""Isolated external-lane subprocess lifecycle for council dispatch.

Checks platform filesystem-sandbox availability before isolated external
launch, creates the tracked-source snapshot *before* building adapter argv,
rewrites repo/CWD flags to the snapshot, and guarantees cleanup on every exit
path. Optional isolation failure skips that external attempt so its configured
fallback chain can continue; required isolation fails closed.
"""

from __future__ import annotations

import asyncio
import ctypes
import errno
import os
import secrets
import signal
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import (
    ADAPTER_CONTRACT_PAIRS,
    AdapterInvocation,
    assert_exact_session_id,
    build_readonly_invocation,
    default_decoder_for_adapter,
    validate_adapter_contract_pair,
    validate_extra_args,
)
from .context import redact_text
from .dispatch_models import LaneSpec
from .isolation import (
    IsolationSpec,
    IsolatedLane,
    copy_isolated_transport_inputs,
    create_tracked_snapshot,
    filesystem_sandbox_unavailable_message,
    resolve_fs_sandbox_backend,
    rewrite_argv_repo_paths,
    wrap_argv_with_sandbox,
)
from .schema import EffectiveAttempt, ValidationIssue


PROCESS_GROUP_GRACE_SECONDS = 0.5
PROCESS_GROUP_VERIFY_POLL_SECONDS = 0.05
PROCESS_GROUP_VERIFY_ATTEMPTS = 20
PROCESS_GROUP_SETTLE_SECONDS = 0.25
POST_CONTAINMENT_DRAIN_SECONDS = 2.0
DESCENDANT_POLL_SECONDS = 0.5
DESCENDANT_VERIFY_ATTEMPTS = 24


def session_id_for_attempt(
    spec: LaneSpec, attempt: EffectiveAttempt
) -> str | None:
    """Use lane continuity only on its original provider adapter."""
    if attempt.session_id is not None:
        selected = attempt.session_id
    elif attempt.adapter == spec.adapter:
        selected = spec.session_id
    else:
        selected = None
    return (
        assert_exact_session_id(selected, adapter=attempt.adapter)
        if selected is not None
        else None
    )


@dataclass(frozen=True)
class _ProcessRecord:
    pid: int
    ppid: int
    pgid: int
    start_identity: str
    command: str
    darwin_audit_token: tuple[int, ...] | None = None
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
        proc_pidinfo = library.proc_pidinfo
    except (AttributeError, OSError) as exc:
        raise ValidationIssue(
            "isolation_supervision_unavailable",
            f"Darwin proc_pidinfo is unavailable: {type(exc).__name__}",
        ) from exc
    proc_pidinfo.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    proc_pidinfo.restype = ctypes.c_int
    return proc_pidinfo


@lru_cache(maxsize=1)
def _darwin_proc_signal_with_audittoken() -> Any:
    try:
        library = ctypes.CDLL(None, use_errno=True)
        function = library.proc_signal_with_audittoken
    except (AttributeError, OSError) as exc:
        raise ValidationIssue(
            "isolation_supervision_unavailable",
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
            "isolation_supervision_identity_failed",
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
        "isolation_supervision_signal_failed",
        "Cannot signal Darwin process generation: "
        f"{os.strerror(result) if result > 0 else f'error {result}'}",
    )


def _darwin_process_record(pid: int, *, command: str = "") -> _ProcessRecord | None:
    """Return stable Darwin lifetime identity plus current signal token."""
    if sys.platform != "darwin":
        return None
    proc_pidinfo = _darwin_proc_pidinfo()
    info = _DarwinBsdInfoWithUniqueId()
    ctypes.set_errno(0)
    size = proc_pidinfo(
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
                "isolation_supervision_identity_failed",
                f"Darwin cannot inspect pid {pid}: {os.strerror(error_number)}",
            )
        return None
    if size < ctypes.sizeof(info) or int(info.pbsd.pbi_pid) != int(pid):
        raise ValidationIssue(
            "isolation_supervision_identity_failed",
            f"Darwin returned an incomplete process identity for pid {pid}",
        )
    unique_id = int(info.p_uniqidentifier.p_uniqueid)
    pid_version = int(info.p_uniqidentifier.p_idversion)
    return _ProcessRecord(
        pid=int(info.pbsd.pbi_pid),
        ppid=int(info.pbsd.pbi_ppid),
        pgid=int(info.pbsd.pbi_pgid),
        start_identity=(
            f"{int(info.pbsd.pbi_start_tvsec)}:"
            f"{int(info.pbsd.pbi_start_tvusec)}:{unique_id}"
        ),
        command=command,
        darwin_audit_token=_darwin_audit_token(pid, pid_version),
        zombie=int(info.pbsd.pbi_status) == 5,  # SZOMB
    )


def _require_darwin_generation_signaling() -> None:
    """Prove exact-generation signaling before any sandboxed worker launch."""
    if sys.platform != "darwin":
        return
    identity = _darwin_process_record(os.getpid())
    if identity is None or identity.darwin_audit_token is None:
        raise ValidationIssue(
            "isolation_supervision_unavailable",
            "Darwin cannot bind the host process to an audit token",
        )
    _darwin_signal_audit_token(identity.darwin_audit_token, signal.SIGCONT)


def _require_darwin_recursive_containment() -> None:
    """Fail closed until Darwin provides a qualified recursive boundary.

    Process groups do not contain ``setsid`` descendants, macOS kqueue does
    not support ``NOTE_TRACK``, and polling ancestry cannot close the interval
    between a fork and reparenting.  An environment-bearing ``ps`` scan is
    neither complete nor safe to use as a process authority.  External lanes
    that require this hard boundary therefore must not spawn on Darwin.
    """
    if sys.platform == "darwin":
        raise ValidationIssue(
            "isolation_recursive_containment_unavailable",
            "Darwin has no qualified recursive external-process boundary; "
            "continue the configured attempt chain or use a qualified "
            "isolated platform",
        )


def _require_linux_recursive_containment() -> None:
    """Fail closed until launch can atomically bind a Linux child generation.

    ``asyncio.create_subprocess_exec`` does not expose a pidfd returned by the
    same kernel operation that creates the child. Opening one afterwards races
    the child watcher: a short-lived child may already have been reaped and its
    numeric PID reused before ``pidfd_open`` runs. A bwrap PID namespace limits
    descendants, but it does not close that host-PID generation gap. External
    lanes therefore must not spawn through this launcher on Linux.
    """
    if sys.platform.startswith("linux"):
        raise ValidationIssue(
            "isolation_recursive_containment_unavailable",
            "Linux asyncio launch cannot atomically bind the bwrap child to a "
            "generation-safe process handle; continue the configured attempt "
            "chain or use a separate trusted full-run route",
        )


async def _darwin_marker_matches_identity(
    *,
    executable: str,
    pid: int,
    expected_start_identity: str,
    token_marker: str,
) -> bool:
    """Bind ps(1)'s environment view to one native Darwin process generation."""
    before = _darwin_process_record(pid)
    if before is None or before.start_identity != expected_start_identity:
        return False
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            executable,
            "-p",
            str(pid),
            "-o",
            "command=",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=2.0)
    except BaseException as exc:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.shield(proc.communicate())
            except BaseException:
                pass
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise ValidationIssue(
            "isolation_supervision_identity_failed",
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
        message = stderr.decode("utf-8", errors="replace").strip()
        raise ValidationIssue(
            "isolation_supervision_identity_failed",
            f"Darwin marker verification exited {proc.returncode}: {message[:160]}",
        )
    return token_marker in stdout.decode("utf-8", errors="replace")


@dataclass
class _DescendantSupervisor:
    """Host-owned macOS descendant tracker, including reparented sessions."""

    executable: str
    token: str
    root_pid: int
    known_pids: dict[int, _ProcessRecord]
    error: str | None = None
    root_absence_proven: bool = False

    async def scan(self) -> dict[int, _ProcessRecord]:
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                self.executable,
                "-axo",
                "pid=,ppid=,pgid=,command=",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        except BaseException as exc:
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.shield(proc.communicate())
                except BaseException:
                    pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            self.error = f"descendant_scan_failed:{type(exc).__name__}:{exc}"
            return {}
        if proc.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            self.error = f"descendant_scan_exit:{proc.returncode}:{message[:160]}"
            return {}
        records: dict[int, _ProcessRecord] = {}
        token_marker = f"ELVES_ISOLATION_MARKER={self.token}"
        for raw_line in stdout.decode("utf-8", errors="replace").splitlines():
            fields = raw_line.strip().split(None, 3)
            if len(fields) < 3:
                continue
            try:
                pid, ppid, pgid = (int(fields[index]) for index in range(3))
            except ValueError:
                continue
            command = fields[3] if len(fields) == 4 else ""
            try:
                native = _darwin_process_record(pid)
            except ValidationIssue as exc:
                if token_marker in command or pid in self.known_pids:
                    self.error = f"descendant_identity_failed:pid={pid}:{exc.message}"
                    return {}
                continue
            if native is None:
                # The process can exit between ps(1)'s snapshot and the native
                # identity read. In that case this generation is already absent.
                continue
            # ``proc_pidinfo`` is the identity authority. ps supplies only the
            # environment-bearing command needed to find reparented descendants.
            if token_marker in command:
                try:
                    marker_present = await _darwin_marker_matches_identity(
                        executable=self.executable,
                        pid=pid,
                        expected_start_identity=native.start_identity,
                        token_marker=token_marker,
                    )
                except ValidationIssue as exc:
                    self.error = f"descendant_identity_failed:pid={pid}:{exc.message}"
                    return {}
                if marker_present:
                    native = _ProcessRecord(
                        pid=native.pid,
                        ppid=native.ppid,
                        pgid=native.pgid,
                        start_identity=native.start_identity,
                        command=command,
                        darwin_audit_token=native.darwin_audit_token,
                        zombie=native.zombie,
                    )
            records[pid] = native

        # The opaque token survives setsid and ordinary double-fork reparenting.
        discovered = {
            record.pid for record in records.values() if token_marker in record.command
        }
        live_known = {
            pid
            for pid, identity in self.known_pids.items()
            if (record := records.get(pid)) is not None
            and record.start_identity == identity.start_identity
            and not record.zombie
        }
        # A process keeps its unique ID across exec while its PID version (and
        # therefore audit token) rotates. Refresh every still-matching known
        # generation so cleanup always signals with the current kernel token,
        # including leaders that removed the environment marker during exec.
        for pid in live_known:
            self.known_pids[pid] = records[pid]
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
            record = records[pid]
            # A reused numeric PID is a different process generation. Bind the
            # newly discovered marker/ancestry match to its native start identity
            # instead of ever carrying a bare PID forward.
            self.known_pids[pid] = record
        root = records.get(self.root_pid)
        self.root_absence_proven = bool(
            self.root_pid > 0
            and (
                root is None
                or self.root_pid not in self.known_pids
                or self.known_pids[self.root_pid].start_identity
                != root.start_identity
            )
        )
        self.error = None
        return records

    def alive_from_records(
        self,
        records: Mapping[int, _ProcessRecord],
    ) -> dict[int, _ProcessRecord]:
        return {
            pid: identity
            for pid, identity in self.known_pids.items()
            if (record := records.get(pid)) is not None
            and record.start_identity == identity.start_identity
            and not record.zombie
        }

    async def alive(self) -> dict[int, _ProcessRecord]:
        records = await self.scan()
        if self.error:
            return {}
        return self.alive_from_records(records)


async def _monitor_descendants(
    supervisor: _DescendantSupervisor,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set() and supervisor.error is None:
        await supervisor.scan()
        try:
            await asyncio.wait_for(stop.wait(), timeout=DESCENDANT_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def _wait_for_supervised_leader_exit(
    supervisor: _DescendantSupervisor,
    proc: asyncio.subprocess.Process,
) -> None:
    """Observe Darwin leader exit without depending on inherited-pipe EOF."""
    expected = supervisor.known_pids.get(supervisor.root_pid)
    if expected is None:
        if supervisor.root_absence_proven:
            # A very short-lived leader can exit before the first marker scan
            # binds its audit token.  The authoritative native scan proves that
            # numeric PID absent, while asyncio's child watcher remains the
            # authority for this particular Popen generation's exit.  Waiting
            # for returncode also prevents a live process that stripped its
            # marker from being mistaken for the vanished fast-leader case.
            while proc.returncode is None:
                await asyncio.sleep(PROCESS_GROUP_VERIFY_POLL_SECONDS)
            return
        raise ValidationIssue(
            "isolation_supervision_identity_failed",
            "Darwin external leader has no bound process generation",
        )
    while True:
        current = _darwin_process_record(supervisor.root_pid)
        if (
            current is None
            or current.zombie
            or current.start_identity != expected.start_identity
        ):
            return
        await asyncio.sleep(PROCESS_GROUP_VERIFY_POLL_SECONDS)


async def _terminate_supervised_descendants(
    supervisor: _DescendantSupervisor,
) -> dict[str, Any]:
    """Signal and prove absence of every supervised/reparented descendant."""
    initial_error = supervisor.error
    cleanup: dict[str, Any] = {
        "descendant_supervised": True,
        "descendant_sigterm_sent": False,
        "descendant_sigkill_sent": False,
        "descendants_absent": False,
        "supervised_pids": sorted(supervisor.known_pids),
        "identity_mismatches": [],
        "supervision_error": initial_error,
    }
    # A monitor failure is not permission to abandon already bound generations.
    # Retry authoritative discovery once, then use audit-token signaling for all
    # known generations even if the retry fails. Absence remains unproved in that
    # case because an unobserved marker-bearing descendant may exist.
    supervisor.error = None
    try:
        records = await supervisor.scan()
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        supervisor.error = (
            f"descendant_scan_failed:{type(exc).__name__}:{exc}"
        )
        records = {}
    authoritative = supervisor.error is None
    if authoritative:
        alive = supervisor.alive_from_records(records)
    else:
        alive = dict(supervisor.known_pids)
    targets = {
        pid: identity
        for pid, identity in alive.items()
        if pid != os.getpid()
    }
    cleanup["descendants_found"] = sorted(targets)

    def _signal_targets(pids: Mapping[int, _ProcessRecord], sig: int) -> bool:
        sent = False
        for pid in sorted(pids, reverse=True):
            identity = pids[pid]
            try:
                current = _darwin_process_record(pid)
            except ValidationIssue as exc:
                supervisor.error = f"descendant_identity_failed:pid={pid}:{exc.message}"
                continue
            if current is None:
                continue
            if current.start_identity != identity.start_identity:
                cleanup["identity_mismatches"].append(
                    {
                        "pid": pid,
                        "expected": identity.start_identity,
                        "observed": current.start_identity,
                    }
                )
                # A native start-identity mismatch proves the tracked generation
                # is gone. Never redirect a cleanup signal to the reused PID.
                continue
            try:
                sent = (
                    _darwin_signal_audit_token(current.darwin_audit_token, sig)
                    or sent
                )
            except ValidationIssue as exc:
                supervisor.error = f"descendant_signal_failed:pid={pid}:{exc.message}"
        return sent

    cleanup["descendant_sigterm_sent"] = _signal_targets(targets, signal.SIGTERM)
    for _ in range(8):
        await asyncio.sleep(PROCESS_GROUP_VERIFY_POLL_SECONDS)
        if not authoritative:
            break
        alive = await supervisor.alive()
        if supervisor.error:
            authoritative = False
            break
        if not alive:
            break
    if alive:
        cleanup["descendant_sigkill_sent"] = _signal_targets(alive, signal.SIGKILL)

    for _ in range(DESCENDANT_VERIFY_ATTEMPTS):
        if not authoritative:
            break
        alive = await supervisor.alive()
        if supervisor.error:
            authoritative = False
            break
        if not alive:
            cleanup["descendants_absent"] = True
            break
        _signal_targets(alive, signal.SIGKILL)
        cleanup["descendant_sigkill_sent"] = True
        await asyncio.sleep(PROCESS_GROUP_VERIFY_POLL_SECONDS)
    if not authoritative:
        # Best-effort cleanup of every generation learned before discovery failed.
        _signal_targets(
            {
                pid: identity
                for pid, identity in supervisor.known_pids.items()
                if pid != os.getpid()
            },
            signal.SIGKILL,
        )
        cleanup["descendant_sigkill_sent"] = bool(supervisor.known_pids)
    cleanup["supervised_pids"] = sorted(supervisor.known_pids)
    cleanup["supervision_error"] = supervisor.error or (
        initial_error if not authoritative else None
    )
    return cleanup


def _linux_process_group_states(pgid: int) -> list[str] | None:
    """Return Linux member states, treating zombies as inert containment residue."""
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    states: list[str] = []
    try:
        entries = tuple(proc_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8")
            close_paren = raw.rfind(")")
            fields = raw[close_paren + 2 :].split()
            state = fields[0]
            process_group = int(fields[2])
        except (OSError, ValueError, IndexError):
            continue
        if process_group == pgid:
            states.append(state)
    return states


def pgid_alive(pgid: int) -> bool:
    """Return whether a process group has any executable (non-zombie) member."""
    linux_states = _linux_process_group_states(pgid)
    if linux_states:
        return any(state not in {"Z", "X", "x"} for state in linux_states)
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but is not signalable as us; treat it as still present.
        return True
    except OSError:
        return False


async def wait_for_process_group_settle(
    pgid: int,
    *,
    timeout: float = PROCESS_GROUP_SETTLE_SECONDS,
) -> bool:
    """Allow bwrap/init helpers a bounded natural-reap window after leader exit."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while pgid_alive(pgid):
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(PROCESS_GROUP_VERIFY_POLL_SECONDS)
    return True


async def terminate_process_group(
    proc: asyncio.subprocess.Process,
    *,
    grace_seconds: float = PROCESS_GROUP_GRACE_SECONDS,
    known_pgid: int | None = None,
    supervisor: _DescendantSupervisor | None = None,
) -> dict[str, Any]:
    """Terminate an entire external lane process group and verify absence."""
    cleanup: dict[str, Any] = {
        "signaled_group": False,
        "sigterm_sent": False,
        "sigkill_sent": False,
        "reaped": False,
        "group_absent": False,
        "pid": proc.pid,
        "pgid": known_pgid,
        "error": None,
    }

    def _record_error(message: str) -> None:
        cleanup["error"] = (
            f"{cleanup['error']};{message}" if cleanup.get("error") else message
        )

    if sys.platform == "darwin":
        # killpg(2) accepts only a numeric PGID. Once asyncio has reaped the
        # leader, that PGID can be reused. All launched Darwin lanes therefore
        # use audit tokens; the compatibility path is observation-only.
        if supervisor is None:
            pgid = known_pgid
            if proc.returncode is None:
                cleanup["error"] = "darwin_generation_supervisor_required"
                return cleanup
            try:
                await asyncio.wait_for(
                    proc.wait(),
                    timeout=max(grace_seconds, PROCESS_GROUP_VERIFY_POLL_SECONDS),
                )
                cleanup["reaped"] = True
            except (
                asyncio.TimeoutError,
                ProcessLookupError,
                ChildProcessError,
            ) as exc:
                cleanup["error"] = f"darwin_reap_failed:{type(exc).__name__}"
            cleanup["group_absent"] = bool(
                cleanup["reaped"]
                and (pgid is None or not pgid_alive(pgid))
            )
            if not cleanup["group_absent"] and cleanup.get("error") is None:
                cleanup["error"] = "darwin_process_group_absence_unproved"
            return cleanup
        descendants = await _terminate_supervised_descendants(supervisor)
        try:
            await asyncio.wait_for(
                proc.wait(),
                timeout=max(grace_seconds, PROCESS_GROUP_VERIFY_POLL_SECONDS),
            )
            cleanup["reaped"] = True
        except (asyncio.TimeoutError, ProcessLookupError) as exc:
            cleanup["error"] = f"darwin_reap_failed:{type(exc).__name__}"
        cleanup.update(descendants)
        cleanup["sigterm_sent"] = bool(
            descendants.get("descendant_sigterm_sent")
        )
        cleanup["sigkill_sent"] = bool(
            descendants.get("descendant_sigkill_sent")
        )
        cleanup["group_absent"] = bool(
            cleanup["reaped"]
            and descendants.get("descendants_absent")
            and not descendants.get("supervision_error")
        )
        if not cleanup["group_absent"] and cleanup.get("error") is None:
            cleanup["error"] = "darwin_generation_cleanup_unproved"
        return cleanup

    # No generic process-group operation is generation-bound. External Linux
    # launches are blocked before spawn, and this defensive path never touches
    # a numeric PID or PGID if an internal caller bypasses that gate.
    _record_error("generation_bound_process_boundary_required")
    return cleanup


@dataclass
class ExternalLaunchPlan:
    argv: list[str]
    cwd: str
    env: dict[str, str]
    isolated: IsolatedLane | None
    isolation_meta: dict[str, Any]
    # Compatibility name: true means this external attempt was skipped and the
    # configured attempt chain should continue. It does not prove native ran.
    fallback_host_native: bool
    invocation: AdapterInvocation | None
    stdin_bytes: bytes | None

    @property
    def external_attempt_skipped(self) -> bool:
        """Truthful name for the retained compatibility storage field."""
        return self.fallback_host_native


def _require_qualified_process_boundary(plan: ExternalLaunchPlan) -> str:
    """Return the proven recursive process boundary or fail before launch."""
    if sys.platform == "darwin":
        _require_darwin_recursive_containment()
        return "host-supervised"  # pragma: no cover - gate currently fails closed

    if sys.platform.startswith("linux"):
        _require_linux_recursive_containment()
        return "pid-namespace"  # pragma: no cover - gate currently fails closed

    raise ValidationIssue(
        "isolation_recursive_containment_unavailable",
        f"No qualified recursive external-process boundary on {sys.platform}",
    )


def prepare_external_launch(
    *,
    spec: LaneSpec,
    attempt: EffectiveAttempt,
    attempt_index: int,
    repo_root: Path,
    packet_path: Path,
    prompt_path: Path,
    packet_dict: Mapping[str, Any],
    redacted_task: str,
    exact_secret_values: frozenset[str],
    grants: Sequence[str],
    scrub_env: Mapping[str, str],
    command_override: tuple[str, ...] | None,
    parent_env: Mapping[str, str] | None,
) -> ExternalLaunchPlan:
    """Build isolated launch plan. Isolation happens before argv construction."""
    isolation_required = bool(spec.required) or bool(attempt.required)
    # A command override still launches a subprocess and receives the same
    # production isolation boundary. There is no public unsafe bypass.
    use_isolation = attempt.adapter != "host-native" or command_override is not None
    isolated: IsolatedLane | None = None
    isolation_meta: dict[str, Any] = {"enabled": False}
    launch_repo = Path(repo_root)

    def _skip_external_attempt(reason: str) -> ExternalLaunchPlan:
        return ExternalLaunchPlan(
            argv=[],
            cwd=str(repo_root),
            env=dict(scrub_env),
            isolated=None,
            isolation_meta={
                "enabled": False,
                "external_attempt": "skipped",
                "fallback_chain": "continue",
                "reason": reason,
            },
            fallback_host_native=True,
            invocation=None,
            stdin_bytes=None,
        )

    if use_isolation:
        try:
            recursive_gate = (
                _require_darwin_recursive_containment
                if sys.platform == "darwin"
                else (
                    _require_linux_recursive_containment
                    if sys.platform.startswith("linux")
                    else None
                )
            )
            if recursive_gate is not None:
                try:
                    recursive_gate()
                except ValidationIssue as exc:
                    if isolation_required:
                        raise
                    return _skip_external_attempt(f"{exc.code}: {exc.message}")
            backend = resolve_fs_sandbox_backend()
            # A tracked snapshot alone cannot prevent absolute host/sibling reads.
            # Required routes block; optional routes skip this external attempt.
            if backend is None:
                reason = filesystem_sandbox_unavailable_message(
                    platform_name=sys.platform,
                )
                if isolation_required:
                    raise ValidationIssue(
                        "isolation_sandbox_unavailable",
                        filesystem_sandbox_unavailable_message(
                            platform_name=sys.platform,
                            required=True,
                        ),
                    )
                return _skip_external_attempt(reason)
            isolated = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=Path(repo_root),
                    lane_id=str(spec.lane_id),
                    include_instructions_as_data=spec.include_instructions_as_data,
                    credential_grants={
                        name: scrub_env[name]
                        for name in grants
                        if name in scrub_env and scrub_env[name]
                    },
                    base_env={
                        "PATH": scrub_env.get("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
                    },
                    # Every real external launch gets the OS boundary. Required
                    # controls fail-closed versus continuing the attempt chain.
                    require_fs_sandbox=True,
                    qualified_backend=backend,
                )
            )
            launch_repo = isolated.snapshot
            isolation_meta = {
                "enabled": True,
                "snapshot": str(isolated.snapshot),
                "sandbox_backend": isolated.sandbox_backend,
                "process_containment": isolated.process_containment,
                "instruction_data_files": list(isolated.instruction_data_files),
            }
        except Exception as exc:  # noqa: BLE001
            if isolated is not None:
                isolated.cleanup()
                isolated = None
            if isolation_required:
                raise ValidationIssue(
                    "required_isolation_failed",
                    f"Required isolation failed: {type(exc).__name__}: {exc}; "
                    "refusing repo-root external launch",
                ) from exc
            # Optional setup failures skip this attempt so the configured chain
            # can continue; they never launch in the original repository.
            return _skip_external_attempt(f"{type(exc).__name__}: {exc}")

    # Any error after snapshot creation but before ownership passes to the
    # launch plan must clean the disposable tree here.
    try:
        launch_packet_path = packet_path
        launch_prompt_path = prompt_path
        if isolated is not None:
            launch_packet_path, launch_prompt_path = copy_isolated_transport_inputs(
                isolated,
                packet_path=packet_path,
                prompt_path=prompt_path,
            )

        defaults = ADAPTER_CONTRACT_PAIRS.get(
            attempt.adapter, ("json-stdio", "custom-json-envelope")
        )
        attempt_input_contract = (attempt.input_contract or defaults[0]).strip()
        attempt_output_contract = (attempt.output_contract or defaults[1]).strip()
        if attempt_output_contract == "json-role-report":
            attempt_output_contract = "custom-json-envelope"

        validate_extra_args(attempt.adapter, attempt.extra_args)
        if command_override is None:
            validate_adapter_contract_pair(
                attempt.adapter,
                input_contract=attempt_input_contract,
                output_contract=attempt_output_contract,
            )

        attempt_session = session_id_for_attempt(spec, attempt)
        if command_override is not None and attempt_index == 0:
            command = list(command_override)
            invocation = AdapterInvocation(
                adapter=attempt.adapter,
                executable=command[0] if command else "",
                argv=tuple(command),
                read_only=True,
                notes="command_override",
                input_mode="none",
                decoder=default_decoder_for_adapter(attempt.adapter)
                if attempt.adapter != "custom-cli"
                else "custom-json-envelope",
                cwd=str(launch_repo),
                session_id=attempt_session,
            )
        else:
            invocation = build_readonly_invocation(
                adapter=attempt.adapter,
                profile=attempt.profile,
                executable=attempt.executable,
                packet_path=launch_packet_path,
                prompt_path=launch_prompt_path,
                requested_model=attempt.requested_model,
                extra_args=attempt.extra_args,
                packet=dict(packet_dict),
                task=redacted_task,
                role=spec.role,
                input_contract=attempt_input_contract,
                output_contract=attempt_output_contract,
                repo_root=launch_repo,
                session_id=attempt_session,
                cwd=str(launch_repo),
            )
            command = list(invocation.argv)

        if invocation.unavailable:
            raise ValidationIssue(
                "adapter_unavailable",
                invocation.unavailable_reason or "adapter unavailable",
            )
        if not command:
            raise ValidationIssue("empty_command", "empty command")

        if isolated is not None:
            # Grok reads its full prompt from a file. Put the final body at the
            # already-sandboxed path before the read-only mount is launched.
            if invocation.prompt_file_body is not None:
                launch_prompt_path.write_text(
                    redact_text(
                        invocation.prompt_file_body,
                        exact_values=exact_secret_values,
                    ).text,
                    encoding="utf-8",
                )
                launch_prompt_path.chmod(0o600)
            command = rewrite_argv_repo_paths(
                command, original_repo=Path(repo_root), snapshot=isolated.snapshot
            )
            command_executable = Path(command[0]).expanduser()
            if command_executable.is_absolute() and not command_executable.is_file():
                raise ValidationIssue(
                    "launch_executable_not_found",
                    f"Launch executable not found inside isolation boundary: {command[0]}",
                    path=str(command_executable),
                )
            if isolated.sandbox_backend:
                command = wrap_argv_with_sandbox(command, isolated)
            child_env = dict(isolated.env)
            for key in ("PATH", "LANG", "LC_ALL", "TERM"):
                if key in scrub_env and key not in child_env:
                    child_env[key] = scrub_env[key]
            child_cwd = str(isolated.snapshot)
        else:
            child_env = dict(scrub_env)
            child_cwd = str(invocation.cwd or repo_root)

        stdin_bytes = None
        if invocation.stdin_text is not None:
            stdin_bytes = redact_text(
                invocation.stdin_text, exact_values=exact_secret_values
            ).text.encode("utf-8")

        return ExternalLaunchPlan(
            argv=command,
            cwd=child_cwd,
            env=child_env,
            isolated=isolated,
            isolation_meta=isolation_meta,
            fallback_host_native=False,
            invocation=invocation,
            stdin_bytes=stdin_bytes,
        )
    except BaseException:
        if isolated is not None:
            isolated.cleanup()
        raise


async def run_external_subprocess(
    *,
    plan: ExternalLaunchPlan,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Launch an external process and always clean up its isolation boundary."""
    isolated = plan.isolated

    def _cleanup() -> dict[str, Any]:
        meta = {"isolation_cleaned": True}
        if isolated is not None:
            root = isolated.root
            try:
                isolated.cleanup()
            except Exception as exc:  # noqa: BLE001
                meta["isolation_cleanup_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
            meta["isolation_cleaned"] = not root.exists() and not root.is_symlink()
            meta["isolation_root"] = str(root)
        return meta

    def _cleanup_proven(meta: Mapping[str, Any]) -> bool:
        return bool(
            meta.get("isolation_cleaned")
            and not meta.get("isolation_cleanup_error")
        )

    def _cleanup_failure_reason(meta: Mapping[str, Any]) -> str:
        return str(
            meta.get("isolation_cleanup_error")
            or "isolation residue remains"
        )

    def _finalize(result: dict[str, Any]) -> dict[str, Any]:
        cleanup = result.setdefault("cleanup", {})
        cleanup.update(_cleanup())
        if not _cleanup_proven(cleanup):
            reason = _cleanup_failure_reason(cleanup)
            result.update(
                {
                    "ok": False,
                    "failure_class": "isolation_failure",
                    "reason": f"isolation_cleanup_failed: {reason}",
                }
            )
        return result

    try:
        process_boundary = _require_qualified_process_boundary(plan)
    except ValidationIssue as exc:
        return _finalize(
            {
                "ok": False,
                "failure_class": "isolation_failure",
                "reason": f"{exc.code}: {exc.message}",
                "cleanup": {"descendants_absent": False},
                "process_launched": False,
            }
        )
    needs_descendant_supervision = process_boundary == "host-supervised"
    supervisor_executable: str | None = None
    supervision_token: str | None = None
    if needs_descendant_supervision:
        if isolated is not None and isolated.sandbox_backend == "sandbox-exec":
            supervisor_executable = isolated.supervisor_executable
            supervision_token = isolated.supervision_token
        else:
            supervisor_executable = "/bin/ps"
            supervision_token = secrets.token_hex(24)
    if needs_descendant_supervision and (
        not supervisor_executable
        or not supervision_token
        or not Path(supervisor_executable).is_file()
        or not os.access(supervisor_executable, os.X_OK)
    ):
        return _finalize(
            {
                "ok": False,
                "failure_class": "isolation_failure",
                "reason": "qualified macOS descendant supervision unavailable",
                "cleanup": {"descendants_absent": False},
                "process_launched": False,
            }
        )
    if needs_descendant_supervision:
        try:
            _require_darwin_generation_signaling()
        except ValidationIssue as exc:
            return _finalize(
                {
                    "ok": False,
                    "failure_class": "isolation_failure",
                    "reason": exc.message,
                    "cleanup": {"descendants_absent": False},
                    "process_launched": False,
                }
            )

    launch_env = dict(plan.env)
    if supervision_token is not None:
        launch_env["ELVES_ISOLATION_MARKER"] = supervision_token

    def _new_supervisor(root_pid: int) -> _DescendantSupervisor:
        if supervisor_executable is None or supervision_token is None:
            raise ValidationIssue(
                "isolation_supervision_unavailable",
                "Darwin descendant supervision was not configured",
            )
        return _DescendantSupervisor(
            executable=supervisor_executable,
            token=supervision_token,
            root_pid=root_pid,
            known_pids={},
        )

    # Allocate every host-owned containment object before launch. Once a process
    # handle exists, setup only binds this object to the returned PID and scans.
    prelaunch_supervisor = (
        _new_supervisor(0) if needs_descendant_supervision else None
    )

    def _bind_supervisor_root(
        supervisor: _DescendantSupervisor,
        process: asyncio.subprocess.Process,
    ) -> None:
        root_pid = process.pid
        supervisor.root_pid = root_pid
        supervisor.root_absence_proven = False
        if process.returncode is not None:
            supervisor.root_absence_proven = True
            return
        # Bind the direct child to its native generation before the next await.
        # This closes the gap in which the child can exec with a scrubbed
        # environment before the marker-bearing ps scan.  asyncio cannot run
        # its reap callback and recycle this child PID while this task retains
        # the event loop, so a returned record belongs to this Popen generation.
        root = _darwin_process_record(root_pid)
        if root is None:
            # The child won the exit race before it could be bound.  The wait
            # path still requires this exact Process handle's returncode.
            supervisor.root_absence_proven = True
            return
        supervisor.known_pids[root_pid] = root

    proc: asyncio.subprocess.Process | None = None
    launched_pgid: int | None = None
    supervisor = prelaunch_supervisor
    monitor_stop: asyncio.Event | None = None
    monitor_task: asyncio.Task[None] | None = None

    async def _stop_monitor() -> None:
        if monitor_stop is not None:
            monitor_stop.set()
        if monitor_task is not None:
            await asyncio.shield(monitor_task)

    async def _contain_processes(*, force_group: bool) -> dict[str, Any]:
        if proc is None:
            raise ValidationIssue(
                "isolation_cleanup_failed",
                "External process handle is unavailable for containment",
            )
        if supervisor is not None:
            await _stop_monitor()
            group = await terminate_process_group(
                proc,
                known_pgid=launched_pgid,
                supervisor=supervisor,
            )
            group["pid_namespace_teardown"] = False
            return group

        if process_boundary == "pid-namespace" and proc.returncode is not None:
            # The reaped outer bwrap process was PID 1 for the isolated PID
            # namespace. Its exit is the namespace teardown proof; probing or
            # signaling the old host PGID after reap would target a reusable
            # numeric identity.
            await _stop_monitor()
            return {
                "pid": proc.pid,
                "pgid": launched_pgid,
                "reaped": True,
                "group_absent": True,
                "error": None,
                "signaled_group": False,
                "sigterm_sent": False,
                "sigkill_sent": False,
                "settled_without_signal": True,
                "descendant_supervised": False,
                "descendants_absent": True,
                "descendants_found": [],
                "pid_namespace_teardown": True,
            }

        group = await terminate_process_group(
            proc,
            known_pgid=launched_pgid,
        )
        await _stop_monitor()
        pid_namespace_teardown = bool(
            process_boundary == "pid-namespace"
            and group.get("reaped")
            and group.get("group_absent")
            and not group.get("error")
        )
        descendants: dict[str, Any] = {
            "descendant_supervised": False,
            "descendants_absent": pid_namespace_teardown,
            "descendants_found": [],
        }
        group.update(descendants)
        group["pid_namespace_teardown"] = pid_namespace_teardown
        return group

    def _containment_proven(cleanup: Mapping[str, Any] | None) -> bool:
        return bool(
            cleanup
            and cleanup.get("group_absent")
            and cleanup.get("descendants_absent")
            and not cleanup.get("supervision_error")
            and not cleanup.get("error")
        )

    launch_coro: Any = None
    try:
        launch_coro = asyncio.create_subprocess_exec(
            *plan.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=(
                asyncio.subprocess.PIPE if plan.stdin_bytes is not None else None
            ),
            env=launch_env,
            cwd=plan.cwd,
            start_new_session=True,
        )
        launch_task = asyncio.create_task(launch_coro)
    except BaseException:
        if launch_coro is not None:
            launch_coro.close()
        cleanup_meta = _cleanup()
        if not _cleanup_proven(cleanup_meta):
            raise ValidationIssue(
                "isolation_cleanup_failed",
                _cleanup_failure_reason(cleanup_meta),
            )
        raise
    try:
        # Shield the launch so cancellation cannot lose the process handle in
        # the narrow fork/exec window. If the caller cancels, finish acquiring
        # the handle, terminate the containment root, then remove the snapshot.
        proc = await asyncio.shield(launch_task)
    except asyncio.CancelledError as cancelled:
        try:
            proc = await asyncio.shield(launch_task)
        except BaseException:
            cleanup_meta = _cleanup()
            if not _cleanup_proven(cleanup_meta):
                raise ValidationIssue(
                    "isolation_cleanup_failed",
                    _cleanup_failure_reason(cleanup_meta),
                )
            raise cancelled
        if process_boundary == "pid-namespace":
            launched_pgid = None
        else:
            try:
                launched_pgid = (
                    os.getpgid(proc.pid) if proc.pid is not None else None
                )
            except OSError:
                launched_pgid = None
        supervisor = prelaunch_supervisor
        if supervisor is not None:
            try:
                _bind_supervisor_root(supervisor, proc)
                await asyncio.shield(supervisor.scan())
            except BaseException as exc:
                supervisor.error = (
                    f"descendant_setup_failed:{type(exc).__name__}:{exc}"
                )
        try:
            group_cleanup = await asyncio.shield(
                _contain_processes(force_group=True)
            )
        except BaseException as containment_error:
            group_cleanup = {
                "group_absent": False,
                "descendants_absent": False,
                "error": f"cancellation_cleanup_failed:{type(containment_error).__name__}",
            }
        if not _containment_proven(group_cleanup):
            try:
                group_cleanup = await asyncio.shield(
                    _contain_processes(force_group=True)
                )
            except BaseException as containment_error:
                group_cleanup = {
                    "group_absent": False,
                    "descendants_absent": False,
                    "error": (
                        "cancellation_cleanup_retry_failed:"
                        f"{type(containment_error).__name__}"
                    ),
                }
        containment_ok = _containment_proven(group_cleanup)
        cleanup_meta = _cleanup()
        cleanup_ok = _cleanup_proven(cleanup_meta)
        if not containment_ok or not cleanup_ok:
            raise ValidationIssue(
                "isolation_cancellation_cleanup_failed",
                "Cancellation could not prove process and filesystem cleanup",
            )
        raise
    except FileNotFoundError as exc:
        return _finalize({
            "ok": False,
            "failure_class": "launch_error",
            "reason": f"executable not found: {exc}",
            "cleanup": {},
            "process_launched": False,
        })
    except OSError as exc:
        return _finalize({
            "ok": False,
            "failure_class": "launch_error",
            "reason": f"launch error: {exc}",
            "cleanup": {},
            "process_launched": False,
        })
    except BaseException:
        cleanup_meta = _cleanup()
        if not _cleanup_proven(cleanup_meta):
            raise ValidationIssue(
                "isolation_cleanup_failed",
                _cleanup_failure_reason(cleanup_meta),
            )
        raise

    timed_out = False
    cleanup: dict[str, Any] = {"pgid": None}
    stdout_b = b""
    stderr_b = b""
    try:
        if process_boundary == "pid-namespace":
            launched_pgid = None
        else:
            try:
                launched_pgid = (
                    os.getpgid(proc.pid) if proc.pid is not None else None
                )
            except OSError:
                launched_pgid = None
        cleanup["pgid"] = launched_pgid
        if supervisor is not None:
            _bind_supervisor_root(supervisor, proc)
            await supervisor.scan()
            monitor_stop = asyncio.Event()
            monitor_coro = _monitor_descendants(supervisor, monitor_stop)
            try:
                monitor_task = asyncio.create_task(monitor_coro)
            except BaseException:
                monitor_coro.close()
                raise
    except BaseException as setup_error:
        if monitor_stop is not None:
            monitor_stop.set()
        if monitor_task is not None:
            try:
                await asyncio.shield(monitor_task)
            except BaseException:
                pass
        group_cleanup: dict[str, Any]
        try:
            group_cleanup = await asyncio.shield(
                _contain_processes(force_group=True)
            )
        except BaseException as cleanup_error:
            group_cleanup = {
                "group_absent": False,
                "descendants_absent": False,
                "error": f"setup_cleanup_failed:{type(cleanup_error).__name__}",
            }
        cleanup_meta = _cleanup()
        containment_ok = _containment_proven(group_cleanup)
        cleanup_ok = _cleanup_proven(cleanup_meta)
        if not containment_ok or not cleanup_ok:
            raise ValidationIssue(
                "isolation_setup_cleanup_failed",
                "Post-launch setup failed and process/filesystem absence "
                "could not be proved",
            ) from setup_error
        raise

    result: dict[str, Any]
    communication_task: asyncio.Task[tuple[bytes, bytes]] | None = None
    containment_finalized = False
    try:
        runtime_error: Exception | None = None
        communication_coro = proc.communicate(input=plan.stdin_bytes)
        try:
            communication_task = asyncio.create_task(communication_coro)
        except BaseException:
            communication_coro.close()
            raise
        try:
            # communicate() drains concurrently so a chatty leader cannot block;
            # native Darwin identity observes exit independently of pipe EOF.
            await asyncio.wait_for(
                (
                    _wait_for_supervised_leader_exit(supervisor, proc)
                    if supervisor is not None
                    else proc.wait()
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            timed_out = True
            cleanup = await _contain_processes(force_group=True)
        except asyncio.CancelledError:
            cleanup = await asyncio.shield(_contain_processes(force_group=True))
            containment_ok = _containment_proven(cleanup)
            if not containment_ok:
                raise ValidationIssue(
                    "isolation_cancellation_cleanup_failed",
                    "Cancellation could not prove process cleanup",
                )
            containment_finalized = True
            cleanup_meta = _cleanup()
            cleanup_ok = _cleanup_proven(cleanup_meta)
            if not cleanup_ok:
                raise ValidationIssue(
                    "isolation_cancellation_cleanup_failed",
                    "Cancellation could not prove process and filesystem cleanup",
                )
            raise
        except Exception as exc:  # noqa: BLE001
            cleanup = await _contain_processes(force_group=True)
            runtime_error = exc
        else:
            cleanup = await _contain_processes(force_group=False)

        containment_finalized = _containment_proven(cleanup)

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                communication_task,
                timeout=POST_CONTAINMENT_DRAIN_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            runtime_error = runtime_error or exc
            stdout_b, stderr_b = b"", b""

        stdout_raw = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr_raw = (stderr_b or b"").decode("utf-8", errors="replace")
        containment_failed = (
            not cleanup.get("group_absent", False)
            or not cleanup.get("descendants_absent", False)
            or bool(cleanup.get("supervision_error"))
            or bool(cleanup.get("error"))
        )
        if containment_failed:
            result = {
                "ok": False,
                "failure_class": "isolation_failure",
                "reason": "descendant containment could not prove absence",
                "cleanup": cleanup,
                "process_launched": True,
                "exit_code": proc.returncode,
                "timeout": timed_out,
                "stdout_raw": stdout_raw,
                "stderr_raw": stderr_raw,
            }
        elif runtime_error is not None:
            result = {
                "ok": False,
                "failure_class": "execution_failure",
                "reason": (
                    "execution_runtime_error: "
                    f"{type(runtime_error).__name__}: {runtime_error}"
                ),
                "cleanup": cleanup,
                "process_launched": True,
                "exit_code": proc.returncode,
                "stdout_raw": stdout_raw,
                "stderr_raw": stderr_raw,
            }
        else:
            descendants_found = bool(cleanup.get("descendants_found"))
            if timed_out:
                result = {
                    "ok": False,
                    "failure_class": "timeout",
                    "reason": f"timeout after {timeout_seconds}s",
                    "cleanup": cleanup,
                    "process_launched": True,
                    "exit_code": proc.returncode,
                    "timeout": True,
                    "stdout_raw": stdout_raw,
                    "stderr_raw": stderr_raw,
                }
            elif descendants_found or cleanup.get("sigterm_sent") or cleanup.get("sigkill_sent"):
                result = {
                    "ok": False,
                    "failure_class": "execution_failure",
                    "reason": "external leader exited with live descendants",
                    "cleanup": cleanup,
                    "process_launched": True,
                    "exit_code": proc.returncode,
                    "stdout_raw": stdout_raw,
                    "stderr_raw": stderr_raw,
                }
            else:
                result = {
                    "ok": True,
                    "process_launched": True,
                    "exit_code": proc.returncode,
                    "stdout_raw": stdout_raw,
                    "stderr_raw": stderr_raw,
                    "cleanup": cleanup,
                    "timeout": False,
                }
        return _finalize(result)
    except BaseException as original_error:
        # Every exceptional path stops the monitor, contains the process, and
        # removes disk. The retry is intentionally idempotent.
        # The leader may already be reaped while marker-bound detached children
        # remain alive, so containment is required regardless of returncode.
        if communication_task is not None:
            if not communication_task.done():
                communication_task.cancel()
            try:
                await asyncio.gather(communication_task, return_exceptions=True)
            except BaseException:
                pass
        retry_cleanup: dict[str, Any] | None = None
        retry_error: BaseException | None = None
        if not containment_finalized:
            try:
                retry_cleanup = await asyncio.shield(
                    _contain_processes(force_group=True)
                )
            except BaseException as exc:  # cleanup proof is checked below
                retry_error = exc
        cleanup_meta = _cleanup()
        containment_ok = containment_finalized or (
            retry_error is None and _containment_proven(retry_cleanup)
        )
        cleanup_ok = _cleanup_proven(cleanup_meta)
        if not containment_ok or not cleanup_ok:
            code = (
                "isolation_cancellation_cleanup_failed"
                if isinstance(original_error, asyncio.CancelledError)
                else "isolation_cleanup_failed"
            )
            reason_bits = []
            if retry_error is not None:
                reason_bits.append(
                    f"containment retry failed: {type(retry_error).__name__}"
                )
            if retry_cleanup is not None and not _containment_proven(retry_cleanup):
                reason_bits.append("process absence remained unproved")
            if not cleanup_ok:
                reason_bits.append(
                    str(
                        cleanup_meta.get("isolation_cleanup_error")
                        or "process-handle or filesystem residue remains"
                    )
                )
            raise ValidationIssue(
                code,
                "; ".join(reason_bits) or "containment cleanup remained unproved",
            ) from (retry_error or original_error)
        raise
