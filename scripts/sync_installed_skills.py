#!/usr/bin/env python3
"""Mirror the canonical Elves skill bundle into local Claude/Codex/Grok installs.

Usage:
  python3 scripts/sync_installed_skills.py --check
  python3 scripts/sync_installed_skills.py --apply
  python3 scripts/sync_installed_skills.py --apply --target codex
  python3 scripts/sync_installed_skills.py --apply --target grok

`--check` reports drift between this repo checkout and the local installed copies.
`--apply` overwrites the managed files/directories in the installed copies so they match
this checkout exactly. Claude Code Cobbler, setup, compatibility, and provider shortcut alias
skills are marker-gated: unmarked user-owned alias skill directories are reported as conflicts and
are never overwritten.
When `--target all` is used, the script only operates on **already-installed** Elves skill roots
it finds (update-only). First-time install of a host must use an explicit target
(`claude`, `codex`, or `grok`).

Runtime shipment rule (v2.1.0+): ship the entire ``scripts/cobbler_runtime/`` package
recursively plus required top-level helpers (including ``openrouter_lens.py``). Adding a
new module under the package requires no manual copy-list edit.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Top-level helpers that other shipped entrypoints exec or load by relative path
# (outside the recursive cobbler_runtime package). Tests assert these basenames
# still appear at the preflight/full_run call sites and stay on the ship list.
TOP_LEVEL_RUNTIME_CALLSITE_DEPS = [
    "scripts/worktree_gc.py",  # preflight.sh --gc-worktrees
    "scripts/provider_supervisor.py",  # full_run.py provider child supervisor
]

# Top-level helpers that must ship with installed skill bundles.
TOP_LEVEL_RUNTIME_SCRIPT_PATHS = [
    "scripts/preflight.sh",
    "scripts/preflight_worktree.py",
    "scripts/notify.sh",
    "scripts/install_doctor.py",
    "scripts/validate_survival_guide.py",
    "scripts/acceptance_contract.py",
    "scripts/elves_landing_check.py",
    "scripts/landing_profile.py",
    "scripts/cobbler_agents.py",
    "scripts/openrouter_lens.py",
    "scripts/workspace_guard.py",
    *TOP_LEVEL_RUNTIME_CALLSITE_DEPS,
    "scripts/run_fugu.sh",
    "scripts/run_manus.sh",
    "scripts/run_grok.sh",
    "scripts/run_devin.sh",
    "scripts/run_omp.sh",
]

# Source-checkout archives that must never appear in an installed skill bundle.
# Enforced by: (1) managed_paths allowlist never listing them, (2) validate_managed
# refuse if a path is added later, (3) check/apply reject if they exist under install,
# (4) installed_bundle_smoke FORBIDDEN_INSTALLED_ARCHIVE_PATHS.
SOURCE_ONLY_ARCHIVE_PATHS = (
    "docs/plans",
    "docs/elves",
)


def managed_paths_include_source_only_archive(managed_paths: list[str]) -> list[str]:
    """Return managed allowlist entries that would install source-only archives."""
    bad: list[str] = []
    for path in managed_paths:
        if path == "docs" or path.startswith("docs/"):
            bad.append(path)
            continue
        for archive in SOURCE_ONLY_ARCHIVE_PATHS:
            if path == archive or path.startswith(f"{archive}/"):
                bad.append(path)
    return sorted(set(bad))

# Entire package is shipped recursively — no per-module allowlist.
RUNTIME_PACKAGE_PATH = "scripts/cobbler_runtime"

REPO_ONLY_SCRIPT_PATHS = [
    "scripts/check_repo_consistency.py",
    "scripts/release_checklist.py",
    "scripts/pr_portfolio_report.py",
    "scripts/sync_installed_skills.py",
    "scripts/verify_repo.py",
    "scripts/installed_bundle_smoke.py",
]

CLAUDE_ALIAS_MARKER = "<!-- elves-managed-alias: claude-skill-alias v1 -->"
CLAUDE_ALIAS_NAMES = [
    "cobbler",
    "cobbler-mode",
    "council",
    "ec",
    "elves-council",
    "fugu",
    "manus",
    "grok",
    "devin",
    "omp",
    "setup-cobbler",
    "setup-council",
]

IGNORED_NAMES = {"__pycache__", ".DS_Store"}
IGNORED_SUFFIXES = {".pyc"}


def should_ignore(path: Path) -> bool:
    return any(part in IGNORED_NAMES for part in path.parts) or path.suffix in IGNORED_SUFFIXES


def list_runtime_package_files(repo_root: Path | None = None) -> list[str]:
    """Return sorted relative paths of all shippable files under cobbler_runtime/."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    package = root / RUNTIME_PACKAGE_PATH
    if not package.is_dir():
        return []
    files: list[str] = []
    for path in sorted(package.rglob("*")):
        if not path.is_file():
            continue
        rel_inside = path.relative_to(package)
        if should_ignore(rel_inside):
            continue
        files.append(path.relative_to(root).as_posix())
    return files


