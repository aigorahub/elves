"""Oh My Pi (omp) main-driver host, install, and prewalk invariants."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cobbler_runtime.codex_catalog import (
    CODEX_CATALOG_ENV,
    reset_codex_model_catalog_cache,
)
from cobbler_runtime.host_profiles import (
    HostLaunchRequest,
    host_profile_or_none,
    resolve_host_profile,
)
from cobbler_runtime.adapters import build_readonly_invocation
from cobbler_runtime.native_worker import (
    _native_worker_child_env,
    _qualification_assistant_text,
    build_native_worker_spec,
    preflight_omp_provider_auth,
)
from cobbler_runtime.prewalk import (
    PREWALK_CONTINUATION_INPUT,
    advertised_prewalk_capabilities,
    load_prewalk_capability_evidence,
)
from cobbler_runtime.schema import ValidationIssue

REPO = Path(__file__).resolve().parents[1]
_BROKER_TOKEN = "broker-secret-must-not-leak"


def _omp_worktree(root: Path) -> tuple[Path, Path]:
    worktree = root / "wt"
    runtime = root / "rt"
    worktree.mkdir()
    runtime.mkdir()
    subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Elves Test"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "elves@test.invalid"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )
    return worktree, runtime


def _write_omp_broker_config(home: Path, *, url: str, token: str | None) -> None:
    agent = home / ".omp" / "agent"
    agent.mkdir(parents=True)
    token_line = f"    token: {token}\n" if token is not None else ""
    (agent / "config.yml").write_text(
        "auth:\n  broker:\n    url: " + url + "\n" + token_line,
        encoding="utf-8",
    )


class _BrokerOKHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


class OmpHostProfileTests(unittest.TestCase):
    def test_qualification_text_reassembles_omp_deltas(self) -> None:
        stdout = "\n".join(
            (
                json.dumps(
                    {
                        "type": "message_update",
                        "assistantMessageEvent": {
                            "type": "text_delta",
                            "delta": "ELVES_PREWALK_",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "message_update",
                        "assistantMessageEvent": {
                            "type": "text_delta",
                            "delta": "CANARY_GUIDE token fact",
                        },
                    }
                ),
            )
        )
        self.assertIn(
            "ELVES_PREWALK_CANARY_GUIDE token fact",
            _qualification_assistant_text(stdout),
        )

    def test_omp_resolves_and_omp_cli_is_not_host(self) -> None:
        profile = resolve_host_profile("omp")
        self.assertEqual(profile.host, "omp")
        self.assertEqual(profile.capability_host, "omp")
        self.assertTrue(profile.launch_ready)
        self.assertTrue(profile.identity_from_stream_required)
        self.assertIsNone(host_profile_or_none("omp-cli"))
        self.assertEqual(resolve_host_profile("oh-my-pi").host, "omp")

    def test_omp_launch_argv_create_and_resume(self) -> None:
        profile = resolve_host_profile("omp")
        create = profile.launch_plan(
            HostLaunchRequest(
                effort="high",
                requested_model="xai-oauth/grok-4.5",
                cwd="/tmp/worktree",
                git_write_roots=(),
                session_id=None,
                fixture_script=None,
            )
        )
        self.assertEqual(create.argv[0], "omp")
        self.assertIn("--mode", create.argv)
        self.assertIn("json", create.argv)
        self.assertIn("--cwd", create.argv)
        self.assertIn("--profile", create.argv)
        self.assertIsNone(create.prompt_file_flag)
        self.assertEqual(create.input_file_prefix, "@")
        self.assertNotIn("Follow the system packet.", create.argv)
        self.assertNotIn("--prewalk", create.argv)
        self.assertNotIn("--continue", create.argv)
        self.assertNotIn("-c", create.argv)
        self.assertIsNone(create.session_id)
        self.assertFalse(create.positional_input)
        sid = "019fe47e-339d-7000-84a0-b0553db4969e"
        resume = profile.launch_plan(
            HostLaunchRequest(
                effort="medium",
                requested_model="anthropic/claude-opus-5",
                cwd="/tmp/worktree",
                git_write_roots=(),
                session_id=sid,
                fixture_script=None,
            )
        )
        self.assertIn("--resume", resume.argv)
        self.assertIn(sid, resume.argv)
        create_profile = create.argv[create.argv.index("--profile") + 1]
        resume_profile = resume.argv[resume.argv.index("--profile") + 1]
        self.assertEqual(create_profile, resume_profile)
        self.assertTrue(resume.positional_input)
        self.assertIsNone(resume.input_file_prefix)
        self.assertIsNone(resume.prompt_file_flag)
        self.assertNotIn("Follow the system packet.", resume.argv)
        self.assertNotIn("--prewalk", resume.argv)
        self.assertNotIn("--continue", resume.argv)

    def test_build_native_worker_spec_omp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            spec = build_native_worker_spec(
                host="omp",
                worktree=repo,
                effort="high",
                requested_model="xai-oauth/grok-4.5",
            )
            self.assertEqual(spec.host, "omp")
            self.assertIn("omp", spec.argv[0])
            self.assertNotIn("--prewalk", spec.argv)
            self.assertIsNone(spec.prompt_file_flag)
            self.assertEqual(spec.input_file_prefix, "@")

    def test_omp_accepts_xhigh_and_max_without_lowering_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            for effort in ("xhigh", "max"):
                with self.subTest(effort=effort):
                    spec = build_native_worker_spec(
                        host="omp",
                        worktree=repo,
                        effort=effort,
                        requested_model="openai-codex/gpt-5.6-luna",
                    )
                    self.assertEqual(
                        spec.argv[spec.argv.index("--thinking") + 1], effort
                    )
            # Pin an unreadable Codex catalog so the offline floor is the rule
            # here on every machine, installed host or not. Catalog-derived
            # widening has its own coverage in test_adaptive_worker_routing.
            with mock.patch.dict(
                os.environ, {CODEX_CATALOG_ENV: "/nonexistent/elves-codex-catalog.json"}
            ):
                reset_codex_model_catalog_cache()
                self.addCleanup(reset_codex_model_catalog_cache)
                for other_host, model in (
                    ("grok", "grok-4.5"),
                    ("claude", "claude-opus-5"),
                    ("codex", "gpt-5.6"),
                ):
                    with self.subTest(host=other_host):
                        with self.assertRaises(ValidationIssue) as caught:
                            build_native_worker_spec(
                                host=other_host,
                                worktree=repo,
                                effort="max",
                                requested_model=model,
                            )
                        self.assertEqual(
                            caught.exception.code, "invalid_worker_effort"
                        )

    def test_omp_behavioral_evidence_accepts_xhigh_to_max_route(self) -> None:
        advertised = advertised_prewalk_capabilities(
            host="omp",
            version="17.2.15",
            create_help="--resume SESSION_ID --model --thinking",
            resume_help="--resume SESSION_ID --model --thinking",
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "omp-prewalk.json"
            payload = {
                "artifact_type": "native_prewalk_behavioral_qualification",
                "schema_version": 1,
                "host": "omp",
                "transport": "omp_build",
                "installed_version": "17.2.15",
                "session_id": "exact-omp-session",
                "create_exit_code": 0,
                "resume_exit_code": 0,
                "same_session_id": True,
                "same_worktree": True,
                "unique_guide_fact_observed": True,
                "packet_replayed": False,
                "stream_identity_verified": True,
                "instruction_fidelity": "retained_safe",
                "guide_route": {
                    "model": "openai-codex/gpt-5.6-luna",
                    "effort": "xhigh",
                },
                "execution_route": {
                    "model": "openai-codex/gpt-5.6-luna",
                    "effort": "max",
                },
                "model_calls_made": True,
                "guide_prompt_sha256": hashlib.sha256(b"guide").hexdigest(),
                "continuation_sha256": hashlib.sha256(
                    PREWALK_CONTINUATION_INPUT.encode("utf-8")
                ).hexdigest(),
            }
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            artifact.chmod(0o600)
            qualified = load_prewalk_capability_evidence(
                artifact,
                host="omp",
                installed_version="17.2.15",
                advertised=advertised,
            )
        self.assertTrue(qualified.qualified())
        self.assertTrue(
            qualified.route_matches(
                guide_model="openai-codex/gpt-5.6-luna",
                guide_effort="xhigh",
                execution_model="openai-codex/gpt-5.6-luna",
                execution_effort="max",
            )
        )

    def test_omp_child_env_projects_single_secret(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / "wt"
            runtime = Path(tmp) / "rt"
            worktree.mkdir()
            runtime.mkdir()
            subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.name", "Elves Test"],
                cwd=worktree,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "elves@test.invalid"],
                cwd=worktree,
                check=True,
                capture_output=True,
            )
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin"),
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "XAI_API_KEY": "xai-test",
                "OPENAI_API_KEY": "sk-oai",
                "GH_TOKEN": "gh-secret",
                "HOME": str(Path(tmp) / "home"),
            }
            old = os.environ.copy()
            try:
                os.environ.clear()
                os.environ.update(env)
                child = _native_worker_child_env(
                    host="omp",
                    worktree=worktree,
                    runtime_dir=runtime,
                    requested_model="xai-oauth/grok-4.5",
                )
            finally:
                os.environ.clear()
                os.environ.update(old)
            # Model-matched: xAI wins over ambient Anthropic/OpenAI keys.
            self.assertIn("XAI_API_KEY", child)
            self.assertNotIn("ANTHROPIC_API_KEY", child)
            self.assertNotIn("OPENAI_API_KEY", child)
            self.assertNotIn("GH_TOKEN", child)
            self.assertNotIn("OMP_AUTH_BROKER_URL", child)
            self.assertNotIn("OMP_AUTH_BROKER_TOKEN", child)

    def test_omp_child_env_rejects_remote_auth_broker(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / "wt"
            runtime = Path(tmp) / "rt"
            worktree.mkdir()
            runtime.mkdir()
            subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.name", "Elves Test"],
                cwd=worktree,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "elves@test.invalid"],
                cwd=worktree,
                check=True,
                capture_output=True,
            )
            old = os.environ.copy()
            try:
                os.environ.clear()
                os.environ.update(
                    {
                        "PATH": old.get("PATH", "/usr/bin"),
                        "HOME": str(Path(tmp) / "home"),
                        "OMP_AUTH_BROKER_URL": "https://broker.example.test",
                        "OMP_AUTH_BROKER_TOKEN": "broker-secret",
                    }
                )
                with self.assertRaises(ValidationIssue) as caught:
                    _native_worker_child_env(
                        host="omp",
                        worktree=worktree,
                        runtime_dir=runtime,
                        requested_model="openai-codex/gpt-5.6-luna",
                    )
            finally:
                os.environ.clear()
                os.environ.update(old)
        self.assertEqual(
            caught.exception.code, "omp_auth_broker_projection_invalid"
        )
        self.assertNotIn("broker-secret", caught.exception.message)


class OmpAuthPreflightTests(unittest.TestCase):
    def test_missing_auth_fails_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            worktree, runtime = _omp_worktree(Path(tmp))
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin"),
                "HOME": str(Path(tmp) / "home"),
            }
            old = os.environ.copy()
            try:
                os.environ.clear()
                os.environ.update(env)
                with self.assertRaises(ValidationIssue) as caught:
                    _native_worker_child_env(
                        host="omp",
                        worktree=worktree,
                        runtime_dir=runtime,
                        requested_model="openai-codex/gpt-5.6-luna",
                    )
            finally:
                os.environ.clear()
                os.environ.update(old)
        self.assertEqual(caught.exception.code, "omp_auth_preflight_missing")
        self.assertIn("omp auth-broker serve", caught.exception.message)
        self.assertNotIn(_BROKER_TOKEN, caught.exception.message)
        self.assertNotIn(_BROKER_TOKEN, json.dumps(caught.exception.to_dict()))

    def test_healthy_broker_from_persistent_settings(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _BrokerOKHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                home = root / "home"
                _write_omp_broker_config(home, url=url, token=_BROKER_TOKEN)
                worktree, runtime = _omp_worktree(root)
                env = {
                    "PATH": os.environ.get("PATH", "/usr/bin"),
                    "HOME": str(home),
                }
                old = os.environ.copy()
                try:
                    os.environ.clear()
                    os.environ.update(env)
                    child = _native_worker_child_env(
                        host="omp",
                        worktree=worktree,
                        runtime_dir=runtime,
                        requested_model="openai-codex/gpt-5.6-luna",
                    )
                finally:
                    os.environ.clear()
                    os.environ.update(old)
            self.assertEqual(child["OMP_AUTH_BROKER_URL"], url)
            self.assertEqual(child["OMP_AUTH_BROKER_TOKEN"], _BROKER_TOKEN)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_env_overrides_persistent_broker_settings(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _BrokerOKHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            env = {
                "HOME": "/tmp/unused-home",
                "OMP_AUTH_BROKER_URL": url,
                "OMP_AUTH_BROKER_TOKEN": _BROKER_TOKEN,
            }
            pair = preflight_omp_provider_auth(
                ("openai-codex/gpt-5.6-luna",), env=env
            )
            self.assertEqual(pair, (url, _BROKER_TOKEN))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_incomplete_settings_fail_closed(self) -> None:
        env = {
            "HOME": "/tmp/unused-home",
            "OMP_AUTH_BROKER_URL": "http://127.0.0.1:8777",
        }
        with self.assertRaises(ValidationIssue) as caught:
            preflight_omp_provider_auth(("openai-codex/gpt-5.6-luna",), env=env)
        self.assertEqual(caught.exception.code, "omp_auth_broker_projection_invalid")
        self.assertNotIn(_BROKER_TOKEN, caught.exception.message)

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            _write_omp_broker_config(
                home, url="http://127.0.0.1:8777", token=None
            )
            with self.assertRaises(ValidationIssue) as config_caught:
                preflight_omp_provider_auth(
                    ("xai-oauth/grok-4.6",),
                    env={"HOME": str(home)},
                )
        self.assertEqual(
            config_caught.exception.code, "omp_auth_broker_projection_invalid"
        )
        leak = json.dumps(config_caught.exception.to_dict())
        self.assertNotIn(_BROKER_TOKEN, leak)

    def test_remote_url_fails_closed(self) -> None:
        with self.assertRaises(ValidationIssue) as caught:
            preflight_omp_provider_auth(
                ("google/gemini-3.7-flash",),
                env={
                    "OMP_AUTH_BROKER_URL": "https://broker.example.test",
                    "OMP_AUTH_BROKER_TOKEN": _BROKER_TOKEN,
                },
            )
        self.assertEqual(caught.exception.code, "omp_auth_broker_projection_invalid")
        rendered = json.dumps(caught.exception.to_dict())
        self.assertNotIn(_BROKER_TOKEN, rendered)
        self.assertNotIn(_BROKER_TOKEN, caught.exception.message)

    def test_unhealthy_broker_fails_closed(self) -> None:
        with self.assertRaises(ValidationIssue) as caught:
            preflight_omp_provider_auth(
                ("openai-codex/gpt-5.6-luna",),
                env={
                    "OMP_AUTH_BROKER_URL": "http://127.0.0.1:1",
                    "OMP_AUTH_BROKER_TOKEN": _BROKER_TOKEN,
                },
            )
        self.assertEqual(caught.exception.code, "omp_auth_broker_unhealthy")
        self.assertIn("omp auth-broker serve", caught.exception.message)
        self.assertNotIn(_BROKER_TOKEN, caught.exception.message)


class OmpInstallTargetTests(unittest.TestCase):
    def test_build_targets_includes_omp_frozen_root(self) -> None:
        import sync_installed_skills as sync

        targets = sync.build_targets(REPO)
        self.assertIn("omp", targets)
        root = targets["omp"]["root"]
        self.assertEqual(root, Path.home() / ".omp" / "agent" / "skills" / "elves")
        self.assertNotIn("managed_aliases", targets["omp"])

    def test_apply_omp_target_writes_skill(self) -> None:
        import sync_installed_skills as sync

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            repo = Path(tmpdir) / "repo"
            # minimal managed files from real REPO via build_targets then retarget
            sync.REPO_ROOT = REPO
            sync.TARGETS = sync.build_targets(REPO)
            sync.TARGETS["omp"]["root"] = home / ".omp" / "agent" / "skills" / "elves"
            problems = sync.apply_target("omp")
            self.assertEqual(problems, [])
            skill = sync.TARGETS["omp"]["root"] / "SKILL.md"
            self.assertTrue(skill.is_file())
            self.assertNotIn("omp-cli main driver", skill.read_text().lower())
            # no claude alias tree
            self.assertFalse((sync.TARGETS["omp"]["root"] / "aliases").exists())


class OmpPrewalkArgvInvariantTests(unittest.TestCase):
    def test_omp_cli_adapter_forbids_product_prewalk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "packet.md"
            prompt.write_text("# packet\n", encoding="utf-8")
            inv = build_readonly_invocation(
                adapter="omp-cli",
                profile="default",
                packet_path=prompt,
                prompt_path=prompt,
                cwd=str(tmp),
                requested_model="xai-oauth/grok-4.5",
            )
            self.assertNotIn("--prewalk", inv.argv)
            self.assertNotIn("--continue", inv.argv)
            self.assertNotIn("-c", inv.argv)


if __name__ == "__main__":
    unittest.main()
