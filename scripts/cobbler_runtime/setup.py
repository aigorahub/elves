"""Setup UX for Cobbler external-agent preferences.

Inventory executables/capabilities without printing credentials or launching paid
model turns unless the caller explicitly opts into a smoke. Generate or update
the intentionally ignored local `.elves/models.toml`. Never stage that file.

Public default remains native-only with zero external tools or keys.
"""

from __future__ import annotations

import json
import re
import stat
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence  # Any used by PROFILE_RECIPES

from .context import SECRET_VALUE_PATTERNS as _SHARED_SECRET_VALUE_PATTERNS

from .adapters import default_profiles, is_fugu_profile_route
from .capabilities import doctor_inventory
from .config import models_toml_is_local_only, resolve_config
from .executables import resolve_executable
from .schema import NATIVE_PROFILE_NAME, RoleName, ValidationIssue
from .toml_compat import loads as load_toml_text


# Role slots users can prefer during setup (operations, not model identities).
SETUP_ROLE_SLOTS: tuple[str, ...] = (
    "planning",
    "implement",
    "lightweight_review",
    "validate",
    "review",
    "synthesize",
    "scout",
)

# Env var *names* only — never values.
OPTIONAL_ENV_NAMES: tuple[str, ...] = (
    "OPENROUTER_API_KEY",
    "META_API_KEY",
    "MODEL_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "EXA_API_KEY",
)

_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Shared corpus first so setup scanning and runtime redaction cannot drift.
    *(pattern for _name, pattern in _SHARED_SECRET_VALUE_PATTERNS),
    # Setup-specific: local filesystem paths are identifying in shared recipes.
    re.compile(r"/Users/[^\s\"']+"),
    re.compile(r"/home/[^\s\"']+"),
)


@dataclass
class ToolInventoryItem:
    adapter: str
    executable: str | None
    present: bool
    version: str | None = None
    auth: str = "unknown"
    session_support: str = "unknown"
    write_qualified: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SetupPreferences:
    """User/role preferences collected by setup (non-secret)."""

    roles: dict[str, str] = field(default_factory=dict)
    fallbacks: dict[str, list[str]] = field(default_factory=dict)
    required_roles: list[str] = field(default_factory=list)
    session_mode: str = "ephemeral"
    sharing_policy: str = "local-only"
    document_owner: str = "host-coordinator"
    usage_budget_warning: int | None = None
    run_smoke: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SetupResult:
    ok: bool
    inventory: list[ToolInventoryItem] = field(default_factory=list)
    preferences: SetupPreferences = field(default_factory=SetupPreferences)
    models_toml_path: str | None = None
    models_toml_written: bool = False
    models_toml_ignored: bool = True
    survival_guide_snapshot: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    smoke_ran: bool = False
    credentials_printed: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "inventory": [item.to_dict() for item in self.inventory],
            "preferences": self.preferences.to_dict(),
            "models_toml_path": self.models_toml_path,
            "models_toml_written": self.models_toml_written,
            "models_toml_ignored": self.models_toml_ignored,
            "survival_guide_snapshot": self.survival_guide_snapshot,
            "recommendations": list(self.recommendations),
            "warnings": list(self.warnings),
            "issues": list(self.issues),
            "smoke_ran": self.smoke_ran,
            "credentials_printed": self.credentials_printed,
            "notes": list(self.notes),
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def which_executable(name: str | None) -> str | None:
    return resolve_executable(name)


