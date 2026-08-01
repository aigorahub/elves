"""Stdlib tool-output compact layer (RTK ideas without an RTK dependency).

Collapses high-volume, low-signal command output for host/worker prompts while
preserving failure tails and a short head for orientation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_PASS_LINE = re.compile(
    r"(?i)^(ok|passed|pass|✓|✔|\.|#\s*pass)\b|tests?\s+passed|0\s+failed"
)
_FAIL_LINE = re.compile(
    r"(?i)\b(fail(ed|ure)?|error|traceback|exception|assert|not ok)\b"
)


@dataclass(frozen=True)
class CompactResult:
    text: str
    original_lines: int
    kept_lines: int
    truncated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "original_lines": self.original_lines,
            "kept_lines": self.kept_lines,
            "truncated": self.truncated,
        }


def compact_tool_output(
    raw: str,
    *,
    max_lines: int = 80,
    head_lines: int = 12,
    tail_lines: int = 40,
    collapse_success_runs: bool = True,
) -> CompactResult:
    """Return a compact representation of tool/shell output.

    - Keeps the first ``head_lines`` and last ``tail_lines`` when over budget.
    - Optionally collapses long runs of pure success markers to a count line.
    - Always retains lines that look like failures even in the middle.
    """
    if max_lines < 8:
        max_lines = 8
    text = raw if isinstance(raw, str) else str(raw)
    lines = text.splitlines()
    original = len(lines)
    if original == 0:
        return CompactResult(text="", original_lines=0, kept_lines=0, truncated=False)

    if collapse_success_runs:
        collapsed: list[str] = []
        run = 0
        for line in lines:
            if _PASS_LINE.search(line) and not _FAIL_LINE.search(line):
                run += 1
                continue
            if run:
                collapsed.append(f"[compact] {run} success-marker line(s) omitted")
                run = 0
            collapsed.append(line)
        if run:
            collapsed.append(f"[compact] {run} success-marker line(s) omitted")
        lines = collapsed

    # Pull middle failures into the kept set when truncating.
    if len(lines) <= max_lines:
        out = "\n".join(lines)
        if text.endswith("\n") and out:
            out += "\n"
        return CompactResult(
            text=out if out or not text else text,
            original_lines=original,
            kept_lines=len(lines),
            truncated=False,
        )

    head = lines[:head_lines]
    tail = lines[-tail_lines:]
    middle = lines[head_lines : len(lines) - tail_lines]
    failure_hits = [ln for ln in middle if _FAIL_LINE.search(ln)]
    # budget remaining for failure samples
    budget = max_lines - len(head) - len(tail) - 1
    if budget < 0:
        budget = 0
    sample = failure_hits[:budget]
    marker = (
        f"[compact] omitted {len(middle) - len(sample)} middle line(s); "
        f"kept {len(sample)} failure-like hit(s)"
    )
    kept = head + [marker] + sample + tail
    out = "\n".join(kept)
    if text.endswith("\n"):
        out += "\n"
    return CompactResult(
        text=out,
        original_lines=original,
        kept_lines=len(kept),
        truncated=True,
    )
