"""Full-run supervisor product-boundary tests (no live provider)."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import io
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CLI = SCRIPTS / "cobbler_agents.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime import full_run as full_run_module  # noqa: E402
from cobbler_runtime import provider_auth as provider_auth_module
from cobbler_runtime.behavior_policy import (  # noqa: E402
    FORBIDDEN_FULL_RUN_WAKE_TRIGGERS,
    PARKED_MONITOR_UPDATE_POLICY,
    PARKED_MONITOR_WAKE_CONDITIONS,
    parked_monitor_poll_after_seconds,
    resolve_from_signals,
    resolve_scenario,
)
from cobbler_runtime.full_run import (  # noqa: E402
    await_full_run,
    build_worker_confidence_review_context,
    build_full_run_argv,
    build_full_run_env,
    capture_fingerprint,
    full_run_root,
    launch_full_run,
    load_state,
    logs_full_run,
    monitor_full_run,
    prepare_full_run,
    reconcile_full_run_with_git,
    reconstruct_missing_report,
    stop_full_run,
    validate_event,
    validate_run_report,
    verify_fingerprint,
    write_report,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402
from cobbler_runtime.storage import StorageError, digest_key  # noqa: E402
from cobbler_runtime.worker_routing import (  # noqa: E402
    GrokCapabilities,
    GrokCapabilityEvidence,
)


FAKE_WORKER = r'''#!/usr/bin/env python3
"""Explicit fixture multi-batch worker (adapter=fixture only)."""
import json, os, time
from datetime import datetime, timezone
from pathlib import Path

def utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

session = os.environ["ELVES_FULL_RUN_SESSION"]
events = Path(os.environ["ELVES_FULL_RUN_EVENTS"])
report = Path(os.environ["ELVES_FULL_RUN_REPORT"])
branch = os.environ.get("ELVES_FULL_RUN_BRANCH", "feature")
head = os.environ.get("ELVES_FULL_RUN_START_HEAD", "deadbeef")
transcript = Path(os.environ["ELVES_FULL_RUN_TRANSCRIPT"])

def emit(etype, batch, summary, **extra):
    row = {
        "timestamp": utc(),
        "session_id": session,
        "branch": branch,
        "head": head,
        "batch": batch,
        "type": etype,
        "summary": summary,
    }
    row.update(extra)
    with events.open("a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    with transcript.open("a") as f:
        f.write(summary + "\n")

emit("run_started", 0, "fake worker started")
batches = []
commits = []
acceptance = []
for batch in (1, 2, 3):
    emit("batch_started", batch, f"batch {batch} started")
    time.sleep(0.05)
    head = f"{batch:040x}"
    emit("commit_pushed", batch, f"batch {batch} commit", head=head)
    emit("gate_result", batch, f"batch {batch} gates ok")
    emit("batch_complete", batch, f"batch {batch} complete", head=head)
    batches.append({
        "id": f"batch-{batch}",
        "status": "complete",
        "evidence": f"focused gates passed at {head}",
    })
    commits.append(head)
    acceptance.append({
        "id": f"B{batch}-A1",
        "criterion": f"batch {batch} complete",
        "met": True,
        "evidence": f"commit {head}",
    })
    emit("heartbeat", batch, f"heartbeat after batch {batch}", head=head)

report.write_text(json.dumps({
    "run_id": os.environ["ELVES_FULL_RUN_RUN_ID"],
    "attempt": int(os.environ["ELVES_FULL_RUN_ATTEMPT"]),
    "session_id": session,
    "branch": branch,
    "start_head": os.environ.get("ELVES_FULL_RUN_START_HEAD", "deadbeef"),
    "final_head": head,
    "status": "complete",
    "batches": batches,
    "acceptance": acceptance,
    "commits": commits,
    "blockers": [],
    "merge_authority": False,
}, indent=2) + "\n")
emit("run_complete", 3, "fake multi-batch run complete", head=head)
'''


def _proven_test_grok_capabilities() -> GrokCapabilities:
    """Capability result for provider-lifecycle tests that use a synthetic binary."""
    proven = GrokCapabilityEvidence("proven", "test_fixture", "advertised_by_help")
    return GrokCapabilities(
        installed=True,
        authenticated=True,
        models=("grok-4.5",),
        default_model="grok-4.5",
        capability_ledger=tuple(
            (name, proven)
            for name in (
                "prompt_file",
                "cwd",
                "model",
                "permission_mode",
                "always_approve",
                "reasoning_effort",
                "max_turns",
                "output_format",
                "session_id",
                "resume",
                "streaming_json",
                "check",
            )
        ),
    )

FAKE_DEVIN = r'''#!/usr/bin/env python3
"""Fake Devin CLI fixture: supports `list --format json` and prompt-file runs."""
import json, os, subprocess, sys, time
from pathlib import Path

def utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

args = sys.argv[1:]
if args[:2] == ["list", "--format"] and len(args) >= 3 and args[2] == "json":
    cwd = str(Path.cwd().resolve())
    print(json.dumps([{
        "id": "devin-sess-123",
        "working_directory": cwd,
        "last_activity_at": int(time.time()),
    }], separators=(",", ":")))
    raise SystemExit(0)

prompt_file = None
export_path = None
for i, arg in enumerate(args):
    if arg == "--prompt-file" and i + 1 < len(args):
        prompt_file = args[i + 1]
    elif arg == "--export" and i + 1 < len(args):
        export_path = args[i + 1]

session = os.environ["ELVES_FULL_RUN_SESSION"]
events = Path(os.environ["ELVES_FULL_RUN_EVENTS"])
report = Path(os.environ["ELVES_FULL_RUN_REPORT"])
transcript = Path(os.environ["ELVES_FULL_RUN_TRANSCRIPT"])
branch = os.environ.get("ELVES_FULL_RUN_BRANCH", "feature")
head = os.environ.get("ELVES_FULL_RUN_START_HEAD", "deadbeef")
worktree = Path(os.environ.get("ELVES_FULL_RUN_WORKTREE", str(Path.cwd())))

if prompt_file:
    prompt = Path(prompt_file).read_text(encoding="utf-8")
else:
    prompt = ""

def emit(etype, batch, summary, **extra):
    row = {
        "timestamp": utc(),
        "session_id": session,
        "branch": branch,
        "head": head,
        "batch": batch,
        "type": etype,
        "summary": summary,
    }
    row.update(extra)
    with events.open("a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    with transcript.open("a") as f:
        f.write(summary + "\n")

emit("run_started", 0, "fake devin worker started", prompt_head=prompt[:40])
emit("batch_started", 1, "devin batch started")
(worktree / "devin-progress.txt").write_text("ok\n", encoding="utf-8")
subprocess.run(["git", "-C", str(worktree), "add", "devin-progress.txt"], check=True)
subprocess.run(["git", "-C", str(worktree), "commit", "-q", "-m", "devin progress"], check=True)
new_head = subprocess.run(
    ["git", "-C", str(worktree), "rev-parse", "HEAD"],
    check=True, capture_output=True, text=True,
).stdout.strip()
subprocess.run(
    ["git", "-C", str(worktree), "push", "-q", "origin", f"HEAD:refs/heads/{branch}"],
    check=True,
)
emit("commit_pushed", 1, "devin commit", head=new_head)
emit("gate_result", 1, "devin gates ok", head=new_head)
emit("batch_complete", 1, "devin batch complete", head=new_head)
report.write_text(json.dumps({
    "run_id": os.environ["ELVES_FULL_RUN_RUN_ID"],
    "attempt": int(os.environ["ELVES_FULL_RUN_ATTEMPT"]),
    "session_id": session,
    "branch": branch,
    "start_head": head,
    "final_head": new_head,
    "status": "complete",
    "batches": [{"id": "batch-1", "status": "complete", "evidence": "devin gates passed"}],
    "acceptance": [
        {"id": "B1-A1", "criterion": "criterion for B1-A1", "met": True, "evidence": new_head},
        {"id": "M-A1", "criterion": "criterion for M-A1", "met": True, "evidence": new_head},
    ],
    "commits": [new_head],
    "blockers": [],
    "merge_authority": False,
}, indent=2) + "\n")
pause = os.environ.get("ELVES_FAKE_DEVIN_PAUSE")
if pause:
    time.sleep(float(pause))
emit("run_complete", 1, "fake devin run complete", head=new_head)
if export_path:
    Path(export_path).write_text(json.dumps({"exported": True, "model": "swe-1-7-lightning", "session_id": "devin-sess-123"}, indent=2), encoding="utf-8")
'''

FAKE_DEVIN_EMPTY_LIST = FAKE_DEVIN.replace(
    """    print(json.dumps([{
        "id": "devin-sess-123",
        "working_directory": cwd,
        "last_activity_at": int(time.time()),
    }], separators=(",", ":")))""",
    '    print("[]")',
).replace(
    'if export_path:\n    Path(export_path).write_text',
    'if False and export_path:\n    Path(export_path).write_text',
)

FAKE_DEVIN_AMBIGUOUS_LIST = FAKE_DEVIN.replace(
    """    print(json.dumps([{
        "id": "devin-sess-123",
        "working_directory": cwd,
        "last_activity_at": int(time.time()),
    }], separators=(",", ":")))""",
    """    print(json.dumps([
        {"id": "devin-sess-a", "working_directory": cwd, "last_activity_at": int(time.time())},
        {"id": "devin-sess-b", "working_directory": cwd, "last_activity_at": int(time.time())},
    ], separators=(",", ":")))""",
).replace(
    'if export_path:\n    Path(export_path).write_text',
    'if False and export_path:\n    Path(export_path).write_text',
)

LONG_SLEEPER = r'''#!/usr/bin/env python3
import os, time
from pathlib import Path
Path(os.environ["ELVES_FULL_RUN_TRANSCRIPT"]).write_text("sleeping\n")
time.sleep(30)
'''

COMMIT_WITHOUT_REPORT = r'''#!/usr/bin/env python3
import subprocess
from pathlib import Path

worktree = Path(__import__("os").environ["ELVES_FULL_RUN_WORKTREE"])
(worktree / "f.txt").write_text("progress without report\n", encoding="utf-8")
subprocess.run(["git", "-C", str(worktree), "add", "f.txt"], check=True)
subprocess.run(
    ["git", "-C", str(worktree), "commit", "-m", "progress without report"],
    check=True,
)
'''

COMPLETE_WITH_LINGERING_CHILD = FAKE_WORKER + r'''
import subprocess, sys
subprocess.Popen(
    [sys.executable, "-c", "import os,time; os.setsid(); child=os.fork(); "
     "os._exit(0) if child else time.sleep(30)"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
'''

GROK_COMMIT_AND_WAIT = r'''#!/usr/bin/env python3
import os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
if "--version" in args or (args and args[0] == "version"):
    print("grok 0.2.93 (test) [stable]")
    raise SystemExit(0)
auth_path = Path(os.environ["GROK_AUTH_PATH"])
if not auth_path.is_file() or Path(os.environ["GROK_HOME"]) == auth_path.parent:
    raise SystemExit(92)
cwd = Path(args[args.index("--cwd") + 1])
if "--resume" not in args:
    (cwd / "resume-checkpoint.txt").write_text("checkpoint\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(cwd), "add", "resume-checkpoint.txt"], check=True)
    subprocess.run(["git", "-C", str(cwd), "commit", "-q", "-m", "checkpoint"], check=True)
    subprocess.run(
        ["git", "-C", str(cwd), "push", "-q", "origin", "HEAD:refs/heads/" + os.environ["ELVES_FULL_RUN_BRANCH"]],
        check=True,
    )
time.sleep(30)
'''

GROK_ROTATE_AUTH_AND_WAIT = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path

args = sys.argv[1:]
if "--version" in args or (args and args[0] == "version"):
    print("grok 0.2.93 (test) [stable]")
    raise SystemExit(0)
auth = Path(os.environ["GROK_AUTH_PATH"])
payload = json.loads(auth.read_text(encoding="utf-8"))
record = next(value for value in payload.values() if isinstance(value, dict))
record["key"] = "provider-rotated-access"
record["refresh_token"] = "provider-rotated-refresh"
temporary = auth.with_name("auth.provider-next")
temporary.write_text(json.dumps(payload), encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(auth)
time.sleep(30)
'''


def _compile_native_grok_launcher(
    root: Path,
    script_source: str,
    *,
    name: str,
) -> Path:
    """Compile a native argv-forwarding test provider with the Grok marker."""
    compiler = shutil.which("cc")
    if compiler is None:
        raise unittest.SkipTest("native C compiler unavailable")
    script = root / f"{name}-worker.py"
    script.write_text(script_source, encoding="utf-8")
    source = root / f"{name}-launcher.c"
    source.write_text(
        "#include <stdlib.h>\n"
        "#include <unistd.h>\n"
        'static volatile const char marker[] = "GROK_AUTH_PATH";\n'
        "int main(int argc, char **argv) {\n"
        "  if (marker[0] == '\\0') return 126;\n"
        '  setenv("ELVES_TEST_NATIVE_LAUNCHER", argv[0], 1);\n'
        "  char **forwarded = calloc((size_t)argc + 2, sizeof(char *));\n"
        "  if (forwarded == NULL) return 127;\n"
        f"  forwarded[0] = {json.dumps(sys.executable)};\n"
        f"  forwarded[1] = {json.dumps(str(script))};\n"
        "  for (int i = 1; i < argc; i++) forwarded[i + 1] = argv[i];\n"
        "  forwarded[argc + 1] = NULL;\n"
        f"  execv({json.dumps(sys.executable)}, forwarded);\n"
        "  return 127;\n"
        "}\n",
        encoding="utf-8",
    )
    binary = root / name
    subprocess.run(
        [compiler, "-std=c99", str(source), "-o", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )
    binary.chmod(0o700)
    return binary


def _packet_binding_kwargs(packet: Path) -> dict[str, object]:
    raw = packet.read_bytes()
    packet.chmod(0o600)
    return {
        "staged_packet_path": str(packet),
        "staged_packet_identity": full_run_module._private_staged_packet_identity(
            packet
        ),
        "packet_sha256": hashlib.sha256(raw).hexdigest(),
        "packet_size": len(raw),
    }


def _run_bound_supervisor_after_mutation(
    root: Path,
    provider: Path,
    identity: dict[str, object],
    mutation: Callable[[], None],
) -> tuple[int, dict[str, object]]:
    """Release the embedded supervisor only after a test mutates its binding."""
    (root / "supervisor.fingerprint.json").write_text(
        '{"pid":1}\n', encoding="utf-8"
    )
    backend = str(full_run_module._qualified_process_supervisor())
    state = full_run_module.FullRunState(
        session_id="provider-secure-binding-test",
        branch="feat/x",
        start_head="a" * 40,
        worktree=str(root),
        packet_path=str(root / "packet.md"),
        attempt=1,
        supervision_token="a" * 48,
    )
    packet = Path(state.packet_path)
    packet.write_text("bound supervisor packet\n", encoding="utf-8")
    supervisor_argv = full_run_module._provider_supervisor_argv(
        root=root,
        session_id=state.session_id,
        provider_argv=[str(provider), str(packet)],
        attempt=state.attempt,
        supervisor_executable=backend,
        provider_executable_identity=identity,
        **_packet_binding_kwargs(packet),
    )
    env = {
        "PATH": os.environ.get("PATH") or os.defpath,
        "ELVES_FULL_RUN_SUPERVISION_MARKER": (
            full_run_module._descendant_supervision_marker(state)
        ),
    }
    proc = subprocess.Popen(
        supervisor_argv,
        cwd=root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        mutation()
        proc.communicate(
            (str(state.supervision_token) + "\n").encode("ascii"),
            timeout=5.0,
        )
    except BaseException:
        proc.kill()
        proc.communicate(timeout=2.0)
        raise
    record = json.loads(
        (root / "exit_record.json").read_text(encoding="utf-8")
    )
    return int(proc.returncode), record


# `monitor_full_run` refuses to trust an exit record while the recorded supervisor
# identity is still alive, reporting that refusal as `failed` with a
# premature-exit-record blocker and no `exit_code`. The product bridges the normal
# sidecar write/exit race with its own bounded window (`EXIT_RECORD_SETTLE_SECONDS`,
# 0.25s on Linux and 0.75s on Darwin), but a loaded host can leave the group
# unreaped past it.
#
# That refusal is *not* transient in the state machine: it latches. A later poll
# recovers `exit_code` once the record validates, but `blocker` keeps naming the
# premature refusal forever, so the settled classification is unreachable. A test
# that polls for the first terminal state can therefore both capture a status with
# no exit code and permanently lose the classification it came to assert.
#
# The deterministic fix is to never observe the reaping window: wait for the
# recorded identity to be fully reaped, then monitor once. Reuse the product's own
# settle primitive with a generous test budget rather than racing it.
def await_supervised_reap(repo: Path, session: str, *, timeout_seconds: float = 10.0) -> None:
    """Block until the run's recorded supervisor identity is fully reaped.

    Fails loudly rather than returning early: a caller that monitored anyway would
    observe the reaping window and latch the premature refusal, turning a timing
    problem into a confusing assertion about state or exit codes somewhere else.
    """
    state = load_state(repo, session)
    pid_alive, group_alive = full_run_module._settle_recorded_supervisor_exit(
        state.pid,
        state.pgid,
        timeout_seconds=timeout_seconds,
    )
    if pid_alive or group_alive:
        raise AssertionError(
            f"supervisor identity still alive after {timeout_seconds}s "
            f"(pid={state.pid} alive={pid_alive}, pgid={state.pgid} alive={group_alive}); "
            "monitoring now would observe the reaping window"
        )


def _init_feature_repo(path: Path, branch: str = "feat/x") -> str:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "full-run@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Full Run Test"],
        check=True,
    )
    (path / ".gitignore").write_text(".elves/\n", encoding="utf-8")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "base"], check=True)
    current_branch = subprocess.run(
        ["git", "-C", str(path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current_branch != branch:
        subprocess.run(
            ["git", "-C", str(path), "checkout", "-q", "-b", branch], check=True
        )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _attach_origin(repo: Path, remote: Path, branch: str) -> None:
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", str(remote)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "push", "-q", "-u", "origin", branch],
        check=True,
    )


def _write_production_packet(path: Path, *acceptance_ids: str) -> None:
    ids = acceptance_ids or ("B1-A1",)
    if not any(item.startswith("M-A") for item in ids):
        ids = (*ids, "M-A1")
    rows = ["# Production packet", "", "## Acceptance"]
    rows.extend(f"- {item} — criterion for {item}" for item in ids)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_production_acceptance_contract(repo: Path, packet: Path) -> Path:
    rows = full_run_module._staged_acceptance_criteria(packet)
    batches: dict[int, list[tuple[str, str]]] = {}
    master: list[tuple[str, str]] = []
    for acceptance_id, criterion in rows:
        if acceptance_id.startswith("B"):
            batch = int(acceptance_id[1:].split("-", 1)[0])
            batches.setdefault(batch, []).append((acceptance_id, criterion))
        else:
            master.append((acceptance_id, criterion))

    contract_root = repo / ".elves" / "test-acceptance"
    contract_root.mkdir(parents=True, exist_ok=True)
    plan = contract_root / "plan.md"
    plan_lines = ["# Production full-run test plan", ""]
    for number, batch_rows in sorted(batches.items()):
        plan_lines.extend(
            [
                f"## Batch {number}: Production test",
                "",
                "**Acceptance criteria:**",
                "",
                *[
                    f"- [ ] {acceptance_id}: {criterion}"
                    for acceptance_id, criterion in batch_rows
                ],
                "",
            ]
        )
    plan_lines.extend(
        [
            "## Master Acceptance",
            "",
            *[
                f"- [ ] {acceptance_id}: {criterion}"
                for acceptance_id, criterion in master
            ],
        ]
    )
    plan.write_text("\n".join(plan_lines) + "\n", encoding="utf-8")

    session = contract_root / "session.json"
    session.write_text(
        json.dumps(
            {
                "plan_path": ".elves/test-acceptance/plan.md",
                "batches": [
                    {
                        "id": f"B{number}",
                        "status": "pending",
                        "acceptance": [
                            {
                                "id": acceptance_id,
                                "criterion": criterion,
                                "met": False,
                                "evidence": "",
                            }
                            for acceptance_id, criterion in batch_rows
                        ],
                    }
                    for number, batch_rows in sorted(batches.items())
                ],
                "master_acceptance": [
                    {
                        "id": acceptance_id,
                        "criterion": criterion,
                        "met": False,
                        "evidence": "",
                    }
                    for acceptance_id, criterion in master
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return session


class BehaviorPolicyCompositionTests(unittest.TestCase):
    def test_compose_trusted_grok_chat_to_land(self) -> None:
        decision = resolve_from_signals(
            {"full_run": True, "trusted_grok": True, "chat_to_land": True}
        )
        self.assertEqual(decision.work_driver, "grok_build")
        self.assertEqual(decision.delegation_scope, "full_run")
        self.assertEqual(decision.driver_monitor_mode, "parked_monitor")
        self.assertEqual(decision.landing_mode, "chat_to_land")
        self.assertEqual(decision.git_mode, "branch_progress")

    def test_full_run_alone_stays_host_native(self) -> None:
        d = resolve_from_signals({"full_run": True})
        self.assertEqual(d.work_driver, "host_native")
        self.assertNotEqual(d.driver_monitor_mode, "parked_monitor")

    def test_overnight_alone_stays_host_native(self) -> None:
        d = resolve_from_signals({"overnight": True})
        self.assertEqual(d.work_driver, "host_native")

    def test_matrix_dimensions(self) -> None:
        cases = [
            ({"direct_edit": True}, "host_native"),
            ({"bounded_task": True}, "host_native"),
            ({"bounded_task": True, "work_driver_grok": True}, "grok_build"),
            ({"untrusted": True}, "untrusted_writer"),
            ({"legacy_two_call": True}, "host_native"),
            ({"full_run": True, "trusted_grok": True}, "grok_build"),
            ({"full_run": True}, "host_native"),
            ({"chat_to_work": True}, "host_native"),
        ]
        for signals, driver in cases:
            with self.subTest(signals=signals):
                d = resolve_from_signals(signals)
                self.assertEqual(d.work_driver, driver)

    def test_parked_forbids_per_push(self) -> None:
        self.assertIn("per_push", FORBIDDEN_FULL_RUN_WAKE_TRIGGERS)
        self.assertIn("worker_exit", PARKED_MONITOR_WAKE_CONDITIONS)

    def test_quiet_poll_interval_is_derived_from_stale_window(self) -> None:
        self.assertEqual(parked_monitor_poll_after_seconds(30), 60)
        self.assertEqual(parked_monitor_poll_after_seconds(300), 150)
        self.assertEqual(parked_monitor_poll_after_seconds(3600), 300)
        with self.assertRaises(TypeError):
            parked_monitor_poll_after_seconds(True)

    def test_natural_turn_it_over_to_grok_routes_full_run(self) -> None:
        decision = resolve_from_signals(
            {}, intent="Please turn it over to Grok for the full run"
        )
        self.assertEqual(decision.work_driver, "grok_build")
        self.assertEqual(decision.delegation_scope, "full_run")
        self.assertEqual(decision.driver_monitor_mode, "parked_monitor")


class FullRunReportValidationTests(unittest.TestCase):
    def test_grok_stream_decoder_sanitizes_progress_usage_terminal_and_unknowns(self) -> None:
        secret = "secret-value-for-redaction"
        lines = [
            json.dumps({"type": "thought", "data": secret}),
            json.dumps({"type": "text", "data": f"working with {secret}"}),
            json.dumps({"type": "future_event", "payload": secret}),
            json.dumps(
                {
                    "type": "end",
                    "sessionId": "11111111-1111-1111-1111-111111111111",
                    "stopReason": "EndTurn",
                    "usage": {"inputTokens": 10, "outputTokens": 4, "opaque": secret},
                }
            ),
            json.dumps({"type": "error", "errorType": "rate_limit", "message": secret}),
        ]
        rendered, cursor = full_run_module.grok_streaming_follow_lines(
            lines,
            exact_values=(secret,),
        )
        self.assertEqual(cursor, 5)
        payload = "\n".join(rendered)
        self.assertNotIn(secret, payload)
        self.assertIn("grok:thought", payload)
        self.assertIn("grok:unknown", payload)
        self.assertNotIn("unknown[future_event]", payload)
        self.assertIn("inputTokens:10", payload)
        self.assertIn("terminal", payload)
        self.assertNotIn("error=rate_limit", payload)

    def test_grok_stream_decoder_shared_oauth_never_exposes_free_text(self) -> None:
        rendered, _cursor = full_run_module.grok_streaming_follow_lines(
            [json.dumps({"type": "text", "data": "private progress detail"})],
            shared_oauth=True,
        )
        self.assertEqual(rendered, ["grok:text"])

    def test_grok_stream_rejects_mismatched_or_noncanonical_session_identity(self) -> None:
        expected = "11111111-1111-1111-1111-111111111111"
        for streamed in (
            "22222222-2222-2222-2222-222222222222",
            "NOT-A-UUID",
        ):
            with self.subTest(streamed=streamed), self.assertRaises(ValidationIssue) as caught:
                full_run_module.decode_grok_streaming_event(
                    json.dumps({"type": "end", "sessionId": streamed}),
                    expected_session_id=expected,
                )
            self.assertIn(caught.exception.code, {
                "grok_stream_session_identity_invalid",
                "grok_stream_session_identity_mismatch",
            })

    def test_grok_transcript_cursor_survives_more_than_one_thousand_and_partial_long_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            transcript = repo / ".elves" / "runtime" / "transcript.jsonl"
            transcript.parent.mkdir(parents=True)
            records = [json.dumps({"type": "text", "data": f"event-{index}"}) for index in range(1505)]
            long_record = json.dumps({"type": "text", "data": "x" * 100_000})
            transcript.write_bytes(("\n".join([*records, long_record]) + "\n").encode("utf-8"))
            first, cursor = full_run_module._read_grok_transcript_records(
                repo, transcript, full_run_module.GrokTranscriptCursor()
            )
            self.assertEqual(len(first), 1506)
            partial = json.dumps({"type": "text", "data": "partial-event"})
            with transcript.open("ab") as handle:
                handle.write(partial[:10].encode("utf-8"))
            second, cursor = full_run_module._read_grok_transcript_records(repo, transcript, cursor)
            self.assertEqual(second, [])
            with transcript.open("ab") as handle:
                handle.write(partial[10:].encode("utf-8") + b"\n")
            third, cursor = full_run_module._read_grok_transcript_records(repo, transcript, cursor)
            self.assertEqual(third, [partial])
            self.assertGreater(cursor.offset, 0)

    def test_grok_follow_detects_absent_grant_across_read_chunk_boundaries(self) -> None:
        redaction_marker = "grant-value-absent-from-monitor-environment"
        state = full_run_module.FullRunState(
            session_id="11111111-1111-1111-1111-111111111111",
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp",
            packet_path="/tmp/packet.md",
            supervision_token="c" * 48,
            credential_granted_names=["XAI_API_KEY"],
        )
        state.credential_grant_lengths = {"XAI_API_KEY": len(redaction_marker)}
        state.credential_grant_digests = {
            "XAI_API_KEY": full_run_module._credential_grant_digest(
                state, "XAI_API_KEY", redaction_marker
            )
        }
        state.credential_grant_metadata_mac = full_run_module._credential_grant_metadata_mac(state)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            transcript = repo / ".elves" / "runtime" / "transcript.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(
                json.dumps(
                    {"type": "text", "data": f"before-{redaction_marker}-after"}
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(full_run_module, "GROK_STREAM_READ_CHUNK_BYTES", 7):
                rows, _cursor = full_run_module._read_grok_transcript_records(
                    repo, transcript, full_run_module.GrokTranscriptCursor()
                )
            with mock.patch.dict(os.environ, {}, clear=True):
                rendered, _ = full_run_module.grok_streaming_follow_lines(
                    rows,
                    expected_session_id=state.session_id,
                    credential_grant_state=state,
                )
            payload = "\n".join(rendered)
            self.assertNotIn(redaction_marker, payload)
            self.assertIn("[REDACTED:credential_grant]", payload)

    def test_grok_follow_fails_closed_when_grant_metadata_is_unverified(self) -> None:
        state = full_run_module.FullRunState(
            session_id="11111111-1111-1111-1111-111111111111",
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp",
            packet_path="/tmp/packet.md",
            supervision_token="d" * 48,
            credential_granted_names=["XAI_API_KEY"],
            credential_grant_metadata_mac="0" * 64,
        )
        with self.assertRaises(ValidationIssue) as caught:
            full_run_module.decode_grok_streaming_event(
                json.dumps({"type": "text", "data": "must not render"}),
                expected_session_id=state.session_id,
                credential_grant_state=state,
            )
        self.assertEqual(
            caught.exception.code,
            "grok_follow_redaction_context_unverified",
        )

    def test_grok_follow_redacts_secret_bearing_metadata_but_keeps_safe_terminal_facts(self) -> None:
        secret = "xai-secret-metadata-123456789"
        expected = "11111111-1111-1111-1111-111111111111"
        state = full_run_module.FullRunState(
            session_id=expected,
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp",
            packet_path="/tmp/packet.md",
            supervision_token="f" * 48,
            credential_granted_names=["XAI_API_KEY"],
        )
        state.credential_grant_lengths = {"XAI_API_KEY": len(secret)}
        state.credential_grant_digests = {
            "XAI_API_KEY": full_run_module._credential_grant_digest(
                state, "XAI_API_KEY", secret
            )
        }
        state.credential_grant_metadata_mac = full_run_module._credential_grant_metadata_mac(state)
        metadata_fragment = secret[:14]
        message_fragment = secret[14:]

        rendered, _ = full_run_module.grok_streaming_follow_lines(
            [
                json.dumps({"type": secret, "payload": "unused"}),
                json.dumps(
                    {
                        "type": "error",
                        "errorType": metadata_fragment,
                        "message": message_fragment,
                    }
                ),
                json.dumps(
                    {
                        "type": "end",
                        "stopReason": secret,
                        "sessionId": expected,
                        "usage": {"inputTokens": 7},
                    }
                ),
            ],
            expected_session_id=expected,
            credential_grant_state=state,
        )
        payload = "\n".join(rendered)
        self.assertNotIn(secret, payload)
        self.assertNotIn(metadata_fragment, payload)
        self.assertNotIn(message_fragment, payload)
        self.assertIn("grok:unknown", payload)
        self.assertNotIn("unknown[", payload)
        self.assertIn("grok:error", payload)
        self.assertNotIn("error=", payload)
        self.assertNotIn("stop=", payload)
        self.assertNotIn(f"session={expected}", payload)
        self.assertIn("usage=inputTokens:7", payload)
        self.assertIn("terminal", payload)

        uuid_secret = "22222222-2222-2222-2222-222222222222"
        uuid_state = full_run_module.FullRunState(
            session_id=uuid_secret,
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp",
            packet_path="/tmp/packet.md",
            supervision_token="a" * 48,
            credential_granted_names=["XAI_API_KEY"],
        )
        uuid_state.credential_grant_lengths = {"XAI_API_KEY": len(uuid_secret)}
        uuid_state.credential_grant_digests = {
            "XAI_API_KEY": full_run_module._credential_grant_digest(
                uuid_state, "XAI_API_KEY", uuid_secret
            )
        }
        uuid_state.credential_grant_metadata_mac = (
            full_run_module._credential_grant_metadata_mac(uuid_state)
        )
        uuid_rendered, _ = full_run_module.grok_streaming_follow_lines(
            [
                json.dumps(
                    {
                        "type": "end",
                        "sessionId": uuid_secret,
                        "usage": {"outputTokens": 2},
                    }
                )
            ],
            expected_session_id=uuid_secret,
            credential_grant_state=uuid_state,
        )
        uuid_payload = "\n".join(uuid_rendered)
        self.assertNotIn(uuid_secret, uuid_payload)
        self.assertIn("usage=outputTokens:2", uuid_payload)
        self.assertIn("terminal", uuid_payload)

    def test_grok_follow_quarantines_adjacent_chunks_until_split_grant_is_safe(self) -> None:
        secret = "grant-value-split-between-streaming-events"
        expected = "11111111-1111-1111-1111-111111111111"
        state = full_run_module.FullRunState(
            session_id=expected,
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp",
            packet_path="/tmp/packet.md",
            supervision_token="b" * 48,
            credential_granted_names=["XAI_API_KEY"],
        )
        state.credential_grant_lengths = {"XAI_API_KEY": len(secret)}
        state.credential_grant_digests = {
            "XAI_API_KEY": full_run_module._credential_grant_digest(
                state, "XAI_API_KEY", secret
            )
        }
        state.credential_grant_metadata_mac = full_run_module._credential_grant_metadata_mac(state)
        redaction_state = full_run_module.GrokStreamingRedactionState()
        first_fragment = secret[:17]
        second_fragment = secret[17:]

        first, _ = full_run_module.grok_streaming_follow_lines(
            [json.dumps({"type": "text", "data": first_fragment})],
            expected_session_id=expected,
            credential_grant_state=state,
            redaction_state=redaction_state,
        )
        self.assertEqual(first, [])
        second, _ = full_run_module.grok_streaming_follow_lines(
            [
                json.dumps({"type": "text", "data": second_fragment}),
                json.dumps(
                    {
                        "type": "end",
                        "sessionId": expected,
                        "stopReason": "EndTurn",
                        "usage": {"outputTokens": 3},
                    }
                ),
            ],
            expected_session_id=expected,
            credential_grant_state=state,
            redaction_state=redaction_state,
        )
        payload = "\n".join(second)
        self.assertNotIn(secret, payload)
        self.assertNotIn(first_fragment, payload)
        self.assertNotIn(second_fragment, payload)
        self.assertGreaterEqual(payload.count("[REDACTED:credential_grant]"), 2)
        self.assertIn("usage=outputTokens:3", payload)
        self.assertIn("terminal", payload)

        safe_state = full_run_module.GrokStreamingRedactionState()
        safe_first, _ = full_run_module.grok_streaming_follow_lines(
            [json.dumps({"type": "text", "data": "safe progress remains visible"})],
            expected_session_id=expected,
            credential_grant_state=state,
            redaction_state=safe_state,
        )
        self.assertEqual(safe_first, [])
        safe_final, _ = full_run_module.grok_streaming_follow_lines(
            [json.dumps({"type": "end", "sessionId": expected})],
            expected_session_id=expected,
            credential_grant_state=state,
            redaction_state=safe_state,
        )
        self.assertIn("safe progress remains visible", "\n".join(safe_final))

    def test_await_wakes_safely_on_streamed_session_mismatch(self) -> None:
        expected = "11111111-1111-1111-1111-111111111111"
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            state = full_run_module.FullRunState(
                session_id=expected,
                branch="feat/x",
                start_head="a" * 40,
                worktree=str(repo),
                packet_path=str(repo / "packet.md"),
                supervision_token="e" * 48,
                adapter="grok-build",
            )
            root = full_run_root(repo, expected)
            root.mkdir(parents=True)
            (root / "transcript.log").write_text(
                json.dumps(
                    {
                        "type": "end",
                        "sessionId": "22222222-2222-2222-2222-222222222222",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            quiet = {
                "ok": True,
                "state": "healthy",
                "next_action": "parked_monitor",
                "material_transition": False,
                "unchanged_healthy_poll_silent": True,
                "poll_after_seconds": 0,
            }
            with (
                mock.patch.object(full_run_module, "monitor_full_run", return_value=quiet),
                mock.patch.object(full_run_module, "load_state", return_value=state),
                mock.patch.object(full_run_module, "_all_follow_events", return_value=[]),
            ):
                result = await_full_run(
                    repo,
                    session_id=expected,
                    sleep_fn=lambda _delay: None,
                )
            self.assertEqual(result["next_action"], "driver_wake_safety_tripwire")
            self.assertIn("grok_stream_session_identity_mismatch", result["blocker"])

    def _complete(self) -> dict:
        return {
            "run_id": "run-1",
            "attempt": 1,
            "session_id": "session-1",
            "branch": "feat/x",
            "start_head": "a" * 40,
            "final_head": "b" * 40,
            "status": "complete",
            "batches": [
                {"id": "batch-1", "status": "complete", "evidence": "gates passed"}
            ],
            "acceptance": [
                {
                    "id": "B1-A1",
                    "criterion": "verified",
                    "met": True,
                    "evidence": "test output",
                }
            ],
            "commits": ["b" * 40],
        }

    def test_complete_requires_nonempty_batches_commits_and_exact_acceptance(self) -> None:
        for mutation in ("batches", "commits"):
            with self.subTest(mutation=mutation):
                report = self._complete()
                report[mutation] = []
                errors = validate_run_report(
                    report, require_complete_acceptance=True, expected_run_id="run-1"
                )
                self.assertTrue(any(mutation in error for error in errors), errors)

        for field, value in (
            ("id", ""),
            ("criterion", ""),
            ("met", False),
            ("evidence", ""),
        ):
            with self.subTest(field=field):
                report = self._complete()
                report["acceptance"][0][field] = value
                errors = validate_run_report(
                    report, require_complete_acceptance=True, expected_run_id="run-1"
                )
                self.assertTrue(errors)

    def test_event_v1_rejects_bad_types_timestamp_sha_and_batch(self) -> None:
        valid = {
            "timestamp": "2026-07-13T05:14:00Z",
            "session_id": "session-1",
            "branch": "feat/x",
            "head": "a" * 40,
            "batch": 2,
            "type": "heartbeat",
            "summary": "healthy",
        }
        self.assertEqual(validate_event(valid), [])
        for field, value in (
            ("timestamp", "2026-07-13T05:14:00-04:00"),
            ("head", "abc123"),
            ("batch", True),
            ("batch", -1),
            ("summary", 7),
            ("session_id", 7),
        ):
            with self.subTest(field=field, value=value):
                event = {**valid, field: value}
                self.assertTrue(validate_event(event))

    def test_high_risk_checkpoint_event_must_be_staged_unique_and_typed(self) -> None:
        event = {
            "timestamp": "2026-07-13T05:14:00Z",
            "session_id": "session-1",
            "branch": "feat/x",
            "head": "a" * 40,
            "batch": 2,
            "type": "high_risk_checkpoint",
            "checkpoint_id": "security-boundary",
            "summary": "Host review requested",
        }
        self.assertEqual(
            validate_event(
                event,
                expected_high_risk_checkpoints=["security-boundary"],
            ),
            [],
        )
        self.assertTrue(
            validate_event(event, expected_high_risk_checkpoints=[])
        )
        self.assertTrue(
            validate_event(
                event,
                expected_high_risk_checkpoints=["security-boundary"],
                seen_high_risk_checkpoints=["security-boundary"],
            )
        )
        self.assertTrue(validate_event({**event, "checkpoint_id": "bad id"}))
        self.assertTrue(
            validate_event({**event, "type": "heartbeat"})
        )

    def test_confidence_signal_optional_fields_valid_on_events(self) -> None:
        base = {
            "timestamp": "2026-07-18T05:14:00Z",
            "session_id": "session-1",
            "branch": "feat/x",
            "head": "a" * 40,
            "batch": 2,
            "type": "batch_complete",
            "summary": "batch 2 complete",
        }
        with_signal = {
            **base,
            "confidence": "low",
            "unsure_about": [
                "retry backoff bounds in queue.py",
                "whether the legacy CSV importer hits the new validator",
            ],
        }
        self.assertEqual(validate_event(with_signal), [])
        # An empty unsure_about list is a valid, complete answer.
        empty_list = {**base, "confidence": "high", "unsure_about": []}
        self.assertEqual(validate_event(empty_list), [])
        # Absent fields stay valid (backward compatible).
        self.assertEqual(validate_event(base), [])
        run_complete = {
            **base,
            "type": "run_complete",
            "confidence": "medium",
            "unsure_about": [],
        }
        self.assertEqual(validate_event(run_complete), [])

    def test_confidence_signal_rejects_malformed_fields_with_stable_codes(self) -> None:
        base = {
            "timestamp": "2026-07-18T05:14:00Z",
            "session_id": "session-1",
            "branch": "feat/x",
            "head": "a" * 40,
            "batch": 2,
            "type": "batch_complete",
            "summary": "batch 2 complete",
        }
        cases = (
            (
                {"confidence": "certain"},
                "confidence must be one of high, medium, low",
            ),
            ({"unsure_about": "oops"}, "unsure_about must be a list"),
            (
                {"unsure_about": [7]},
                "unsure_about items must be non-empty strings",
            ),
            (
                {"unsure_about": ["   "]},
                "unsure_about items must be non-empty strings",
            ),
            (
                {"unsure_about": ["x" * 501]},
                "unsure_about item exceeds 500 chars",
            ),
            (
                {"unsure_about": [f"item {index}" for index in range(17)]},
                "unsure_about exceeds 16 items",
            ),
            (
                {"unsure_about": ["uses bearer abc123token for the API call"]},
                "unsure_about contains secret-shaped content",
            ),
        )
        for mutation, expected in cases:
            with self.subTest(expected=expected):
                errors = validate_event({**base, **mutation})
                self.assertIn(expected, errors)

    def test_report_batch_rows_accept_and_reject_confidence_signal(self) -> None:
        valid = self._complete()
        valid["batches"][0]["confidence"] = "high"
        valid["batches"][0]["unsure_about"] = []
        self.assertEqual(
            validate_run_report(
                valid, require_complete_acceptance=True, expected_run_id="run-1"
            ),
            [],
        )
        flagged = self._complete()
        flagged["batches"][0]["confidence"] = "low"
        flagged["batches"][0]["unsure_about"] = ["retry backoff bounds"]
        self.assertEqual(
            validate_run_report(
                flagged, require_complete_acceptance=True, expected_run_id="run-1"
            ),
            [],
        )
        for mutation, expected in (
            (
                {"confidence": "certain"},
                "batches[0].confidence must be one of high, medium, low",
            ),
            ({"unsure_about": "oops"}, "batches[0].unsure_about must be a list"),
            (
                {"unsure_about": [""]},
                "batches[0].unsure_about items must be non-empty strings",
            ),
            (
                {"unsure_about": ["uses bearer abc123token for the API call"]},
                "batches[0].unsure_about contains secret-shaped content",
            ),
        ):
            with self.subTest(expected=expected):
                report = self._complete()
                report["batches"][0].update(mutation)
                errors = validate_run_report(
                    report,
                    require_complete_acceptance=True,
                    expected_run_id="run-1",
                )
                self.assertIn(expected, errors)

    def test_review_context_turns_confidence_into_required_attention(self) -> None:
        report = self._complete()
        report["batches"][0].update(
            {
                "confidence": "low",
                "unsure_about": ["retry backoff bounds"],
            }
        )
        events = [
            {
                "type": "batch_complete",
                "batch": 1,
                "confidence": "medium",
                "unsure_about": ["legacy CSV validator path"],
            },
            {
                "type": "run_complete",
                "batch": 1,
                "confidence": "high",
                "unsure_about": [],
            },
        ]
        context = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=report,
            events=events,
        )

        batch = context["signals"][0]
        self.assertEqual(batch["attention"], "deep")
        self.assertEqual(batch["confidence"], "low")
        self.assertTrue(batch["signal_conflict"])
        self.assertEqual(batch["sources"], ["event", "report"])
        self.assertEqual(
            batch["unsure_about"],
            ["retry backoff bounds", "legacy CSV validator path"],
        )
        self.assertEqual(context["lowest_confidence"], "low")
        self.assertFalse(context["review_policy"]["confidence_can_reduce_scope"])
        prompt = context["review_prompt_block"]
        self.assertIn("[DEEP] batch-1", prompt)
        self.assertIn("CONFLICTING SOURCES", prompt)
        self.assertIn("Perform baseline review for every batch", prompt)

    def test_review_context_distinguishes_absent_from_asserted_clean(self) -> None:
        absent = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=self._complete(),
            events=[],
        )
        self.assertEqual(absent["signal_status"], "absent")
        self.assertEqual(absent["signals"][0]["signal_status"], "missing")
        self.assertIn("absence is not evidence of safety", absent["review_prompt_block"])

        clean_report = self._complete()
        clean_report["batches"][0].update(
            {"confidence": "high", "unsure_about": []}
        )
        clean = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=clean_report,
            events=[],
        )
        self.assertEqual(clean["signal_status"], "present")
        self.assertEqual(clean["signals"][0]["unsure_about_count"], 0)
        self.assertIn("worker asserted no reservations", clean["review_prompt_block"])

    def test_review_context_hides_shared_oauth_reservation_text(self) -> None:
        report = self._complete()
        report["batches"][0].update(
            {
                "confidence": "medium",
                "unsure_about": ["private worker reservation"],
            }
        )
        context = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=report,
            events=[
                {
                    "type": "batch_complete",
                    "batch": 1,
                    "confidence": "medium",
                    "unsure_about_count": 1,
                }
            ],
            shared_oauth=True,
        )
        encoded = json.dumps(context, sort_keys=True)
        self.assertNotIn("private worker reservation", encoded)
        self.assertEqual(context["signals"][0]["unsure_about_count"], 1)
        self.assertTrue(context["signals"][0]["free_text_hidden"])
        self.assertIn("text hidden by shared-OAuth safety", context["review_prompt_block"])

    def test_review_context_bounds_never_make_optional_triage_a_gate(self) -> None:
        report = self._complete()
        report["batches"] = [
            {
                "id": f"batch-{index}",
                "status": "complete",
                "evidence": "gates passed",
                "confidence": "high" if index < 257 else "low",
                "unsure_about": [],
            }
            for index in range(1, 258)
        ]
        context = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=report,
            events=[],
        )

        self.assertEqual(len(context["signals"]), 256)
        self.assertEqual(context["omitted_signal_rows"], 1)
        self.assertEqual(context["signal_status"], "partial")
        self.assertIn("Perform full baseline review", context["review_prompt_block"])

    def test_review_context_attributes_canonical_b0_b1_ids_to_their_own_batches(
        self,
    ) -> None:
        report = self._complete()
        report["batches"] = [
            {
                "id": "B0",
                "status": "complete",
                "evidence": "gates passed",
                "confidence": "high",
                "unsure_about": [],
            },
            {
                "id": "B1",
                "status": "complete",
                "evidence": "gates passed",
                "confidence": "high",
                "unsure_about": [],
            },
        ]
        events = [
            {
                "type": "batch_complete",
                "batch": 0,
                "confidence": "low",
                "unsure_about": ["B0 rollback path untested"],
            },
            {
                "type": "batch_complete",
                "batch": 1,
                "confidence": "high",
                "unsure_about": [],
            },
        ]
        context = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=report,
            events=events,
        )

        labels = [row["batch"] for row in context["signals"]]
        self.assertEqual(labels, ["B0", "B1"])
        by_label = {row["batch"]: row for row in context["signals"]}
        # B0's event signal lands on B0 (not an orphan batch-0 row, not B1).
        self.assertEqual(by_label["B0"]["sources"], ["event", "report"])
        self.assertEqual(by_label["B0"]["confidence"], "low")
        self.assertEqual(
            by_label["B0"]["unsure_about"], ["B0 rollback path untested"]
        )
        # Same-batch conflict detection can fire: report high vs event low.
        self.assertTrue(by_label["B0"]["signal_conflict"])
        # B1's clean event agrees with its report row: no fabricated conflict,
        # no corroboration borrowed from another batch's event.
        self.assertEqual(by_label["B1"]["sources"], ["event", "report"])
        self.assertFalse(by_label["B1"]["signal_conflict"])
        self.assertEqual(by_label["B1"]["confidence"], "high")

    def test_confidence_count_without_list_rejected_outside_projection(self) -> None:
        base = {
            "timestamp": "2026-07-18T05:14:00Z",
            "session_id": "session-1",
            "branch": "feat/x",
            "head": "a" * 40,
            "batch": 2,
            "type": "batch_complete",
            "summary": "batch 2 complete",
        }
        abusive = {**base, "confidence": "high", "unsure_about_count": 9999}
        errors = validate_event(abusive)
        self.assertTrue(
            any("unsure_about_count" in error for error in errors), errors
        )
        modest = {**base, "unsure_about_count": 3}
        self.assertTrue(
            any(
                "unsure_about_count" in error
                for error in validate_event(modest)
            )
        )
        # The shared-OAuth projection of a hidden list stays legitimate.
        projected_ok = validate_event(
            {**base, "unsure_about_count": 3},
            allow_projected_unsure_count=True,
        )
        self.assertEqual(projected_ok, [])
        # Even the projection route rejects an out-of-bounds count.
        projected_abuse = validate_event(
            {**base, "unsure_about_count": 9999},
            allow_projected_unsure_count=True,
        )
        self.assertTrue(
            any("unsure_about_count" in error for error in projected_abuse)
        )
        report = self._complete()
        report["batches"][0]["unsure_about_count"] = 9999
        report_errors = validate_run_report(
            report, require_complete_acceptance=True, expected_run_id="run-1"
        )
        self.assertTrue(
            any("unsure_about_count" in error for error in report_errors),
            report_errors,
        )

    def test_review_context_overflow_keeps_highest_attention_rows(self) -> None:
        report = self._complete()
        report["batches"] = [
            {
                "id": f"batch-{index}",
                "status": "complete",
                "evidence": "gates passed",
                "confidence": "high",
                "unsure_about": [],
            }
            for index in range(1, 4)
        ] + [
            {
                "id": "batch-critical",
                "status": "complete",
                "evidence": "gates passed",
                "confidence": "low",
                "unsure_about": ["rollback path untested"],
            }
        ]
        with mock.patch.object(
            full_run_module, "MAX_REVIEW_CONFIDENCE_PROMPT_CHARS", 750
        ):
            context = build_worker_confidence_review_context(
                session_id="session-1",
                branch="feat/x",
                final_head="b" * 40,
                report=report,
                events=[],
            )
        block = context["review_prompt_block"]
        self.assertLessEqual(len(block), 750)
        # The deep-attention row survives; lower-attention rows are dropped
        # with an explicit count instead of a generic wipe-out.
        self.assertIn("batch-critical", block)
        self.assertIn("rollback path untested", block)
        self.assertIn("confidence row(s) dropped to fit", block)
        self.assertIn("Perform baseline review for every batch", block)

    def test_reservation_truncation_states_hidden_item_count(self) -> None:
        report = self._complete()
        report["batches"][0].update(
            {
                "confidence": "low",
                "unsure_about": [f"reservation {index} " + "x" * 90 for index in range(8)],
            }
        )
        context = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=report,
            events=[],
        )
        block = context["review_prompt_block"]
        self.assertIn("of 8 reservation(s) hidden)", block)

    def test_identical_reservations_in_different_order_do_not_conflict(self) -> None:
        report = self._complete()
        report["batches"][0].update(
            {
                "confidence": "medium",
                "unsure_about": ["alpha risk", "beta risk"],
            }
        )
        events = [
            {
                "type": "batch_complete",
                "batch": 1,
                "confidence": "medium",
                "unsure_about": ["beta risk", "alpha risk"],
            }
        ]
        context = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=report,
            events=events,
        )
        row = context["signals"][0]
        self.assertEqual(row["sources"], ["event", "report"])
        self.assertFalse(row["signal_conflict"])
        self.assertNotIn("CONFLICTING SOURCES", context["review_prompt_block"])

    def test_host_reconstruction_returns_the_same_confidence_review_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            start = "a" * 40
            tip = "b" * 40
            state = full_run_module.FullRunState(
                session_id="session-1",
                branch="feat/x",
                start_head=start,
                worktree=str(repo),
                packet_path=str(repo / "packet.md"),
                acceptance_criteria={"B1-A1": "verified behavior"},
                origin_url="https://github.com/example/repo.git",
                origin_config_digest="origin-digest",
                exit_code=0,
            )
            confidence_event = {
                "type": "batch_complete",
                "batch": 1,
                "confidence": "low",
                "unsure_about": ["reconstructed retry path"],
            }
            with (
                mock.patch.object(
                    full_run_module, "_full_run_lock", return_value=nullcontext()
                ),
                mock.patch.object(full_run_module, "load_state", return_value=state),
                mock.patch.object(
                    full_run_module, "verify_protected_refs_unchanged", return_value=[]
                ),
                mock.patch.object(
                    full_run_module,
                    "_canonical_origin_url",
                    return_value=state.origin_url,
                ),
                mock.patch.object(
                    full_run_module,
                    "_origin_config_digest",
                    return_value=state.origin_config_digest,
                ),
                mock.patch.object(full_run_module, "_assert_clean_worktree"),
                mock.patch.object(full_run_module, "_git_head", return_value=tip),
                mock.patch.object(full_run_module, "_is_ancestor", return_value=True),
                mock.patch.object(
                    full_run_module, "_git_commit_chain", return_value=[tip]
                ),
                mock.patch.object(
                    full_run_module,
                    "run_git",
                    return_value=mock.Mock(returncode=0, stdout="implemented\n", stderr=""),
                ),
                mock.patch.object(full_run_module, "write_report"),
                mock.patch.object(full_run_module, "save_state"),
                mock.patch.object(
                    full_run_module,
                    "_launch_evidence_context",
                    return_value=(True, frozenset()),
                ),
                mock.patch.object(
                    full_run_module,
                    "_read_events",
                    return_value=([confidence_event], []),
                ),
            ):
                result = reconstruct_missing_report(
                    repo,
                    session_id=state.session_id,
                    host_tests_pass=True,
                )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["next_action"], "final_readiness")
        self.assertEqual(result["review_context"]["lowest_confidence"], "low")
        self.assertIn(
            "reconstructed retry path",
            result["review_context"]["review_prompt_block"],
        )

    def test_material_change_event_has_concrete_typed_schema(self) -> None:
        event = {
            "timestamp": "2026-07-13T05:14:00Z",
            "session_id": "session-1",
            "branch": "feat/x",
            "head": "a" * 40,
            "batch": 2,
            "type": "material_scope_or_assumption_change",
            "change_id": "api-contract-expanded",
            "change_kind": "scope",
            "summary": "A public API compatibility constraint changed",
        }
        self.assertEqual(validate_event(event), [])
        for mutation in (
            {"change_id": "bad id"},
            {"change_kind": "preference"},
            {"change_id": None},
            {"change_kind": None},
        ):
            with self.subTest(mutation=mutation):
                self.assertTrue(validate_event({**event, **mutation}))
        self.assertTrue(validate_event({**event, "type": "heartbeat"}))

    def test_follow_uses_absolute_event_sequence_beyond_diagnostic_tail(self) -> None:
        state = mock.Mock(attempt=1, grok_auth_strategy=None)
        events_50 = [
            {
                "timestamp": f"2026-07-13T05:14:{index:02d}Z",
                "batch": 1,
                "type": "heartbeat",
                "head": "a" * 40,
                "summary": f"event {index}",
            }
            for index in range(50)
        ]
        events_55 = events_50 + [
            {
                "timestamp": f"2026-07-13T05:15:{index:02d}Z",
                "batch": 2,
                "type": "commit_pushed",
                "head": "b" * 40,
                "summary": f"event {index + 50}",
            }
            for index in range(5)
        ]
        quiet = {
            "state": "healthy",
            "next_action": "parked_monitor",
            "material_transition": False,
            "unchanged_healthy_poll_silent": True,
            "poll_after_seconds": 0,
        }
        terminal = {
            **quiet,
            "state": "complete",
            "next_action": "final_readiness",
            "material_transition": True,
            "unchanged_healthy_poll_silent": False,
        }
        from cobbler_runtime import full_run_monitor as full_run_monitor_module

        with (
            mock.patch.object(
                full_run_monitor_module,
                "monitor_full_run",
                side_effect=[quiet, terminal],
            ),
            mock.patch.object(
                full_run_monitor_module, "load_state", return_value=state
            ),
            mock.patch.object(
                full_run_monitor_module,
                "_all_follow_events",
                side_effect=[events_50, events_55],
            ),
        ):
            result = await_full_run(
                Path("/tmp/repo"),
                session_id="session-1",
                sleep_fn=lambda _delay: None,
            )
        self.assertEqual(len(result["follow_stream_lines"]), 55)
        self.assertIn("event 54", result["follow_stream_lines"][-1])

    def test_follow_resets_absolute_cursor_when_resume_attempt_rotates_log(self) -> None:
        from cobbler_runtime import full_run_monitor as full_run_monitor_module

        def events(prefix: str, count: int) -> list[dict[str, object]]:
            return [
                {
                    "timestamp": f"2026-07-13T05:14:0{index}Z",
                    "batch": 1,
                    "type": "heartbeat",
                    "head": "a" * 40,
                    "summary": f"{prefix} {index}",
                }
                for index in range(count)
            ]

        quiet = {
            "state": "healthy",
            "next_action": "parked_monitor",
            "material_transition": False,
            "unchanged_healthy_poll_silent": True,
            "poll_after_seconds": 0,
        }
        terminal = {
            **quiet,
            "state": "complete",
            "next_action": "final_readiness",
            "material_transition": True,
            "unchanged_healthy_poll_silent": False,
        }
        attempt_1 = mock.Mock(attempt=1, grok_auth_strategy=None)
        attempt_2 = mock.Mock(attempt=2, grok_auth_strategy=None)
        with (
            mock.patch.object(
                full_run_monitor_module,
                "monitor_full_run",
                side_effect=[quiet, terminal],
            ),
            mock.patch.object(
                full_run_monitor_module,
                "load_state",
                side_effect=[attempt_1, attempt_2],
            ),
            mock.patch.object(
                full_run_monitor_module,
                "_all_follow_events",
                side_effect=[events("attempt-1", 3), events("attempt-2", 2)],
            ),
        ):
            result = await_full_run(
                Path("/tmp/repo"),
                session_id="session-1",
                sleep_fn=lambda _delay: None,
            )
        self.assertEqual(len(result["follow_stream_lines"]), 5)
        self.assertIn("attempt-2 0", result["follow_stream_lines"][-2])

    def test_report_v1_rejects_malformed_batch_and_commit_records(self) -> None:
        valid = self._complete()
        self.assertEqual(
            validate_run_report(
                valid, require_complete_acceptance=True, expected_run_id="run-1"
            ),
            [],
        )
        malformed = (
            {"batches": ["batch-1"]},
            {"batches": [{"id": 1, "status": "complete", "evidence": "ok"}]},
            {"batches": [{"id": "batch-1", "status": "running", "evidence": "ok"}]},
            {"batches": [{"id": "batch-1", "status": "complete", "evidence": ""}]},
            {"commits": ["short"]},
            {"commits": [{"sha": "b" * 40}]},
            {"commits": [{"sha": "short", "subject": "change"}]},
        )
        for mutation in malformed:
            with self.subTest(mutation=mutation):
                report = {**valid, **mutation}
                self.assertTrue(
                    validate_run_report(
                        report,
                        require_complete_acceptance=True,
                        expected_run_id="run-1",
                    )
                )

    def test_report_v1_requires_positive_non_boolean_attempt(self) -> None:
        for value in (None, 0, -1, True, "1"):
            with self.subTest(value=value):
                report = self._complete()
                if value is None:
                    report.pop("attempt")
                else:
                    report["attempt"] = value
                errors = validate_run_report(
                    report,
                    require_complete_acceptance=True,
                    expected_run_id="run-1",
                    expected_attempt=1,
                )
                self.assertTrue(any("attempt" in error for error in errors), errors)

    def test_nested_secret_fields_are_rejected_without_identifier_false_positives(self) -> None:
        report = self._complete()
        report["tests"] = {
            "nested": {"refresh_token": "opaque-refresh-value-123456789"}
        }
        errors = validate_run_report(
            report,
            require_complete_acceptance=True,
            expected_run_id="run-1",
        )
        self.assertTrue(any("secret" in error for error in errors), errors)

        clean = self._complete()
        clean["tests"] = {"test_api_key_redaction": "passed"}
        self.assertEqual(
            validate_run_report(
                clean,
                require_complete_acceptance=True,
                expected_run_id="run-1",
            ),
            [],
        )

    def test_complete_report_rejects_blockers_and_remaining_risks(self) -> None:
        for key in ("blockers", "remaining_risks"):
            with self.subTest(key=key):
                report = self._complete()
                report[key] = ["not actually ready"]
                errors = validate_run_report(
                    report,
                    require_complete_acceptance=True,
                    expected_run_id="run-1",
                )
                self.assertTrue(any(key in error for error in errors), errors)

    def test_grok_launch_prompt_complete_example_and_terminal_invariants_match_runtime(self) -> None:
        prompt = (
            Path(__file__).resolve().parents[1]
            / "references"
            / "grok-implementer-launch-prompt.md"
        ).read_text(encoding="utf-8")
        section = prompt.split("### Full-run report v1", 1)[1].split(
            "## Legacy bounded-batch done report schema", 1
        )[0]
        example = json.loads(section.split("```json", 1)[1].split("```", 1)[0])
        self.assertEqual(
            validate_run_report(
                example,
                expected_run_id="full-run-run-a1b2c3d4",
                expected_attempt=1,
                expected_session_id="20e34572-1a71-44aa-8b90-0123456789ab",
                expected_branch="feat/delegated-worker",
                expected_start_head="a" * 40,
                require_complete_acceptance=True,
            ),
            [],
        )
        normalized_section = " ".join(section.split())
        for runtime_invariant in (
            'status: "complete"',
            "both `blockers` and `remaining_risks` must be empty",
            "exact ordered `start_head..final_head` Git chain",
            "tracked and untracked worktree state clean",
            "final report id set must exactly equal the staged id set",
        ):
            with self.subTest(runtime_invariant=runtime_invariant):
                self.assertIn(runtime_invariant, normalized_section)

    def test_event_rejects_future_timestamp_post_terminal_and_secret_key(self) -> None:
        valid = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "session_id": "session-1",
            "branch": "feat/x",
            "head": "a" * 40,
            "batch": 1,
            "type": "heartbeat",
            "summary": "healthy",
        }
        future = {
            **valid,
            "timestamp": (
                datetime.now(timezone.utc)
                + timedelta(seconds=full_run_module.MAX_EVENT_FUTURE_SKEW_SECONDS + 30)
            ).replace(microsecond=0).isoformat(),
        }
        self.assertTrue(
            any("future" in error for error in validate_event(future)),
            validate_event(future),
        )
        self.assertTrue(
            any("after terminal" in error for error in validate_event(valid, seen_terminal=True))
        )
        opaque = "opaque-granted-value-used-as-a-key-473829"
        secret_key_event = {**valid, opaque: "innocent-looking value"}
        self.assertTrue(
            any(
                "secret" in error
                for error in validate_event(
                    secret_key_event,
                    exact_secret_values={opaque},
                )
            )
        )

    def test_redacted_mapping_keys_cannot_overwrite_suffix_like_real_keys(self) -> None:
        semantic = full_run_module._redact_full_run_structure(
            {
                "[REDACTED:secret_field_name]#1": "operator evidence",
                "api_key": "first-secret-value-123456",
                "refresh_token": "second-secret-value-123456",
            }
        )
        self.assertEqual(len(semantic), 3)
        self.assertEqual(
            semantic["[REDACTED:secret_field_name]#1"], "operator evidence"
        )
        self.assertEqual(
            semantic["[REDACTED:secret_field_name]"],
            "[REDACTED:secret_field]",
        )
        self.assertEqual(
            semantic["[REDACTED:secret_field_name]#2"],
            "[REDACTED:secret_field]",
        )

        secret = "opaque-grant-for-key-collision-481516"
        state = full_run_module.FullRunState(
            session_id="redaction-collision",
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp",
            packet_path="/tmp/packet.md",
            supervision_token="b" * 48,
            credential_granted_names=["XAI_API_KEY"],
        )
        state.credential_grant_lengths = {"XAI_API_KEY": len(secret)}
        state.credential_grant_digests = {
            "XAI_API_KEY": full_run_module._credential_grant_digest(
                state, "XAI_API_KEY", secret
            )
        }
        state.credential_grant_metadata_mac = (
            full_run_module._credential_grant_metadata_mac(state)
        )
        opaque = full_run_module._redact_persisted_credential_grants(
            {
                "[REDACTED:credential_grant_key]#1": "operator evidence",
                f"first-{secret}": "first leak",
                f"second-{secret}": "second leak",
            },
            state,
        )
        self.assertEqual(len(opaque), 3)
        self.assertEqual(
            opaque["[REDACTED:credential_grant_key]#1"], "operator evidence"
        )
        self.assertEqual(
            opaque["[REDACTED:credential_grant_key]"], "first leak"
        )
        self.assertEqual(
            opaque["[REDACTED:credential_grant_key]#2"], "second leak"
        )

    def test_bounded_json_reader_rejects_numeric_and_structural_pathologies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "report.json"
            payloads = {
                "huge-integer": '{"value":' + ("9" * 1000) + "}",
                "deep": json.dumps(
                    {
                        "value": "leaf",
                    }
                ).replace('"leaf"', "[" * 40 + '"leaf"' + "]" * 40),
                "many-nodes": json.dumps(
                    {"value": [0] * (full_run_module.MAX_JSON_NODES + 1)}
                ),
                "long-key": json.dumps(
                    {"k" * (full_run_module.MAX_JSON_KEY_CHARS + 1): "value"}
                ),
                "long-string": json.dumps(
                    {"value": "x" * (full_run_module.MAX_JSON_STRING_CHARS + 1)}
                ),
            }
            for name, payload in payloads.items():
                with self.subTest(name=name):
                    path.write_text(payload, encoding="utf-8")
                    with self.assertRaises(StorageError):
                        full_run_module._read_bounded_json_object(
                            path,
                            label="test report",
                        )

            path.write_text('{"value":"ok"}', encoding="utf-8")
            for parse_error in (ValueError("bounded parse"), RecursionError()):
                with self.subTest(parse_error=type(parse_error).__name__):
                    with mock.patch.object(
                        full_run_module.json,
                        "loads",
                        side_effect=parse_error,
                    ):
                        with self.assertRaises(StorageError):
                            full_run_module._read_bounded_json_object(
                                path,
                                label="test report",
                            )

        nested: object = "leaf"
        for _ in range(full_run_module.MAX_JSON_DEPTH + 5):
            nested = [nested]
        errors = validate_run_report({"nested": nested})
        self.assertTrue(any("depth budget" in error for error in errors), errors)


class FullRunGrokArgvTests(unittest.TestCase):
    def test_cancelled_terminal_stream_is_a_typed_failure(self) -> None:
        session_id = "11111111-1111-1111-1111-111111111111"
        cancelled = full_run_module.classify_grok_terminal_records(
            [
                json.dumps({"type": "thought", "data": "working"}),
                json.dumps(
                    {
                        "type": "end",
                        "stopReason": "Cancelled",
                        "sessionId": session_id,
                    }
                ),
            ],
            expected_session_id=session_id,
        )
        self.assertEqual(cancelled["code"], "grok_provider_cancelled")
        self.assertEqual(cancelled["stop_reason"], "Cancelled")

        max_turns = full_run_module.classify_grok_terminal_records(
            [
                json.dumps({"type": "max_turns_reached"}),
                json.dumps(
                    {
                        "type": "end",
                        "stopReason": "Cancelled",
                        "sessionId": session_id,
                    }
                ),
            ],
            expected_session_id=session_id,
        )
        self.assertEqual(max_turns["code"], "grok_max_turns_reached")

        refusal = full_run_module.classify_grok_terminal_records(
            [
                json.dumps(
                    {
                        "type": "end",
                        "stopReason": "Refusal",
                        "sessionId": session_id,
                    }
                )
            ],
            expected_session_id=session_id,
        )
        self.assertEqual(refusal["code"], "grok_provider_refusal")

        provider_error = full_run_module.classify_grok_terminal_records(
            [json.dumps({"type": "error", "errorType": "ProviderUnavailable"})],
            expected_session_id=session_id,
        )
        self.assertEqual(provider_error["code"], "grok_provider_error")
        self.assertEqual(provider_error["error_type"], "ProviderUnavailable")

        completed = full_run_module.classify_grok_terminal_records(
            [
                json.dumps(
                    {
                        "type": "end",
                        "stopReason": "EndTurn",
                        "sessionId": session_id,
                    }
                )
            ],
            expected_session_id=session_id,
        )
        self.assertIsNone(completed)

    def test_goal_canary_state_keeps_private_artifact_and_safe_evidence_across_resume(self) -> None:
        artifact = "/private/runtime/grok-goal-canary.json"
        evidence = "grok-goal-canary:v1:" + "a" * 24
        created = full_run_module.FullRunState(
            session_id="11111111-1111-1111-1111-111111111111",
            branch="feat/x",
            start_head="b" * 40,
            worktree="/tmp/worktree",
            packet_path="/tmp/packet.md",
            create_session=True,
            goal_behavioral_artifact_path=artifact,
            goal_behavioral_evidence=evidence,
            goal_mode_behaviorally_verified=True,
        )

        restored_create = full_run_module.FullRunState.from_dict(created.to_dict())
        self.assertTrue(restored_create.create_session)
        self.assertEqual(restored_create.goal_behavioral_artifact_path, artifact)
        self.assertEqual(restored_create.goal_behavioral_evidence, evidence)
        self.assertNotEqual(
            restored_create.goal_behavioral_artifact_path,
            restored_create.goal_behavioral_evidence,
        )

        restored_create.create_session = False
        restored_resume = full_run_module.FullRunState.from_dict(
            restored_create.to_dict()
        )
        self.assertFalse(restored_resume.create_session)
        self.assertEqual(restored_resume.goal_behavioral_artifact_path, artifact)
        self.assertEqual(restored_resume.goal_behavioral_evidence, evidence)

    def test_full_run_runtime_rejects_symlinked_store_root_without_outside_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            outside = root / "outside"
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            (repo / ".elves").symlink_to(outside, target_is_directory=True)
            packet = root / "packet.md"
            packet.write_text("fixture packet\n", encoding="utf-8")
            worker = root / "worker.py"
            worker.write_text("print('ok')\n", encoding="utf-8")
            head = _init_feature_repo(repo)
            with self.assertRaises(StorageError):
                prepare_full_run(
                    repo,
                    session_id="symlinked-runtime-root",
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    adapter="fixture",
                    fixture_script=worker,
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged\n")
            self.assertEqual(sorted(path.name for path in outside.iterdir()), ["sentinel.txt"])

    def test_prepare_output_keeps_supervision_token_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            packet = repo / "packet.md"
            packet.write_text("fixture packet\n", encoding="utf-8")
            worker = repo / "worker.py"
            worker.write_text("print('ok')\n", encoding="utf-8")
            head = _init_feature_repo(repo)
            prepared = prepare_full_run(
                repo,
                session_id="private-supervision-token",
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                adapter="fixture",
                fixture_script=worker,
            )
            private_state = load_state(repo, "private-supervision-token")
            self.assertTrue(private_state.supervision_token)
            self.assertNotIn("supervision_token", prepared["state"])
            self.assertNotIn(
                str(private_state.supervision_token),
                json.dumps(prepared, sort_keys=True),
            )

    def test_github_pull_ref_exemption_requires_exact_github_host(self) -> None:
        managed = full_run_module._github_provider_managed_ref
        self.assertTrue(managed("https://github.com/org/repo.git", "refs/pull/1/head"))
        self.assertTrue(managed("git@github.com:org/repo.git", "refs/pull/1/head"))
        self.assertFalse(managed("https://example.com/github.com/repo", "refs/pull/1/head"))
        self.assertFalse(managed("/tmp/github.com/repo.git", "refs/pull/1/head"))
        self.assertFalse(managed("file:///tmp/github.com/repo.git", "refs/pull/1/head"))
        self.assertFalse(managed("https://github.com/org/repo.git", "refs/heads/main"))

    def test_acceptance_parser_supports_canonical_markdown_and_json_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "packet.md"
            markdown.write_text(
                "B1-A9 is only an inline reference.\n"
                "- [ ] [B0-A1] bracketed staging criterion\n"
                "- [ ] B1-A1 — first observable criterion\n"
                "* M-A2: second observable criterion\n",
                encoding="utf-8",
            )
            self.assertEqual(
                full_run_module._staged_acceptance_ids(markdown),
                ["B0-A1", "B1-A1", "M-A2"],
            )
            self.assertEqual(
                full_run_module._staged_acceptance_criteria(markdown),
                [
                    ("B0-A1", "bracketed staging criterion"),
                    ("B1-A1", "first observable criterion"),
                    ("M-A2", "second observable criterion"),
                ],
            )
            json_packet = root / "packet.json"
            json_packet.write_text(
                json.dumps(
                    {
                        "acceptance": [
                            {"id": "B2-A1", "criterion": "JSON criterion"},
                            {"id": "B2-A2", "criterion": "another criterion"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                full_run_module._staged_acceptance_ids(json_packet),
                ["B2-A1", "B2-A2"],
            )
            self.assertEqual(
                full_run_module._staged_acceptance_criteria(json_packet),
                [
                    ("B2-A1", "JSON criterion"),
                    ("B2-A2", "another criterion"),
                ],
            )
            inline_only = root / "inline.md"
            inline_only.write_text("Report B3-A1 when complete.\n", encoding="utf-8")
            self.assertEqual(full_run_module._staged_acceptance_ids(inline_only), [])

    def test_acceptance_parser_reports_actionable_malformed_stable_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "packet.md"
            packet.write_text(
                "- [ ] B0-A1 criterion missing its separator\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._staged_acceptance_criteria(packet)

            self.assertEqual(ctx.exception.code, "full_run_acceptance_syntax")
            diagnostic = f"{ctx.exception.message} {ctx.exception.hint or ''}"
            self.assertIn("- [ ] B0-A1: <criterion>", diagnostic)
            self.assertIn("- [ ] [B0-A1] <criterion>", diagnostic)

    def test_prepare_rejects_plan_session_packet_drift_before_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            head = _init_feature_repo(repo)
            plan = repo / "plan.md"
            plan.write_text(
                "### Batch 0: Staging\n\n**Acceptance criteria:**\n"
                "- [ ] [B0-A1] Canonical staging criterion\n\n"
                "## Master Acceptance\n\n- [ ] M-A1: Canonical master criterion\n",
                encoding="utf-8",
            )
            session_path = repo / ".elves-session.json"
            session_path.write_text(
                json.dumps(
                    {
                        "plan_path": "plan.md",
                        "batches": [
                            {
                                "id": "B0",
                                "status": "pending",
                                "acceptance": [
                                    {
                                        "id": "B0-A1",
                                        "criterion": "Copied text drifted",
                                        "met": False,
                                        "evidence": "",
                                    }
                                ],
                            }
                        ],
                        "master_acceptance": [
                            {
                                "id": "M-A1",
                                "criterion": "Canonical master criterion",
                                "met": False,
                                "evidence": "",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            packet = repo / "packet.md"
            packet.write_text(
                "- [ ] B0-A1: Canonical staging criterion\n"
                "- [ ] [M-A1] Canonical master criterion\n",
                encoding="utf-8",
            )
            worker = root / "worker.py"
            worker.write_text("print('must not run')\n", encoding="utf-8")
            session_id = "acceptance-drift-before-state"

            with self.assertRaises(ValidationIssue) as ctx:
                prepare_full_run(
                    repo,
                    session_id=session_id,
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=session_path,
                    adapter="fixture",
                    fixture_script=worker,
                )

            self.assertEqual(
                ctx.exception.code,
                "full_run_acceptance_contract_mismatch",
            )
            self.assertIn("B0-A1", ctx.exception.message)
            self.assertFalse((full_run_root(repo, session_id) / "state.json").exists())

    def test_prepare_prioritizes_actionable_plan_row_syntax_before_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            head = _init_feature_repo(repo)
            plan = repo / "plan.md"
            plan.write_text(
                "### Batch 0: Staging\n\n**Acceptance criteria:**\n"
                "- [ ] B0-A1 criterion missing its separator\n",
                encoding="utf-8",
            )
            session_path = repo / ".elves-session.json"
            session_path.write_text(
                json.dumps(
                    {
                        "plan_path": "plan.md",
                        "batches": [
                            {
                                "id": "B0",
                                "status": "pending",
                                "acceptance": [],
                            }
                        ],
                        "master_acceptance": [],
                    }
                ),
                encoding="utf-8",
            )
            packet = repo / "packet.md"
            packet.write_text(
                "- [ ] B0-A1: criterion missing its separator\n"
                "- [ ] M-A1: Master criterion\n",
                encoding="utf-8",
            )
            worker = root / "worker.py"
            worker.write_text("print('must not run')\n", encoding="utf-8")
            session_id = "acceptance-syntax-before-state"

            with self.assertRaises(ValidationIssue) as ctx:
                prepare_full_run(
                    repo,
                    session_id=session_id,
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=session_path,
                    adapter="fixture",
                    fixture_script=worker,
                )

            self.assertEqual(
                ctx.exception.code,
                "full_run_acceptance_contract_invalid",
            )
            diagnostic = f"{ctx.exception.message} {ctx.exception.hint or ''}"
            self.assertIn("- [ ] B0-A1: <criterion>", diagnostic)
            self.assertIn("- [ ] [B0-A1] <criterion>", diagnostic)
            self.assertFalse((full_run_root(repo, session_id) / "state.json").exists())

    def test_launch_revalidates_bound_plan_session_packet_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            head = _init_feature_repo(repo)
            plan = repo / "plan.md"
            plan.write_text(
                "### Batch 0: Staging\n\n**Acceptance criteria:**\n"
                "- [ ] [B0-A1] Canonical staging criterion\n\n"
                "## Master Acceptance\n\n- [ ] M-A1: Canonical master criterion\n",
                encoding="utf-8",
            )
            session_path = repo / ".elves-session.json"
            session = {
                "plan_path": "plan.md",
                "batches": [
                    {
                        "id": "B0",
                        "status": "pending",
                        "acceptance": [
                            {
                                "id": "B0-A1",
                                "criterion": "Canonical staging criterion",
                                "met": False,
                                "evidence": "",
                            }
                        ],
                    }
                ],
                "master_acceptance": [
                    {
                        "id": "M-A1",
                        "criterion": "Canonical master criterion",
                        "met": False,
                        "evidence": "",
                    }
                ],
            }
            session_path.write_text(json.dumps(session), encoding="utf-8")
            packet = repo / "packet.md"
            packet.write_text(
                "- [ ] B0-A1: Canonical staging criterion\n"
                "- [ ] [M-A1] Canonical master criterion\n",
                encoding="utf-8",
            )
            worker = root / "worker.py"
            worker.write_text("print('must not run')\n", encoding="utf-8")
            session_id = "acceptance-drift-before-launch"
            prepare_full_run(
                repo,
                session_id=session_id,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                session_path=session_path,
                adapter="fixture",
                fixture_script=worker,
            )
            session["batches"][0]["acceptance"][0]["criterion"] = "Later drift"
            session_path.write_text(json.dumps(session), encoding="utf-8")

            with mock.patch("cobbler_runtime.full_run.subprocess.Popen") as popen:
                with self.assertRaises(ValidationIssue) as ctx:
                    launch_full_run(repo, session_id=session_id)

            self.assertEqual(
                ctx.exception.code,
                "full_run_acceptance_contract_mismatch",
            )
            popen.assert_not_called()

    def test_prepare_binds_private_packet_copy_and_launch_rejects_source_or_copy_drift(
        self,
    ) -> None:
        for mutation in ("source", "copy"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo = root / "repo"
                repo.mkdir()
                packet = root / "packet.md"
                packet.write_text("- B1-A1 — exact criterion\n", encoding="utf-8")
                worker = root / "worker.py"
                worker.write_text("print('should not run')\n", encoding="utf-8")
                head = _init_feature_repo(repo)
                session = f"packet-drift-{mutation}"
                prepare_full_run(
                    repo,
                    session_id=session,
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    adapter="fixture",
                    fixture_script=worker,
                )
                state = load_state(repo, session)
                self.assertEqual(
                    state.acceptance_criteria,
                    {"B1-A1": "exact criterion"},
                )
                self.assertEqual(
                    Path(state.staged_packet_path or "").read_bytes(),
                    packet.read_bytes(),
                )
                self.assertEqual(
                    state.packet_sha256,
                    hashlib.sha256(packet.read_bytes()).hexdigest(),
                )
                target = (
                    packet
                    if mutation == "source"
                    else Path(state.staged_packet_path or "")
                )
                target.write_text("- B1-A1 — changed criterion\n", encoding="utf-8")
                with mock.patch("cobbler_runtime.full_run.subprocess.Popen") as popen:
                    with self.assertRaises(ValidationIssue) as ctx:
                        launch_full_run(repo, session_id=session)
                self.assertEqual(
                    ctx.exception.code,
                    (
                        "full_run_packet_source_changed"
                        if mutation == "source"
                        else "full_run_staged_packet_changed"
                    ),
                )
                popen.assert_not_called()

    def test_provider_reads_supervisor_snapshot_after_staged_path_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            original = b"- B1-A1 -- exact delayed-read criterion\n"
            packet.write_bytes(original)
            worker = root / "delayed-packet-reader.py"
            worker.write_text(
                "import os, sys, time\n"
                "from pathlib import Path\n"
                "worktree = Path(os.environ['ELVES_FULL_RUN_WORKTREE'])\n"
                "packet = Path(sys.argv[-1])\n"
                "(worktree / 'packet-reader-started').write_text(str(packet), encoding='utf-8')\n"
                "time.sleep(0.35)\n"
                "(worktree / 'packet-reader-observed').write_bytes(packet.read_bytes())\n",
                encoding="utf-8",
            )
            head = _init_feature_repo(repo)
            session = "packet-post-launch-mutation"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                adapter="fixture",
                fixture_script=worker,
            )
            state = load_state(repo, session)
            launch_full_run(repo, session_id=session)
            started = repo / "packet-reader-started"
            observed = repo / "packet-reader-observed"
            deadline = time.time() + 5
            while not started.exists() and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(started.exists())
            self.assertTrue(started.read_text(encoding="utf-8").startswith("/dev/fd/"))

            # Same-user in-place mutation after launch cannot affect the
            # provider's inherited, anonymous read-only packet snapshot.
            Path(state.staged_packet_path or "").write_bytes(
                b"- B1-A1 -- attacker-controlled changed criterion\n"
            )
            while not observed.exists() and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(observed.exists())
            self.assertEqual(observed.read_bytes(), original)

            for _ in range(100):
                status = monitor_full_run(repo, session_id=session)
                if status["state"] != "healthy":
                    break
                time.sleep(0.01)
            self.assertNotEqual(status["state"], "healthy")

    def test_supervisor_rejects_staged_packet_mutation_before_provider_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = root / "staged-packet.md"
            packet.write_text("original bound packet\n", encoding="utf-8")
            provider_ran = root / "provider-ran"
            provider = root / "provider.py"
            provider.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                f"Path({str(provider_ran)!r}).touch()\n",
                encoding="utf-8",
            )
            provider.chmod(0o700)
            (root / "supervisor.fingerprint.json").write_text(
                '{"pid":1}\n', encoding="utf-8"
            )
            state = full_run_module.FullRunState(
                session_id="packet-supervisor-recheck",
                branch="feat/x",
                start_head="a" * 40,
                worktree=str(root),
                packet_path=str(packet),
                supervision_token="c" * 48,
            )
            supervisor_argv = full_run_module._provider_supervisor_argv(
                root=root,
                session_id=state.session_id,
                provider_argv=[str(provider), str(packet)],
                attempt=state.attempt,
                supervisor_executable=str(
                    full_run_module._qualified_process_supervisor()
                ),
                **_packet_binding_kwargs(packet),
            )
            proc = subprocess.Popen(
                supervisor_argv,
                cwd=root,
                env={
                    "PATH": os.environ.get("PATH") or os.defpath,
                    "ELVES_FULL_RUN_SUPERVISION_MARKER": (
                        full_run_module._descendant_supervision_marker(state)
                    ),
                },
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            packet.write_text("changed after supervisor spawn\n", encoding="utf-8")
            proc.communicate(
                (str(state.supervision_token) + "\n").encode("ascii"), timeout=5
            )
            record = json.loads(
                (root / "exit_record.json").read_text(encoding="utf-8")
            )
            self.assertEqual(proc.returncode, 125)
            self.assertFalse(provider_ran.exists())
            self.assertIsNone(record["provider_pid"])
            self.assertEqual(
                record["supervision_error"], "staged_packet_binding_mismatch"
            )

    def test_complete_report_criterion_text_is_bound_for_markdown_and_json_packets(
        self,
    ) -> None:
        for packet_format in ("markdown", "json"):
            with self.subTest(packet_format=packet_format), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo = root / "repo"
                repo.mkdir()
                head = _init_feature_repo(repo)
                _attach_origin(repo, root / "origin.git", "feat/x")
                packet = root / ("packet.json" if packet_format == "json" else "packet.md")
                if packet_format == "json":
                    packet.write_text(
                        json.dumps(
                            {
                                "acceptance": [
                                    {"id": "B1-A1", "criterion": "exact criterion"},
                                    {"id": "M-A1", "criterion": "master criterion"},
                                ]
                            }
                        ),
                        encoding="utf-8",
                    )
                else:
                    packet.write_text(
                        "- B1-A1 — exact criterion\n"
                        "- [M-A1] master criterion\n",
                        encoding="utf-8",
                    )
                session = f"criterion-binding-{packet_format}"
                prepare_full_run(
                    repo,
                    session_id=session,
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=_write_production_acceptance_contract(repo, packet),
                    adapter="grok-build",
                    executable="grok",
                )
                baseline = json.loads(
                    (full_run_root(repo, session) / "report.json").read_text(
                        encoding="utf-8"
                    )
                )
                report = {
                    **baseline,
                    "final_head": head,
                    "status": "complete",
                    "batches": [
                        {"id": "batch-1", "status": "complete", "evidence": head}
                    ],
                    "acceptance": [
                        {
                            "id": "B1-A1",
                            "criterion": "altered criterion",
                            "met": True,
                            "evidence": head,
                        },
                        {
                            "id": "M-A1",
                            "criterion": "master criterion",
                            "met": True,
                            "evidence": head,
                        },
                    ],
                    "commits": [head],
                }
                with self.assertRaises(ValidationIssue) as ctx:
                    write_report(repo, session, report)
                self.assertEqual(ctx.exception.code, "full_run_report_invalid")
                self.assertIn("criterion text mismatch", ctx.exception.message)

                report["acceptance"][0]["criterion"] = "exact criterion"
                self.assertTrue(write_report(repo, session, report).is_file())

    def test_pre_binding_state_remains_readable_but_launch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            packet.write_text("fixture packet\n", encoding="utf-8")
            worker = root / "worker.py"
            worker.write_text("print('should not run')\n", encoding="utf-8")
            head = _init_feature_repo(repo)
            session = "legacy-packet-state"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                adapter="fixture",
                fixture_script=worker,
            )
            state_path = full_run_root(repo, session) / "state.json"
            legacy = json.loads(state_path.read_text(encoding="utf-8"))
            for key in (
                "staged_packet_path",
                "staged_packet_identity",
                "packet_sha256",
                "packet_size",
                "packet_contract_sha256",
                "acceptance_criteria",
            ):
                legacy.pop(key, None)
            state_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
            self.assertEqual(load_state(repo, session).session_id, session)
            with mock.patch("cobbler_runtime.full_run.subprocess.Popen") as popen:
                with self.assertRaises(ValidationIssue) as ctx:
                    launch_full_run(repo, session_id=session)
            self.assertEqual(ctx.exception.code, "full_run_packet_binding_missing")
            popen.assert_not_called()

    def test_legacy_production_state_without_acceptance_binding_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet)
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            session = "legacy-production-acceptance-binding"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                session_path=_write_production_acceptance_contract(repo, packet),
                adapter="grok-build",
                executable="grok",
            )
            state_path = full_run_root(repo, session) / "state.json"
            legacy = json.loads(state_path.read_text(encoding="utf-8"))
            for key in (
                "acceptance_plan_path",
                "acceptance_plan_sha256",
                "acceptance_session_path",
                "acceptance_session_sha256",
                "acceptance_contract_sha256",
            ):
                legacy.pop(key, None)
            state_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

            self.assertEqual(load_state(repo, session).session_id, session)
            with mock.patch("cobbler_runtime.full_run.subprocess.Popen") as popen:
                with self.assertRaises(ValidationIssue) as ctx:
                    launch_full_run(repo, session_id=session)
            self.assertEqual(
                ctx.exception.code,
                "full_run_acceptance_contract_binding_missing",
            )
            popen.assert_not_called()

    def test_acceptance_packet_reader_rejects_unsafe_or_oversized_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oversized = root / "large.md"
            oversized.write_bytes(b"x" * (full_run_module.MAX_PACKET_BYTES + 1))
            with self.assertRaises(ValidationIssue):
                full_run_module._staged_acceptance_ids(oversized)

            target = root / "target.md"
            target.write_text("- B1-A1 — criterion\n", encoding="utf-8")
            link = root / "link.md"
            link.symlink_to(target)
            with self.assertRaises(ValidationIssue):
                full_run_module._staged_acceptance_ids(link)

            if hasattr(os, "mkfifo"):
                fifo = root / "packet.fifo"
                os.mkfifo(fifo)
                with self.assertRaises(ValidationIssue):
                    full_run_module._staged_acceptance_ids(fifo)

    def test_acceptance_packet_ignores_narrative_bullet_id_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "packet.md"
            packet.write_text(
                "- [B0-A1] Exact staging criterion.\n"
                "- The worker must report B0-A1 unchanged in final JSON.\n",
                encoding="utf-8",
            )

            self.assertEqual(
                full_run_module._staged_acceptance_criteria(packet),
                [("B0-A1", "Exact staging criterion.")],
            )

    def test_acceptance_json_packet_rejects_deep_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "packet.json"
            depth = full_run_module.MAX_JSON_DEPTH + 2
            packet.write_text(
                '{"acceptance":[],"nested":'
                + "[" * depth
                + "null"
                + "]" * depth
                + "}\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._staged_acceptance_criteria(packet)
            self.assertEqual(ctx.exception.code, "full_run_packet_invalid_json")

    def test_production_rejects_missing_and_duplicate_acceptance_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            cases = (
                (
                    "missing",
                    "- The worker must report B1-A1 unchanged in final JSON.\n",
                    "full_run_acceptance_ids_required",
                ),
                (
                    "duplicate",
                    "- B1-A1 — first\n- B1-A1 — repeated\n",
                    "full_run_acceptance_ids_duplicate",
                ),
            )
            for name, content, expected_code in cases:
                with self.subTest(name=name):
                    packet = root / f"{name}.md"
                    packet.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValidationIssue) as ctx:
                        prepare_full_run(
                            repo,
                            session_id=f"acceptance-{name}",
                            branch="feat/x",
                            start_head=head,
                            worktree=repo,
                            packet_path=packet,
                            adapter="grok-build",
                            executable="grok",
                        )
                    self.assertEqual(ctx.exception.code, expected_code)

    def test_production_prepare_requires_canonical_session_in_core(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet)
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")

            with self.assertRaises(ValidationIssue) as ctx:
                prepare_full_run(
                    repo,
                    session_id="production-session-required",
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    adapter="grok-build",
                    executable="grok",
                )

            self.assertEqual(
                ctx.exception.code,
                "full_run_acceptance_session_required",
            )
            self.assertFalse(
                (
                    full_run_root(repo, "production-session-required")
                    / "state.json"
                ).exists()
            )

    def test_production_prepare_rejects_deep_session_before_state_creation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet)
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            session_path = _write_production_acceptance_contract(repo, packet)
            depth = full_run_module.MAX_JSON_DEPTH + 2
            session_path.write_text(
                '{"plan_path":"plan.md","batches":[],"master_acceptance":[],'
                '"nested":'
                + "[" * depth
                + "null"
                + "]" * depth
                + "}\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValidationIssue) as ctx:
                prepare_full_run(
                    repo,
                    session_id="production-deep-session",
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=session_path,
                    adapter="grok-build",
                    executable="grok",
                )

            self.assertEqual(
                ctx.exception.code,
                "full_run_acceptance_session_invalid",
            )
            self.assertFalse(
                (full_run_root(repo, "production-deep-session") / "state.json").exists()
            )

    def test_production_prepare_rejects_master_only_acceptance_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet, "M-A1")
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            session_path = _write_production_acceptance_contract(repo, packet)

            with self.assertRaises(ValidationIssue) as ctx:
                prepare_full_run(
                    repo,
                    session_id="production-master-only",
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=session_path,
                    adapter="grok-build",
                    executable="grok",
                )

            self.assertEqual(
                ctx.exception.code,
                "full_run_acceptance_contract_invalid",
            )
            self.assertFalse(
                (full_run_root(repo, "production-master-only") / "state.json").exists()
            )

    def test_production_requires_origin_and_clean_bound_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet)
            head = _init_feature_repo(repo)
            with self.assertRaises(ValidationIssue) as ctx:
                prepare_full_run(
                    repo,
                    session_id="prod-no-origin",
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=_write_production_acceptance_contract(repo, packet),
                    adapter="grok-build",
                    executable="grok",
                )
            self.assertEqual(ctx.exception.code, "full_run_origin_required")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet)
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                prepare_full_run(
                    repo,
                    session_id="prod-dirty",
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=_write_production_acceptance_contract(repo, packet),
                    adapter="grok-build",
                    executable="grok",
                )
            self.assertEqual(ctx.exception.code, "full_run_worktree_dirty")

    def test_production_launch_rechecks_cleanliness_and_origin_config(self) -> None:
        for mutation in ("dirty", "origin"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo = root / "repo"
                repo.mkdir()
                packet = root / "packet.md"
                _write_production_packet(packet)
                head = _init_feature_repo(repo)
                _attach_origin(repo, root / "origin.git", "feat/x")
                prepare_full_run(
                    repo,
                    session_id=f"prod-launch-{mutation}",
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=_write_production_acceptance_contract(repo, packet),
                    adapter="grok-build",
                    executable="grok",
                )
                if mutation == "dirty":
                    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
                    expected = "full_run_worktree_dirty"
                else:
                    subprocess.run(
                        ["git", "-C", str(repo), "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/changed/*"],
                        check=True,
                    )
                    expected = "full_run_origin_binding_changed"
                with self.assertRaises(ValidationIssue) as ctx:
                    launch_full_run(repo, session_id=f"prod-launch-{mutation}")
                self.assertEqual(ctx.exception.code, expected)

    @mock.patch("cobbler_runtime.full_run._run_supervision_canary", return_value=True)
    def test_grok_create_and_resume_argv(self, _canary) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            packet = repo / "packet.md"
            _write_production_packet(packet)
            start_head = _init_feature_repo(repo)
            remote = Path(tmp) / "origin.git"
            subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True)
            subprocess.run(["git", "-C", str(repo), "push", "-q", "-u", "origin", "feat/x"], check=True)
            worktree = repo
            prep = prepare_full_run(
                repo,
                session_id="11111111-1111-1111-1111-111111111111",
                branch="feat/x",
                start_head=start_head,
                worktree=worktree,
                packet_path=packet,
                session_path=_write_production_acceptance_contract(repo, packet),
                adapter="grok-build",
                model="grok-4.5",
                permission_mode="auto",
                executable="grok",
                create=True,
                check=True,
            )
            self.assertTrue(prep["ok"])
            state = load_state(repo, "11111111-1111-1111-1111-111111111111")
            argv = build_full_run_argv(state)
            self.assertEqual(argv[0], "grok")
            self.assertIn("--session-id", argv)
            self.assertIn("11111111-1111-1111-1111-111111111111", argv)
            self.assertIn("--prompt-file", argv)
            self.assertIn(str(state.staged_packet_path), argv)
            self.assertNotIn(str(packet), argv)
            self.assertIn("--cwd", argv)
            self.assertIn("--model", argv)
            self.assertIn("grok-4.5", argv)
            self.assertNotIn("--permission-mode", argv)
            self.assertIn("--always-approve", argv)
            self.assertNotIn("--yolo", argv)
            self.assertIn("--effort", argv)
            self.assertEqual(argv[argv.index("--effort") + 1], "high")
            self.assertIn("--max-turns", argv)
            self.assertIn("--output-format", argv)
            self.assertIn("streaming-json", argv)
            self.assertIn("--check", argv)
            self.assertNotIn("--new-session", argv)
            self.assertNotIn("--goal", argv)
            self.assertNotIn("--resume", argv)

            goal_path = full_run_module._prepare_goal_prompt(repo, full_run_root(repo, state.session_id), state)
            state.goal_mode_behaviorally_verified = True
            goal_argv = build_full_run_argv(state)
            self.assertEqual(goal_argv[goal_argv.index("--prompt-file") + 1], str(goal_path))
            self.assertTrue(goal_path.read_text(encoding="utf-8").startswith("/goal "))
            self.assertEqual(state.goal_launch_mode, "headless_slash_goal")
            self.assertNotIn("--goal", goal_argv)
            state.create_session = False
            resume_goal_path = full_run_module._prepare_goal_prompt(
                repo, full_run_root(repo, state.session_id), state
            )
            resume_argv = build_full_run_argv(state)
            self.assertIn("--resume", resume_argv)
            self.assertNotIn("--session-id", resume_argv)
            self.assertEqual(
                resume_argv[resume_argv.index("--prompt-file") + 1],
                str(resume_goal_path),
            )
            self.assertEqual(
                resume_goal_path.read_text(encoding="utf-8"),
                "/goal resume\n",
            )

    def test_devin_create_and_resume_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            packet = repo / "packet.md"
            _write_production_packet(packet)
            start_head = _init_feature_repo(repo)
            remote = Path(tmp) / "origin.git"
            devin_env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith("GIT_CONFIG_KEY_") and not k.startswith("GIT_CONFIG_VALUE_")
            }
            devin_env["GIT_CONFIG_COUNT"] = "0"
            with mock.patch.dict(os.environ, devin_env, clear=True):
                _attach_origin(repo, remote, "feat/x")
                prep = prepare_full_run(
                    repo,
                    session_id="22222222-2222-2222-2222-222222222222",
                    branch="feat/x",
                    start_head=start_head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=_write_production_acceptance_contract(repo, packet),
                    adapter="devin-cli",
                    executable="devin",
                )
            self.assertTrue(prep["ok"])
            state = load_state(repo, "22222222-2222-2222-2222-222222222222")
            create_argv = build_full_run_argv(state)
            self.assertEqual(create_argv[0], "devin")
            self.assertIn("--prompt-file", create_argv)
            self.assertIn("--print", create_argv)
            self.assertNotIn("--session-id", create_argv)
            self.assertNotIn("--resume", create_argv)
            self.assertIn("swe-1-7-lightning", create_argv)
            state.create_session = False
            state.provider_session_id = "devin-sess-resume"
            resume_argv = build_full_run_argv(state)
            self.assertIn("--resume", resume_argv)
            index = resume_argv.index("--resume")
            self.assertEqual(resume_argv[index + 1], "devin-sess-resume")
            self.assertIn("--print", resume_argv)
            self.assertNotIn("--session-id", resume_argv)
            self.assertIn("--prompt-file", resume_argv)

    def test_production_grok_launch_fails_before_spawn_without_explicit_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet)
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            prepare_full_run(
                repo,
                session_id="auth-required-before-spawn",
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                session_path=_write_production_acceptance_contract(repo, packet),
                adapter="grok-build",
                executable=sys.executable,
            )
            with mock.patch.dict(os.environ, {}, clear=False):
                for name in ("XAI_API_KEY", "GROK_API_KEY", "OPENAI_API_KEY"):
                    os.environ.pop(name, None)
                with mock.patch.object(
                    full_run_module, "open_repo_text", wraps=full_run_module.open_repo_text
                ) as open_mock:
                    with self.assertRaises(ValidationIssue) as ctx:
                        launch_full_run(
                            repo, session_id="auth-required-before-spawn"
                        )
            self.assertEqual(ctx.exception.code, "full_run_grok_auth_required")
            self.assertFalse(open_mock.called)

    def test_failed_oauth_launch_preserves_canonical_auth_without_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet)
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            native_grok = _compile_native_grok_launcher(
                root,
                "print('grok 0.2.93 (test)')\n",
                name="failed-launch-native-grok",
            )
            session = "11111111-1111-4111-8111-111111111101"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                session_path=_write_production_acceptance_contract(repo, packet),
                adapter="grok-build",
                executable=str(native_grok),
            )
            host_home = root / "host-home"
            auth = host_home / ".grok" / "auth.json"
            auth.parent.mkdir(parents=True)
            auth.write_text(
                json.dumps({"account": {"key": "test-access"}}), encoding="utf-8"
            )
            auth.chmod(0o600)
            original = auth.read_bytes()
            with mock.patch.dict(os.environ, {"HOME": str(host_home)}, clear=False):
                with mock.patch.object(provider_auth_module, "_assert_grok_auth_path_capability",
                    return_value=(0, 2, 93),
                ), mock.patch(
                    "cobbler_runtime.worker_routing.probe_grok_capabilities",
                    return_value=_proven_test_grok_capabilities(),
                ), mock.patch.object(
                    full_run_module,
                    "open_repo_text",
                    side_effect=OSError("synthetic transcript failure"),
                ):
                    with self.assertRaises(OSError):
                        launch_full_run(
                            repo,
                            session_id=session,
                            grant_grok_auth=True,
                        )
            self.assertEqual(auth.read_bytes(), original)
            self.assertFalse(
                (full_run_root(repo, session) / full_run_module.GROK_HOME_REL / "auth.json").exists()
            )

    def test_refused_oauth_launch_never_strands_auth_across_boundaries(self) -> None:
        failure_points = ("stale_artifact", "directory_setup", "state_save")
        for failure_point in failure_points:
            with self.subTest(failure_point=failure_point), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo = root / "repo"
                repo.mkdir()
                packet = root / "packet.md"
                _write_production_packet(packet)
                head = _init_feature_repo(repo)
                _attach_origin(repo, root / "origin.git", "feat/x")
                native_grok = _compile_native_grok_launcher(
                    root,
                    "print('grok 0.2.93 (test)')\n",
                    name="refused-launch-native-grok",
                )
                session = f"oauth-cleanup-{failure_point}"
                prepare_full_run(
                    repo,
                    session_id=session,
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    session_path=_write_production_acceptance_contract(repo, packet),
                    adapter="grok-build",
                    executable=str(native_grok),
                )
                run_root = full_run_root(repo, session)
                host_home = root / "host-home"
                auth = host_home / ".grok" / "auth.json"
                auth.parent.mkdir(parents=True)
                auth.write_text(
                    json.dumps({"account": {"key": "test-access"}}),
                    encoding="utf-8",
                )
                auth.chmod(0o600)

                patches: list[mock._patch] = []
                if failure_point == "stale_artifact":
                    stale = run_root / "exit_record.json"
                    stale.write_text("{}\n", encoding="utf-8")
                    stale.chmod(0o600)
                elif failure_point == "directory_setup":
                    original_ensure = full_run_module.ensure_private_dir

                    def fail_directory(path: Path, **kwargs: object) -> Path:
                        if Path(path).name == ".cache":
                            raise OSError("synthetic directory failure")
                        return original_ensure(path, **kwargs)

                    patches.append(
                        mock.patch.object(
                            full_run_module,
                            "ensure_private_dir",
                            side_effect=fail_directory,
                        )
                    )
                else:
                    patches.append(
                        mock.patch.object(
                            full_run_module,
                            "save_state",
                            side_effect=OSError("synthetic state failure"),
                        )
                    )

                original = auth.read_bytes()
                with mock.patch.dict(os.environ, {"HOME": str(host_home)}, clear=False), mock.patch.object(provider_auth_module, "_assert_grok_auth_path_capability",
                    return_value=(0, 2, 93),
                ):
                    for patcher in patches:
                        patcher.start()
                    try:
                        with self.assertRaises((OSError, ValidationIssue)):
                            launch_full_run(
                                repo,
                                session_id=session,
                                grant_grok_auth=True,
                            )
                    finally:
                        for patcher in reversed(patches):
                            patcher.stop()
                self.assertEqual(auth.read_bytes(), original)
                self.assertFalse((run_root / full_run_module.GROK_HOME_REL / "auth.json").exists())

    def test_live_shared_oauth_rotation_survives_monitor_report_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet)
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            grok = _compile_native_grok_launcher(
                root,
                GROK_ROTATE_AUTH_AND_WAIT,
                name="fake-grok",
            )
            session = "11111111-1111-4111-8111-111111111102"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                session_path=_write_production_acceptance_contract(repo, packet),
                adapter="grok-build",
                executable=str(grok),
            )
            host_home = root / "host-home"
            auth = host_home / ".grok" / "auth.json"
            auth.parent.mkdir(parents=True)
            auth.write_text(
                json.dumps(
                    {
                        "account": {
                            "key": "initial-access",
                            "refresh_token": "initial-refresh",
                        }
                    }
                ),
                encoding="utf-8",
            )
            auth.chmod(0o600)
            with mock.patch.dict(os.environ, {"HOME": str(host_home)}, clear=False):
                with mock.patch(
                    "cobbler_runtime.worker_routing.probe_grok_capabilities",
                    return_value=_proven_test_grok_capabilities(),
                ):
                    launched = launch_full_run(
                        repo, session_id=session, grant_grok_auth=True
                    )
            try:
                deadline = time.time() + 4
                payload: dict[str, object] = {}
                while time.time() < deadline:
                    payload = json.loads(auth.read_text(encoding="utf-8"))
                    if "provider-rotated-refresh" in json.dumps(payload):
                        break
                    time.sleep(0.02)
                self.assertIn("provider-rotated-refresh", json.dumps(payload))
                state = load_state(repo, session)
                self.assertEqual(
                    state.grok_executable_identity["security_profile"],
                    "shared_oauth_native",
                )
                self.assertTrue(state.grok_executable_identity["parent_chain"])
                report = full_run_module._running_report(state, final_head=head)
                self.assertTrue(write_report(repo, session, report).is_file())
                observed = monitor_full_run(repo, session_id=session)
                self.assertEqual(observed["state"], "healthy", observed)
                self.assertNotIn(str(auth), json.dumps(launched, sort_keys=True))
                self.assertNotIn(str(auth), json.dumps(observed, sort_keys=True))
                self.assertFalse(
                    (
                        full_run_root(repo, session)
                        / full_run_module.GROK_HOME_REL
                        / "auth.json"
                    ).exists()
                )
            finally:
                stopped = stop_full_run(repo, session_id=session, grace_seconds=1.0)
                self.assertTrue(stopped["ok"], stopped)
            self.assertIn(
                "provider-rotated-refresh", auth.read_text(encoding="utf-8")
            )

    def test_post_handoff_interrupt_preserves_durable_stop_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = repo / "packet.md"
            packet.write_text("fixture packet\n", encoding="utf-8")
            marker = root / "provider.pid"
            worker = root / "provider.py"
            worker.write_text(
                "import os,time\n"
                f"_t = {str(marker)!r} + '.tmp'\n"
                f"open(_t, 'w').write(str(os.getpid()))\n"
                f"os.replace(_t, {str(marker)!r})\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            head = _init_feature_repo(repo)
            session = "post-handoff-interrupt"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                adapter="fixture",
                fixture_script=worker,
            )
            real_handoff = full_run_module._handoff_supervision_secret

            def handoff_then_interrupt(proc: object, state: object) -> None:
                real_handoff(proc, state)
                deadline = time.time() + 3
                while not marker.exists() and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                raise KeyboardInterrupt("synthetic post-transfer interrupt")

            with mock.patch.object(
                full_run_module,
                "_handoff_supervision_secret",
                side_effect=handoff_then_interrupt,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    launch_full_run(repo, session_id=session)

            durable = load_state(repo, session)
            self.assertEqual(durable.status, "healthy")
            self.assertIsNotNone(durable.pid)
            self.assertIsNotNone(durable.fingerprint)
            provider_pid = int(marker.read_text(encoding="utf-8"))
            self.assertTrue(full_run_module._pid_alive(provider_pid))
            stopped = stop_full_run(repo, session_id=session, grace_seconds=1.0)
            self.assertTrue(stopped["ok"], stopped)
            deadline = time.time() + 2
            while full_run_module._pid_alive(provider_pid) and time.time() < deadline:
                time.sleep(0.02)
            self.assertFalse(full_run_module._pid_alive(provider_pid))

    def test_pretransfer_handoff_failures_roll_back_to_relaunchable_state(self) -> None:
        for failure_point in (
            "before_payload",
            "dead_before_write",
            "partial_keyboard_interrupt",
        ):
            with self.subTest(failure_point=failure_point), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo = root / "repo"
                repo.mkdir()
                packet = repo / "packet.md"
                packet.write_text("fixture packet\n", encoding="utf-8")
                worker = root / "provider.py"
                worker.write_text("print('should not start')\n", encoding="utf-8")
                head = _init_feature_repo(repo)
                session = f"pretransfer-{failure_point}"
                prepare_full_run(
                    repo,
                    session_id=session,
                    branch="feat/x",
                    start_head=head,
                    worktree=repo,
                    packet_path=packet,
                    adapter="fixture",
                    fixture_script=worker,
                )
                real_handoff = full_run_module._handoff_supervision_secret

                def fail_before_transfer(proc: object, state: object) -> None:
                    if failure_point == "before_payload":
                        with mock.patch.object(full_run_module, "_supervision_secret",
                            side_effect=KeyboardInterrupt(
                                "synthetic pre-payload interrupt"
                            ),
                        ):
                            real_handoff(proc, state)
                        return
                    if failure_point == "dead_before_write":
                        proc.kill()
                        proc.wait(timeout=1.0)
                        real_handoff(proc, state)
                        return
                    real_write = os.write
                    calls = 0

                    def partial_then_interrupt(fd: int, data: bytes) -> int:
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            return real_write(fd, data[:5])
                        raise KeyboardInterrupt("synthetic partial handoff")

                    with mock.patch.object(
                        full_run_module.os,
                        "write",
                        side_effect=partial_then_interrupt,
                    ):
                        real_handoff(proc, state)

                with mock.patch.object(
                    full_run_module,
                    "_handoff_supervision_secret",
                    side_effect=fail_before_transfer,
                ):
                    with self.assertRaises(full_run_module._PreTransferHandoffError):
                        launch_full_run(repo, session_id=session)

                durable = load_state(repo, session)
                self.assertEqual(durable.status, "pending")
                self.assertEqual(durable.next_action, "launch")
                self.assertIsNone(durable.pid)
                self.assertIsNone(durable.pgid)
                self.assertIsNone(durable.fingerprint)
                self.assertIsNone(durable.launched_at)
                run_root = full_run_root(repo, session)
                self.assertFalse((run_root / "supervisor.fingerprint.json").exists())
                self.assertFalse((run_root / "worker.fingerprint.json").exists())

    def test_monitor_reaps_dead_child_without_deleting_shared_oauth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = repo / "packet.md"
            packet.write_text("fixture packet\n", encoding="utf-8")
            marker = root / "provider.pid"
            worker = root / "provider.py"
            worker.write_text(
                "import os,time\n"
                f"_t = {str(marker)!r} + '.tmp'\n"
                f"open(_t, 'w').write(str(os.getpid()))\n"
                f"os.replace(_t, {str(marker)!r})\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            head = _init_feature_repo(repo)
            session = "abnormal-oauth-zombie-cleanup"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                adapter="fixture",
                fixture_script=worker,
            )
            host_home = root / "host-home"
            auth = host_home / ".grok" / "auth.json"
            auth.parent.mkdir(parents=True)
            auth.write_text(
                json.dumps({"account": {"refresh_token": "test-refresh"}}),
                encoding="utf-8",
            )
            auth.chmod(0o600)
            state = load_state(repo, session)
            _raw, identity = full_run_module._read_host_grok_auth(
                {"HOME": str(host_home)}
            )
            state.grok_auth_strategy = "oauth_shared_file"
            state.grok_auth_path_identity = identity
            full_run_module.save_state(repo, state)
            original = auth.read_bytes()

            with mock.patch.dict(os.environ, {"HOME": str(host_home)}, clear=False):
                launched = launch_full_run(repo, session_id=session)
                deadline = time.time() + 3
                while not marker.exists() and time.time() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                provider_pid = int(marker.read_text(encoding="utf-8"))
                supervisor_pid = int(launched["pid"])
                os.kill(provider_pid, signal.SIGKILL)
                os.kill(supervisor_pid, signal.SIGKILL)
                time.sleep(0.05)
                observed = monitor_full_run(repo, session_id=session)

            self.assertEqual(auth.read_bytes(), original)
            self.assertEqual(observed["state"], "failed")
            self.assertEqual(observed["next_action"], "driver_wake_error")
            self.assertFalse(observed["check_summary"]["group_alive"])

    def test_env_grants_by_name_not_values_on_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            packet = repo / "p.md"
            packet.write_text("x\n")
            start_head = _init_feature_repo(repo)
            wt = repo
            prepare_full_run(
                repo,
                session_id="sess-env-1",
                branch="feat/x",
                start_head=start_head,
                worktree=wt,
                packet_path=packet,
                adapter="fixture",
                fixture_script=repo / "noop.py",
            )
            (repo / "noop.py").write_text("print('ok')\n")
            state = load_state(repo, "sess-env-1")
            root = full_run_root(repo, "sess-env-1")
            parent = {
                "PATH": "/bin",
                "XAI_API_KEY": "grant-secret",
                "OPENAI_API_KEY": "other-secret",
                "UNRELATED_SENTINEL": "should-not-appear",
                "HOME": "/host-home",
                "GROK_AUTH_PATH": "/host-home/.grok/auth.json",
                "TMPDIR": "/host-tmp",
                "XDG_CONFIG_HOME": "/host-config",
                "HTTPS_PROXY": "https://proxy-user:proxy-secret@example.invalid",
            }
            env = build_full_run_env(
                state=state,
                root=root,
                parent_env=parent,
                credential_grant_names=["XAI_API_KEY"],
            )
            self.assertEqual(env.get("XAI_API_KEY"), "grant-secret")
            self.assertNotIn("UNRELATED_SENTINEL", env)
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertEqual(env["HOME"], str(root / "worker-home"))
            self.assertEqual(env["TMPDIR"], str(root / "worker-tmp"))
            self.assertEqual(env["XDG_CONFIG_HOME"], str(root / "worker-home" / ".config"))
            self.assertEqual(env["GROK_HOME"], str(root / "worker-grok-home"))
            event_contract = json.loads(env["ELVES_FULL_RUN_EVENT_CONTRACT"])
            self.assertIn(
                "material_scope_or_assumption_change", event_contract["types"]
            )
            self.assertEqual(
                event_contract["material_change"],
                {
                    "type": "material_scope_or_assumption_change",
                    "required": ["change_id", "change_kind"],
                    "change_kind": ["assumption", "scope"],
                    "driver_action": "wake",
                },
            )
            self.assertNotIn("GROK_AUTH_PATH", env)
            self.assertNotIn("HTTPS_PROXY", env)
            stop_secret = str(state.supervision_token)
            descendant_marker = env["ELVES_FULL_RUN_SUPERVISION_MARKER"]
            self.assertEqual(
                descendant_marker,
                full_run_module._descendant_supervision_marker(state),
            )
            self.assertEqual(len(descendant_marker), 64)
            self.assertNotEqual(descendant_marker, stop_secret)
            self.assertNotIn(stop_secret, json.dumps(env, sort_keys=True))
            # argv never carries KEY=VALUE secrets
            argv = build_full_run_argv(state)
            joined = " ".join(argv)
            self.assertNotIn("grant-secret", joined)
            self.assertNotIn("XAI_API_KEY=", joined)
            supervisor_argv = full_run_module._provider_supervisor_argv(
                root=root,
                session_id=state.session_id,
                provider_argv=argv,
                attempt=state.attempt,
                supervisor_executable=state.supervisor_executable or "/proc",
                staged_packet_path=str(state.staged_packet_path),
                staged_packet_identity=dict(state.staged_packet_identity or {}),
                packet_sha256=str(state.packet_sha256),
                packet_size=int(state.packet_size or 0),
            )
            self.assertNotIn(stop_secret, json.dumps(supervisor_argv))
            with self.assertRaises(ValidationIssue) as ctx:
                build_full_run_env(
                    state=state,
                    root=root,
                    parent_env=parent,
                    credential_grant_names=["HOME"],
                )
            self.assertEqual(
                ctx.exception.code,
                "full_run_isolation_control_grant_forbidden",
            )
            with self.assertRaises(ValidationIssue) as ctx:
                build_full_run_env(
                    state=state,
                    root=root,
                    parent_env=parent,
                    credential_grant_names=["GROK_AUTH_PATH"],
                )
            self.assertEqual(
                ctx.exception.code,
                "full_run_isolation_control_grant_forbidden",
            )
            for reserved_name in (
                "PATH",
                "XDG_STATE_HOME",
                "ELVES_FULL_RUN_EVENTS",
                "GIT_CONFIG_COUNT",
                "GIT_ASKPASS",
                "SSH_AUTH_SOCK",
                "GH_CONFIG_DIR",
            ):
                with self.subTest(reserved_name=reserved_name):
                    with self.assertRaises(ValidationIssue) as ctx:
                        build_full_run_env(
                            state=state,
                            root=root,
                            parent_env={
                                **parent,
                                reserved_name: "synthetic-control-value",
                            },
                            credential_grant_names=[reserved_name],
                        )
                    self.assertEqual(
                        ctx.exception.code,
                        "full_run_isolation_control_grant_forbidden",
                    )
            invalid = "XAI_API_KEY=literal-secret"
            with self.assertRaises(ValidationIssue) as ctx:
                build_full_run_env(
                    state=state,
                    root=root,
                    parent_env=parent,
                    credential_grant_names=[invalid],
                )
            self.assertEqual(
                ctx.exception.code,
                "full_run_credential_grant_name_invalid",
            )
            self.assertNotIn("literal-secret", str(ctx.exception))
            invalid_session = "invalid-grant-is-never-persisted"
            with self.assertRaises(ValidationIssue) as ctx:
                prepare_full_run(
                    repo,
                    session_id=invalid_session,
                    branch="feat/x",
                    start_head=start_head,
                    worktree=wt,
                    packet_path=packet,
                    adapter="fixture",
                    fixture_script=repo / "noop.py",
                    credential_grant_names=[invalid],
                )
            self.assertEqual(
                ctx.exception.code,
                "full_run_credential_grant_name_invalid",
            )
            self.assertNotIn("literal-secret", str(ctx.exception))
            self.assertFalse(
                (full_run_root(repo, invalid_session) / "state.json").exists()
            )
            reserved_session = "reserved-grant-is-never-persisted"
            with self.assertRaises(ValidationIssue) as ctx:
                prepare_full_run(
                    repo,
                    session_id=reserved_session,
                    branch="feat/x",
                    start_head=start_head,
                    worktree=wt,
                    packet_path=packet,
                    adapter="fixture",
                    fixture_script=repo / "noop.py",
                    credential_grant_names=["ELVES_FULL_RUN_EVENTS"],
                )
            self.assertEqual(
                ctx.exception.code,
                "full_run_isolation_control_grant_forbidden",
            )
            self.assertFalse(
                (full_run_root(repo, reserved_session) / "state.json").exists()
            )
            with self.assertRaises(ValidationIssue) as ctx:
                build_full_run_env(
                    state=state,
                    root=root,
                    parent_env=parent,
                    credential_grant_names="XAI_API_KEY",
                )
            self.assertEqual(
                ctx.exception.code,
                "full_run_credential_grant_name_invalid",
            )
            with self.assertRaises(ValidationIssue) as ctx:
                build_full_run_env(
                    state=state,
                    root=root,
                    parent_env={**parent, "GROK_HOME": "/host-grok"},
                    credential_grant_names=["GROK_HOME"],
                )
            self.assertEqual(
                ctx.exception.code,
                "full_run_isolation_control_grant_forbidden",
            )

    def test_github_https_push_auth_is_explicit_isolated_and_token_free_in_config(
        self,
    ) -> None:
        state = full_run_module.FullRunState(
            session_id="github-push-auth",
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp/worktree",
            packet_path="/tmp/packet",
            origin_url="https://github.com/example/project.git",
            supervision_token="b" * 48,
        )
        with self.assertRaises(ValidationIssue) as ctx:
            full_run_module._configure_github_push_auth(
                state,
                {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                grant_github_push=False,
            )
        self.assertEqual(ctx.exception.code, "full_run_github_push_auth_required")

        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": "/nonexistent-isolated-home",
            "GH_TOKEN": "abc",
        }
        full_run_module._configure_github_push_auth(
            state,
            env,
            grant_github_push=False,
        )
        self.assertEqual(state.github_push_auth_strategy, "env_gh_token")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertNotIn("abc", env["GIT_CONFIG_VALUE_1"])
        credential = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        fields = dict(
            line.split("=", 1)
            for line in credential.stdout.splitlines()
            if "=" in line
        )
        self.assertEqual(fields.get("username"), "x-access-token")
        self.assertEqual(fields.get("password"), "abc")

    def test_isolated_git_identity_is_explicit_and_never_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            host_home = root / "host-home"
            host_home.mkdir()
            parent = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(host_home),
            }
            state = full_run_module.FullRunState(
                session_id="git-identity",
                branch="feat/x",
                start_head="a" * 40,
                worktree=str(repo),
                packet_path="/tmp/packet",
                supervision_token="b" * 48,
            )
            launch_env = {
                "PATH": parent["PATH"],
                "HOME": str(root / "worker-home"),
            }
            with self.assertRaises(ValidationIssue) as missing:
                full_run_module._configure_git_commit_identity(
                    state,
                    launch_env,
                    parent_env=parent,
                )
            self.assertEqual(
                missing.exception.code,
                "full_run_git_identity_unavailable",
            )

            subprocess.run(
                ["git", "config", "--global", "user.name", "Bound Canary Author"],
                env=parent,
                check=True,
            )
            subprocess.run(
                ["git", "config", "--global", "user.email", "canary@example.invalid"],
                env=parent,
                check=True,
            )
            full_run_module._configure_git_commit_identity(
                state,
                launch_env,
                parent_env=parent,
            )
            self.assertEqual(launch_env["GIT_AUTHOR_NAME"], "Bound Canary Author")
            self.assertEqual(
                launch_env["GIT_AUTHOR_EMAIL"],
                "canary@example.invalid",
            )
            self.assertEqual(
                launch_env["GIT_COMMITTER_NAME"],
                launch_env["GIT_AUTHOR_NAME"],
            )
            self.assertEqual(
                launch_env["GIT_COMMITTER_EMAIL"],
                launch_env["GIT_AUTHOR_EMAIL"],
            )
            identity = subprocess.run(
                ["git", "-C", str(repo), "var", "GIT_AUTHOR_IDENT"],
                env=launch_env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertIn(
                "Bound Canary Author <canary@example.invalid>",
                identity,
            )

    def test_host_gh_push_projection_persists_only_strategy_and_keyed_metadata_input(
        self,
    ) -> None:
        state = full_run_module.FullRunState(
            session_id="host-github-push-auth",
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp/worktree",
            packet_path="/tmp/packet",
            origin_url="https://github.com/example/project.git",
            supervision_token="b" * 48,
        )
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        with mock.patch.object(
            full_run_module,
            "_read_host_github_token",
            return_value="abc",
        ):
            full_run_module._configure_github_push_auth(
                state,
                env,
                grant_github_push=True,
            )
        self.assertEqual(state.github_push_auth_strategy, "host_gh_token")
        self.assertEqual(state.credential_grant_names, ["GH_TOKEN"])
        self.assertEqual(env["GH_TOKEN"], "abc")
        self.assertNotIn("abc", json.dumps(state.to_dict(), sort_keys=True))
        self.assertNotIn("abc", env["GIT_CONFIG_VALUE_1"])

    def test_isolated_push_auth_rejects_ssh_and_leaves_local_remotes_credential_free(
        self,
    ) -> None:
        state = full_run_module.FullRunState(
            session_id="push-transport",
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp/worktree",
            packet_path="/tmp/packet",
            origin_url="git@github.com:example/project.git",
            supervision_token="b" * 48,
        )
        with self.assertRaises(ValidationIssue) as ctx:
            full_run_module._configure_github_push_auth(
                state,
                {},
                grant_github_push=False,
            )
        self.assertEqual(ctx.exception.code, "full_run_git_push_transport_unsupported")

        state.origin_url = "/tmp/local-origin.git"
        env: dict[str, str] = {}
        full_run_module._configure_github_push_auth(
            state,
            env,
            grant_github_push=False,
        )
        self.assertFalse(any(name.startswith("GIT_") for name in env))

    def test_grok_credentials_are_never_implicitly_granted(self) -> None:
        state = full_run_module.FullRunState(
            session_id="explicit-auth-only",
            branch="feat/x",
            start_head="a" * 40,
            worktree="/tmp/worktree",
            packet_path="/tmp/packet",
            supervision_token="b" * 48,
        )
        env = build_full_run_env(
            state=state,
            root=Path("/tmp/full-run-explicit-auth"),
            parent_env={
                "PATH": "/bin",
                "XAI_API_KEY": "xai-secret",
                "GROK_API_KEY": "grok-secret",
                "OPENAI_API_KEY": "openai-secret",
                "GROK_AUTH_PATH": "/host/.grok/auth.json",
            },
        )
        self.assertNotIn("XAI_API_KEY", env)
        self.assertNotIn("GROK_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("GROK_AUTH_PATH", env)

    def test_shared_grok_oauth_path_is_private_bounded_and_rotation_tolerant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            host_home = root / "host-home"
            source = host_home / ".grok" / "auth.json"
            source.parent.mkdir(parents=True)
            payload = {
                "issuer::account": {
                    "auth_mode": "oauth",
                    "key": "access-token-value",
                    "refresh_token": "refresh-token-value",
                }
            }
            source.write_text(json.dumps(payload), encoding="utf-8")
            source.chmod(0o600)
            run_root = repo / ".elves" / "runtime" / "implement" / "auth-test"
            native_grok = _compile_native_grok_launcher(
                root,
                "print('grok 0.2.93 (test)')\n",
                name="oauth-path-native-grok",
            )
            state = full_run_module.FullRunState(
                session_id="oauth-shared",
                branch="feat/x",
                start_head="a" * 40,
                worktree=str(repo),
                packet_path=str(repo / "packet"),
                supervision_token="c" * 48,
                executable=str(native_grok),
            )
            parent = {"HOME": str(host_home)}
            raw, identity = full_run_module._read_host_grok_auth(parent)
            self.assertEqual(
                full_run_module._oauth_secret_values(raw),
                {"access-token-value", "refresh-token-value"},
            )
            with mock.patch.dict(os.environ, parent, clear=False), mock.patch.object(provider_auth_module, "_assert_grok_auth_path_capability",
                return_value=(0, 2, 93),
            ):
                launch_env = {"GROK_HOME": str(run_root / "worker-grok-home")}
                full_run_module._configure_grok_auth(
                    repo,
                    run_root,
                    state,
                    launch_env,
                    grant_grok_auth=True,
                )
            self.assertEqual(state.grok_auth_strategy, "oauth_shared_file")
            self.assertEqual(state.grok_auth_path_identity, identity)
            self.assertEqual(launch_env["GROK_AUTH_PATH"], str(source.resolve()))
            self.assertFalse(
                (run_root / full_run_module.GROK_HOME_REL / "auth.json").exists()
            )

            rotated_payload = {
                "issuer::account": {
                    "auth_mode": "oauth",
                    "key": "rotated-access-token",
                    "refresh_token": "rotated-refresh-token",
                }
            }
            replacement = source.with_name("auth.next")
            replacement.write_text(json.dumps(rotated_payload), encoding="utf-8")
            replacement.chmod(0o600)
            replacement.replace(source)
            rotated_raw = full_run_module._revalidate_shared_grok_auth(state)
            self.assertEqual(
                full_run_module._oauth_secret_values(rotated_raw),
                {"rotated-access-token", "rotated-refresh-token"},
            )
            self.assertEqual(state.grok_auth_path_identity, identity)

    def test_shared_oauth_evidence_context_reads_one_token_generation(self) -> None:
        canonical_path = "/private/owner/.grok/auth.json"
        state = full_run_module.FullRunState(
            session_id="oauth-single-snapshot",
            branch="feat/x",
            start_head="a" * 40,
            worktree="/private/worktree",
            packet_path="/private/packet",
            grok_auth_strategy="oauth_shared_file",
            grok_auth_path_identity={"path": canonical_path},
        )
        raw = json.dumps(
            {"account": {"refresh_token": "single-generation-value"}}
        ).encode("utf-8")
        with mock.patch.object(provider_auth_module, "_revalidate_shared_grok_auth",
            return_value=raw,
        ) as revalidate:
            verified, exact_values = full_run_module._launch_evidence_context(state)
        self.assertTrue(verified)
        revalidate.assert_called_once_with(state)
        self.assertIn(canonical_path, exact_values)
        self.assertIn("single-generation-value", exact_values)

    def test_grok_auth_path_capability_probe_is_version_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            native_grok = _compile_native_grok_launcher(
                Path(tmp),
                "raise SystemExit(0)\n",
                name="version-gated-grok",
            )
            supported = subprocess.CompletedProcess(
                [str(native_grok), "version", "--json"],
                0,
                '{"currentVersion":"0.2.93 (test)"}\n',
                "",
            )
            with mock.patch.object(
                full_run_module.subprocess, "run", return_value=supported
            ) as run_mock, mock.patch.object(provider_auth_module, "_executable_advertises_grok_auth_path",
                return_value=True,
            ):
                self.assertEqual(
                    full_run_module._assert_grok_auth_path_capability(
                        str(native_grok)
                    ),
                    (0, 2, 93),
                )
            run_mock.assert_called_once()

            with mock.patch.object(
                full_run_module.subprocess, "run", return_value=supported
            ), mock.patch.object(provider_auth_module, "_executable_advertises_grok_auth_path",
                return_value=False,
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    full_run_module._assert_grok_auth_path_capability(
                        str(native_grok)
                    )
            self.assertEqual(
                ctx.exception.code, "full_run_grok_auth_path_unsupported"
            )

            unsupported = subprocess.CompletedProcess(
                [str(native_grok), "version", "--json"],
                0,
                '{"currentVersion":"0.2.92"}\n',
                "",
            )
            with mock.patch.object(
                full_run_module.subprocess, "run", return_value=unsupported
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    full_run_module._assert_grok_auth_path_capability(
                        str(native_grok)
                    )
            self.assertEqual(
                ctx.exception.code, "full_run_grok_auth_path_unsupported"
            )

    def test_grok_capability_probe_isolated_and_launch_binding_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observation = root / "probe-observation.json"
            grok = _compile_native_grok_launcher(
                root,
                "#!/usr/bin/env python3\n"
                "# Native capability marker: GROK_AUTH_PATH\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                f"observation = Path({str(observation)!r})\n"
                "observation.write_text(json.dumps({\n"
                "    'argv0': str(Path(sys.argv[0]).resolve()),\n"
                "    'native_launcher': os.environ.get('ELVES_TEST_NATIVE_LAUNCHER'),\n"
                "    'home': os.environ.get('HOME'),\n"
                "    'keys': sorted(os.environ),\n"
                "}), encoding='utf-8')\n"
                "print(json.dumps({'currentVersion': '0.2.93'}))\n",
                name="fake-grok-0.2.93",
            )
            alias = root / "grok"
            alias.symlink_to(grok)
            host_controls = {
                "HOME": str(root / "host-home-with-auth"),
                "GROK_HOME": str(root / "host-grok-home"),
                "GROK_AUTH_PATH": str(root / "host-grok-home" / "auth.json"),
                "XAI_API_KEY": "host-api-key-must-not-cross-probe",
                "UNRELATED_SENTINEL": "must-not-cross-probe",
            }
            with mock.patch.dict(os.environ, host_controls, clear=False):
                self.assertEqual(
                    full_run_module._assert_grok_auth_path_capability(str(alias)),
                    (0, 2, 93),
                )
            observed = json.loads(observation.read_text(encoding="utf-8"))
            self.assertEqual(observed["native_launcher"], str(grok.resolve()))
            self.assertNotEqual(observed["home"], host_controls["HOME"])
            self.assertFalse(Path(observed["home"]).exists())
            for forbidden in (
                "GROK_HOME",
                "GROK_AUTH_PATH",
                "XAI_API_KEY",
                "UNRELATED_SENTINEL",
            ):
                self.assertNotIn(forbidden, observed["keys"])

            state = full_run_module.FullRunState(
                session_id="33333333-3333-3333-3333-333333333333",
                branch="feat/x",
                start_head="a" * 40,
                worktree=str(root),
                packet_path=str(root / "packet.md"),
                executable=str(alias),
            )
            Path(state.packet_path).write_text("test packet\n", encoding="utf-8")
            full_run_module._configure_grok_auth(
                root,
                root / "runtime",
                state,
                {"XAI_API_KEY": "explicit-test-key"},
                grant_grok_auth=False,
            )
            self.assertEqual(state.executable, str(grok.resolve()))
            self.assertEqual(
                state.grok_executable_identity["path"], str(grok.resolve())
            )
            provider_argv = build_full_run_argv(state)
            self.assertEqual(provider_argv[0], str(grok.resolve()))
            supervisor_argv = full_run_module._provider_supervisor_argv(
                root=root,
                session_id=state.session_id,
                provider_argv=provider_argv,
                attempt=state.attempt,
                supervisor_executable="/proc",
                provider_executable_identity=state.grok_executable_identity,
                **_packet_binding_kwargs(Path(state.packet_path)),
            )
            self.assertIn(
                json.dumps(state.grok_executable_identity, sort_keys=True),
                supervisor_argv,
            )

    def test_shared_oauth_executable_rejects_scripts_and_writable_surfaces(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            safe_parent = root / "safe-provider-home"
            safe_parent.mkdir(mode=0o700)
            native = _compile_native_grok_launcher(
                safe_parent,
                "print('grok 0.2.93 (test)')\n",
                name="native-grok",
            )
            script = safe_parent / "script-grok"
            script.write_text(
                "#!/bin/sh\necho 'grok 0.2.93 (test)'\n", encoding="utf-8"
            )
            script.chmod(0o700)

            resolved, identity = (
                full_run_module._resolve_shared_oauth_grok_executable(str(native))
            )
            self.assertEqual(resolved, native.resolve())
            self.assertEqual(identity["security_profile"], "shared_oauth_native")
            self.assertIn(identity["native_format"], {"mach-o", "elf"})

            with mock.patch.object(full_run_module.subprocess, "run") as probe:
                with self.assertRaises(ValidationIssue) as ctx:
                    full_run_module._assert_grok_auth_path_capability(str(script))
            probe.assert_not_called()
            self.assertEqual(ctx.exception.code, "full_run_grok_executable_not_native")

            native.chmod(0o777)
            try:
                with mock.patch.object(full_run_module.subprocess, "run") as probe:
                    with self.assertRaises(ValidationIssue) as ctx:
                        full_run_module._assert_grok_auth_path_capability(str(native))
                probe.assert_not_called()
                self.assertEqual(ctx.exception.code, "full_run_grok_executable_unsafe")
            finally:
                native.chmod(0o700)

            safe_parent.chmod(0o777)
            try:
                with mock.patch.object(full_run_module.subprocess, "run") as probe:
                    with self.assertRaises(ValidationIssue) as ctx:
                        full_run_module._assert_grok_auth_path_capability(str(native))
                probe.assert_not_called()
                self.assertEqual(
                    ctx.exception.code,
                    "full_run_grok_executable_parent_unsafe",
                )
            finally:
                safe_parent.chmod(0o700)

    def test_shared_oauth_executable_binding_closes_every_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native = _compile_native_grok_launcher(
                root,
                "print('grok 0.2.93 (test)')\n",
                name="fd-safe-native-grok",
            )
            script = root / "fd-rejected-script-grok"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o700)
            real_open = full_run_module.os.open
            real_close = full_run_module.os.close

            for candidate, expected_code in (
                (native, None),
                (script, "full_run_grok_executable_not_native"),
            ):
                with self.subTest(candidate=candidate.name):
                    opened: list[int] = []
                    closed: list[int] = []

                    def tracked_open(*args: object, **kwargs: object) -> int:
                        descriptor = real_open(*args, **kwargs)
                        opened.append(descriptor)
                        return descriptor

                    def tracked_close(descriptor: int) -> None:
                        closed.append(descriptor)
                        real_close(descriptor)

                    with mock.patch.object(
                        full_run_module.os, "open", side_effect=tracked_open
                    ), mock.patch.object(
                        full_run_module.os, "close", side_effect=tracked_close
                    ):
                        if expected_code is None:
                            full_run_module._resolve_shared_oauth_grok_executable(
                                str(candidate)
                            )
                        else:
                            with self.assertRaises(ValidationIssue) as ctx:
                                full_run_module._resolve_shared_oauth_grok_executable(
                                    str(candidate)
                                )
                            self.assertEqual(ctx.exception.code, expected_code)
                    self.assertTrue(opened)
                    self.assertCountEqual(opened, closed)

    def test_installed_grok_satisfies_shared_oauth_native_binding(self) -> None:
        installed = shutil.which("grok")
        if installed is None:
            self.skipTest("installed Grok unavailable")
        resolved, identity = (
            full_run_module._resolve_shared_oauth_grok_executable(installed)
        )
        self.assertEqual(str(resolved), identity["path"])
        self.assertEqual(identity["security_profile"], "shared_oauth_native")
        self.assertTrue(identity["parent_chain"])
        self.assertGreaterEqual(
            full_run_module._assert_grok_auth_path_capability(installed),
            full_run_module.GROK_AUTH_PATH_MIN_VERSION,
        )

    def test_shared_oauth_executable_rejects_real_darwin_allow_acls(self) -> None:
        if sys.platform != "darwin":
            self.skipTest("Darwin extended ACL semantics only")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            safe_parent = root / "safe-provider-home"
            safe_parent.mkdir(mode=0o700)
            native = _compile_native_grok_launcher(
                safe_parent,
                "print('grok 0.2.93 (test)')\n",
                name="acl-native-grok",
            )
            for target, rule in (
                (native, "everyone allow execute"),
                (safe_parent, "everyone allow search"),
            ):
                with self.subTest(target=target.name):
                    result = subprocess.run(
                        ["chmod", "+a", rule, str(target)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode != 0:
                        self.skipTest(
                            "temporary filesystem does not support extended ACLs"
                        )
                    try:
                        with mock.patch.object(
                            full_run_module.subprocess, "run"
                        ) as probe:
                            with self.assertRaises(ValidationIssue) as ctx:
                                full_run_module._assert_grok_auth_path_capability(
                                    str(native)
                                )
                        probe.assert_not_called()
                        self.assertEqual(
                            ctx.exception.code,
                            "full_run_grok_executable_acl_unsafe",
                        )
                    finally:
                        subprocess.run(
                            ["chmod", "-N", str(target)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )

    def test_provider_supervisor_rejects_executable_replacement_before_spawn(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = root / "provider.py"
            executed = root / "provider-executed"
            provider.write_text(
                "#!/usr/bin/env python3\n"
                f"from pathlib import Path; Path({str(executed)!r}).touch()\n",
                encoding="utf-8",
            )
            provider.chmod(0o700)
            _resolved, identity = full_run_module._resolve_grok_executable(
                str(provider)
            )
            replacement = root / "replacement.py"
            replacement.write_text(
                "#!/usr/bin/env python3\nraise SystemExit(0)\n",
                encoding="utf-8",
            )
            replacement.chmod(0o700)
            fingerprint = root / "supervisor.fingerprint.json"
            fingerprint.write_text('{"pid":1}\n', encoding="utf-8")
            backend = str(full_run_module._qualified_process_supervisor())
            session_id = "provider-executable-toctou"
            state = full_run_module.FullRunState(
                session_id=session_id,
                branch="feat/x",
                start_head="a" * 40,
                worktree=str(root),
                packet_path=str(root / "packet.md"),
                attempt=1,
                supervision_token="a" * 48,
            )
            packet = Path(state.packet_path)
            packet.write_text("executable replacement packet\n", encoding="utf-8")
            supervisor_argv = full_run_module._provider_supervisor_argv(
                root=root,
                session_id=session_id,
                provider_argv=[str(provider), str(packet)],
                attempt=state.attempt,
                supervisor_executable=backend,
                provider_executable_identity=identity,
                **_packet_binding_kwargs(packet),
            )
            env = {
                "PATH": os.environ.get("PATH") or os.defpath,
                "ELVES_FULL_RUN_SUPERVISION_MARKER": (
                    full_run_module._descendant_supervision_marker(state)
                ),
            }
            proc = subprocess.Popen(
                supervisor_argv,
                cwd=root,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            replacement.replace(provider)
            stdout, stderr = proc.communicate(
                (str(state.supervision_token) + "\n").encode("ascii"),
                timeout=5.0,
            )
            self.assertIsNone(stdout)
            self.assertIsNone(stderr)
            self.assertEqual(proc.returncode, 125)
            self.assertFalse(executed.exists())
            exit_record = json.loads(
                (root / "exit_record.json").read_text(encoding="utf-8")
            )
            self.assertIsNone(exit_record["provider_pid"])
            self.assertEqual(
                exit_record["supervision_error"],
                "provider_executable_identity_mismatch",
            )

    def test_provider_supervisor_rejects_shared_oauth_ancestor_replacement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "controlled"
            intermediate = base / "intermediate"
            provider_home = intermediate / "bin"
            provider_home.mkdir(parents=True)
            for directory in (base, intermediate, provider_home):
                directory.chmod(0o700)
            executed = root / "provider-executed"
            provider = _compile_native_grok_launcher(
                provider_home,
                f"from pathlib import Path; Path({str(executed)!r}).touch()\n",
                name="native-grok",
            )
            _resolved, identity = (
                full_run_module._resolve_shared_oauth_grok_executable(
                    str(provider)
                )
            )

            def replace_intermediate_ancestor() -> None:
                moved = base / "old-intermediate"
                intermediate.replace(moved)
                intermediate.mkdir(mode=0o700)
                (moved / "bin").replace(intermediate / "bin")

            returncode, record = _run_bound_supervisor_after_mutation(
                root,
                provider,
                identity,
                replace_intermediate_ancestor,
            )
            self.assertEqual(returncode, 125)
            self.assertFalse(executed.exists())
            self.assertIsNone(record["provider_pid"])
            self.assertEqual(
                record["supervision_error"],
                "provider_executable_identity_mismatch",
            )

    def test_provider_supervisor_rechecks_shared_oauth_darwin_allow_acls(
        self,
    ) -> None:
        if sys.platform != "darwin":
            self.skipTest("Darwin extended ACL semantics only")
        for target_kind, rule in (
            ("executable", "everyone allow execute"),
            ("ancestor", "everyone allow search"),
        ):
            with self.subTest(target_kind=target_kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                provider_home = root / "safe-provider-home"
                provider_home.mkdir(mode=0o700)
                executed = root / "provider-executed"
                provider = _compile_native_grok_launcher(
                    provider_home,
                    f"from pathlib import Path; Path({str(executed)!r}).touch()\n",
                    name="native-grok",
                )
                _resolved, identity = (
                    full_run_module._resolve_shared_oauth_grok_executable(
                        str(provider)
                    )
                )
                target = provider if target_kind == "executable" else provider_home

                def add_allow_acl() -> None:
                    result = subprocess.run(
                        ["chmod", "+a", rule, str(target)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode != 0:
                        raise unittest.SkipTest(
                            "temporary filesystem does not support extended ACLs"
                        )

                try:
                    returncode, record = _run_bound_supervisor_after_mutation(
                        root,
                        provider,
                        identity,
                        add_allow_acl,
                    )
                    self.assertEqual(returncode, 125)
                    self.assertFalse(executed.exists())
                    self.assertIsNone(record["provider_pid"])
                    self.assertEqual(
                        record["supervision_error"],
                        "provider_executable_identity_mismatch",
                    )
                finally:
                    subprocess.run(
                        ["chmod", "-N", str(target)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )

    def test_grok_oauth_import_rejects_unsafe_or_unrecognized_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host_home = root / "home"
            auth_dir = host_home / ".grok"
            auth_dir.mkdir(parents=True)
            source = auth_dir / "auth.json"
            parent = {"HOME": str(host_home)}

            source.write_text("{}", encoding="utf-8")
            source.chmod(0o600)
            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._read_host_grok_auth(parent)
            self.assertEqual(ctx.exception.code, "full_run_grok_auth_source_invalid")

            source.write_text(
                json.dumps({"account": {"key": "secret"}}), encoding="utf-8"
            )
            source.chmod(0o644)
            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._read_host_grok_auth(parent)
            self.assertEqual(ctx.exception.code, "full_run_grok_auth_source_unsafe")

            source.unlink()
            target = root / "target-auth.json"
            target.write_text(
                json.dumps({"account": {"key": "secret"}}), encoding="utf-8"
            )
            target.chmod(0o600)
            source.symlink_to(target)
            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._read_host_grok_auth(parent)
            self.assertEqual(ctx.exception.code, "full_run_grok_auth_source_unsafe")

            unsafe_parent = root / "unsafe-parent"
            unsafe_parent.mkdir()
            unsafe_parent.chmod(0o777)
            unsafe_auth = unsafe_parent / "auth.json"
            unsafe_auth.write_text(
                json.dumps({"account": {"key": "secret"}}), encoding="utf-8"
            )
            unsafe_auth.chmod(0o600)
            try:
                with self.assertRaises(ValidationIssue) as ctx:
                    full_run_module._read_host_grok_auth(
                        {"GROK_AUTH_PATH": str(unsafe_auth)}
                    )
                self.assertEqual(
                    ctx.exception.code, "full_run_grok_auth_parent_unsafe"
                )
            finally:
                unsafe_parent.chmod(0o700)

    def test_grok_oauth_rejects_real_darwin_allow_acl_on_leaf(self) -> None:
        if sys.platform != "darwin":
            self.skipTest("Darwin extended ACL semantics only")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth_dir = root / "home" / ".grok"
            auth_dir.mkdir(parents=True)
            auth = auth_dir / "auth.json"
            auth.write_text(
                json.dumps({"account": {"refresh_token": "test-refresh"}}),
                encoding="utf-8",
            )
            auth.chmod(0o600)
            result = subprocess.run(
                ["chmod", "+a", "everyone allow read", str(auth)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest("temporary filesystem does not support extended ACLs")
            try:
                with self.assertRaises(ValidationIssue) as ctx:
                    full_run_module._read_host_grok_auth(
                        {"GROK_AUTH_PATH": str(auth)}
                    )
                self.assertEqual(ctx.exception.code, "full_run_grok_auth_acl_unsafe")
            finally:
                subprocess.run(
                    ["chmod", "-N", str(auth)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )

    def test_grok_oauth_rejects_real_darwin_allow_acl_on_every_ancestor_right(
        self,
    ) -> None:
        if sys.platform != "darwin":
            self.skipTest("Darwin extended ACL semantics only")
        for permission in ("list", "search", "add_file", "delete_child"):
            with self.subTest(permission=permission), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ancestor = root / "controlled-ancestor"
                auth_dir = ancestor / "home" / ".grok"
                auth_dir.mkdir(parents=True)
                auth = auth_dir / "auth.json"
                auth.write_text(
                    json.dumps({"account": {"refresh_token": "test-refresh"}}),
                    encoding="utf-8",
                )
                auth.chmod(0o600)
                result = subprocess.run(
                    [
                        "chmod",
                        "+a",
                        f"everyone allow {permission}",
                        str(ancestor),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    self.skipTest(
                        "temporary filesystem does not support extended ACLs"
                    )
                try:
                    with self.assertRaises(ValidationIssue) as ctx:
                        full_run_module._read_host_grok_auth(
                            {"GROK_AUTH_PATH": str(auth)}
                        )
                    self.assertEqual(
                        ctx.exception.code, "full_run_grok_auth_acl_unsafe"
                    )
                finally:
                    subprocess.run(
                        ["chmod", "-N", str(ancestor)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )

    def test_grok_oauth_accepts_real_darwin_deny_only_acls(self) -> None:
        if sys.platform != "darwin":
            self.skipTest("Darwin extended ACL semantics only")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ancestor = root / "controlled-ancestor"
            auth_dir = ancestor / "home" / ".grok"
            auth_dir.mkdir(parents=True)
            auth = auth_dir / "auth.json"
            auth.write_text(
                json.dumps({"account": {"refresh_token": "test-refresh"}}),
                encoding="utf-8",
            )
            auth.chmod(0o600)
            acl_paths = (ancestor, auth)
            for path in acl_paths:
                result = subprocess.run(
                    ["chmod", "+a", "everyone deny delete", str(path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    for cleanup in reversed(acl_paths):
                        subprocess.run(
                            ["chmod", "-N", str(cleanup)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                    self.skipTest(
                        "temporary filesystem does not support extended ACLs"
                    )
            try:
                raw, identity = full_run_module._read_host_grok_auth(
                    {"GROK_AUTH_PATH": str(auth)}
                )
                self.assertIn(b"test-refresh", raw)
                self.assertEqual(identity["path"], str(auth.resolve()))
            finally:
                for path in reversed(acl_paths):
                    subprocess.run(
                        ["chmod", "-N", str(path)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )

    def test_grok_oauth_rejects_writable_ancestor_and_fifo_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsafe_ancestor = root / "unsafe-ancestor"
            auth_dir = unsafe_ancestor / "private-leaf"
            auth_dir.mkdir(parents=True)
            unsafe_ancestor.chmod(0o777)
            auth_dir.chmod(0o700)
            auth = auth_dir / "auth.json"
            auth.write_text(
                json.dumps({"account": {"refresh_token": "test-refresh"}}),
                encoding="utf-8",
            )
            auth.chmod(0o600)
            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._read_host_grok_auth(
                    {"GROK_AUTH_PATH": str(auth)}
                )
            self.assertEqual(ctx.exception.code, "full_run_grok_auth_parent_unsafe")

            fifo_dir = root / "fifo-leaf"
            fifo_dir.mkdir()
            fifo_dir.chmod(0o700)
            fifo = fifo_dir / "auth.json"
            os.mkfifo(fifo, 0o600)
            probe = (
                "from cobbler_runtime import full_run; import sys; "
                "from cobbler_runtime.schema import ValidationIssue; "
                "\ntry: full_run._read_host_grok_auth({'GROK_AUTH_PATH': sys.argv[1]})"
                "\nexcept ValidationIssue as exc: raise SystemExit(0 if exc.code == "
                "'full_run_grok_auth_source_unsafe' else 2)"
                "\nraise SystemExit(3)"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", probe, str(fifo)],
                cwd=str(SCRIPTS),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                child.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                self.fail("owner-only FIFO auth leaf blocked instead of failing closed")
            self.assertEqual(child.returncode, 0)

    def test_grok_oauth_revalidation_binds_intermediate_parent_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base"
            intermediate = base / "intermediate"
            auth_dir = intermediate / "auth-home"
            auth_dir.mkdir(parents=True)
            for directory in (base, intermediate, auth_dir):
                directory.chmod(0o700)
            auth = auth_dir / "auth.json"
            auth.write_text(
                json.dumps({"account": {"refresh_token": "test-refresh"}}),
                encoding="utf-8",
            )
            auth.chmod(0o600)
            _raw, identity = full_run_module._read_host_grok_auth(
                {"GROK_AUTH_PATH": str(auth)}
            )

            moved = base / "old-intermediate"
            intermediate.replace(moved)
            intermediate.mkdir(mode=0o700)
            (moved / "auth-home").replace(intermediate / "auth-home")
            _raw, observed = full_run_module._read_host_grok_auth(
                {"GROK_AUTH_PATH": str(auth)}
            )
            self.assertEqual(identity["parent_ino"], observed["parent_ino"])
            self.assertNotEqual(identity["parent_chain"], observed["parent_chain"])

            state = full_run_module.FullRunState(
                session_id="oauth-chain-binding",
                branch="feat/x",
                start_head="a" * 40,
                worktree=str(root),
                packet_path=str(root / "packet"),
                grok_auth_strategy="oauth_shared_file",
                grok_auth_path_identity=identity,
            )
            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._revalidate_shared_grok_auth(state)
            self.assertEqual(ctx.exception.code, "full_run_grok_auth_identity_changed")

    def test_grok_oauth_source_swap_cannot_bypass_private_fd_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host_home = root / "home"
            auth_dir = host_home / ".grok"
            auth_dir.mkdir(parents=True)
            source = auth_dir / "auth.json"
            source.write_text(
                json.dumps({"account": {"key": "original-secret"}}),
                encoding="utf-8",
            )
            source.chmod(0o600)
            replacement = auth_dir / "replacement.json"
            replacement.write_text(
                json.dumps({"account": {"key": "replacement-secret"}}),
                encoding="utf-8",
            )
            replacement.chmod(0o644)
            real_open = os.open
            swapped = False

            def swap_before_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
                nonlocal swapped
                if (
                    not swapped
                    and Path(path).name == "auth.json"
                    and kwargs.get("dir_fd") is not None
                ):
                    swapped = True
                    source.unlink()
                    replacement.replace(source)
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(full_run_module.os, "open", side_effect=swap_before_open):
                with self.assertRaises(ValidationIssue) as ctx:
                    full_run_module._read_host_grok_auth({"HOME": str(host_home)})
            self.assertTrue(swapped)
            self.assertEqual(ctx.exception.code, "full_run_grok_auth_source_unsafe")

    def test_shared_oauth_rotation_preserves_structured_evidence_but_disables_raw_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = repo / "packet.md"
            packet.write_text("fixture\n", encoding="utf-8")
            worker = repo / "noop.py"
            worker.write_text("print('unused')\n", encoding="utf-8")
            head = _init_feature_repo(repo)
            session = "oauth-evidence-context"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                adapter="fixture",
                fixture_script=worker,
            )
            host_home = root / "host-home"
            auth = host_home / ".grok" / "auth.json"
            auth.parent.mkdir(parents=True)
            opaque_secret = "opaque-refresh-value-9f3c2a"
            auth.write_text(
                json.dumps({"account": {"refresh_token": opaque_secret}}),
                encoding="utf-8",
            )
            auth.chmod(0o600)
            state = load_state(repo, session)
            _raw, identity = full_run_module._read_host_grok_auth(
                {"HOME": str(host_home)}
            )
            state.grok_auth_strategy = "oauth_shared_file"
            state.grok_auth_path_identity = identity
            full_run_module.save_state(repo, state)
            canonical_auth = str(identity["path"])
            transcript = full_run_root(repo, session) / "transcript.log"
            transcript.write_text(opaque_secret + "\n", encoding="utf-8")
            transcript.chmod(0o600)

            matching = logs_full_run(
                repo, session_id=session, raw_tail=True, tail_lines=5
            )
            self.assertTrue(matching["ok"], matching)
            self.assertFalse(matching["transcript_included"])
            self.assertIn("shared OAuth", matching["transcript_error"])
            self.assertNotIn(str(auth), json.dumps(matching, sort_keys=True))

            event_path = full_run_root(repo, session) / "events.jsonl"
            full_run_module._append_event(
                event_path,
                {
                    "timestamp": full_run_module._utc_now(),
                    "session_id": session,
                    "branch": "feat/x",
                    "head": head,
                    "batch": 1,
                    "type": "heartbeat",
                    "summary": f"historical {opaque_secret} from {canonical_auth}",
                },
                expected_session_id=session,
                expected_branch="feat/x",
                repo_root=repo,
            )
            full_run_module._append_event(
                event_path,
                {
                    "timestamp": full_run_module._utc_now(),
                    "session_id": session,
                    "branch": "feat/x",
                    "head": head,
                    "batch": 1,
                    "type": "blocked",
                    "summary": f"blocked with {opaque_secret} at {canonical_auth}",
                },
                expected_session_id=session,
                expected_branch="feat/x",
                repo_root=repo,
            )

            rotated_secret = "rotated-value-5e7d3a"
            replacement = auth.with_name("auth.next")
            replacement.write_text(
                json.dumps({"account": {"refresh_token": rotated_secret}}),
                encoding="utf-8",
            )
            replacement.chmod(0o600)
            replacement.replace(auth)
            rotated = logs_full_run(repo, session_id=session, raw_tail=False)
            self.assertTrue(rotated["ok"], rotated)
            rotated_json = json.dumps(rotated, sort_keys=True)
            self.assertNotIn(str(auth), rotated_json)
            self.assertNotIn(canonical_auth, rotated_json)
            self.assertNotIn(opaque_secret, rotated_json)
            self.assertNotIn(rotated_secret, rotated_json)
            self.assertTrue(rotated["events_tail"])
            self.assertTrue(
                all("summary" not in item for item in rotated["events_tail"])
            )
            self.assertEqual(rotated["events_tail"][-1]["type"], "blocked")
            self.assertTrue(full_run_module._launch_grants_verified(load_state(repo, session)))
            redacted = full_run_module._redact_full_run_structure(
                {"summary": rotated_secret},
                exact_values=full_run_module._state_secret_values(load_state(repo, session)),
            )
            self.assertNotIn(rotated_secret, json.dumps(redacted, sort_keys=True))
            observed = monitor_full_run(repo, session_id=session)
            self.assertNotEqual(observed["state"], "failed", observed)
            observed_json = json.dumps(observed, sort_keys=True)
            self.assertNotIn(str(auth), observed_json)
            self.assertNotIn(canonical_auth, observed_json)
            self.assertNotIn(opaque_secret, observed_json)
            self.assertNotIn(rotated_secret, observed_json)
            self.assertEqual(
                observed["blocker"], "shared OAuth worker reported a blocked state"
            )
            report = full_run_module._running_report(
                load_state(repo, session), final_head=head
            )
            report_with_path = dict(report)
            report_with_path["security_notes"] = [
                f"historical {opaque_secret} at {canonical_auth}"
            ]
            with self.assertRaises(ValidationIssue) as ctx:
                write_report(repo, session, report_with_path)
            self.assertEqual(ctx.exception.code, "full_run_report_invalid")
            self.assertNotIn(str(auth), str(ctx.exception))
            self.assertNotIn(canonical_auth, str(ctx.exception))
            self.assertNotIn(opaque_secret, str(ctx.exception))

            report["security_notes"] = [f"historical {opaque_secret}"]
            report_path = write_report(repo, session, report)
            self.assertTrue(report_path.is_file())
            self.assertNotIn(str(auth), str(report_path))
            self.assertNotIn(canonical_auth, str(report_path))
            self.assertNotIn(opaque_secret, str(report_path))
            observed_after_report = monitor_full_run(repo, session_id=session)
            observed_after_json = json.dumps(observed_after_report, sort_keys=True)
            self.assertNotIn(str(auth), observed_after_json)
            self.assertNotIn(canonical_auth, observed_after_json)
            self.assertNotIn(opaque_secret, observed_after_json)

            auth.unlink()
            missing = logs_full_run(repo, session_id=session, raw_tail=False)
            self.assertFalse(missing["ok"])
            self.assertFalse(missing["transcript_included"])

    def test_shared_oauth_reconcile_returns_only_structured_rotation_safe_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet, "B1-A1")
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            session = "oauth-reconcile-projection"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                session_path=_write_production_acceptance_contract(repo, packet),
                adapter="grok-build",
                executable="grok",
            )
            auth_dir = root / "host-home" / ".grok"
            auth_dir.mkdir(parents=True)
            old_secret = "opaque-historical-reconcile-value"
            current_secret = "opaque-current-reconcile-value"
            auth = auth_dir / "auth.json"
            auth.write_text(
                json.dumps({"account": {"refresh_token": old_secret}}),
                encoding="utf-8",
            )
            auth.chmod(0o600)
            _raw, identity = full_run_module._read_host_grok_auth(
                {"GROK_AUTH_PATH": str(auth)}
            )
            state = load_state(repo, session)
            state.grok_auth_strategy = "oauth_shared_file"
            state.grok_auth_path_identity = identity
            full_run_module.save_state(repo, state)

            (repo / "tracked.txt").write_text("delegated progress\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-m", "delegated progress"],
                check=True,
            )
            tip = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(repo), "push", "-q", "origin", "feat/x"],
                check=True,
            )
            events = full_run_root(repo, session) / "events.jsonl"
            for event_type in ("commit_pushed", "run_complete"):
                full_run_module._append_event(
                    events,
                    {
                        "timestamp": full_run_module._utc_now(),
                        "session_id": session,
                        "branch": "feat/x",
                        "head": tip,
                        "batch": 1,
                        "type": event_type,
                        "summary": f"{old_secret} used through {auth}",
                    },
                    expected_session_id=session,
                    expected_branch="feat/x",
                    repo_root=repo,
                )

            replacement = auth.with_name("auth.next")
            replacement.write_text(
                json.dumps({"account": {"refresh_token": current_secret}}),
                encoding="utf-8",
            )
            replacement.chmod(0o600)
            replacement.replace(auth)
            report = {
                "run_id": full_run_module._expected_run_id(session),
                "attempt": 1,
                "session_id": session,
                "branch": "feat/x",
                "start_head": head,
                "final_head": tip,
                "status": "complete",
                "batches": [
                    {"id": "batch-1", "status": "complete", "evidence": old_secret}
                ],
                "acceptance": [
                    {
                        "id": "B1-A1",
                        "criterion": "criterion for B1-A1",
                        "met": True,
                        "evidence": old_secret,
                    },
                    {
                        "id": "M-A1",
                        "criterion": "criterion for M-A1",
                        "met": True,
                        "evidence": old_secret,
                    },
                ],
                "commits": [{"sha": tip, "subject": old_secret}],
                "blockers": [],
                "remaining_risks": [],
                "tests": {"result": old_secret},
            }
            report_path = write_report(repo, session, report)
            self.assertTrue(report_path.is_file())
            reconciled = reconcile_full_run_with_git(repo, session_id=session)
            encoded = json.dumps(reconciled, sort_keys=True)
            self.assertTrue(reconciled["ok"], reconciled)
            self.assertNotIn(str(auth), encoded)
            self.assertNotIn(old_secret, encoded)
            self.assertNotIn(current_secret, encoded)
            self.assertEqual(reconciled["final_head"], tip)
            self.assertEqual(
                reconciled["review_context"]["schema"],
                "elves-worker-confidence-review-v1",
            )
            self.assertTrue(
                reconciled["review_context"]["review_policy"][
                    "baseline_review_required"
                ]
            )

    def test_grok_auth_selection_requires_one_explicit_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            run_root = repo / ".elves" / "runtime" / "implement" / "auth-select"
            state = full_run_module.FullRunState(
                session_id="auth-select",
                branch="feat/x",
                start_head="a" * 40,
                worktree=str(repo),
                packet_path=str(repo / "packet"),
                supervision_token="d" * 48,
                executable=sys.executable,
            )
            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._configure_grok_auth(
                    repo, run_root, state, {}, grant_grok_auth=False
                )
            self.assertEqual(ctx.exception.code, "full_run_grok_auth_required")

            api_env = {"XAI_API_KEY": "explicit-secret"}
            full_run_module._configure_grok_auth(
                repo, run_root, state, api_env, grant_grok_auth=False
            )
            self.assertEqual(state.grok_auth_strategy, "xai_api_key")
            self.assertNotIn("GROK_AUTH_PATH", api_env)
            self.assertIsNone(state.grok_auth_path_identity)

            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._configure_grok_auth(
                    repo, run_root, state, api_env, grant_grok_auth=True
                )
            self.assertEqual(ctx.exception.code, "full_run_grok_auth_ambiguous")

    def test_digest_keyed_dirs_and_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            packet = repo / "p.md"
            packet.write_text("x\n")
            start_head = _init_feature_repo(repo, branch="feat")
            wt = repo
            sid = "a/b"
            prepare_full_run(
                repo,
                session_id=sid,
                branch="feat",
                start_head=start_head,
                worktree=wt,
                packet_path=packet,
                adapter="fixture",
                fixture_script=repo / "n.py",
            )
            (repo / "n.py").write_text("print(1)\n")
            root = full_run_root(repo, sid)
            self.assertIn(digest_key(sid, prefix="fullrun"), str(root))
            self.assertNotIn("a/b", root.name)
            with self.assertRaises(ValidationIssue):
                prepare_full_run(
                    repo,
                    session_id=sid,
                    branch="feat",
                    start_head=start_head,
                    worktree=wt,
                    packet_path=packet,
                    adapter="fixture",
                    fixture_script=repo / "n.py",
                )

    def test_prepare_preflight_rejects_wrong_branch_head_protected_branch_and_symlink_packet(
        self,
    ) -> None:
        cases = ("branch", "head", "protected", "symlink")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                branch = "main" if case == "protected" else "feat/x"
                packet_target = repo / "packet-target.md"
                packet_target.write_text("packet\n", encoding="utf-8")
                packet = repo / "packet.md"
                if case == "symlink":
                    packet.symlink_to(packet_target)
                else:
                    packet.write_text("packet\n", encoding="utf-8")
                start = _init_feature_repo(repo, branch=branch)
                staged_branch = "feat/other" if case == "branch" else branch
                staged_head = "0" * 40 if case == "head" else start
                with self.assertRaises(ValidationIssue):
                    prepare_full_run(
                        repo,
                        session_id=f"preflight-{case}",
                        branch=staged_branch,
                        start_head=staged_head,
                        worktree=repo,
                        packet_path=packet,
                        adapter="fixture",
                        fixture_script=repo / "fixture.py",
                    )


class EventSalvageAndDeliveryTests(unittest.TestCase):
    """B3: torn-final-line salvage on reconstruction and delivery proof."""

    def test_read_events_keeps_valid_lines_before_a_torn_final_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.jsonl"
            valid = {
                "timestamp": "2026-07-19T05:14:00Z",
                "session_id": "session-1",
                "branch": "feat/x",
                "head": "a" * 40,
                "batch": 0,
                "type": "batch_complete",
                "summary": "batch complete",
                "confidence": "low",
                "unsure_about": ["salvaged reservation"],
            }
            events.write_text(
                json.dumps(valid) + "\n" + '{"type": "batch_co',
                encoding="utf-8",
            )
            rows, errors = full_run_module._read_events(
                events,
                expected_session_id="session-1",
                expected_branch="feat/x",
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["confidence"], "low")
            self.assertTrue(
                any("incomplete" in error for error in errors), errors
            )

    def test_review_context_partial_evidence_wording(self) -> None:
        report = {
            "batches": [
                {"id": "batch-1", "status": "complete", "evidence": "ok"}
            ]
        }
        partial_absent = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=report,
            events=[],
            event_evidence_partial=True,
        )
        self.assertTrue(partial_absent["event_evidence_partial"])
        block = partial_absent["review_prompt_block"]
        self.assertIn("partial or discarded during", block)
        self.assertNotIn("No worker confidence signal was reported", block)

        partial_present = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=report,
            events=[
                {
                    "type": "batch_complete",
                    "batch": 1,
                    "confidence": "low",
                    "unsure_about": ["salvaged reservation"],
                }
            ],
            event_evidence_partial=True,
        )
        self.assertIn(
            "partial or discarded", partial_present["review_prompt_block"]
        )
        self.assertIn(
            "salvaged reservation", partial_present["review_prompt_block"]
        )

        intact = build_worker_confidence_review_context(
            session_id="session-1",
            branch="feat/x",
            final_head="b" * 40,
            report=report,
            events=[],
        )
        self.assertFalse(intact["event_evidence_partial"])
        self.assertIn(
            "No worker confidence signal was reported",
            intact["review_prompt_block"],
        )

    def test_reconstruction_salvages_confidence_from_torn_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            start = "a" * 40
            tip = "b" * 40
            state = full_run_module.FullRunState(
                session_id="session-1",
                branch="feat/x",
                start_head=start,
                worktree=str(repo),
                packet_path=str(repo / "packet.md"),
                acceptance_criteria={"B1-A1": "verified behavior"},
                origin_url="https://github.com/example/repo.git",
                origin_config_digest="origin-digest",
                exit_code=0,
            )
            confidence_event = {
                "type": "batch_complete",
                "batch": 1,
                "confidence": "low",
                "unsure_about": ["salvaged retry path"],
            }
            with (
                mock.patch.object(
                    full_run_module, "_full_run_lock", return_value=nullcontext()
                ),
                mock.patch.object(full_run_module, "load_state", return_value=state),
                mock.patch.object(
                    full_run_module, "verify_protected_refs_unchanged", return_value=[]
                ),
                mock.patch.object(
                    full_run_module,
                    "_canonical_origin_url",
                    return_value=state.origin_url,
                ),
                mock.patch.object(
                    full_run_module,
                    "_origin_config_digest",
                    return_value=state.origin_config_digest,
                ),
                mock.patch.object(full_run_module, "_assert_clean_worktree"),
                mock.patch.object(full_run_module, "_git_head", return_value=tip),
                mock.patch.object(full_run_module, "_is_ancestor", return_value=True),
                mock.patch.object(
                    full_run_module, "_git_commit_chain", return_value=[tip]
                ),
                mock.patch.object(
                    full_run_module,
                    "run_git",
                    return_value=mock.Mock(returncode=0, stdout="implemented\n", stderr=""),
                ),
                mock.patch.object(full_run_module, "write_report"),
                mock.patch.object(full_run_module, "save_state"),
                mock.patch.object(
                    full_run_module,
                    "_launch_evidence_context",
                    return_value=(True, frozenset()),
                ),
                mock.patch.object(
                    full_run_module,
                    "_read_events",
                    # A torn final line: the valid earlier event survives and
                    # the recorded error marks the evidence partial.
                    return_value=(
                        [confidence_event],
                        ["final event record is incomplete"],
                    ),
                ),
            ):
                result = reconstruct_missing_report(
                    repo,
                    session_id=state.session_id,
                    host_tests_pass=True,
                )

        self.assertTrue(result["ok"], result)
        review = result["review_context"]
        self.assertEqual(review["lowest_confidence"], "low")
        self.assertTrue(review["event_evidence_partial"])
        self.assertIn("salvaged retry path", review["review_prompt_block"])
        self.assertIn("partial or discarded", review["review_prompt_block"])

    def test_monitor_and_await_deliver_review_context_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            packet = root / "packet.md"
            _write_production_packet(packet, "B1-A1")
            head = _init_feature_repo(repo)
            _attach_origin(repo, root / "origin.git", "feat/x")
            session = "review-context-delivery"
            prepare_full_run(
                repo,
                session_id=session,
                branch="feat/x",
                start_head=head,
                worktree=repo,
                packet_path=packet,
                session_path=_write_production_acceptance_contract(repo, packet),
                adapter="grok-build",
                executable="grok",
            )
            state = load_state(repo, session)
            state.status = "complete"
            state.next_action = "final_readiness"
            state.head = head
            full_run_module.save_state(repo, state)
            review_context = {
                "schema": "elves-worker-confidence-review-v1",
                "review_prompt_block": "## Worker confidence triage (test sentinel)",
            }
            reconcile_payload = {
                "ok": True,
                "review_context": review_context,
                "final_head": head,
            }
            with mock.patch.object(
                full_run_module,
                "reconcile_full_run_with_git",
                return_value=reconcile_payload,
            ) as reconcile_mock:
                observed = monitor_full_run(repo, session_id=session)
            self.assertTrue(reconcile_mock.called)
            self.assertEqual(observed["review_context"], review_context)

            with mock.patch.object(
                full_run_module,
                "reconcile_full_run_with_git",
                return_value=reconcile_payload,
            ):
                awaited = await_full_run(
                    repo,
                    session_id=session,
                    timeout_seconds=0.0,
                    quiet=True,
                )
            self.assertEqual(awaited["review_context"], review_context)

    def test_cli_print_sites_emit_review_prompt_block(self) -> None:
        import cobbler_agents as cli_mod

        review_context = {
            "review_prompt_block": "## Worker confidence triage (cli sentinel)"
        }
        cases = (
            (
                "monitor_full_run",
                ["implement", "full-run-monitor", "--session-id", "s1"],
                {"state": "complete", "review_context": review_context},
            ),
            (
                "await_full_run",
                ["implement", "full-run-await", "--session-id", "s1", "--quiet"],
                {"state": "complete", "review_context": review_context},
            ),
            (
                "reconstruct_missing_report",
                [
                    "implement",
                    "full-run-reconcile",
                    "--session-id",
                    "s1",
                    "--host-tests-pass",
                ],
                {"ok": True, "review_context": review_context},
            ),
        )
        for target, argv, payload in cases:
            with self.subTest(target=target):
                stdout = io.StringIO()
                with (
                    mock.patch.object(
                        cli_mod, target, return_value=payload
                    ),
                    mock.patch.object(sys, "stdout", stdout),
                ):
                    code = cli_mod.main(argv)
                self.assertEqual(code, 0)
                self.assertIn(
                    "## Worker confidence triage (cli sentinel)",
                    stdout.getvalue(),
                )


class WorkerEffortAuthorityTests(unittest.TestCase):
    """B2: one normalized default authority plus persisted explicitness."""

    def test_cli_rejects_abbreviated_long_options(self) -> None:
        import cobbler_agents as cli_mod

        base = [
            "implement",
            "full-run-prepare",
            "--session-id",
            "abbrev-guard",
            "--branch",
            "feat/x",
            "--start-head",
            "a" * 40,
            "--packet",
            "/tmp/packet.md",
        ]
        parser = cli_mod.build_parser()
        for abbreviation in (["--effor", "low"], ["--eff", "low"]):
            with self.subTest(abbreviation=abbreviation[0]):
                stderr = io.StringIO()
                with (
                    mock.patch.object(sys, "stderr", stderr),
                    self.assertRaises(SystemExit) as ctx,
                ):
                    parser.parse_args(base + abbreviation)
                self.assertNotEqual(ctx.exception.code, 0)
                self.assertIn(abbreviation[0], stderr.getvalue())
        # The exact spelling still parses, and omission passes None so
        # prepare_full_run stays the single default authority.
        parsed = parser.parse_args(base + ["--effort", "low"])
        self.assertEqual(parsed.effort, "low")
        self.assertIsNone(parser.parse_args(base).effort)

    def test_resolution_normalizes_adapter_and_effort(self) -> None:
        resolve = full_run_module.resolve_worker_effort
        self.assertEqual(resolve("grok-build", None), ("high", False))
        self.assertEqual(resolve("Grok-Build", None), ("high", False))
        self.assertEqual(resolve("  GROK-BUILD  ", None), ("high", False))
        self.assertEqual(
            resolve("fixture", None), (full_run_module.DEFAULT_EFFORT, False)
        )
        self.assertEqual(resolve("Grok-Build", " Medium "), ("medium", True))
        self.assertEqual(resolve(None, None), ("high", False))

    def _fixture_prepare(self, repo: Path, *, effort: str | None, create: bool = True):
        packet = repo / "packet.md"
        if not packet.exists():
            packet.write_text("fixture packet\n", encoding="utf-8")
        worker = repo / "worker.py"
        if not worker.exists():
            worker.write_text("print('ok')\n", encoding="utf-8")
        head = _init_feature_repo(repo) if not (repo / ".git").exists() else None
        return prepare_full_run(
            repo,
            session_id="effort-explicitness",
            branch="feat/x",
            start_head=head or full_run_module._git_head(repo),
            worktree=repo,
            packet_path=packet,
            adapter="fixture",
            fixture_script=worker,
            effort=effort,
            create=create,
        )

    def test_flagless_resume_prepare_keeps_originally_explicit_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._fixture_prepare(repo, effort="low")
            state = load_state(repo, "effort-explicitness")
            self.assertEqual(state.effort, "low")
            self.assertTrue(state.effort_explicit)

            # A second create prepare still fails closed.
            with self.assertRaises(full_run_module.ValidationIssue) as ctx:
                self._fixture_prepare(repo, effort=None, create=True)
            self.assertEqual(ctx.exception.code, "full_run_already_prepared")

            # A flagless resume prepare keeps the explicit value instead of
            # flipping to the adapter default.
            self._fixture_prepare(repo, effort=None, create=False)
            resumed = load_state(repo, "effort-explicitness")
            self.assertEqual(resumed.effort, "low")
            self.assertTrue(resumed.effort_explicit)
            self.assertFalse(resumed.create_session)

    def test_flagless_resume_prepare_over_default_stays_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._fixture_prepare(repo, effort=None)
            state = load_state(repo, "effort-explicitness")
            self.assertEqual(state.effort, full_run_module.DEFAULT_EFFORT)
            self.assertFalse(state.effort_explicit)
            self._fixture_prepare(repo, effort=None, create=False)
            resumed = load_state(repo, "effort-explicitness")
            self.assertEqual(resumed.effort, full_run_module.DEFAULT_EFFORT)
            self.assertFalse(resumed.effort_explicit)

    def test_resume_prepare_refuses_possibly_live_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._fixture_prepare(repo, effort="low")
            state = load_state(repo, "effort-explicitness")
            state.pid = 4242
            full_run_module.save_state(repo, state)
            with self.assertRaises(full_run_module.ValidationIssue) as ctx:
                self._fixture_prepare(repo, effort=None, create=False)
            self.assertEqual(
                ctx.exception.code, "full_run_resume_prepare_live"
            )

    def test_resume_prepare_refuses_terminal_run_complete_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            prep = self._fixture_prepare(repo, effort="low")
            events_path = Path(prep["events_path"])
            before = events_path.read_bytes()
            state = load_state(repo, "effort-explicitness")
            state.status = "complete"
            state.pid = None
            full_run_module.save_state(repo, state)
            with events_path.open("ab") as handle:
                handle.write(
                    (
                        json.dumps(
                            {
                                "timestamp": "2026-08-01T00:00:00Z",
                                "session_id": "effort-explicitness",
                                "branch": "feat/x",
                                "head": state.head,
                                "batch": 0,
                                "type": "run_complete",
                                "summary": "done",
                            }
                        )
                        + "\n"
                    ).encode("utf-8")
                )
            after_append = events_path.read_bytes()
            with self.assertRaises(full_run_module.ValidationIssue) as ctx:
                self._fixture_prepare(repo, effort=None, create=False)
            self.assertEqual(
                ctx.exception.code, "full_run_resume_prepare_terminal"
            )
            self.assertEqual(events_path.read_bytes(), after_append)
            self.assertNotEqual(after_append, before)
            # No second run_started after the terminal event.
            text = after_append.decode("utf-8")
            self.assertEqual(text.count('"type":"run_started"'), 1)
            self.assertIn('"type": "run_complete"', text)

    def test_resume_prepare_refuses_terminal_blocked_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            prep = self._fixture_prepare(repo, effort="low")
            events_path = Path(prep["events_path"])
            before = events_path.read_bytes()
            state = load_state(repo, "effort-explicitness")
            state.status = "blocked"
            state.pid = None
            full_run_module.save_state(repo, state)
            with events_path.open("ab") as handle:
                handle.write(
                    (
                        json.dumps(
                            {
                                "timestamp": "2026-08-01T00:00:00Z",
                                "session_id": "effort-explicitness",
                                "branch": "feat/x",
                                "head": state.head,
                                "batch": 0,
                                "type": "blocked",
                                "summary": "blocked",
                            }
                        )
                        + "\n"
                    ).encode("utf-8")
                )
            after_append = events_path.read_bytes()
            with self.assertRaises(full_run_module.ValidationIssue) as ctx:
                self._fixture_prepare(repo, effort=None, create=False)
            self.assertEqual(
                ctx.exception.code, "full_run_resume_prepare_terminal"
            )
            self.assertEqual(events_path.read_bytes(), after_append)
            self.assertEqual(after_append[: len(before)], before)

    def test_prepare_full_run_keeps_the_serialization_lock(self) -> None:
        # v2.10.2 terminal-review blocker: inserting resolve_worker_effort
        # between @_locked_full_run and prepare_full_run silently moved the
        # per-session lock onto the pure helper, leaving prepare unserialized
        # against concurrent launch/stop/monitor. The lock must wrap the
        # state-mutating entry point, and the pure helper must stay bare.
        self.assertTrue(
            hasattr(full_run_module.prepare_full_run, "__wrapped__"),
            "prepare_full_run must carry the _locked_full_run wrapper",
        )
        self.assertFalse(
            hasattr(full_run_module.resolve_worker_effort, "__wrapped__"),
            "resolve_worker_effort is a pure helper and must stay undecorated",
        )


class FullRunLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.worker = Path(self.tmp.name) / "fake_worker.py"
        self.worker.write_text(FAKE_WORKER, encoding="utf-8")
        self.worker.chmod(self.worker.stat().st_mode | stat.S_IXUSR)
        self.packet = Path(self.tmp.name) / "packet.md"
        self.packet.write_text("# packet\n", encoding="utf-8")
        self.session = "sess-full-run-001"
        self.branch = "codex/delegated-worker-v2-1"
        self.start_head = "aaa111"
        # git worktree for ancestry/branch checks
        os.system(f"git -C {self.repo} init -q")
        os.system(f"git -C {self.repo} config user.email t@t")
        os.system(f"git -C {self.repo} config user.name t")
        (self.repo / ".gitignore").write_text(".elves/\n", encoding="utf-8")
        (self.repo / "f.txt").write_text("1\n")
        os.system(
            f"git -C {self.repo} add .gitignore f.txt && "
            f"git -C {self.repo} commit -q -m init"
        )
        os.system(f"git -C {self.repo} checkout -q -b {self.branch}")
        self.start_head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        # Isolated fake Devin CLI auth directories for full-run tests.
        self.devin_config_dir = Path(self.tmp.name) / "devin-config"
        self.devin_data_dir = Path(self.tmp.name) / "devin-data"
        (self.devin_config_dir / "devin").mkdir(parents=True)
        (self.devin_data_dir / "devin").mkdir(parents=True)
        (self.devin_config_dir / "devin" / "config.json").write_text(
            json.dumps({"version": 1, "devin": {"org_id": "test-org"}}, indent=2),
            encoding="utf-8",
        )
        (self.devin_config_dir / "devin" / "config.json").chmod(0o600)
        (self.devin_data_dir / "devin" / "credentials.toml").write_text(
            'windsurf_api_key = "devin-test-key-do-not-use"\n'
            'api_server_url = "https://server.codeium.com"\n'
            'devin_webapp_host = "https://app.devin.ai"\n'
            'devin_api_url = "https://api.devin.ai"\n',
            encoding="utf-8",
        )
        (self.devin_data_dir / "devin" / "credentials.toml").chmod(0o600)

    def tearDown(self) -> None:
        try:
            stop_full_run(self.repo, session_id=self.session, grace_seconds=0.1)
        except Exception:
            pass
        self.tmp.cleanup()

    def test_fixture_multi_batch_and_bounded_status(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        launch = launch_full_run(self.repo, session_id=self.session)
        self.assertTrue(launch["returned_promptly"])
        self.assertEqual(launch["adapter"], "fixture")
        self.assertFalse(launch["merge_authority"])
        deadline = time.time() + 10
        status = monitor_full_run(self.repo, session_id=self.session, stale_after_seconds=60)
        while status.get("state") not in {"complete", "failed", "blocked"} and time.time() < deadline:
            time.sleep(0.05)
            status = monitor_full_run(self.repo, session_id=self.session, stale_after_seconds=60)
        self.assertEqual(status["state"], "complete", status)
        self.assertTrue(status["transcript_private"])
        self.assertFalse(status["merge_authority"])
        self.assertEqual(status["driver_monitor_mode"], "parked_monitor")
        self.assertEqual(status["driver_contract"], "parked_monitor")
        self.assertNotIn("transcript", status)
        logs = logs_full_run(self.repo, session_id=self.session, raw_tail=False)
        self.assertFalse(logs["transcript_included"])
        self.assertEqual(status["check_summary"]["exit_code"], 0)
        self.assertTrue(status["check_summary"]["exit_record"])
        bounded = logs_full_run(
            self.repo, session_id=self.session, raw_tail=True, tail_lines=10000
        )
        self.assertLessEqual(len(bounded["events_tail"]), 100)
        self.assertLessEqual(len(bounded["transcript_tail"]), 100)
        self.assertTrue(all(len(line) <= 1000 for line in bounded["transcript_tail"]))

    def test_monitor_surfaces_batch_complete_confidence_signal(self) -> None:
        confident = FAKE_WORKER.replace(
            'emit("batch_complete", batch, f"batch {batch} complete", head=head)',
            'emit("batch_complete", batch, f"batch {batch} complete", head=head, '
            'confidence="medium", unsure_about=[f"retry bounds in batch {batch}"])',
        )
        self.assertNotEqual(confident, FAKE_WORKER)
        worker = Path(self.tmp.name) / "confident_worker.py"
        worker.write_text(confident, encoding="utf-8")
        worker.chmod(worker.stat().st_mode | stat.S_IXUSR)
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=worker,
        )
        launch_full_run(self.repo, session_id=self.session)
        deadline = time.time() + 10
        status = monitor_full_run(
            self.repo, session_id=self.session, stale_after_seconds=60
        )
        while (
            status.get("state") not in {"complete", "failed", "blocked"}
            and time.time() < deadline
        ):
            time.sleep(0.05)
            status = monitor_full_run(
                self.repo, session_id=self.session, stale_after_seconds=60
            )
        self.assertEqual(status["state"], "complete", status)
        self.assertEqual(
            status["check_summary"]["last_batch_confidence"], "medium"
        )
        self.assertEqual(
            status["check_summary"]["last_batch_unsure_about"],
            ["retry bounds in batch 3"],
        )
        self.assertEqual(
            status["check_summary"]["last_batch_unsure_about_count"], 1
        )
        # A second monitor pass (terminal state re-reads the full log) keeps
        # surfacing the signal, and the persisted event-summary cache carries
        # all three fields for later cache-reusing polls.
        repeated = monitor_full_run(
            self.repo, session_id=self.session, stale_after_seconds=60
        )
        self.assertEqual(
            repeated["check_summary"]["last_batch_confidence"], "medium"
        )
        self.assertEqual(
            repeated["check_summary"]["last_batch_unsure_about"],
            ["retry bounds in batch 3"],
        )
        cache_path = (
            self.repo / ".elves" / "runtime" / "implement" / "full-run" / self.session / "monitor-cache.json"
        )
        if cache_path.is_file():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            summary = cached.get("event_summary") or {}
            self.assertEqual(summary.get("last_batch_confidence"), "medium")
            self.assertEqual(
                summary.get("last_batch_unsure_about"),
                ["retry bounds in batch 3"],
            )
            self.assertEqual(summary.get("last_batch_unsure_about_count"), 1)

    def test_monitor_resets_signal_when_a_later_batch_omits_it(self) -> None:
        # Batch signals must not leak forward: a later batch_complete without
        # the fields resets last_batch_* to the no-signal state (null).
        confident_then_silent = FAKE_WORKER.replace(
            'emit("batch_complete", batch, f"batch {batch} complete", head=head)',
            'emit("batch_complete", batch, f"batch {batch} complete", head=head, '
            '**({"confidence": "low", "unsure_about": ["early wiring"]} if batch == 1 else {}))',
        )
        self.assertNotEqual(confident_then_silent, FAKE_WORKER)
        worker = Path(self.tmp.name) / "confident_then_silent_worker.py"
        worker.write_text(confident_then_silent, encoding="utf-8")
        worker.chmod(worker.stat().st_mode | stat.S_IXUSR)
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=worker,
        )
        launch_full_run(self.repo, session_id=self.session)
        deadline = time.time() + 10
        status = monitor_full_run(
            self.repo, session_id=self.session, stale_after_seconds=60
        )
        while (
            status.get("state") not in {"complete", "failed", "blocked"}
            and time.time() < deadline
        ):
            time.sleep(0.05)
            status = monitor_full_run(
                self.repo, session_id=self.session, stale_after_seconds=60
            )
        self.assertEqual(status["state"], "complete", status)
        self.assertIsNone(status["check_summary"]["last_batch_confidence"])
        self.assertIsNone(status["check_summary"]["last_batch_unsure_about"])
        self.assertIsNone(
            status["check_summary"]["last_batch_unsure_about_count"]
        )

    def test_json_await_streams_sanitized_follow_to_stderr_and_terminal_json_to_stdout(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "implement",
                "full-run-await",
                "--repo-root",
                str(self.repo),
                "--session-id",
                self.session,
                "--timeout",
                "0",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["follow"])
        self.assertIn("run_started", result.stderr)

    def test_material_scope_change_event_wakes_parked_driver(self) -> None:
        sleeper = Path(self.tmp.name) / "material_change_sleeper.py"
        sleeper.write_text(LONG_SLEEPER, encoding="utf-8")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=sleeper,
        )
        launch_full_run(self.repo, session_id=self.session)
        event = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "session_id": self.session,
            "branch": self.branch,
            "head": self.start_head,
            "batch": 1,
            "type": "material_scope_or_assumption_change",
            "change_id": "unexpected-api-contract",
            "change_kind": "assumption",
            "summary": "A staged compatibility assumption no longer holds",
        }
        with (full_run_root(self.repo, self.session) / "events.jsonl").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write(json.dumps(event) + "\n")
        status = monitor_full_run(
            self.repo, session_id=self.session, stale_after_seconds=60
        )
        self.assertEqual(
            status["next_action"],
            "driver_wake_material_scope_or_assumption_change",
            status,
        )
        self.assertTrue(status["material_transition"])

    def test_planned_high_risk_checkpoint_wakes_once_then_explicit_ack_reparks(self) -> None:
        self.packet.write_text(
            "# packet\n\n- High-risk checkpoint: security-boundary\n",
            encoding="utf-8",
        )
        worker = Path(self.tmp.name) / "checkpoint_worker.py"
        worker.write_text(
            "import json, os, time\n"
            "from datetime import datetime, timezone\n"
            "from pathlib import Path\n"
            "event = {\n"
            "  'timestamp': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),\n"
            "  'session_id': os.environ['ELVES_FULL_RUN_SESSION'],\n"
            "  'branch': os.environ['ELVES_FULL_RUN_BRANCH'],\n"
            "  'head': os.environ['ELVES_FULL_RUN_START_HEAD'],\n"
            "  'batch': 1,\n"
            "  'type': 'high_risk_checkpoint',\n"
            "  'checkpoint_id': 'security-boundary',\n"
            "  'summary': 'Host review requested',\n"
            "}\n"
            "with Path(os.environ['ELVES_FULL_RUN_EVENTS']).open('a') as handle:\n"
            "  handle.write(json.dumps(event, separators=(',', ':')) + '\\n')\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        prepare = prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=worker,
        )
        self.assertEqual(
            prepare["state"]["planned_high_risk_checkpoints"],
            ["security-boundary"],
        )
        launch_full_run(self.repo, session_id=self.session)
        events_path = full_run_root(self.repo, self.session) / "events.jsonl"
        deadline = time.time() + 5
        while "security-boundary" not in events_path.read_text(encoding="utf-8"):
            self.assertLess(time.time(), deadline, "checkpoint event was not emitted")
            time.sleep(0.02)

        wake = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(wake["state"], "healthy", wake)
        self.assertEqual(
            wake["next_action"], "driver_wake_high_risk_checkpoint"
        )
        self.assertEqual(wake["pending_high_risk_checkpoint"], "security-boundary")
        self.assertTrue(wake["chat_update_recommended"])
        self.assertFalse(wake["unchanged_healthy_poll_silent"])

        repeated = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(
            repeated["next_action"], "driver_wake_high_risk_checkpoint"
        )
        self.assertFalse(repeated["chat_update_recommended"])
        self.assertFalse(repeated["unchanged_healthy_poll_silent"])

        acknowledged = monitor_full_run(
            self.repo,
            session_id=self.session,
            acknowledge_high_risk_checkpoint="security-boundary",
        )
        self.assertEqual(acknowledged["next_action"], "parked_monitor")
        self.assertIsNone(acknowledged["pending_high_risk_checkpoint"])
        self.assertEqual(
            acknowledged["acknowledged_high_risk_checkpoints"],
            ["security-boundary"],
        )
        with self.assertRaises(ValidationIssue) as ctx:
            monitor_full_run(
                self.repo,
                session_id=self.session,
                acknowledge_high_risk_checkpoint="security-boundary",
            )
        self.assertEqual(ctx.exception.code, "full_run_checkpoint_ack_invalid")

    def test_checkpoint_emitted_before_clean_exit_still_gates_final_readiness(self) -> None:
        self.packet.write_text(
            "# packet\n\n- High-risk checkpoint: security-boundary\n",
            encoding="utf-8",
        )
        worker = Path(self.tmp.name) / "checkpoint_complete_worker.py"
        worker.write_text(
            FAKE_WORKER.replace(
                'emit("run_started", 0, "fake worker started")',
                'emit("run_started", 0, "fake worker started")\n'
                'emit("high_risk_checkpoint", 0, "host review requested", '
                'checkpoint_id="security-boundary")',
            ),
            encoding="utf-8",
        )
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=worker,
        )
        launch_full_run(self.repo, session_id=self.session)

        deadline = time.time() + 10
        status = monitor_full_run(self.repo, session_id=self.session)
        while (
            status.get("state") not in {"complete", "failed"}
            and time.time() < deadline
        ):
            time.sleep(0.05)
            status = monitor_full_run(self.repo, session_id=self.session)

        self.assertEqual(status["state"], "complete", status)
        self.assertEqual(
            status["next_action"], "driver_wake_high_risk_checkpoint"
        )
        self.assertEqual(status["pending_high_risk_checkpoint"], "security-boundary")
        acknowledged = monitor_full_run(
            self.repo,
            session_id=self.session,
            acknowledge_high_risk_checkpoint="security-boundary",
        )
        self.assertEqual(acknowledged["state"], "complete", acknowledged)
        self.assertEqual(acknowledged["next_action"], "final_readiness")
        self.assertIsNone(acknowledged["pending_high_risk_checkpoint"])

    def test_clean_completion_fails_when_planned_checkpoint_event_is_omitted(self) -> None:
        self.packet.write_text(
            "# packet\n\n- High-risk checkpoint: security-boundary\n",
            encoding="utf-8",
        )
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        launch_full_run(self.repo, session_id=self.session)

        deadline = time.time() + 10
        status = monitor_full_run(self.repo, session_id=self.session)
        while status.get("state") not in {"failed", "blocked"} and time.time() < deadline:
            time.sleep(0.05)
            status = monitor_full_run(self.repo, session_id=self.session)

        self.assertEqual(status["state"], "failed", status)
        self.assertEqual(status["next_action"], "driver_wake_error")
        self.assertIn("omitted", status["blocker"])

    def test_checkpoint_contract_is_bound_into_private_packet_digest(self) -> None:
        self.packet.write_text(
            "# packet\n\n- High-risk checkpoint: data-migration\n",
            encoding="utf-8",
        )
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        state = load_state(self.repo, self.session)
        self.assertEqual(state.planned_high_risk_checkpoints, ["data-migration"])
        state.planned_high_risk_checkpoints = []
        full_run_module.save_state(self.repo, state)
        with self.assertRaises(ValidationIssue) as ctx:
            launch_full_run(self.repo, session_id=self.session)
        self.assertEqual(ctx.exception.code, "full_run_packet_binding_changed")

    def test_monitor_wakes_on_pathological_event_and_report_json(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        root = full_run_root(self.repo, self.session)
        base_event = {
            "timestamp": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "session_id": self.session,
            "branch": self.branch,
            "head": self.start_head,
            "batch": 0,
            "type": "heartbeat",
            "summary": "bounded ingestion fixture",
        }
        huge_integer = json.dumps(base_event)[:-1] + ',"counter":' + ("9" * 1000) + "}"
        many_nodes = dict(base_event)
        many_nodes["extra"] = [0] * (full_run_module.MAX_JSON_NODES + 1)
        (root / "events.jsonl").write_text(
            huge_integer + "\n" + json.dumps(many_nodes) + "\n",
            encoding="utf-8",
        )
        nested: object = "leaf"
        for _ in range(full_run_module.MAX_JSON_DEPTH + 5):
            nested = [nested]
        (root / "report.json").write_text(
            json.dumps({"nested": nested}) + "\n",
            encoding="utf-8",
        )

        observed = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(observed["state"], "failed", observed)
        self.assertEqual(observed["next_action"], "driver_wake_error")
        self.assertGreaterEqual(observed["check_summary"]["event_errors"], 2)
        self.assertGreaterEqual(observed["check_summary"]["report_errors"], 1)

    def test_launch_grant_override_is_persisted_and_exact_value_is_redacted(self) -> None:
        worker = Path(self.tmp.name) / "secret_worker.py"
        worker.write_text(
            "import os, time\n"
            "from pathlib import Path\n"
            "Path(os.environ['ELVES_FULL_RUN_TRANSCRIPT']).write_text("
            "os.environ['CUSTOM_OPAQUE_TOKEN'] + '\\n', encoding='utf-8')\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        secret = "opaque-value-without-a-known-provider-prefix-93742"
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=worker,
            credential_grant_names=[],
        )
        with mock.patch.dict(os.environ, {"CUSTOM_OPAQUE_TOKEN": secret}, clear=False):
            launch_full_run(
                self.repo,
                session_id=self.session,
                credential_grant_names=["CUSTOM_OPAQUE_TOKEN"],
            )
            deadline = time.time() + 3
            transcript = full_run_root(self.repo, self.session) / "transcript.log"
            while transcript.stat().st_size == 0 and time.time() < deadline:
                time.sleep(0.02)
            state = load_state(self.repo, self.session)
            self.assertEqual(state.credential_grant_names, ["CUSTOM_OPAQUE_TOKEN"])
            logs = logs_full_run(
                self.repo, session_id=self.session, raw_tail=True, tail_lines=10
            )
            serialized = json.dumps(logs, sort_keys=True)
            self.assertNotIn(secret, serialized)
            self.assertIn("REDACTED", serialized)
        # A parked monitor normally runs in a fresh host process where the
        # launch credential is intentionally absent. Persisted keyed digest +
        # length metadata must keep evidence validation available without
        # storing or reloading the raw value.
        state = load_state(self.repo, self.session)
        original_supervision_token = state.supervision_token
        self.assertEqual(
            state.credential_grant_lengths,
            {"CUSTOM_OPAQUE_TOKEN": len(secret)},
        )
        self.assertNotIn(secret, json.dumps(state.to_dict(), sort_keys=True))
        verified, absent_values = full_run_module._launch_evidence_context(state)
        self.assertTrue(verified)
        self.assertNotIn(secret, absent_values)
        available = logs_full_run(
            self.repo, session_id=self.session, raw_tail=True, tail_lines=10
        )
        available_serialized = json.dumps(available, sort_keys=True)
        self.assertTrue(available["transcript_included"])
        self.assertEqual(
            available["transcript_tail"],
            ["[REDACTED:credential_grant]"],
        )
        self.assertNotIn("cannot be verified", available_serialized)
        self.assertNotIn(secret, available_serialized)

        # Corrupting the private HMAC authority must fail closed.  A public
        # session id is never an acceptable fallback key, and bounded logs must
        # remain unavailable rather than leaking a now-undetectable grant.
        state.supervision_token = None
        with mock.patch.dict(
            os.environ,
            {"CUSTOM_OPAQUE_TOKEN": secret},
            clear=False,
        ):
            verified, still_redacted_values = (
                full_run_module._launch_evidence_context(state)
            )
        self.assertFalse(verified)
        self.assertIn(secret, still_redacted_values)
        full_run_module.save_state(self.repo, state)
        unavailable = logs_full_run(
            self.repo, session_id=self.session, raw_tail=True, tail_lines=10
        )
        unavailable_serialized = json.dumps(unavailable, sort_keys=True)
        self.assertFalse(unavailable["transcript_included"])
        self.assertIn("cannot be verified", unavailable_serialized)
        self.assertNotIn(secret, unavailable_serialized)

        state.supervision_token = "b" * 48
        full_run_module.save_state(self.repo, state)
        wrong_key = logs_full_run(
            self.repo, session_id=self.session, raw_tail=True, tail_lines=10
        )
        wrong_key_serialized = json.dumps(wrong_key, sort_keys=True)
        self.assertFalse(wrong_key["transcript_included"])
        self.assertIn("cannot be verified", wrong_key_serialized)
        self.assertNotIn(secret, wrong_key_serialized)

        state.supervision_token = original_supervision_token
        full_run_module.save_state(self.repo, state)

        # Persisted JSON field types are untrusted input to later CLI processes.
        # Scalar corruption must make public evidence unavailable without a raw
        # TypeError, even while the exact launch credential remains exported.
        for field_name in (
            "credential_grant_names",
            "credential_granted_names",
        ):
            with self.subTest(corrupt_field=field_name):
                corrupt = load_state(self.repo, self.session)
                original_value = getattr(corrupt, field_name)
                setattr(corrupt, field_name, 42)
                full_run_module.save_state(self.repo, corrupt)
                with mock.patch.dict(
                    os.environ,
                    {"CUSTOM_OPAQUE_TOKEN": secret},
                    clear=False,
                ):
                    with self.assertRaises(ValidationIssue) as ctx:
                        logs_full_run(
                            self.repo,
                            session_id=self.session,
                            raw_tail=True,
                            tail_lines=10,
                        )
                self.assertEqual(ctx.exception.code, "full_run_state_malformed")
                self.assertNotIn(secret, ctx.exception.message)
                setattr(corrupt, field_name, original_value)
                full_run_module.save_state(self.repo, corrupt)

        # Exact leaks are found in event values and report keys even without
        # the environment value. Diagnostics remain bounded and secret-free.
        run_root = full_run_root(self.repo, self.session)
        with (run_root / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc)
                        .replace(microsecond=0)
                        .isoformat(),
                        "session_id": self.session,
                        "branch": self.branch,
                        "head": self.start_head,
                        "batch": 0,
                        "type": "heartbeat",
                        "summary": f"worker leaked {secret} here",
                    }
                )
                + "\n"
            )
        leaked_report = json.loads(
            (run_root / "report.json").read_text(encoding="utf-8")
        )
        leaked_report[f"worker-{secret}-field"] = "unsafe key"
        (run_root / "report.json").write_text(
            json.dumps(leaked_report) + "\n",
            encoding="utf-8",
        )
        status = monitor_full_run(self.repo, session_id=self.session)
        leaked_logs = logs_full_run(
            self.repo, session_id=self.session, raw_tail=False, tail_lines=10
        )
        combined = json.dumps({"status": status, "logs": leaked_logs}, sort_keys=True)
        self.assertNotIn(secret, combined)
        self.assertGreater(status["check_summary"]["event_errors"], 0)
        self.assertGreater(status["check_summary"]["report_errors"], 0)
        self.assertTrue(any("secret-shaped" in row for row in leaked_logs["event_errors"]))
        sanitized_report = (run_root / "report.json").read_text(encoding="utf-8")
        self.assertNotIn(secret, sanitized_report)
        self.assertIn("REDACTED:credential_grant_key", sanitized_report)

    def test_malformed_state_fails_every_public_cli_without_traceback_or_value_leak(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        state_path = full_run_root(self.repo, self.session) / "state.json"
        record = json.loads(state_path.read_text(encoding="utf-8"))
        sentinel = "opaque-corrupt-state-secret-123456789"
        record["worktree"] = [sentinel]
        state_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

        for action in (
            "full-run-launch",
            "full-run-monitor",
            "full-run-logs",
            "full-run-stop",
        ):
            with self.subTest(action=action):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(CLI),
                        "implement",
                        action,
                        "--repo-root",
                        str(self.repo),
                        "--session-id",
                        self.session,
                        "--json",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                response = json.loads(result.stdout)
                self.assertFalse(response["ok"])
                self.assertEqual(
                    response["issues"][0]["code"],
                    "full_run_state_malformed",
                )
                surfaced = result.stdout + result.stderr
                self.assertNotIn(sentinel, surfaced)
                self.assertNotIn("Traceback", surfaced)

    def test_raw_transcript_redacts_json_credentials_and_multiline_pem(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        transcript = full_run_root(self.repo, self.session) / "transcript.log"
        transcript.write_text(
            '{"refresh_token":"opaque-refresh-value-123456789"}\n'
            "test_api_key_redaction is a legitimate test identifier\n",
            encoding="utf-8",
        )
        logs = logs_full_run(
            self.repo, session_id=self.session, raw_tail=True, tail_lines=10
        )
        serialized = json.dumps(logs, sort_keys=True)
        self.assertNotIn("opaque-refresh-value-123456789", serialized)
        self.assertIn("test_api_key_redaction", serialized)

        transcript.write_text(
            "before\n-----BEGIN PRIVATE KEY-----\nline-one\nline-two\n"
            "-----END PRIVATE KEY-----\nafter\n",
            encoding="utf-8",
        )
        pem_logs = logs_full_run(
            self.repo, session_id=self.session, raw_tail=True, tail_lines=10
        )
        self.assertEqual(pem_logs["transcript_tail"], ["[REDACTED:pem_block]"])

    def test_event_reader_bounds_and_partial_final_policy(self) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "session_id": self.session,
            "branch": self.branch,
            "head": self.start_head,
            "batch": 0,
            "type": "heartbeat",
            "summary": "bounded event",
        }
        encoded = json.dumps(event, separators=(",", ":")).encode("utf-8")
        root = Path(self.tmp.name)
        partial = root / "partial.jsonl"
        partial.write_bytes(encoded)
        rows, errors = full_run_module._read_events(
            partial,
            expected_session_id=self.session,
            expected_branch=self.branch,
            allow_partial_final=True,
        )
        self.assertEqual(rows, [])
        self.assertEqual(errors, [])
        rows, errors = full_run_module._read_events(
            partial,
            expected_session_id=self.session,
            expected_branch=self.branch,
            allow_partial_final=False,
        )
        self.assertEqual(rows, [])
        self.assertTrue(any("incomplete" in error for error in errors), errors)

        too_many = root / "too-many.jsonl"
        too_many.write_bytes((encoded + b"\n") * (full_run_module.MAX_EVENT_LINES + 1))
        _rows, errors = full_run_module._read_events(
            too_many,
            expected_session_id=self.session,
            expected_branch=self.branch,
        )
        self.assertTrue(any("line limit" in error for error in errors), errors)

    def test_shared_oauth_projection_carries_confidence_and_derived_unsure_count(self) -> None:
        # Under shared OAuth the free-text unsure_about list is hidden, but
        # suppression must never read as the asserted-clean empty list: the
        # projection carries the confidence enum (validated fail-closed) plus
        # a bounded derived unsure_about_count instead of the text.
        def event(batch, **extra):
            return {
                "timestamp": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
                "session_id": self.session,
                "branch": self.branch,
                "head": self.start_head,
                "batch": batch,
                "type": "batch_complete",
                "summary": f"batch {batch} complete",
                **extra,
            }

        root = Path(self.tmp.name)
        events_path = root / "oauth-confidence.jsonl"
        events_path.write_text(
            json.dumps(
                event(1, confidence="medium", unsure_about=["retry bounds", "cache path"])
            )
            + "\n"
            + json.dumps(event(2, confidence="high", unsure_about=[]))
            + "\n",
            encoding="utf-8",
        )
        rows, errors = full_run_module._read_events(
            events_path,
            expected_session_id=self.session,
            expected_branch=self.branch,
            shared_oauth_safe_projection=True,
        )
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["confidence"], "medium")
        self.assertNotIn("unsure_about", rows[0])
        self.assertEqual(rows[0]["unsure_about_count"], 2)
        self.assertEqual(rows[1]["confidence"], "high")
        self.assertEqual(rows[1]["unsure_about_count"], 0)

        malformed = root / "oauth-bad-confidence.jsonl"
        malformed.write_text(
            json.dumps(event(1, confidence="certain")) + "\n", encoding="utf-8"
        )
        _rows, errors = full_run_module._read_events(
            malformed,
            expected_session_id=self.session,
            expected_branch=self.branch,
            shared_oauth_safe_projection=True,
        )
        self.assertTrue(
            any("confidence" in error for error in errors), errors
        )

        malformed_unsure_cases = {
            "wrong-type": "not-a-list",
            "too-many": [f"item-{index}" for index in range(17)],
            "empty-item": [""],
            "too-long": ["x" * 501],
            "secret-shaped": ["api_key=supersecretvalue"],
        }
        for name, unsure_about in malformed_unsure_cases.items():
            with self.subTest(name=name):
                malformed_unsure = root / f"oauth-bad-unsure-{name}.jsonl"
                malformed_unsure.write_text(
                    json.dumps(
                        event(
                            1,
                            confidence="high",
                            unsure_about=unsure_about,
                        )
                    )
                    + "\n",
                    encoding="utf-8",
                )
                rows, errors = full_run_module._read_events(
                    malformed_unsure,
                    expected_session_id=self.session,
                    expected_branch=self.branch,
                    shared_oauth_safe_projection=True,
                )
                self.assertEqual(rows, [])
                self.assertTrue(
                    any("unsure_about" in error for error in errors), errors
                )

        too_large = root / "too-large.jsonl"
        too_large.write_bytes(b"x" * (full_run_module.MAX_EVENT_FILE_BYTES + 1))
        _rows, errors = full_run_module._read_events(
            too_large,
            expected_session_id=self.session,
            expected_branch=self.branch,
        )
        self.assertTrue(any("exceeds" in error for error in errors), errors)

    def test_invalid_or_oversized_report_fails_closed_without_crashing(self) -> None:
        for payload in (
            b"\xff\xfe",
            b"{" + b"x" * full_run_module.MAX_REPORT_BYTES,
        ):
            with self.subTest(size=len(payload)):
                session = f"{self.session}-{len(payload)}"
                prepare_full_run(
                    self.repo,
                    session_id=session,
                    branch=self.branch,
                    start_head=self.start_head,
                    worktree=self.repo,
                    packet_path=self.packet,
                    adapter="fixture",
                    fixture_script=self.worker,
                )
                report = full_run_root(self.repo, session) / "report.json"
                report.write_bytes(payload)
                status = monitor_full_run(self.repo, session_id=session)
                self.assertEqual(status["state"], "failed", status)
                self.assertEqual(status["next_action"], "driver_wake_error")

    def test_real_resume_archives_attempt_after_committed_pushed_checkpoint(self) -> None:
        self.session = "11111111-1111-4111-8111-111111111103"
        remote = Path(self.tmp.name) / "resume-origin.git"
        _attach_origin(self.repo, remote, self.branch)
        grok = _compile_native_grok_launcher(
            Path(self.tmp.name),
            GROK_COMMIT_AND_WAIT,
            name="fake-grok",
        )
        _write_production_packet(self.packet)
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            session_path=_write_production_acceptance_contract(
                self.repo, self.packet
            ),
            adapter="grok-build",
            executable=str(grok),
        )
        host_home = Path(self.tmp.name) / "host-home"
        host_auth = host_home / ".grok" / "auth.json"
        host_auth.parent.mkdir(parents=True)
        host_auth.write_text(
            json.dumps({"account": {"key": "test-access", "refresh_token": "test-refresh"}}),
            encoding="utf-8",
        )
        host_auth.chmod(0o600)
        with mock.patch.dict(os.environ, {"HOME": str(host_home)}, clear=False):
            with mock.patch(
                "cobbler_runtime.worker_routing.probe_grok_capabilities",
                return_value=_proven_test_grok_capabilities(),
            ):
                launched = launch_full_run(
                    self.repo, session_id=self.session, grant_grok_auth=True
                )
            self.assertEqual(launched["grok_auth_strategy"], "oauth_shared_file")
            self.assertNotIn(str(host_auth), json.dumps(launched, sort_keys=True))
            self.assertFalse(
                (
                    full_run_root(self.repo, self.session)
                    / full_run_module.GROK_HOME_REL
                    / "auth.json"
                ).exists()
            )
            deadline = time.time() + 8
            checkpoint = self.start_head
            while checkpoint == self.start_head and time.time() < deadline:
                time.sleep(0.05)
                checkpoint = subprocess.run(
                    ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            self.assertNotEqual(checkpoint, self.start_head)
            stopped = stop_full_run(self.repo, session_id=self.session, grace_seconds=1.0)
            self.assertTrue(stopped["ok"], stopped)
            self.assertTrue(host_auth.is_file())
            closed = load_state(self.repo, self.session)
            self.assertIsNone(closed.pid)
            self.assertIsNone(closed.pgid)
            self.assertIsNone(closed.fingerprint)
            self.assertIsNotNone(closed.interruption_evidence)

            rotated = host_auth.with_name("auth.next")
            rotated.write_text(
                json.dumps(
                    {
                        "account": {
                            "key": "rotated-access",
                            "refresh_token": "rotated-refresh",
                        }
                    }
                ),
                encoding="utf-8",
            )
            rotated.chmod(0o600)
            rotated.replace(host_auth)
            rotated_bytes = host_auth.read_bytes()
            with mock.patch(
                "cobbler_runtime.worker_routing.probe_grok_capabilities",
                return_value=_proven_test_grok_capabilities(),
            ):
                resumed = launch_full_run(
                    self.repo, session_id=self.session, resume=True
                )
            self.assertIn("--resume", resumed["argv"])
            index = resumed["argv"].index("--resume")
            self.assertEqual(resumed["argv"][index + 1], self.session)
            self.assertNotIn("--session-id", resumed["argv"])
            self.assertNotIn(str(host_auth), json.dumps(resumed, sort_keys=True))
        state = load_state(self.repo, self.session)
        self.assertEqual(state.attempt, 2)
        self.assertEqual(state.start_head, self.start_head)
        self.assertEqual(state.launch_start_head, self.start_head)
        self.assertEqual(state.head, checkpoint)
        archive = full_run_root(self.repo, self.session) / "attempts" / "attempt-0001"
        for name in (
            "events.jsonl",
            "report.json",
            "exit_record.json",
            "supervisor.fingerprint.json",
            "worker.fingerprint.json",
        ):
            self.assertTrue((archive / name).is_file(), name)
        second_stop = stop_full_run(self.repo, session_id=self.session, grace_seconds=1.0)
        self.assertTrue(second_stop["ok"], second_stop)
        self.assertEqual(host_auth.read_bytes(), rotated_bytes)

    def test_attempt_archive_fails_closed_without_atomic_noreplace(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        state = load_state(self.repo, self.session)
        root = full_run_root(self.repo, self.session)
        events = root / "events.jsonl"
        self.assertTrue(events.is_file())

        with mock.patch(
            "cobbler_runtime.storage._load_atomic_noreplace_rename",
            return_value=None,
        ), self.assertRaises(StorageError) as ctx:
            full_run_module._archive_and_reset_resume_attempt(
                self.repo,
                state,
                checkpoint_head=self.start_head,
            )

        self.assertEqual(ctx.exception.code, "atomic_noreplace_unsupported")
        self.assertEqual(state.attempt, 1)
        self.assertTrue(events.is_file())
        archive = root / "attempts" / "attempt-0001"
        self.assertTrue((archive / "state.json").is_file())
        self.assertFalse((archive / "events.jsonl").exists())

    def test_complete_report_waits_for_real_clean_exit(self) -> None:
        delayed = Path(self.tmp.name) / "delayed_worker.py"
        delayed.write_text(FAKE_WORKER + "\ntime.sleep(0.6)\n", encoding="utf-8")
        delayed.chmod(delayed.stat().st_mode | stat.S_IXUSR)
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=delayed,
        )
        launch_full_run(self.repo, session_id=self.session)
        # macOS CI process-group reaping and fingerprint observation need more
        # wall time than the Linux runners used for the original 2s budget.
        deadline = time.time() + (8 if sys.platform == "darwin" else 3)
        status = monitor_full_run(self.repo, session_id=self.session, stale_after_seconds=60)
        while status["check_summary"]["report_status"] != "complete" and time.time() < deadline:
            time.sleep(0.02)
            status = monitor_full_run(self.repo, session_id=self.session, stale_after_seconds=60)
        self.assertEqual(status["check_summary"]["report_status"], "complete", status)
        self.assertIn(status["state"], {"healthy", "pending"}, status)
        self.assertFalse(status["check_summary"]["exit_record"])

        await_supervised_reap(self.repo, self.session)
        status = monitor_full_run(
            self.repo, session_id=self.session, stale_after_seconds=60
        )
        self.assertEqual(status["state"], "complete", status)
        self.assertEqual(status["check_summary"]["exit_code"], 0, status)

    def test_terminal_retired_identity_is_never_reprobed_or_resignaled(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        launch_full_run(self.repo, session_id=self.session)
        await_supervised_reap(self.repo, self.session)
        status = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(status["state"], "complete", status)
        retired = load_state(self.repo, self.session)
        self.assertIsNone(retired.pid)
        self.assertIsNone(retired.pgid)
        self.assertIsNone(retired.fingerprint)
        self.assertIsNotNone(retired.closed_process_identity)
        with (
            mock.patch("cobbler_runtime.full_run._pid_alive", side_effect=AssertionError("historical pid probed")),
            mock.patch("cobbler_runtime.full_run._process_group_alive", side_effect=AssertionError("historical pgid probed")),
            mock.patch("cobbler_runtime.full_run._scan_supervision_pids", side_effect=AssertionError("historical marker scanned")),
        ):
            repeated = monitor_full_run(self.repo, session_id=self.session)
            stopped = stop_full_run(self.repo, session_id=self.session)
        self.assertEqual(repeated["state"], "complete")
        self.assertTrue(stopped["ok"])
        self.assertFalse(stopped["signaled"])

    def test_nonzero_exit_overrides_complete_worker_report(self) -> None:
        failing = Path(self.tmp.name) / "failing_worker.py"
        failing.write_text(FAKE_WORKER + "\nraise SystemExit(7)\n", encoding="utf-8")
        failing.chmod(failing.stat().st_mode | stat.S_IXUSR)
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=failing,
        )
        launch_full_run(self.repo, session_id=self.session)
        await_supervised_reap(self.repo, self.session)
        status = monitor_full_run(
            self.repo, session_id=self.session, stale_after_seconds=60
        )
        self.assertEqual(status["state"], "failed", status)
        self.assertEqual(status["check_summary"]["exit_code"], 7, status)
        self.assertIn("nonzero exit", status["blocker"])

    def test_monitoring_the_reaping_window_yields_a_failure_without_an_exit_code(
        self,
    ) -> None:
        # Deterministic form of the load-sensitive flake that `await_supervised_reap`
        # exists to avoid. Holding the recorded group "alive" past the product's
        # settle window makes the monitor refuse the exit record and report `failed`
        # with no `exit_code` — the exact status a poll-for-first-terminal-state test
        # used to capture on a loaded CI host.
        #
        # Note: this refusal latches. A later poll recovers `exit_code`, but the
        # blocker keeps naming the premature refusal, so the settled nonzero-exit
        # classification is never reached once the window has been observed. That
        # behavior is deliberately not asserted here; it is the reason the tests wait
        # for the reap rather than polling through it.
        failing = Path(self.tmp.name) / "failing_worker.py"
        failing.write_text(FAKE_WORKER + "\nraise SystemExit(7)\n", encoding="utf-8")
        failing.chmod(failing.stat().st_mode | stat.S_IXUSR)
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=failing,
        )
        launch_full_run(self.repo, session_id=self.session)

        settled = full_run_module._settle_recorded_supervisor_exit
        unreaped_polls: list[dict] = []

        def hold_group_alive_once(pid, pgid, **kwargs):
            if not unreaped_polls:
                unreaped_polls.append({})
                return True, True
            return settled(pid, pgid, **kwargs)

        with mock.patch.object(
            full_run_module,
            "_settle_recorded_supervisor_exit",
            side_effect=hold_group_alive_once,
        ):
            # Reach the exit-record validation, which is where the refusal happens.
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                refused = monitor_full_run(
                    self.repo, session_id=self.session, stale_after_seconds=60
                )
                if unreaped_polls:
                    break
                time.sleep(0.02)

        self.assertTrue(unreaped_polls, "settle helper was never exercised")
        self.assertEqual(refused["state"], "failed", refused)
        self.assertIsNone(refused["check_summary"]["exit_code"], refused)
        self.assertIn("premature exit record", refused["blocker"], refused)

    def test_clean_exit_with_git_progress_but_no_complete_report_fails(self) -> None:
        worker = Path(self.tmp.name) / "progress_only.py"
        worker.write_text(COMMIT_WITHOUT_REPORT, encoding="utf-8")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=worker,
        )
        launch_full_run(self.repo, session_id=self.session)
        deadline = time.time() + 5
        status = monitor_full_run(self.repo, session_id=self.session)
        while (
            status["state"] not in {"complete", "failed", "blocked"}
            and time.time() < deadline
        ):
            time.sleep(0.03)
            status = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(status["state"], "blocked", status)
        self.assertEqual(status["next_action"], "driver_wake_reconcile", status)
        self.assertEqual(status["check_summary"]["exit_code"], 0)
        self.assertIn("without a validated complete report", status["blocker"])

    @unittest.skipIf(
        sys.platform == "darwin",
        "Darwin has no pidfd; detached descendants fail closed instead of numeric PID signaling",
    )
    def test_recursive_supervisor_reaps_setsid_double_fork_before_completion(self) -> None:
        worker = Path(self.tmp.name) / "lingering_child.py"
        worker.write_text(COMPLETE_WITH_LINGERING_CHILD, encoding="utf-8")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=worker,
        )
        launch_full_run(self.repo, session_id=self.session)
        await_supervised_reap(self.repo, self.session)
        status = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(status["state"], "complete", status)
        record = json.loads(
            (full_run_root(self.repo, self.session) / "exit_record.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(record["descendants_absent"], record)
        self.assertTrue(record["supervised_pids"], record)

    def test_malformed_exit_record_fails_and_wakes_driver(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        (full_run_root(self.repo, self.session) / "exit_record.json").write_text(
            "{malformed", encoding="utf-8"
        )
        status = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(status["state"], "failed", status)
        self.assertEqual(status["next_action"], "driver_wake_error")
        self.assertGreater(status["check_summary"]["exit_record_errors"], 0)

    def test_concurrent_launch_allows_exactly_one_supervisor(self) -> None:
        sleeper = Path(self.tmp.name) / "concurrent_sleeper.py"
        sleeper.write_text(LONG_SLEEPER, encoding="utf-8")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=sleeper,
        )
        barrier = threading.Barrier(3)
        outcomes: list[str] = []

        def launch() -> None:
            barrier.wait()
            try:
                launch_full_run(self.repo, session_id=self.session)
                outcomes.append("launched")
            except ValidationIssue as issue:
                outcomes.append(issue.code)

        threads = [threading.Thread(target=launch) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(outcomes.count("launched"), 1, outcomes)
        self.assertEqual(outcomes.count("full_run_already_running"), 1, outcomes)
        stopped = stop_full_run(self.repo, session_id=self.session, grace_seconds=0.2)
        self.assertTrue(stopped["ok"], stopped)

    def test_new_tag_is_a_protected_ref_safety_tripwire(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "tag", "worker-created-tag"], check=True
        )
        status = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(status["state"], "failed", status)
        self.assertIn("new protected ref", status["blocker"])

    def test_host_codex_turn_diff_ref_is_not_a_worker_safety_tripwire(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "update-ref",
                "refs/codex/turn-diffs/task-1/turn-2",
                self.start_head,
            ],
            check=True,
        )
        status = monitor_full_run(self.repo, session_id=self.session)
        self.assertNotEqual(status["next_action"], "driver_wake_safety_tripwire", status)
        self.assertNotIn("new protected ref", status.get("blocker") or "")

    def test_all_local_ref_namespaces_are_protected(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        replace_source = subprocess.run(
            ["git", "-C", str(self.repo), "hash-object", "-w", "--stdin"],
            input="unused source\n",
            text=True,
            check=True,
            capture_output=True,
        ).stdout.strip()
        replace_target = subprocess.run(
            ["git", "-C", str(self.repo), "hash-object", "-w", "--stdin"],
            input="unused target\n",
            text=True,
            check=True,
            capture_output=True,
        ).stdout.strip()
        refs = (
            "refs/notes/full-run-sentinel",
            f"refs/replace/{replace_source}",
            "refs/b0/full-run-sentinel",
        )
        for ref in refs:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.repo),
                    "update-ref",
                    ref,
                    replace_target if ref.startswith("refs/replace/") else self.start_head,
                ],
                check=True,
            )
        status = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(status["state"], "failed", status)
        for ref in refs:
            self.assertIn(ref, status["blocker"])

    def test_all_remote_ref_namespaces_are_protected(self) -> None:
        remote = Path(self.tmp.name) / "protected-origin.git"
        _attach_origin(self.repo, remote, self.branch)
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "push",
                "-q",
                "origin",
                f"{self.start_head}:refs/notes/remote-sentinel",
            ],
            check=True,
        )
        status = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(status["state"], "failed", status)
        self.assertIn(
            "remote::origin::refs/notes/remote-sentinel", status["blocker"]
        )

    def test_reconcile_requires_origin_feature_tip_to_equal_local(self) -> None:
        remote = Path(self.tmp.name) / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "remote", "add", "origin", str(remote)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "push", "-q", "-u", "origin", self.branch],
            check=True,
        )
        _write_production_packet(self.packet)
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            session_path=_write_production_acceptance_contract(
                self.repo, self.packet
            ),
            adapter="grok-build",
            executable="grok",
        )
        (self.repo / "f.txt").write_text("local only\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "f.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "local only"],
            check=True,
        )
        tip = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        baseline = json.loads(
            (full_run_root(self.repo, self.session) / "report.json").read_text(
                encoding="utf-8"
            )
        )
        write_report(
            self.repo,
            self.session,
            {
                **baseline,
                "final_head": tip,
                "status": "complete",
                "batches": [
                    {"id": "batch-1", "status": "complete", "evidence": "gates passed"}
                ],
                "acceptance": [
                    {
                        "id": "B1-A1",
                        "criterion": "criterion for B1-A1",
                        "met": True,
                        "evidence": tip,
                    },
                    {
                        "id": "M-A1",
                        "criterion": "criterion for M-A1",
                        "met": True,
                        "evidence": tip,
                    },
                ],
                "commits": [tip],
            },
        )
        with self.assertRaises(ValidationIssue) as ctx:
            reconcile_full_run_with_git(self.repo, session_id=self.session)
        self.assertEqual(ctx.exception.code, "full_run_remote_feature_mismatch")

    def test_reconcile_requires_every_planned_checkpoint_event_and_host_ack(self) -> None:
        remote = Path(self.tmp.name) / "checkpoint-origin.git"
        _attach_origin(self.repo, remote, self.branch)
        _write_production_packet(self.packet, "B1-A1")
        with self.packet.open("a", encoding="utf-8") as handle:
            handle.write("\n- High-risk checkpoint: security-boundary\n")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            session_path=_write_production_acceptance_contract(
                self.repo, self.packet
            ),
            adapter="grok-build",
            executable="grok",
        )
        (self.repo / "f.txt").write_text("checkpoint evidence\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "f.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "checkpoint evidence"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "push", "-q", "origin", self.branch],
            check=True,
        )
        tip = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        baseline = json.loads(
            (full_run_root(self.repo, self.session) / "report.json").read_text(
                encoding="utf-8"
            )
        )
        write_report(
            self.repo,
            self.session,
            {
                **baseline,
                "final_head": tip,
                "status": "complete",
                "batches": [{"id": "batch-1", "status": "complete", "evidence": tip}],
                "acceptance": [
                    {
                        "id": "B1-A1",
                        "criterion": "criterion for B1-A1",
                        "met": True,
                        "evidence": tip,
                    },
                    {
                        "id": "M-A1",
                        "criterion": "criterion for M-A1",
                        "met": True,
                        "evidence": tip,
                    },
                ],
                "commits": [tip],
            },
        )

        with self.assertRaises(ValidationIssue) as missing:
            reconcile_full_run_with_git(self.repo, session_id=self.session)
        self.assertEqual(missing.exception.code, "full_run_checkpoint_incomplete")

        full_run_module._append_event(
            full_run_root(self.repo, self.session) / "events.jsonl",
            {
                "timestamp": full_run_module._utc_now(),
                "session_id": self.session,
                "branch": self.branch,
                "head": tip,
                "batch": 1,
                "type": "high_risk_checkpoint",
                "checkpoint_id": "security-boundary",
                "summary": "host review requested",
            },
            expected_session_id=self.session,
            expected_branch=self.branch,
            expected_high_risk_checkpoints=["security-boundary"],
            repo_root=self.repo,
        )
        with self.assertRaises(ValidationIssue) as unacknowledged:
            reconcile_full_run_with_git(self.repo, session_id=self.session)
        self.assertEqual(
            unacknowledged.exception.code,
            "full_run_checkpoint_incomplete",
        )

    def test_reconcile_binds_commit_chain_events_and_staged_acceptance_ids(self) -> None:
        remote = Path(self.tmp.name) / "evidence-origin.git"
        _attach_origin(self.repo, remote, self.branch)
        _write_production_packet(self.packet, "B1-A1", "B1-A2")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            session_path=_write_production_acceptance_contract(
                self.repo, self.packet
            ),
            adapter="grok-build",
            executable="grok",
        )
        (self.repo / "f.txt").write_text("evidence\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "f.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "evidence"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "push", "-q", "origin", self.branch],
            check=True,
        )
        tip = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        baseline = json.loads(
            (full_run_root(self.repo, self.session) / "report.json").read_text(
                encoding="utf-8"
            )
        )
        write_report(
            self.repo,
            self.session,
            {
                **baseline,
                "final_head": tip,
                "status": "complete",
                "batches": [{"id": "batch-1", "status": "complete", "evidence": tip}],
                "acceptance": [
                    {
                        "id": acceptance_id,
                        "criterion": f"criterion for {acceptance_id}",
                        "met": True,
                        "evidence": tip,
                    }
                    for acceptance_id in ("B1-A1", "B1-A2", "M-A1")
                ],
                # Exact SHA shape, but intentionally not the start..final chain.
                "commits": [self.start_head],
            },
        )
        tree = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD^{tree}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        unrelated = subprocess.run(
            ["git", "-C", str(self.repo), "commit-tree", tree, "-m", "unrelated"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        with (full_run_root(self.repo, self.session) / "events.jsonl").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write(
                json.dumps(
                    {
                        "timestamp": "2026-07-13T00:00:00+00:00",
                        "session_id": self.session,
                        "branch": self.branch,
                        "head": unrelated,
                        "batch": 1,
                        "type": "heartbeat",
                        "summary": "unrelated head",
                    }
                )
                + "\n"
            )
        with self.assertRaises(ValidationIssue) as ctx:
            reconcile_full_run_with_git(self.repo, session_id=self.session)
        self.assertEqual(ctx.exception.code, "full_run_git_evidence_mismatch")
        self.assertIn("commit", ctx.exception.message)
        self.assertIn("event", ctx.exception.message)

    def test_stopped_terminal_state_does_not_regress_on_monitor(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        stopped = stop_full_run(self.repo, session_id=self.session)
        self.assertEqual(stopped["status"], "stopped")
        status = monitor_full_run(self.repo, session_id=self.session)
        self.assertEqual(status["state"], "stopped", status)

    def test_live_but_silent_worker_becomes_stale(self) -> None:
        sleeper = Path(self.tmp.name) / "sleeper.py"
        sleeper.write_text(LONG_SLEEPER, encoding="utf-8")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=sleeper,
        )
        launch_full_run(self.repo, session_id=self.session)
        time.sleep(0.2)
        status = monitor_full_run(self.repo, session_id=self.session, stale_after_seconds=0)
        self.assertTrue(status.get("fingerprint_ok"), status)
        self.assertEqual(status["state"], "stale", status)
        self.assertEqual(status["next_action"], "driver_wake_stale_heartbeat")
        stop = stop_full_run(self.repo, session_id=self.session, grace_seconds=0.2)
        self.assertTrue(stop.get("fingerprint_verified"))
        self.assertTrue(stop["ok"], stop)
        self.assertFalse(stop["still_alive"], stop)

    def test_unchanged_healthy_monitor_poll_is_explicitly_silent(self) -> None:
        sleeper = Path(self.tmp.name) / "quiet-monitor-sleeper.py"
        sleeper.write_text(LONG_SLEEPER, encoding="utf-8")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=sleeper,
        )
        launch_full_run(self.repo, session_id=self.session)
        time.sleep(0.2)
        first = monitor_full_run(
            self.repo,
            session_id=self.session,
            stale_after_seconds=300,
        )
        second = monitor_full_run(
            self.repo,
            session_id=self.session,
            stale_after_seconds=300,
        )
        self.assertEqual(first["state"], "healthy", first)
        self.assertEqual(second["state"], "healthy", second)
        self.assertEqual(second["poll_after_seconds"], 150)
        self.assertEqual(second["user_heartbeat_seconds"], 900)
        self.assertEqual(second["chat_update_policy"], PARKED_MONITOR_UPDATE_POLICY)
        self.assertFalse(second["chat_update_recommended"], second)
        self.assertTrue(second["unchanged_healthy_poll_silent"], second)
        stopped = stop_full_run(
            self.repo,
            session_id=self.session,
            grace_seconds=0.1,
        )
        self.assertTrue(stopped["ok"], stopped)
        stop_request = json.loads(
            (
                full_run_root(self.repo, self.session)
                / full_run_module.STOP_REQUEST_NAME
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(stop_request["session_id"], self.session)
        self.assertEqual(len(stop_request["authority"]), 64)
        self.assertNotIn(
            str(load_state(self.repo, self.session).supervision_token),
            json.dumps(stop_request, sort_keys=True),
        )

    def test_provider_receives_only_derived_marker_and_read_only_packet_fd(self) -> None:
        observer = Path(self.tmp.name) / "supervision-boundary-observer.py"
        observer.write_text(
            "import hashlib, json, os, sys, time\n"
            "from pathlib import Path\n"
            "open_fds = []\n"
            "for fd in range(3, 64):\n"
            "    try:\n"
            "        os.fstat(fd)\n"
            "    except OSError:\n"
            "        continue\n"
            "    open_fds.append(fd)\n"
            "packet_arg = next(value for value in sys.argv if value.startswith('/dev/fd/'))\n"
            "packet_fd = int(packet_arg.rsplit('/', 1)[1])\n"
            "try:\n"
            "    os.write(packet_fd, b'x')\n"
            "    packet_fd_read_only = False\n"
            "except OSError:\n"
            "    packet_fd_read_only = True\n"
            "snapshot = {\n"
            "    'argv': sys.argv,\n"
            "    'marker': os.environ.get('ELVES_FULL_RUN_SUPERVISION_MARKER'),\n"
            "    'env_value_hashes': sorted(hashlib.sha256(value.encode()).hexdigest() "
            "for value in os.environ.values()),\n"
            "    'open_fds_above_stderr': open_fds,\n"
            "    'packet_fd': packet_fd,\n"
            "    'packet_fd_read_only': packet_fd_read_only,\n"
            "    'stdin_eof': os.read(0, 1) == b'',\n"
            "}\n"
            "Path(os.environ['ELVES_FULL_RUN_TRANSCRIPT']).write_text("
            "json.dumps(snapshot), encoding='utf-8')\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=observer,
        )
        launch = launch_full_run(self.repo, session_id=self.session)
        state = load_state(self.repo, self.session)
        stop_secret = str(state.supervision_token)
        expected_marker = full_run_module._descendant_supervision_marker(state)
        transcript = full_run_root(self.repo, self.session) / "transcript.log"
        deadline = time.time() + 5
        snapshot = None
        while snapshot is None and time.time() < deadline:
            try:
                snapshot = json.loads(transcript.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                time.sleep(0.02)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["marker"], expected_marker)
        self.assertNotEqual(snapshot["marker"], stop_secret)
        self.assertNotIn(stop_secret, json.dumps(snapshot["argv"]))
        self.assertNotIn(
            hashlib.sha256(stop_secret.encode()).hexdigest(),
            snapshot["env_value_hashes"],
        )
        self.assertEqual(
            snapshot["open_fds_above_stderr"], [snapshot["packet_fd"]]
        )
        self.assertTrue(snapshot["packet_fd_read_only"])
        self.assertTrue(snapshot["stdin_eof"])
        self.assertNotIn(stop_secret, json.dumps(launch, sort_keys=True))

        stopped = stop_full_run(
            self.repo,
            session_id=self.session,
            grace_seconds=0.1,
        )
        self.assertTrue(stopped["ok"], stopped)
        exit_record = json.loads(
            (full_run_root(self.repo, self.session) / "exit_record.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(exit_record["supervision_marker"], expected_marker)
        self.assertNotIn("supervision_token", exit_record)
        self.assertNotIn(stop_secret, json.dumps(exit_record, sort_keys=True))

    def test_descendant_marker_cannot_forge_stop_and_malformed_fifo_are_ignored(self) -> None:
        ready = Path(self.tmp.name) / "stop-artifact-attacks-complete"
        attacker = Path(self.tmp.name) / "stop-artifact-attacker.py"
        attacker.write_text(
            "import hashlib, hmac, json, os, time\n"
            "from pathlib import Path\n"
            f"ready = Path({str(ready)!r})\n"
            "root = Path(os.environ['ELVES_FULL_RUN_EVENTS']).parent\n"
            "request = root / 'stop_request.json'\n"
            "session_id = os.environ['ELVES_FULL_RUN_SESSION']\n"
            "attempt = int(os.environ['ELVES_FULL_RUN_ATTEMPT'])\n"
            "marker = os.environ['ELVES_FULL_RUN_SUPERVISION_MARKER']\n"
            "message = f'stop\\0{session_id}\\0{attempt}'.encode('utf-8')\n"
            "forged = hmac.new(marker.encode(), message, hashlib.sha256).hexdigest()\n"
            "request.write_text(json.dumps({'session_id': session_id, "
            "'attempt': attempt, 'authority': forged}), encoding='utf-8')\n"
            "time.sleep(0.25)\n"
            "request.write_text('{}', encoding='utf-8')\n"
            "time.sleep(0.25)\n"
            "request.unlink()\n"
            "os.mkfifo(request)\n"
            "time.sleep(0.25)\n"
            "ready.write_text('done', encoding='utf-8')\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=attacker,
        )
        launch_full_run(self.repo, session_id=self.session)
        deadline = time.time() + 5
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.02)

        self.assertTrue(ready.exists(), "worker was terminated or supervisor wedged")
        root = full_run_root(self.repo, self.session)
        self.assertFalse((root / "exit_record.json").exists())
        status = monitor_full_run(
            self.repo,
            session_id=self.session,
            stale_after_seconds=300,
        )
        self.assertEqual(status["state"], "healthy", status)

        stopped = stop_full_run(
            self.repo,
            session_id=self.session,
            grace_seconds=0.1,
        )
        self.assertTrue(stopped["ok"], stopped)
        exit_record = json.loads(
            (root / "exit_record.json").read_text(encoding="utf-8")
        )
        self.assertIsNone(exit_record["supervision_error"])
        self.assertEqual(exit_record["interrupted_signal"], signal.SIGTERM)

    def test_host_stop_signals_only_verified_supervisor_not_cached_group(self) -> None:
        sleeper = Path(self.tmp.name) / "identity-sleeper.py"
        sleeper.write_text(LONG_SLEEPER, encoding="utf-8")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=sleeper,
        )
        launch_full_run(self.repo, session_id=self.session)
        with mock.patch.object(
            full_run_module.os,
            "killpg",
            side_effect=AssertionError("host must not signal a reusable PGID"),
        ) as killpg:
            stopped = stop_full_run(
                self.repo,
                session_id=self.session,
                grace_seconds=0.1,
            )
        killpg.assert_not_called()
        self.assertTrue(stopped["ok"], stopped)
        self.assertTrue(stopped["fingerprint_verified"], stopped)

    def test_signal_helper_refuses_darwin_numeric_pid_signal(self) -> None:
        fingerprint = {
            "pid": 424242,
            "pgid": 424242,
            "start_time": "original-start",
            "executable": sys.executable,
            "session_id": self.session,
        }
        with (
            mock.patch.object(full_run_module.sys, "platform", "darwin"),
            mock.patch.object(full_run_module.os, "kill") as kill,
        ):
            with self.assertRaises(ValidationIssue) as ctx:
                full_run_module._signal_verified_supervisor(
                    fingerprint,
                    expected_session_id=self.session,
                    signum=signal.SIGTERM,
                )
        self.assertEqual(ctx.exception.code, "full_run_atomic_signal_unavailable")
        kill.assert_not_called()

    def test_supervision_canary_uses_minimal_credential_free_environment(self) -> None:
        captured: dict[str, object] = {}

        class FakeProcess:
            pid = 4242

            def poll(self):
                return None

            def kill(self):
                captured["killed"] = True

            def wait(self, timeout=None):
                captured["wait_timeout"] = timeout
                return -signal.SIGKILL

        def fake_popen(*args, **kwargs):
            captured["env"] = dict(kwargs["env"])
            return FakeProcess()

        parent = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "synthetic-canary-secret",
            "UNRELATED_SENTINEL": "must-not-enter-canary",
            "HOME": "/host-home",
        }
        with (
            mock.patch.dict(os.environ, parent, clear=True),
            mock.patch.object(full_run_module.subprocess, "Popen", side_effect=fake_popen),
            mock.patch.object(
                full_run_module,
                "_scan_supervision_pids",
                return_value={FakeProcess.pid},
            ),
        ):
            self.assertTrue(full_run_module._run_supervision_canary(Path("/usr/bin/ps")))

        env = captured["env"]
        self.assertIsInstance(env, dict)
        self.assertEqual(env["PATH"], parent["PATH"])
        self.assertEqual(env["LANG"], parent["LANG"])
        self.assertRegex(env["ELVES_FULL_RUN_SUPERVISION_MARKER"], r"^[0-9a-f]{64}$")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("UNRELATED_SENTINEL", env)
        self.assertNotIn("HOME", env)

    def test_embedded_supervisor_tracks_start_identity_and_uses_pidfd_on_linux(self) -> None:
        source = full_run_module._provider_supervisor_script()
        self.assertIn("known_identities", source)
        self.assertNotIn("known_pids", source)
        self.assertIn("os.pidfd_open", source)
        self.assertIn("signal.pidfd_send_signal", source)
        self.assertIn("current[4] != expected_start", source)
        self.assertNotIn("os.kill(pid, signum)", source)

    def test_recent_meaningful_event_keeps_live_worker_healthy(self) -> None:
        sleeper = Path(self.tmp.name) / "eventful-sleeper.py"
        sleeper.write_text(LONG_SLEEPER, encoding="utf-8")
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=sleeper,
        )
        launch_full_run(self.repo, session_id=self.session)
        state = load_state(self.repo, self.session)
        state.launched_at = "2000-01-01T00:00:00+00:00"
        state.heartbeat_at = None
        full_run_module.save_state(self.repo, state)
        event = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "session_id": self.session,
            "branch": self.branch,
            "head": self.start_head,
            "batch": 1,
            "type": "heartbeat",
            "summary": "worker is still making meaningful progress",
        }
        with (full_run_root(self.repo, self.session) / "events.jsonl").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write(json.dumps(event) + "\n")
        status = monitor_full_run(
            self.repo, session_id=self.session, stale_after_seconds=5
        )
        self.assertTrue(status.get("fingerprint_ok"), status)
        self.assertEqual(status["state"], "healthy", status)

    def test_forged_event_rejected(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        root = full_run_root(self.repo, self.session)
        events = root / "events.jsonl"
        # Foreign session event
        with events.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp": "t",
                        "session_id": "OTHER",
                        "branch": self.branch,
                        "head": self.start_head,
                        "batch": 1,
                        "type": "run_complete",
                        "summary": "forged",
                    }
                )
                + "\n"
            )
        status = monitor_full_run(self.repo, session_id=self.session, stale_after_seconds=60)
        self.assertGreaterEqual(status["check_summary"]["event_errors"], 1)
        self.assertNotEqual(status["state"], "complete")

    def test_fingerprint_mismatch_refuses_stop(self) -> None:
        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        state = load_state(self.repo, self.session)
        state.fingerprint = {
            "pid": 999999,
            "pgid": 999999,
            "start_time": "not-a-real-start",
            "executable": "/no/such/exe",
            "session_id": self.session,
        }
        state.pid = 999999
        from cobbler_runtime.full_run import save_state  # noqa: PLC0415

        save_state(self.repo, state)
        with self.assertRaises(ValidationIssue) as ctx:
            stop_full_run(self.repo, session_id=self.session, grace_seconds=0.1)
        self.assertEqual(ctx.exception.code, "full_run_fingerprint_mismatch")

    def test_launch_never_clears_unverifiable_live_or_dead_identity(self) -> None:
        import signal
        from cobbler_runtime.full_run import save_state

        prepare_full_run(
            self.repo,
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=self.repo,
            packet_path=self.packet,
            adapter="fixture",
            fixture_script=self.worker,
        )
        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            state = load_state(self.repo, self.session)
            fp = capture_fingerprint(
                pid=sleeper.pid,
                pgid=os.getpgid(sleeper.pid),
                session_id=self.session,
                executable_hint=sys.executable,
            ).to_dict()
            fp["start_time"] = "forged-start"
            state.pid = sleeper.pid
            state.pgid = os.getpgid(sleeper.pid)
            state.fingerprint = fp
            save_state(self.repo, state)
            with self.assertRaises(ValidationIssue) as ctx:
                launch_full_run(self.repo, session_id=self.session)
            self.assertEqual(ctx.exception.code, "full_run_already_running")
            self.assertEqual(load_state(self.repo, self.session).fingerprint, fp)
        finally:
            try:
                os.killpg(sleeper.pid, signal.SIGKILL)
            except OSError:
                pass
            sleeper.wait(timeout=5)

        state = load_state(self.repo, self.session)
        state.pid = 99999999
        state.pgid = 99999999
        state.fingerprint = {
            "pid": 99999999,
            "pgid": 99999999,
            "start_time": "dead",
            "executable": sys.executable,
            "session_id": self.session,
        }
        save_state(self.repo, state)
        with self.assertRaises(ValidationIssue) as ctx:
            launch_full_run(self.repo, session_id=self.session)
        self.assertEqual(ctx.exception.code, "full_run_relaunch_unauthenticated")

    def test_event_schema_rejects_secret_shaped_summary(self) -> None:
        errors = validate_event(
            {
                "timestamp": "t",
                "session_id": "s",
                "branch": "b",
                "head": "h",
                "batch": 1,
                "type": "heartbeat",
                "summary": "token api_key=SUPERSECRET",
            }
        )
        self.assertTrue(any("secret" in e for e in errors))


    def test_forged_pgid_two_sleeper(self) -> None:
        """Stored PGID that is not the verified process group must fail fingerprint/stop."""
        import os
        import signal
        import time

        # Two sleepers: victim process group vs real process group.
        real = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        forged = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.05)
            real_pgid = os.getpgid(real.pid)
            forged_pgid = os.getpgid(forged.pid)
            self.assertNotEqual(real_pgid, forged_pgid)
            fp = capture_fingerprint(
                pid=real.pid,
                pgid=forged_pgid,  # forged: not real's process group
                session_id="sess-forged-pgid",
                executable_hint=sys.executable,
            )
            ok, reason = verify_fingerprint(fp, expected_session_id="sess-forged-pgid")
            self.assertFalse(ok)
            self.assertIn("pgid", reason.lower())
            # Matching session + correct pgid succeeds.
            fp_ok = capture_fingerprint(
                pid=real.pid,
                pgid=real_pgid,
                session_id="sess-forged-pgid",
                executable_hint=sys.executable,
            )
            ok2, reason2 = verify_fingerprint(fp_ok, expected_session_id="sess-forged-pgid")
            self.assertTrue(ok2, reason2)
            # Executable mismatch never excused by start_time match.
            bad_exe = dict(fp_ok.to_dict())
            bad_exe["executable"] = "/nonexistent/forged-binary"
            ok3, reason3 = verify_fingerprint(bad_exe, expected_session_id="sess-forged-pgid")
            self.assertFalse(ok3)
            self.assertIn("executable", reason3.lower())
        finally:
            for p in (real, forged):
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except OSError:
                    try:
                        p.kill()
                    except OSError:
                        pass
                try:
                    p.wait(timeout=1)
                except Exception:
                    pass

    def _devin_clean_env(self) -> dict[str, str]:
        base = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GIT_CONFIG_KEY_") and not k.startswith("GIT_CONFIG_VALUE_")
        }
        base["GIT_CONFIG_COUNT"] = "0"
        base["XDG_CONFIG_HOME"] = str(self.devin_config_dir)
        base["XDG_DATA_HOME"] = str(self.devin_data_dir)
        return base

    def test_devin_fixture_create_and_capture(self) -> None:
        remote = Path(self.tmp.name) / "devin-origin.git"
        _write_production_packet(self.packet, "B1-A1")
        devin = Path(self.tmp.name) / "fake_devin.py"
        devin.write_text(FAKE_DEVIN, encoding="utf-8")
        devin.chmod(devin.stat().st_mode | stat.S_IXUSR)
        with mock.patch.dict(os.environ, self._devin_clean_env(), clear=True):
            _attach_origin(self.repo, remote, self.branch)
            prepare_full_run(
                self.repo,
                session_id=self.session,
                branch=self.branch,
                start_head=self.start_head,
                worktree=self.repo,
                packet_path=self.packet,
                session_path=_write_production_acceptance_contract(self.repo, self.packet),
                adapter="devin-cli",
                executable=str(devin),
            )
            state = load_state(self.repo, self.session)
            self.assertEqual(state.adapter, "devin-cli")
            self.assertEqual(state.model, "swe-1-7-lightning")
            self.assertEqual(state.effort, "medium")
            self.assertEqual(state.executable, str(devin))
            self.assertIsNone(state.provider_session_id)

            launched = launch_full_run(
                self.repo,
                session_id=self.session,
                grant_devin_auth=True,
            )
            self.assertFalse(launched["merge_authority"])
            self.assertIn("--prompt-file", launched["argv"])
            self.assertIn("--print", launched["argv"])
            self.assertNotIn("--resume", launched["argv"])

            deadline = time.time() + 10
            status = monitor_full_run(self.repo, session_id=self.session, stale_after_seconds=60)
            while status.get("state") not in {"complete", "failed"} and time.time() < deadline:
                time.sleep(0.05)
                status = monitor_full_run(self.repo, session_id=self.session, stale_after_seconds=60)
            logs = logs_full_run(
                self.repo, session_id=self.session, raw_tail=True, tail_lines=50
            ) if status["state"] == "failed" else None
            self.assertEqual(status["state"], "complete", logs or status)

            state = load_state(self.repo, self.session)
            self.assertEqual(state.provider_session_id, "devin-sess-123")
            self.assertEqual(state.devin_auth_strategy, "projected_files")
            self.assertIsInstance(state.devin_auth_identity, dict)
            events_path = full_run_root(self.repo, self.session) / "events.jsonl"
            event_types = [
                json.loads(line).get("type")
                for line in events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertIn("devin_session_captured", event_types)
            state_json = json.dumps(state.to_dict(), indent=2, sort_keys=True)
            events_text = events_path.read_text(encoding="utf-8")
            self.assertNotIn("devin-test-key", state_json)
            self.assertNotIn("devin-test-key", events_text)
            worker_home = full_run_root(self.repo, self.session) / "worker-home"
            self.assertEqual(
                (worker_home / ".config" / "devin" / "config.json").stat().st_mode & 0o777,
                0o600,
            )
            self.assertEqual(
                (worker_home / ".local" / "share" / "devin" / "credentials.toml").stat().st_mode & 0o777,
                0o600,
            )
        export = full_run_root(self.repo, self.session) / "devin-export.atif"
        self.assertTrue(export.is_file())
        self.assertIn("swe-1-7-lightning", export.read_text(encoding="utf-8"))

    def _run_devin_until_terminal(
        self,
        *,
        devin_script: str,
        deadline_seconds: float = 10.0,
    ) -> dict[str, object]:
        remote = Path(self.tmp.name) / "devin-terminal-origin.git"
        _write_production_packet(self.packet, "B1-A1")
        devin = Path(self.tmp.name) / "fake_devin_terminal.py"
        devin.write_text(devin_script, encoding="utf-8")
        devin.chmod(devin.stat().st_mode | stat.S_IXUSR)
        with mock.patch.dict(os.environ, self._devin_clean_env(), clear=True):
            _attach_origin(self.repo, remote, self.branch)
            prepare_full_run(
                self.repo,
                session_id=self.session,
                branch=self.branch,
                start_head=self.start_head,
                worktree=self.repo,
                packet_path=self.packet,
                session_path=_write_production_acceptance_contract(self.repo, self.packet),
                adapter="devin-cli",
                executable=str(devin),
            )
            launch_full_run(
                self.repo,
                session_id=self.session,
                grant_devin_auth=True,
            )
            deadline = time.time() + deadline_seconds
            status: dict[str, object] = {"state": "pending"}
            while status.get("state") not in {
                "complete",
                "failed",
                "blocked",
            } and time.time() < deadline:
                time.sleep(0.05)
                status = monitor_full_run(
                    self.repo,
                    session_id=self.session,
                    stale_after_seconds=60,
                )
        return status

    def test_devin_clean_exit_without_capture_stays_blocked(self) -> None:
        status = self._run_devin_until_terminal(devin_script=FAKE_DEVIN_EMPTY_LIST)
        self.assertEqual(status["state"], "blocked", status)
        self.assertIn("provider session id", str(status.get("blocker") or "").lower())

        state = load_state(self.repo, self.session)
        self.assertIsNone(state.provider_session_id)
        events_path = full_run_root(self.repo, self.session) / "events.jsonl"
        event_types = [
            json.loads(line).get("type")
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertIn("devin_capture_failed", event_types)

    def test_devin_clean_exit_with_ambiguous_capture_stays_blocked(self) -> None:
        status = self._run_devin_until_terminal(
            devin_script=FAKE_DEVIN_AMBIGUOUS_LIST
        )
        self.assertEqual(status["state"], "blocked", status)
        self.assertIn("provider session id", str(status.get("blocker") or "").lower())

        state = load_state(self.repo, self.session)
        self.assertIsNone(state.provider_session_id)
        events_path = full_run_root(self.repo, self.session) / "events.jsonl"
        event_types = [
            json.loads(line).get("type")
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertIn("devin_capture_failed", event_types)

    def test_devin_fixture_resume_exact_session(self) -> None:
        remote = Path(self.tmp.name) / "devin-resume-origin.git"
        _write_production_packet(self.packet, "B1-A1")
        devin = Path(self.tmp.name) / "fake_devin.py"
        # Keep the fixture alive beyond the ten-second observation window so
        # loaded CI runners cannot turn the intended stop/resume case into a
        # clean completion before stop_full_run records interruption evidence.
        # Bake the delay into the fixture because production launch correctly
        # does not inherit arbitrary ELVES_FAKE_* environment variables.
        devin.write_text(
            FAKE_DEVIN.replace(
                'pause = os.environ.get("ELVES_FAKE_DEVIN_PAUSE")',
                'pause = "30"',
            ),
            encoding="utf-8",
        )
        devin.chmod(devin.stat().st_mode | stat.S_IXUSR)
        with mock.patch.dict(os.environ, self._devin_clean_env(), clear=True):
            _attach_origin(self.repo, remote, self.branch)
            prepare_full_run(
                self.repo,
                session_id=self.session,
                branch=self.branch,
                start_head=self.start_head,
                worktree=self.repo,
                packet_path=self.packet,
                session_path=_write_production_acceptance_contract(self.repo, self.packet),
                adapter="devin-cli",
                executable=str(devin),
            )
            launch_full_run(
                self.repo,
                session_id=self.session,
                grant_devin_auth=True,
            )
            deadline = time.time() + 10
            while time.time() < deadline:
                time.sleep(0.05)
                monitor_full_run(self.repo, session_id=self.session, stale_after_seconds=60)
                state = load_state(self.repo, self.session)
                events_path = full_run_root(self.repo, self.session) / "events.jsonl"
                if state.provider_session_id and events_path.is_file():
                    text = events_path.read_text(encoding="utf-8")
                    if any(
                        json.loads(line).get("type") == "commit_pushed"
                        for line in text.splitlines()
                        if line.strip()
                    ):
                        break
            state = load_state(self.repo, self.session)
            self.assertEqual(state.provider_session_id, "devin-sess-123")

            stop_full_run(self.repo, session_id=self.session, grace_seconds=0.2)
            resumed = launch_full_run(
                self.repo,
                session_id=self.session,
                resume=True,
                grant_devin_auth=True,
            )
            self.assertIn("--resume", resumed["argv"])
            index = resumed["argv"].index("--resume")
            self.assertEqual(resumed["argv"][index + 1], "devin-sess-123")
            self.assertIn("--print", resumed["argv"])
            self.assertNotIn("--session-id", resumed["argv"])
            self.assertEqual(resumed["adapter"], "devin-cli")

    def test_devin_auth_missing_grant_fails_before_spawn(self) -> None:
        remote = Path(self.tmp.name) / "devin-missing-origin.git"
        _write_production_packet(self.packet, "B1-A1")
        devin = Path(self.tmp.name) / "fake_devin_missing.py"
        devin.write_text(FAKE_DEVIN, encoding="utf-8")
        devin.chmod(devin.stat().st_mode | stat.S_IXUSR)
        with mock.patch.dict(os.environ, self._devin_clean_env(), clear=True):
            _attach_origin(self.repo, remote, self.branch)
            prepare_full_run(
                self.repo,
                session_id=self.session,
                branch=self.branch,
                start_head=self.start_head,
                worktree=self.repo,
                packet_path=self.packet,
                session_path=_write_production_acceptance_contract(self.repo, self.packet),
                adapter="devin-cli",
                executable=str(devin),
            )
            with self.assertRaises(ValidationIssue) as ctx:
                launch_full_run(self.repo, session_id=self.session)
            self.assertEqual(ctx.exception.code, "full_run_devin_auth_required")

    def test_devin_auth_rejects_unsafe_source_permissions(self) -> None:
        remote = Path(self.tmp.name) / "devin-unsafe-origin.git"
        _write_production_packet(self.packet, "B1-A1")
        devin = Path(self.tmp.name) / "fake_devin_unsafe.py"
        devin.write_text(FAKE_DEVIN, encoding="utf-8")
        devin.chmod(devin.stat().st_mode | stat.S_IXUSR)
        env = self._devin_clean_env()
        with mock.patch.dict(os.environ, env, clear=True):
            _attach_origin(self.repo, remote, self.branch)
            prepare_full_run(
                self.repo,
                session_id=self.session,
                branch=self.branch,
                start_head=self.start_head,
                worktree=self.repo,
                packet_path=self.packet,
                session_path=_write_production_acceptance_contract(self.repo, self.packet),
                adapter="devin-cli",
                executable=str(devin),
            )
            (self.devin_data_dir / "devin" / "credentials.toml").chmod(0o644)
            with self.assertRaises(ValidationIssue) as ctx:
                launch_full_run(
                    self.repo,
                    session_id=self.session,
                    grant_devin_auth=True,
                )
            self.assertEqual(ctx.exception.code, "full_run_devin_auth_source_unsafe")

    def test_devin_auth_projection_replaces_worker_symlink_without_following_it(self) -> None:
        run_root = full_run_root(self.repo, self.session)
        worker_home = run_root / "worker-home"
        target = worker_home / ".local" / "share" / "devin" / "credentials.toml"
        target.parent.mkdir(parents=True)
        outside = Path(self.tmp.name) / "outside-credentials"
        outside.write_text("leave-me-alone\n", encoding="utf-8")
        target.symlink_to(outside)
        state = full_run_module.FullRunState(
            session_id=self.session,
            branch=self.branch,
            start_head=self.start_head,
            worktree=str(self.repo),
            packet_path=str(self.packet),
            adapter="devin-cli",
            executable=sys.executable,
        )
        with mock.patch.dict(os.environ, self._devin_clean_env(), clear=True):
            full_run_module._configure_devin_auth(
                self.repo,
                run_root,
                state,
                {},
                grant_devin_auth=True,
            )
        self.assertEqual(outside.read_text(encoding="utf-8"), "leave-me-alone\n")
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_devin_host_capture_event_may_follow_worker_terminal_event(self) -> None:
        base = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "session_id": self.session,
            "branch": self.branch,
            "head": self.start_head,
            "batch": 1,
            "summary": "terminal",
        }
        terminal = dict(base, type="run_complete")
        capture = dict(
            base,
            type="devin_session_captured",
            summary="Devin session captured from ATIF after fast worker exit",
            provider_session_id="devin-sess-123",
            candidate_count=0,
        )
        events = full_run_root(self.repo, self.session) / "events.jsonl"
        events.parent.mkdir(parents=True, exist_ok=True)
        events.write_text(
            json.dumps(terminal) + "\n" + json.dumps(capture) + "\n",
            encoding="utf-8",
        )
        rows, errors = full_run_module._read_events(
            events,
            expected_session_id=self.session,
            expected_branch=self.branch,
            repo_root=self.repo,
        )
        self.assertEqual(errors, [])
        self.assertEqual([row["type"] for row in rows], ["run_complete", "devin_session_captured"])

    def test_devin_auth_adapter_mismatch(self) -> None:
        state = full_run_module.FullRunState(
            session_id="devin-auth-mismatch",
            branch=self.branch,
            start_head=self.start_head,
            worktree=str(self.repo),
            packet_path=str(self.packet),
            adapter="fixture",
            executable=sys.executable,
        )
        with self.assertRaises(ValidationIssue) as ctx:
            full_run_module._configure_devin_auth(
                self.repo,
                full_run_root(self.repo, state.session_id),
                state,
                {},
                grant_devin_auth=True,
            )
        self.assertEqual(ctx.exception.code, "full_run_devin_auth_adapter_mismatch")


if __name__ == "__main__":
    unittest.main()
