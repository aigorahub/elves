"""Host-owned landing authority and exact-HEAD readiness (Elves 2.3).

Independence invariants:
- ready=true never grants merge permission
- driver_authorized=true never proves readiness
- merge requires both at the same exact HEAD
- worker evidence cannot grant merge or change landing_outcome

Pure policy helpers (no network). Host drivers call these; workers must not.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


POLICY_VERSION = "2.4.0"
EXACT_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")

LANDING_OUTCOMES: tuple[str, ...] = (
    "landable_pr",  # complete-without-merge (default)
    "complete_and_merge",  # regular merge commit when authorized
)

# Fields a worker report may not set or flip.
WORKER_IMMUTABLE_HOST_FIELDS: frozenset[str] = frozenset(
    {
        "landing_outcome",
        "driver_authorized",
        "merge_authority",
        "ready",
        "readiness_head",
        "readiness_attested_at",
        "host_merge_authorized",
        "driver_merge_authorized",
        "project_landing_checks_green",
        "project_landing_checks_digest",
    }
)


@dataclass(frozen=True)
class LandingControl:
    """Host-owned landing control plane (immutable from worker evidence)."""

    landing_outcome: str = "landable_pr"
    driver_authorized: bool = False
    ready: bool = False
    readiness_head: str | None = None
    readiness_inputs_digest: str | None = None
    acceptance_complete: bool = False
    blockers_resolved: bool = False
    exact_tip_review_clean: bool = False
    required_checks_green: bool = False
    project_landing_checks_green: bool = False
    project_landing_checks_digest: str | None = None
    worktree_clean: bool = False
    not_draft: bool = True
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReadinessAttestation:
    head: str
    inputs_digest: str
    acceptance_complete: bool
    blockers_resolved: bool
    exact_tip_review_clean: bool
    required_checks_green: bool
    project_landing_checks_green: bool
    project_landing_checks_digest: str | None
    worktree_clean: bool
    ready: bool
    invalidated_scopes: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MergeGuardDecision:
    allowed: bool
    reasons: tuple[str, ...]
    required: tuple[str, ...]
    head: str | None
    landing_outcome: str
    driver_authorized: bool
    ready: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HostileFieldStrip:
    stripped: tuple[str, ...]
    control: LandingControl

    def to_dict(self) -> dict[str, Any]:
        return {
            "stripped": list(self.stripped),
            "control": self.control.to_dict(),
        }


def normalize_landing_outcome(raw: str | None) -> str:
    text = (raw or "landable_pr").strip().lower().replace("-", "_")
    aliases = {
        "landable_pr": "landable_pr",
        "landable": "landable_pr",
        "chat_to_work": "landable_pr",
        "complete_without_merge": "landable_pr",
        "complete_and_merge": "complete_and_merge",
        "chat_to_land": "complete_and_merge",
        "merge_on_green": "complete_and_merge",
        "reviewed_pr_landing": "complete_and_merge",
    }
    if text not in aliases:
        raise ValueError(f"unknown landing outcome: {raw!r}")
    return aliases[text]


def initial_control(
    *,
    landing_outcome: str = "landable_pr",
    driver_authorized: bool = False,
) -> LandingControl:
    outcome = normalize_landing_outcome(landing_outcome)
    # complete_and_merge still starts unauthorized unless host explicitly grants.
    return LandingControl(
        landing_outcome=outcome,
        driver_authorized=bool(driver_authorized) and outcome == "complete_and_merge",
        ready=False,
        notes=(
            "host_owned_landing_control",
            "worker_cannot_mutate",
        ),
    )


def strip_worker_authority_claims(
    host_control: LandingControl,
    worker_payload: Mapping[str, Any] | None,
) -> HostileFieldStrip:
    """Ignore hostile worker fields; never let them mutate host control."""
    payload = dict(worker_payload or {})
    stripped: list[str] = []
    for key in WORKER_IMMUTABLE_HOST_FIELDS:
        if key in payload:
            stripped.append(key)
    # Host control is returned unchanged — worker cannot grant or flip anything.
    return HostileFieldStrip(stripped=tuple(sorted(stripped)), control=host_control)


def apply_worker_report_to_control(
    host_control: LandingControl,
    worker_report: Mapping[str, Any] | None,
) -> LandingControl:
    """Reconcile worker report evidence without granting authority.

    Worker may contribute completion *evidence* consumed by the host later;
    this function deliberately returns host_control unchanged for authority
    fields (and overall). Host attestation is a separate step.
    """
    strip_worker_authority_claims(host_control, worker_report)
    return host_control


def grant_driver_authorization(
    control: LandingControl,
    *,
    grant_source: str,
    active_run: bool = True,
) -> LandingControl:
    """Active-run land-pr / explicit Run Control grant.

    Grants driver_authorized without restarting readiness. Does not set ready.
    """
    source = (grant_source or "").strip().lower()
    allowed_sources = {
        "land-pr",
        "/land-pr",
        "\\land-pr",
        "reviewed_pr_landing",
        "run_control",
        "chat_to_land",
        "merge_on_green",
        "user_explicit",
    }
    if source not in allowed_sources:
        raise ValueError(f"refusing unknown grant source: {grant_source!r}")
    notes = list(control.notes) + [
        f"driver_authorized_via:{source}",
        "readiness_not_restarted" if active_run else "grant_outside_active_run",
    ]
    return LandingControl(
        landing_outcome="complete_and_merge",
        driver_authorized=True,
        ready=control.ready,
        readiness_head=control.readiness_head,
        readiness_inputs_digest=control.readiness_inputs_digest,
        acceptance_complete=control.acceptance_complete,
        blockers_resolved=control.blockers_resolved,
        exact_tip_review_clean=control.exact_tip_review_clean,
        required_checks_green=control.required_checks_green,
        project_landing_checks_green=control.project_landing_checks_green,
        project_landing_checks_digest=control.project_landing_checks_digest,
        worktree_clean=control.worktree_clean,
        not_draft=control.not_draft,
        notes=tuple(notes),
    )


def compute_readiness_inputs_digest(
    *,
    head: str,
    acceptance_rows: Sequence[Mapping[str, Any]] | None = None,
    blocker_ids: Sequence[str] | None = None,
    review_evidence_id: str | None = None,
    required_check_digest: str | None = None,
    project_landing_checks_green: bool = True,
    project_landing_checks_digest: str | None = None,
    proof_scopes: Mapping[str, str] | None = None,
) -> str:
    payload = {
        "head": head,
        "acceptance": [
            {
                "id": row.get("id"),
                "met": bool(row.get("met")),
                "criterion": row.get("criterion"),
            }
            for row in sorted(
                (acceptance_rows or ()),
                key=lambda r: str(r.get("id") or ""),
            )
        ],
        "blockers": sorted(str(b) for b in (blocker_ids or ())),
        "review_evidence_id": review_evidence_id or "",
        "required_check_digest": required_check_digest or "",
        "project_landing_checks_green": bool(project_landing_checks_green),
        "project_landing_checks_digest": project_landing_checks_digest or "",
        "proof_scopes": dict(sorted((proof_scopes or {}).items())),
    }
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def attest_readiness(
    control: LandingControl,
    *,
    head: str,
    acceptance_complete: bool,
    blockers_resolved: bool,
    exact_tip_review_clean: bool,
    required_checks_green: bool,
    worktree_clean: bool,
    inputs_digest: str,
    project_landing_checks_green: bool = True,
    project_landing_checks_digest: str | None = None,
    previous_digest: str | None = None,
    changed_input_scopes: Sequence[str] | None = None,
) -> tuple[LandingControl, ReadinessAttestation]:
    """Host attests readiness to an exact HEAD.

    Changed inputs invalidate only affected proof scopes; readiness requires
    all gates true at this HEAD. Authorization is untouched.
    """
    if not isinstance(head, str) or EXACT_COMMIT_RE.fullmatch(head) is None:
        raise ValueError("readiness requires an exact 40-character commit HEAD")
    reasons: list[str] = []
    if not acceptance_complete:
        reasons.append("acceptance_incomplete")
    if not blockers_resolved:
        reasons.append("blockers_unresolved")
    if not exact_tip_review_clean:
        reasons.append("exact_tip_review_not_clean")
    if not required_checks_green:
        reasons.append("required_checks_not_green")
    if not project_landing_checks_green:
        reasons.append("project_landing_checks_not_green")
    if not worktree_clean:
        reasons.append("worktree_dirty")

    invalidated = tuple(sorted(set(changed_input_scopes or ())))
    if previous_digest and previous_digest != inputs_digest and not invalidated:
        # Conservative: unknown change scope invalidates all readiness proof.
        invalidated = (
            "acceptance",
            "review",
            "checks",
            "project_landing",
            "worktree",
        )
        reasons.append("inputs_changed_without_scope_map")

    ready = not reasons and not (
        invalidated and any(
            scope
            in {
                "acceptance",
                "review",
                "checks",
                "project_landing",
                "worktree",
                "all",
            }
            for scope in invalidated
        )
        and (
            not acceptance_complete
            or not blockers_resolved
            or not exact_tip_review_clean
            or not required_checks_green
            or not project_landing_checks_green
            or not worktree_clean
        )
    )
    # If scopes were invalidated, require the corresponding booleans still true
    # after host re-proof. When all booleans are true and no reasons, ready.
    ready = len(reasons) == 0

    attestation = ReadinessAttestation(
        head=head,
        inputs_digest=inputs_digest,
        acceptance_complete=acceptance_complete,
        blockers_resolved=blockers_resolved,
        exact_tip_review_clean=exact_tip_review_clean,
        required_checks_green=required_checks_green,
        project_landing_checks_green=project_landing_checks_green,
        project_landing_checks_digest=project_landing_checks_digest,
        worktree_clean=worktree_clean,
        ready=ready,
        invalidated_scopes=invalidated,
        reasons=tuple(reasons),
    )
    updated = LandingControl(
        landing_outcome=control.landing_outcome,
        driver_authorized=control.driver_authorized,
        ready=ready,
        readiness_head=head if ready else control.readiness_head,
        readiness_inputs_digest=inputs_digest if ready else control.readiness_inputs_digest,
        acceptance_complete=acceptance_complete,
        blockers_resolved=blockers_resolved,
        exact_tip_review_clean=exact_tip_review_clean,
        required_checks_green=required_checks_green,
        project_landing_checks_green=project_landing_checks_green,
        project_landing_checks_digest=(
            project_landing_checks_digest if project_landing_checks_green else None
        ),
        worktree_clean=worktree_clean,
        not_draft=control.not_draft,
        notes=control.notes + (("readiness_attested",) if ready else ("readiness_incomplete",)),
    )
    return updated, attestation


def invalidate_on_head_change(
    control: LandingControl,
    *,
    current_head: str,
) -> LandingControl:
    """Changed HEAD clears readiness; never touches driver_authorized."""
    if control.readiness_head and control.readiness_head == current_head:
        return control
    return LandingControl(
        landing_outcome=control.landing_outcome,
        driver_authorized=control.driver_authorized,
        ready=False,
        readiness_head=None,
        readiness_inputs_digest=None,
        acceptance_complete=False,
        blockers_resolved=control.blockers_resolved,
        exact_tip_review_clean=False,
        required_checks_green=False,
        project_landing_checks_green=False,
        project_landing_checks_digest=None,
        worktree_clean=control.worktree_clean,
        not_draft=control.not_draft,
        notes=control.notes + ("readiness_invalidated_head_changed",),
    )


def invalidate_scopes(
    control: LandingControl,
    scopes: Sequence[str],
) -> LandingControl:
    """Invalidate only affected readiness proof scopes."""
    scopes_set = {s.lower() for s in scopes}
    acceptance = control.acceptance_complete
    blockers = control.blockers_resolved
    review = control.exact_tip_review_clean
    checks = control.required_checks_green
    project_landing = control.project_landing_checks_green
    project_landing_digest = control.project_landing_checks_digest
    worktree = control.worktree_clean
    if scopes_set & {"acceptance", "all"}:
        acceptance = False
    if scopes_set & {"blockers", "all"}:
        blockers = False
    if scopes_set & {"review", "all"}:
        review = False
    if scopes_set & {"checks", "all"}:
        checks = False
    if scopes_set & {"project_landing", "all"}:
        project_landing = False
        project_landing_digest = None
    if scopes_set & {"worktree", "all"}:
        worktree = False
    still_ready = (
        acceptance
        and blockers
        and review
        and checks
        and project_landing
        and worktree
        and control.ready
    )
    return LandingControl(
        landing_outcome=control.landing_outcome,
        driver_authorized=control.driver_authorized,
        ready=still_ready,
        readiness_head=control.readiness_head if still_ready else None,
        readiness_inputs_digest=control.readiness_inputs_digest if still_ready else None,
        acceptance_complete=acceptance,
        blockers_resolved=blockers,
        exact_tip_review_clean=review,
        required_checks_green=checks,
        project_landing_checks_green=project_landing,
        project_landing_checks_digest=project_landing_digest,
        worktree_clean=worktree,
        not_draft=control.not_draft,
        notes=control.notes + (f"invalidated:{','.join(sorted(scopes_set))}",),
    )


MERGE_GUARD_REQUIREMENTS: tuple[str, ...] = (
    "acceptance_complete",
    "blockers_resolved",
    "exact_tip_review_clean",
    "required_checks_green",
    "project_landing_checks_green",
    "worktree_clean",
    "not_draft",
    "ready",
    "driver_authorized",
    "landing_outcome_complete_and_merge",
    "exact_head_matches_readiness",
)


def evaluate_merge_guard(
    control: LandingControl,
    *,
    current_head: str,
) -> MergeGuardDecision:
    """Host-only merge guard. Never callable as a worker privilege."""
    missing: list[str] = []
    if not control.acceptance_complete:
        missing.append("acceptance_complete")
    if not control.blockers_resolved:
        missing.append("blockers_resolved")
    if not control.exact_tip_review_clean:
        missing.append("exact_tip_review_clean")
    if not control.required_checks_green:
        missing.append("required_checks_green")
    if not control.project_landing_checks_green:
        missing.append("project_landing_checks_green")
    if not control.worktree_clean:
        missing.append("worktree_clean")
    if not control.not_draft:
        missing.append("not_draft")
    if not control.ready:
        missing.append("ready")
    if not control.driver_authorized:
        missing.append("driver_authorized")
    if control.landing_outcome != "complete_and_merge":
        missing.append("landing_outcome_complete_and_merge")
    exact_current_head = (
        isinstance(current_head, str)
        and EXACT_COMMIT_RE.fullmatch(current_head) is not None
    )
    if not exact_current_head:
        missing.append("current_head_exact_commit")
    if (
        not control.readiness_head
        or EXACT_COMMIT_RE.fullmatch(control.readiness_head) is None
        or control.readiness_head.lower() != current_head.lower()
    ):
        missing.append("exact_head_matches_readiness")

    # Independence: ready alone never allows merge.
    if control.ready and not control.driver_authorized:
        if "driver_authorized" not in missing:
            missing.append("driver_authorized")
    # Authorization alone never allows merge.
    if control.driver_authorized and not control.ready:
        if "ready" not in missing:
            missing.append("ready")

    allowed = not missing
    reasons = (
        ("merge_allowed_at_exact_head",)
        if allowed
        else tuple(f"missing:{m}" for m in missing)
    )
    return MergeGuardDecision(
        allowed=allowed,
        reasons=reasons,
        required=MERGE_GUARD_REQUIREMENTS,
        head=current_head,
        landing_outcome=control.landing_outcome,
        driver_authorized=control.driver_authorized,
        ready=control.ready,
    )


def shared_readiness_pipeline_id() -> str:
    """Complete-without-merge and complete-and-merge share one pipeline."""
    return "elves_2_3_shared_readiness_pipeline_v1"


def terminal_action(control: LandingControl, *, current_head: str) -> dict[str, Any]:
    """Decide host terminal action without implying the other authority."""
    if control.landing_outcome == "landable_pr" or not control.driver_authorized:
        return {
            "action": "landable_pr",
            "merge": False,
            "pipeline": shared_readiness_pipeline_id(),
            "ready": control.ready,
            "driver_authorized": control.driver_authorized,
            "head": current_head,
            "note": "hand_off_landable_pr_to_user",
        }
    decision = evaluate_merge_guard(control, current_head=current_head)
    if decision.allowed:
        return {
            "action": "complete_and_merge",
            "merge": True,
            "merge_method": "merge_commit",  # never squash
            "pipeline": shared_readiness_pipeline_id(),
            "ready": True,
            "driver_authorized": True,
            "head": current_head,
            "note": "host_regular_merge_commit_only",
        }
    return {
        "action": "hold",
        "merge": False,
        "pipeline": shared_readiness_pipeline_id(),
        "ready": control.ready,
        "driver_authorized": control.driver_authorized,
        "head": current_head,
        "guard": decision.to_dict(),
        "note": "await_missing_merge_guard_requirements",
    }


def policy_snapshot() -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "landing_outcomes": list(LANDING_OUTCOMES),
        "worker_immutable_host_fields": sorted(WORKER_IMMUTABLE_HOST_FIELDS),
        "merge_guard_requirements": list(MERGE_GUARD_REQUIREMENTS),
        "shared_readiness_pipeline": shared_readiness_pipeline_id(),
        "independence": [
            "ready_true_never_grants_merge_permission",
            "driver_authorized_true_never_proves_readiness",
            "merge_requires_both_at_same_exact_head",
            "worker_evidence_cannot_grant_merge_or_change_landing_outcome",
        ],
    }
