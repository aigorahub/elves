from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_survival_guide.py"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("validate_survival_guide_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load validate_survival_guide module for tests")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def valid_guide_text() -> str:
    return """# Survival Guide

## Run Control

- Run mode: open-ended
- Stop policy: continue until explicit stop or true blocker
- User intent: keep going
- Checkpoint due by: none
- Checkpoint semantics: checkpoint only
- May continue after checkpoint: yes
- Actual stop conditions: explicit stop, true blocker, hard environment failure
- Workspace ownership: one branch and one checkout
- Branch tip at start: abc123
- Merge policy: never merge by default
- Final-response policy: only when Stop Gate allows
- Batch completion rule: commit and push before moving on
- Re-read rule: re-read this guide after every commit and push
- Checkpoint rule: checkpoint is not completion
- Continuation rule: continue without waiting for user acknowledgment

## Cobbler Session State

- Cobbler default: on
- Activated by: Elves invocation
- Scope: current Elves run
- Behavior: treat follow-up prompts as Cobbler-mediated by default
- Persistence: survival guide and .elves-session.json
- Exit phrases: Cobbler Mode: off, leave Cobbler Mode

## Stop Gate

- Planned batches remaining: 2
- Stop allowed right now: no
- Why: work remains
- Next required action: start the next batch

## Effort Standard

- Work as hard as you can for the full run.
- Avoid the minimum acceptable change.
- Take the next highest-value action.

## Forbidden Stop Reasons

- Reaching a checkpoint is not a stop reason.
- Making a commit or push is not a stop reason.
- Writing a tidy summary is not a stop reason.

## Current Phase

- Status: active
- Active batch: Batch 1
- What was just finished: staging
- Single next action: implement

## Active Compute

- None

## Next Exact Batch

- Batch: Batch 1
- Scope: validator checks
- Acceptance criteria: validator reports expected issues
- Risk: low

## Post-Checkpoint Control Loop

- Every completed batch must end with a commit and push.
- After that, re-read this survival guide before doing anything else.
- If the Stop Gate still say `Stop allowed right now: no`, continue.

## After Any Compaction

- Read the Run Control section and Stop Gate first.
- Check `.elves-session.json` continuation_guard before deciding to stop.

## Launch Readiness

- [x] Stop Gate initialized with `Stop allowed right now: no`
"""


VALIDATOR = load_validator_module()


class SurvivalGuideValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = VALIDATOR

    def write_guide(self, text: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "survival-guide.md"
        path.write_text(text)
        return path

    def test_valid_guide_has_no_errors_or_warnings(self) -> None:
        errors, warnings = self.validator.validate(self.write_guide(valid_guide_text()))

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_missing_required_section_reports_error(self) -> None:
        guide = valid_guide_text().replace("## Stop Gate\n", "## Removed Stop Gate\n", 1)

        errors, warnings = self.validator.validate(self.write_guide(guide))

        self.assertIn("missing section `## Stop Gate`", errors)
        self.assertEqual(warnings, [])

    def test_present_section_missing_required_phrase_reports_error(self) -> None:
        guide = valid_guide_text().replace("- Final-response policy: only when Stop Gate allows\n", "")

        errors, _ = self.validator.validate(self.write_guide(guide))

        self.assertIn("`## Run Control` missing `Final-response policy`", errors)

    def test_forbidden_stop_reasons_require_checkpoint_and_commit_signals(self) -> None:
        guide = valid_guide_text().replace(
            """- Reaching a checkpoint is not a stop reason.
- Making a commit or push is not a stop reason.
- Writing a tidy summary is not a stop reason.""",
            """- Feeling tired is not a stop reason.
- Having a clean summary is not a stop reason.
- Being between tasks is not a stop reason.""",
        )

        errors, _ = self.validator.validate(self.write_guide(guide))

        self.assertIn(
            "`## Forbidden Stop Reasons` should explicitly mention checkpoints",
            errors,
        )
        self.assertIn(
            "`## Forbidden Stop Reasons` should explicitly mention commits or pushes",
            errors,
        )

    def test_forbidden_stop_reasons_require_three_false_stop_signals(self) -> None:
        guide = valid_guide_text().replace(
            """- Reaching a checkpoint is not a stop reason.
- Making a commit or push is not a stop reason.
- Writing a tidy summary is not a stop reason.""",
            "- Reaching a checkpoint after a commit and push is not a stop reason.",
        )

        errors, _ = self.validator.validate(self.write_guide(guide))

        self.assertIn(
            "`## Forbidden Stop Reasons` should list at least 3 concrete false stop signals",
            errors,
        )

    def test_placeholder_fields_emit_warnings(self) -> None:
        guide = valid_guide_text().replace("- Run mode: open-ended", "- Run mode: [finite/open-ended]")

        errors, warnings = self.validator.validate(self.write_guide(guide))

        self.assertEqual(errors, [])
        self.assertIn("`## Run Control` still has placeholder content on `Run mode`", warnings)

    def test_launch_readiness_missing_stop_gate_checkbox_emits_warning(self) -> None:
        guide = valid_guide_text().replace(
            "- [x] Stop Gate initialized with `Stop allowed right now: no`\n",
            "",
        )

        errors, warnings = self.validator.validate(self.write_guide(guide))

        self.assertEqual(errors, [])
        self.assertIn(
            "`## Launch Readiness` is missing the Stop Gate initialization checkbox",
            warnings,
        )

    def test_delegated_run_requires_every_control_field(self) -> None:
        delegated_fields = """- E2E mode: chat-to-land
- Work driver: grok-build
- Implementation lane: fast
- Delegation scope: full_run
- Git mode: branch_progress
- Driver monitor mode: parked-monitor
- Driver update policy: bounded events and heartbeats
- Driver review policy: final independent review only
- High-risk checkpoints: final readiness
- Re-drive budget: 3
- Continuation harness: host-native
"""
        guide = valid_guide_text().replace(
            "- Continuation rule: continue without waiting for user acknowledgment\n",
            "- Continuation rule: continue without waiting for user acknowledgment\n"
            + delegated_fields,
        )
        errors, warnings = self.validator.validate(self.write_guide(guide))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

        for field in self.validator.DELEGATED_RUN_CONTROL_FIELDS:
            with self.subTest(field=field):
                without_field = "\n".join(
                    line for line in guide.splitlines() if not line.startswith(f"- {field}:")
                )
                errors, _ = self.validator.validate(self.write_guide(without_field + "\n"))
                self.assertIn(
                    f"`## Run Control` missing delegated field `{field}`",
                    errors,
                )

    def test_load_path_uses_environment_fallback(self) -> None:
        path = self.write_guide(valid_guide_text())

        with mock.patch.dict(os.environ, {"ELVES_SURVIVAL_GUIDE_PATH": str(path)}):
            loaded_path = self.validator.load_path(None)

        self.assertEqual(loaded_path, path.resolve())


if __name__ == "__main__":
    unittest.main()
