"""Host-profile registry: byte-identical native argv, grok arm, gated routing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime import native_worker  # noqa: E402
from cobbler_runtime.native_worker import (  # noqa: E402
    build_native_worker_spec,
    native_worker_profiles,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402

CLI = SCRIPTS / "cobbler_agents.py"


def _standalone_repo(root: Path) -> Path:
    """A standalone checkout: no external git write roots, deterministic argv."""
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "codex/task", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Elves Test"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "elves@example.invalid"], check=True
    )
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "base.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    return repo


class NativeArgvByteIdentityTests(unittest.TestCase):
    """B2-A1: codex/claude/fixture argv stays byte-identical through the registry."""

    def test_native_claude_worker_rejects_sakana_endpoint_and_fugu_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            with mock.patch.dict(
                os.environ,
                {"ANTHROPIC_BASE_URL": "https://api.sakana.ai"},
            ):
                with self.assertRaises(ValidationIssue) as endpoint:
                    build_native_worker_spec(
                        host="claude",
                        worktree=repo,
                        effort="high",
                        requested_model="current-model",
                    )
            self.assertEqual(
                endpoint.exception.code,
                "fugu_implementation_route_blocked",
            )
            with self.assertRaises(ValidationIssue) as model:
                build_native_worker_spec(
                    host="claude",
                    worktree=repo,
                    effort="high",
                    requested_model="fugu[1m]",
                )
            self.assertEqual(
                model.exception.code,
                "fugu_implementation_route_blocked",
            )

    def test_codex_create_and_resume_argv_exact_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            cwd = str(repo.resolve())
            created = build_native_worker_spec(
                host="codex", worktree=repo, effort="medium", requested_model="current-model"
            )
            self.assertEqual(
                created.argv,
                (
                    "codex", "exec", "--json", "--ignore-user-config", "--ignore-rules",
                    "--sandbox", "workspace-write", "-c", 'model_reasoning_effort="medium"',
                    "--model", "current-model", "-C", cwd, "-",
                ),
            )
            self.assertIsNone(created.resume_argv)
            self.assertIsNone(created.session_id)
            self.assertEqual(created.session_id_source, "thread.started.thread_id")
            self.assertEqual(created.commit_mode, "sandboxed_worker_commit")
            self.assertEqual(created.profile, "elves-native-worker")
            self.assertTrue(created.stdin_packet)
            resumed = build_native_worker_spec(
                host="codex",
                worktree=repo,
                effort="low",
                requested_model="current-model",
                session_id="thread-exact-1",
            )
            self.assertEqual(
                resumed.argv,
                (
                    "codex", "exec", "--json", "--ignore-user-config", "--ignore-rules",
                    "--sandbox", "workspace-write", "-c", 'model_reasoning_effort="low"',
                    "--model", "current-model", "resume", "thread-exact-1", "-",
                ),
            )
            self.assertEqual(resumed.resume_argv, resumed.argv)
            self.assertEqual(resumed.session_id, "thread-exact-1")

    def test_claude_create_and_resume_argv_exact_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            created = build_native_worker_spec(
                host="claude", worktree=repo, effort="high", requested_model="current-model"
            )
            sid = created.session_id
            self.assertIsNotNone(sid)
            self.assertEqual(str(uuid.UUID(str(sid))), sid)
            self.assertEqual(
                created.argv,
                (
                    "claude", "--safe-mode", "--print", "--verbose",
                    "--output-format", "stream-json", "--input-format", "text",
                    "--effort", "high", "--permission-mode", "auto",
                    "--model", "current-model", "--session-id", str(sid),
                ),
            )
            self.assertIsNone(created.resume_argv)
            self.assertEqual(created.host, "claude-code")
            self.assertEqual(created.session_id_source, "requested_session_id")
            self.assertEqual(created.commit_mode, "classifier_approved_worker_commit")
            resumed = build_native_worker_spec(
                host="claude",
                worktree=repo,
                effort="low",
                requested_model="current-model",
                session_id=str(sid),
            )
            self.assertEqual(
                resumed.argv,
                (
                    "claude", "--safe-mode", "--print", "--verbose",
                    "--output-format", "stream-json", "--input-format", "text",
                    "--effort", "low", "--permission-mode", "auto",
                    "--model", "current-model", "--resume", str(sid),
                ),
            )
            self.assertEqual(resumed.resume_argv, resumed.argv)

    def test_fixture_argv_and_identity_exact_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            script = Path(tmp) / "fixture.py"
            script.write_text("print('ok')\n", encoding="utf-8")
            spec = build_native_worker_spec(
                host="fixture",
                worktree=repo,
                effort="medium",
                requested_model="current-model",
                fixture_script=script,
            )
            self.assertEqual(spec.argv, (sys.executable, str(script.resolve())))
            self.assertEqual(spec.profile, "elves-native-worker-fixture")
            self.assertEqual(spec.session_id_source, "fixture_session_id")
            self.assertEqual(spec.commit_mode, "fixture")
            self.assertTrue(str(spec.session_id).startswith("fixture-"))
            self.assertEqual(spec.git_write_roots, ())
            with self.assertRaises(ValidationIssue) as caught:
                build_native_worker_spec(
                    host="fixture", worktree=repo, effort="medium", requested_model="m"
                )
            self.assertEqual(caught.exception.code, "fixture_script_required")

    def test_unknown_host_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            with self.assertRaises(ValidationIssue) as caught:
                build_native_worker_spec(
                    host="devin", worktree=repo, effort="medium", requested_model="m"
                )
            self.assertEqual(caught.exception.code, "unsupported_host")

    def test_profile_view_keeps_codex_and_claude_semantics(self) -> None:
        profiles = native_worker_profiles()
        for host, transport, identity, commit_mode in (
            ("codex", "codex_exec", "thread.started.thread_id", "sandboxed_worker_commit"),
            ("claude", "claude_code", "caller-assigned UUID", "classifier_approved_worker_commit"),
        ):
            entry = profiles[host]
            self.assertEqual(entry["transport"], transport)
            self.assertEqual(entry["session_identity"], identity)
            self.assertEqual(entry["commit_mode"], commit_mode)
            self.assertEqual(entry["model_policy"], "inherit_live_driver_model")
            self.assertTrue(entry["separate_session"])
            self.assertFalse(entry["worker_merge_authority"])
            self.assertFalse(entry["visibility_ready"])
            self.assertFalse(entry["cache_handoff"])


class GrokHostArmTests(unittest.TestCase):
    """B2-A2/B2-A4: feature-gated grok host row — exact argv, narrow env."""

    def test_grok_create_argv_exact_with_preset_uuid_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            cwd = str(repo.resolve())
            spec = build_native_worker_spec(
                host="grok", worktree=repo, effort="medium", requested_model="grok-4.5"
            )
            sid = spec.session_id
            self.assertIsNotNone(sid)
            # Caller-generated UUID identity recorded on the spec before launch.
            self.assertEqual(str(uuid.UUID(str(sid))), sid)
            self.assertEqual(
                spec.argv,
                (
                    "grok", "--session-id", str(sid), "--cwd", cwd,
                    "--model", "grok-4.5", "--effort", "medium",
                    "--permission-mode", "auto",
                    "--output-format", "streaming-json",
                ),
            )
            for forbidden in ("--always-approve", "--yolo", "dontAsk"):
                self.assertNotIn(forbidden, spec.argv)
            self.assertEqual(spec.argv[spec.argv.index("--permission-mode") + 1], "auto")
            self.assertIsNone(spec.resume_argv)
            self.assertEqual(spec.host, "grok")
            self.assertEqual(spec.session_id_source, "requested_session_id")
            self.assertEqual(spec.commit_mode, "permission_gated_worker_commit")
            # Packet travels on the same prompt-file surface implement.py uses.
            self.assertFalse(spec.stdin_packet)
            self.assertEqual(spec.prompt_file_flag, "--prompt-file")

    def test_grok_resume_argv_exact_with_execution_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            sid = "11111111-2222-3333-4444-555555555555"
            spec = build_native_worker_spec(
                host="grok",
                worktree=repo,
                effort="low",
                requested_model="grok-4.5",
                session_id=sid,
            )
            self.assertEqual(
                spec.argv,
                (
                    "grok", "--resume", sid,
                    "--model", "grok-4.5", "--effort", "low",
                    "--permission-mode", "auto",
                    "--output-format", "streaming-json",
                ),
            )
            self.assertEqual(spec.resume_argv, spec.argv)
            for forbidden in ("--always-approve", "--yolo", "dontAsk"):
                self.assertNotIn(forbidden, spec.argv)
            with self.assertRaises(ValidationIssue):
                build_native_worker_spec(
                    host="grok",
                    worktree=repo,
                    effort="low",
                    requested_model="grok-4.5",
                    session_id="continue",
                )

    def test_grok_child_env_allowlists_only_documented_auth_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            runtime = Path(tmp) / "runtime"
            overlay = {
                "XAI_API_KEY": "xai-secret-value-1234",
                "GROK_AUTH_PATH": str(Path(tmp) / "auth.json"),
                "ARBITRARY_API_KEY": "must-not-cross-1234",
                "OTHER_SECRET_TOKEN": "must-not-cross-5678",
                "GH_TOKEN": "gh-must-not-cross",
                "ANTHROPIC_API_KEY": "anthropic-not-for-grok",
            }
            with mock.patch.dict(os.environ, overlay, clear=False):
                env = native_worker._native_worker_child_env(
                    host="grok", worktree=repo, runtime_dir=runtime
                )
            self.assertEqual(env.get("XAI_API_KEY"), "xai-secret-value-1234")
            # GROK_AUTH_PATH is a host-owned isolation control; only the
            # provider_auth-validated projection (trusted full-run lane) may
            # set it, so the plain allowlist must never pass it through.
            self.assertNotIn("GROK_AUTH_PATH", env)
            self.assertNotIn("ARBITRARY_API_KEY", env)
            self.assertNotIn("OTHER_SECRET_TOKEN", env)
            self.assertNotIn("GH_TOKEN", env)
            self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_native_hosts_never_receive_grok_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            runtime = Path(tmp) / "runtime"
            overlay = {"XAI_API_KEY": "xai-secret-value-1234"}
            with mock.patch.dict(os.environ, overlay, clear=False):
                for host in ("codex", "claude-code"):
                    env = native_worker._native_worker_child_env(
                        host=host, worktree=repo, runtime_dir=runtime
                    )
                    self.assertNotIn("XAI_API_KEY", env, host)

    def test_identity_events_are_host_scoped(self) -> None:
        sid = "11111111-2222-3333-4444-555555555555"
        end_line = json.dumps({"type": "end", "sessionId": sid})
        self.assertEqual(native_worker._provider_session_id(end_line, host="grok"), sid)
        self.assertIsNone(native_worker._provider_session_id(end_line, host="codex"))
        self.assertIsNone(native_worker._provider_session_id(end_line, host="claude"))
        thread_line = json.dumps({"type": "thread.started", "thread_id": "thread-1"})
        self.assertIsNone(native_worker._provider_session_id(thread_line, host="grok"))
        self.assertEqual(
            native_worker._provider_session_id(thread_line, host="codex"), "thread-1"
        )
        log_line = json.dumps({"type": "log", "session_id": sid})
        for host in (None, "grok", "codex", "claude", "fixture"):
            self.assertIsNone(native_worker._provider_session_id(log_line, host=host))

    def test_grok_advertised_grammar_from_recorded_help_fixture(self) -> None:
        from cobbler_runtime.prewalk import advertised_prewalk_capabilities

        help_text = (REPO_ROOT / "tests" / "fixtures" / "grok-0.2.93-help.txt").read_text()
        capabilities = advertised_prewalk_capabilities(
            host="grok", version="0.2.93", create_help=help_text, resume_help=help_text
        )
        self.assertEqual(capabilities.host, "grok")
        self.assertEqual(capabilities.transport, "grok_build")
        self.assertTrue(capabilities.advertised_exact_resume)
        self.assertTrue(capabilities.advertised_route_override_on_resume)
        self.assertFalse(capabilities.behaviorally_verified_session_continuity)
        self.assertFalse(capabilities.qualified())
        self.assertEqual(capabilities.instruction_fidelity, "unsupported")
        self.assertFalse(capabilities.model_calls_made)

    def test_profile_view_gates_grok_launch_and_names_transport(self) -> None:
        profiles = native_worker_profiles()
        grok = profiles["grok"]
        self.assertEqual(grok["transport"], "grok_build")
        self.assertEqual(grok["session_identity"], "caller-assigned UUID")
        self.assertEqual(grok["commit_mode"], "permission_gated_worker_commit")
        self.assertFalse(grok["launch_ready"])
        self.assertTrue(profiles["codex"]["launch_ready"])
        self.assertTrue(profiles["claude"]["launch_ready"])

    def test_grok_launch_plan_is_prompt_file_non_yolo_and_api_key_only(self) -> None:
        """#95: materialize packet via --prompt-file; never yolo/always-approve."""
        from cobbler_runtime.host_profiles import (  # noqa: PLC0415
            HostLaunchRequest,
            resolve_host_profile,
        )

        profile = resolve_host_profile("grok")
        self.assertFalse(profile.launch_ready)
        self.assertEqual(profile.provider_secret_names, frozenset({"XAI_API_KEY"}))
        create = profile.launch_plan(
            HostLaunchRequest(
                effort="high",
                requested_model="grok-4.5",
                cwd="/tmp/worktree",
                git_write_roots=(),
                session_id=None,
                fixture_script=None,
            )
        )
        self.assertEqual(create.prompt_file_flag, "--prompt-file")
        self.assertFalse(create.stdin_packet)
        argv = " ".join(create.argv)
        self.assertIn("--permission-mode auto", argv)
        self.assertNotIn("--yolo", argv)
        self.assertNotIn("--always-approve", argv)
        self.assertNotIn("dontAsk", argv)
        resume = profile.launch_plan(
            HostLaunchRequest(
                effort="high",
                requested_model="grok-4.5",
                cwd="/tmp/worktree",
                git_write_roots=(),
                session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                fixture_script=None,
            )
        )
        self.assertIn("--resume", resume.argv)
        self.assertEqual(resume.prompt_file_flag, "--prompt-file")
        # Qualification artifacts never flip the host-level launch_ready gate.
        self.assertFalse(resolve_host_profile("grok").launch_ready)


