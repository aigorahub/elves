"""Version-safe Grok Build launch surface for the read-only shortcut runner.

The installed Grok Build CLI changes its flags between releases. Grok Build
1.0.13 removed the top-level ``--no-auto-update`` and ``--check`` flags that
``run_grok.sh`` used to pass unconditionally, which killed the route outright.

This module reads the installed CLI's own advertised surface once, before the
launch, and builds argv from it:

* **Required** flags carry the safety posture (isolated working directory, inner
  strict sandbox profile, headless single-turn output). If the installed CLI does
  not advertise one of them, the launch fails closed rather than running with a
  weaker posture.
* **Optional** flags are quality features, not controls. They are passed only when
  the installed CLI still advertises them, so old versions keep them and new
  versions stop crashing on them.
* Auto-update suppression moved from a removed flag to the isolated
  ``[cli] auto_update = false`` config key, which every supported version reads.
  The outer kernel sandbox remains the authority: it never grants write access to
  the CLI's own install tree.

Nothing here relaxes the outer isolation snapshot, the credential grant, or the
fail-closed rules; it only decides which advertised flags exist.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from .schema import ValidationIssue


GROK_PROBE_TIMEOUT_SECONDS = 15.0
# Help and catalog output is small; anything larger is a broken or hostile CLI.
GROK_PROBE_MAX_OUTPUT_BYTES = 512 * 1024

# Reasoning efforts the shortcut will pass. The CLI does not enumerate them in
# help, so this is a pinned allowlist rather than a probe result.
SUPPORTED_GROK_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh")
DEFAULT_GROK_EFFORT = "high"

# Without these the launch would lose its isolated cwd, the inner strict sandbox
# profile, or headless single-turn behavior. Missing one fails closed.
REQUIRED_GROK_FLAGS: tuple[str, ...] = ("--cwd", "--sandbox", "--output-format", "--single")
# Exactly one of these must exist; `--effort` is the older spelling.
EFFORT_FLAG_CANDIDATES: tuple[str, ...] = ("--reasoning-effort", "--effort")
# Quality features that some versions no longer advertise.
OPTIONAL_GROK_FLAGS: tuple[str, ...] = ("--no-auto-update", "--check")
MODEL_FLAG_CANDIDATES: tuple[str, ...] = ("--model", "-m")

_FLAG_PATTERN = re.compile(r"(?<![\w-])(--?[A-Za-z][A-Za-z0-9-]*)")
_CATALOG_ENTRY = re.compile(r"^\s*[*-]\s+(?P<model>[A-Za-z0-9][A-Za-z0-9._-]*)")
_AUTH_LINE = re.compile(r"^\s*You are using\s+(?P<route>[^.\n]+?)\s*\.?\s*$", re.MULTILINE)


@dataclass(frozen=True)
class GrokCapabilities:
    """The installed CLI's advertised top-level flags."""

    version: str | None
    flags: frozenset[str]

    def supports(self, flag: str) -> bool:
        return flag in self.flags

    def first_supported(self, candidates: Sequence[str]) -> str | None:
        for flag in candidates:
            if flag in self.flags:
                return flag
        return None

    def to_dict(self) -> dict[str, object]:
        return {"version": self.version, "flags": sorted(self.flags)}


@dataclass(frozen=True)
class GrokCatalog:
    """Live model catalog plus the authentication route the CLI reports."""

    models: tuple[str, ...] = ()
    auth_route: str | None = None
    available: bool = True
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "models": list(self.models),
            "auth_route": self.auth_route,
            "available": bool(self.available),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GrokLaunchPlan:
    """Argv plus the record a host needs to describe the route honestly."""

    argv: tuple[str, ...]
    effort: str
    model: str | None
    auth_route: str | None
    capabilities: GrokCapabilities
    omitted_flags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "effort": self.effort,
            "model": self.model,
            "auth_route": self.auth_route,
            "omitted_flags": list(self.omitted_flags),
            "cli_version": self.capabilities.version,
        }


def _run_probe(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None,
    label: str,
) -> str:
    """Run one bounded, non-interactive probe and return its combined output."""
    try:
        proc = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=GROK_PROBE_TIMEOUT_SECONDS,
            env=dict(env) if env is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationIssue(
            "grok_cli_probe_timeout",
            f"{label} did not answer within {GROK_PROBE_TIMEOUT_SECONDS:g}s",
            hint="The installed Grok Build CLI is unresponsive; treat the route as unavailable.",
        ) from exc
    except OSError as exc:
        raise ValidationIssue(
            "grok_cli_probe_failed",
            f"{label} could not be executed: {exc}",
        ) from exc
    body = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if len(body) > GROK_PROBE_MAX_OUTPUT_BYTES:
        raise ValidationIssue(
            "grok_cli_probe_oversized",
            f"{label} produced more than {GROK_PROBE_MAX_OUTPUT_BYTES} bytes",
        )
    return body


