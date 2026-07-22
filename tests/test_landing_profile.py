"""Exact-HEAD project landing profile tests."""

from __future__ import annotations

import errno
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CLI = SCRIPTS / "landing_profile.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime import landing_profile as landing_profile_module  # noqa: E402
from cobbler_runtime.landing_profile import (  # noqa: E402
    MAX_PROFILE_BYTES,
    evaluate_landing_profile,
    load_landing_profile,
    path_matches_any,
    validate_landing_profile,
)


def always() -> dict[str, str]:
    return {"kind": "always"}


def path_check(
    *,
    check_id: str = "path-check",
    severity: str = "blocking",
    when: dict | None = None,
    paths: list[str] | None = None,
) -> dict:
    return {
        "id": check_id,
        "kind": "path_touched",
        "severity": severity,
        "when": when or always(),
        "paths": paths or ["scripts/**"],
    }


def profile(*checks: dict) -> dict:
    return {"schema_version": 1, "checks": list(checks)}


class LandingProfileLoaderTests(unittest.TestCase):
    def test_missing_profile_is_neutral_without_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            loaded = load_landing_profile(Path(raw))
            evaluated = evaluate_landing_profile(Path(raw))

        self.assertEqual(loaded.status, "missing")
        self.assertTrue(loaded.ok)
        self.assertEqual(evaluated.status, "missing")
        self.assertTrue(evaluated.green)
        self.assertFalse(evaluated.profile_present)

    def test_malformed_duplicate_non_object_and_invalid_utf8_fail_stably(self) -> None:
        cases = (
            (b"{", "profile_invalid_json"),
            (b'{"schema_version":1,"schema_version":1}', "profile_duplicate_key"),
            (b"[]", "profile_root_not_object"),
            (b"\xff", "profile_invalid_utf8"),
            (b'{"x":' + (b"[" * 40) + b"0" + (b"]" * 40) + b"}", "profile_json_too_deep"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                path = root / ".elves" / "landing-profile.json"
                path.parent.mkdir()
                path.write_bytes(payload)

                result = load_landing_profile(root)

                self.assertEqual(result.status, "invalid")
                self.assertEqual(result.diagnostic.code, expected)
                self.assertNotIn(str(root), result.diagnostic.message)

    def test_symlinked_parent_symlinked_profile_and_irregular_profile_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "target"
            target.mkdir()
            (target / "landing-profile.json").write_text("{}", encoding="utf-8")
            (root / ".elves").symlink_to(target, target_is_directory=True)
            self.assertEqual(load_landing_profile(root).diagnostic.code, "profile_parent_symlink")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            parent = root / ".elves"
            parent.mkdir()
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            (parent / "landing-profile.json").symlink_to(target)
            self.assertEqual(load_landing_profile(root).diagnostic.code, "profile_symlink")

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                path = root / ".elves" / "landing-profile.json"
                path.parent.mkdir()
                os.mkfifo(path)
                self.assertEqual(load_landing_profile(root).diagnostic.code, "profile_not_regular")

    def test_oversized_profile_fails_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / ".elves" / "landing-profile.json"
            path.parent.mkdir()
            path.write_bytes(b"x" * (MAX_PROFILE_BYTES + 1))
            result = load_landing_profile(root)

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.diagnostic.code, "profile_too_large")

    def test_unsupported_secure_open_platform_fails_closed_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / ".elves" / "landing-profile.json"
            path.parent.mkdir()
            path.write_text(json.dumps(profile(path_check())), encoding="utf-8")
            with mock.patch.object(os, "supports_dir_fd", frozenset()):
                result = load_landing_profile(root)

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.diagnostic.code, "profile_secure_open_unsupported")

    def test_secure_open_platform_error_fails_with_same_stable_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / ".elves" / "landing-profile.json"
            path.parent.mkdir()
            path.write_text(json.dumps(profile(path_check())), encoding="utf-8")
            with (
                mock.patch.object(
                    landing_profile_module.os,
                    "open",
                    side_effect=OSError(errno.ENOTSUP, "unsupported"),
                ) as secure_open,
                mock.patch.object(
                    landing_profile_module.os,
                    "supports_dir_fd",
                    {secure_open},
                ),
            ):
                result = load_landing_profile(root)

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.diagnostic.code, "profile_secure_open_unsupported")


