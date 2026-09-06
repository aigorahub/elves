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
import platform as host_platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cobbler_runtime.schema import ValidationIssue


REPO = "aigorahub/elves"
ACTIVE_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "elves" / "install-doctor.json"
HTTP_TIMEOUT_SECONDS = 5
DEFAULT_CACHE_HOURS = 24
STALE_RELEASE_REVALIDATION_HOURS = 1
VERSION_RE = re.compile(r'^\s*version:\s*"([^"]+)"\s*$', re.MULTILINE)
MANAGED_WSL_DISTRIBUTIONS = frozenset({"docker-desktop", "docker-desktop-data"})


GLOBAL_INSTALLS = {
    "claude": Path.home() / ".claude" / "skills" / "elves",
    "codex": Path.home() / ".codex" / "skills" / "elves",
    "grok": Path.home() / ".grok" / "skills" / "elves",
    "omp": Path.home() / ".omp" / "agent" / "skills" / "elves",
}

LOCAL_INSTALL_SUFFIXES = {
    "claude": Path(".claude") / "skills" / "elves",
    "codex": Path(".codex") / "skills" / "elves",
    "grok": Path(".grok") / "skills" / "elves",
    "omp": Path(".omp") / "agent" / "skills" / "elves",
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
    match = VERSION_RE.search(skill_path.read_text(encoding="utf-8"))
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
    return False


def load_cache(max_age_hours: int, minimum_version: str | None = None) -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    checked_at = payload.get("checked_at")
    if not isinstance(checked_at, str):
        return None

    try:
        checked = datetime.fromisoformat(checked_at)
    except ValueError:
        return None

    cache_age = datetime.now(timezone.utc) - checked
    if cache_age > timedelta(hours=max_age_hours):
        return None

    cached_version = normalize_version(str(payload.get("latest_version") or ""))
    if minimum_version and (
        cached_version is None or version_is_newer(minimum_version, cached_version)
    ):
        if cache_age > timedelta(hours=STALE_RELEASE_REVALIDATION_HOURS):
            return None
    return payload


def save_cache(payload: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def fetch_json_with_gh(endpoint: str) -> dict[str, Any] | list[Any] | None:
    if not shutil.which("gh"):
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


def fetch_latest_release(max_age_hours: int, minimum_version: str | None = None) -> dict[str, Any]:
    cached = load_cache(max_age_hours, minimum_version)
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


def _normalized_path_parts(path: Path) -> tuple[str, ...]:
    return tuple(
        part.casefold()
        for part in re.split(r"[\\/]+", str(path))
        if part not in {"", "."}
    )


def _path_has_suffix(path: Path, suffix: tuple[str, ...]) -> bool:
    parts = _normalized_path_parts(path)
    return len(parts) >= len(suffix) and parts[-len(suffix) :] == suffix


def infer_platform(path: Path) -> str | None:
    if _path_has_suffix(path, (".claude", "skills", "elves")):
        return "claude"
    if _path_has_suffix(path, (".codex", "skills", "elves")) or _path_has_suffix(
        path, (".agents", "skills", "elves")
    ):
        return "codex"
    if _path_has_suffix(path, (".grok", "skills", "elves")):
        return "grok"
    if _path_has_suffix(path, (".omp", "agent", "skills", "elves")):
        return "omp"
    return None


def infer_scope(path: Path) -> str:
    resolved = path.resolve()
    normalized = _normalized_path_parts(path)
    for global_path in GLOBAL_INSTALLS.values():
        if normalized == _normalized_path_parts(global_path):
            return "global"
        if global_path.exists() and resolved == global_path.resolve():
            return "global"
    if infer_platform(path) is not None:
        return "project-local"
    return "repo-checkout"


def _decode_wsl_output(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if b"\x00" in raw:
        try:
            return raw.decode("utf-16-le")
        except UnicodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _parse_wsl_distribution_names(output: str) -> list[str]:
    names: list[str] = []
    for raw_line in output.splitlines():
        name = raw_line.lstrip("\ufeff").strip()
        if name and name not in names:
            names.append(name)
    return names


def _parse_wsl_distributions(
    output: str,
    names: list[str],
) -> list[dict[str, Any]]:
    distributions: list[dict[str, Any]] = []
    unmatched = list(names)
    for raw_line in output.splitlines():
        line = raw_line.lstrip("\ufeff").strip()
        is_default = line.startswith("*")
        if is_default:
            line = line[1:].lstrip()
        for name in sorted(unmatched, key=len, reverse=True):
            if not line.casefold().startswith(name.casefold()):
                continue
            remainder = line[len(name) :]
            if remainder and not remainder[0].isspace():
                continue
            match = re.match(r"^\s+(?P<state>.+?)\s+(?P<version>[12])\s*$", remainder)
            if match is None:
                continue
            distributions.append(
                {
                    "name": name,
                    "state": match.group("state").strip().casefold(),
                    "version": int(match.group("version")),
                    "default": is_default,
                    "managed": name.casefold() in MANAGED_WSL_DISTRIBUTIONS,
                }
            )
            unmatched.remove(name)
            break
    distributions.extend(
        {
            "name": name,
            "state": None,
            "version": None,
            "default": False,
            "managed": name.casefold() in MANAGED_WSL_DISTRIBUTIONS,
        }
        for name in unmatched
    )
    return distributions


def _powershell_argument(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9._-]+", value):
        return value
    return "'" + value.replace("'", "''") + "'"


def _preferred_wsl_distribution(
    distributions: list[dict[str, Any]],
    *,
    version: int,
) -> dict[str, Any] | None:
    candidates = [
        item
        for item in distributions
        if not item["managed"] and item["version"] == version
    ]
    return next((item for item in candidates if item["default"]), None) or (
        candidates[0] if candidates else None
    )


def _run_wsl_query(
    wsl_runner: Any,
    *,
    mode: str,
    label: str,
) -> tuple[Any | None, str | None]:
    try:
        result = wsl_runner(
            ["wsl.exe", "--list", mode],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return None, f"The WSL {label} query timed out."
    except OSError:
        return None, f"The WSL {label} query could not start."
    except subprocess.SubprocessError:
        return None, f"The WSL {label} query failed."
    if getattr(result, "returncode", 1) != 0:
        return (
            result,
            "The WSL "
            f"{label} query exited with status {getattr(result, 'returncode', 'unknown')}.",
        )
    return result, None


def _shortcut_capability(
    *,
    ready: bool,
    backend: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "ready": ready,
        "backend": backend,
        "providers": ["fugu", "grok", "omp"],
        "reason": reason,
    }


def _external_council_capability(platform_name: str) -> dict[str, Any]:
    if platform_name.startswith("linux"):
        reason = (
            "Linux asyncio launch cannot atomically bind the bwrap child to a "
            "generation-safe process handle"
        )
    elif platform_name == "darwin":
        reason = "Darwin has no qualified recursive external-process boundary"
    elif platform_name == "win32":
        reason = "Native Windows has no qualified Elves external-process boundary"
    else:
        reason = f"{platform_name} has no qualified Elves external-process boundary"
    return {
        "ready": False,
        "reason_code": "isolation_recursive_containment_unavailable",
        "reason": reason,
    }


def build_host_support(
    *,
    platform_name: str | None = None,
    environ: dict[str, str] | None = None,
    kernel_release: str | None = None,
    wsl_runner: Any = subprocess.run,
    sandbox_resolver: Any = None,
    probe_sandbox: bool = True,
) -> dict[str, Any]:
    """Return host support and provider-boundary facts without changing the host."""
    selected_platform = platform_name or sys.platform
    selected_env = dict(os.environ if environ is None else environ)
    selected_release = kernel_release or host_platform.release()
    distro_name = selected_env.get("WSL_DISTRO_NAME") or None
    release_lower = selected_release.casefold()
    in_wsl = bool(distro_name) or "microsoft" in release_lower
    external_council = _external_council_capability(selected_platform)

    def unsupported_capabilities(reason: str) -> dict[str, Any]:
        return {
            "local_provider_shortcuts": _shortcut_capability(
                ready=False,
                reason=reason,
            ),
            "external_council": external_council,
        }

    def wsl_probe_failure(reason: str) -> dict[str, Any]:
        return {
            "status": "wsl_probe_failed",
            "supported": False,
            "summary": reason + " Native Win32 is not supported.",
            "wsl": {
                "distribution": None,
                "version": None,
                "distributions": [],
            },
            "remediation": "wsl --status; wsl --list --verbose",
            "capabilities": unsupported_capabilities(
                "Confirm a working WSL2 distribution before provider checks."
            ),
        }

    def probe_shortcut_capability(*, expected_backend: str | None = None) -> dict[str, Any]:
        if not probe_sandbox:
            return _shortcut_capability(
                ready=False,
                reason="Sandbox probe was not requested.",
            )
        try:
            resolver = sandbox_resolver
            if resolver is None:
                from cobbler_runtime.isolation import resolve_fs_sandbox_backend

                resolver = resolve_fs_sandbox_backend
            resolved_backend = resolver()
            backend_name = getattr(resolved_backend, "name", None)
        except (OSError, RuntimeError, ValidationIssue):
            return _shortcut_capability(
                ready=False,
                reason="The filesystem-sandbox probe failed.",
            )
        ready = backend_name is not None and (
            expected_backend is None or backend_name == expected_backend
        )
        return _shortcut_capability(
            ready=ready,
            backend=backend_name,
            reason=(
                None
                if ready
                else f"Qualified {expected_backend or 'filesystem sandbox'} is unavailable."
            ),
        )

    if selected_platform == "win32":
        quiet_result, probe_error = _run_wsl_query(
            wsl_runner,
            mode="--quiet",
            label="distribution",
        )
        if probe_error is not None:
            return wsl_probe_failure(probe_error)
        assert quiet_result is not None

        names = _parse_wsl_distribution_names(
            _decode_wsl_output(getattr(quiet_result, "stdout", b""))
        )
        if not names:
            return {
                "status": "needs_wsl_distribution",
                "supported": False,
                "summary": "Native Win32 is not supported. Install an Ubuntu WSL2 distribution.",
                "wsl": {
                    "distribution": None,
                    "version": None,
                    "distributions": [],
                },
                "remediation": "wsl --install -d Ubuntu",
                "capabilities": unsupported_capabilities(
                    "Install and enter a WSL2 distribution before provider checks."
                ),
            }

        verbose_result, probe_error = _run_wsl_query(
            wsl_runner,
            mode="--verbose",
            label="version",
        )
        if probe_error is not None:
            return wsl_probe_failure(probe_error)
        assert verbose_result is not None

        distributions = _parse_wsl_distributions(
            _decode_wsl_output(getattr(verbose_result, "stdout", b"")),
            names,
        )
        wsl2 = _preferred_wsl_distribution(distributions, version=2)
        wsl1 = _preferred_wsl_distribution(distributions, version=1)
        if wsl2 is not None:
            distro = str(wsl2["name"])
            return {
                "status": "use_wsl2",
                "supported": False,
                "summary": f"Native Win32 is not supported. Run Elves inside WSL2 distribution {distro}.",
                "wsl": {
                    "distribution": distro,
                    "version": 2,
                    "distributions": distributions,
                },
                "remediation": f"wsl -d {_powershell_argument(distro)}",
                "capabilities": unsupported_capabilities(
                    "Enter the WSL2 distribution before provider checks."
                ),
            }
        if wsl1 is not None:
            distro = str(wsl1["name"])
            return {
                "status": "needs_wsl2_conversion",
                "supported": False,
                "summary": f"WSL1 distribution {distro} is not a supported Elves host.",
                "wsl": {
                    "distribution": distro,
                    "version": 1,
                    "distributions": distributions,
                },
                "remediation": f"wsl --set-version {_powershell_argument(distro)} 2",
                "capabilities": unsupported_capabilities(
                    "Convert the distribution to WSL2 before provider checks."
                ),
            }
        usable_distributions = [item for item in distributions if not item["managed"]]
        if usable_distributions:
            return {
                "status": "wsl_generation_unknown",
                "supported": False,
                "summary": "The installed WSL distribution version could not be confirmed.",
                "wsl": {
                    "distribution": None,
                    "version": None,
                    "distributions": distributions,
                },
                "remediation": "Run `wsl --list --verbose` and confirm VERSION 2.",
                "capabilities": unsupported_capabilities(
                    "Only a confirmed WSL2 distribution is supported."
                ),
            }
        return {
            "status": "needs_wsl_distribution",
            "supported": False,
            "summary": (
                "Native Win32 is not supported. Install an Ubuntu WSL2 distribution. "
                "Managed Docker Desktop distributions are not Elves hosts."
            ),
            "wsl": {
                "distribution": None,
                "version": None,
                "distributions": distributions,
            },
            "remediation": "wsl --install -d Ubuntu",
            "capabilities": unsupported_capabilities(
                "Install and enter a WSL2 distribution before provider checks."
            ),
        }

    if selected_platform.startswith("linux") and in_wsl:
        if "wsl2" in release_lower or "microsoft-standard" in release_lower:
            wsl_version = 2
        elif "microsoft" in release_lower:
            wsl_version = 1
        else:
            wsl_version = None
        if wsl_version != 2:
            status = (
                "needs_wsl2_conversion"
                if wsl_version == 1 and distro_name
                else "wsl_generation_unknown"
            )
            remediation = (
                f"wsl --set-version {_powershell_argument(distro_name)} 2"
                if wsl_version == 1 and distro_name
                else "Run `wsl --list --verbose` in Windows and confirm VERSION 2."
            )
            return {
                "status": status,
                "supported": False,
                "summary": "This WSL environment is not confirmed as WSL2.",
                "wsl": {"distribution": distro_name, "version": wsl_version},
                "remediation": remediation,
                "capabilities": unsupported_capabilities(
                    "Only a confirmed WSL2 environment is supported."
                ),
            }

        return {
            "status": "supported",
            "supported": True,
            "summary": "Elves is running inside confirmed WSL2.",
            "wsl": {"distribution": distro_name, "version": 2},
            "remediation": None,
            "capabilities": {
                "local_provider_shortcuts": probe_shortcut_capability(
                    expected_backend="bwrap"
                ),
                "external_council": external_council,
            },
        }

    return {
        "status": "supported",
        "supported": True,
        "summary": f"Elves is running on supported host platform {selected_platform}.",
        "wsl": None,
        "remediation": None,
        "capabilities": {
            "local_provider_shortcuts": probe_shortcut_capability(),
            "external_council": external_council,
        },
    }


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

    for platform in ("claude", "codex", "grok", "omp"):
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
            "checkout, run `python3 scripts/sync_installed_skills.py --apply` from the repo. "
            "For Claude Code, this also syncs the managed /cobbler and Council-compatible alias "
            "skills."
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


def render_doctor(
    installs: list[Install],
    latest_release: dict[str, Any],
    notes: list[str],
    host_support: dict[str, Any] | None = None,
) -> str:
    lines = ["Elves installation report"]
    if host_support is not None:
        lines.append("")
        lines.append("Host support:")
        lines.append(f"- Status: {host_support['status']}")
        lines.append(f"- {host_support['summary']}")
        remediation = host_support.get("remediation")
        if remediation:
            lines.append(f"- Next command: {remediation}")
        capabilities = host_support.get("capabilities") or {}
        shortcuts = capabilities.get("local_provider_shortcuts") or {}
        council = capabilities.get("external_council") or {}
        shortcut_state = "ready" if shortcuts.get("ready") else "unavailable"
        backend = shortcuts.get("backend")
        if backend:
            shortcut_state += f" ({backend})"
        lines.append(f"- Fugu, Grok, and OMP local sandbox: {shortcut_state}")
        if shortcuts.get("reason"):
            lines.append(f"  Reason: {shortcuts['reason']}")
        council_state = "ready" if council.get("ready") else "unavailable"
        lines.append(f"- External council process boundary: {council_state}")
        if council.get("reason"):
            lines.append(f"  Reason: {council['reason']}")

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
    latest_release = fetch_latest_release(args.cache_hours, active_install.version)
    notes = build_recommendations(installs, active_install, latest_release)
    host_support = build_host_support(probe_sandbox=not mode_startup)
    if not host_support["supported"] and host_support.get("remediation"):
        notes = dedupe(
            [
                *notes,
                host_support["summary"],
                f"Run `{host_support['remediation']}`.",
            ]
        )

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
        "host_support": host_support,
        "recommendations": notes,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    if mode_startup:
        if notes:
            print(render_startup(notes))
        return 0

    print(render_doctor(installs, latest_release, notes, host_support))
    return 0


if __name__ == "__main__":
    sys.exit(main())
