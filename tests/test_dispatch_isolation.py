"""Dispatched external lane isolation (not standalone helper tests)."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cobbler_runtime.isolation as isolation  # noqa: E402
from cobbler_runtime.dispatch_models import (  # noqa: E402
    AttemptResult,
    LaneResult,
    LaneSpec,
)
from cobbler_runtime.isolation import (  # noqa: E402
    IsolationSpec,
    IsolatedLane,
    QualifiedSandboxBackend,
    _macos_executable_access,
    _macos_dynamic_dependencies,
    _narrow_runtime_root,
    capture_snapshot_state,
    create_tracked_snapshot,
    export_snapshot_handoff,
    prepare_fs_sandbox,
    resolve_fs_sandbox_backend,
    rewrite_argv_repo_paths,
    wrap_argv_with_sandbox,
)
from cobbler_runtime.schema import EffectiveAttempt, ValidationIssue  # noqa: E402


def _init_repo(path: Path) -> None:
    os.system(f"git -C {path} init -q")
    os.system(f"git -C {path} config user.email t@t")
    os.system(f"git -C {path} config user.name t")


def _commit_all(path: Path) -> None:
    os.system(f"git -C {path} add -A && git -C {path} commit -q -m fixture")


def _write_tool_stub(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o700)
    return path


FAKE_EXTERNAL = r'''#!/usr/bin/env python3
"""Hostile external lane: try to read secrets; report what is visible."""
import json, os, sys
from pathlib import Path

cwd = Path.cwd()
home = Path(os.environ.get("HOME", ""))

def can_read(path):
    try:
        path.read_bytes()
        return True
    except OSError:
        return False

report = {
    "role": "hostile",
    "verdict": "info",
    "confidence": 0.5,
    "key_findings": [],
    "evidence": [],
    "risks": [],
    "recommended_actions": [],
    "open_questions": [],
}
# Attempt reads relative to CWD (should be isolated snapshot)
checks = {
    "cwd_env": can_read(cwd / ".env"),
    "cwd_agents": can_read(cwd / "AGENTS.md"),
    "cwd_src": can_read(cwd / "src" / "app.py"),
    "home_secret": can_read(home / ".secret"),
    "sibling": can_read(cwd.parent.parent / "sibling-secret.txt") if cwd.parent else False,
}
# Also try absolute paths to host sentinels from env
host_home = os.environ.get("PROBE_HOST_HOME_GRANT")
if host_home:
    checks["abs_home_secret"] = can_read(Path(host_home) / ".secret")
host_write = os.environ.get("PROBE_HOST_WRITE_GRANT")
if host_write:
    try:
        Path(host_write).write_text("HOST_MUTATED\n")
        checks["abs_host_write"] = True
    except OSError:
        checks["abs_host_write"] = False
report["evidence"] = [json.dumps({"isolation_checks": checks}, sort_keys=True)]
print(json.dumps({"role_report": report, "actual_model": "fake-external"}))
'''


class DispatchIsolationTests(unittest.TestCase):
    @unittest.skip("Hard external lanes fail closed before launch")
    def test_dispatched_lane_cannot_read_secrets(self) -> None:
        if resolve_fs_sandbox_backend() is None:
            self.skipTest("usable filesystem sandbox backend not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            os.system(f"git -C {repo} init -q")
            os.system(f"git -C {repo} config user.email t@t")
            os.system(f"git -C {repo} config user.name t")
            (repo / "src").mkdir()
            (repo / "src" / "app.py").write_text("print('ok')\n")
            (repo / "AGENTS.md").write_text("SECRET_INSTRUCTION\n")
            (repo / ".env").write_text("SECRET_SENTINEL=x\n")

            # Keep the hostile executable tracked so bwrap can run the rewritten
            # snapshot path instead of requiring a host-temp bind.
            script = repo / "hostile.py"
            script.write_text(FAKE_EXTERNAL)
            script.chmod(0o700)
            os.system(
                f"git -C {repo} add src/app.py AGENTS.md hostile.py "
                f"&& git -C {repo} commit -q -m init"
            )
            host_home = root / "host-home"
            host_home.mkdir()
            (host_home / ".secret").write_text("HOST\n")
            host_write = root / "host-write.txt"
            sibling = root / "sibling-secret.txt"
            sibling.write_text("sib\n")

            attempt = EffectiveAttempt(
                profile="custom-cli",
                adapter="custom-cli",
                executable=sys.executable,
                requested_model=None,
                extra_args=(),
                env_grants=("PROBE_HOST_HOME_GRANT", "PROBE_HOST_WRITE_GRANT"),
                input_contract="json-stdio",
                output_contract="custom-json-envelope",
                capabilities=(),
                reason="isolation test",
                required=True,
                enabled=True,
                source="test",
            )
            # Build a fake lane that runs our script as the "adapter executable"
            # by command_override via council isn't direct — use _run_single_attempt path
            # through run_council with a custom profile is heavy. Use asyncio direct.
            from cobbler_runtime.dispatch import (  # noqa: PLC0415
                ContextPacket,
                _HostEvidenceLedger,
                _run_single_attempt,
            )
            from cobbler_runtime.context import build_context_packet  # noqa: PLC0415

            packet = build_context_packet(
                task="probe isolation",
                role="hostile",
                mode="read-only",
                scope="test",
                relevant_files=[],
                plan_path=None,
                head_sha=None,
                requested_model=None,
                profile="custom-cli",
                adapter="custom-cli",
                run_id="iso-test",
            )
            spec = LaneSpec(
                lane_id="hostile",
                role="hostile",
                adapter="custom-cli",
                profile="custom-cli",
                required=True,
                timeout_seconds=10.0,
                attempts=(attempt,),
            )

            work = root / "work"
            work.mkdir()
            env = {
                "PATH": os.environ.get("PATH", "/bin"),
                "PROBE_HOST_HOME_GRANT": str(host_home),
                "PROBE_HOST_WRITE_GRANT": str(host_write),
                "HOME": str(host_home),
                "SECRET_SENTINEL": "should-not-pass",
            }
            attempt_result, lane = asyncio.run(
                _run_single_attempt(
                    spec=spec,
                    attempt=attempt,
                    attempt_index=0,
                    packet=packet,
                    work_dir=work,
                    parent_env=env,
                    command_override=(sys.executable, str(script)),
                    repo_root=repo,
                    host_ledger=_HostEvidenceLedger("iso-test"),
                    task="probe isolation",
                )
            )
            if sys.platform == "darwin":
                self.assertFalse(attempt_result.ok, attempt_result)
                self.assertFalse(attempt_result.process_launched, attempt_result)
                self.assertFalse(lane.process_launched, lane)
                self.assertEqual(attempt_result.failure_class, "isolation_failure")
                self.assertIn(
                    "recursive external-process boundary",
                    attempt_result.reason or "",
                )
                self.assertFalse(host_write.exists())
                return
            self.assertTrue(
                attempt_result.ok,
                f"{attempt_result.reason}; stderr={lane.stderr_summary}",
            )
            self.assertTrue(lane.ok, lane.error)
            self.assertIsNotNone(lane.report)
            self.assertTrue(attempt_result.process_launched)
            self.assertTrue(lane.process_launched)
            iso = (attempt_result.effective_contract or {}).get("isolation") or {}
            self.assertTrue(iso.get("enabled"), iso)
            self.assertIn(iso.get("sandbox_backend"), {"sandbox-exec", "bwrap"}, iso)
            # Disposable isolation parent should be cleaned after the attempt.
            if iso.get("snapshot"):
                snap = Path(iso["snapshot"])
                self.assertFalse(snap.exists(), f"snapshot still present: {snap}")
                self.assertFalse(
                    snap.parent.exists(),
                    f"isolation parent still present: {snap.parent}",
                )
            art = Path(lane.artifact_dir or work)
            stdout_files = list(art.rglob("stdout.txt"))
            self.assertTrue(stdout_files, f"expected stdout artifact under {art}")
            body = stdout_files[0].read_text()
            data = json.loads(body)
            rr = data.get("role_report") or data
            evidence = rr.get("evidence") or []
            self.assertTrue(evidence, rr)
            checks = json.loads(evidence[0]).get("isolation_checks") or {}
            self.assertFalse(checks.get("cwd_env"), checks)
            self.assertFalse(checks.get("cwd_agents"), checks)
            self.assertTrue(checks.get("cwd_src"), checks)
            self.assertFalse(checks.get("home_secret"), checks)
            self.assertIn("abs_home_secret", checks)
            self.assertFalse(checks.get("abs_home_secret"), checks)
            self.assertIn("abs_host_write", checks)
            self.assertFalse(checks.get("abs_host_write"), checks)
            self.assertFalse(host_write.exists(), "hostile lane wrote outside isolation")

    def test_required_isolation_fails_closed_without_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("print('ok')\n")
            work = root / "work"
            work.mkdir()

            attempt = EffectiveAttempt(
                profile="custom-cli",
                adapter="custom-cli",
                executable=sys.executable,
                requested_model=None,
                extra_args=(),
                input_contract="json-stdio",
                output_contract="custom-json-envelope",
                capabilities=(),
                reason="no-backend isolation test",
                required=True,
                enabled=True,
                source="test",
            )

            spec = LaneSpec(
                lane_id="no-backend",
                role="hostile",
                adapter="custom-cli",
                profile="custom-cli",
                required=True,
                timeout_seconds=10.0,
                attempts=(attempt,),
            )

            from cobbler_runtime.context import build_context_packet  # noqa: PLC0415
            from cobbler_runtime.dispatch import (  # noqa: PLC0415
                _HostEvidenceLedger,
                _run_single_attempt,
            )

            packet = build_context_packet(
                task="must not launch",
                role="hostile",
                mode="read-only",
                scope="test",
                relevant_files=[],
                plan_path=None,
                head_sha=None,
                requested_model=None,
                profile="custom-cli",
                adapter="custom-cli",
                run_id="no-backend-test",
            )
            with mock.patch(
                "cobbler_runtime.dispatch_external.resolve_fs_sandbox_backend",
                return_value=None,
            ), mock.patch.object(
                asyncio,
                "create_subprocess_exec",
                new_callable=mock.AsyncMock,
            ) as launch:
                attempt_result, lane = asyncio.run(
                    _run_single_attempt(
                        spec=spec,
                        attempt=attempt,
                        attempt_index=0,
                        packet=packet,
                        work_dir=work,
                        parent_env={"PATH": os.environ.get("PATH", "/bin")},
                        command_override=(
                            sys.executable,
                            "-c",
                            "raise SystemExit('must not launch')",
                        ),
                        repo_root=repo,
                        host_ledger=_HostEvidenceLedger("no-backend-test"),
                        task="must not launch",
                    )
                )

            self.assertFalse(attempt_result.ok)
            self.assertEqual(attempt_result.failure_class, "isolation_failure")
            self.assertIn("Required isolation failed", attempt_result.reason or "")
            self.assertFalse(attempt_result.process_launched)
            self.assertFalse(attempt_result.model_call_made)
            self.assertFalse(lane.ok)
            self.assertEqual(lane.failure_class, "isolation_failure")
            self.assertFalse(lane.process_launched)
            self.assertFalse(lane.model_call_made)
            self.assertEqual(list(work.rglob("stdout.txt")), [])
            launch.assert_not_awaited()

class BuiltInAdapterIsolationTests(unittest.TestCase):
    @staticmethod
    def _prepare_transport_plan(prepare_external_launch, **kwargs):
        """Exercise snapshot/transport construction without a live OS backend."""
        import cobbler_runtime.dispatch_external as external

        real_create = external.create_tracked_snapshot

        def create_without_live_backend(specification: IsolationSpec) -> IsolatedLane:
            return real_create(
                replace(
                    specification,
                    require_fs_sandbox=False,
                    qualified_backend=None,
                )
            )

        with mock.patch.object(
            external,
            "resolve_fs_sandbox_backend",
            return_value=QualifiedSandboxBackend("bwrap", Path("/usr/bin/bwrap")),
        ), mock.patch.object(
            external,
            "create_tracked_snapshot",
            side_effect=create_without_live_backend,
        ), mock.patch.object(
            external,
            "_require_darwin_recursive_containment",
            return_value=None,
        ), mock.patch.object(
            external,
            "_require_linux_recursive_containment",
            return_value=None,
        ):
            return prepare_external_launch(**kwargs)

    def test_codex_argv_uses_snapshot_cd_not_original_repo(self) -> None:
        """Built-in codex-fugu argv must embed --cd <snapshot>, not original repo."""
        from cobbler_runtime.dispatch_external import prepare_external_launch
        from cobbler_runtime.schema import EffectiveAttempt
        from cobbler_runtime.context import scrub_environment, build_context_packet
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            os.system(f"git -C {repo} init -q")
            os.system(f"git -C {repo} config user.email t@t && git -C {repo} config user.name t")
            (repo / "src").mkdir()
            (repo / "src" / "app.py").write_text("print(1)\n")
            (repo / ".env").write_text("SECRET=1\n")
            os.system(f"git -C {repo} add src/app.py && git -C {repo} commit -q -m i")
            attempt = EffectiveAttempt(
                profile="codex-fugu",
                adapter="codex-fugu",
                executable="codex",
                requested_model=None,
                extra_args=(),
                input_contract="stdin",
                output_contract="codex-jsonl",
                capabilities=(),
                reason="test",
                required=True,
                enabled=True,
                source="test",
            )

            spec = LaneSpec(
                lane_id="codex",
                role="reviewer",
                adapter="codex-fugu",
                profile="codex-fugu",
                required=True,
                timeout_seconds=5.0,
                attempts=(attempt,),
            )

            work = root / "work"
            work.mkdir()
            packet_path = work / "packet.json"
            prompt_path = work / "prompt.txt"
            packet_path.write_text("{}")
            prompt_path.write_text("task")
            tool_bin = root / "tool-bin"
            _write_tool_stub(tool_bin / "codex")
            scrub = scrub_environment(
                {"PATH": f"{tool_bin}{os.pathsep}{os.environ.get('PATH', '/bin')}"}
            )
            plan = self._prepare_transport_plan(
                prepare_external_launch,
                spec=spec,
                attempt=attempt,
                attempt_index=0,
                repo_root=repo,
                packet_path=packet_path,
                prompt_path=prompt_path,
                packet_dict={"task": "x"},
                redacted_task="x",
                exact_secret_values=frozenset(),
                grants=(),
                scrub_env=scrub.env,
                command_override=None,
                parent_env=scrub.env,
            )
            self.assertFalse(plan.external_attempt_skipped)
            argv = plan.argv
            self.assertIn("--cd", argv)
            cd_val = argv[argv.index("--cd") + 1]
            self.assertIn("snapshot", cd_val)
            self.assertNotEqual(Path(cd_val).resolve(), repo.resolve())
            self.assertFalse((Path(cd_val) / ".env").exists())
            if plan.isolated:
                plan.isolated.cleanup()

    def test_grok_prompt_file_is_inside_snapshot_with_full_body(self) -> None:
        from cobbler_runtime.context import scrub_environment
        from cobbler_runtime.dispatch_external import prepare_external_launch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "app.py").write_text("print('ok')\n")
            (repo / "GEMINI.md").write_text("INERT_ONLY\n")
            _commit_all(repo)
            work = root / "work"
            work.mkdir()
            packet = work / "packet.json"
            prompt = work / "prompt.txt"
            packet.write_text('{"task":"review"}\n')
            prompt.write_text("short placeholder\n")
            tool_bin = root / "tool-bin"
            _write_tool_stub(tool_bin / "grok")
            attempt = EffectiveAttempt(
                profile="grok-build",
                adapter="grok-build",
                executable="grok",
                input_contract="prompt-file",
                output_contract="grok-json",
                required=True,
                source="test",
            )
            spec = LaneSpec(
                lane_id="grok",
                role="reviewer",
                adapter="grok-build",
                profile="grok-build",
                required=True,
                attempts=(attempt,),
                include_instructions_as_data=True,
            )
            scrub = scrub_environment(
                {"PATH": f"{tool_bin}{os.pathsep}{os.environ.get('PATH', '/bin')}"}
            )
            plan = self._prepare_transport_plan(
                prepare_external_launch,
                spec=spec,
                attempt=attempt,
                attempt_index=0,
                repo_root=repo,
                packet_path=packet,
                prompt_path=prompt,
                packet_dict={"task": "review", "constraints": ["read-only"]},
                redacted_task="review",
                exact_secret_values=frozenset(),
                grants=(),
                scrub_env=scrub.env,
                command_override=None,
                parent_env=scrub.env,
            )
            try:
                self.assertFalse(plan.external_attempt_skipped)
                prompt_index = plan.argv.index("--prompt-file") + 1
                sandbox_prompt = Path(plan.argv[prompt_index])
                self.assertTrue(sandbox_prompt.is_file(), plan.argv)
                self.assertEqual(plan.isolated.snapshot, sandbox_prompt.parents[1])
                body = sandbox_prompt.read_text()
                self.assertIn("read-only", body)
                self.assertNotEqual(body, "short placeholder\n")
                self.assertTrue(plan.isolation_meta["instruction_data_files"])
                self.assertFalse((plan.isolated.snapshot / "GEMINI.md").exists())
            finally:
                if plan.isolated:
                    plan.isolated.cleanup()

    def test_custom_adapter_packet_path_is_inside_snapshot(self) -> None:
        from cobbler_runtime.context import scrub_environment
        from cobbler_runtime.dispatch_external import prepare_external_launch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            executable = repo / "agent.py"
            executable.write_text("print('{}')\n")
            _commit_all(repo)
            work = root / "work"
            work.mkdir()
            packet = work / "packet.json"
            prompt = work / "prompt.txt"
            packet.write_text('{"task":"review"}\n')
            prompt.write_text("review\n")
            attempt = EffectiveAttempt(
                profile="custom",
                adapter="custom-cli",
                executable=str(executable),
                input_contract="json-stdio",
                output_contract="custom-json-envelope",
                required=True,
            )
            spec = LaneSpec(
                lane_id="custom",
                role="reviewer",
                adapter="custom-cli",
                profile="custom",
                required=True,
                attempts=(attempt,),
            )
            scrub = scrub_environment({"PATH": os.environ.get("PATH", "/bin")})
            plan = self._prepare_transport_plan(
                prepare_external_launch,
                spec=spec,
                attempt=attempt,
                attempt_index=0,
                repo_root=repo,
                packet_path=packet,
                prompt_path=prompt,
                packet_dict={"task": "review"},
                redacted_task="review",
                exact_secret_values=frozenset(),
                grants=(),
                scrub_env=scrub.env,
                command_override=None,
                parent_env=scrub.env,
            )
            try:
                envelope = json.loads(plan.stdin_bytes.decode("utf-8"))
                sandbox_packet = Path(envelope["packet_path"])
                self.assertTrue(sandbox_packet.is_file())
                self.assertEqual(plan.isolated.snapshot, sandbox_packet.parents[1])
                self.assertNotIn(str(work.resolve()), plan.stdin_bytes.decode("utf-8"))
            finally:
                if plan.isolated:
                    plan.isolated.cleanup()


class IsolationSnapshotRegressionTests(unittest.TestCase):
    def test_argv_rewrite_preserves_ordinary_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            snapshot = root / "snapshot"
            repo.mkdir()
            snapshot.mkdir()
            absolute = repo / "src" / "app.py"
            argv = [
                "tool",
                "review docs",
                "relative.txt",
                "--message=src/app.py",
                "--cd",
                "src",
                "--cwd=./pkg",
                ".",
                str(absolute),
            ]
            rewritten = rewrite_argv_repo_paths(
                argv, original_repo=repo, snapshot=snapshot
            )
            resolved_snapshot = snapshot.resolve()
            self.assertEqual(rewritten[1:4], argv[1:4])
            self.assertEqual(rewritten[5], str(resolved_snapshot / "src"))
            self.assertEqual(rewritten[6], f"--cwd={resolved_snapshot / 'pkg'}")
            self.assertEqual(rewritten[7], str(resolved_snapshot))
            self.assertEqual(rewritten[8], str(resolved_snapshot / "src" / "app.py"))

    def test_empty_tracked_repo_never_copies_untracked_or_nested_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "untracked.py").write_text("secret\n")
            (repo / ".aws").mkdir()
            (repo / ".aws" / "credentials").write_text("TOKEN\n")
            lane = create_tracked_snapshot(IsolationSpec(repo_root=repo, lane_id="empty"))
            try:
                self.assertEqual(lane.tracked_file_count, 0)
                self.assertFalse((lane.snapshot / "untracked.py").exists())
                self.assertFalse((lane.snapshot / ".aws" / "credentials").exists())
            finally:
                lane.cleanup()

    def test_safe_worktree_snapshot_admits_nonignored_untracked_with_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "tracked.py").write_text("tracked\n", encoding="utf-8")
            _commit_all(repo)
            (repo / "new_test.py").write_text("untracked\n", encoding="utf-8")
            (repo / ".gitignore").write_text("node_modules/\n*.pem\n", encoding="utf-8")
            (repo / "node_modules").mkdir()
            (repo / "node_modules" / "package.js").write_text("ignored\n", encoding="utf-8")
            (repo / "server.pem").write_text("PRIVATE\n", encoding="utf-8")

            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="safe-worktree",
                    include_untracked=True,
                    include_paths=("new_test.py",),
                )
            )
            try:
                self.assertEqual(lane.tracked_file_count, 1)
                self.assertEqual(lane.untracked_file_count, 2)  # .gitignore + new_test.py
                self.assertTrue((lane.snapshot / "tracked.py").is_file())
                self.assertTrue((lane.snapshot / "new_test.py").is_file())
                self.assertFalse((lane.snapshot / "node_modules").exists())
                self.assertFalse((lane.snapshot / "server.pem").exists())
                manifest = json.loads(
                    (lane.snapshot / "_elves_context" / "manifest.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(manifest["requested_paths"], ["new_test.py"])
                self.assertEqual(
                    manifest["admitted_requested_paths"], ["new_test.py"]
                )
                self.assertEqual(manifest["untracked_files"], 2)
            finally:
                lane.cleanup()

    def test_worktree_snapshot_excludes_dotenv_variant_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "safe.txt").write_text("safe\n", encoding="utf-8")
            (repo / ".env.staging").write_text("STAGING_SECRET=1\n", encoding="utf-8")
            nested = repo / "config"
            nested.mkdir()
            (nested / ".env.development.local").write_text(
                "LOCAL_SECRET=1\n", encoding="utf-8"
            )
            _commit_all(repo)
            (repo / ".env.preview").write_text("PREVIEW_SECRET=1\n", encoding="utf-8")
            (repo / "local.env").write_text("LOCAL_SECRET=1\n", encoding="utf-8")
            (repo / "test.ENV").write_text("TEST_SECRET=1\n", encoding="utf-8")
            (nested / "prod.env").write_text("PROD_SECRET=1\n", encoding="utf-8")

            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="dotenv-variants",
                    include_untracked=True,
                )
            )
            try:
                self.assertTrue((lane.snapshot / "safe.txt").is_file())
                for rel in (
                    ".env.staging",
                    "config/.env.development.local",
                    ".env.preview",
                    "local.env",
                    "test.ENV",
                    "config/prod.env",
                ):
                    self.assertFalse((lane.snapshot / rel).exists(), rel)
                manifest = json.loads(
                    (lane.snapshot / "_elves_context" / "manifest.json").read_text(
                        encoding="utf-8"
                    )
                )
                excluded = {
                    item["path"]: item["reason"]
                    for item in manifest["diagnostics"]
                }
                self.assertEqual(excluded[".env.staging"], "policy")
                self.assertEqual(
                    excluded["config/.env.development.local"], "policy"
                )
                self.assertEqual(excluded[".env.preview"], "policy")
                self.assertEqual(excluded["local.env"], "policy")
                self.assertEqual(excluded["test.ENV"], "policy")
                self.assertEqual(excluded["config/prod.env"], "policy")
            finally:
                lane.cleanup()

    def test_snapshot_reserves_internal_namespaces_before_source_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            source_paths = (
                "_elves_context/manifest.json",
                "_elves_review/source.txt",
                "_instruction_evidence/source.txt",
                "_elves_transport/source.txt",
            )
            for rel in source_paths:
                target = repo / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"repository source: {rel}\n", encoding="utf-8")
            _commit_all(repo)

            lane = create_tracked_snapshot(
                IsolationSpec(repo_root=repo, lane_id="reserved-namespaces")
            )
            try:
                manifest_path = lane.snapshot / "_elves_context" / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["schema_version"], 1)
                excluded = {
                    item["path"]: item["reason"]
                    for item in manifest["diagnostics"]
                }
                for rel in source_paths:
                    self.assertEqual(excluded[rel], "internal_namespace")
                self.assertFalse((lane.snapshot / "_elves_review").exists())
                self.assertFalse((lane.snapshot / "_instruction_evidence").exists())
                self.assertFalse((lane.snapshot / "_elves_transport").exists())
                self.assertNotIn("repository source", manifest_path.read_text())
            finally:
                lane.cleanup()

    def test_provider_writable_usage_tolerates_concurrent_subtree_removal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            victim = (
                root
                / ".codex"
                / ".tmp"
                / "plugins-clone-race"
                / "agents"
            )
            victim.mkdir(parents=True)
            (victim / "agent.md").write_text("temporary\n", encoding="utf-8")
            race_parent = victim.parent
            race_identity = race_parent.stat()
            real_open = isolation.os.open
            removed = threading.Event()

            def remove_before_descent(path, flags, mode=0o777, *, dir_fd=None):
                if (
                    path == "agents"
                    and dir_fd is not None
                    and os.fstat(dir_fd).st_dev == race_identity.st_dev
                    and os.fstat(dir_fd).st_ino == race_identity.st_ino
                    and not removed.is_set()
                ):
                    remover = threading.Thread(
                        target=shutil.rmtree,
                        args=(victim,),
                    )
                    remover.start()
                    remover.join()
                    removed.set()
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch(
                "cobbler_runtime.isolation.os.open",
                side_effect=remove_before_descent,
            ):
                entries, total_bytes, largest = (
                    isolation.provider_writable_tree_usage((root,))
                )

            self.assertTrue(removed.is_set())
            self.assertGreaterEqual(entries, 4)
            self.assertEqual(total_bytes, 0)
            self.assertIsNone(largest)

    def test_provider_writable_usage_never_follows_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "home"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "large.bin").write_bytes(b"x" * 4096)
            (root / "outside-link").symlink_to(outside, target_is_directory=True)

            entries, total_bytes, largest = (
                isolation.provider_writable_tree_usage((root,))
            )

            self.assertEqual(entries, 1)
            self.assertEqual(total_bytes, 0)
            self.assertIsNone(largest)

    def test_requested_context_rejects_ignored_forbidden_and_outside_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / ".gitignore").write_text("generated/\n", encoding="utf-8")
            (repo / "generated").mkdir()
            (repo / "generated" / "bundle.js").write_text("ignored\n", encoding="utf-8")
            (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")

            cases = (
                ("generated/bundle.js", "isolation_requested_path_ignored"),
                (".env.local", "isolation_requested_path_forbidden"),
                (str(outside), "isolation_include_path_escape"),
            )
            for requested, expected in cases:
                with self.subTest(requested=requested), self.assertRaises(
                    ValidationIssue
                ) as ctx:
                    create_tracked_snapshot(
                        IsolationSpec(
                            repo_root=repo,
                            lane_id="requested-reject",
                            include_paths=(requested,),
                        )
                    )
                self.assertEqual(ctx.exception.code, expected)

    def test_requested_context_disappearance_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            selected = repo / "selected.txt"
            selected.write_text("selected\n", encoding="utf-8")
            real_copy = isolation._copy_tracked_regular_file
            isolation_root = root / "known-isolation-root"

            def remove_before_copy(repo_root, rel, destination, **kwargs):
                if rel == "selected.txt":
                    selected.unlink(missing_ok=True)
                return real_copy(repo_root, rel, destination, **kwargs)

            with mock.patch(
                "cobbler_runtime.isolation.tempfile.mkdtemp",
                side_effect=lambda **_kwargs: str(
                    isolation_root.mkdir() or isolation_root
                ),
            ), mock.patch(
                "cobbler_runtime.isolation._copy_tracked_regular_file",
                side_effect=remove_before_copy,
            ), self.assertRaises(ValidationIssue) as ctx:
                create_tracked_snapshot(
                    IsolationSpec(
                        repo_root=repo,
                        lane_id="requested-disappeared",
                        include_paths=("selected.txt",),
                    )
                )

            self.assertEqual(
                ctx.exception.code, "isolation_requested_path_unavailable"
            )
            self.assertFalse(isolation_root.exists())

    def test_safe_worktree_snapshot_rejects_untracked_symlink_and_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            outside = root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            (repo / "link.txt").symlink_to(outside)

            with self.assertRaises(ValidationIssue) as symlink_ctx:
                create_tracked_snapshot(
                    IsolationSpec(
                        repo_root=repo,
                        lane_id="untracked-symlink",
                        include_untracked=True,
                    )
                )
            self.assertIn(
                symlink_ctx.exception.code,
                {"isolation_tracked_symlink", "isolation_tracked_open_failed"},
            )

            (repo / "link.txt").unlink()
            os.link(outside, repo / "hardlink.txt")
            with self.assertRaises(ValidationIssue) as hardlink_ctx:
                create_tracked_snapshot(
                    IsolationSpec(
                        repo_root=repo,
                        lane_id="untracked-hardlink",
                        include_untracked=True,
                    )
                )
            self.assertEqual(hardlink_ctx.exception.code, "isolation_tracked_hardlink")

    def test_context_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "large.txt").write_text("12345", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                create_tracked_snapshot(
                    IsolationSpec(
                        repo_root=repo,
                        lane_id="file-limit",
                        include_untracked=True,
                        max_context_file_bytes=4,
                    )
                )
            self.assertEqual(ctx.exception.code, "isolation_context_file_too_large")

    def test_context_special_file_fails_closed_without_blocking(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            os.mkfifo(repo / "untracked.pipe")

            started = time.monotonic()
            with self.assertRaises(ValidationIssue) as ctx:
                create_tracked_snapshot(
                    IsolationSpec(
                        repo_root=repo,
                        lane_id="special-file",
                        include_untracked=True,
                        include_paths=("untracked.pipe",),
                    )
                )
            self.assertEqual(ctx.exception.code, "isolation_tracked_nonregular")
            self.assertLess(time.monotonic() - started, 2.0)

    def test_instruction_evidence_counts_toward_context_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "AGENTS.md").write_text("instructions\n", encoding="utf-8")
            _commit_all(repo)

            with self.assertRaises(ValidationIssue) as ctx:
                create_tracked_snapshot(
                    IsolationSpec(
                        repo_root=repo,
                        lane_id="instruction-limit",
                        include_instructions_as_data=True,
                        max_context_bytes=4,
                    )
                )
            self.assertEqual(ctx.exception.code, "isolation_context_byte_limit")

    def test_writable_snapshot_exports_audited_inert_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "modified.txt").write_text("before\n", encoding="utf-8")
            (repo / "deleted.txt").write_text("delete me\n", encoding="utf-8")
            _commit_all(repo)
            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="write-handoff",
                    snapshot_writable=True,
                )
            )
            try:
                baseline = capture_snapshot_state(lane)
                (lane.snapshot / "modified.txt").write_text("after\n", encoding="utf-8")
                (lane.snapshot / "deleted.txt").unlink()
                (lane.snapshot / "added.txt").write_text("new\n", encoding="utf-8")
                destination = root / "handoff"

                with mock.patch(
                    "cobbler_runtime.isolation.tempfile.mkdtemp",
                    side_effect=lambda **_kwargs: str(
                        destination.mkdir() or destination
                    ),
                ):
                    handoff = export_snapshot_handoff(
                        lane,
                        baseline,
                        metadata={"mode": "task", "model": "fugu"},
                    )

                manifest = json.loads(
                    (handoff / "manifest.json").read_text(encoding="utf-8")
                )
                self.assertFalse(manifest["automatically_applied"])
                self.assertEqual(manifest["changed_files"], 3)
                self.assertEqual(
                    [(item["path"], item["status"]) for item in manifest["changes"]],
                    [
                        ("added.txt", "added"),
                        ("deleted.txt", "deleted"),
                        ("modified.txt", "modified"),
                    ],
                )
                self.assertEqual(
                    (handoff / "files" / "modified.txt").read_text(encoding="utf-8"),
                    "after\n",
                )
                self.assertEqual(
                    (handoff / "files" / "added.txt").read_text(encoding="utf-8"),
                    "new\n",
                )
                self.assertFalse((handoff / "files" / "deleted.txt").exists())
                self.assertEqual(
                    (repo / "modified.txt").read_text(encoding="utf-8"), "before\n"
                )
                self.assertTrue((repo / "deleted.txt").is_file())
                self.assertFalse((repo / "added.txt").exists())
            finally:
                lane.cleanup()

    def test_writable_handoff_rejects_protected_credential_and_unsafe_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "source.txt").write_text("source\n", encoding="utf-8")
            _commit_all(repo)

            cases = [
                "protected",
                "credential",
                "symlink",
                "hardlink",
                "unsafe-directory",
                "unsafe-mode",
            ]
            if hasattr(os, "mkfifo"):
                cases.append("special")
            for case in cases:
                with self.subTest(case=case):
                    lane = create_tracked_snapshot(
                        IsolationSpec(
                            repo_root=repo,
                            lane_id=f"write-reject-{case}",
                            snapshot_writable=True,
                        )
                    )
                    try:
                        baseline = capture_snapshot_state(lane)
                        if case == "protected":
                            (lane.snapshot / "_elves_context" / "manifest.json").write_text(
                                "{}\n", encoding="utf-8"
                            )
                        elif case == "credential":
                            (lane.snapshot / "output.txt").write_text(
                                "granted-value\n", encoding="utf-8"
                            )
                        elif case == "symlink":
                            (lane.snapshot / "output.txt").symlink_to("/etc/passwd")
                        elif case == "hardlink":
                            os.link(
                                lane.snapshot / "source.txt",
                                lane.snapshot / "output.txt",
                            )
                        elif case == "unsafe-directory":
                            (lane.snapshot / ".git").mkdir()
                        elif case == "unsafe-mode":
                            (lane.snapshot / "output.txt").write_text(
                                "unsafe mode\n", encoding="utf-8"
                            )
                            (lane.snapshot / "output.txt").chmod(0o777)
                        else:
                            os.mkfifo(lane.snapshot / "output.pipe")
                        with self.assertRaises(ValidationIssue) as ctx:
                            export_snapshot_handoff(
                                lane,
                                baseline,
                                forbidden_values=("granted-value",),
                            )
                        expected = {
                            "protected": "isolation_handoff_forbidden_path",
                            "credential": "isolation_handoff_credential",
                            "symlink": "isolation_tracked_symlink",
                            "hardlink": "isolation_tracked_hardlink",
                            "unsafe-directory": "isolation_handoff_forbidden_path",
                            "unsafe-mode": "isolation_handoff_unsafe_mode",
                            "special": "isolation_tracked_nonregular",
                        }[case]
                        self.assertEqual(ctx.exception.code, expected)
                    finally:
                        lane.cleanup()

    def test_writable_handoff_preserves_mode_only_and_new_executable_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            existing = repo / "existing.sh"
            existing.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            existing.chmod(0o644)
            _commit_all(repo)
            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="write-executable-modes",
                    snapshot_writable=True,
                )
            )
            try:
                baseline = capture_snapshot_state(lane)
                snapshot_existing = lane.snapshot / "existing.sh"
                snapshot_existing.chmod(0o755)
                added = lane.snapshot / "added.sh"
                added.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                added.chmod(0o755)
                destination = root / "handoff"

                with mock.patch(
                    "cobbler_runtime.isolation.tempfile.mkdtemp",
                    side_effect=lambda **_kwargs: str(
                        destination.mkdir() or destination
                    ),
                ):
                    handoff = export_snapshot_handoff(lane, baseline)

                manifest = json.loads(
                    (handoff / "manifest.json").read_text(encoding="utf-8")
                )
                changes = {item["path"]: item for item in manifest["changes"]}
                self.assertEqual(set(changes), {"added.sh", "existing.sh"})
                self.assertEqual(changes["existing.sh"]["before_mode"], 0o644)
                self.assertEqual(changes["existing.sh"]["after_mode"], 0o755)
                self.assertEqual(changes["existing.sh"]["export_mode"], 0o700)
                self.assertEqual(changes["added.sh"]["after_mode"], 0o755)
                self.assertEqual(changes["added.sh"]["export_mode"], 0o700)
                self.assertEqual(
                    stat.S_IMODE((handoff / "files" / "existing.sh").stat().st_mode),
                    0o700,
                )
                self.assertEqual(
                    stat.S_IMODE((handoff / "files" / "added.sh").stat().st_mode),
                    0o700,
                )
            finally:
                lane.cleanup()

    def test_non_git_workspace_fails_closed_and_cleans_partial_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".aws").mkdir()
            (repo / ".aws" / "credentials").write_text("TOKEN\n")
            isolation_root = root / "known-isolation-root"
            with mock.patch(
                "cobbler_runtime.isolation.tempfile.mkdtemp",
                side_effect=lambda **_kwargs: str(isolation_root.mkdir() or isolation_root),
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    create_tracked_snapshot(
                        IsolationSpec(repo_root=repo, lane_id="non-git")
                    )
            self.assertEqual(ctx.exception.code, "isolation_git_ls_files_failed")
            self.assertFalse(isolation_root.exists())

    def test_tracked_symlink_is_rejected_and_partial_snapshot_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            outside = root / "outside-secret"
            outside.write_text("SECRET\n")
            (repo / "link.txt").symlink_to(outside)
            _commit_all(repo)
            isolation_root = root / "known-isolation-root"
            with mock.patch(
                "cobbler_runtime.isolation.tempfile.mkdtemp",
                side_effect=lambda **_kwargs: str(isolation_root.mkdir() or isolation_root),
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    create_tracked_snapshot(
                        IsolationSpec(repo_root=repo, lane_id="symlink")
                    )
            self.assertEqual(ctx.exception.code, "isolation_tracked_symlink")
            self.assertFalse(isolation_root.exists())

    def test_tracked_file_symlink_swap_fails_before_snapshot_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            tracked = repo / "app.py"
            tracked.write_text("safe tracked contents\n", encoding="utf-8")
            _commit_all(repo)
            outside = root / "outside-secret.txt"
            secret = "outside sentinel must never enter snapshot\n"
            outside.write_text(secret, encoding="utf-8")
            isolation_root = root / "known-isolation-root"
            real_open = os.open
            swapped = False

            def swap_before_final_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if path == "app.py" and dir_fd is not None and not swapped:
                    swapped = True
                    tracked.unlink()
                    tracked.symlink_to(outside)
                if dir_fd is None:
                    return real_open(path, flags, mode)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch(
                "cobbler_runtime.isolation.tempfile.mkdtemp",
                side_effect=lambda **_kwargs: str(isolation_root.mkdir() or isolation_root),
            ), mock.patch(
                "cobbler_runtime.isolation.os.open",
                side_effect=swap_before_final_open,
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    create_tracked_snapshot(
                        IsolationSpec(repo_root=repo, lane_id="swap-race")
                    )

            self.assertTrue(swapped)
            self.assertIn(
                ctx.exception.code,
                {"isolation_tracked_symlink", "isolation_tracked_open_failed"},
            )
            self.assertEqual(outside.read_text(encoding="utf-8"), secret)
            self.assertFalse(isolation_root.exists())

    def test_tracked_hardlink_is_rejected_before_snapshot_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            tracked = repo / "app.py"
            tracked.write_text("safe tracked contents\n", encoding="utf-8")
            _commit_all(repo)
            outside = root / "outside-secret.txt"
            secret = "outside hardlink sentinel must never enter snapshot\n"
            outside.write_text(secret, encoding="utf-8")
            tracked.unlink()
            os.link(outside, tracked)
            isolation_root = root / "known-isolation-root"

            with mock.patch(
                "cobbler_runtime.isolation.tempfile.mkdtemp",
                side_effect=lambda **_kwargs: str(isolation_root.mkdir() or isolation_root),
            ):
                with self.assertRaises(ValidationIssue) as ctx:
                    create_tracked_snapshot(
                        IsolationSpec(repo_root=repo, lane_id="hardlink")
                    )

            self.assertEqual(ctx.exception.code, "isolation_tracked_hardlink")
            self.assertEqual(outside.read_text(encoding="utf-8"), secret)
            self.assertFalse(isolation_root.exists())

    def test_provider_instructions_are_inert_and_executable_config_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "src.py").write_text("print(1)\n")
            (repo / "GEMINI.md").write_text("AUTOLOAD_SENTINEL\n")
            (repo / ".github" / "instructions").mkdir(parents=True)
            (repo / ".github" / "copilot-instructions.md").write_text("COPILOT\n")
            (repo / ".github" / "instructions" / "secure.instructions.md").write_text(
                "NESTED_COPILOT\n"
            )
            (repo / ".gemini").mkdir()
            (repo / ".gemini" / "settings.json").write_text(
                '{"mcpServers":{"evil":{"command":"steal"}}}\n'
            )
            (repo / ".agent" / "rules").mkdir(parents=True)
            (repo / ".agent" / "rules" / "autoload.md").write_text(
                "ANTIGRAVITY_AUTOLOAD\n"
            )
            (repo / ".mcp.json").write_text('{"token":"SECRET"}\n')
            (repo / ".vscode").mkdir()
            (repo / ".vscode" / "mcp.json").write_text('{"command":"steal"}\n')
            (repo / "opencode.json").write_text('{"command":"steal"}\n')
            for protected in (".claude", ".codex", ".grok", ".gemini", ".agent"):
                nested = repo / "packages" / "demo" / protected
                nested.mkdir(parents=True, exist_ok=True)
                (nested / "settings.json").write_text('{"command":"nested-steal"}\n')
            nested_vscode = repo / "packages" / "demo" / ".vscode"
            nested_vscode.mkdir(parents=True, exist_ok=True)
            (nested_vscode / "mcp.json").write_text('{"command":"nested-mcp"}\n')
            _commit_all(repo)
            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="instructions",
                    include_instructions_as_data=True,
                )
            )
            try:
                self.assertTrue((lane.snapshot / "src.py").is_file())
                for active in (
                    "GEMINI.md",
                    ".github/copilot-instructions.md",
                    ".github/instructions/secure.instructions.md",
                    ".gemini/settings.json",
                    ".agent/rules/autoload.md",
                    ".mcp.json",
                    ".vscode/mcp.json",
                    "opencode.json",
                    "packages/demo/.claude/settings.json",
                    "packages/demo/.codex/settings.json",
                    "packages/demo/.grok/settings.json",
                    "packages/demo/.gemini/settings.json",
                    "packages/demo/.agent/settings.json",
                    "packages/demo/.vscode/mcp.json",
                ):
                    self.assertFalse((lane.snapshot / active).exists(), active)
                evidence = "\n".join(lane.instruction_data_files)
                self.assertIn("GEMINI", evidence)
                self.assertIn("copilot", evidence.lower())
                self.assertNotIn("mcp", evidence.lower())
                self.assertNotIn("opencode", evidence.lower())
                combined = "\n".join(
                    path.read_text()
                    for path in (lane.snapshot / "_instruction_evidence").glob("*.txt")
                )
                self.assertNotIn("SECRET", combined)
                self.assertNotIn("steal", combined)
            finally:
                lane.cleanup()

    def test_extra_exclude_globs_are_enforced_and_must_be_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "keep.py").write_text("ok\n")
            (repo / "generated").mkdir()
            (repo / "generated" / "bundle.js").write_text("generated\n")
            (repo / "server.pem").write_text("PRIVATE\n")
            _commit_all(repo)
            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="globs",
                    extra_exclude_globs=("generated/**", "*.pem"),
                )
            )
            try:
                self.assertTrue((lane.snapshot / "keep.py").is_file())
                self.assertFalse((lane.snapshot / "generated" / "bundle.js").exists())
                self.assertFalse((lane.snapshot / "server.pem").exists())
            finally:
                lane.cleanup()
            with self.assertRaises(ValidationIssue) as ctx:
                create_tracked_snapshot(
                    IsolationSpec(
                        repo_root=repo,
                        lane_id="bad-glob",
                        extra_exclude_globs=("../escape",),
                    )
                )
            self.assertEqual(ctx.exception.code, "invalid_isolation_exclude_glob")

    def test_cleanup_repairs_read_only_tree_and_rejects_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "app.py").write_text("ok\n")
            _commit_all(repo)
            lane = create_tracked_snapshot(IsolationSpec(repo_root=repo, lane_id="cleanup"))
            (lane.snapshot / "app.py").chmod(0o400)
            lane.snapshot.chmod(0o500)
            lane.root.chmod(0o500)
            lane.cleanup()
            self.assertFalse(lane.root.exists())

            lane = create_tracked_snapshot(IsolationSpec(repo_root=repo, lane_id="residue"))
            try:
                with mock.patch("cobbler_runtime.isolation.shutil.rmtree", return_value=None):
                    with self.assertRaises(ValidationIssue) as ctx:
                        lane.cleanup()
                self.assertEqual(ctx.exception.code, "isolation_cleanup_failed")
                self.assertTrue(lane.root.exists())
            finally:
                lane.cleanup()


class IsolationSandboxRegressionTests(unittest.TestCase):
    @staticmethod
    def _host_evidence(role: str) -> dict[str, object]:
        return {
            "executor_id": "dispatch-isolation-host",
            "actual_model": "host-native",
            "adapter_metadata": {
                "executor_id": "dispatch-isolation-host",
                "actual_model": "host-native",
                "source": "host-executor",
            },
            "role_report": {
                "role": role,
                "verdict": "pass",
                "confidence": "medium",
                "key_findings": ["native fallback executed"],
                "evidence": ["host-executor"],
                "risks": [],
                "recommended_actions": [],
                "open_questions": [],
            },
        }

    @unittest.skipUnless(sys.platform == "darwin", "Darwin audit-token API required")
    def test_macos_generation_signal_preflight_is_real(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        identity = external._darwin_process_record(os.getpid())
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertTrue(
            external._darwin_signal_audit_token(
                identity.darwin_audit_token,
                signal.SIGCONT,
            )
        )

    @unittest.skipUnless(sys.platform == "darwin", "Darwin gate required")
    def test_macos_hard_external_boundary_fails_before_spawn(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            asyncio,
            "create_subprocess_exec",
        ) as spawn:
            plan = external.ExternalLaunchPlan(
                argv=["/usr/bin/true"],
                cwd=tmp,
                env={"PATH": "/usr/bin:/bin"},
                isolated=None,
                isolation_meta={"enabled": False},
                fallback_host_native=True,
                invocation=None,
                stdin_bytes=None,
            )
            result = asyncio.run(
                external.run_external_subprocess(
                    plan=plan,
                    timeout_seconds=1.0,
                )
            )

        spawn.assert_not_called()
        self.assertFalse(result["ok"], result)
        self.assertFalse(result["process_launched"], result)
        self.assertEqual(result["failure_class"], "isolation_failure")
        self.assertIn(
            "isolation_recursive_containment_unavailable",
            result["reason"],
        )

    def test_unqualified_linux_detached_child_plan_fails_before_spawn(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lane = self._lane(root / "lane", backend="")
            pid_path = root / "escaped.pid"
            escape_script = (
                "import os, pathlib, sys, time; "
                "pid = os.fork(); "
                "pid and os._exit(0); "
                "os.setsid(); "
                "pid = os.fork(); "
                "pid and os._exit(0); "
                "os.environ.clear(); "
                "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
                "time.sleep(30)"
            )
            plan = external.ExternalLaunchPlan(
                argv=[sys.executable, "-c", escape_script, str(pid_path)],
                cwd=str(lane.snapshot),
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                isolated=lane,
                isolation_meta={"enabled": False},
                fallback_host_native=False,
                invocation=None,
                stdin_bytes=None,
            )
            with mock.patch.object(
                external.sys,
                "platform",
                "linux",
            ), mock.patch.object(
                external,
                "resolve_fs_sandbox_backend",
                return_value=None,
            ), mock.patch.object(
                asyncio,
                "create_subprocess_exec",
                new_callable=mock.AsyncMock,
            ) as spawn:
                result = asyncio.run(
                    external.run_external_subprocess(
                        plan=plan,
                        timeout_seconds=1.0,
                    )
                )

            spawn.assert_not_awaited()
            self.assertFalse(result["ok"], result)
            self.assertFalse(result["process_launched"], result)
            self.assertEqual(result["failure_class"], "isolation_failure")
            self.assertIn(
                "cannot atomically bind the bwrap child",
                result["reason"],
            )
            self.assertFalse(pid_path.exists())
            self.assertFalse(lane.root.exists())

    def test_linux_prepare_skips_optional_and_blocks_required_before_snapshot(
        self,
    ) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        optional_attempt = EffectiveAttempt(
            profile="custom",
            adapter="custom-cli",
            executable="custom-agent",
            input_contract="json-stdio",
            output_contract="custom-json-envelope",
            required=False,
        )
        optional_spec = LaneSpec(
            lane_id="linux-capability",
            role="reviewer",
            adapter="custom-cli",
            profile="custom",
            required=False,
            attempts=(optional_attempt,),
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            external.sys,
            "platform",
            "linux",
        ), mock.patch.object(
            external,
            "resolve_fs_sandbox_backend",
        ) as resolve_backend, mock.patch.object(
            external,
            "create_tracked_snapshot",
        ) as create_snapshot, mock.patch.object(
            asyncio,
            "create_subprocess_exec",
        ) as spawn:
            root = Path(tmp)
            plan = external.prepare_external_launch(
                spec=optional_spec,
                attempt=optional_attempt,
                attempt_index=0,
                repo_root=root,
                packet_path=root / "packet.json",
                prompt_path=root / "prompt.txt",
                packet_dict={},
                redacted_task="task",
                exact_secret_values=frozenset(),
                grants=(),
                scrub_env={"PATH": "/usr/bin:/bin"},
                command_override=None,
                parent_env=None,
            )
            self.assertTrue(plan.external_attempt_skipped, plan)
            self.assertEqual(plan.argv, [])
            self.assertIsNone(plan.isolated)
            self.assertIn(
                "isolation_recursive_containment_unavailable",
                plan.isolation_meta.get("reason", ""),
            )

            required_spec = replace(optional_spec, required=True)
            with self.assertRaises(ValidationIssue) as caught:
                external.prepare_external_launch(
                    spec=required_spec,
                    attempt=optional_attempt,
                    attempt_index=0,
                    repo_root=root,
                    packet_path=root / "packet.json",
                    prompt_path=root / "prompt.txt",
                    packet_dict={},
                    redacted_task="task",
                    exact_secret_values=frozenset(),
                    grants=(),
                    scrub_env={"PATH": "/usr/bin:/bin"},
                    command_override=None,
                    parent_env=None,
                )

        self.assertEqual(caught.exception.code, "required_isolation_failed")
        self.assertIn("cannot atomically bind", caught.exception.message)
        resolve_backend.assert_not_called()
        create_snapshot.assert_not_called()
        spawn.assert_not_called()

    def test_darwin_prepare_skips_optional_and_blocks_required_route(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        optional_attempt = EffectiveAttempt(
            profile="custom",
            adapter="custom-cli",
            executable="custom-agent",
            input_contract="json-stdio",
            output_contract="custom-json-envelope",
            required=False,
        )
        optional_spec = LaneSpec(
            lane_id="darwin-capability",
            role="reviewer",
            adapter="custom-cli",
            profile="custom",
            required=False,
            attempts=(optional_attempt,),
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            external.sys,
            "platform",
            "darwin",
        ):
            root = Path(tmp)
            plan = external.prepare_external_launch(
                spec=optional_spec,
                attempt=optional_attempt,
                attempt_index=0,
                repo_root=root,
                packet_path=root / "packet.json",
                prompt_path=root / "prompt.txt",
                packet_dict={},
                redacted_task="task",
                exact_secret_values=frozenset(),
                grants=(),
                scrub_env={"PATH": "/usr/bin:/bin"},
                command_override=None,
                parent_env=None,
            )
            self.assertTrue(plan.external_attempt_skipped, plan)
            self.assertEqual(plan.argv, [])
            self.assertIsNone(plan.isolated)
            self.assertIn(
                "isolation_recursive_containment_unavailable",
                plan.isolation_meta.get("reason", ""),
            )

            required_spec = replace(optional_spec, required=True)
            with self.assertRaises(ValidationIssue) as caught:
                external.prepare_external_launch(
                    spec=required_spec,
                    attempt=optional_attempt,
                    attempt_index=0,
                    repo_root=root,
                    packet_path=root / "packet.json",
                    prompt_path=root / "prompt.txt",
                    packet_dict={},
                    redacted_task="task",
                    exact_secret_values=frozenset(),
                    grants=(),
                    scrub_env={"PATH": "/usr/bin:/bin"},
                    command_override=None,
                    parent_env=None,
                )
        self.assertEqual(caught.exception.code, "required_isolation_failed")
        self.assertIn("recursive external-process boundary", caught.exception.message)

    def test_darwin_required_external_failure_blocks_native_fallback(self) -> None:
        import cobbler_runtime.dispatch as dispatch  # noqa: PLC0415
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        host_calls: list[dict[str, object]] = []

        def host_executor(challenge: dict) -> dict:
            host_calls.append(challenge)
            return self._host_evidence("reviewer")

        attempts = (
            EffectiveAttempt(
                profile="required-external",
                adapter="custom-cli",
                executable="custom-agent",
                input_contract="json-stdio",
                output_contract="custom-json-envelope",
                required=False,
            ),
            EffectiveAttempt(profile="host-native", adapter="host-native"),
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            external.sys,
            "platform",
            "darwin",
        ), mock.patch.object(
            asyncio,
            "create_subprocess_exec",
            new_callable=mock.AsyncMock,
        ) as spawn:
            result = dispatch.run_council_sync(
                [
                    LaneSpec(
                        lane_id="required-darwin",
                        role="reviewer",
                        adapter="custom-cli",
                        profile="required-external",
                        required=True,
                        attempts=attempts,
                        host_executor=host_executor,
                    )
                ],
                repo_root=Path(tmp),
                task="required containment",
                parent_env={"PATH": "/usr/bin:/bin"},
            )

        lane = result.lane_results[0]
        self.assertTrue(result.blocked, result)
        self.assertFalse(result.ok, result)
        self.assertFalse(lane.ok, lane)
        self.assertEqual(len(lane.attempts), 1, lane)
        self.assertEqual(lane.attempts[0].failure_class, "isolation_failure")
        self.assertTrue(
            lane.attempts[0].effective_contract.get("fallback_terminal")
        )
        self.assertEqual(host_calls, [])
        spawn.assert_not_awaited()

    def test_darwin_optional_external_failure_uses_native_fallback(self) -> None:
        import cobbler_runtime.dispatch as dispatch  # noqa: PLC0415
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        host_calls: list[dict[str, object]] = []

        def host_executor(challenge: dict) -> dict:
            host_calls.append(challenge)
            return self._host_evidence("reviewer")

        attempts = (
            EffectiveAttempt(
                profile="optional-external",
                adapter="custom-cli",
                executable="custom-agent",
                input_contract="json-stdio",
                output_contract="custom-json-envelope",
                required=False,
            ),
            EffectiveAttempt(profile="host-native", adapter="host-native"),
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            external.sys,
            "platform",
            "darwin",
        ), mock.patch.object(
            asyncio,
            "create_subprocess_exec",
            new_callable=mock.AsyncMock,
        ) as spawn:
            result = dispatch.run_council_sync(
                [
                    LaneSpec(
                        lane_id="optional-darwin",
                        role="reviewer",
                        adapter="custom-cli",
                        profile="optional-external",
                        attempts=attempts,
                        host_executor=host_executor,
                    )
                ],
                repo_root=Path(tmp),
                task="optional containment",
                parent_env={"PATH": "/usr/bin:/bin"},
            )

        lane = result.lane_results[0]
        self.assertTrue(result.ok, result)
        self.assertFalse(result.blocked, result)
        self.assertTrue(lane.ok, lane)
        self.assertEqual(len(lane.attempts), 2, lane)
        self.assertEqual(lane.attempts[0].failure_class, "unavailable")
        self.assertTrue(lane.attempts[1].ok)
        self.assertEqual(lane.fallback_used, "host-native")
        self.assertEqual(len(host_calls), 1)
        spawn.assert_not_awaited()

    def test_postlaunch_isolation_failure_blocks_optional_fallback(self) -> None:
        import cobbler_runtime.dispatch as dispatch  # noqa: PLC0415

        attempted_indexes: list[int] = []

        async def fake_attempt(**kwargs):
            index = int(kwargs["attempt_index"])
            attempt = kwargs["attempt"]
            spec = kwargs["spec"]
            attempted_indexes.append(index)
            if index == 0:
                attempt_result = AttemptResult(
                    attempt_index=0,
                    profile=attempt.profile,
                    adapter=attempt.adapter,
                    requested_model=attempt.requested_model,
                    actual_model=None,
                    model_evidence_source=None,
                    status="failed",
                    failure_class="isolation_failure",
                    reason="recursive absence unproved after launch",
                    process_launched=True,
                    model_call_made=True,
                )
                lane = LaneResult(
                    lane_id=spec.lane_id,
                    role=spec.role,
                    adapter=attempt.adapter,
                    profile=attempt.profile,
                    ok=False,
                    launch_time=1.0,
                    start_time=1.0,
                    end_time=2.0,
                    failure_class="isolation_failure",
                    process_launched=True,
                    model_call_made=True,
                    error="recursive absence unproved after launch",
                )
                return attempt_result, lane

            report = self._host_evidence("reviewer")
            attempt_result = AttemptResult(
                attempt_index=index,
                profile=attempt.profile,
                adapter=attempt.adapter,
                requested_model=attempt.requested_model,
                actual_model="host-native",
                model_evidence_source="host-executor",
                status="ok",
                ok=True,
                process_launched=False,
                model_call_made=True,
            )
            lane = LaneResult(
                lane_id=spec.lane_id,
                role=spec.role,
                adapter=attempt.adapter,
                profile=attempt.profile,
                ok=True,
                launch_time=2.0,
                start_time=2.0,
                end_time=3.0,
                report=report,
                execution_id="host-fallback-that-must-not-run",
                actual_model="host-native",
                model_evidence_source="host-executor",
                model_call_made=True,
            )
            return attempt_result, lane

        attempts = (
            EffectiveAttempt(
                profile="optional-external",
                adapter="custom-cli",
                executable="custom-agent",
                required=False,
            ),
            EffectiveAttempt(profile="host-native", adapter="host-native"),
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            dispatch,
            "_run_single_attempt",
            side_effect=fake_attempt,
        ):
            result = dispatch.run_council_sync(
                [
                    LaneSpec(
                        lane_id="optional-postlaunch-containment",
                        role="reviewer",
                        adapter="custom-cli",
                        profile="optional-external",
                        attempts=attempts,
                    )
                ],
                repo_root=Path(tmp),
                task="postlaunch containment must be terminal",
                phase_required=False,
            )

        lane = result.lane_results[0]
        self.assertEqual(attempted_indexes, [0])
        self.assertEqual(len(lane.attempts), 1)
        self.assertFalse(lane.ok)
        self.assertTrue(lane.process_launched)
        self.assertEqual(lane.failure_class, "isolation_failure")
        self.assertTrue(lane.attempts[0].effective_contract["fallback_terminal"])
        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)
        self.assertEqual(result.confidence, "blocked")
        self.assertTrue(
            any("post-launch containment unproved" in note for note in result.notes),
            result.notes,
        )

    def test_darwin_process_scan_never_requests_environment(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        calls: list[tuple[object, ...]] = []

        class FakePs:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"", b""

        async def launch(*args, **_kwargs):
            calls.append(args)
            return FakePs()

        supervisor = external._DescendantSupervisor(
            executable="/bin/ps",
            token="fixture",
            root_pid=0,
            known_pids={},
        )
        with mock.patch.object(
            asyncio,
            "create_subprocess_exec",
            side_effect=launch,
        ):
            asyncio.run(supervisor.scan())

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0],
            ("/bin/ps", "-axo", "pid=,ppid=,pgid=,command="),
        )
        self.assertNotIn("e", calls[0])
        self.assertNotIn("-E", calls[0])

    @staticmethod
    def _lane(root: Path, *, backend: str) -> IsolatedLane:
        snapshot = root / "snapshot"
        home = root / "home"
        tmp = root / "tmp"
        config = root / "config"
        cache = root / "cache"
        data = root / "data"
        for path in (snapshot, home, tmp, config, cache, data):
            path.mkdir(parents=True, exist_ok=True)
        return IsolatedLane(
            lane_id="test",
            root=root,
            snapshot=snapshot,
            home=home,
            tmp=tmp,
            xdg_config=config,
            xdg_cache=cache,
            xdg_data=data,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            tracked_file_count=0,
            sandbox_backend=backend,
            sandbox_executable=(
                "/usr/bin/sandbox-exec" if backend == "sandbox-exec" else "/usr/bin/bwrap"
            ),
        )

    def test_bwrap_binds_user_local_install_narrowly_without_run_or_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host_home = root / "host-home"
            user_bin = host_home / ".local" / "bin"
            user_bin.mkdir(parents=True)
            executable = user_bin / "fake-agent"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            lane = self._lane(root / "lane", backend="bwrap")
            lane.env["PATH"] = f"{user_bin}:/usr/bin:/bin"
            argv = wrap_argv_with_sandbox(["fake-agent", "--version"], lane)
            bind_pairs = list(zip(argv, argv[1:], argv[2:]))
            self.assertIn(
                ("--ro-bind", str(executable.resolve()), str(executable.resolve())),
                bind_pairs,
            )
            self.assertNotIn(("--ro-bind", str(host_home), str(host_home)), bind_pairs)
            self.assertNotIn(("--ro-bind-try", "/run", "/run"), bind_pairs)
            self.assertNotIn(("--ro-bind-try", "/etc", "/etc"), bind_pairs)
            self.assertIn("--die-with-parent", argv)
            self.assertIn("--unshare-all", argv)

    def test_bwrap_binds_complete_hostedtoolcache_runtime_and_creates_parents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "opt" / "hostedtoolcache" / "Python" / "3.12.9" / "x64"
            executable = runtime / "bin" / "python3"
            library = runtime / "lib" / "libpython3.12.so"
            executable.parent.mkdir(parents=True)
            library.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            library.write_text("fixture\n")
            lane = self._lane(root / "lane", backend="bwrap")
            lane.env["PATH"] = f"{executable.parent}:/usr/bin:/bin"
            argv = wrap_argv_with_sandbox(["python3", "--version"], lane)
            triples = list(zip(argv, argv[1:], argv[2:]))
            self.assertIn(
                ("--ro-bind", str(runtime.resolve()), str(runtime.resolve())), triples
            )
            self.assertIn("--dir", argv)
            self.assertIn(str(runtime.resolve().parent), argv)
            self.assertNotIn(("--ro-bind-try", "/run", "/run"), triples)
            self.assertNotIn(("--ro-bind-try", "/etc", "/etc"), triples)

    def test_bwrap_can_omit_proc_for_credential_bearing_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "fake-agent"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            lane = self._lane(root / "lane", backend="bwrap")
            lane.env["PATH"] = f"{root}:/usr/bin:/bin"

            argv = wrap_argv_with_sandbox(
                ["fake-agent", "--version"], lane, mount_proc=False
            )

            pairs = list(zip(argv, argv[1:]))
            self.assertNotIn(("--proc", "/proc"), pairs)
            self.assertIn("--unshare-all", argv)
            self.assertIn(("--dev", "/dev"), pairs)

    def test_bwrap_writable_lane_binds_only_snapshot_read_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = _write_tool_stub(root / "fake-agent")
            lane = self._lane(root / "lane", backend="bwrap")
            lane.snapshot_writable = True
            lane.env["PATH"] = f"{root}:/usr/bin:/bin"

            argv = wrap_argv_with_sandbox(
                [str(executable), "--version"], lane, mount_proc=False
            )
            triples = list(zip(argv, argv[1:], argv[2:]))
            snapshot = str(lane.snapshot)
            self.assertIn(("--bind", snapshot, snapshot), triples)
            self.assertNotIn(("--ro-bind", snapshot, snapshot), triples)
            self.assertNotIn(("--proc", "/proc"), list(zip(argv, argv[1:])))

    def test_standalone_codex_runtime_root_is_one_versioned_release(self) -> None:
        executable = Path(
            "/Users/fixture/.codex/packages/standalone/releases/"
            "0.144.6-aarch64-apple-darwin/bin/codex"
        )
        self.assertEqual(
            _narrow_runtime_root(executable),
            Path(
                "/Users/fixture/.codex/packages/standalone/releases/"
                "0.144.6-aarch64-apple-darwin"
            ),
        )

    def test_uv_interpreter_install_runtime_root_is_one_versioned_dist(self) -> None:
        # v2.24 B8: uv-managed interpreter installs are a narrow versioned
        # runtime root (same class as pyenv/asdf) — without this, sandboxed
        # lane children running a uv python die importing their own stdlib.
        executable = Path(
            "/Users/fixture/.local/share/uv/python/"
            "cpython-3.12.13-macos-aarch64-none/bin/python3.12"
        )
        self.assertEqual(
            _narrow_runtime_root(executable),
            Path(
                "/Users/fixture/.local/share/uv/python/"
                "cpython-3.12.13-macos-aarch64-none"
            ),
        )
        # uv *tools* keep their existing narrower mapping.
        self.assertEqual(
            _narrow_runtime_root(
                Path("/Users/fixture/.local/share/uv/tools/ruff/bin/ruff")
            ),
            Path("/Users/fixture/.local/share/uv/tools/ruff"),
        )

    def test_bwrap_never_mounts_entire_hidden_agent_install_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_root = root / "host-home" / ".grok"
            executable = agent_root / "bin" / "grok"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            (agent_root / "credentials.json").write_text("SECRET\n")
            lane = self._lane(root / "lane", backend="bwrap")
            lane.env["PATH"] = f"{executable.parent}:/usr/bin:/bin"
            argv = wrap_argv_with_sandbox(["grok", "--version"], lane)
            triples = list(zip(argv, argv[1:], argv[2:]))
            self.assertIn(
                ("--ro-bind", str(executable.resolve()), str(executable.resolve())),
                triples,
            )
            self.assertNotIn(("--ro-bind", str(agent_root), str(agent_root)), triples)

    def test_bwrap_canonicalizes_symlink_and_binds_only_standalone_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host_home = root / "host-home"
            target = host_home / "secrets" / "agent-real"
            target.parent.mkdir(parents=True)
            target.write_text("#!/bin/sh\nexit 0\n")
            target.chmod(0o700)
            user_bin = host_home / "bin"
            user_bin.mkdir()
            (user_bin / "agent").symlink_to(target)
            lane = self._lane(root / "lane", backend="bwrap")
            lane.env["PATH"] = f"{user_bin}:/usr/bin:/bin"
            argv = wrap_argv_with_sandbox(["agent"], lane)
            triples = list(zip(argv, argv[1:], argv[2:]))
            resolved = target.resolve()
            self.assertEqual(argv[-1], str(resolved))
            self.assertIn(("--ro-bind", str(resolved), str(resolved)), triples)
            self.assertNotIn(("--ro-bind", str(host_home), str(host_home)), triples)
            self.assertNotIn(
                ("--ro-bind", str(target.parent), str(target.parent)), triples
            )

    def test_backend_resolution_ignores_fake_path_executables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "sandbox-exec"
            fake.write_text("#!/bin/sh\nexit 0\n")
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(fake.parent)}):
                backend = resolve_fs_sandbox_backend()
            if backend is not None:
                self.assertIn(
                    backend,
                    {
                        QualifiedSandboxBackend(
                            "sandbox-exec", Path("/usr/bin/sandbox-exec")
                        ),
                        QualifiedSandboxBackend("bwrap", Path("/usr/bin/bwrap")),
                    },
                )
                self.assertNotEqual(backend.executable, fake)

    def test_backend_resolution_rejects_present_but_unusable_backend(self) -> None:
        candidate = Path("/usr/bin/bwrap")
        with mock.patch(
            "cobbler_runtime.isolation._SANDBOX_BACKEND_CANDIDATES",
            (("bwrap", candidate),),
        ), mock.patch(
            "cobbler_runtime.isolation._qualified_system_executable",
            return_value=candidate,
        ), mock.patch(
            "cobbler_runtime.isolation._probe_fs_sandbox_backend",
            return_value=False,
        ) as probe:
            self.assertIsNone(resolve_fs_sandbox_backend())
        probe.assert_called_once_with("bwrap", candidate)

    def test_prepare_backend_capability_failure_is_optional_or_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lane = self._lane(Path(tmp) / "lane", backend="bwrap")
            selected = QualifiedSandboxBackend("bwrap", Path("/usr/bin/bwrap"))
            with mock.patch(
                "cobbler_runtime.isolation._validate_qualified_backend",
                return_value=selected,
            ), mock.patch(
                "cobbler_runtime.isolation._probe_fs_sandbox_backend",
                return_value=False,
            ):
                self.assertEqual(
                    prepare_fs_sandbox(
                        lane,
                        required=False,
                        qualified_backend=selected,
                    ),
                    (None, None),
                )
                with self.assertRaises(ValidationIssue) as caught:
                    prepare_fs_sandbox(
                        lane,
                        required=True,
                        qualified_backend=selected,
                    )
            self.assertEqual(caught.exception.code, "isolation_sandbox_unusable")

    def test_sandbox_exec_writable_lane_allows_only_snapshot_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lane = self._lane(root / "lane", backend="sandbox-exec")
            lane.snapshot_writable = True
            selected = QualifiedSandboxBackend(
                "sandbox-exec", Path("/usr/bin/sandbox-exec")
            )
            with mock.patch(
                "cobbler_runtime.isolation._validate_qualified_backend",
                return_value=selected,
            ), mock.patch(
                "cobbler_runtime.isolation._probe_fs_sandbox_backend",
                return_value=True,
            ), mock.patch(
                "cobbler_runtime.isolation._resolve_macos_supervisor",
                return_value=Path("/bin/ps"),
            ):
                backend, profile_path = prepare_fs_sandbox(
                    lane,
                    required=True,
                    qualified_backend=selected,
                )

            self.assertEqual(backend, "sandbox-exec")
            assert profile_path is not None
            profile = Path(profile_path).read_text(encoding="utf-8")
            self.assertIn(
                f'(allow file-write* (subpath "{lane.snapshot.resolve()}"))',
                profile,
            )
            self.assertNotIn(
                f'(allow file-write* (subpath "{root.resolve()}"))',
                profile,
            )

    def test_sandbox_exec_profile_records_narrow_child_tool_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lane = self._lane(root / "lane", backend="sandbox-exec")
            profile = lane.root / "sandbox.sb"
            profile.write_text(
                "(version 1)\n;; ELVES_EXECUTABLE_ALLOWLIST\n",
                encoding="utf-8",
            )
            lane.sandbox_profile_path = str(profile)
            exact_tool = (root / "tools" / "git").resolve()
            runtime = (root / "runtime").resolve()
            with mock.patch(
                "cobbler_runtime.isolation._macos_executable_access",
                return_value=([exact_tool], [runtime]),
            ):
                argv = wrap_argv_with_sandbox([sys.executable, "--version"], lane)

            body = profile.read_text(encoding="utf-8")
            self.assertIn(
                f'(allow file-read* (literal "{exact_tool}"))',
                body,
            )
            self.assertIn(
                f'(allow file-read* (subpath "{runtime}"))',
                body,
            )
            self.assertEqual(argv[:3], ["/usr/bin/sandbox-exec", "-f", str(profile)])

    def test_macos_dependency_scan_never_grants_arbitrary_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = _write_tool_stub(root / "hostile")
            runtime_dependency = root / "Cellar" / "libdemo" / "1" / "libdemo.dylib"
            runtime_dependency.parent.mkdir(parents=True)
            runtime_dependency.write_bytes(b"runtime")
            unrelated = root / "credentials" / "private-token.txt"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("host secret sentinel\n", encoding="utf-8")
            output = (
                f"{executable}:\n"
                f"\t{runtime_dependency} (compatibility version 1.0.0)\n"
                f"\t{unrelated} (compatibility version 1.0.0)\n"
            )
            result = subprocess.CompletedProcess(
                args=["otool"], returncode=0, stdout=output, stderr=""
            )
            _macos_dynamic_dependencies.cache_clear()
            try:
                with mock.patch(
                    "cobbler_runtime.isolation._qualified_system_executable",
                    return_value=Path("/usr/bin/otool"),
                ), mock.patch(
                    "cobbler_runtime.isolation.subprocess.run",
                    return_value=result,
                ):
                    dependencies = _macos_dynamic_dependencies((executable.resolve(),))
            finally:
                _macos_dynamic_dependencies.cache_clear()

            self.assertIn(runtime_dependency.resolve(), dependencies)
            self.assertNotIn(unrelated.resolve(), dependencies)

    def test_macos_dependency_alias_remains_exact_without_lexical_root_grant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = _write_tool_stub(root / "tools" / "hostile")
            canonical = (
                root / "allowed" / "Cellar" / "demo" / "1" / "libdemo.dylib"
            )
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"runtime")
            canonical = canonical.resolve()
            alias = (
                root / "sensitive" / "Cellar" / "alias" / "1" / "libdemo.dylib"
            )
            alias.parent.mkdir(parents=True)
            alias.symlink_to(canonical)
            lane = self._lane(root / "lane", backend="sandbox-exec")

            with mock.patch(
                "cobbler_runtime.isolation._MACOS_CHILD_TOOL_NAMES", ()
            ), mock.patch(
                "cobbler_runtime.isolation._shebang_interpreter", return_value=None
            ), mock.patch(
                "cobbler_runtime.isolation._macos_dynamic_dependencies",
                return_value=(alias, canonical),
            ):
                exact_files, runtime_roots = _macos_executable_access(
                    executable.resolve(),
                    lane,
                    literal_executable=executable.resolve(),
                )

            canonical_root = canonical.parent
            lexical_alias_root = alias.parent
            self.assertIn(alias, exact_files)
            self.assertIn(canonical_root, runtime_roots)
            self.assertNotIn(lexical_alias_root, runtime_roots)

    def test_malicious_lane_id_is_digested_and_real_sandbox_profile_parses(self) -> None:
        qualified = resolve_fs_sandbox_backend()
        if qualified is None:
            self.skipTest("filesystem sandbox backend not available")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "app.py").write_text("SNAPSHOT_OK\n")
            _commit_all(repo)
            malicious = 'lane\")\n(allow file-read* (subpath "/"))\n;'
            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id=malicious,
                    require_fs_sandbox=True,
                    qualified_backend=qualified,
                )
            )
            try:
                self.assertRegex(lane.root.name, r"^elves-iso-[0-9a-f]{12}-")
                self.assertNotIn(malicious, str(lane.root))
                command = wrap_argv_with_sandbox(
                    [
                        sys.executable,
                        "-c",
                        "import pathlib; assert pathlib.Path('app.py').read_text().strip() == 'SNAPSHOT_OK'",
                    ],
                    lane,
                )
                result = subprocess.run(
                    command,
                    cwd=lane.snapshot,
                    env=lane.env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                if lane.sandbox_profile_path:
                    profile = Path(lane.sandbox_profile_path).read_text()
                    self.assertNotIn(malicious, profile)
            finally:
                lane.cleanup()

    def test_sandbox_exec_allows_snapshot_and_denies_host_sentinels(self) -> None:
        qualified = resolve_fs_sandbox_backend()
        if qualified is None or qualified.name != "sandbox-exec":
            self.skipTest("sandbox-exec not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lane = self._lane(root / "lane", backend="sandbox-exec")
            sentinel = root / "host-sentinel.txt"
            sentinel.write_text("HOST_SECRET\n")
            source = lane.snapshot / "source.txt"
            source.write_text("SNAPSHOT_OK\n")
            codex_home = lane.home / ".codex"
            codex_home.mkdir()
            lane.env["CODEX_HOME"] = str(codex_home)
            backend, profile = prepare_fs_sandbox(
                lane,
                required=True,
                qualified_backend=qualified,
            )
            lane.sandbox_backend = backend
            lane.sandbox_profile_path = profile
            lane.process_containment = "host-supervised"
            command = wrap_argv_with_sandbox(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os, pathlib; "
                        "assert pathlib.Path('source.txt').read_text().strip() == 'SNAPSHOT_OK'; "
                        "assert pathlib.Path.cwd().resolve(strict=True).is_dir(); "
                        "assert pathlib.Path(os.environ['CODEX_HOME']).resolve(strict=True).is_dir(); "
                        f"p=pathlib.Path({str(sentinel)!r}); "
                        "\ntry: p.read_text(); raise SystemExit(41)\nexcept OSError: pass\n"
                        "try: p.write_text('MUTATED'); raise SystemExit(42)\nexcept OSError: pass\n"
                    ),
                ],
                lane,
            )
            profile_body = Path(profile).read_text()
            self.assertNotIn("(deny process-fork)", profile_body)
            self.assertNotIn('(subpath "/opt")', profile_body)
            self.assertIn(
                f'(allow file-read-metadata (literal "{lane.root.resolve()}"))',
                profile_body,
            )
            self.assertIn(
                '(allow file-read-metadata (subpath "/var"))',
                profile_body,
            )
            self.assertNotIn('(allow file-read* (subpath "/var"))', profile_body)
            self.assertTrue(lane.supervisor_executable)
            result = subprocess.run(
                command,
                cwd=lane.snapshot,
                env=lane.env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sentinel.read_text(), "HOST_SECRET\n")

    def test_macos_supervisor_never_signals_reused_pid_identity(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        original = external._ProcessRecord(
            pid=4242,
            ppid=1,
            pgid=4242,
            start_identity="100:1",
            command="tracked generation",
            darwin_audit_token=(0, 0, 0, 0, 0, 4242, 0, 17),
        )
        supervisor = external._DescendantSupervisor(
            executable="/bin/ps",
            token="fixture-marker",
            root_pid=4242,
            known_pids={4242: original},
        )
        supervisor.scan = mock.AsyncMock(  # type: ignore[method-assign]
            return_value={4242: original}
        )
        supervisor.alive = mock.AsyncMock(  # type: ignore[method-assign]
            side_effect=[{}, {}]
        )
        reused = external._ProcessRecord(
            pid=4242,
            ppid=1,
            pgid=4242,
            start_identity="200:2",
            command="unrelated replacement",
        )
        with mock.patch.object(
            external,
            "_darwin_process_record",
            return_value=reused,
        ), mock.patch.object(external.os, "kill") as kill_mock, mock.patch.object(
            external,
            "_darwin_signal_audit_token",
        ) as audit_signal:
            cleanup = asyncio.run(
                external._terminate_supervised_descendants(supervisor)
            )

        kill_mock.assert_not_called()
        audit_signal.assert_not_called()
        self.assertTrue(cleanup["descendants_absent"], cleanup)
        self.assertEqual(
            cleanup["identity_mismatches"],
            [{"pid": 4242, "expected": "100:1", "observed": "200:2"}],
        )

    def test_macos_supervisor_uses_generation_token_after_identity_check(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        token = (0, 0, 0, 0, 0, 4242, 0, 17)
        original = external._ProcessRecord(
            pid=4242,
            ppid=1,
            pgid=4242,
            start_identity="100:1",
            command="tracked generation",
            darwin_audit_token=token,
        )
        supervisor = external._DescendantSupervisor(
            executable="/bin/ps",
            token="fixture-marker",
            root_pid=4242,
            known_pids={4242: original},
        )
        supervisor.scan = mock.AsyncMock(  # type: ignore[method-assign]
            return_value={4242: original}
        )
        supervisor.alive = mock.AsyncMock(  # type: ignore[method-assign]
            side_effect=[{}, {}]
        )
        with mock.patch.object(
            external,
            "_darwin_process_record",
            return_value=original,
        ), mock.patch.object(
            external,
            "_darwin_signal_audit_token",
            return_value=False,  # kernel reports the generation exited/reused
        ) as audit_signal, mock.patch.object(external.os, "kill") as numeric_kill:
            cleanup = asyncio.run(
                external._terminate_supervised_descendants(supervisor)
            )

        numeric_kill.assert_not_called()
        audit_signal.assert_called_once_with(token, signal.SIGTERM)
        self.assertTrue(cleanup["descendants_absent"], cleanup)

    def test_macos_monitor_error_still_cleans_known_generation(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        token = (0, 0, 0, 0, 0, 4242, 0, 17)
        original = external._ProcessRecord(
            pid=4242,
            ppid=1,
            pgid=4242,
            start_identity="100:1",
            command="tracked generation",
            darwin_audit_token=token,
        )
        supervisor = external._DescendantSupervisor(
            executable="/bin/ps",
            token="fixture-marker",
            root_pid=4242,
            known_pids={4242: original},
            error="monitor_failed",
        )

        async def failed_retry() -> dict[int, object]:
            supervisor.error = "descendant_scan_failed:fixture"
            return {}

        supervisor.scan = mock.AsyncMock(  # type: ignore[method-assign]
            side_effect=failed_retry
        )
        with mock.patch.object(
            external,
            "_darwin_process_record",
            return_value=original,
        ), mock.patch.object(
            external,
            "_darwin_signal_audit_token",
            return_value=True,
        ) as audit_signal:
            cleanup = asyncio.run(
                external._terminate_supervised_descendants(supervisor)
            )

        calls = [call.args for call in audit_signal.call_args_list]
        self.assertIn((token, signal.SIGTERM), calls)
        self.assertIn((token, signal.SIGKILL), calls)
        self.assertFalse(cleanup["descendants_absent"], cleanup)
        self.assertEqual(
            cleanup["supervision_error"],
            "descendant_scan_failed:fixture",
        )

    def test_macos_descendant_monitor_does_not_hot_loop_ps(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        supervisor = mock.Mock()
        supervisor.error = None
        supervisor.scan = mock.AsyncMock(return_value={})

        async def scenario() -> int:
            stop = asyncio.Event()
            task = asyncio.create_task(
                external._monitor_descendants(supervisor, stop)
            )
            await asyncio.sleep(0.12)
            stop.set()
            await task
            return supervisor.scan.await_count

        self.assertLessEqual(asyncio.run(scenario()), 2)

    def test_macos_reaped_group_path_never_sends_numeric_signal(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        proc = mock.Mock()
        proc.pid = 4242
        proc.returncode = 0
        proc.wait = mock.AsyncMock(return_value=0)
        with mock.patch.object(
            external.sys,
            "platform",
            "darwin",
        ), mock.patch.object(
            external,
            "pgid_alive",
            return_value=False,
        ), mock.patch.object(external.os, "killpg") as killpg:
            cleanup = asyncio.run(
                external.terminate_process_group(proc, known_pgid=4242)
            )

        killpg.assert_not_called()
        self.assertTrue(cleanup["group_absent"], cleanup)

    def test_macos_marker_snapshot_cannot_bind_reused_pid(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        original = external._ProcessRecord(
            pid=4242,
            ppid=1,
            pgid=4242,
            start_identity="100:1",
            command="",
        )
        replacement = external._ProcessRecord(
            pid=4242,
            ppid=1,
            pgid=4242,
            start_identity="200:2",
            command="",
        )

        class FakePs:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return b"tool ELVES_ISOLATION_MARKER=fixture-marker\n", b""

        with mock.patch.object(
            external,
            "_darwin_process_record",
            side_effect=[original, replacement],
        ), mock.patch.object(
            asyncio,
            "create_subprocess_exec",
            new=mock.AsyncMock(return_value=FakePs()),
        ):
            matched = asyncio.run(
                external._darwin_marker_matches_identity(
                    executable="/bin/ps",
                    pid=4242,
                    expected_start_identity="100:1",
                    token_marker="ELVES_ISOLATION_MARKER=fixture-marker",
                )
            )

        self.assertFalse(matched)

    @unittest.skip("Darwin hard external lanes now fail closed before launch")
    def test_macos_supervisor_kills_setsid_double_fork_before_success(self) -> None:
        qualified = resolve_fs_sandbox_backend()
        if qualified is None or qualified.name != "sandbox-exec":
            self.skipTest("macOS sandbox-exec not available")
        from cobbler_runtime.dispatch_external import (  # noqa: PLC0415
            ExternalLaunchPlan,
            run_external_subprocess,
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _init_repo(repo)
            script = repo / "daemonizer.py"
            script.write_text(
                """import json, os, pathlib, subprocess, sys, time
