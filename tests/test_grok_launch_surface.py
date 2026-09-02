"""The Grok Build launch surface follows the installed CLI, not a stale guess.

Grok Build 1.0.13 removed the top-level `--no-auto-update` and `--check` flags,
which made `run_grok.sh` die on `error: unexpected argument '--check' found`
before the model ever ran. Argv is now built from the flags the installed CLI
advertises: safety flags are required and fail closed when absent, quality flags
are passed only when still advertised, and auto-update suppression moved to the
isolated `[cli] auto_update` config key that every supported version reads.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.grok_launch import (  # noqa: E402
    DEFAULT_GROK_EFFORT,
    inner_sandbox_conflict,
    require_inner_sandbox,
    GrokCapabilities,
    GrokCatalog,
    build_grok_argv,
    isolated_grok_config,
    parse_grok_catalog,
    parse_grok_flags,
    probe_grok_capabilities,
    require_supported_grok_cli,
    resolve_grok_effort,
    resolve_grok_model,
)
from cobbler_runtime.schema import ValidationIssue  # noqa: E402


EXE = "/opt/grok/bin/grok"

# Grok Build 1.0.13: no --no-auto-update, no top-level --check, and the effort
# flag is spelled --reasoning-effort with --effort kept as an alias.
HELP_1_0_13 = """
Grok Build TUI

Usage: grok [OPTIONS] [PROMPT] [COMMAND]

Options:
      --cwd <CWD>
          Working directory
  -m, --model <MODEL>
          Model ID to use
      --output-format <OUTPUT_FORMAT>
          Output format for headless mode
  -p, --single <PROMPT>
          Single-turn prompt. Prints the response to stdout and exits
      --permission-mode <MODE>
          Permission mode
      --reasoning-effort <EFFORT>
          Reasoning effort for reasoning models

          [aliases: --effort]
      --sandbox <PROFILE>
          Sandbox profile for filesystem and network access
"""

# An older compatible release that still advertises both quality flags and the
# older --effort spelling.
HELP_LEGACY = """
Grok Build

Options:
      --no-auto-update
          Do not check for updates on startup
      --check
          Self-check the answer before returning
      --cwd <CWD>
      --sandbox <PROFILE>
      --effort <EFFORT>
      --output-format <FORMAT>
      --model <MODEL>
      --single <PROMPT>
"""

CATALOG_TEXT = """You are using XAI_API_KEY.

Default model: grok-4.6

Available models:
  * grok-4.6 (default)
  - grok-4.5