class GrokNativeWorkerCliTests(unittest.TestCase):
    """B2-A2 (CLI surface): spec works for grok; launch fails closed."""

    def _cli(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI), *argv],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(REPO_ROOT),
        )

    def test_spec_host_grok_emits_exact_argv_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            result = self._cli(
                "native-worker", "spec",
                "--host", "grok",
                "--worktree", str(repo),
                "--effort", "medium",
                "--model", "grok-4.5",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            worker = payload["worker"]
            sid = worker["session_id"]
            self.assertEqual(str(uuid.UUID(sid)), sid)
            self.assertEqual(
                worker["argv"],
                [
                    "grok", "--session-id", sid, "--cwd", str(repo.resolve()),
                    "--model", "grok-4.5", "--effort", "medium",
                    "--permission-mode", "auto",
                    "--output-format", "streaming-json",
                ],
            )
            self.assertIn("grok", payload["profiles"])
            self.assertEqual(payload["prewalk"]["actual"], "off")
            self.assertFalse(payload["model_calls_made"])

    def test_launch_host_grok_fails_closed_with_stable_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _standalone_repo(Path(tmp))
            packet = Path(tmp) / "packet.md"
            packet.write_text("task\n", encoding="utf-8")
            result = self._cli(
                "native-worker", "launch",
                "--host", "grok",
                "--worktree", str(repo),
                "--effort", "medium",
                "--model", "grok-4.5",
                "--repo-root", str(repo),
                "--run-id", "grok-gated-run",
                "--packet", str(packet),
                "--json",
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(
                payload["issues"][0]["code"], "grok_native_worker_launch_unqualified"
            )
            # Fails before any spec/launch work: no run state may exist.
            self.assertFalse(
                (repo / ".elves" / "runtime" / "native-worker").exists()
            )

    def test_launch_without_host_emits_arguments_envelope_not_traceback(self) -> None:
        # The launch_ready gate must not resolve a profile before the
        # required-arguments check: a missing --host keeps the clean JSON
        # envelope instead of an uncaught unsupported-host ValidationIssue.
        result = self._cli("native-worker", "launch", "--json")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["issues"][0]["code"], "native_worker_arguments_required"
        )
        self.assertNotIn("Traceback", result.stderr)

    def test_prewalk_capabilities_host_grok_is_probeable_without_model_calls(self) -> None:
        result = self._cli(
            "native-worker", "prewalk-capabilities", "--host", "grok", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        capabilities = payload["prewalk_capabilities"]
        self.assertEqual(capabilities["host"], "grok")
        self.assertEqual(capabilities["transport"], "grok_build")
        self.assertFalse(capabilities["qualified"])
        self.assertFalse(payload["model_calls_made"])


if __name__ == "__main__":
    unittest.main()
