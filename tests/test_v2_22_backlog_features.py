"""Unit tests for v2.22 backlog feature modules (real shipped entry points)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.context import SECRET_FILE_NAMES
from cobbler_runtime.isolation import DEFAULT_EXCLUDED_FILE_NAMES
from cobbler_runtime.manus import SECRET_FILE_NAMES as MANUS_NAMES
from cobbler_runtime.planning_harvest import (
    assess_goal_completion,
    auto_plan_from_branch_signals,
    build_plan_beacon,
    discover_plans,
    filter_review_findings,
    lean_plan_summary,
    merge_recovery_scope_lock,
    mission_prep,
    resolve_plan_mode,
    task_sandbox_packet,
)
from cobbler_runtime.parallel_lanes import LaneSupervisor, validate_lane_staging
from cobbler_runtime.tool_output_compact import compact_tool_output
from cobbler_runtime.capabilities import route_on_usage_pressure
from cobbler_runtime.summary_video import build_summary_storyboard
from cobbler_runtime.worker_routing import (
    handoff_cache_key,
    resolve_user_specified_worker_model,
)


class SecretCorpusTests(unittest.TestCase):
    def test_shared_secret_file_names_are_consumed(self) -> None:
        self.assertIn(".env.local", SECRET_FILE_NAMES)
        self.assertTrue(SECRET_FILE_NAMES <= DEFAULT_EXCLUDED_FILE_NAMES)
        self.assertTrue(SECRET_FILE_NAMES <= set(MANUS_NAMES) or SECRET_FILE_NAMES == MANUS_NAMES)


class WorkerHandoffTests(unittest.TestCase):
    def test_user_specified_model_requires_catalog(self) -> None:
        model, policy = resolve_user_specified_worker_model(
            requested_model="claude-opus-5",
            live_catalog=["claude-opus-5", "gpt-5.6"],
        )
        self.assertEqual(model, "claude-opus-5")
        self.assertEqual(policy, "explicit_catalog_model_pin")
        missing, reason = resolve_user_specified_worker_model(
            requested_model="nope",
            live_catalog=["claude-opus-5"],
        )
        self.assertIsNone(missing)
        self.assertTrue(reason.startswith("model_unavailable:"))

    def test_handoff_cache_key_stable(self) -> None:
        a = handoff_cache_key(
            host="claude",
            guide_model="x",
            worker_model="y",
            worker_effort="high",
            prewalk_mode="auto",
        )
        b = handoff_cache_key(
            host="claude",
            guide_model="x",
            worker_model="y",
            worker_effort="high",
            prewalk_mode="auto",
        )
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)


class CompactTests(unittest.TestCase):
    def test_compact_truncates_long_success_output(self) -> None:
        raw = "\n".join(["ok"] * 200) + "\n"
        result = compact_tool_output(raw, max_lines=40)
        self.assertTrue(result.truncated or result.kept_lines < result.original_lines)
        self.assertIn("compact", result.text)


class PlanningHarvestTests(unittest.TestCase):
    PLAN = """# Plan: Demo

## Mission

Ship the demo feature safely.

### Batch 1 [B1]: Core

- [ ] B1-A1: tests pass

### Batch 2 [B2]: Docs

- [ ] B2-A1: guide updated

## Master Acceptance

