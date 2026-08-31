"""Adapter protocol, version-aware command builders, and transport decoders.

Command construction and transport decoding live here — not in the dispatcher.
Model-authored report text never certifies transport identity. Built-in CLI
contracts match Claude Code 2.1.207, Grok Build 0.2.93, and Codex 0.144.1 help.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .context import ROLE_REPORT_SCHEMA_FIELDS
from .executables import resolve_executable, resolve_executable_for_launch
from .schema import (
    AMBIGUOUS_SESSION_TOKENS,
    BUILTIN_ADAPTER_NAMES,
    HarnessProfile,
    NATIVE_PROFILE_NAME,
    ValidationIssue,
)


class Adapter(Protocol):
    """Minimal adapter surface for dispatch/session batches."""

    name: str

    def describe(self) -> dict[str, object]:
        """Return a stable machine-readable description."""


@dataclass(frozen=True)
class StubAdapter:
    """Built-in adapter metadata with no side effects."""

    name: str
    executable_hint: str
    supports_persistent_sessions: bool = False
    supports_isolated_write: bool = False

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "executable_hint": self.executable_hint,
            "supports_persistent_sessions": self.supports_persistent_sessions,
            "supports_isolated_write": self.supports_isolated_write,
            "status": "readonly-builder",
            "note": "Read-only command builders available; write leases land later",
        }


@dataclass(frozen=True)
class AdapterInvocation:
    """Argv-safe read-only invocation (never a shell string)."""

    adapter: str
    executable: str
    argv: tuple[str, ...]
    read_only: bool = True
    tool_scope: str = "read-only"
    sandbox_scope: str = "ephemeral"
    notes: str = ""
    stdin_text: str | None = None
    input_mode: str = "none"  # none | stdin | prompt-file | json-stdio
    decoder: str = "none"
    unavailable: bool = False
    unavailable_reason: str = ""
    cwd: str | None = None
    prompt_file_body: str | None = None  # full body when writing prompt-file
    session_id: str | None = None  # exact external chat id when resume/create known

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "executable": self.executable,
            "argv": list(self.argv),
            "read_only": self.read_only,
            "tool_scope": self.tool_scope,
            "sandbox_scope": self.sandbox_scope,
            "notes": self.notes,
            "input_mode": self.input_mode,
            "decoder": self.decoder,
            "unavailable": self.unavailable,
            "unavailable_reason": self.unavailable_reason,
            "cwd": self.cwd,
            "has_stdin": bool(self.stdin_text),
            "session_id": self.session_id,
            "argv_digest": hashlib.sha256("\0".join(self.argv).encode()).hexdigest()[:16],
        }


@dataclass(frozen=True)
class TransportDecodeResult:
    """Decoded transport evidence separate from model-authored report body."""

    role_report: dict[str, Any]
    actual_model: str | None
    model_evidence_source: str | None
    session_id: str | None = None
    transport_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_report": dict(self.role_report),
            "actual_model": self.actual_model,
            "model_evidence_source": self.model_evidence_source,
            "session_id": self.session_id,
            "transport_notes": list(self.transport_notes),
        }


_BUILTIN: dict[str, StubAdapter] = {
    "host-native": StubAdapter(
        name="host-native",
        executable_hint="python3",
        supports_persistent_sessions=False,
        supports_isolated_write=True,
    ),
    "claude-code": StubAdapter(
        name="claude-code",
        executable_hint="claude",
        supports_persistent_sessions=True,
        supports_isolated_write=True,
    ),
    "grok-build": StubAdapter(
        name="grok-build",
        executable_hint="grok",
        supports_persistent_sessions=True,
        supports_isolated_write=True,
    ),
    "codex-fugu": StubAdapter(
        name="codex-fugu",
        executable_hint="codex-fugu",
        supports_persistent_sessions=True,
        supports_isolated_write=False,
    ),
    "gemini-cli": StubAdapter(
        name="gemini-cli",
        executable_hint="gemini",
        # Exact --session-id create / --resume <uuid> only (never latest/continue).
        supports_persistent_sessions=True,
        # API-key Gemini CLI is a plan/review lens; not an isolated write implementer.
        supports_isolated_write=False,
    ),
    "antigravity-cli": StubAdapter(
        name="antigravity-cli",
        # Prefer binary name `agy` (Antigravity CLI); `antigravity` is a fallback alias.
        executable_hint="agy",
        # Exact --conversation <id> only (never bare --continue).
        supports_persistent_sessions=True,
        # Not host-import write-lease qualified. Experimental labor is host-launched
        # headless `agy -p` with model pin (e.g. Gemini 3.5 Flash), not Lane A/Grok.
        supports_isolated_write=False,
    ),
    "opencode-cli": StubAdapter(
        name="opencode-cli",
        executable_hint="opencode",
        # Exact --session <id> only (never bare --continue / -c).
        supports_persistent_sessions=True,
        # Terminal coding agent (Claude Code–like) with OpenRouter and other providers.
        # Not host-import write-lease qualified; experimental implement via opencode run --auto.
        supports_isolated_write=False,
    ),
    "devin-cli": StubAdapter(
        name="devin-cli",
        executable_hint="devin",
        # Exact --resume <id> only (never bare --continue / -c or latest).
        supports_persistent_sessions=True,
        # Full-run capable isolated write implementer; host captures provider session id.
        supports_isolated_write=True,
    ),
    "omp-cli": StubAdapter(
        name="omp-cli",
        executable_hint="omp",
        # Exact --resume <uuid> only (never --continue / -c / latest).
        supports_persistent_sessions=True,
        # Full-run capable isolated write implementer; host captures session from NDJSON.
        supports_isolated_write=True,
    ),
    "custom-cli": StubAdapter(
        name="custom-cli",
        executable_hint="(user-defined)",
        supports_persistent_sessions=False,
        supports_isolated_write=False,
    ),
}

FORBIDDEN_INVENTED_FLAGS: frozenset[str] = frozenset(
    {
        "--packet",
        "--readonly",
    }
)

# Reserved control options that profile extra_args may not override.
_RESERVED_CONTROL_FLAGS: dict[str, frozenset[str]] = {
    "claude-code": frozenset(
        {
            "--print",
            "-p",
            "--output-format",
            "--permission-mode",
            "--model",
            "--json-schema",
            "--no-session-persistence",
            "--dangerously-skip-permissions",
            "--allow-dangerously-skip-permissions",
            "--cwd",
            "--resume",
            "--session-id",
            "--input-format",
        }
    ),
    "grok-build": frozenset(
        {
            "--prompt-file",
            "--prompt-json",
            "--output-format",
            "--json-schema",
            "--model",
            "-m",
            "--permission-mode",
            "--sandbox",
            "--cwd",
            "--resume",
            "--session-id",
            "--always-approve",
            "--no-subagents",
            "--no-memory",
            "--disable-web-search",
        }
    ),
    "codex-fugu": frozenset(
        {
            "--json",
            "--sandbox",
            "-s",
            "--model",
            "-m",
            "--cd",
            "-C",
            "--config",
            "-c",
            "--dangerously-bypass-approvals-and-sandbox",
            "-",
        }
    ),
    "gemini-cli": frozenset(
        {
            "-p",
            "--prompt",
            "-i",
            "--prompt-interactive",
            "-m",
            "--model",
            "-o",
            "--output-format",
            "--skip-trust",
            "--approval-mode",
            "-y",
            "--yolo",
            "--acp",
            "--experimental-acp",
            "--session-id",
            "--session-file",
            "-r",
            "--resume",
        }
    ),
    "antigravity-cli": frozenset(
        {
            "-p",
            "--print",
            "--prompt",
            "-i",
            "--prompt-interactive",
            "--model",
            "--mode",
            "--sandbox",
            "--dangerously-skip-permissions",
            "--conversation",
            "--continue",
            "--config",
            "--project",
            "--new-project",
            "--agent",
            "--add-dir",
            "--print-timeout",
        }
    ),
    "opencode-cli": frozenset(
        {
            "run",
            "-m",
            "--model",
            "-s",
            "--session",
            "--config",
            "--continue",
            "--fork",
            "--agent",
            "--format",
            "-f",
            "--file",
            "--title",
            "--attach",
            "--dir",
            "--auto",
            "--variant",
            "--thinking",
            "-i",
            "--interactive",
            "--prompt",
        }
    ),
    "devin-cli": frozenset(
        {
            "-m",
            "--model",
            "--permission-mode",
            "-c",
            "--continue",
            "-r",
            "--resume",
            "-p",
            "--print",
            "--prompt-file",
            "--export",
            "--config",
            "--sandbox",
            "--respect-workspace-trust",
        }
    ),
    "omp-cli": frozenset(
        {
            "--mode",
            "--model",
            "--thinking",
            "--approval-mode",
            "--auto-approve",
            "--cwd",
            "--profile",
            "--session-dir",
            "--resume",
            "-r",
            "--continue",
            "-c",
            "--print",
            "-p",
            "--prewalk",
            "--no-session",
        }
    ),
    "custom-cli": frozenset(),
}

ALLOWED_INPUT_CONTRACTS: frozenset[str] = frozenset(
    {
        "stdin",
        "prompt-file",
        "json-stdio",
        "none",
        "host-injected",
    }
)
ALLOWED_OUTPUT_CONTRACTS: frozenset[str] = frozenset(
    {
        "claude-json",
        "grok-json",
        "codex-jsonl",
        "omp-jsonl",
        "custom-json-envelope",
        "host-injected",
        "json-role-report",  # legacy alias -> custom envelope for wrappers
        "none",
    }
)

ALLOWED_VERDICTS: frozenset[str] = frozenset(
    {"pass", "fail", "warn", "abstain", "info", "blocked"}
)
CONFIDENCE_ALIASES: dict[str, float] = {
    "high": 0.9,
    "medium": 0.6,
    "low": 0.3,
    "blocked": 0.0,
    "reduced": 0.45,
}


def builtin_adapter_names() -> tuple[str, ...]:
    return BUILTIN_ADAPTER_NAMES


def get_adapter(name: str) -> StubAdapter:
    """Return the built-in adapter. Never silently remaps known names to custom-cli."""
    key = (name or "").strip().lower()
    adapter = _BUILTIN.get(key)
    if adapter is None:
        raise ValidationIssue(
            "unknown_adapter",
            f"Unknown adapter `{name}`",
            path=f"adapters.{name}",
            hint=f"Built-in adapters: {', '.join(BUILTIN_ADAPTER_NAMES)}",
        )
    return adapter


def resolve_adapter_name(name: str, *, executable: str | None = None) -> str:
    """Map a requested adapter name to a registry identity.

    Built-in adapters always keep their canonical names and contracts. Only
    truly unknown names with an explicit executable may fall through to
    ``custom-cli``.
    """
    key = (name or "").strip().lower()
    if not key:
        raise ValidationIssue(
            "unknown_adapter",
            "Adapter name is required",
            path="adapters",
            hint=f"Built-in adapters: {', '.join(BUILTIN_ADAPTER_NAMES)}",
        )
    if key in _BUILTIN:
        return key
    if key == "custom-cli":
        return "custom-cli"
    if executable:
        return "custom-cli"
    raise ValidationIssue(
        "unknown_adapter",
        f"Unknown adapter `{name}` and no executable provided",
        path=f"adapters.{name}",
        hint=f"Built-in adapters: {', '.join(BUILTIN_ADAPTER_NAMES)}",
    )


def _validate_fugu_launch_controls(
    name: str,
    *,
    executable: str | None,
    requested_model: str | None,
    extra_args: Sequence[str],
) -> None:
    executable_name = Path(executable).name if executable else ""
    if name != "codex-fugu":
        if executable_name == "codex-fugu":
            raise ValidationIssue(
                "reserved_fugu_executable",
                "The codex-fugu executable is reserved for the codex-fugu adapter",
                path=f"adapters.{name}.executable",
            )
        return
    if executable and executable_name != "codex-fugu":
        raise ValidationIssue(
            "invalid_fugu_executable",
            "The codex-fugu adapter must use the codex-fugu executable",
            path="adapters.codex-fugu.executable",
        )
    if requested_model not in {None, "", "fugu"}:
        raise ValidationIssue(
            "invalid_fugu_model_override",
            "Cobbler Fugu profiles are pinned to regular fugu/high",
            path="adapters.codex-fugu.requested_model",
            hint="Use the audited provider shortcut for an explicit non-default Fugu profile",
        )
    if extra_args:
        raise ValidationIssue(
            "invalid_fugu_extra_args",
            "Cobbler Fugu profiles do not accept extra arguments",
            path="adapters.codex-fugu.extra_args",
            hint="Use the audited provider shortcut for explicit Fugu controls",
        )


def adapter_contract_pair(name: str) -> tuple[str, str]:
    """Canonical input/output contract pair for a built-in or custom adapter."""
    key = (name or "").strip().lower()
    if key not in _BUILTIN and key != "custom-cli":
        key = "custom-cli"
    return ADAPTER_CONTRACT_PAIRS.get(key, ("json-stdio", "custom-json-envelope"))


def default_profiles() -> dict[str, HarnessProfile]:
    """Return built-in profiles without personal model defaults."""
    profiles: dict[str, HarnessProfile] = {}
    for name, adapter in _BUILTIN.items():
        if name == "claude-code":
            input_c, output_c = "stdin", "claude-json"
        elif name == "grok-build":
            input_c, output_c = "prompt-file", "grok-json"
        elif name == "codex-fugu":
            input_c, output_c = "stdin", "codex-jsonl"
        elif name in {"gemini-cli", "antigravity-cli", "opencode-cli"}:
            input_c, output_c = "none", "custom-json-envelope"
        elif name == "devin-cli":
            input_c, output_c = "prompt-file", "custom-json-envelope"
        elif name == "omp-cli":
            input_c, output_c = "none", "omp-jsonl"
        elif name == "custom-cli":
            input_c, output_c = "json-stdio", "custom-json-envelope"
        else:
            input_c, output_c = "host-injected", "host-injected"
        profiles[name] = HarnessProfile(
            name=name,
            adapter=adapter.name,
            executable=None if name == NATIVE_PROFILE_NAME else adapter.executable_hint,
            notes=f"Built-in {adapter.name} profile",
            input_contract=input_c,
            output_contract=output_c,
        )
    return profiles


def registry_snapshot() -> dict[str, dict[str, object]]:
    return {name: adapter.describe() for name, adapter in sorted(_BUILTIN.items())}


def default_decoder_for_adapter(adapter: str) -> str:
    name = adapter.strip().lower()
    return {
        "claude-code": "claude-json",
        "grok-build": "grok-json",
        "codex-fugu": "codex-jsonl",
        "devin-cli": "custom-json-envelope",
        "omp-cli": "omp-jsonl",
        "custom-cli": "custom-json-envelope",
        "host-native": "host-injected",
    }.get(name, "custom-json-envelope")


def compose_full_prompt(*, packet: Mapping[str, Any], task: str, role: str) -> str:
    """Full task + redacted packet for prompt-file / stdin (never a fragment)."""
    packet_json = json.dumps(dict(packet), indent=2, sort_keys=True)
    return (
        f"Role: {role}\n"
        f"Task:\n{task}\n\n"
        f"--- context packet (JSON) ---\n"
        f"{packet_json}\n"
        f"--- end context packet ---\n"
        f"Return a structured role report for the requested transport contract.\n"
    )


def _normalize_flag_token(token: str) -> str:
    if token.startswith("--") and "=" in token:
        return token.split("=", 1)[0]
    return token


def validate_extra_args(
    adapter: str,
    extra_args: Sequence[str],
) -> None:
    """Fail when extra_args attempt to override reserved control options."""
    reserved = _RESERVED_CONTROL_FLAGS.get(adapter.strip().lower(), frozenset())
    if not reserved and not extra_args:
        return
    seen: set[str] = set()
    for raw in extra_args:
        token = _normalize_flag_token(str(raw))
        if not token.startswith("-"):
            continue
        if token in reserved or token in FORBIDDEN_INVENTED_FLAGS:
            raise ValidationIssue(
                "unsafe_extra_args",
                f"extra_args may not override reserved control option `{token}` for `{adapter}`",
                path=f"adapters.{adapter}.extra_args",
                hint="Remove the override or use an ordered fallback profile",
            )
        if token in seen:
            raise ValidationIssue(
                "duplicate_extra_args",
                f"Duplicate extra_args flag `{token}` for `{adapter}`",
                path=f"adapters.{adapter}.extra_args",
            )
        seen.add(token)


# Built-in adapters accept only their supported IO pair (not any global enum value).
ADAPTER_CONTRACT_PAIRS: dict[str, tuple[str, str]] = {
    "claude-code": ("stdin", "claude-json"),
    "grok-build": ("prompt-file", "grok-json"),
    "codex-fugu": ("stdin", "codex-jsonl"),
    # Google CLIs: prompt via -p/--print (not bare stdin). stdout is freeform text that
    # should contain a JSON role report (fenced JSON ok); decode as custom envelope.
    "gemini-cli": ("none", "custom-json-envelope"),
    "antigravity-cli": ("none", "custom-json-envelope"),
    "opencode-cli": ("none", "custom-json-envelope"),
    "devin-cli": ("prompt-file", "custom-json-envelope"),
    "omp-cli": ("none", "omp-jsonl"),
    "custom-cli": ("json-stdio", "custom-json-envelope"),
    "host-native": ("host-injected", "host-injected"),
}


def validate_contracts(*, input_contract: str, output_contract: str) -> None:
    ic = (input_contract or "").strip()
    oc = (output_contract or "").strip()
    if ic not in ALLOWED_INPUT_CONTRACTS:
        raise ValidationIssue(
            "unsupported_input_contract",
            f"Unsupported input_contract `{ic}`",
            hint=f"Allowed: {', '.join(sorted(ALLOWED_INPUT_CONTRACTS))}",
        )
    if oc not in ALLOWED_OUTPUT_CONTRACTS:
        raise ValidationIssue(
            "unsupported_output_contract",
            f"Unsupported output_contract `{oc}`",
            hint=f"Allowed: {', '.join(sorted(ALLOWED_OUTPUT_CONTRACTS))}",
        )


def validate_adapter_contract_pair(
    adapter: str,
    *,
    input_contract: str,
    output_contract: str,
) -> tuple[str, str]:
    """Require the supported pair for built-ins; fail incompatible declarations."""
    name = adapter.strip().lower()
    ic = (input_contract or "").strip()
    oc = (output_contract or "").strip()
    if oc == "json-role-report":
        oc = "custom-json-envelope"
    validate_contracts(input_contract=ic, output_contract=oc)
    expected = ADAPTER_CONTRACT_PAIRS.get(name)
    if expected is not None and (ic, oc) != expected:
        raise ValidationIssue(
            "incompatible_adapter_contract",
            (
                f"Adapter `{name}` requires input/output contract "
                f"{expected[0]}/{expected[1]}, got {ic}/{oc}"
            ),
            path=f"adapters.{name}.contracts",
        )
    return ic, oc


# Canonical set lives in schema.AMBIGUOUS_SESSION_TOKENS; keep the historical
# module-level alias for existing importers.
_AMBIGUOUS_SESSION_TOKENS: frozenset[str] = AMBIGUOUS_SESSION_TOKENS


def assert_exact_session_id(session_id: str, *, adapter: str = "") -> str:
    """Require a concrete session/conversation id — never latest/continue/last."""
    sid = (session_id or "").strip()
    if not sid:
        raise ValidationIssue(
            "missing_session_id",
            "Exact session_id is required",
            path=f"adapters.{adapter or 'session'}.session_id",
            hint="Use a concrete UUID/conversation id from the registry — never latest/continue",
        )
    if sid.lower() in _AMBIGUOUS_SESSION_TOKENS:
        raise ValidationIssue(
            "ambiguous_session_id",
            f"Session id `{sid}` is ambiguous and forbidden",
            path=f"adapters.{adapter or 'session'}.session_id",
            hint="Pass the exact UUID/conversation id recorded at create time",
        )
    if sid.startswith("-"):
        raise ValidationIssue(
            "ambiguous_session_id",
            f"Session id `{sid}` looks like a flag, not an id",
            path=f"adapters.{adapter or 'session'}.session_id",
        )
    return sid


def build_readonly_invocation(
    *,
    adapter: str,
    profile: str,
    packet_path: Path,
    prompt_path: Path,
    executable: str | None = None,
    requested_model: str | None = None,
    extra_args: tuple[str, ...] | list[str] = (),
    cwd: str | None = None,
    packet: Mapping[str, Any] | None = None,
    task: str = "",
    role: str = "",
    input_contract: str | None = None,
    output_contract: str | None = None,
    repo_root: Path | str | None = None,
    session_id: str | None = None,
) -> AdapterInvocation:
    """Build an argv-safe read-only command for a known adapter.

    When ``session_id`` is set, Google/Claude/etc. resume that exact conversation so
    a reviewer that helped plan can keep planning context. Ambiguous tokens
    (latest/continue/last) are rejected.
    """
    name = resolve_adapter_name(adapter, executable=executable)
    meta = _BUILTIN.get(name, _BUILTIN["custom-cli"])
    extras = tuple(extra_args)
    _validate_fugu_launch_controls(
        name,
        executable=executable,
        requested_model=requested_model,
        extra_args=extras,
    )
    exe = resolve_executable_for_launch(executable or meta.executable_hint)
    validate_extra_args(name, extras)
    exact_session = (
        assert_exact_session_id(session_id, adapter=name) if session_id else None
    )

    default_in, default_out = ADAPTER_CONTRACT_PAIRS.get(
        name, ("json-stdio", "custom-json-envelope")
    )
    in_c = (input_contract or default_in).strip()
    out_c = (output_contract or default_out).strip()
    if out_c == "json-role-report":
        out_c = "custom-json-envelope"
    in_c, out_c = validate_adapter_contract_pair(
        name, input_contract=in_c, output_contract=out_c
    )

    work_cwd = str(repo_root) if repo_root is not None else (cwd or None)
    packet_obj = dict(packet or {})
    full_prompt = compose_full_prompt(packet=packet_obj, task=task, role=role or profile)

    if name == "host-native":
        return AdapterInvocation(
            adapter="host-native",
            executable="",
            argv=(),
            read_only=True,
            tool_scope="read-only",
            sandbox_scope="host",
            notes="host-native has no subprocess; requires bound injected host evidence",
            input_mode="none",
            decoder="host-injected",
            unavailable=True,
            unavailable_reason=(
                "host_native_requires_injected_report: standalone council cannot "
                "fabricate a host vote or count host-native toward quorum"
            ),
            cwd=work_cwd,
        )

    if name == "claude-code":
        argv_list = [
            exe,
            "--print",
            "--output-format",
            "json",
            "--permission-mode",
            "plan",
            "--no-session-persistence",
        ]
        if requested_model:
            argv_list.extend(["--model", requested_model])
        # Benign extras only — reserved already validated.
        argv_list.extend(extras)
        return AdapterInvocation(
            adapter="claude-code",
            executable=exe,
            argv=tuple(argv_list),
            read_only=True,
            tool_scope="read-only",
            sandbox_scope="ephemeral",
            notes=(
                "structural read-only scope via permission-mode plan; "
                "no permission-bypass flags; prompt on stdin; decoder claude-json"
            ),
            stdin_text=full_prompt,
            input_mode="stdin",
            decoder="claude-json",
            cwd=work_cwd,
        )

    if name == "grok-build":
        from .implement import require_exact_grok_session_uuid  # noqa: PLC0415

        # Full packet/task written to prompt_path by dispatcher; argv references path.
        argv_list = [exe]
        if exact_session:
            exact_session = require_exact_grok_session_uuid(exact_session)
            argv_list.extend(["--resume", exact_session])
        argv_list.extend(
            [
            "--prompt-file",
            str(prompt_path),
            "--output-format",
            "json",
            "--permission-mode",
            "plan",
            "--no-subagents",
            "--no-memory",
            "--disable-web-search",
            ]
        )
        if requested_model:
            argv_list.extend(["--model", requested_model])
        argv_list.extend(extras)
        return AdapterInvocation(
            adapter="grok-build",
            executable=exe,
            argv=tuple(argv_list),
            read_only=True,
            tool_scope="read-only",
            sandbox_scope="ephemeral",
            notes="full prompt-file body; actual_model not claimed from stdout alone",
            input_mode="prompt-file",
            decoder="grok-json",
            cwd=work_cwd,
            prompt_file_body=full_prompt,
            session_id=exact_session,
        )

    if name == "codex-fugu":
        if work_cwd is None:
            work_cwd = str(packet_path.parent)
        argv_list = [
            exe,
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--cd",
            work_cwd,
            "--model",
            "fugu",
            "--config",
            'model_reasoning_effort="high"',
        ]
        argv_list.append("-")
        return AdapterInvocation(
            adapter="codex-fugu",
            executable=exe,
            argv=tuple(argv_list),
            read_only=True,
            tool_scope="read-only",
            sandbox_scope="read-only",
            notes="codex exec JSONL; prompt on stdin; cwd is repository root",
            stdin_text=full_prompt,
            input_mode="stdin",
            decoder="codex-jsonl",
            cwd=work_cwd,
        )

    if name == "opencode-cli":
        # OpenCode (opencode.ai): Claude Code–like TUI/agent; headless via `opencode run`.
        # OpenRouter and 75+ providers; model format provider/model. Exact -s/--session only.
        if not exe:
            exe = "opencode"
        # Prefer plan agent for read-only council/review when available.
        agent = "plan"
        # Both the positional message and --file are array-valued in OpenCode's
        # yargs parser. Keep the message immediately after `run` so any file
        # options added by a caller or future builder cannot consume the prompt.
        argv_list = [exe, "run", full_prompt, "--format", "default", "--agent", agent]
        if exact_session:
            argv_list.extend(["--session", exact_session])
        if requested_model:
            argv_list.extend(["--model", str(requested_model)])
        argv_list.extend(extras)
        return AdapterInvocation(
            adapter=name,
            executable=exe,
            argv=tuple(argv_list),
            read_only=True,
            tool_scope="read-only",
            sandbox_scope="ephemeral",
            notes=(
                "OpenCode headless `run` with --agent plan (read-oriented). "
                "Pin model as provider/model (e.g. openrouter/qwen/qwen3-max). "
                "Exact --session <id> for plan→review; never bare --continue. "
                "For implement labor use profile opencode-labor / --auto separately."
            ),
            stdin_text=None,
            input_mode="none",
            decoder="custom-json-envelope",
            cwd=work_cwd,
            session_id=exact_session,
        )

    if name == "devin-cli":
        if not exe:
            exe = "devin"
        argv_list = [
            exe,
            "--prompt-file",
            str(prompt_path),
            "--print",
            "--permission-mode",
            "auto",
        ]
        if exact_session:
            argv_list.extend(["--resume", exact_session])
        if requested_model:
            argv_list.extend(["--model", str(requested_model)])
        argv_list.extend(extras)
        return AdapterInvocation(
            adapter=name,
            executable=exe,
            argv=tuple(argv_list),
            read_only=True,
            tool_scope="read-only",
            sandbox_scope="ephemeral",
            notes=(
                "Devin CLI headless --print with --prompt-file; exact --resume <id> only; "
                "never bare --continue/-c. Host captures the provider session id from "
                "`devin list --format json` after create."
            ),
            stdin_text=None,
            input_mode="prompt-file",
            decoder="custom-json-envelope",
            cwd=work_cwd,
            prompt_file_body=full_prompt,
            session_id=exact_session,
        )

    if name == "omp-cli":
        if not exe:
            exe = "omp"
        profile_name = f"elves-omp-ro-{Path(work_cwd or '.').name}"[:48]
        argv_list = [
            exe,
            "--mode",
            "json",
            "--approval-mode",
            "always-ask",
            "--profile",
            profile_name,
            "--thinking",
            "medium",
        ]
        if work_cwd:
            argv_list.extend(["--cwd", str(work_cwd)])
        if exact_session:
            argv_list.extend(["--resume", exact_session])
        if requested_model:
            argv_list.extend(["--model", str(requested_model)])
        # Bare prompt path for supervisors; omp loads via append-system-prompt
        argv_list.extend(["--append-system-prompt", str(prompt_path)])
        argv_list.append(full_prompt if full_prompt.strip() else "Follow the attached packet.")
        argv_list.extend(extras)
        inv = AdapterInvocation(
            adapter=name,
            executable=exe,
            argv=tuple(argv_list),
            read_only=True,
            tool_scope="read-only",
            sandbox_scope="ephemeral",
            notes=(
                "Oh My Pi (omp) headless --mode json; exact --resume <uuid> only; "
                "never --continue/-c; never omp --prewalk. Host captures session id "
                "from typed NDJSON session events."
            ),
            stdin_text=None,
            input_mode="none",
            decoder="omp-jsonl",
            cwd=work_cwd,
            session_id=exact_session,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        if "--prewalk" in inv.argv:
            raise ValidationIssue(
                "omp_prewalk_forbidden",
                "omp --prewalk is not Elves exact-session prewalk and is forbidden",
            )
        return inv

    if name in {"gemini-cli", "antigravity-cli"}:
        # Dogfood (2026-07): Gemini CLI 0.50 + Antigravity CLI (agy) 1.1.
        # Prefer latest Gemini models in models.toml (e.g. Gemini 3.1 Pro for plan/review,
        # Gemini 3.5 Flash for optional experimental labor). Headless uses -p/--print;
        # bare stdin without -p does not run a one-shot turn.
        if name == "antigravity-cli":
            # Resolve executable: prefer agy, then antigravity, then configured name.
            candidates: list[str] = []
            for cand in (exe, "agy", "antigravity"):
                if cand and cand not in candidates and cand != "(user-defined)":
                    candidates.append(str(cand))
            resolved = None
            for cand in candidates:
                if resolve_executable(cand):
                    resolved = resolve_executable_for_launch(cand)
                    break
            if resolved:
                exe = resolved
            elif not exe:
                exe = "agy"
            argv_list = [exe]
            if exact_session:
                # Exact conversation resume — planning context for later review.
                argv_list.extend(["--conversation", exact_session])
            argv_list.extend(["--print", full_prompt, "--mode", "plan"])
            if requested_model:
                argv_list.extend(["--model", str(requested_model)])
            argv_list.extend(extras)
            return AdapterInvocation(
                adapter=name,
                executable=exe,
                argv=tuple(argv_list),
                read_only=True,
                tool_scope="read-only",
                sandbox_scope="ephemeral",
                notes=(
                    "Antigravity CLI (agy) headless --print; pin latest Gemini model "
                    "(3.1 Pro plan/review, 3.5 Flash optional labor). Not Lane A / not "
                    "host-import write-lease qualified. Experimental implement: host "
                    "launches agy with --dangerously-skip-permissions separately. "
                    "Pass exact session_id/--conversation so review resumes planning chat."
                ),
                stdin_text=None,
                input_mode="none",
                decoder="custom-json-envelope",
                cwd=work_cwd,
                session_id=exact_session,
            )

        # gemini-cli
        if not exe:
            exe = "gemini"
        argv_list = [
            exe,
            "--skip-trust",
            "--approval-mode",
            "plan",
            "-o",
            "text",
        ]
        if exact_session:
            # Resume exact planning conversation so review keeps plan context.
            argv_list.extend(["--resume", exact_session])
        argv_list.extend(["-p", full_prompt])
        if requested_model:
            argv_list.extend(["-m", str(requested_model)])
        argv_list.extend(extras)
        return AdapterInvocation(
            adapter=name,
            executable=exe,
            argv=tuple(argv_list),
            read_only=True,
            tool_scope="read-only",
            sandbox_scope="ephemeral",
            notes=(
                "Gemini CLI headless -p + --skip-trust + plan approval; pin a current "
                "Gemini model id via requested_model. Prefer plan/review; API-key path "
                "is not a substitute for Antigravity OAuth sessions. "
                "Pass exact session_id to resume planning context into review."
            ),
            stdin_text=None,
            input_mode="none",
            decoder="custom-json-envelope",
            cwd=work_cwd,
            session_id=exact_session,
        )

    # custom-cli: provider-neutral JSON-over-stdio envelope on stdin.
    if not exe or exe == "(user-defined)":
        raise ValidationIssue(
            "missing_executable",
            f"custom-cli profile `{profile}` requires an executable",
            path=f"profiles.{profile}.executable",
        )
    # Relative project scripts (e.g. scripts/openrouter_lens.py) resolve from repo root.
    script_path = Path(exe) if exe else None
    if (
        work_cwd
        and exe
        and not Path(exe).is_absolute()
        and (Path(work_cwd) / exe).is_file()
    ):
        script_path = Path(work_cwd) / exe
        exe = str(script_path)
    envelope = {
        "role": role or profile,
        "task": task,
        "requested_model": requested_model,
        "profile": profile,
        "packet": packet_obj,
        "packet_path": str(packet_path),
        "execution_identity": packet_obj.get("execution_identity"),
        "output_contract": "custom-json-envelope",
        "session_id": exact_session,
    }
    # Run .py wrappers via the same Python as Cobbler (no +x / PATH dependency).
    if script_path is not None and str(script_path).endswith(".py"):
        import sys as _sys  # noqa: PLC0415

        argv_list = [_sys.executable, str(script_path), *extras]
        exe = _sys.executable
    else:
        argv_list = [exe, *extras]
    # OpenRouter lens: pass --repo-root so session store lands in the checkout.
    if script_path is not None and "openrouter_lens" in script_path.name.replace("-", "_"):
        joined_extras = " ".join(str(x) for x in argv_list)
        if work_cwd and "--repo-root" not in joined_extras:
            argv_list.extend(["--repo-root", work_cwd])
        if exact_session and "--session-id" not in joined_extras:
            argv_list.extend(["--session-id", exact_session])
        if requested_model and "--model" not in joined_extras:
            argv_list.extend(["--model", str(requested_model)])
    return AdapterInvocation(
        adapter="custom-cli",
        executable=exe,
        argv=tuple(argv_list),
        read_only=True,
        tool_scope="read-only",
        sandbox_scope="ephemeral",
        notes=(
            "JSON-stdio wrapper envelope; transport fields outer, report nested. "
            "For OpenRouter: scripts/openrouter_lens.py + OPENROUTER_API_KEY; "
            "prefer exact session_id for plan→review; else attach plan/docs in packet."
        ),
        stdin_text=json.dumps(envelope, sort_keys=True) + "\n",
        input_mode="json-stdio",
        decoder="custom-json-envelope",
        cwd=work_cwd,
        session_id=exact_session,
    )


# --- Role report validation -------------------------------------------------


def normalize_confidence(raw: Any) -> float:
    if isinstance(raw, bool):
        raise ValidationIssue(
            "invalid_confidence",
            "confidence must not be a boolean",
        )
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value != value or value in (float("inf"), float("-inf")):
            raise ValidationIssue(
                "invalid_confidence",
                "confidence must be a finite number",
            )
        if value < 0.0 or value > 1.0:
            raise ValidationIssue(
                "invalid_confidence",
                f"confidence {value} outside accepted range [0, 1]",
            )
        return value
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in CONFIDENCE_ALIASES:
            return CONFIDENCE_ALIASES[key]
        raise ValidationIssue(
            "invalid_confidence",
            f"Unknown confidence alias `{raw}`",
        )
    raise ValidationIssue(
        "invalid_confidence",
        f"Unsupported confidence type `{type(raw).__name__}`",
    )


def validate_role_report(
    data: Mapping[str, Any],
    *,
    expected_role: str | None = None,
) -> dict[str, Any]:
    """Strict role-report validation. Model identity fields are never authoritative."""
    if not isinstance(data, Mapping):
        raise ValidationIssue("invalid_report_type", "Role report must be an object")
    report = dict(data)
    missing = [field for field in ROLE_REPORT_SCHEMA_FIELDS if field not in report]
    if missing:
        raise ValidationIssue(
            "missing_report_fields",
            "Role report missing required fields: " + ", ".join(missing),
            hint=f"required fields: {', '.join(ROLE_REPORT_SCHEMA_FIELDS)}",
        )

    role = report.get("role")
    if not isinstance(role, str) or not role.strip():
        raise ValidationIssue(
            "invalid_report_role",
            "Role report role must be a non-empty string",
        )
    role = role.strip()
    if expected_role is not None and role != expected_role:
        raise ValidationIssue(
            "role_mismatch",
            f"Report role `{role}` does not match expected `{expected_role}`",
        )
    report["role"] = role

    verdict = report.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        raise ValidationIssue(
            "invalid_verdict",
            "Role report verdict must be a non-empty string",
        )
    verdict_n = verdict.strip().lower()
    if verdict_n not in ALLOWED_VERDICTS:
        raise ValidationIssue(
            "invalid_verdict",
            f"Verdict `{verdict}` not in allowed set",
        )
    report["verdict"] = verdict_n

    report["confidence"] = normalize_confidence(report.get("confidence"))

    allowed_keys = set(ROLE_REPORT_SCHEMA_FIELDS) | {
        "actual_model",
        "model",
        "requested_model",
    }
    unexpected = sorted(str(k) for k in report.keys() if k not in allowed_keys)
    if unexpected:
        raise ValidationIssue(
            "unexpected_report_fields",
            "Role report contains unexpected fields: " + ", ".join(unexpected),
        )

    for key in (
        "key_findings",
        "evidence",
        "risks",
        "recommended_actions",
        "open_questions",
    ):
        value = report.get(key)
        if value is None:
            raise ValidationIssue(
                "invalid_report_field_type",
                f"Role report field `{key}` must be a list of strings, not null",
            )
        if isinstance(value, str):
            report[key] = [value]
            continue
        if not isinstance(value, list):
            raise ValidationIssue(
                "invalid_report_field_type",
                f"Role report field `{key}` must be a list of strings",
            )
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValidationIssue(
                    "invalid_report_field_type",
                    f"Role report field `{key}` members must be strings",
                )
            cleaned.append(item)
        report[key] = cleaned
    return report


def parse_role_report(
    stdout: str,
    *,
    expected_role: str | None = None,
    requested_model: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible entry: decode custom envelope or bare report.

    ``requested_model`` is ignored for identity (model-authored untrusted).
    Prefer :func:`decode_adapter_output` with an explicit decoder.
    """
    _ = requested_model
    result = decode_adapter_output(
        stdout,
        decoder="custom-json-envelope",
        expected_role=expected_role,
        requested_model=None,
        require_model=False,
    )
    return result.role_report


