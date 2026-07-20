#!/usr/bin/env python3
"""Thin operator CLI for Cobbler external-agent configuration.

Commands:
  validate-config [--json]   Resolve config with provenance; no model calls
  doctor [--json]            Read-only inventory of adapters/capabilities/sessions
  council [--json]           Parallel read-only council fan-out (host synthesis)
  lightweight-review [--json]
                             Single bounded utility review (not a council vote)
  session list|probe|resume  Exact persistent session registry helpers
  worker prepare|audit|export|refresh
                             Single external writer lease lifecycle (host-owned)
  implement full-run-prepare|full-run-launch|full-run-monitor|full-run-await|full-run-reconcile|full-run-logs|full-run-stop
                             Trusted persistent external full-run supervisor
  implement prepare|launch|gate|resume-batch|status
                             Legacy bounded external batch implementer
  implement rollback-ref    Host-owned run/session-scoped safety ref
  setup [--json]             Inventory tools and write local .elves/models.toml
  onboard plan|show|apply|probe
                             Model onboarding: interview packet, update routes, probe

This entry point stays thin; implementation lives under scripts/cobbler_runtime/.
"""

from __future__ import annotations

import argparse
from functools import partial
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cobbler_runtime.adapters import (  # noqa: E402
    build_session_resume_invocation,
    build_write_resume_invocation,
    grok_write_profile,
    registry_snapshot,
    workspace_sandbox_write_profile,
)
from cobbler_runtime.acceptance import normalize_batch_id  # noqa: E402
from cobbler_runtime.parallel_lanes import (  # noqa: E402
    DECLINE_NO_LANES,
    DECLINE_PARTITION_INVALID,
    DECLINE_PREFERENCE_OFF,
    LANES_TIMINGS_MAX_BYTES,
    load_lanes_from_plan,
    validate_lane_partition,
    width_test,
)
from cobbler_runtime.audit import (  # noqa: E402
    audit_lease_turn,
    build_audit_evidence,
    build_worker_pre_snapshot,
    build_worker_credential_grant_context,
    export_binary_patches,
    host_apply_check,
    host_import_patches,
    normalize_worker_credential_grant_names,
    validate_worker_pre_snapshot,
    verify_patch_manifest,
    verify_worker_credential_grant_context,
    worker_credential_grant_context_digest,
)
from cobbler_runtime.capabilities import (  # noqa: E402
    doctor_inventory,
    summarize_capabilities,
)
from cobbler_runtime.config import (  # noqa: E402
    lanes_from_resolved,
    models_toml_is_local_only,
    resolve_from_repo,
)
from cobbler_runtime.dispatch import (  # noqa: E402
    LaneSpec,
    run_council_sync,
    run_lightweight_review_sync,
)
from cobbler_runtime.context import (  # noqa: E402
    collect_secret_env_values,
    redact_structure,
    redact_text,
)
from cobbler_runtime.leases import (  # noqa: E402
    LIVE_LEASE_STATES,
    LeaseStore,
    build_write_task_packet,
)
from cobbler_runtime.host_profiles import resolve_host_profile  # noqa: E402
from cobbler_runtime.schema import ValidationIssue  # noqa: E402
from cobbler_runtime.sessions import SessionRegistry  # noqa: E402
from cobbler_runtime.implement import (  # noqa: E402
    launch_payload,
    prepare_implement,
    resume_batch_payload,
    run_gate,
    status_payload,
)
from cobbler_runtime.full_run import (  # noqa: E402
    _assert_bounded_json_structure,
    _loads_bounded_json,
    launch_full_run,
    logs_full_run,
    monitor_full_run,
    await_full_run,
    reconstruct_missing_report,
    prepare_full_run,
    stop_full_run,
)
from cobbler_runtime.delegated_git import create_rollback_ref  # noqa: E402
from cobbler_runtime.setup import (  # noqa: E402
    preferences_from_flags,
    run_setup,
)
from cobbler_runtime.onboard import (  # noqa: E402
    apply_onboarding,
    build_onboarding_packet,
    probe_routes,
    show_onboarding,
)
from cobbler_runtime.storage import (  # noqa: E402
    StorageError,
    atomic_write_json,
    read_repo_regular_bytes,
)
from cobbler_runtime.preferences import (  # noqa: E402
    preference_snapshot,
    reset_preferences,
    set_preference,
)
from cobbler_runtime.worker_routing import (  # noqa: E402
    GrokCapabilities,
    decide_worker_route,
    discover_repository_worker_policy,
    probe_grok_capabilities,
)
from cobbler_runtime.prewalk import (  # noqa: E402
    fixture_prewalk_capabilities,
    load_grok_prewalk_qualification,
    probe_installed_prewalk_capabilities,
)
from cobbler_runtime.native_worker import (  # noqa: E402
    build_native_worker_prewalk_spec,
    build_native_worker_spec,
    follow_native_worker,
    launch_native_worker,
    native_worker_status,
    native_worker_profiles,
    supervise_native_worker,
)


def _nonnegative_batch_arg(value: str) -> int:
    batch = normalize_batch_id(value)
    if batch is None:
        raise argparse.ArgumentTypeError(
            "batch must be B0, B1+, or an unambiguous non-negative integer"
        )
    return batch


WORKER_SNAPSHOT_MAX_BYTES = 4 * 1024 * 1024


def _redacted_storage_issue(error: StorageError) -> dict[str, Any]:
    message = redact_text(
        error.message,
        exact_values=collect_secret_env_values(),
    ).text
    return {
        "code": f"storage_{error.code}",
        "message": message,
        "category": "storage",
    }


def _emit_storage_error(
    args: argparse.Namespace,
    error: StorageError,
    *,
    command: str,
) -> int:
    issue = _redacted_storage_issue(error)
    payload = {
        "ok": False,
        "issues": [issue],
        "mutated_repo": False,
        "model_calls_made": False,
    }
    if getattr(args, "json", False):
        return _emit_json(payload, exit_code=1)
    print(
        f"{command}: FAILED [{issue['code']}] {issue['message']}",
        file=sys.stderr,
    )
    return 1


def _read_worker_snapshot(repo_root: Path, path: Path) -> dict[str, Any]:
    """Read one bounded store snapshot without following links."""
    raw = read_repo_regular_bytes(
        repo_root,
        path,
        max_bytes=WORKER_SNAPSHOT_MAX_BYTES,
    )
    try:
        payload = _loads_bounded_json(
            raw.decode("utf-8"),
            label="worker snapshot",
        )
        _assert_bounded_json_structure(payload, label="worker_snapshot")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError, StorageError) as exc:
        raise StorageError(
            "malformed_json",
            f"Worker snapshot at {path} exceeds canonical JSON resource limits or is malformed",
        ) from exc
    if not isinstance(payload, dict):
        raise StorageError(
            "malformed_json",
            f"Worker snapshot must be a JSON object: {path}",
        )
    return payload


