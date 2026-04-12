#!/usr/bin/env python3
"""Check high-value consistency rules for the Elves repo.

This is intentionally narrow and opinionated: it only checks the specific cross-file drift that
already caused review churn in `v1.7.0`.
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
