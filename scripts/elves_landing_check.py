#!/usr/bin/env python3
"""Pre-land / readiness check: green CI + status:complete is not enough.

Policy: landable means plan Acceptance with proof.

Usage:
  python3 scripts/elves_landing_check.py
  python3 scripts/elves_landing_check.py --session .elves-session.json
  python3 scripts/elves_landing_check.py --session path/to/.elves-session.json \\
      --plan docs/plans/my-plan.md --execution-log docs/elves/execution-log.md

Exit codes:
  0 — all checks pass (or advisory-only warnings when --advisory)
  1 — blocking failures
  2 — usage / IO error

This script is intentionally narrow. It does not run tests or inspect PR checks.
It verifies that self-certified batch completion is backed by one-to-one
acceptance evidence in session JSON and the authoritative plan. Execution-log
and evidence-directory checks remain optional additional surfaces.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cobbler_runtime.acceptance import (
    BATCH_NUMBER_PATTERN,
    STABLE_ACCEPTANCE_ID_PATTERN,
    STABLE_BATCH_ACCEPTANCE_ID_RE,
    AcceptanceIssue,
    active_markdown as _shared_active_markdown,
    find_acceptance_section,
    normalize_batch_id,
    parse_markdown_acceptance_rows,
)
from cobbler_runtime.landing_authority import (
    EXACT_COMMIT_RE,
    LandingControl,
    attest_readiness,
    grant_driver_authorization,
    initial_control,
    invalidate_on_head_change,
    strip_worker_authority_claims,
    terminal_action,
)
from cobbler_runtime.landing_profile import evaluate_landing_profile
from cobbler_runtime.schema import ValidationIssue


DEFAULT_SESSION = ".elves-session.json"

# Structure/regex "lock" language that must not alone complete a split/god-file batch
# unless the plan Acceptance explicitly allows characterization-only completion.
LOCK_ONLY_PATTERNS = re.compile(
    r"(structure\s+already\s+exists|"
    r"characterization[\s-]?only|"
    r"regex\s+lock|"
    r"source[\s-]regex|"
    r"structure[\s-]only|"
    r"lock\s+behavior|"
    r"behavioral\s+lock)",
    re.IGNORECASE,
)

# Plan Acceptance criteria that look like real split/god-file outcomes.
SPLIT_ACCEPTANCE_PATTERNS = re.compile(
    r"(\bloc\b|"
    r"lines?\s+of\s+code|"
    r"facade|"
    r"extract|"
    r"split\s+(?:the\s+)?(?:file|module|god)|"
    r"under\s+\d+\s*(?:loc|lines)|"
    r"<=?\s*\d+\s*(?:loc|lines)|"
    r"max(?:imum)?\s+\d+\s*(?:loc|lines))",
    re.IGNORECASE,
)

CHARACTERIZATION_ALLOW_PATTERNS = re.compile(
    r"(characterization[\s-]?only|"
    r"structure[\s-]only\s+allowed|"
    r"lock[\s-]only\s+allowed|"
    r"explicitly\s+allows?\s+characterization)",
    re.IGNORECASE,
)

BATCH_HEADING = re.compile(
    rf"^###?\s+Batch\s+\[?({BATCH_NUMBER_PATTERN})\]?\s*[:.\-–—]?\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
LOOSE_BATCH_HEADING = re.compile(
    r"^###?\s+Batch\s+\[?([0-9]+)\]?\s*[:.\-–—]?\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
CHECKBOX = re.compile(r"^[ ]{0,3}[\-\*]\s+\[([ xX])\]\s+(.+)$", re.MULTILINE)
MASTER_ACCEPTANCE_HEADING = re.compile(
    r"(?im)^(#{1,6})\s+Master\s+Acceptance\s*$"
)
MARKDOWN_HEADING = re.compile(r"(?m)^(#{1,6})\s+.+$")
STABLE_BATCH_ACCEPTANCE_ID = STABLE_BATCH_ACCEPTANCE_ID_RE
VALIDATE_SECTION = re.compile(
    r"(?im)^\*\*Validate(?:\s+section)?(?:\s+for\s+batch\s+(\d+))?:\*\*"
)
MULTI_BATCH_CLOSE = re.compile(
    r"(?i)(close\s+remaining|batches?\s+\d+\s*[-–—,/&]\s*\d+|multi[\s-]?batch\s+close)"
)
GATE_NAMES = ("typecheck", "lint", "test", "build")


@dataclass
class Finding:
    severity: str  # ERROR | WARN
    code: str
    message: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    landing: dict[str, Any] | None = None
    project_landing: dict[str, Any] | None = None

    def error(self, code: str, message: str) -> None:
        self.findings.append(Finding("ERROR", code, message))

    def warn(self, code: str, message: str) -> None:
        self.findings.append(Finding("WARN", code, message))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "WARN"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check that Elves batch completion is backed by plan Acceptance evidence. "
            "Green CI + status:complete alone is not landable."
        )
    )
    parser.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help=f"Path to .elves-session.json (default: {DEFAULT_SESSION})",
    )
    parser.add_argument(
        "--plan",
        default=None,
        help="Plan markdown path (required; defaults to session plan_path when present).",
    )
    parser.add_argument(
        "--execution-log",
        default=None,
        help="Optional execution log path. Defaults to session execution_log_path when present.",
    )
    parser.add_argument(
        "--evidence-root",
        default=None,
        help=(
            "Optional SCRATCH/evidence root. When set, expects "
            "{root}/batch-N/{typecheck,lint,test,build} for each complete batch."
        ),
    )
    parser.add_argument(
        "--require-evidence-dirs",
        action="store_true",
        help="Treat missing gate evidence dirs as errors when --evidence-root is set.",
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="Print findings but always exit 0 when the session file is readable.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON report on stdout.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help=(
            "Repository root for strict landing provenance. When set, the session "
            "and plan must be ordinary, tracked files in this worktree and session "
            "branch/run identity is verified against Git."
        ),
    )
    parser.add_argument(
        "--project-base",
        default=None,
        help=(
            "Optional project-profile base ref. Defaults to session project_base_ref "
            "and then origin/main; it is resolved once to an exact commit."
        ),
    )
    parser.add_argument(
        "--grant-driver-authorization",
        metavar="SOURCE",
        default=None,
        help=(
            "Host-only active-run authority update (for example land-pr). Writes only "
            "session landing authority, preserves any exact-HEAD readiness attestation, "
            "and exits without running readiness again."
        ),
    )
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"Session file could not be read: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Session file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Session file must be a JSON object: {path}")
    return data


def as_batches(session: dict[str, Any]) -> list[dict[str, Any]]:
    batches = session.get("batches")
    if batches is None:
        return []
    if not isinstance(batches, list):
        raise SystemExit("Session field `batches` must be an array")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(batches):
        if not isinstance(item, dict):
            raise SystemExit(f"Session `batches[{index}]` must be an object")
        out.append(item)
    return out


def batch_id(batch: dict[str, Any]) -> str:
    raw = batch.get("id", batch.get("name", "?"))
    return str(raw)


def numeric_batch_id(batch: dict[str, Any]) -> int | None:
    """Resolve canonical ``B#`` or legacy non-negative batch identities."""

    return normalize_batch_id(batch.get("id"))