- [ ] M-A1: demo works
"""

    def test_beacon_and_lean_summary(self) -> None:
        beacon = build_plan_beacon("docs/plans/demo.md", self.PLAN)
        self.assertEqual(beacon.title, "Plan: Demo")
        self.assertIn("B1", beacon.batch_ids)
        summary = lean_plan_summary(self.PLAN)
        self.assertIn("Ship the demo", summary)
        self.assertIn("B1-A1", summary)

    def test_sandbox_is_batch_scoped(self) -> None:
        packet = task_sandbox_packet(self.PLAN, batch_id="B1")
        self.assertIn("B1 only", packet)
        self.assertIn("B1-A1", packet)
        self.assertNotIn("B2-A1", packet)

    def test_goal_assessor_is_conservative(self) -> None:
        open_a = assess_goal_completion(
            open_acceptance_ids=["B1-A1"],
            stop_allowed=False,
            user_stop=False,
            open_ended=True,
        )
        self.assertFalse(open_a.complete)
        closed = assess_goal_completion(
            open_acceptance_ids=[],
            stop_allowed=True,
            user_stop=True,
            open_ended=False,
        )
        self.assertTrue(closed.complete)

    def test_review_filter_and_merge_lock(self) -> None:
        kept = filter_review_findings(
            [
                {"severity": "high", "confidence": "low", "title": "sec"},
                {"severity": "low", "confidence": "low", "title": "nit"},
                {"severity": "info", "confidence": "high", "stale": True, "title": "old"},
            ]
        )
        titles = {k.get("title") for k in kept}
        self.assertIn("sec", titles)
        self.assertNotIn("old", titles)
        lock = merge_recovery_scope_lock(
            allowed_paths=["scripts/"],
            attempted_paths=["scripts/a.py", "README.md"],
        )
        self.assertFalse(lock["ok"])
        self.assertIn("README.md", lock["violations"])
        bypass = merge_recovery_scope_lock(
            allowed_paths=["scripts/"],
            attempted_paths=["scripts/../.env.local"],
        )
        self.assertFalse(bypass["ok"])

    def test_discover_and_resolve_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plans = root / "docs" / "plans"
            plans.mkdir(parents=True)
            (plans / "x.md").write_text("# p\n", encoding="utf-8")
            found = discover_plans(root, session_plan_path="docs/plans/x.md")
            self.assertIn("docs/plans/x.md", found["filesystem"])
            self.assertEqual(found["session"], ["docs/plans/x.md"])
        self.assertTrue(resolve_plan_mode("skip")["ok"])
        self.assertFalse(resolve_plan_mode("file")["ok"])
        auto = auto_plan_from_branch_signals(
            branch="feat/x",
            commits=["abc Land work"],
            changed_paths=["src/a.py"],
        )
        self.assertIn("feat/x", auto)
        self.assertIn("B1-A1", auto)

    def test_mission_prep_strips_philosophy(self) -> None:
        raw = "Keep this gotcha: use X.\nThis is a pivotal moment for the tapestry.\n"
        cleaned = mission_prep(raw)
        self.assertIn("gotcha", cleaned)
        self.assertNotIn("pivotal moment", cleaned)


class ParallelvesRuntimeTests(unittest.TestCase):
    def test_staging_and_supervisor(self) -> None:
        issues = validate_lane_staging(
            plan_lanes=[{"id": "L1"}],
            session_lanes=[],
        )
        self.assertTrue(any(i.code == "parallel_lanes_session_missing" for i in issues))
        clean = validate_lane_staging(
            plan_lanes=[{"id": "L1"}],
            session_lanes=[{"id": "L1", "branch": "lane-l1"}],
        )
        self.assertEqual(clean, [])
        sup = LaneSupervisor()
        sup.register("L1", branch="lane-l1")
        sup.mark_running("L1")
        sup.mark_completed("L1")
        rec = sup.reconcile()
        self.assertTrue(rec["ok_to_integrate"])


class UsageAndVideoTests(unittest.TestCase):
    def test_usage_routing_honest_unknown(self) -> None:
        r = route_on_usage_pressure(remaining_quota="unknown")
        self.assertEqual(r["action"], "continue")
        self.assertFalse(r["quota_known"])
        r2 = route_on_usage_pressure(remaining_quota=0, alternate_provider="native")
        self.assertEqual(r2["action"], "failover")

    def test_summary_storyboard(self) -> None:
        board = build_summary_storyboard(
            mission="Ship v2.22",
            batches=[("B1", "handoffs")],
            residual_risks=["none"],
        )
        self.assertEqual(board["format"], "elves-summary-storyboard-v1")
        self.assertGreaterEqual(len(board["scenes"]), 3)


class FuguModuleTests(unittest.TestCase):
    def test_fugu_module_exists_and_shim_points_at_it(self) -> None:
        fugu = REPO / "scripts" / "cobbler_runtime" / "fugu.py"
        shim = REPO / "scripts" / "run_fugu.sh"
        self.assertTrue(fugu.is_file())
        text = shim.read_text(encoding="utf-8")
        self.assertIn("cobbler_runtime/fugu.py", text)
        self.assertNotIn("<<'PY'", text)


if __name__ == "__main__":
    unittest.main()
