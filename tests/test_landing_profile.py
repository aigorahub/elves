"""Exact-HEAD project landing profile tests."""

from __future__ import annotations

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

from cobbler_runtime.landing_profile import (  # noqa: E402
    MAX_PROFILE_BYTES,
    evaluate_landing_profile,
    load_landing_profile,
    path_matches_any,
    validate_landing_profile,
)


def always() -> dict[str, str]:
    return {"kind": "always"}


def command_check(
    *,
    check_id: str = "command-check",
    argv: list[str] | None = None,
    severity: str = "blocking",
    timeout_seconds: int = 10,
    when: dict | None = None,
) -> dict:
    return {
        "id": check_id,
        "kind": "command",
        "severity": severity,
        "when": when or always(),
        "argv": argv or ["python3", "-c", "print('ok')"],
        "timeout_seconds": timeout_seconds,
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
            self.assertEqual(
                load_landing_profile(root).diagnostic.code,
                "profile_parent_symlink",
            )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            parent = root / ".elves"
            parent.mkdir()
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            (parent / "landing-profile.json").symlink_to(target)
            self.assertEqual(
                load_landing_profile(root).diagnostic.code,
                "profile_symlink",
            )

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                path = root / ".elves" / "landing-profile.json"
                path.parent.mkdir()
                os.mkfifo(path)
                self.assertEqual(
                    load_landing_profile(root).diagnostic.code,
                    "profile_not_regular",
                )

    def test_oversized_profile_fails_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / ".elves" / "landing-profile.json"
            path.parent.mkdir()
            path.write_bytes(b"x" * (MAX_PROFILE_BYTES + 1))

            result = load_landing_profile(root)

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.diagnostic.code, "profile_too_large")