def acceptance_items(batch: dict[str, Any]) -> list[dict[str, Any]]:
    raw = batch.get("acceptance")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SystemExit(f"Batch {batch_id(batch)} field `acceptance` must be an array")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SystemExit(
                f"Batch {batch_id(batch)} `acceptance[{index}]` must be an object"
            )
        out.append(item)
    return out


def master_acceptance_items(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Return canonical branch-level Master Acceptance evidence rows."""
    raw = session.get("master_acceptance")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SystemExit("Session field `master_acceptance` must be an array")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SystemExit(
                f"Session `master_acceptance[{index}]` must be an object"
            )
        out.append(item)
    return out


def check_session_batches(session: dict[str, Any], report: Report) -> None:
    batches = as_batches(session)
    if not batches:
        report.error(
            "no_batches",
            "Session has no `batches` array. Landing requires per-batch status and acceptance evidence.",
        )
        return

    seen_batch_ids: set[int] = set()
    for batch in batches:
        bid = batch_id(batch)
        numeric_id = numeric_batch_id(batch)
        if numeric_id is None:
            report.error(
                "batch_id_invalid",
                f"Batch {bid!r} must have a canonical `B#` or an unambiguous "
                "legacy non-negative integer `id` matching a plan Batch heading; "
                "both B0 and B1+ are valid.",
            )
        elif numeric_id in seen_batch_ids:
            report.error("batch_id_duplicate", f"Duplicate session batch id: {numeric_id}")
        else:
            seen_batch_ids.add(numeric_id)
        status = str(batch.get("status", "")).strip().lower()
        if status != "complete":
            report.error(
                "batch_incomplete",
                f"Batch {bid} status is {status!r}, not 'complete'.",
            )
            continue

        items = acceptance_items(batch)
        if not items:
            report.error(
                "missing_acceptance",
                f"Batch {bid} is status=complete but `acceptance` is missing or empty. "
                "Record plan Acceptance criteria with evidence before marking complete.",
            )
            continue

        for index, item in enumerate(items):
            criterion = str(item.get("criterion") or "").strip()
            evidence = str(item.get("evidence") or "").strip()
            met = item.get("met")
            label = criterion or f"item[{index}]"

            if met is not True:
                report.error(
                    "acceptance_not_met",
                    f"Batch {bid} acceptance {label!r}: met must be true (got {met!r}).",
                )
            if not criterion:
                report.error(
                    "acceptance_no_criterion",
                    f"Batch {bid} acceptance item {index} is missing `criterion`.",
                )
            if not evidence:
                report.error(
                    "acceptance_no_evidence",
                    f"Batch {bid} acceptance {label!r} is missing `evidence` "
                    "(path, command transcript, metric, or commit SHA).",
                )

        # God-file / structure-lock rule: lock-only acceptance cannot alone complete
        # a split batch unless characterization-only is explicitly allowed.
        criteria_text = " ".join(str(i.get("criterion") or "") for i in items)
        evidence_text = " ".join(str(i.get("evidence") or "") for i in items)
        blob = f"{criteria_text} {evidence_text}"
        if LOCK_ONLY_PATTERNS.search(blob) and not CHARACTERIZATION_ALLOW_PATTERNS.search(blob):
            if SPLIT_ACCEPTANCE_PATTERNS.search(blob) or any(
                SPLIT_ACCEPTANCE_PATTERNS.search(str(i.get("criterion") or "")) for i in items
            ):
                # Has both lock language and split language — OK if met with real evidence.
                pass
            else:
                # All acceptance looks lock/structure-only with no split metric.
                only_lock = all(
                    LOCK_ONLY_PATTERNS.search(str(i.get("criterion") or ""))
                    or LOCK_ONLY_PATTERNS.search(str(i.get("evidence") or ""))
                    or not SPLIT_ACCEPTANCE_PATTERNS.search(str(i.get("criterion") or ""))
                    for i in items
                )
                if only_lock and not any(
                    SPLIT_ACCEPTANCE_PATTERNS.search(str(i.get("criterion") or "")) for i in items
                ):
                    # Soft when criteria are ordinary (not god-file related).
                    # Hard when every criterion is lock-only style.
                    if all(
                        LOCK_ONLY_PATTERNS.search(str(i.get("criterion") or ""))
                        or LOCK_ONLY_PATTERNS.search(str(i.get("evidence") or ""))
                        for i in items
                    ):
                        report.error(
                            "god_file_lock_only",
                            f"Batch {bid}: structure/regex lock evidence alone must not complete "
                            "a split/god-file batch unless plan Acceptance explicitly allows "
                            "characterization-only. Add LOC/facade/size evidence or a hard-stop note.",
                        )


def check_session_master_acceptance(session: dict[str, Any], report: Report) -> None:
    """Validate canonical top-level Master Acceptance evidence values."""
    for index, item in enumerate(master_acceptance_items(session)):
        criterion = str(item.get("criterion") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        met = item.get("met")
        label = criterion or f"item[{index}]"
        if met is not True:
            report.error(
                "master_acceptance_not_met",
                f"Master acceptance {label!r}: met must be true (got {met!r}).",
            )
        if not criterion:
            report.error(
                "master_acceptance_no_criterion",
                f"Master acceptance item {index} is missing `criterion`.",
            )
        if not evidence:
            report.error(
                "master_acceptance_no_evidence",
                f"Master acceptance {label!r} is missing `evidence` "
                "(path, command transcript, metric, or commit SHA).",
            )


def normalize_criterion(value: Any) -> str:
    """Normalize legacy criterion text without erasing semantic punctuation."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip().casefold()


def active_markdown(plan_text: str) -> str:
    """Compatibility wrapper around the shared active-Markdown lexer."""

    return _shared_active_markdown(plan_text)


def _parse_checkboxes(section: str) -> list[dict[str, Any]]:
    return [
        {
            "checked": box.group(1).lower() == "x",
            "text": box.group(2).strip(),
        }
        for box in CHECKBOX.finditer(section)
    ]


def _parse_stable_checkboxes(
    section: str,
    *,
    base_line: int = 1,
) -> list[dict[str, Any]]:
    """Parse stable-ID checkboxes, including wrapped criterion continuation lines."""
    rows, _ = parse_markdown_acceptance_rows(
        section,
        require_checkbox=True,
        base_line=base_line,
    )
    return [
        {
            "checked": bool(row.checked),
            "id": row.id,
            "criterion": row.criterion,
            "line": row.line,
        }
        for row in rows
    ]


def parse_master_acceptance(plan_text: str) -> tuple[bool, list[dict[str, Any]]]:
    """Parse global Master Acceptance checkboxes outside per-batch sections."""
    found = False
    acceptance: list[dict[str, Any]] = []
    for match in MASTER_ACCEPTANCE_HEADING.finditer(plan_text):
        found = True
        level = len(match.group(1))
        end = len(plan_text)
        for heading in MARKDOWN_HEADING.finditer(plan_text, match.end()):
            if len(heading.group(1)) <= level:
                end = heading.start()
                break
        acceptance.extend(_parse_checkboxes(plan_text[match.end() : end]))
    return found, acceptance


def parse_master_stable_acceptance(plan_text: str) -> tuple[bool, list[dict[str, Any]]]:
    """Parse stable-ID rows only from explicit Master Acceptance sections."""
    found, acceptance, _ = parse_master_stable_acceptance_details(plan_text)
    return found, acceptance


def parse_master_stable_acceptance_details(
    plan_text: str,
) -> tuple[bool, list[dict[str, Any]], list[AcceptanceIssue]]:
    """Parse Master Acceptance rows and retain line-specific syntax issues."""

    found = False
    acceptance: list[dict[str, Any]] = []
    issues: list[AcceptanceIssue] = []
    for match in MASTER_ACCEPTANCE_HEADING.finditer(plan_text):
        found = True
        level = len(match.group(1))
        end = len(plan_text)
        for heading in MARKDOWN_HEADING.finditer(plan_text, match.end()):
            if len(heading.group(1)) <= level:
                end = heading.start()
                break
        section = plan_text[match.end() : end]
        base_line = plan_text.count("\n", 0, match.end()) + 1
        rows, section_issues = parse_markdown_acceptance_rows(
            section,
            require_checkbox=True,
            base_line=base_line,
        )
        acceptance.extend(
            {
                "checked": bool(row.checked),
                "id": row.id,
                "criterion": row.criterion,
                "line": row.line,
            }
            for row in rows
        )
        issues.extend(section_issues)
    return found, acceptance, issues


def parse_plan_batches(plan_text: str) -> dict[int, dict[str, Any]]:
    """Return parsed Batch headings and their explicit Acceptance sections."""
    matches = list(BATCH_HEADING.finditer(plan_text))
    result: dict[int, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plan_text)
        body = plan_text[start:end]
        bid = normalize_batch_id(match.group(1))
        if bid is None:
            continue
        title = match.group(2).strip()
        body_line = plan_text.count("\n", 0, start) + 1
        section = find_acceptance_section(body, base_line=body_line)
        acceptance_section = section.text if section is not None else ""
        acceptance = _parse_checkboxes(acceptance_section) if section is not None else []
        stable_rows, syntax_issues = parse_markdown_acceptance_rows(
            acceptance_section,
            require_checkbox=True,
            base_line=section.content_line if section is not None else body_line,
        )
        result[bid] = {
            "title": title,
            "acceptance": acceptance,
            "stable_acceptance": [
                {
                    "checked": bool(row.checked),
                    "id": row.id,
                    "criterion": row.criterion,
                    "line": row.line,
                }
                for row in stable_rows
            ],
            "acceptance_syntax_issues": syntax_issues,
            "acceptance_section": acceptance_section,
            "has_acceptance_section": section is not None,
            "body": body,
        }
    return result


def check_legacy_acceptance_mapping(
    plan_batches: dict[int, dict[str, Any]],
    master_acceptance: list[dict[str, Any]],
    session_master_acceptance: list[dict[str, Any]],
    session: dict[str, Any],
    report: Report,
) -> None:
    """Require one evidence row per normalized legacy plan criterion."""
    session_by_id = {
        numeric_batch_id(batch): batch
        for batch in as_batches(session)
        if numeric_batch_id(batch) is not None
    }
    remaining: Counter[str] = Counter()
    labels: dict[str, str] = {}

    for bid, info in sorted(plan_batches.items()):
        expected = Counter(normalize_criterion(item["text"]) for item in info["acceptance"])
        for item in info["acceptance"]:
            labels.setdefault(normalize_criterion(item["text"]), item["text"])
        duplicates = [labels[key] for key, count in expected.items() if count > 1]
        for criterion in duplicates:
            report.error(
                "plan_acceptance_duplicate_criterion",
                f"Plan Batch {bid} repeats legacy Acceptance criterion {criterion!r}.",
            )

        batch = session_by_id.get(bid)
        observed = Counter()
        if batch is not None:
            observed.update(
                normalize_criterion(item.get("criterion"))
                for item in acceptance_items(batch)
            )
        for key, count in expected.items():
            matched = min(count, observed[key])
            if matched < count:
                report.error(
                    "acceptance_criterion_missing",
                    f"Plan Batch {bid} criterion {labels[key]!r} has no one-to-one "
                    "session evidence row.",
                )
            observed[key] -= matched
            if observed[key] <= 0:
                observed.pop(key, None)
        remaining.update(observed)

    for item in session_master_acceptance:
        key = normalize_criterion(item.get("criterion"))
        labels.setdefault(key, str(item.get("criterion") or ""))
        remaining[key] += 1

    master_expected = Counter(
        normalize_criterion(item["text"]) for item in master_acceptance
    )
    for item in master_acceptance:
        labels.setdefault(normalize_criterion(item["text"]), item["text"])
    for key, count in master_expected.items():
        if count > 1:
            report.error(
                "master_acceptance_duplicate_criterion",
                f"Master Acceptance repeats criterion {labels[key]!r}.",
            )
        matched = min(count, remaining[key])
        if matched < count:
            report.error(
                "master_acceptance_evidence_missing",
                f"Master Acceptance criterion {labels[key]!r} has no one-to-one "
                "session evidence row.",
            )
        remaining[key] -= matched
        if remaining[key] <= 0:
            remaining.pop(key, None)

    for key, count in sorted(remaining.items()):
        report.error(
            "acceptance_evidence_unrelated",
            f"Session contains {count} unrelated legacy evidence row(s) for "
            f"{labels.get(key, key)!r} that do not map to plan Acceptance.",
        )


def check_plan(plan_path: Path, session: dict[str, Any], report: Report) -> None:
    if not plan_path.exists():
        report.error("plan_missing", f"Plan file not found: {plan_path}")
        return
    try:
        text = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        report.error("plan_unparseable", f"Plan file could not be parsed: {plan_path}: {exc}")
        return
    text = active_markdown(text)
    for match in LOOSE_BATCH_HEADING.finditer(text):
        raw_batch = match.group(1)
        if (
            re.fullmatch(BATCH_NUMBER_PATTERN, raw_batch) is not None
            and normalize_batch_id(raw_batch) is not None
        ):
            continue
        reason = (
            "uses an ambiguous leading-zero id; use Batch 0 or a nonzero "
            "number without leading zeros"
            if re.fullmatch(BATCH_NUMBER_PATTERN, raw_batch) is None
            else "exceeds the supported numeric bound"
        )
        report.error(
            "batch_id_invalid",
            f"Plan Batch {raw_batch[:80]} {reason}.",
        )

    plan_batches = parse_plan_batches(text)
    if not plan_batches:
        report.error(
            "plan_no_batch_headings",
            f"Could not parse Batch headings from {plan_path}. "
            "Expected `### Batch N: Name` with Acceptance criteria checkboxes.",
        )
        return

    heading_ids = [
        batch_number
        for match in BATCH_HEADING.finditer(text)
        if (batch_number := normalize_batch_id(match.group(1))) is not None
    ]
    if len(heading_ids) != len(set(heading_ids)):
        report.error(
            "plan_duplicate_batch_heading",
            f"Plan contains duplicate Batch heading ids: {heading_ids}",
        )

    master_present, master_acceptance = parse_master_acceptance(text)
    _, master_stable, master_syntax_issues = parse_master_stable_acceptance_details(text)
    for issue in master_syntax_issues:
        report.error(issue.code, issue.message)
    if master_present and not master_acceptance:
        if not master_syntax_issues:
            report.error(
                "master_acceptance_unparseable",
                "Master Acceptance heading has no parseable checkboxes.",
            )
    for item in master_acceptance:
        if not item["checked"]:
            report.error(
                "plan_acceptance_open",
                f"Master Acceptance is unchecked: {item['text'][:120]}",
            )

    session_batches = {
        numeric: batch
        for batch in as_batches(session)
        if (numeric := numeric_batch_id(batch)) is not None
    }
    plan_batch_ids = set(plan_batches)
    session_batch_ids = set(session_batches)
    for bid in sorted(session_batch_ids - plan_batch_ids):
        report.error(
            "session_batch_missing_in_plan",
            f"Session Batch {bid} has no matching Batch heading in the authoritative plan.",
        )
    for bid, info in sorted(plan_batches.items()):
        syntax_issues = info["acceptance_syntax_issues"]
        for issue in syntax_issues:
            report.error(issue.code, issue.message)
        if not info["has_acceptance_section"]:
            report.error(
                "plan_acceptance_section_missing",
                f"Plan Batch {bid} has no explicit Acceptance criteria section. "
                "Accepted labels include `**Acceptance criteria:**`, "
                "`**Acceptance criteria**:`, `### Acceptance criteria`, and "
                "`Acceptance criteria:`.",
            )
        elif not info["acceptance"]:
            if not syntax_issues:
                report.error(
                    "plan_acceptance_unparseable",
                    f"Plan Batch {bid} has no parseable Acceptance criteria checkboxes.",
                )
        open_boxes = [a for a in info["acceptance"] if not a["checked"]]
        if open_boxes:
            titles = "; ".join(a["text"][:80] for a in open_boxes[:5])
            report.error(
                "plan_acceptance_open",
                f"Plan Batch {bid} has unchecked Acceptance criteria: {titles}",
            )

        # God-file targets still open: if acceptance mentions LOC/facade and is checked
        # only via structure language in session, the session checker handles it.
        # Here: if plan still has open LOC-style boxes, already covered by open_boxes.

        sb = session_batches.get(bid)
        if sb is None:
            # Plan batch with no session entry is only an error if we expected full land.
            report.error(
                "plan_batch_missing_in_session",
                f"Plan Batch {bid} has no matching entry in session `batches`.",
            )
            continue

        # If plan acceptance requires split metrics, session evidence must not be lock-only only.
        plan_needs_split = any(
            SPLIT_ACCEPTANCE_PATTERNS.search(a["text"]) for a in info["acceptance"]
        )
        plan_allows_char = CHARACTERIZATION_ALLOW_PATTERNS.search(info["body"]) or any(
            CHARACTERIZATION_ALLOW_PATTERNS.search(a["text"]) for a in info["acceptance"]
        )
        if plan_needs_split and not plan_allows_char:
            items = acceptance_items(sb)
            if items and all(
                LOCK_ONLY_PATTERNS.search(str(i.get("criterion", "")))
                or LOCK_ONLY_PATTERNS.search(str(i.get("evidence", "")))
                for i in items
            ):
                report.error(
                    "god_file_plan_mismatch",
                    f"Plan Batch {bid} requires LOC/facade/split Acceptance, but session "
                    "acceptance evidence is structure/regex-lock only.",
                )

    # Stable acceptance ID one-to-one mapping (B#-A# / M-A#). Parse only
    # explicit batch Acceptance and Master Acceptance sections so task lists or
    # prose cannot be mistaken for landing evidence.
    session_master = master_acceptance_items(session)
    all_evidence_items: list[
        tuple[dict[str, Any] | None, dict[str, Any]]
    ] = [
        (batch, item)
        for batch in as_batches(session)
        for item in acceptance_items(batch)
    ]
    all_evidence_items.extend((None, item) for item in session_master)
    evidence_has_ids = any(str(item.get("id") or "").strip() for _, item in all_evidence_items)
    batch_stable_rows = [
        item
        for info in plan_batches.values()
        for item in info["stable_acceptance"]
    ]
    stable_syntax_issues = [
        issue
        for info in plan_batches.values()
        for issue in info["acceptance_syntax_issues"]
    ] + master_syntax_issues
    stable_mode = bool(batch_stable_rows or master_stable or stable_syntax_issues) or evidence_has_ids
    if not stable_mode:
        check_legacy_acceptance_mapping(
            plan_batches,
            master_acceptance,
            session_master,
            session,
            report,
        )
        return

    plan_items: list[dict[str, Any]] = []
    for bid, info in sorted(plan_batches.items()):
        parsed = info["stable_acceptance"]
        syntax_issues = info["acceptance_syntax_issues"]
        if len(parsed) != len(info["acceptance"]) and not syntax_issues:
            report.error(
                "plan_acceptance_id_missing",
                f"Stable-ID mode requires every Acceptance checkbox in Batch {bid} "
                "to have a B#-A# id and separator.",
            )
        for item in parsed:
            aid = item["id"]
            match = STABLE_BATCH_ACCEPTANCE_ID.fullmatch(aid)
            if match is None:
                report.error(
                    "plan_acceptance_wrong_scope",
                    f"Master acceptance id {aid} must appear under `## Master Acceptance`, "
                    f"not Batch {bid}.",
                )
            else:
                acceptance_batch = normalize_batch_id(match.group(1))
                if acceptance_batch is None:
                    report.error(
                        "acceptance_id_invalid",
                        f"Plan acceptance {aid[:80]} exceeds the supported numeric bound.",
                    )
                elif acceptance_batch != bid:
                    report.error(
                        "plan_acceptance_wrong_batch",
                        f"Plan acceptance {aid} appears under Batch {bid}; it belongs under "
                        f"Batch {match.group(1)}.",
                    )
            plan_items.append({**item, "batch_id": bid})

    if not master_present:
        report.error(
            "master_acceptance_missing",
            "Stable-ID plans require an explicit `## Master Acceptance` section.",
        )
    elif not master_stable:
        report.error(
            "master_acceptance_unparseable",
            "Stable-ID plans require at least one parseable M-A# row under Master Acceptance.",
        )
    if len(master_stable) != len(master_acceptance):
        report.error(
            "master_acceptance_id_missing",
            "Stable-ID mode requires every Master Acceptance checkbox to have an M-A# "
            "id and separator.",
        )
    for item in master_stable:
        aid = item["id"]
        if not aid.startswith("M-A"):
            report.error(
                "plan_acceptance_wrong_scope",
                f"Batch acceptance id {aid} must appear in its Batch Acceptance section, "
                "not Master Acceptance.",
            )
        plan_items.append({**item, "batch_id": None})

    if stable_syntax_issues and not plan_items:
        report.error(
            "plan_acceptance_unparseable",
            "Plan contains stable-looking Acceptance rows but none could be parsed "
            "from explicit Batch or Master Acceptance sections.",
        )

    plan_by_id: dict[str, dict[str, Any]] = {}
    for item in plan_items:
        aid = item["id"]
        if not item["checked"]:
            report.error(
                "plan_acceptance_open",
                f"Plan stable Acceptance {aid} is unchecked: {item['criterion']}",
            )
        if aid in plan_by_id:
            report.error(
                "plan_acceptance_duplicate_id",
                f"Duplicate plan acceptance id {aid}.",
            )
        else:
            plan_by_id[aid] = item

    canonical_master_present = "master_acceptance" in session
    legacy_master_rows = [
        (batch, item)
        for batch, item in all_evidence_items
        if batch is not None and str(item.get("id") or "").strip().startswith("M-A")
    ]
    if legacy_master_rows and not canonical_master_present:
        report.warn(
            "legacy_master_acceptance_location",
            "Session stores M-A# evidence inside a batch `acceptance` array. "
            "This remains readable for compatibility; new sessions should use the "
            "top-level `master_acceptance` array.",
        )

    evidence_by_id: dict[
        str, tuple[dict[str, Any] | None, dict[str, Any]]
    ] = {}
    for batch, item in all_evidence_items:
        aid = str(item.get("id") or "").strip()
        if not aid:
            scope = (
                "top-level master_acceptance"
                if batch is None
                else f"Batch {batch_id(batch)}"
            )
            report.error(
                "acceptance_id_missing",
                f"Stable-ID plan requires an id on every evidence row in {scope}.",
            )
            continue
        if not re.fullmatch(STABLE_ACCEPTANCE_ID_PATTERN, aid):
            report.error(
                "acceptance_id_invalid",
                f"Session evidence id {aid!r} is not a B#-A# or M-A# stable id.",
            )
        batch_match = STABLE_BATCH_ACCEPTANCE_ID.fullmatch(aid)
        if batch_match is not None:
            if batch is None:
                report.error(
                    "acceptance_id_wrong_scope",
                    f"Batch evidence {aid} must be stored in Batch "
                    f"{batch_match.group(1)} `acceptance`, not top-level "
                    "`master_acceptance`.",
                )
            else:
                expected_batch = numeric_batch_id(batch)
                acceptance_batch = normalize_batch_id(batch_match.group(1))
                if (
                    expected_batch is None
                    or acceptance_batch is None
                    or acceptance_batch != expected_batch
                ):
                    report.error(
                        "acceptance_id_wrong_batch",
                        f"Evidence {aid} is stored in session Batch {batch_id(batch)}; "
                        f"B{batch_match.group(1)} evidence must stay in Batch "
                        f"{batch_match.group(1)}.",
                    )
        elif aid.startswith("M-A") and batch is not None and canonical_master_present:
            report.error(
                "acceptance_id_wrong_scope",
                f"Master evidence {aid} must be stored in top-level "
                "`master_acceptance`, not Batch {batch_id(batch)} `acceptance`.",
            )
        if aid in evidence_by_id:
            report.error(
                "acceptance_evidence_duplicate_id",
                f"Session contains duplicate evidence rows for {aid}.",
            )
        else:
            evidence_by_id[aid] = (batch, item)

    for aid, plan_item in sorted(plan_by_id.items()):
        observed = evidence_by_id.get(aid)
        if observed is None:
            report.error(
                "acceptance_evidence_missing",
                f"Plan acceptance {aid} has no one-to-one session evidence row.",
            )
            continue
        _, evidence_item = observed
        observed_criterion = str(evidence_item.get("criterion") or "").strip()
        expected_criterion = str(plan_item["criterion"]).strip()
        if observed_criterion != expected_criterion:
            report.error(
                "acceptance_criterion_mismatch",
                f"Session evidence criterion for {aid} does not exactly match the "
                f"authoritative plan: expected {expected_criterion[:160]!r}, "
                f"got {observed_criterion[:160]!r}.",
            )

    for aid in sorted(set(evidence_by_id) - set(plan_by_id)):
        report.error(
            "acceptance_evidence_unrelated",
            f"Session evidence {aid} does not map to an authoritative plan Acceptance row.",
        )


def check_execution_log(
    log_path: Path,
    report: Report,
    *,
    expected_batch_ids: set[int] | None = None,
) -> None:
    if not log_path.exists():
        report.warn("execution_log_missing", f"Execution log not found: {log_path}")
        return
    text = log_path.read_text(encoding="utf-8")

    if MULTI_BATCH_CLOSE.search(text):
        # Multi-batch closes require explicit, labeled Validate sections. Batch
        # headings alone are navigation, not validation evidence.
        validate_hits = VALIDATE_SECTION.findall(text)
        # findall with one group returns list of group contents (batch ids or '')
        batch_ids_with_validate = {int(v) for v in validate_hits if v}
        expected = set(expected_batch_ids or set())
        missing = sorted(expected - batch_ids_with_validate) if expected else []
        if len(batch_ids_with_validate) < 2 or missing:
            suffix = f" Missing labeled batches: {missing}." if missing else ""
            report.error(
                "multi_batch_close",
                "Execution log mentions multi-batch close / close remaining without "
                "separate `**Validate for batch N:**` sections per completed batch."
                + suffix,
            )


def check_evidence_dirs(
    root: Path,
    session: dict[str, Any],
    report: Report,
    *,
    required: bool,
) -> None:
    if not root.exists():
        msg = f"Evidence root does not exist: {root}"
        if required:
            report.error("evidence_root_missing", msg)
        else:
            report.warn("evidence_root_missing", msg)
        return

    for batch in as_batches(session):
        if str(batch.get("status", "")).strip().lower() != "complete":
            continue
        raw_bid = batch_id(batch)
        numeric_bid = numeric_batch_id(batch)
        bid = numeric_bid if numeric_bid is not None else raw_bid
        candidate_names = [f"batch-{bid}", f"batch_{bid}"]
        if raw_bid != str(bid):
            candidate_names.extend((f"batch-{raw_bid}", f"batch_{raw_bid}"))
        candidates = [root / name for name in candidate_names]
        batch_dir = next(
            (candidate for candidate in candidates if candidate.is_dir()),
            candidates[0],
        )
        if not batch_dir.is_dir():
            msg = f"Missing evidence dir for batch {bid}: expected {root}/batch-{bid}/"
            if required:
                report.error("evidence_dir_missing", msg)
            else:
                report.warn("evidence_dir_missing", msg)
            continue
        for gate in GATE_NAMES:
            gate_path = batch_dir / gate
            # Accept file or directory (transcripts often live as gate.log or gate/stdout.txt)
            has = gate_path.exists() or (batch_dir / f"{gate}.log").exists() or (
                batch_dir / f"{gate}.txt"
            ).exists()
            if not has:
                msg = (
                    f"Batch {bid} evidence missing gate `{gate}` under {batch_dir} "
                    f"(expected `{gate}`, `{gate}.log`, or `{gate}.txt`)."
                )
                if required:
                    report.error("evidence_gate_missing", msg)
                else:
                    report.warn("evidence_gate_missing", msg)


def resolve_path(raw: str | None, base: Path) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )


