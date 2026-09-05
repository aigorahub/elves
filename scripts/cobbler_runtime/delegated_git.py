"""Delegated Git contract for trusted feature-branch workers.

Trusted workers may advance only the staged feature branch with descendant
commits. The driver retains base, merge, tag, force-push, and PR authority.
Unexpected ancestry fails closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .acceptance import (
    normalize_batch_id,
    parse_markdown_acceptance_rows,
    parse_plan_acceptance_contract,
)
from .schema import ValidationIssue
from .storage import atomic_write_json, ensure_private_dir


PROTECTED_ACTIONS: frozenset[str] = frozenset(
    {
        "merge",
        "tag",
        "force_push",
        "change_base",
        "open_second_pr",
        "delete_base",
        "rebase",
        "push_other_ref",
    }
)

HOST_CONTROL_FIELDS: frozenset[str] = frozenset(
    {
        "merge_on_green",
        "stop_allowed",
        "run_mode",
        "pr_number",
        "continuation_guard",
        "driver_monitor_mode",
        "team",
        "team_callback",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_git(cwd: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return result


@dataclass
class DelegatedGitContract:
    feature_branch: str
    base_branch: str
    start_head: str
    session_id: str
    run_id: str
    allowed_actions: tuple[str, ...] = (
        "commit",
        "push_feature_branch",
        "status",
        "diff",
        "log",
        "add",
    )
    protected_actions: tuple[str, ...] = tuple(sorted(PROTECTED_ACTIONS))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assert_action_allowed(contract: DelegatedGitContract, action: str) -> None:
    if action in contract.protected_actions or action in PROTECTED_ACTIONS:
        raise ValidationIssue(
            "delegated_git_protected",
            f"Action `{action}` is driver-only; trusted worker may not perform it",
            path=f"delegated_git.{action}",
        )
    if action not in contract.allowed_actions:
        raise ValidationIssue(
            "delegated_git_forbidden",
            f"Action `{action}` is not allowed for this delegated contract",
            path=f"delegated_git.{action}",
        )


def assert_feature_branch(cwd: Path, expected_branch: str) -> str:
    result = run_git(cwd, ["branch", "--show-current"])
    if result.returncode != 0:
        raise ValidationIssue(
            "delegated_git_branch_query_failed",
            (result.stderr or result.stdout or "git branch failed").strip(),
        )
    current = (result.stdout or "").strip()
    if current != expected_branch:
        raise ValidationIssue(
            "delegated_git_wrong_branch",
            f"Current branch `{current}` is not the staged feature branch `{expected_branch}`",
        )
    return current


def assert_descendant(cwd: Path, *, ancestor: str, head: str | None = None) -> str:
    """Fail closed when head is not a descendant of the previously known tip."""
    tip = head
    if tip is None:
        result = run_git(cwd, ["rev-parse", "HEAD"])
        if result.returncode != 0:
            raise ValidationIssue("delegated_git_rev_parse_failed", result.stderr.strip())
        tip = result.stdout.strip()
    check = run_git(cwd, ["merge-base", "--is-ancestor", ancestor, tip])
    if check.returncode != 0:
        raise ValidationIssue(
            "delegated_git_unexpected_ancestry",
            f"HEAD `{tip}` is not a descendant of expected ancestor `{ancestor}`",
            hint="Refuse force/non-descendant advances on the feature branch",
        )
    return tip


def push_feature_branch(
    cwd: Path,
    contract: DelegatedGitContract,
    *,
    remote: str = "origin",
    previous_tip: str | None = None,
) -> dict[str, Any]:
    """Push only the staged feature branch after ancestry checks."""
    assert_action_allowed(contract, "push_feature_branch")
    assert_feature_branch(cwd, contract.feature_branch)
    ancestor = previous_tip or contract.start_head
    tip = assert_descendant(cwd, ancestor=ancestor)
    # Refuse force and other refs.
    result = run_git(
        cwd,
        ["push", remote, f"HEAD:refs/heads/{contract.feature_branch}"],
    )
    if result.returncode != 0:
        raise ValidationIssue(
            "delegated_git_push_failed",
            (result.stderr or result.stdout or "push failed").strip(),
        )
    return {
        "ok": True,
        "branch": contract.feature_branch,
        "remote": remote,
        "head": tip,
        "forced": False,
    }


def rollback_ref_name(*, run_id: str, session_id: str, batch: int) -> str:
    """Collision-free run/session-scoped rollback ref with digest of full IDs."""
    import hashlib
    normalized_batch = normalize_batch_id(batch)
    if normalized_batch is None:
        raise ValidationIssue(
            "delegated_git_batch_invalid",
            "Rollback batch must be B0, B1+, or an unambiguous non-negative integer",
        )
    material = f"{run_id}\0{session_id}\0{normalized_batch}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()[:12]
    safe_run = re.sub(r"[^A-Za-z0-9._-]+", "_", run_id)[:24]
    safe_sess = re.sub(r"[^A-Za-z0-9._-]+", "_", session_id)[:16]
    return f"refs/elves/rollback/{safe_run}/{safe_sess}/b{normalized_batch}-{digest}"


def create_rollback_ref(
    cwd: Path,
    *,
    run_id: str,
    session_id: str,
    batch: int,
    head: str | None = None,
    push_remote: str | None = None,
) -> dict[str, Any]:
    tip_expr = head or "HEAD"
    resolved = run_git(cwd, ["rev-parse", "--verify", f"{tip_expr}^{{commit}}"])
    if resolved.returncode != 0:
        raise ValidationIssue(
            "delegated_git_rev_parse_failed",
            (resolved.stderr or resolved.stdout or f"invalid commit: {tip_expr}").strip(),
        )
    tip = resolved.stdout.strip()
    ref = rollback_ref_name(run_id=run_id, session_id=session_id, batch=batch)
    existing = run_git(cwd, ["rev-parse", "-q", "--verify", ref])
    local_ref_created = False
    idempotent = False
    if existing.returncode == 0 and existing.stdout.strip():
        existing_tip = existing.stdout.strip()
        if existing_tip != tip:
            raise ValidationIssue(
                "delegated_git_rollback_ref_collision",
                f"Rollback ref `{ref}` already points to `{existing_tip}`; refusing to move it",
            )
        idempotent = True
    else:
        object_format = run_git(cwd, ["rev-parse", "--show-object-format"])
        fmt = object_format.stdout.strip() if object_format.returncode == 0 else "sha1"
        zero_oid = "0" * (64 if fmt == "sha256" else 40)
        result = run_git(cwd, ["update-ref", ref, tip, zero_oid])
        if result.returncode != 0:
            raise ValidationIssue(
                "delegated_git_rollback_ref_failed",
                (result.stderr or result.stdout or "update-ref failed").strip(),
            )
        local_ref_created = True
    pushed = False
    remote_ref_created = False
    remote_idempotent = False
    if push_remote:
        remote_result = run_git(cwd, ["ls-remote", "--refs", push_remote, ref])
        if remote_result.returncode != 0:
            raise ValidationIssue(
                "delegated_git_rollback_remote_inspect_failed",
                (remote_result.stderr or remote_result.stdout or "ls-remote failed").strip(),
            )
        remote_rows = [row.split(None, 1) for row in remote_result.stdout.splitlines()]
        remote_tip = next(
            (parts[0] for parts in remote_rows if len(parts) == 2 and parts[1] == ref),
            None,
        )
        if remote_tip and remote_tip != tip:
            raise ValidationIssue(
                "delegated_git_rollback_remote_collision",
                f"Remote rollback ref `{ref}` already points to `{remote_tip}`; refusing to move it",
            )
        if remote_tip == tip:
            remote_idempotent = True
        else:
            # Empty force-with-lease expectation means the remote ref must still
            # be absent at push time, closing the inspect/push race.
            pushed_result = run_git(
                cwd,
                [
                    "push",
                    f"--force-with-lease={ref}:",
                    push_remote,
                    f"{tip}:{ref}",
                ],
            )
            if pushed_result.returncode != 0:
                raise ValidationIssue(
                    "delegated_git_rollback_push_failed",
                    (pushed_result.stderr or pushed_result.stdout or "rollback push failed").strip(),
                )
            pushed = True
            remote_ref_created = True
    return {
        "ok": True,
        "ref": ref,
        "head": tip,
        "batch": batch,
        "local_ref_created": local_ref_created,
        "idempotent": idempotent,
        "pushed": pushed,
        "remote_ref_created": remote_ref_created,
        "remote_idempotent": remote_idempotent,
        "remote": push_remote,
    }


def reconcile_worker_report(
    host_state: Mapping[str, Any],
    worker_report: Mapping[str, Any],
    *,
    expected_session_id: str,
    expected_branch: str,
    expected_start_head: str | None = None,
) -> dict[str, Any]:
    """Merge worker evidence without allowing host control field mutation."""
    errors: list[str] = []
    if worker_report.get("session_id") != expected_session_id:
        errors.append("session_id mismatch")
    if worker_report.get("branch") != expected_branch:
        errors.append("branch mismatch")
    if expected_start_head and worker_report.get("start_head") not in {
        None,
        expected_start_head,
    }:
        # Allow worker to omit start_head but not rewrite a different one.
        if worker_report.get("start_head") != expected_start_head:
            errors.append("start_head mismatch")
    if errors:
        raise ValidationIssue(
            "report_reconciliation_failed",
            "Worker report reconciliation failed: " + ", ".join(errors),
        )

    merged = dict(host_state)
    # Preserve host controls.
    preserved = {k: host_state[k] for k in HOST_CONTROL_FIELDS if k in host_state}
    # Import non-control evidence surfaces only.
    for key in ("batches", "acceptance", "commits", "tests", "final_head", "status"):
        if key in worker_report:
            merged[key] = worker_report[key]
    merged.update(preserved)
    merged["reconciled_at"] = _utc_now()
    merged["reconciled_session_id"] = expected_session_id
    return merged


def parse_plan_acceptance(plan_text: str) -> list[dict[str, str]]:
    """Parse stable acceptance IDs and wrapped criterion text from a plan."""
    if not plan_text or not plan_text.strip():
        raise ValidationIssue(
            "plan_unparseable",
            "Plan text is empty; cannot parse acceptance criteria",
        )
    contract = parse_plan_acceptance_contract(plan_text)
    if contract.batch_ids or contract.issues:
        rows = list(contract.rows)
        syntax_issues = list(contract.issues)
    else:
        # Compatibility for old standalone ``### Acceptance`` fragments that
        # predate explicit Batch and Master Acceptance scoping.
        rows, syntax_issues = parse_markdown_acceptance_rows(
            plan_text,
            require_checkbox=True,
        )
    if syntax_issues:
        issue = syntax_issues[0]
        raise ValidationIssue(issue.code, issue.message)
    items = [{"id": row.id, "criterion": row.criterion} for row in rows]
    if not items:
        raise ValidationIssue(
            "plan_unparseable",
            "No stable acceptance IDs (B#-A# / M-A#) found in plan",
        )
    return items


def validate_acceptance_mapping(
    plan_items: Sequence[Mapping[str, str]],
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    require_master: bool = True,
) -> list[str]:
    """One-to-one ID/text/evidence mapping. Return errors (empty = pass)."""
    errors: list[str] = []
    plan_by_id = {str(item["id"]): str(item["criterion"]) for item in plan_items}
    seen: set[str] = set()
    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    for item in evidence_items:
        aid = str(item.get("id") or "")
        if not aid:
            errors.append("evidence item missing id")
            continue
        if aid in seen:
            errors.append(f"duplicate evidence id: {aid}")
        seen.add(aid)
        evidence_by_id[aid] = item

    for aid, criterion in plan_by_id.items():
        if aid not in evidence_by_id:
            errors.append(f"missing evidence for {aid}")
            continue
        ev = evidence_by_id[aid]
        if str(ev.get("criterion") or "") != criterion:
            errors.append(f"criterion text mismatch for {aid}")
        if ev.get("met") is not True:
            errors.append(f"acceptance not met for {aid}")
        if not ev.get("evidence"):
            errors.append(f"missing concrete evidence for {aid}")

    for aid in evidence_by_id:
        if aid not in plan_by_id:
            # Unrelated green evidence without plan id is rejected.
            errors.append(f"unrelated evidence id not in plan: {aid}")

    if require_master:
        masters = [aid for aid in plan_by_id if aid.startswith("M-A")]
        if not masters:
            errors.append("missing Master Acceptance (M-A#) in plan")
        for aid in masters:
            if aid not in evidence_by_id or evidence_by_id[aid].get("met") is not True:
                errors.append(f"master acceptance incomplete: {aid}")
    return errors
