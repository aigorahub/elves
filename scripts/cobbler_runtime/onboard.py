"""Model onboarding: plan, show, apply, probe.

Host agents (Claude Code or Codex) walk the user through purpose→route choices.
This module is deterministic CLI support: inventory, preference I/O, and probes.
Never print credential values. Paid smokes are opt-in only.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import default_profiles
from .setup import (
    OPTIONAL_ENV_NAMES,
    PROFILE_RECIPES,
    SETUP_ROLE_SLOTS,
    inventory_tools,
    preferences_from_flags,
    profile_adapter_name,
    profile_is_apply_blocked,
    recommend_routes,
    resolve_recipe_executable,
    run_setup,
    which_executable,
)
from .toml_compat import loads as load_toml_text


# Purposes the user assigns tools to. Core map to setup role slots.
# Google subscription CLIs are plan/review-oriented (usually not cost-effective for bulk implement).
# Claude/Codex support planning vs labor profile tiers within the same family.
PURPOSE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "planning",
        "role_slot": "planning",
        "label": "Planning / design",
        "description": "Contracts, batch design, architecture choices (prefer high-quality model)",
        "default_route": "host-native",
        "suggested_routes": (
            "host-native",
            "claude-code-planning",
            "codex-fugu-planning",
            "claude-code",
            "codex-fugu",
            "gemini-cli",
            "antigravity-cli",
            "opencode-cli",
        ),
        "required": False,
    },
    {
        "id": "implement",
        "role_slot": "implement",
        "label": "Implementation (labor)",
        "description": (
            "Writing code for a batch — prefer host-native, labor-tier Claude/Codex, or Grok; "
            "optional experimental antigravity-labor (Gemini Flash-class) is not Lane A"
        ),
        "default_route": "host-native",
        "suggested_routes": (
            "host-native",
            "claude-code-labor",
            "codex-fugu-labor",
            "grok-build",
            "devin-cli",
            "omp-cli",
            "claude-code",
            "codex-fugu",
            "antigravity-labor",
            "opencode-labor",
        ),
        "required": False,
    },
    {
        "id": "review",
        "role_slot": "review",
        "label": "Independent review",
        "description": "Read-only critique (prefer high-quality model / optional Google lenses)",
        "default_route": "host-native",
        "suggested_routes": (
            "host-native",
            "claude-code-planning",
            "codex-fugu-planning",
            "claude-code",
            "codex-fugu",
            "gemini-cli",
            "antigravity-cli",
            "opencode-cli",
            "openrouter-lens",
            "or-qwen-max",
            "or-glm",
            "meta-muse",
        ),
        "required": False,
    },
    {
        "id": "lightweight_review",
        "role_slot": "lightweight_review",
        "label": "Quick utility review",
        "description": "Fast single-lens checks",
        "default_route": "host-native",
        "suggested_routes": (
            "host-native",
            "claude-code-labor",
            "codex-fugu-labor",
            "claude-code",
            "codex-fugu",
            "gemini-cli",
        ),
        "required": False,
    },
    {
        "id": "scout",
        "role_slot": "scout",
        "label": "Scouting / discovery",
        "description": "Breadth search, math Discovery Sprint lanes",
        "default_route": "host-native",
        "suggested_routes": (
            "host-native",
            "claude-code",
            "gemini-cli",
            "antigravity-cli",
            "openrouter-lens",
            "or-qwen-max",
            "or-glm",
            "meta-muse",
        ),
        "required": False,
    },
    {
        "id": "validate",
        "role_slot": "validate",
        "label": "Validation ownership",
        "description": "Who owns gates (prefer host-native)",
        "default_route": "host-native",
        "suggested_routes": ("host-native",),
        "required": True,
    },
    {
        "id": "synthesize",
        "role_slot": "synthesize",
        "label": "Synthesis / fitted answer",
        "description": "Who fits one answer (prefer host-native)",
        "default_route": "host-native",
        "suggested_routes": ("host-native",),
        "required": True,
    },
    {
        "id": "math_evolutionary_search",
        "role_slot": None,
        "label": "Math evolutionary search (AlphaEvolve)",
        "description": (
            "Optional numerical examples / counterexample search when GCP runner exists "
            "(Survival Guide / math config — not an onboard role flag)"
        ),
        "default_route": "off",
        "suggested_routes": ("off", "alphaevolve"),
        "required": False,
        "optional_tool": "alphaevolve",
        "apply_via": "manual",  # not a SETUP_ROLE_SLOTS flag
    },
)

# Extended env names (presence only).
ONBOARD_ENV_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *OPTIONAL_ENV_NAMES,
            "META_API_KEY",
            "MODEL_API_KEY",
            "EXA_API_KEY",
            "SAKANA_API_KEY",
        )
    )
)

ROUTE_HELP: dict[str, str] = {
    "host-native": "Current host agent (Claude Code or Codex) — default, always available",
    "claude-code": "Claude Code CLI (default model for the install)",
    "claude-code-planning": "Claude Code high-quality tier for plan/review (pin requested_model in TOML)",
    "claude-code-labor": "Claude Code labor tier for implement volume (pin requested_model in TOML)",
    "grok-build": "Grok Build CLI for optional external implement batches",
    "devin-cli": (
        "Devin CLI (Cognition) — optional implement worker pinned to SWE-1.7 Lightning; "
        "host captures exact session id; exact --resume <id> only"
    ),
    "omp-cli": (
        "Oh My Pi (omp) — optional implement worker; headless --mode json; "
        "host captures session UUID from NDJSON; exact --resume only; "
        "run-scoped --profile isolation"
    ),
    "codex-fugu": "Codex/Fugu CLI (default model for the install)",
    "codex-fugu-planning": "Codex high-quality tier for plan/review (pin requested_model in TOML)",
    "codex-fugu-labor": "Codex labor tier for implement volume (pin requested_model in TOML)",
    "gemini-cli": (
        "Google Gemini CLI (API key) — plan/review/scout; pin latest Gemini model; "
        "headless needs --skip-trust; not bulk implement"
    ),
    "antigravity-cli": (
        "Google Antigravity CLI (agy) — plan/review; pin latest Gemini "
        "(e.g. 3.1 Pro High); OAuth/GCP; not the main Elves host"
    ),
    "antigravity-labor": (
        "Experimental Antigravity labor (agy + Flash-class model) — optional volume "
        "implement; not Lane A / not write-lease qualified; pin e.g. Gemini 3.5 Flash"
    ),
    "openrouter": (
        "Bare token blocked — use openrouter-lens / or-qwen-max / or-glm "
        "(scripts/openrouter_lens.py + OPENROUTER_API_KEY)"
    ),
    "openrouter-lens": (
        "OpenRouter plan/review lens — pin requested_model to any current OR id; "
        "prefer exact session_id for plan→review; else attach plan/docs"
    ),
    "or-qwen-max": (
        "OpenRouter Qwen-class plan/review preset — pin current slug (e.g. qwen/qwen3-max)"
    ),
    "or-glm": (
        "OpenRouter GLM-class plan/review preset — pin current slug (e.g. z-ai/glm-5)"
    ),
    "opencode-cli": (
        "OpenCode terminal agent (Claude Code–like) — plan/review; OpenRouter + 75+ providers; "
        "pin provider/model; exact --session preferred"
    ),
    "opencode-labor": (
        "OpenCode implement labor — main batch coding via opencode run --auto + OR/other models; "
        "experimental; not Grok Lane A default; not write-lease qualified"
    ),
    "meta-muse": (
        "Meta Muse Spark (API key) — not a bare CLI. Configure a custom-cli wrapper profile "
        "(cobbler-setup-recipes.md); bare `onboard apply --review meta-muse` is rejected"
    ),
    "alphaevolve": (
        "Google Cloud AlphaEvolve for evolutionary example search (math Survival Guide config, "
        "not an onboard apply role — see math-alphaevolve.md)"
    ),
    "off": "Disabled for this purpose",
    "custom-cli": "User wrapper executable (qualify before write roles)",
}


def route_presence_adapter(route: str) -> str | None:
    """Map onboard route / tier label → inventory adapter key (single source: PROFILE_RECIPES)."""
    if route in ("host-native", "off"):
        return None
    if profile_is_apply_blocked(route):
        return None  # env / gcloud presence handled separately
    recipe = PROFILE_RECIPES.get(route)
    if recipe:
        adapter = recipe.get("adapter")
        return str(adapter) if adapter else None
    # Bare adapter name or custom profile name
    defaults = default_profiles()
    if route in defaults:
        return route
    return None


@dataclass
class ProbeResult:
    route: str
    purpose: str | None
    status: str  # pass | warn | fail | skip
    detail: str
    kind: str = "structural"  # structural | live_smoke

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OnboardPacket:
    """Payload the host agent uses to interview the user and apply choices."""

    generated_at: str
    host_hints: dict[str, str]
    inventory: list[dict[str, Any]] = field(default_factory=list)
    env_present: dict[str, bool] = field(default_factory=dict)
    current_roles: dict[str, str] = field(default_factory=dict)
    purposes: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelsTomlState:
    """Parsed local models.toml for onboarding (roles + profile bodies)."""

    roles: dict[str, str]
    profiles: dict[str, dict[str, Any]]
    warnings: list[str]
    path: Path
    exists: bool
    parse_ok: bool
    required_roles: list[str] = field(default_factory=list)
    session_mode: str = "ephemeral"
    sharing_policy: str = "local-only"
    document_owner: str = "host-coordinator"
    usage_budget_warning: int | None = None
    unknown_top_level: dict[str, Any] = field(default_factory=dict)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_ENV_LOCAL_ASSIGN = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$",
)


def _env_names_from_dotenv(path: Path) -> set[str]:
    """Return env *names* with non-empty values in a dotenv file. Never returns values."""
    if not path.is_file():
        return set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LOCAL_ASSIGN.match(stripped)
        if not match:
            continue
        name, raw = match.group(1), match.group(2)
        # Drop inline comments and surrounding quotes without exposing the value.
        value_part = raw.split("#", 1)[0].strip()
        if len(value_part) >= 2 and value_part[0] == value_part[-1] and value_part[0] in "\"'":
            value_part = value_part[1:-1]
        if value_part.strip():
            names.add(name)
    return names


def env_name_presence(
    names: Sequence[str] = ONBOARD_ENV_NAMES,
    *,
    environ: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> dict[str, bool]:
    """Report whether env var *names* are set. Never returns values.

    When ``repo_root`` is provided, also treats a name as present if it appears as a
    left-hand assignment in ignored ``.env.local`` (name scan only — file values are
    never returned). Process environment still wins for actual runtime; this only
    improves onboarding *availability hints* when keys live in `.env.local` but are
    not yet exported into the CLI process.
    """
    env = environ if environ is not None else os.environ
    dotenv_names: set[str] = set()
    if repo_root is not None:
        dotenv_names = _env_names_from_dotenv(Path(repo_root) / ".env.local")
    out: dict[str, bool] = {}
    for name in names:
        val = env.get(name)
        in_process = bool(val and str(val).strip())
        out[name] = in_process or (name in dotenv_names)
    return out


def load_models_toml_state(repo_root: Path) -> ModelsTomlState:
    """Load roles and [profiles.*] bodies from ignored models.toml if present."""
    path = Path(repo_root) / ".elves" / "models.toml"
    roles = {role: "host-native" for role in SETUP_ROLE_SLOTS}
    profiles: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    required_roles: list[str] = []
    if not path.is_file():
        return ModelsTomlState(
            roles=roles,
            profiles=profiles,
            warnings=warnings,
            path=path,
            exists=False,
            parse_ok=True,
            required_roles=required_roles,
        )
    try:
        data = load_toml_text(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — surface parse failure, do not crash
        warnings.append(
            f"`{path}` could not be parsed ({type(exc).__name__}: {exc}); "
            "falling back to host-native roles for display/probe"
        )
        return ModelsTomlState(
            roles=roles,
            profiles=profiles,
            warnings=warnings,
            path=path,
            exists=True,
            parse_ok=False,
            required_roles=required_roles,
        )
    if not isinstance(data, dict):
        warnings.append(f"`{path}` root is not a table; falling back to host-native")
        return ModelsTomlState(
            roles=roles,
            profiles=profiles,
            warnings=warnings,
            path=path,
            exists=True,
            parse_ok=False,
            required_roles=required_roles,
        )
    for role, body in (data.get("roles") or {}).items():
        if role in roles and isinstance(body, dict) and body.get("profile"):
            roles[role] = str(body["profile"])
            if body.get("required") is True:
                required_roles.append(role)
    for name, body in (data.get("profiles") or {}).items():
        if isinstance(body, dict):
            profiles[str(name)] = dict(body)
    return ModelsTomlState(
        roles=roles,
        profiles=profiles,
        warnings=warnings,
        path=path,
        exists=True,
        parse_ok=True,
        required_roles=required_roles,
        session_mode=str(data.get("session_mode_default") or "ephemeral"),
        sharing_policy=str(data.get("sharing_policy") or "local-only"),
        document_owner=str(data.get("document_owner") or "host-coordinator"),
        usage_budget_warning=(
            int(data["usage_budget_warning_tokens"])
            if isinstance(data.get("usage_budget_warning_tokens"), int)
            else None
        ),
        unknown_top_level={
            str(key): value
            for key, value in data.items()
            if key
            not in {
                "roles",
                "profiles",
                "session_mode_default",
                "sharing_policy",
                "document_owner",
                "usage_budget_warning_tokens",
            }
        },
    )


def load_role_profiles_from_models_toml(repo_root: Path) -> dict[str, str]:
    """Read current role→profile map from ignored models.toml if present."""
    return load_models_toml_state(repo_root).roles


def build_onboarding_packet(
    repo_root: Path,
    *,
    fake_presence: Mapping[str, bool] | None = None,
    environ: Mapping[str, str] | None = None,
) -> OnboardPacket:
    inventory = inventory_tools(fake_presence=fake_presence)
    env_present = env_name_presence(environ=environ, repo_root=repo_root)
    state = load_models_toml_state(repo_root)
    current = state.roles
    present_adapters = sorted(i.adapter for i in inventory if i.present)

    questions: list[dict[str, Any]] = []
    for purpose in PURPOSE_CATALOG:
        options = []
        for route in purpose["suggested_routes"]:
            available = True
            apply_ready = not profile_is_apply_blocked(route) and route not in ("off",)
            adapter_key = route_presence_adapter(route)
            if adapter_key:
                available = adapter_key in present_adapters
            if route == "openrouter":
                available = env_present.get("OPENROUTER_API_KEY", False)
                apply_ready = False
            if route in {"openrouter-lens", "or-qwen-max", "or-glm"}:
                available = env_present.get("OPENROUTER_API_KEY", False)
                apply_ready = available  # wrapper ships in-repo; key must be present
            if route == "meta-muse":
                available = env_present.get("META_API_KEY", False) or env_present.get(
                    "MODEL_API_KEY", False
                )
                apply_ready = False
            if route == "alphaevolve":
                available = shutil.which("gcloud") is not None
                apply_ready = False
            if route == "host-native":
                available = True
                apply_ready = True
            if route == "off":
                available = True
                apply_ready = False
            options.append(
                {
                    "route": route,
                    "help": ROUTE_HELP.get(route, route),
                    "available_hint": available,
                    "apply_ready": apply_ready,
                    "apply_blocked": profile_is_apply_blocked(route),
                }
            )
        current_route = purpose["default_route"]
        slot = purpose.get("role_slot")
        if slot and slot in current:
            current_route = current[slot]
        questions.append(
            {
                "purpose_id": purpose["id"],
                "prompt": (
                    f"For **{purpose['label']}** ({purpose['description']}), "
                    f"which route do you want? Current/default: `{current_route}`."
                ),
                "options": options,
                "current": current_route,
                "allow_custom": True,
                "apply_via": purpose.get("apply_via", "role_flag"),
            }
        )

    notes = [
        "Native-only is always valid: leave everything host-native and skip optional tools.",
        "Never paste API keys into chat, models.toml, or the Survival Guide.",
        "Commit/push/PR are host operations, not model roles.",
        "After apply, run `onboard probe` (and optional `--smoke`) to verify routes.",
        "Update anytime: re-run onboarding or `onboard apply` with new flags "
        "(partial apply merges into existing models.toml roles).",
        "Claude Code: /setup-cobbler or natural language. Codex: $elves setup-cobbler / natural language.",
        "Tier split: high-quality Claude/Codex for plan+review, labor model for implement "
        "(claude-code-planning / claude-code-labor, codex-fugu-planning / codex-fugu-labor).",
        "Google Gemini CLI / Antigravity CLI: good for plan/review; usually not for bulk implement.",
        "openrouter / meta-muse / alphaevolve are interview hints only for bare apply — "
        "configure a custom-cli wrapper (or math Survival Guide for AlphaEvolve) first.",
    ]
    if env_present.get("OPENROUTER_API_KEY"):
        notes.append(
            "OPENROUTER_API_KEY name is set: offer OpenRouter via a custom-cli wrapper recipe, "
            "not bare --review openrouter."
        )
    if env_present.get("META_API_KEY") or env_present.get("MODEL_API_KEY"):
        notes.append(
            "Meta API key name is set: offer Muse Spark via a custom-cli wrapper recipe, "
            "not bare --review meta-muse."
        )
    if shutil.which("gcloud"):
        notes.append("gcloud present: AlphaEvolve may be available if the project has a runner.")

    return OnboardPacket(
        generated_at=_utc_now(),
        host_hints={
            "claude_code": "/setup-cobbler or natural language: set up my model routes",
            "codex": "$elves setup-cobbler or natural language (not a top-level Codex slash)",
            "cli_plan": "python3 scripts/cobbler_agents.py onboard plan --json",
            "cli_apply": "python3 scripts/cobbler_agents.py onboard apply --planning … --review …",
            "cli_show": "python3 scripts/cobbler_agents.py onboard show --json",
            "cli_probe": "python3 scripts/cobbler_agents.py onboard probe --json",
            "cli_probe_smoke": "python3 scripts/cobbler_agents.py onboard probe --json --smoke",
        },
        inventory=[i.to_dict() for i in inventory],
        env_present=env_present,
        current_roles=current,
        purposes=list(PURPOSE_CATALOG),
        questions=questions,
        recommendations=recommend_routes(inventory),
        notes=notes,
        warnings=list(state.warnings),
    )


def apply_onboarding(
    repo_root: Path,
    *,
    role_flags: Mapping[str, str | None],
    required: Sequence[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    run_smoke: bool = False,
    smoke_executor: Any | None = None,
    fake_presence: Mapping[str, bool] | None = None,
    merge_existing: bool = True,
) -> dict[str, Any]:
    """Write role preferences (setup). Returns setup result dict + onboarding meta.

    Partial apply is **merge** by default: existing models.toml roles are preserved
    unless a flag overwrites them. Pass ``merge_existing=False`` to reset all
    unspecified roles to host-native.
    """
    base_roles = None
    existing_profiles: Mapping[str, Mapping[str, Any]] | None = None
    existing_top_level: Mapping[str, Any] | None = None
    session_mode = "ephemeral"
    sharing_policy = "local-only"
    document_owner = "host-coordinator"
    usage_budget_warning: int | None = None
    if required is None:
        merged_required: list[str] = []
    else:
        merged_required = list(required)
    if merge_existing:
        state = load_models_toml_state(repo_root)
        base_roles = state.roles
        existing_profiles = state.profiles
        if state.parse_ok:
            existing_top_level = state.unknown_top_level
        session_mode = state.session_mode
        sharing_policy = state.sharing_policy
        document_owner = state.document_owner
        usage_budget_warning = state.usage_budget_warning
        # Preserve existing required flags unless caller passes --required explicitly.
        if required is None:
            merged_required = list(state.required_roles)
    prefs = preferences_from_flags(
        implement=role_flags.get("implement"),
        review=role_flags.get("review"),
        planning=role_flags.get("planning"),
        lightweight_review=role_flags.get("lightweight_review"),
        validate=role_flags.get("validate"),
        synthesize=role_flags.get("synthesize"),
        scout=role_flags.get("scout"),
        required=merged_required,
        session_mode=session_mode,
        sharing_policy=sharing_policy,
        native_fallback=True,
        base_roles=base_roles,
    )
    prefs.document_owner = document_owner
    prefs.usage_budget_warning = usage_budget_warning
    result = run_setup(
        Path(repo_root),
        preferences=prefs,
        write_toml=not dry_run,
        force_toml=force,
        run_smoke=run_smoke,
        smoke_executor=smoke_executor,
        dry_run=dry_run,
        fake_presence=fake_presence,
        existing_profiles=existing_profiles,
        existing_top_level=existing_top_level,
    )
    payload = result.to_dict()
    changed = {
        k: v
        for k, v in prefs.roles.items()
        if role_flags.get(k)  # only flags the user actually passed
    }
    payload["onboarding"] = {
        "action": "apply",
        "merge_existing": merge_existing,
        "updated_roles": changed,
        "effective_roles": dict(prefs.roles),
        "next": [
            "python3 scripts/cobbler_agents.py onboard show --json",
            "python3 scripts/cobbler_agents.py onboard probe --json",
            "Optional paid smoke: onboard probe --json --smoke (host supplies smoke_executor)",
        ],
    }
    return payload


def _resolve_executable_for_probe(
    name: str,
    *,
    repo_root: Path | None = None,
) -> str | None:
    """Locate an executable for structural probe.

    Prefer an absolute path when ``name`` is absolute and exists. For relative
    recipe/profile paths (e.g. ``scripts/openrouter_lens.py``), resolve against
    ``repo_root`` so probe matches adapter dispatch even when the operator's cwd
    is not the checkout root. Bare basenames fall back to ``PATH`` via
    ``shutil.which``.
    """
    candidate = Path(name)
    if candidate.is_absolute():
        return str(candidate) if candidate.is_file() else None
    if repo_root is not None:
        under_root = Path(repo_root) / name
        if under_root.is_file():
            return str(under_root.resolve())
    return which_executable(name)


def _probe_executable(
    name: str | None,
    *,
    route: str | None = None,
    repo_root: Path | None = None,
) -> ProbeResult:
    label = route or name or "unknown"
    if not name:
        return ProbeResult(
            route=label,
            purpose=None,
            status="skip",
            detail="No executable name",
        )
    path = _resolve_executable_for_probe(name, repo_root=repo_root)
    if not path:
        return ProbeResult(
            route=label,
            purpose=None,
            status="fail",
            detail=f"Executable `{name}` not found on PATH or under repo root",
        )
    try:
        proc = subprocess.run(
            [path, "--help"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        # Many CLIs return 0 or 2 for --help; any output means the binary runs.
        out = (proc.stdout or "") + (proc.stderr or "")
        if out.strip() or proc.returncode in (0, 1, 2):
            return ProbeResult(
                route=label,
                purpose=None,
                status="pass",
                detail=f"`{name}` runs (--help ok, exit={proc.returncode})",
            )
        return ProbeResult(
            route=label,
            purpose=None,
            status="warn",
            detail=f"`{name}` found but --help produced no output (exit={proc.returncode})",
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(
            route=label,
            purpose=None,
            status="warn",
            detail=f"`{name}` --help timed out",
        )
    except OSError as exc:
        return ProbeResult(
            route=label,
            purpose=None,
            status="fail",
            detail=f"`{name}` failed to launch: {exc}",
        )


def _resolve_profile_executable(
    profile: str,
    *,
    profile_bodies: Mapping[str, Mapping[str, Any]],
    inventory_by_adapter: Mapping[str, Any],
) -> tuple[str | None, str]:
    """Return (executable_or_None, detail_hint) for a configured profile name."""
    body = profile_bodies.get(profile) or {}
    if body.get("executable"):
        return str(body["executable"]), "from models.toml profiles.*.executable"
    recipe_exe = resolve_recipe_executable(profile)
    if recipe_exe:
        return recipe_exe, "from PROFILE_RECIPES"
    adapter = str(body.get("adapter") or profile_adapter_name(profile))
    item = inventory_by_adapter.get(adapter)
    if item is not None and getattr(item, "executable", None):
        return str(item.executable), f"from inventory adapter `{adapter}`"
    defaults = default_profiles()
    if adapter in defaults and defaults[adapter].executable:
        return defaults[adapter].executable, f"from default adapter `{adapter}`"
    return None, f"no executable for profile `{profile}` (adapter `{adapter}`)"


def probe_routes(
    repo_root: Path,
    *,
    live_smoke: bool = False,
    smoke_executor: Any | None = None,
    fake_presence: Mapping[str, bool] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Structural probes for configured routes; optional live smoke.

    Structural: executable on PATH (or under ``repo_root`` for relative paths) +
    --help, env *names* present for API routes.
    Live smoke: only when live_smoke and smoke_executor provided (never invents responses).
    """
    state = load_models_toml_state(repo_root)
    roles = state.roles
    inventory = inventory_tools(fake_presence=fake_presence)
    by_adapter = {i.adapter: i for i in inventory}
    env_present = env_name_presence(environ=environ, repo_root=repo_root)
    probes: list[ProbeResult] = []
    notes = [
        "Structural probes do not spend model tokens.",
        "Live smoke is opt-in and must use a host-provided smoke_executor or follow-up host turns.",
        "Never print API key values.",
    ]
    notes.extend(state.warnings)

    # Always confirm host-native.
    probes.append(
        ProbeResult(
            route="host-native",
            purpose="always",
            status="pass",
            detail="Host coordinator path requires no external tool",
        )
    )

    for role, profile in roles.items():
        if profile == "host-native":
            probes.append(
                ProbeResult(
                    route=profile,
                    purpose=role,
                    status="pass",
                    detail="host-native",
                )
            )
            continue
        if profile_is_apply_blocked(profile):
            probes.append(
                ProbeResult(
                    route=profile,
                    purpose=role,
                    status="fail",
                    detail=(
                        f"Profile `{profile}` is apply-blocked (not a bare CLI). "
                        "Configure a custom-cli wrapper profile and point the role at that name."
                    ),
                )
            )
            continue

        adapter_key = route_presence_adapter(profile) or profile_adapter_name(profile)
        item = by_adapter.get(adapter_key)
        body = state.profiles.get(profile) or {}
        body_exe = str(body["executable"]) if body.get("executable") else None

        # Built-in adapters: inventory presence (including fake_presence) is authoritative.
        # custom-cli wrappers always declare their own executable in models.toml and are
        # probed by that binary, not by a generic "custom-cli" PATH entry.
        if (
            item is not None
            and not item.present
            and adapter_key != "custom-cli"
        ):
            probes.append(
                ProbeResult(
                    route=profile,
                    purpose=role,
                    status="fail",
                    detail=f"Adapter `{adapter_key}` not present on PATH (profile `{profile}`)",
                )
            )
            continue

        exe, exe_source = _resolve_profile_executable(
            profile,
            profile_bodies=state.profiles,
            inventory_by_adapter=by_adapter,
        )

        if not exe:
            # Unknown custom profile without executable — warn, not silent pass.
            probes.append(
                ProbeResult(
                    route=profile,
                    purpose=role,
                    status="warn" if profile in state.profiles else "fail",
                    detail=(
                        f"{exe_source}. Set profiles.{profile}.executable in models.toml "
                        "(see cobbler-setup-recipes.md for custom-cli wrappers)."
                    ),
                )
            )
            continue

        pr = _probe_executable(exe, route=profile, repo_root=repo_root)
        pr.purpose = role
        if pr.status == "pass":
            pr.detail = f"{pr.detail} ({exe_source})"
        probes.append(pr)

    # Optional API routes (env presence only unless smoke).
    if env_present.get("OPENROUTER_API_KEY"):
        probes.append(
            ProbeResult(
                route="openrouter",
                purpose="provider_breadth",
                status="pass",
                detail=(
                    "OPENROUTER_API_KEY name is set (value not inspected). "
                    "Use a custom-cli wrapper profile for dispatch — bare openrouter is not apply-ready."
                ),
            )
        )
    else:
        probes.append(
            ProbeResult(
                route="openrouter",
                purpose="provider_breadth",
                status="skip",
                detail="OPENROUTER_API_KEY not set — optional OpenRouter routes unavailable",
            )
        )

    if env_present.get("META_API_KEY") or env_present.get("MODEL_API_KEY"):
        probes.append(
            ProbeResult(
                route="meta-muse",
                purpose="provider_breadth",
                status="pass",
                detail=(
                    "META_API_KEY or MODEL_API_KEY name is set (value not inspected). "
                    "Use a custom-cli wrapper profile for dispatch — bare meta-muse is not apply-ready."
                ),
            )
        )
    else:
        probes.append(
            ProbeResult(
                route="meta-muse",
                purpose="provider_breadth",
                status="skip",
                detail="No Meta API key name set — Muse optional routes unavailable",
            )
        )

    if shutil.which("gcloud"):
        probes.append(
            ProbeResult(
                route="alphaevolve",
                purpose="math_evolutionary_search",
                status="pass",
                detail="gcloud on PATH (project must still provide AlphaEvolve runner + evaluator)",
            )
        )
    else:
        probes.append(
            ProbeResult(
                route="alphaevolve",
                purpose="math_evolutionary_search",
                status="skip",
                detail="gcloud not on PATH — AlphaEvolve optional",
            )
        )

    smoke: dict[str, Any] = {"requested": live_smoke, "ran": False, "detail": ""}
    if live_smoke:
        if smoke_executor is None:
            smoke["detail"] = (
                "Live smoke requested but no smoke_executor provided; "
                "host agent should run a real tiny completion per external route and re-invoke"
            )
            probes.append(
                ProbeResult(
                    route="live_smoke",
                    purpose=None,
                    status="warn",
                    detail=smoke["detail"],
                    kind="live_smoke",
                )
            )
        else:
            try:
                out = smoke_executor(roles=roles, inventory=inventory)
            except Exception as exc:  # noqa: BLE001
                smoke["detail"] = f"Smoke executor failed: {type(exc).__name__}: {exc}"
                probes.append(
                    ProbeResult(
                        route="live_smoke",
                        purpose=None,
                        status="fail",
                        detail=smoke["detail"],
                        kind="live_smoke",
                    )
                )
            else:
                if isinstance(out, Mapping) and (
                    out.get("text") or out.get("content") or out.get("results")
                ):
                    smoke["ran"] = True
                    smoke["detail"] = (
                        "Smoke executor returned a non-empty response (credentials not printed)"
                    )
                    probes.append(
                        ProbeResult(
                            route="live_smoke",
                            purpose=None,
                            status="pass",
                            detail=smoke["detail"],
                            kind="live_smoke",
                        )
                    )
                else:
                    smoke["detail"] = "Smoke executor returned empty or invalid payload"
                    probes.append(
                        ProbeResult(
                            route="live_smoke",
                            purpose=None,
                            status="fail",
                            detail=smoke["detail"],
                            kind="live_smoke",
                        )
                    )

    fails = sum(1 for p in probes if p.status == "fail")
    warns = sum(1 for p in probes if p.status == "warn")
    return {
        "ok": fails == 0,
        "generated_at": _utc_now(),
        "roles": roles,
        "profiles": {
            name: {
                "adapter": body.get("adapter"),
                "executable": body.get("executable"),
            }
            for name, body in state.profiles.items()
        },
        "env_present": env_present,
        "probes": [p.to_dict() for p in probes],
        "summary": {
            "pass": sum(1 for p in probes if p.status == "pass"),
            "warn": warns,
            "fail": fails,
        },
        "smoke": smoke,
        "credentials_printed": False,
        "warnings": list(state.warnings),
        "notes": notes,
    }


def show_onboarding(repo_root: Path) -> dict[str, Any]:
    state = load_models_toml_state(repo_root)
    return {
        "ok": state.parse_ok or not state.exists,
        "models_toml_path": str(state.path),
        "models_toml_exists": state.exists,
        "roles": state.roles,
        "profiles": {
            name: {
                "adapter": body.get("adapter"),
                "executable": body.get("executable"),
            }
            for name, body in state.profiles.items()
        },
        "required_roles": list(state.required_roles),
        "session_mode_default": state.session_mode,
        "sharing_policy": state.sharing_policy,
        "purposes": list(PURPOSE_CATALOG),
        "env_present": env_name_presence(repo_root=repo_root),
        "warnings": list(state.warnings),
        "update_hint": (
            "Re-run onboard plan (host interviews user) then onboard apply, "
            "or pass flags to onboard apply / setup directly. "
            "Partial apply merges into existing roles."
        ),
        "credentials_printed": False,
    }