def _strict_repo_file(
    raw: str | Path,
    *,
    base: Path,
    repo_root: Path,
    label: str,
    report: Report,
) -> Path | None:
    """Resolve an ordinary tracked file without allowing symlink indirection."""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    lexical = Path(os.path.abspath(candidate))
    try:
        resolved = lexical.resolve(strict=True)
        relative = resolved.relative_to(repo_root)
    except (OSError, ValueError):
        report.error(
            f"{label}_outside_repo",
            f"{label.capitalize()} path must stay inside the repository: {lexical}",
        )
        return None

    cursor = lexical
    while cursor != cursor.parent:
        if cursor.is_symlink():
            report.error(
                f"{label}_symlink",
                f"{label.capitalize()} path must not use a symlink: {cursor}",
            )
            return None
        try:
            at_repo_root = cursor.resolve(strict=False) == repo_root
        except OSError:
            at_repo_root = False
        if at_repo_root:
            break
        cursor = cursor.parent
    if not lexical.is_file():
        report.error(
            f"{label}_not_regular",
            f"{label.capitalize()} must be an existing regular file: {lexical}",
        )
        return None
    rel_text = relative.as_posix()
    tracked = _git(repo_root, "ls-files", "--error-unmatch", "--", rel_text)
    if tracked.returncode != 0:
        report.error(
            f"{label}_untracked",
            f"{label.capitalize()} must be tracked by Git: {rel_text}",
        )
        return None
    committed = _git(repo_root, "cat-file", "-e", f"HEAD:{rel_text}")
    if committed.returncode != 0:
        report.error(
            f"{label}_not_committed",
            f"{label.capitalize()} must exist in the current HEAD tree: {rel_text}",
        )
        return None
    return resolved


