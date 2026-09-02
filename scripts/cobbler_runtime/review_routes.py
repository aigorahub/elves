"""Optional-provider review routing: probe, select, and record the real route.

Fugu is optional. When Fugu (or any other optional provider) is unavailable
because of quota, authentication, catalog, runner, timeout, or provider failure,
the run must select another available independent reviewer instead of stopping.
This module is host-neutral: Claude Code, Codex, Grok Build, and Oh My Pi all get
the same selection order, the same failure vocabulary, and the same ledger keys.

Two rules the rest of the runtime depends on:

* An optional-provider failure never blocks a run while a qualified review route
  remains. Only a *required* review with **no** route at all blocks.
* A decision never claims a review ran. ``review_claim`` is the only place that
  turns a selected route plus a produced report into ``review_ran: true``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from .schema import ValidationIssue


# Why an optional review route is not usable right now. These are the exact
# reason codes the runners emit and the CLI accepts.
REVIEW_ROUTE_FAILURE_REASONS: frozenset[str] = frozenset(
    {
        "quota",
        "authentication",
        "catalog",
        "runner",
        "timeout",
        "provider",
        "unconfigured",
        "not_independent",
        "unknown",
    }
)

# Optional provider-backed review routes, in host-neutral preference order.
OPTIONAL_REVIEW_ROUTES: tuple[str, ...] = ("fugu", "grok", "omp", "council")

# The supported native reviewer for each host. A native reviewer is always a
# qualified review route: it needs no external provider, quota, or catalog.
NATIVE_REVIEW_ROUTES: Mapping[str, str] = {
    "claude-code": "claude-code-subagent",
    "codex": "codex-native-review",
    "grok-build": "grok-native-review",
    "omp": "omp-native-review",
}

SUPPORTED_REVIEW_HOSTS: tuple[str, ...] = tuple(sorted(NATIVE_REVIEW_ROUTES))

# Ordered classifiers. Order matters: "model not found" is a catalog failure,
# not a missing runner, so catalog patterns are tested before runner patterns.
_FAILURE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "quota",
        (
            r"\bquota\b",
            r"\brate[ _-]?limit",
            r"\busage limit",
            r"\bsubscription limit",
            r"\binsufficient (?:credit|quota|balance)",
            r"\bout of credit",
            r"\bbilling\b",
            r"\b429\b",
        ),
    ),
    (
        "authentication",
        (
            r"\bunauthori[sz]ed\b",
            r"\bforbidden\b",
            r"\bauthenticat",
            r"\bnot logged in\b",
            r"\blog in\b",
            r"\bapi[ _-]?key\b",
            r"\bcredential",
            r"\boauth\b",
            r"\btoken (?:expired|invalid)",
            r"\b401\b",
            r"\b403\b",
        ),
    ),
    (
        "catalog",
        (
            r"\bcatalog\b",
            r"\bmodel not found\b",
            r"\bunknown model\b",
            r"\bunsupported model\b",
            r"\bdoes not offer\b",
            r"\bnot available in the api\b",
        ),
    ),
    (
        "runner",
        (
            r"\bcommand not found\b",
            r"\bnot found\b",
            r"\bno such file\b",
            r"\blauncher (?:missing|not )",
            r"\bexecutable (?:missing|not )",
            r"\bis not installed\b",
            r"\barguments are incomplete\b",
            r"\bunknown [a-z]+ profile\b",
            r"\bcannot nest sandboxes\b",
            r"\bdoes not advertise required launch controls\b",
        ),
    ),
    (
        "timeout",
        (
            r"\btimed out\b",
            r"\btimeout\b",
            r"\bwall timeout\b",
            r"\bdeadline exceeded\b",
        ),
    ),
)

_EXIT_CODE_REASONS: Mapping[int, str] = {
    124: "timeout",
    126: "runner",
    127: "runner",
}


def normalize_review_route_reason(reason: str | None) -> str:
    """Map free-form text onto the closed reason vocabulary."""
    token = (reason or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not token:
        return "unknown"
    if token in REVIEW_ROUTE_FAILURE_REASONS:
        return token
    return "unknown"


def classify_review_route_failure(
    *,
    exit_code: int | None = None,
    text: str = "",
) -> str | None:
    """Classify one optional-route failure into a stable reason code.

    An explicit ``exit_code`` of ``0`` means success and returns ``None``, whatever
    the text says. With no exit code, the text alone decides. Unclassifiable
    non-zero exits are ``provider`` failures, which is still a real fallback
    trigger.
    """
    # An explicit success code is authoritative. A successful log may still say
    # "retry on timeout" or "not found"; that is not a route failure.
    if exit_code is not None and int(exit_code) == 0:
        return None
    body = (text or "").lower()
    for reason, patterns in _FAILURE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, body):
                return reason
    if exit_code is None:
        return None
    return _EXIT_CODE_REASONS.get(int(exit_code), "provider")


@dataclass(frozen=True)
class ReviewRouteProbe:
    """One probed review route and why it is or is not usable."""

    name: str
    available: bool
    reason: str | None = None
    kind: str = "optional-provider"

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValidationIssue(
                "invalid_review_route_probe",
                "A review route probe needs a non-empty route name",
                path="ReviewRouteProbe.name",
            )
        if self.available and self.reason:
            raise ValidationIssue(
                "invalid_review_route_probe",
                f"Available review route `{self.name}` must not carry a failure reason",
                path="ReviewRouteProbe.reason",
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "route": self.name,
            "kind": self.kind,
            "available": bool(self.available),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReviewRouteDecision:
    """Requested route, actual route, and the reason they differ."""

    requested_route: str | None
    actual_route: str | None
    fallback_reason: str | None
    status: str  # selected | unavailable
    host: str
    kind: str | None = None
    considered: tuple[dict[str, object], ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def selected(self) -> bool:
        return self.actual_route is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_route": self.requested_route,
            "actual_route": self.actual_route,
            "fallback_reason": self.fallback_reason,
            "status": self.status,
            "host": self.host,
            "kind": self.kind,
            "considered": [dict(item) for item in self.considered],
            "notes": list(self.notes),
        }


def _probe_map(probes: Iterable[ReviewRouteProbe]) -> dict[str, ReviewRouteProbe]:
    resolved: dict[str, ReviewRouteProbe] = {}
    for probe in probes:
        resolved[str(probe.name).strip()] = probe
    return resolved


def _unavailable_reason(
    route: str,
    probes: Mapping[str, ReviewRouteProbe],
    excluded: frozenset[str],
) -> str:
    if route in excluded:
        return "not_independent"
    probe = probes.get(route)
    if probe is None:
        return "unconfigured"
    if probe.available:
        return "unknown"
    return normalize_review_route_reason(probe.reason)


def select_review_route(
    *,
    host: str,
    requested: str | None = None,
    probes: Sequence[ReviewRouteProbe] = (),
    exclude: Sequence[str] = (),
) -> ReviewRouteDecision:
    """Choose the review route that will actually run.

    An explicit user route is preserved whenever it works. Otherwise the first
    available independent optional provider wins, and when none works the host's
    supported native reviewer is preferred over declaring the review impossible.
    """
    host_name = str(host).strip().lower()
    if host_name not in NATIVE_REVIEW_ROUTES:
        raise ValidationIssue(
            "unknown_review_host",
            f"Unknown review host `{host}`; supported hosts: "
            + ", ".join(SUPPORTED_REVIEW_HOSTS),
            path="select_review_route.host",
        )
    resolved = _probe_map(probes)
    excluded = frozenset(str(name).strip() for name in exclude if str(name).strip())
    requested_name = (requested or "").strip() or None
    native_route = NATIVE_REVIEW_ROUTES[host_name]

    considered: list[dict[str, object]] = []
    notes: list[str] = []

    def _is_available(route: str) -> bool:
        if route in excluded:
            return False
        probe = resolved.get(route)
        if probe is None:
            # Only the native reviewer is usable without an explicit probe.
            return route == native_route
        return bool(probe.available)

    order: list[tuple[str, str]] = []
    if requested_name:
        order.append(
            (
                requested_name,
                "native" if requested_name == native_route else "optional-provider",
            )
        )
    for route in OPTIONAL_REVIEW_ROUTES:
        if route != requested_name:
            order.append((route, "optional-provider"))
    if native_route != requested_name:
        order.append((native_route, "native"))

    for route, kind in order:
        available = _is_available(route)
        reason = None if available else _unavailable_reason(route, resolved, excluded)
        considered.append(
            {"route": route, "kind": kind, "available": available, "reason": reason}
        )
        if not available:
            continue
        if requested_name and route == requested_name:
            return ReviewRouteDecision(
                requested_route=requested_name,
                actual_route=route,
                fallback_reason=None,
                status="selected",
                host=host_name,
                kind=kind,
                considered=tuple(considered),
                notes=("explicit_user_route_preserved",),
            )
        pieces: list[str] = []
        for item in considered[:-1]:
            if item["available"]:
                continue
            token = f"{item['route']}:{item['reason']}"
            if token not in pieces:
                pieces.append(token)
        if kind == "native":
            notes.append("native_reviewer_preferred_when_no_optional_provider")
        if pieces:
            notes.append("optional_provider_failure_did_not_block_the_run")
        else:
            # Nothing was requested and nothing failed: this is the default route.
            notes.append("default_route_selected")
        return ReviewRouteDecision(
            requested_route=requested_name,
            actual_route=route,
            fallback_reason="; ".join(pieces) or None,
            status="selected",
            host=host_name,
            kind=kind,
            considered=tuple(considered),
            notes=tuple(notes),
        )

    pieces = [f"{item['route']}:{item['reason']}" for item in considered]
    return ReviewRouteDecision(
        requested_route=requested_name,
        actual_route=None,
        fallback_reason="; ".join(pieces) or "unknown",
        status="unavailable",
        host=host_name,
        kind=None,
        considered=tuple(considered),
        notes=("no_review_route_available", "do_not_claim_a_review_ran"),
    )


def review_route_blocks_run(
    decision: ReviewRouteDecision,
    *,
    required: bool,
) -> bool:
    """Only a required review with no route at all blocks the run."""
    return bool(required) and decision.actual_route is None


def review_claim(
    decision: ReviewRouteDecision,
    *,
    report_produced: bool,
) -> dict[str, object]:
    """The only place a run may say a review ran.

    A selected route is not a review. ``review_ran`` needs both a selected route
    and a produced report, so an unavailable or empty route can never be narrated
    as a completed review.
    """
    ran = bool(decision.actual_route) and bool(report_produced)
    # Written as one literal mapping so the public CLI contract stays inspectable.
    return {
        "requested_route": decision.requested_route,
        "actual_route": decision.actual_route,
        "fallback_reason": decision.fallback_reason,
        "status": decision.status,
        "host": decision.host,
        "kind": decision.kind,
        "considered": [dict(item) for item in decision.considered],
        "notes": list(decision.notes),
        "review_ran": ran,
        "report_produced": bool(report_produced),
        "claim": (
            f"review ran on {decision.actual_route}"
            if ran
            else "no review ran on this tip"
        ),
    }


def route_unavailable_directive(provider: str, reason: str) -> str:
    """One line a runner prints so the host driver reroutes instead of stopping."""
    code = normalize_review_route_reason(reason)
    route = str(provider).strip().lower()
    return (
        f"{provider} review route unavailable [{code}]: select another available "
        "review agent and record requested route, actual route, and fallback "
        "reason. Optional-provider failure does not block the run while a "
        "qualified review route exists. Probe with: python3 "
        '"$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" review-route --host <host> '
        f"--requested {route} --unavailable {route}={code}"
    )