# --- Adapter-specific transport decoders -----------------------------------


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValidationIssue("empty_output", "Adapter produced empty stdout")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.S)
    if fence:
        stripped = fence.group(1)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        # Try last object span.
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(stripped[start : end + 1])
            except json.JSONDecodeError as exc2:
                raise ValidationIssue(
                    "malformed_json",
                    f"Adapter stdout is not valid JSON: {exc2.msg}",
                ) from exc2
        else:
            raise ValidationIssue(
                "malformed_json",
                f"Adapter stdout is not valid JSON: {exc.msg}",
            ) from exc
    if not isinstance(data, dict):
        raise ValidationIssue("invalid_report_type", "JSON root must be an object")
    return data


def _report_from_text_blob(blob: Any, *, expected_role: str | None) -> dict[str, Any]:
    if isinstance(blob, dict):
        # If nested role_report present, use it; else treat as report.
        if isinstance(blob.get("role_report"), dict):
            return validate_role_report(blob["role_report"], expected_role=expected_role)
        if all(field in blob for field in ("role", "verdict", "confidence")):
            return validate_role_report(blob, expected_role=expected_role)
        raise ValidationIssue(
            "malformed_output",
            "Transport content object is not a role report",
        )
    if not isinstance(blob, str) or not blob.strip():
        raise ValidationIssue(
            "malformed_output",
            "Transport content must be a role-report object or JSON string",
        )
    inner = _parse_json_object(blob)
    if isinstance(inner.get("role_report"), dict):
        return validate_role_report(inner["role_report"], expected_role=expected_role)
    return validate_role_report(inner, expected_role=expected_role)


