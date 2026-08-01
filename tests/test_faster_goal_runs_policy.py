"""Focused tests for Elves 2.2 faster trusted-run policy (B0–B3 helpers)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.evidence_review import plan_review  # noqa: E402
from cobbler_runtime.implement import (  # noqa: E402
    detect_native_grok_goal,
    optional_media_capabilities,
    resolve_phase_route,
)
from cobbler_runtime.preflight_cache import (  # noqa: E402
    cleanup_only_tip_attestation,
    compute_product_test_input_digest,
    gate_evidence_reuse,
    path_is_docs_or_run_metadata,
)
from cobbler_runtime.risk_policy import (  # noqa: E402
    SAFETY_KERNEL,
    build_reconstructed_report,
    classify_risk_tier,
    dispose_bug_category_findings,
    gate_reuse_decision,
    monitor_depth_for_status,
    plan_host_reconstruction,
    pr_feedback_policy,
    progress_commit_subject_ok,
    proof_budget_for_tier,
    safety_kernel_snapshot,
)


class RiskTierAndSafetyKernelTests(unittest.TestCase):
    def test_four_tiers_and_kernel_inventory(self) -> None:
        snap = safety_kernel_snapshot()
        self.assertEqual(len(snap["risk_tiers"]), 4)
        self.assertIn("trivial_docs", snap["risk_tiers"])
        self.assertIn("untrusted", snap["risk_tiers"])
        self.assertEqual(len(SAFETY_KERNEL), 6)
        self.assertIn("validate once", snap["proof_budget"])

    def test_proof_defaults_touched_except_checkpoint_terminal(self) -> None:
        docs = classify_risk_tier(changed_paths=["README.md", "docs/x.md"])
        self.assertEqual(docs.tier, "trivial_docs")
        self.assertFalse(docs.broad_proof_required)
        self.assertEqual(docs.proof_mode, "touched")

        std = classify_risk_tier(changed_paths=["scripts/foo.py"])
        self.assertEqual(std.tier, "standard_trusted")
        self.assertFalse(std.broad_proof_required)

        hi = classify_risk_tier(is_high_risk_checkpoint=True)
        self.assertEqual(hi.tier, "high_risk_trusted")
        self.assertTrue(hi.broad_proof_required)

        term = classify_risk_tier(is_final_readiness=True)
        self.assertTrue(term.broad_proof_required)
        self.assertEqual(term.proof_mode, "terminal_broad")

        budget = proof_budget_for_tier("standard_trusted")
        self.assertEqual(budget["per_batch_default"], "touched_surfaces")
        self.assertFalse(budget["broad_required_now"])

    def test_pr_feedback_mid_vs_terminal(self) -> None:
        mid = pr_feedback_policy(is_terminal_readiness=False)
        self.assertTrue(mid.fetch_new_unresolved_only)
        self.assertFalse(mid.wait_for_required_checks)
        parked = pr_feedback_policy(
            is_terminal_readiness=False,
            trusted_parked_full_run=True,
        )
        self.assertFalse(parked.fetch_new_unresolved_only)
        self.assertEqual(parked.mode, "defer_all_until_terminal")
        term = pr_feedback_policy(is_terminal_readiness=True)
        self.assertTrue(term.wait_for_required_checks)

    def test_bug_category_blocks_only_confirmed_same_root_on_owned(self) -> None:
        disp = dispose_bug_category_findings(
            [
                {
                    "id": "owned-confirmed",
                    "confirmed_same_root": True,
                    "paths": ["scripts/a.py"],
                },
                {
                    "id": "owned-unconfirmed",
                    "confirmed_same_root": False,
                    "paths": ["scripts/a.py"],
                },
                {
                    "id": "sibling-elsewhere",
                    "confirmed_same_root": True,
                    "paths": ["other/z.py"],
                },
            ],
            owned_or_affected_paths=["scripts/a.py"],
        )
        self.assertEqual(disp.blocking, ("owned-confirmed",))
        self.assertIn("owned-unconfirmed", disp.advisory)
        self.assertIn("sibling-elsewhere", disp.advisory)

    def test_evidence_review_docs_defer_broad_final_requires(self) -> None:
        docs = plan_review(changed_paths=["README.md"])
        self.assertFalse(docs.broad_gate_required)
        final = plan_review(changed_paths=["README.md"], is_final_readiness=True)
        self.assertTrue(final.broad_gate_required)

        runtime = plan_review(changed_paths=["scripts/cobbler_runtime/full_run.py"])
        self.assertFalse(runtime.broad_gate_required)
        self.assertIn("unit:runtime", runtime.focused_checks)

        checkpoint = plan_review(
            changed_paths=["scripts/cobbler_runtime/full_run.py"],
            is_high_risk_checkpoint=True,
        )
        self.assertTrue(checkpoint.broad_gate_required)


class GoalAwaitAndMonitorDepthTests(unittest.TestCase):
    def test_native_goal_detection_honest_fallback(self) -> None:
        tui = detect_native_grok_goal(
            help_text="Grok TUI\n  /goal  open goal mode in the UI\n"
        )
        self.assertFalse(tui["native_goal"])
        self.assertEqual(tui["mode"], "headless_compatible_fallback")
        native = detect_native_grok_goal(
            help_text="Options:\n  --goal <packet>  Run a headless goal\n"
        )
        self.assertTrue(native["advertised_headless_entrypoint"])
        self.assertFalse(native["goal_mode_behaviorally_verified"])
        self.assertFalse(native["native_goal"])
        self.assertEqual(native["mode"], "advertised_headless_entrypoint")

    def test_monitor_depth_incremental_vs_full(self) -> None:
        self.assertEqual(
            monitor_depth_for_status(
                status="healthy",
                next_action="parked_monitor",
                remote_audit_due=False,
            ),
            "incremental",
        )
        self.assertEqual(
            monitor_depth_for_status(
                status="healthy",
                next_action="parked_monitor",
                remote_audit_due=True,
            ),
            "full",
        )
        self.assertEqual(
            monitor_depth_for_status(
                status="complete", next_action="final_readiness"
            ),
            "full",
        )
        self.assertEqual(
            monitor_depth_for_status(
                status="healthy",
                next_action="driver_wake_reconcile",
            ),
            "full",
        )

    def test_await_returns_on_material_transition(self) -> None:
        from cobbler_runtime import full_run as fr
        from cobbler_runtime import full_run_monitor as fr_mon

        calls = {"n": 0}

        def fake_monitor(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "state": "healthy",
                    "next_action": "parked_monitor",
                    "unchanged_healthy_poll_silent": True,
                    "material_transition": False,
                    "poll_after_seconds": 0.01,
                }
            return {
                "state": "complete",
                "next_action": "final_readiness",
                "unchanged_healthy_poll_silent": False,
                "material_transition": True,
                "poll_after_seconds": 0.01,
            }

        sleeps: list[float] = []
        with mock.patch.object(fr_mon, "monitor_full_run", side_effect=fake_monitor):
            out = fr.await_full_run(
                Path("."),
                session_id="s",
                sleep_fn=lambda s: sleeps.append(s),
                monotonic_fn=lambda: 0.0,
            )
        self.assertEqual(calls["n"], 2)
        self.assertTrue(out["awaited"])
        self.assertEqual(out["state"], "complete")
        self.assertEqual(sleeps, [0.01])

    def test_progress_commit_subjects(self) -> None:
        self.assertFalse(
            progress_commit_subject_ok(
                "[codex/x · Batch 1/4 · Implement] progress"
            )
        )
        self.assertFalse(
            progress_commit_subject_ok("[codex/x · Batch 1/4] WIP")
        )
        self.assertTrue(
            progress_commit_subject_ok(
                "[codex/x · Batch 1/4 · Implement] Add await and goal detection"
            )
        )


class ReconstructionAndGateCacheTests(unittest.TestCase):
    def test_reconstruction_provenance_and_refusal(self) -> None:
        ok = plan_host_reconstruction(
            clean_exit=True,
            ancestry_ok=True,
            clean_worktree=True,
            protected_refs_ok=True,
            origin_ok=True,
            acceptance_bound=True,
            checkpoints_satisfied=True,
            host_tests_pass=True,
            available_facts={
                "session_id": "s",
                "final_head": "abc",
                "status": "complete",
            },
        )
        self.assertTrue(ok.allowed)
        report = build_reconstructed_report(
            ok,
            facts={
                "session_id": "s",
                "final_head": "abc",
                "status": "complete",
                "worker_internal_notes": "must not appear",
            },
        )
        self.assertEqual(report["provenance"], "host_reconstructed")
        self.assertFalse(report["merge_authority"])
        self.assertNotIn("worker_internal_notes", report)

        refused = plan_host_reconstruction(
            clean_exit=True,
            ancestry_ok=True,
            clean_worktree=True,
            protected_refs_ok=True,
            origin_ok=True,
            acceptance_bound=True,
            checkpoints_satisfied=False,
            host_tests_pass=True,
        )
        self.assertFalse(refused.allowed)
        with self.assertRaises(ValueError):
            build_reconstructed_report(refused, facts={})

        untrusted = plan_host_reconstruction(
            clean_exit=True,
            ancestry_ok=True,
            clean_worktree=True,
            protected_refs_ok=True,
            origin_ok=True,
            acceptance_bound=True,
            checkpoints_satisfied=True,
            host_tests_pass=True,
            untrusted_writer=True,
        )
        self.assertFalse(untrusted.allowed)

    def test_gate_digest_reuse_and_invalidation(self) -> None:
        d1 = "abc"
        hit = gate_reuse_decision(cached_digest=d1, current_digest=d1)
        self.assertTrue(hit.reuse)
        self.assertFalse(hit.final_readiness_accepts_cache_alone)
        miss = gate_reuse_decision(cached_digest=d1, current_digest="zzz")
        self.assertFalse(miss.reuse)
        self.assertEqual(miss.reason, "input_digest_mismatch")

    def test_docs_metadata_paths_and_cleanup_only(self) -> None:
        self.assertTrue(path_is_docs_or_run_metadata("README.md"))
        self.assertTrue(path_is_docs_or_run_metadata("docs/elves/x.md"))
        self.assertFalse(path_is_docs_or_run_metadata("requirements.txt"))
        self.assertFalse(path_is_docs_or_run_metadata("scripts/x.py"))
        ok = cleanup_only_tip_attestation(
            parent_tip="deadbeef",
            proven_tip="deadbeef",
            name_status_rows=["D\t.elves-session.json", "D\tdocs/elves/log.md"],
            recorded_operational_paths=[
                ".elves-session.json",
                "docs/elves/log.md",
            ],
            product_test_input_digest_unchanged=True,
        )
        self.assertTrue(ok["reuse"])
        bad = cleanup_only_tip_attestation(
            parent_tip="deadbeef",
            proven_tip="deadbeef",
            name_status_rows=["M\tscripts/x.py"],
            recorded_operational_paths=[".elves-session.json"],
            product_test_input_digest_unchanged=True,
        )
        self.assertTrue(bad["force_live_proof"])

    def test_product_digest_stable_on_docs_only_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "a.py").write_text("print(1)\n", encoding="utf-8")
            (root / "README.md").write_text("# hi\n", encoding="utf-8")
            d1 = compute_product_test_input_digest(root)
            (root / "README.md").write_text("# changed docs\n", encoding="utf-8")
            d2 = compute_product_test_input_digest(root)
            self.assertEqual(d1, d2)
            (root / "scripts" / "a.py").write_text("print(2)\n", encoding="utf-8")
            d3 = compute_product_test_input_digest(root)
            self.assertNotEqual(d1, d3)
            (root / "requirements.txt").write_text("demo==1\n", encoding="utf-8")
            d4 = compute_product_test_input_digest(root)
            self.assertNotEqual(d3, d4)
            decision = gate_evidence_reuse(root, cached_input_digest=d1)
            self.assertFalse(decision["reuse"])


class PhaseRoutingAndMediaTests(unittest.TestCase):
    def test_phase_route_records_fallback(self) -> None:
        route = resolve_phase_route(
            phase="implement",
            requested_model="strong",
            requested_effort="high",
            capability_available=False,
            host="codex",
        )
        self.assertIsNotNone(route["fallback_reason"])
        self.assertEqual(route["actual_route"]["route"], "host-native")
        ok = resolve_phase_route(
            phase="planning",
            requested_model="strong",
            requested_effort="xhigh",
            capability_available=True,
            host="claude",
        )
        self.assertIsNone(ok["fallback_reason"])
        self.assertEqual(ok["actual_route"]["effort"], "xhigh")

    def test_optional_media_non_fatal(self) -> None:
        caps = optional_media_capabilities(
            image_available=False, video_available=None
        )
        self.assertFalse(caps["image"]["required"])
        self.assertEqual(caps["image"]["status"], "unavailable")
        self.assertEqual(caps["video"]["status"], "unknown")
        self.assertIn("optional", caps["policy"])


if __name__ == "__main__":
    unittest.main()
