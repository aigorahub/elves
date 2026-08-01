"""Capability records and doctor inventory for harness profiles.

Live paid model probes are optional. Doctor reports executable/version/auth,
discovered models, qualification freshness, and session support as separate
fields without inventing remaining quota.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .schema import CapabilityRecord, CapabilityStatus, HarnessProfile


# Core capability names used by later batches.
CORE_CAPABILITIES: tuple[str, ...] = (
    "availability",
    "version",
    "authentication",
    "model_discovery",
    "read_only_repo",
    "local_commands",
    "file_edit",
    "structured_output",
    "actual_model_reporting",
    "persistent_session",
    "parent_child_lineage",
    "parallel_read_only",
    "isolated_write",
    "worktree",
    "permission_policy",
    "credential_isolation",
    "network_egress",
    "usage_reporting",
    "remaining_quota",
)


def default_capabilities_for(profile: HarnessProfile) -> list[CapabilityRecord]:
    """Return non-probed capability records for a profile.

    Host-native is always available for coordination without external tools.
    External adapters start as advertised/unknown until a later batch qualifies
    them with fixtures or live probes.
    """
    if profile.adapter == "host-native":
        return [
            CapabilityRecord(
                name="availability",
                status=CapabilityStatus.QUALIFIED,
                detail="Host coordinator path requires no external executable",
            ),
            CapabilityRecord(
                name="read_only_repo",
                status=CapabilityStatus.QUALIFIED,
                detail="Host can inspect the owned checkout",
            ),
            CapabilityRecord(
                name="local_commands",
                status=CapabilityStatus.QUALIFIED,
                detail="Host runs validation gates directly",
            ),
            CapabilityRecord(
                name="file_edit",
                status=CapabilityStatus.QUALIFIED,
                detail="Host edits the owned checkout",
            ),
            CapabilityRecord(
                name="remaining_quota",
                status=CapabilityStatus.UNKNOWN,
                detail="Host subscription quota is not tracked by Elves",
            ),
            CapabilityRecord(
                name="persistent_session",
                status=CapabilityStatus.UNAVAILABLE,
                detail="Host-native has no external provider session registry entry",
            ),
        ]

    records: list[CapabilityRecord] = []
    for name in CORE_CAPABILITIES:
        if name == "remaining_quota":
            status = CapabilityStatus.UNKNOWN
            detail = "Remaining quota is unknown unless a harness exposes it"
        elif name in {"availability", "version", "authentication", "model_discovery"}:
            status = CapabilityStatus.ADVERTISED
            detail = "Requires doctor inventory; not probed without an explicit smoke"
        elif name == "persistent_session":
            status = CapabilityStatus.ADVERTISED
            detail = "Exact create/resume builders available; qualify per harness version"
        elif name == "parent_child_lineage" and profile.adapter == "grok-build":
            status = CapabilityStatus.ADVERTISED
            detail = (
                "Grok parent→worktree child lineage is exact but distinct UUIDs; "
                "headless worktree-resume broken on 0.2.93"
            )
        else:
            status = CapabilityStatus.UNKNOWN
            detail = "Unqualified until adapter probe or fixture proves behavior"
        records.append(CapabilityRecord(name=name, status=status, detail=detail))
    return records


def summarize_capabilities(
    profiles: dict[str, HarnessProfile],
) -> dict[str, list[dict[str, object]]]:
    """Return JSON-ready capability inventory for doctor --json."""
    return {
        name: [record.to_dict() for record in default_capabilities_for(profile)]
        for name, profile in sorted(profiles.items())
    }


def doctor_inventory(
    profiles: Mapping[str, HarnessProfile],
    *,
    discovered_models: Mapping[str, list[str]] | None = None,
    versions: Mapping[str, str | None] | None = None,
    auth_states: Mapping[str, str] | None = None,
    qualification_times: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Build doctor --json adapter inventory with separated fields.

    Never invents remaining quota. Session support is separate from auth and
    model discovery. Qualification freshness is an ISO timestamp or null.
    """
    discovered_models = discovered_models or {}
    versions = versions or {}
    auth_states = auth_states or {}
    qualification_times = qualification_times or {}
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    adapters: dict[str, Any] = {}
    for name, profile in sorted(profiles.items()):
        caps = default_capabilities_for(profile)
        session_cap = next(
            (c for c in caps if c.name == "persistent_session"),
            None,
        )
        adapters[name] = {
            "executable": profile.executable,
            "version": versions.get(name),
            "auth": auth_states.get(name, "unknown"),
            "discovered_models": list(discovered_models.get(name, [])),
            "qualification_freshness": qualification_times.get(name),
            "session_support": {
                "status": session_cap.status.value if session_cap else "unknown",
                "detail": session_cap.detail if session_cap else "",
                "exact_resume": profile.adapter != "host-native",
                "ambiguous_selection_forbidden": True,
            },
            "remaining_quota": "unknown",
            "quota_known": False,
            "capabilities": [c.to_dict() for c in caps],
            "adapter": profile.adapter,
            "inventory_generated_at": now,
        }
        # Grok-specific known incompatibility note (not a personal model default).
        if profile.adapter == "grok-build":
            adapters[name]["known_incompatibilities"] = [
                {
                    "version": "0.2.93",
                    "issue": "headless --worktree --resume retains source CWD",
                    "policy": "fail closed; discover child id and resume from registered worktree",
                }
            ]

    return {
        "adapters": adapters,
        "notes": [
            "remaining_quota is unknown unless a harness explicitly exposes it",
            "exact session IDs are required; bare --resume/--continue/--last are forbidden",
            "doctor does not launch paid model turns unless an explicit smoke is requested",
        ],
    }


def route_on_usage_pressure(
    *,
    remaining_quota: str | float | int | None,
    rate_limited: bool = False,
    alternate_provider: str | None = None,
) -> dict[str, object]:
    """Honest usage-pressure routing without inventing remaining quota.

    When remaining quota is unknown, only explicit rate-limit signals may force
    a documented alternate. Callers must pass harness-provided values only.
    """
    if rate_limited:
        return {
            "action": "failover" if alternate_provider else "backoff",
            "reason": "rate_limited",
            "alternate_provider": alternate_provider,
            "quota_known": remaining_quota not in (None, "unknown", ""),
        }
    if remaining_quota in (None, "unknown", ""):
        return {
            "action": "continue",
            "reason": "remaining_quota_unknown",
            "alternate_provider": None,
            "quota_known": False,
        }
    try:
        value = float(remaining_quota)
    except (TypeError, ValueError):
        return {
            "action": "continue",
            "reason": "remaining_quota_unparseable",
            "alternate_provider": None,
            "quota_known": False,
        }
    if value <= 0:
        return {
            "action": "failover" if alternate_provider else "stop",
            "reason": "quota_exhausted",
            "alternate_provider": alternate_provider,
            "quota_known": True,
        }
    if value < 0.1:
        return {
            "action": "prefer_alternate" if alternate_provider else "warn",
            "reason": "quota_low",
            "alternate_provider": alternate_provider,
            "quota_known": True,
        }
    return {
        "action": "continue",
        "reason": "quota_ok",
        "alternate_provider": None,
        "quota_known": True,
    }
