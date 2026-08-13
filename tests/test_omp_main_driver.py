"""Oh My Pi (omp) main-driver host, install, and prewalk invariants."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from cobbler_runtime.host_profiles import (
    HostLaunchRequest,
    host_profile_or_none,
    resolve_host_profile,
)
from cobbler_runtime.adapters import build_readonly_invocation
from cobbler_runtime.native_worker import _native_worker_child_env, build_native_worker_spec
from cobbler_runtime.prewalk import (
    PREWALK_CONTINUATION_INPUT,
    advertised_prewalk_capabilities,
    load_prewalk_capability_evidence,
)
from cobbler_runtime.schema import ValidationIssue

REPO = Path(__file__).resolve().parents[1]


class OmpHostProfileTests(unittest.TestCase):
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
        self.assertEqual(create.prompt_file_flag, "--append-system-prompt")
        self.assertIn("Follow the system packet.", create.argv)
        self.assertNotIn("--prewalk", create.argv)
        self.assertNotIn("--continue", create.argv)
        self.assertNotIn("-c", create.argv)
        self.assertIsNone(create.session_id)
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
            self.assertEqual(spec.prompt_file_flag, "--append-system-prompt")

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
            with self.assertRaises(ValidationIssue) as caught:
                build_native_worker_spec(
                    host="grok",
                    worktree=repo,
                    effort="max",
                    requested_model="grok-4.5",
                )
            self.assertEqual(caught.exception.code, "invalid_worker_effort")

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