def parse_grok_flags(help_text: str) -> frozenset[str]:
    """Collect the option spellings a help page advertises."""
    return frozenset(_FLAG_PATTERN.findall(help_text or ""))


def probe_grok_capabilities(
    executable: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    help_text: str | None = None,
    version: str | None = None,
) -> GrokCapabilities:
    """Read the installed CLI's advertised flags.

    ``help_text`` and ``version`` exist so tests can pin a released surface without
    executing anything.
    """
    text = (
        help_text
        if help_text is not None
        else _run_probe([str(executable), "--help"], env=env, label="grok --help")
    )
    resolved_version = version
    if resolved_version is None and help_text is None:
        raw = _run_probe([str(executable), "--version"], env=env, label="grok --version")
        match = re.search(r"\b(\d+\.\d+\.\d+[A-Za-z0-9.\-]*)", raw)
        resolved_version = match.group(1) if match else None
    return GrokCapabilities(version=resolved_version, flags=parse_grok_flags(text))


def require_supported_grok_cli(capabilities: GrokCapabilities) -> str:
    """Fail closed when the installed CLI cannot carry the safety posture.

    Returns the effort flag spelling to use.
    """
    missing = [flag for flag in REQUIRED_GROK_FLAGS if not capabilities.supports(flag)]
    effort_flag = capabilities.first_supported(EFFORT_FLAG_CANDIDATES)
    if effort_flag is None:
        missing.append(EFFORT_FLAG_CANDIDATES[0])
    if missing:
        raise ValidationIssue(
            "grok_cli_incompatible",
            "Installed Grok Build CLI does not advertise required launch controls: "
            + ", ".join(sorted(set(missing))),
            hint=(
                "Elves will not launch Grok without an isolated working directory, the "
                "inner strict sandbox profile, headless single-turn output, and an "
                "explicit reasoning effort. Update or reinstall the Grok Build CLI, or "
                "select another review route."
            ),
        )
    assert effort_flag is not None
    return effort_flag


def resolve_grok_effort(requested: str | None) -> str:
    """Validate an explicit reasoning effort, or return the pinned default."""
    token = (requested or "").strip().lower()
    if not token:
        return DEFAULT_GROK_EFFORT
    if token not in SUPPORTED_GROK_EFFORTS:
        raise ValidationIssue(
            "invalid_grok_effort",
            f"Unsupported Grok reasoning effort `{requested}`",
            path="ELVES_GROK_EFFORT",
            hint="Use one of: " + ", ".join(SUPPORTED_GROK_EFFORTS),
        )
    return token


def parse_grok_catalog(text: str) -> GrokCatalog:
    """Read `grok models` output into a live catalog plus its auth route."""
    auth = _AUTH_LINE.search(text or "")
    models: list[str] = []
    collecting = False
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.strip().lower().startswith("available models"):
            collecting = True
            continue
        if not collecting:
            continue
        match = _CATALOG_ENTRY.match(line)
        if match is None:
            # The bullet list ended; anything after it is not catalog content.
            if not line.startswith(" "):
                break
            continue
        models.append(match.group("model"))
    return GrokCatalog(
        models=tuple(dict.fromkeys(models)),
        auth_route=auth.group("route").strip() if auth else None,
        available=bool(models),
        reason=None if models else "live catalog listed no models",
    )


def probe_grok_catalog(
    executable: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    text: str | None = None,
) -> GrokCatalog:
    """Read the authenticated live catalog. Never invents a model id."""
    if text is None:
        try:
            text = _run_probe([str(executable), "models"], env=env, label="grok models")
        except ValidationIssue as exc:
            return GrokCatalog(available=False, reason=exc.code)
    return parse_grok_catalog(text)


def resolve_grok_model(requested: str | None, catalog: GrokCatalog) -> str | None:
    """Admit an explicit model only when the live catalog lists it."""
    token = (requested or "").strip()
    if not token:
        return None
    if not catalog.available:
        raise ValidationIssue(
            "grok_catalog_unavailable",
            f"Cannot admit model `{token}`: the live Grok catalog could not be read",
            path="ELVES_GROK_MODEL",
            hint=(
                "Elves never invents a Grok model id. Fix Grok Build authentication, "
                "or clear ELVES_GROK_MODEL to let the authenticated configuration choose."
            ),
        )
    if token not in catalog.models:
        raise ValidationIssue(
            "grok_model_not_in_catalog",
            f"Model `{token}` is not in the authenticated live Grok catalog",
            path="ELVES_GROK_MODEL",
            hint="Live catalog: " + (", ".join(catalog.models) or "(empty)"),
        )
    return token


