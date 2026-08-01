"""Full-run monitor and await entrypoints (extracted from full_run.py).

Host-facing lifecycle ops for parked full-run supervision. Shared state machines,
event parsing, and prepare/launch remain in ``full_run``.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Import the full_run module for private helpers and shared types. This module is
# loaded only after full_run has finished initializing (via full_run.__getattr__
# or an explicit import by the CLI after full_run is already loaded).
from . import full_run as _fr


_KEEP = frozenset(
    {
        "_fr",
        "_bind",
        "_refresh_helpers",
        "_KEEP",
        "monitor_full_run",
        "await_full_run",
        "Any",
        "Mapping",
        "Path",
        "Sequence",
        "annotations",
    }
)


def _refresh_helpers() -> None:
    """Rebind helpers from full_run so unit-test patches on full_run apply here."""
    g = globals()
    for name, value in _fr.__dict__.items():
        if name.startswith("__") or name in _KEEP:
            continue
        g[name] = value


_refresh_helpers()


@_locked_full_run
def monitor_full_run(
    repo_root: Path,
    *,
    session_id: str,
    stale_after_seconds: int = DEFAULT_STALE_SECONDS,
    acknowledge_high_risk_checkpoint: str | None = None,
    depth: str | None = None,
    force_full: bool = False,
) -> dict[str, Any]:
    """Classify health using fingerprint + branch head + validated events/report.

    ``depth`` may be ``incremental`` or ``full``. When omitted, healthy polls use
    incremental reconciliation (liveness + local refs + events) and terminal or
    safety wakes force full remote-audit + deep Git reconciliation.
    """
    _refresh_helpers()
    state = load_state(repo_root, session_id)
    initial_status = state.status
    initial_next_action = state.next_action
    initial_blocker = state.blocker
    initial_completed_at = state.completed_at
    initial_pending_checkpoint = state.pending_high_risk_checkpoint
    initial_acknowledged_checkpoints = tuple(
        state.acknowledged_high_risk_checkpoints
    )
    # Lazy on purpose: risk_policy imports full_run at module level (real cycle).
    from .risk_policy import monitor_depth_for_status  # noqa: PLC0415

    cache = dict(state.monitor_cache or {})
    remote_audit_due = True
    last_remote = cache.get("last_remote_audit_at")
    if last_remote and isinstance(last_remote, str):
        try:
            last_dt = datetime.fromisoformat(last_remote.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
            # Bounded remote all-ref cadence: half the stale window, min 60s.
            cadence = max(60, max(0, stale_after_seconds) // 2)
            remote_audit_due = age >= cadence
        except ValueError:
            remote_audit_due = True
    resolved_depth = depth or monitor_depth_for_status(
        status=state.status,
        next_action=state.next_action,
        force_full=force_full,
        remote_audit_due=remote_audit_due,
    )
    # Always full when already terminal/safety or ack is present.
    if (
        force_full
        or acknowledge_high_risk_checkpoint is not None
        or state.status in {"complete", "failed", "blocked", "stopped", "stale"}
        or (state.next_action or "").startswith("driver_wake_")
    ):
        resolved_depth = "full"
    include_remote_audit = resolved_depth == "full"
    identity_retired = bool(
        state.closed_process_identity
        and state.pid is None
        and state.pgid is None
        and state.fingerprint is None
    )
    root = full_run_root(repo_root, session_id)

    # Devin CLI does not preallocate a session id; capture the exact provider
    # UUID using the isolated worker env. Capture is attempted even if a fast
    # worker has already exited, so long as an identity has not been retired.
    if (
        state.adapter == "devin-cli"
        and not state.provider_session_id
        and not identity_retired
    ):
        attempts = int(cache.get("devin_capture_attempts") or 0)
        last_attempt = cache.get("devin_capture_last_attempt")
        now = time.monotonic()
        backoff = min(5 + attempts * 2, 60)
        if last_attempt is None or (now - float(last_attempt)) >= backoff:
            launch_env = build_full_run_env(
                state=state,
                root=root,
                parent_env=os.environ,
            )
            captured = _capture_devin_session_id(
                state, root, Path(repo_root), launch_env
            )
            cache["devin_capture_attempts"] = attempts + 1
            cache["devin_capture_last_attempt"] = now
            if captured:
                state.provider_session_id = captured
                cache["devin_capture_succeeded_at"] = now
                state.monitor_cache = cache
                save_state(repo_root, state)

    grant_context_verified, exact_secret_values = _launch_evidence_context(state)
    events_path = root / "events.jsonl"
    events_reused = False
    event_signature: dict[str, Any] | None = None
    cached_event_summary = cache.get("event_summary")
    try:
        event_signature = _event_log_signature(Path(repo_root), events_path)
    except StorageError as exc:
        event_signature = None
        events, event_errors = [], [exc.message]
    else:
        events_reused = bool(
            resolved_depth == "incremental"
            and event_signature == cache.get("event_signature")
            and isinstance(cached_event_summary, Mapping)
        )
    if event_signature is not None and events_reused:
        events, event_errors = [], []
    elif event_signature is not None and grant_context_verified:
        events, event_errors = _read_events(
            events_path,
            expected_session_id=session_id,
            expected_branch=state.branch,
            expected_high_risk_checkpoints=state.planned_high_risk_checkpoints,
            exact_secret_values=exact_secret_values,
            credential_grant_state=state,
            shared_oauth_safe_projection=(
                state.grok_auth_strategy == "oauth_shared_file"
            ),
            allow_partial_final=not identity_retired and bool(state.pid or state.pgid),
            repo_root=Path(repo_root),
        )
    elif event_signature is not None:
        events, event_errors = [], [
            "launch credential context cannot be verified for worker evidence"
        ]
    report_path = root / "report.json"
    report: dict[str, Any] = {}
    report_errors: list[str] = (
        []
        if grant_context_verified
        else ["launch credential context cannot be verified for worker report"]
    )
    try:
        report_exists = repo_regular_file_exists(Path(repo_root), report_path)
    except StorageError as exc:
        report_exists = False
        report_errors = [exc.message]
    if report_exists and grant_context_verified:
        try:
            report = _read_bounded_json_object(
                report_path,
                label="run report",
                repo_root=Path(repo_root),
            )
            report_errors = validate_run_report(
                report,
                expected_session_id=session_id,
                expected_branch=state.branch,
                expected_start_head=state.start_head,
                require_complete_acceptance=report.get("status") == "complete",
                expected_run_id=_expected_run_id(session_id),
                expected_attempt=state.attempt,
                expected_acceptance_criteria=(
                    state.acceptance_criteria
                    if state.adapter != "fixture"
                    else None
                ),
                exact_secret_values=exact_secret_values,
                credential_grant_state=state,
            )
            redacted_report = _redact_full_run_structure(
                _redact_persisted_credential_grants(report, state),
                exact_values=exact_secret_values,
            )
            if redacted_report != report:
                # The worker writes this private artifact directly. Replace any
                # detected credential material before surfacing a generic error.
                atomic_write_json(
                    report_path,
                    redacted_report,
                    repo_root=Path(repo_root),
                )
            if report_errors:
                report = {}
        except StorageError as exc:
            report_errors = [exc.message]
            report = {}

    # Process fingerprint is primary liveness for long Grok turns. The process
    # group is tracked independently because a provider can leave descendants
    # behind after its direct parent exits.
    fp_ok = False
    fp_reason = "retired process identity" if identity_retired else "no fingerprint"
    alive = False
    if state.fingerprint and not identity_retired:
        fp_ok, fp_reason = verify_fingerprint(
            state.fingerprint, expected_session_id=session_id
        )
        alive = fp_ok
        if not fp_ok and state.pid:
            # In embedded/API use this process may still be the supervisor's
            # parent. Reap a dead exact child before probing its former process
            # group; otherwise a zombie can make killpg(..., 0) look live
            # indefinitely and strand lifecycle finalization.
            _reap_supervisor_if_child(state.pid)
    elif state.pid and not identity_retired:
        alive = _pid_alive(state.pid)
        fp_reason = "legacy pid without fingerprint"
    group_alive = False if identity_retired else _process_group_alive(state.pgid)
    supervised_pids: set[int] = set()
    supervision_scan_ok = bool(identity_retired)
    if not identity_retired:
        try:
            supervised_pids = _supervised_alive(state)
        except ValidationIssue as issue:
            exit_record_errors = [issue.message]
        else:
            exit_record_errors = []
            supervision_scan_ok = True
    else:
        exit_record_errors = []

    # Host-owned exit sidecar: actual child exit code + fingerprint after provider exits.
    exit_record: dict[str, Any] | None = None
    candidate_exit_record = None
    if not identity_retired:
        try:
            candidate_exit_record = read_exit_record(
                root,
                repo_root=Path(repo_root),
            )
        except StorageError as exc:
            exit_record_errors.append(exc.message)
    if candidate_exit_record is not None and not identity_retired:
        exit_record_errors.extend(_validate_exit_record(candidate_exit_record, state))
        if not exit_record_errors:
            pid_still_alive, group_alive = _settle_recorded_supervisor_exit(
                state.pid,
                state.pgid,
            )
            if not pid_still_alive and not group_alive:
                try:
                    supervised_pids = _supervised_alive(state)
                except ValidationIssue as issue:
                    exit_record_errors.append(issue.message)
                    supervision_scan_ok = False
                else:
                    supervision_scan_ok = True
            if pid_still_alive or group_alive or supervised_pids:
                exit_record_errors.append(
                    "premature exit record while supervised process identity remains alive"
                )
                fp_reason = "premature exit record"
            else:
                exit_record = candidate_exit_record
                state.exit_code = int(exit_record["exit_code"])
                alive = False
                fp_ok = False
                fp_reason = "validated exit record after full process-group exit"

    grok_terminal_failure: dict[str, str] | None = None
    if exit_record is not None and state.adapter == "grok-build" and grant_context_verified:
        try:
            grok_terminal_failure = _grok_terminal_failure(
                Path(repo_root),
                state,
                exact_values=exact_secret_values,
            )
        except ValidationIssue as issue:
            exit_record_errors.append(issue.message)

    # Observed feature-branch state. Process liveness is not a heartbeat: a hung
    # provider can remain fingerprint-valid indefinitely and must still wake the
    # parked driver when no meaningful worker/event activity is observed.
    observed_head = _git_head(Path(state.worktree))
    observed_branch = _git_branch(Path(state.worktree))
    if observed_head:
        state.head = observed_head

    last_type = (
        cached_event_summary.get("last_type")
        if events_reused and isinstance(cached_event_summary, Mapping)
        else None
    )
    saw_run_complete_event = bool(
        events_reused
        and isinstance(cached_event_summary, Mapping)
        and cached_event_summary.get("saw_run_complete")
    )
    observed_high_risk_checkpoints: list[str] = (
        [str(item) for item in cached_event_summary.get("high_risk_checkpoints", [])]
        if events_reused and isinstance(cached_event_summary, Mapping)
        else []
    )
    observed_material_change = bool(
        events_reused
        and isinstance(cached_event_summary, Mapping)
        and cached_event_summary.get("material_scope_or_assumption_change")
    )
    event_count = (
        int(cached_event_summary.get("count") or 0)
        if events_reused and isinstance(cached_event_summary, Mapping)
        else len(events)
    )
    # Three distinct states, and they must never conflate: None = no signal
    # captured, [] = the worker's positive asserted-clean answer, items = the
    # worker's reservations. A shared-OAuth run carries only the derived count.
    cached_signal = _project_confidence_signal(
        {
            "confidence": cached_event_summary.get("last_batch_confidence"),
            **(
                {
                    "unsure_about": cached_event_summary.get(
                        "last_batch_unsure_about"
                    )
                }
                if isinstance(
                    cached_event_summary.get("last_batch_unsure_about"), list
                )
                else {}
            ),
            "unsure_about_count": cached_event_summary.get(
                "last_batch_unsure_about_count"
            ),
        }
        if events_reused and isinstance(cached_event_summary, Mapping)
        else {}
    )
    last_batch_confidence: str | None = cached_signal["confidence"]
    last_batch_unsure_about: list[str] | None = cached_signal["unsure_about"]
    last_batch_unsure_about_count: int | None = cached_signal["unsure_about_count"]
    for ev in events:
        last_type = ev.get("type") or last_type
        if ev.get("type") == "batch_started":
            try:
                state.batch = int(ev.get("batch") or state.batch or 0)
            except (TypeError, ValueError):
                pass
        state.heartbeat_at = _latest_utc_iso8601(
            state.heartbeat_at, ev.get("timestamp")
        )
        if ev.get("type") == "blocked":
            state.status = "blocked"
            state.blocker = (
                "worker reported a blocked event"
                if state.grok_auth_strategy == "oauth_shared_file"
                else str(ev.get("summary") or "blocked")
            )
            state.next_action = "driver_wake_blocker"
        if ev.get("type") == "run_complete":
            # Lone run_complete never establishes completion — needs validated report
            # or clean provider exit with feature-branch progress.
            saw_run_complete_event = True
        if ev.get("type") == "high_risk_checkpoint":
            observed_high_risk_checkpoints.append(str(ev.get("checkpoint_id")))
        if ev.get("type") == "material_scope_or_assumption_change":
            observed_material_change = True
        if ev.get("type") == "batch_complete":
            # Optional worker confidence signal: bounded review-triage metadata
            # only, never authority. Reset from every batch_complete so
            # "last_batch_*" is true to its name — a later batch without the
            # signal must not inherit an earlier batch's reservations. Under
            # shared OAuth the projection already replaced the free-text list
            # with a derived count; the enum survives the projection.
            event_signal = _project_confidence_signal(
                ev,
                transform=lambda item: _redact_full_run_text(
                    item, exact_values=exact_secret_values
                ),
            )
            last_batch_confidence = event_signal["confidence"]
            last_batch_unsure_about = event_signal["unsure_about"]
            last_batch_unsure_about_count = event_signal["unsure_about_count"]

    if not event_errors and not events_reused and event_signature is not None:
        cache["event_signature"] = event_signature
        cache["event_summary"] = {
            "count": len(events),
            "last_type": last_type,
            "saw_run_complete": saw_run_complete_event,
            "high_risk_checkpoints": list(observed_high_risk_checkpoints),
            "material_scope_or_assumption_change": observed_material_change,
            "last_batch_confidence": last_batch_confidence,
            "last_batch_unsure_about": (
                list(last_batch_unsure_about)
                if last_batch_unsure_about is not None
                else None
            ),
            "last_batch_unsure_about_count": last_batch_unsure_about_count,
        }

    if acknowledge_high_risk_checkpoint is not None:
        checkpoint_id = str(acknowledge_high_risk_checkpoint)
        if (
            event_errors
            or not _HIGH_RISK_CHECKPOINT_ID_RE.fullmatch(checkpoint_id)
            or state.pending_high_risk_checkpoint != checkpoint_id
            or checkpoint_id not in observed_high_risk_checkpoints
            or checkpoint_id in state.acknowledged_high_risk_checkpoints
        ):
            raise ValidationIssue(
                "full_run_checkpoint_ack_invalid",
                "Checkpoint acknowledgement must match the exact pending validated event",
            )
        state.acknowledged_high_risk_checkpoints = sorted(
            {*state.acknowledged_high_risk_checkpoints, checkpoint_id}
        )
        state.pending_high_risk_checkpoint = None

    unacknowledged_high_risk_checkpoints = [
        checkpoint_id
        for checkpoint_id in observed_high_risk_checkpoints
        if checkpoint_id not in state.acknowledged_high_risk_checkpoints
    ]
    if (
        state.pending_high_risk_checkpoint is not None
        and state.pending_high_risk_checkpoint
        not in observed_high_risk_checkpoints
    ):
        event_errors.append("pending checkpoint is missing from the event log")

    # Report is evidence only after validation. Completion requires a fully
    # evidenced report, exact head/ancestry, and a clean exit accepted only after
    # the supervisor PID and its entire process group are dead.
    if report and not report_errors:
        if report.get("status") == "complete":
            final_head = str(report.get("final_head") or "")
            # Real adapters must prove feature-branch ancestry. Explicit fixture mode
            # may emit synthetic heads for multi-batch semantics without mutating git.
            if state.adapter != "fixture":
                if final_head and observed_head and final_head != observed_head:
                    report_errors.append(
                        "report final_head does not match observed feature branch head"
                    )
                elif final_head and not _is_ancestor(
                    Path(state.worktree), state.start_head, final_head
                ):
                    report_errors.append(
                        "report final_head is not a descendant of start_head"
                    )
        elif report.get("status") == "blocked":
            state.status = "blocked"
            state.blocker = state.blocker or "report status blocked"
            state.next_action = "driver_wake_blocker"
        elif report.get("status") == "failed":
            state.status = "failed"
            state.next_action = "driver_wake_error"

    report_errors.extend(
        _validate_git_bound_evidence(state, report, events, observed_head)
    )
    missing_high_risk_checkpoints = [
        checkpoint_id
        for checkpoint_id in state.planned_high_risk_checkpoints
        if checkpoint_id not in observed_high_risk_checkpoints
    ]
    if (
        exit_record is not None
        and state.exit_code == 0
        and report
        and report.get("status") == "complete"
        and missing_high_risk_checkpoints
    ):
        # A packet-declared checkpoint is part of the staged execution
        # contract. A worker cannot bypass the host wake gate by simply omitting
        # the event and racing directly to a complete report.
        report_errors.append(
            "complete run omitted one or more planned high-risk checkpoints"
        )

    # Protected refs: any movement blocks readiness (policy trust, not OS sandbox).
    # Incremental healthy polls verify local refs only; remote all-ref audit runs
    # on a bounded cadence and always at terminal/safety depth.
    try:
        protected_errors = verify_protected_refs_unchanged(
            Path(repo_root),
            state.protected_refs or {},
            feature_branch=state.branch,
            include_remote=include_remote_audit,
        )
    except ValidationIssue as issue:
        protected_errors = [issue.message]
    if include_remote_audit:
        cache["last_remote_audit_at"] = _utc_now()
    if state.adapter != "fixture":
        try:
            if (
                _canonical_origin_url(Path(repo_root)) != state.origin_url
                or _origin_config_digest(Path(repo_root)) != state.origin_config_digest
            ):
                protected_errors.append("origin URL/config changed after preparation")
        except ValidationIssue as issue:
            protected_errors.append(issue.message)
    if protected_errors:
        state.status = "failed"
        state.blocker = "; ".join(protected_errors)
        state.next_action = "driver_wake_safety_tripwire"

    # Invalid worker evidence is wake-worthy. Exit-record and event corruption
    # always fail hard. Report validation failures also fail hard unless the
    # report is entirely missing after a clean exit (host reconcilable path).
    clean_provider_exit = exit_record is not None and state.exit_code == 0
    if event_errors or exit_record_errors:
        state.status = "failed"
        evidence_errors = event_errors + exit_record_errors
        state.blocker = "; ".join(evidence_errors[:4]) or "untrusted worker evidence"
        state.next_action = "driver_wake_error"
    elif report_errors and not (clean_provider_exit and not report):
        # Checkpoint/head/ancestry/security report failures remain hard failures.
        state.status = "failed"
        state.blocker = "; ".join(report_errors[:4]) or "untrusted worker evidence"
        state.next_action = "driver_wake_error"

    # Branch mismatch is a safety signal.
    if observed_branch and observed_branch != state.branch:
        state.status = "failed"
        state.blocker = f"worktree branch `{observed_branch}` != staged `{state.branch}`"
        state.next_action = "driver_wake_safety_tripwire"

    # A validated nonzero provider exit is authoritative even if the worker wrote
    # a superficially complete report immediately before terminating.
    if exit_record is not None and state.exit_code != 0:
        state.status = "failed"
        state.blocker = f"provider nonzero exit: {state.exit_code}"
        state.next_action = "driver_wake_error"
    elif exit_record is not None and grok_terminal_failure is not None:
        failure_code = grok_terminal_failure["code"]
        state.status = "failed"
        state.blocker = f"{failure_code}: Grok provider did not complete the run"
        state.next_action = (
            "driver_wake_provider_limit"
            if failure_code == "grok_max_turns_reached"
            else (
                "driver_wake_provider_cancelled"
                if failure_code == "grok_provider_cancelled"
                else "driver_wake_error"
            )
        )

    if state.status not in {"blocked", "failed", "stopped"} and not (
        identity_retired
        and initial_status in {"complete", "stopped", "failed", "blocked"}
    ):
        clean_exit = exit_record is not None and state.exit_code == 0
        complete_report = bool(
            report
            and not report_errors
            and report.get("status") == "complete"
        )
        if clean_exit and complete_report and not protected_errors:
            if state.adapter == "devin-cli" and not (
                state.provider_session_id or ""
            ).strip():
                state.status = "blocked"
                state.blocker = (
                    "Devin full-run cannot complete without a captured "
                    "provider session id"
                )
                state.next_action = "driver_wake_reconcile"
            else:
                state.status = "complete"
                state.completed_at = state.completed_at or _utc_now()
                state.next_action = "final_readiness"
                state.head = str(
                    report.get("final_head") or observed_head or state.start_head
                )
        elif clean_exit and not protected_errors and (
            not report or report.get("status") != "complete"
        ):
            # Missing or incomplete machine report is host-reconcilable.
            # A present complete report that failed kernel validation already
            # failed hard above via report_errors.
            state.status = "blocked"
            state.blocker = (
                "provider exited cleanly without a validated complete report; "
                "host may reconstruct independently provable fields"
            )
            state.next_action = "driver_wake_reconcile"
        elif clean_exit:
            state.status = "failed"
            state.blocker = "provider exited cleanly without a validated complete report"
            state.next_action = "driver_wake_error"
        elif alive:
            state.status = "healthy"
            state.next_action = "parked_monitor"
            hb = state.heartbeat_at or state.launched_at
            if hb:
                try:
                    hb_dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
                    if age > max(0, stale_after_seconds):
                        state.status = "stale"
                        state.next_action = "driver_wake_stale_heartbeat"
                except ValueError:
                    pass
        elif group_alive:
            state.status = "failed"
            state.blocker = "supervisor exited while its process group remains alive"
            state.next_action = "driver_wake_error"
        elif supervised_pids:
            state.status = "failed"
            state.blocker = "supervisor exited while recursively supervised descendants remain alive"
            state.next_action = "driver_wake_error"
        elif state.launched_at:
            state.status = "failed"
            state.blocker = "supervisor disappeared without a validated exit record"
            state.next_action = "driver_wake_error"
        elif last_type == "blocked":
            state.status = "blocked"
            state.next_action = "driver_wake_blocker"
        elif saw_run_complete_event:
            state.status = "failed"
            state.blocker = "run_complete event without validated complete report and exit"
            state.next_action = "driver_wake_error"
        else:
            # A genuinely prepared-but-not-launched session remains pending.
            state.status = "pending"
            state.next_action = "launch"

    # Planned checkpoints gate both an active run and a cleanly completed
    # provider. This closes the race where the worker emits a checkpoint and a
    # complete report before the driver's next poll. Error, blocker, stale, and
    # safety outcomes still outrank the checkpoint wake path.
    if (
        state.status in {"healthy", "complete"}
        and unacknowledged_high_risk_checkpoints
    ):
        pending = state.pending_high_risk_checkpoint
        if pending not in unacknowledged_high_risk_checkpoints:
            pending = unacknowledged_high_risk_checkpoints[0]
        state.pending_high_risk_checkpoint = pending
        state.next_action = "driver_wake_high_risk_checkpoint"
    elif state.status == "complete":
        state.pending_high_risk_checkpoint = None
        if (
            state.next_action == "driver_wake_high_risk_checkpoint"
            or initial_next_action == "driver_wake_high_risk_checkpoint"
        ):
            state.next_action = "final_readiness"
    elif state.status != "healthy":
        state.pending_high_risk_checkpoint = None

    # A worker-discovered material contract change is an explicit hand-back,
    # not ordinary progress. Keep the process/result intact and wake the driver
    # so the changed scope or assumption can be resolved before readiness.
    if state.status in {"healthy", "complete"} and observed_material_change:
        state.next_action = "driver_wake_material_scope_or_assumption_change"

    if exit_record is not None and state.fingerprint is not None:
        _retire_process_identity(
            state,
            reason="validated_provider_exit",
            evidence=exit_record,
        )
        identity_retired = True

    # Terminal states are monotonic across repeated monitor calls. A completed
    # run may still be demoted to failed by newly detected safety corruption,
    # but stopped/failed/blocked never regress to an active state.
    if initial_status in {"stopped", "failed", "blocked"}:
        state.status = initial_status
        state.next_action = initial_next_action
        state.blocker = initial_blocker
        state.completed_at = initial_completed_at
    elif initial_status == "complete" and state.status != "failed":
        state.status = "complete"
        if unacknowledged_high_risk_checkpoints:
            state.next_action = "driver_wake_high_risk_checkpoint"
        elif (
            initial_next_action == "driver_wake_high_risk_checkpoint"
            and acknowledge_high_risk_checkpoint is not None
        ):
            state.next_action = "final_readiness"
        else:
            state.next_action = initial_next_action or "final_readiness"
        state.completed_at = initial_completed_at or state.completed_at

    # Production finalization path: reconcile git + protected refs when complete.
    # Explicit fixture mode may use synthetic heads without mutating git.
    reconcile_payload: dict[str, Any] | None = None
    if (
        state.status == "complete"
        and state.next_action == "final_readiness"
        and state.adapter != "fixture"
    ):
        try:
            reconcile_payload = reconcile_full_run_with_git(
                repo_root, session_id=session_id
            )
        except ValidationIssue as issue:
            state.status = "failed"
            state.blocker = issue.message
            state.next_action = "driver_wake_error"
            reconcile_payload = {"ok": False, "error": issue.message}

    if state.blocker:
        state.blocker = _redact_full_run_text(
            state.blocker, exact_values=exact_secret_values
        )
    # Lazy on purpose: behavior_policy imports full_run at module level (real cycle).
    from .behavior_policy import (  # noqa: PLC0415
        PARKED_MONITOR_UPDATE_POLICY,
        PARKED_MONITOR_USER_HEARTBEAT_SECONDS,
        PARKED_MONITOR_WAKE_CONDITIONS,
        parked_monitor_poll_after_seconds,
    )

    material_state_change = bool(
        state.status != initial_status
        or state.next_action != initial_next_action
        or state.blocker != initial_blocker
        or state.completed_at != initial_completed_at
        or state.pending_high_risk_checkpoint != initial_pending_checkpoint
        or tuple(state.acknowledged_high_risk_checkpoints)
        != initial_acknowledged_checkpoints
    )
    unchanged_healthy_poll_silent = bool(
        state.status == "healthy"
        and state.next_action == "parked_monitor"
        and not material_state_change
    )
    # Healthy batch progress is silent; wakes and terminal transitions chat.
    chat_update_recommended = bool(
        material_state_change
        and not (
            state.status == "healthy" and state.next_action == "parked_monitor"
        )
    )
    state.monitor_cache = cache
    if include_remote_audit:
        cache["last_depth"] = "full"
    else:
        cache["last_depth"] = "incremental"
        cache["skipped_full_event_rescan"] = events_reused
        cache["skipped_deep_git_reconciliation"] = True
        cache["skipped_remote_all_ref_audit"] = True
    save_state(repo_root, state)

    status = {
        "ok": state.status in {"healthy", "complete", "pending"}
        or state.next_action == "driver_wake_reconcile",
        "session_id": session_id,
        "state": state.status,
        "batch": state.batch,
        "head": state.head or state.start_head,
        "branch": state.branch,
        "heartbeat_at": state.heartbeat_at,
        "pid": state.pid,
        "pgid": state.pgid,
        "next_action": state.next_action,
        "blocker": _driver_visible_blocker(state),
        "driver_contract": "parked_monitor",
        "driver_monitor_mode": "parked_monitor",
        "poll_after_seconds": parked_monitor_poll_after_seconds(stale_after_seconds),
        "user_heartbeat_seconds": PARKED_MONITOR_USER_HEARTBEAT_SECONDS,
        "chat_update_policy": PARKED_MONITOR_UPDATE_POLICY,
        "chat_update_recommended": chat_update_recommended,
        "unchanged_healthy_poll_silent": unchanged_healthy_poll_silent,
        "material_transition": material_state_change
        or state.next_action != "parked_monitor"
        or state.status != "healthy",
        "monitor_depth": resolved_depth,
        "remote_all_ref_audit": include_remote_audit,
        "goal_launch_mode": state.goal_launch_mode,
        "report_provenance": state.report_provenance,
        "wake_conditions": sorted(PARKED_MONITOR_WAKE_CONDITIONS),
        "planned_high_risk_checkpoints": list(
            state.planned_high_risk_checkpoints
        ),
        "pending_high_risk_checkpoint": state.pending_high_risk_checkpoint,
        "acknowledged_high_risk_checkpoints": list(
            state.acknowledged_high_risk_checkpoints
        ),
        "check_summary": {
            "events": event_count,
            "events_reused": events_reused,
            "last_event_type": last_type,
            "alive": alive,
            "group_alive": group_alive,
            "fingerprint_reason": fp_reason,
            "report_status": report.get("status") if report else None,
            "event_errors": len(event_errors),
            "report_errors": len(report_errors),
            "exit_record_errors": len(exit_record_errors),
            "observed_branch": observed_branch,
            "exit_code": state.exit_code,
            "exit_record": bool(exit_record),
            "high_risk_checkpoints_observed": len(
                observed_high_risk_checkpoints
            ),
            "last_batch_confidence": last_batch_confidence,
            "last_batch_unsure_about": (
                list(last_batch_unsure_about)
                if last_batch_unsure_about is not None
                else None
            ),
            "last_batch_unsure_about_count": last_batch_unsure_about_count,
            "reconcile_ok": (
                None if reconcile_payload is None else bool(reconcile_payload.get("ok"))
            ),
        },
        "report_path": str(report_path),
        "events_path": str(root / "events.jsonl"),
        "transcript_private": True,
        "adapter": state.adapter,
        "fingerprint_ok": fp_ok,
        "review_context": (
            reconcile_payload.get("review_context")
            if reconcile_payload is not None and reconcile_payload.get("ok")
            else None
        ),
        "merge_authority": False,
    }
    assert "transcript" not in status
    assert "stdout" not in status
    assert set(status) <= STATUS_KEYS | {"ok"}
    _redact_full_run_mapping_in_place(status, exact_values=exact_secret_values)
    return status




def await_full_run(
    repo_root: Path,
    *,
    session_id: str,
    stale_after_seconds: int = DEFAULT_STALE_SECONDS,
    timeout_seconds: float | None = None,
    sleep_fn=None,
    monotonic_fn=None,
    acknowledge_high_risk_checkpoint: str | None = None,
    follow: bool = True,
    quiet: bool = False,
    stream_writer=None,
) -> dict[str, Any]:
    """Block until a material monitor transition (or timeout).

    By default follows a sanitized human-readable worker stream (no model
    inference; replaces timed driver chat updates). Pass ``quiet=True`` or
    ``follow=False`` to opt out of stream emission while still parking.

    Returns the first monitor payload that is not an unchanged healthy park.
    Designed for one host tool call instead of model-turn polling.
    """
    # Do not rebind helpers here: unit tests patch this module's load_state /
    # _all_follow_events / monitor_full_run. monitor_full_run refreshes from
    # full_run for its own production path.
    import time as _time  # noqa: PLC0415

    sleep = sleep_fn or _time.sleep
    mono = monotonic_fn or _time.monotonic
    started = mono()
    follow_enabled = bool(follow) and not bool(quiet)
    seen_events = 0
    grok_transcript_cursor = GrokTranscriptCursor()
    grok_redaction_state = GrokStreamingRedactionState()
    seen_attempt: int | None = None
    stream_lines: list[str] = []
    write = stream_writer
    while True:
        # Call the local monitor by name so public API snapshot AST inspection
        # can resolve the output shape. Unit tests that need a double should
        # patch cobbler_runtime.full_run_monitor.monitor_full_run.
        observed = monitor_full_run(
            repo_root,
            session_id=session_id,
            stale_after_seconds=stale_after_seconds,
            acknowledge_high_risk_checkpoint=acknowledge_high_risk_checkpoint,
        )
        if follow_enabled:
            try:
                state = load_state(repo_root, session_id)
                shared_oauth = state.grok_auth_strategy == "oauth_shared_file"
                if seen_attempt != state.attempt:
                    # A supervised resume archives and resets events.jsonl.
                    seen_events = 0
                    grok_transcript_cursor = GrokTranscriptCursor()
                    grok_redaction_state = GrokStreamingRedactionState()
                    seen_attempt = state.attempt
                events_tail = _all_follow_events(Path(repo_root), state)
                if not events_tail:
                    # Fixture/direct monitor callers may already provide a
                    # validated projection without a staged launch-evidence
                    # context. Preserve that supported path; production uses
                    # the complete absolute sequence above.
                    events_tail = observed.get("events_tail") or observed.get("events") or []
                new_lines, seen_events = follow_stream_lines(
                    events_tail if isinstance(events_tail, list) else [],
                    shared_oauth=shared_oauth,
                    already_seen=seen_events,
                )
                for line in new_lines:
                    stream_lines.append(line)
                    if write is not None:
                        write(line)
                if state.adapter == "grok-build":
                    launch_context_verified, exact_secret_values = (
                        _launch_evidence_context(state)
                    )
                    if not launch_context_verified:
                        raise ValidationIssue(
                            "grok_follow_redaction_context_unverified",
                            "Grok follow cannot verify persisted launch redaction evidence",
                        )
                    transcript_lines, grok_transcript_cursor = (
                        _read_grok_transcript_records(
                            Path(repo_root),
                            full_run_root(Path(repo_root), state.session_id)
                            / "transcript.log",
                            grok_transcript_cursor,
                        )
                    )
                    grok_lines, _decoded_count = grok_streaming_follow_lines(
                        transcript_lines,
                        shared_oauth=shared_oauth,
                        exact_values=tuple(exact_secret_values),
                        expected_session_id=state.session_id,
                        credential_grant_state=state,
                        redaction_state=grok_redaction_state,
                    )
                    for line in grok_lines:
                        stream_lines.append(line)
                        if write is not None:
                            write(line)
            except ValidationIssue as issue:
                if issue.code.startswith("grok_follow_") or issue.code.startswith(
                    "grok_stream_"
                ):
                    result = dict(observed)
                    result.update(
                        {
                            "ok": False,
                            "state": "failed",
                            "material_transition": True,
                            "unchanged_healthy_poll_silent": False,
                            "next_action": "driver_wake_safety_tripwire",
                            "blocker": f"Grok follow safety check failed ({issue.code})",
                            "awaited": True,
                            "follow": follow_enabled,
                            "follow_model_inference": FOLLOW_MODE_MODEL_INFERENCE,
                            "follow_replaces_timed_chat": FOLLOW_MODE_REPLACES_TIMED_CHAT,
                            "follow_stream_lines": list(stream_lines),
                            "merge_authority": False,
                        }
                    )
                    return result
            except Exception:  # noqa: BLE001 — non-security display remains best-effort
                pass
        material = bool(
            observed.get("material_transition")
            or not observed.get("unchanged_healthy_poll_silent")
        )
        if material:
            result = dict(observed)
            result["awaited"] = True
            result["follow"] = follow_enabled
            result["follow_model_inference"] = FOLLOW_MODE_MODEL_INFERENCE
            result["follow_replaces_timed_chat"] = FOLLOW_MODE_REPLACES_TIMED_CHAT
            result["follow_stream_lines"] = list(stream_lines)
            result["merge_authority"] = False
            return result
        elapsed = mono() - started
        if timeout_seconds is not None and elapsed >= max(0.0, timeout_seconds):
            result = dict(observed)
            result["awaited"] = True
            result["await_timed_out"] = True
            result["follow"] = follow_enabled
            result["follow_model_inference"] = FOLLOW_MODE_MODEL_INFERENCE
            result["follow_replaces_timed_chat"] = FOLLOW_MODE_REPLACES_TIMED_CHAT
            result["follow_stream_lines"] = list(stream_lines)
            result["merge_authority"] = False
            return result
        delay = float(observed.get("poll_after_seconds") or 60)
        if timeout_seconds is not None:
            delay = min(delay, max(0.0, float(timeout_seconds) - elapsed))
        sleep(delay)
