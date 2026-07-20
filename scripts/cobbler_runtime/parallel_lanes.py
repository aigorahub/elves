"""Deterministic Parallelves lane validator and width test.

Implements the planner-side tooling for `references/parallelves.md`: a bounded
line-based parser for the plan's optional ``## Lanes`` fenced block (no yaml
dependency), a lane-partition validator, and the four-gate width test. Serial
is the default everywhere; the width test only *recommends* lanes and records a
concrete ``parallel_declined:<gate>:<detail>`` reason for every failed gate.
Deterministic, model-free, read-only.
"""

from __future__ import annotations

import math
import posixpath
import re
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .schema import ValidationIssue

LANES_PLAN_MAX_BYTES = 1024 * 1024
LANES_TIMINGS_MAX_BYTES = 64 * 1024
LANES_SECTION_HEADING = "## Lanes"
LANE_ID_PATTERN = re.compile(r"^L[1-9][0-9]*$")
MIN_STRUCTURAL_LANES = 2
DEFAULT_MAX_LANES = 3
WORKER_DOMINANCE_RATIO = 2.0
HIGH_RISK_POSTURE = "high"
RISK_POSTURES = ("low", "standard", "high")

DECLINE_NO_LANES = "parallel_declined:structural_width:no_lanes_declared"
DECLINE_SINGLE_LANE = "parallel_declined:structural_width:single_lane"
DECLINE_CROSS_LANE_DEPENDENCY = (
    "parallel_declined:structural_width:cross_lane_dependency"
)
DECLINE_PARTITION_INVALID = "parallel_declined:structural_width:partition_invalid"
DECLINE_NO_TIMINGS = "parallel_declined:worker_dominance:no_recorded_timings"
DECLINE_DRIVER_DOMINATES = (
    "parallel_declined:worker_dominance:driver_review_dominates"
)
DECLINE_INVALID_TIMINGS = "parallel_declined:worker_dominance:invalid_timings"
DECLINE_OVER_MAX_LANES = "parallel_declined:lane_budget:over_max_lanes"
DECLINE_HIGH_RISK = "parallel_declined:risk_posture:high_risk_serial"
DECLINE_PREFERENCE_OFF = "parallel_declined:preference:off"

_LANE_FIELDS = ("name", "depends_on", "owned_surfaces", "batches")


def _grammar_error(message: str, *, line: int | None = None) -> ValidationIssue:
    hint = f"near line {line}" if line is not None else None
    text = message if line is None else f"{message} (near line {line})"
    return ValidationIssue("parallel_lanes_grammar_invalid", text, hint=hint)


def _parse_inline_list(value: str, *, line: int) -> list[str]:
    body = value.strip()
    if not (body.startswith("[") and body.endswith("]")):
        raise _grammar_error("Expected an inline [..] list", line=line)
    inner = body[1:-1].strip()
    if not inner:
        return []
    items = [item.strip() for item in inner.split(",")]
    if any(not item for item in items):
        raise _grammar_error("Inline list contains an empty item", line=line)
    return items


def extract_lanes_block(plan_text: str) -> list[tuple[int, str]]:
    """Return (line_number, line) pairs inside the ``## Lanes`` fenced block."""

    lines = plan_text.splitlines()
    # Track fenced-code state while scanning so a `## Lanes` line inside any
    # earlier fenced block is ignored (fence-decoy hardening); duplicate real
    # sections fail closed.
    in_fence = False
    section_starts: list[int] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and stripped == LANES_SECTION_HEADING:
            section_starts.append(index)
    if not section_starts:
        raise ValidationIssue(
            "parallel_lanes_missing",
            "Plan has no `## Lanes` section; serial is the default",
        )
    if len(section_starts) > 1:
        raise _grammar_error(
            "Duplicate `## Lanes` section", line=section_starts[1] + 1
        )
    section_start = section_starts[0]
    block: list[tuple[int, str]] | None = None
    fence_start: int | None = None
    for index in range(section_start + 1, len(lines)):
        stripped = lines[index].strip()
        if fence_start is None and stripped.startswith("## "):
            break
        if stripped.startswith("```"):
            if fence_start is None:
                if block is not None:
                    raise _grammar_error(
                        "Duplicate fenced block in `## Lanes` section",
                        line=index + 1,
                    )
                fence_start = index
                block = []
            else:
                fence_start = None
        elif fence_start is not None and block is not None:
            block.append((index + 1, lines[index]))
    if fence_start is not None:
        raise _grammar_error(
            "Lanes fenced block is never closed", line=fence_start + 1
        )
    if block is None:
        raise ValidationIssue(
            "parallel_lanes_missing",
            "`## Lanes` section has no fenced lanes block",
        )
    return block