# Named profiles beyond bare adapter names: planning-quality vs labor tiers, Google plan/review.
PROFILE_RECIPES: dict[str, dict[str, Any]] = {
    NATIVE_PROFILE_NAME: {"adapter": NATIVE_PROFILE_NAME},
    "claude-code": {"adapter": "claude-code"},
    "claude-code-planning": {
        "adapter": "claude-code",
        "notes": "High-quality Claude for planning/review (set requested_model in TOML if desired)",
        "tier": "planning",
    },
    "claude-code-labor": {
        "adapter": "claude-code",
        "notes": "Volume Claude for implement labor (cheaper/faster model via requested_model)",
        "tier": "labor",
    },
    "grok-build": {"adapter": "grok-build"},
    "devin-cli": {
        "adapter": "devin-cli",
        "executable": "devin",
        "notes": (
            "Devin CLI (Cognition) — optional implement worker pinned to "
            "SWE-1.7 Lightning by default. Host captures the exact provider "
            "session id after create; resume uses --resume <id>. "
            "Permission mode auto maps to dangerous for unattended labor."
        ),
    },
    "omp-cli": {
        "adapter": "omp-cli",
        "executable": "omp",
        "notes": (
            "Oh My Pi (omp) — optional implement worker. Headless --mode json; "
            "host captures session UUID from NDJSON; resume uses --resume <uuid> only. "
            "Run-scoped --profile isolation; never --continue or omp --prewalk. "
            "Pin model via requested_model (e.g. google/gemini-2.5-flash)."
        ),
    },
    "codex-fugu": {
        "adapter": "codex-fugu",
        "notes": "Sakana Fugu for planning and read-only review only",
        "plan_review_only": True,
        "implement_blocked": True,
    },
    "codex-fugu-planning": {
        "adapter": "codex-fugu",
        "notes": "Regular fugu/high for planning and read-only review",
        "tier": "planning",
        "plan_review_only": True,
        "implement_blocked": True,
    },
    "codex-fugu-labor": {
        "adapter": "codex-fugu",
        "notes": "Deprecated Fugu labor profile. Fugu is limited to planning and read-only review.",
        "tier": "planning",
        "plan_review_only": True,
        "implement_blocked": True,
    },
    "gemini-cli": {
        "adapter": "gemini-cli",
        "executable": "gemini",
        "notes": (
            "Google Gemini CLI (API key / GEMINI_API_KEY) — plan/review lens. "
            "Pin a current model via requested_model (prefer latest Gemini, e.g. "
            "gemini-2.5-pro or newer when available). Headless needs --skip-trust. "
            "Not recommended for bulk implement."
        ),
        "plan_review_only": True,
    },
    "antigravity-cli": {
        "adapter": "antigravity-cli",
        "executable": "agy",
        "notes": (
            "Google Antigravity CLI (agy) — preferred Google plan/review lens. "
            "Pin latest Gemini via requested_model (e.g. 'Gemini 3.1 Pro (High)' for "
            "plan/review). OAuth or GCP project; not a main Elves host."
        ),
        "plan_review_only": True,
        "executable_fallbacks": ("antigravity",),
    },
    # Experimental labor: same adapter, Flash-class model for volume implement.
    # Not Lane A (that remains Grok-oriented). Host must qualify tools/yolo.
    "antigravity-labor": {
        "adapter": "antigravity-cli",
        "executable": "agy",
        "notes": (
            "Experimental Antigravity labor tier — pin a fast current model "
            "(e.g. 'Gemini 3.5 Flash (High)' or Medium). Not host-import write-lease "
            "qualified; not cobbler implement prepare/launch (Grok Lane A). "
            "Use only when you accept Google CLI tool semantics and cost."
        ),
        "tier": "labor",
        "plan_review_only": False,
        "executable_fallbacks": ("antigravity",),
    },
    "opencode-cli": {
        "adapter": "opencode-cli",
        "executable": "opencode",
        "notes": (
            "OpenCode (opencode.ai) — Claude Code–like terminal agent; OpenRouter and 75+ "
            "providers. Prefer plan/review with --agent plan; pin model as provider/model "
            "(e.g. openrouter/qwen/qwen3-max). Exact --session for continuity."
        ),
        "plan_review_only": True,
    },
    "opencode-labor": {
        "adapter": "opencode-cli",
        "executable": "opencode",
        "notes": (
            "Experimental OpenCode implement labor (main batch coding) via "
            "`opencode run --auto` + OpenRouter/other models. Not host-import write-lease "
            "qualified; not Grok Lane A default. Pin requested_model (provider/model). "
            "Prefer exact --session for continuity."
        ),
        "tier": "labor",
        "plan_review_only": False,
    },
    "custom-cli": {"adapter": "custom-cli"},
    # Provider-breadth tokens used in interview — not bare apply targets.
    # Host must configure a custom-cli wrapper (see cobbler-setup-recipes.md).
    "openrouter": {
        "adapter": "custom-cli",
        "apply_blocked": True,
        "notes": (
            "Bare token blocked. Use openrouter-lens or a named or-* preset "
            "(scripts/openrouter_lens.py + OPENROUTER_API_KEY)."
        ),
    },
    # Apply-ready OpenRouter plan/review lenses (custom-cli → scripts/openrouter_lens.py).
    "openrouter-lens": {
        "adapter": "custom-cli",
        "executable": "scripts/openrouter_lens.py",
        "notes": (
            "OpenRouter plan/review lens (read-only). Requires OPENROUTER_API_KEY. "
            "Pin requested_model to a current OpenRouter id (e.g. qwen/qwen3-max, "
            "z-ai/glm-5). Prefer exact session_id for plan→review; else attach plan "
            "docs via packet/context files. Never main host or bulk implement."
        ),
        "plan_review_only": True,
    },
    "or-qwen-max": {
        "adapter": "custom-cli",
        "executable": "scripts/openrouter_lens.py",
        "notes": (
            "Named OpenRouter preset for a strong Qwen-class plan/review model. "
            "Set requested_model to the current OpenRouter slug (re-check catalog). "
            "Example dogfood: qwen/qwen3-max — update when OpenRouter renames."
        ),
        "plan_review_only": True,
        "default_requested_model": "qwen/qwen3-max",
    },
    "or-glm": {
        "adapter": "custom-cli",
        "executable": "scripts/openrouter_lens.py",
        "notes": (
            "Named OpenRouter preset for a strong GLM-class plan/review model. "
            "Set requested_model to the current OpenRouter slug (re-check catalog). "
            "Example dogfood: z-ai/glm-5 — update when OpenRouter renames."
        ),
        "plan_review_only": True,
        "default_requested_model": "z-ai/glm-5",
    },
    "meta-muse": {
        "adapter": "custom-cli",
        "apply_blocked": True,
        "notes": (
            "Meta Muse is not a bare CLI. Configure a custom-cli wrapper profile "
            "(see cobbler-setup-recipes.md) and apply that profile name."
        ),
    },
    "alphaevolve": {
        "adapter": "custom-cli",
        "apply_blocked": True,
        "notes": (
            "AlphaEvolve is math Survival Guide config, not an onboard apply role "
            "(see math-alphaevolve.md)."
        ),
    },
}


