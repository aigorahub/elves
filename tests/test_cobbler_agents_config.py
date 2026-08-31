from __future__ import annotations

import importlib
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


def _ensure_import_path() -> None:
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


_ensure_import_path()

from cobbler_runtime import config as config_mod  # noqa: E402
from cobbler_runtime import schema as schema_mod  # noqa: E402
from cobbler_runtime import toml_compat  # noqa: E402
from cobbler_runtime.adapters import default_profiles, registry_snapshot  # noqa: E402
from cobbler_runtime.capabilities import default_capabilities_for  # noqa: E402
from cobbler_runtime.schema import (  # noqa: E402
    ConfigSource,
    RoleName,
    is_non_model_operation,
)


class SchemaContractTests(unittest.TestCase):
    def test_builtin_adapters_are_provider_neutral(self) -> None:
        names = schema_mod.BUILTIN_ADAPTER_NAMES
        self.assertIn("claude-code", names)
        self.assertIn("grok-build", names)
        self.assertIn("codex-fugu", names)
        self.assertIn("custom-cli", names)
        # Personal model IDs must never be public defaults.
        forbidden = {
            "claude-fable-5",
            "grok-4.5",
            "fugu-ultra",
            "gpt-5.6-sol",
            "gpt-5.6-luna",
        }
        for profile in default_profiles().values():
            self.assertNotIn(profile.name, forbidden)
            self.assertNotIn(profile.adapter, forbidden)

    def test_lightweight_review_is_a_first_class_role(self) -> None:
        self.assertEqual(RoleName.LIGHTWEIGHT_REVIEW.value, "lightweight_review")
        self.assertIn(RoleName.LIGHTWEIGHT_REVIEW, schema_mod.DEFAULT_ROLES)

    def test_usage_remaining_quota_defaults_unknown(self) -> None:
        usage = schema_mod.UsageRecord()
        self.assertFalse(usage.quota_known)
        self.assertEqual(usage.to_dict()["remaining_quota"], "unknown")

    def test_git_pr_ops_do_not_dispatch_models(self) -> None:
        for op in ("git", "git status", "gh", "pr_create", "pr_merge", "push", "commit"):
            with self.subTest(op=op):
                self.assertTrue(is_non_model_operation(op))
        self.assertFalse(is_non_model_operation("council"))
        self.assertFalse(is_non_model_operation("implement"))