marker = pathlib.Path(os.environ['HOME']) / 'daemon.pid'
helper = r'''import os, pathlib, sys, time
if os.fork(): os._exit(0)
os.setsid()
if os.fork(): os._exit(0)
pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(30)
'''
subprocess.Popen(
    [sys.executable, '-c', helper, str(marker)],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
for _ in range(100):
    if marker.exists(): break
    time.sleep(0.01)
pid = int(marker.read_text())
print(json.dumps({'daemon_pid': pid}))
""",
                encoding="utf-8",
            )
            _commit_all(repo)
            lane = create_tracked_snapshot(
                IsolationSpec(
                    repo_root=repo,
                    lane_id="double-fork",
                    require_fs_sandbox=True,
                    qualified_backend=qualified,
                )
            )
            command = wrap_argv_with_sandbox(
                [sys.executable, str(lane.snapshot.resolve() / "daemonizer.py")], lane
            )
            plan = ExternalLaunchPlan(
                argv=command,
                cwd=str(lane.snapshot),
                env=dict(lane.env),
                isolated=lane,
                isolation_meta={"enabled": True},
                fallback_host_native=False,
                invocation=None,
                stdin_bytes=None,
            )
            result = asyncio.run(
                run_external_subprocess(plan=plan, timeout_seconds=5.0)
            )
            self.assertFalse(result["ok"], result)
            self.assertEqual(result.get("failure_class"), "execution_failure")
            cleanup = result.get("cleanup") or {}
            self.assertTrue(cleanup.get("descendants_absent"), cleanup)
            self.assertTrue(cleanup.get("descendants_found"), cleanup)
            self.assertTrue(cleanup.get("isolation_cleaned"), cleanup)
            daemon_pid = json.loads(result["stdout_raw"])["daemon_pid"]
            with self.assertRaises(ProcessLookupError):
                os.kill(daemon_pid, 0)
            self.assertFalse(lane.root.exists())

    @unittest.skip("Darwin hard external lanes now fail closed before launch")
    def test_macos_leader_exit_does_not_wait_for_inherited_pipes(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        parent = Path(tempfile.mkdtemp(prefix="external-pipe-holder-"))
        lane = self._lane(parent / "lane", backend="")
        pid_path = parent / "pipe-holder.pid"
        child_script = (
            "import os, pathlib, signal, sys, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); "
            "print('external-child-ready', flush=True); "
            "time.sleep(30)"
        )
        leader_script = (
            "import subprocess, sys, time; "
            "subprocess.Popen("
            f"[sys.executable, '-c', {child_script!r}, sys.argv[1]], "
            "start_new_session=True); "
            "\nfor _ in range(200):\n"
            "    if __import__('pathlib').Path(sys.argv[1]).exists(): break\n"
            "    time.sleep(0.01)\n"
            "print('external-leader-success', flush=True)"
        )
        plan = external.ExternalLaunchPlan(
            argv=[sys.executable, "-c", leader_script, str(pid_path)],
            cwd=str(lane.snapshot),
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            isolated=lane,
            isolation_meta={"enabled": True},
            fallback_host_native=False,
            invocation=None,
            stdin_bytes=None,
        )
        child_pid: int | None = None
        started = time.monotonic()
        try:
            result = asyncio.run(
                external.run_external_subprocess(
                    plan=plan,
                    timeout_seconds=5.0,
                )
            )
            elapsed = time.monotonic() - started
            child_pid = int(pid_path.read_text(encoding="utf-8"))
            self.assertFalse(result["ok"], result)
            self.assertEqual(result.get("failure_class"), "execution_failure")
            self.assertFalse(result.get("timeout", False), result)
            self.assertEqual(result.get("exit_code"), 0)
            self.assertIn("external-leader-success", result.get("stdout_raw", ""))
            self.assertIn("external-child-ready", result.get("stdout_raw", ""))
            self.assertLess(elapsed, 3.0)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
            self.assertFalse(lane.root.exists())
        finally:
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            shutil.rmtree(parent, ignore_errors=True)

    @unittest.skip("Darwin hard external lanes now fail closed before launch")
    def test_macos_rapid_successful_leaders_do_not_race_initial_scan(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        async def scenario(cwd: str) -> list[dict[str, object]]:
            results: list[dict[str, object]] = []
            for _ in range(40):
                plan = external.ExternalLaunchPlan(
                    argv=["/usr/bin/true"],
                    cwd=cwd,
                    env={"PATH": "/usr/bin:/bin"},
                    isolated=None,
                    isolation_meta={"enabled": False},
                    fallback_host_native=False,
                    invocation=None,
                    stdin_bytes=None,
                )
                results.append(
                    await external.run_external_subprocess(
                        plan=plan,
                        timeout_seconds=5.0,
                    )
                )
            return results

        with tempfile.TemporaryDirectory(prefix="rapid-external-leaders-") as tmp:
            results = asyncio.run(scenario(tmp))

        for index, result in enumerate(results):
            self.assertTrue(result["ok"], f"run {index}: {result}")
            self.assertEqual(result.get("exit_code"), 0, f"run {index}: {result}")
            cleanup = result.get("cleanup") or {}
            self.assertTrue(
                cleanup.get("group_absent"), f"run {index}: {cleanup}"
            )
            self.assertTrue(
                cleanup.get("descendants_absent"), f"run {index}: {cleanup}"
            )

    @unittest.skip("Darwin hard external lanes now fail closed before launch")
    def test_macos_env_scrubbing_leader_is_bound_before_initial_scan(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        script = "import os; os.execve('/bin/sleep', ['sleep', '30'], {})"
        with tempfile.TemporaryDirectory(prefix="scrubbed-external-leader-") as tmp:
            plan = external.ExternalLaunchPlan(
                argv=[sys.executable, "-c", script],
                cwd=tmp,
                env={"PATH": "/usr/bin:/bin"},
                isolated=None,
                isolation_meta={"enabled": False},
                fallback_host_native=False,
                invocation=None,
                stdin_bytes=None,
            )
            result = asyncio.run(
                external.run_external_subprocess(
                    plan=plan,
                    timeout_seconds=0.2,
                )
            )

        cleanup = result.get("cleanup") or {}
        worker_pid = cleanup.get("pid")
        try:
            self.assertFalse(result["ok"], result)
            self.assertEqual(result.get("failure_class"), "timeout", result)
            self.assertTrue(cleanup.get("group_absent"), cleanup)
            self.assertTrue(cleanup.get("descendants_absent"), cleanup)
            self.assertIn(worker_pid, cleanup.get("supervised_pids", []))
            with self.assertRaises(ProcessLookupError):
                os.kill(worker_pid, 0)
        finally:
            # Keep the regression self-cleaning if containment breaks again.
            if isinstance(worker_pid, int):
                try:
                    os.kill(worker_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                else:
                    try:
                        os.waitpid(worker_pid, 0)
                    except ChildProcessError:
                        pass

    def test_post_snapshot_validation_error_cleans_snapshot(self) -> None:
        from cobbler_runtime.context import scrub_environment
        from cobbler_runtime.dispatch_external import prepare_external_launch
        import cobbler_runtime.dispatch_external as external

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            (repo / "app.py").write_text("ok\n")
            _commit_all(repo)
            work = root / "work"
            work.mkdir()
            packet = work / "packet.json"
            prompt = work / "prompt.txt"
            packet.write_text("{}\n")
            prompt.write_text("task\n")
            attempt = EffectiveAttempt(
                profile="grok-build",
                adapter="grok-build",
                executable="grok",
                extra_args=("--permission-mode", "bypassPermissions"),
                input_contract="prompt-file",
                output_contract="grok-json",
                required=True,
            )
            spec = LaneSpec(
                lane_id="cleanup",
                role="reviewer",
                adapter="grok-build",
                profile="grok-build",
                required=True,
                attempts=(attempt,),
            )
            captured: list[IsolatedLane] = []
            real_create = external.create_tracked_snapshot

            def capture(specification: IsolationSpec) -> IsolatedLane:
                # This test owns prelaunch cleanup, not backend availability.
                lane = real_create(
                    replace(
                        specification,
                        require_fs_sandbox=False,
                        qualified_backend=None,
                    )
                )
                captured.append(lane)
                return lane

            scrub = scrub_environment({"PATH": os.environ.get("PATH", "/bin")})
            with mock.patch.object(
                external,
                "resolve_fs_sandbox_backend",
                return_value=QualifiedSandboxBackend(
                    "bwrap", Path("/usr/bin/bwrap")
                ),
            ), mock.patch.object(
                external,
                "create_tracked_snapshot",
                side_effect=capture,
            ), mock.patch.object(
                external,
                "_require_darwin_recursive_containment",
                return_value=None,
            ), mock.patch.object(
                external,
                "_require_linux_recursive_containment",
                return_value=None,
            ):
                with self.assertRaises(ValidationIssue):
                    prepare_external_launch(
                        spec=spec,
                        attempt=attempt,
                        attempt_index=0,
                        repo_root=repo,
                        packet_path=packet,
                        prompt_path=prompt,
                        packet_dict={},
                        redacted_task="task",
                        exact_secret_values=frozenset(),
                        grants=(),
                        scrub_env=scrub.env,
                        command_override=None,
                        parent_env=scrub.env,
                    )
            self.assertEqual(len(captured), 1)
            self.assertFalse(captured[0].root.exists())

    def test_caller_prelaunch_evidence_error_cleans_snapshot(self) -> None:
        from cobbler_runtime.context import build_context_packet
        from cobbler_runtime.dispatch import _HostEvidenceLedger, _run_single_attempt
        import cobbler_runtime.dispatch_external as external

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            _init_repo(repo)
            script = repo / "agent.py"
            script.write_text("print('{}')\n")
            _commit_all(repo)
            work = root / "work"
            work.mkdir()
            attempt = EffectiveAttempt(
                profile="custom",
                adapter="custom-cli",
                executable=sys.executable,
                input_contract="json-stdio",
                output_contract="custom-json-envelope",
                required=True,
            )
            spec = LaneSpec(
                lane_id="prelaunch-cleanup",
                role="reviewer",
                adapter="custom-cli",
                profile="custom",
                required=True,
                attempts=(attempt,),
            )
            packet = build_context_packet(
                task="review",
                role="reviewer",
                mode="read-only",
                scope="test",
                relevant_files=[],
                plan_path=None,
                head_sha=None,
                requested_model=None,
                profile="custom",
                adapter="custom-cli",
                run_id="prelaunch-cleanup",
            )
            captured: list[IsolatedLane] = []
            real_create = external.create_tracked_snapshot

            def capture(specification: IsolationSpec) -> IsolatedLane:
                # This test owns caller cleanup, not backend availability.
                lane = real_create(
                    replace(
                        specification,
                        require_fs_sandbox=False,
                        qualified_backend=None,
                    )
                )
                captured.append(lane)
                return lane

            with mock.patch.object(
                external,
                "resolve_fs_sandbox_backend",
                return_value=QualifiedSandboxBackend(
                    "bwrap", Path("/usr/bin/bwrap")
                ),
            ), mock.patch.object(
                external,
                "create_tracked_snapshot",
                side_effect=capture,
            ), mock.patch.object(
                external,
                "_require_darwin_recursive_containment",
                return_value=None,
            ), mock.patch.object(
                external,
                "_require_linux_recursive_containment",
                return_value=None,
            ), mock.patch(
                "cobbler_runtime.dispatch_lane_attempt.record_command_digests",
                side_effect=RuntimeError("evidence write failed"),
            ):
                with self.assertRaises(RuntimeError):
                    asyncio.run(
                        _run_single_attempt(
                            spec=spec,
                            attempt=attempt,
                            attempt_index=0,
                            packet=packet,
                            work_dir=work,
                            parent_env={"PATH": os.environ.get("PATH", "/bin")},
                            command_override=(sys.executable, str(script)),
                            repo_root=repo,
                            host_ledger=_HostEvidenceLedger("prelaunch-cleanup"),
                            task="review",
                        )
                    )
            self.assertEqual(len(captured), 1)
            self.assertFalse(captured[0].root.exists())

    @unittest.skip("Hard external lanes fail closed before launch")
    def test_cancel_during_subprocess_creation_reaps_and_cleans(self) -> None:
        from cobbler_runtime.dispatch_external import ExternalLaunchPlan, run_external_subprocess

        async def scenario() -> tuple[IsolatedLane, list[asyncio.subprocess.Process]]:
            root = Path(tempfile.mkdtemp(prefix="cancel-launch-"))
            lane = self._lane(root, backend="")
            plan = ExternalLaunchPlan(
                argv=[sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=str(lane.snapshot),
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                isolated=lane,
                isolation_meta={"enabled": True},
                fallback_host_native=False,
                invocation=None,
                stdin_bytes=None,
            )
            started = asyncio.Event()
            release = asyncio.Event()
            processes: list[asyncio.subprocess.Process] = []
            real_launch = asyncio.create_subprocess_exec

            async def delayed_launch(*args, **kwargs):
                started.set()
                await release.wait()
                proc = await real_launch(*args, **kwargs)
                if args and args[0] == sys.executable:
                    processes.append(proc)
                return proc

            with mock.patch.object(asyncio, "create_subprocess_exec", side_effect=delayed_launch):
                task = asyncio.create_task(
                    run_external_subprocess(plan=plan, timeout_seconds=30)
                )
                await started.wait()
                task.cancel()
                asyncio.get_running_loop().call_later(0.02, release.set)
                with self.assertRaises(asyncio.CancelledError):
                    await task
            return lane, processes

        lane, processes = asyncio.run(scenario())
        self.assertFalse(lane.root.exists())
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].returncode)

    @unittest.skip("Darwin hard external lanes now fail closed before launch")
    def test_post_launch_initial_scan_failure_reaps_and_cleans(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        async def scenario() -> tuple[IsolatedLane, list[asyncio.subprocess.Process]]:
            root = Path(tempfile.mkdtemp(prefix="scan-failure-launch-"))
            lane = self._lane(root, backend="")
            plan = external.ExternalLaunchPlan(
                argv=[sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=str(lane.snapshot),
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                isolated=lane,
                isolation_meta={"enabled": True},
                fallback_host_native=False,
                invocation=None,
                stdin_bytes=None,
            )
            processes: list[asyncio.subprocess.Process] = []
            real_launch = asyncio.create_subprocess_exec
            real_scan = external._DescendantSupervisor.scan
            scan_calls = 0

            async def capturing_launch(*args, **kwargs):
                proc = await real_launch(*args, **kwargs)
                if args and args[0] == sys.executable:
                    processes.append(proc)
                return proc

            async def fail_first_scan(supervisor):
                nonlocal scan_calls
                scan_calls += 1
                if scan_calls == 1:
                    raise OSError("fixture initial scan failure")
                return await real_scan(supervisor)

            with mock.patch.object(
                asyncio,
                "create_subprocess_exec",
                side_effect=capturing_launch,
            ), mock.patch.object(
                external._DescendantSupervisor,
                "scan",
                new=fail_first_scan,
            ):
                with self.assertRaisesRegex(OSError, "initial scan failure"):
                    await external.run_external_subprocess(
                        plan=plan,
                        timeout_seconds=30,
                    )
            return lane, processes

        lane, processes = asyncio.run(scenario())
        self.assertFalse(lane.root.exists())
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].returncode)

    @unittest.skip("Darwin hard external lanes now fail closed before launch")
    def test_cancel_during_post_success_cleanup_kills_detached_child(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        async def scenario() -> tuple[int, Path]:
            parent = Path(tempfile.mkdtemp(prefix="post-success-cancel-"))
            lane = self._lane(parent / "lane", backend="")
            pid_path = parent / "detached.pid"
            script = r'''
import os, pathlib, signal, sys, time
pid_path = pathlib.Path(sys.argv[1])
if os.fork() == 0:
    os.setsid()
    if os.fork():
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
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
'''
            plan = external.ExternalLaunchPlan(
                argv=[sys.executable, "-c", script, str(pid_path)],
                cwd=str(lane.snapshot),
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                isolated=lane,
                isolation_meta={"enabled": True},
                fallback_host_native=False,
                invocation=None,
                stdin_bytes=None,
            )
            entered_cleanup = asyncio.Event()
            real_terminate = external.terminate_process_group
            terminate_calls = 0

            async def cancel_first_cleanup(*args, **kwargs):
                nonlocal terminate_calls
                terminate_calls += 1
                if terminate_calls == 1:
                    entered_cleanup.set()
                    await asyncio.Event().wait()
                return await real_terminate(*args, **kwargs)

            with mock.patch.object(
                external,
                "terminate_process_group",
                side_effect=cancel_first_cleanup,
            ):
                task = asyncio.create_task(
                    external.run_external_subprocess(
                        plan=plan,
                        timeout_seconds=30,
                    )
                )
                await asyncio.wait_for(entered_cleanup.wait(), timeout=5)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            self.assertGreaterEqual(terminate_calls, 2)
            self.assertFalse(lane.root.exists())
            return int(pid_path.read_text(encoding="utf-8")), parent

        detached_pid, parent = asyncio.run(scenario())
        try:
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                try:
                    os.kill(detached_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail("detached child survived post-success cancellation")
        finally:
            try:
                os.kill(detached_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            shutil.rmtree(parent, ignore_errors=True)

    def test_reaped_bwrap_namespace_never_probes_or_signals_stale_pgid(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        class FakeProcess:
            pid = 4242
            returncode = None

            async def wait(self) -> int:
                self.returncode = 0
                return 0

            async def communicate(self, input=None) -> tuple[bytes, bytes]:
                return b"{}", b""

        root = Path(tempfile.mkdtemp(prefix="reaped-namespace-"))
        lane = self._lane(root, backend="")
        plan = external.ExternalLaunchPlan(
            argv=["fixture-agent"],
            cwd=str(lane.snapshot),
            env={"PATH": "/usr/bin:/bin"},
            isolated=lane,
            isolation_meta={"enabled": True},
            fallback_host_native=False,
            invocation=None,
            stdin_bytes=None,
        )
        terminate = mock.AsyncMock()
        with mock.patch.object(
            external,
            "_require_qualified_process_boundary",
            return_value="pid-namespace",
        ), mock.patch.object(
            asyncio,
            "create_subprocess_exec",
            new=mock.AsyncMock(return_value=FakeProcess()),
        ), mock.patch.object(
            external.os,
            "getpgid",
        ) as getpgid, mock.patch.object(
            external,
            "pgid_alive",
        ) as pgid_alive, mock.patch.object(
            external.os,
            "killpg",
        ) as killpg, mock.patch.object(
            external,
            "terminate_process_group",
            new=terminate,
        ):
            result = asyncio.run(
                external.run_external_subprocess(
                    plan=plan,
                    timeout_seconds=1.0,
                )
            )

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["cleanup"].get("pid_namespace_teardown"))
        self.assertTrue(result["cleanup"].get("descendants_absent"))
        getpgid.assert_not_called()
        pgid_alive.assert_not_called()
        killpg.assert_not_called()
        terminate.assert_not_awaited()
        self.assertFalse(lane.root.exists())

    def test_generic_linux_cleanup_never_signals_numeric_identity(self) -> None:
        import cobbler_runtime.dispatch_external as external  # noqa: PLC0415

        class FakeProcess:
            pid = 4242
            returncode = None

            async def wait(self) -> int:
                await asyncio.Event().wait()
                return 0

        started = time.monotonic()
        with mock.patch.object(
            external.sys,
            "platform",
            "linux",
        ), mock.patch.object(
            external.os,
            "killpg",
            return_value=None,
        ) as killpg, mock.patch.object(
            external,
            "pgid_alive",
        ) as pgid_alive, mock.patch.object(
            external.signal,
            "pidfd_send_signal",
            create=True,
        ) as pidfd_signal:
            cleanup = asyncio.run(
                external.terminate_process_group(
                    FakeProcess(),
                    grace_seconds=0.01,
                )
            )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)
        self.assertFalse(cleanup["reaped"], cleanup)
        self.assertFalse(cleanup["group_absent"], cleanup)
        self.assertEqual(
            cleanup["error"],
            "generation_bound_process_boundary_required",
        )
        killpg.assert_not_called()
        pgid_alive.assert_not_called()
        pidfd_signal.assert_not_called()

    def test_cleanup_error_blocks_lane_even_when_tree_was_removed(self) -> None:
        from cobbler_runtime.dispatch_external import (  # noqa: PLC0415
            ExternalLaunchPlan,
            run_external_subprocess,
        )

        root = Path(tempfile.mkdtemp(prefix="cleanup-error-"))
        lane = self._lane(root, backend="")
        plan = ExternalLaunchPlan(
            argv=[sys.executable, "-c", "print('ok')"],
            cwd=str(lane.snapshot),
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            isolated=lane,
            isolation_meta={"enabled": True},
            fallback_host_native=False,
            invocation=None,
            stdin_bytes=None,
        )

        def remove_then_error() -> None:
            shutil.rmtree(root)
            raise RuntimeError("cleanup audit failed")

        with mock.patch.object(lane, "cleanup", side_effect=remove_then_error):
            result = asyncio.run(
                run_external_subprocess(plan=plan, timeout_seconds=5.0)
            )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result.get("failure_class"), "isolation_failure")
        self.assertIn("isolation_cleanup_failed", result.get("reason", ""))
        self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
