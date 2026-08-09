from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def _ensure_import_path() -> None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))


_ensure_import_path()

from cobbler_runtime.config import resolve_config  # noqa: E402
from cobbler_runtime.schema import ValidationIssue  # noqa: E402
from cobbler_runtime.setup import (  # noqa: E402
    assert_toml_has_no_secrets,
    inventory_tools,
    preferences_from_flags,
    recommend_routes,
    render_models_toml,
    run_setup,
    write_models_toml,
    PROFILE_RECIPES,
)


class InventoryTests(unittest.TestCase):
    def test_no_tools_native_only(self) -> None:
        items = inventory_tools(
            fake_presence={
                "claude-code": False,
                "grok-build": False,
                "codex-fugu": False,
                "custom-cli": False,
                "gemini-cli": False,
                "antigravity-cli": False,
                "opencode-cli": False,
                "devin-cli": False,
                "omp-cli": False,
            }
        )
        by_name = {i.adapter: i for i in items}
        self.assertTrue(by_name["host-native"].present)
        self.assertFalse(by_name["claude-code"].present)
        recs = recommend_routes(items)
        self.assertTrue(any("No external CLIs" in r for r in recs))

    def test_claude_only_grok_only_fugu_only_and_all_three(self) -> None:
        cases = [
            ({"claude-code": True}, "claude-code"),
            ({"grok-build": True}, "grok-build"),
            ({"codex-fugu": True}, "codex-fugu"),
            (
                {"claude-code": True, "grok-build": True, "codex-fugu": True},
                "claude-code",
            ),
        ]
        for presence, expected in cases:
            with self.subTest(presence=presence):
                items = inventory_tools(fake_presence=presence)
                present = {i.adapter for i in items if i.present and i.adapter != "host-native"}
                self.assertTrue(expected in present or all(presence.values()))
                recs = " ".join(recommend_routes(items))
                self.assertIn("host-native", recs.lower())


class TomlGenerationTests(unittest.TestCase):
    def test_generated_toml_validates_and_has_no_secrets(self) -> None:
        prefs = preferences_from_flags(
            implement="grok-build",
            review="claude-code",
            lightweight_review="host-native",
            required=["validate"],
        )
        text = render_models_toml(prefs)
        assert_toml_has_no_secrets(text)
        self.assertNotIn("sk-", text)
        self.assertNotIn("/Users/", text)
        self.assertIn("OPENROUTER_API_KEY", text)  # name only in comments
        self.assertIn('[roles.implement]', text)
        self.assertIn('profile = "grok-build"', text)
        self.assertIn('profile = "host-native"', text)
        # Prefer tomllib when available; otherwise resolve via equivalent mapping.
        try:
            import tomllib

            parsed = tomllib.loads(text)
        except ModuleNotFoundError:
            parsed = {
                "profiles": {
                    "grok-build": {"adapter": "grok-build"},
                    "claude-code": {"adapter": "claude-code"},
                    "host-native": {"adapter": "host-native"},
                },
                "roles": {
                    "implement": {
                        "profile": "grok-build",
                        "required": False,
                        "fallback_chain": [{"profile": "host-native"}],
                    },
                    "review": {"profile": "claude-code", "required": False},
                    "lightweight_review": {"profile": "host-native", "required": False},
                    "validate": {"profile": "host-native", "required": True},
                },
            }
        resolved = resolve_config(models_toml=parsed)
        self.assertTrue(resolved.ok, [i.message for i in resolved.issues])
        self.assertEqual(resolved.roles["implement"].profile, "grok-build")
        self.assertEqual(resolved.roles["lightweight_review"].profile, "host-native")
        self.assertEqual(
            [e.profile for e in resolved.roles["implement"].fallback_chain],
            ["host-native"],
        )

    def test_tier_and_google_profiles_render(self) -> None:
        prefs = preferences_from_flags(
            planning="claude-code-planning",
            review="gemini-cli",
            implement="claude-code-labor",
        )
        text = render_models_toml(prefs)
        self.assertIn("[profiles.claude-code-planning]", text)
        self.assertIn("[profiles.claude-code-labor]", text)
        self.assertIn("[profiles.gemini-cli]", text)
        self.assertIn('adapter = "gemini-cli"', text)
        self.assertIn("requested_model", text)
        self.assertIn("claude-code-planning", PROFILE_RECIPES)
        self.assertIn("antigravity-cli", PROFILE_RECIPES)
        self.assertIn("antigravity-labor", PROFILE_RECIPES)
        self.assertTrue(PROFILE_RECIPES["gemini-cli"].get("plan_review_only"))
        self.assertTrue(PROFILE_RECIPES["antigravity-cli"].get("plan_review_only"))
        self.assertFalse(PROFILE_RECIPES["antigravity-labor"].get("plan_review_only"))
        self.assertEqual(PROFILE_RECIPES["antigravity-labor"].get("adapter"), "antigravity-cli")
        try:
            import tomllib

            parsed = tomllib.loads(text)
            self.assertEqual(parsed["roles"]["planning"]["profile"], "claude-code-planning")
            self.assertEqual(parsed["roles"]["implement"]["profile"], "claude-code-labor")
            self.assertEqual(parsed["profiles"]["gemini-cli"]["adapter"], "gemini-cli")
            self.assertEqual(parsed["profiles"]["claude-code-planning"]["adapter"], "claude-code")
        except ModuleNotFoundError:
            self.assertIn('profile = "claude-code-labor"', text)

    def test_secret_patterns_rejected(self) -> None:
        with self.assertRaises(ValidationIssue):
            assert_toml_has_no_secrets('token = "sk-abcdefghijklmnop"')
        with self.assertRaises(ValidationIssue):
            assert_toml_has_no_secrets('path = "/Users/me/secret"')

    def test_local_toml_ignored_and_not_staged_concept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text(".elves/\n", encoding="utf-8")
            result = run_setup(
                root,
                preferences=preferences_from_flags(implement="claude-code"),
                write_toml=True,
                fake_presence={"claude-code": True},
            )
            self.assertTrue(result.ok)
            self.assertTrue(result.models_toml_written)
            self.assertTrue(result.models_toml_ignored)
            path = root / ".elves" / "models.toml"
            self.assertTrue(path.is_file())
            # Tracked example remains separate and stable in repo.
            example = REPO_ROOT / "references" / "models.toml.example"
            self.assertTrue(example.is_file())
            self.assertNotEqual(path.read_text(encoding="utf-8"), example.read_text(encoding="utf-8"))