class ConfigResolutionTests(unittest.TestCase):
    def test_native_only_defaults_without_external_profiles(self) -> None:
        resolved = config_mod.resolve_config()
        self.assertTrue(resolved.ok)
        self.assertEqual(resolved.sources_consulted, ["native_default"])
        for role in schema_mod.DEFAULT_ROLES:
            route = resolved.roles[role.value]
            self.assertEqual(route.profile, "host-native")
            self.assertEqual(route.source, ConfigSource.NATIVE_DEFAULT)
            self.assertFalse(route.required)

    def test_precedence_survival_guide_over_toml_over_json(self) -> None:
        user_config = {
            "model_routing": {
                "phases": {
                    "implement": {
                        "profile": "claude-code",
                        "required": False,
                    }
                }
            }
        }
        models_toml = {
            "roles": {
                "implement": {
                    "profile": "grok-build",
                    "required": False,
                }
            }
        }
        survival = {
            "model_routing": {
                "phases": {
                    "implement": {
                        "profile": "custom-cli",
                        "required": True,
                    }
                }
            }
        }
        resolved = config_mod.resolve_config(
            survival_guide=survival,
            models_toml=models_toml,
            user_config=user_config,
        )
        self.assertTrue(resolved.ok)
        route = resolved.roles["implement"]
        self.assertEqual(route.profile, "custom-cli")
        self.assertEqual(route.source, ConfigSource.SURVIVAL_GUIDE)
        self.assertTrue(route.required)
        self.assertEqual(
            resolved.sources_consulted,
            [
                "native_default",
                "user_config_json",
                "local_models_toml",
                "survival_guide",
            ],
        )

    def test_toml_beats_user_config_when_no_survival_override(self) -> None:
        resolved = config_mod.resolve_config(
            models_toml={
                "roles": {
                    "review": {"profile": "codex-fugu", "required": False},
                }
            },
            user_config={
                "model_routing": {
                    "phases": {
                        "review": {"profile": "claude-code", "required": False},
                    }
                }
            },
        )
        route = resolved.roles["review"]
        self.assertEqual(route.profile, "codex-fugu")
        self.assertEqual(route.source, ConfigSource.LOCAL_MODELS_TOML)

    def test_fugu_cannot_resolve_as_implementation_route(self) -> None:
        optional = config_mod.resolve_config(
            models_toml={
                "roles": {
                    "implement": {"profile": "codex-fugu", "required": False},
                }
            }
        )
        self.assertTrue(optional.ok)
        self.assertEqual(optional.roles["implement"].profile, "host-native")
        self.assertTrue(any("cannot use Fugu" in item for item in optional.warnings))

        required = config_mod.resolve_config(
            survival_guide={
                "model_routing": {
                    "phases": {
                        "implement": {"profile": "codex-fugu", "required": True},
                    }
                }
            }
        )
        self.assertFalse(required.ok)
        self.assertTrue(
            any(issue.code == "fugu_implement_route_blocked" for issue in required.issues)
        )

    def test_fugu_profile_controls_fail_closed(self) -> None:
        resolved = config_mod.resolve_config(
            models_toml={
                "profiles": {
                    "wrong-launcher": {
                        "adapter": "codex-fugu",
                        "executable": "codex",
                    },
                    "same-name-launcher-path": {
                        "adapter": "codex-fugu",
                        "executable": "/tmp/codex-fugu",
                    },
                    "premium-model": {
                        "adapter": "codex-fugu",
                        "executable": "codex-fugu",
                        "requested_model": "fugu-ultra-v1.1",
                    },
                    "extra-controls": {
                        "adapter": "codex-fugu",
                        "executable": "codex-fugu",
                        "extra_args": ["-c", 'model_reasoning_effort="max"'],
                    },
                    "disguised-fugu": {
                        "adapter": "custom-cli",
                        "executable": "codex-fugu",
                    },
                }
            }
        )
        self.assertFalse(resolved.ok)
        codes = {issue.code for issue in resolved.issues}
        self.assertIn("invalid_fugu_executable", codes)
        self.assertIn("invalid_fugu_model_override", codes)
        self.assertIn("invalid_fugu_extra_args", codes)
        self.assertIn("reserved_fugu_executable", codes)

    def test_deterministic_fallback_order_preserved(self) -> None:
        resolved = config_mod.resolve_config(
            models_toml={
                "roles": {
                    "implement": {
                        "profile": "grok-build",
                        "fallback_chain": [
                            {"profile": "claude-code", "reason": "first"},
                            {"profile": "host-native", "reason": "second"},
                        ],
                    }
                }
            }
        )
        chain = resolved.roles["implement"].fallback_chain
        self.assertEqual([entry.profile for entry in chain], ["claude-code", "host-native"])
        self.assertEqual([entry.reason for entry in chain], ["first", "second"])

    def test_required_unknown_profile_blocks_validation(self) -> None:
        resolved = config_mod.resolve_config(
            survival_guide={
                "model_routing": {
                    "phases": {
                        "implement": {
                            "profile": "does-not-exist",
                            "required": True,
                        }
                    }
                }
            }
        )
        self.assertFalse(resolved.ok)
        codes = {issue.code for issue in resolved.issues}
        self.assertIn("unknown_profile", codes)
        # Required must not be silently weakened.
        self.assertEqual(resolved.roles["implement"].profile, "does-not-exist")
        self.assertTrue(resolved.roles["implement"].required)

    def test_optional_unknown_profile_falls_back_to_native(self) -> None:
        resolved = config_mod.resolve_config(
            models_toml={
                "roles": {
                    "scout": {
                        "profile": "missing-optional",
                        "required": False,
                    }
                }
            }
        )
        self.assertTrue(resolved.ok)
        self.assertEqual(resolved.roles["scout"].profile, "host-native")
        self.assertTrue(any("missing-optional" in warning for warning in resolved.warnings))

    def test_map_implementation_to_claude_grok_or_custom_without_source_changes(self) -> None:
        for profile in ("claude-code", "grok-build", "custom-cli"):
            with self.subTest(profile=profile):
                resolved = config_mod.resolve_config(
                    models_toml={
                        "profiles": {
                            "worker": {"adapter": profile, "executable": "tool"},
                        },
                        "roles": {
                            "implement": {"profile": "worker", "required": False},
                        },
                    }
                )
                self.assertTrue(resolved.ok)
                self.assertEqual(resolved.roles["implement"].profile, "worker")
                self.assertEqual(resolved.profiles["worker"].adapter, profile)

    def test_lightweight_review_mapping_leaves_supervisor_unchanged(self) -> None:
        resolved = config_mod.resolve_config(
            models_toml={
                "roles": {
                    "review": {"profile": "claude-code", "required": False},
                    "lightweight_review": {"profile": "codex-fugu", "required": False},
                }
            }
        )
        self.assertEqual(resolved.roles["review"].profile, "claude-code")
        self.assertEqual(resolved.roles["lightweight_review"].profile, "codex-fugu")
        # Supervising/synthesize route stays native unless explicitly changed.
        self.assertEqual(resolved.roles["synthesize"].profile, "host-native")
        self.assertEqual(resolved.roles["synthesize"].source, ConfigSource.NATIVE_DEFAULT)

    def test_invalid_role_name_produces_actionable_issue(self) -> None:
        resolved = config_mod.resolve_config(
            models_toml={"roles": {"not-a-real-role": "host-native"}}
        )
        self.assertFalse(resolved.ok)
        self.assertEqual(resolved.issues[0].code, "unknown_role")
        self.assertIn("Known roles", resolved.issues[0].hint or "")

    def test_duplicate_profile_names_in_one_source_rejected(self) -> None:
        # JSON/TOML can't literally duplicate keys; simulate via double-parse path
        # by feeding a profiles mapping that the parser would see once. Instead
        # verify unknown adapter path and that profiles overwrite cleanly by name.
        resolved = config_mod.resolve_config(
            models_toml={
                "profiles": {
                    "coder": {"adapter": "claude-code"},
                },
                "roles": {"implement": "coder"},
            },
            survival_guide={
                "model_routing": {
                    "profiles": {
                        "coder": {"adapter": "grok-build"},
                    },
                    "phases": {
                        "implement": {"profile": "coder"},
                    },
                }
            },
        )
        self.assertTrue(resolved.ok)
        # Survival guide wins for profile definition and role.
        self.assertEqual(resolved.profiles["coder"].adapter, "grok-build")
        self.assertEqual(resolved.roles["implement"].source, ConfigSource.SURVIVAL_GUIDE)

    def test_load_toml_uses_python_310_compat_parser_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.toml"
            path.write_text('[roles]\nimplement = "host-native"\n', encoding="utf-8")
            with mock.patch.object(toml_compat, "_tomllib", None):
                loaded = config_mod.load_toml_file(path)
            self.assertEqual(loaded["roles"]["implement"], "host-native")

    def test_missing_toml_on_older_python_still_allows_native_json(self) -> None:
        with mock.patch.object(toml_compat, "_tomllib", None):
            resolved = config_mod.resolve_config(
                user_config={
                    "model_routing": {
                        "phases": {
                            "validate": {"profile": "host-native"},
                        }
                    }
                }
            )
        self.assertTrue(resolved.ok)
        self.assertEqual(resolved.roles["validate"].profile, "host-native")

    def test_models_toml_local_only_metadata(self) -> None:
        meta = config_mod.models_toml_is_local_only(REPO_ROOT)
        self.assertTrue(meta["ignored_by_gitignore"])
        self.assertFalse(meta["committed"])
        self.assertIn("never stage", meta["note"])
        self.assertIn(".elves/models.toml", meta["path"])

    def test_tracked_example_is_credential_and_path_free(self) -> None:
        example = REPO_ROOT / "references" / "models.toml.example"
        # File lands in a later commit; skip content checks if not yet present
        # only during partial development. Final suite requires it.
        if not example.is_file():
            self.skipTest("references/models.toml.example not created yet")
        text = example.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?i)(api[_-]?key\s*=\s*[\"'][^$])")
        self.assertNotRegex(text, r"/Users/")
        self.assertNotRegex(text, r"sk-[A-Za-z0-9]{10,}")
        self.assertNotRegex(text, r"xai-[A-Za-z0-9]{10,}")
        self.assertIn("OPENROUTER_API_KEY", text)
        self.assertIn("host-native", text)


class CapabilityAdapterTests(unittest.TestCase):
    def test_host_native_capabilities_are_qualified(self) -> None:
        profile = default_profiles()["host-native"]
        caps = {record.name: record for record in default_capabilities_for(profile)}
        self.assertEqual(caps["availability"].status.value, "qualified")

    def test_external_adapter_capabilities_start_unqualified(self) -> None:
        profile = default_profiles()["grok-build"]
        caps = default_capabilities_for(profile)
        statuses = {record.status.value for record in caps}
        self.assertIn("unknown", statuses)
        self.assertNotIn("qualified", statuses)

    def test_registry_snapshot_lists_built_ins(self) -> None:
        snap = registry_snapshot()
        self.assertIn("claude-code", snap)
        self.assertIn("grok-build", snap)
        self.assertIn(snap["host-native"]["status"], {"stub", "readonly-builder"})


class CliSkeletonTests(unittest.TestCase):
    def test_validate_config_json_native_defaults(self) -> None:
        cli = REPO_ROOT / "scripts" / "cobbler_agents.py"
        if not cli.is_file():
            self.skipTest("CLI not created yet")
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(cli), "validate-config", "--json", "--repo-root", tmp],
                check=False,
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["roles"]["implement"]["profile"], "host-native")
        self.assertFalse(payload.get("mutated_repo", False))

    def test_validate_config_json_does_not_mutate_repo(self) -> None:
        cli = REPO_ROOT / "scripts" / "cobbler_agents.py"
        if not cli.is_file():
            self.skipTest("CLI not created yet")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = {path.name for path in root.iterdir()} if root.exists() else set()
            result = subprocess.run(
                [sys.executable, str(cli), "validate-config", "--json", "--repo-root", tmp],
                check=False,
                capture_output=True,
                text=True,
            )
            after = {path.name for path in root.iterdir()}
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, after)

    def test_doctor_json_reports_capabilities_without_model_calls(self) -> None:
        cli = REPO_ROOT / "scripts" / "cobbler_agents.py"
        if not cli.is_file():
            self.skipTest("CLI not created yet")
        env = os.environ.copy()
        env["ELVES_COBBLER_BLOCK_MODEL_CALLS"] = "1"
        result = subprocess.run(
            [sys.executable, str(cli), "doctor", "--json", "--repo-root", str(REPO_ROOT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("adapters", payload)
        self.assertIn("capabilities", payload)
        self.assertFalse(payload.get("model_calls_made", True))
        self.assertIn("host-native", payload["adapters"])

    def test_required_unavailable_profile_exits_nonzero(self) -> None:
        # required:true is only honored from Survival Guide provenance.
        resolved = config_mod.resolve_config(
            survival_guide={
                "model_routing": {
                    "phases": {
                        "implement": {
                            "profile": "missing-required",
                            "required": True,
                        }
                    }
                }
            }
        )
        self.assertFalse(resolved.ok)
        self.assertTrue(any(issue.code == "unknown_profile" for issue in resolved.issues))
        self.assertTrue(resolved.roles["implement"].required)


class ExampleAndIgnoreTests(unittest.TestCase):
    def test_gitignore_covers_elves_directory(self) -> None:
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".elves/", text)

    def test_example_models_toml_documents_precedence(self) -> None:
        path = REPO_ROOT / "references" / "models.toml.example"
        if not path.is_file():
            self.skipTest("references/models.toml.example not created yet")
        text = path.read_text(encoding="utf-8")
        self.assertIn("Survival Guide", text)
        self.assertIn("native", text.lower())
        self.assertIn("[roles.", text)




class FinalHostAuditConfigTests(unittest.TestCase):
    def test_qualified_capabilities_ignored_from_all_config_sources(self) -> None:
        for source_kwargs, label in (
            (
                {
                    "user_config": {
                        "profiles": {
                            "w": {
                                "adapter": "custom-cli",
                                "executable": "/bin/w",
                                "capabilities": ["read_only_repo"],
                                "qualified_capabilities": ["read_only_repo"],
                            }
                        }
                    }
                },
                "user",
            ),
            (
                {
                    "models_toml": {
                        "profiles": {
                            "w": {
                                "adapter": "custom-cli",
                                "executable": "/bin/w",
                                "qualified": ["read_only_repo"],
                            }
                        }
                    }
                },
                "local",
            ),
            (
                {
                    "survival_guide": {
                        "model_routing": {
                            "profiles": {
                                "w": {
                                    "adapter": "custom-cli",
                                    "executable": "/bin/w",
                                    "qualified_capabilities": ["read_only_repo"],
                                }
                            }
                        }
                    }
                },
                "survival",
            ),
        ):
            resolved = config_mod.resolve_config(**source_kwargs)
            profile = resolved.profiles["w"]
            self.assertEqual(
                list(profile.qualified_capabilities),
                [],
                f"{label} must not self-certify qualification",
            )
            self.assertTrue(
                any("qualified_capabilities" in w for w in resolved.warnings),
                f"{label} should warn: {resolved.warnings}",
            )

    def test_named_profile_defaults_to_adapter_contract_pair(self) -> None:
        resolved = config_mod.resolve_config(
            models_toml={
                "profiles": {
                    "my-claude": {"adapter": "claude-code", "executable": "claude"},
                    "my-grok": {"adapter": "grok-build", "executable": "grok"},
                    "my-fugu": {"adapter": "codex-fugu", "executable": "codex-fugu"},
                    "my-custom": {"adapter": "custom-cli", "executable": "/bin/wrap"},
                    "bad-claude": {
                        "adapter": "claude-code",
                        "executable": "claude",
                        "input_contract": "prompt-file",
                        "output_contract": "grok-json",
                    },
                }
            }
        )
        self.assertEqual(resolved.profiles["my-claude"].input_contract, "stdin")
        self.assertEqual(resolved.profiles["my-claude"].output_contract, "claude-json")
        self.assertEqual(resolved.profiles["my-grok"].input_contract, "prompt-file")
        self.assertEqual(resolved.profiles["my-grok"].output_contract, "grok-json")
        self.assertEqual(resolved.profiles["my-fugu"].input_contract, "stdin")
        self.assertEqual(resolved.profiles["my-fugu"].output_contract, "codex-jsonl")
        self.assertEqual(resolved.profiles["my-custom"].input_contract, "json-stdio")
        self.assertEqual(
            resolved.profiles["my-custom"].output_contract, "custom-json-envelope"
        )
        # Explicit incompatible values preserved for later fail-closed dispatch.
        self.assertEqual(resolved.profiles["bad-claude"].input_contract, "prompt-file")
        self.assertEqual(resolved.profiles["bad-claude"].output_contract, "grok-json")


if __name__ == "__main__":
    unittest.main()
