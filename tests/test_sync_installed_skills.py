from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync_installed_skills.py"


def load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_installed_skills_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load sync_installed_skills module for tests")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(
    sys.version_info < (3, 10),
    "sync_installed_skills requires Python >= 3.10 (repo floor); skipping on older interpreter",
)
class SyncInstalledSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sync = load_sync_module()

    def configure_temp_repo(self, tmpdir: str) -> tuple[Path, Path]:
        root = Path(tmpdir)
        repo = root / "repo"
        home = root / "home"
        repo.mkdir()

        version = self.sync.read_version(REPO_ROOT / "SKILL.md")
        self.assertIsNotNone(version)
        (repo / "SKILL.md").write_text(
            f'---\nmetadata:\n  version: "{version}"\n---\n'
        )
        (repo / "AGENTS.md").write_text(f'---\nversion: "{version}"\n---\n')
        (repo / "config.json.example").write_text('{"cobbler": {"enabled": true}}\n')
        (repo / "references").mkdir()
        (repo / "references" / "guide.md").write_text("guide\n")
        (repo / "scripts").mkdir()
        for relative in self.sync.TOP_LEVEL_RUNTIME_SCRIPT_PATHS + self.sync.REPO_ONLY_SCRIPT_PATHS:
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n")
        # Recursive package shipment: one seed module is enough for apply/check.
        package = repo / self.sync.RUNTIME_PACKAGE_PATH
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text('"""runtime package."""\n')
        (package / "schema.py").write_text("SCHEMA = True\n")
        (package / "nested").mkdir()
        (package / "nested" / "extra.py").write_text("EXTRA = True\n")

        for alias_name in self.sync.CLAUDE_ALIAS_NAMES:
            alias_dir = repo / "aliases" / "claude" / alias_name
            alias_dir.mkdir(parents=True)
            alias_dir.joinpath("SKILL.md").write_text(
                f"---\nname: {alias_name}\n---\n\n{self.sync.CLAUDE_ALIAS_MARKER}\n",
            )

        self.sync.REPO_ROOT = repo
        self.sync.TARGETS = self.sync.build_targets(repo)
        # Point install roots into the temp home.
        self.sync.TARGETS["claude"]["root"] = home / ".claude" / "skills" / "elves"
        self.sync.TARGETS["claude"]["alias_root"] = home / ".claude" / "skills"
        self.sync.TARGETS["codex"]["root"] = home / ".codex" / "skills" / "elves"
        return repo, home

    def test_apply_creates_missing_claude_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _, home = self.configure_temp_repo(tmpdir)

            problems = self.sync.apply_target("claude")

            self.assertEqual(problems, [])
            for alias_name in self.sync.CLAUDE_ALIAS_NAMES:
                skill_path = home / ".claude" / "skills" / alias_name / "SKILL.md"
                self.assertTrue(skill_path.exists(), alias_name)
                self.assertIn(self.sync.CLAUDE_ALIAS_MARKER, skill_path.read_text())

    def test_apply_refuses_unmarked_user_owned_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _, home = self.configure_temp_repo(tmpdir)
            alias_path = home / ".claude" / "skills" / "cobbler" / "SKILL.md"
            alias_path.parent.mkdir(parents=True)
            alias_path.write_text("user-owned alias\n")

            problems = self.sync.apply_target("claude")

            self.assertEqual(alias_path.read_text(), "user-owned alias\n")
            self.assertIn(
                f"alias conflict: {alias_path.parent} exists without Elves managed alias marker",
                problems,
            )
            self.assertFalse(
                (home / ".claude" / "skills" / "elves" / "SKILL.md").exists(),
                "alias conflicts must be detected before mutating the main install",
            )

    def test_apply_updates_marked_stale_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, home = self.configure_temp_repo(tmpdir)
            alias_path = home / ".claude" / "skills" / "cobbler" / "SKILL.md"
            alias_path.parent.mkdir(parents=True)
            alias_path.write_text(f"{self.sync.CLAUDE_ALIAS_MARKER}\nstale\n")

            problems = self.sync.apply_target("claude")

            self.assertEqual(problems, [])
            self.assertEqual(
                alias_path.read_text(),
                (repo / "aliases" / "claude" / "cobbler" / "SKILL.md").read_text(),
            )

    def test_check_reports_unmarked_alias_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _, home = self.configure_temp_repo(tmpdir)
            self.sync.apply_target("claude")
            alias_path = home / ".claude" / "skills" / "council" / "SKILL.md"
            alias_path.write_text("user-owned council alias\n")

            ok, problems = self.sync.check_target("claude")

            self.assertFalse(ok)
            self.assertIn(
                f"alias conflict: {alias_path.parent} exists without Elves managed alias marker",
                problems,
            )

    def test_codex_apply_does_not_create_claude_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _, home = self.configure_temp_repo(tmpdir)

            problems = self.sync.apply_target("codex")

            self.assertEqual(problems, [])
            self.assertFalse((home / ".claude" / "skills" / "cobbler").exists())

    def test_apply_removes_repo_only_helpers_from_installed_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _, home = self.configure_temp_repo(tmpdir)
            installed_root = home / ".codex" / "skills" / "elves"
            installed_helpers = [installed_root / path for path in self.sync.REPO_ONLY_SCRIPT_PATHS]
            for installed_helper in installed_helpers:
                installed_helper.parent.mkdir(parents=True, exist_ok=True)
                installed_helper.write_text("stale repo-only helper\n")

            problems = self.sync.apply_target("codex")

            self.assertEqual(problems, [])
            for installed_helper in installed_helpers:
                self.assertFalse(installed_helper.exists(), str(installed_helper))

    def test_apply_installs_config_template_for_all_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _, home = self.configure_temp_repo(tmpdir)

            self.assertEqual(self.sync.apply_target("claude"), [])
            self.assertEqual(self.sync.apply_target("codex"), [])

            self.assertTrue(
                (home / ".claude" / "skills" / "elves" / "config.json.example").exists()
            )
            self.assertTrue(
                (home / ".codex" / "skills" / "elves" / "config.json.example").exists()
            )
            for host_root in (
                home / ".claude" / "skills" / "elves",
                home / ".codex" / "skills" / "elves",
            ):
                self.assertTrue((host_root / "SKILL.md").is_file())
                self.assertTrue((host_root / "AGENTS.md").is_file())

    def test_apply_unlinks_managed_file_symlinks_without_overwriting_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, _home = self.configure_temp_repo(tmpdir)
            for host in ("claude", "codex"):
                with self.subTest(host=host):
                    root = self.sync.TARGETS[host]["root"]
                    root.mkdir(parents=True, exist_ok=True)
                    outside = Path(tmpdir) / f"outside-{host}.md"
                    outside.write_text("keep\n", encoding="utf-8")
                    managed = root / "SKILL.md"
                    managed.symlink_to(outside)

                    problems = self.sync.apply_target(host)

                    self.assertEqual(problems, [])
                    self.assertEqual(outside.read_text(encoding="utf-8"), "keep\n")
                    self.assertFalse(managed.is_symlink())
                    self.assertEqual(managed.read_text(), (repo / "SKILL.md").read_text())

    def test_apply_rejects_symlinked_install_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _repo, home = self.configure_temp_repo(tmpdir)
            outside = Path(tmpdir) / "outside-skills"
            outside.mkdir()
            skills = home / ".codex" / "skills"
            skills.parent.mkdir(parents=True)
            skills.symlink_to(outside, target_is_directory=True)

            problems = self.sync.apply_target("codex")

            self.assertTrue(any("unsafe symlinked install path" in item for item in problems))
            self.assertFalse((outside / "elves").exists())

    def test_apply_preflight_does_not_follow_cleanup_parent_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _repo, _home = self.configure_temp_repo(tmpdir)
            installed_root = self.sync.TARGETS["codex"]["root"]
            installed_root.mkdir(parents=True)
            outside = Path(tmpdir) / "outside-user-files"
            outside.mkdir()
            sentinel = outside / "release_checklist.py"
            sentinel.write_text("user-owned sentinel\n", encoding="utf-8")
            (installed_root / "scripts").symlink_to(outside, target_is_directory=True)

            problems = self.sync.apply_target("codex")

            self.assertTrue(any("unsafe symlinked install path" in item for item in problems))
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "user-owned sentinel\n")
            # Preflight is all-or-nothing: no safe-looking managed file is copied
            # before the unsafe cleanup destination is discovered.
            self.assertFalse((installed_root / "SKILL.md").exists())

    def test_check_all_without_installed_targets_is_advisory_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.configure_temp_repo(tmpdir)
            stdout = io.StringIO()

            with mock.patch.object(sys, "argv", ["sync_installed_skills.py", "--check"]):
                with contextlib.redirect_stdout(stdout):
                    result = self.sync.main()

            self.assertEqual(result, 0)
            self.assertIn("No installed Elves skill copies were detected.", stdout.getvalue())

    def test_recursive_runtime_package_ships_nested_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, home = self.configure_temp_repo(tmpdir)
            problems = self.sync.apply_target("claude")
            self.assertEqual(problems, [])
            installed = home / ".claude" / "skills" / "elves"
            self.assertTrue((installed / "scripts" / "cobbler_runtime" / "nested" / "extra.py").is_file())
            self.assertTrue((installed / "scripts" / "openrouter_lens.py").is_file())
            self.assertTrue((installed / "scripts" / "workspace_guard.py").is_file())
            # Adding a module under the package requires no allowlist edit.
            (repo / "scripts" / "cobbler_runtime" / "brand_new.py").write_text("X=1\n")
            problems = self.sync.apply_target("claude")
            self.assertEqual(problems, [])
            self.assertTrue((installed / "scripts" / "cobbler_runtime" / "brand_new.py").is_file())

    def test_required_standalone_runtime_helpers_are_managed(self) -> None:
        self.assertIn(
            "scripts/openrouter_lens.py",
            self.sync.TOP_LEVEL_RUNTIME_SCRIPT_PATHS,
        )
        self.assertIn(
            "scripts/workspace_guard.py",
            self.sync.TOP_LEVEL_RUNTIME_SCRIPT_PATHS,
        )

    def test_exactly_eleven_claude_aliases(self) -> None:
        self.assertEqual(len(self.sync.CLAUDE_ALIAS_NAMES), 11)
        self.assertEqual(
            self.sync.CLAUDE_ALIAS_NAMES,
            [
                "cobbler",
                "cobbler-mode",
                "council",
                "ec",
                "elves-council",
                "fugu",
                "manus",
                "grok",
                "devin",
                "setup-cobbler",
                "setup-council",
            ],
        )


if __name__ == "__main__":
    unittest.main()
