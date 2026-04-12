#!/usr/bin/env python3
"""Mirror the canonical Elves skill bundle into local Claude/Codex installs.

Usage:
  python3 scripts/sync_installed_skills.py --check
  python3 scripts/sync_installed_skills.py --apply
  python3 scripts/sync_installed_skills.py --apply --target codex

`--check` reports drift between this repo checkout and the local installed copies.
`--apply` overwrites the managed files/directories in the installed copies so they match
this checkout exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

TARGETS = {
    "claude": {
        "root": Path.home() / ".claude" / "skills" / "elves",
        "managed_paths": ["SKILL.md", "references", "scripts"],
    },
    "codex": {
        "root": Path.home() / ".codex" / "skills" / "elves",
        "managed_paths": ["SKILL.md", "AGENTS.md", "references", "scripts"],
    },
}

IGNORED_NAMES = {"__pycache__", ".DS_Store"}
IGNORED_SUFFIXES = {".pyc"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check or sync installed Claude/Codex Elves skill copies against this repo checkout."
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
        choices=("all", "claude", "codex"),
        default="all",
        help="Which installed skill copy to inspect or sync.",
    )
    return parser.parse_args()


def selected_targets(target_name: str) -> list[str]:
    if target_name == "all":
        return ["claude", "codex"]
    return [target_name]


def read_version(path: Path) -> str | None:
    if not path.exists():
        return None
    match = re.search(r'^\s*version:\s*"([^"]+)"\s*$', path.read_text(), re.MULTILINE)
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


def should_ignore(path: Path) -> bool:
    return any(part in IGNORED_NAMES for part in path.parts) or path.suffix in IGNORED_SUFFIXES


def compare_file(src: Path, dst: Path, rel_path: str) -> list[str]:
    if not dst.exists():
        return [f"missing file: {rel_path}"]
    if sha256(src) != sha256(dst):
        return [f"content differs: {rel_path}"]
    return []


def compare_dir(src_dir: Path, dst_dir: Path, rel_path: str) -> list[str]:
    problems: list[str] = []
    if not dst_dir.exists():
        return [f"missing directory: {rel_path}/"]

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


def check_target(name: str) -> tuple[bool, list[str]]:
    root = TARGETS[name]["root"]
    problems: list[str] = []

    if not root.exists():
        problems.append(f"missing install root: {root}")
        return False, problems

    for relative in TARGETS[name]["managed_paths"]:
        src = REPO_ROOT / relative
        dst = root / relative
        if src.is_dir():
            problems.extend(compare_dir(src, dst, relative))
        else:
            problems.extend(compare_file(src, dst, relative))

    return not problems, problems


def sync_path(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
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


def apply_target(name: str) -> None:
    root = TARGETS[name]["root"]
    root.mkdir(parents=True, exist_ok=True)
    for relative in TARGETS[name]["managed_paths"]:
        sync_path(REPO_ROOT / relative, root / relative)


def main() -> int:
    args = parse_args()
    repo_version = read_version(REPO_ROOT / "SKILL.md") or "unknown"
    targets = selected_targets(args.target)
    had_drift = False

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
        apply_target(name)
        ok, problems = check_target(name)
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
