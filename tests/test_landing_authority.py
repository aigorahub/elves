"""Host-owned landing authority and exact-HEAD readiness tests (B1)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cobbler_runtime.landing_authority import (  # noqa: E402
    apply_worker_report_to_control,
    attest_readiness,
    compute_readiness_inputs_digest,
    evaluate_merge_guard,
    grant_driver_authorization,
    initial_control,
    invalidate_on_head_change,
    invalidate_scopes,
    shared_readiness_pipeline_id,
    strip_worker_authority_claims,
    terminal_action,
)


class LandingAuthorityTests(unittest.TestCase):
    HEAD_A = "a" * 40
    HEAD_B = "b" * 40
    def test_worker_cannot_grant_merge_or_change_outcome(self) -> None:
        host = initial_control(landing_outcome="landable_pr")
        hostile = {
            "merge_authority": True,
            "driver_authorized": True,
            "landing_outcome": "complete_and_merge",
            "ready": True,
            "project_landing_checks_green": True,
            "project_landing_checks_digest": "f" * 64,
            "status": "complete",
        }
        stripped = strip_worker_authority_claims(host, hostile)
        self.assertIn("merge_authority", stripped.stripped)
        self.assertIn("driver_authorized", stripped.stripped)
        self.assertIn("landing_outcome", stripped.stripped)
        self.assertIn("project_landing_checks_green", stripped.stripped)
        self.assertIn("project_landing_checks_digest", stripped.stripped)
        self.assertFalse(stripped.control.driver_authorized)
        self.assertFalse(stripped.control.ready)
        self.assertEqual(stripped.control.landing_outcome, "landable_pr")

        after = apply_worker_report_to_control(host, hostile)
        self.assertFalse(after.driver_authorized)
        self.assertFalse(after.ready)
        self.assertEqual(after.landing_outcome, "landable_pr")

    def test_shared_pipeline_for_both_terminal_outcomes(self) -> None:
        pipe = shared_readiness_pipeline_id()
        landable = initial_control(landing_outcome="landable_pr")
        mergeable = initial_control(landing_outcome="complete_and_merge")
        self.assertEqual(
            terminal_action(landable, current_head="abc")["pipeline"], pipe
        )
        self.assertEqual(
            terminal_action(mergeable, current_head="abc")["pipeline"], pipe
        )
        self.assertEqual(
            terminal_action(landable, current_head="abc")["action"], "landable_pr"
        )

    def test_land_pr_grants_without_restarting_readiness(self) -> None:
        control, att = attest_readiness(
            initial_control(),
            head=self.HEAD_A,
            acceptance_complete=True,
            blockers_resolved=True,
            exact_tip_review_clean=True,
            required_checks_green=True,
            worktree_clean=True,
            inputs_digest="d1",
        )
        self.assertTrue(att.ready)
        self.assertTrue(control.ready)
        self.assertFalse(control.driver_authorized)

        granted = grant_driver_authorization(
            control, grant_source="land-pr", active_run=True
        )
        self.assertTrue(granted.driver_authorized)
        self.assertTrue(granted.ready)  # readiness not cleared
        self.assertEqual(granted.readiness_head, self.HEAD_A)
        self.assertEqual(granted.landing_outcome, "complete_and_merge")
        self.assertIn("readiness_not_restarted", granted.notes)

    def test_readiness_exact_head_and_scope_invalidation(self) -> None:
        digest = compute_readiness_inputs_digest(
            head=self.HEAD_A,
            acceptance_rows=[{"id": "B0-A1", "met": True, "criterion": "x"}],
        )
        control, att = attest_readiness(
            initial_control(),
            head=self.HEAD_A,
            acceptance_complete=True,
            blockers_resolved=True,
            exact_tip_review_clean=True,
            required_checks_green=True,
            worktree_clean=True,
            inputs_digest=digest,
        )
        self.assertTrue(control.ready)
        self.assertEqual(control.readiness_head, self.HEAD_A)

        # HEAD change clears readiness only.
        granted = grant_driver_authorization(control, grant_source="/land-pr")
        moved = invalidate_on_head_change(granted, current_head=self.HEAD_B)
        self.assertFalse(moved.ready)
        self.assertIsNone(moved.readiness_head)
        self.assertTrue(moved.driver_authorized)  # auth survives

        # Scope invalidation is selective.
        partial = invalidate_scopes(control, ["checks"])
        self.assertFalse(partial.required_checks_green)
        self.assertTrue(partial.acceptance_complete)
        self.assertFalse(partial.ready)

        project_invalidated = invalidate_scopes(control, ["project_landing"])
        self.assertFalse(project_invalidated.project_landing_checks_green)
        self.assertIsNone(project_invalidated.project_landing_checks_digest)
        self.assertFalse(project_invalidated.ready)

    def test_project_landing_state_is_distinct_and_digest_bound(self) -> None:
        generic = compute_readiness_inputs_digest(head=self.HEAD_A)
        project = compute_readiness_inputs_digest(
            head=self.HEAD_A,
            project_landing_checks_green=True,
            project_landing_checks_digest="f" * 64,
        )
        failed = compute_readiness_inputs_digest(
            head=self.HEAD_A,
            project_landing_checks_green=False,
            project_landing_checks_digest="f" * 64,
        )
        self.assertNotEqual(generic, project)
        self.assertNotEqual(project, failed)

        control, attestation = attest_readiness(
            initial_control(landing_outcome="complete_and_merge"),
            head=self.HEAD_A,
            acceptance_complete=True,
            blockers_resolved=True,
            exact_tip_review_clean=True,
            required_checks_green=True,
            worktree_clean=True,
            inputs_digest=failed,
            project_landing_checks_green=False,
            project_landing_checks_digest="f" * 64,
        )
        self.assertFalse(control.ready)
        self.assertFalse(attestation.ready)
        self.assertIn("project_landing_checks_not_green", attestation.reasons)
        decision = evaluate_merge_guard(control, current_head=self.HEAD_A)
        self.assertIn("missing:project_landing_checks_green", decision.reasons)

    def test_merge_guard_requires_all_host_conditions(self) -> None:
        control = initial_control(landing_outcome="complete_and_merge")
        decision = evaluate_merge_guard(control, current_head=self.HEAD_A)
        self.assertFalse(decision.allowed)
        self.assertTrue(any("driver_authorized" in r for r in decision.reasons))

        ready_only, _ = attest_readiness(
            control,
            head=self.HEAD_A,
            acceptance_complete=True,
            blockers_resolved=True,
            exact_tip_review_clean=True,
            required_checks_green=True,
            worktree_clean=True,
            inputs_digest="x",
        )
        # ready alone never merges
        d2 = evaluate_merge_guard(ready_only, current_head=self.HEAD_A)
        self.assertFalse(d2.allowed)
        self.assertTrue(any("driver_authorized" in r for r in d2.reasons))

        authorized = grant_driver_authorization(ready_only, grant_source="user_explicit")
        d3 = evaluate_merge_guard(authorized, current_head=self.HEAD_A)
        self.assertTrue(d3.allowed)

        # wrong head
        d4 = evaluate_merge_guard(authorized, current_head=self.HEAD_B)
        self.assertFalse(d4.allowed)

        action = terminal_action(authorized, current_head=self.HEAD_A)
        self.assertTrue(action["merge"])
        self.assertEqual(action["merge_method"], "merge_commit")

    def test_attestation_rejects_abbreviated_or_symbolic_head(self) -> None:
        for head in ("abc", "HEAD", "a" * 39, "g" * 40):
            with self.subTest(head=head):
                with self.assertRaisesRegex(ValueError, "exact 40-character"):
                    attest_readiness(
                        initial_control(),
                        head=head,
                        acceptance_complete=True,
                        blockers_resolved=True,
                        exact_tip_review_clean=True,
                        required_checks_green=True,
                        worktree_clean=True,
                        inputs_digest="d",
                    )


if __name__ == "__main__":
    unittest.main()