def decode_claude_json(
    stdout: str,
    *,
    expected_role: str | None = None,
) -> TransportDecodeResult:
    """Claude Code 2.1.207: outer object with result + modelUsage."""
    data = _parse_json_object(stdout)
    # modelUsage is machine metadata; never trust model-authored nested metadata.
    actual: str | None = None
    source: str | None = None
    usage = data.get("modelUsage")
    top_model = data.get("model") if isinstance(data.get("model"), str) else None
    if isinstance(usage, dict) and usage:
        keys = [str(k) for k in usage.keys() if str(k).strip()]
        if len(keys) == 1:
            actual = keys[0]
            source = "claude.modelUsage"
        elif len(keys) > 1:
            # Multiple models are ambiguous unless top-level model disambiguates.
            if top_model and top_model.strip() in keys:
                actual = top_model.strip()
                source = "claude.model+modelUsage"
            else:
                raise ValidationIssue(
                    "ambiguous_model_usage",
                    "Claude modelUsage contains multiple models without disambiguating model field",
                )
    elif top_model and top_model.strip():
        actual = top_model.strip()
        source = "claude.model"
    content = data.get("result")
    if content is None:
        raise ValidationIssue(
            "malformed_output",
            "Claude JSON missing transport field `result`",
        )
    report = _report_from_text_blob(content, expected_role=expected_role)
    return TransportDecodeResult(
        role_report=report,
        actual_model=actual,
        model_evidence_source=source,
        session_id=str(data["session_id"]) if data.get("session_id") else None,
        transport_notes=("claude-json",),
    )


