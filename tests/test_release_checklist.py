from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "release_checklist.py"


def load_release_checklist_module():
    spec = importlib.util.spec_from_file_location("release_checklist_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load release_checklist module for tests")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReleaseChecklistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.release_checklist = load_release_checklist_module()

    def configure_temp_repo(self, tmpdir: str, version: str = "1.15.0") -> Path:
        repo = Path(tmpdir)
        (repo / "SKILL.md").write_text(f'---\nmetadata:\n  version: "{version}"\n---\n')
        (repo / "AGENTS.md").write_text(f'---\nversion: "{version}"\n---\n')
        (repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n"
            "## [Unreleased]\n\n"
            f"## [{version}] - 2026-06-14\n\n"
            "- Released.\n"
        )
        tests_dir = repo / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_sync_installed_skills.py").write_text(
            f'fixture current version "{version}"\n'
        )
        return repo

    def configure_full_runtime_tree(self, repo: Path) -> None:
        for alias_name in self.release_checklist.EXPECTED_CLAUDE_ALIASES:
            alias = repo / "aliases" / "claude" / alias_name
            alias.mkdir(parents=True)
            (alias / "SKILL.md").write_text(
                f"---\nname: {alias_name}\n---\n",
                encoding="utf-8",
            )

        package = repo / "scripts" / "cobbler_runtime"
        package.mkdir(parents=True)
        for name in ("__init__.py", "config.py", "dispatch.py", "schema.py", "setup.py"):
            (package / name).write_text(f'"""{name}."""\n', encoding="utf-8")
        for helper in self.release_checklist.REQUIRED_RUNTIME_HELPERS:
            path = repo / helper
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'"""{helper.name}."""\n', encoding="utf-8")

    def test_release_checklist_passes_when_release_surfaces_are_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir)

            result = self.release_checklist.build_release_checklist(repo, base_ref=None)

        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])

    def test_read_text_uses_utf8_encoding(self) -> None:
        path = mock.Mock()
        path.read_text.return_value = "ok"

        self.assertEqual(self.release_checklist.read_text(path), "ok")

        path.read_text.assert_called_once_with(encoding="utf-8")

    def test_frontmatter_version_missing_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.md"

            self.assertIsNone(self.release_checklist.read_frontmatter_version(missing))

    def test_release_checklist_fails_when_changelog_latest_release_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir, version="1.16.0")
            (repo / "CHANGELOG.md").write_text(
                "# Changelog\n\n"
                "## [Unreleased]\n\n"
                "## [1.15.0] - 2026-06-14\n\n"
                "- Released.\n"
            )

            result = self.release_checklist.build_release_checklist(repo, base_ref=None)

        self.assertFalse(result.ok)
        self.assertIn(
            "CHANGELOG.md: latest release `1.15.0` does not match `1.16.0`",
            result.failures,
        )

    def test_release_checklist_fails_when_unreleased_content_was_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir)
            changelog = (repo / "CHANGELOG.md").read_text()
            (repo / "CHANGELOG.md").write_text(
                changelog.replace("## [Unreleased]\n\n", "## [Unreleased]\n\n- Pending.\n\n")
            )

            result = self.release_checklist.build_release_checklist(repo, base_ref=None)

        self.assertFalse(result.ok)
        self.assertIn(
            (
                "CHANGELOG.md: `## [Unreleased]` still has content; "
                "promote it under the release heading"
            ),
            result.failures,
        )

    def test_release_checklist_can_warn_for_unreleased_content_on_development_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir)
            changelog = (repo / "CHANGELOG.md").read_text()
            (repo / "CHANGELOG.md").write_text(
                changelog.replace("## [Unreleased]\n\n", "## [Unreleased]\n\n- Pending.\n\n")
            )

            result = self.release_checklist.build_release_checklist(
                repo,
                base_ref=None,
                allow_unreleased=True,
            )

        self.assertTrue(result.ok)
        self.assertIn(
            (
                "CHANGELOG.md: `## [Unreleased]` still has content; "
                "promote it under the release heading"
            ),
            result.warnings,
        )

    def test_render_result_labels_warning_only_runs_without_plain_ok(self) -> None:
        result = self.release_checklist.ChecklistResult(
            version="1.15.0",
            warnings=["Review newly added human-facing surfaces"],
        )

        rendered = self.release_checklist.render_result(result)

        self.assertIn("WARNINGS", rendered)
        self.assertIn("Release checklist completed with warnings", rendered)
        self.assertNotIn("Release checklist OK", rendered)

    def test_release_checklist_fails_when_current_version_example_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir, version="1.16.0")
            (repo / "tests" / "test_sync_installed_skills.py").write_text(
                'fixture stale version "1.15.0"\n'
            )

            result = self.release_checklist.build_release_checklist(repo, base_ref=None)

        self.assertFalse(result.ok)
        self.assertIn(
            "tests/test_sync_installed_skills.py: missing current version example `1.16.0`",
            result.failures,
        )

    def test_release_checklist_accepts_current_version_source_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir, version="1.16.0")
            (repo / "tests" / "test_sync_installed_skills.py").write_text(
                'version = self.sync.read_version(REPO_ROOT / "SKILL.md")\n'
            )

            result = self.release_checklist.build_release_checklist(repo, base_ref=None)

        self.assertTrue(result.ok)

    def test_release_checklist_requires_workspace_guard_in_full_runtime_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir)
            self.configure_full_runtime_tree(repo)
            (repo / "scripts" / "workspace_guard.py").unlink()

            result = self.release_checklist.build_release_checklist(repo, base_ref=None)

        self.assertFalse(result.ok)
        self.assertIn(
            "scripts/workspace_guard.py: missing required runtime helper",
            result.failures,
        )

    def test_release_checklist_compiles_all_required_runtime_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir)
            self.configure_full_runtime_tree(repo)

            result = self.release_checklist.build_release_checklist(repo, base_ref=None)

        self.assertTrue(result.ok, result.failures)
        self.assertIn(
            (
                "Alias inventory (11) + required runtime helpers "
                "(acceptance_contract.py, openrouter_lens.py, workspace_guard.py, "
                "worktree_gc.py, provider_supervisor.py) "
                "+ recursive compile smoke: OK"
            ),
            result.notes,
        )

    def test_release_checklist_compile_smoke_leaves_no_source_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir)
            self.configure_full_runtime_tree(repo)

            result = self.release_checklist.build_release_checklist(repo, base_ref=None)

            self.assertTrue(result.ok, result.failures)
            self.assertEqual(list(repo.rglob("__pycache__")), [])
            self.assertEqual(list(repo.rglob("*.pyc")), [])

    def test_release_sweep_classifies_release_contract_operator_and_guide_docs(self) -> None:
        for path in (
            "api-break-approvals.json",
            "docs/cobbler.md",
            "PRODUCT.md",
            "guide/index.html",
        ):
            with self.subTest(path=path):
                self.assertTrue(self.release_checklist.is_human_facing_surface(path))

    def test_parse_name_status_uses_new_path_for_renames(self) -> None:
        changes = self.release_checklist.parse_name_status(
            "M\tREADME.md\n"
            "A\treferences/new-guide.md\n"
            "R100\told.md\treferences/new-name.md\n"
            "C100\told.md\treferences/copied-name.md\n"
        )

        self.assertEqual(
            [(change.status, change.path) for change in changes],
            [
                ("M", "README.md"),
                ("A", "references/new-guide.md"),
                ("R100", "references/new-name.md"),
                ("C100", "references/copied-name.md"),
            ],
        )

    def test_changed_files_since_reports_missing_git_without_crashing(self) -> None:
        with mock.patch.object(
            self.release_checklist.subprocess,
            "run",
            side_effect=FileNotFoundError,
        ):
            changes, warning = self.release_checklist.changed_files_since(
                Path("/repo"),
                "origin/main",
            )

        self.assertEqual(changes, [])
        self.assertEqual(warning, "git command not found in PATH")

    def test_changed_files_since_decodes_git_output_as_utf8(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="M\tREADME.md\n", stderr="")
        with mock.patch.object(
            self.release_checklist.subprocess,
            "run",
            return_value=completed,
        ) as run:
            changes, warning = self.release_checklist.changed_files_since(
                Path("/repo"),
                "origin/main",
            )

        self.assertIsNone(warning)
        self.assertEqual([(change.status, change.path) for change in changes], [("M", "README.md")])
        run.assert_called_once_with(
            ["git", "diff", "--name-status", "origin/main...HEAD"],
            cwd=Path("/repo"),
            check=False,
            stdout=self.release_checklist.subprocess.PIPE,
            stderr=self.release_checklist.subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def test_release_checklist_warns_for_added_human_facing_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.configure_temp_repo(tmpdir)
            git_changes = [
                self.release_checklist.NameStatusChange("A", "references/new-guide.md"),
                self.release_checklist.NameStatusChange("M", "scripts/internal.py"),
            ]

            with mock.patch.object(
                self.release_checklist,
                "changed_files_since",
                return_value=(git_changes, None),
            ):
                result = self.release_checklist.build_release_checklist(
                    repo,
                    base_ref="origin/main",
                )

        self.assertTrue(result.ok)
        self.assertIn(
            (
                "Review newly added human-facing surfaces for README, changelog, and "
                "repo-consistency coverage: references/new-guide.md"
            ),
            result.warnings,
        )
        self.assertIn(
            "Human-facing surfaces changed since `origin/main`: A references/new-guide.md",
            result.notes,
        )

    def test_main_preserves_empty_programmatic_argv(self) -> None:
        expected = self.release_checklist.ChecklistResult(version="1.15.0")

        with mock.patch.object(sys, "argv", ["release_checklist.py", "--version", "9.9.9"]):
            with mock.patch.object(
                self.release_checklist,
                "build_release_checklist",
                return_value=expected,
            ) as build:
                with mock.patch("builtins.print"):
                    exit_code = self.release_checklist.main([])

        self.assertEqual(exit_code, 0)
        build.assert_called_once_with(
            self.release_checklist.REPO_ROOT,
            expected_version=None,
            base_ref="origin/main",
            allow_unreleased=False,
        )

    def test_result_to_json_dict_has_stable_field_shape(self) -> None:
        result = self.release_checklist.ChecklistResult(
            version="1.15.0",
            failures=["failure-a", "failure-b"],
            warnings=["warning-a"],
            notes=["note-a", "note-b", "note-c"],
        )

        payload = self.release_checklist.result_to_json_dict(result)

        self.assertEqual(
            set(payload.keys()),
            {"version", "ok", "failures", "warnings", "notes"},
        )
        self.assertEqual(payload["version"], "1.15.0")
        self.assertIs(payload["ok"], False)
        self.assertEqual(payload["failures"], ["failure-a", "failure-b"])
        self.assertEqual(payload["warnings"], ["warning-a"])
        self.assertEqual(payload["notes"], ["note-a", "note-b", "note-c"])
        self.assertIs(payload["ok"], result.ok)

    def test_render_result_json_emits_one_object_with_ordered_arrays(self) -> None:
        result = self.release_checklist.ChecklistResult(
            version="2.0.0",
            failures=["first-failure", "second-failure"],
            warnings=["only-warning"],
            notes=["note-one", "note-two"],
        )

        rendered = self.release_checklist.render_result_json(result)
        payload = json.loads(rendered)

        self.assertEqual(payload["version"], "2.0.0")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failures"], ["first-failure", "second-failure"])
        self.assertEqual(payload["warnings"], ["only-warning"])
        self.assertEqual(payload["notes"], ["note-one", "note-two"])
        # Deterministic key order from sort_keys=True
        self.assertEqual(
            list(json.loads(rendered, object_pairs_hook=list)),
            [
                ("failures", ["first-failure", "second-failure"]),
                ("notes", ["note-one", "note-two"]),
                ("ok", False),
                ("version", "2.0.0"),
                ("warnings", ["only-warning"]),
            ],
        )

    def test_main_json_success_stdout_is_pure_json_and_exit_zero(self) -> None:
        expected = self.release_checklist.ChecklistResult(
            version="1.15.0",
            notes=["all good"],
        )
        stdout = io.StringIO()

        with mock.patch.object(
            self.release_checklist,
            "build_release_checklist",
            return_value=expected,
        ):
            with redirect_stdout(stdout):
                exit_code = self.release_checklist.main(["--json", "--base", ""])

        raw = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Release checklist", raw)
        payload = json.loads(raw)
        self.assertEqual(
            set(payload.keys()),
            {"version", "ok", "failures", "warnings", "notes"},
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "1.15.0")
        self.assertEqual(payload["failures"], [])
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["notes"], ["all good"])

    def test_main_json_failure_preserves_exit_code_and_failure_order(self) -> None:
        expected = self.release_checklist.ChecklistResult(
            version="1.16.0",
            failures=["CHANGELOG.md: latest release stale", "AGENTS.md: version mismatch"],
            warnings=["review surfaces"],
        )
        stdout = io.StringIO()

        with mock.patch.object(
            self.release_checklist,
            "build_release_checklist",
            return_value=expected,
        ):
            with redirect_stdout(stdout):
                exit_code = self.release_checklist.main(["--json"])

        raw = stdout.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertNotIn("FAILURES", raw)
        self.assertNotIn("Release checklist", raw)
        payload = json.loads(raw)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            payload["failures"],
            ["CHANGELOG.md: latest release stale", "AGENTS.md: version mismatch"],
        )
        self.assertEqual(payload["warnings"], ["review surfaces"])

    def test_main_default_text_mode_unchanged_without_json_flag(self) -> None:
        expected = self.release_checklist.ChecklistResult(
            version="1.15.0",
            warnings=["surface review"],
        )
        stdout = io.StringIO()

        with mock.patch.object(
            self.release_checklist,
            "build_release_checklist",
            return_value=expected,
        ):
            with redirect_stdout(stdout):
                exit_code = self.release_checklist.main(["--base", ""])

        raw = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Release checklist for v1.15.0", raw)
        self.assertIn("WARNINGS", raw)
        self.assertIn("- surface review", raw)
        self.assertIn("Release checklist completed with warnings", raw)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw)


if __name__ == "__main__":
    unittest.main()