def profile_adapter_name(profile: str) -> str:
    """Resolve a profile or tier name to its inventory adapter key."""
    recipe = PROFILE_RECIPES.get(profile)
    if recipe:
        return str(recipe.get("adapter") or profile)
    return profile


def profile_is_apply_blocked(profile: str) -> bool:
    recipe = PROFILE_RECIPES.get(profile) or {}
    return bool(recipe.get("apply_blocked"))


def profile_is_fugu_route(
    profile: str,
    existing_profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> bool:
    body = dict((existing_profiles or {}).get(profile) or {})
    recipe = PROFILE_RECIPES.get(profile) or {}
    adapter = str(body.get("adapter") or recipe.get("adapter") or profile)
    executable = body.get("executable") or recipe.get("executable")
    return is_fugu_profile_route(
        adapter=adapter,
        executable=str(executable) if executable else None,
        requested_model=(
            str(body.get("requested_model") or body.get("model") or "") or None
        ),
    )


def resolve_recipe_executable(profile: str) -> str | None:
    """Pick executable from recipe, preferring PATH-present fallbacks."""
    recipe = PROFILE_RECIPES.get(profile) or {}
    primary = recipe.get("executable")
    if primary and which_executable(str(primary)):
        return str(primary)
    for alt in recipe.get("executable_fallbacks") or ():
        if which_executable(str(alt)):
            return str(alt)
    if primary:
        return str(primary)
    # Bare adapter profiles use default_profiles executable hints.
    defaults = default_profiles()
    adapter = profile_adapter_name(profile)
    if adapter in defaults and defaults[adapter].executable:
        return defaults[adapter].executable
    return None


def inventory_tools(
    *,
    fake_presence: Mapping[str, bool] | None = None,
    fake_versions: Mapping[str, str | None] | None = None,
    fake_auth: Mapping[str, str] | None = None,
) -> list[ToolInventoryItem]:
    """Inventory built-in adapters without reading secret values."""
    fake_presence = fake_presence or {}
    fake_versions = fake_versions or {}
    fake_auth = fake_auth or {}
    items: list[ToolInventoryItem] = []
    for name, profile in sorted(default_profiles().items()):
        if name == NATIVE_PROFILE_NAME:
            items.append(
                ToolInventoryItem(
                    adapter=name,
                    executable=None,
                    present=True,
                    version="host",
                    auth="n/a",
                    session_support="unavailable",
                    write_qualified=True,
                    notes="Host coordinator always available; no external key required",
                )
            )
            continue
        exe = profile.executable
        if name in fake_presence:
            present = bool(fake_presence[name])
        else:
            present = which_executable(exe) is not None
            if name == "antigravity-cli" and not present:
                # Prefer agy; accept legacy antigravity binary name.
                for alt in ("agy", "antigravity"):
                    if which_executable(alt):
                        present = True
                        exe = alt
                        break
        version = fake_versions.get(name)
        auth = fake_auth.get(name, "unknown" if present else "missing")
        # Never infer auth from env var *presence of values* — only name existence as hint.
        write_qualified = False
        if name == "grok-build" and present:
            write_qualified = True  # still requires lease/devbox qualification at runtime
        session = "advertised" if present else "unavailable"
        notes = ""
        if name == "grok-build":
            notes = "Headless worktree-resume broken on 0.2.93; use exact child + registered worktree"
        if name == "custom-cli":
            notes = "User-defined wrapper; qualify capabilities before write roles"
        if name in {"gemini-cli", "antigravity-cli"}:
            notes = "Google subscription CLI — prefer planning/review; avoid bulk implement cost"
        items.append(
            ToolInventoryItem(
                adapter=name,
                executable=exe,
                present=present,
                version=version,
                auth=auth,
                session_support=session,
                write_qualified=write_qualified,
                notes=notes,
            )
        )
    return items


def recommend_routes(inventory: Sequence[ToolInventoryItem]) -> list[str]:
    """Capability-first recommendations with dates — not prestige model names."""
    present = {item.adapter for item in inventory if item.present}
    recs: list[str] = [
        f"Generated {_utc_now()}: prefer host-native for validate/synthesize by default.",
        "Setup is optional; native-only Elves needs no external tools or keys.",
        "Commit/push/PR are host operations, not model roles.",
        "Within a family, prefer a high-quality model for plan/review and a labor model for implement.",
    ]
    if "claude-code" in present:
        recs.append(
            "claude-code present: use claude-code-planning for plan/review and "
            "claude-code-labor for implement volume when you want a tier split; "
            "set requested_model on each profile in models.toml (no public prestige defaults)."
        )
    if "grok-build" in present:
        recs.append(
            "grok-build present: candidate for isolated implementation under a writer lease "
            "with verified detached worktree; never treat headless worktree-resume as isolation on 0.2.93."
        )
    if "codex-fugu" in present:
        recs.append(
            "codex-fugu present: use it only for planning or read-only review; "
            "MCP OAuth warnings are not inference failures."
        )
    if "gemini-cli" in present or "antigravity-cli" in present:
        recs.append(
            "Google Gemini CLI / Antigravity CLI present: good optional plan/review lenses; "
            "usually not cost-effective for the main implement batch."
        )
    if present <= {NATIVE_PROFILE_NAME}:
        recs.append("No external CLIs detected: stay fully native-host for all roles.")
    else:
        recs.append(
            "Map optional external adapters by capability (session/write/read-only), "
            "and keep native fallbacks for every optional role."
        )
    recs.append(
        "OpenRouter/API-only routes (when configured) are optional read-only breadth; "
        "they cannot edit worktrees unless a qualified wrapper proves write/isolation."
    )
    return recs


def assert_toml_has_no_secrets(text: str) -> None:
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(text):
            raise ValidationIssue(
                "secret_or_path_in_toml",
                "Generated or provided models.toml appears to contain a secret or personal path",
                hint="Use environment variable names only; never paste key values or /Users/... paths",
            )


def _toml_key(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_-]+", value) else json.dumps(value)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, Mapping):
        entries = ", ".join(
            f"{_toml_key(str(key))} = {_toml_value(item)}"
            for key, item in value.items()
            if item is not None
        )
        return "{ " + entries + " }"
    raise ValidationIssue(
        "unsupported_profile_value",
        f"Cannot preserve models.toml profile value of type {type(value).__name__}",
    )


def render_models_toml(
    preferences: SetupPreferences,
    *,
    existing_profiles: Mapping[str, Mapping[str, Any]] | None = None,
    existing_top_level: Mapping[str, Any] | None = None,
) -> str:
    """Render a local models.toml from preferences (no credentials)."""
    lines: list[str] = [
        "# Local Cobbler external-agent preferences (machine-local; do not stage)",
        f"# Generated by cobbler_agents setup at {_utc_now()}",
        "# Precedence: Survival Guide > this file > config.json > native defaults",
        "# Never put raw credentials or personal absolute paths in this file.",
        "# optional env var names only, e.g. OPENROUTER_API_KEY",
        "",
        f'sharing_policy = "{preferences.sharing_policy}"',
        f'document_owner = "{preferences.document_owner}"',
        f'session_mode_default = "{preferences.session_mode}"',
        "",
    ]
    if preferences.usage_budget_warning is not None:
        lines.append(f"usage_budget_warning_tokens = {int(preferences.usage_budget_warning)}")
        lines.append("")

    standard_top_level = {
        "roles",
        "profiles",
        "session_mode_default",
        "sharing_policy",
        "document_owner",
        "usage_budget_warning_tokens",
    }
    for key, value in (existing_top_level or {}).items():
        if key not in standard_top_level and value is not None:
            lines.append(f"{_toml_key(str(key))} = {_toml_value(value)}")
    if existing_top_level:
        lines.append("")

    # Profiles referenced by roles
    profiles_needed: set[str] = set()
    for profile in preferences.roles.values():
        profiles_needed.add(profile)
    for chain in preferences.fallbacks.values():
        profiles_needed.update(chain)
    # Partial apply must preserve every existing profile body, including inactive
    # custom wrappers the user may route to again later.
    profiles_needed.update((existing_profiles or {}).keys())
    profiles_needed.discard("")

    for profile_name in sorted(profiles_needed):
        recipe = PROFILE_RECIPES.get(profile_name)
        if recipe is None:
            adapter = "custom-cli"
            executable = None
            notes = (
                "Unknown profile name — set adapter/executable explicitly before use; "
                "onboard apply rejects bare openrouter/meta-muse/alphaevolve tokens"
            )
        else:
            adapter = str(recipe.get("adapter") or "custom-cli")
            executable = resolve_recipe_executable(profile_name)
            notes = recipe.get("notes")
        lines.append(f"[profiles.{_toml_key(profile_name)}]")
        existing_body = dict((existing_profiles or {}).get(profile_name) or {})
        if existing_body:
            existing_body.setdefault("adapter", adapter)
            if executable:
                existing_body.setdefault("executable", executable)
            priority = ("adapter", "executable", "requested_model", "extra_args", "notes")
            ordered_keys = [key for key in priority if key in existing_body]
            ordered_keys.extend(key for key in existing_body if key not in ordered_keys)
            for key in ordered_keys:
                value = existing_body[key]
                if value is not None:
                    lines.append(f"{_toml_key(str(key))} = {_toml_value(value)}")
            lines.append("")
            continue
        lines.append(f'adapter = "{adapter}"')
        if executable:
            lines.append(f'executable = "{executable}"')
        if (
            adapter == "custom-cli"
            and profile_name not in PROFILE_RECIPES
            and not executable
        ):
            # Do not invent my-coding-agent for known apply-blocked tokens.
            lines.append(
                '# executable = "…"  # required for custom-cli — set your wrapper path'
            )
        if notes:
            safe = str(notes).replace('"', "'")
            lines.append(f'notes = "{safe}"')
        if (
            recipe
            and recipe.get("tier") in {"planning", "labor"}
            and adapter != "codex-fugu"
        ):
            lines.append(
                '# requested_model = "…"  # optional: pin high-quality vs labor model for this tier'
            )
        default_model = (recipe or {}).get("default_requested_model")
        if default_model:
            lines.append(
                f'# requested_model = "{default_model}"  '
                "# pin current OpenRouter slug; re-check catalog after upgrades"
            )
        if recipe and recipe.get("plan_review_only"):
            lines.append(
                "# Prefer this profile on planning/review/scout roles only — not bulk implement."
            )
        if recipe and recipe.get("apply_blocked"):
            lines.append(
                "# apply_blocked: do not use this token as roles.*.profile without a real wrapper."
            )
        lines.append("")

    for role in SETUP_ROLE_SLOTS:
        profile = preferences.roles.get(role, NATIVE_PROFILE_NAME)
        required = role in preferences.required_roles
        lines.append(f"[roles.{role}]")
        lines.append(f'profile = "{profile}"')
        lines.append(f"required = {'true' if required else 'false'}")
        chain = preferences.fallbacks.get(role) or []
        if chain:
            lines.append("fallback_chain = [")
            for entry in chain:
                lines.append(
                    f'  {{ profile = "{entry}", reason = "setup-configured fallback" }},'
                )
            lines.append("]")
        lines.append("")

    lines.append("# Optional env var names for provider-backed breadth (values live in the environment):")
    lines.append("# optional_env = [")
    for name in OPTIONAL_ENV_NAMES:
        lines.append(f'#   "{name}",')
    lines.append("# ]")
    lines.append("")
    text = "\n".join(lines)
    assert_toml_has_no_secrets(text)
    return text


def write_models_toml(
    repo_root: Path,
    text: str,
    *,
    force: bool = False,
    preserve_existing_if_unknown_sections: bool = True,
    unknown_sections_preserved: bool = False,
) -> tuple[Path, bool]:
    """Write ignored local models.toml. Refuses lossy overwrite when unknown sections exist."""
    assert_toml_has_no_secrets(text)
    path = Path(repo_root) / ".elves" / "models.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and not force:
        existing = path.read_text(encoding="utf-8")
        # Heuristic: unknown top-level sections beyond profiles/roles/comments
        if (
            preserve_existing_if_unknown_sections
            and not unknown_sections_preserved
            and re.search(
                r"^\[(?!profiles\.|roles\.)[^\]]+\]", existing, re.M
            )
        ):
            raise ValidationIssue(
                "models_toml_unknown_sections",
                f"`{path}` has unknown sections; refusing lossy rewrite",
                path=str(path),
                hint="Pass force=True only after reviewing the file, or merge manually",
            )
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path, True


def survival_guide_route_snapshot(
    preferences: SetupPreferences,
    *,
    inventory: Sequence[ToolInventoryItem],
) -> dict[str, Any]:
    """Committed-route-snapshot *shape* for Survival Guide (host writes the file)."""
    present = sorted(item.adapter for item in inventory if item.present)
    return {
        "document_owner": preferences.document_owner,
        "sharing_policy": preferences.sharing_policy,
        "session_mode_default": preferences.session_mode,
        "roles": {
            role: {
                "profile": preferences.roles.get(role, NATIVE_PROFILE_NAME),
                "required": role in preferences.required_roles,
                "fallback_chain": list(preferences.fallbacks.get(role) or []),
                "source": "setup_preferences",
            }
            for role in SETUP_ROLE_SLOTS
        },
        "inventory_present": present,
        "notes": [
            "Host coordinator should paste/adapt this snapshot into the Survival Guide "
            "model-routing block during staging for reviewable provenance.",
            "Local .elves/models.toml remains ignored machine preference.",
        ],
        "generated_at": _utc_now(),
    }


def preferences_from_flags(
    *,
    implement: str | None = None,
    review: str | None = None,
    planning: str | None = None,
    lightweight_review: str | None = None,
    validate: str | None = None,
    synthesize: str | None = None,
    scout: str | None = None,
    required: Sequence[str] | None = None,
    session_mode: str = "ephemeral",
    sharing_policy: str = "local-only",
    native_fallback: bool = True,
    base_roles: Mapping[str, str] | None = None,
) -> SetupPreferences:
    """Deterministic non-interactive preference builder.

    When ``base_roles`` is provided (e.g. existing models.toml), only roles with
    explicit non-empty flags are overwritten — partial apply is merge semantics.
    """
    roles = {role: NATIVE_PROFILE_NAME for role in SETUP_ROLE_SLOTS}
    if base_roles:
        for role, profile in base_roles.items():
            if role in roles and profile:
                roles[role] = str(profile)
    mapping = {
        "implement": implement,
        "review": review,
        "planning": planning,
        "lightweight_review": lightweight_review,
        "validate": validate,
        "synthesize": synthesize,
        "scout": scout,
    }
    for role, value in mapping.items():
        if value:
            roles[role] = value
    fallbacks: dict[str, list[str]] = {}
    if native_fallback:
        for role, profile in roles.items():
            if profile != NATIVE_PROFILE_NAME:
                fallbacks[role] = [NATIVE_PROFILE_NAME]
    required_roles = [r for r in (required or []) if r in SETUP_ROLE_SLOTS]
    return SetupPreferences(
        roles=roles,
        fallbacks=fallbacks,
        required_roles=required_roles,
        session_mode=session_mode,
        sharing_policy=sharing_policy,
        document_owner="host-coordinator",
    )


def run_setup(
    repo_root: Path,
    *,
    preferences: SetupPreferences | None = None,
    write_toml: bool = True,
    force_toml: bool = False,
    run_smoke: bool = False,
    smoke_executor: Any | None = None,
    dry_run: bool = False,
    fake_presence: Mapping[str, bool] | None = None,
    fake_versions: Mapping[str, str | None] | None = None,
    fake_auth: Mapping[str, str] | None = None,
    existing_profiles: Mapping[str, Mapping[str, Any]] | None = None,
    existing_top_level: Mapping[str, Any] | None = None,
) -> SetupResult:
    """Run setup inventory + optional local models.toml generation.

    Never prints credentials. ``run_smoke`` is opt-in and sets ``smoke_ran`` only
    when ``smoke_executor`` returns a valid non-empty model response. Dry-run and
    default paths write nothing unless ``write_toml`` is True and not dry-run.
    """
    root = Path(repo_root)
    inventory = inventory_tools(
        fake_presence=fake_presence,
        fake_versions=fake_versions,
        fake_auth=fake_auth,
    )
    prefs = preferences or preferences_from_flags()
    result = SetupResult(
        ok=True,
        inventory=inventory,
        preferences=prefs,
        recommendations=recommend_routes(inventory),
        notes=[
            "Never stage .elves/models.toml",
            "Never paste API keys into TOML, chat, or Survival Guide",
            "Commit/push/PR are host operations, not model roles",
            "Setup is optional for native-only Elves",
        ],
        credentials_printed=False,
        smoke_ran=False,
    )

    if run_smoke:
        if smoke_executor is None:
            result.warnings.append(
                "Smoke requested but no smoke_executor was provided; smoked=false "
                "(acknowledgment alone is not a model response)"
            )
        else:
            try:
                smoke_result = smoke_executor(inventory=inventory, preferences=prefs)
            except Exception as exc:  # noqa: BLE001 — surface as setup issue, not crash
                result.ok = False
                result.issues.append(
                    {
                        "code": "smoke_failed",
                        "message": f"Smoke executor failed: {type(exc).__name__}: {exc}",
                    }
                )
                smoke_result = None
            if isinstance(smoke_result, Mapping):
                text = str(
                    smoke_result.get("text")
                    or smoke_result.get("content")
                    or smoke_result.get("message")
                    or ""
                ).strip()
                model = smoke_result.get("actual_model") or smoke_result.get("model")
                if text and model:
                    result.smoke_ran = True
                    result.notes.append(
                        f"Smoke succeeded with actual_model={model} (credentials not printed)"
                    )
                else:
                    result.warnings.append(
                        "Smoke executor returned no valid model response; smoked=false"
                    )
            elif smoke_result:
                result.warnings.append(
                    "Smoke executor returned a non-mapping result; smoked=false"
                )

    # Reject apply-blocked tokens (openrouter/meta-muse/alphaevolve bare names).
    for role, profile in prefs.roles.items():
        if profile_is_apply_blocked(profile):
            result.ok = False
            result.issues.append(
                {
                    "code": "apply_blocked_profile",
                    "message": (
                        f"Role `{role}` uses apply-blocked profile `{profile}`. "
                        f"{(PROFILE_RECIPES.get(profile) or {}).get('notes', '')}"
                    ),
                }
            )

    # Reject profiles that cannot perform implementation work.
    implement_profile = prefs.roles.get("implement", NATIVE_PROFILE_NAME)
    impl_recipe = PROFILE_RECIPES.get(implement_profile) or {}
    if impl_recipe.get("implement_blocked") or profile_is_fugu_route(
        implement_profile,
        existing_profiles,
    ):
        result.ok = False
        result.issues.append(
            {
                "code": "implement_profile_blocked",
                "message": (
                    f"Implement role uses profile `{implement_profile}`, which is limited "
                    "to planning and read-only review."
                ),
            }
        )
    elif impl_recipe.get("plan_review_only"):
        result.warnings.append(
            f"Implement role uses plan/review-only profile `{implement_profile}` — "
            "usually not cost-effective for bulk implement; prefer host-native or labor tier."
        )

    # Validate required roles against inventory presence (tier → underlying adapter).
    present = {item.adapter for item in inventory if item.present}
    for role in prefs.required_roles:
        profile = prefs.roles.get(role, NATIVE_PROFILE_NAME)
        if profile == NATIVE_PROFILE_NAME:
            continue
        if profile_is_apply_blocked(profile):
            continue  # already recorded
        adapter = profile_adapter_name(profile)
        if adapter not in present and profile not in present:
            result.ok = False
            result.issues.append(
                {
                    "code": "required_route_unavailable",
                    "message": (
                        f"Required role `{role}` maps to profile `{profile}` "
                        f"(adapter `{adapter}`) but that tool is not present"
                    ),
                }
            )

    meta = models_toml_is_local_only(root)
    result.models_toml_ignored = bool(meta.get("ignored_by_gitignore", True))
    result.models_toml_path = str(root / ".elves" / "models.toml")

    should_write = write_toml and result.ok and not dry_run
    if dry_run:
        result.notes.append("Dry-run: no files written")
    if should_write:
        try:
            text = render_models_toml(
                prefs,
                existing_profiles=existing_profiles,
                existing_top_level=existing_top_level,
            )
            path, written = write_models_toml(
                root,
                text,
                force=force_toml,
                unknown_sections_preserved=existing_top_level is not None,
            )
            result.models_toml_written = written
            result.models_toml_path = str(path)
            # Prove generated TOML parses and resolves on every supported Python.
            parsed = load_toml_text(text)
            resolved = resolve_config(models_toml=parsed)
            if not resolved.ok:
                result.warnings.append(
                    "Generated models.toml has validation issues: "
                    + "; ".join(i.message for i in resolved.issues)
                )
        except ValidationIssue as issue:
            result.ok = False
            result.issues.append(issue.to_dict())

    result.survival_guide_snapshot = survival_guide_route_snapshot(
        prefs, inventory=inventory
    )
    # Doctor inventory shape available for richer reports without secrets.
    _ = doctor_inventory(default_profiles())
    return result
