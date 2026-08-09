"""Typed contracts for Cobbler external-agent configuration.

These types are provider-neutral. Personal model IDs must never appear as public
defaults; only harness profile names and capability language belong here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ConfigSource(str, Enum):
    """Where a resolved route value came from."""

    SURVIVAL_GUIDE = "survival_guide"
    LOCAL_MODELS_TOML = "local_models_toml"
    USER_CONFIG_JSON = "user_config_json"
    NATIVE_DEFAULT = "native_default"


class CapabilityStatus(str, Enum):
    """Lifecycle of a claimed capability."""

    UNKNOWN = "unknown"
    ADVERTISED = "advertised"
    QUALIFIED = "qualified"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class RoleName(str, Enum):
    """Configurable role slots for full-run routing."""

    PLANNING = "planning"
    IMPLEMENT = "implement"
    VALIDATE = "validate"
    REVIEW = "review"
    LIGHTWEIGHT_REVIEW = "lightweight_review"
    SYNTHESIZE = "synthesize"
    SCOUT = "scout"


class SessionMode(str, Enum):
    """Schema placeholders for later session runtime (Batch 3)."""

    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"
    EXACT_RESUME = "exact_resume"


class ContextSharingPolicy(str, Enum):
    """Schema placeholders for context isolation between lanes."""

    INDEPENDENT = "independent"
    SHARED_PACKET = "shared_packet"
    REHYDRATE_FROM_DISK = "rehydrate_from_disk"


class PrewalkMode(str, Enum):
    """Operator request for trajectory-preserving native-worker prewalk."""

    OFF = "off"
    AUTO = "auto"
    REQUIRED = "required"
    EXPERIMENTAL = "experimental"


class NativeWorkerPhaseRole(str, Enum):
    """Provider-neutral role of one child in a logical native-worker run."""

    GUIDE = "prewalk"
    EXECUTION = "execution"


class PrewalkInstructionFidelity(str, Enum):
    """What is actually known about the temporary guide instruction on resume."""

    PRUNED = "pruned"
    TURN_SCOPED = "turn_scoped"
    RETAINED_SAFE = "retained_safe"
    UNSUPPORTED = "unsupported"


class PrewalkCapabilityState(str, Enum):
    """Qualification layer for native prewalk transport behavior."""

    UNAVAILABLE = "unavailable"
    ADVERTISED = "advertised"
    QUALIFIED = "qualified"


DEFAULT_ROLES: tuple[RoleName, ...] = (
    RoleName.PLANNING,
    RoleName.IMPLEMENT,
    RoleName.VALIDATE,
    RoleName.REVIEW,
    RoleName.LIGHTWEIGHT_REVIEW,
    RoleName.SYNTHESIZE,
    RoleName.SCOUT,
)

BUILTIN_ADAPTER_NAMES: tuple[str, ...] = (
    "claude-code",
    "grok-build",
    "codex-fugu",
    "gemini-cli",
    "antigravity-cli",
    "opencode-cli",
    "devin-cli",
    "omp-cli",
    "custom-cli",
    "host-native",
)

# One canonical spelling of the session filename; every cobbler_runtime module
# imports this instead of repeating the literal (see docs/plans/hygiene-and-hardening.md B4).
ELVES_SESSION_BASENAME = ".elves-session.json"

NATIVE_PROFILE_NAME = "host-native"
NATIVE_ROUTE = "host-native"

# One canonical forbidden set for ambiguous session selectors, imported by the
# session-id validators in native_worker, implement, adapters, full_run, and
# openrouter_lens so a token added here is rejected at those call sites at once.
# Exact ids only; selector words that mean "whatever session was most recent"
# are forbidden.
AMBIGUOUS_SESSION_TOKENS: frozenset[str] = frozenset(
    {
        "latest",
        "last",
        "continue",
        "most-recent",
        "most_recent",
        "recent",
        "current",
        "active",
    }
)

# Operations that never dispatch model inference.
NON_MODEL_OPERATIONS: frozenset[str] = frozenset(
    {
        "git",
        "gh",
        "push",
        "pull",
        "fetch",
        "pr_create",
        "pr_comment",
        "pr_merge",
        "tag",
        "commit",
        "checkout",
        "status",
        "diff",
        "log",
    }
)


class ValidationIssue(Exception):
    """Actionable configuration validation error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.path is not None:
            payload["path"] = self.path
        if self.hint is not None:
            payload["hint"] = self.hint
        return payload


@dataclass(frozen=True)
class NativeWorkerPhaseRoute:
    """One explicit guide or execution route without host-specific CLI flags."""

    role: NativeWorkerPhaseRole
    transport: str
    model_policy: str
    model: str | None
    effort: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["role"] = self.role.value
        return payload


