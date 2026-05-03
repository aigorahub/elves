#!/usr/bin/env python3
"""Check high-value consistency rules for the Elves repo.

This is intentionally narrow and opinionated: it only checks the specific cross-file drift that
already caused review churn in `v1.7.0` and `v1.8.0`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_FILES = {
    "SKILL.md": REPO_ROOT / "SKILL.md",
    "AGENTS.md": REPO_ROOT / "AGENTS.md",
}

CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

RECOVERY_ORDER_FILES = {
    "SKILL.md": REPO_ROOT / "SKILL.md",
    "AGENTS.md": REPO_ROOT / "AGENTS.md",
    "README.md": REPO_ROOT / "README.md",
    "references/kickoff-prompt-template.md": REPO_ROOT / "references" / "kickoff-prompt-template.md",
    "references/survival-guide-template.md": REPO_ROOT / "references" / "survival-guide-template.md",
}

RECOVERY_ORDER_TOKENS = [
    "survival guide",
    ".elves-session.json",
    "learnings",
    "plan",
    "execution log",
    ".ai-docs/manifest.md",
]

PENDING_DOCS_FILES = {
    "SKILL.md": REPO_ROOT / "SKILL.md",
    "AGENTS.md": REPO_ROOT / "AGENTS.md",
    "references/review-subagent.md": REPO_ROOT / "references" / "review-subagent.md",
}

DURABLE_DOCS = [
    REPO_ROOT / "docs" / "elves" / "learnings.md",
    REPO_ROOT / ".ai-docs" / "manifest.md",
    REPO_ROOT / ".ai-docs" / "architecture.md",
    REPO_ROOT / ".ai-docs" / "conventions.md",
    REPO_ROOT / ".ai-docs" / "gotchas.md",
    REPO_ROOT / "references" / "learnings-template.md",
]

NONSTOP_GUARDRAIL_PHRASES = {
    "SKILL.md": [
        "Stop Gate",
        "continuation_guard",
        "After every commit and push, re-read the survival guide before doing anything else.",
        "Do not wait for user acknowledgment",
    ],
    "AGENTS.md": [
        "Stop Gate",
        "continuation_guard",
        "After every commit and push, re-read the survival guide before doing anything else.",
        "Do not wait for user acknowledgment",
    ],
    "references/survival-guide-template.md": [
        "## Stop Gate",
        "## Forbidden Stop Reasons",
        "Stop allowed right now",
        "Every completed batch must end with a commit and push",
        "continue without waiting for user acknowledgment",
    ],
    "references/kickoff-prompt-template.md": [
        "Every completed batch must end with a commit and push before you start anything else.",
        "Immediately after every commit and push, re-read the survival guide before any other action.",
        "Do not send a final response unless the survival guide Stop Gate says stopping is allowed or a true blocker forces it.",
    ],
    "references/open-ended-guide.md": [
        "## Stop Gate Pattern",
        "## Forbidden Stop Reasons",
        "continuation_guard.stop_allowed: false",
    ],
}

EFFORT_GUARDRAIL_PHRASES = {
    "SKILL.md": [
        "## Effort Standard",
        "Do not be lazy.",
        "Work as hard as you can for",
    ],
    "AGENTS.md": [
        "## Effort Standard",
        "Do not be lazy.",
        "Work as hard as you can for",
    ],
    "references/survival-guide-template.md": [
        "## Effort Standard",
        "Do not be lazy.",
        "Work as hard as you can for the full run.",
    ],
    "references/kickoff-prompt-template.md": [
        "Do not be lazy. Work as hard as you can for the entire run.",
        "Do not coast after the first success, first green check, or first useful checkpoint.",
    ],
    "references/open-ended-guide.md": [
        "## Sustain Effort",
        "Do not be lazy.",
        "Work as hard as you can for the full",
    ],
}

FINAL_READINESS_REVIEW_PHRASES = {
    "SKILL.md": [
        "Final Readiness Review",
        "git diff <default-branch>...HEAD",
        "review subagent",
    ],
    "AGENTS.md": [
        "Final Readiness Review",
        "git diff <default-branch>...HEAD",
        "review subagent",
    ],
    "README.md": [
        "Final readiness review",
        "git diff <default-branch>...HEAD",
    ],
    "references/review-subagent.md": [
        "## Final Readiness Review",
        "git diff [DEFAULT_BRANCH]...HEAD",
    ],
    "references/kickoff-prompt-template.md": [
        "Require a final readiness review",
        "git diff <default-branch>...HEAD",
    ],
}

MEMORY_HYGIENE_PHRASES = {
    "SKILL.md": [
        "## Strategic Forgetting",
        "chats are for execution",
        "memory and resource hygiene",
    ],
    "AGENTS.md": [
        "## Strategic Forgetting",
        "Chats are for execution",
        "memory and resource hygiene",
    ],
    "README.md": [
        "strategic forgetting",
        "handoff docs are for memory",
    ],
    "references/survival-guide-template.md": [
        "## Strategic Forgetting",
        "## Memory and Resource Hygiene",
    ],
    "references/autonomy-guide.md": [
        "## Memory Pressure And Strategic Forgetting",
        "Local app maintenance",
    ],
}


def read_text(path: Path) -> str:
    return path.read_text()


def read_frontmatter_version(path: Path) -> str | None:
    match = re.search(r'^\s*version:\s*"([^"]+)"\s*$', read_text(path), re.MULTILINE)
    return match.group(1) if match else None


def read_latest_changelog_version(path: Path) -> str | None:
    match = re.search(r"^## \[([^\]]+)\] - ", read_text(path), re.MULTILINE)
    return match.group(1) if match else None


def verify_order(label: str, text: str, tokens: list[str], errors: list[str]) -> None:
    lower = text.lower()
    cursor = 0
    for token in tokens:
        index = lower.find(token.lower(), cursor)
        if index == -1:
            errors.append(f"{label}: missing recovery-order token `{token}`")
            return
        cursor = index + len(token)


def main() -> int:
    errors: list[str] = []

    versions = {label: read_frontmatter_version(path) for label, path in VERSION_FILES.items()}
    changelog_version = read_latest_changelog_version(CHANGELOG_PATH)

    for label, version in versions.items():
        if version is None:
            errors.append(f"{label}: missing frontmatter version")

    if changelog_version is None:
        errors.append("CHANGELOG.md: missing release heading")

    if not errors:
        expected = next(iter(versions.values()))
        for label, version in versions.items():
            if version != expected:
                errors.append(
                    f"{label}: version `{version}` does not match repo skill version `{expected}`"
                )
        if changelog_version != expected:
            errors.append(
                f"CHANGELOG.md: latest release `{changelog_version}` does not match repo skill version `{expected}`"
            )

    for label, path in RECOVERY_ORDER_FILES.items():
        verify_order(label, read_text(path), RECOVERY_ORDER_TOKENS, errors)

    for label, path in PENDING_DOCS_FILES.items():
        if "PENDING-DOCS" not in read_text(path):
            errors.append(f"{label}: missing `PENDING-DOCS` guidance")

    for path in DURABLE_DOCS:
        if not path.exists():
            errors.append(f"missing durable doc: {path.relative_to(REPO_ROOT)}")

    for label, phrases in NONSTOP_GUARDRAIL_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing non-stop guardrail phrase `{phrase}`")

    for label, phrases in EFFORT_GUARDRAIL_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing effort guardrail phrase `{phrase}`")

    for label, phrases in FINAL_READINESS_REVIEW_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing final-readiness-review phrase `{phrase}`")

    for label, phrases in MEMORY_HYGIENE_PHRASES.items():
        path = REPO_ROOT / label
        text = read_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{label}: missing memory-hygiene phrase `{phrase}`")

    if errors:
        print("Repo consistency check FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Repo consistency check OK")
    print(f"- Version: {next(iter(versions.values()))}")
    print("- Recovery order is aligned across repo docs")
    print("- `PENDING-DOCS` guidance is present where expected")
    print("- Durable docs and learnings surfaces exist")
    print("- Non-stop guardrails are aligned across runtime and template docs")
    print("- Effort guardrails are aligned across runtime and template docs")
    print("- Final readiness review guardrails are aligned")
    print("- Strategic forgetting and memory hygiene guardrails are aligned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