"""


def _caps(help_text: str, version: str) -> GrokCapabilities:
    return probe_grok_capabilities(EXE, help_text=help_text, version=version)


class FlagParsingTests(unittest.TestCase):
    def test_help_flags_are_read_including_aliases(self) -> None:
        flags = parse_grok_flags(HELP_1_0_13)
        for flag in ("--cwd", "--sandbox", "--output-format", "--single", "--model"):
            self.assertIn(flag, flags)
        self.assertIn("--reasoning-effort", flags)
        self.assertIn("--effort", flags)
        self.assertNotIn("--check", flags)
        self.assertNotIn("--no-auto-update", flags)

    def test_legacy_help_still_advertises_the_quality_flags(self) -> None:
        flags = parse_grok_flags(HELP_LEGACY)
        self.assertIn("--check", flags)
        self.assertIn("--no-auto-update", flags)
        self.assertIn("--effort", flags)
        self.assertNotIn("--reasoning-effort", flags)


class SupportedArgvTests(unittest.TestCase):
    def test_current_cli_argv_drops_only_the_removed_flags(self) -> None:
        plan = build_grok_argv(
            EXE,
            snapshot="/lane/snapshot",
            prompt="review this",
            platform_name="linux",
            outer_backend="bwrap",
            capabilities=_caps(HELP_1_0_13, "1.0.13"),
            effort="xhigh",
            model="grok-4.6",
            auth_route="XAI_API_KEY",
        )
        self.assertEqual(
            list(plan.argv),
            [
                EXE,
                "--cwd",
                "/lane/snapshot",
                "--sandbox",
                "strict",
                "--reasoning-effort",
                "xhigh",
                "--output-format",
                "plain",
                "--model",
                "grok-4.6",
                "--single=review this",
            ],
        )
        self.assertEqual(plan.omitted_flags, ("--no-auto-update", "--check"))
        self.assertEqual(plan.auth_route, "XAI_API_KEY")

    def test_legacy_cli_keeps_its_original_argv(self) -> None:
        plan = build_grok_argv(
            EXE,
            snapshot="/lane/snapshot",
            prompt="do the thing",
            platform_name="linux",
            outer_backend="bwrap",
            capabilities=_caps(HELP_LEGACY, "0.9.1"),
        )
        self.assertEqual(
            list(plan.argv),
            [
                EXE,
                "--no-auto-update",
                "--cwd",
                "/lane/snapshot",
                "--sandbox",
                "strict",
                "--effort",
                "high",
                "--output-format",
                "plain",
                "--check",
                "--single=do the thing",
            ],
        )
        self.assertEqual(plan.omitted_flags, ())
        self.assertEqual(plan.effort, DEFAULT_GROK_EFFORT)

    def test_the_inner_strict_sandbox_is_always_passed(self) -> None:
        for help_text, version in ((HELP_1_0_13, "1.0.13"), (HELP_LEGACY, "0.9.1")):
            plan = build_grok_argv(
                EXE,
                snapshot="/lane/snapshot",
                prompt="x",
                platform_name="linux",
            outer_backend="bwrap",
            capabilities=_caps(help_text, version),
            )
            argv = list(plan.argv)
            self.assertIn("--sandbox", argv, version)
            self.assertEqual(argv[argv.index("--sandbox") + 1], "strict", version)
            self.assertIn("--cwd", argv, version)
            self.assertEqual(argv[argv.index("--cwd") + 1], "/lane/snapshot", version)
            self.assertTrue(argv[-1].startswith("--single="), version)

    def test_prompt_is_never_split_across_argv(self) -> None:
        plan = build_grok_argv(
            EXE,
            snapshot="/s",
            prompt="line one\n--sandbox permissive\nline three",
            platform_name="linux",
            outer_backend="bwrap",
            capabilities=_caps(HELP_1_0_13, "1.0.13"),
        )
        self.assertEqual(
            plan.argv[-1], "--single=line one\n--sandbox permissive\nline three"
        )
        self.assertEqual(plan.argv.count("--sandbox"), 1)

    def test_relative_executable_fails_closed(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            build_grok_argv(
                "grok",
                snapshot="/s",
                prompt="x",
                platform_name="linux",
            outer_backend="bwrap",
            capabilities=_caps(HELP_1_0_13, "1.0.13"),
            )
        self.assertEqual(ctx.exception.code, "grok_executable_not_absolute")


class FailClosedTests(unittest.TestCase):
    def test_missing_sandbox_flag_blocks_the_launch(self) -> None:
        stripped = HELP_1_0_13.replace("--sandbox <PROFILE>", "--profile <PROFILE>")
        with self.assertRaises(ValidationIssue) as ctx:
            require_supported_grok_cli(_caps(stripped, "9.9.9"))
        self.assertEqual(ctx.exception.code, "grok_cli_incompatible")
        self.assertIn("--sandbox", ctx.exception.message)

    def test_missing_cwd_or_single_blocks_the_launch(self) -> None:
        for removed in ("--cwd <CWD>", "--single <PROMPT>", "--output-format <OUTPUT_FORMAT>"):
            stripped = HELP_1_0_13.replace(removed, "--gone <X>")
            with self.assertRaises(ValidationIssue) as ctx:
                build_grok_argv(
                    EXE,
                    snapshot="/s",
                    prompt="x",
                    platform_name="linux",
            outer_backend="bwrap",
            capabilities=_caps(stripped, "9.9.9"),
                )
            self.assertEqual(ctx.exception.code, "grok_cli_incompatible", removed)

    def test_missing_effort_flag_blocks_the_launch(self) -> None:
        stripped = HELP_1_0_13.replace("--reasoning-effort <EFFORT>", "--x <EFFORT>")
        stripped = stripped.replace("[aliases: --effort]", "[aliases: none]")
        with self.assertRaises(ValidationIssue) as ctx:
            require_supported_grok_cli(_caps(stripped, "9.9.9"))
        self.assertEqual(ctx.exception.code, "grok_cli_incompatible")

    def test_unknown_effort_is_rejected(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            resolve_grok_effort("ludicrous")
        self.assertEqual(ctx.exception.code, "invalid_grok_effort")
        self.assertEqual(resolve_grok_effort(""), DEFAULT_GROK_EFFORT)
        self.assertEqual(resolve_grok_effort(None), DEFAULT_GROK_EFFORT)
        self.assertEqual(resolve_grok_effort(" XHIGH "), "xhigh")

    def test_model_selection_requires_a_flag_the_cli_advertises(self) -> None:
        stripped = HELP_1_0_13.replace("-m, --model <MODEL>", "--pinned <MODEL>")
        with self.assertRaises(ValidationIssue) as ctx:
            build_grok_argv(
                EXE,
                snapshot="/s",
                prompt="x",
                platform_name="linux",
            outer_backend="bwrap",
            capabilities=_caps(stripped, "9.9.9"),
                model="grok-4.6",
            )
        self.assertEqual(ctx.exception.code, "grok_model_flag_unsupported")


class InnerSandboxTests(unittest.TestCase):
    """The inner profile is never dropped to make a launch succeed."""

    def test_macos_cannot_nest_the_inner_profile(self) -> None:
        conflict = inner_sandbox_conflict(
            platform_name="darwin", outer_backend="sandbox-exec"
        )
        self.assertIsNotNone(conflict)
        self.assertIn("cannot nest sandboxes", conflict or "")
        with self.assertRaises(ValidationIssue) as ctx:
            require_inner_sandbox(platform_name="darwin", outer_backend="sandbox-exec")
        self.assertEqual(ctx.exception.code, "grok_inner_sandbox_unavailable")
        # The remediation never suggests weakening either boundary.
        hint = ctx.exception.hint or ""
        self.assertIn("will not drop the inner profile", hint)
        self.assertIn("outer boundary is not optional", hint)

    def test_linux_bwrap_is_not_blocked_by_elves(self) -> None:
        self.assertIsNone(
            inner_sandbox_conflict(platform_name="linux", outer_backend="bwrap")
        )
        require_inner_sandbox(platform_name="linux", outer_backend="bwrap")

    def test_no_outer_backend_is_not_a_nesting_conflict(self) -> None:
        self.assertIsNone(
            inner_sandbox_conflict(platform_name="darwin", outer_backend=None)
        )

    def test_a_disabled_inner_profile_is_not_the_nesting_case(self) -> None:
        # Elves never selects these, but the rule must not misfire on them.
        for profile in ("", "none", "off"):
            self.assertIsNone(
                inner_sandbox_conflict(
                    platform_name="darwin",
                    outer_backend="sandbox-exec",
                    profile=profile,
                ),
                profile,
            )


    def test_build_argv_cannot_skip_the_nesting_check(self) -> None:
        # A second launcher must not be able to reach argv without the check.
        with self.assertRaises(ValidationIssue) as ctx:
            build_grok_argv(
                EXE,
                snapshot="/s",
                prompt="x",
                platform_name="darwin",
                outer_backend="sandbox-exec",
                capabilities=_caps(HELP_1_0_13, "1.0.13"),
            )
        self.assertEqual(ctx.exception.code, "grok_inner_sandbox_unavailable")


class HelpParsingPrecisionTests(unittest.TestCase):
    """Prose is not an advertisement. Only option rows and alias rows count."""

    def test_a_flag_named_only_in_prose_is_not_advertised(self) -> None:
        help_text = HELP_1_0_13 + """
      --output-format <FORMAT>
          The --check flag was removed in 1.0.13; --no-auto-update is gone too.