# macOS Seatbelt refuses a second `sandbox_init` inside an existing profile, so
# Grok's own `--sandbox` profile cannot initialize under Elves' required outer
# `sandbox-exec` boundary. Grok Build 1.0.13 refuses to start when its profile
# cannot apply; older releases only warned and ran on with the inner protection
# silently missing. Elves reports the conflict instead of either lie.
NESTED_INNER_SANDBOX_BACKENDS: Mapping[str, str] = {"darwin": "sandbox-exec"}
INNER_SANDBOX_DISABLED_PROFILES: frozenset[str] = frozenset({"", "none", "off"})


def inner_sandbox_conflict(
    *,
    platform_name: str,
    outer_backend: str | None,
    profile: str = "strict",
) -> str | None:
    """Return why the inner Grok profile cannot run under this outer backend."""
    if (profile or "").strip().lower() in INNER_SANDBOX_DISABLED_PROFILES:
        return None
    for prefix, backend in NESTED_INNER_SANDBOX_BACKENDS.items():
        if platform_name.startswith(prefix) and outer_backend == backend:
            return (
                f"{platform_name} cannot nest sandboxes: Grok's inner `{profile}` "
                f"profile cannot initialize inside Elves' required outer "
                f"`{backend}` boundary"
            )
    return None


def require_inner_sandbox(
    *,
    platform_name: str,
    outer_backend: str | None,
    profile: str = "strict",
) -> None:
    """Fail closed rather than run with the inner profile silently missing."""
    conflict = inner_sandbox_conflict(
        platform_name=platform_name,
        outer_backend=outer_backend,
        profile=profile,
    )
    if conflict is None:
        return
    raise ValidationIssue(
        "grok_inner_sandbox_unavailable",
        conflict,
        hint=(
            "Elves will not drop the inner profile to make the launch succeed, and "
            "the outer boundary is not optional. Run the Grok shortcut on a Linux "
            "host with the bwrap backend, or select another review route."
        ),
    )


def isolated_grok_config(*, model_default: str | None = None) -> str:
    """Isolated `config.toml` body for the disposable GROK_HOME.

    Auto-update is disabled here rather than through the removed
    ``--no-auto-update`` flag, so every supported version gets the same behavior.
    Only this key and an optional model default are written: the host's own config
    (permission mode, plugins, MCP servers) is never copied into the lane.
    """
    body = "[cli]\nauto_update = false\n"
    if model_default:
        body += "\n[models]\ndefault = " + json.dumps(model_default) + "\n"
    return body


def build_grok_argv(
    executable: str | Path,
    *,
    snapshot: str | Path,
    prompt: str,
    capabilities: GrokCapabilities,
    effort: str = DEFAULT_GROK_EFFORT,
    model: str | None = None,
    auth_route: str | None = None,
    sandbox_profile: str = "strict",
    output_format: str = "plain",
) -> GrokLaunchPlan:
    """Build the headless argv from the flags this CLI actually advertises."""
    effort_flag = require_supported_grok_cli(capabilities)
    resolved_effort = resolve_grok_effort(effort)
    binary = Path(str(executable))
    if not binary.is_absolute():
        raise ValidationIssue(
            "grok_executable_not_absolute",
            f"Grok Build executable must be an absolute resolved path: {executable}",
            path="build_grok_argv.executable",
        )
    argv: list[str] = [str(binary)]
    omitted: list[str] = []

    # Optional quality flags keep their original argv positions, so a version that
    # still advertises them behaves exactly as it did before this repair.
    if capabilities.supports("--no-auto-update"):
        argv.append("--no-auto-update")
    else:
        omitted.append("--no-auto-update")

    argv.extend(["--cwd", str(snapshot)])
    # The inner strict profile is not optional; require_supported_grok_cli already
    # proved the flag exists.
    argv.extend(["--sandbox", sandbox_profile])
    argv.extend([effort_flag, resolved_effort])
    argv.extend(["--output-format", output_format])

    resolved_model = (model or "").strip() or None
    if resolved_model:
        model_flag = capabilities.first_supported(MODEL_FLAG_CANDIDATES)
        if model_flag is None:
            raise ValidationIssue(
                "grok_model_flag_unsupported",
                "Installed Grok Build CLI does not advertise a model selection flag",
                path="ELVES_GROK_MODEL",
                hint="Clear ELVES_GROK_MODEL to use the authenticated default model.",
            )
        argv.extend([model_flag, resolved_model])

    if capabilities.supports("--check"):
        argv.append("--check")
    else:
        omitted.append("--check")

    argv.append("--single=" + prompt)
    return GrokLaunchPlan(
        argv=tuple(argv),
        effort=resolved_effort,
        model=resolved_model,
        auth_route=auth_route,
        capabilities=capabilities,
        omitted_flags=tuple(omitted),
    )