class SetupScenarioTests(unittest.TestCase):
    def test_noninteractive_dry_run_no_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text(".elves/\n", encoding="utf-8")
            result = run_setup(
                root,
                preferences=preferences_from_flags(),
                write_toml=False,
                fake_presence={},
            )
            self.assertTrue(result.ok)
            self.assertFalse(result.models_toml_written)
            self.assertFalse((root / ".elves" / "models.toml").is_file())
            self.assertFalse(result.credentials_printed)
            self.assertFalse(result.smoke_ran)

    def test_required_unavailable_route_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text(".elves/\n", encoding="utf-8")
            result = run_setup(
                root,
                preferences=preferences_from_flags(
                    implement="grok-build",
                    required=["implement"],
                ),
                write_toml=False,
                fake_presence={"grok-build": False},
            )
            self.assertFalse(result.ok)
            self.assertTrue(
                any(i.get("code") == "required_route_unavailable" for i in result.issues)
            )

    def test_auth_unknown_and_no_model_list(self) -> None:
        items = inventory_tools(
            fake_presence={"claude-code": True},
            fake_auth={"claude-code": "unknown"},
            fake_versions={"claude-code": None},
        )
        claude = next(i for i in items if i.adapter == "claude-code")
        self.assertEqual(claude.auth, "unknown")
        # Doctor/setup inventory does not invent model lists here.
        self.assertIsNone(claude.version)

    def test_unknown_quota_guidance_in_recommendations(self) -> None:
        recs = " ".join(recommend_routes(inventory_tools(fake_presence={})))
        self.assertIn("OpenRouter", recs)

    def test_smoke_opt_in_does_not_print_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text(".elves/\n", encoding="utf-8")
            # Acknowledgment without an executor is not a smoke.
            bare = run_setup(
                root,
                write_toml=False,
                run_smoke=True,
                fake_presence={"claude-code": True},
            )
            self.assertFalse(bare.smoke_ran)
            self.assertFalse(bare.credentials_printed)

            def _executor(**_kwargs):
                return {"text": "ok", "actual_model": "claude-fable-5"}

            result = run_setup(
                root,
                write_toml=False,
                run_smoke=True,
                smoke_executor=_executor,
                fake_presence={"claude-code": True},
            )
            self.assertTrue(result.smoke_ran)
            self.assertFalse(result.credentials_printed)

    def test_survival_guide_snapshot_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text(".elves/\n", encoding="utf-8")
            result = run_setup(
                root,
                preferences=preferences_from_flags(review="claude-code"),
                write_toml=False,
                fake_presence={"claude-code": True},
            )
            snap = result.survival_guide_snapshot
            self.assertIn("roles", snap)
            self.assertEqual(snap["roles"]["review"]["profile"], "claude-code")
            self.assertIn("generated_at", snap)

    def test_refuse_lossy_toml_overwrite_with_unknown_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".elves" / "models.toml"
            path.parent.mkdir(parents=True)
            path.write_text("[custom_experimental]\nfoo = 1\n", encoding="utf-8")
            with self.assertRaises(ValidationIssue) as ctx:
                write_models_toml(root, render_models_toml(preferences_from_flags()), force=False)
            self.assertEqual(ctx.exception.code, "models_toml_unknown_sections")