def decode_grok_json(
    stdout: str,
    *,
    expected_role: str | None = None,
) -> TransportDecodeResult:
    """Grok Build 0.2.93: outer text/stopReason/sessionId; no actual_model."""
    data = _parse_json_object(stdout)
    if "text" not in data:
        raise ValidationIssue(
            "malformed_output",
            "Grok JSON missing transport field `text`",
        )
    report = _report_from_text_blob(data.get("text"), expected_role=expected_role)
    session_id = data.get("sessionId") or data.get("session_id")
    return TransportDecodeResult(
        role_report=report,
        actual_model=None,
        model_evidence_source=None,
        session_id=str(session_id) if session_id else None,
        transport_notes=(
            "grok-json",
            "actual_model_unknown_from_stdout",
            f"stopReason={data.get('stopReason')}",
        ),
    )


def decode_codex_jsonl(
    stdout: str,
    *,
    expected_role: str | None = None,
) -> TransportDecodeResult:
    """Codex exec --json: JSONL event stream; final agent message is the report."""
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        raise ValidationIssue("empty_output", "Codex JSONL stdout is empty")
    messages: list[str] = []
    actual: str | None = None
    source: str | None = None
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationIssue(
                "malformed_json",
                f"Codex JSONL line is not valid JSON: {exc.msg}",
            ) from exc
        if not isinstance(event, dict):
            continue
        # Capture model from machine event fields only (not message content).
        for key in ("model", "actual_model"):
            if isinstance(event.get(key), str) and event[key].strip():
                actual = event[key].strip()
                source = f"codex.event.{key}"
        item = event.get("item")
        if isinstance(item, dict):
            for key in ("model", "actual_model"):
                if isinstance(item.get(key), str) and item[key].strip():
                    actual = item[key].strip()
                    source = f"codex.item.{key}"
            text = item.get("text") or item.get("content")
            if isinstance(text, str) and text.strip():
                if item.get("type") in {None, "agent_message", "message", "agent_message_content"}:
                    messages.append(text)
        if event.get("type") in {"agent_message", "message"} and isinstance(event.get("text"), str):
            messages.append(event["text"])
    if not messages:
        raise ValidationIssue(
            "malformed_output",
            "Codex JSONL stream contained no agent message text",
        )
    report = _report_from_text_blob(messages[-1], expected_role=expected_role)
    return TransportDecodeResult(
        role_report=report,
        actual_model=actual,
        model_evidence_source=source,
        transport_notes=("codex-jsonl",),
    )