def parse_lanes_block(block: Sequence[tuple[int, str]]) -> dict[str, Any]:
    """Parse the documented line-based lanes grammar into a plain mapping."""

    trunk: list[str] = []
    lanes: list[dict[str, Any]] = []
    mode: str | None = None  # None | "trunk" | "lanes"
    lane: dict[str, Any] | None = None
    lane_seen: set[str] = set()
    lane_start_line: int | None = None
    pending_list: str | None = None

    def require_complete_lane() -> None:
        if lane is None:
            return
        missing = [field for field in _LANE_FIELDS if field not in lane_seen]
        if missing:
            raise _grammar_error(
                "Lane declaration is missing required field(s): " + ", ".join(missing),
                line=lane_start_line,
            )

    for line_no, raw in block:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        text = raw.strip()

        if indent == 0:
            require_complete_lane()
            pending_list = None
            lane = None
            if text == "trunk:":
                mode = "trunk"
                continue
            if text.startswith("trunk:"):
                trunk.extend(_parse_inline_list(text[len("trunk:"):], line=line_no))
                mode = None
                continue
            if text == "lanes:":
                mode = "lanes"
                continue
            raise _grammar_error(f"Unexpected top-level line `{text}`", line=line_no)

        if mode == "trunk":
            if text.startswith("- ") and len(text) > 2:
                trunk.append(text[2:].strip())
                continue
            raise _grammar_error(f"Invalid trunk entry `{text}`", line=line_no)

        if mode != "lanes":
            raise _grammar_error(f"Indented line outside any section `{text}`", line=line_no)

        if text.startswith("- id:"):
            require_complete_lane()
            value = text[len("- id:"):].strip()
            if not value:
                raise _grammar_error("Lane `id` value is empty", line=line_no)
            lane = {
                "id": value,
                "name": "",
                "depends_on": [],
                "owned_surfaces": [],
                "batches": [],
            }
            lanes.append(lane)
            lane_seen = set()
            lane_start_line = line_no
            pending_list = None
            continue

        if lane is None:
            raise _grammar_error(
                f"Lane field before any `- id:` entry `{text}`", line=line_no
            )

        if text.startswith("- "):
            if pending_list is None:
                raise _grammar_error(
                    f"Dash item outside a list field `{text}`", line=line_no
                )
            item = text[2:].strip()
            if not item:
                raise _grammar_error("List item is empty", line=line_no)
            lane[pending_list].append(item)
            continue

        key, separator, value = text.partition(":")
        key = key.strip()
        if not separator or key not in _LANE_FIELDS:
            raise _grammar_error(f"Unknown lane field `{text}`", line=line_no)
        if key in lane_seen:
            raise _grammar_error(
                f"Duplicate lane field `{key}` within one lane item", line=line_no
            )
        lane_seen.add(key)
        value = value.strip()
        if key == "name":
            pending_list = None
            if not value:
                raise _grammar_error("Lane `name` value is empty", line=line_no)
            lane["name"] = value
            continue
        # key is one of the list fields
        if value:
            lane[key] = _parse_inline_list(value, line=line_no)
            pending_list = None
        else:
            lane[key] = []
            pending_list = key

    require_complete_lane()
    return {"trunk": trunk, "lanes": lanes}