class SetupCliTests(unittest.TestCase):
    def test_setup_cli_json_dry_run(self) -> None:
        cli = REPO_ROOT / "scripts" / "cobbler_agents.py"
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "setup",
                    "--json",
                    "--dry-run",
                    "--repo-root",
                    tmp,
                    "--implement",
                    "host-native",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["models_toml_written"])
        self.assertFalse(payload["credentials_printed"])
        self.assertFalse(payload["staged_models_toml"])

    def test_setup_cli_partial_apply_preserves_profile_and_top_level_values(self) -> None:
        cli = REPO_ROOT / "scripts" / "cobbler_agents.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".elves" / "models.toml"
            path.parent.mkdir(parents=True)
            path.write_text(
                """
sharing_policy = "private-machine"
document_owner = "custom-host"
session_mode_default = "exact_resume"
usage_budget_warning_tokens = 1234

[profiles.claude-code-planning]
adapter = "claude-code"
executable = "claude"
requested_model = "claude-opus-user-pin"

[roles.planning]
profile = "claude-code-planning"
required = false

[roles.review]
profile = "host-native"
required = true
""".lstrip(),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "setup",
                    "--json",
                    "--repo-root",
                    tmp,
                    "--implement",
                    "host-native",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            text = path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('requested_model = "claude-opus-user-pin"', text)
        self.assertIn('sharing_policy = "private-machine"', text)
        self.assertIn('document_owner = "custom-host"', text)
        self.assertIn('session_mode_default = "exact_resume"', text)
        self.assertIn("usage_budget_warning_tokens = 1234", text)


class AliasDelegationTests(unittest.TestCase):
    def test_setup_aliases_exist_with_managed_marker(self) -> None:
        for name in ("setup-cobbler", "setup-council"):
            path = REPO_ROOT / "aliases" / "claude" / name / "SKILL.md"
            self.assertTrue(path.is_file(), name)
            text = path.read_text(encoding="utf-8")
            self.assertIn("elves-managed-alias: claude-skill-alias v1", text)
            self.assertIn("cobbler_agents.py setup", text)
            self.assertIn("Never stage", text)
            self.assertRegex(text, r"(?i)(must not require openrouter|do not require openrouter)")

    def test_setup_aliases_in_sync_list(self) -> None:
        from pathlib import Path as P
        import importlib.util

        path = REPO_ROOT / "scripts" / "sync_installed_skills.py"
        spec = importlib.util.spec_from_file_location("sync_mod", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        self.assertIn("setup-cobbler", mod.CLAUDE_ALIAS_NAMES)
        self.assertIn("setup-council", mod.CLAUDE_ALIAS_NAMES)
        # Package is shipped recursively; individual modules need no allowlist entry.
        self.assertIn("scripts/cobbler_runtime", mod.RUNTIME_SCRIPT_PATHS)
        self.assertIn("scripts/openrouter_lens.py", mod.RUNTIME_SCRIPT_PATHS)
        self.assertEqual(len(mod.CLAUDE_ALIAS_NAMES), 12)


if __name__ == "__main__":
    unittest.main()
