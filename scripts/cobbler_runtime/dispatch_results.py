"""Attempt and lane result assembly for council dispatch.

The coordinator supplies runtime facts; this module owns their redacted result
representation.  It depends on stable dispatch contracts, never the dispatch
facade, so lane execution has a single dependency direction.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable

from .adapters import decode_adapter_output, default_decoder_for_adapter
from .context import (
    EnvScrubResult,
    redact_structure,
    redact_text,
    write_text_artifact,
)
from .dispatch_attempt import classify_failure
from .dispatch_models import AttemptResult, LaneResult, LaneSpec
from .schema import EffectiveAttempt, ValidationIssue


def require_exact_session_identity(
    *, expected: str | None, observed: str | None
) -> None:
    """Require transport proof for an invocation that requested one exact session."""
    if expected is None:
        return
    if observed != expected:
        raise ValidationIssue(
            "session_identity_mismatch",
            "Provider transport did not confirm the requested exact session identity",
        )


def summarize(
    text: str,
    *,
    exact_values: frozenset[str] | set[str] | None = None,
    limit: int = 400,
) -> str:
    redacted = redact_text(text or "", exact_values=exact_values).text
    compact = " ".join(redacted.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def build_failed_attempt(
    *,
    attempt_result: AttemptResult,
    spec: LaneSpec,
    attempt: EffectiveAttempt,
    launch_time: float,
    scrub: EnvScrubResult,
    grants: list[str],
    exact_secret_values: frozenset[str],
    attempt_dir: str,
    reason: str,
    failure_class: str,
    command: list[str] | None = None,
    process_launched: bool = False,
    exit_code: int | None = None,
    timeout: bool = False,
    cleanup: dict[str, Any] | None = None,
    stdout: str = "",
    stderr: str = "",
    model_call_made: bool | None = None,
) -> tuple[AttemptResult, LaneResult]:
    """Record one failed attempt and its lane-facing result."""
    end = time.monotonic()
    red_reason = redact_text(reason, exact_values=exact_secret_values).text
    call_made = (
        model_call_made
        if model_call_made is not None
        else (process_launched and attempt.adapter != "host-native")
    )
    attempt_result.end_time = end
    attempt_result.status = "failed"
    attempt_result.failure_class = failure_class
    attempt_result.reason = red_reason
    attempt_result.ok = False
    attempt_result.timeout = timeout
    attempt_result.exit_code = exit_code
    attempt_result.command = list(command or [])
    attempt_result.cleanup = dict(cleanup or {})
    attempt_result.process_launched = process_launched
    attempt_result.model_call_made = call_made
    attempt_result.requested_model = (
        redact_text(
            str(attempt.requested_model), exact_values=exact_secret_values
        ).text
        if attempt.requested_model is not None
        else None
    )
    lane = LaneResult(
        lane_id=spec.lane_id,
        role=spec.role,
        adapter=attempt.adapter,
        profile=attempt.profile,
        ok=False,
        launch_time=launch_time,
        start_time=attempt_result.start_time,
        end_time=end,
        timeout=timeout,
        exit_code=exit_code,
        error=red_reason,
        requested_model=attempt_result.requested_model,
        stripped_env_names=list(scrub.stripped_names),
        granted_env_names=list(grants),
        command=list(command or []),
        artifact_dir=attempt_dir,
        failure_class=failure_class,
        stdout_summary=summarize(stdout, exact_values=exact_secret_values),
        stderr_summary=summarize(stderr, exact_values=exact_secret_values),
        process_launched=process_launched,
        model_call_made=call_made,
        mutated_repo=False,
    )
    return attempt_result, lane


def assemble_external_result(
    *,
    proc_result: dict[str, Any],
    invocation: Any,
    redacted_command: list[str],
    attempt_result: AttemptResult,
    attempt: EffectiveAttempt,
    spec: LaneSpec,
    attempt_index: int,
    attempt_dir: Path,
    exact_secret_values: frozenset[str],
    scrub: EnvScrubResult,
    grants: list[str],
    launch_time: float,
    fail_fn: Callable[..., tuple[AttemptResult, LaneResult]],
) -> tuple[AttemptResult, LaneResult]:
    """Decode an external process result into attempt and lane evidence."""
    if not proc_result.get("ok"):
        stdout = redact_text(
            proc_result.get("stdout_raw") or "",
            exact_values=exact_secret_values,
        ).text
        stderr = redact_text(
            proc_result.get("stderr_raw") or "",
            exact_values=exact_secret_values,
        ).text
        if stdout:
            write_text_artifact(attempt_dir / "stdout.txt", stdout)
        if stderr:
            write_text_artifact(attempt_dir / "stderr.txt", stderr)
        return fail_fn(
            reason=redact_text(
                str(proc_result.get("reason") or "external failed"),
                exact_values=exact_secret_values,
            ).text,
            failure_class=str(
                proc_result.get("failure_class") or "execution_failure"
            ),
            command=redacted_command,
            process_launched=bool(proc_result.get("process_launched")),
            exit_code=proc_result.get("exit_code"),
            timeout=bool(proc_result.get("timeout")),
            cleanup=proc_result.get("cleanup") or {},
            stdout=stdout,
            stderr=stderr,
        )

    stdout_raw = proc_result.get("stdout_raw") or ""
    stderr_raw = proc_result.get("stderr_raw") or ""
    stdout = redact_text(stdout_raw, exact_values=exact_secret_values).text
    stderr = redact_text(stderr_raw, exact_values=exact_secret_values).text
    write_text_artifact(attempt_dir / "stdout.txt", stdout)
    write_text_artifact(attempt_dir / "stderr.txt", stderr)
    exit_code = int(proc_result.get("exit_code") or 0)
    command = redacted_command
    decoder = invocation.decoder or default_decoder_for_adapter(attempt.adapter)
    try:
        decoded = decode_adapter_output(
            stdout_raw,
            decoder=decoder,
            expected_role=spec.role,
            requested_model=attempt.requested_model,
            require_model=attempt.requested_model is not None,
        )
        require_exact_session_identity(
            expected=invocation.session_id,
            observed=decoded.session_id,
        )
        report = redact_structure(
            decoded.role_report, exact_values=exact_secret_values
        )
        actual = (
            redact_text(
                str(decoded.actual_model), exact_values=exact_secret_values
            ).text
            if decoded.actual_model is not None
            else None
        )
        decoded = type(decoded)(
            role_report=report,
            actual_model=actual,
            model_evidence_source=decoded.model_evidence_source,
            session_id=decoded.session_id,
            transport_notes=decoded.transport_notes,
        )
    except ValidationIssue as issue:
        msg = redact_text(issue.message, exact_values=exact_secret_values).text
        if exit_code != 0:
            msg = f"non-zero terminal status: exit_code={exit_code}; {msg}"
        return fail_fn(
            reason=msg,
            failure_class=classify_failure(
                timeout=False,
                exit_code=exit_code,
                error=issue.message,
            ),
            command=command,
            process_launched=True,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )

    end_time = time.monotonic()
    attempt_result.end_time = end_time
    attempt_result.exit_code = exit_code
    attempt_result.command = list(command)
    attempt_result.actual_model = decoded.actual_model
    attempt_result.model_evidence_source = decoded.model_evidence_source
    attempt_result.process_launched = True
    attempt_result.model_call_made = True
    if exit_code != 0:
        # Keep parseable report for diagnostics, but never mark ok.
        end_time = time.monotonic()
        attempt_result.end_time = end_time
        attempt_result.status = "failed"
        attempt_result.failure_class = "execution_failure"
        attempt_result.reason = f"non-zero terminal status: exit_code={exit_code}"
        attempt_result.ok = False
        attempt_result.model_call_made = True
        lane = LaneResult(
            lane_id=spec.lane_id,
            role=spec.role,
            adapter=attempt.adapter,
            profile=attempt.profile,
            ok=False,
            launch_time=launch_time,
            start_time=attempt_result.start_time,
            end_time=end_time,
            exit_code=exit_code,
            error=attempt_result.reason,
            requested_model=(
                redact_text(
                    str(attempt.requested_model),
                    exact_values=exact_secret_values,
                ).text
                if attempt.requested_model is not None
                else None
            ),
            native_session_id=decoded.session_id,
            actual_model=decoded.actual_model,
            model_evidence_source=decoded.model_evidence_source,
            report=decoded.role_report,
            stripped_env_names=list(scrub.stripped_names),
            granted_env_names=[name for name in grants if name in scrub.kept_names],
            command=command,
            artifact_dir=str(attempt_dir),
            failure_class="execution_failure",
            stdout_summary=summarize(stdout, exact_values=exact_secret_values),
            stderr_summary=summarize(stderr, exact_values=exact_secret_values),
            process_launched=True,
            model_call_made=True,
            mutated_repo=False,
        )
        return attempt_result, lane

    execution_id = hashlib.sha256(
        f"{spec.lane_id}:{attempt_index}:{decoded.actual_model}:{time.time()}".encode()
    ).hexdigest()[:16]
    attempt_result.ok = True
    attempt_result.status = "success"
    lane = LaneResult(
        lane_id=spec.lane_id,
        role=spec.role,
        adapter=attempt.adapter,
        profile=attempt.profile,
        ok=True,
        launch_time=launch_time,
        start_time=attempt_result.start_time,
        end_time=end_time,
        exit_code=exit_code,
        requested_model=(
            redact_text(
                str(attempt.requested_model), exact_values=exact_secret_values
            ).text
            if attempt.requested_model is not None
            else None
        ),
        native_session_id=decoded.session_id,
        actual_model=decoded.actual_model,
        model_evidence_source=decoded.model_evidence_source,
        stdout_summary=summarize(stdout, exact_values=exact_secret_values),
        stderr_summary=summarize(stderr, exact_values=exact_secret_values),
        report=decoded.role_report,
        stripped_env_names=list(scrub.stripped_names),
        granted_env_names=[name for name in grants if name in scrub.kept_names],
        command=command,
        artifact_dir=str(attempt_dir),
        successful_attempt_index=attempt_index,
        execution_id=execution_id,
        process_launched=True,
        model_call_made=True,
        mutated_repo=False,
    )
    return attempt_result, lane
