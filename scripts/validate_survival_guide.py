#!/usr/bin/env python3
"""Advisory validator for generated Elves survival guides.

Usage:
  python3 scripts/validate_survival_guide.py path/to/survival-guide.md

If no path is provided, the script falls back to ELVES_SURVIVAL_GUIDE_PATH.

This is intentionally advisory: it exits non-zero when it finds issues so callers can decide
whether to warn or fail. The recommended use is to surface warnings during staging/preflight
without blocking launch automatically.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    "Run Control",
    "Stop Gate",
    "Effort Standard",
    "Forbidden Stop Reasons",
    "Current Phase",
    "Active Compute",
    "Next Exact Batch",
    "Post-Checkpoint Control Loop",
    "After Any Compaction",
]

SECTION_REQUIREMENTS = {
    "Run Control": [
        "Run mode",
        "Stop policy",
        "User intent",
        "Checkpoint due by",
        "Checkpoint semantics",
        "May continue after checkpoint",
        "Actual stop conditions",
        "Final-response policy",
        "Batch completion rule",
        "Re-read rule",
        "Checkpoint rule",
        "Continuation rule",
    ],
    "Stop Gate": [
        "Planned batches remaining",
        "Stop allowed right now",
        "Why",
        "Next required action",
    ],
    "Effort Standard": [
        "Work as hard as you can",
        "Do not be lazy",
        "minimum acceptable change",
        "next highest-value action",
    ],
    "Current Phase": [
        "Status",
        "Active batch",
        "What was just finished",
        "Single next action",
    ],
    "Next Exact Batch": [
        "Batch",
        "Scope",
        "Acceptance criteria",
        "Risk",
    ],
    "Post-Checkpoint Control Loop": [
        "Every completed batch must end with a commit and push",
        "re-read this survival guide before doing anything else",
        "Stop Gate still say `Stop allowed right now: no`",
    ],
    "After Any Compaction": [
        "Run Control section and Stop Gate",
        "continuation_guard",
    ],
}

CRITICAL_PLACEHOLDER_FIELDS = [
    "Run mode",
    "Stop policy",
    "User intent",
    "Checkpoint due by",
    "Checkpoint semantics",
    "May continue after checkpoint",
    "Actual stop conditions",
    "Final-response policy",
    "Planned batches remaining",
    "Stop allowed right now",
    "Why",
    "Next required action",
    "Status",
    "Active batch",
    "What was just finished",
    "Single next action",
    "Batch",
    "Risk",
]

PLACEHOLDER_PATTERN = re.compile(r"\[[^\]]*[A-Za-z][^\]]*\]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Advisory validation for a generated Elves survival guide."
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to the survival guide markdown file. Defaults to ELVES_SURVIVAL_GUIDE_PATH.",
    )
    return parser.parse_args()


def load_path(arg_path: str | None) -> Path:
    raw = arg_path or os.environ.get("ELVES_SURVIVAL_GUIDE_PATH")
    if not raw:
        raise SystemExit(
            "No survival guide path provided. Pass a path argument or set ELVES_SURVIVAL_GUIDE_PATH."
        )
    return Path(raw).expanduser().resolve()


def read_text(path: Path) -> str:
    return path.read_text()


def section_bounds(text: str) -> dict[str, tuple[int, int]]:
    matches = list(re.finditer(r"^## (.+)$", text, re.MULTILINE))
    bounds: dict[str, tuple[int, int]] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        bounds[match.group(1).strip()] = (start, end)
    return bounds


def section_text(text: str, bounds: dict[str, tuple[int, int]], heading: str) -> str:
    start, end = bounds[heading]
    return text[start:end].strip()


def find_line(section: str, label: str) -> str | None:
    for line in section.splitlines():
        if label in line:
            return line.strip()
    return None


def validate(path: Path) -> tuple[list[str], list[str]]:
    text = read_text(path)
    bounds = section_bounds(text)
    errors: list[str] = []
    warnings: list[str] = []

    for heading in REQUIRED_SECTIONS:
        if heading not in bounds:
            errors.append(f"missing section `## {heading}`")

    if errors:
        return errors, warnings

    for heading, phrases in SECTION_REQUIREMENTS.items():
        body = section_text(text, bounds, heading)
        for phrase in phrases:
            if phrase not in body:
                errors.append(f"`## {heading}` missing `{phrase}`")

    forbidden_reasons = section_text(text, bounds, "Forbidden Stop Reasons")
    reason_lines = [line.strip() for line in forbidden_reasons.splitlines() if line.strip().startswith("-")]
    if len(reason_lines) < 3:
        errors.append("`## Forbidden Stop Reasons` should list at least 3 concrete false stop signals")
    if not any("checkpoint" in line.lower() for line in reason_lines):
        errors.append("`## Forbidden Stop Reasons` should explicitly mention checkpoints")
    if not any("commit" in line.lower() or "push" in line.lower() for line in reason_lines):
        errors.append("`## Forbidden Stop Reasons` should explicitly mention commits or pushes")

    for heading, label_list in SECTION_REQUIREMENTS.items():
        body = section_text(text, bounds, heading)
        for label in label_list:
            if label not in CRITICAL_PLACEHOLDER_FIELDS:
                continue
            line = find_line(body, label)
            if line and PLACEHOLDER_PATTERN.search(line):
                warnings.append(f"`## {heading}` still has placeholder content on `{label}`")

    launch_readiness = section_text(text, bounds, "Launch Readiness") if "Launch Readiness" in bounds else ""
    if "Stop Gate initialized with `Stop allowed right now: no`" not in launch_readiness:
        warnings.append("`## Launch Readiness` is missing the Stop Gate initialization checkbox")

    return errors, warnings


def main() -> int:
    args = parse_args()
    path = load_path(args.path)

    if not path.exists():
        print(f"Survival guide validation FAILED\n- file not found: {path}")
        return 1
    if not path.is_file():
        print(f"Survival guide validation FAILED\n- not a file: {path}")
        return 1

    errors, warnings = validate(path)

    if not errors and not warnings:
        print("Survival guide validation OK")
        print(f"- Guide: {path}")
        print("- Required stop-control sections are present")
        print("- Stop Gate and continuation guidance are populated")
        return 0

    print("Survival guide validation found issues")
    print(f"- Guide: {path}")
    for error in errors:
        print(f"- ERROR: {error}")
    for warning in warnings:
        print(f"- WARN: {warning}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