def _check_session_git_identity(
    session: dict[str, Any], repo_root: Path, report: Report
) -> None:
    run_id = session.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        report.error(
            "session_run_id_missing",
            "Final landing session must record a non-empty `run_id`.",
        )

    branch = session.get("branch")
    current = _git(repo_root, "branch", "--show-current")
    current_branch = current.stdout.strip() if current.returncode == 0 else ""
    if not isinstance(branch, str) or not branch.strip():
        report.error(
            "session_branch_missing",
            "Final landing session must record the active `branch`.",
        )
    elif not current_branch or branch != current_branch:
        report.error(
            "session_branch_mismatch",
            f"Session branch {branch!r} does not match active branch {current_branch!r}.",
        )

    start_head = session.get("start_head")
    if not isinstance(start_head, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", start_head):
        report.error(
            "session_start_head_invalid",
            "Final landing session must record an exact 40-character `start_head` commit.",
        )
        return
    resolved = _git(repo_root, "rev-parse", "--verify", f"{start_head}^{{commit}}")
    if resolved.returncode != 0 or resolved.stdout.strip().lower() != start_head.lower():
        report.error(
            "session_start_head_missing",
            f"Session start_head is not an exact commit in this repository: {start_head}",
        )
        return
    ancestor = _git(repo_root, "merge-base", "--is-ancestor", start_head, "HEAD")
    if ancestor.returncode != 0:
        report.error(
            "session_start_head_not_ancestor",
            f"Session start_head {start_head} is not an ancestor of current HEAD.",
        )


def _landing_control_from_session(
    session: dict[str, Any], report: Report
) -> tuple[LandingControl, dict[str, Any] | None]:
    """Load only host-owned landing state; worker authority claims are ignored."""

    raw = session.get("landing")
    if raw is None:
        return initial_control(), None
    if not isinstance(raw, dict):
        report.error("landing_invalid", "Session field `landing` must be an object.")
        return initial_control(), None

    if raw.get("worker_merge_authority") is not False:
        report.error(
            "worker_merge_authority_invalid",
            "Session landing.worker_merge_authority must be false; a worker can never "
            "authorize or perform merge.",
        )
    try:
        control = initial_control(
            landing_outcome=str(raw.get("outcome") or "landable_pr"),
            driver_authorized=raw.get("driver_authorized") is True,
        )
    except ValueError as exc:
        report.error("landing_outcome_invalid", str(exc))
        control = initial_control()

    worker_payload = session.get("worker_report")
    if isinstance(worker_payload, dict):
        stripped = strip_worker_authority_claims(control, worker_payload)
        if stripped.stripped:
            report.warn(
                "worker_authority_claims_ignored",
                "Ignored worker-owned landing authority fields: "
                + ", ".join(stripped.stripped),
            )

    readiness = raw.get("readiness")
    if readiness is None:
        return control, None
    if not isinstance(readiness, dict):
        report.error(
            "landing_readiness_invalid",
            "Session landing.readiness must be an object when present.",
        )
        return control, None
    return control, readiness


def _check_project_landing_profile(
    session: dict[str, Any],
    repo_root: Path,
    report: Report,
    *,
    base_ref: str | None,
) -> None:
    configured_base = base_ref or session.get("project_base_ref") or "origin/main"
    if not isinstance(configured_base, str) or not configured_base.strip():
        report.error(
            "project_landing_base_invalid",
            "Project landing base must be a non-empty Git ref.",
        )
        return
    result = evaluate_landing_profile(repo_root, base_ref=configured_base)
    report.project_landing = result.to_dict()
    for diagnostic in result.diagnostics:
        report.error(diagnostic.code, diagnostic.message)
    for outcome in result.checks:
        if outcome.status != "failed":
            continue
        message = (
            f"Project landing check {outcome.id!r} failed"
            + (f": {outcome.code}" if outcome.code else "")
        )
        if outcome.severity == "advisory":
            report.warn("project_landing_advisory_failed", message)
        else:
            report.error("project_landing_blocking_failed", message)


def _check_host_landing_control(
    session: dict[str, Any], repo_root: Path, report: Report
) -> None:
    """Bind declared v2.3 landing control to a required exact-HEAD attestation."""

    current = _git(repo_root, "rev-parse", "--verify", "HEAD^{commit}")
    current_head = current.stdout.strip() if current.returncode == 0 else ""
    if EXACT_COMMIT_RE.fullmatch(current_head) is None:
        report.error(
            "current_head_invalid",
            "Landing readiness requires Git to resolve HEAD to an exact 40-character commit.",
        )
        return

    from cobbler_runtime.teams import readiness_check as team_readiness_check
    try:
        team_readiness_check(session, current_head)
    except ValidationIssue as exc:
        report.error(exc.code, exc.message)

    control, readiness = _landing_control_from_session(session, report)
    if readiness is None:
        report.landing = terminal_action(control, current_head=current_head)
        if isinstance(session.get("landing"), dict):
            report.error(
                "readiness_missing",
                "Session declares v2.3 landing control but has no host exact-HEAD "
                "readiness attestation. Attest readiness before declaring the PR landable "
                "or authorizing merge.",
            )
        return

    attested_head = readiness.get("head")
    if not isinstance(attested_head, str) or EXACT_COMMIT_RE.fullmatch(attested_head) is None:
        report.error(
            "readiness_head_invalid",
            "Session landing.readiness.head must be an exact 40-character commit HEAD.",
        )
        report.landing = terminal_action(control, current_head=current_head)
        return
    if attested_head.lower() != current_head.lower():
        invalidated = invalidate_on_head_change(
            LandingControl(
                landing_outcome=control.landing_outcome,
                driver_authorized=control.driver_authorized,
                ready=True,
                readiness_head=attested_head,
            ),
            current_head=current_head,
        )
        report.error(
            "readiness_head_changed",
            f"Readiness was attested at {attested_head}, but current HEAD is "
            f"{current_head}; the attestation is invalidated and must be refreshed.",
        )
        report.landing = terminal_action(invalidated, current_head=current_head)
        return

    inputs_digest = readiness.get("inputs_digest")
    if not isinstance(inputs_digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", inputs_digest) is None:
        report.error(
            "readiness_digest_invalid",
            "Session landing.readiness.inputs_digest must be a 64-character SHA-256 digest.",
        )
        report.landing = terminal_action(control, current_head=current_head)
        return

    project_result = report.project_landing
    project_green = True
    project_digest: str | None = None
    if project_result is not None and project_result.get("profile_present") is True:
        live_digest = project_result.get("digest")
        attested_digest = readiness.get("project_landing_checks_digest")
        attested_green = readiness.get("project_landing_checks_green") is True
        if not attested_green:
            report.error(
                "project_landing_attestation_missing",
                "Present project landing profile requires host-owned "
                "project_landing_checks_green:true readiness evidence.",
            )
        if (
            not isinstance(attested_digest, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", attested_digest) is None
        ):
            report.error(
                "project_landing_digest_invalid",
                "Present project landing profile requires a 64-character host-owned digest.",
            )
        elif not isinstance(live_digest, str) or attested_digest.lower() != live_digest.lower():
            report.error(
                "project_landing_digest_mismatch",
                "Host project landing digest does not match the live exact-HEAD result.",
            )
        project_green = (
            project_result.get("green") is True
            and attested_green
            and isinstance(live_digest, str)
            and isinstance(attested_digest, str)
            and live_digest.lower() == attested_digest.lower()
        )
        project_digest = live_digest if project_green else None
    elif "project_landing_checks_green" in readiness or "project_landing_checks_digest" in readiness:
        report.error(
            "project_landing_attestation_stale",
            "Readiness carries project landing evidence but the tracked profile is missing.",
        )
        project_green = False

    updated, attestation = attest_readiness(
        control,
        head=current_head,
        acceptance_complete=not report.errors and readiness.get("acceptance_complete") is True,
        blockers_resolved=readiness.get("blockers_resolved") is True,
        exact_tip_review_clean=readiness.get("exact_tip_review_clean") is True,
        required_checks_green=readiness.get("required_checks_green") is True,
        worktree_clean=readiness.get("worktree_clean") is True,
        inputs_digest=inputs_digest,
        project_landing_checks_green=project_green,
        project_landing_checks_digest=project_digest,
    )
    if not attestation.ready:
        report.error(
            "readiness_incomplete",
            "Host readiness attestation is incomplete: "
            + ", ".join(attestation.reasons),
        )
    report.landing = terminal_action(updated, current_head=current_head)


def _grant_session_driver_authorization(session_path: Path, source: str) -> dict[str, Any]:
    """Persist a host grant without changing or discarding readiness evidence."""

    session = load_json(session_path)
    landing = session.get("landing")
    if landing is None:
        landing = {}
    if not isinstance(landing, dict):
        raise SystemExit("Session field `landing` must be an object")
    try:
        granted = grant_driver_authorization(
            initial_control(
                landing_outcome=str(landing.get("outcome") or "landable_pr"),
                driver_authorized=landing.get("driver_authorized") is True,
            ),
            grant_source=source,
            active_run=True,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    # Deliberately mutate only host authority. In particular, preserve the
    # readiness object byte-for-byte at the data-model level.
    landing["outcome"] = granted.landing_outcome
    landing["driver_authorized"] = granted.driver_authorized
    landing["authorized_by"] = source
    landing["worker_merge_authority"] = False
    session["landing"] = landing
    replacement = session_path.with_name(f".{session_path.name}.tmp-{os.getpid()}")
    replacement.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    os.replace(replacement, session_path)
    return landing


def run_checks(args: argparse.Namespace) -> Report:
    report = Report()
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else None
    if repo_root is not None:
        if _git(repo_root, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
            report.error(
                "repo_root_invalid",
                f"Strict landing root is not a Git worktree: {repo_root}",
            )
            return report
        session_path = _strict_repo_file(
            args.session,
            base=repo_root,
            repo_root=repo_root,
            label="session",
            report=report,
        )
        if session_path is None:
            return report
    else:
        session_path = Path(args.session).expanduser().resolve()
    session = load_json(session_path)
    base = session_path.parent

    if repo_root is not None:
        _check_session_git_identity(session, repo_root, report)

    check_session_batches(session, report)
    check_session_master_acceptance(session, report)

    recorded_plan_raw = session.get("plan_path")
    if repo_root is not None and not recorded_plan_raw:
        report.error(
            "session_plan_path_missing",
            "Final landing session must record its authoritative `plan_path`.",
        )
        plan_path = None
    elif repo_root is not None:
        recorded_plan = _strict_repo_file(
            str(recorded_plan_raw),
            base=repo_root,
            repo_root=repo_root,
            label="plan",
            report=report,
        )
        explicit_plan = None
        if args.plan is not None:
            explicit_plan = _strict_repo_file(
                args.plan,
                base=repo_root,
                repo_root=repo_root,
                label="plan",
                report=report,
            )
            if (
                recorded_plan is not None
                and explicit_plan is not None
                and recorded_plan != explicit_plan
            ):
                report.error(
                    "plan_path_mismatch",
                    f"Explicit --plan {explicit_plan} does not exactly match session "
                    f"plan_path {recorded_plan}.",
                )
        plan_path = explicit_plan if args.plan is not None else recorded_plan
    else:
        plan_raw = args.plan or recorded_plan_raw
        plan_path = resolve_path(str(plan_raw) if plan_raw else None, base)
    if plan_path is not None:
        check_plan(plan_path, session, report)
    else:
        report.error(
            "no_plan_path",
            "No plan path provided and session has no plan_path; landing requires the "
            "authoritative plan Acceptance walk.",
        )

    log_raw = args.execution_log or session.get("execution_log_path")
    log_path = resolve_path(str(log_raw) if log_raw else None, base)
    if log_path is not None:
        complete_batch_ids = {
            numeric
            for batch in as_batches(session)
            if str(batch.get("status", "")).strip().lower() == "complete"
            if (numeric := numeric_batch_id(batch)) is not None
        }
        check_execution_log(
            log_path,
            report,
            expected_batch_ids=complete_batch_ids,
        )

    if args.evidence_root:
        evidence_root = resolve_path(args.evidence_root, base)
        if evidence_root is not None:
            check_evidence_dirs(
                evidence_root,
                session,
                report,
                required=args.require_evidence_dirs,
            )

    if repo_root is not None:
        _check_project_landing_profile(
            session,
            repo_root,
            report,
            base_ref=args.project_base,
        )
        _check_host_landing_control(session, repo_root, report)

    # One-line policy reminder when anything failed
    if report.errors:
        report.warn(
            "policy",
            "Green CI + status:complete is not landable; landable is plan Acceptance with proof.",
        )

    return report


def print_human(report: Report, session_path: Path) -> None:
    errors = report.errors
    warnings = report.warnings
    if not errors and not warnings:
        print("Elves landing check OK")
        print(f"- Session: {session_path}")
        print("- Every complete batch has acceptance evidence with met:true")
        print("- Policy: plan Acceptance with proof (not green CI alone)")
        return

    status = "FAILED" if errors else "WARNINGS"
    print(f"Elves landing check {status}")
    print(f"- Session: {session_path}")
    for finding in report.findings:
        print(f"- {finding.severity} [{finding.code}]: {finding.message}")


def print_json(report: Report, session_path: Path) -> None:
    payload = {
        "session": str(session_path),
        "ok": not report.errors,
        "errors": [
            {"code": f.code, "message": f.message} for f in report.errors
        ],
        "warnings": [
            {"code": f.code, "message": f.message} for f in report.warnings
        ],
        "policy": (
            "Green CI + status:complete is not landable; "
            "landable is plan Acceptance with proof."
        ),
        "landing": report.landing,
        "project_landing": report.project_landing,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    session_path = Path(args.session).expanduser().resolve()
    try:
        if args.grant_driver_authorization is not None:
            landing = _grant_session_driver_authorization(
                session_path, args.grant_driver_authorization
            )
            if args.json:
                print(
                    json.dumps(
                        {
                            "session": str(session_path),
                            "ok": True,
                            "landing": landing,
                            "readiness_restarted": False,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print("Elves landing authority updated")
                print(f"- Session: {session_path}")
                print("- Driver authorized: true")
                print("- Landing outcome: complete_and_merge")
                print("- Existing readiness preserved: yes")
            return 0
        report = run_checks(args)
    except SystemExit as exc:
        # load_json / validation usage exits
        message = str(exc) if exc.args else "usage error"
        if message.isdigit():
            return int(message)
        print(f"Elves landing check ERROR\n- {message}", file=sys.stderr)
        return 2

    if args.json:
        print_json(report, session_path)
    else:
        print_human(report, session_path)

    if args.advisory:
        return 0
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
