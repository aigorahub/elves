"""Observed-usage ledger (v2.24).

Aggregates usage that transports actually reported into an additive
``usage_observed`` block for ``.elves-session.json``, advisory Session Budget
lines, and an Elves Report panel. Honesty contract (locked product decision):

- only **observed** usage is recorded; unknown remains the literal string
  ``unobserved`` and is never rendered as a number or zero;
- cache-read style token counts are excluded from ceiling comparisons — the
  basis is observed input + output tokens only (mirrors prime-agent's
  accounting choice, adapted with attribution, MIT);
- an explicit user-set ceiling is **advisory**: crossing it produces a
  checkpoint classification, never a stop, and never alters worker routing;
- observed ≠ billed.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .sessions import UsageRecord, parse_usage_payload

USAGE_BLOCK_KEY = "usage_observed"
COMPLETENESS_COMPLETE = "complete"
COMPLETENESS_PARTIAL = "partial"
COMPLETENESS_UNOBSERVED = "unobserved"
CEILING_NO_CEILING = "no_ceiling"
CEILING_UNDER = "under"
CEILING_CROSSED = "crossed"
CEILING_CHECKPOINT_CLASSIFICATION = "usage_ceiling_checkpoint"
_COUNT_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def _record_observed(record: UsageRecord) -> bool:
    return any(
        getattr(record, field) is not None for field in _COUNT_FIELDS
    ) or record.cost_usd is not None


def _route_entry(route: str, record: UsageRecord) -> dict[str, Any]:
    entry: dict[str, Any] = {"route": route}
    for field in _COUNT_FIELDS:
        value = getattr(record, field)
        if value is not None:
            entry[field] = value
    if record.cost_usd is not None:
        entry["cost_usd"] = record.cost_usd
    entry["observed"] = _record_observed(record)
    return entry


def aggregate(observations: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate ``[{route, payload}]`` observations into a usage block.

    ``payload`` is a raw transport usage mapping parsed strictly through
    ``parse_usage_payload``; a route whose payload carries no counts stays an
    unobserved route rather than a zero.
    """

    by_route: list[dict[str, Any]] = []
    totals: dict[str, int | float] = {}
    observed_routes = 0
    for observation in observations:
        route = str(observation.get("route") or "unlabeled")
        record = parse_usage_payload(observation.get("payload") or {})
        entry = _route_entry(route, record)
        by_route.append(entry)
        if entry["observed"]:
            observed_routes += 1
            for field in _COUNT_FIELDS:
                value = getattr(record, field)
                if value is not None:
                    totals[field] = int(totals.get(field, 0)) + value
            if record.cost_usd is not None:
                totals["cost_usd"] = float(totals.get("cost_usd", 0.0)) + record.cost_usd
    if not observations or observed_routes == 0:
        completeness = COMPLETENESS_UNOBSERVED
    elif observed_routes == len(observations):
        completeness = COMPLETENESS_COMPLETE
    else:
        completeness = COMPLETENESS_PARTIAL
    return {
        "schema": 1,
        "completeness": completeness,
        "total": totals if totals else COMPLETENESS_UNOBSERVED,
        "by_route": by_route,
        "note": "observed transport reports only; observed ≠ billed",
    }


def ceiling_basis_tokens(usage_block: Mapping[str, Any]) -> int | None:
    """Advisory ceiling basis: observed input+output only, never cache reads.

    ``parse_usage_payload`` never ingests cache-read style counters, so any
    ``cache_read`` / ``cache_creation`` fields in raw payloads are structurally
    excluded from this basis.
    """

    total = usage_block.get("total")
    if not isinstance(total, Mapping):
        return None
    input_tokens = total.get("input_tokens")
    output_tokens = total.get("output_tokens")
    if input_tokens is None and output_tokens is None:
        return None
    return int(input_tokens or 0) + int(output_tokens or 0)