class LandingProfileSchemaTests(unittest.TestCase):
    def test_minimal_kinds_and_conditions_validate(self) -> None:
        raw = profile(
            command_check(),
            {
                "id": "docs-touched",
                "kind": "path_touched",
                "severity": "advisory",
                "when": {
                    "kind": "any_path_glob",
                    "patterns": ["scripts/**"],
                },
                "paths": ["README.md", "references/**"],
            },
            {
                "id": "release-follow-through",
                "kind": "post_merge_checklist",
                "when": always(),
                "description": "Verify the immutable release tag; draft but never post the announcement.",
            },
        )

        parsed, issues = validate_landing_profile(raw)

        self.assertEqual(issues, ())
        self.assertEqual([check.kind for check in parsed.checks], [
            "command",
            "path_touched",
            "post_merge_checklist",
        ])

    def test_unsupported_keys_kinds_conditions_severity_and_shell_fail(self) -> None:
        cases = (
            ({**profile(command_check()), "future": True}, "profile_unsupported_key"),
            ({"schema_version": True, "checks": [command_check()]}, "profile_schema_version_unsupported"),
            (profile({**command_check(), "future": True}), "profile_unsupported_key"),
            (profile({**command_check(), "kind": "llm_rubric"}), "profile_check_kind_unsupported"),
            (profile(command_check(when={"kind": "branch"})), "profile_condition_unsupported"),
            (profile(command_check(severity="optional")), "profile_severity_invalid"),
            (profile(command_check(argv=["sh", "-c", "true"])), "profile_shell_forbidden"),
            (profile(command_check(argv=["python3", "../outside.py"])), "profile_path_unsafe"),
            (profile(command_check(argv=["git", "push", "origin", "main"])), "profile_authority_command_forbidden"),
            (profile(command_check(argv=["gh", "release", "create", "v1"])), "profile_authority_command_forbidden"),
            (profile(command_check(argv=["python3", "scripts/elves_landing_check.py"])), "profile_recursive_command_forbidden"),
            (
                profile(
                    {
                        "id": "secret-description",
                        "kind": "post_merge_checklist",
                        "when": always(),
                        "description": "token=super-secret-material-12345",
                    }
                ),
                "profile_string_secret_like",
            ),
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

        parsed, issues = validate_landing_profile(
            profile(
                {
                    "id": "unsafe",
                    "kind": "path_touched",
                    "severity": "blocking",
                    "when": always(),
                    "paths": ["../README.md"],
                }
            )
        )
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

    def test_blocking_advisory_skipped_path_command_and_post_merge_results(self) -> None:
        raw_profile = profile(
            command_check(check_id="command-pass"),
            command_check(
                check_id="advisory-fail",
                argv=["python3", "-c", "raise SystemExit(7)"],
                severity="advisory",
            ),
            {
                "id": "docs-pass",
                "kind": "path_touched",
                "severity": "blocking",
                "when": {"kind": "any_path_glob", "patterns": ["scripts/**"]},
                "paths": ["scripts/**"],
            },
            {
                "id": "skipped",
                "kind": "path_touched",
                "severity": "blocking",
                "when": {"kind": "any_path_glob", "patterns": ["src/**"]},
                "paths": ["README.md"],
            },
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
                ("command-pass", "passed"),
                ("advisory-fail", "failed"),
                ("docs-pass", "passed"),
                ("skipped", "skipped"),
                ("post-merge", "applicable"),
            ],
        )

    def test_blocking_failure_is_not_green(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(
                raw,
                profile(command_check(argv=["python3", "-c", "raise SystemExit(3)"])),
            )
            result = evaluate_landing_profile(root, base_ref=base)

        self.assertFalse(result.green)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.checks[0].exit_code, 3)

    def test_environment_is_scrubbed_and_output_is_bounded_and_redacted(self) -> None:
        token = "landing-profile-secret-value-12345"
        code = (
            "import os; from pathlib import Path; "
            "print(os.environ.get('LANDING_TEST_API_TOKEN', 'missing')); "
            "print(Path('secret.txt').read_text()); print('x' * 70000)"
        )
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(
                raw,
                profile(command_check(argv=["python3", "-c", code])),
                changed_path="secret.txt",
            )
            (root / "secret.txt").write_text(token, encoding="utf-8")
            self._run(root, "add", "secret.txt")
            self._run(root, "commit", "--amend", "--no-edit", "-q")
            with mock.patch.dict(os.environ, {"LANDING_TEST_API_TOKEN": token}):
                result = evaluate_landing_profile(root, base_ref=base)

        output = result.checks[0].output
        self.assertTrue(result.green)
        self.assertIn("missing", output)
        self.assertNotIn(token, output)
        self.assertIn("[REDACTED:", output)
        self.assertTrue(result.checks[0].output_truncated)
        self.assertLessEqual(len(output), 4001)

    def test_timeout_is_hard_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(
                raw,
                profile(
                    command_check(
                        argv=["python3", "-c", "import time; time.sleep(5)"],
                        timeout_seconds=1,
                    )
                ),
            )
            result = evaluate_landing_profile(root, base_ref=base)

        self.assertFalse(result.green)
        self.assertEqual(result.checks[0].code, "command_timed_out")
        self.assertEqual(result.checks[0].exit_code, 124)

    def test_digest_is_deterministic_and_binds_head_base_profile_and_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, profile(command_check()))
            first = evaluate_landing_profile(root, base_ref=base)
            second = evaluate_landing_profile(root, base_ref=base)
            self.assertEqual(first.digest, second.digest)

            self._run(root, "branch", "base-two", base)
            self._run(root, "checkout", "-q", "base-two")
            self._run(root, "commit", "--allow-empty", "-qm", "move base")
            moved_base = self._run(root, "rev-parse", "HEAD")
            self._run(root, "checkout", "-q", "feature")
            changed_base = evaluate_landing_profile(root, base_ref=moved_base)
            self.assertNotEqual(first.digest, changed_base.digest)
            self.assertEqual(first.head, changed_base.head)
            self.assertEqual(first.merge_base, changed_base.merge_base)

            path = root / ".elves" / "landing-profile.json"
            raw_profile = json.loads(path.read_text(encoding="utf-8"))
            raw_profile["checks"][0]["timeout_seconds"] = 11
            path.write_text(json.dumps(raw_profile), encoding="utf-8")
            dirty = evaluate_landing_profile(root, base_ref=base)
            self.assertFalse(dirty.green)
            self.assertEqual(dirty.diagnostics[0].code, "profile_differs_from_head")

    def test_digest_excludes_bounded_raw_output(self) -> None:
        code = "from pathlib import Path; print(Path('runtime-output.txt').read_text())"
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(
                raw,
                profile(command_check(argv=["python3", "-c", code])),
            )
            runtime_output = root / "runtime-output.txt"
            runtime_output.write_text("first\n", encoding="utf-8")
            first = evaluate_landing_profile(root, base_ref=base)
            runtime_output.write_text("second\n", encoding="utf-8")
            second = evaluate_landing_profile(root, base_ref=base)

        self.assertEqual(first.status, "passed")
        self.assertEqual(second.status, "passed")
        self.assertNotEqual(first.checks[0].output, second.checks[0].output)
        self.assertEqual(first.digest, second.digest)

    def test_expected_head_mismatch_and_head_move_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, profile(command_check()))
            mismatch = evaluate_landing_profile(
                root,
                base_ref=base,
                expected_head="0" * 40,
            )
            self.assertEqual(mismatch.diagnostics[0].code, "profile_head_mismatch")

        with tempfile.TemporaryDirectory() as raw:
            moving_code = (
                "import subprocess; subprocess.run("
                "['git', 'commit', '--allow-empty', '-m', 'profile moved head'], check=True)"
            )
            moving = command_check(argv=["python3", "-c", moving_code])
            root, base = self._repo(raw, profile(moving))
            moved = evaluate_landing_profile(root, base_ref=base)
            self.assertEqual(moved.status, "invalid")
            self.assertEqual(moved.diagnostics[0].code, "profile_head_changed")

        with tempfile.TemporaryDirectory() as raw:
            mutating = command_check(
                argv=[
                    "python3",
                    "-c",
                    "from pathlib import Path; Path('created.txt').write_text('changed')",
                ]
            )
            root, base = self._repo(raw, profile(mutating))
            mutated = evaluate_landing_profile(root, base_ref=base)
            self.assertEqual(mutated.status, "invalid")
            self.assertEqual(mutated.diagnostics[0].code, "profile_repository_mutated")

    def test_thin_cli_emits_deterministic_json_from_unrelated_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, base = self._repo(raw, profile(command_check()))
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
            first = subprocess.run(
                command,
                cwd=root.parent,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            second = subprocess.run(
                command,
                cwd=root.parent,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        payload = json.loads(first.stdout)
        self.assertTrue(payload["green"])
        self.assertEqual(payload["status"], "passed")
        self.assertNotIn(str(root), first.stdout)


if __name__ == "__main__":
    unittest.main()