class LandingProfileSchemaTests(unittest.TestCase):
    def test_declarative_kinds_and_conditions_validate(self) -> None:
        raw = profile(
            path_check(
                check_id="docs-touched",
                severity="advisory",
                when={"kind": "any_path_glob", "patterns": ["scripts/**"]},
                paths=["README.md", "references/**"],
            ),
            {
                "id": "release-follow-through",
                "kind": "post_merge_checklist",
                "when": always(),
                "description": "Verify the immutable release tag; draft but never post the announcement.",
            },
        )

        parsed, issues = validate_landing_profile(raw)

        self.assertEqual(issues, ())
        self.assertEqual([check.kind for check in parsed.checks], ["path_touched", "post_merge_checklist"])

    def test_command_and_every_argv_bearing_shape_share_stable_unsupported_diagnostic(self) -> None:
        cases = (
            {"id": "command", "kind": "command", "when": always(), "argv": ["true"]},
            {"kind": "command", "argv": []},
            {"id": "future", "kind": "llm_rubric", "when": always(), "argv": ["python3"]},
            {**path_check(), "argv": ["python3", "-c", "pass"]},
            {**path_check(), "timeout_seconds": 1},
            {**path_check(), "shell": "echo unsafe"},
        )
        for raw_check in cases:
            with self.subTest(raw_check=raw_check):
                parsed, issues = validate_landing_profile(profile(raw_check))
                self.assertIsNone(parsed)
                self.assertEqual(issues[0].code, "profile_executable_check_unsupported")

    def test_unsupported_keys_kinds_conditions_and_severity_fail(self) -> None:
        cases = (
            ({**profile(path_check()), "future": True}, "profile_unsupported_key"),
            ({"schema_version": True, "checks": [path_check()]}, "profile_schema_version_unsupported"),
            (profile({**path_check(), "future": True}), "profile_unsupported_key"),
            (profile({**path_check(), "kind": "llm_rubric"}), "profile_check_kind_unsupported"),
            (profile(path_check(when={"kind": "branch"})), "profile_condition_unsupported"),
            (profile(path_check(severity="optional")), "profile_severity_invalid"),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                parsed, issues = validate_landing_profile(raw)
                self.assertIsNone(parsed)
                self.assertEqual(issues[0].code, expected)

    def test_globs_are_repository_relative_and_separator_aware(self) -> None:
        self.assertTrue(path_matches_any("scripts/a.py", ["scripts/**"]))
        self.assertTrue(path_matches_any("scripts/nested/a.py", ["scripts/**"]))
        self.assertTrue(path_matches_any("README.md", ["*.md"]))
        self.assertFalse(path_matches_any("docs/README.md", ["*.md"]))
        self.assertTrue(path_matches_any("docs/README.md", ["**/*.md"]))

        parsed, issues = validate_landing_profile(profile(path_check(paths=["../README.md"])))
        self.assertIsNone(parsed)
        self.assertEqual(issues[0].code, "profile_path_unsafe")


class LandingProfileEvaluationTests(unittest.TestCase):
    def _run(self, root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()

    def _repo(self, raw: str, raw_profile: dict, *, changed_path: str = "scripts/feature.py") -> tuple[Path, str]:
        root = Path(raw)
        self._run(root, "init", "-q", "-b", "feature")
        self._run(root, "config", "user.email", "tests@example.invalid")
        self._run(root, "config", "user.name", "Elves Tests")
        (root / "README.md").write_text("base\n", encoding="utf-8")
        self._run(root, "add", "README.md")
        self._run(root, "commit", "-qm", "base")
        base = self._run(root, "rev-parse", "HEAD")

        profile_path = root / ".elves" / "landing-profile.json"
        profile_path.parent.mkdir()
        profile_path.write_text(json.dumps(raw_profile, indent=2) + "\n", encoding="utf-8")
        changed = root / changed_path
        changed.parent.mkdir(parents=True, exist_ok=True)
        changed.write_text("changed\n", encoding="utf-8")
        self._run(root, "add", ".elves/landing-profile.json", changed_path)
        self._run(root, "commit", "-qm", "feature")
        return root, base

    def test_blocking_advisory_skipped_and_post_merge_outcomes(self) -> None:
        raw_profile = profile(
            path_check(check_id="blocking-pass", paths=["scripts/**"]),
            path_check(check_id="advisory-fail", severity="advisory", paths=["docs/**"]),
            path_check(
                check_id="skipped",
                when={"kind": "any_path_glob", "patterns": ["src/**"]},
                paths=["README.md"],
            ),
            {
                "id": "post-merge",
                "kind": "post_merge_checklist",
                "when": always(),
                "description": "Draft the announcement; never post it.",
            },
        )
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, raw_profile)
            result = evaluate_landing_profile(root, base_ref=base)

        self.assertTrue(result.green)
        self.assertEqual(result.status, "passed")
        self.assertRegex(result.digest, r"^[0-9a-f]{64}$")
        self.assertEqual(
            [(item.id, item.status) for item in result.checks],
            [
                ("blocking-pass", "passed"),
                ("advisory-fail", "failed"),
                ("skipped", "skipped"),
                ("post-merge", "applicable"),
            ],
        )

    def test_blocking_failure_is_not_green(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, profile(path_check(paths=["docs/**"])))
            result = evaluate_landing_profile(root, base_ref=base)

        self.assertFalse(result.green)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.checks[0].code, "required_path_not_touched")

    def test_digest_is_deterministic_and_binds_head_base_profile_and_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, profile(path_check()))
            first = evaluate_landing_profile(root, base_ref=base)
            second = evaluate_landing_profile(root, base_ref=base)
            self.assertEqual(first.to_dict(), second.to_dict())
            self.assertEqual(first.digest, second.digest)

            self._run(root, "branch", "base-two", base)
            self._run(root, "checkout", "-q", "base-two")
            self._run(root, "commit", "--allow-empty", "-qm", "move base")
            moved_base = self._run(root, "rev-parse", "HEAD")
            self._run(root, "checkout", "-q", "feature")
            changed_base = evaluate_landing_profile(root, base_ref=moved_base)
            self.assertNotEqual(first.digest, changed_base.digest)
            self.assertEqual(first.head, changed_base.head)

            path = root / ".elves" / "landing-profile.json"
            changed_profile = json.loads(path.read_text(encoding="utf-8"))
            changed_profile["checks"][0]["severity"] = "advisory"
            path.write_text(json.dumps(changed_profile), encoding="utf-8")
            dirty = evaluate_landing_profile(root, base_ref=base)
            self.assertFalse(dirty.green)
            self.assertEqual(dirty.diagnostics[0].code, "profile_differs_from_head")

    def test_expected_head_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, profile(path_check()))
            mismatch = evaluate_landing_profile(root, base_ref=base, expected_head="0" * 40)

        self.assertEqual(mismatch.status, "invalid")
        self.assertEqual(mismatch.diagnostics[0].code, "profile_head_mismatch")

    def test_executable_profile_is_rejected_before_any_process_launch(self) -> None:
        executable = profile(
            {
                "id": "detached-child",
                "kind": "command",
                "severity": "blocking",
                "when": always(),
                "argv": ["python3", "-c", "spawn detached child"],
            }
        )
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, executable)
            with mock.patch.object(landing_profile_module.subprocess, "Popen") as launch:
                result = evaluate_landing_profile(root, base_ref=base)

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.diagnostics[0].code, "profile_executable_check_unsupported")
        launch.assert_not_called()
        self.assertFalse(hasattr(landing_profile_module, "_run_bounded"))
        self.assertFalse(hasattr(landing_profile_module, "_terminate_process_group"))

    def test_fixed_git_timeout_cleanup_uses_cross_platform_process_kill(self) -> None:
        process = mock.Mock()
        process.stdout = io.BytesIO(b"")
        process.returncode = None
        process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="git", timeout=30),
            0,
        ]
        with mock.patch.object(landing_profile_module.subprocess, "Popen", return_value=process):
            result = landing_profile_module._run_git(Path.cwd(), "rev-parse", "HEAD")

        self.assertEqual(result.returncode, 124)
        process.kill.assert_called_once_with()

    def test_thin_cli_emits_deterministic_json_from_unrelated_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, profile(path_check()))
            command = [
                sys.executable,
                str(CLI),
                "check",
                "--repo-root",
                str(root),
                "--base",
                base,
                "--head",
                self._run(root, "rev-parse", "HEAD"),
                "--json",
            ]
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            first = subprocess.run(command, cwd=root.parent, env=env, text=True, capture_output=True)
            second = subprocess.run(command, cwd=root.parent, env=env, text=True, capture_output=True)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        payload = json.loads(first.stdout)
        self.assertTrue(payload["green"])
        self.assertEqual(payload["status"], "passed")
        self.assertNotIn(str(root), first.stdout)


if __name__ == "__main__":
    unittest.main()
