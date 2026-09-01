"""Compatibility facade and orchestration for parallel read-only dispatch.

Lanes launch concurrently. Inside each lane, primary then fallback attempts run
sequentially after recoverable failures; a failed required attempt is terminal.
Focused ``dispatch_*`` modules own contracts, attempt policy, external processes,
and result assembly. Host synthesis remains the only fitted-answer step.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from .context import (
    ContextPacket,
    build_context_packet,
    create_exclusive_artifact_root,
    new_run_id,
    resolve_contained_path,
    safe_path_component,
    write_json_artifact,
)
# Historical imports remain available from this facade while focused modules
# own their implementations.
from .storage import ensure_private_dir
from .dispatch_attempt import (
    attempt_env_grants as _attempt_env_grants,
    check_capabilities as _check_capabilities,
    classify_failure as _classify_failure,
)
from .dispatch_external import (
    PROCESS_GROUP_GRACE_SECONDS,
    PROCESS_GROUP_VERIFY_ATTEMPTS,
    PROCESS_GROUP_VERIFY_POLL_SECONDS,
    pgid_alive as _pgid_alive,
    terminate_process_group as _terminate_process_group,
)
from .dispatch_lane_attempt import run_single_attempt as _run_single_attempt_impl
from .dispatch_models import (
    AttemptResult,
    CouncilResult,
    HostExecutor,
    LaneResult,
    LaneSpec,
)
from .dispatch_results import (
    assemble_external_result as _assemble_external_result,
    build_failed_attempt as _build_failed_attempt,
    summarize as _summarize,
)
from .schema import EffectiveAttempt, ValidationIssue


LaneRunner = Callable[["LaneSpec", ContextPacket, Path], Awaitable["LaneResult"]]


def validate_quorum_value(
    value: int | None,
    *,
    name: str,
    lane_count: int,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationIssue(
            "invalid_quorum",
            f"{name} must be a positive integer, not {type(value).__name__}",
        )
    if value <= 0:
        raise ValidationIssue(
            "invalid_quorum",
            f"{name} must be a positive integer (got {value})",
        )
    if lane_count >= 0 and value > max(lane_count, 0):
        raise ValidationIssue(
            "invalid_quorum",
            f"{name}={value} exceeds distinct eligible lane count {lane_count}",
        )
    return value


def evaluate_quorum(
    *,
    successful_count: int,
    target_quorum: int | None,
    required_quorum: int | None,
    phase_required: bool,
    required_lane_failures: Sequence[str] = (),
    lane_count: int | None = None,
) -> tuple[bool, bool, bool, str, list[str]]:
    """Return (ok, council_verified, blocked, confidence, notes)."""
    notes: list[str] = []
    blocked = False
    council_verified = False
    confidence = "high"

    if required_lane_failures:
        blocked = True
        notes.append("Required lane failure(s): " + ", ".join(required_lane_failures))

    # Zero reports can never verify a council.
    if successful_count <= 0:
        council_verified = False

    if phase_required and required_quorum is not None:
        if successful_count < required_quorum or successful_count <= 0:
            blocked = True
            notes.append(
                f"required_quorum={required_quorum} unmet "
                f"(successful_independent_reports={successful_count})"
            )
        else:
            council_verified = True
            notes.append(
                f"required_quorum={required_quorum} met "
                f"(successful_independent_reports={successful_count})"
            )
    elif target_quorum is not None:
        if successful_count >= target_quorum and successful_count > 0:
            council_verified = True
            notes.append(
                f"target_quorum={target_quorum} met "
                f"(successful_independent_reports={successful_count})"
            )
        else:
            confidence = "reduced"
            notes.append(
                f"target_quorum={target_quorum} unmet after fallbacks; "
                "host synthesis continues without council-verified label "
                f"(successful_independent_reports={successful_count})"
            )
    else:
        if successful_count > 0:
            notes.append("No quorum configured; host synthesis owns the fitted answer")
        else:
            confidence = "low"
            notes.append("No successful independent reports")

    ok = not blocked and successful_count > 0
    if blocked:
        ok = False
        confidence = "blocked"
    elif successful_count == 0:
        confidence = "low"
    return ok, council_verified, blocked, confidence, notes


def _primary_attempt_from_spec(spec: LaneSpec) -> EffectiveAttempt:
    return EffectiveAttempt(
        profile=spec.profile,
        adapter=spec.adapter,
        executable=spec.executable,
        requested_model=spec.requested_model,
        extra_args=tuple(spec.extra_args),
        env_grants=tuple(spec.env_grants),
        enabled=True,
        required=spec.required,
        reason="primary",
    )


def _ordered_attempts(spec: LaneSpec) -> tuple[EffectiveAttempt, ...]:
    if spec.attempts:
        return spec.attempts
    return (_primary_attempt_from_spec(spec),)


def _binding_digest(*, run_id: str, lane_id: str, role: str, task: str) -> str:
    payload = f"{run_id}|{lane_id}|{role}|{task}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _HostEvidenceLedger:
    """Issue per-lane challenges and bind real host executor invocations."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._used_execution_ids: set[str] = set()
        self._lane_tokens: dict[str, str] = {}
        self._lane_execution_ids: dict[str, str] = {}
        self._invoked_lanes: set[str] = set()

    def issue_token(self, lane_id: str) -> str:
        token = f"host-exec-{uuid.uuid4().hex}"
        self._lane_tokens[lane_id] = token
        self._lane_execution_ids[lane_id] = f"host-exec-id-{uuid.uuid4().hex}"
        return token

    def token_for(self, lane_id: str) -> str | None:
        return self._lane_tokens.get(lane_id)

    def execution_id_for(self, lane_id: str) -> str | None:
        return self._lane_execution_ids.get(lane_id)

    def challenge_packet(
        self,
        *,
        lane_id: str,
        role: str,
        task: str,
        packet: Mapping[str, Any],
    ) -> dict[str, Any]:
        token = self._lane_tokens.get(lane_id)
        execution_id = self._lane_execution_ids.get(lane_id)
        if not token or not execution_id:
            raise ValidationIssue(
                "host_challenge_missing",
                f"No host challenge issued for lane `{lane_id}`",
            )
        binding = _binding_digest(
            run_id=self.run_id, lane_id=lane_id, role=role, task=task
        )
        return {
            "run_id": self.run_id,
            "lane_id": lane_id,
            "role": role,
            "task": task,
            "challenge_token": token,
            "execution_id": execution_id,
            "binding": binding,
            "packet": dict(packet),
        }

    def bind_executor_result(
        self,
        *,
        lane_id: str,
        role: str,
        task: str,
        challenge: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if lane_id in self._invoked_lanes:
            raise ValidationIssue(
                "host_executor_replay",
                f"host executor already invoked for lane `{lane_id}`",
            )
        issued_token = self._lane_tokens.get(lane_id)
        issued_exec = self._lane_execution_ids.get(lane_id)
        token = str(challenge.get("challenge_token") or "").strip()
        if not issued_token or token != issued_token:
            raise ValidationIssue(
                "host_evidence_challenge_mismatch",
                "host executor challenge_token does not match issued token",
            )
        if not evidence:
            raise ValidationIssue(
                "host_evidence_missing",
                "host executor returned empty evidence",
            )
        # Runtime-owned identity — ignore caller-forged execution_id.
        execution_id = issued_exec or f"host-exec-id-{uuid.uuid4().hex}"
        if execution_id in self._used_execution_ids:
            raise ValidationIssue(
                "host_evidence_replay",
                f"execution_id `{execution_id}` already consumed in this run",
            )
        expected_binding = _binding_digest(
            run_id=self.run_id, lane_id=lane_id, role=role, task=task
        )
        if str(challenge.get("binding") or "") != expected_binding:
            raise ValidationIssue(
                "host_evidence_binding_mismatch",
                "host executor challenge binding mismatch",
            )
        executor_id = str(
            evidence.get("executor_id")
            or (evidence.get("adapter_metadata") or {}).get("executor_id")
            or ""
        ).strip()
        if not executor_id:
            raise ValidationIssue(
                "host_evidence_incomplete",
                "host executor evidence requires executor_id",
            )
        bound = dict(evidence)
        bound["execution_id"] = execution_id
        bound["challenge_token"] = token
        bound["bound_lane_id"] = lane_id
        bound["bound_run_id"] = self.run_id
        bound["binding"] = expected_binding
        bound["executor_id"] = executor_id
        self._used_execution_ids.add(execution_id)
        self._invoked_lanes.add(lane_id)
        return bound, execution_id


async def _run_single_attempt(
    *,
    spec: LaneSpec,
    attempt: EffectiveAttempt,
    attempt_index: int,
    packet: ContextPacket,
    work_dir: Path,
    parent_env: Mapping[str, str] | None,
    command_override: tuple[str, ...] | None,
    repo_root: Path,
    host_ledger: _HostEvidenceLedger | None,
    task: str,
) -> tuple[AttemptResult, LaneResult]:
    """Thin coordinator (≤150 lines): transport → native/external → decode/result.

    Host-native execution, isolated external lifecycle, decode/result assembly,
    and artifact/redaction live in focused modules under ``dispatch_*``.
    """
    return await _run_single_attempt_impl(
        spec=spec,
        attempt=attempt,
        attempt_index=attempt_index,
        packet=packet,
        work_dir=work_dir,
        parent_env=parent_env,
        command_override=command_override,
        repo_root=repo_root,
        host_ledger=host_ledger,
        task=task,
    )


async def _run_lane_with_fallbacks(
    spec: LaneSpec,
    packet: ContextPacket,
    work_dir: Path,
    *,
    parent_env: Mapping[str, str] | None = None,
    repo_root: Path,
    host_ledger: _HostEvidenceLedger | None,
    task: str,
) -> LaneResult:
    launch_time = time.monotonic()
    ensure_private_dir(work_dir)
    attempts = _ordered_attempts(spec)
    attempt_results: list[AttemptResult] = []
    last_lane: LaneResult | None = None

    for index, attempt in enumerate(attempts):
        override = spec.command_override if index == 0 else None
        attempt_packet = build_context_packet(
            task=packet.task,
            role=packet.role,
            mode=packet.mode,
            scope=packet.scope,
            relevant_files=list(packet.relevant_files),
            plan_path=packet.plan_path,
            head_sha=packet.head_sha,
            requested_model=attempt.requested_model,
            profile=attempt.profile,
            adapter=attempt.adapter,
            run_id=packet.run_id,
            evidence_needs=list(packet.evidence_needs),
            forbidden_actions=list(packet.forbidden_actions),
            constraints=list(packet.constraints),
            extra={
                **dict(packet.extra or {}),
                "execution_identity": {
                    "run_id": packet.run_id,
                    "lane_id": spec.lane_id,
                    "attempt_index": index,
                    "profile": attempt.profile,
                },
            },
        )
        attempt_result, lane = await _run_single_attempt(
            spec=spec,
            attempt=attempt,
            attempt_index=index,
            packet=attempt_packet,
            work_dir=work_dir,
            parent_env=parent_env,
            command_override=override,
            repo_root=repo_root,
            host_ledger=host_ledger,
            task=task,
        )
        # Persist redacted attempt contract snapshot.
        contract_path = Path(lane.artifact_dir or work_dir) / "effective-contract.json"
        write_json_artifact(contract_path, attempt_result.effective_contract)
        attempt_results.append(attempt_result)
        last_lane = lane
        containment_terminal = bool(
            lane.failure_class == "isolation_failure" and lane.process_launched
        )
        if containment_terminal:
            # Once an external process launched, unproved containment is a
            # run-level safety failure, not a recoverable provider miss. Never
            # start another attempt (including host-native) in that state.
            attempt_result.effective_contract["fallback_terminal"] = True
            write_json_artifact(contract_path, attempt_result.effective_contract)
        if lane.ok:
            lane.attempts = attempt_results
            lane.launch_time = launch_time
            if index > 0:
                lane.fallback_used = attempt.profile
            return lane
        if (
            attempt.required
            or bool(attempt_result.effective_contract.get("fallback_terminal"))
            or (spec.required and lane.failure_class == "isolation_failure")
            or containment_terminal
        ):
            # A required attempt is a contract, not a preference. In
            # particular, required-isolation failure must block rather than
            # silently changing the execution route to host-native.
            break

    assert last_lane is not None
    last_lane.attempts = attempt_results
    last_lane.launch_time = launch_time
    last_lane.start_time = attempt_results[0].start_time if attempt_results else launch_time
    last_lane.end_time = attempt_results[-1].end_time if attempt_results else time.monotonic()
    last_lane.process_launched = any(a.process_launched for a in attempt_results)
    classes = [a.failure_class for a in attempt_results if a.failure_class]
    last_lane.failure_class = classes[-1] if classes else "unknown"
    reasons = [a.reason for a in attempt_results if a.reason]
    if reasons:
        last_lane.error = " | ".join(str(r) for r in reasons)
    return last_lane


async def run_council(
    lanes: Sequence[LaneSpec],
    *,
    repo_root: Path,
    task: str,
    mode: str = "read-only-council",
    phase: str = "review",
    phase_required: bool = False,
    target_quorum: int | None = None,
    required_quorum: int | None = None,
    head_sha: str | None = None,
    plan_path: str | None = None,
    run_id: str | None = None,
    parent_env: Mapping[str, str] | None = None,
    relevant_files: list[str] | None = None,
    create_artifacts: bool | None = None,
) -> CouncilResult:
    """Launch independent read-only lanes concurrently and collect reports."""
    lane_list = list(lanes)
    lane_count = len(lane_list)

    if required_quorum is not None and not phase_required:
        required_quorum = None

    try:
        target_quorum = validate_quorum_value(
            target_quorum, name="target_quorum", lane_count=lane_count
        )
        required_quorum = validate_quorum_value(
            required_quorum, name="required_quorum", lane_count=lane_count
        )
    except ValidationIssue as issue:
        rid = run_id or new_run_id(prefix=f"council-{phase}")
        return CouncilResult(
            run_id=rid,
            ok=False,
            council_verified=False,
            blocked=True,
            confidence="blocked",
            notes=[issue.message],
            target_quorum=target_quorum if isinstance(target_quorum, int) else None,
            required_quorum=required_quorum if isinstance(required_quorum, int) else None,
            phase_required=phase_required,
        )

    rid = run_id or new_run_id(prefix=f"council-{phase}")

    # Reject duplicate lane IDs before concurrent directory creation.
    seen_lane_ids: set[str] = set()
    normalized_lane_keys: set[str] = set()
    for spec in lane_list:
        if spec.lane_id in seen_lane_ids:
            return CouncilResult(
                run_id=rid,
                ok=False,
                council_verified=False,
                blocked=True,
                confidence="blocked",
                notes=[f"duplicate_lane_id: `{spec.lane_id}`"],
                phase_required=phase_required,
            )
        seen_lane_ids.add(spec.lane_id)
        norm = safe_path_component(spec.lane_id, field="lane_id")
        if norm in normalized_lane_keys:
            return CouncilResult(
                run_id=rid,
                ok=False,
                council_verified=False,
                blocked=True,
                confidence="blocked",
                notes=[f"duplicate_normalized_lane_id: `{spec.lane_id}` -> `{norm}`"],
                phase_required=phase_required,
            )
        normalized_lane_keys.add(norm)

    external_planned = any(
        spec.adapter != "host-native"
        or spec.command_override is not None
        or spec.host_executor is not None
        or any(a.adapter != "host-native" for a in (spec.attempts or ()))
        for spec in lane_list
    )
    # Host-executor-only native council still should not create .elves if no external
    # process is planned and create_artifacts is not forced.
    process_external = any(
        spec.adapter != "host-native" or spec.command_override is not None
        or any(a.adapter != "host-native" for a in (spec.attempts or ()))
        for spec in lane_list
    )
    should_create_artifacts = (
        create_artifacts if create_artifacts is not None else process_external
    )

    root: Path | None = None
    if should_create_artifacts:
        root = create_exclusive_artifact_root(repo_root, rid)

    host_ledger = _HostEvidenceLedger(rid)
    for spec in lane_list:
        if spec.adapter == "host-native" or any(
            a.adapter == "host-native" for a in (spec.attempts or ())
        ):
            host_ledger.issue_token(spec.lane_id)

    async def _one(spec: LaneSpec) -> LaneResult:
        safe_lane = safe_path_component(spec.lane_id, field="lane_id")
        packet = build_context_packet(
            task=task,
            role=spec.role,
            mode=mode,
            scope="read-only lens",
            relevant_files=relevant_files,
            plan_path=plan_path,
            head_sha=head_sha,
            requested_model=spec.requested_model,
            profile=spec.profile,
            adapter=spec.adapter,
            run_id=rid,
            extra={
                "host_challenge_token": host_ledger.token_for(spec.lane_id),
                "binding": _binding_digest(
                    run_id=rid, lane_id=spec.lane_id, role=spec.role, task=task
                ),
            },
        )
        ephemeral_dirs: list[Path] = []
        if root is not None:
            work_dir = ensure_private_dir(resolve_contained_path(root, safe_lane))
        else:
            # Scoped ephemeral dir with guaranteed cleanup (success/fail/timeout).
            import tempfile

            work_dir = Path(tempfile.mkdtemp(prefix=f"cobbler-lane-{safe_lane}-"))
            ephemeral_dirs.append(work_dir)
        try:
            return await _run_lane_with_fallbacks(
                spec,
                packet,
                work_dir,
                parent_env=parent_env,
                repo_root=Path(repo_root),
                host_ledger=host_ledger,
                task=task,
            )
        finally:
            import shutil

            for path in ephemeral_dirs:
                shutil.rmtree(path, ignore_errors=True)

    results = list(await asyncio.gather(*[_one(spec) for spec in lane_list]))

    successful_reports: list[dict[str, Any]] = []
    successful_execution_ids: list[str] = []
    required_failures: list[str] = []
    containment_failures: list[str] = []
    model_calls = False
    for lane, spec in zip(results, lane_list):
        # Explicit per-lane/per-attempt call truth (host executor + subprocess).
        if lane.model_call_made or any(a.model_call_made for a in lane.attempts):
            model_calls = True
        # Artifact roots under the council run mean runtime mutation of ignored state.
        if root is not None:
            lane.mutated_repo = True
            for attempt in lane.attempts:
                # keep attempt-level truth separate; mutation is lane/run scoped
                pass
        if lane.ok and lane.report is not None and lane.execution_id:
            if lane.execution_id not in successful_execution_ids:
                successful_execution_ids.append(lane.execution_id)
                successful_reports.append(lane.report)
        elif spec.required:
            required_failures.append(spec.lane_id)
        if lane.failure_class == "isolation_failure" and lane.process_launched:
            containment_failures.append(spec.lane_id)

    ok, verified, blocked, confidence, notes = evaluate_quorum(
        successful_count=len(successful_execution_ids),
        target_quorum=target_quorum,
        required_quorum=required_quorum,
        phase_required=phase_required,
        required_lane_failures=required_failures,
        lane_count=lane_count,
    )
    if containment_failures:
        ok = False
        verified = False
        blocked = True
        confidence = "blocked"
        notes.append(
            "post-launch containment unproved: "
            + ", ".join(sorted(containment_failures))
        )
    notes.append("lanes_independent=true; host_synthesis_only=true")
    notes.append("host_native_requires_host_executor_callback=true")
    notes.append("quorum_counts_distinct_execution_ids=true")

    mutated = root is not None  # exclusive council artifact root created
    summary = CouncilResult(
        run_id=rid,
        ok=ok,
        council_verified=verified,
        blocked=blocked,
        confidence=confidence,
        successful_reports=successful_reports,
        lane_results=results,
        target_quorum=target_quorum,
        required_quorum=required_quorum,
        phase_required=phase_required,
        notes=notes,
        artifact_root=str(root) if root is not None else None,
        model_calls_made=model_calls,
        mutated_repo=mutated,
        successful_execution_ids=successful_execution_ids,
    )
    if root is not None:
        write_json_artifact(root / "council-result.json", summary.to_dict())
    return summary


async def run_lightweight_review(
    *,
    repo_root: Path,
    task: str,
    adapter: str = "host-native",
    profile: str = "host-native",
    executable: str | None = None,
    requested_model: str | None = None,
    command_override: tuple[str, ...] | None = None,
    timeout_seconds: float = 30.0,
    parent_env: Mapping[str, str] | None = None,
    head_sha: str | None = None,
    run_id: str | None = None,
    env_grants: tuple[str, ...] = (),
    injected_host_evidence: dict[str, Any] | None = None,
    host_executor: HostExecutor | None = None,
) -> LaneResult:
    """Single bounded ephemeral read-only utility review."""
    rid = run_id or new_run_id(prefix="lightweight-review")
    external = adapter != "host-native" or command_override is not None
    root: Path | None = None
    if external:
        root = create_exclusive_artifact_root(repo_root, rid)

    # Do not fabricate host identities for static evidence. Verified host-native
    # reviews require a host_executor callback.
    _ = injected_host_evidence  # compatibility diagnostics only; not a vote.

    spec = LaneSpec(
        lane_id="lightweight_review",
        role="lightweight_review",
        adapter=adapter,
        profile=profile,
        requested_model=requested_model,
        executable=executable,
        required=False,
        timeout_seconds=timeout_seconds,
        command_override=command_override,
        env_grants=env_grants,
        host_executor=host_executor,
    )
    packet = build_context_packet(
        task=task,
        role="lightweight_review",
        mode="lightweight-review",
        scope="read-only lens",
        head_sha=head_sha,
        requested_model=requested_model,
        profile=profile,
        adapter=adapter,
        run_id=rid,
        constraints=[
            "ephemeral",
            "not_a_council_vote",
            "cannot_close_high_risk_review",
            "no_git_or_pr_mutations",
        ],
        forbidden_actions=[
            "git_commit",
            "git_push",
            "open_pr",
            "merge_pr",
            "close_high_risk_review",
            "mutate_run_memory",
            "edit_product_files",
        ],
    )
    host_ledger = _HostEvidenceLedger(rid)
    if adapter == "host-native":
        host_ledger.issue_token(spec.lane_id)

    ephemeral: Path | None = None
    if root is not None:
        work_dir = ensure_private_dir(resolve_contained_path(root, "lightweight_review"))
    else:
        import tempfile

        ephemeral = Path(tempfile.mkdtemp(prefix="cobbler-lightweight-"))
        work_dir = ephemeral
    try:
        result = await _run_lane_with_fallbacks(
            spec,
            packet,
            work_dir,
            parent_env=parent_env,
            repo_root=Path(repo_root),
            host_ledger=host_ledger,
            task=task,
        )
        # Explicit mutation truth from whether an external artifact root was created.
        result.mutated_repo = root is not None
        if root is not None:
            write_json_artifact(root / "lightweight-review-result.json", result.to_dict())
            if result.artifact_dir is None:
                result.artifact_dir = str(root)
        return result
    finally:
        if ephemeral is not None:
            import shutil

            shutil.rmtree(ephemeral, ignore_errors=True)


def host_evidence_binding(*, run_id: str, lane_id: str, role: str, task: str) -> str:
    """Public helper so tests/hosts can bind injected evidence correctly."""
    return _binding_digest(run_id=run_id, lane_id=lane_id, role=role, task=task)


def run_council_sync(*args: Any, **kwargs: Any) -> CouncilResult:
    return asyncio.run(run_council(*args, **kwargs))


def run_lightweight_review_sync(*args: Any, **kwargs: Any) -> LaneResult:
    return asyncio.run(run_lightweight_review(*args, **kwargs))
