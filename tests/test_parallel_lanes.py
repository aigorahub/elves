"""Deterministic Parallelves lane validator, width test, preference, and CLI tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
CLI = SCRIPTS / "cobbler_agents.py"
TEMPLATE = REPO_ROOT / "references" / "plan-template.md"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import cobbler_agents  # noqa: E402
from cobbler_runtime import parallel_lanes as pl  # noqa: E402
from cobbler_runtime import preferences  # noqa: E402
from cobbler_runtime.schema import ValidationIssue  # noqa: E402


VALID_PLAN = """# Plan

## Lanes

```yaml
trunk:
  - B1
lanes:
  - id: L1
    name: Validator core
    depends_on: []
    owned_surfaces:
      - scripts/validator/
    batches:
      - B2
  - id: L2
    name: Docs
    depends_on: []
    owned_surfaces:
      - docs/validator.md
    batches:
      - B3
```
"""


def _lane(lane_id, surfaces, depends_on=()):
    return {
        "id": lane_id,
        "name": f"Lane {lane_id}",
        "depends_on": list(depends_on),
        "owned_surfaces": list(surfaces),
        "batches": ["B2"],
    }


def _plan_with_block(block_body: str) -> str:
    return f"# Plan\n\n## Lanes\n\n```yaml\n{block_body}```\n"


class LanesGrammarTests(unittest.TestCase):
    def test_golden_template_example_parses_verbatim(self) -> None:
        # Extracted from references/plan-template.md at test time so drift fails.
        text = TEMPLATE.read_text(encoding="utf-8")
        block = pl.extract_lanes_block(text)
        raw = [line for _, line in block]
        self.assertIn("    depends_on: []", raw)  # documented inline empty list
        parsed = pl.parse_lanes_block(block)
        self.assertEqual(parsed["trunk"], ["B1"])
        self.assertEqual([lane["id"] for lane in parsed["lanes"]], ["L1", "L2"])
        first = parsed["lanes"][0]
        self.assertEqual(first["name"], "Validator core")
        self.assertEqual(first["depends_on"], [])
        self.assertEqual(
            first["owned_surfaces"], ["scripts/validator/", "tests/test_validator.py"]
        )
        self.assertEqual(first["batches"], ["B2"])
        self.assertEqual(pl.validate_lane_partition(parsed["lanes"]), [])

    def test_missing_section_fails_closed(self) -> None:
        with self.assertRaises(ValidationIssue) as caught:
            pl.extract_lanes_block("# Plan\n\nNo lanes here.\n")
        self.assertEqual(caught.exception.code, "parallel_lanes_missing")

    def test_section_without_fenced_block_fails_closed(self) -> None:
        with self.assertRaises(ValidationIssue) as caught:
            pl.extract_lanes_block("# Plan\n\n## Lanes\n\nprose only\n\n## Next\n")
        self.assertEqual(caught.exception.code, "parallel_lanes_missing")

    def test_unknown_lane_field_rejected(self) -> None:
        block = pl.extract_lanes_block(
            _plan_with_block("lanes:\n  - id: L1\n    owner: me\n")
        )
        with self.assertRaises(ValidationIssue) as caught:
            pl.parse_lanes_block(block)
        self.assertEqual(caught.exception.code, "parallel_lanes_grammar_invalid")
        self.assertIn("line", caught.exception.message)

    def test_non_list_depends_on_rejected(self) -> None:
        block = pl.extract_lanes_block(
            _plan_with_block("lanes:\n  - id: L1\n    depends_on: L2\n")
        )
        with self.assertRaises(ValidationIssue) as caught:
            pl.parse_lanes_block(block)
        self.assertEqual(caught.exception.code, "parallel_lanes_grammar_invalid")

    def test_missing_required_lane_fields_rejected(self) -> None:
        required_snippets = {
            "name": "    name: Validator core\n",
            "depends_on": "    depends_on: []\n",
            "owned_surfaces": (
                "    owned_surfaces:\n"
                "      - scripts/validator/\n"
            ),
            "batches": "    batches:\n      - B2\n",
        }
        for field, snippet in required_snippets.items():
            with self.subTest(field=field):
                malformed = VALID_PLAN.replace(snippet, "", 1)
                block = pl.extract_lanes_block(malformed)
                with self.assertRaises(ValidationIssue) as caught:
                    pl.parse_lanes_block(block)
                self.assertEqual(
                    caught.exception.code, "parallel_lanes_grammar_invalid"
                )
                self.assertIn(field, caught.exception.message)

    def test_duplicate_and_malformed_ids_rejected_by_partition(self) -> None:
        duplicate = [_lane("L1", ["a/"]), _lane("L1", ["b/"])]
        codes = [issue.code for issue in pl.validate_lane_partition(duplicate)]
        self.assertIn("parallel_lanes_id_invalid", codes)
        malformed = [_lane("lane-one", ["a/"])]
        codes = [issue.code for issue in pl.validate_lane_partition(malformed)]
        self.assertIn("parallel_lanes_id_invalid", codes)

    def test_empty_surfaces_rejected(self) -> None:
        codes = [issue.code for issue in pl.validate_lane_partition([_lane("L1", [])])]
        self.assertIn("parallel_lanes_surfaces_required", codes)

    def test_empty_batches_rejected(self) -> None:
        lane = _lane("L1", ["a/"])
        lane["batches"] = []
        codes = [issue.code for issue in pl.validate_lane_partition([lane])]
        self.assertIn("parallel_lanes_batches_required", codes)


class LanesFenceAndDuplicateTests(unittest.TestCase):
    def test_fence_decoy_heading_is_ignored(self) -> None:
        decoy = (
            "# Plan\n\n```md\n## Lanes\ndecoy inside a fence\n```\n\n"
            + VALID_PLAN.split("# Plan\n", 1)[1]
        )
        parsed = pl.parse_lanes_block(pl.extract_lanes_block(decoy))
        self.assertEqual([lane["id"] for lane in parsed["lanes"]], ["L1", "L2"])

    def test_fence_decoy_only_means_missing(self) -> None:
        text = "# Plan\n\n```md\n## Lanes\n```\n\nprose\n"
        with self.assertRaises(ValidationIssue) as caught:
            pl.extract_lanes_block(text)
        self.assertEqual(caught.exception.code, "parallel_lanes_missing")

    def test_duplicate_lanes_section_rejected(self) -> None:
        text = VALID_PLAN + "\n## Lanes\n\n```yaml\nlanes:\n```\n"
        with self.assertRaises(ValidationIssue) as caught:
            pl.extract_lanes_block(text)
        self.assertEqual(caught.exception.code, "parallel_lanes_grammar_invalid")
        self.assertIn("line", caught.exception.message)

    def test_second_fenced_block_in_section_rejected(self) -> None:
        text = VALID_PLAN + "\n```yaml\nlanes:\n```\n"
        with self.assertRaises(ValidationIssue) as caught:
            pl.extract_lanes_block(text)
        self.assertEqual(caught.exception.code, "parallel_lanes_grammar_invalid")

    def test_duplicate_key_within_lane_item_rejected(self) -> None:
        block = pl.extract_lanes_block(
            _plan_with_block(
                "lanes:\n  - id: L1\n    name: One\n    name: Two\n"
            )
        )
        with self.assertRaises(ValidationIssue) as caught:
            pl.parse_lanes_block(block)
        self.assertEqual(caught.exception.code, "parallel_lanes_grammar_invalid")
        self.assertIn("line", caught.exception.message)


class LanePartitionTests(unittest.TestCase):
    def test_exact_duplicate_surface_overlap(self) -> None:
        lanes = [_lane("L1", ["scripts/foo.py"]), _lane("L2", ["scripts/foo.py"])]
        issues = pl.validate_lane_partition(lanes)
        self.assertIn("parallel_lanes_surface_overlap", [i.code for i in issues])
        message = issues[0].message
        self.assertIn("L1", message)
        self.assertIn("L2", message)
        self.assertIn("scripts/foo.py", message)

    def test_nested_prefix_overlap_both_directions(self) -> None:
        forward = [_lane("L1", ["scripts/foo/"]), _lane("L2", ["scripts/foo/bar.py"])]
        backward = [_lane("L1", ["scripts/foo/bar.py"]), _lane("L2", ["scripts/foo/"])]
        for lanes in (forward, backward):
            codes = [issue.code for issue in pl.validate_lane_partition(lanes)]
            self.assertIn("parallel_lanes_surface_overlap", codes)

    def test_disjoint_sibling_paths_do_not_overlap(self) -> None:
        lanes = [_lane("L1", ["scripts/foo/"]), _lane("L2", ["scripts/foobar/"])]
        self.assertEqual(pl.validate_lane_partition(lanes), [])

    def test_unknown_dependency_rejected(self) -> None:
        lanes = [_lane("L1", ["a/"], depends_on=["L9"]), _lane("L2", ["b/"])]
        codes = [issue.code for issue in pl.validate_lane_partition(lanes)]
        self.assertIn("parallel_lanes_dependency_unknown", codes)

    def test_trunk_batch_dependency_is_not_unknown(self) -> None:
        lanes = [_lane("L1", ["a/"], depends_on=["B1"]), _lane("L2", ["b/"])]
        self.assertEqual(pl.validate_lane_partition(lanes), [])

    def test_surface_invalid_shapes_rejected(self) -> None:
        for surface in ("", "   ", ".", "/", "/etc/passwd", "../up", "..", "a/.."):
            with self.subTest(surface=repr(surface)):
                issues = pl.validate_lane_partition(
                    [_lane("L1", [surface]), _lane("L2", ["b/"])]
                )
                codes = [issue.code for issue in issues]
                self.assertIn("parallel_lanes_surface_invalid", codes)
                invalid = next(
                    issue
                    for issue in issues
                    if issue.code == "parallel_lanes_surface_invalid"
                )
                self.assertIn("L1", invalid.message)
                self.assertIn(surface, invalid.message)

    def test_case_insensitive_overlap_is_flagged(self) -> None:
        lanes = [_lane("L1", ["Scripts/Foo/"]), _lane("L2", ["scripts/foo/bar.py"])]
        codes = [issue.code for issue in pl.validate_lane_partition(lanes)]
        self.assertIn("parallel_lanes_surface_overlap", codes)

    def test_deep_dependency_chain_validates_without_recursion_error(self) -> None:
        depth = 1500
        lanes = [
            _lane(
                f"L{n}",
                [f"dir{n}/"],
                depends_on=[f"L{n + 1}"] if n < depth else [],
            )
            for n in range(1, depth + 1)
        ]
        self.assertEqual(pl.validate_lane_partition(lanes), [])

    def test_dependency_cycle_detected(self) -> None:
        lanes = [
            _lane("L1", ["a/"], depends_on=["L2"]),
            _lane("L2", ["b/"], depends_on=["L1"]),
        ]
        codes = [issue.code for issue in pl.validate_lane_partition(lanes)]
        self.assertIn("parallel_lanes_dependency_cycle", codes)


class WidthTestTests(unittest.TestCase):
    GOOD_TIMINGS = {"worker_seconds": 100.0, "driver_seconds": 10.0}

    def _pair(self):
        return [_lane("L1", ["a/"]), _lane("L2", ["b/"])]

    def test_no_lanes_declines_structural_width(self) -> None:
        result = pl.width_test([], timings=self.GOOD_TIMINGS)
        self.assertFalse(result["parallel"])
        self.assertIn(
            "parallel_declined:structural_width:no_lanes_declared", result["declined"]
        )

    def test_single_lane_declines_structural_width(self) -> None:
        result = pl.width_test([_lane("L1", ["a/"])], timings=self.GOOD_TIMINGS)
        self.assertFalse(result["parallel"])
        self.assertIn(
            "parallel_declined:structural_width:single_lane", result["declined"]
        )

    def test_cross_lane_dependency_declines_structural_width(self) -> None:
        lanes = [_lane("L1", ["a/"]), _lane("L2", ["b/"], depends_on=["L1"])]
        result = pl.width_test(lanes, timings=self.GOOD_TIMINGS)
        self.assertFalse(result["parallel"])
        self.assertIn(
            "parallel_declined:structural_width:cross_lane_dependency",
            result["declined"],
        )

    def test_trunk_dependency_does_not_fail_structural_width(self) -> None:
        lanes = [_lane("L1", ["a/"], depends_on=["B1"]), _lane("L2", ["b/"])]
        result = pl.width_test(lanes, timings=self.GOOD_TIMINGS)
        self.assertTrue(result["parallel"])

    def test_absent_timings_decline_worker_dominance(self) -> None:
        result = pl.width_test(self._pair(), timings=None)
        self.assertFalse(result["parallel"])
        self.assertIn(
            "parallel_declined:worker_dominance:no_recorded_timings",
            result["declined"],
        )

    def test_missing_timing_keys_decline_worker_dominance(self) -> None:
        result = pl.width_test(self._pair(), timings={"worker_seconds": 10})
        self.assertIn(
            "parallel_declined:worker_dominance:no_recorded_timings",
            result["declined"],
        )

    def test_driver_dominant_timings_decline(self) -> None:
        result = pl.width_test(
            self._pair(), timings={"worker_seconds": 10, "driver_seconds": 6}
        )
        self.assertFalse(result["parallel"])
        self.assertIn(
            "parallel_declined:worker_dominance:driver_review_dominates",
            result["declined"],
        )

    def test_zero_worker_timings_decline_as_invalid_evidence(self) -> None:
        result = pl.width_test(
            self._pair(), timings={"worker_seconds": 0, "driver_seconds": 0}
        )
        self.assertFalse(result["parallel"])
        self.assertIn(
            "parallel_declined:worker_dominance:invalid_timings",
            result["declined"],
        )

    def test_zero_driver_timing_is_valid_evidence(self) -> None:
        result = pl.width_test(
            self._pair(), timings={"worker_seconds": 100, "driver_seconds": 0}
        )
        self.assertTrue(result["parallel"])
        self.assertEqual(result["declined"], [])

    def test_over_budget_declines_lane_budget(self) -> None:
        lanes = [_lane(f"L{n}", [f"dir{n}/"]) for n in range(1, 5)]
        for requested_max in (3, 4):
            with self.subTest(requested_max=requested_max):
                result = pl.width_test(
                    lanes, timings=self.GOOD_TIMINGS, max_lanes=requested_max
                )
                self.assertFalse(result["parallel"])
                self.assertIn(
                    "parallel_declined:lane_budget:over_max_lanes",
                    result["declined"],
                )

    def test_high_risk_declines_risk_posture(self) -> None:
        result = pl.width_test(self._pair(), timings=self.GOOD_TIMINGS, risk="high")
        self.assertFalse(result["parallel"])
        self.assertIn(
            "parallel_declined:risk_posture:high_risk_serial", result["declined"]
        )

    def test_invalid_timing_values_decline_not_recommend(self) -> None:
        cases = (
            {"worker_seconds": float("nan"), "driver_seconds": 10},
            {"worker_seconds": 100, "driver_seconds": float("nan")},
            {"worker_seconds": float("inf"), "driver_seconds": 10},
            {"worker_seconds": -100, "driver_seconds": 10},
            {"worker_seconds": 100, "driver_seconds": -1},
            {"worker_seconds": "100", "driver_seconds": 10},
            {"worker_seconds": True, "driver_seconds": 10},
            {"worker_seconds": 10**400, "driver_seconds": 10},
        )
        for timings in cases:
            with self.subTest(timings=timings):
                result = pl.width_test(self._pair(), timings=timings)
                self.assertFalse(result["parallel"])
                self.assertIn(
                    "parallel_declined:worker_dominance:invalid_timings",
                    result["declined"],
                )

    def test_unknown_risk_posture_raises(self) -> None:
        with self.assertRaises(ValidationIssue) as caught:
            pl.width_test(self._pair(), timings=self.GOOD_TIMINGS, risk="HIGH")
        self.assertEqual(caught.exception.code, "parallel_lanes_risk_invalid")

    def test_all_gates_pass_recommends_parallel(self) -> None:
        result = pl.width_test(self._pair(), timings=self.GOOD_TIMINGS)
        self.assertEqual(
            result, {"parallel": True, "lanes": ["L1", "L2"], "declined": []}
        )


class WorkerParallelPreferenceTests(unittest.TestCase):
    def test_default_is_off(self) -> None:
        self.assertEqual(
            preferences.DEFAULT_PREFERENCES["worker"]["parallel"], "off"
        )
        with tempfile.TemporaryDirectory() as raw:
            values = preferences.load_preferences(Path(raw) / "missing.json")
        self.assertEqual(values["worker"]["parallel"], "off")

    def test_round_trip_auto(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "config.json"
            preferences.set_preference("worker.parallel", "auto", path=target)
            values = preferences.load_preferences(target)
        self.assertEqual(values["worker"]["parallel"], "auto")

    def test_rejects_unknown_value(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "config.json"
            with self.assertRaises(ValidationIssue) as caught:
                preferences.set_preference("worker.parallel", "on", path=target)
        self.assertEqual(caught.exception.code, "invalid_global_preference")

    def test_grants_nothing_no_authority_fields(self) -> None:
        snapshot = preferences.PreferenceSnapshot(path="x", values={}, exists=False)
        self.assertFalse(snapshot.to_dict()["authority_fields_supported"])


class LaneTimingsLoaderTests(unittest.TestCase):
    def _write_and_load(self, content: str):
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "timings.json"
            target.write_text(content, encoding="utf-8")
            return cobbler_agents._load_lane_timings(target)

    def _assert_rejects(self, content: str) -> None:
        with self.assertRaises(ValidationIssue) as caught:
            self._write_and_load(content)
        self.assertEqual(caught.exception.code, "parallel_lanes_timings_invalid")

    def test_valid_timings_load(self) -> None:
        data = self._write_and_load('{"worker_seconds": 100, "driver_seconds": 10}')
        self.assertEqual(data["worker_seconds"], 100)

    def test_rejects_bad_values(self) -> None:
        huge = "1" + "0" * 400
        cases = {
            "non_numeric": '{"worker_seconds": "100", "driver_seconds": 10}',
            "bool": '{"worker_seconds": true, "driver_seconds": 10}',
            "nan": '{"worker_seconds": NaN, "driver_seconds": 10}',
            "infinity": '{"worker_seconds": Infinity, "driver_seconds": 10}',
            "negative": '{"worker_seconds": 100, "driver_seconds": -10}',
            "huge_int_overflow": (
                '{"worker_seconds": ' + huge + ', "driver_seconds": 10}'
            ),
            "non_object": '[1, 2]',
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                self._assert_rejects(content)

    def test_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            real = base / "real.json"
            real.write_text(
                '{"worker_seconds": 100, "driver_seconds": 10}', encoding="utf-8"
            )
            link = base / "link.json"
            link.symlink_to(real)
            with self.assertRaises(ValidationIssue) as caught:
                cobbler_agents._load_lane_timings(link)
        self.assertEqual(caught.exception.code, "parallel_lanes_timings_invalid")

    def test_rejects_oversized_file(self) -> None:
        padding = '{"worker_seconds": 100, "driver_seconds": 10, "pad": "'
        content = padding + "x" * (64 * 1024) + '"}'
        self._assert_rejects(content)


class LanesCliTests(unittest.TestCase):
    def _run(self, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(
            [sys.executable, str(CLI), "lanes", *args],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def _parallel_env(self, directory: Path, value: str) -> dict[str, str]:
        config_root = directory / "xdg"
        preferences.set_preference(
            "worker.parallel", value, path=config_root / "elves" / "config.json"
        )
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(config_root)
        return env

    def _write_plan(self, directory: Path, content: str = VALID_PLAN) -> Path:
        plan = directory / "plan.md"
        plan.write_text(content, encoding="utf-8")
        return plan

    def test_validate_ok(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            plan = self._write_plan(Path(raw))
            proc = self._run("validate", "--plan", str(plan), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["issues"], [])
        self.assertEqual(payload["lanes"], ["L1", "L2"])
        self.assertEqual(payload["trunk"], ["B1"])
        self.assertFalse(payload["mutated_repo"])
        self.assertFalse(payload["model_calls_made"])

    def test_validate_bad_partition_is_envelope_exit_1(self) -> None:
        overlapping = VALID_PLAN.replace("docs/validator.md", "scripts/validator/x.py")
        with tempfile.TemporaryDirectory() as raw:
            plan = self._write_plan(Path(raw), overlapping)
            proc = self._run("validate", "--plan", str(plan), "--json")
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            payload["issues"][0]["code"], "parallel_lanes_surface_overlap"
        )
        self.assertNotIn("Traceback", proc.stderr)

    def test_incomplete_lane_declaration_is_error_not_recommendation(self) -> None:
        incomplete = VALID_PLAN.replace("    batches:\n      - B2\n", "", 1)
        with tempfile.TemporaryDirectory() as raw:
            plan = self._write_plan(Path(raw), incomplete)
            for action in ("validate", "plan"):
                with self.subTest(action=action):
                    proc = self._run(action, "--plan", str(plan), "--json")
                    self.assertEqual(proc.returncode, 1, proc.stderr)
                    payload = json.loads(proc.stdout)
                    self.assertFalse(payload["ok"])
                    self.assertEqual(
                        payload["issues"][0]["code"],
                        "parallel_lanes_grammar_invalid",
                    )

    def test_plan_declines_without_timings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            plan = self._write_plan(Path(raw))
            proc = self._run("plan", "--plan", str(plan), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["parallel"])
        self.assertIn(
            "parallel_declined:worker_dominance:no_recorded_timings",
            payload["declined"],
        )

    def test_plan_passes_with_timings_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            plan = self._write_plan(base)
            timings = base / "timings.json"
            timings.write_text(
                json.dumps({"worker_seconds": 100, "driver_seconds": 10}),
                encoding="utf-8",
            )
            env = self._parallel_env(base, "auto")
            proc = self._run(
                "plan",
                "--plan",
                str(plan),
                "--timings",
                str(timings),
                "--json",
                env=env,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["parallel"])
        self.assertEqual(payload["declined"], [])
        self.assertEqual(payload["lanes"], ["L1", "L2"])
        self.assertEqual(payload["parallel_preference"], "auto")

    def test_plan_respects_off_preference_when_width_gates_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            plan = self._write_plan(base)
            timings = base / "timings.json"
            timings.write_text(
                json.dumps({"worker_seconds": 100, "driver_seconds": 10}),
                encoding="utf-8",
            )
            env = self._parallel_env(base, "off")
            proc = self._run(
                "plan",
                "--plan",
                str(plan),
                "--timings",
                str(timings),
                "--json",
                env=env,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["parallel"])
        self.assertEqual(payload["parallel_preference"], "off")
        self.assertIn("parallel_declined:preference:off", payload["declined"])

    def test_plan_enforces_fixed_v1_lane_cap(self) -> None:
        extra_lanes = """  - id: L3
    name: Tests
    depends_on: []
    owned_surfaces: [tests/three.py]
    batches: [B4]
  - id: L4
    name: Guide
    depends_on: []
    owned_surfaces: [guide/four.md]
    batches: [B5]
