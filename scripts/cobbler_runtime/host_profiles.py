"""Single host-profile registry for native-worker transports.

One table owns the per-host launch grammar (create/resume argv builders and
effort flag grammar), transport name, identity event types and source,
provider-secret allowlist, help-probe argv, and commit mode.  It is consumed
by ``native_worker`` (spec construction, child-env secrets, identity
readiness), ``prewalk`` (advertised/probe capabilities), and
``worker_routing`` (transport naming) so no host ``if/elif`` chain exists at
those call sites.  New hosts become table rows, not new branches.

This module intentionally imports only :mod:`cobbler_runtime.schema` so every
runtime consumer can depend on it without an import cycle.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .schema import AMBIGUOUS_SESSION_TOKENS, ValidationIssue


def normalize_host_token(host: str) -> str:
    return host.strip().lower().replace("_", "-")


def exact_session_id(session_id: str) -> str:
    """Reject empty, ambiguous, and dash-leading worker session ids."""
    value = session_id.strip()
    if not value or value.lower() in AMBIGUOUS_SESSION_TOKENS or value.startswith("-"):
        raise ValidationIssue("invalid_exact_session_id", "An exact worker session id is required")
    return value


@dataclass(frozen=True)
class HostLaunchRequest:
    """Validated inputs one host profile turns into concrete launch argv."""

    effort: str
    requested_model: str
    cwd: str
    git_write_roots: tuple[str, ...]
    session_id: str | None
    fixture_script: Path | None


@dataclass(frozen=True)
class HostLaunchPlan:
    """Concrete argv product of one host profile for one launch request."""

    argv: tuple[str, ...]
    resume_argv: tuple[str, ...] | None
    session_id: str | None
    session_id_source: str
    stdin_packet: bool
    prompt_file_flag: str | None = None


def _codex_launch_plan(request: HostLaunchRequest) -> HostLaunchPlan:
    common = [
        "codex", "exec", "--json", "--ignore-user-config", "--ignore-rules",
        "--sandbox", "workspace-write", "-c", f'model_reasoning_effort="{request.effort}"',
    ]
    for root in request.git_write_roots:
        common.extend(["--add-dir", root])
    common.extend(["--model", request.requested_model])
    if request.session_id is None:
        argv: tuple[str, ...] = (*common, "-C", request.cwd, "-")
        resume = None
    else:
        sid = exact_session_id(request.session_id)
        # Keep exec-level sandbox and additional-write-root options before
        # the resume subcommand. The supervisor binds the exact OS cwd.
        argv = tuple(common + ["resume", sid, "-"])
        resume = argv
    return HostLaunchPlan(
        argv=argv,
        resume_argv=resume,
        session_id=request.session_id,
        session_id_source="thread.started.thread_id",
        stdin_packet=True,
    )


def _claude_launch_plan(request: HostLaunchRequest) -> HostLaunchPlan:
    common = [
        "claude", "--safe-mode", "--print", "--verbose",
        "--output-format", "stream-json", "--input-format", "text",
        "--effort", request.effort, "--permission-mode", "auto",
    ]
    for root in request.git_write_roots:
        common.extend(["--add-dir", root])
    common.extend(["--model", request.requested_model])
    if request.session_id is None:
        # Claude accepts a caller-generated UUID, providing exact identity before launch.
        sid = str(uuid.uuid4())
        argv = tuple(common + ["--session-id", sid])
        resume = None
    else:
        sid = exact_session_id(request.session_id)
        argv = tuple(common + ["--resume", sid])
        resume = argv
    return HostLaunchPlan(
        argv=argv,
        resume_argv=resume,
        session_id=sid,
        session_id_source="requested_session_id",
        stdin_packet=True,
    )


def _fixture_launch_plan(request: HostLaunchRequest) -> HostLaunchPlan:
    if request.fixture_script is None:
        raise ValidationIssue("fixture_script_required", "Fixture native worker requires --fixture-script")
    sid = (
        exact_session_id(request.session_id)
        if request.session_id
        else f"fixture-{hashlib.sha256(str(request.fixture_script).encode()).hexdigest()[:16]}"
    )
    argv = (sys.executable, str(request.fixture_script.resolve(strict=True)))
    return HostLaunchPlan(
        argv=argv,
        resume_argv=None,
        session_id=sid,
        session_id_source="fixture_session_id",
        stdin_packet=True,
    )


def _grok_launch_plan(request: HostLaunchRequest) -> HostLaunchPlan:
    """Non-yolo Grok Build prewalk-lane grammar (verified against 0.2.102).

    Never ``--always-approve``, never ``--yolo``, never any ``dontAsk``
    surface on this lane: ``--permission-mode auto`` fails closed headless.
    The packet is delivered via the ``--prompt-file`` surface (the same flag
    the trusted full-run lane in ``implement.build_launch_argv`` uses), so
    the spec carries no stdin packet.
    """
    route = (
        "--model", request.requested_model,
        "--effort", request.effort,
        "--permission-mode", "auto",
        "--output-format", "streaming-json",
    )
    if request.session_id is None:
        # Caller-generated UUID identity (claude-style), recorded before launch.
        sid = str(uuid.uuid4())
        argv: tuple[str, ...] = ("grok", "--session-id", sid, "--cwd", request.cwd, *route)
        resume = None
    else:
        sid = exact_session_id(request.session_id)
        # Exact resume only; model/effort route override applies on resume and
        # the sandbox (including --cwd) is resume-sticky from create.
        argv = ("grok", "--resume", sid, *route)
        resume = argv
    return HostLaunchPlan(
        argv=argv,
        resume_argv=resume,
        session_id=sid,
        session_id_source="requested_session_id",
        stdin_packet=False,
        prompt_file_flag="--prompt-file",
    )


def _codex_help_grammar(create_help: str, resume_help: str) -> tuple[bool, bool]:
    exact = "resume" in create_help and "SESSION_ID" in resume_help.upper()
    config_override = ("--config" in create_help or "-c" in create_help) and (
        "--config" in resume_help or "-c" in resume_help
    )
    route = "--model" in create_help and "--model" in resume_help and config_override
    return exact, route


def _flagged_session_help_grammar(create_help: str, resume_help: str) -> tuple[bool, bool]:
    """Shared grammar for hosts advertising --session-id/--resume/--model/--effort."""
    exact = "--session-id" in create_help and "--resume" in resume_help
    route = "--model" in resume_help and "--effort" in resume_help
    return exact, route


@dataclass(frozen=True)
class HostProfile:
    """One native-worker host row: launch grammar, identity, secrets, probes."""

    host: str
    aliases: tuple[str, ...]
    capability_host: str
    transport: str
    spec_profile: str
    commit_mode: str
    effort_flag: str
    worktree_binding: str
    session_identity: str
    # Structured stdout event types (and candidate keys, in precedence order)
    # that may bind or challenge session identity for this host. Arbitrary
    # typed lines never bind identity.
    identity_event_keys: tuple[tuple[str, tuple[str, ...]], ...]
    # True when identity arrives only from the provider stream (codex); False
    # when the caller presets the exact session id before launch.
    identity_from_stream_required: bool
    provider_secret_names: frozenset[str]
    grants_git_write_roots: bool
    # Where this transport reports observed usage, if anywhere. Capability
    # metadata for the observed-usage ledger: a transport without a usage
    # surface stays literal "unobserved" — never estimated, never zero.
    reports_usage: str
    launch_plan: Callable[[HostLaunchRequest], HostLaunchPlan]
    # Installed-binary help probe (no model calls). None => not probeable.
    executable: str | None
    version_argv: tuple[str, ...]
    create_help_argv: tuple[str, ...]
    resume_help_argv: tuple[str, ...]
    help_grammar: Callable[[str, str], tuple[bool, bool]] | None
    # False => `native-worker launch` fails closed for this host until a
    # valid behavioral qualification artifact exists (grok stays gated off).
    launch_ready: bool


_CODEX_IDENTITY_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("thread.started", ("thread_id",)),
    ("turn.started", ("thread_id", "session_id")),
    ("turn.completed", ("thread_id", "session_id")),
)
_CLAUDE_IDENTITY_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("system", ("session_id",)),
)


HOST_PROFILES: tuple[HostProfile, ...] = (
    HostProfile(
        host="codex",
        aliases=("codex",),
        capability_host="codex",
        transport="codex_exec",
        spec_profile="elves-native-worker",
        commit_mode="sandboxed_worker_commit",
        effort_flag='-c model_reasoning_effort="<effort>"',
        worktree_binding="-C create; OS cwd resume",
        session_identity="thread.started.thread_id",
        identity_event_keys=_CODEX_IDENTITY_EVENTS,
        identity_from_stream_required=True,
        provider_secret_names=frozenset({"OPENAI_API_KEY", "CODEX_API_KEY"}),
        grants_git_write_roots=True,
        reports_usage="turn_completed_token_usage",
        launch_plan=_codex_launch_plan,
        executable="codex",
        version_argv=("--version",),
        create_help_argv=("exec", "--help"),
        resume_help_argv=("exec", "resume", "--help"),
        help_grammar=_codex_help_grammar,
        launch_ready=True,
    ),
    HostProfile(
        host="claude-code",
        aliases=("claude", "claude-code"),
        capability_host="claude",
        transport="claude_code",
        spec_profile="elves-native-worker",
        commit_mode="classifier_approved_worker_commit",
        effort_flag="--effort <effort>",
        worktree_binding="supervisor cwd or native isolated worktree",
        session_identity="caller-assigned UUID",
        identity_event_keys=_CLAUDE_IDENTITY_EVENTS,
        identity_from_stream_required=False,
        provider_secret_names=frozenset({"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}),
        grants_git_write_roots=True,
        reports_usage="stream_json_result_usage",
        launch_plan=_claude_launch_plan,
        executable="claude",
        version_argv=("--version",),
        create_help_argv=("--help",),
        resume_help_argv=("--help",),
        help_grammar=_flagged_session_help_grammar,
        launch_ready=True,
    ),
    HostProfile(
        host="fixture",
        aliases=("fixture",),
        capability_host="fixture",
        transport="fixture_process",
        spec_profile="elves-native-worker-fixture",
        commit_mode="fixture",
        effort_flag="none",
        worktree_binding="supervisor cwd",
        session_identity="caller-assigned fixture id",
        # The deterministic fixture keeps its current grammar: it replays both
        # native host identity vocabularies without a provider process.
        identity_event_keys=_CODEX_IDENTITY_EVENTS + _CLAUDE_IDENTITY_EVENTS,
        identity_from_stream_required=False,
        provider_secret_names=frozenset(),
        grants_git_write_roots=False,
        reports_usage="fixture_replay",
        launch_plan=_fixture_launch_plan,
        executable=None,
        version_argv=(),
        create_help_argv=(),
        resume_help_argv=(),
        help_grammar=None,
        launch_ready=True,
    ),
    HostProfile(
        host="grok",
        aliases=("grok", "grok-build"),
        capability_host="grok",
        transport="grok_build",
        spec_profile="elves-native-worker",
        commit_mode="permission_gated_worker_commit",
        effort_flag="--effort <effort>",
        worktree_binding="--cwd create; sandbox resume-sticky",
        session_identity="caller-assigned UUID",
        # The streaming JSON surface publishes sessionId only on the terminal
        # `end` event; the caller-preset UUID is the identity of record and
        # the end event may only confirm (or challenge) it.
        identity_event_keys=(("end", ("sessionId",)),),
        identity_from_stream_required=False,
        # API-key route only. GROK_AUTH_PATH is a host-owned isolation control
        # (context.ISOLATION_CONTROL_ENV_NAMES): the shared-OAuth route may
        # project it only through the provider_auth-validated flow used by the
        # trusted full-run lane, which is not wired at this seam yet.
        provider_secret_names=frozenset({"XAI_API_KEY"}),
        grants_git_write_roots=True,
        reports_usage="stream_usage_events",
        launch_plan=_grok_launch_plan,
        executable="grok",
        version_argv=("--version",),
        create_help_argv=("--help",),
        resume_help_argv=("--help",),
        help_grammar=_flagged_session_help_grammar,
        launch_ready=False,
    ),
)

_PROFILES_BY_TOKEN: dict[str, HostProfile] = {}
for _profile in HOST_PROFILES:
    for _token in (_profile.host, *_profile.aliases):
        _PROFILES_BY_TOKEN[_token] = _profile


def host_profile_or_none(host: str | None) -> HostProfile | None:
    if not host:
        return None
    return _PROFILES_BY_TOKEN.get(normalize_host_token(host))


def resolve_host_profile(host: str) -> HostProfile:
    profile = host_profile_or_none(host)
    if profile is None:
        raise ValidationIssue("unsupported_host", f"Unsupported native worker host `{host}`")
    return profile


def transport_for_host(host: str) -> str:
    return resolve_host_profile(host).transport


def provider_secret_names(host: str | None) -> frozenset[str]:
    profile = host_profile_or_none(host)
    return profile.provider_secret_names if profile else frozenset()


def identity_event_keys(host: str | None = None) -> dict[str, tuple[str, ...]]:
    """Per-host identity event map; ``None`` returns the cross-host union.

    The union exists only for callers that inspect a line without a bound
    host (diagnostics and tests). Supervised phases always pass the exact
    launch host so one host's identity vocabulary can never bind another's.
    """
    if host is not None:
        profile = host_profile_or_none(host)
        return dict(profile.identity_event_keys) if profile else {}
    merged: dict[str, tuple[str, ...]] = {}
    for profile in HOST_PROFILES:
        for event_type, keys in profile.identity_event_keys:
            existing = merged.get(event_type, ())
            merged[event_type] = existing + tuple(key for key in keys if key not in existing)
    return merged


def native_worker_profile_view() -> dict[str, dict[str, Any]]:
    """Semantically matched profile table view; syntax stays host-specific."""
    common = {
        "model_policy": "inherit_live_driver_model",
        "effort_policy": "plan_execution_reasoning",
        "separate_session": True,
        "full_packet": True,
        "visibility_ready": False,
        "visibility_mode": "commit_only",
        "worker_merge_authority": False,
        "cache_handoff": False,
    }
    view: dict[str, dict[str, Any]] = {}
    for profile in HOST_PROFILES:
        if profile.host == "fixture":
            continue
        view[profile.capability_host] = {
            **common,
            "transport": profile.transport,
            "worktree_binding": profile.worktree_binding,
            "session_identity": profile.session_identity,
            "commit_mode": profile.commit_mode,
            "launch_ready": profile.launch_ready,
        }
    return view