"""
        flags = parse_grok_flags(help_text)
        self.assertNotIn("--check", flags)
        self.assertNotIn("--no-auto-update", flags)
        plan = build_grok_argv(
            EXE,
            snapshot="/s",
            prompt="x",
            platform_name="linux",
            outer_backend="bwrap",
            capabilities=probe_grok_capabilities(
                EXE, help_text=help_text, version="1.0.13"
            ),
        )
        self.assertNotIn("--check", plan.argv)
        self.assertNotIn("--no-auto-update", plan.argv)

    def test_alias_rows_still_count_as_advertised(self) -> None:
        flags = parse_grok_flags(HELP_1_0_13)
        self.assertIn("--effort", flags)
        self.assertIn("--reasoning-effort", flags)

    def test_a_renamed_required_flag_is_not_rescued_by_prose(self) -> None:
        help_text = HELP_1_0_13.replace("--sandbox <PROFILE>", "--profile <PROFILE>")
        help_text += "\n          Note: --sandbox is the old name for --profile.\n"
        with self.assertRaises(ValidationIssue) as ctx:
            require_supported_grok_cli(
                probe_grok_capabilities(EXE, help_text=help_text, version="9.9.9")
            )
        self.assertEqual(ctx.exception.code, "grok_cli_incompatible")


class CatalogTests(unittest.TestCase):
    def test_live_catalog_and_auth_route_are_read(self) -> None:
        catalog = parse_grok_catalog(CATALOG_TEXT)
        self.assertEqual(catalog.models, ("grok-4.6", "grok-4.5"))
        self.assertEqual(catalog.auth_route, "XAI_API_KEY")
        self.assertTrue(catalog.available)

    def test_both_real_authentication_routes_are_recognized(self) -> None:
        # The API key and the Grok Build subscription bill different accounts,
        # so the record must tell them apart.
        subscription = parse_grok_catalog(
            CATALOG_TEXT.replace(
                "You are using XAI_API_KEY.", "You are logged in with grok.com."
            )
        )
        self.assertEqual(subscription.auth_route, "grok.com")

    def test_an_unrecognized_auth_line_never_reaches_stderr_verbatim(self) -> None:
        # The route label is printed. A future CLI must not be able to put a
        # credential-shaped blob on that line and have it echoed.
        leaky = CATALOG_TEXT.replace(
            "You are using XAI_API_KEY.", "You are using xai-" + "A" * 120
        )
        self.assertEqual(parse_grok_catalog(leaky).auth_route, "unrecognized")

    def test_a_model_outside_the_live_catalog_is_never_invented(self) -> None:
        catalog = parse_grok_catalog(CATALOG_TEXT)
        self.assertEqual(resolve_grok_model("grok-4.6", catalog), "grok-4.6")
        with self.assertRaises(ValidationIssue) as ctx:
            resolve_grok_model("grok-4.6-fast", catalog)
        self.assertEqual(ctx.exception.code, "grok_model_not_in_catalog")

    def test_an_unreadable_catalog_blocks_an_explicit_model(self) -> None:
        with self.assertRaises(ValidationIssue) as ctx:
            resolve_grok_model("grok-4.6", GrokCatalog(available=False, reason="probe"))
        self.assertEqual(ctx.exception.code, "grok_catalog_unavailable")

    def test_no_requested_model_needs_no_catalog(self) -> None:
        self.assertIsNone(resolve_grok_model("", GrokCatalog(available=False)))
        self.assertIsNone(resolve_grok_model(None, GrokCatalog(available=False)))


class IsolatedConfigTests(unittest.TestCase):
    def test_auto_update_is_disabled_in_every_isolated_config(self) -> None:
        body = isolated_grok_config()
        self.assertIn("[cli]", body)
        self.assertIn("auto_update = false", body)
        self.assertNotIn("[models]", body)

    def test_model_default_is_the_only_extra_key(self) -> None:
        body = isolated_grok_config(model_default="grok-4.6")
        self.assertIn("auto_update = false", body)
        self.assertIn('default = "grok-4.6"', body)
        # The host's own posture is never copied into the lane.
        for leaked in ("permission_mode", "yolo", "mcp_servers", "plugins", "marketplace"):
            self.assertNotIn(leaked, body)


class RunnerWiringTests(unittest.TestCase):
    def test_runner_no_longer_hardcodes_the_removed_flags(self) -> None:
        body = (REPO_ROOT / "scripts" / "run_grok.sh").read_text(encoding="utf-8")
        self.assertNotIn('"--no-auto-update"', body)
        self.assertNotIn('"--check"', body)
        self.assertIn("build_grok_argv", body)
        self.assertIn("probe_grok_capabilities", body)
        self.assertIn("isolated_grok_config", body)
        self.assertIn("require_inner_sandbox", body)

    def test_runner_keeps_its_isolation_and_credential_posture(self) -> None:
        body = (REPO_ROOT / "scripts" / "run_grok.sh").read_text(encoding="utf-8")
        self.assertIn("require_fs_sandbox=True", body)
        self.assertIn("credential_grants={credential_name: credential_value}", body)
        self.assertIn("wrap_argv_with_sandbox", body)
        self.assertIn("mount_proc=False", body)
        self.assertIn("unset XAI_API_KEY GROK_CODE_XAI_API_KEY", body)
        self.assertIn('"defaultMode": "dontAsk"', body)
        self.assertIn("disable_bypass_permissions_mode = true", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
