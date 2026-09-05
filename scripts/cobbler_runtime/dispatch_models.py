"""Stable contracts shared by council dispatch components.

This module deliberately depends only on the runtime schema.  Focused attempt,
external-process, result, and facade modules may import these contracts without
creating a dependency back to :mod:`cobbler_runtime.dispatch`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Union

from .schema import EffectiveAttempt


HostExecutor = Callable[
    [Mapping[str, Any]],
    Union[Mapping[str, Any], Awaitable[Mapping[str, Any]]],
]


@dataclass(frozen=True)
class LaneSpec:
    """One independent read-only council lane."""

    lane_id: str
    role: str
    adapter: str
    profile: str
    requested_model: str | None = None
    executable: str | None = None
    required: bool = False
    timeout_seconds: float = 30.0
    extra_args: tuple[str, ...] = ()
    env_extra_allowlist: tuple[str, ...] = ()
    env_grants: tuple[str, ...] = ()
    command_override: tuple[str, ...] | None = None
    attempts: tuple[EffectiveAttempt, ...] = ()
    injected_host_evidence: dict[str, Any] | None = None
    # Trusted host executor callback: (challenge: dict) -> evidence dict.
    # Static injected_host_evidence alone cannot count as a verified vote.
    host_executor: HostExecutor | None = None
    # Trusted qualified capability names for this lane (fixture/host evidence).
    qualified_capabilities: tuple[str, ...] = ()
    # When True, lane grants come only from attempt.env_grants (no LaneSpec inherit).
    isolate_attempt_env_grants: bool = True
    # Exact external chat/session id for plan→review continuity (never latest/continue).
    session_id: str | None = None
    # When explicitly requested, prose instruction files are copied under an
    # inert evidence path. Executable agent/MCP config is always excluded.
    include_instructions_as_data: bool = False


@dataclass
class AttemptResult:
    """Evidence for one ordered attempt inside a lane."""

    attempt_index: int
    profile: str
    adapter: str
    requested_model: str | None
    actual_model: str | None
    model_evidence_source: str | None
    status: str
    failure_class: str | None = None
    reason: str | None = None
    ok: bool = False
    timeout: bool = False
    exit_code: int | None = None
    command: list[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    cleanup: dict[str, Any] = field(default_factory=dict)
    effective_contract: dict[str, Any] = field(default_factory=dict)
    process_launched: bool = False
    model_call_made: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LaneResult:
    """Per-lane evidence for host synthesis."""

    lane_id: str
    role: str
    adapter: str
    profile: str
    ok: bool
    launch_time: float
    start_time: float
    end_time: float
    timeout: bool = False
    exit_code: int | None = None
    requested_model: str | None = None
    actual_model: str | None = None
    model_evidence_source: str | None = None
    stdout_summary: str = ""
    stderr_summary: str = ""
    report: dict[str, Any] | None = None
    error: str | None = None
    fallback_used: str | None = None
    stripped_env_names: list[str] = field(default_factory=list)
    granted_env_names: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    artifact_dir: str | None = None
    attempts: list[AttemptResult] = field(default_factory=list)
    successful_attempt_index: int | None = None
    failure_class: str | None = None
    native_session_id: str | None = None
    execution_id: str | None = None
    process_launched: bool = False
    # Explicit call/mutation truth (not inferred from path substrings).
    model_call_made: bool = False
    mutated_repo: bool = False

    @property
    def wall_seconds(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CouncilResult:
    """Aggregate parallel council outcome for host synthesis."""

    run_id: str
    ok: bool
    council_verified: bool
    blocked: bool
    confidence: str
    successful_reports: list[dict[str, Any]] = field(default_factory=list)
    lane_results: list[LaneResult] = field(default_factory=list)
    target_quorum: int | None = None
    required_quorum: int | None = None
    phase_required: bool = False
    notes: list[str] = field(default_factory=list)
    artifact_root: str | None = None
    model_calls_made: bool = False
    mutated_repo: bool = False
    successful_execution_ids: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.blocked:
            return "blocked"
        if self.ok:
            return "success"
        return "unavailable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "ok": self.ok,
            "council_verified": self.council_verified,
            "blocked": self.blocked,
            "confidence": self.confidence,
            "successful_reports": list(self.successful_reports),
            "lane_results": [lane.to_dict() for lane in self.lane_results],
            "target_quorum": self.target_quorum,
            "required_quorum": self.required_quorum,
            "phase_required": self.phase_required,
            "notes": list(self.notes),
            "artifact_root": self.artifact_root,
            "successful_count": len(self.successful_execution_ids),
            "model_calls_made": self.model_calls_made,
            "mutated_repo": self.mutated_repo,
            "successful_execution_ids": list(self.successful_execution_ids),
        }