def runtime_managed_paths(repo_root: Path | None = None) -> list[str]:
    """Managed runtime surfaces: top-level helpers + recursive package directory."""
    return [*TOP_LEVEL_RUNTIME_SCRIPT_PATHS, RUNTIME_PACKAGE_PATH]


# Backward-compatible name used by tests and callers that expect a flat list of
# managed script-ish paths. The package path is included as a directory entry;
# individual package files are discoverable via list_runtime_package_files().
RUNTIME_SCRIPT_PATHS = runtime_managed_paths()


def _bundle_managed_paths(repo_root: Path | None = None) -> list[str]:
    """Shared managed paths for every first-class host skill root."""
    managed = runtime_managed_paths(repo_root)
    return [
        "SKILL.md",
        "AGENTS.md",
        "config.json.example",
        "references",
        *managed,
    ]


def build_targets(repo_root: Path | None = None) -> dict[str, dict]:
    """Return TARGETS keyed for Claude Code, Codex, and Grok Build installs."""
    managed = _bundle_managed_paths(repo_root)
    return {
        "claude": {
            "root": Path.home() / ".claude" / "skills" / "elves",
            "managed_paths": list(managed),
            "cleanup_paths": REPO_ONLY_SCRIPT_PATHS,
            "alias_root": Path.home() / ".claude" / "skills",
            "managed_aliases": CLAUDE_ALIAS_NAMES,
        },
        "codex": {
            "root": Path.home() / ".codex" / "skills" / "elves",
            "managed_paths": list(managed),
            "cleanup_paths": REPO_ONLY_SCRIPT_PATHS,
        },
        "grok": {
            # Grok Build native skill root (first-class host install).
            "root": Path.home() / ".grok" / "skills" / "elves",
            "managed_paths": list(managed),
            "cleanup_paths": REPO_ONLY_SCRIPT_PATHS,
        },
    }


TARGETS = build_targets()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check or sync installed Claude/Codex/Grok Elves skill copies against this repo "
            "checkout."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="Report whether installed skill copies match this checkout.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Overwrite managed installed-skill files so they match this checkout.",
    )
    parser.add_argument(
        "--target",
        choices=("all", "claude", "codex", "grok"),
        default="all",
        help=(
            "Which installed skill copy to inspect or sync. "
            "`all` updates only hosts that already have an Elves skill root; "
            "first-time install requires an explicit host target."
        ),
    )
    return parser.parse_args()


def selected_targets(target_name: str) -> list[str]:
    if target_name == "all":
        # Update-only: do not create missing host roots under `all`.
        return [name for name, config in TARGETS.items() if config["root"].exists()]
    return [target_name]