def decode_custom_json_envelope(
    stdout: str,
    *,
    expected_role: str | None = None,
) -> TransportDecodeResult:
    """Provider-neutral wrapper: outer transport fields + nested report.

    Outer ``actual_model`` / ``session_id`` are wrapper-authored transport fields.
    Nested report text cannot supply adapter_metadata as authority.
    """
    data = _parse_json_object(stdout)
    # Reject model-authored lookalike authority path.
    if "adapter_metadata" in data and "role_report" in data:
        # Only accept adapter_metadata if marked as wrapper_transport by the wrapper.
        meta = data.get("adapter_metadata")
        if isinstance(meta, dict) and meta.get("source") == "wrapper-transport":
            actual = meta.get("actual_model")
            source = "custom.wrapper-transport"
            report = validate_role_report(data["role_report"], expected_role=expected_role)
            return TransportDecodeResult(
                role_report=report,
                actual_model=str(actual) if actual else None,
                model_evidence_source=source if actual else None,
                session_id=str(meta["session_id"]) if meta.get("session_id") else None,
                transport_notes=("custom-json-envelope", "wrapper-transport"),
            )
        raise ValidationIssue(
            "untrusted_model_authored_metadata",
            "Model-authored adapter_metadata/role_report envelope is not transport authority",
            hint="Wrapper must set outer actual_model with source=wrapper-transport",
        )

    actual = data.get("actual_model")
    if actual is not None and not isinstance(actual, str):
        raise ValidationIssue(
            "invalid_transport_field",
            "Outer actual_model must be a string when present",
        )
    session_id = data.get("session_id")
    if "role_report" in data:
        report = validate_role_report(data["role_report"], expected_role=expected_role)
    elif "content" in data:
        report = _report_from_text_blob(data.get("content"), expected_role=expected_role)
    elif all(field in data for field in ("role", "verdict", "confidence")):
        # Bare report only — no transport model evidence.
        report = validate_role_report(data, expected_role=expected_role)
        return TransportDecodeResult(
            role_report=report,
            actual_model=None,
            model_evidence_source=None,
            transport_notes=("custom-json-envelope", "bare-report-no-transport-model"),
        )
    else:
        raise ValidationIssue(
            "malformed_output",
            "Custom envelope missing role_report/content",
        )
    return TransportDecodeResult(
        role_report=report,
        actual_model=actual.strip() if isinstance(actual, str) and actual.strip() else None,
        model_evidence_source="custom.outer.actual_model" if actual else None,
        session_id=str(session_id) if session_id else None,
        transport_notes=("custom-json-envelope",),
    )



