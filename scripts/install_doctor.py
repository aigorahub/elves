#!/usr/bin/env python3
"""Check Elves installation health.

This script serves two related jobs:
1. Tell users when a newer Elves release is available.
2. Explain which local/global installs exist so shadowing copies are easier to manage.

Typical usage:
  python3 scripts/install_doctor.py --startup
  python3 scripts/install_doctor.py --doctor
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO = "aigorahub/elves"
ACTIVE_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "elves" / "install-doctor.json"
HTTP_TIMEOUT_SECONDS = 5
DEFAULT_CACHE_HOURS = 24
VERSION_RE = re.compile(r'^\s*version:\s*"([^"]+)"\s*$', re.MULTILINE)


GLOBAL_INSTALLS = {
    "claude": Path.home() / ".claude" / "skills" / "elves",
    "codex": Path.home() / ".codex" / "skills" / "elves",
}

LOCAL_INSTALL_SUFFIXES = {
    "claude": Path(".claude") / "skills" / "elves",
    "codex": Path(".codex") / "skills" / "elves",
}

LEGACY_INSTALLS = {
    "codex": {
        "global": Path.home() / ".agents" / "skills" / "elves",
        "local_suffix": Path(".agents") / "skills" / "elves",
    }
}


@dataclass(frozen=True)
class Install:
    platform: str
    scope: str
    path: Path
    version: str | None
    active: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check for Elves updates and install conflicts.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--startup",
        action="store_true",
        help="Print only actionable notices for startup/preflight use.",
    )
    mode.add_argument(
        "--doctor",
        action="store_true",
        help="Print a full installation report.",
    )
    parser.add_argument(
        "--cache-hours",
        type=int,
        default=DEFAULT_CACHE_HOURS,
        help="How long to reuse cached release info before checking GitHub again.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as JSON (for tooling).",
    )
    return parser.parse_args()


def read_version(root: Path) -> str | None:
    skill_path = root / "SKILL.md"
    if not skill_path.exists():
        return None
    match = VERSION_RE.search(skill_path.read_text())
    return match.group(1) if match else None


def normalize_version(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.strip().lstrip("v")


def parse_version(version: str | None) -> tuple[int, ...] | None:
    normalized = normalize_version(version)
    if normalized is None:
        return None
    parts = normalized.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def version_is_newer(candidate: str | None, current: str | None) -> bool:
    candidate_key = parse_version(candidate)
    current_key = parse_version(current)
    if candidate_key is not None and current_key is not None:
        return candidate_key > current_key
    if candidate and current:
        return normalize_version(candidate) > normalize_version(current)
    return False


def load_cache(max_age_hours: int) -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    checked_at = payload.get("checked_at")
    if not isinstance(checked_at, str):
        return None

    try:
        checked = datetime.fromisoformat(checked_at)
    except ValueError:
        return None

    if datetime.now(timezone.utc) - checked > timedelta(hours=max_age_hours):
        return None
    return payload


def save_cache(payload: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))


def fetch_json_with_gh(endpoint: str) -> dict[str, Any] | list[Any] | None:
    if not shutil_which("gh"):
        return None
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def fetch_json_with_http(url: str) -> dict[str, Any] | list[Any] | None:
    request = urllib.request.Request(url, headers={"User-Agent": "elves-install-doctor"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
    ):
        return None


def fetch_latest_release(max_age_hours: int) -> dict[str, Any]:
    cached = load_cache(max_age_hours)
    if cached is not None:
        return cached

    release_payload = fetch_json_with_gh(f"repos/{REPO}/releases/latest")
    source = "gh-release"
    if release_payload is None:
        release_payload = fetch_json_with_http(f"https://api.github.com/repos/{REPO}/releases/latest")
        source = "http-release"

    latest_version = None
    latest_url = None

    if isinstance(release_payload, dict):
        latest_version = normalize_version(str(release_payload.get("tag_name") or ""))
        latest_url = release_payload.get("html_url")

    if latest_version is None:
        tags_payload = fetch_json_with_gh(f"repos/{REPO}/tags?per_page=1")
        source = "gh-tag"
        if tags_payload is None:
            tags_payload = fetch_json_with_http(f"https://api.github.com/repos/{REPO}/tags?per_page=1")
            source = "http-tag"
        if isinstance(tags_payload, list) and tags_payload:
            first = tags_payload[0]
            if isinstance(first, dict):
                latest_version = normalize_version(str(first.get("name") or ""))
                latest_url = f"https://github.com/{REPO}/releases/tag/{first.get('name') or ''}"

    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "latest_version": latest_version,
        "latest_url": latest_url,
        "source": source if latest_version else "unavailable",
    }
    save_cache(payload)
    return payload


def shutil_which(name: str) -> str | None:
    paths = os.environ.get("PATH", "").split(os.pathsep)
    for base in paths:
        candidate = Path(base) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def nearest_local_install(start: Path, suffix: Path) -> Path | None:
    probe = start.resolve()
    for ancestor in (probe, *probe.parents):
        candidate = ancestor / suffix
        if candidate.exists():
            return candidate
    return None


def discover_installs(cwd: Path) -> tuple[list[Install], Install]:
    installs: list[Install] = []
    active_install = Install(
        platform=infer_platform(ACTIVE_ROOT) or "unknown",
        scope=infer_scope(ACTIVE_ROOT),
        path=ACTIVE_ROOT,
        version=read_version(ACTIVE_ROOT),
        active=True,
    )
    installs.append(active_install)

    seen = {ACTIVE_ROOT.resolve()}

    for platform, path in GLOBAL_INSTALLS.items():
        if path.exists() and path.resolve() not in seen:
            installs.append(
                Install(
                    platform=platform,
                    scope="global",
                    path=path,
                    version=read_version(path),
                )
            )
            seen.add(path.resolve())

    for platform, suffix in LOCAL_INSTALL_SUFFIXES.items():
        local_install = nearest_local_install(cwd, suffix)
        if local_install is not None and local_install.resolve() not in seen:
            installs.append(
                Install(
                    platform=platform,
                    scope="project-local",
                    path=local_install,
                    version=read_version(local_install),
                )
            )
            seen.add(local_install.resolve())

    for platform, legacy in LEGACY_INSTALLS.items():
        global_legacy = legacy["global"]
        if global_legacy.exists() and global_legacy.resolve() not in seen:
            installs.append(
                Install(
                    platform=platform,
                    scope="legacy-global",
                    path=global_legacy,
                    version=read_version(global_legacy),
                )
            )
            seen.add(global_legacy.resolve())

        local_legacy = nearest_local_install(cwd, legacy["local_suffix"])
        if local_legacy is not None and local_legacy.resolve() not in seen:
            installs.append(
                Install(
                    platform=platform,
                    scope="legacy-project-local",
                    path=local_legacy,
                    version=read_version(local_legacy),
                )
            )
            seen.add(local_legacy.resolve())

    installs.sort(key=lambda install: (install.platform, install.scope, str(install.path)))
    return installs, active_install


def infer_platform(path: Path) -> str | None:
    path_str = str(path)
    if "/.claude/skills/elves" in path_str:
        return "claude"
    if "/.codex/skills/elves" in path_str or "/.agents/skills/elves" in path_str:
        return "codex"
    return None


def infer_scope(path: Path) -> str:
    resolved = path.resolve()
    path_str = str(resolved)
    for global_path in GLOBAL_INSTALLS.values():
        if global_path.exists() and resolved == global_path.resolve():
            return "global"
    if "/.claude/skills/elves" in path_str or "/.codex/skills/elves" in path_str or "/.agents/skills/elves" in path_str:
        return "project-local"
    return "repo-checkout"


def describe_install(install: Install) -> str:
    version = install.version or "unknown"
    active = " [active]" if install.active else ""
    return f"{install.platform} {install.scope}{active}: {install.path} (v{version})"


def build_recommendations(
    installs: list[Install],
    active_install: Install,
    latest_release: dict[str, Any],
) -> list[str]:
    notes: list[str] = []
    active_version = active_install.version
    latest_version = latest_release.get("latest_version")
    latest_url = latest_release.get("latest_url")

    if version_is_newer(latest_version, active_version):
        update_note = f"Update available: v{active_version or 'unknown'} -> v{latest_version}"
        if latest_url:
            update_note += f" ({latest_url})"
        notes.append(update_note)

    installs_by_key = {(install.platform, install.scope): install for install in installs}

    for platform in ("claude", "codex"):
        local_install = installs_by_key.get((platform, "project-local"))
        global_install = installs_by_key.get((platform, "global"))
        if local_install and global_install and local_install.version != global_install.version:
            notes.append(
                f"{platform.capitalize()} project-local install v{local_install.version or 'unknown'} "
                f"at {local_install.path} differs from global v{global_install.version or 'unknown'} "
                f"at {global_install.path}. Project-local copies usually take precedence."
            )

        legacy_global = installs_by_key.get((platform, "legacy-global"))
        legacy_local = installs_by_key.get((platform, "legacy-project-local"))
        for legacy_install in (legacy_global, legacy_local):
            if legacy_install:
                notes.append(
                    f"Legacy {platform} install detected at {legacy_install.path}. "
                    "Retire it if you have moved to the current `.codex/skills` layout."
                )

    if active_install.scope == "repo-checkout" and any(
        install.scope in {"global", "project-local"}
        and install.version != active_install.version
        for install in installs
        if not install.active
    ):
        notes.append(
            "Repo checkout is active right now. If you want your installed copies to match this "
            "checkout, run `python3 scripts/sync_installed_skills.py --apply` from the repo."
        )

    return dedupe(notes)


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def render_doctor(installs: list[Install], latest_release: dict[str, Any], notes: list[str]) -> str:
    lines = ["Elves installation report"]
    lines.append("")
    lines.append("Installs:")
    for install in installs:
        lines.append(f"- {describe_install(install)}")

    lines.append("")
    latest_version = latest_release.get("latest_version")
    latest_url = latest_release.get("latest_url")
    if latest_version:
        release_line = f"Latest published release: v{latest_version}"
        if latest_url:
            release_line += f" ({latest_url})"
        lines.append(release_line)
    else:
        lines.append("Latest published release: unavailable")

    if notes:
        lines.append("")
        lines.append("Recommendations:")
        for note in notes:
            lines.append(f"- {note}")
    else:
        lines.append("")
        lines.append("Recommendations:")
        lines.append("- No action needed.")
    return "\n".join(lines)


def render_startup(notes: list[str]) -> str:
    return "\n".join(f"- {note}" for note in notes)


def main() -> int:
    args = parse_args()
    mode_startup = args.startup and not args.doctor
    cwd = Path.cwd()

    installs, active_install = discover_installs(cwd)
    latest_release = fetch_latest_release(args.cache_hours)
    notes = build_recommendations(installs, active_install, latest_release)

    report = {
        "active_root": str(active_install.path),
        "active_version": active_install.version,
        "latest_release": latest_release,
        "installs": [
            {
                "platform": install.platform,
                "scope": install.scope,
                "path": str(install.path),
                "version": install.version,
                "active": install.active,
            }
            for install in installs
        ],
        "recommendations": notes,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    if mode_startup:
        if notes:
            print(render_startup(notes))
        return 0

    print(render_doctor(installs, latest_release, notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
