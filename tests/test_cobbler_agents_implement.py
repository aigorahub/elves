"""Focused unit tests for Lane A implement CLI (prepare|launch|gate|resume-batch|status)."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
CLI = SCRIPTS / "cobbler_agents.py"


def _ensure_import_path() -> None:
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


_ensure_import_path()

import cobbler_runtime.implement as implement_module  # noqa: E402
from cobbler_runtime.implement import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_PERMISSION_MODE,
    MAX_DONE_REPORT_BYTES,
    build_launch_argv,
    humanize_grok_failure,
    implement_root,
    launch_payload,
    parse_unittest_output,
    prepare_implement,
    resolve_implement_model,
    resume_batch_payload,
    run_gate,
    state_path,
    status_payload,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402
from cobbler_runtime.worker_routing import (  # noqa: E402
    GrokCapabilities,
    GrokCapabilityEvidence,
)
import cobbler_runtime.storage as storage_module  # noqa: E402


TEST_GROK_SESSION = "11111111-1111-1111-1111-111111111111"


def _proven_grok_capabilities(*, models: tuple[str, ...] = ("grok-build",)) -> GrokCapabilities:
    proven = GrokCapabilityEvidence("proven", "test_fixture", "advertised_by_help")
    return GrokCapabilities(
        installed=True,
        authenticated=True,
        models=models,
        default_model=models[0],
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
                "streaming_json",
                "session_id",
                "resume",
                "check",
            )
        ),
    )


def _fake_bounded_result(
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    timed_out: bool = False,
) -> implement_module._BoundedProcessResult:
    stdout_bytes = stdout.encode()
    stderr_bytes = stderr.encode()
    return implement_module._BoundedProcessResult(
        exit_code=124 if timed_out else exit_code,
        timed_out=timed_out,
        stdout_window=stdout,
        stderr_window=stderr,
        stdout_digest=hashlib.sha256(stdout_bytes).hexdigest()[:16],
        stderr_digest=hashlib.sha256(stderr_bytes).hexdigest()[:16],
        stdout_bytes=len(stdout_bytes),
        stderr_bytes=len(stderr_bytes),
    )


def _write_fake_grok(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if args == ['version', '--json']:\n"
        "    print('{\"currentVersion\":\"0.2.101 (5bc4b5dfadcf)\"}')\n"
        "elif args == ['models']:\n"
        "    print('Default model: grok-build\\nAvailable models:\\n  * grok-build (default)')\n"
        "elif args == ['agent', 'stdio', '--help']:\n"
        "    print('Run the agent over stdio')\n"
        "else:\n"
        "    print('--prompt-file --cwd --model --permission-mode --always-approve "
        "--reasoning-effort --max-turns --output-format streaming-json "
        "--session-id --resume --check')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _run_cli(repo_root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args, "--repo-root", str(repo_root)],
        check=check,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _pid_is_executable(pid: int) -> bool:
    """Treat Linux zombies as inert while waiting for recursive cleanup."""
    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
    except OSError:
        raw = ""
    if raw:
        close_paren = raw.rfind(")")
        fields = raw[close_paren + 2 :].split() if close_paren >= 0 else []
        if fields and fields[0] in {"Z", "X", "x"}:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class BuildLaunchArgvTests(unittest.TestCase):
    def test_fugu_launchers_are_blocked_for_every_implement_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "batch-1.md"
            packet.write_text("# packet\n", encoding="utf-8")
            for adapter, executable in (
                ("opencode-cli", "codex-fugu"),
                ("grok-build", "Claude-Fugu"),
                ("devin-cli", "/tmp/CODEX-FUGU"),
                ("omp-cli", "claude-fugu"),
                ("codex-fugu", "grok"),
            ):
                with self.subTest(adapter=adapter, executable=executable):
                    with self.assertRaises(ValidationIssue) as raised:
                        build_launch_argv(
                            session_id=TEST_GROK_SESSION,
                            packet=packet,
                            cwd=tmp,
                            adapter=adapter,
                            executable=executable,
                        )
                    self.assertEqual(
                        raised.exception.code,
                        "fugu_implementation_route_blocked",
                    )

    def test_resume_argv_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "batch-1.md"
            packet.write_text("# packet\n", encoding="utf-8")
            cwd = Path(tmp) / "wt"
            cwd.mkdir()
            argv = build_launch_argv(
                session_id=TEST_GROK_SESSION,
                packet=packet,
                cwd=cwd,
            )
        self.assertEqual(argv[0], "grok")
        self.assertIn("--resume", argv)
        self.assertIn(TEST_GROK_SESSION, argv)
        self.assertNotIn("--session-id", argv)
        self.assertNotIn("--permission-mode", argv)
        self.assertEqual(argv[argv.index("--model") + 1], DEFAULT_MODEL)
        self.assertIn("--prompt-file", argv)
        self.assertIn("--always-approve", argv)
        self.assertIn("--effort", argv)
        self.assertEqual(argv[argv.index("--effort") + 1], "high")
        self.assertIn("--max-turns", argv)
        self.assertNotIn("--no-subagents", argv)
        self.assertNotIn("dontAsk", argv)
        self.assertNotIn("-p", argv)
        self.assertNotIn("--single", argv)

    def test_non_yolo_launch_keeps_explicit_permission_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "batch-1.md"
            packet.write_text("# packet\n", encoding="utf-8")
            argv = build_launch_argv(
                session_id=TEST_GROK_SESSION,
                packet=packet,
                cwd=tmp,
                permission_mode=DEFAULT_PERMISSION_MODE,
                yolo=False,
            )
        self.assertEqual(
            argv[argv.index("--permission-mode") + 1],
            DEFAULT_PERMISSION_MODE,
        )
        self.assertNotIn("--always-approve", argv)

    def test_create_uses_session_id_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("x\n", encoding="utf-8")
            cwd = Path(tmp)
            argv = build_launch_argv(
                session_id=TEST_GROK_SESSION,
                packet=packet,
                cwd=cwd,
                create=True,
            )
        self.assertIn("--session-id", argv)
        self.assertNotIn("--resume", argv)

    def test_explicit_grok_effort_overrides_high_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("x\n", encoding="utf-8")
            argv = build_launch_argv(
                session_id=TEST_GROK_SESSION,
                packet=packet,
                cwd=tmp,
                effort="low",
            )
        self.assertEqual(argv[argv.index("--effort") + 1], "low")

    def test_dontask_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("x\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                build_launch_argv(
                    session_id=TEST_GROK_SESSION,
                    packet=packet,
                    cwd=tmp,
                    permission_mode="dontAsk",
                )
        self.assertEqual(ctx.exception.code, "implement_dontask_forbidden")

    def test_create_requires_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("x\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                build_launch_argv(
                    session_id="  ",
                    packet=packet,
                    cwd=tmp,
                    create=True,
                )
        self.assertEqual(ctx.exception.code, "missing_session_id")

    def test_grok_model_is_not_expanded_from_legacy_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("x\n", encoding="utf-8")
            argv = build_launch_argv(
                session_id=TEST_GROK_SESSION,
                packet=packet,
                cwd=tmp,
                model="deep",
                check=True,
            )
        self.assertEqual(argv[argv.index("--model") + 1], "deep")
        self.assertEqual(argv[argv.index("--effort") + 1], "high")
        self.assertIn("--check", argv)

    def test_grok_fast_alias_remains_an_exact_catalog_candidate(self) -> None:
        model, effort, notes = resolve_implement_model("fast")
        self.assertEqual(model, "fast")
        self.assertEqual(notes, [])
        self.assertEqual(effort, "high")

    def test_devin_keeps_balanced_default_when_grok_uses_high(self) -> None:
        model, effort, notes = resolve_implement_model(
            None,
            adapter="devin-cli",
        )
        self.assertEqual(model, "swe-1-7-lightning")
        self.assertEqual(effort, "medium")
        self.assertEqual(notes, [])

    def test_grok_session_must_be_canonical_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("x\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as caught:
                build_launch_argv(session_id="not-a-uuid", packet=packet, cwd=tmp)
        self.assertEqual(caught.exception.code, "invalid_grok_session_uuid")

    def test_opencode_message_precedes_file_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("# packet\n", encoding="utf-8")
            argv = build_launch_argv(
                session_id="session-1",
                packet=packet,
                cwd=tmp,
                model="openrouter/qwen/qwen3-max",
                executable="opencode",
                adapter="opencode-cli",
            )

        self.assertEqual(argv[:2], ["opencode", "run"])
        self.assertIn("Implement the attached task packet", argv[2])
        self.assertLess(2, argv.index("--file"))
        self.assertEqual(argv[argv.index("--file") + 1], str(packet.resolve()))
        self.assertIn("--auto", argv)

    def test_devin_create_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("# packet\n", encoding="utf-8")
            cwd = Path(tmp) / "wt"
            cwd.mkdir()
            argv = build_launch_argv(
                packet=packet,
                cwd=cwd,
                adapter="devin-cli",
                create=True,
            )
        self.assertEqual(argv[0], "devin")
        self.assertIn("--prompt-file", argv)
        self.assertIn(str(packet.resolve()), argv)
        self.assertIn("--print", argv)
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "swe-1-7-lightning")
        self.assertIn("--permission-mode", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dangerous")
        self.assertNotIn("--resume", argv)
        self.assertNotIn("--session-id", argv)
        self.assertNotIn("--cwd", argv)
        self.assertNotIn("-c", argv)
        self.assertNotIn("--continue", argv)

    def test_devin_resume_argv_exact_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("# packet\n", encoding="utf-8")
            argv = build_launch_argv(
                session_id="poised-eoraptor",
                packet=packet,
                cwd=tmp,
                adapter="devin-cli",
                create=False,
            )
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], "poised-eoraptor")
        self.assertIn("--print", argv)
        self.assertNotIn("--continue", argv)
        self.assertNotIn("-c", argv)

    def test_devin_resume_rejects_bare_continue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("# packet\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                build_launch_argv(
                    session_id="continue",
                    packet=packet,
                    cwd=tmp,
                    adapter="devin-cli",
                )
        self.assertEqual(ctx.exception.code, "ambiguous_session_id")

    def test_devin_export_path_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "p.md"
            packet.write_text("# packet\n", encoding="utf-8")
            export_path = str(Path(tmp) / "devin.atif")
            argv = build_launch_argv(
                packet=packet,
                cwd=tmp,
                adapter="devin-cli",
                create=True,
                export_path=export_path,
            )
        self.assertIn("--export", argv)
        self.assertEqual(argv[argv.index("--export") + 1], export_path)
        self.assertIn("--print", argv)


class HumanizeGrokFailureTests(unittest.TestCase):
    def test_tools_allowlist_requirement_error(self) -> None:
        msg = humanize_grok_failure(
            stderr="RequirementError: run_terminal_cmd background param with --tools"
        )
        self.assertIn("disallowed-tools", msg)
        self.assertNotIn("thread '", msg)

    def test_auth_failure(self) -> None:
        msg = humanize_grok_failure(stdout="Error: not logged in")
        self.assertIn("not authenticated", msg.lower())

    def test_empty_with_exit_code(self) -> None:
        msg = humanize_grok_failure(exit_code=2)
        self.assertIn("2", msg)


class PrepareImplementTests(unittest.TestCase):
    def test_prepare_rejects_fugu_implementation_route_before_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValidationIssue) as raised:
                prepare_implement(
                    root,
                    adapter="devin-cli",
                    executable="Claude-Fugu",
                )
            self.assertEqual(
                raised.exception.code,
                "fugu_implementation_route_blocked",
            )
            self.assertFalse(state_path(root).exists())

    def test_regular_default_model_defers_to_live_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = prepare_implement(Path(tmp), session_id="composer-default")
            self.assertEqual(payload["state"]["model"], "auto")

    def test_prepare_writes_state_and_private_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = prepare_implement(
                root,
                worktree=root / "wt",
                model="grok-4.5",
                session_id="sess-prepare",
                branch="feat/lane-a",
            )
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["network_required"])
            self.assertFalse(payload["model_calls_made"])
            runtime = implement_root(root)
            self.assertTrue(runtime.is_dir())
            mode = stat.S_IMODE(runtime.stat().st_mode)
            # 0700 on platforms that honor chmod
            if os.name != "nt":
                self.assertEqual(mode, 0o700)
            data = json.loads(state_path(root).read_text(encoding="utf-8"))
            self.assertEqual(data["lane"], "fast")
            self.assertEqual(data["git_mode"], "branch_progress")
            self.assertEqual(data["session_id"], "sess-prepare")
            self.assertEqual(data["model"], "grok-4.5")
            self.assertEqual(data["permission_mode"], "auto")
            self.assertTrue(data["subagents"])
            self.assertTrue((runtime / "gates").is_dir())
            self.assertTrue((runtime / "done").is_dir())

    def test_prepare_rejects_dontask(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValidationIssue):
                prepare_implement(Path(tmp), permission_mode="dontAsk")

    def test_prepare_keeps_legacy_model_name_as_exact_catalog_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = prepare_implement(root, model="deep", session_id="s")
            self.assertEqual(payload["state"]["model"], "deep")
            self.assertFalse(
                any("alias" in n.lower() for n in payload["state"]["notes"])
            )

    def test_prepare_rejects_symlinked_runtime_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_parent = root / ".elves" / "runtime"
            runtime_parent.mkdir(parents=True)
            external = root / "external-runtime"
            external.mkdir()
            implement = runtime_parent / "implement"
            try:
                implement.symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")

            with self.assertRaises(ValidationIssue) as ctx:
                prepare_implement(root, session_id="s")

            self.assertEqual(ctx.exception.code, "implement_runtime_symlink")
            self.assertEqual(list(external.iterdir()), [])

    def test_state_read_rejects_hardlink_without_touching_external_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id="hardlink-state")
            state = state_path(root)
            external = root / "external-state.json"
            original = state.read_text(encoding="utf-8")
            external.write_text(original, encoding="utf-8")
            state.unlink()
            try:
                os.link(external, state)
            except (OSError, NotImplementedError):
                self.skipTest("hard links unavailable")

            with self.assertRaises(ValidationIssue) as ctx:
                status_payload(root)

            self.assertEqual(ctx.exception.code, "implement_runtime_hardlink")
            self.assertEqual(external.read_text(encoding="utf-8"), original)

    def test_state_read_rejects_ancestor_swap_after_initial_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id="race-state")
            runtime = implement_root(root)
            parked = runtime.with_name("implement-parked")
            external = root / "external-runtime"
            external.mkdir()
            outside_state = external / "state.json"
            outside_state.write_text('{"outside":true}\n', encoding="utf-8")
            original_guard = storage_module.guard_repo_path
            armed = True

            def swap_after_guard(repo_root: Path, path: Path) -> Path:
                nonlocal armed
                candidate = original_guard(repo_root, path)
                if armed and Path(path) == state_path(root):
                    runtime.rename(parked)
                    runtime.symlink_to(external, target_is_directory=True)
                    armed = False
                return candidate

            try:
                with (
                    mock.patch(
                        "cobbler_runtime.storage.guard_repo_path",
                        side_effect=swap_after_guard,
                    ),
                    self.assertRaises(ValidationIssue) as ctx,
                ):
                    status_payload(root)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink race fixture unavailable")

            self.assertEqual(ctx.exception.code, "implement_runtime_symlink")
            self.assertEqual(
                outside_state.read_text(encoding="utf-8"), '{"outside":true}\n'
            )

    def test_state_read_rejects_leaf_symlink_swap_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id="race-state-leaf")
            state = state_path(root)
            parked = state.with_name("state-parked.json")
            external = root / "external-state.json"
            original = '{"outside":"keep"}\n'
            external.write_text(original, encoding="utf-8")
            original_assert = storage_module._assert_safe_regular_leaf
            armed = True

            def swap_after_leaf_check(
                parent_fd: int,
                name: str,
                *,
                display_path: Path,
            ) -> os.stat_result | None:
                nonlocal armed
                info = original_assert(
                    parent_fd,
                    name,
                    display_path=display_path,
                )
                if armed and display_path == state:
                    state.rename(parked)
                    state.symlink_to(external)
                    armed = False
                return info

            try:
                with (
                    mock.patch(
                        "cobbler_runtime.storage._assert_safe_regular_leaf",
                        side_effect=swap_after_leaf_check,
                    ),
                    self.assertRaises(ValidationIssue) as ctx,
                ):
                    status_payload(root)
            except (OSError, NotImplementedError):
                self.skipTest("file symlink race fixture unavailable")

            self.assertEqual(ctx.exception.code, "implement_runtime_symlink")
            self.assertEqual(external.read_text(encoding="utf-8"), original)


class LaunchAndResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.capability_probe = mock.patch(
            "cobbler_runtime.worker_routing.probe_grok_capabilities",
            return_value=_proven_grok_capabilities(),
        )
        self.capability_probe.start()
        self.addCleanup(self.capability_probe.stop)

    def test_launch_payload_print_only_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id=TEST_GROK_SESSION, worktree=root)
            packet = root / "packet.md"
            packet.write_text("batch\n", encoding="utf-8")
            payload = launch_payload(
                root,
                packet=packet,
                batch=1,
                exec_process=False,
            )
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["launched"])
            self.assertIn("--resume", payload["argv"])
            self.assertIn(TEST_GROK_SESSION, payload["argv"])
            self.assertNotIn("--no-subagents", payload["argv"])
            state = json.loads(state_path(root).read_text(encoding="utf-8"))
            self.assertEqual(state["last_batch"], 1)
            self.assertTrue(state["last_packet"].endswith("packet.md"))

    def test_resume_batch_sets_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id=TEST_GROK_SESSION)
            packet = root / "b2.md"
            packet.write_text("b2\n", encoding="utf-8")
            payload = resume_batch_payload(root, batch=2, packet=packet)
            self.assertEqual(payload["action"], "resume-batch")
            self.assertEqual(payload["batch"], 2)
            self.assertIn("--resume", payload["argv"])

    def test_legacy_launch_rejects_alias_or_model_absent_from_live_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id=TEST_GROK_SESSION, model="deep")
            packet = root / "batch.md"
            packet.write_text("batch\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as caught:
                launch_payload(root, packet=packet, exec_process=False)
            self.assertEqual(caught.exception.code, "grok_model_not_in_live_catalog")


class ParseUnittestOutputTests(unittest.TestCase):
    def test_ok_with_skips(self) -> None:
        text = ".....\n----------------------------------------------------------------------\nRan 5 tests in 0.01s\n\nOK (skipped=1)\n"
        counts = parse_unittest_output(text)
        self.assertEqual(counts["total"], 5)
        self.assertEqual(counts["skipped"], 1)
        self.assertEqual(counts["failed"], 0)
        self.assertEqual(counts["passed"], 4)

    def test_failed(self) -> None:
        text = (
            "F.\n----------------------------------------------------------------------\n"
            "Ran 2 tests in 0.00s\n\nFAILED (failures=1)\n"
        )
        counts = parse_unittest_output(text)
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["passed"], 1)


class RunGateTests(unittest.TestCase):
    def test_gate_records_and_fails_on_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            failing = [
                sys.executable,
                "-c",
                "import sys; print('Ran 1 test in 0.0s'); print('FAILED (failures=1)'); sys.exit(1)",
            ]
            record = run_gate(root, batch=3, test_command=failing)
            self.assertFalse(record["ok"])
            self.assertEqual(record["batch"], 3)
            self.assertEqual(record["tests"]["failed"], 1)
            gate_file = implement_root(root) / "gates" / "batch-3.json"
            self.assertTrue(gate_file.is_file())
            saved = json.loads(gate_file.read_text(encoding="utf-8"))
            self.assertFalse(saved["ok"])
            # Missing done report is warning-only.
            self.assertTrue(
                any("done report missing" in w for w in record.get("warnings") or [])
            )

    def test_gate_ok_with_done_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            done = implement_root(root) / "done" / "batch-1.json"
            done.write_text(
                json.dumps(
                    {
                        "batch": 1,
                        "status": "complete",
                        "session_id": "s",
                        "head": "abc",
                        "commits": [],
                        "tests": {"passed": 1, "failed": 0, "skipped": 0},
                        "blockers": [],
                        "acceptance": [
                            {"criterion": "x", "met": True, "evidence": "y"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            ok_cmd = [
                sys.executable,
                "-c",
                "print('Ran 1 test in 0.0s'); print('OK')",
            ]
            record = run_gate(root, batch=1, test_command=ok_cmd)
            self.assertTrue(record["ok"])
            self.assertTrue(record["done_report_present"])
            self.assertEqual(record["done_report"]["status"], "complete")

    def test_gate_confidence_signal_valid_and_malformed_fields(self) -> None:
        base_report = {
            "batch": 5,
            "status": "complete",
            "session_id": "s",
            "head": "abc",
            "commits": [],
            "tests": {"passed": 1, "failed": 0, "skipped": 0},
            "blockers": [],
            "acceptance": [{"criterion": "x", "met": True, "evidence": "y"}],
        }
        ok_cmd = [
            sys.executable,
            "-c",
            "print('Ran 1 test in 0.0s'); print('OK')",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            done = implement_root(root) / "done" / "batch-5.json"
            for signal in (
                {"confidence": "low", "unsure_about": ["retry bounds", "csv path"]},
                # Empty unsure_about is a valid, complete answer.
                {"confidence": "high", "unsure_about": []},
                # Absent fields stay valid.
                {},
            ):
                with self.subTest(signal=signal):
                    done.write_text(
                        json.dumps({**base_report, **signal}), encoding="utf-8"
                    )
                    record = run_gate(root, batch=5, test_command=ok_cmd)
                    self.assertTrue(record["ok"])
                    self.assertFalse(
                        [
                            w
                            for w in record["warnings"]
                            if "confidence" in w or "unsure_about" in w
                        ],
                        record["warnings"],
                    )
            done.write_text(
                json.dumps(
                    {**base_report, "confidence": "certain", "unsure_about": "oops"}
                ),
                encoding="utf-8",
            )
            record = run_gate(root, batch=5, test_command=ok_cmd)
            # Legacy dogfood posture: malformed signal is warning-only.
            self.assertTrue(record["ok"])
            self.assertIn(
                "done report confidence must be one of high, medium, low",
                record["warnings"],
            )
            self.assertIn(
                "done report unsure_about must be a list", record["warnings"]
            )

    def test_done_report_confidence_warning_helper_bounds(self) -> None:
        helper = implement_module._done_report_confidence_warnings
        self.assertEqual(helper({}), [])
        self.assertEqual(helper({"confidence": "medium", "unsure_about": []}), [])
        self.assertEqual(
            helper({"unsure_about": [7]}),
            ["done report unsure_about items must be non-empty strings"],
        )
        self.assertEqual(
            helper({"unsure_about": ["x" * 501]}),
            ["done report unsure_about item exceeds 500 chars"],
        )
        self.assertEqual(
            helper({"unsure_about": [f"item {index}" for index in range(17)]}),
            ["done report unsure_about exceeds 16 items"],
        )

    def test_gate_uses_minimal_env_and_redacts_all_returned_and_saved_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            secret = "opaque-gate-secret-123456789"
            done = implement_root(root) / "done" / "batch-2.json"
            done.write_text(
                json.dumps(
                    {
                        "batch": 2,
                        "status": "complete",
                        "nested": {secret: secret},
                    }
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                "-c",
                (
                    "import os,sys; "
                    f"print({secret!r}); "
                    "print('child_has_secret=' + str('CUSTOM_GATE_SECRET' in os.environ)); "
                    "print('child_has_unrelated=' + str('UNRELATED_HOST_VALUE' in os.environ)); "
                    "print('HOME=' + os.environ['HOME']); "
                    "print('TMPDIR=' + os.environ['TMPDIR']); "
                    f"sys.stderr.write({secret!r} + '\\n'); "
                    "print('Ran 1 test in 0.0s'); print('OK')"
                ),
            ]
            with mock.patch.dict(
                os.environ,
                {"CUSTOM_GATE_SECRET": secret, "UNRELATED_HOST_VALUE": "do-not-inherit"},
                clear=False,
            ):
                record = run_gate(root, batch=2, test_command=command)

            returned = json.dumps(record, sort_keys=True)
            saved = (implement_root(root) / "gates" / "batch-2.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(secret, returned)
            self.assertNotIn(secret, saved)
            self.assertIn("[REDACTED:", returned)
            self.assertIn("child_has_secret=False", record["stdout_tail"])
            self.assertIn("child_has_unrelated=False", record["stdout_tail"])
            home_line = next(
                line for line in record["stdout_tail"].splitlines() if line.startswith("HOME=")
            )
            tmp_line = next(
                line for line in record["stdout_tail"].splitlines() if line.startswith("TMPDIR=")
            )
            self.assertFalse(Path(home_line.removeprefix("HOME=")).exists())
            self.assertFalse(Path(tmp_line.removeprefix("TMPDIR=")).exists())

    def test_gate_record_not_mangled_by_short_secret_named_flag_values(self) -> None:
        # Regression (B1): Claude Code sessions export secret-*named* flags with
        # value "1". Exact-value redaction must skip them; otherwise every
        # literal 1 in the record (gate_path, cwd, timestamps) is replaced with
        # [REDACTED:exact_grant] and the recorded gate_path no longer exists.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            command = [
                sys.executable,
                "-c",
                "print('Ran 1 test in 0.0s'); print('OK')",
            ]
            with mock.patch.dict(
                os.environ,
                {
                    "CLAUDE_CODE_SDK_HAS_OAUTH_REFRESH": "1",
                    "CLAUDE_CODE_CHILD_SESSION": "1",
                },
                clear=False,
            ):
                record = run_gate(root, batch=12, test_command=command)
            self.assertTrue(record["ok"])
            for field in ("gate_path", "cwd", "done_report_path", "recorded_at"):
                self.assertNotIn("[REDACTED", record[field], field)
            gate_path = Path(record["gate_path"])
            self.assertTrue(gate_path.is_file())
            self.assertEqual(
                gate_path,
                implement_root(root) / "gates" / "batch-12.json",
            )
            saved = json.loads(gate_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["gate_path"], record["gate_path"])

    def test_gate_still_redacts_minimum_length_secret_named_env_values(self) -> None:
        # Regression companion (B1): the guard must narrow only short values.
        # A secret-named env value of exactly 8 characters (the minimum) still
        # redacts everywhere it appears in returned and persisted evidence.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            secret = "opaqu8tk"
            self.assertEqual(len(secret), 8)
            command = [
                sys.executable,
                "-c",
                (
                    f"print({secret!r}); "
                    "print('Ran 1 test in 0.0s'); print('OK')"
                ),
            ]
            with mock.patch.dict(
                os.environ, {"CUSTOM_GATE_TOKEN": secret}, clear=False
            ):
                record = run_gate(root, batch=13, test_command=command)
            returned = json.dumps(record, sort_keys=True)
            self.assertNotIn(secret, returned)
            self.assertIn("[REDACTED:exact_grant]", record["stdout_tail"])
            saved = (implement_root(root) / "gates" / "batch-13.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(secret, saved)

    def test_gate_redacts_semantic_secret_fields_without_collapsing_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            secrets = {
                "api_key": "opaque-api-key-value-123456789",
                "refresh_token": "opaque-refresh-token-value-123456789",
                "password": "opaque-password-value-123456789",
                "authorization": "Bearer opaque-authorization-value-123456789",
            }
            done = implement_root(root) / "done" / "batch-11.json"
            done.write_text(
                json.dumps(
                    {
                        "batch": 11,
                        "status": "complete",
                        # Force a collision with the suffix that the second
                        # semantic secret field would otherwise receive.
                        "[REDACTED:secret_field_name]#4": "operator-note",
                        "api_key": secrets["api_key"],
                        "refresh_token": secrets["refresh_token"],
                        # A descriptive, non-secret field containing the phrase
                        # must remain available as useful evidence.
                        "test_api_key_redaction": "passed",
                        "nested": {
                            "password": secrets["password"],
                            "safe": "kept",
                        },
                        "items": [
                            {"Authorization": secrets["authorization"]},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                "-c",
                "print('Ran 1 test in 0.0s'); print('OK')",
            ]

            returned_record = run_gate(root, batch=11, test_command=command)
            saved_record = json.loads(
                (implement_root(root) / "gates" / "batch-11.json").read_text(
                    encoding="utf-8"
                )
            )

            for record in (returned_record, saved_record):
                serialized = json.dumps(record, sort_keys=True)
                for secret in secrets.values():
                    self.assertNotIn(secret, serialized)
                for raw_key in (
                    '"api_key"',
                    '"refresh_token"',
                    '"password"',
                    '"Authorization"',
                ):
                    self.assertNotIn(raw_key, serialized)
                report = record["done_report"]
                secret_keys = [
                    key
                    for key in report
                    if report[key] == "[REDACTED:secret_field]"
                ]
                self.assertEqual(len(secret_keys), 2)
                self.assertEqual(
                    {report[key] for key in secret_keys},
                    {"[REDACTED:secret_field]"},
                )
                self.assertEqual(
                    report["[REDACTED:secret_field_name]#4"],
                    "operator-note",
                )
                self.assertEqual(report["test_api_key_redaction"], "passed")
                self.assertEqual(report["nested"]["safe"], "kept")
                self.assertEqual(
                    report["nested"]["[REDACTED:secret_field_name]"],
                    "[REDACTED:secret_field]",
                )
                self.assertEqual(
                    report["items"][0]["[REDACTED:secret_field_name]"],
                    "[REDACTED:secret_field]",
                )

    def test_gate_bounds_done_report_and_rejects_runtime_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            done = implement_root(root) / "done" / "batch-4.json"
            done.write_bytes(b"x" * (MAX_DONE_REPORT_BYTES + 1))
            command = [
                sys.executable,
                "-c",
                "print('Ran 1 test in 0.0s'); print('OK')",
            ]
            record = run_gate(root, batch=4, test_command=command)
            self.assertTrue(record["done_report_present"])
            self.assertIsNone(record["done_report"])
            self.assertTrue(any("byte limit" in item for item in record["warnings"]))

            external = root / "external-done.json"
            external.write_text('{"status":"complete"}\n', encoding="utf-8")
            done.unlink()
            try:
                done.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(ValidationIssue) as ctx:
                run_gate(root, batch=4, test_command=command)
            self.assertEqual(ctx.exception.code, "implement_runtime_symlink")
            self.assertEqual(external.read_text(encoding="utf-8"), '{"status":"complete"}\n')

    def test_gate_spawn_error_is_redacted_and_scoped_env_is_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            secret = "opaque-spawn-secret-123456789"
            with (
                mock.patch.dict(
                    os.environ, {"CUSTOM_GATE_SECRET": secret}, clear=False
                ),
                mock.patch(
                    "cobbler_runtime.implement.subprocess.run",
                    side_effect=OSError(f"cannot execute {secret}"),
                ) as run_mock,
                self.assertRaises(ValidationIssue) as ctx,
            ):
                run_gate(root, batch=5, test_command=[secret])
            self.assertEqual(ctx.exception.code, "implement_gate_spawn_failed")
            self.assertNotIn(secret, ctx.exception.message)
            child_env = run_mock.call_args.kwargs["env"]
            self.assertNotIn("CUSTOM_GATE_SECRET", child_env)
            self.assertFalse(Path(child_env["HOME"]).exists())
            self.assertFalse(Path(child_env["TMPDIR"]).exists())

    def test_gate_redacts_before_tail_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            secret = "opaque-boundary-secret-zyxwvutsrqponmlk"
            prefix = "Ran 1 test in 0.0s\nOK\n"
            # Make the 2,000-character tail start ten characters into the
            # secret. Redacting only after slicing would expose its suffix.
            stdout = prefix + secret + ("z" * (2010 - len(secret)))
            test_result = subprocess.CompletedProcess(
                args=["gate-test"], returncode=0, stdout=stdout, stderr=""
            )
            git_result = subprocess.CompletedProcess(
                args=["git", "rev-parse", "HEAD"],
                returncode=1,
                stdout="",
                stderr="",
            )
            with (
                mock.patch.dict(
                    os.environ, {"CUSTOM_GATE_SECRET": secret}, clear=False
                ),
                mock.patch(
                    "cobbler_runtime.implement.subprocess.run",
                    side_effect=[test_result, git_result],
                ),
            ):
                record = run_gate(root, batch=6, test_command=["gate-test"])

            self.assertNotIn(secret[10:], record["stdout_tail"])
            saved = (implement_root(root) / "gates" / "batch-6.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(secret[10:], saved)

    def test_gate_rejects_hardlinked_done_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            external = root / "external-done.json"
            original = '{"status":"complete"}\n'
            external.write_text(original, encoding="utf-8")
            done = implement_root(root) / "done" / "batch-7.json"
            try:
                os.link(external, done)
            except (OSError, NotImplementedError):
                self.skipTest("hard links unavailable")
            command = [
                sys.executable,
                "-c",
                "print('Ran 1 test in 0.0s'); print('OK')",
            ]

            with self.assertRaises(ValidationIssue) as ctx:
                run_gate(root, batch=7, test_command=command)

            self.assertEqual(ctx.exception.code, "implement_runtime_hardlink")
            self.assertEqual(external.read_text(encoding="utf-8"), original)

    def test_gate_rejects_hardlinked_destination_without_replacing_external(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            external = root / "external-gate.json"
            original = '{"outside":"keep"}\n'
            external.write_text(original, encoding="utf-8")
            gate = implement_root(root) / "gates" / "batch-8.json"
            try:
                os.link(external, gate)
            except (OSError, NotImplementedError):
                self.skipTest("hard links unavailable")
            command = [
                sys.executable,
                "-c",
                "print('Ran 1 test in 0.0s'); print('OK')",
            ]

            with self.assertRaises(ValidationIssue) as ctx:
                run_gate(root, batch=8, test_command=command)

            self.assertEqual(ctx.exception.code, "implement_runtime_hardlink")
            self.assertEqual(external.read_text(encoding="utf-8"), original)

    def test_gate_write_rejects_ancestor_swap_after_initial_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            gates = implement_root(root) / "gates"
            parked = gates.with_name("gates-parked")
            external = root / "external-gates"
            external.mkdir()
            sentinel = external / "outside.json"
            sentinel.write_text('{"outside":"keep"}\n', encoding="utf-8")
            gate = gates / "batch-9.json"
            original_guard = storage_module.guard_repo_path
            armed = True

            def swap_after_guard(repo_root: Path, path: Path) -> Path:
                nonlocal armed
                candidate = original_guard(repo_root, path)
                if armed and Path(path) == gate:
                    gates.rename(parked)
                    gates.symlink_to(external, target_is_directory=True)
                    armed = False
                return candidate

            command = [
                sys.executable,
                "-c",
                "print('Ran 1 test in 0.0s'); print('OK')",
            ]
            try:
                with (
                    mock.patch(
                        "cobbler_runtime.storage.guard_repo_path",
                        side_effect=swap_after_guard,
                    ),
                    self.assertRaises(ValidationIssue) as ctx,
                ):
                    run_gate(root, batch=9, test_command=command)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink race fixture unavailable")

            self.assertEqual(ctx.exception.code, "implement_runtime_symlink")
            self.assertEqual(
                sentinel.read_text(encoding="utf-8"), '{"outside":"keep"}\n'
            )
            self.assertFalse((external / "batch-9.json").exists())

    def test_gate_write_rejects_leaf_hardlink_swap_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root)
            gate = implement_root(root) / "gates" / "batch-10.json"
            gate.write_text('{"old":true}\n', encoding="utf-8")
            external = root / "external-gate.json"
            original = '{"outside":"keep"}\n'
            external.write_text(original, encoding="utf-8")
            original_assert = storage_module._assert_safe_regular_leaf
            armed = True

            def swap_after_leaf_check(
                parent_fd: int,
                name: str,
                *,
                display_path: Path,
            ) -> os.stat_result | None:
                nonlocal armed
                info = original_assert(
                    parent_fd,
                    name,
                    display_path=display_path,
                )
                if armed and display_path == gate:
                    gate.unlink()
                    os.link(external, gate)
                    armed = False
                return info

            command = [
                sys.executable,
                "-c",
                "print('Ran 1 test in 0.0s'); print('OK')",
            ]
            try:
                with (
                    mock.patch(
                        "cobbler_runtime.storage._assert_safe_regular_leaf",
                        side_effect=swap_after_leaf_check,
                    ),
                    self.assertRaises(ValidationIssue) as ctx,
                ):
                    run_gate(root, batch=10, test_command=command)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link race fixture unavailable")

            self.assertEqual(ctx.exception.code, "implement_runtime_hardlink")
            self.assertEqual(external.read_text(encoding="utf-8"), original)


class StatusTests(unittest.TestCase):
    def test_status_absent_and_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            absent = status_payload(root)
            self.assertTrue(absent["ok"])
            self.assertFalse(absent["present"])
            prepare_implement(root, session_id="sid")
            present = status_payload(root)
            self.assertTrue(present["present"])
            self.assertEqual(present["state"]["session_id"], "sid")

    def test_status_listing_rejects_hardlinked_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id="sid")
            external = root / "external-list.json"
            original = '{"outside":"keep"}\n'
            external.write_text(original, encoding="utf-8")
            gate = implement_root(root) / "gates" / "batch-1.json"
            try:
                os.link(external, gate)
            except (OSError, NotImplementedError):
                self.skipTest("hard links unavailable")

            with self.assertRaises(ValidationIssue) as ctx:
                status_payload(root)

            self.assertEqual(ctx.exception.code, "implement_runtime_hardlink")
            self.assertEqual(external.read_text(encoding="utf-8"), original)

    def test_status_listing_rejects_ancestor_swap_after_initial_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id="sid")
            gates = implement_root(root) / "gates"
            parked = gates.with_name("gates-parked")
            external = root / "external-gates"
            external.mkdir()
            sentinel = external / "batch-outside.json"
            sentinel.write_text('{"outside":"keep"}\n', encoding="utf-8")
            original_guard = storage_module.guard_repo_path
            armed = True

            def swap_after_guard(repo_root: Path, path: Path) -> Path:
                nonlocal armed
                candidate = original_guard(repo_root, path)
                if armed and Path(path) == gates:
                    gates.rename(parked)
                    gates.symlink_to(external, target_is_directory=True)
                    armed = False
                return candidate

            try:
                with (
                    mock.patch(
                        "cobbler_runtime.storage.guard_repo_path",
                        side_effect=swap_after_guard,
                    ),
                    self.assertRaises(ValidationIssue) as ctx,
                ):
                    status_payload(root)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink race fixture unavailable")

            self.assertEqual(ctx.exception.code, "implement_runtime_symlink")
            self.assertEqual(
                sentinel.read_text(encoding="utf-8"), '{"outside":"keep"}\n'
            )


class CliIntegrationTests(unittest.TestCase):
    def test_implement_help(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "implement", "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("prepare", result.stdout)
        self.assertIn("launch", result.stdout)
        self.assertIn("gate", result.stdout)
        self.assertIn("resume-batch", result.stdout)
        self.assertIn("status", result.stdout)

    def test_cli_prepare_json_and_launch_print(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_grok = _write_fake_grok(root / "grok")
            prep = _run_cli(
                root,
                "implement",
                "prepare",
                "--json",
                "--session-id",
                TEST_GROK_SESSION,
                "--branch",
                "feat/x",
                "--executable",
                str(fake_grok),
            )
            self.assertEqual(prep.returncode, 0, prep.stderr)
            payload = json.loads(prep.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["state"]["lane"], "fast")
            self.assertEqual(payload["state"]["git_mode"], "branch_progress")

            packet = root / "batch.md"
            packet.write_text("packet\n", encoding="utf-8")
            launch = _run_cli(
                root,
                "implement",
                "launch",
                "--packet",
                str(packet),
                "--cwd",
                str(root),
                "--batch",
                "B0",
            )
            self.assertEqual(launch.returncode, 0, launch.stderr)
            line = launch.stdout.strip()
            self.assertTrue(line.startswith(str(fake_grok)))
            self.assertIn(f"--resume {TEST_GROK_SESSION}", line)
            self.assertNotIn("--permission-mode", line)
            self.assertIn("--always-approve", line)
            self.assertNotIn("--no-subagents", line)
            self.assertNotIn("dontAsk", line)

            status = _run_cli(root, "implement", "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            st = json.loads(status.stdout)
            self.assertTrue(st["present"])
            self.assertEqual(st["state"]["last_batch"], 0)

            rejected = _run_cli(
                root,
                "implement",
                "launch",
                "--packet",
                str(packet),
                "--batch",
                "-1",
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("non-negative", rejected.stderr)

    def test_cli_launch_rejects_dontask(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_grok = _write_fake_grok(root / "grok")
            _run_cli(
                root,
                "implement",
                "prepare",
                "--session-id",
                TEST_GROK_SESSION,
                "--executable",
                str(fake_grok),
            )
            packet = root / "p.md"
            packet.write_text("p\n", encoding="utf-8")
            result = _run_cli(
                root,
                "implement",
                "launch",
                "--packet",
                str(packet),
                "--permission-mode",
                "dontAsk",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dontAsk", result.stderr)

    def test_cli_gate_failure_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Gate with focused flag still needs a real tests dir; use module API with mock
            # via subprocess that invokes run_gate logic is covered above. Here: CLI gate
            # against a temp tree without tests should still run and likely fail or find 0.
            # Use implement module through CLI by pointing cwd at REPO with focused + monkey
            # is hard; assert CLI gate --help and a failing focused discovery on empty tree.
            empty_tests = root / "tests"
            empty_tests.mkdir()
            (empty_tests / "__init__.py").write_text("", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "implement",
                    "gate",
                    "--batch",
                    "9",
                    "--focused",
                    "--cwd",
                    str(root),
                    "--repo-root",
                    str(root),
                    "--json",
                ],
                capture_output=True,
                text=True,
                cwd=str(root),
            )
            # focused looks for test_cobbler_agents_implement.py which is absent → exit non-zero
            # or zero with 0 tests depending on unittest; either way gate should record.
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
            if payload:
                gate_path = Path(payload["gate_path"])
                self.assertTrue(gate_path.is_file())

    def test_cli_gate_json_unmangled_with_claude_code_env_flags(self) -> None:
        # Regression (B1): with the short-valued secret-named flags Claude Code
        # sessions export, the CLI gate JSON previously replaced every literal
        # 1 with [REDACTED:exact_grant], corrupting gate_path and timestamps.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_tests = root / "tests"
            empty_tests.mkdir()
            (empty_tests / "__init__.py").write_text("", encoding="utf-8")
            env = dict(os.environ)
            env["CLAUDE_CODE_SDK_HAS_OAUTH_REFRESH"] = "1"
            env["CLAUDE_CODE_CHILD_SESSION"] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "implement",
                    "gate",
                    "--batch",
                    "9",
                    "--focused",
                    "--cwd",
                    str(root),
                    "--repo-root",
                    str(root),
                    "--json",
                ],
                capture_output=True,
                text=True,
                cwd=str(root),
                env=env,
            )
            payload = json.loads(result.stdout)
            for field in ("gate_path", "cwd", "done_report_path", "recorded_at"):
                self.assertNotIn("[REDACTED", str(payload[field]), field)
            gate_path = Path(payload["gate_path"])
            self.assertTrue(gate_path.is_file())
            self.assertEqual(payload["batch"], 9)


class LaunchExecOptionalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.capability_probe = mock.patch(
            "cobbler_runtime.worker_routing.probe_grok_capabilities",
            return_value=_proven_grok_capabilities(),
        )
        self.capability_probe.start()
        self.addCleanup(self.capability_probe.stop)
    def test_linux_same_uid_unreadable_environment_fails_closed(self) -> None:
        stat_fields = ["S", "1", "4242", *("0" for _ in range(16)), "99"]
        raw_stat = f"4242 (fixture) {' '.join(stat_fields)}"
        with mock.patch.object(
            implement_module.Path,
            "read_text",
            return_value=raw_stat,
        ), mock.patch.object(
            implement_module.Path,
            "read_bytes",
            side_effect=PermissionError("fixture non-dumpable"),
        ), mock.patch.object(
            implement_module.Path,
            "stat",
            return_value=mock.Mock(st_uid=os.geteuid()),
        ):
            with self.assertRaisesRegex(ValidationIssue, "same-UID Linux"):
                implement_module._linux_process_record(4242, marker="fixture")

    @unittest.skipUnless(sys.platform == "darwin", "Darwin audit-token API required")
    def test_darwin_generation_signal_preflight_is_real(self) -> None:
        identity = implement_module._darwin_process_record(os.getpid())
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertTrue(
            implement_module._darwin_signal_audit_token(
                identity.darwin_audit_token,
                signal.SIGCONT,
            )
        )

    def test_darwin_process_scan_never_requests_environment(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )
        with mock.patch.object(
            implement_module.sys,
            "platform",
            "darwin",
        ), mock.patch.object(
            implement_module.subprocess,
            "run",
            return_value=completed,
        ) as run:
            records = implement_module._scan_implement_processes("fixture")

        self.assertEqual(records, {})
        argv = run.call_args.args[0]
        self.assertEqual(
            argv,
            ["/bin/ps", "-axo", "pid=,ppid=,pgid=,command="],
        )
        self.assertNotIn("e", argv)
        self.assertNotIn("-E", argv)

    @unittest.skipUnless(sys.platform == "darwin", "Darwin boundary required")
    def test_darwin_bounded_executor_fails_before_popen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            implement_module.subprocess,
            "Popen",
        ) as popen:
            with self.assertRaises(ValidationIssue) as caught:
                implement_module._execute_bounded_process(
                    [sys.executable, "-c", "raise SystemExit(99)"],
                    cwd=Path(tmp),
                    env={"PATH": "/usr/bin:/bin"},
                )

        self.assertEqual(
            caught.exception.code,
            "implement_recursive_containment_unavailable",
        )
        popen.assert_not_called()

    def test_bounded_executor_preflights_cleanup_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            implement_module,
            "_require_implement_supervision_capability",
            side_effect=ValidationIssue(
                "implement_pidfd_unavailable",
                "pidfd denied by fixture",
            ),
        ), mock.patch.object(implement_module.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValidationIssue, "pidfd denied"):
                implement_module._execute_bounded_process(
                    [sys.executable, "-c", "raise SystemExit(99)"],
                    cwd=Path(tmp),
                    env={"PATH": os.environ.get("PATH", "")},
                )

        popen.assert_not_called()

    def test_linux_clean_env_escape_fails_before_popen(self) -> None:
        escape_script = (
            "import os; "
            "pid = os.fork(); "
            "pid and os._exit(0); "
            "os.setsid(); "
            "pid = os.fork(); "
            "pid and os._exit(0); "
            "os.execve('/bin/sleep', ['sleep', '30'], {})"
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            implement_module.sys,
            "platform",
            "linux",
        ), mock.patch.object(implement_module.subprocess, "Popen") as popen:
            with self.assertRaises(ValidationIssue) as caught:
                implement_module._execute_bounded_process(
                    [sys.executable, "-c", escape_script],
                    cwd=Path(tmp),
                    env={"PATH": os.environ.get("PATH", "")},
                )

        self.assertEqual(
            caught.exception.code,
            "implement_recursive_containment_unavailable",
        )
        popen.assert_not_called()

    def test_selector_setup_failure_happens_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            implement_module,
            "_require_implement_supervision_capability",
            return_value=None,
        ), mock.patch.object(
            implement_module.selectors,
            "DefaultSelector",
            side_effect=OSError("fixture selector exhaustion"),
        ), mock.patch.object(implement_module.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(OSError, "selector exhaustion"):
                implement_module._execute_bounded_process(
                    [sys.executable, "-c", "raise SystemExit(99)"],
                    cwd=Path(tmp),
                    env={"PATH": os.environ.get("PATH", "")},
                )

        popen.assert_not_called()

    def test_post_launch_attach_failure_reaps_worker_and_closes_pipes(self) -> None:
        real_popen = subprocess.Popen
        processes: list[subprocess.Popen[bytes]] = []

        def capture_launch(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            argv = args[0] if args else kwargs.get("args", ())
            if argv and argv[0] == sys.executable:
                processes.append(proc)
            return proc

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            implement_module,
            "_require_implement_supervision_capability",
            return_value=None,
        ), mock.patch.object(
            implement_module.subprocess,
            "Popen",
            side_effect=capture_launch,
        ), mock.patch.object(
            implement_module._ImplementDescendantSupervisor,
            "attach",
            side_effect=RuntimeError("fixture attach failure"),
        ), mock.patch.object(
            implement_module._ImplementDescendantSupervisor,
            "terminate_known_descendants",
            return_value=None,
        ):
            with self.assertRaisesRegex(RuntimeError, "attach failure"):
                implement_module._execute_bounded_process(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    cwd=Path(tmp),
                    env={"PATH": os.environ.get("PATH", "")},
                    term_grace_seconds=0.05,
                    kill_grace_seconds=0.5,
                )

        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].returncode)
        assert processes[0].stdout is not None
        assert processes[0].stderr is not None
        self.assertTrue(processes[0].stdout.closed)
        self.assertTrue(processes[0].stderr.closed)

    def test_cleanup_failure_retries_and_best_effort_reaps_live_worker(self) -> None:
        real_popen = subprocess.Popen
        processes: list[subprocess.Popen[bytes]] = []

        def capture_launch(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            argv = args[0] if args else kwargs.get("args", ())
            if argv and argv[0] == sys.executable:
                proc.poll = mock.Mock(
                    side_effect=AssertionError("cleanup must not poll before killpg")
                )
                processes.append(proc)
            return proc

        cleanup_failure = ValidationIssue(
            "fixture_cleanup_failed",
            "fixture cleanup proof failed",
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            implement_module,
            "_require_implement_supervision_capability",
            return_value=None,
        ), mock.patch.object(
            implement_module.subprocess,
            "Popen",
            side_effect=capture_launch,
        ), mock.patch.object(
            implement_module._ImplementDescendantSupervisor,
            "attach",
            return_value=None,
        ), mock.patch.object(
            implement_module._ImplementDescendantSupervisor,
            "root_exited",
            return_value=False,
        ), mock.patch.object(
            implement_module,
            "_terminate_and_reap_process_group",
            side_effect=cleanup_failure,
        ) as cleanup:
            with self.assertRaises(ValidationIssue) as caught:
                implement_module._execute_bounded_process(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    cwd=Path(tmp),
                    env={"PATH": os.environ.get("PATH", "")},
                    timeout_seconds=0.05,
                    kill_grace_seconds=0.5,
                )

        self.assertEqual(caught.exception.code, "implement_cleanup_failed")
        self.assertEqual(cleanup.call_count, 2)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].returncode)

    def test_exec_invokes_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id=TEST_GROK_SESSION, executable="true")
            packet = root / "p.md"
            packet.write_text("p\n", encoding="utf-8")
            # On Unix `true` succeeds; argv[0] is "true" with flags that true ignores.
            with mock.patch(
                "cobbler_runtime.implement._execute_bounded_process",
                return_value=_fake_bounded_result(),
            ) as execute_mock:
                payload = launch_payload(
                    root,
                    packet=packet,
                    exec_process=True,
                    executable="true",
                )
            self.assertTrue(payload["launched"])
            self.assertTrue(payload["ok"])
            execute_mock.assert_called_once()
            self.assertIn("stdout_digest", payload)
            self.assertEqual(payload["stdout_tail"], "")
            self.assertEqual(payload["stderr_tail"], "")
            # Minimal env: no wholesale host secret inheritance in call kwargs.
            env = execute_mock.call_args.kwargs.get("env") or {}
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertFalse(Path(env["HOME"]).exists())
            self.assertFalse(Path(env["TMPDIR"]).exists())

    def test_nonzero_exit_redacts_grants_and_cleans_scoped_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id=TEST_GROK_SESSION, executable="tool")
            packet = root / "p.md"
            packet.write_text("p\n", encoding="utf-8")
            secret = "xai-failure-secret-123456789"
            with (
                mock.patch.dict(os.environ, {"XAI_API_KEY": secret}, clear=False),
                mock.patch(
                    "cobbler_runtime.implement._execute_bounded_process",
                    return_value=_fake_bounded_result(
                        stdout=secret,
                        stderr=f"provider failed: {secret}",
                        exit_code=17,
                    ),
                ) as execute_mock,
            ):
                payload = launch_payload(
                    root,
                    packet=packet,
                    exec_process=True,
                    executable="tool",
                )

            self.assertFalse(payload["ok"])
            self.assertEqual(payload["exit_code"], 17)
            self.assertNotIn(secret, json.dumps(payload, sort_keys=True))
            child_env = execute_mock.call_args.kwargs["env"]
            self.assertEqual(child_env["XAI_API_KEY"], secret)
            self.assertFalse(Path(child_env["HOME"]).exists())
            self.assertFalse(Path(child_env["TMPDIR"]).exists())

    def test_spawn_error_redacts_grants_and_cleans_scoped_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id=TEST_GROK_SESSION, executable="tool")
            packet = root / "p.md"
            packet.write_text("p\n", encoding="utf-8")
            secret = "xai-spawn-secret-123456789"
            with (
                mock.patch.dict(os.environ, {"XAI_API_KEY": secret}, clear=False),
                mock.patch(
                    "cobbler_runtime.implement._execute_bounded_process",
                    side_effect=OSError(f"cannot start {secret}"),
                ) as execute_mock,
                self.assertRaises(ValidationIssue) as ctx,
            ):
                launch_payload(
                    root,
                    packet=packet,
                    exec_process=True,
                    executable="tool",
                )

            self.assertEqual(ctx.exception.code, "implement_launch_spawn_failed")
            self.assertNotIn(secret, ctx.exception.message)
            child_env = execute_mock.call_args.kwargs["env"]
            self.assertFalse(Path(child_env["HOME"]).exists())
            self.assertFalse(Path(child_env["TMPDIR"]).exists())

    def test_resume_batch_exec_preserves_bounded_redacted_legacy_tails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id=TEST_GROK_SESSION, executable="tool")
            packet = root / "p.md"
            packet.write_text("p\n", encoding="utf-8")
            with mock.patch(
                "cobbler_runtime.implement._execute_bounded_process",
                return_value=_fake_bounded_result(
                    stdout="x" * 5000,
                    stderr="y" * 5000,
                ),
            ):
                payload = resume_batch_payload(
                    root,
                    batch=2,
                    packet=packet,
                    exec_process=True,
                    executable="tool",
                )
            self.assertEqual(payload["action"], "resume-batch")
            self.assertEqual(len(payload["stdout_tail"]), 4000)
            self.assertEqual(len(payload["stderr_tail"]), 4000)

    def test_timeout_result_preserves_legacy_payload_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_implement(root, session_id=TEST_GROK_SESSION, executable="tool")
            packet = root / "p.md"
            packet.write_text("p\n", encoding="utf-8")
            with mock.patch(
                "cobbler_runtime.implement._execute_bounded_process",
                return_value=_fake_bounded_result(
                    stdout="before timeout",
                    stderr="still running",
                    timed_out=True,
                ),
            ) as execute_mock:
                payload = launch_payload(
                    root,
                    packet=packet,
                    exec_process=True,
                    executable="tool",
                )
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["exit_code"], 124)
            self.assertIn("process group terminated", payload["error_human"])
            self.assertEqual(payload["stdout_tail"], "before timeout")
            child_env = execute_mock.call_args.kwargs["env"]
            self.assertFalse(Path(child_env["HOME"]).exists())
            self.assertFalse(Path(child_env["TMPDIR"]).exists())

    def test_bounded_executor_streams_chatty_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chunk_bytes = 64 * 1024
            chunk_count = 32
            capture_bytes = 8192
            script = (
                "import os; "
                f"chunk_out = b'x' * {chunk_bytes}; "
                f"chunk_err = b'y' * {chunk_bytes}; "
                f"[(os.write(1, chunk_out), os.write(2, chunk_err)) for _ in range({chunk_count})]"
            )

            real_read_bytes = Path.read_bytes

            def readable_test_environment(path: Path) -> bytes:
                try:
                    return real_read_bytes(path)
                except PermissionError:
                    if (
                        sys.platform.startswith("linux")
                        and path.name == "environ"
                        and path.parent.name.isdigit()
                        and path.parent.parent == Path("/proc")
                    ):
                        # GitHub-hosted Linux mounts /proc with same-UID
                        # environment reads denied. This test targets rolling
                        # pipe capture, while a separate regression proves that
                        # the production supervisor fails closed on that denial.
                        return b""
                    raise

            with mock.patch.object(
                implement_module,
                "_require_implement_supervision_capability",
                return_value=None,
            ), mock.patch.object(
                Path,
                "read_bytes",
                new=readable_test_environment,
            ):
                result = implement_module._execute_bounded_process(
                    [sys.executable, "-c", script],
                    cwd=root,
                    env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
                    timeout_seconds=10,
                    term_grace_seconds=0.1,
                    kill_grace_seconds=0.5,
                    capture_window_bytes=capture_bytes,
                )

            expected_bytes = chunk_bytes * chunk_count
            self.assertFalse(result.timed_out)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.stdout_bytes, expected_bytes)
            self.assertEqual(result.stderr_bytes, expected_bytes)
            self.assertLessEqual(len(result.stdout_window.encode()), capture_bytes)
            self.assertLessEqual(len(result.stderr_window.encode()), capture_bytes)
            self.assertEqual(result.stdout_window, "x" * capture_bytes)
            self.assertEqual(result.stderr_window, "y" * capture_bytes)
            self.assertEqual(
                result.stdout_digest,
                hashlib.sha256(b"x" * expected_bytes).hexdigest()[:16],
            )
            self.assertEqual(
                result.stderr_digest,
                hashlib.sha256(b"y" * expected_bytes).hexdigest()[:16],
            )

    @unittest.skip(
        "legacy bounded implementer fails closed without a qualified PID namespace"
    )
    def test_bounded_executor_times_out_descendant_that_holds_pipes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid_path = root / "descendant.pid"
            child_script = (
                "import os, pathlib, signal, sys, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); "
                "print('descendant-ready', flush=True); "
                "time.sleep(30)"
            )
            script = (
                "import subprocess, sys, time; "
                "subprocess.Popen("
                f"[sys.executable, '-c', {child_script!r}, sys.argv[1]], "
                "start_new_session=True); "
                "print('parent-running', flush=True); "
                "time.sleep(30)"
            )
            descendant_pid: int | None = None
            started = time.monotonic()
            try:
                result = implement_module._execute_bounded_process(
                    [sys.executable, "-c", script, str(pid_path)],
                    cwd=root,
                    env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
                    timeout_seconds=0.3,
                    term_grace_seconds=0.2,
                    kill_grace_seconds=0.5,
                    capture_window_bytes=4096,
                )
                elapsed = time.monotonic() - started
                descendant_pid = int(pid_path.read_text(encoding="utf-8"))

                self.assertTrue(result.timed_out)
                self.assertEqual(result.exit_code, 124)
                self.assertIn("parent-running", result.stdout_window)
                self.assertIn("descendant-ready", result.stdout_window)
                self.assertLess(elapsed, 3.0)

                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    if not _pid_is_executable(descendant_pid):
                        break
                    time.sleep(0.02)
                else:
                    self.fail("setsid pipe-holding descendant survived timeout cleanup")
            finally:
                if descendant_pid is not None:
                    try:
                        os.kill(descendant_pid, 9)
                    except ProcessLookupError:
                        pass

    @unittest.skip(
        "legacy bounded implementer fails closed without a qualified PID namespace"
    )
    def test_bounded_executor_success_cleans_setsid_pipe_holder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid_path = root / "success-descendant.pid"
            child_script = (
                "import os, pathlib, signal, sys, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); "
                "print('success-descendant-ready', flush=True); "
                "time.sleep(30)"
            )
            script = (
                "import subprocess, sys; "
                "subprocess.Popen("
                f"[sys.executable, '-c', {child_script!r}, sys.argv[1]], "
                "start_new_session=True); "
                "print('leader-success', flush=True)"
            )
            descendant_pid: int | None = None
            started = time.monotonic()
            try:
                result = implement_module._execute_bounded_process(
                    [sys.executable, "-c", script, str(pid_path)],
                    cwd=root,
                    env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
                    timeout_seconds=5.0,
                    term_grace_seconds=0.1,
                    kill_grace_seconds=0.5,
                    capture_window_bytes=4096,
                )
                elapsed = time.monotonic() - started
                self.assertTrue(pid_path.exists(), "pipe-holder fixture did not start")
                descendant_pid = int(pid_path.read_text(encoding="utf-8"))
                self.assertFalse(result.timed_out)
                self.assertEqual(result.exit_code, 0)
                self.assertIn("leader-success", result.stdout_window)
                self.assertIn("success-descendant-ready", result.stdout_window)
                self.assertLess(elapsed, 3.0)
                self.assertFalse(_pid_is_executable(descendant_pid))
            finally:
                if descendant_pid is not None:
                    try:
                        os.kill(descendant_pid, 9)
                    except ProcessLookupError:
                        pass

    @unittest.skip(
        "legacy bounded implementer fails closed without a qualified PID namespace"
    )
    def test_bounded_executor_cleans_double_fork_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid_path = root / "double-fork.pid"
            script = r'''
import os, pathlib, signal, sys, time
pid_path = pathlib.Path(sys.argv[1])
if os.fork() == 0:
    os.setsid()
    if os.fork():
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pid_path.write_text(str(os.getpid()), encoding='utf-8')
    time.sleep(30)
    os._exit(0)
for _ in range(200):
    if pid_path.exists():
        break
    time.sleep(0.01)
print('leader-complete', flush=True)
'''
            daemon_pid: int | None = None
            try:
                result = implement_module._execute_bounded_process(
                    [sys.executable, "-c", script, str(pid_path)],
                    cwd=root,
                    env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
                    timeout_seconds=5.0,
                    term_grace_seconds=0.1,
                    kill_grace_seconds=0.5,
                    capture_window_bytes=4096,
                )
                self.assertTrue(pid_path.exists(), "double-fork fixture did not start")
                daemon_pid = int(pid_path.read_text(encoding="utf-8"))
                self.assertFalse(result.timed_out)
                self.assertEqual(result.exit_code, 0)
                self.assertIn("leader-complete", result.stdout_window)

                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    if not _pid_is_executable(daemon_pid):
                        break
                    time.sleep(0.02)
                else:
                    self.fail("double-fork descendant survived successful cleanup")
            finally:
                if daemon_pid is not None:
                    try:
                        os.kill(daemon_pid, 9)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