def read_version(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(errors="ignore")
    # AGENTS.md uses top-level frontmatter version; SKILL.md nests under metadata.
    match = re.search(r'^\s*version:\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if match:
        return match.group(1)
    match = re.search(r'^\s*version:\s*"([^"]+)"\s*$', text, re.MULTILINE)
    return match.group(1) if match else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def compare_file(src: Path, dst: Path, rel_path: str) -> list[str]:
    if not src.exists():
        return [f"missing source file: {rel_path}"]
    if dst.is_symlink():
        return [f"unsafe symlink: {rel_path}"]
    if not dst.exists():
        return [f"missing file: {rel_path}"]
    if sha256(src) != sha256(dst):
        return [f"content differs: {rel_path}"]
    return []


def compare_dir(src_dir: Path, dst_dir: Path, rel_path: str) -> list[str]:
    problems: list[str] = []
    if not src_dir.exists():
        return [f"missing source directory: {rel_path}/"]
    if dst_dir.is_symlink():
        return [f"unsafe symlink: {rel_path}/"]
    if not dst_dir.exists():
        return [f"missing directory: {rel_path}/"]

    symlinks = sorted(
        path.relative_to(dst_dir).as_posix()
        for path in dst_dir.rglob("*")
        if path.is_symlink()
    )
    if symlinks:
        return [f"unsafe symlink: {rel_path}/{relative}" for relative in symlinks]

    src_files = {
        path.relative_to(src_dir).as_posix()
        for path in src_dir.rglob("*")
        if path.is_file() and not should_ignore(path.relative_to(src_dir))
    }
    dst_files = {
        path.relative_to(dst_dir).as_posix()
        for path in dst_dir.rglob("*")
        if path.is_file() and not should_ignore(path.relative_to(dst_dir))
    }

    for relative in sorted(src_files - dst_files):
        problems.append(f"missing file: {rel_path}/{relative}")
    for relative in sorted(dst_files - src_files):
        problems.append(f"extra file: {rel_path}/{relative}")
    for relative in sorted(src_files & dst_files):
        src_path = src_dir / relative
        dst_path = dst_dir / relative
        if sha256(src_path) != sha256(dst_path):
            problems.append(f"content differs: {rel_path}/{relative}")
    return problems


def alias_source_dir(alias_name: str) -> Path:
    return REPO_ROOT / "aliases" / "claude" / alias_name


def alias_display_path(alias_name: str) -> str:
    return f"aliases/claude/{alias_name}/"


def is_elves_managed_alias(alias_dir: Path) -> bool:
    skill_path = alias_dir / "SKILL.md"
    if not skill_path.exists():
        return False
    return CLAUDE_ALIAS_MARKER in skill_path.read_text(errors="ignore")


def compare_alias(alias_name: str, dst_dir: Path) -> list[str]:
    src_dir = alias_source_dir(alias_name)
    display_path = alias_display_path(alias_name)

    if not src_dir.exists():
        return [f"missing source alias: {display_path}"]
    if not dst_dir.exists():
        return [f"missing alias skill: {dst_dir}"]
    if not is_elves_managed_alias(dst_dir):
        return [f"alias conflict: {dst_dir} exists without Elves managed alias marker"]
    return compare_dir(src_dir, dst_dir, display_path.rstrip("/"))


def check_target(name: str) -> tuple[bool, list[str]]:
    root = TARGETS[name]["root"]
    problems: list[str] = []

    unsafe = _unsafe_destination_component(root, root / ".elves-safety-check")
    if unsafe is not None:
        return False, [f"unsafe symlinked install path: {unsafe}"]

    if not root.exists():
        problems.append(f"missing install root: {root}")
        return False, problems

    for relative in managed_paths_include_source_only_archive(
        list(TARGETS[name]["managed_paths"])
    ):
        problems.append(
            f"source-only archive must not be managed install path: {relative}"
        )

    for relative in TARGETS[name]["managed_paths"]:
        src = REPO_ROOT / relative
        dst = root / relative
        if src.is_dir():
            problems.extend(compare_dir(src, dst, relative))
        else:
            problems.extend(compare_file(src, dst, relative))

    for relative in TARGETS[name]["cleanup_paths"]:
        if (root / relative).exists():
            problems.append(f"unexpected repo-only helper: {relative}")

    for relative in SOURCE_ONLY_ARCHIVE_PATHS:
        if (root / relative).exists():
            problems.append(f"source-only archive leaked into install: {relative}")

    alias_root = TARGETS[name].get("alias_root")
    for alias_name in TARGETS[name].get("managed_aliases", []):
        problems.extend(compare_alias(alias_name, alias_root / alias_name))

    # Codex must never receive the Claude alias tree under the skill install.
    if name == "codex":
        for alias_name in CLAUDE_ALIAS_NAMES:
            alias_under_skill = root / "aliases" / "claude" / alias_name
            if alias_under_skill.exists():
                problems.append(f"unexpected Claude alias under Codex install: {alias_under_skill}")

    return not problems, problems


def _unsafe_destination_component(root: Path, dst: Path) -> Path | None:
    root = root.absolute()
    dst = dst.absolute()
    try:
        relative = dst.relative_to(root)
    except ValueError:
        return dst
    # The install root and its user-controlled ancestors must be real
    # directories.  Do not reject platform-level aliases such as macOS /var ->
    # /private/var, which sit well above a skill install root.
    for component in (root, *root.parents[:4]):
        if component.is_symlink():
            return component
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            return cursor
    return None


def sync_path(src: Path, dst: Path, *, safe_root: Path | None = None) -> None:
    if safe_root is not None:
        unsafe = _unsafe_destination_component(safe_root, dst)
        if unsafe is not None:
            raise ValueError(f"unsafe symlinked install path: {unsafe}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink():
        dst.unlink()
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(
            src,
            dst,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
    else:
        shutil.copy2(src, dst)


def remove_path(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
        return
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def preflight_apply_target(name: str) -> list[str]:
    """Validate every destination before the first install mutation.

    Managed copies already defend each destination at write time.  Cleanup paths
    need the same ancestor guarantee: an install-internal directory symlink must
    never redirect deletion outside the managed root.  Preflighting the complete
    target also avoids partially updating the main bundle before discovering an
    unsafe alias or cleanup destination.
    """
    config = TARGETS[name]
    root = config["root"]
    problems: list[str] = []

    destinations = [
        *(root / relative for relative in config["managed_paths"]),
        *(root / relative for relative in config["cleanup_paths"]),
    ]
    for destination in destinations:
        unsafe = _unsafe_destination_component(root, destination)
        if unsafe is not None:
            problems.append(f"unsafe symlinked install path: {unsafe}")

    alias_root = config.get("alias_root")
    for alias_name in config.get("managed_aliases", []):
        dst_dir = alias_root / alias_name
        unsafe = _unsafe_destination_component(alias_root, dst_dir)
        if unsafe is not None:
            problems.append(f"unsafe symlinked alias path: {unsafe}")
            continue
        if dst_dir.is_symlink():
            problems.append(f"unsafe symlinked alias path: {dst_dir}")
        elif dst_dir.exists() and not is_elves_managed_alias(dst_dir):
            problems.append(f"alias conflict: {dst_dir} exists without Elves managed alias marker")

    # A shared unsafe ancestor may affect several managed paths.  Report it once
    # while preserving deterministic discovery order for operators and tests.
    return list(dict.fromkeys(problems))


def apply_target(name: str) -> list[str]:
    root = TARGETS[name]["root"]
    problems = preflight_apply_target(name)
    if problems:
        return problems
    for relative in managed_paths_include_source_only_archive(
        list(TARGETS[name]["managed_paths"])
    ):
        problems.append(
            f"source-only archive must not be managed install path: {relative}"
        )
    if problems:
        return problems
    root.mkdir(parents=True, exist_ok=True)
    for relative in TARGETS[name]["managed_paths"]:
        try:
            sync_path(REPO_ROOT / relative, root / relative, safe_root=root)
        except ValueError as exc:
            problems.append(str(exc))
    for relative in TARGETS[name]["cleanup_paths"]:
        remove_path(root / relative)
    for relative in SOURCE_ONLY_ARCHIVE_PATHS:
        remove_path(root / relative)

    alias_root = TARGETS[name].get("alias_root")
    for alias_name in TARGETS[name].get("managed_aliases", []):
        src_dir = alias_source_dir(alias_name)
        dst_dir = alias_root / alias_name
        if dst_dir.is_symlink():
            problems.append(f"unsafe symlinked alias path: {dst_dir}")
            continue
        if dst_dir.exists() and not is_elves_managed_alias(dst_dir):
            problems.append(f"alias conflict: {dst_dir} exists without Elves managed alias marker")
            continue
        try:
            sync_path(src_dir, dst_dir, safe_root=alias_root)
        except ValueError as exc:
            problems.append(str(exc))
    return problems


def _require_python_floor() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit(
            "sync_installed_skills requires Python >= 3.10 (repo floor); "
            f"found {sys.version_info.major}.{sys.version_info.minor}"
        )


def main() -> int:
    _require_python_floor()
    args = parse_args()
    # Do not rebuild TARGETS here: tests (and operators) may monkeypatch REPO_ROOT
    # and TARGETS roots. Managed paths are already directory-recursive for the package.

    repo_version = read_version(REPO_ROOT / "SKILL.md") or "unknown"
    targets = selected_targets(args.target)
    had_drift = False

    if not targets:
        print("No installed Elves skill copies were detected.")
        print(
            "Use `--target claude`, `--target codex`, or `--target grok` with `--apply` "
            "to create one explicitly (`all` only updates existing installs)."
        )
        if args.check and args.target == "all":
            return 0
        return 1

    for name in targets:
        root = TARGETS[name]["root"]
        installed_version = read_version(root / "SKILL.md") or "missing"

        if args.check:
            ok, problems = check_target(name)
            status = "OK" if ok else "STALE"
            print(f"[{name}] {status} repo={repo_version} installed={installed_version}")
            for problem in problems:
                print(f"  - {problem}")
            had_drift = had_drift or not ok
            continue

        print(f"[{name}] syncing repo={repo_version} -> {root}")
        apply_problems = apply_target(name)
        ok, problems = check_target(name)
        problems = apply_problems + [problem for problem in problems if problem not in apply_problems]
        ok = ok and not apply_problems
        if ok:
            synced_version = read_version(root / "SKILL.md") or "unknown"
            print(f"  - synced successfully (installed={synced_version})")
        else:
            had_drift = True
            print("  - sync incomplete:")
            for problem in problems:
                print(f"    - {problem}")

    if args.check and had_drift:
        return 1
    if args.apply and had_drift:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
