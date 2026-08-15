"""Deterministic, model-free adaptive implementation-worker routing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import load_json_file, load_toml_file
from .host_profiles import (
    resolve_host_profile,
    supported_efforts_for_host,
    transport_for_host,
)
from .prewalk import PrewalkCapabilities
from .storage import read_bounded_artifact_bytes
from .schema import (
    NativeWorkerPhaseRole,
    NativeWorkerPhaseRoute,
    PrewalkCapabilityState,
    PrewalkInstructionFidelity,
    PrewalkMode,
    PrewalkRoutePair,
    ValidationIssue,
)


REASONING_LEVELS = ("low", "medium", "high")
REVIEW_RISKS = ("low", "standard", "high")
# xAI retired Composer 2.5; permitted Grok workers use Grok 4.5 when the live
# catalog offers it. There is no separate "heavy" model id in current Grok Build
# catalogs — strength is model `grok-4.5` plus default effort `high`.
GROK_WORKER_MODEL = "grok-4.5"
GROK_COMPLEX_MODEL = GROK_WORKER_MODEL  # historical alias for the strong worker
GROK_RETIRED_COMPOSER_MODEL = "grok-composer-2.5-fast"  # never select; tests only
GROK_UPSTREAM_SOURCE_URL = "https://github.com/xai-org/grok-build"
GROK_UPSTREAM_SEMANTIC_COMMIT = "7cfcb20d2b50b0d18801a6c0af2e401c0e060894"
MAX_GROK_GOAL_CANARY_ARTIFACT_BYTES = 64 * 1024
MAX_GROK_GOAL_CANARY_PROMPT_BYTES = 32 * 1024

# GPT-5.6 sibling models: Codex multi-agent v2 supports cross-sibling
# delegation within the 5.6 family via model change on exact resume.
GPT_56_SIBLINGS = frozenset({
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-daybreak-blue-latest",  # defensive cybersecurity variant
    "gpt-5.5",  # complex coding/research
})


@dataclass(frozen=True)
class GrokCapabilityEvidence:
    """Redaction-safe evidence for one installed-binary capability."""

    state: str
    source: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state, "source": self.source, "reason": self.reason}


@dataclass(frozen=True)
class GrokCapabilities:
    installed: bool = False
    authenticated: bool = False
    models: tuple[str, ...] = ()
    goal_entrypoint_advertised: bool = False
    goal_mode_behaviorally_verified: bool = False
    goal_behavioral_evidence: str | None = None
    # Private input locator retained only so a resumed full-run can revalidate
    # the same artifact. It is intentionally absent from safe_snapshot().
    goal_behavioral_artifact_path: str | None = None
    version: str | None = None
    installed_build_commit: str | None = None
    default_model: str | None = None
    capability_ledger: tuple[tuple[str, GrokCapabilityEvidence], ...] = ()

    def supports(self, model: str) -> bool:
        return self.installed and self.authenticated and model in self.models

    def capability(self, name: str) -> GrokCapabilityEvidence | None:
        return dict(self.capability_ledger).get(name)

    def core_launch_unavailable_reason(
        self,
        *,
        create: bool = True,
        check: bool = False,
    ) -> str | None:
        """Return the first missing capability for the actual trusted launch argv."""
        if not self.capability_ledger:
            return None
        required = [
            "prompt_file",
            "cwd",
            "model",
            "permission_mode",
            "always_approve",
            "reasoning_effort",
            "max_turns",
            "output_format",
            "streaming_json",
            "session_id" if create else "resume",
        ]
        if check:
            required.append("check")
        for name in required:
            evidence = self.capability(name)
            if evidence is None or evidence.state != "proven":
                detail = evidence.reason if evidence is not None else "not_probed"
                return f"capability_unavailable:{name}:{detail}"
        return None

    def safe_snapshot(self) -> dict[str, Any]:
        """Return normalized facts only; never retain command output or auth diagnostics."""
        return {
            "schema_version": 1,
            "installed": self.installed,
            "version": self.version,
            "installed_build_commit": self.installed_build_commit,
            "authenticated": self.authenticated,
            "models": list(self.models),
            "default_model": self.default_model,
            "semantic_reference": {
                "url": GROK_UPSTREAM_SOURCE_URL,
                "commit": GROK_UPSTREAM_SEMANTIC_COMMIT,
                "authority": "semantic_reference_only",
            },
            "capabilities": {
                name: evidence.to_dict() for name, evidence in self.capability_ledger
            },
        }


_GROK_HELP_CAPABILITIES: tuple[tuple[str, str], ...] = (
    ("prompt_file", "--prompt-file"),
    ("cwd", "--cwd"),
    ("model", "--model"),
    ("permission_mode", "--permission-mode"),
    ("always_approve", "--always-approve"),
    ("reasoning_effort", "--reasoning-effort"),
    ("max_turns", "--max-turns"),
    ("output_format", "--output-format"),
    ("no_subagents", "--no-subagents"),
    ("no_memory", "--no-memory"),
    ("disable_web_search", "--disable-web-search"),
    ("check", "--check"),
    ("session_id", "--session-id"),
    ("resume", "--resume"),
    ("new_session", "--new-session"),
    ("streaming_json", "streaming-json"),
    ("json_schema", "--json-schema"),
)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_MODEL_ID_RE = r"[A-Za-z0-9][A-Za-z0-9._:/-]*"
_MODEL_ROW_RE = re.compile(
    rf"(?im)^\s*(?P<marker>[-*])\s+(?P<model>{_MODEL_ID_RE})"
    rf"(?P<default>\s+\(default\))?\s*$"
)
_DEFAULT_MODEL_RE = re.compile(
    rf"(?im)^\s*Default model:\s*(?P<model>{_MODEL_ID_RE})\s*$"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def is_gpt_56_sibling(model: str | None) -> bool:
    """Return whether a model is a GPT-5.6 family sibling."""
    if model is None:
        return False
    normalized = model.strip().lower()
    # Match canonical Codex desktop slugs plus any future 5.6 variants
    if normalized in GPT_56_SIBLINGS:
        return True
    # Also accept variants with different casing or "gpt5.6" without hyphen
    base = normalized.replace("gpt-", "gpt").replace("gpt5.6", "gpt-5.6")
    return base in {s.replace("gpt-", "gpt") for s in GPT_56_SIBLINGS}


def select_preferred_grok_worker_model(
    capabilities: GrokCapabilities,
    *,
    requested: str | None = None,
) -> str | None:
    """Choose a launchable Grok model from live capabilities.

    Preference order:
    1. Explicit requested id (when present in the live catalog and not retired)
    2. ``GROK_WORKER_MODEL`` (``grok-4.5``) when present
    3. Non-retired live default
    4. ``None`` when only retired/unavailable options remain
    """
    req = (requested or "").strip()
    if req and req not in {"", "auto"}:
        if req == GROK_RETIRED_COMPOSER_MODEL:
            return None
        return req if capabilities.supports(req) else None
    if capabilities.supports(GROK_WORKER_MODEL):
        return GROK_WORKER_MODEL
    default = capabilities.default_model
    if default and default != GROK_RETIRED_COMPOSER_MODEL and capabilities.supports(default):
        return default
    return None


def resolve_user_specified_worker_model(
    *,
    requested_model: str | None,
    live_catalog: Mapping[str, Any] | Sequence[str] | None = None,
    retired: frozenset[str] | None = None,
) -> tuple[str | None, str]:
    """Resolve an explicit user-pinned worker model against a live catalog.

    Returns ``(model_id_or_none, policy_or_reason)``. Missing/retired/unlisted
    models fail closed with ``None`` and a stable reason token. Prewalk and
    prompt-cache eligibility remain separate: callers must still qualify the
    host transport before claiming exact-session prewalk.
    """
    retired = retired or frozenset({GROK_RETIRED_COMPOSER_MODEL})
    req = (requested_model or "").strip()
    if not req or req == "auto":
        return None, "no_explicit_worker_model"
    if req in retired:
        return None, f"model_retired:{req}"
    catalog: set[str] = set()
    if live_catalog is None:
        return None, "live_catalog_unavailable"
    if isinstance(live_catalog, Mapping):
        for key in ("models", "available", "ids"):
            val = live_catalog.get(key)
            if isinstance(val, (list, tuple, set)):
                catalog.update(str(x).strip() for x in val if str(x).strip())
        # also accept mapping keys as model ids when values are truthy metadata
        if not catalog:
            catalog.update(str(k).strip() for k, v in live_catalog.items() if v and str(k).strip())
    else:
        catalog.update(str(x).strip() for x in live_catalog if str(x).strip())
    if req not in catalog:
        return None, f"model_unavailable:{req}"
    return req, "explicit_catalog_model_pin"


def handoff_cache_key(
    *,
    host: str,
    guide_model: str | None,
    worker_model: str | None,
    worker_effort: str | None,
    prewalk_mode: str,
) -> str:
    """Stable, non-secret key for reuse of qualified handoff/prewalk proof."""
    payload = {
        "host": host,
        "guide_model": guide_model or "",
        "worker_model": worker_model or "",
        "worker_effort": worker_effort or "",
        "prewalk_mode": prewalk_mode,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_live_model_catalog(stdout: str) -> tuple[tuple[str, ...], str | None]:
    """Parse only anchored rows from `grok models`, never diagnostic prose."""
    clean = _ANSI_ESCAPE_RE.sub("", stdout or "")
    header = re.search(r"(?im)^\s*Available models:\s*$", clean)
    if header is None:
        return (), None
    rows = list(_MODEL_ROW_RE.finditer(clean[header.end() :]))
    models = tuple(dict.fromkeys(match.group("model") for match in rows))
    default_match = _DEFAULT_MODEL_RE.search(clean)
    default_model = default_match.group("model") if default_match else None
    default_rows = [
        match
        for match in rows
        if match.group("model") == default_model
        and (match.group("marker") == "*" or match.group("default"))
    ]
    if not models or default_model not in models or len(default_rows) != 1:
        return (), None
    return models, default_model


def _goal_canary_unavailable(reason: str) -> tuple[GrokCapabilityEvidence, None]:
    return (
        GrokCapabilityEvidence(
            state="unavailable",
            source="validated_terminal_goal_canary_artifact",
            reason=reason,
        ),
        None,
    )


def _read_goal_canary_artifact(path_value: str) -> bytes:
    """Read one bounded regular artifact without following a symlink."""
    return read_bounded_artifact_bytes(
        Path(path_value).expanduser(),
        max_bytes=MAX_GROK_GOAL_CANARY_ARTIFACT_BYTES,
    )


def validate_grok_goal_canary_artifact(
    artifact_path: str | None,
    *,
    installed_version: str | None,
    installed_build_commit: str | None,
) -> tuple[GrokCapabilityEvidence, str | None]:
    """Validate terminal goal proof bound to the exact installed Grok build.

    Artifact schema v1 is a bounded JSON object with:
    ``artifact_type``, ``schema_version``, installed version/build, canonical
    ``session_id``, exact ``prompt`` plus ``prompt_sha256``, zero ``exit_code``,
    and the exact successful streaming ``terminal_event``.
    """
    value = str(artifact_path or "").strip()
    if not value:
        return _goal_canary_unavailable("terminal_objective_canary_not_recorded")
    if not installed_version or not installed_build_commit:
        return _goal_canary_unavailable("installed_build_identity_unavailable")
    try:
        raw = _read_goal_canary_artifact(value)
    except (OSError, RuntimeError, ValueError):
        return _goal_canary_unavailable("goal_canary_artifact_unavailable_or_unsafe")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _goal_canary_unavailable("goal_canary_artifact_malformed")
    if not isinstance(payload, Mapping):
        return _goal_canary_unavailable("goal_canary_artifact_malformed")
    required = {
        "artifact_type",
        "schema_version",
        "installed_version",
        "installed_build_commit",
        "session_id",
        "prompt",
        "prompt_sha256",
        "exit_code",
        "terminal_event",
    }
    if set(payload) != required:
        return _goal_canary_unavailable("goal_canary_artifact_schema_invalid")
    if (
        payload.get("artifact_type") != "grok_goal_terminal_canary"
        or payload.get("schema_version") != 1
        or payload.get("installed_version") != installed_version
        or str(payload.get("installed_build_commit") or "").lower()
        != installed_build_commit.lower()
    ):
        return _goal_canary_unavailable("goal_canary_artifact_build_mismatch")
    session_id = payload.get("session_id")
    try:
        canonical_session = str(uuid.UUID(str(session_id)))
    except (AttributeError, TypeError, ValueError):
        return _goal_canary_unavailable("goal_canary_artifact_session_invalid")
    if canonical_session != session_id:
        return _goal_canary_unavailable("goal_canary_artifact_session_invalid")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return _goal_canary_unavailable("goal_canary_artifact_prompt_invalid")
    prompt_raw = prompt.encode("utf-8")
    if (
        not prompt.startswith("/goal ")
        or not prompt[len("/goal ") :].strip()
        or len(prompt_raw) > MAX_GROK_GOAL_CANARY_PROMPT_BYTES
    ):
        return _goal_canary_unavailable("goal_canary_artifact_prompt_invalid")
    prompt_sha256 = payload.get("prompt_sha256")
    if (
        not isinstance(prompt_sha256, str)
        or not _SHA256_RE.fullmatch(prompt_sha256)
        or hashlib.sha256(prompt_raw).hexdigest() != prompt_sha256
    ):
        return _goal_canary_unavailable("goal_canary_artifact_prompt_digest_mismatch")
    if isinstance(payload.get("exit_code"), bool) or payload.get("exit_code") != 0:
        return _goal_canary_unavailable("goal_canary_artifact_not_successful")
    terminal = payload.get("terminal_event")
    if (
        not isinstance(terminal, Mapping)
        or terminal.get("type") != "end"
        or terminal.get("sessionId") != canonical_session
    ):
        return _goal_canary_unavailable("goal_canary_artifact_terminal_invalid")
    evidence_id = "grok-goal-canary:v1:" + hashlib.sha256(raw).hexdigest()[:24]
    return (
        GrokCapabilityEvidence(
            state="proven",
            source="validated_terminal_goal_canary_artifact",
            reason="terminal_objective_canary_validated_for_installed_build",
        ),
        evidence_id,
    )


def _contains_positive_usage(value: Any) -> bool:
    """Reject any nested positive token/usage accounting from a model-free probe."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower().replace("_", "")
            if (
                ("usage" in key_text or "token" in key_text)
                and not isinstance(child, bool)
                and isinstance(child, (int, float))
                and child > 0
            ):
                return True
            if _contains_positive_usage(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_positive_usage(child) for child in value)
    return False