def ceiling_check(
    usage_block: Mapping[str, Any], ceiling: int | None
) -> dict[str, Any]:
    """Classify an advisory ceiling. Crossing is a checkpoint, never a stop."""

    if ceiling is None:
        return {"status": CEILING_NO_CEILING, "basis_tokens": ceiling_basis_tokens(usage_block)}
    if not isinstance(ceiling, int) or ceiling <= 0:
        raise ValueError("usage ceiling must be a positive integer token count")
    basis = ceiling_basis_tokens(usage_block)
    if basis is None:
        return {
            "status": CEILING_UNDER,
            "basis_tokens": None,
            "note": "no observed basis; unknown is never treated as a number",
        }
    if basis >= ceiling:
        return {
            "status": CEILING_CROSSED,
            "basis_tokens": basis,
            "ceiling": ceiling,
            "classification": CEILING_CHECKPOINT_CLASSIFICATION,
            "note": (
                "advisory ceiling crossed: checkpoint and notify; never a stop "
                "reason and never a routing input"
            ),
        }
    return {"status": CEILING_UNDER, "basis_tokens": basis, "ceiling": ceiling}


def write_session_block(session_path: Path, usage_block: Mapping[str, Any]) -> None:
    """Additively set ``usage_observed`` preserving every other session key."""

    data = json.loads(session_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("session file must contain a JSON object")
    data[USAGE_BLOCK_KEY] = dict(usage_block)
    tmp = session_path.with_suffix(session_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, session_path)


def session_budget_lines(usage_block: Mapping[str, Any], ceiling: int | None) -> list[str]:
    """Render advisory Session Budget lines (survival guide)."""

    total = usage_block.get("total")
    if isinstance(total, Mapping) and total:
        parts = [
            f"{field.replace('_tokens', '')} {total[field]:,}"
            for field in _COUNT_FIELDS
            if field in total
        ]
        if "cost_usd" in total:
            parts.append(f"cost ${total['cost_usd']:.2f} observed")
        rendered = "; ".join(parts)
    else:
        rendered = COMPLETENESS_UNOBSERVED
    lines = [
        f"- **Observed usage so far:** {rendered} "
        f"_({usage_block.get('completeness', COMPLETENESS_UNOBSERVED)}; observed ≠ billed; "
        "cache reads excluded from ceilings)_",
    ]
    if ceiling is not None:
        lines.append(
            f"- **Usage ceiling (advisory):** {ceiling:,} tokens — crossing is a checkpoint, "
            "never a stop"
        )
    return lines


def report_panel_html(usage_block: Mapping[str, Any]) -> str:
    """Bounded, escaped Elves Report panel; empty when nothing was observed."""

    if usage_block.get("completeness") == COMPLETENESS_UNOBSERVED:
        return ""
    rows: list[str] = []
    for entry in list(usage_block.get("by_route", []))[:20]:
        route = html.escape(str(entry.get("route", "unlabeled")))
        if entry.get("observed"):
            cells = [
                f"{entry[field]:,}" if field in entry else "—"
                for field in _COUNT_FIELDS
            ]
            cost = f"${entry['cost_usd']:.2f}" if "cost_usd" in entry else "—"
        else:
            cells = ["unobserved"] * len(_COUNT_FIELDS)
            cost = "unobserved"
        rows.append(
            f"<tr><td>{route}</td><td>{cells[0]}</td><td>{cells[1]}</td>"
            f"<td>{cells[2]}</td><td>{cost}</td></tr>"
        )
    completeness = html.escape(str(usage_block.get("completeness", "")))
    return (
        '<section class="usage-observed"><h2>Observed usage</h2>'
        f"<p>completeness: {completeness} — observed transport reports only; "
        "observed &ne; billed; cache reads excluded from ceilings.</p>"
        "<table><thead><tr><th>route</th><th>input</th><th>output</th>"
        "<th>total</th><th>cost</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )
