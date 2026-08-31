"""Batch 1 runtime-hardening regression tests for the native worker.

Covers event-typed identity capture, transient-failure scoping, the shared
ambiguous-session-token set, supervisor git-timeout terminalization, torn
follow-log tolerance, stderr-tail preservation, and the prewalk failure-code
inventory (2026-07 audit follow-ups, Batch 1).
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime import adapters, implement, native_worker, schema  # noqa: E402
from cobbler_runtime.prewalk import PREWALK_FAILURE_CODES  # noqa: E402
from cobbler_runtime.schema import ValidationIssue  # noqa: E402


def _phase_worker(
    tmp: Path,
    *,
    script_body: str,
    preset_session_id: str | None = None,
) -> tuple[dict[str, object], native_worker._PhaseResult]:
    """Run one _run_worker_phase against a tiny deterministic child script."""
    script = tmp / "child.py"
    script.write_text(textwrap.dedent(script_body), encoding="utf-8")
    state_path, log_path = native_worker.native_worker_paths(tmp, "hardening-run")
    state: dict[str, object] = {
        "run_id": "hardening-run",
        "worktree": str(tmp),
        "status": "launching",
        "session_id": preset_session_id,
        "provider_event_count": 0,
        "stderr_tail": None,
    }
    native_worker._write_private_json(state_path, state)
    import os

    result = native_worker._run_worker_phase(
        state_path=state_path,
        log_path=log_path,
        state=state,
        phase="execution",
        argv=(sys.executable, str(script)),
        input_text="",
        child_env=dict(os.environ),
        expected_session_id=preset_session_id,
    )
    return state, result


class ProviderIdentityEventTypingTests(unittest.TestCase):
    """B1-A2: identity binds only from documented identity event types."""

    def test_log_event_with_session_id_key_is_not_identity(self) -> None:
        line = json.dumps({"type": "log", "session_id": "11111111-2222-3333-4444-555555555555"})
        self.assertIsNone(native_worker._provider_session_id(line))

    def test_untyped_and_unknown_typed_lines_are_not_identity(self) -> None:
        for payload in (
            {"session_id": "abc-123"},
            {"type": "message", "sessionId": "abc-123"},
            {"type": "item.completed", "thread_id": "abc-123"},
            {"type": "system", "subtype": "status", "session_id": "abc-123"},
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(native_worker._provider_session_id(json.dumps(payload)))

    def test_codex_thread_started_still_binds(self) -> None:
        line = json.dumps({"type": "thread.started", "thread_id": "thread-1"})
        self.assertEqual(native_worker._provider_session_id(line), "thread-1")

    def test_claude_system_init_still_confirms_identity(self) -> None:
        line = json.dumps({"type": "system", "subtype": "init", "session_id": "claude-uuid-1"})
        self.assertEqual(native_worker._provider_session_id(line), "claude-uuid-1")

    def test_turn_events_still_carry_continuity_identity(self) -> None:
        line = json.dumps({"type": "turn.started", "session_id": "different-session"})
        self.assertEqual(native_worker._provider_session_id(line), "different-session")

    def test_foreign_log_session_id_neither_binds_nor_mismatches_in_phase(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state, result = _phase_worker(
                Path(raw),
                script_body="""
                import json
                print(json.dumps({"type": "log", "session_id": "99999999-9999-9999-9999-999999999999"}), flush=True)
                """,
            )
        self.assertFalse(result.session_mismatch)
        self.assertEqual(result.observed_session_ids, ())
        self.assertIsNone(state["session_id"])
        self.assertEqual(result.provider_event_count, 1)

    def test_foreign_log_session_id_does_not_mismatch_preset_claude_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state, result = _phase_worker(
                Path(raw),
                preset_session_id="caller-preset-uuid",
                script_body="""
                import json
                print(json.dumps({"type": "log", "session_id": "foreign-uuid"}), flush=True)
                print(json.dumps({"type": "system", "subtype": "init", "session_id": "caller-preset-uuid"}), flush=True)
                """,
            )
        self.assertFalse(result.session_mismatch)
        self.assertEqual(result.observed_session_ids, ("caller-preset-uuid",))
        self.assertEqual(state["session_id"], "caller-preset-uuid")

    def test_codex_binding_from_stream_still_works_in_phase(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state, result = _phase_worker(
                Path(raw),
                script_body="""
                import json
                print(json.dumps({"type": "thread.started", "thread_id": "bound-thread"}), flush=True)
                """,
            )
        self.assertEqual(state["session_id"], "bound-thread")
        self.assertFalse(result.session_mismatch)

    def test_turn_event_with_foreign_identity_still_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _state, result = _phase_worker(
                Path(raw),
                preset_session_id="exact-session",
                script_body="""
                import json
                print(json.dumps({"type": "turn.started", "session_id": "different-session"}), flush=True)
                """,
            )
        self.assertTrue(result.session_mismatch)


class TransientFailureScopingTests(unittest.TestCase):
    """B1-A3: transient markers apply to stderr and provider error events only."""

    def test_stdout_task_text_with_timeout_word_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _state, result = _phase_worker(
                Path(raw),
                script_body="""
                print("investigating the request timeout bug in task code", flush=True)
                raise SystemExit(7)
                """,
            )
        self.assertEqual(result.exit_code, 7)
        self.assertFalse(result.transient_transport_failure)

    def test_stderr_transport_failure_is_still_transient(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _state, result = _phase_worker(
                Path(raw),
                script_body="""
                import sys
                print("provider overloaded: 503 temporarily unavailable", file=sys.stderr, flush=True)
                raise SystemExit(7)
                """,
            )
        self.assertTrue(result.transient_transport_failure)

    def test_provider_error_event_is_still_transient(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _state, result = _phase_worker(
                Path(raw),
                script_body="""
                import json
                print(json.dumps({"type": "error", "message": "429 too many requests"}), flush=True)
                raise SystemExit(7)
                """,
            )
        self.assertTrue(result.transient_transport_failure)

    def test_non_error_provider_event_with_marker_text_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _state, result = _phase_worker(
                Path(raw),
                script_body="""
                import json
                print(json.dumps({"type": "log", "message": "user asked about rate limit handling"}), flush=True)
                raise SystemExit(7)
                """,
            )
        self.assertFalse(result.transient_transport_failure)


class SharedAmbiguousSessionTokenTests(unittest.TestCase):
    """B1-A4: one canonical forbidden set shared by every session validator."""

    def test_canonical_set_contains_required_tokens(self) -> None:
        self.assertLessEqual(
            {"latest", "last", "continue", "most-recent", "most_recent"},
            schema.AMBIGUOUS_SESSION_TOKENS,
        )

    def test_adapters_alias_is_the_shared_object(self) -> None:
        self.assertIs(adapters._AMBIGUOUS_SESSION_TOKENS, schema.AMBIGUOUS_SESSION_TOKENS)

    def test_native_worker_rejects_every_shared_token(self) -> None:
        for token in sorted(schema.AMBIGUOUS_SESSION_TOKENS):
            with self.subTest(token=token):
                with self.assertRaises(ValidationIssue) as caught:
                    native_worker._exact_session_id(token)
                self.assertEqual(caught.exception.code, "invalid_exact_session_id")
        with self.assertRaises(ValidationIssue):
            native_worker._exact_session_id("--last")

    def test_adapters_reject_every_shared_token(self) -> None:
        for token in sorted(schema.AMBIGUOUS_SESSION_TOKENS):
            with self.subTest(token=token):
                with self.assertRaises(ValidationIssue) as caught:
                    adapters.assert_exact_session_id(token, adapter="grok-build")
                self.assertEqual(caught.exception.code, "ambiguous_session_id")

    def test_implement_launch_rejects_shared_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            packet = tmp / "packet.md"
            packet.write_text("packet body\n", encoding="utf-8")
            for token in ("continue", "most-recent", "most_recent"):
                with self.subTest(token=token):
                    with self.assertRaises(ValidationIssue) as caught:
                        implement.build_launch_argv(
                            session_id=token, packet=packet, cwd=tmp
                        )
                    self.assertEqual(caught.exception.code, "ambiguous_session_id")


class SupervisorRobustnessTests(unittest.TestCase):
    """B1-A5: hung git, torn follow lines, and stderr-tail preservation."""

    def _state_file(self, tmp: Path, state: dict[str, object]) -> Path:
        state_path, _ = native_worker.native_worker_paths(tmp, str(state["run_id"]))
        native_worker._write_private_json(state_path, state)
        return state_path

    def test_launch_revalidates_caller_constructed_spec(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            packet = tmp / "packet.md"
            packet.write_text("packet body\n", encoding="utf-8")
            spec = native_worker.NativeWorkerSpec(
                host="fixture",
                profile="fixture",
                effort="low",
                model_policy="exact",
                requested_model="fixture-model",
                separate_session=True,
                cwd=str(tmp),
                argv=("claude-fugu",),
                stdin_packet=True,
                session_id_source="stream",
            )
            with self.assertRaises(ValidationIssue) as caught:
                native_worker.launch_native_worker(
                    repo_root=tmp,
                    run_id="blocked-fugu",
                    spec=spec,
                    packet=packet,
                    cli_path=REPO_ROOT / "scripts" / "cobbler_agents.py",
                )
            self.assertEqual(
                caught.exception.code,
                "fugu_implementation_route_blocked",
            )

    def test_single_phase_supervisor_revalidates_persisted_argv(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            packet = tmp / "packet.md"
            packet.write_text("packet body\n", encoding="utf-8")
            state = {
                "run_id": "persisted-fugu",
                "host": "fixture",
                "worktree": str(tmp),
                "argv": ["claude-fugu"],
                "requested_model": "fixture-model",
            }
            state_path = self._state_file(tmp, state)
            _, log_path = native_worker.native_worker_paths(tmp, "persisted-fugu")
            with self.assertRaises(ValidationIssue) as caught:
                native_worker._supervise_single_phase(
                    state_path=state_path,
                    log_path=log_path,
                    state=state,
                    packet=packet,
                    child_env={},
                )
            self.assertEqual(
                caught.exception.code,
                "fugu_implementation_route_blocked",
            )

    def test_hung_git_timeout_writes_terminal_failed_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            state_path = self._state_file(
                tmp,
                {
                    "run_id": "timeout-run",
                    "host": "fixture",
                    "worktree": str(tmp),
                    "status": "running",
                    "git_authority_mode": "fixture",
                    "provider_event_count": 0,
                    "stderr_tail": None,
                    "supervisor_pid": 12345,
                },
            )
            with mock.patch.object(
                native_worker,
                "_supervise_single_phase",
                side_effect=subprocess.TimeoutExpired(cmd=["git", "status"], timeout=30),
            ):
                code = native_worker.supervise_native_worker(
                    repo_root=tmp, run_id="timeout-run", packet=state_path
                )
            self.assertEqual(code, 1)
            final = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "failed")
            self.assertEqual(final["failure_reason"], "native_worker_git_timeout")

    def test_terminalize_survives_hung_git_authority_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            state = {
                "run_id": "authority-timeout",
                "worktree": str(tmp),
                "status": "running",
                "git_authority_mode": "feature_only",
                "provider_event_count": 1,
            }
            state_path = self._state_file(tmp, state)
            with mock.patch.object(
                native_worker,
                "_verify_native_git_contract",
                side_effect=subprocess.TimeoutExpired(cmd=["git", "rev-parse"], timeout=30),
            ):
                code = native_worker._terminalize_native_worker(
                    state_path=state_path,
                    state=state,
                    worktree=tmp,
                    exit_code=0,
                )
            self.assertEqual(code, 1)
            final = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "failed")
            self.assertFalse(final["authority_verified"])
            self.assertIn("timed out", final["authority_errors"][0])

    def test_follower_skips_torn_log_lines(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            _, log_path = native_worker.native_worker_paths(tmp, "torn-run")
            log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            log_path.write_text(
                json.dumps({"stream": "stdout", "line": "first good line"})
                + "\n"
                + '{"stream": "stdout", "line": "torn but newline-terminat'
                + "\n"
                + json.dumps({"stream": "stderr", "line": "second good line"})
                + "\n"
                + '{"stream": "stdout", "line": "torn tail without newline',
                encoding="utf-8",
            )
            self._state_file(
                tmp,
                {
                    "run_id": "torn-run",
                    "status": "complete",
                    "worktree": str(tmp),
                    "follow_log": str(log_path),
                    "pid": None,
                    "pid_start": None,
                },
            )
            output = io.StringIO()
            state = native_worker.follow_native_worker(
                tmp, "torn-run", wait=False, output=output
            )
            text = output.getvalue()
            self.assertEqual(state["status"], "complete")
            self.assertIn("first good line", text)
            self.assertIn("second good line", text)
            self.assertNotIn("torn", text)

    def test_stderr_tail_survives_when_provider_events_exist(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state, result = _phase_worker(
                Path(raw),
                script_body="""
                import json, sys
                print(json.dumps({"type": "thread.started", "thread_id": "tail-thread"}), flush=True)
                print("late transport diagnostic on stderr", file=sys.stderr, flush=True)
                raise SystemExit(7)
                """,
            )
        self.assertEqual(result.exit_code, 7)
        self.assertGreaterEqual(result.provider_event_count, 1)
        self.assertIsNotNone(state["stderr_tail"])
        self.assertIn("late transport diagnostic on stderr", str(state["stderr_tail"]))


class PrewalkFailureCodeInventoryTests(unittest.TestCase):
    """B1-A6: every emitted prewalk_* failure reason is in the inventory."""

    _EMISSION_PATTERNS = (
        r'failure_reason="(prewalk_[a-z_]+)"',
        r'return "(prewalk_[a-z_]+)"',
        r'"fallback_reason": "(prewalk_[a-z_]+)"',
        r'ValidationIssue\(\s*"(prewalk_[a-z_]+)"',
        r'(?:missing_code|invalid_code)="(prewalk_[a-z_]+)"',
        r'code = "(prewalk_[a-z_]+)"',
    )

    def test_every_emitted_failure_reason_is_inventoried(self) -> None:
        emitted: set[str] = set()
        for module in ("native_worker.py", "prewalk.py"):
            source = (REPO_ROOT / "scripts" / "cobbler_runtime" / module).read_text(
                encoding="utf-8"
            )
            for pattern in self._EMISSION_PATTERNS:
                emitted.update(re.findall(pattern, source))
        self.assertGreaterEqual(len(emitted), 10, sorted(emitted))
        self.assertLessEqual(emitted, set(PREWALK_FAILURE_CODES), sorted(emitted - set(PREWALK_FAILURE_CODES)))

    def test_guide_recovery_reports_post_edit_code_when_head_moved(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": "/usr/bin:/bin"}
            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", "-C", str(tmp), *args],
                    capture_output=True, text=True, check=True, env=env,
                ).stdout.strip()

            git("init", "-q", "-b", "feature/hardening")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (tmp / "product.txt").write_text("base\n", encoding="utf-8")
            git("add", "product.txt")
            git("commit", "-qm", "base")
            start_head = git("rev-parse", "HEAD")
            (tmp / "product.txt").write_text("guide committed edit\n", encoding="utf-8")
            git("add", "product.txt")
            git("commit", "-qm", "guide edit")
            reason = native_worker._guide_recovery_failure_reason(
                {"start_head": start_head}, tmp
            )
            self.assertEqual(reason, "prewalk_post_edit_cold_fallback_forbidden")


if __name__ == "__main__":
    unittest.main()