def _probe_reason(result: Any | None, error: BaseException | None) -> str:
    if error is not None:
        return f"probe_error:{type(error).__name__}"
    return f"command_failed:exit_{getattr(result, 'returncode', 'unknown')}"


def probe_grok_goal_resolution(
    located: str,
    *,
    runner: Any = subprocess.run,
    auth_path: Path | None = None,
    api_key: str | None = None,
) -> tuple[GrokCapabilityEvidence, str | None]:
    """Resolve `/goal status` with narrow auth but without catalog/model inference."""
    if auth_path is None and not api_key:
        return (
            GrokCapabilityEvidence(
                state="unavailable",
                source="isolated_auth_projected_command_probe",
                reason="narrow_auth_projection_not_provided",
            ),
            None,
        )
    resolved_auth: Path | None = None
    if auth_path is not None:
        try:
            resolved_auth = auth_path.expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return (
                GrokCapabilityEvidence(
                    state="unavailable",
                    source="isolated_auth_projected_command_probe",
                    reason="narrow_auth_projection_unavailable",
                ),
                None,
            )
    with tempfile.TemporaryDirectory(prefix="elves-grok-goal-probe-") as tmp:
        root = Path(tmp)
        session_id = str(uuid.uuid4())
        env = {
            "HOME": str(root),
            "GROK_HOME": str(root / "grok"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_DATA_HOME": str(root / "data"),
            "PATH": os.environ.get("PATH") or os.defpath,
            "LANG": os.environ.get("LANG") or "C.UTF-8",
        }
        if resolved_auth is not None:
            env["GROK_AUTH_PATH"] = str(resolved_auth)
        elif api_key:
            env["XAI_API_KEY"] = api_key
        for name in ("grok", "config", "cache", "data"):
            (root / name).mkdir(mode=0o700)
        argv = [
            located,
            "--session-id",
            session_id,
            "--permission-mode",
            "plan",
            "--no-subagents",
            "--no-memory",
            "--disable-web-search",
            "--output-format",
            "streaming-json",
            "--single",
            "/goal status",
        ]
        try:
            result = runner(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
                env=env,
                cwd=tmp,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return (
                GrokCapabilityEvidence(
                    state="unavailable",
                    source="isolated_auth_projected_command_probe",
                    reason=f"probe_error:{type(exc).__name__}",
                ),
                None,
            )
    event_types: list[str] = []
    exact_session = False
    goal_status_resolved = False
    malformed = False
    positive_usage = False
    for line in (result.stdout or "").splitlines():
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            malformed = True
            continue
        if not isinstance(event, Mapping):
            malformed = True
            continue
        positive_usage = positive_usage or _contains_positive_usage(event)
        event_type = str(event.get("type") or "")
        event_types.append(event_type)
        if event_type == "text" and "No goal is currently set" in str(event.get("data") or ""):
            goal_status_resolved = True
        if event_type == "end" and event.get("sessionId") == session_id:
            exact_session = True
    inference_events = {"thought", "tool", "tool_call", "usage"}.intersection(event_types)
    if (
        getattr(result, "returncode", 1) == 0
        and goal_status_resolved
        and exact_session
        and not inference_events
        and not positive_usage
        and not malformed
    ):
        evidence_id = "isolated:/goal-status:text+end:exact-session:no-model-events"
        return (
            GrokCapabilityEvidence(
                state="proven",
                source="isolated_auth_projected_command_probe",
                reason="slash_command_resolved_without_model_events",
            ),
            evidence_id,
        )
    combined = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
    if "not signed in" in combined or "authenticate" in combined:
        reason = "authentication_required_before_command_resolution"
    elif malformed:
        reason = "malformed_streaming_probe_output"
    elif inference_events or positive_usage:
        reason = "unexpected_model_events"
    else:
        reason = f"goal_status_not_resolved:exit_{getattr(result, 'returncode', 'unknown')}"
    return (
        GrokCapabilityEvidence(
            state="unavailable",
            source="isolated_auth_projected_command_probe",
            reason=reason,
        ),
        None,
    )


def probe_grok_capabilities(
    executable: str = "grok",
    *,
    runner: Any = subprocess.run,
    goal_auth_path: Path | None = None,
    goal_api_key: str | None = None,
    command_env: Mapping[str, str] | None = None,
    goal_behavioral_evidence: str | None = None,
) -> GrokCapabilities:
    """Silently inventory Grok without launching an inference turn.

    `grok models` is the authentication/model qualification. Goal-command
    resolution and terminal behavioral proof are separate: only a validated
    exact-build canary artifact upgrades headless goal support.
    """
    located = shutil.which(executable)
    if not located:
        return GrokCapabilities(
            capability_ledger=(
                (
                    "install",
                    GrokCapabilityEvidence(
                        state="unavailable",
                        source="executable_lookup",
                        reason="executable_not_found",
                    ),
                ),
            )
        )
    common = {"check": False, "capture_output": True, "text": True, "timeout": 5}
    if command_env is not None:
        common["env"] = dict(command_env)
    results: dict[str, Any | None] = {}
    errors: dict[str, BaseException | None] = {}
    for name, argv in (
        ("version", [located, "version", "--json"]),
        ("models", [located, "models"]),
        ("help", [located, "--help"]),
        ("acp", [located, "agent", "stdio", "--help"]),
    ):
        try:
            results[name] = runner(argv, **common)
            errors[name] = None
        except (OSError, subprocess.SubprocessError) as exc:
            results[name] = None
            errors[name] = exc

    version_result = results["version"]
    models_result = results["models"]
    help_result = results["help"]
    version_text = ""
    if version_result is not None:
        version_text = (version_result.stdout or version_result.stderr or "").strip()
    version_match = re.search(r"\d+\.\d+(?:\.\d+)?", version_text)
    build_match = re.search(r"\(([0-9a-f]{7,40})\)", version_text, re.I)
    version_command_ok = bool(
        version_result is not None and getattr(version_result, "returncode", 1) == 0
    )
    if not version_command_ok:
        version_match = None
        build_match = None
    model_stdout = models_result.stdout or "" if models_result is not None else ""
    model_combined = (
        model_stdout + "\n" + (models_result.stderr or "")
        if models_result is not None
        else ""
    )
    model_lower = model_combined.lower()
    auth_failed = bool(
        re.search(
            r"not signed in|not logged in|not authenticated|unauthori[sz]ed|authentication required",
            model_lower,
        )
    )
    catalog_failed = bool(
        re.search(r"failed to fetch models|model refresh failed|settings fetch failed", model_lower)
    )
    models_command_ok = models_result is not None and getattr(models_result, "returncode", 1) == 0
    parsed_models, parsed_default = _parse_live_model_catalog(model_stdout)
    models_available = bool(
        models_command_ok
        and not auth_failed
        and not catalog_failed
        and parsed_models
        and parsed_default in parsed_models
    )
    models = parsed_models if models_available else ()
    default_model = parsed_default if models_available else None
    ledger: list[tuple[str, GrokCapabilityEvidence]] = [
        (
            "install",
            GrokCapabilityEvidence(
                state="proven",
                source="executable_lookup",
                reason="installed_binary_resolved",
            ),
        )
    ]
    if version_match:
        ledger.append(
            (
                "version",
                GrokCapabilityEvidence(
                    state="proven",
                    source="installed_binary:version_json",
                    reason="semantic_version_parsed",
                ),
            )
        )
    else:
        ledger.append(
            (
                "version",
                GrokCapabilityEvidence(
                    state="unavailable",
                    source="installed_binary:version_json",
                    reason=(
                        "version_unparseable"
                        if version_result is not None and getattr(version_result, "returncode", 1) == 0
                        else _probe_reason(version_result, errors["version"])
                    ),
                ),
            )
        )
    if models_available:
        model_reason = "authenticated_live_catalog_returned"
        auth_state = "proven"
        catalog_state = "proven"
    elif auth_failed:
        model_reason = "authentication_rejected"
        auth_state = "refuted"
        catalog_state = "unavailable"
    elif catalog_failed:
        model_reason = "live_catalog_unavailable"
        auth_state = "unavailable"
        catalog_state = "unavailable"
    else:
        model_reason = _probe_reason(models_result, errors["models"])
        auth_state = "unavailable"
        catalog_state = "unavailable"
    ledger.extend(
        (
            (
                "authentication",
                GrokCapabilityEvidence(
                    state=auth_state,
                    source="installed_binary:models",
                    reason=model_reason,
                ),
            ),
            (
                "model_catalog",
                GrokCapabilityEvidence(
                    state=catalog_state,
                    source="installed_binary:models",
                    reason=model_reason,
                ),
            ),
        )
    )
    goal_advertised = False
    help_available = help_result is not None and getattr(help_result, "returncode", 1) == 0
    help_text = ""
    if help_available:
        help_text = help_result.stdout or help_result.stderr or ""
        from .implement import detect_native_grok_goal

        goal_advertised = bool(
            detect_native_grok_goal(help_text=help_text).get(
                "advertised_headless_entrypoint"
            )
        )
    for name, marker in _GROK_HELP_CAPABILITIES:
        if help_available:
            present = marker in help_text
            ledger.append(
                (
                    name,
                    GrokCapabilityEvidence(
                        state="proven" if present else "refuted",
                        source="installed_binary:--help",
                        reason="advertised_by_help" if present else "not_advertised_by_help",
                    ),
                )
            )
        else:
            ledger.append(
                (
                    name,
                    GrokCapabilityEvidence(
                        state="unavailable",
                        source="installed_binary:--help",
                        reason=_probe_reason(help_result, errors["help"]),
                    ),
                )
            )
    help_capabilities = {name: marker in help_text for name, marker in _GROK_HELP_CAPABILITIES}
    read_only_markers = ("permission_mode", "no_subagents", "no_memory", "disable_web_search")
    ledger.append(
        (
            "read_only_controls",
            GrokCapabilityEvidence(
                state=(
                    "proven"
                    if help_available and all(help_capabilities[name] for name in read_only_markers)
                    else "refuted" if help_available else "unavailable"
                ),
                source="installed_binary:--help",
                reason=(
                    "all_read_only_controls_advertised"
                    if help_available and all(help_capabilities[name] for name in read_only_markers)
                    else "read_only_controls_incomplete"
                    if help_available
                    else _probe_reason(help_result, errors["help"])
                ),
            ),
        )
    )
    acp_result = results["acp"]
    acp_available = (
        acp_result is not None
        and getattr(acp_result, "returncode", 1) == 0
        and "agent over stdio" in ((acp_result.stdout or "") + (acp_result.stderr or "")).lower()
    )
    goal_resolution_evidence, _goal_resolution_id = probe_grok_goal_resolution(
        located,
        runner=runner,
        auth_path=goal_auth_path,
        api_key=goal_api_key,
    )
    goal_behavior_evidence, recorded_goal_evidence = (
        validate_grok_goal_canary_artifact(
            goal_behavioral_evidence,
            installed_version=version_match.group(0) if version_match else None,
            installed_build_commit=(
                build_match.group(1).lower() if build_match else None
            ),
        )
    )
    ledger.extend(
        (
            (
                "goal_command_resolution",
                goal_resolution_evidence,
            ),
            (
                "goal_behavior",
                goal_behavior_evidence,
            ),
            (
                "acp",
                GrokCapabilityEvidence(
                    state="proven" if acp_available else "unavailable",
                    source="installed_binary:agent_stdio_help",
                    reason=(
                        "agent_stdio_advertised"
                        if acp_available
                        else _probe_reason(acp_result, errors["acp"])
                    ),
                ),
            ),
        )
    )
    return GrokCapabilities(
        installed=True,
        authenticated=models_available,
        models=models,
        goal_entrypoint_advertised=goal_advertised,
        goal_mode_behaviorally_verified=bool(recorded_goal_evidence),
        goal_behavioral_evidence=recorded_goal_evidence,
        goal_behavioral_artifact_path=(
            str(goal_behavioral_evidence).strip()
            if recorded_goal_evidence and goal_behavioral_evidence
            else None
        ),
        version=version_match.group(0) if version_match else None,
        installed_build_commit=build_match.group(1).lower() if build_match else None,
        default_model=default_model,
        capability_ledger=tuple(ledger),
    )


def grok_prewalk_unqualified_reason(
    qualification: PrewalkCapabilities | None,
) -> str | None:
    """Concrete reason grok prewalk is unqualified, or None for valid evidence.

    This is the B3 seam: Batch 2 ships the qualification-based gate without
    any qualification tooling, so no caller can produce a valid grok prewalk
    qualification and every default environment reports a concrete
    unqualified reason (prewalk actual mode stays ``off``). Batch 3 plugs in
    the artifact loader by validating its bounded qualification artifact into
    a ``PrewalkCapabilities`` and passing it here; the gate itself does not
    change shape.
    """
    if qualification is None:
        return "qualification_artifact_missing"
    if not isinstance(qualification, PrewalkCapabilities):
        return "qualification_artifact_invalid"
    if qualification.host != "grok" or qualification.transport != "grok_build":
        return "qualification_host_mismatch"
    # Deterministic fixtures bypass route matching inside PrewalkCapabilities;
    # that convenience is for native-host tests and must never qualify grok.
    if qualification.evidence_source == "deterministic_fixture":
        return "qualification_fixture_evidence_forbidden"
    if not qualification.qualified():
        return qualification.unavailable_reason() or "qualification_incomplete"
    return None


@dataclass(frozen=True)
class RouteDecision:
    provider: str
    worker_transport: str
    worker_model_policy: str
    worker_model: str | None
    worker_effort: str
    execution_reasoning: str
    review_risk: str
    provenance: dict[str, str]
    fallback: dict[str, str] | None
    advisory_driver_upgrade: str | None
    goal_mode: bool
    reasons: tuple[str, ...]
    prewalk: PrewalkRoutePair | None = None
    model_calls_made: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["prewalk"] = self.prewalk.to_dict() if self.prewalk else None
        return payload


def _choice(layers: tuple[tuple[str, Mapping[str, Any] | None], ...], key: str, default: Any) -> tuple[Any, str]:
    for source, layer in layers:
        if layer is not None and key in layer and layer[key] is not None:
            return layer[key], source
    return default, "built_in_default"


def discover_repository_worker_policy(
    repo_root: Path, *, override_path: Path | None = None
) -> tuple[dict[str, Any], str]:
    """Discover target-repository worker defaults/vetoes from established config files."""
    candidates = [override_path] if override_path else [repo_root / "config.json", repo_root / ".elves" / "models.toml"]
    merged: dict[str, Any] = {}
    sources: list[str] = []
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        data = load_toml_file(candidate) if candidate.suffix == ".toml" else load_json_file(candidate)
        worker = data.get("worker", {}) if isinstance(data, Mapping) else {}
        if not isinstance(worker, Mapping):
            raise ValidationIssue("invalid_route_policy", "Repository `worker` policy must be an object", path=str(candidate))
        merged.update(worker)
        sources.append(str(candidate.resolve()))
    return ({"worker": merged} if merged else {}), (" > ".join(sources) if sources else "none")


def decide_worker_route(
    *,
    host: str,
    execution_reasoning: str,
    review_risk: str,
    global_preferences: Mapping[str, Any] | None = None,
    explicit_intent: Mapping[str, Any] | None = None,
    repo_policy: Mapping[str, Any] | None = None,
    grok: GrokCapabilities | None = None,
    driver_effort: str | None = None,
    prewalk_capabilities: PrewalkCapabilities | None = None,
    grok_prewalk_qualification: PrewalkCapabilities | None = None,
) -> RouteDecision:
    """Return an inspectable route. Repository policy is the final safety veto."""
    host_token = host.strip().lower().replace("_", "-")
    if host_token not in {"codex", "claude", "claude-code", "grok", "omp", "oh-my-pi"}:
        raise ValidationIssue("unsupported_host", f"Unsupported host `{host}`", path="host")
    execution = execution_reasoning.strip().lower()
    risk = review_risk.strip().lower()
    accepted_efforts = supported_efforts_for_host(host_token)
    if execution not in accepted_efforts:
        raise ValidationIssue("invalid_execution_reasoning", f"Unknown execution reasoning `{execution}`")
    if risk not in REVIEW_RISKS:
        raise ValidationIssue("invalid_review_risk", f"Unknown review risk `{risk}`")

    global_worker = (global_preferences or {}).get("worker", {})
    if not isinstance(global_worker, Mapping):
        global_worker = {}
    explicit_worker = (explicit_intent or {}).get("worker", explicit_intent or {})
    repo_worker = (repo_policy or {}).get("worker", repo_policy or {})
    if not isinstance(explicit_worker, Mapping) or not isinstance(repo_worker, Mapping):
        raise ValidationIssue("invalid_route_policy", "Worker intent/policy must be objects")

    provider, provider_source = _choice(
        (
            ("explicit_run_intent", explicit_worker),
            ("repository_default", repo_worker),
            ("global_preferences", global_worker),
        ),
        "provider",
        "auto",
    )
    effort, effort_source = _choice(
        (
            ("explicit_run_intent", explicit_worker),
            ("repository_default", repo_worker),
            ("global_preferences", global_worker),
        ),
        "native_effort",
        "auto",
    )
    prewalk_value, prewalk_source = _choice(
        (
            ("explicit_run_intent", explicit_worker),
            ("repository_default", repo_worker),
            ("global_preferences", global_worker),
        ),
        "prewalk",
        "auto",
    )
    guide_effort_value, guide_effort_source = _choice(
        (
            ("explicit_run_intent", explicit_worker),
            ("repository_default", repo_worker),
            ("global_preferences", global_worker),
        ),
        "prewalk_guide_effort",
        "high",
    )
    guide_model_value, guide_model_source = _choice(
        (
            ("explicit_run_intent", explicit_worker),
            ("repository_default", repo_worker),
            ("global_preferences", global_worker),
        ),
        "prewalk_guide_model",
        None,
    )
    provider = str(provider).lower()
    effort_is_auto = effort == "auto"
    effort = execution if effort_is_auto else str(effort).lower()
    if provider not in {"auto", "native", "grok"}:
        raise ValidationIssue("invalid_provider_preference", f"Unknown worker provider `{provider}`")
    if effort not in accepted_efforts:
        raise ValidationIssue("invalid_worker_effort", f"Unknown worker effort `{effort}`")
    prewalk_token = str(prewalk_value).lower()
    if prewalk_token not in {mode.value for mode in PrewalkMode}:
        raise ValidationIssue("invalid_prewalk_mode", f"Unknown prewalk mode `{prewalk_value}`")
    guide_effort = str(guide_effort_value).lower()
    if guide_effort not in accepted_efforts:
        raise ValidationIssue("invalid_worker_effort", f"Unknown guide effort `{guide_effort}`")

    grok_info = grok or GrokCapabilities()
    prohibited = repo_worker.get("allow_grok") is False
    consent_source = "none"
    if explicit_worker.get("provider") == "grok":
        consent_source = "explicit_run_provider"
    elif explicit_worker.get("allow_grok") is True:
        consent_source = "explicit_run_allow_grok"
    elif global_worker.get("provider") == "grok":
        consent_source = "global_provider_preference"
    permitted = consent_source != "none"
    requested_grok_model, requested_grok_model_source = _choice(
        (
            ("explicit_run_intent", explicit_worker),
            ("repository_default", repo_worker),
            ("global_preferences", global_worker),
        ),
        "grok_model",
        None,
    )
    reasons: list[str] = []
    fallback: dict[str, str] | None = None

    wants_grok = provider == "grok" or (provider == "auto" and permitted)
    selected_provider = "native"
    selected_model: str | None = None
    model_policy = "inherit_live_driver_model"
    goal_mode = False
    if wants_grok:
        if prohibited:
            fallback = {"requested": "grok", "actual": "native", "reason": "repository_policy_prohibits_grok"}
        elif not permitted:
            fallback = {"requested": "grok", "actual": "native", "reason": "grok_not_explicitly_permitted"}
        else:
            requested_for_select = (
                str(requested_grok_model).strip()
                if requested_grok_model is not None
                else None
            )
            # "auto" is a prepare-time placeholder, not a live model id. An
            # explicit worker.grok_model pin of "auto" is never a catalog member.
            if requested_for_select == "auto":
                candidate = None
                model_policy = "auto_placeholder"
            else:
                # Explicit user pin against the live catalog (fail-closed if absent).
                pinned, pin_policy = resolve_user_specified_worker_model(
                    requested_model=requested_for_select,
                    live_catalog=list(grok_info.models),
                )
                if requested_for_select:
                    candidate = pinned
                    model_policy = pin_policy
                else:
                    candidate = select_preferred_grok_worker_model(
                        grok_info, requested=None
                    )
                    model_policy = (
                        "preferred_grok_worker_model"
                        if candidate == GROK_WORKER_MODEL
                        else "authenticated_live_catalog_default"
                    )
            goal_qualified = bool(
                grok_info.goal_mode_behaviorally_verified
                and grok_info.goal_behavioral_evidence
            )
            core_unavailable = grok_info.core_launch_unavailable_reason()
            if candidate and not core_unavailable:
                selected_provider = "grok"
                selected_model = candidate
                if requested_grok_model is not None and model_policy.startswith(
                    "explicit"
                ):
                    pass  # keep pin_policy
                elif candidate == GROK_WORKER_MODEL and not requested_for_select:
                    model_policy = "preferred_grok_worker_model"
                elif not requested_for_select:
                    model_policy = "authenticated_live_catalog_default"
                goal_mode = goal_qualified
                reasons.append("permitted_grok_capability_matches_plan")
                if not goal_qualified:
                    fallback = {
                        "requested": "grok_goal",
                        "actual": "grok_packet_prompt",
                        "reason": "goal_mode_not_behaviorally_verified",
                    }
                    reasons.append("compatible_one_packet_fallback")
            else:
                if not (grok_info.installed and grok_info.authenticated):
                    missing = "unavailable_or_unauthenticated"
                elif (
                    requested_for_select == GROK_RETIRED_COMPOSER_MODEL
                    or (
                        not requested_for_select
                        and grok_info.default_model == GROK_RETIRED_COMPOSER_MODEL
                        and not grok_info.supports(GROK_WORKER_MODEL)
                    )
                ):
                    missing = f"model_retired:{GROK_RETIRED_COMPOSER_MODEL}"
                elif requested_for_select and not candidate:
                    missing = f"model_unavailable:{requested_for_select}"
                elif not candidate:
                    missing = "live_default_model_unavailable"
                elif core_unavailable:
                    missing = core_unavailable
                else:
                    missing = "grok_provider_unqualified"
                fallback = {"requested": "grok", "actual": "native", "reason": missing}

    if selected_provider == "grok" and effort_is_auto:
        # Grok is a cross-family handoff, not a cheaper same-model execution
        # phase. Use the provider's highest supported reasoning level unless
        # the operator explicitly requested another effort.
        effort = "high"

    if selected_provider == "native":
        reasons.append("subscription_native_default")
    if fallback:
        reasons.append(f"honest_fallback:{fallback['reason']}")

    advisory = None
    if risk == "high" and driver_effort in {"low", "medium"}:
        advisory = "consider_high_effort_driver_for_terminal_review"

    requested_prewalk = PrewalkMode(prewalk_token)
    caps = prewalk_capabilities or PrewalkCapabilities(
        host=host_token,
        transport=transport_for_host(host_token),
    )
    prewalk_transport = (
        transport_for_host("grok")
        if selected_provider == "grok"
        else transport_for_host(host_token)
    )
    guide_model = str(guide_model_value).strip() if guide_model_value else None
    guide_policy = "explicit_guide_model_pin" if guide_model else "inherit_live_driver_model"
    actual_prewalk = "off"
    prewalk_fallback: str | None = None
    if requested_prewalk is not PrewalkMode.OFF:
        if selected_provider != "native":
            # Qualification-based gating (never a categorical veto): a grok
            # prewalk request activates only on a valid behavioral
            # qualification whose routes match. The absolute `allow_grok`
            # veto and consent rules were already applied before any
            # evidence was consulted, so an unpermitted or vetoed request
            # never reaches this arm. Without Batch 3 qualification tooling
            # every request reports the concrete unqualified fallback.
            # The reported capability fields must describe grok evidence:
            # native-host capabilities never appear under grok transports.
            caps = (
                grok_prewalk_qualification
                if isinstance(grok_prewalk_qualification, PrewalkCapabilities)
                and grok_prewalk_qualification.host == "grok"
                and grok_prewalk_qualification.transport == "grok_build"
                else PrewalkCapabilities(
                    host="grok", transport=transport_for_host("grok")
                )
            )
            unqualified = grok_prewalk_unqualified_reason(grok_prewalk_qualification)
            if unqualified is None and grok_prewalk_qualification is not None:
                caps = grok_prewalk_qualification
                if caps.route_matches(
                    guide_model=guide_model,
                    guide_effort=guide_effort,
                    execution_model=selected_model,
                    execution_effort=effort,
                ):
                    actual_prewalk = "exact_session"
                    reasons.append("trajectory_preserving_prewalk_qualified")
                else:
                    prewalk_fallback = (
                        "prewalk_capability_unavailable:grok_prewalk_unqualified:"
                        "qualification_route_mismatch"
                    )
            else:
                if requested_prewalk is PrewalkMode.REQUIRED:
                    actual_prewalk = "qualification_required"
                    reasons.append("prewalk_live_qualification_required")
                elif requested_prewalk is PrewalkMode.EXPERIMENTAL:
                    actual_prewalk = "qualification_required"
                    reasons.append("prewalk_experimental_advertised_probe_required")
                else:
                    prewalk_fallback = (
                        "prewalk_capability_unavailable:grok_prewalk_unqualified:"
                        f"{unqualified}"
                    )
        elif requested_prewalk is PrewalkMode.AUTO and execution == "low":
            prewalk_fallback = "prewalk_atomic_task_skipped"
        elif caps.qualified() and caps.route_matches(
            guide_model=guide_model,
            guide_effort=guide_effort,
            execution_model=selected_model,
            execution_effort=effort,
        ):
            actual_prewalk = "exact_session"
            reasons.append("trajectory_preserving_prewalk_qualified")
        elif requested_prewalk is PrewalkMode.EXPERIMENTAL:
            if caps.experimental_eligible():
                actual_prewalk = "exact_session_experimental"
                reasons.append("explicit_experimental_prewalk")
            else:
                actual_prewalk = "qualification_required"
                reasons.append("prewalk_experimental_advertised_probe_required")
        elif requested_prewalk is PrewalkMode.REQUIRED:
            actual_prewalk = "qualification_required"
            reasons.append("prewalk_live_qualification_required")
        elif caps.qualified():
            prewalk_fallback = "prewalk_route_change_unqualified"
        else:
            prewalk_fallback = caps.unavailable_reason() or "prewalk_capability_unavailable"
    if prewalk_fallback:
        reasons.append(f"honest_prewalk_fallback:{prewalk_fallback}")
    capability_state = (
        PrewalkCapabilityState.QUALIFIED
        if caps.qualified()
        else PrewalkCapabilityState.ADVERTISED
        if caps.advertised_exact_resume or caps.advertised_route_override_on_resume
        else PrewalkCapabilityState.UNAVAILABLE
    )
    try:
        fidelity = PrewalkInstructionFidelity(caps.instruction_fidelity)
    except ValueError:
        fidelity = PrewalkInstructionFidelity.UNSUPPORTED
    prewalk_route = PrewalkRoutePair(
        requested_mode=requested_prewalk,
        actual_mode=actual_prewalk,
        guide=NativeWorkerPhaseRoute(
            role=NativeWorkerPhaseRole.GUIDE,
            transport=prewalk_transport,
            model_policy=guide_policy,
            model=guide_model,
            effort=guide_effort,
        ),
        execution=NativeWorkerPhaseRoute(
            role=NativeWorkerPhaseRole.EXECUTION,
            transport=prewalk_transport,
            model_policy=model_policy,
            model=selected_model,
            effort=effort,
        ),
        capability_state=capability_state,
        advertised_exact_resume=caps.advertised_exact_resume,
        advertised_route_override_on_resume=caps.advertised_route_override_on_resume,
        behaviorally_verified_session_continuity=caps.behaviorally_verified_session_continuity,
        behaviorally_verified_instruction_pruning=caps.behaviorally_verified_instruction_pruning,
        worktree_binding_verified=caps.worktree_binding_verified,
        stream_identity_verified=caps.stream_identity_verified,
        instruction_fidelity=fidelity,
        fallback_reason=prewalk_fallback,
        qualification_model_calls_made=caps.model_calls_made,
    )

    return RouteDecision(
        provider=selected_provider,
        worker_transport=(
            transport_for_host(host_token)
            if selected_provider == "native"
            else transport_for_host("grok")
        ),
        worker_model_policy=model_policy,
        worker_model=selected_model,
        worker_effort=effort,
        execution_reasoning=execution,
        review_risk=risk,
        provenance={
            "provider": provider_source,
            "worker_effort": (
                "grok_highest_supported_default"
                if effort_is_auto and selected_provider == "grok"
                else "plan_execution_reasoning"
                if effort_is_auto
                else effort_source
            ),
            "prewalk": prewalk_source,
            "prewalk_guide_effort": guide_effort_source,
            "prewalk_guide_model": guide_model_source,
            "grok_consent": consent_source,
            "grok_safety_veto": "repository_policy" if prohibited else "none",
            "grok_goal_evidence": (
                "validated_terminal_goal_canary_artifact"
                if grok_info.goal_mode_behaviorally_verified
                and grok_info.goal_behavioral_evidence
                else "none"
            ),
            "grok_model": (
                requested_grok_model_source
                if requested_grok_model is not None
                else "authenticated_live_catalog_default"
            ),
        },
        fallback=fallback,
        advisory_driver_upgrade=advisory,
        goal_mode=goal_mode,
        reasons=tuple(reasons),
        prewalk=prewalk_route,
    )