"""
        four_lane_plan = VALID_PLAN.replace("```\n", extra_lanes + "```\n", 1)
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            plan = self._write_plan(base, four_lane_plan)
            timings = base / "timings.json"
            timings.write_text(
                json.dumps({"worker_seconds": 100, "driver_seconds": 10}),
                encoding="utf-8",
            )
            env = self._parallel_env(base, "auto")
            proc = self._run(
                "plan",
                "--plan",
                str(plan),
                "--timings",
                str(timings),
                "--json",
                env=env,
            )
            help_proc = self._run("plan", "--help", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["parallel"])
        self.assertIn(
            "parallel_declined:lane_budget:over_max_lanes", payload["declined"]
        )
        self.assertNotIn("--max-lanes", help_proc.stdout)

    def test_plan_mode_no_lanes_section_translates_to_honest_decline(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            plan = self._write_plan(base, "# Plan\n\nNo lanes section here.\n")
            env = self._parallel_env(base, "auto")
            proc = self._run("plan", "--plan", str(plan), "--json", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["parallel"])
        self.assertEqual(
            payload["declined"],
            ["parallel_declined:structural_width:no_lanes_declared"],
        )
        self.assertEqual(payload["parallel_preference"], "auto")

    def test_plan_mode_partition_invalid_declines(self) -> None:
        overlapping = VALID_PLAN.replace("docs/validator.md", "scripts/validator/x.py")
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            plan = self._write_plan(base, overlapping)
            env = self._parallel_env(base, "auto")
            proc = self._run("plan", "--plan", str(plan), "--json", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["parallel"])
        self.assertIn(
            "parallel_declined:structural_width:partition_invalid",
            payload["declined"],
        )
        self.assertEqual(
            payload["issues"][0]["code"], "parallel_lanes_surface_overlap"
        )
        self.assertEqual(payload["parallel_preference"], "auto")

    def test_plan_rejects_malformed_parallel_preference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            plan = self._write_plan(base)
            config = base / "xdg" / "elves" / "config.json"
            config.parent.mkdir(parents=True)
            config.write_text(
                json.dumps({"version": 1, "worker": {"parallel": "sometimes"}}),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["XDG_CONFIG_HOME"] = str(base / "xdg")
            proc = self._run("plan", "--plan", str(plan), "--json", env=env)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["issues"][0]["code"], "invalid_global_preference")

    def test_missing_plan_file_is_error_in_both_actions(self) -> None:
        for action in ("validate", "plan"):
            with self.subTest(action=action):
                with tempfile.TemporaryDirectory() as raw:
                    absent = Path(raw) / "no-such-plan.md"
                    proc = self._run(action, "--plan", str(absent), "--json")
                self.assertEqual(proc.returncode, 1)
                payload = json.loads(proc.stdout)
                self.assertFalse(payload["ok"])
                self.assertEqual(
                    payload["issues"][0]["code"], "parallel_lanes_plan_missing"
                )
                self.assertNotIn("Traceback", proc.stderr)

    def test_missing_plan_argument_yields_envelope_not_traceback(self) -> None:
        for action in ("validate", "plan"):
            with self.subTest(action=action):
                proc = self._run(action, "--json")
                self.assertEqual(proc.returncode, 1)
                payload = json.loads(proc.stdout)
                self.assertFalse(payload["ok"])
                self.assertEqual(
                    payload["issues"][0]["code"], "missing_required_argument"
                )
                self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