def _write_worker_snapshot(
    repo_root: Path,
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Atomically publish one repo-anchored worker snapshot."""
    atomic_write_json(path, payload, repo_root=repo_root)


def _repo_root_from_args(args: argparse.Namespace) -> Path:
    if args.repo_root:
        return Path(args.repo_root).expanduser().resolve()
    return Path.cwd().resolve()


def _emit_json(
    payload: dict[str, Any],
    *,
    exit_code: int,
    exact_secret_values: frozenset[str] | None = None,
) -> int:
    safe = redact_structure(
        payload,
        exact_values=(
            exact_secret_values
            if exact_secret_values is not None
            else collect_secret_env_values()
        ),
    )
    json.dump(safe, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return exit_code


def _redacted_validation_issue(issue: ValidationIssue) -> dict[str, Any]:
    payload = redact_structure(
        issue.to_dict(),
        exact_values=collect_secret_env_values(),
    )
    return dict(payload) if isinstance(payload, dict) else issue.to_dict()


def _reject_live_worker_lease(
    store: LeaseStore,
    lease_id: str,
    reason: object,
) -> None:
    """Best-effort terminalization after a partially published worker transition."""
    safe_reason = redact_text(
        str(reason),
        exact_values=collect_secret_env_values(),
    ).text
    try:
        lease = store.get(lease_id)
        if lease.state in LIVE_LEASE_STATES:
            store.reject(lease_id, safe_reason or "worker lifecycle transition failed")
    except Exception:
        # Preserve the primary exception. A secondary storage failure is surfaced
        # by subsequent strict store reads and must not replace the root cause.
        pass


def _emit_text_validate(payload: dict[str, Any]) -> int:
    if payload["ok"]:
        print("validate-config: OK")
        for role, route in sorted(payload["roles"].items()):
            print(
                f"  {role}: profile={route['profile']} "
                f"source={route['source']} required={route['required']}"
            )
        for warning in payload.get("warnings") or []:
            print(f"warning: {warning}")
        return 0
    print("validate-config: FAILED", file=sys.stderr)
    for issue in payload.get("issues") or []:
        path = f" ({issue['path']})" if issue.get("path") else ""
        print(f"  [{issue['code']}]{path} {issue['message']}", file=sys.stderr)
        if issue.get("hint"):
            print(f"    hint: {issue['hint']}", file=sys.stderr)
    return 1


def cmd_validate_config(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from_args(args)
    try:
        resolved = resolve_from_repo(repo_root)
    except ValidationIssue as issue:
        payload = {
            "ok": False,
            "issues": [issue.to_dict()],
            "warnings": [],
            "roles": {},
            "profiles": {},
            "sources_consulted": [],
            "mutated_repo": False,
            "model_calls_made": False,
            "repo_root": str(repo_root),
        }
        if args.json:
            return _emit_json(payload, exit_code=1)
        return _emit_text_validate(payload)

    payload = resolved.to_dict()
    payload["mutated_repo"] = False
    payload["model_calls_made"] = False
    payload["repo_root"] = str(repo_root)
    payload["local_models_toml"] = models_toml_is_local_only(repo_root)
    if args.json:
        return _emit_json(payload, exit_code=0 if resolved.ok else 1)
    return _emit_text_validate(payload)


def _emit_lanes_payload(args: argparse.Namespace, payload: dict[str, Any], *, exit_code: int) -> int:
    payload.setdefault("mutated_repo", False)
    payload.setdefault("model_calls_made", False)
    if getattr(args, "json", False):
        return _emit_json(payload, exit_code=exit_code)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return exit_code


def _load_lane_timings(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValidationIssue(
            "parallel_lanes_timings_invalid",
            "Timings file must be a regular non-symlink file",
            path=str(path),
        )
    if path.stat().st_size > LANES_TIMINGS_MAX_BYTES:
        raise ValidationIssue(
            "parallel_lanes_timings_invalid",
            "Timings file exceeds the bounded read size",
            path=str(path),
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationIssue(
            "parallel_lanes_timings_invalid",
            f"Timings file is not valid bounded JSON: {exc}",
            path=str(path),
        ) from exc
    if not isinstance(data, dict):
        raise ValidationIssue(
            "parallel_lanes_timings_invalid",
            "Timings file must be a JSON object",
            path=str(path),
        )
    for key in ("worker_seconds", "driver_seconds"):
        value = data.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValidationIssue(
                "parallel_lanes_timings_invalid",
                f"Timings key `{key}` must be numeric",
                path=str(path),
            )
        # Reject non-finite (NaN/Infinity), negative, and float-overflowing
        # huge-int values so the width test never sees garbage timings.
        try:
            finite = math.isfinite(float(value))
        except (OverflowError, TypeError, ValueError):
            finite = False
        if not finite or value < 0:
            raise ValidationIssue(
                "parallel_lanes_timings_invalid",
                f"Timings key `{key}` must be a finite non-negative number",
                path=str(path),
            )
    return data


def cmd_lanes(args: argparse.Namespace) -> int:
    """Read-only lane validation and width-test recommendation; never launches."""

    if not getattr(args, "plan", None):
        payload = {
            "ok": False,
            "issues": [
                {
                    "code": "missing_required_argument",
                    "message": "`--plan` is required",
                    "path": "--plan",
                }
            ],
        }
        return _emit_lanes_payload(args, payload, exit_code=1)

    plan_path = Path(args.plan)
    action = args.lanes_action

    parallel_preference = None
    if action == "plan":
        try:
            parallel_preference = (
                preference_snapshot().values.get("worker", {}).get("parallel", "off")
            )
        except ValidationIssue as issue:
            payload = {"ok": False, "issues": [issue.to_dict()]}
            return _emit_lanes_payload(args, payload, exit_code=1)

    try:
        declaration = load_lanes_from_plan(plan_path)
    except ValidationIssue as issue:
        if action == "plan" and issue.code == "parallel_lanes_missing":
            payload = {
                "ok": True,
                "parallel": False,
                "lanes": [],
                "declined": [DECLINE_NO_LANES],
                "issues": [],
                "parallel_preference": parallel_preference,
            }
            return _emit_lanes_payload(args, payload, exit_code=0)
        payload = {"ok": False, "issues": [issue.to_dict()]}
        return _emit_lanes_payload(args, payload, exit_code=1)

    lanes = declaration["lanes"]
    issues = validate_lane_partition(lanes)

    if action == "validate":
        payload = {
            "ok": not issues,
            "issues": [issue.to_dict() for issue in issues],
            "trunk": declaration["trunk"],
            "lanes": [lane["id"] for lane in lanes],
        }
        return _emit_lanes_payload(args, payload, exit_code=0 if not issues else 1)

    timings = None
    if getattr(args, "timings", None):
        try:
            timings = _load_lane_timings(Path(args.timings))
        except ValidationIssue as issue:
            payload = {"ok": False, "issues": [issue.to_dict()]}
            return _emit_lanes_payload(args, payload, exit_code=1)

    if issues:
        payload = {
            "ok": True,
            "parallel": False,
            "lanes": [lane["id"] for lane in lanes],
            "declined": [DECLINE_PARTITION_INVALID],
            "issues": [issue.to_dict() for issue in issues],
            "parallel_preference": parallel_preference,
        }
        return _emit_lanes_payload(args, payload, exit_code=0)

    decision = width_test(
        lanes,
        timings=timings,
        risk=args.risk,
    )
    if parallel_preference != "auto":
        decision["parallel"] = False
        decision["declined"].append(DECLINE_PREFERENCE_OFF)
    payload = {
        "ok": True,
        "issues": [],
        "parallel_preference": parallel_preference,
        **decision,
    }
    return _emit_lanes_payload(args, payload, exit_code=0)


def cmd_preferences(args: argparse.Namespace) -> int:
    """Show or safely change the shared XDG preference file."""
    try:
        if args.preferences_action == "show":
            snapshot = preference_snapshot()
        elif args.preferences_action == "set":
            set_preference(args.preference, args.value)
            snapshot = preference_snapshot()
        else:
            reset_preferences()
            snapshot = preference_snapshot()
    except ValidationIssue as issue:
        payload = {"ok": False, "issues": [issue.to_dict()], "model_calls_made": False}
        if args.json:
            return _emit_json(payload, exit_code=1)
        print(f"preferences: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
        return 1
    payload = {
        "ok": True,
        "path": snapshot.path,
        "exists": snapshot.exists,
        "schema_version": snapshot.schema_version,
        "values": snapshot.values,
        "authority_fields_supported": False,
        "model_calls_made": False,
    }
    if args.json:
        return _emit_json(payload, exit_code=0)
    print(f"preferences: {snapshot.path}")
    sys.stdout.write(json.dumps(snapshot.values, indent=2, sort_keys=True) + "\n")
    return 0


def cmd_route_worker(args: argparse.Namespace) -> int:
    """Explain a model-free worker recommendation."""
    if args.grok_goal_behavioral_evidence and not args.probe_grok:
        issue = ValidationIssue(
            "grok_goal_canary_probe_required",
            "Goal canary artifacts can be qualified only against the installed Grok binary",
            path="grok_goal_behavioral_evidence",
            hint="Pass --probe-grok with the bounded JSON canary artifact path",
        )
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    try:
        preference_state = preference_snapshot()
    except ValidationIssue as issue:
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    preferences = preference_state.values if preference_state.exists else {}
    explicit: dict[str, Any] = {"worker": {}}
    if args.provider:
        explicit["worker"]["provider"] = args.provider
    if args.effort:
        explicit["worker"]["native_effort"] = args.effort
    if args.prewalk:
        explicit["worker"]["prewalk"] = args.prewalk
    if args.guide_effort:
        explicit["worker"]["prewalk_guide_effort"] = args.guide_effort
    if args.guide_model:
        explicit["worker"]["prewalk_guide_model"] = args.guide_model
    if args.allow_grok:
        explicit["worker"]["allow_grok"] = True
    if args.grok_worker_model:
        explicit["worker"]["grok_model"] = args.grok_worker_model
    repo_root = Path(args.repo_root or ".").resolve()
    try:
        repo_policy, repo_policy_source = discover_repository_worker_policy(
            repo_root, override_path=Path(args.repo_policy).resolve() if args.repo_policy else None
        )
    except ValidationIssue as issue:
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    if args.prohibit_grok:
        repo_policy.setdefault("worker", {})["allow_grok"] = False
        repo_policy_source = "explicit_cli_veto"
    default_grok_auth = Path(
        os.environ.get("GROK_AUTH_PATH") or (Path.home() / ".grok" / "auth.json")
    )
    grok = (
        probe_grok_capabilities(
            args.grok_executable,
            goal_auth_path=default_grok_auth if default_grok_auth.is_file() else None,
            goal_behavioral_evidence=args.grok_goal_behavioral_evidence,
        )
        if args.probe_grok
        else GrokCapabilities(
            installed=args.grok_installed,
            authenticated=args.grok_authenticated,
            models=tuple(args.grok_model or ()),
            default_model=args.grok_default_model,
            goal_entrypoint_advertised=args.grok_goal_advertised,
            goal_mode_behaviorally_verified=False,
            goal_behavioral_evidence=None,
            version=args.grok_version,
        )
    )
    if args.prewalk_capability_evidence and not args.probe_prewalk:
        issue = ValidationIssue(
            "prewalk_capability_unavailable",
            "Behavioral prewalk evidence requires the installed help/version probe",
            path="prewalk_capability_evidence",
        )
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    try:
        prewalk_caps = (
            probe_installed_prewalk_capabilities(
                args.host,
                behavioral_evidence=(
                    Path(args.prewalk_capability_evidence)
                    if args.prewalk_capability_evidence
                    else None
                ),
            )
            if args.probe_prewalk
            else None
        )
    except ValidationIssue as issue:
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    grok_prewalk_qualification = None
    if args.grok_prewalk_qualification:
        # Qualification is meaningful only when the artifact is bound to the
        # exact installed binary observed in this routing decision. Facts
        # asserted by the artifact itself are not an installed-version proof.
        if not args.probe_grok:
            issue = ValidationIssue(
                "prewalk_capability_unavailable",
                "Grok prewalk qualification requires --probe-grok to bind the artifact to the installed binary",
                path="grok_prewalk_qualification",
            )
            return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
        if not grok.version or not grok.installed_build_commit:
            issue = ValidationIssue(
                "prewalk_capability_unavailable",
                "Installed Grok version and build commit are required to validate prewalk qualification",
                path="grok_prewalk_qualification",
            )
            return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
        try:
            grok_prewalk_qualification = load_grok_prewalk_qualification(
                Path(args.grok_prewalk_qualification),
                installed_version=grok.version,
                installed_build_commit=grok.installed_build_commit,
            )
        except ValidationIssue as issue:
            return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    try:
        decision = decide_worker_route(
            host=args.host,
            execution_reasoning=args.execution_reasoning,
            review_risk=args.review_risk,
            global_preferences=preferences,
            explicit_intent=explicit,
            repo_policy=repo_policy,
            grok=grok,
            driver_effort=args.driver_effort,
            prewalk_capabilities=prewalk_caps,
            grok_prewalk_qualification=grok_prewalk_qualification,
        )
    except ValidationIssue as issue:
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    payload = {
        "ok": True,
        "decision": decision.to_dict(),
        "preferences_path": preference_state.path,
        "repository_policy_source": repo_policy_source,
        "grok_capabilities": grok.safe_snapshot(),
        "prewalk_capabilities": prewalk_caps.to_dict() if prewalk_caps else None,
        "grok_prewalk_qualification": (
            grok_prewalk_qualification.to_dict()
            if grok_prewalk_qualification
            else None
        ),
    }
    if args.json:
        return _emit_json(payload, exit_code=0)
    print(
        f"worker route: provider={decision.provider} transport={decision.worker_transport} "
        f"effort={decision.worker_effort} model={decision.worker_model or decision.worker_model_policy}"
    )
    if decision.fallback:
        print(f"fallback: {decision.fallback['reason']}")
    return 0


def cmd_native_worker(args: argparse.Namespace) -> int:
    action = args.native_worker_action or "spec"
    repo_root = Path(args.repo_root or ".").resolve()
    action_required = {
        "follow": ("run_id",),
        "status": ("run_id",),
        "_supervise": ("run_id", "packet"),
    }
    action_missing = [name for name in action_required.get(action, ()) if not getattr(args, name)]
    if action_missing:
        issue = ValidationIssue("native_worker_arguments_required", f"Missing native worker arguments: {', '.join(action_missing)}")
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    if action == "follow":
        try:
            state = follow_native_worker(repo_root, args.run_id, wait=not args.no_wait)
        except ValidationIssue as issue:
            return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
        return 0 if state.get("status") != "failed" else 1
    if action == "status":
        try:
            state = native_worker_status(repo_root, args.run_id)
        except ValidationIssue as issue:
            return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
        if args.json:
            return _emit_json({"ok": True, "worker": state}, exit_code=0)
        print(state["status"])
        return 0
    if action == "prewalk-capabilities":
        if not args.host or args.host == "fixture":
            issue = ValidationIssue(
                "native_worker_arguments_required",
                "prewalk-capabilities requires --host codex, claude, or grok",
            )
            return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
        try:
            capabilities = probe_installed_prewalk_capabilities(
                args.host,
                behavioral_evidence=(
                    Path(args.prewalk_capability_evidence)
                    if args.prewalk_capability_evidence
                    else None
                ),
            )
        except ValidationIssue as issue:
            return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
        payload = {
            "ok": True,
            "prewalk_capabilities": capabilities.to_dict(),
            "model_calls_made": False,
        }
        if args.json:
            return _emit_json(payload, exit_code=0)
        print(
            f"{capabilities.host}: qualified={str(capabilities.qualified()).lower()} "
            f"fidelity={capabilities.instruction_fidelity}"
        )
        return 0
    if action == "_supervise":
        return supervise_native_worker(repo_root=repo_root, run_id=args.run_id, packet=Path(args.packet))
    if action == "launch" and args.host:
        # Feature-gated hosts (registry launch_ready=False) exist for spec and
        # prewalk-capabilities only. Qualification evidence describes transport
        # behavior but does not itself open a launch gate. A missing --host
        # falls through to the required-arguments envelope below.
        launch_profile = resolve_host_profile(args.host)
        if not launch_profile.launch_ready:
            issue = ValidationIssue(
                f"{launch_profile.capability_host}_native_worker_launch_unqualified",
                f"{launch_profile.capability_host} native-worker launch is feature-gated off; qualification evidence alone does not authorize launch",
            )
            return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    prewalk_requested = (args.prewalk or "off") != "off"
    execution_effort = args.execution_effort or args.effort
    execution_model = args.execution_model or args.model
    if args.execution_effort and args.effort and args.execution_effort != args.effort:
        issue = ValidationIssue(
            "ambiguous_prewalk_execution_route",
            "--effort and --execution-effort disagree",
        )
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    if args.execution_model and args.model and args.execution_model != args.model:
        issue = ValidationIssue(
            "ambiguous_prewalk_execution_route",
            "--model and --execution-model disagree",
        )
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    required_names = ["host", "worktree"]
    if prewalk_requested:
        required_names.extend(("guide_effort", "guide_model"))
        if not execution_effort:
            required_names.append("execution_effort")
        if not execution_model:
            required_names.append("execution_model")
    else:
        required_names.extend(("effort", "model"))
    missing = [name for name in required_names if not getattr(args, name, None) and not (
        name == "execution_effort" and execution_effort
    ) and not (name == "execution_model" and execution_model)]
    if action == "launch" and (not args.run_id or not args.packet):
        missing.extend(name for name in ("run_id", "packet") if not getattr(args, name))
    if missing:
        issue = ValidationIssue("native_worker_arguments_required", f"Missing native worker arguments: {', '.join(missing)}")
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    watcher = None
    visibility_mode = "native_host_agent_view" if args.host_view_visible else "commit_only"
    if action == "launch":
        import shlex
        watcher = shlex.join([sys.executable, str(Path(__file__).resolve()), "native-worker", "follow", "--repo-root", str(repo_root), "--run-id", args.run_id])
        visibility_mode = "follow_log"
    prewalk_spec = None
    prewalk_fallback = None
    try:
        if prewalk_requested:
            capabilities = (
                fixture_prewalk_capabilities()
                if args.host == "fixture"
                else probe_installed_prewalk_capabilities(
                    args.host,
                    behavioral_evidence=(
                        Path(args.prewalk_capability_evidence)
                        if args.prewalk_capability_evidence
                        else None
                    ),
                )
            )
            if capabilities.qualified():
                prewalk_spec = build_native_worker_prewalk_spec(
                    host=args.host,
                    worktree=Path(args.worktree),
                    guide_effort=args.guide_effort,
                    execution_effort=execution_effort,
                    guide_model=args.guide_model,
                    execution_model=execution_model,
                    capabilities=capabilities,
                    requested_mode=args.prewalk,
                    todo_limit=args.todo_limit,
                    visibility_mode=visibility_mode,
                    watcher_command=watcher,
                    guide_fixture_script=(
                        Path(args.fixture_script) if args.fixture_script else None
                    ),
                    execution_fixture_script=(
                        Path(args.execution_fixture_script)
                        if args.execution_fixture_script
                        else None
                    ),
                    forbidden_paths=tuple(args.forbidden_path or ()),
                )
                spec = prewalk_spec.guide
            elif args.prewalk == "auto":
                prewalk_fallback = capabilities.unavailable_reason() or "prewalk_capability_unavailable"
                spec = build_native_worker_spec(
                    host=args.host,
                    worktree=Path(args.worktree),
                    effort=execution_effort,
                    requested_model=execution_model,
                    session_id=args.session_id,
                    visibility_mode=visibility_mode,
                    watcher_command=watcher,
                    fixture_script=Path(args.fixture_script) if args.fixture_script else None,
                )
            else:
                raise ValidationIssue(
                    capabilities.unavailable_reason() or "prewalk_capability_unavailable",
                    "Required prewalk is unavailable before launch",
                )
        else:
            spec = build_native_worker_spec(
                host=args.host,
                worktree=Path(args.worktree),
                effort=args.effort,
                requested_model=args.model,
                session_id=args.session_id,
                visibility_mode=visibility_mode,
                watcher_command=watcher,
                fixture_script=Path(args.fixture_script) if args.fixture_script else None,
            )
    except ValidationIssue as issue:
        return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
    if action == "launch":
        try:
            state = launch_native_worker(
                repo_root=repo_root,
                run_id=args.run_id,
                spec=spec,
                packet=Path(args.packet),
                cli_path=Path(__file__),
                prewalk_spec=prewalk_spec,
            )
        except (OSError, ValidationIssue) as issue:
            if isinstance(issue, ValidationIssue):
                return _emit_json({"ok": False, "issues": [issue.to_dict()]}, exit_code=1)
            return _emit_json({"ok": False, "issues": [{"code": "native_worker_launch_failed", "message": str(issue)}]}, exit_code=1)
        payload = {
            "ok": True,
            "worker": state,
            "prewalk": {
                "requested": args.prewalk,
                "actual": "exact_session" if prewalk_spec else "off",
                "fallback_reason": prewalk_fallback,
            },
            "model_calls_made": args.host != "fixture",
        }
    else:
        payload = {
            "ok": True,
            "worker": prewalk_spec.to_dict() if prewalk_spec else spec.to_dict(),
            "profiles": native_worker_profiles(),
            "prewalk": {
                "requested": args.prewalk,
                "actual": "exact_session" if prewalk_spec else "off",
                "fallback_reason": prewalk_fallback,
            },
            "model_calls_made": False,
        }
    if args.json:
        return _emit_json(payload, exit_code=0)
    if action == "launch":
        print(payload["worker"]["watcher_command"])
    else:
        sys.stdout.write(" ".join(prewalk_spec.guide.argv if prewalk_spec else spec.argv) + "\n")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Read-only inventory. Never launches paid model turns."""
    repo_root = _repo_root_from_args(args)
    resolved = resolve_from_repo(repo_root)
    inventory = doctor_inventory(resolved.profiles)
    try:
        registry = SessionRegistry.open_readonly(repo_root)
    except StorageError as error:
        return _emit_storage_error(args, error, command="doctor")
    session_issue: dict[str, Any] | None = None
    try:
        sessions = [rec.to_dict() for rec in registry.list_sessions_strict()]
    except ValidationIssue as issue:
        sessions = []
        session_issue = _redacted_validation_issue(issue)
    issues = [
        _redacted_validation_issue(issue) for issue in resolved.issues
    ]
    if session_issue is not None:
        issues.append(session_issue)
    doctor_ok = resolved.ok and session_issue is None
    payload: dict[str, Any] = {
        "ok": doctor_ok,
        "repo_root": str(repo_root),
        "model_calls_made": False,
        "mutated_repo": False,
        "read_only": True,
        "adapters": inventory["adapters"],
        "adapter_registry": registry_snapshot(),
        "capabilities": summarize_capabilities(resolved.profiles),
        "roles": {name: route.to_dict() for name, route in resolved.roles.items()},
        "sessions": sessions,
        "session_count": len(sessions),
        "issues": issues,
        "warnings": list(resolved.warnings),
        "local_models_toml": models_toml_is_local_only(repo_root),
        "notes": inventory.get("notes", [])
        + [
            "Doctor reports executable/version/auth/models/session_support separately.",
            "remaining_quota is unknown unless a harness exposes it.",
            "Exact session IDs only; bare --resume/--continue/--last are forbidden.",
            "Git and PR operations never dispatch model inference.",
        ],
    }
    if args.json:
        return _emit_json(payload, exit_code=0 if doctor_ok else 1)

    print("cobbler doctor")
    print(f"  repo_root: {repo_root}")
    print(f"  model_calls_made: false")
    print(f"  ok: {doctor_ok}")
    print(f"  session_count: {len(sessions)}")
    print("  adapters:")
    for name, info in sorted(payload["adapters"].items()):
        print(
            f"    - {name}: version={info.get('version')} auth={info.get('auth')} "
            f"session_support={info.get('session_support', {}).get('status')} "
            f"remaining_quota={info.get('remaining_quota')}"
        )
    if issues:
        print("  issues:")
        for issue in issues:
            print(f"    - [{issue['code']}] {issue['message']}")
    return 0 if doctor_ok else 1


def cmd_session(args: argparse.Namespace) -> int:
    """Exact session registry helpers (list / probe / resume argv)."""
    repo_root = _repo_root_from_args(args)
    action = args.session_action

    if action in {"list", "probe"}:
        # Truly read-only: never create runtime directories.
        try:
            registry = SessionRegistry.open_readonly(repo_root)
        except StorageError as error:
            return _emit_storage_error(args, error, command=f"session {action}")
    else:
        try:
            registry = SessionRegistry(repo_root)
        except StorageError as error:
            return _emit_storage_error(args, error, command=f"session {action}")

    if action == "list":
        try:
            records = [rec.to_dict() for rec in registry.list_sessions_strict()]
        except ValidationIssue as issue:
            safe_issue = _redacted_validation_issue(issue)
            payload = {
                "ok": False,
                "repo_root": str(repo_root),
                "sessions": [],
                "count": 0,
                "issues": [safe_issue],
                "mutated_repo": False,
                "read_only": True,
            }
            if args.json:
                return _emit_json(payload, exit_code=1)
            print(
                f"session list: FAILED [{safe_issue['code']}] "
                f"{safe_issue['message']}",
                file=sys.stderr,
            )
            return 1
        payload = {
            "ok": True,
            "repo_root": str(repo_root),
            "sessions": records,
            "count": len(records),
            "mutated_repo": False,
            "read_only": True,
        }
        if args.json:
            return _emit_json(payload, exit_code=0)
        print(f"session list: {len(records)} record(s)")
        for rec in records:
            print(
                f"  - {rec['session_id']} harness={rec['harness']} "
                f"lifecycle={rec['lifecycle']} parent={rec.get('parent_id')}"
            )
        return 0

    if action == "probe":
        try:
            rec = registry.get(args.session_id)
        except ValidationIssue as issue:
            safe_issue = _redacted_validation_issue(issue)
            payload = {"ok": False, "issues": [safe_issue], "read_only": True}
            if args.json:
                return _emit_json(payload, exit_code=1)
            print(
                f"session probe: FAILED [{safe_issue['code']}] "
                f"{safe_issue['message']}",
                file=sys.stderr,
            )
            return 1
        payload = {
            "ok": True,
            "session": rec.to_dict(),
            "mutated_repo": False,
            "read_only": True,
        }
        if args.json:
            return _emit_json(payload, exit_code=0)
        print(f"session probe: {rec.session_id}")
        print(f"  lifecycle: {rec.lifecycle.value}")
        print(f"  harness: {rec.harness}")
        print(f"  actual_model: {rec.actual_model}")
        print(f"  parent_id: {rec.parent_id}")
        print(f"  cwd: {rec.cwd}")
        print(f"  write_reuse_blocked: {rec.write_reuse_blocked}")
        return 0

    if action == "resume":
        # Exact registered record only — never construct argv for unregistered IDs.
        try:
            rec, record_storage_kind = registry.get_with_storage_kind(args.session_id)
        except ValidationIssue as issue:
            safe_issue = _redacted_validation_issue(issue)
            payload = {"ok": False, "issues": [safe_issue]}
            if args.json:
                return _emit_json(payload, exit_code=1)
            print(
                f"session resume: FAILED [{safe_issue['code']}] "
                f"{safe_issue['message']}",
                file=sys.stderr,
            )
            return 1
        adapter = args.adapter or rec.harness
        profile = args.profile or rec.profile or adapter
        model = args.model or rec.actual_model or rec.requested_model
        cwd = args.cwd or rec.cwd
        # Reject contradictory overrides.
        if args.adapter and rec.harness and args.adapter != rec.harness:
            issue = ValidationIssue(
                "session_resume_adapter_mismatch",
                f"Override adapter `{args.adapter}` != registered `{rec.harness}`",
            )
            payload = {"ok": False, "issues": [issue.to_dict()]}
            if args.json:
                return _emit_json(payload, exit_code=1)
            print(f"session resume: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
            return 1
        if getattr(args, "require_write", False):
            if record_storage_kind != "canonical":
                issue = ValidationIssue(
                    "session_legacy_read_only",
                    "Legacy session records cannot qualify for write reuse until explicitly migrated",
                    path=str(registry.root),
                )
                safe_issue = _redacted_validation_issue(issue)
                payload = {"ok": False, "issues": [safe_issue]}
                if args.json:
                    return _emit_json(payload, exit_code=1)
                print(
                    f"session resume: FAILED [{safe_issue['code']}] "
                    f"{safe_issue['message']}",
                    file=sys.stderr,
                )
                return 1
            # Observations must come from flags/probe — never substitute stored values.
            from cobbler_runtime.sessions import (  # noqa: PLC0415
                SessionLifecycle,
                evaluate_session_continuity,
                recompute_context_digest,
            )

            if (
                rec.lifecycle != SessionLifecycle.ACTIVE
                or rec.write_reuse_blocked
                or rec.pending_context_digest
                or rec.pending_source_head
                or rec.rehydration_reason
                or not rec.context_components
            ):
                issue = ValidationIssue(
                    "session_write_reuse_unqualified",
                    "Write reuse requires an exact ACTIVE session with persisted "
                    "canonical digest inputs and no drift/rehydration state",
                    hint=f"lifecycle={rec.lifecycle.value}",
                )
                payload = {"ok": False, "issues": [issue.to_dict()]}
                if args.json:
                    return _emit_json(payload, exit_code=1)
                print(f"session resume: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
                return 1

            observed_model = getattr(args, "model", None) or None
            observed_cwd = getattr(args, "cwd", None) or None
            observed_worktree = getattr(args, "worktree", None) or None
            observed_parent = getattr(args, "parent_id", None) or None
            observed_head = getattr(args, "source_head", None) or getattr(
                args, "head", None
            )
            observed_adapter = getattr(args, "adapter", None) or None
            observed_profile = getattr(args, "profile", None) or None
            missing = []
            for field_name, value in (
                ("adapter", observed_adapter),
                ("profile", observed_profile),
                ("model", observed_model),
                ("cwd", observed_cwd),
                ("worktree", observed_worktree),
                ("parent_id", observed_parent),
                ("source_head", observed_head),
            ):
                if not value:
                    missing.append(field_name)
            if missing:
                issue = ValidationIssue(
                    "session_write_reuse_unqualified",
                    "Write reuse refused: missing observations from flags/probe "
                    f"(required: {', '.join(missing)}); never substitute stored values",
                    hint=",".join(missing),
                )
                payload = {"ok": False, "issues": [issue.to_dict()]}
                if args.json:
                    return _emit_json(payload, exit_code=1)
                print(f"session resume: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
                return 1
            if observed_adapter and rec.harness and observed_adapter != rec.harness:
                issue = ValidationIssue(
                    "session_resume_adapter_mismatch",
                    f"Observed adapter `{observed_adapter}` != registered `{rec.harness}`",
                )
                payload = {"ok": False, "issues": [issue.to_dict()]}
                if args.json:
                    return _emit_json(payload, exit_code=1)
                print(f"session resume: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
                return 1
            if observed_profile and rec.profile and observed_profile != rec.profile:
                issue = ValidationIssue(
                    "session_resume_profile_mismatch",
                    f"Observed profile `{observed_profile}` != registered `{rec.profile}`",
                )
                payload = {"ok": False, "issues": [issue.to_dict()]}
                if args.json:
                    return _emit_json(payload, exit_code=1)
                print(f"session resume: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
                return 1
            if observed_model and rec.actual_model and observed_model != rec.actual_model:
                if rec.requested_model and observed_model != rec.requested_model:
                    issue = ValidationIssue(
                        "session_resume_model_mismatch",
                        f"Contradictory model: observed={observed_model} "
                        f"recorded actual={rec.actual_model} requested={rec.requested_model}",
                    )
                    payload = {"ok": False, "issues": [issue.to_dict()]}
                    if args.json:
                        return _emit_json(payload, exit_code=1)
                    print(
                        f"session resume: FAILED [{issue.code}] {issue.message}",
                        file=sys.stderr,
                    )
                    return 1
            digest = recompute_context_digest(
                rec,
                actual_model=observed_model,
                parent_id=observed_parent,
                cwd=observed_cwd,
                worktree=observed_worktree,
                source_head=observed_head,
            )
            if not rec.context_digest or digest.digest != rec.context_digest:
                issue = ValidationIssue(
                    "session_write_reuse_unqualified",
                    "Write reuse refused: canonical on-disk context digest changed",
                )
                payload = {
                    "ok": False,
                    "issues": [issue.to_dict()],
                    "recorded_digest": rec.context_digest,
                    "observed_digest": digest.digest,
                }
                if args.json:
                    return _emit_json(payload, exit_code=1)
                print(f"session resume: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
                return 1
            continuity = evaluate_session_continuity(
                rec,
                observed_model=observed_model,
                observed_cwd=observed_cwd,
                observed_worktree=observed_worktree,
                observed_parent_id=observed_parent,
                observed_head=observed_head,
                current_digest=digest,
            )
            if (
                not continuity.ok
                or continuity.expected_change
                or continuity.rehydration is not None
                or continuity.write_reuse_blocked
                or rec.write_reuse_blocked
            ):
                issue = ValidationIssue(
                    "session_write_reuse_unqualified",
                    "Write reuse refused by exact registry continuity: "
                    + ("; ".join(continuity.reasons) or rec.block_reason or "blocked"),
                )
                payload = {
                    "ok": False,
                    "issues": [issue.to_dict()],
                    "continuity": continuity.to_dict()
                    if hasattr(continuity, "to_dict")
                    else {"reasons": continuity.reasons},
                }
                if args.json:
                    return _emit_json(payload, exit_code=1)
                print(f"session resume: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
                return 1
            # Use observed (flag) values only for resume argv when require_write.
            adapter = observed_adapter or adapter
            profile = observed_profile or profile
            model = observed_model or model
            cwd = observed_cwd or cwd
        try:
            inv = build_session_resume_invocation(
                adapter=adapter,
                profile=profile,
                session_id=args.session_id,
                executable=args.executable,
                requested_model=model,
                cwd=cwd,
            )
        except ValidationIssue as issue:
            payload = {"ok": False, "issues": [issue.to_dict()]}
            if args.json:
                return _emit_json(payload, exit_code=1)
            print(f"session resume: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
            return 1
        payload = {
            "ok": True,
            "session_id": args.session_id,
            "invocation": inv.to_dict(),
            "registered": True,
            "launched": False,
            "mutated_repo": False,
            "notes": [
                "Exact registered session resume argv only; no process was launched",
                "Verify CWD/worktree registration before any write role",
            ],
        }
        if args.json:
            return _emit_json(payload, exit_code=0)
        print("session resume: argv built (not launched)")
        print("  " + " ".join(inv.argv))
        return 0

    print(f"unknown session action: {action}", file=sys.stderr)
    return 2


def cmd_setup(args: argparse.Namespace) -> int:
    """Inventory tools and optionally write ignored local models.toml."""
    repo_root = _repo_root_from_args(args)
    # Partial flag updates merge into existing models.toml roles (same as onboard apply).
    from cobbler_runtime.onboard import load_models_toml_state  # noqa: PLC0415

    base_roles = None
    existing_profiles = None
    existing_top_level = None
    session_mode = args.session_mode or "ephemeral"
    sharing_policy = args.sharing_policy or "local-only"
    document_owner = "host-coordinator"
    usage_budget_warning = None
    required: list[str] | None
    if getattr(args, "required", None) is None:
        required = None
    else:
        required = [r.strip() for r in str(args.required).split(",") if r.strip()]
    if not getattr(args, "reset_roles", False):
        state = load_models_toml_state(repo_root)
        base_roles = state.roles
        existing_profiles = state.profiles
        if state.parse_ok:
            existing_top_level = state.unknown_top_level
        session_mode = args.session_mode or state.session_mode
        sharing_policy = args.sharing_policy or state.sharing_policy
        document_owner = state.document_owner
        usage_budget_warning = state.usage_budget_warning
        if required is None:
            required = list(state.required_roles)
    else:
        required = required or []
    prefs = preferences_from_flags(
        implement=args.implement,
        review=args.review,
        planning=args.planning,
        lightweight_review=args.lightweight_review,
        validate=args.validate,
        synthesize=args.synthesize,
        scout=args.scout,
        required=required or [],
        session_mode=session_mode,
        sharing_policy=sharing_policy,
        native_fallback=not args.no_native_fallback,
        base_roles=base_roles,
    )
    prefs.document_owner = document_owner
    prefs.usage_budget_warning = usage_budget_warning
    try:
        result = run_setup(
            repo_root,
            preferences=prefs,
            write_toml=not args.dry_run,
            force_toml=bool(args.force),
            run_smoke=bool(args.smoke),
            existing_profiles=existing_profiles,
            existing_top_level=existing_top_level,
        )
    except ValidationIssue as issue:
        payload = {"ok": False, "issues": [issue.to_dict()], "credentials_printed": False}
        if args.json:
            return _emit_json(payload, exit_code=1)
        print(f"setup: FAILED [{issue.code}] {issue.message}", file=sys.stderr)
        return 1

    payload = result.to_dict()
    payload["mutated_repo"] = False
    payload["staged_models_toml"] = False
    if args.json:
        return _emit_json(payload, exit_code=0 if result.ok else 1)

    print(f"setup: {'OK' if result.ok else 'FAILED'}")
    print(f"  models_toml_written: {result.models_toml_written}")
    print(f"  models_toml_ignored: {result.models_toml_ignored}")
    print(f"  smoke_ran: {result.smoke_ran}")
    print(f"  credentials_printed: {result.credentials_printed}")
    for rec in result.recommendations:
        print(f"  recommend: {rec}")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    for issue in result.issues:
        print(f"  issue: [{issue.get('code')}] {issue.get('message')}")
    print("  note: never stage .elves/models.toml; snapshot routes into Survival Guide when staging")
    return 0 if result.ok else 1


def cmd_onboard(args: argparse.Namespace) -> int:
    """Model onboarding: plan / show / apply / probe (Claude Code + Codex)."""
    repo_root = _repo_root_from_args(args)
    action = getattr(args, "onboard_action", None) or "plan"

    if action == "plan":
        packet = build_onboarding_packet(repo_root)
        payload = packet.to_dict()
        payload["ok"] = True
        payload["credentials_printed"] = False
        if args.json:
            return _emit_json(payload, exit_code=0)
        print("onboard plan: interview packet ready")
        print(f"  purposes: {len(packet.purposes)}")
        print(f"  questions: {len(packet.questions)}")
        for q in packet.questions:
            print(f"  - {q['purpose_id']}: current={q['current']}")
        for note in packet.notes[:5]:
            print(f"  note: {note}")
        print("  next: host agent asks questions, then onboard apply with chosen routes")
        return 0

    if action == "show":
        payload = show_onboarding(repo_root)
        if args.json:
            return _emit_json(payload, exit_code=0)
        print("onboard show:")
        print(f"  models_toml_exists: {payload['models_toml_exists']}")
        for role, profile in sorted(payload["roles"].items()):
            print(f"  {role}: {profile}")
        print(f"  update: {payload['update_hint']}")
        return 0

    if action == "apply":
        # None = preserve existing required flags on merge; list = explicit set (may be empty).
        required_raw = getattr(args, "required", None)
        required: list[str] | None
        if required_raw is None:
            required = None
        else:
            required = [r.strip() for r in str(required_raw).split(",") if r.strip()]
        role_flags = {
            "implement": getattr(args, "implement", None),
            "review": getattr(args, "review", None),
            "planning": getattr(args, "planning", None),
            "lightweight_review": getattr(args, "lightweight_review", None),
            "validate": getattr(args, "validate", None),
            "synthesize": getattr(args, "synthesize", None),
            "scout": getattr(args, "scout", None),
        }
        payload = apply_onboarding(
            repo_root,
            role_flags=role_flags,
            required=required,
            force=bool(getattr(args, "force", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            run_smoke=bool(getattr(args, "smoke", False)),
            merge_existing=not bool(getattr(args, "reset_roles", False)),
        )
        if args.json:
            return _emit_json(payload, exit_code=0 if payload.get("ok") else 1)
        print(f"onboard apply: {'OK' if payload.get('ok') else 'FAILED'}")
        print(f"  models_toml_written: {payload.get('models_toml_written')}")
        for rec in payload.get("recommendations") or []:
            print(f"  recommend: {rec}")
        for warning in payload.get("warnings") or []:
            print(f"  warning: {warning}")
        for issue in payload.get("issues") or []:
            print(f"  issue: [{issue.get('code')}] {issue.get('message')}")
        print("  next: python3 scripts/cobbler_agents.py onboard probe --json")
        return 0 if payload.get("ok") else 1

    if action == "probe":
        payload = probe_routes(
            repo_root,
            live_smoke=bool(getattr(args, "smoke", False)),
        )
        if args.json:
            return _emit_json(payload, exit_code=0 if payload.get("ok") else 1)
        print(f"onboard probe: {'OK' if payload.get('ok') else 'FAILED'}")
        summary = payload.get("summary") or {}
        print(
            f"  pass={summary.get('pass')} warn={summary.get('warn')} fail={summary.get('fail')}"
        )
        for probe in payload.get("probes") or []:
            print(
                f"  [{probe.get('status')}] {probe.get('route')}"
                f"{'/' + probe['purpose'] if probe.get('purpose') else ''}: "
                f"{probe.get('detail')}"
            )
        if payload.get("smoke", {}).get("requested") and not payload.get("smoke", {}).get("ran"):
            print("  note: live smoke needs host-provided executor or follow-up host turns")
        return 0 if payload.get("ok") else 1

    print(f"unknown onboard action: {action}", file=sys.stderr)
    return 2


def cmd_worker(args: argparse.Namespace) -> int:
    """Writer lease prepare/audit/export/refresh — host-owned lifecycle."""
    repo_root = _repo_root_from_args(args)
    action = args.worker_action

    try:
        store = LeaseStore(repo_root)
        if action == "prepare":
            grant_names = normalize_worker_credential_grant_names(
                list(getattr(args, "grant_env", None) or [])
            )
            grant_context = build_worker_credential_grant_context(
                args.lease_id,
                grant_names,
            )
            grant_context_digest = worker_credential_grant_context_digest(
                grant_context
            )
            profile = grok_write_profile(args.grok_version)
            if args.sandbox_profile == "workspace":
                profile = workspace_sandbox_write_profile()
            # Host-issued qualification: private evidence file or registry id (not booleans).
            qualification = None
            qual_file = getattr(args, "qualification_file", None)
            qual_id = getattr(args, "qualification_id", None)
            if qual_file:
                qpath = Path(qual_file)
                qualification = json.loads(qpath.read_text(encoding="utf-8"))
            elif qual_id:
                # Store-owned digest path under leases/qualifications/
                qpath = store.snapshot_dir(qual_id) / "qualification.json"
                try:
                    qualification = _read_worker_snapshot(repo_root, qpath)
                except StorageError as exc:
                    if exc.code != "not_found":
                        raise
                    raise ValidationIssue(
                        "qualification_id_not_found",
                        f"No host qualification record for id `{qual_id}`",
                        path=str(qpath),
                    ) from exc
            lease = store.prepare(
                lease_id=args.lease_id,
                host_checkout=Path(args.host_checkout),
                worker_checkout=Path(args.worker_checkout),
                session_id=args.session_id,
                base_head=args.base_head,
                adapter=args.adapter,
                profile=args.profile,
                allowed_paths=list(args.allowed_path or []),
                sandbox_profile=args.sandbox_profile,
                detached_commits_permitted=profile.detached_commits_permitted,
                write_profile_qualified=profile.qualified and not args.unqualified,
                grok_version=args.grok_version,
                qualification_evidence=qualification,
                credential_grant_names=grant_names,
                credential_grant_context_digest=grant_context_digest,
            )
            try:
                # Publish all prepare-time evidence before ACTIVE authority. Any
                # failure terminalizes the already-published PREPARED record so
                # exclusivity cannot deadlock future work.
                snaps = build_worker_pre_snapshot(lease)
                snap_dir = store.snapshot_dir(lease.lease_id)
                grant_context_path = snap_dir / "credential_grants.json"
                _write_worker_snapshot(repo_root, grant_context_path, grant_context)
                snap_path = snap_dir / "pre.json"
                _write_worker_snapshot(repo_root, snap_path, snaps)
                inv = None
                if args.adapter == "grok-build":
                    inv = build_write_resume_invocation(
                        adapter="grok-build",
                        session_id=args.session_id,
                        cwd=args.worker_checkout,
                        version=args.grok_version,
                    ).to_dict()
                store.activate(lease.lease_id)
            except BaseException as exc:
                _reject_live_worker_lease(store, lease.lease_id, exc)
                raise
            payload = {
                "ok": True,
                "lease": store.get(lease.lease_id).to_dict(),
                "write_resume_invocation": inv,
                "pre_snapshots": snaps,
                "mutated_repo": False,
            }
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(f"worker prepare: {lease.lease_id} ACTIVE")
            return 0

        if action == "audit":
            lease = store.get(args.lease_id)
            # Capture once so the same exact grant set protects the live audit,
            # immutable evidence (including pre-snapshots), and CLI response.
            supplied_grant_names = normalize_worker_credential_grant_names(
                list(getattr(args, "grant_env", None) or [])
            )
            try:
                if lease.credential_grant_context_digest is None:
                    if supplied_grant_names or lease.credential_grant_names:
                        raise ValidationIssue(
                            "worker_credential_context_missing",
                            "Lease has no prepare-time credential grant authority",
                        )
                    verified_grant_values = frozenset()
                else:
                    grant_context_path = (
                        store.snapshot_dir(args.lease_id) / "credential_grants.json"
                    )
                    grant_context = _read_worker_snapshot(
                        repo_root,
                        grant_context_path,
                    )
                    verified_grant_values = verify_worker_credential_grant_context(
                        lease,
                        grant_context,
                        supplied_grant_names,
                    )
            except BaseException as exc:
                _reject_live_worker_lease(store, lease.lease_id, exc)
                raise
            exact_secret_values = frozenset(
                set(collect_secret_env_values()) | set(verified_grant_values)
            )
            pre_path = store.snapshot_dir(args.lease_id) / "pre.json"
            try:
                # Missing or unsafe pre.json is terminal for this lease: audit
                # cannot be retried honestly without prepare-time evidence.
                pre = validate_worker_pre_snapshot(
                    lease,
                    _read_worker_snapshot(repo_root, pre_path),
                )
            except BaseException as exc:
                _reject_live_worker_lease(store, lease.lease_id, exc)
                if not isinstance(exc, StorageError) or exc.code != "not_found":
                    raise
                raise ValidationIssue(
                    "audit_missing_pre_snapshot",
                    "Missing pre.json snapshot; refuse audit without prepare-time evidence",
                    path=str(pre_path),
                ) from exc
            try:
                store.mark_auditing(lease.lease_id)
                result = audit_lease_turn(
                    store.get(args.lease_id),
                    pre_refs_digest=pre.get("refs_digest"),
                    pre_remotes=pre.get("remotes"),
                    pre_config=pre.get("config"),
                    pre_hooks=pre.get("hooks"),
                    pre_common_config=pre.get("common_config"),
                    pre_common_hooks=pre.get("common_hooks"),
                    pre_ref_storage=pre.get("ref_storage"),
                    pre_git_dir=pre.get("git_dir"),
                    pre_git_common_dir=pre.get("git_common_dir"),
                    pre_authority=pre.get("authority"),
                    pre_static_control=pre.get("static_control"),
                    observed_commands=list(args.observed_command or []),
                    exact_secret_values=exact_secret_values,
                )
                if not result.ok:
                    store.reject(args.lease_id, "; ".join(result.reasons))
                else:
                    # Persist immutable evidence + atomic audited_pass transition.
                    evidence = build_audit_evidence(
                        result,
                        pre_snapshots=pre,
                        exact_secret_values=exact_secret_values,
                    )
                    store.mark_audited_pass(args.lease_id, evidence=evidence)
            except BaseException as exc:
                _reject_live_worker_lease(store, lease.lease_id, exc)
                raise
            payload = {
                "ok": result.ok,
                "audit": result.to_dict(exact_secret_values=exact_secret_values),
                "mutated_repo": False,
            }
            if args.json:
                return _emit_json(
                    payload,
                    exit_code=0 if result.ok else 1,
                    exact_secret_values=exact_secret_values,
                )
            print(f"worker audit: {'OK' if result.ok else 'FAILED'}")
            if result.reasons:
                # Never send free-form worker/Git material to a terminal logging
                # sink. The JSON mode above applies the exact-value redactor and
                # is the explicit structured diagnostic surface.
                print(
                    f"  - {len(result.reasons)} audit finding(s); "
                    "details omitted from text output (use --json for redacted details)"
                )
            return 0 if result.ok else 1

        if action == "export":
            lease = store.get(args.lease_id)
            out = Path(args.output_dir)
            # Load persisted audit evidence; never rerun a weaker audit without snapshots.
            evidence_path = store.snapshot_dir(args.lease_id) / "audit_evidence.json"
            try:
                evidence = _read_worker_snapshot(repo_root, evidence_path)
            except StorageError as exc:
                if exc.code != "not_found":
                    raise
                raise ValidationIssue(
                    "export_missing_audit_evidence",
                    "Export requires persisted audit evidence from an AUDITED_PASS lease",
                    path=str(evidence_path),
                ) from exc
            required_evidence_fields = {
                "ok",
                "lease_id",
                "worker_tip",
                "base_head",
                "commit_chain",
                "audited_git_surfaces",
                "patch_transport_digests",
                "evidence_digest",
            }
            missing_evidence = sorted(required_evidence_fields - set(evidence))
            if missing_evidence:
                raise ValidationIssue(
                    "export_evidence_incomplete",
                    "Persisted audit evidence missing fields: "
                    + ", ".join(missing_evidence),
                )
            if not evidence.get("ok") or lease.state.value not in {
                "audited_pass",
                "exported",
                "apply_checked",
            }:
                raise ValidationIssue(
                    "export_requires_audited_pass",
                    f"Export refused: lease state={lease.state.value} evidence.ok={evidence.get('ok')}",
                )
            if evidence.get("lease_id") != lease.lease_id:
                raise ValidationIssue(
                    "export_evidence_lease_mismatch",
                    "Persisted audit evidence lease_id does not match",
                )
            if str(evidence.get("base_head") or "") != lease.base_head:
                raise ValidationIssue(
                    "export_evidence_base_mismatch",
                    "Persisted audit evidence base_head does not match lease",
                )
            if str(evidence.get("worker_tip") or "") != str(lease.worker_tip or ""):
                raise ValidationIssue(
                    "export_evidence_tip_mismatch",
                    "Persisted audit evidence worker_tip does not match audited lease tip",
                )
            # Recompute evidence digest over canonical payload (excluding digest field).
            import hashlib

            stored_digest = str(evidence.get("evidence_digest") or "")
            canonical = {k: v for k, v in evidence.items() if k != "evidence_digest"}
            recomputed = hashlib.sha256(
                json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if len(stored_digest) != 64 or any(
                ch not in "0123456789abcdef" for ch in stored_digest.lower()
            ):
                raise ValidationIssue(
                    "export_evidence_digest_missing",
                    "Persisted audit evidence requires a complete SHA-256 evidence digest",
                )
            if stored_digest != recomputed:
                raise ValidationIssue(
                    "export_evidence_digest_mismatch",
                    "Persisted audit evidence digest does not match recomputed canonical payload "
                    "(tampered evidence)",
                )
            if stored_digest != str(lease.audit_evidence_digest or ""):
                raise ValidationIssue(
                    "export_evidence_lease_digest_mismatch",
                    "Persisted audit evidence digest does not match the lease's audited digest",
                )
            chain = evidence.get("commit_chain") or []
            from cobbler_runtime.audit import CommitInfo  # noqa: PLC0415

            commit_objs = [
                CommitInfo(
                    sha=str(c["sha"]),
                    parents=list(c.get("parents") or []),
                    tree=str(c.get("tree") or ""),
                    subject=str(c.get("subject") or ""),
                    author=str(c.get("author") or ""),
                    paths=list(c.get("paths") or []),
                )
                for c in chain
                if isinstance(c, dict)
            ]
            # Do not mark EXPORTED until patch export and optional apply-check succeed.
            patches = export_binary_patches(
                lease,
                output_dir=out,
                chain=commit_objs,
                audit_evidence=evidence,
            )
            # Re-open and verify the complete directory immediately before any
            # host apply-check. Producer-side hashes are not authority until a
            # separate consumer rejects tampering, extras, and reorderings.
            patches = verify_patch_manifest(lease, output_dir=out)
            apply_result = None
            if args.host_apply_check:
                apply_result = host_apply_check(
                    Path(lease.host_checkout),
                    patches,
                    base_head=lease.base_head,
                    cumulative=True,
                    disposable=True,
                    lease=lease,
                    manifest_dir=out,
                )
                if not apply_result.get("ok"):
                    raise ValidationIssue(
                        "export_apply_check_failed",
                        "Host apply-check failed; refusing EXPORTED state: "
                        + str(apply_result.get("error") or apply_result.get("reasons") or apply_result),
                    )
            store.mark_exported(args.lease_id, str(out))
            if apply_result is not None and apply_result.get("ok"):
                lease2 = store.get(args.lease_id)
                if lease2.state.value == "exported":
                    store.mark_apply_checked(args.lease_id, evidence=apply_result)
            payload = {
                "ok": True,
                "patches": [str(p) for p in patches],
                "audit": evidence,
                "host_apply_check": apply_result,
                "mutated_repo": False,
                "note": "Host creates sanitized branch commits after apply-check",
            }
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(f"worker export: {len(patches)} patch(es) -> {out}")
            return 0

        if action == "import":
            lease = store.get(args.lease_id)
            if not lease.exported_patch_dir:
                raise ValidationIssue(
                    "host_import_export_path_missing",
                    "Worker import requires the store-owned exported patch directory",
                )
            result = host_import_patches(
                lease,
                manifest_dir=Path(lease.exported_patch_dir),
            )
            payload = {
                "ok": True,
                "import": result,
                "mutated_repo": True,
            }
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(
                f"worker import: {len(result['checked'])} patch(es) staged; "
                f"tree={result['resulting_tree']}"
            )
            return 0

        if action == "refresh":
            lease = store.get(args.lease_id)
            if lease.state.value != "apply_checked" and lease.state.value != "integrated":
                raise ValidationIssue(
                    "refresh_requires_apply_checked",
                    f"refresh requires APPLY_CHECKED (got {lease.state.value}); "
                    "never synthesize from EXPORTED alone",
                    path=f"leases.{args.lease_id}.state",
                )
            if lease.state.value == "apply_checked":
                store.mark_integrated(args.lease_id, new_tip=args.new_tip)
            elif not lease.integrated_tip or lease.integrated_tip != args.new_tip:
                raise ValidationIssue(
                    "refresh_tip_mismatch",
                    "Worker refresh tip must match the recorded integrated host tip",
                )
            result = store.refresh_worker_to_tip(args.lease_id, new_tip=args.new_tip)
            store.close(args.lease_id)
            payload = {"ok": True, "refresh": result, "mutated_repo": True}
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(f"worker refresh: tip={result['worker_tip']}")
            return 0

        if action == "packet":
            lease = store.get(args.lease_id)
            packet = build_write_task_packet(lease, task=args.task)
            if args.json:
                return _emit_json({"ok": True, "packet": packet}, exit_code=0)
            safe_packet = redact_structure(
                packet,
                exact_values=collect_secret_env_values(),
            )
            print(json.dumps(safe_packet, indent=2, sort_keys=True))
            return 0

    except StorageError as error:
        return _emit_storage_error(args, error, command=f"worker {action}")
    except ValidationIssue as issue:
        safe_issue = _redacted_validation_issue(issue)
        payload = {"ok": False, "issues": [safe_issue]}
        if args.json:
            return _emit_json(payload, exit_code=1)
        print(
            f"worker {action}: FAILED [{safe_issue['code']}] {safe_issue['message']}",
            file=sys.stderr,
        )
        return 1

    print(f"unknown worker action: {action}", file=sys.stderr)
    return 2


def cmd_implement(args: argparse.Namespace) -> int:
    """Optional external batch implementer + full-run supervisor."""
    repo_root = _repo_root_from_args(args)
    action = args.implement_action

    try:
        if action == "rollback-ref":
            payload = create_rollback_ref(
                repo_root,
                run_id=args.run_id,
                session_id=args.session_id,
                batch=args.batch,
                head=args.head,
                push_remote=args.remote if args.push else None,
            )
            payload.update(
                {
                    "action": "rollback_ref",
                    "model_calls_made": False,
                    "mutated_repo": bool(
                        payload.get("local_ref_created") or payload.get("pushed")
                    ),
                }
            )
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(f"rollback ref: {payload['ref']} -> {payload['head']}")
            return 0

        if action == "full-run-prepare":
            adapter_name = getattr(args, "adapter", None) or "grok-build"
            acceptance_session = getattr(args, "session", None)
            if adapter_name != "fixture" and not acceptance_session:
                default_session = repo_root / ".elves-session.json"
                if default_session.is_file():
                    acceptance_session = str(default_session)
                else:
                    raise ValidationIssue(
                        "full_run_acceptance_session_required",
                        "Production full-run-prepare requires --session (or a repo-root .elves-session.json) so plan/session/packet Acceptance can be reconciled before launch",
                    )
            payload = prepare_full_run(
                repo_root,
                session_id=args.session_id,
                branch=args.branch,
                start_head=args.start_head,
                worktree=args.worktree or repo_root,
                packet_path=args.packet,
                session_path=acceptance_session,
                plan_path=getattr(args, "plan", None),
                adapter=adapter_name,
                model=(
                    getattr(args, "model", None)
                    or (
                        "swe-1-7-lightning"
                        if adapter_name == "devin-cli"
                        else "auto"
                    )
                ),
                permission_mode=getattr(args, "permission_mode", None) or "auto",
                # None means "not explicitly requested": prepare_full_run's
                # normalized resolution is the single default authority.
                effort=getattr(args, "effort", None),
                executable=getattr(args, "executable", None),
                create=not bool(getattr(args, "resume", False)),
                check=bool(getattr(args, "check", False)),
                max_turns=int(getattr(args, "max_turns", 80) or 80),
                fixture_script=getattr(args, "fixture_script", None),
                credential_grant_names=list(getattr(args, "grant_env", None) or []) or None,
                goal_behavioral_evidence=getattr(
                    args, "grok_goal_behavioral_evidence", None
                ),
            )
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if action == "full-run-launch":
            payload = launch_full_run(
                repo_root,
                session_id=args.session_id,
                resume=bool(getattr(args, "resume", False)),
                credential_grant_names=list(getattr(args, "grant_env", None) or []) or None,
                grant_grok_auth=bool(getattr(args, "grant_grok_auth", False)),
                grant_devin_auth=bool(
                    getattr(args, "grant_devin_auth", False)
                ),
                grant_github_push=bool(
                    getattr(args, "grant_github_push", False)
                ),
            )
            if args.json:
                return _emit_json(payload, exit_code=0 if payload.get("ok") else 1)
            print(
                f"full-run launch: session={payload.get('session_id')} "
                f"pid={payload.get('pid')} adapter={payload.get('adapter')} "
                f"status={payload.get('status')}"
            )
            return 0 if payload.get("ok") else 1

        if action == "full-run-monitor" and getattr(args, "wait", False):
            action = "full-run-await"
        if action == "full-run-monitor":
            payload = monitor_full_run(
                repo_root,
                session_id=args.session_id,
                stale_after_seconds=int(getattr(args, "stale_after", 300) or 300),
                acknowledge_high_risk_checkpoint=getattr(
                    args, "ack_high_risk_checkpoint", None
                ),
                force_full=bool(getattr(args, "full", False)),
            )
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(
                f"full-run monitor: state={payload.get('state')} "
                f"batch={payload.get('batch')} head={payload.get('head')} "
                f"next={payload.get('next_action')}"
            )
            review_context = payload.get("review_context")
            if isinstance(review_context, Mapping) and isinstance(
                review_context.get("review_prompt_block"), str
            ):
                print(review_context["review_prompt_block"])
            return 0

        if action == "full-run-await":
            follow = True
            if getattr(args, "quiet", False):
                follow = False
            if getattr(args, "follow", None) is False:
                follow = False
            if getattr(args, "no_follow", False):
                follow = False
            stream_writer = None
            if follow:
                # Keep stdout as one parseable terminal JSON object for
                # machine-readable callers while the live, sanitized worker
                # window remains visible on stderr. Text mode follows stdout.
                stream_writer = partial(
                    print,
                    file=(sys.stderr if getattr(args, "json", False) else sys.stdout),
                    flush=True,
                )
            payload = await_full_run(
                repo_root,
                session_id=args.session_id,
                stale_after_seconds=int(getattr(args, "stale_after", 300) or 300),
                timeout_seconds=(
                    float(args.timeout) if getattr(args, "timeout", None) is not None else None
                ),
                acknowledge_high_risk_checkpoint=getattr(
                    args, "ack_high_risk_checkpoint", None
                ),
                follow=follow,
                quiet=bool(getattr(args, "quiet", False)),
                stream_writer=stream_writer,
            )
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(
                f"full-run await: state={payload.get('state')} "
                f"next={payload.get('next_action')} "
                f"material={payload.get('material_transition')} "
                f"follow={payload.get('follow')}"
            )
            review_context = payload.get("review_context")
            if isinstance(review_context, Mapping) and isinstance(
                review_context.get("review_prompt_block"), str
            ):
                print(review_context["review_prompt_block"])
            return 0

        if action == "full-run-reconcile":
            payload = reconstruct_missing_report(
                repo_root,
                session_id=args.session_id,
                host_tests_pass=bool(getattr(args, "host_tests_pass", False)),
            )
            if args.json:
                return _emit_json(payload, exit_code=0 if payload.get("ok") else 1)
            print(
                f"full-run reconcile: ok={payload.get('ok')} "
                f"next={payload.get('next_action')} "
                f"provenance={payload.get('provenance')}"
            )
            review_context = payload.get("review_context")
            if isinstance(review_context, Mapping) and isinstance(
                review_context.get("review_prompt_block"), str
            ):
                print(review_context["review_prompt_block"])
            return 0 if payload.get("ok") else 1

        if action == "full-run-logs":
            payload = logs_full_run(
                repo_root,
                session_id=args.session_id,
                raw_tail=bool(getattr(args, "raw_tail", False)),
                tail_lines=int(getattr(args, "tail", 40) or 40),
            )
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if action == "full-run-stop":
            payload = stop_full_run(repo_root, session_id=args.session_id)
            if args.json:
                return _emit_json(payload, exit_code=0 if payload.get("ok") else 1)
            print(
                f"full-run stop: session={payload.get('session_id')} "
                f"signaled={payload.get('signaled')} still_alive={payload.get('still_alive')}"
            )
            return 0 if payload.get("ok") else 1

        if action == "prepare":
            payload = prepare_implement(
                repo_root,
                worktree=args.worktree,
                model=args.model,
                session_id=args.session_id,
                branch=args.branch,
                lane=args.lane,
                git_mode=args.git_mode,
                permission_mode=args.permission_mode,
                executable=args.executable,
                adapter=getattr(args, "adapter", None) or "grok-build",
            )
            if args.json:
                return _emit_json(payload, exit_code=0)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if action == "launch":
            payload = launch_payload(
                repo_root,
                session_id=args.session_id,
                packet=args.packet,
                cwd=args.cwd or args.worktree,
                model=args.model,
                permission_mode=args.permission_mode,
                executable=args.executable,
                create=bool(args.create),
                batch=args.batch,
                exec_process=bool(args.exec),
                effort=getattr(args, "effort", None),
                check=bool(getattr(args, "check", False)),
            )
            if args.json:
                return _emit_json(
                    payload,
                    exit_code=0 if payload.get("ok") else int(payload.get("exit_code") or 1),
                )
            # Default human surface: exact argv line (host/human launches).
            print(payload["argv_joined"])
            if payload.get("error_human"):
                print(f"error: {payload['error_human']}", file=sys.stderr)
            if payload.get("launched"):
                return int(payload.get("exit_code") or 0)
            return 0

        if action == "resume-batch":
            payload = resume_batch_payload(
                repo_root,
                batch=int(args.batch),
                packet=args.packet,
                session_id=args.session_id,
                cwd=args.cwd or args.worktree,
                model=args.model,
                permission_mode=args.permission_mode,
                executable=args.executable,
                exec_process=bool(args.exec),
                effort=getattr(args, "effort", None),
                check=bool(getattr(args, "check", False)),
            )
            if args.json:
                return _emit_json(
                    payload,
                    exit_code=0 if payload.get("ok") else int(payload.get("exit_code") or 1),
                )
            print(payload["argv_joined"])
            if payload.get("error_human"):
                print(f"error: {payload['error_human']}", file=sys.stderr)
            if payload.get("launched"):
                return int(payload.get("exit_code") or 0)
            return 0

        if action == "gate":
            payload = run_gate(
                repo_root,
                batch=int(args.batch),
                focused=bool(args.focused),
                cwd=args.cwd,
            )
            if args.json:
                return _emit_json(payload, exit_code=0 if payload.get("ok") else 1)
            status = "OK" if payload.get("ok") else "FAILED"
            tests = payload.get("tests") or {}
            print(
                f"implement gate: {status} batch={payload.get('batch')} "
                f"tip={payload.get('tip')} "
                f"passed={tests.get('passed')} failed={tests.get('failed')} "
                f"skipped={tests.get('skipped')}"
            )
            for warning in payload.get("warnings") or []:
                print(f"warning: {warning}", file=sys.stderr)
            print(f"  gate_path: {payload.get('gate_path')}")
            return 0 if payload.get("ok") else 1

        if action == "status":
            payload = status_payload(repo_root)
            if args.json:
                return _emit_json(payload, exit_code=0)
            if not payload.get("present"):
                print("implement status: no runtime state (run prepare first)")
                return 0
            state = payload.get("state") or {}
            print("implement status:")
            print(f"  runtime_dir: {payload.get('runtime_dir')}")
            print(f"  lane: {state.get('lane')}")
            print(f"  git_mode: {state.get('git_mode')}")
            print(f"  session_id: {state.get('session_id')}")
            print(f"  model: {state.get('model')}")
            print(f"  worktree: {state.get('worktree')}")
            print(f"  permission_mode: {state.get('permission_mode')}")
            print(f"  last_batch: {state.get('last_batch')}")
            print(f"  last_packet: {state.get('last_packet')}")
            print(f"  gates: {len(payload.get('gates') or [])}")
            print(f"  done_reports: {len(payload.get('done_reports') or [])}")
            return 0

    except ValidationIssue as issue:
        safe_issue = _redacted_validation_issue(issue)
        payload = {"ok": False, "issues": [safe_issue]}
        if args.json:
            return _emit_json(payload, exit_code=1)
        print(
            f"implement {action}: FAILED [{safe_issue['code']}] "
            f"{safe_issue['message']}",
            file=sys.stderr,
        )
        if safe_issue.get("hint"):
            print(f"  hint: {safe_issue['hint']}", file=sys.stderr)
        return 1

    print(f"unknown implement action: {action}", file=sys.stderr)
    return 2


def _add_common_flags(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root for config discovery (default: cwd)",
    )
    subparser.add_argument(
        "--json",
        action="store_true",
        help="Emit stable machine-readable JSON",
    )


def cmd_council(args: argparse.Namespace) -> int:
    """Parallel read-only council fan-out. Host still owns fitted synthesis."""
    repo_root = _repo_root_from_args(args)
    resolved = resolve_from_repo(repo_root)

    if not resolved.ok:
        payload = {
            "ok": False,
            "blocked": True,
            "council_verified": False,
            "issues": [issue.to_dict() for issue in resolved.issues],
            "warnings": list(resolved.warnings),
            "model_calls_made": False,
            "mutated_repo": False,
            "host_synthesis_only": True,
            "external_routing_enabled": resolved.external_routing_enabled,
            "notes": ["resolved config is not ok; refusing council launch"],
        }
        if args.json:
            return _emit_json(payload, exit_code=1)
        print("council: FAILED (resolved config not ok)", file=sys.stderr)
        for issue in resolved.issues:
            print(f"  [{issue.code}] {issue.message}", file=sys.stderr)
        return 1

    # Build lanes from each resolved role/profile without dropping fields.
    # Survival-guide required routes remain even when --use-resolved-routes is off.
    role_names = [
        name.strip()
        for name in (args.roles or "architect,skeptic,tester").split(",")
        if name.strip()
    ]
    lanes: list[LaneSpec] = lanes_from_resolved(
        resolved,
        role_names=role_names,
        timeout_seconds=float(args.timeout),
        use_resolved_routes=bool(args.use_resolved_routes),
    )

    target = args.target_quorum
    required = args.required_quorum
    phase_required = bool(args.phase_required)
    result = run_council_sync(
        lanes,
        repo_root=repo_root,
        task=args.task,
        phase=args.phase,
        phase_required=phase_required,
        target_quorum=target,
        required_quorum=required if phase_required else None,
        plan_path=args.plan_path,
        head_sha=args.head,
    )
    payload = result.to_dict()
    # Prefer runtime-truthful counters from dispatch.
    payload["model_calls_made"] = bool(result.model_calls_made)
    payload["mutated_repo"] = bool(result.mutated_repo)
    payload["host_synthesis_only"] = True
    payload["external_routing_enabled"] = resolved.external_routing_enabled
    if args.json:
        return _emit_json(payload, exit_code=0 if result.ok and not result.blocked else 1)

    print(f"council: {'OK' if result.ok and not result.blocked else 'FAILED'}")
    print(f"  run_id: {result.run_id}")
    print(f"  council_verified: {result.council_verified}")
    print(f"  blocked: {result.blocked}")
    print(f"  confidence: {result.confidence}")
    print(f"  successful_reports: {len(result.successful_reports)}")
    print(f"  model_calls_made: {result.model_calls_made}")
    print(f"  mutated_repo: {result.mutated_repo}")
    for note in result.notes:
        print(f"  note: {note}")
    return 0 if result.ok and not result.blocked else 1


def cmd_lightweight_review(args: argparse.Namespace) -> int:
    """Single bounded utility review; not a council vote and not high-risk close."""
    repo_root = _repo_root_from_args(args)
    result = run_lightweight_review_sync(
        repo_root=repo_root,
        task=args.task,
        adapter=args.adapter,
        profile=args.profile,
        executable=args.executable,
        requested_model=args.model,
        timeout_seconds=float(args.timeout),
        head_sha=args.head,
    )
    payload = result.to_dict()
    payload["not_a_council_vote"] = True
    payload["cannot_close_high_risk_review"] = True
    # Explicit lane-level truth from dispatch (not path-substring inference).
    payload["mutated_repo"] = bool(result.mutated_repo)
    payload["model_calls_made"] = bool(result.model_call_made) or any(
        a.model_call_made for a in (result.attempts or [])
    )
    if args.json:
        return _emit_json(payload, exit_code=0 if result.ok else 1)
    print(f"lightweight-review: {'OK' if result.ok else 'FAILED'}")
    print(f"  role: {result.role}")
    print(f"  adapter: {result.adapter}")
    if result.error:
        print(f"  error: {result.error}")
    return 0 if result.ok else 1


class _NoAbbrevArgumentParser(argparse.ArgumentParser):
    """Operator parser that rejects abbreviated long options.

    Abbreviations like ``--effor low`` would parse silently while
    presence-based explicitness checks scan for the literal spelling,
    inverting an explicitly requested value. Subparsers inherit this class
    through argparse's parser_class default, so every subcommand rejects
    abbreviations too.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = _NoAbbrevArgumentParser(
        prog="cobbler_agents.py",
        description=(
            "Cobbler external-agent operator CLI "
            "(config validation, doctor, read-only council)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    preferences = sub.add_parser(
        "preferences",
        help="Show, set, or reset safe machine-global worker preferences",
    )
    preferences_sub = preferences.add_subparsers(dest="preferences_action", required=True)
    for action in ("show", "reset"):
        item = preferences_sub.add_parser(action)
        item.add_argument("--json", action="store_true")
        item.set_defaults(func=cmd_preferences)
    pref_set = preferences_sub.add_parser("set")
    pref_set.add_argument(
        "preference",
        choices=("worker.provider", "worker.native_effort", "worker.prewalk", "worker.parallel"),
    )
    pref_set.add_argument("value")
    pref_set.add_argument("--json", action="store_true")
    pref_set.set_defaults(func=cmd_preferences)

    lanes = sub.add_parser(
        "lanes",
        help="Deterministic Parallelves lane validation and width test (read-only, recommend-only)",
    )
    lanes_sub = lanes.add_subparsers(dest="lanes_action", required=True)
    lanes_validate = lanes_sub.add_parser(
        "validate", help="Parse the plan's `## Lanes` block and validate the lane partition"
    )
    lanes_validate.add_argument("--plan", default=None, help="Path to the plan markdown file")
    lanes_validate.add_argument("--json", action="store_true")
    lanes_validate.set_defaults(func=cmd_lanes)
    lanes_plan = lanes_sub.add_parser(
        "plan", help="Run the four-gate width test; recommend-only, never launches lanes"
    )
    lanes_plan.add_argument("--plan", default=None, help="Path to the plan markdown file")
    lanes_plan.add_argument("--timings", default=None, help="Optional bounded timings JSON file")
    lanes_plan.add_argument("--risk", choices=("low", "standard", "high"), default="standard")
    lanes_plan.add_argument("--json", action="store_true")
    lanes_plan.set_defaults(func=cmd_lanes)

    route_worker = sub.add_parser(
        "route-worker",
        help="Inspect a deterministic native/optional-Grok worker recommendation",
    )
    route_worker.add_argument("--host", choices=("codex", "claude"), required=True)
    route_worker.add_argument("--execution-reasoning", choices=("low", "medium", "high"), required=True)
    route_worker.add_argument("--review-risk", choices=("low", "standard", "high"), required=True)
    route_worker.add_argument("--driver-effort", choices=("low", "medium", "high"))
    route_worker.add_argument("--provider", choices=("auto", "native", "grok"))
    route_worker.add_argument("--effort", choices=("low", "medium", "high"))
    route_worker.add_argument("--prewalk", choices=("off", "auto", "required"))
    route_worker.add_argument("--guide-model")
    route_worker.add_argument("--guide-effort", choices=("low", "medium", "high"))
    route_worker.add_argument(
        "--probe-prewalk",
        action="store_true",
        help="Probe installed native help/version only; never launches inference",
    )
    route_worker.add_argument(
        "--prewalk-capability-evidence",
        help="Version-bound behavioral qualification artifact; requires --probe-prewalk",
    )
    route_worker.add_argument("--allow-grok", action="store_true")
    route_worker.add_argument("--prohibit-grok", action="store_true")
    route_worker.add_argument("--repo-root", default=".", help="Target repository used for policy/default discovery")
    route_worker.add_argument("--repo-policy", help="Explicit repository policy JSON/TOML override (tests/operators)")
    route_worker.add_argument("--grok-installed", action="store_true")
    route_worker.add_argument("--grok-authenticated", action="store_true")
    route_worker.add_argument("--grok-model", action="append")
    route_worker.add_argument("--grok-default-model")
    route_worker.add_argument(
        "--grok-worker-model",
        help="Explicit catalog-returned Grok model to select instead of the live default",
    )
    route_worker.add_argument("--grok-goal-advertised", action="store_true")
    route_worker.add_argument(
        "--grok-goal-behavioral-evidence",
        help=(
            "Path to a bounded JSON terminal-canary artifact; requires --probe-grok "
            "and must match the installed version/build"
        ),
    )
    route_worker.add_argument(
        "--grok-prewalk-qualification",
        help=(
            "Path to a bounded JSON grok prewalk qualification artifact "
            "(artifact_type grok_prewalk_qualification_canary); validated "
            "fail-closed against the installed version/build from --probe-grok, "
            "never fabricated"
        ),
    )
    route_worker.add_argument("--grok-version")
    route_worker.add_argument("--probe-grok", action="store_true", help="Safely probe installed Grok flags, live catalog/default, ACP, and optional isolated goal evidence")
    route_worker.add_argument("--grok-executable", default="grok")
    route_worker.add_argument("--json", action="store_true")
    route_worker.set_defaults(func=cmd_route_worker)

    native_worker = sub.add_parser(
        "native-worker",
        help="Build a separate exact-session Codex or Claude worker launch specification",
    )
    native_worker.add_argument(
        "native_worker_action",
        nargs="?",
        choices=("spec", "launch", "follow", "status", "prewalk-capabilities", "_supervise"),
        default="spec",
    )
    native_worker.add_argument("--host", choices=("codex", "claude", "fixture", "grok"))
    native_worker.add_argument("--worktree")
    native_worker.add_argument("--effort", choices=("low", "medium", "high"))
    native_worker.add_argument("--model", help="Current driver model observed by the host, or an explicit routed model")
    native_worker.add_argument("--prewalk", choices=("off", "auto", "required"), default="off")
    native_worker.add_argument("--guide-model")
    native_worker.add_argument("--guide-effort", choices=("low", "medium", "high"))
    native_worker.add_argument("--execution-model")
    native_worker.add_argument("--execution-effort", choices=("low", "medium", "high"))
    native_worker.add_argument("--todo-limit", type=int, default=10)
    native_worker.add_argument("--prewalk-capability-evidence")
    native_worker.add_argument("--forbidden-path", action="append")
    native_worker.add_argument("--session-id")
    native_worker.add_argument("--repo-root", default=".")
    native_worker.add_argument("--run-id")
    native_worker.add_argument("--packet")
    native_worker.add_argument("--fixture-script", help="Explicit no-model subprocess fixture (tests only)")
    native_worker.add_argument("--execution-fixture-script", help="Second no-model subprocess fixture for prewalk lifecycle tests")
    native_worker.add_argument("--host-view-visible", action="store_true", help="Record a capability-proven user-visible native host agent view")
    native_worker.add_argument("--no-wait", action="store_true", help="For follow: print currently available lines and return")
    native_worker.add_argument("--json", action="store_true")
    native_worker.set_defaults(func=cmd_native_worker)

    validate = sub.add_parser(
        "validate-config",
        help="Resolve role routes with provenance; no model inference or repo mutation",
    )
    _add_common_flags(validate)
    validate.set_defaults(func=cmd_validate_config)

    doctor = sub.add_parser(
        "doctor",
        help="Read-only adapter/capability inventory; never launches model turns",
    )
    _add_common_flags(doctor)
    doctor.set_defaults(func=cmd_doctor)

    setup = sub.add_parser(
        "setup",
        help="Inventory tools and write local ignored .elves/models.toml (no secrets)",
    )
    _add_common_flags(setup)
    setup.add_argument("--implement", default=None, help="Profile for implement role")
    setup.add_argument("--review", default=None, help="Profile for review role")
    setup.add_argument("--planning", default=None, help="Profile for planning role")
    setup.add_argument(
        "--lightweight-review",
        default=None,
        help="Profile for lightweight_review role",
    )
    setup.add_argument("--validate", default=None, help="Profile for validate role")
    setup.add_argument("--synthesize", default=None, help="Profile for synthesize role")
    setup.add_argument("--scout", default=None, help="Profile for scout role")
    setup.add_argument(
        "--required",
        default=None,
        help="Comma-separated roles that are required (explicit opt-in; omit to preserve existing)",
    )
    setup.add_argument(
        "--session-mode",
        default=None,
        choices=["ephemeral", "persistent", "exact_resume"],
        help="Default session mode preference (omit to preserve existing)",
    )
    setup.add_argument(
        "--sharing-policy",
        default=None,
        help="models.toml sharing policy (omit to preserve existing; local-only for new config)",
    )
    setup.add_argument(
        "--no-native-fallback",
        action="store_true",
        help="Do not auto-add host-native fallbacks for external profiles",
    )
    setup.add_argument(
        "--dry-run",
        action="store_true",
        help="Inventory and recommendations only; do not write models.toml",
    )
    setup.add_argument(
        "--force",
        action="store_true",
        help="Overwrite models.toml even when unknown sections exist",
    )
    setup.add_argument(
        "--smoke",
        action="store_true",
        help="Opt into smoke acknowledgment (still does not print secrets or require paid turns)",
    )
    setup.add_argument(
        "--reset-roles",
        action="store_true",
        help="Reset unspecified roles to host-native instead of merging into existing models.toml",
    )
    setup.set_defaults(func=cmd_setup)

    onboard = sub.add_parser(
        "onboard",
        help="Model onboarding: plan interview, show/apply routes, probe (Claude Code + Codex)",
    )
    _add_common_flags(onboard)
    onboard_sub = onboard.add_subparsers(dest="onboard_action", required=True)

    onboard_plan = onboard_sub.add_parser(
        "plan",
        help="Emit interview packet (inventory, env presence, purpose questions)",
    )
    _add_common_flags(onboard_plan)
    onboard_plan.set_defaults(func=cmd_onboard, onboard_action="plan")

    onboard_show = onboard_sub.add_parser(
        "show",
        help="Show current role→route map from ignored models.toml",
    )
    _add_common_flags(onboard_show)
    onboard_show.set_defaults(func=cmd_onboard, onboard_action="show")

    onboard_apply = onboard_sub.add_parser(
        "apply",
        help="Write role preferences to ignored .elves/models.toml (same as setup)",
    )
    _add_common_flags(onboard_apply)
    onboard_apply.add_argument("--implement", default=None)
    onboard_apply.add_argument("--review", default=None)
    onboard_apply.add_argument("--planning", default=None)
    onboard_apply.add_argument("--lightweight-review", default=None)
    onboard_apply.add_argument("--validate", default=None)
    onboard_apply.add_argument("--synthesize", default=None)
    onboard_apply.add_argument("--scout", default=None)
    onboard_apply.add_argument(
        "--required",
        default=None,
        help="Comma-separated roles marked required (omit to preserve existing required flags)",
    )
    onboard_apply.add_argument("--dry-run", action="store_true")
    onboard_apply.add_argument("--force", action="store_true")
    onboard_apply.add_argument("--smoke", action="store_true")
    onboard_apply.add_argument(
        "--reset-roles",
        action="store_true",
        help="Reset unspecified roles to host-native instead of merging into existing models.toml",
    )
    onboard_apply.set_defaults(func=cmd_onboard, onboard_action="apply")

    onboard_probe = onboard_sub.add_parser(
        "probe",
        help="Structural probes for configured routes; optional --smoke (host executor)",
    )
    _add_common_flags(onboard_probe)
    onboard_probe.add_argument(
        "--smoke",
        action="store_true",
        help="Request live smoke (needs host smoke_executor; never prints secrets)",
    )
    onboard_probe.set_defaults(func=cmd_onboard, onboard_action="probe")

    council = sub.add_parser(
        "council",
        help="Parallel read-only council fan-out; host owns fitted synthesis",
    )
    _add_common_flags(council)
    council.add_argument("--task", required=True, help="Task text for every independent lane")
    council.add_argument(
        "--roles",
        default="architect,skeptic,tester",
        help="Comma-separated lens role names (default: architect,skeptic,tester)",
    )
    council.add_argument("--phase", default="review", help="Phase label for artifacts/quorum")
    council.add_argument(
        "--phase-required",
        action="store_true",
        help="Treat phase as required=true (enables required_quorum)",
    )
    council.add_argument("--target-quorum", type=int, default=None, help="Advisory quorum")
    council.add_argument(
        "--required-quorum",
        type=int,
        default=None,
        help="Hard quorum when --phase-required is set",
    )
    council.add_argument("--timeout", type=float, default=30.0, help="Per-lane timeout seconds")
    council.add_argument("--plan-path", default=None, help="Optional plan path for packets")
    council.add_argument("--head", default=None, help="Optional HEAD sha for packets")
    council.add_argument(
        "--use-resolved-routes",
        action="store_true",
        help="Use resolved review/planning profile adapters (may require external CLIs)",
    )
    council.set_defaults(func=cmd_council)

    light = sub.add_parser(
        "lightweight-review",
        help="Single bounded utility review; not a council vote",
    )
    _add_common_flags(light)
    light.add_argument("--task", required=True, help="Utility review task")
    light.add_argument("--adapter", default="host-native", help="Adapter name")
    light.add_argument("--profile", default="host-native", help="Profile name")
    light.add_argument("--executable", default=None, help="Optional executable override")
    light.add_argument("--model", default=None, help="Optional requested model")
    light.add_argument("--timeout", type=float, default=30.0, help="Timeout seconds")
    light.add_argument("--head", default=None, help="Optional HEAD sha for packets")
    light.set_defaults(func=cmd_lightweight_review)

    session = sub.add_parser(
        "session",
        help="Exact persistent session registry helpers (list|probe|resume)",
    )
    session_sub = session.add_subparsers(dest="session_action", required=True)

    session_list = session_sub.add_parser("list", help="List registry sessions")
    _add_common_flags(session_list)
    session_list.set_defaults(func=cmd_session)

    session_probe = session_sub.add_parser("probe", help="Probe one exact session id")
    _add_common_flags(session_probe)
    session_probe.add_argument("--session-id", required=True, help="Exact session id")
    session_probe.set_defaults(func=cmd_session)

    session_resume = session_sub.add_parser(
        "resume",
        help="Build exact resume argv (does not launch models)",
    )
    _add_common_flags(session_resume)
    session_resume.add_argument("--session-id", required=True, help="Exact session id")
    session_resume.add_argument(
        "--adapter",
        default="claude-code",
        help=(
            "Adapter name (default: claude-code; must match the registered harness, "
            "so pass an explicit adapter for non-Claude sessions)"
        ),
    )
    session_resume.add_argument("--profile", default=None, help="Profile name")
    session_resume.add_argument("--executable", default=None, help="Executable override")
    session_resume.add_argument("--model", default=None, help="Requested/actual model observation")
    session_resume.add_argument("--cwd", default=None, help="Verified CWD observation")
    session_resume.add_argument(
        "--worktree",
        default=None,
        help="Verified worktree observation (required with --require-write)",
    )
    session_resume.add_argument(
        "--parent-id",
        default=None,
        dest="parent_id",
        help="Observed parent session id (required with --require-write)",
    )
    session_resume.add_argument(
        "--source-head",
        default=None,
        dest="source_head",
        help="Observed source HEAD (required with --require-write)",
    )
    session_resume.add_argument(
        "--require-write",
        action="store_true",
        help="Fail closed unless flag/probe observations pass exact registry continuity",
    )
    session_resume.set_defaults(func=cmd_session)

    worker = sub.add_parser(
        "worker",
        help="Single external writer lease lifecycle (host-owned import)",
    )
    worker_sub = worker.add_subparsers(dest="worker_action", required=True)

    w_prepare = worker_sub.add_parser("prepare", help="Create exclusive writer lease after preflight")
    _add_common_flags(w_prepare)
    w_prepare.add_argument("--lease-id", required=True)
    w_prepare.add_argument("--host-checkout", required=True)
    w_prepare.add_argument("--worker-checkout", required=True)
    w_prepare.add_argument("--session-id", required=True)
    w_prepare.add_argument("--base-head", required=True)
    w_prepare.add_argument("--adapter", default="grok-build")
    w_prepare.add_argument("--profile", default="grok-build-write")
    w_prepare.add_argument("--sandbox-profile", default="devbox")
    w_prepare.add_argument("--allowed-path", action="append", default=[])
    w_prepare.add_argument(
        "--grant-env",
        action="append",
        default=[],
        help=(
            "Launch-scoped credential grant by NAME only; repeat the exact names "
            "and values for worker audit (never KEY=VALUE)"
        ),
    )
    w_prepare.add_argument("--grok-version", default="0.2.93")
    w_prepare.add_argument(
        "--unqualified",
        action="store_true",
        help="Mark write profile unqualified (should fail)",
    )
    w_prepare.add_argument(
        "--qualification-file",
        default=None,
        help="Host-owned private qualification evidence JSON (required for prepare)",
    )
    w_prepare.add_argument(
        "--qualification-id",
        default=None,
        help="Host-owned qualification registry id under store-owned snapshot path",
    )
    w_prepare.set_defaults(func=cmd_worker)

    w_audit = worker_sub.add_parser("audit", help="Post-turn audit of worker checkout")
    _add_common_flags(w_audit)
    w_audit.add_argument("--lease-id", required=True)
    w_audit.add_argument(
        "--grant-env",
        action="append",
        default=[],
        help=(
            "Exact prepare-time credential grant NAME set; current values must "
            "match private prepare authority (never KEY=VALUE)"
        ),
    )
    w_audit.add_argument(
        "--observed-command",
        action="append",
        default=[],
        help="Command observed during the turn (repeatable)",
    )
    w_audit.set_defaults(func=cmd_worker)

    w_export = worker_sub.add_parser(
        "export",
        help="Export binary patches and optional host apply --check",
    )
    _add_common_flags(w_export)
    w_export.add_argument("--lease-id", required=True)
    w_export.add_argument("--output-dir", required=True)
    w_export.add_argument(
        "--host-apply-check",
        action="store_true",
        help="Run git apply --check --index on host checkout",
    )
    w_export.set_defaults(func=cmd_worker)

    w_import = worker_sub.add_parser(
        "import",
        help="Apply the descriptor-verified audited bundle to the clean host",
    )
    _add_common_flags(w_import)
    w_import.add_argument("--lease-id", required=True)
    w_import.set_defaults(func=cmd_worker)

    w_refresh = worker_sub.add_parser(
        "refresh",
        help="After integration, move clean detached worker to new host tip",
    )
    _add_common_flags(w_refresh)
    w_refresh.add_argument("--lease-id", required=True)
    w_refresh.add_argument("--new-tip", required=True)
    w_refresh.set_defaults(func=cmd_worker)

    w_packet = worker_sub.add_parser(
        "packet",
        help="Emit write-task packet JSON for an existing lease",
    )
    _add_common_flags(w_packet)
    w_packet.add_argument("--lease-id", required=True)
    w_packet.add_argument("--task", required=True)
    w_packet.set_defaults(func=cmd_worker)

    implement = sub.add_parser(
        "implement",
        help=(
            "Optional external implementer: trusted full-run-prepare/launch/monitor/await/reconcile/logs/stop "
            "or legacy bounded prepare/launch/gate/resume-batch/status; Grok Build or OpenCode"
        ),
    )
    implement_sub = implement.add_subparsers(dest="implement_action", required=True)

    i_fr_prepare = implement_sub.add_parser(
        "full-run-prepare",
        help="Prepare trusted full-run supervisor artifacts for one exact session",
    )
    _add_common_flags(i_fr_prepare)
    i_fr_prepare.add_argument("--session-id", required=True)
    i_fr_prepare.add_argument("--branch", required=True)
    i_fr_prepare.add_argument("--start-head", required=True)
    i_fr_prepare.add_argument("--packet", required=True, help="Path to full-run packet")
    i_fr_prepare.add_argument(
        "--session",
        default=None,
        help=(
            "Canonical .elves-session.json; defaults to the repo-root file for "
            "production and is validated before any worker state is created"
        ),
    )
    i_fr_prepare.add_argument(
        "--plan",
        default=None,
        help="Optional equality assertion against the session plan_path",
    )
    i_fr_prepare.add_argument(
        "--adapter",
        default="grok-build",
        help="grok-build (default), devin-cli, or fixture (explicit test mode only)",
    )
    i_fr_prepare.add_argument(
        "--model",
        default="auto",
        help="Catalog-returned model id, or auto for preferred grok-4.5 / non-retired live default",
    )
    i_fr_prepare.add_argument("--permission-mode", default="auto")
    i_fr_prepare.add_argument(
        "--effort",
        # None means "not explicitly requested": prepare_full_run resolves the
        # adapter default, and a resume without --effort keeps the originally
        # persisted value instead of flipping to the current default.
        default=None,
        help=(
            "Worker effort (Grok Build defaults to high, its highest supported "
            "level; other adapters keep their own balanced default)"
        ),
    )
    i_fr_prepare.add_argument(
        "--grok-goal-behavioral-evidence",
        default=None,
        help=(
            "Path to a bounded terminal `/goal <objective>` JSON canary artifact; "
            "omit to use the one-packet fallback"
        ),
    )
    i_fr_prepare.add_argument(
        "--executable",
        default=None,
        help="CLI executable (default: grok; fixture mode uses python3)",
    )
    i_fr_prepare.add_argument("--worktree", default=None)
    i_fr_prepare.add_argument("--check", action="store_true")
    i_fr_prepare.add_argument("--max-turns", type=int, default=80)
    i_fr_prepare.add_argument(
        "--resume",
        action="store_true",
        help="Prepare for resume (exact --resume) instead of create (--session-id)",
    )
    i_fr_prepare.add_argument(
        "--fixture-script",
        default=None,
        help="Explicit test fixture script (only with --adapter fixture)",
    )
    i_fr_prepare.add_argument(
        "--grant-env",
        action="append",
        default=[],
        help="Credential grant by NAME only (value from private env; never KEY=VALUE)",
    )
    i_fr_prepare.set_defaults(func=cmd_implement)

    i_fr_launch = implement_sub.add_parser(
        "full-run-launch",
        help="Background-launch Grok (or explicit fixture) for one exact session",
    )
    _add_common_flags(i_fr_launch)
    i_fr_launch.add_argument("--session-id", required=True)
    i_fr_launch.add_argument(
        "--resume",
        action="store_true",
        help="Force resume argv (--resume) even if prepare stored create=true",
    )
    i_fr_launch.add_argument(
        "--grant-env",
        action="append",
        default=[],
        help="Credential grant by NAME only (never KEY=VALUE on argv)",
    )
    i_fr_launch.add_argument(
        "--grant-grok-auth",
        action="store_true",
        help=(
            "Trusted Lane A only: isolated credential-free Grok probe plus one "
            "exact bound native executable + ancestor chain and validated host auth.json "
            "(owner/mode/ancestor/ACL) through native GROK_AUTH_PATH"
        ),
    )
    i_fr_launch.add_argument(
        "--grant-devin-auth",
        action="store_true",
        help=(
            "Trusted Lane A only: project validated host Devin CLI config and "
            "credentials into the isolated worker HOME (XDG_CONFIG_HOME/XDG_DATA_HOME)"
        ),
    )
    i_fr_launch.add_argument(
        "--grant-github-push",
        action="store_true",
        help=(
            "Trusted Lane A only: project the authenticated host gh token into "
            "the isolated worker through a launch-scoped Git credential helper"
        ),
    )
    i_fr_launch.set_defaults(func=cmd_implement)

    i_fr_monitor = implement_sub.add_parser(
        "full-run-monitor",
        help="Classify full-run health (healthy/complete/failed/blocked/stale)",
    )
    _add_common_flags(i_fr_monitor)
    i_fr_monitor.add_argument("--session-id", required=True)
    i_fr_monitor.add_argument(
        "--stale-after",
        type=int,
        default=300,
        help="Seconds without heartbeat before stale (default: 300)",
    )
    i_fr_monitor.add_argument(
        "--ack-high-risk-checkpoint",
        default=None,
        help="Acknowledge the exact pending staged checkpoint after host review",
    )
    i_fr_monitor.add_argument(
        "--full",
        action="store_true",
        help="Force full remote-ref audit and deep reconciliation depth",
    )
    i_fr_monitor.add_argument(
        "--wait",
        action="store_true",
        help="Alias: block like full-run-await until a material transition",
    )
    i_fr_monitor.set_defaults(func=cmd_implement)

    i_fr_await = implement_sub.add_parser(
        "full-run-await",
        help=(
            "Block until material progress while following a sanitized worker stream "
            "(default; no model inference). Use --quiet to park silently."
        ),
    )
    _add_common_flags(i_fr_await)
    i_fr_await.add_argument("--session-id", required=True)
    i_fr_await.add_argument(
        "--stale-after",
        type=int,
        default=300,
        help="Seconds without heartbeat before stale (default: 300)",
    )
    i_fr_await.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Optional max seconds to block before returning current status",
    )
    i_fr_await.add_argument(
        "--ack-high-risk-checkpoint",
        default=None,
        help="Acknowledge the exact pending staged checkpoint after host review",
    )
    i_fr_await.add_argument(
        "--quiet",
        action="store_true",
        help="Quiet opt-out: park without emitting the live follow stream",
    )
    i_fr_await.add_argument(
        "--no-follow",
        action="store_true",
        help="Alias for --quiet: disable default sanitized follow stream",
    )
    i_fr_await.set_defaults(func=cmd_implement)

    i_fr_reconcile = implement_sub.add_parser(
        "full-run-reconcile",
        help="Host-reconstruct a missing trusted report from independently proved facts",
    )
    _add_common_flags(i_fr_reconcile)
    i_fr_reconcile.add_argument("--session-id", required=True)
    i_fr_reconcile.add_argument(
        "--host-tests-pass",
        action="store_true",
        help="Explicitly attest that host-run acceptance tests passed",
    )
    i_fr_reconcile.set_defaults(func=cmd_implement)

    i_fr_logs = implement_sub.add_parser(
        "full-run-logs",
        help="Bounded events; opt-in raw transcript tail only with --raw-tail",
    )
    _add_common_flags(i_fr_logs)
    i_fr_logs.add_argument("--session-id", required=True)
    i_fr_logs.add_argument("--raw-tail", action="store_true")
    i_fr_logs.add_argument("--tail", type=int, default=40)
    i_fr_logs.set_defaults(func=cmd_implement)

    i_fr_stop = implement_sub.add_parser(
        "full-run-stop",
        help="Terminate the recorded full-run process group",
    )
    _add_common_flags(i_fr_stop)
    i_fr_stop.add_argument("--session-id", required=True)
    i_fr_stop.set_defaults(func=cmd_implement)

    i_rollback = implement_sub.add_parser(
        "rollback-ref",
        help="Create a collision-safe host rollback ref; optionally push it",
    )
    _add_common_flags(i_rollback)
    i_rollback.add_argument("--run-id", required=True)
    i_rollback.add_argument("--session-id", required=True)
    i_rollback.add_argument("--batch", type=_nonnegative_batch_arg, required=True)
    i_rollback.add_argument("--head", default=None)
    i_rollback.add_argument("--push", action="store_true")
    i_rollback.add_argument("--remote", default="origin")
    i_rollback.set_defaults(func=cmd_implement)

    i_prepare = implement_sub.add_parser(
        "prepare",
        help="Record implementer metadata under .elves/runtime/implement/ (no network)",
    )
    _add_common_flags(i_prepare)
    i_prepare.add_argument(
        "--worktree",
        default=None,
        help="Implementer worktree path (default: repo root)",
    )
    i_prepare.add_argument("--branch", default=None, help="Feature branch name")
    i_prepare.add_argument(
        "--session-id",
        default=None,
        help="Optional exact session id (Grok or OpenCode; never latest/continue)",
    )
    i_prepare.add_argument(
        "--adapter",
        default="grok-build",
        help="Implementer adapter: grok-build (default) or opencode-cli",
    )
    i_prepare.add_argument(
        "--model",
        default=None,
        help=(
            "Default model (Grok: auto for preferred grok-4.5 when live, or an exact catalog id; "
            "OpenCode: provider/model e.g. openrouter/qwen/qwen3-max)"
        ),
    )
    i_prepare.add_argument(
        "--lane",
        default="fast",
        choices=["fast", "untrusted"],
        help="implementation_lane (default: fast)",
    )
    i_prepare.add_argument(
        "--git-mode",
        default="branch_progress",
        help="Git ownership mode (default: branch_progress)",
    )
    i_prepare.add_argument(
        "--permission-mode",
        default="auto",
        help="Grok permission mode (default: auto; never dontAsk)",
    )
    i_prepare.add_argument(
        "--executable",
        default=None,
        help="CLI executable (default: grok or opencode based on --adapter)",
    )
    i_prepare.set_defaults(func=cmd_implement)

    i_launch = implement_sub.add_parser(
        "launch",
        help="Emit exact implementer argv (print-only by default; --exec optional)",
    )
    _add_common_flags(i_launch)
    i_launch.add_argument(
        "--session-id",
        default=None,
        help="Exact session id (required unless prepare already recorded one)",
    )
    i_launch.add_argument(
        "--packet",
        required=True,
        help="Path to batch packet (--prompt-file)",
    )
    i_launch.add_argument(
        "--cwd",
        default=None,
        help="Worktree / CWD for grok (alias: --worktree)",
    )
    i_launch.add_argument(
        "--worktree",
        default=None,
        help="Alias for --cwd",
    )
    i_launch.add_argument(
        "--model",
        default=None,
        help="Model (default: prepare state or authenticated Grok live default)",
    )
    i_launch.add_argument(
        "--effort",
        default=None,
        help="Grok --effort/--reasoning-effort (default: high)",
    )
    i_launch.add_argument(
        "--check",
        action="store_true",
        help="Pass Grok --check for post-work verification (higher latency; Grok only)",
    )
    i_launch.add_argument(
        "--permission-mode",
        default=None,
        help="Permission mode (default: auto; never dontAsk)",
    )
    i_launch.add_argument(
        "--executable",
        default=None,
        help="CLI executable (default: grok)",
    )
    i_launch.add_argument(
        "--batch",
        type=_nonnegative_batch_arg,
        default=None,
        help="Optional batch number to record in state",
    )
    i_launch.add_argument(
        "--create",
        action="store_true",
        help="Use --session-id (create) instead of --resume",
    )
    i_launch.add_argument(
        "--exec",
        action="store_true",
        help=(
            "Request bounded spawn; fails closed unless a qualified recursive "
            "boundary exists (default: print argv only)"
        ),
    )
    i_launch.set_defaults(func=cmd_implement)

    i_gate = implement_sub.add_parser(
        "gate",
        help="Run tests, record tip + counts under gates/batch-N.json",
    )
    _add_common_flags(i_gate)
    i_gate.add_argument(
        "--batch",
        type=_nonnegative_batch_arg,
        required=True,
        help="Batch number (0/B0 and B1+ are equivalent)",
    )
    i_gate.add_argument(
        "--focused",
        action="store_true",
        help="Run focused implement unit tests only",
    )
    i_gate.add_argument(
        "--cwd",
        default=None,
        help="CWD for test run (default: repo root)",
    )
    i_gate.set_defaults(func=cmd_implement)

    i_resume = implement_sub.add_parser(
        "resume-batch",
        help="Print launch argv for next batch packet (same session)",
    )
    _add_common_flags(i_resume)
    i_resume.add_argument(
        "--batch",
        type=_nonnegative_batch_arg,
        required=True,
        help="Next batch number (0/B0 and B1+ are equivalent)",
    )
    i_resume.add_argument(
        "--packet",
        required=True,
        help="Path to next batch packet",
    )
    i_resume.add_argument("--session-id", default=None, help="Exact session id")
    i_resume.add_argument("--cwd", default=None, help="Worktree / CWD")
    i_resume.add_argument("--worktree", default=None, help="Alias for --cwd")
    i_resume.add_argument(
        "--model",
        default=None,
        help="Model override (Grok aliases: fast, deep)",
    )
    i_resume.add_argument(
        "--effort",
        default=None,
        help="Grok --effort override",
    )
    i_resume.add_argument(
        "--check",
        action="store_true",
        help="Pass Grok --check (Grok only)",
    )
    i_resume.add_argument(
        "--permission-mode",
        default=None,
        help="Permission mode (default: auto)",
    )
    i_resume.add_argument("--executable", default=None, help="CLI executable")
    i_resume.add_argument(
        "--exec",
        action="store_true",
        help=(
            "Request bounded spawn; fails closed unless a qualified recursive "
            "boundary exists (default: print argv only)"
        ),
    )
    i_resume.set_defaults(func=cmd_implement)

    i_status = implement_sub.add_parser(
        "status",
        help="Show implement runtime state if present",
    )
    _add_common_flags(i_status)
    i_status.set_defaults(func=cmd_implement)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(argv) if argv is not None else list(sys.argv[1:])
    args = parser.parse_args(raw_argv)
    try:
        return int(args.func(args))
    except StorageError as error:
        command = str(getattr(args, "command", "cobbler"))
        return _emit_storage_error(args, error, command=command)


if __name__ == "__main__":
    raise SystemExit(main())