def decode_omp_jsonl(
    stdout: str,
    *,
    expected_role: str | None = None,
) -> TransportDecodeResult:
    """Oh My Pi ``omp --mode json`` NDJSON stream decoder.

    Transport authority fields only:
    - session id from ``{"type":"session","id":...}``
    - model/provider from assistant message metadata (not free text)
    - terminal from ``agent_end`` (required for success)
    """
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        raise ValidationIssue("empty_output", "OMP JSONL stdout is empty")

    session_id: str | None = None
    actual: str | None = None
    source: str | None = None
    texts: list[str] = []
    saw_agent_end = False
    usage_note = ""

    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationIssue(
                "malformed_json",
                f"OMP JSONL line is not valid JSON: {exc.msg}",
            ) from exc
        if not isinstance(event, dict):
            continue
        et = event.get("type")
        if et == "session":
            raw_id = event.get("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise ValidationIssue(
                    "malformed_output",
                    "OMP session event missing string id",
                )
            sid = raw_id.strip()
            if session_id is None:
                session_id = sid
            elif session_id != sid:
                raise ValidationIssue(
                    "session_id_conflict",
                    f"OMP stream emitted conflicting session ids ({session_id} vs {sid})",
                )
        elif et in {"message_end", "message_start"}:
            msg = event.get("message")
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                model = msg.get("model")
                provider = msg.get("provider")
                if isinstance(model, str) and model.strip():
                    if isinstance(provider, str) and provider.strip():
                        actual = f"{provider.strip()}/{model.strip()}"
                    else:
                        actual = model.strip()
                    source = "omp.message.model"
                content = msg.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text = part.get("text")
                            if isinstance(text, str) and text.strip():
                                texts.append(text)
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    usage_note = f"usage_tokens={usage.get('totalTokens')}"
        elif et == "agent_end":
            saw_agent_end = True
            msgs = event.get("messages")
            if isinstance(msgs, list):
                for msg in msgs:
                    if not isinstance(msg, dict) or msg.get("role") != "assistant":
                        continue
                    model = msg.get("model")
                    provider = msg.get("provider")
                    if isinstance(model, str) and model.strip():
                        if isinstance(provider, str) and provider.strip():
                            actual = f"{provider.strip()}/{model.strip()}"
                        else:
                            actual = model.strip()
                        source = "omp.agent_end.model"
                    content = msg.get("content")
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text = part.get("text")
                                if isinstance(text, str) and text.strip():
                                    texts.append(text)

    if session_id is None:
        raise ValidationIssue(
            "malformed_output",
            "OMP JSONL stream contained no session id",
        )
    if not saw_agent_end:
        raise ValidationIssue(
            "malformed_output",
            "OMP JSONL stream missing agent_end terminal event",
        )
    if not texts:
        raise ValidationIssue(
            "malformed_output",
            "OMP JSONL stream contained no assistant text",
        )
    # Free-text assistant bodies are not role-report JSON; wrap as host transport summary.
    summary = texts[-1].strip()
    role = (expected_role or "implement").strip() or "implement"
    report = validate_role_report(
        {
            "role": role,
            "verdict": "info",
            "confidence": 0.5,
            "key_findings": [summary[:500]],
            "evidence": ["omp.assistant_text"],
            "risks": [],
            "recommended_actions": [],
            "open_questions": [],
        },
        expected_role=expected_role,
    )
    notes = ["omp-jsonl"]
    if usage_note:
        notes.append(usage_note)
    return TransportDecodeResult(
        role_report=report,
        actual_model=actual,
        model_evidence_source=source,
        session_id=session_id,
        transport_notes=tuple(notes),
    )


def decode_adapter_output(
    stdout: str,
    *,
    decoder: str,
    expected_role: str | None = None,
    requested_model: str | None = None,
    require_model: bool = False,
) -> TransportDecodeResult:
    """Decode stdout with a strict adapter-specific decoder."""
    name = (decoder or "").strip()
    if name in {"claude-json"}:
        result = decode_claude_json(stdout, expected_role=expected_role)
    elif name in {"grok-json"}:
        result = decode_grok_json(stdout, expected_role=expected_role)
    elif name in {"codex-jsonl"}:
        result = decode_codex_jsonl(stdout, expected_role=expected_role)
    elif name in {"omp-jsonl"}:
        result = decode_omp_jsonl(stdout, expected_role=expected_role)
    elif name in {"custom-json-envelope", "json-role-report", "json-transport-envelope"}:
        result = decode_custom_json_envelope(stdout, expected_role=expected_role)
    else:
        raise ValidationIssue(
            "unsupported_output_contract",
            f"No decoder for output contract `{decoder}`",
        )

    if require_model or requested_model is not None:
        if result.actual_model is None:
            raise ValidationIssue(
                "actual_model_missing",
                (
                    f"requested_model `{requested_model}` requires authoritative "
                    "transport actual_model; model-authored report fields are not proof"
                ),
            )
        if requested_model is not None and str(result.actual_model) != str(requested_model):
            raise ValidationIssue(
                "actual_model_mismatch",
                (
                    f"authoritative actual_model `{result.actual_model}` does not match "
                    f"requested_model `{requested_model}`"
                ),
            )
    return result


