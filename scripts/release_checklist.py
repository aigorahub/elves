#!/usr/bin/env python3
"""Run a lightweight release readiness checklist for the Elves repo."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_RE = re.compile(r'^\s*version:\s*"([^"]+)"\s*$', re.MULTILINE)
CHANGELOG_RELEASE_RE = re.compile(
    r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - (\d{4}-\d{2}-\d{2})\s*$",
    re.MULTILINE,
)
CHANGELOG_HEADING_RE = re.compile(r"^## \[[^\]]+\]", re.MULTILINE)
SEMVER_RE = re.compile(r"\b[0-9]+\.[0-9]+\.[0-9]+\b")

VERSION_FILES = {
    "SKILL.md": Path("SKILL.md"),
    "AGENTS.md": Path("AGENTS.md"),
}

CURRENT_VERSION_EXAMPLE_FILES = [
    Path("tests/test_sync_installed_skills.py"),
]

CURRENT_VERSION_SOURCE_MARKERS = [
    'read_version(REPO_ROOT / "SKILL.md")',
]

HUMAN_FACING_EXACT_PATHS = {
    "SKILL.md",
    "AGENTS.md",
    "README.md",
    "CHANGELOG.md",
    "PRODUCT.md",
    "TODO.md",
    "api-break-approvals.json",
    "config.json.example",
    "docs/cobbler.md",
    "docs/elves/learnings.md",
    "docs/elves-report-proof-of-concept.html",
}

HUMAN_FACING_PREFIXES = (
    ".ai-docs/",
    ".github/ISSUE_TEMPLATE/",
    "aliases/claude/",
    "docs/plans/",
    "guide/",
    "references/",
)

EXPECTED_CLAUDE_ALIASES = frozenset(
    {
        "cobbler",
        "cobbler-mode",
        "council",
        "ec",
        "elves-council",
        "fugu",
        "manus",
        "grok",
        "devin",
        "setup-cobbler",
        "setup-council",
    }
)

REQUIRED_RUNTIME_HELPERS = (
    Path("scripts/acceptance_contract.py"),
    Path("scripts/openrouter_lens.py"),
    Path("scripts/workspace_guard.py"),
    Path("scripts/worktree_gc.py"),
    Path("scripts/provider_supervisor.py"),
)


@dataclass
class NameStatusChange:
    status: str
    path: str


@dataclass
class ChecklistResult:
    version: str
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_frontmatter_version(path: Path) -> str | None:
    try:
        content = read_text(path)
    except FileNotFoundError:
        return None
    match = VERSION_RE.search(content)
    return match.group(1) if match else None


def read_latest_changelog_release(path: Path) -> tuple[str, str] | None:
    match = CHANGELOG_RELEASE_RE.search(read_text(path))
    if match is None:
        return None
    return match.group(1), match.group(2)


def extract_unreleased_section(changelog: str) -> str | None:
    match = re.search(r"^## \[Unreleased\]\s*$", changelog, re.MULTILINE)
    if match is None:
        return None

    start = match.end()
    next_heading = CHANGELOG_HEADING_RE.search(changelog, start)
    end = next_heading.start() if next_heading else len(changelog)
    return changelog[start:end].strip()


def parse_name_status(output: str) -> list[NameStatusChange]:
    changes: list[NameStatusChange] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0]
        if (status.startswith("R") or status.startswith("C")) and len(parts) >= 3:
            changes.append(NameStatusChange(status=status, path=parts[2]))
        elif len(parts) >= 2:
            changes.append(NameStatusChange(status=status, path=parts[1]))
    return changes


def changed_files_since(repo_root: Path, base_ref: str) -> tuple[list[NameStatusChange], str | None]:
    command = ["git", "diff", "--name-status", f"{base_ref}...HEAD"]
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError:
        return [], "git command not found in PATH"
    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown git error"
        return [], f"Could not diff against `{base_ref}`: {stderr}"
    return parse_name_status(result.stdout), None


def is_human_facing_surface(path: str) -> bool:
    if path in HUMAN_FACING_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in HUMAN_FACING_PREFIXES)


def current_version_examples(repo_root: Path, expected_version: str) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    for relative_path in CURRENT_VERSION_EXAMPLE_FILES:
        path = repo_root / relative_path
        if not path.exists():
            failures.append(f"{relative_path}: current-version example file is missing")
            continue
        text = read_text(path)
        versions = sorted(set(SEMVER_RE.findall(text)))
        reads_current_source = any(marker in text for marker in CURRENT_VERSION_SOURCE_MARKERS)
        if expected_version not in versions and not reads_current_source:
            failures.append(
                f"{relative_path}: missing current version example `{expected_version}`"
            )
        stale_versions = [version for version in versions if version != expected_version]
        if stale_versions:
            warnings.append(
                f"{relative_path}: review non-current version examples {', '.join(stale_versions)}"
            )
    return failures, warnings


def build_release_checklist(
    repo_root: Path,
    expected_version: str | None = None,
    base_ref: str | None = None,
    allow_unreleased: bool = False,
) -> ChecklistResult:
    active_version = expected_version or read_frontmatter_version(repo_root / "SKILL.md") or "unknown"
    result = ChecklistResult(version=active_version)

    for label, relative_path in VERSION_FILES.items():
        version = read_frontmatter_version(repo_root / relative_path)
        if version != active_version:
            result.failures.append(
                f"{label}: version `{version or 'missing'}` does not match `{active_version}`"
            )

    changelog_path = repo_root / "CHANGELOG.md"
    latest_release = read_latest_changelog_release(changelog_path)
    if latest_release is None:
        result.failures.append("CHANGELOG.md: missing latest release heading")
    elif latest_release[0] != active_version:
        result.failures.append(
            f"CHANGELOG.md: latest release `{latest_release[0]}` does not match `{active_version}`"
        )

    changelog = read_text(changelog_path)
    unreleased = extract_unreleased_section(changelog)
    if unreleased is None:
        result.failures.append("CHANGELOG.md: missing `## [Unreleased]` heading")
    elif unreleased:
        message = (
            "CHANGELOG.md: `## [Unreleased]` still has content; promote it under the release heading"
        )
        if allow_unreleased:
            result.warnings.append(message)
        else:
            result.failures.append(message)

    example_failures, example_warnings = current_version_examples(repo_root, active_version)
    result.failures.extend(example_failures)
    result.warnings.extend(example_warnings)

    # Alias inventory + installed import smoke when the full skill tree is present.
    alias_root = repo_root / "aliases" / "claude"
    runtime_pkg = repo_root / "scripts" / "cobbler_runtime"
    runtime_helpers = [repo_root / path for path in REQUIRED_RUNTIME_HELPERS]
    full_tree = alias_root.is_dir() and runtime_pkg.is_dir()
    if full_tree:
        found = {p.name for p in alias_root.iterdir() if p.is_dir()}
        if found != EXPECTED_CLAUDE_ALIASES:
            result.failures.append(
                "aliases/claude: expected exactly twelve managed aliases "
                f"{sorted(EXPECTED_CLAUDE_ALIASES)}; found {sorted(found)}"
            )
        for name in sorted(EXPECTED_CLAUDE_ALIASES):
            skill = alias_root / name / "SKILL.md"
            if not skill.is_file():
                result.failures.append(f"aliases/claude/{name}: missing SKILL.md")
        py_modules = [p for p in runtime_pkg.rglob("*.py") if "__pycache__" not in p.parts]
        if len(py_modules) < 5:
            result.failures.append(
                f"scripts/cobbler_runtime: expected recursive modules, found {len(py_modules)}"
            )
        missing_helpers = [
            relative
            for relative, helper in zip(REQUIRED_RUNTIME_HELPERS, runtime_helpers)
            if not helper.is_file()
        ]
        for relative in missing_helpers:
            result.failures.append(f"{relative}: missing required runtime helper")
        if not missing_helpers:
            import py_compile

            try:
                compile_inputs = [*runtime_helpers, *py_modules]
                # Keep this maintainer check read-only with respect to the
                # checkout.  py_compile's default cfile lives in a source-tree
                # __pycache__, so send every artifact to disposable storage.
                with tempfile.TemporaryDirectory(
                    prefix="elves-release-compile-"
                ) as compile_dir:
                    for index, path in enumerate(compile_inputs):
                        py_compile.compile(
                            str(path),
                            cfile=str(Path(compile_dir) / f"{index}.pyc"),
                            doraise=True,
                        )
                result.notes.append(
                    "Alias inventory (11) + required runtime helpers "
                    "(acceptance_contract.py, openrouter_lens.py, workspace_guard.py, "
                    "worktree_gc.py, provider_supervisor.py) "
                    "+ recursive compile smoke: OK"
                )
            except py_compile.PyCompileError as exc:
                result.failures.append(f"installed-import compile smoke failed: {exc}")
    elif alias_root.is_dir() or runtime_pkg.is_dir() or any(
        helper.is_file() for helper in runtime_helpers
    ):
        result.warnings.append(
            "Partial skill tree detected; skipped full alias/import inventory enforcement"
        )

    # README version line alignment (when the repo has a README).
    readme_path = repo_root / "README.md"
    if readme_path.is_file():
        readme = read_text(readme_path)
        if f"v{active_version}" not in readme and f"{active_version}" not in readme:
            result.failures.append(
                f"README.md: missing current version marker `{active_version}`"
            )

    if base_ref:
        changes, warning = changed_files_since(repo_root, base_ref)
        if warning:
            result.warnings.append(warning)
        else:
            human_changes = [change for change in changes if is_human_facing_surface(change.path)]
            if human_changes:
                rendered = ", ".join(
                    f"{change.status} {change.path}" for change in human_changes
                )
                result.notes.append(
                    f"Human-facing surfaces changed since `{base_ref}`: {rendered}"
                )
            added_human_surfaces = [
                change.path
                for change in human_changes
                if change.status.startswith("A") or change.status.startswith("R")
            ]
            if added_human_surfaces:
                result.warnings.append(
                    "Review newly added human-facing surfaces for README, changelog, and "
                    f"repo-consistency coverage: {', '.join(added_human_surfaces)}"
                )

    return result


def render_result(result: ChecklistResult) -> str:
    lines = [f"Release checklist for v{result.version}"]

    if result.failures:
        lines.append("")
        lines.append("FAILURES")
        lines.extend(f"- {failure}" for failure in result.failures)

    if result.warnings:
        lines.append("")
        lines.append("WARNINGS")
        lines.extend(f"- {warning}" for warning in result.warnings)

    if result.notes:
        lines.append("")
        lines.append("NOTES")
        lines.extend(f"- {note}" for note in result.notes)

    if result.ok and result.warnings:
        lines.append("")
        lines.append("Release checklist completed with warnings")
    elif result.ok:
        lines.append("")
        lines.append("Release checklist OK")

    return "\n".join(lines)


def result_to_json_dict(result: ChecklistResult) -> dict[str, object]:
    """Serialize checklist outcome to a stable machine-readable payload."""
    return {
        "version": result.version,
        "ok": result.ok,
        "failures": list(result.failures),
        "warnings": list(result.warnings),
        "notes": list(result.notes),
    }


def render_result_json(result: ChecklistResult) -> str:
    """Render exactly one deterministic JSON object for automation consumers."""
    return json.dumps(result_to_json_dict(result), indent=2, sort_keys=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        help="Expected release version. Defaults to the version in SKILL.md.",
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help=(
            "Base ref for committed changed human-facing surface notes. "
            "Use an empty string to skip."
        ),
    )
    parser.add_argument(
        "--allow-unreleased",
        action="store_true",
        help="Warn instead of failing when CHANGELOG.md has Unreleased content.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single machine-readable JSON object on stdout instead of the text report.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = build_release_checklist(
        REPO_ROOT,
        expected_version=args.version,
        base_ref=args.base or None,
        allow_unreleased=args.allow_unreleased,
    )
    if args.json:
        print(render_result_json(result))
    else:
        print(render_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