def load_lanes_from_plan(path: Path) -> dict[str, Any]:
    """Bounded, fail-closed read of a plan file's lanes declaration."""

    try:
        before = path.lstat()
    except OSError as exc:
        # Distinct from `parallel_lanes_missing`: an absent/unreadable plan
        # FILE is an error, not an honest "no lanes declared" serial default.
        raise ValidationIssue(
            "parallel_lanes_plan_missing",
            f"Plan file is missing or unreadable: {exc}",
            path=str(path),
        ) from exc
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        raise ValidationIssue(
            "parallel_lanes_grammar_invalid",
            "Plan file must be a regular non-symlink file",
            path=str(path),
        )
    if before.st_size > LANES_PLAN_MAX_BYTES:
        raise ValidationIssue(
            "parallel_lanes_grammar_invalid",
            "Plan file exceeds the bounded read size",
            path=str(path),
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationIssue(
            "parallel_lanes_plan_missing",
            f"Plan file is missing or unreadable: {exc}",
            path=str(path),
        ) from exc
    except UnicodeError as exc:
        raise ValidationIssue(
            "parallel_lanes_grammar_invalid",
            f"Plan file is not bounded UTF-8 text: {exc}",
            path=str(path),
        ) from exc
    return parse_lanes_block(extract_lanes_block(text))


def _normalized_surface(surface: str) -> str:
    return posixpath.normpath(surface.strip()).rstrip("/")


def _surface_invalid_reason(surface: str) -> str | None:
    """Return why a declared owned surface is not a repo-relative path."""

    raw = surface.strip()
    if not raw:
        return "is empty"
    if posixpath.isabs(raw):
        return "is an absolute path"
    norm = _normalized_surface(raw)
    if norm in ("", ".", "/"):
        return "normalizes to the repo root"
    if norm == ".." or norm.startswith("../"):
        return "escapes the repository root"
    return None


def validate_lane_partition(lanes: Sequence[Mapping[str, Any]]) -> list[ValidationIssue]:
    """Validate ids, surfaces, pairwise disjointness, dependencies, and cycles."""

    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()
    for lane in lanes:
        lane_id = str(lane.get("id", ""))
        if not LANE_ID_PATTERN.match(lane_id):
            issues.append(
                ValidationIssue(
                    "parallel_lanes_id_invalid",
                    f"Lane id `{lane_id}` is not a stable L#-style id",
                )
            )
        elif lane_id in seen_ids:
            issues.append(
                ValidationIssue(
                    "parallel_lanes_id_invalid",
                    f"Lane id `{lane_id}` is declared more than once",
                )
            )
        seen_ids.add(lane_id)
        if not lane.get("owned_surfaces"):
            issues.append(
                ValidationIssue(
                    "parallel_lanes_surfaces_required",
                    f"Lane `{lane_id}` declares no owned surfaces",
                )
            )
        if not lane.get("batches"):
            issues.append(
                ValidationIssue(
                    "parallel_lanes_batches_required",
                    f"Lane `{lane_id}` declares no batches",
                )
            )
        for surface in lane.get("owned_surfaces", []):
            reason = _surface_invalid_reason(str(surface))
            if reason is not None:
                issues.append(
                    ValidationIssue(
                        "parallel_lanes_surface_invalid",
                        f"Lane `{lane_id}` owned surface `{surface}` {reason};"
                        " surfaces must be repo-relative paths",
                    )
                )

    # Pairwise-disjoint owned surfaces with path-prefix semantics. Compared
    # case-insensitively (casefold): deliberately conservative for
    # case-insensitive filesystems — this flags overlap even where a
    # case-sensitive filesystem would distinguish the two paths.
    for i, left in enumerate(lanes):
        for right in lanes[i + 1:]:
            for left_surface in left.get("owned_surfaces", []):
                left_norm = _normalized_surface(str(left_surface)).casefold()
                for right_surface in right.get("owned_surfaces", []):
                    right_norm = _normalized_surface(str(right_surface)).casefold()
                    if (
                        left_norm == right_norm
                        or right_norm.startswith(left_norm + "/")
                        or left_norm.startswith(right_norm + "/")
                    ):
                        issues.append(
                            ValidationIssue(
                                "parallel_lanes_surface_overlap",
                                "Owned surfaces overlap: lane "
                                f"`{left.get('id')}` owns `{left_surface}` and lane "
                                f"`{right.get('id')}` owns `{right_surface}`",
                            )
                        )

    known = {str(lane.get("id", "")) for lane in lanes}
    edges: dict[str, list[str]] = {}
    for lane in lanes:
        lane_id = str(lane.get("id", ""))
        lane_edges: list[str] = []
        for dependency in lane.get("depends_on", []):
            dep = str(dependency)
            if dep in known:
                lane_edges.append(dep)
            elif not re.match(r"^B[1-9][0-9]*$", dep):
                issues.append(
                    ValidationIssue(
                        "parallel_lanes_dependency_unknown",
                        f"Lane `{lane_id}` depends on unknown reference `{dep}`",
                    )
                )
        edges[lane_id] = lane_edges

    # Cycle detection over lane-to-lane depends_on edges. Iterative DFS with
    # an explicit stack so arbitrarily deep in-bounds dependency chains
    # validate without hitting Python's recursion limit.
    state: dict[str, int] = {}  # 0 unvisited, 1 on-stack, 2 done
    for start in edges:
        if state.get(start, 0) != 0:
            continue
        state[start] = 1
        trail = [start]
        stack: list[tuple[str, Any]] = [(start, iter(edges.get(start, [])))]
        while stack:
            node, targets = stack[-1]
            advanced = False
            for target in targets:
                target_state = state.get(target, 0)
                if target_state == 1:
                    issues.append(
                        ValidationIssue(
                            "parallel_lanes_dependency_cycle",
                            "Lane depends_on cycle: "
                            + " -> ".join(trail + [target]),
                        )
                    )
                elif target_state == 0:
                    state[target] = 1
                    trail.append(target)
                    stack.append((target, iter(edges.get(target, []))))
                    advanced = True
                    break
            if not advanced:
                state[node] = 2
                stack.pop()
                trail.pop()

    return issues


def width_test(
    lanes: Sequence[Mapping[str, Any]],
    *,
    timings: Mapping[str, Any] | None = None,
    max_lanes: int = DEFAULT_MAX_LANES,
    risk: str = "standard",
) -> dict[str, Any]:
    """Apply the four Parallelves gates to an already-validated lane set.

    Partition validation (``validate_lane_partition``) is a required
    precondition performed by the caller — the CLI composes it before calling
    this function. Recommend-only; never launches anything.
    """

    if risk not in RISK_POSTURES:
        raise ValidationIssue(
            "parallel_lanes_risk_invalid",
            f"Unknown risk posture `{risk}`; expected one of {RISK_POSTURES}",
        )

    declined: list[str] = []
    lane_ids = [str(lane.get("id", "")) for lane in lanes]

    # Gate 1: structural width. v1 treats every listed lane as intended-concurrent.
    if not lanes:
        declined.append(DECLINE_NO_LANES)
    elif len(lanes) < MIN_STRUCTURAL_LANES:
        declined.append(DECLINE_SINGLE_LANE)
    else:
        known = set(lane_ids)
        for lane in lanes:
            if any(str(dep) in known for dep in lane.get("depends_on", [])):
                declined.append(DECLINE_CROSS_LANE_DEPENDENCY)
                break

    # Gate 2: worker dominance from recorded timings; absent history declines honestly.
    if (
        timings is None
        or "worker_seconds" not in timings
        or "driver_seconds" not in timings
    ):
        declined.append(DECLINE_NO_TIMINGS)
    else:
        # Defense in depth beyond the CLI loader: timing values must be real,
        # finite, non-negative numbers (not bool, not str) or the gate
        # declines — it must never spuriously pass on NaN/Infinity/garbage.
        values: dict[str, float] = {}
        for key in ("worker_seconds", "driver_seconds"):
            raw_value = timings[key]
            if isinstance(raw_value, bool) or not isinstance(
                raw_value, (int, float)
            ):
                break
            try:
                value = float(raw_value)
            except (OverflowError, TypeError, ValueError):
                break
            if not math.isfinite(value) or value < 0:
                break
            values[key] = value
        if len(values) != 2 or values.get("worker_seconds") == 0:
            declined.append(DECLINE_INVALID_TIMINGS)
        elif (
            values["worker_seconds"]
            < WORKER_DOMINANCE_RATIO * values["driver_seconds"]
        ):
            declined.append(DECLINE_DRIVER_DOMINATES)

    # Gate 3: lane budget.
    # Callers may tighten the budget, but v1's normative three-lane ceiling is
    # not configurable away through the pure-function API.
    effective_max_lanes = min(max_lanes, DEFAULT_MAX_LANES)
    if len(lanes) > effective_max_lanes:
        declined.append(DECLINE_OVER_MAX_LANES)

    # Gate 4: risk posture.
    if risk == HIGH_RISK_POSTURE:
        declined.append(DECLINE_HIGH_RISK)

    return {"parallel": not declined, "lanes": lane_ids, "declined": declined}