# Compatibility aliases used by older call sites / tests.
def parse_transport_output(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deprecated shape: never treat nested adapter_metadata as authority."""
    try:
        data = _parse_json_object(stdout)
    except ValidationIssue:
        return {}, {}
    if isinstance(data.get("role_report"), dict):
        # Do not return model-authored metadata as authoritative.
        return {}, dict(data["role_report"])
    return {}, dict(data)


def extract_authoritative_model(
    metadata: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Only honor explicitly wrapper-marked transport metadata."""
    if not metadata:
        return None, None
    if metadata.get("source") != "wrapper-transport":
        return None, None
    model = metadata.get("actual_model")
    if model is None or str(model).strip() == "":
        return None, "wrapper-transport"
    return str(model), "wrapper-transport"


def validate_model_evidence(
    *,
    requested_model: str | None,
    metadata: Mapping[str, Any] | None,
    require_when_requested: bool = True,
) -> tuple[str | None, str | None]:
    actual, source = extract_authoritative_model(metadata)
    if requested_model is not None and require_when_requested:
        if actual is None:
            raise ValidationIssue(
                "actual_model_missing",
                (
                    f"requested_model `{requested_model}` requires authoritative "
                    "transport actual_model; model-authored report fields are not proof"
                ),
            )
        if str(actual) != str(requested_model):
            raise ValidationIssue(
                "actual_model_mismatch",
                (
                    f"authoritative actual_model `{actual}` does not match "
                    f"requested_model `{requested_model}`"
                ),
            )
    return actual, source


# --- Exact session create/resume builders (Batch 2/3 surfaces; keep stable) ---

AMBIGUOUS_SESSION_FLAG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|\s)--continue(\s|$)"),
    re.compile(r"(^|\s)--last(\s|$)"),
    re.compile(r"(^|\s)--resume(\s|$)"),
    re.compile(r"(^|\s)-c(\s|$)"),
)


def assert_no_ambiguous_session_flags(argv: tuple[str, ...] | list[str]) -> None:
    tokens = list(argv)
    joined = " ".join(tokens)
    for index, token in enumerate(tokens):
        if token in {"--continue", "--last"}:
            raise ValidationIssue(
                "ambiguous_session_flag",
                f"Forbidden ambiguous session flag `{token}` in argv",
                hint="Use exact session IDs only",
            )
        if token == "--resume":
            nxt = tokens[index + 1] if index + 1 < len(tokens) else None
            if nxt is None or nxt.startswith("-"):
                raise ValidationIssue(
                    "ambiguous_session_flag",
                    "Bare `--resume` without an exact session id is forbidden",
                    hint="Use --resume <exact-session-id> or --session-id <id>",
                )
    for pattern in AMBIGUOUS_SESSION_FLAG_PATTERNS:
        if pattern.pattern.startswith(r"(^|\s)--resume"):
            continue
        if pattern.search(joined):
            raise ValidationIssue(
                "ambiguous_session_flag",
                f"Forbidden ambiguous session selection pattern in: {joined}",
            )


def build_session_create_invocation(
    *,
    adapter: str,
    profile: str,
    executable: str | None = None,
    requested_model: str | None = None,
    extra_args: tuple[str, ...] | list[str] = (),
) -> AdapterInvocation:
    name = adapter.strip().lower()
    meta = _BUILTIN.get(name, _BUILTIN["custom-cli"])
    extras = tuple(extra_args)
    _validate_fugu_launch_controls(
        name,
        executable=executable,
        requested_model=requested_model,
        extra_args=extras,
    )
    exe = resolve_executable_for_launch(executable or meta.executable_hint)
    if name == "host-native":
        raise ValidationIssue(
            "host_native_no_external_session",
            "host-native does not create external provider sessions",
        )
    if name == "claude-code":
        import uuid as _uuid  # noqa: PLC0415

        sid = str(_uuid.uuid4())
        argv = [exe or "claude", "--print", "--output-format", "json"]
        if requested_model:
            argv.extend(["--model", requested_model])
        argv.extend(["--session-id", sid])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="claude-code",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes="exact caller-assigned session create; no --continue/--last",
            session_id=sid,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "grok-build":
        import uuid as _uuid  # noqa: PLC0415

        sid = str(_uuid.uuid4())
        argv = [exe or "grok", "--session-id", sid]
        if requested_model:
            argv.extend(["--model", requested_model])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="grok-build",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes="exact caller-assigned UUID create; no unsupported --new-session flag",
            session_id=sid,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "codex-fugu":
        argv = [
            exe or "codex-fugu",
            "exec",
            "--json",
            "--model",
            "fugu",
            "--config",
            'model_reasoning_effort="high"',
        ]
        inv = AdapterInvocation(
            adapter="codex-fugu",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes="fresh Codex session; capture exact thread.started.thread_id before resume",
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "opencode-cli":
        import uuid as _uuid  # noqa: PLC0415

        correlation = _uuid.uuid4().hex[:8]
        argv = [
            exe or "opencode",
            "run",
            "--title",
            f"elves-create-{correlation}",
            "Reply with exactly: session-created",
        ]
        if requested_model:
            argv.extend(["--model", str(requested_model)])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="opencode-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "OpenCode session create: after first run, capture exact session id via "
                "`opencode session list` / export and register it; resume with --session <id> "
                "only (never bare --continue). The unique title is a discovery correlation, "
                "not a session id; no session_id is authoritative until capture. Preferred "
                "for plan→review continuity."
            ),
            session_id=None,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "devin-cli":
        # Devin does not preallocate a session id. Launch a minimal --print turn so the
        # host can capture the exact provider session id from `devin list --format json`
        # and register it before any resume.
        argv = [exe or "devin", "--print", "Reply with exactly: session-created"]
        if requested_model:
            argv.extend(["--model", str(requested_model)])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="devin-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "Devin session create is host-mediated: after the first turn, capture the "
                "exact session id (not --continue/-c) from `devin list --format json`, "
                "then resume with --resume <id>. No session_id is authoritative until "
                "the provider UUID is captured."
            ),
            session_id=None,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "omp-cli":
        # OMP does not accept a preallocated session id. Headless create emits a typed
        # session event; host captures id before resume.
        argv = [
            exe or "omp",
            "--mode",
            "json",
            "--approval-mode",
            "always-ask",
            "--profile",
            "elves-omp-create",
            "Reply with exactly: session-created",
        ]
        if requested_model:
            argv.extend(["--model", str(requested_model)])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="omp-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "OMP session create: capture exact UUID from NDJSON type=session id; "
                "resume with --resume <uuid> only (never --continue/-c)."
            ),
            session_id=None,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "gemini-cli":
        # Host supplies exact UUID; Gemini creates under --session-id.
        import uuid as _uuid  # noqa: PLC0415

        sid = str(_uuid.uuid4())
        argv = [exe or "gemini", "--skip-trust", "--session-id", sid]
        if requested_model:
            argv.extend(["-m", str(requested_model)])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="gemini-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "exact Gemini session create via --session-id; record session_id in "
                "registry and reuse for review so planning context is preserved"
            ),
            session_id=sid,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "antigravity-cli":
        # First turn creates a conversation; host must capture exact conversation id
        # (agent output CONVID=… or conversations/*.db) and register it before resume.
        argv = [exe or "agy", "--print", "Reply with exactly: session-created"]
        if requested_model:
            argv.extend(["--model", str(requested_model)])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="antigravity-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "Antigravity create is host-mediated: after first turn, record the "
                "exact conversation UUID (not --continue) in the session registry, then "
                "resume with --conversation <id> so plan→review keeps context. No "
                "session_id is authoritative until that provider UUID is captured."
            ),
            session_id=None,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if not exe or exe == "(user-defined)":
        raise ValidationIssue(
            "missing_executable",
            f"custom-cli profile `{profile}` requires an executable for session create",
            path=f"profiles.{profile}.executable",
        )
    argv = [exe, "--session-create"]
    if requested_model:
        argv.extend(["--model", requested_model])
    argv.extend(extras)
    inv = AdapterInvocation(
        adapter="custom-cli",
        executable=exe,
        argv=tuple(argv),
        read_only=True,
        notes="custom exact session create",
    )
    assert_no_ambiguous_session_flags(inv.argv)
    return inv


