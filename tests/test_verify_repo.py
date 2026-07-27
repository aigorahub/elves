"""Tests for the canonical repository verification command."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def load_verify():
    path = SCRIPTS / "verify_repo.py"
    spec = importlib.util.spec_from_file_location("verify_repo_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load verify_repo")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VerifyRepoUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verify = load_verify()

    def _approval_manifest(
        self,
        *,
        release: str = "2.1.0",
        reason: str = "Intentional fail-closed process exit contract.",
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "approvals": [
                {
                    "surface": "cli:cobbler_agents session list",
                    "release": release,
                    "reason": reason,
                    "plan_path": "docs/plans/release.md",
                }
            ],
        }

    def _write_approval_repo(
        self,
        root: Path,
        payload: dict[str, object],
        *,
        create_plan: bool = True,
        track_manifest: bool = True,
        track_plan: bool = True,
    ) -> None:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        plan = root / "docs" / "plans" / "release.md"
        if create_plan:
            plan.parent.mkdir(parents=True)
            plan.write_text("# Release plan\n", encoding="utf-8")
        manifest = root / "api-break-approvals.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        tracked: list[str] = []
        if track_manifest:
            tracked.append("api-break-approvals.json")
        if create_plan and track_plan:
            tracked.append("docs/plans/release.md")
        if tracked:
            subprocess.run(["git", "add", *tracked], cwd=root, check=True)

    def test_compile_scripts_succeeds_on_repo(self) -> None:
        ok, message = self.verify.compile_scripts(REPO_ROOT)
        self.assertTrue(ok, message)
        self.assertIn("compileall ok", message)

    def test_shell_and_json_gates(self) -> None:
        ok, message = self.verify.check_shell(REPO_ROOT)
        self.assertTrue(ok, message)
        ok, message = self.verify.check_json(REPO_ROOT)
        self.assertTrue(ok, message)

    def test_unit_test_failure_preserves_bounded_traceback_tail(self) -> None:
        failure = "\n".join(
            [f"noise {index}" for index in range(80)]
            + [
                "Traceback (most recent call last):",
                '  File "tests/test_example.py", line 12, in test_failure',
                '    raise ValueError("boom")',
                "ValueError: boom",
                "FAILED (errors=1)",
            ]
        )
        proc = subprocess.CompletedProcess(
            args=[sys.executable, "-m", "unittest"],
            returncode=1,
            stdout="\n".join(f"post-failure stdout {index}" for index in range(100)),
            stderr=failure,
        )
        with mock.patch.object(self.verify, "_run", return_value=proc):
            ok, message = self.verify.check_unit_tests(REPO_ROOT)

        self.assertFalse(ok)
        self.assertIn("bounded unittest failure tail", message)
        self.assertIn("Traceback (most recent call last):", message)
        self.assertIn("ValueError: boom", message)
        self.assertLess(len(message), self.verify.UNIT_TEST_FAILURE_MAX_CHARS + 500)

    def test_unit_test_failure_preserves_every_failure_block_before_noisy_stdout(self) -> None:
        failure = "\n".join(
            [
                "=" * 70,
                "ERROR: test_first (tests.test_example.ExampleTests.test_first)",
                "-" * 70,
                "Traceback (most recent call last):",
                '  File "tests/test_example.py", line 10, in test_first',
                '    raise RuntimeError("first root cause")',
                "RuntimeError: first root cause",
                "=" * 70,
                "FAIL: test_second (tests.test_example.ExampleTests.test_second)",
                "-" * 70,
                "Traceback (most recent call last):",
                '  File "tests/test_example.py", line 20, in test_second',
                "    self.assertEqual(1, 2)",
                "AssertionError: 1 != 2",
                "-" * 70,
                "Ran 2 tests in 0.1s",
                "FAILED (failures=1, errors=1)",
            ]
        )
        proc = subprocess.CompletedProcess(
            args=[sys.executable, "-m", "unittest"],
            returncode=1,
            stdout="\n".join(f"noisy stdout {index}" for index in range(200)),
            stderr=failure,
        )
        with mock.patch.object(self.verify, "_run", return_value=proc):
            ok, message = self.verify.check_unit_tests(REPO_ROOT)

        self.assertFalse(ok)
        self.assertIn("ERROR: test_first", message)
        self.assertIn("RuntimeError: first root cause", message)
        self.assertIn("FAIL: test_second", message)
        self.assertIn("AssertionError: 1 != 2", message)
        self.assertLess(len(message), self.verify.UNIT_TEST_FAILURE_MAX_CHARS + 500)

    def test_verification_child_does_not_inherit_host_secret_environment(self) -> None:
        sentinel = "verification-env-sentinel-27f40d"
        with mock.patch.dict(
            os.environ,
            {"ELVES_VERIFICATION_SECRET": sentinel},
            clear=False,
        ):
            proc = self.verify._run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os; "
                        "print(os.environ.get('ELVES_VERIFICATION_SECRET', 'absent'))"
                    ),
                ],
                cwd=REPO_ROOT,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "absent")
        self.assertNotIn(sentinel, proc.stdout + proc.stderr)

    def test_verification_failure_tail_redacts_exact_and_shared_secrets(self) -> None:
        sentinel = "arbitrary-verification-sentinel-c927a1"
        proc = subprocess.CompletedProcess(
            args=[sys.executable, "-m", "unittest"],
            returncode=1,
            stdout="",
            stderr=f"failure {sentinel} Bearer abcdefghijklmnop\nFAILED (errors=1)\n",
        )
        with (
            mock.patch.dict(
                os.environ,
                {"ELVES_VERIFICATION_SECRET": sentinel},
                clear=False,
            ),
            mock.patch.object(self.verify, "_run", return_value=proc),
        ):
            ok, message = self.verify.check_unit_tests(REPO_ROOT)

        self.assertFalse(ok)
        self.assertNotIn(sentinel, message)
        self.assertNotIn("Bearer abcdefghijklmnop", message)
        self.assertIn("[REDACTED:exact_grant]", message)
        self.assertIn("[REDACTED:bearer_token]", message)

    def test_final_readiness_rejects_skip_flags(self) -> None:
        for flag in ("--skip-tests", "--skip-smokes"):
            with self.subTest(flag=flag), self.assertRaises(SystemExit) as caught:
                self.verify.main(
                    [
                        "--repo-root",
                        str(REPO_ROOT),
                        "--final-readiness",
                        "--version",
                        "2.1.0",
                        flag,
                    ]
                )
            self.assertEqual(caught.exception.code, 2)

    def test_final_readiness_requires_explicit_session(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.verify.main(
                [
                    "--repo-root",
                    str(REPO_ROOT),
                    "--final-readiness",
                    "--version",
                    "2.1.0",
                ]
            )
        self.assertEqual(caught.exception.code, 2)

    def test_strict_modes_require_a_resolvable_version(self) -> None:
        # Strict modes default --version from the repo root's SKILL.md
        # frontmatter; a repo root without one still fails closed at parsing.
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("--ci", "--final-readiness"):
                stderr = io.StringIO()
                with self.subTest(mode=mode), self.assertRaises(
                    SystemExit
                ) as caught, contextlib.redirect_stderr(stderr):
                    self.verify.main(["--repo-root", tmp, mode])
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("require --version", stderr.getvalue())

    def test_strict_version_defaults_from_skill_frontmatter(self) -> None:
        # With a frontmatter version present, parsing proceeds past the version
        # requirement; --final-readiness then fails on the NEXT requirement
        # (--session), proving the default resolved without running any gate.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "SKILL.md").write_text(
                '---\nversion: "9.9.9"\n---\n', encoding="utf-8"
            )
            stderr = io.StringIO()
            with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(
                stderr
            ):
                self.verify.main(["--repo-root", tmp, "--final-readiness"])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("--session", stderr.getvalue())
            self.assertNotIn("require --version", stderr.getvalue())

    def test_landing_gate_passes_explicit_session_and_optional_plan(self) -> None:
        # Use a disposable session/plan pair. Product tips remove .elves-session.json
        # after Final Completion cleanup; the gate still must be unit-testable.
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}", stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "docs/plans/v2.1.0-delegated-worker-stabilization.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# plan\n", encoding="utf-8")
            session = root / ".elves" / "session.json"
            session.parent.mkdir(parents=True)
            session.write_text(
                json.dumps(
                    {
                        "plan_path": "docs/plans/v2.1.0-delegated-worker-stabilization.md",
                        "branch": "feat/landing-gate",
                    }
                ),
                encoding="utf-8",
            )
            provenance = [
                (True, session, "ok"),
                (True, plan, "ok"),
                (True, plan, "ok"),
            ]
            with (
                mock.patch.object(
                    self.verify, "_verified_repo_file", side_effect=provenance
                ) as verified_file,
                mock.patch.object(
                    self.verify, "_verify_session_identity", return_value=(True, "ok")
                ),
                mock.patch.object(self.verify, "_run", return_value=proc) as run,
            ):
                ok, message = self.verify.check_landing(
                    root,
                    session_path=Path(".elves/session.json"),
                    plan_path=Path(
                        "docs/plans/v2.1.0-delegated-worker-stabilization.md"
                    ),
                )

            self.assertTrue(ok, message)
            recorded_plan_call = verified_file.call_args_list[1]
            self.assertEqual(recorded_plan_call.kwargs["base"], root)
            command = run.call_args.args[0]
            self.assertIn("--session", command)
            self.assertIn("--plan", command)
            self.assertIn("--repo-root", command)
            self.assertIn("--json", command)

    def test_final_readiness_executes_landing_gate(self) -> None:
        success = (True, "ok")
        with (
            mock.patch.object(self.verify, "compile_scripts", return_value=success),
            mock.patch.object(self.verify, "check_shell", return_value=success),
            mock.patch.object(self.verify, "check_json", return_value=success),
            mock.patch.object(self.verify, "check_evidence_review_plan", return_value=success),
            mock.patch.object(self.verify, "check_consistency", return_value=success),
            mock.patch.object(self.verify, "check_release", return_value=success),
            mock.patch.object(self.verify, "check_public_api", return_value=success),
            mock.patch.object(self.verify, "check_landing", return_value=success) as landing,
            mock.patch.object(self.verify, "check_markdown_links", return_value=success),
            mock.patch.object(self.verify, "check_secret_patterns", return_value=success),
            mock.patch.object(self.verify, "check_unit_tests", return_value=success),
            mock.patch.object(self.verify, "check_installed_smokes", return_value=success),
            mock.patch.object(self.verify, "check_git_diff", return_value=success),
            mock.patch.object(self.verify, "check_preflight_cache", return_value=success),
        ):
            code = self.verify.main(
                [
                    "--repo-root",
                    str(REPO_ROOT),
                    "--final-readiness",
                    "--version",
                    "2.1.0",
                    "--session",
                    ".elves-session.json",
                    "--plan",
                    "docs/plans/plan.md",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        landing.assert_called_once_with(
            REPO_ROOT,
            session_path=Path(".elves-session.json"),
            plan_path=Path("docs/plans/plan.md"),
        )

    def test_ci_mode_is_strict_but_does_not_run_landing(self) -> None:
        success = (True, "ok")
        with (
            mock.patch.object(self.verify, "compile_scripts", return_value=success),
            mock.patch.object(self.verify, "check_shell", return_value=success),
            mock.patch.object(self.verify, "check_json", return_value=success),
            mock.patch.object(self.verify, "check_evidence_review_plan", return_value=success),
            mock.patch.object(self.verify, "check_consistency", return_value=success),
            mock.patch.object(self.verify, "check_release", return_value=success),
            mock.patch.object(self.verify, "check_public_api", return_value=success) as api,
            mock.patch.object(self.verify, "check_landing", return_value=success) as landing,
            mock.patch.object(self.verify, "check_markdown_links", return_value=success) as links,
            mock.patch.object(self.verify, "check_secret_patterns", return_value=success) as secrets,
            mock.patch.object(self.verify, "check_unit_tests", return_value=success),
            mock.patch.object(self.verify, "check_installed_smokes", return_value=success) as smokes,
            mock.patch.object(self.verify, "check_git_diff", return_value=success) as git_diff,
            mock.patch.object(self.verify, "check_preflight_cache", return_value=success) as cache,
        ):
            code = self.verify.main(
                [
                    "--repo-root",
                    str(REPO_ROOT),
                    "--ci",
                    "--version",
                    "2.1.0",
                    "--base-ref",
                    "base-before-sha",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        landing.assert_not_called()
        api.assert_called_once_with(
            REPO_ROOT,
            required=True,
            base_ref="base-before-sha",
            release_version="2.1.0",
        )
        links.assert_called_once_with(REPO_ROOT)
        secrets.assert_called_once_with(REPO_ROOT)
        smokes.assert_called_once_with(REPO_ROOT)
        git_diff.assert_called_once_with(
            REPO_ROOT,
            final_readiness=False,
            cumulative_required=True,
            base_ref="base-before-sha",
        )
        cache.assert_called_once_with(REPO_ROOT, final_readiness=True)

    def test_matching_tracked_api_break_approval_manifest_loads(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_approval_repo(root, self._approval_manifest())

            ok, surfaces, message = self.verify.load_api_break_approvals(
                root,
                release_version="2.1.0",
            )

        self.assertTrue(ok, message)
        self.assertEqual(surfaces, ["cli:cobbler_agents session list"])
        self.assertIn("release=2.1.0", message)

    def test_api_break_approval_manifest_rejects_invalid_provenance_and_scope(self) -> None:
        cases = {
            "malformed structure": {
                "payload": {"schema_version": 1, "approvals": "not-a-list"},
                "expected": "approvals must be a list",
            },
            "empty reason": {
                "payload": self._approval_manifest(reason="   "),
                "expected": "reason must be non-empty",
            },
            "stale release": {
                "payload": self._approval_manifest(release="2.0.0"),
                "expected": "stale for release 2.1.0",
            },
            "untracked manifest": {
                "payload": self._approval_manifest(),
                "track_manifest": False,
                "expected": "manifest must be tracked by Git",
            },
            "missing plan": {
                "payload": self._approval_manifest(),
                "create_plan": False,
                "expected": "plan is missing",
            },
            "untracked plan": {
                "payload": self._approval_manifest(),
                "track_plan": False,
                "expected": "plan must be tracked by Git",
            },
        }
        for label, case in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                self._write_approval_repo(
                    root,
                    case["payload"],
                    create_plan=case.get("create_plan", True),
                    track_manifest=case.get("track_manifest", True),
                    track_plan=case.get("track_plan", True),
                )

                ok, surfaces, message = self.verify.load_api_break_approvals(
                    root,
                    release_version="2.1.0",
                )

                self.assertFalse(ok)
                self.assertEqual(surfaces, [])
                self.assertIn(case["expected"], message)

    def test_check_public_api_passes_only_loaded_release_approvals(self) -> None:
        surface = "cli:cobbler_agents session list"
        result = {
            "ok": True,
            "action": "diffed",
            "diff": {"breaking": [surface]},
        }
        with (
            mock.patch.object(
                self.verify,
                "load_api_break_approvals",
                return_value=(True, [surface], "loaded one approval"),
            ),
            mock.patch(
                "cobbler_runtime.public_api_snapshot.compatibility_gate",
                return_value=result,
            ) as gate,
        ):
            ok, message = self.verify.check_public_api(
                REPO_ROOT,
                required=True,
                base_ref="origin/main",
                release_version="2.1.0",
            )

        self.assertTrue(ok, message)
        gate.assert_called_once_with(
            REPO_ROOT,
            required=True,
            approved_breaks=[surface],
            base_ref="origin/main",
        )

    def test_check_public_api_rejects_approval_absent_from_current_diff(self) -> None:
        surface = "cli:cobbler_agents session list"
        with (
            mock.patch.object(
                self.verify,
                "load_api_break_approvals",
                return_value=(True, [surface], "loaded one approval"),
            ),
            mock.patch(
                "cobbler_runtime.public_api_snapshot.compatibility_gate",
                return_value={"ok": True, "action": "diffed", "diff": {"breaking": []}},
            ),
        ):
            ok, message = self.verify.check_public_api(
                REPO_ROOT,
                required=True,
                base_ref="origin/main",
                release_version="2.1.0",
            )

        self.assertFalse(ok)
        self.assertIn("stale surfaces", message)

    def test_load_api_break_approvals_loads_unreleased_approvals(self) -> None:
        surface = "export:cobbler_runtime.BUILTIN_ADAPTER_NAMES"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_approval_repo(
                root,
                {
                    "schema_version": 1,
                    "approvals": [
                        {
                            "surface": surface,
                            "release": "Unreleased",
                            "reason": "Devin CLI worker adapter addition",
                            "plan_path": "docs/plans/devin-cli-worker-adapter.md",
                        }
                    ],
                },
                create_plan=True,
                track_manifest=True,
                track_plan=True,
            )
            plan = root / "docs" / "plans" / "devin-cli-worker-adapter.md"
            plan.write_text("# Devin CLI worker adapter\n", encoding="utf-8")
            subprocess.run(["git", "add", str(plan.relative_to(root))], cwd=root, check=True)

            ok, surfaces, message = self.verify.load_api_break_approvals(
                root,
                release_version="Unreleased",
            )

        self.assertTrue(ok, message)
        self.assertEqual(surfaces, [surface])
        self.assertIn("Unreleased", message)

    def test_explicit_release_rejects_stale_unreleased_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_approval_repo(
                root,
                {
                    "schema_version": 1,
                    "approvals": [
                        {
                            "surface": "export:cobbler_runtime.BUILTIN_ADAPTER_NAMES",
                            "release": "Unreleased",
                            "reason": "Devin CLI worker adapter addition",
                            "plan_path": "docs/plans/release.md",
                        }
                    ],
                },
                create_plan=True,
                track_manifest=True,
                track_plan=True,
            )

            ok, surfaces, message = self.verify.load_api_break_approvals(
                root,
                release_version="2.3.0",
            )

        self.assertFalse(ok)
        self.assertEqual(surfaces, [])
        self.assertIn("stale for release 2.3.0", message)

    def test_check_public_api_without_version_uses_unreleased_approvals(self) -> None:
        surface = "export:cobbler_runtime.BUILTIN_ADAPTER_NAMES"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_approval_repo(
                root,
                {
                    "schema_version": 1,
                    "approvals": [
                        {
                            "surface": surface,
                            "release": "Unreleased",
                            "reason": "Devin CLI worker adapter addition",
                            "plan_path": "docs/plans/release.md",
                        }
                    ],
                },
                create_plan=True,
                track_manifest=True,
                track_plan=True,
            )
            with mock.patch(
                "cobbler_runtime.public_api_snapshot.compatibility_gate"
            ) as gate:
                gate.return_value = {
                    "ok": True,
                    "action": "diffed",
                    "diff": {"breaking": [surface]},
                }
                ok, message = self.verify.check_public_api(
                    root,
                    required=True,
                    base_ref="origin/main",
                    release_version="Unreleased",
                )

        self.assertTrue(ok, message)
        gate.assert_called_once_with(
            root,
            required=True,
            approved_breaks=[surface],
            base_ref="origin/main",
        )

    def test_check_release_treats_unreleased_as_a_scope_not_a_semver(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Release checklist OK\n", stderr=""
        )
        with mock.patch.object(self.verify, "_run", return_value=completed) as run:
            ok, message = self.verify.check_release(Path("/repo"), "Unreleased")
        self.assertTrue(ok, message)
        command = run.call_args.args[0]
        self.assertIn("--allow-unreleased", command)
        self.assertNotIn("--version", command)

    def test_final_evidence_review_executes_concrete_mapped_checks(self) -> None:
        cache: dict[str, tuple[bool, str]] = {}
        with (
            mock.patch.object(
                self.verify,
                "_cumulative_changed_paths",
                return_value=(True, ["README.md"], "origin/main...HEAD"),
            ),
            mock.patch.object(
                self.verify, "check_unit_tests", return_value=(True, "tests ok")
            ) as unit,
            mock.patch.object(
                self.verify, "check_consistency", return_value=(True, "consistency ok")
            ) as consistency,
            mock.patch.object(
                self.verify, "check_release", return_value=(True, "release ok")
            ) as release,
            mock.patch.object(
                self.verify,
                "check_installed_smokes",
                return_value=(True, "smokes ok"),
            ) as smokes,
        ):
            ok, message = self.verify.check_evidence_review_plan(
                REPO_ROOT,
                execute_focused=True,
                final_readiness=True,
                release_version="2.0.0",
                result_cache=cache,
            )

        self.assertTrue(ok, message)
        unit.assert_called_once_with(REPO_ROOT)
        consistency.assert_called_once_with(REPO_ROOT)
        release.assert_called_once_with(REPO_ROOT, "2.0.0")
        smokes.assert_called_once_with(REPO_ROOT)
        self.assertEqual(
            set(cache),
            {
                "__review_broad__",
                "unit-tests",
                "consistency",
                "release",
                "installed-smokes",
            },
        )
        self.assertIn("full_unittest->unit-tests:ok", message)
        self.assertIn("installed_smokes->installed-smokes:ok", message)

    def test_runtime_review_runs_focused_modules_without_ordinary_broad_gate(self) -> None:
        cache: dict[str, tuple[bool, str]] = {}
        success = (True, "ok")
        with (
            mock.patch.object(
                self.verify,
                "_cumulative_changed_paths",
                return_value=(
                    True,
                    ["scripts/cobbler_runtime/audit.py"],
                    "origin/main...HEAD",
                ),
            ),
            mock.patch.object(
                self.verify, "check_unit_test_modules", return_value=success
            ) as focused,
            mock.patch.object(
                self.verify, "check_unit_tests", return_value=success
            ) as broad,
            mock.patch.object(self.verify, "compile_scripts", return_value=success),
            mock.patch.object(
                self.verify, "check_installed_smokes", return_value=success
            ),
        ):
            ok, message = self.verify.check_evidence_review_plan(
                REPO_ROOT,
                execute_focused=True,
                final_readiness=False,
                result_cache=cache,
            )

        self.assertTrue(ok, message)
        focused.assert_called_once()
        self.assertIn("tests.test_cobbler_agents_leases", focused.call_args.args[1])
        broad.assert_not_called()
        self.assertIn("reasons=", message)
        self.assertIn("selected=", message)
        self.assertIn("skipped=", message)

    def test_cobbler_agents_entrypoint_maps_to_relevant_focused_suites(self) -> None:
        modules = self.verify._focused_unit_modules(["scripts/cobbler_agents.py"])
        self.assertIn("tests.test_cobbler_agents_dispatch", modules)
        self.assertIn("tests.test_cobbler_agents_implement", modules)
        self.assertIn("tests.test_cobbler_agents_leases", modules)
        self.assertNotEqual(modules, ["tests.test_architecture_evidence"])

        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from cobbler_runtime.evidence_review import plan_review

        plan = plan_review(changed_paths=["scripts/cobbler_agents.py"])
        self.assertFalse(plan.broad_gate_required)
        self.assertIn("unit:runtime", plan.focused_checks)

    def test_docs_only_review_executes_links_without_full_unittest_alias(self) -> None:
        success = (True, "ok")
        with (
            mock.patch.object(
                self.verify,
                "_cumulative_changed_paths",
                return_value=(True, ["README.md"], "origin/main...HEAD"),
            ),
            mock.patch.object(
                self.verify, "check_markdown_links", return_value=success
            ) as links,
            mock.patch.object(
                self.verify, "check_unit_tests", return_value=success
            ) as broad,
            mock.patch.object(
                self.verify, "check_installed_smokes", return_value=success
            ) as smokes,
        ):
            ok, message = self.verify.check_evidence_review_plan(
                REPO_ROOT,
                execute_focused=True,
                final_readiness=False,
            )

        self.assertTrue(ok, message)
        links.assert_called_once_with(REPO_ROOT)
        broad.assert_not_called()
        smokes.assert_not_called()
        self.assertIn("broad=False", message)

    def test_exact_preflight_reuse_skips_live_broad_gates_early(self) -> None:
        success = (True, "ok")
        with (
            mock.patch.object(
                self.verify,
                "probe_preflight_reuse",
                return_value={"reuse": True, "reason": "identical_head_and_config"},
            ),
            mock.patch.object(self.verify, "compile_scripts", return_value=success),
            mock.patch.object(self.verify, "check_shell", return_value=success),
            mock.patch.object(self.verify, "check_json", return_value=success),
            mock.patch.object(
                self.verify, "check_evidence_review_plan", return_value=success
            ) as review,
            mock.patch.object(self.verify, "check_consistency", return_value=success),
            mock.patch.object(self.verify, "check_release", return_value=success),
            mock.patch.object(self.verify, "check_public_api", return_value=success),
            mock.patch.object(
                self.verify, "check_unit_tests", return_value=success
            ) as unit,
            mock.patch.object(
                self.verify, "check_installed_smokes", return_value=success
            ) as smokes,
            mock.patch.object(self.verify, "check_git_diff", return_value=success),
            mock.patch.object(self.verify, "check_preflight_cache", return_value=success),
        ):
            code = self.verify.main(
                ["--repo-root", str(REPO_ROOT), "--json"]
            )

        self.assertEqual(code, 0)
        self.assertFalse(review.call_args.kwargs["execute_focused"])
        unit.assert_not_called()
        smokes.assert_not_called()

    def test_untracked_change_invalidates_reuse_and_runs_its_focused_test(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Elves Tests"],
                cwd=root,
                check=True,
            )
            source = root / "runtime.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "runtime.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            ok, message = self.verify.check_preflight_cache(root)
            self.assertTrue(ok, message)

            (root / "new_untracked_test.py").write_text(
                "raise AssertionError('must run live gates')\n",
                encoding="utf-8",
            )
            self.assertFalse(self.verify.probe_preflight_reuse(root)["reuse"])

            success = (True, "ok")

            with (
                mock.patch.object(self.verify, "compile_scripts", return_value=success),
                mock.patch.object(self.verify, "check_shell", return_value=success),
                mock.patch.object(self.verify, "check_json", return_value=success),
                mock.patch.object(
                    self.verify,
                    "_cumulative_changed_paths",
                    return_value=(
                        True,
                        ["new_untracked_test.py"],
                        "main...HEAD + untracked",
                    ),
                ),
                mock.patch.object(self.verify, "check_consistency", return_value=success),
                mock.patch.object(self.verify, "check_release", return_value=success),
                mock.patch.object(self.verify, "check_public_api", return_value=success),
                mock.patch.object(
                    self.verify, "check_unit_tests", return_value=success
                ) as unit,
                mock.patch.object(
                    self.verify, "check_unit_test_modules", return_value=success
                ) as focused,
                mock.patch.object(
                    self.verify, "check_installed_smokes", return_value=success
                ) as smokes,
                mock.patch.object(self.verify, "check_git_diff", return_value=success),
                mock.patch.object(
                    self.verify, "check_preflight_cache", return_value=success
                ),
            ):
                code = self.verify.main(["--repo-root", str(root), "--json"])

            self.assertEqual(code, 0)
            focused.assert_called_once_with(root.resolve(), ["new_untracked_test"])
            unit.assert_not_called()
            smokes.assert_not_called()

    def test_non_broad_plan_keeps_default_verify_focused(self) -> None:
        success = (True, "ok")

        def focused_plan(*_args, **kwargs):
            kwargs["result_cache"]["__review_broad__"] = (False, "docs_only")
            return success

        with (
            mock.patch.object(
                self.verify,
                "probe_preflight_reuse",
                return_value={"reuse": False, "reason": "no_cache"},
            ),
            mock.patch.object(self.verify, "compile_scripts", return_value=success),
            mock.patch.object(self.verify, "check_shell", return_value=success),
            mock.patch.object(self.verify, "check_json", return_value=success),
            mock.patch.object(
                self.verify,
                "check_evidence_review_plan",
                side_effect=focused_plan,
            ),
            mock.patch.object(self.verify, "check_consistency", return_value=success),
            mock.patch.object(self.verify, "check_release", return_value=success),
            mock.patch.object(self.verify, "check_public_api", return_value=success),
            mock.patch.object(
                self.verify, "check_unit_tests", return_value=success
            ) as unit,
            mock.patch.object(
                self.verify, "check_installed_smokes", return_value=success
            ) as smokes,
            mock.patch.object(self.verify, "check_git_diff", return_value=success),
            mock.patch.object(
                self.verify, "check_preflight_cache", return_value=success
            ) as cache,
        ):
            code = self.verify.main(["--repo-root", str(REPO_ROOT), "--json"])

        self.assertEqual(code, 0)
        unit.assert_not_called()
        smokes.assert_not_called()
        self.assertFalse(cache.call_args.kwargs["record_live"])

    def test_final_diff_check_uses_default_branch_merge_base_range(self) -> None:
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            mock.patch.object(
                self.verify, "_resolve_default_branch_ref", return_value="origin/main"
            ),
            mock.patch.object(self.verify, "_merge_base", return_value="abc123"),
            mock.patch.object(self.verify, "_run", return_value=proc) as run,
        ):
            ok, message = self.verify.check_git_diff(
                REPO_ROOT,
                final_readiness=True,
            )

        self.assertTrue(ok, message)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["git", "diff", "--check", "abc123..HEAD"], commands)
        self.assertIn(["git", "diff", "--check", "--cached"], commands)
        self.assertIn(["git", "diff", "--check"], commands)
        self.assertIn(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            commands,
        )

    def test_final_diff_rejects_staged_and_untracked_work(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Elves Tests"], cwd=root, check=True
            )
            tracked = root / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            subprocess.run(["git", "switch", "-qc", "feature"], cwd=root, check=True)

            tracked.write_text("staged trailing whitespace   \n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            ok, message = self.verify.check_git_diff(root, final_readiness=True)
            self.assertFalse(ok)
            self.assertIn("index", message)

            subprocess.run(["git", "reset", "-q", "HEAD", "tracked.txt"], cwd=root, check=True)
            tracked.write_text("base\n", encoding="utf-8")
            (root / "untracked.txt").write_text("clean contents\n", encoding="utf-8")
            ok, message = self.verify.check_git_diff(root, final_readiness=True)
            self.assertFalse(ok)
            self.assertIn("not clean", message)

    def test_ci_diff_rejects_committed_trailing_whitespace_without_requiring_clean(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Elves Tests"], cwd=root, check=True)
            path = root / "tracked.txt"
            path.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            subprocess.run(["git", "switch", "-qc", "feature"], cwd=root, check=True)
            path.write_text("committed trailing whitespace   \n", encoding="utf-8")
            subprocess.run(["git", "commit", "-qam", "bad whitespace"], cwd=root, check=True)

            ok, message = self.verify.check_git_diff(
                root,
                final_readiness=False,
                cumulative_required=True,
            )

            self.assertFalse(ok)
            self.assertIn("cumulative", message)

    def test_cumulative_paths_include_index_worktree_and_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "tests@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Elves Tests"], cwd=root, check=True
            )
            (root / "base.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "base.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            subprocess.run(["git", "switch", "-qc", "feature"], cwd=root, check=True)
            (root / "base.txt").write_text("staged\n", encoding="utf-8")
            subprocess.run(["git", "add", "base.txt"], cwd=root, check=True)
            (root / "untracked.txt").write_text("new\n", encoding="utf-8")

            ok, paths, message = self.verify._cumulative_changed_paths(root)

            self.assertTrue(ok, message)
            self.assertEqual(paths, ["base.txt", "untracked.txt"])
            self.assertIn("index/worktree/untracked", message)

    def test_secret_scan_does_not_allow_file_wide_pattern_words(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "leak.py").write_text(
                'API_KEY="real-secret"\n# unrelated pattern and sentinel docs\n',
                encoding="utf-8",
            )
            ok, message = self.verify.check_secret_patterns(root)
            self.assertFalse(ok)
            self.assertIn("leak.py:1", message)

            (scripts / "leak.py").write_text(
                'PATTERN = "API_KEY="\nOPENROUTER_API_KEY=[REDACTED:value]\n',
                encoding="utf-8",
            )
            ok, message = self.verify.check_secret_patterns(root)
            self.assertTrue(ok, message)

    def test_secret_scan_catches_assignments_provider_tokens_cloud_keys_and_pem(self) -> None:
        cases = {
            "spaced assignment": 'OPENROUTER_API_KEY = "real-secret-value"\n',
            "yaml list assignment": "- API_KEY: real-secret-value\n",
            "generic auth assignment": "auth: real-secret-value\n",
            "credential assignment": "credential: real-secret-value\n",
            "hyphenated assignment": "API-KEY = real-secret-value\n",
            "sk project": "sk-proj-abcdefghijklmnopqrstuvwxyz\n",
            "sk service": "sk-svcacct-abcdefghijklmnopqrstuvwxyz\n",
            "github pat": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n",
            "github oauth": "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n",
            "github fine-grained": "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuvwxyz\n",
            "github server token": "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456\n",
            "aws": "AKIAABCDEFGHIJKLMNOP\n",
            "bearer": "Authorization: Bearer abcdefghijklmnop\n",
            "pem": (
                "-----BEGIN RSA PRIVATE KEY-----\n"
                "MIIEowIBAAKCAQEAsecretmaterial\n"
                "-----END RSA PRIVATE KEY-----\n"
            ),
        }
        for label, leaked in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                scripts = root / "scripts"
                scripts.mkdir()
                # The scanner imports its shared patterns from the real scripts
                # package already loaded by the test module.
                (scripts / "leak.md").write_text(leaked, encoding="utf-8")
                with mock.patch.dict(sys.modules, clear=False):
                    ok, message = self.verify.check_secret_patterns(root)
                self.assertFalse(ok, message)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "safe.md").write_text(
                "OPENROUTER_API_KEY = ${YOUR_API_KEY}\n"
                "TOKEN = [REDACTED:value]\n"
                "PATTERN = `API_KEY=`\n"
                "Authorization: Bearer YOUR_TOKEN_HERE\n"
                "AKIAIOSFODNN7EXAMPLE\n"
                "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
                "github_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
                "sk-proj-YOUR_API_KEY_PLACEHOLDER\n"
                "auth: gcloud-impersonation\n"
                "Authorization: Bearer <token>\n"
                "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
                encoding="utf-8",
            )
            (scripts / "safe.py").write_text(
                "darwin_audit_token=native.darwin_audit_token\n",
                encoding="utf-8",
            )
            ok, message = self.verify.check_secret_patterns(root)
            self.assertTrue(ok, message)

    def test_secret_scan_includes_tracked_env_templates_but_not_ignored_local_env(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            (root / ".gitignore").write_text(".env.local\n", encoding="utf-8")
            template = root / ".env.example"
            template.write_text('OPENAI_API_KEY = "real-secret-value"\n', encoding="utf-8")
            (root / ".env.local").write_text(
                'OPENAI_API_KEY = "expected-local-secret"\n', encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", ".gitignore", ".env.example"], cwd=root, check=True
            )

            ok, message = self.verify.check_secret_patterns(root)
            self.assertFalse(ok, message)
            self.assertIn(".env.example:1", message)

            template.write_text("OPENAI_API_KEY=${YOUR_API_KEY}\n", encoding="utf-8")
            ok, message = self.verify.check_secret_patterns(root)
            self.assertTrue(ok, message)

    def test_secret_scan_distinguishes_python_capability_references_from_literals(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scripts = root / "scripts"
            scripts.mkdir()
            candidate = scripts / "capability.py"
            candidate.write_text(
                "_AUDIT_EVIDENCE_TOKEN = object()\n"
                "def seal(payload):\n"
                "    return Evidence(payload, _token=_AUDIT_EVIDENCE_TOKEN)\n"
                "auth = native.auth\n"
                "MAX_GITHUB_TOKEN_BYTES = 64 * 1024\n",
                encoding="utf-8",
            )

            ok, message = self.verify.check_secret_patterns(root)

            self.assertTrue(ok, message)

            candidate.write_text(
                "def seal(payload):\n"
                '    return Evidence(payload, _token="real-secret-value")\n',
                encoding="utf-8",
            )

            ok, message = self.verify.check_secret_patterns(root)

            self.assertFalse(ok)
            self.assertIn("capability.py:2", message)

            candidate.write_text(
                "TOKEN = 1234567890123456\n",
                encoding="utf-8",
            )

            ok, message = self.verify.check_secret_patterns(root)

            self.assertFalse(ok)
            self.assertIn("capability.py:1", message)

            candidate.write_text(
                'helper = "${GH_TOKEN:-${GITHUB_TOKEN:-}}"\n',
                encoding="utf-8",
            )

            ok, message = self.verify.check_secret_patterns(root)

            self.assertTrue(ok, message)

            candidate.write_text(
                'helper = "${API_KEY:-real-secret-value}"\n',
                encoding="utf-8",
            )

            ok, message = self.verify.check_secret_patterns(root)

            self.assertFalse(ok)
            self.assertIn("capability.py:1", message)

            candidate.write_text(
                "token = (\n"
                "    # API_KEY=real-secret-value\n"
                "    SENTINEL\n"
                ")\n",
                encoding="utf-8",
            )

            ok, message = self.verify.check_secret_patterns(root)

            self.assertFalse(ok)
            self.assertIn("capability.py:2", message)

    def test_secret_scan_allows_github_id_token_permission_but_rejects_a_value(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            candidate = workflows / "pages.yml"
            candidate.write_text("permissions:\n  id-token: write\n", encoding="utf-8")

            ok, message = self.verify.check_secret_patterns(root)

            self.assertTrue(ok, message)

            candidate.write_text(
                "permissions:\n  id-token: real-secret-value\n",
                encoding="utf-8",
            )

            ok, message = self.verify.check_secret_patterns(root)

            self.assertFalse(ok)
            self.assertIn("pages.yml:2", message)

    def test_markdown_links_require_tracked_targets_and_real_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Elves Tests"], cwd=root, check=True)
            docs = root / "docs"
            docs.mkdir()
            target = docs / "guide.md"
            target.write_text(
                "# Setup\n\n# Setup\n\n<a id=\"custom-anchor\"></a>\n",
                encoding="utf-8",
            )
            readme = root / "README.md"
            readme.write_text(
                "[first](docs/guide.md#setup) [duplicate](docs/guide.md#setup-1) "
                "[custom](docs/guide.md#custom-anchor)\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "README.md", "docs/guide.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "docs"], cwd=root, check=True)

            ok, message = self.verify.check_markdown_links(root)
            self.assertTrue(ok, message)

            readme.write_text("[missing](docs/guide.md#does-not-exist)\n", encoding="utf-8")
            ok, message = self.verify.check_markdown_links(root)
            self.assertFalse(ok)
            self.assertIn("missing anchor", message)

            untracked = docs / "untracked.md"
            untracked.write_text("# Exists\n", encoding="utf-8")
            readme.write_text(
                "[untracked][local]\n\n[local]: docs/untracked.md\n",
                encoding="utf-8",
            )
            ok, message = self.verify.check_markdown_links(root)
            self.assertFalse(ok)
            self.assertIn("not shipped/tracked", message)

            target.write_text(
                "# Setup\n\n```md\n# Fake Anchor\n```\n"
                "<!-- # Commented Anchor -->\n",
                encoding="utf-8",
            )
            readme.write_text("[fake](docs/guide.md#fake-anchor)\n", encoding="utf-8")
            ok, message = self.verify.check_markdown_links(root)
            self.assertFalse(ok)
            self.assertIn("missing anchor", message)

            (root / "README.md").write_text(
                "setup: API_KEY=real-secret\n",
                encoding="utf-8",
            )
            ok, message = self.verify.check_secret_patterns(root)
            self.assertFalse(ok)
            self.assertIn("README.md:1", message)

            (root / "README.md").write_text(
                "setup: `API_KEY=` followed by `${YOUR_API_KEY}`\n",
                encoding="utf-8",
            )
            ok, message = self.verify.check_secret_patterns(root)
            self.assertTrue(ok, message)

    def test_failed_continue_run_never_records_passing_preflight(self) -> None:
        success = (True, "ok")
        with (
            mock.patch.object(self.verify, "compile_scripts", return_value=(False, "bad")),
            mock.patch.object(self.verify, "check_shell", return_value=success),
            mock.patch.object(self.verify, "check_json", return_value=success),
            mock.patch.object(self.verify, "check_evidence_review_plan", return_value=success),
            mock.patch.object(self.verify, "check_consistency", return_value=success),
            mock.patch.object(self.verify, "check_release", return_value=success),
            mock.patch.object(self.verify, "check_public_api", return_value=success),
            mock.patch.object(self.verify, "check_git_diff", return_value=success),
            mock.patch.object(self.verify, "check_preflight_cache", return_value=success) as cache,
        ):
            code = self.verify.main(
                [
                    "--repo-root",
                    str(REPO_ROOT),
                    "--continue-on-error",
                    "--skip-tests",
                    "--skip-smokes",
                    "--json",
                ]
            )

        self.assertEqual(code, 1)
        cache.assert_not_called()

    def test_session_and_plan_flags_remain_optional_outside_final_mode(self) -> None:
        success = (True, "ok")
        with (
            mock.patch.object(self.verify, "compile_scripts", return_value=success),
            mock.patch.object(self.verify, "check_shell", return_value=success),
            mock.patch.object(self.verify, "check_json", return_value=success),
            mock.patch.object(self.verify, "check_evidence_review_plan", return_value=success),
            mock.patch.object(self.verify, "check_consistency", return_value=success),
            mock.patch.object(self.verify, "check_release", return_value=success),
            mock.patch.object(self.verify, "check_public_api", return_value=success),
            mock.patch.object(self.verify, "check_git_diff", return_value=success),
            mock.patch.object(self.verify, "check_preflight_cache", return_value=success),
            mock.patch.object(self.verify, "check_landing", return_value=success) as landing,
        ):
            code = self.verify.main(
                [
                    "--repo-root",
                    str(REPO_ROOT),
                    "--session",
                    "missing-session.json",
                    "--plan",
                    "missing-plan.md",
                    "--skip-tests",
                    "--skip-smokes",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        landing.assert_not_called()


class BoundedGateRunnerTests(unittest.TestCase):
    """Gate subprocesses are bounded by construction (plan B9)."""

    def test_run_pins_stdin_closed(self) -> None:
        verify = load_verify()
        proc = verify._run(
            [sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"],
            cwd=Path.cwd(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "0")

    def test_run_timeout_surfaces_as_failing_step(self) -> None:
        verify = load_verify()
        proc = verify._run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=Path.cwd(),
            timeout=1.0,
        )
        self.assertEqual(proc.returncode, 124)
        self.assertIn("timed out after", proc.stderr)


if __name__ == "__main__":
    unittest.main()