@dataclass(frozen=True)
class PrewalkRoutePair:
    """Deterministic route/fidelity decision for one logical worker trajectory."""

    requested_mode: PrewalkMode
    actual_mode: str
    guide: NativeWorkerPhaseRoute
    execution: NativeWorkerPhaseRoute
    capability_state: PrewalkCapabilityState
    advertised_exact_resume: bool
    advertised_route_override_on_resume: bool
    behaviorally_verified_session_continuity: bool
    behaviorally_verified_instruction_pruning: bool
    worktree_binding_verified: bool
    stream_identity_verified: bool
    instruction_fidelity: PrewalkInstructionFidelity
    fallback_reason: str | None = None
    qualification_model_calls_made: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_mode": self.requested_mode.value,
            "actual_mode": self.actual_mode,
            "guide": self.guide.to_dict(),
            "execution": self.execution.to_dict(),
            "capability_state": self.capability_state.value,
            "advertised_exact_resume": self.advertised_exact_resume,
            "advertised_route_override_on_resume": self.advertised_route_override_on_resume,
            "behaviorally_verified_session_continuity": self.behaviorally_verified_session_continuity,
            "behaviorally_verified_instruction_pruning": self.behaviorally_verified_instruction_pruning,
            "worktree_binding_verified": self.worktree_binding_verified,
            "stream_identity_verified": self.stream_identity_verified,
            "instruction_fidelity": self.instruction_fidelity.value,
            "fallback_reason": self.fallback_reason,
            "qualification_model_calls_made": self.qualification_model_calls_made,
        }


@dataclass(frozen=True)
class HarnessProfile:
    """Named harness profile without hardcoding prestige models.

    Additive fields default so existing callers remain compatible. Secret values
    never appear here — only environment variable *names* may be listed in
    ``env_grants``.
    """

    name: str
    adapter: str
    executable: str | None = None
    notes: str = ""
    session_mode: SessionMode = SessionMode.EPHEMERAL
    context_sharing: ContextSharingPolicy = ContextSharingPolicy.INDEPENDENT
    enabled: bool = True
    requested_model: str | None = None
    extra_args: tuple[str, ...] = ()
    env_grants: tuple[str, ...] = ()
    input_contract: str = "prompt-file"
    output_contract: str = "json-role-report"
    capabilities: tuple[str, ...] = ()
    # Trusted qualified capability names (never self-certified from preference text).
    qualified_capabilities: tuple[str, ...] = ()
    # Fields explicitly present in the defining config layer (for field-wise merge).
    provided_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Enums -> values for stable JSON.
        payload["session_mode"] = self.session_mode.value
        payload["context_sharing"] = self.context_sharing.value
        payload["extra_args"] = list(self.extra_args)
        payload["env_grants"] = list(self.env_grants)
        payload["capabilities"] = list(self.capabilities)
        payload["qualified_capabilities"] = list(self.qualified_capabilities)
        payload["provided_fields"] = list(self.provided_fields)
        return payload


@dataclass(frozen=True)
class CapabilityRecord:
    """Behaviorally classified capability for a harness profile."""

    name: str
    status: CapabilityStatus
    detail: str = ""
    qualified_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "qualified_at": self.qualified_at,
        }