def build_session_resume_invocation(
    *,
    adapter: str,
    profile: str,
    session_id: str,
    executable: str | None = None,
    requested_model: str | None = None,
    cwd: str | None = None,
    extra_args: tuple[str, ...] | list[str] = (),
) -> AdapterInvocation:
    sid = assert_exact_session_id(session_id, adapter=adapter)
    name = adapter.strip().lower()
    meta = _BUILTIN.get(name, _BUILTIN["custom-cli"])
    extras = tuple(extra_args)
    _validate_fugu_launch_controls(
        name,
        executable=executable,
        requested_model=requested_model,
        extra_args=extras,
    )
    exe = resolve_executable_for_launch(executable or meta.executable_hint)
    if name == "host-native":
        raise ValidationIssue(
            "host_native_no_external_session",
            "host-native does not resume external provider sessions",
        )
    if name == "claude-code":
        argv = [exe or "claude", "--print", "--output-format", "json", "--resume", sid]
        if requested_model:
            argv.extend(["--model", requested_model])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="claude-code",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes="exact --resume <session-id>",
            session_id=sid,
            cwd=cwd,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "grok-build":
        from .implement import require_exact_grok_session_uuid  # noqa: PLC0415

        sid = require_exact_grok_session_uuid(sid)
        argv = [exe or "grok", "--resume", sid]
        if requested_model:
            argv.extend(["--model", requested_model])
        if cwd:
            argv.extend(["--cwd", cwd])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="grok-build",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes="exact child resume; verify CWD/worktree registration",
            session_id=sid,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "codex-fugu":
        argv = [
            exe or "codex-fugu",
            "exec",
            "resume",
            "--json",
            "--model",
            "fugu",
            "--config",
            'model_reasoning_effort="high"',
        ]
        argv.append(sid)
        inv = AdapterInvocation(
            adapter="codex-fugu",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes="exact `codex exec resume <session-id>`; supervisor sets OS cwd",
            session_id=sid,
            cwd=cwd,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "opencode-cli":
        argv = [exe or "opencode", "run", "--session", sid, "Continue the prior session."]
        if requested_model:
            argv.extend(["--model", str(requested_model)])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="opencode-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "exact opencode --session <id> only — never bare --continue/-c; "
                "resume planning session when reviewing"
            ),
            session_id=sid,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "devin-cli":
        argv = [exe or "devin", "--resume", sid, "--print", "Continue the prior session."]
        if requested_model:
            argv.extend(["--model", str(requested_model)])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="devin-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "exact Devin --resume <id> only — never bare --continue/-c; "
                "resume the same conversation that did planning when reviewing"
            ),
            session_id=sid,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "omp-cli":
        argv = [
            exe or "omp",
            "--mode",
            "json",
            "--resume",
            sid,
            "--approval-mode",
            "always-ask",
            "--profile",
            "elves-omp-resume",
            "Continue the prior session.",
        ]
        if requested_model:
            argv.extend(["--model", str(requested_model)])
        if cwd:
            # keep cwd after mode for resume when provided
            argv = [
                exe or "omp",
                "--mode",
                "json",
                "--cwd",
                str(cwd),
                "--resume",
                sid,
                "--approval-mode",
                "always-ask",
                "--profile",
                "elves-omp-resume",
            ]
            if requested_model:
                argv.extend(["--model", str(requested_model)])
            argv.append("Continue the prior session.")
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="omp-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "exact OMP --resume <uuid> only — never --continue/-c or latest; "
                "session id must match the captured create stream id"
            ),
            session_id=sid,
            cwd=cwd,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "gemini-cli":
        argv = [exe or "gemini", "--skip-trust", "--resume", sid]
        if requested_model:
            argv.extend(["-m", str(requested_model)])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="gemini-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "exact Gemini --resume <uuid> only — never latest/continue; "
                "use planning session id when reviewing"
            ),
            session_id=sid,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if name == "antigravity-cli":
        argv = [exe or "agy", "--conversation", sid]
        if requested_model:
            argv.extend(["--model", str(requested_model)])
        argv.extend(extras)
        inv = AdapterInvocation(
            adapter="antigravity-cli",
            executable=argv[0],
            argv=tuple(argv),
            read_only=True,
            notes=(
                "exact agy --conversation <id> only — never bare --continue; "
                "resume the same conversation that did planning when reviewing"
            ),
            session_id=sid,
        )
        assert_no_ambiguous_session_flags(inv.argv)
        return inv
    if not exe or exe == "(user-defined)":
        raise ValidationIssue(
            "missing_executable",
            f"custom-cli profile `{profile}` requires an executable for session resume",
            path=f"profiles.{profile}.executable",
        )
    argv = [exe, "--session-id", sid]
    if requested_model:
        argv.extend(["--model", requested_model])
    if cwd:
        argv.extend(["--cwd", cwd])
    argv.extend(extras)
    inv = AdapterInvocation(
        adapter="custom-cli",
        executable=exe,
        argv=tuple(argv),
        read_only=True,
        notes="custom exact session resume",
    )
    assert_no_ambiguous_session_flags(inv.argv)
    return inv


GROK_WRITE_FORBIDDEN_ARGV_TOKENS: tuple[str, ...] = (
    "--dangerously-skip-permissions",
    "bypassPermissions",
    "--yolo",
    "--always-approve",
)


@dataclass(frozen=True)
class WriteCapabilityProfile:
    adapter: str
    profile_name: str
    version: str | None
    qualified: bool
    detached_commits_permitted: bool
    require_detached_worktree: bool
    require_cwd_verification: bool
    require_worktree_registration: bool
    forbid_headless_worktree_resume: bool
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def grok_write_profile(version: str | None = "0.2.93") -> WriteCapabilityProfile:
    broken = version in {"0.2.93"} or version is None
    return WriteCapabilityProfile(
        adapter="grok-build",
        profile_name="grok-build-write",
        version=version,
        qualified=True,
        detached_commits_permitted=True,
        require_detached_worktree=True,
        require_cwd_verification=True,
        require_worktree_registration=True,
        forbid_headless_worktree_resume=broken or True,
        notes=(
            "Never use headless --worktree --resume as isolation for Grok Build 0.2.93; "
            "discover child session id and resume from registered detached worktree."
        ),
    )


def workspace_sandbox_write_profile() -> WriteCapabilityProfile:
    return WriteCapabilityProfile(
        adapter="grok-build",
        profile_name="grok-build-workspace-sandbox",
        version="0.2.93",
        qualified=False,
        detached_commits_permitted=False,
        require_detached_worktree=True,
        require_cwd_verification=True,
        require_worktree_registration=True,
        forbid_headless_worktree_resume=True,
        notes="workspace sandbox linked worktree cannot be assumed commit-capable",
    )


def build_write_resume_invocation(
    *,
    adapter: str,
    session_id: str,
    cwd: str,
    version: str | None = None,
    executable: str | None = None,
    requested_model: str | None = None,
    use_headless_worktree_resume: bool = False,
) -> AdapterInvocation:
    if adapter != "grok-build":
        return build_session_resume_invocation(
            adapter=adapter,
            profile=adapter,
            session_id=session_id,
            executable=executable,
            requested_model=requested_model,
            cwd=cwd,
        )
    profile = grok_write_profile(version)
    if use_headless_worktree_resume and profile.forbid_headless_worktree_resume:
        raise ValidationIssue(
            "grok_headless_worktree_resume_forbidden",
            (
                f"Grok write profile forbids headless --worktree --resume as isolation "
                f"(version={version or 'unknown'})"
            ),
            hint="Resume exact child id from the registered worktree CWD only",
        )
    if not cwd or not str(cwd).strip():
        raise ValidationIssue(
            "write_cwd_required",
            "Write resume requires verified worker CWD/worktree path",
        )
    inv = build_session_resume_invocation(
        adapter="grok-build",
        profile=profile.profile_name,
        session_id=session_id,
        executable=executable,
        requested_model=requested_model,
        cwd=cwd,
    )
    joined = " ".join(inv.argv)
    for token in GROK_WRITE_FORBIDDEN_ARGV_TOKENS:
        if token in inv.argv or token in joined:
            raise ValidationIssue(
                "write_permission_bypass_forbidden",
                f"Write invocation contains forbidden token `{token}`",
            )
    if "--worktree" in inv.argv and "--resume" in inv.argv:
        raise ValidationIssue(
            "grok_headless_worktree_resume_forbidden",
            "Combined --worktree and --resume is not permitted as isolation",
        )
    return inv
