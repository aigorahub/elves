"""Fresh installed-bundle smokes and adapter registry identity tests."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(
    sys.version_info < (3, 10),
    "installed_bundle_smoke requires Python >= 3.10 (repo floor); skipping on older interpreter",
)
class InstalledBundleSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.smoke = load_module(
            "installed_bundle_smoke_under_test",
            SCRIPTS / "installed_bundle_smoke.py",
        )

    def test_claude_and_codex_smokes_from_outside_source_tree(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = self.smoke.smoke_host(host, repo_root=REPO_ROOT)
                self.assertTrue(
                    result["ok"],
                    msg=f"{host} failures={result.get('failures')}",
                )
                self.assertGreater(int(result["py_module_count"]), 5)
                self.assertEqual(
                    result["imported_runtime_module_count"],
                    result["py_module_count"],
                )
                self.assertEqual(
                    result["required_runtime_count"],
                    len(self.smoke.REQUIRED_TOP_LEVEL_RUNTIME_PATHS),
                )
                self.assertEqual(result["alias_count"], 11 if host == "claude" else 0)
                self.assertGreater(int(result["markdown_link_count"]), 0)
                self.assertGreater(int(result["installed_document_count"]), 2)
                self.assertIn("installed-cli-target-cwd=ok", result["notes"])
                self.assertIn(
                    "installed-cli-explicit-repo-root=ok",
                    result["notes"],
                )
                self.assertIn("landing-check-help=ok", result["notes"])
                self.assertTrue(result["skill_present"])
                self.assertTrue(result["agents_present"])

    def test_required_top_level_dependencies_are_shipped_with_bundle(self) -> None:
        # Stage via smoke helper's copy path and assert presence without full smoke.
        import sync_installed_skills as sync  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "elves"
            original_root = sync.REPO_ROOT
            original_targets = sync.TARGETS
            try:
                sync.REPO_ROOT = REPO_ROOT
                sync.TARGETS = sync.build_targets(REPO_ROOT)
                cfg = dict(sync.TARGETS["codex"])
                cfg["root"] = dest
                cfg.pop("alias_root", None)
                cfg["managed_aliases"] = []
                sync.TARGETS = {"codex": cfg}
                problems = sync.apply_target("codex")
                self.assertEqual(problems, [])
                self.assertTrue((dest / "scripts" / "openrouter_lens.py").is_file())
                self.assertTrue((dest / "scripts" / "workspace_guard.py").is_file())
                self.assertTrue((dest / "scripts" / "cobbler_runtime" / "implement.py").is_file())
                self.assertTrue((dest / "scripts" / "cobbler_runtime" / "onboard.py").is_file())
                self.assertTrue((dest / "scripts" / "cobbler_runtime" / "executables.py").is_file())
                self.assertTrue((dest / "scripts" / "cobbler_runtime" / "prewalk.py").is_file())
                self.assertTrue((dest / "references" / "prewalk.md").is_file())
                self.assertFalse((dest / "aliases").exists())
            finally:
                sync.REPO_ROOT = original_root
                sync.TARGETS = original_targets

    def test_smoke_contract_rejects_missing_required_runtime_dependency(self) -> None:
        required = (*self.smoke.REQUIRED_TOP_LEVEL_RUNTIME_PATHS, "scripts/missing.py")
        with mock.patch.object(
            self.smoke,
            "REQUIRED_TOP_LEVEL_RUNTIME_PATHS",
            required,
        ):
            result = self.smoke.smoke_host("codex", repo_root=REPO_ROOT)

        self.assertFalse(result["ok"])
        self.assertIn(
            "missing required runtime dependency scripts/missing.py",
            result["failures"],
        )

    def test_both_host_layouts_ship_prewalk_runtime_and_reference(self) -> None:
        import sync_installed_skills as sync  # noqa: PLC0415

        original_root = sync.REPO_ROOT
        original_targets = sync.TARGETS
        try:
            for host in ("claude", "codex"):
                with self.subTest(host=host), tempfile.TemporaryDirectory() as tmpdir:
                    install_root = Path(tmpdir) / "skills"
                    dest = install_root / "elves"
                    sync.REPO_ROOT = REPO_ROOT
                    cfg = dict(sync.build_targets(REPO_ROOT)[host])
                    cfg["root"] = dest
                    if host == "claude":
                        cfg["alias_root"] = install_root
                    else:
                        cfg.pop("alias_root", None)
                        cfg["managed_aliases"] = []
                    sync.TARGETS = {host: cfg}
                    self.assertEqual(sync.apply_target(host), [])
                    self.assertTrue(
                        (dest / "scripts" / "cobbler_runtime" / "prewalk.py").is_file()
                    )
                    self.assertTrue((dest / "references" / "prewalk.md").is_file())
        finally:
            sync.REPO_ROOT = original_root
            sync.TARGETS = original_targets

    def test_installed_markdown_links_reject_unshipped_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            install_root = Path(tmpdir) / "skills"
            bundle = install_root / "elves"
            bundle.mkdir(parents=True)
            (bundle / "SKILL.md").write_text(
                "[source-only docs](README.md)\n",
                encoding="utf-8",
            )

            failures, checked = self.smoke._validate_installed_markdown_links(
                install_root
            )

        self.assertEqual(checked, 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("unshipped link target README.md", failures[0])

    def test_installed_markdown_links_validate_references_but_ignore_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            install_root = Path(tmpdir) / "skills"
            bundle = install_root / "elves"
            bundle.mkdir(parents=True)
            skill = bundle / "SKILL.md"
            skill.write_text(
                "[source-only docs][readme]\n\n"
                "[readme]: README.md\n\n"
                "```md\n[example](MISSING-EXAMPLE.md)\n```\n"
                "<!-- [commented](MISSING-COMMENT.md) -->\n",
                encoding="utf-8",
            )

            failures, checked = self.smoke._validate_installed_markdown_links(
                install_root
            )

        self.assertEqual(checked, 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("unshipped link target README.md", failures[0])

    def test_installed_document_contract_rejects_repo_only_command(self) -> None:
        contract = "\n".join(self.smoke.INSTALLED_PATH_CONTRACT_PHRASES)
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = Path(tmpdir) / "elves"
            references = bundle / "references"
            references.mkdir(parents=True)
            for name in ("SKILL.md", "AGENTS.md"):
                (bundle / name).write_text(contract, encoding="utf-8")
            (references / "runtime-helper-paths.md").write_text(
                "python3 scripts/verify_repo.py --ci\n",
                encoding="utf-8",
            )

            failures, checked = self.smoke._validate_installed_document_contract(
                bundle
            )

        self.assertGreater(checked, 2)
        self.assertEqual(len(failures), 1)
        self.assertIn("executable repo-only helper command", failures[0])

    def test_installed_document_contract_requires_both_host_paths(self) -> None:
        incomplete = "\n".join(
            phrase
            for phrase in self.smoke.INSTALLED_PATH_CONTRACT_PHRASES
            if phrase != "~/.codex/skills/elves"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = Path(tmpdir) / "elves"
            references = bundle / "references"
            references.mkdir(parents=True)
            (bundle / "SKILL.md").write_text(incomplete, encoding="utf-8")
            (bundle / "AGENTS.md").write_text(incomplete, encoding="utf-8")
            (references / "runtime-helper-paths.md").write_text(
                "Installed helper rules.\n",
                encoding="utf-8",
            )

            failures, _ = self.smoke._validate_installed_document_contract(bundle)

        self.assertEqual(len(failures), 2)
        self.assertTrue(
            all("~/.codex/skills/elves" in failure for failure in failures),
            failures,
        )

    def test_claude_alias_inventory_rejects_an_eighth_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            install_root = Path(tmpdir) / "skills"
            bundle = install_root / "elves"
            bundle.mkdir(parents=True)
            for name in self.smoke.EXPECTED_CLAUDE_ALIASES:
                alias = install_root / name
                alias.mkdir()
                (alias / "SKILL.md").write_text(
                    self.smoke.CLAUDE_ALIAS_MARKER,
                    encoding="utf-8",
                )
            (install_root / "extra-alias").mkdir()

            failures, count = self.smoke._validate_alias_installation(
                "claude",
                bundle_root=bundle,
            )

        self.assertEqual(count, 12)
        self.assertEqual(len(failures), 1)
        self.assertIn("expected exactly eleven managed aliases", failures[0])

    def test_codex_alias_inventory_rejects_any_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            install_root = Path(tmpdir) / "skills"
            bundle = install_root / "elves"
            bundle.mkdir(parents=True)
            (install_root / "cobbler").mkdir()

            failures, count = self.smoke._validate_alias_installation(
                "codex",
                bundle_root=bundle,
            )

        self.assertEqual(count, 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("Codex install must contain no Claude aliases", failures[0])


class BuiltinAdapterRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        from cobbler_runtime.adapters import (  # noqa: PLC0415
            ADAPTER_CONTRACT_PAIRS,
            adapter_contract_pair,
            builtin_adapter_names,
            get_adapter,
            resolve_adapter_name,
        )
        from cobbler_runtime.schema import BUILTIN_ADAPTER_NAMES, ValidationIssue  # noqa: PLC0415

        self.get_adapter = get_adapter
        self.resolve = resolve_adapter_name
        self.contract = adapter_contract_pair
        self.pairs = ADAPTER_CONTRACT_PAIRS
        self.names = builtin_adapter_names
        self.ValidationIssue = ValidationIssue
        self.BUILTIN_ADAPTER_NAMES = BUILTIN_ADAPTER_NAMES

    def test_builtin_names_keep_identity(self) -> None:
        for name in (
            "gemini-cli",
            "antigravity-cli",
            "opencode-cli",
            "claude-code",
            "grok-build",
            "codex-fugu",
            "host-native",
        ):
            with self.subTest(name=name):
                adapter = self.get_adapter(name)
                self.assertEqual(adapter.name, name)
                self.assertEqual(self.resolve(name), name)
                pair = self.contract(name)
                self.assertEqual(pair, self.pairs[name])
                self.assertNotEqual(name, "custom-cli")

    def test_unknown_without_executable_fails_closed(self) -> None:
        with self.assertRaises(self.ValidationIssue):
            self.resolve("totally-unknown-adapter")

    def test_unknown_with_executable_maps_to_custom_cli(self) -> None:
        self.assertEqual(self.resolve("totally-unknown-adapter", executable="foo"), "custom-cli")


if __name__ == "__main__":
    unittest.main()