@dataclass(frozen=True)
class FallbackEntry:
    """One step in a deterministic fallback chain."""

    profile: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RoleRoute:
    """Resolved route for one role slot."""

    role: RoleName
    profile: str
    required: bool = False
    fallback_chain: tuple[FallbackEntry, ...] = ()
    source: ConfigSource = ConfigSource.NATIVE_DEFAULT
    session_mode: SessionMode = SessionMode.EPHEMERAL
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "profile": self.profile,
            "required": self.required,
            "fallback_chain": [entry.to_dict() for entry in self.fallback_chain],
            "source": self.source.value,
            "session_mode": self.session_mode.value,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class EffectiveAttempt:
    """One ordered attempt (primary or fallback) with full profile fields.

    Serializable without secret values — ``env_grants`` carries names only.
    """

    profile: str
    adapter: str
    executable: str | None = None
    requested_model: str | None = None
    extra_args: tuple[str, ...] = ()
    env_grants: tuple[str, ...] = ()
    enabled: bool = True
    required: bool = False
    source: str = ConfigSource.NATIVE_DEFAULT.value
    session_mode: str = SessionMode.EPHEMERAL.value
    context_sharing: str = ContextSharingPolicy.INDEPENDENT.value
    # Empty means "use adapter default pair" at dispatch time.
    input_contract: str = ""
    output_contract: str = ""
    capabilities: tuple[str, ...] = ()
    qualified_capabilities: tuple[str, ...] = ()
    reason: str = "primary"
    notes: str = ""
    # Exact external chat id for continuity (plan → review). Never latest/continue.
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "adapter": self.adapter,
            "executable": self.executable,
            "requested_model": self.requested_model,
            "extra_args": list(self.extra_args),
            "env_grants": list(self.env_grants),
            "enabled": self.enabled,
            "required": self.required,
            "source": self.source,
            "session_mode": self.session_mode,
            "context_sharing": self.context_sharing,
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
            "capabilities": list(self.capabilities),
            "qualified_capabilities": list(self.qualified_capabilities),
            "reason": self.reason,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class UsageRecord:
    """Observed usage with honest unknown remaining quota."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    remaining_quota: str | int | None = "unknown"
    quota_known: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "remaining_quota": self.remaining_quota if self.quota_known else "unknown",
            "quota_known": self.quota_known,
        }


@dataclass
class ResolvedConfig:
    """Fully resolved routing table with provenance."""

    roles: dict[str, RoleRoute] = field(default_factory=dict)
    profiles: dict[str, HarnessProfile] = field(default_factory=dict)
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources_consulted: list[str] = field(default_factory=list)
    external_routing_enabled: bool = True

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "external_routing_enabled": self.external_routing_enabled,
            "roles": {name: route.to_dict() for name, route in self.roles.items()},
            "profiles": {name: profile.to_dict() for name, profile in self.profiles.items()},
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": list(self.warnings),
            "sources_consulted": list(self.sources_consulted),
        }


def parse_role_name(raw: str) -> RoleName:
    normalized = raw.strip().lower().replace("-", "_")
    try:
        return RoleName(normalized)
    except ValueError as exc:
        raise ValidationIssue(
            "unknown_role",
            f"Unknown role `{raw}`",
            path=f"roles.{raw}",
            hint=f"Known roles: {', '.join(role.value for role in RoleName)}",
        ) from exc


def is_non_model_operation(operation: str) -> bool:
    """Return True when the operation must never dispatch model inference."""
    token = operation.strip().lower().replace("-", "_")
    if token in NON_MODEL_OPERATIONS:
        return True
    head = token.split()[0] if token else ""
    return head in NON_MODEL_OPERATIONS


def attempt_from_profile(
    profile: HarnessProfile,
    *,
    required: bool = False,
    source: ConfigSource | str = ConfigSource.NATIVE_DEFAULT,
    reason: str = "primary",
    route_session_mode: SessionMode | None = None,
) -> EffectiveAttempt:
    """Build one effective attempt from a fully resolved profile (no field loss)."""
    src = source.value if isinstance(source, ConfigSource) else str(source)
    session = (route_session_mode or profile.session_mode).value
    return EffectiveAttempt(
        profile=profile.name,
        adapter=profile.adapter,
        executable=profile.executable,
        requested_model=profile.requested_model,
        extra_args=tuple(profile.extra_args),
        env_grants=tuple(profile.env_grants),
        enabled=profile.enabled,
        required=required,
        source=src,
        session_mode=session,
        context_sharing=profile.context_sharing.value,
        input_contract=profile.input_contract,
        output_contract=profile.output_contract,
        capabilities=tuple(profile.capabilities),
        qualified_capabilities=tuple(profile.qualified_capabilities),
        reason=reason,
        notes=profile.notes,
    )


def build_effective_attempts(
    route: RoleRoute,
    profiles: dict[str, HarnessProfile],
) -> tuple[EffectiveAttempt, ...]:
    """Expand a role route into ordered primary + fallback attempts.

    Each fallback carries that profile's own executable/model/args/env fields,
    not only the profile name.
    """
    attempts: list[EffectiveAttempt] = []
    primary = profiles.get(route.profile)
    if primary is None:
        raise ValidationIssue(
            "unknown_profile",
            f"Cannot build attempts: unknown profile `{route.profile}`",
            path=f"roles.{route.role.value}.profile",
        )
    attempts.append(
        attempt_from_profile(
            primary,
            required=route.required,
            source=route.source,
            reason="primary",
            route_session_mode=route.session_mode,
        )
    )
    for entry in route.fallback_chain:
        fb_profile = profiles.get(entry.profile)
        if fb_profile is None:
            raise ValidationIssue(
                "unknown_fallback_profile",
                f"Cannot build fallback attempt: unknown profile `{entry.profile}`",
                path=f"roles.{route.role.value}.fallback_chain",
            )
        attempts.append(
            attempt_from_profile(
                fb_profile,
                required=route.required,
                source=route.source,
                reason=entry.reason or f"fallback:{entry.profile}",
                route_session_mode=route.session_mode,
            )
        )
    return tuple(attempts)
