#!/usr/bin/env python3
"""OpenRouter plan/review lens for Cobbler (read-only).

Usage (Cobbler custom-cli / JSON-stdio):
  echo '{"role":"review","task":"...","requested_model":"qwen/qwen3-max",...}' \\
    | python3 scripts/openrouter_lens.py

Usage (host dogfood / one-shot):
  python3 scripts/openrouter_lens.py --model qwen/qwen3-max --prompt "…"
  python3 scripts/openrouter_lens.py --model z-ai/glm-5 --prompt-file plan.md \\
    --session-id <uuid> --context-file docs/plans/….md

Environment:
  OPENROUTER_API_KEY (required; never printed)
  OPENROUTER_SITE_URL / OPENROUTER_APP_TITLE (optional attribution)

Session continuity (preferred when possible):
  --session-id <exact-uuid> stores messages under
  .elves/runtime/openrouter-sessions/<id>.json (gitignored). Resume the same id
  for plan→review. Never use latest/continue.

No session id:
  Pass plan/contract/constitution via --context-file (repeatable) or include them
  in the Cobbler packet task text so the model can still see repo context.

Never print credential values. Exit non-zero on hard failures.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cobbler_runtime.context import (
    SECRET_FILE_NAMES as _CTX_SECRET_FILE_NAMES,
    SECRET_PATH_PARTS as _CTX_SECRET_PATH_PARTS,
    is_secret_env_name,
    redact_structure,
    redact_text,
)
from cobbler_runtime.schema import AMBIGUOUS_SESSION_TOKENS

DEFAULT_MODEL = "openrouter/auto"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
SESSION_DIR_REL = Path(".elves") / "runtime" / "openrouter-sessions"
_AMBIGUOUS = AMBIGUOUS_SESSION_TOKENS
_SENSITIVE_PATH_PARTS = frozenset(_CTX_SECRET_PATH_PARTS)
_SENSITIVE_FILE_NAMES = frozenset(_CTX_SECRET_FILE_NAMES)
_SENSITIVE_FILE_SUFFIXES = frozenset({".jks", ".key", ".keystore", ".p12", ".pem", ".pfx"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_dotenv_local(repo_root: Path) -> None:
    path = repo_root / ".env.local"
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        key, _, raw = stripped.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = raw.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ[key] = val


def _api_key() -> str:
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "OPENROUTER_API_KEY is not set (env or ignored .env.local). "
            "OpenRouter lenses are optional; fall back to host-native."
        )
    return key


def _assert_exact_session_id(session_id: str | None) -> str | None:
    if session_id is None or not str(session_id).strip():
        return None
    sid = str(session_id).strip()
    if sid.lower() in _AMBIGUOUS or sid.startswith("-"):
        raise SystemExit(
            f"Ambiguous session id `{sid}` is forbidden. "
            "Pass an exact UUID, or omit session id and use --context-file / repo docs."
        )
    return sid


def _session_path(repo_root: Path, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", session_id)
    return repo_root / SESSION_DIR_REL / f"{safe}.json"


def _secret_env_values() -> frozenset[str]:
    """Return exact secret-looking environment values for value-only redaction."""
    return frozenset(
        value
        for name, value in os.environ.items()
        if is_secret_env_name(name) and isinstance(value, str) and len(value) >= 8
    )


def _is_sensitive_path(path: Path) -> bool:
    lowered_parts = tuple(part.lower() for part in path.parts)
    name = path.name.lower()
    return (
        any(part in _SENSITIVE_PATH_PARTS for part in lowered_parts)
        or name == ".env"
        or name.startswith(".env.")
        or name in _SENSITIVE_FILE_NAMES
        or name.startswith("secrets.")
        or path.suffix.lower() in _SENSITIVE_FILE_SUFFIXES
    )


def _read_safe_repo_text(
    *,
    repo_root: Path,
    requested_path: Path,
    exact_secret_values: frozenset[str],
) -> tuple[str, str]:
    """Read and redact a non-sensitive regular file contained by the checkout."""
    candidate = requested_path if requested_path.is_absolute() else repo_root / requested_path
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"Unable to resolve input file {requested_path}: {exc}") from None
    try:
        relative = resolved.relative_to(repo_root)
    except ValueError:
        raise SystemExit(
            f"Refusing input file outside repo root: {requested_path}. "
            "Copy review material into the checkout before attaching it."
        ) from None
    if _is_sensitive_path(relative):
        raise SystemExit(f"Refusing sensitive input file: {relative.as_posix()}")
    if not resolved.is_file():
        raise SystemExit(f"Input path is not a regular file: {relative.as_posix()}")
    try:
        body = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SystemExit(f"Unable to read input file {relative.as_posix()}: {exc}") from None
    if len(body) > 120_000:
        body = body[:120_000] + "\n\n…[truncated]…\n"
    return relative.as_posix(), redact_text(body, exact_values=exact_secret_values).text


def _load_session(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"session_id": path.stem, "messages": [], "created_at": _utc_now()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"session_id": path.stem, "messages": [], "created_at": _utc_now()}
    if not isinstance(data, dict):
        return {"session_id": path.stem, "messages": [], "created_at": _utc_now()}
    data.setdefault("messages", [])
    return data


def _save_session(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _utc_now()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _role_report_instruction(role: str) -> str:
    return (
        "You are a Cobbler read-only lens for planning or review. "
        f"Role label: {role}. "
        "Respond with a single JSON object only (no markdown fences) with keys: "
        "role, verdict, confidence, key_findings, evidence, risks, recommended_actions, "
        "open_questions, actual_model. "
        "verdict must be one of: pass, fail, warn, abstain, info, blocked. "
        "confidence must be a number from 0 to 1. "
        "For review roles: check plan completeness, constitution deal-breakers if provided, "
        "and regressions (indirect breakage), not only local correctness of a diff. "
        "Prefer concrete evidence. Do not invent secrets. Do not claim to have edited files."
    )


def _build_user_content(
    *,
    task: str,
    context_blobs: list[tuple[str, str]],
    packet: dict[str, Any] | None,
) -> str:
    parts: list[str] = [task.strip() or "(no task text)"]
    for label, body in context_blobs:
        parts.append(f"\n\n## Context: {label}\n\n{body}")
    if packet:
        # Compact non-secret packet snapshot for structure (not a substitute for files).
        safe = {
            k: packet.get(k)
            for k in (
                "user_intent",
                "mode",
                "work_scope",
                "relevant_files",
                "run_state",
                "constraints",
                "forbidden_actions",
            )
            if k in packet
        }
        if safe:
            parts.append(
                "\n\n## Cobbler packet (redacted structure)\n\n"
                + json.dumps(safe, indent=2, sort_keys=True)
            )
    return "\n".join(parts).strip() + "\n"


def _parse_model_json(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("empty model content")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.S)
    if fence:
        stripped = fence.group(1)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            # Freeform fallback: wrap as info report so transport still works.
            return {
                "role": "review",
                "verdict": "info",
                "confidence": 0.4,
                "key_findings": [stripped[:4000]],
                "evidence": [],
                "risks": ["Model returned non-JSON; wrapped as freeform findings"],
                "recommended_actions": ["Re-run with stricter JSON instruction if needed"],
                "open_questions": [],
            }
        data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model JSON root must be an object")
    return data


def _openrouter_chat(
    *,
    key: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    timeout_s: float,
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL")
        or "https://github.com/aigorahub/elves",
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE") or "elves-openrouter-lens",
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:500]
        # Never include Authorization header material.
        raise SystemExit(f"OpenRouter HTTP {exc.code}: {err_body}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(f"OpenRouter network error: {exc.reason}") from None
    data = json.loads(raw)
    return data


def _normalize_report(report: dict[str, Any], *, role: str, model: str) -> dict[str, Any]:
    out = dict(report)
    out.setdefault("role", role)
    out.setdefault("verdict", "info")
    try:
        conf = float(out.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    out["confidence"] = max(0.0, min(1.0, conf))
    for key in (
        "key_findings",
        "evidence",
        "risks",
        "recommended_actions",
        "open_questions",
    ):
        val = out.get(key)
        if val is None:
            out[key] = []
        elif isinstance(val, str):
            out[key] = [val]
        elif isinstance(val, list):
            # Models often return structured evidence objects even when asked for
            # strings. Normalize at the wrapper boundary so Cobbler receives the
            # documented role-report contract instead of rejecting a useful lane.
            out[key] = [
                item
                if isinstance(item, str)
                else json.dumps(item, sort_keys=True, ensure_ascii=False)
                if isinstance(item, (dict, list))
                else str(item)
                for item in val
            ]
        else:
            out[key] = [str(val)]
    out["actual_model"] = str(out.get("actual_model") or model)
    return out


def run_lens(
    *,
    repo_root: Path,
    model: str,
    role: str,
    task: str,
    session_id: str | None,
    context_files: list[Path],
    packet: dict[str, Any] | None,
    max_tokens: int,
    temperature: float,
    timeout_s: float,
    prompt_file: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    _load_dotenv_local(repo_root)
    key = _api_key()
    sid = _assert_exact_session_id(session_id)
    exact_secret_values = _secret_env_values()

    if prompt_file is not None:
        _, task = _read_safe_repo_text(
            repo_root=repo_root,
            requested_path=prompt_file,
            exact_secret_values=exact_secret_values,
        )

    context_blobs: list[tuple[str, str]] = []
    for path in context_files:
        context_blobs.append(
            _read_safe_repo_text(
                repo_root=repo_root,
                requested_path=path,
                exact_secret_values=exact_secret_values,
            )
        )

    user_content = _build_user_content(
        task=redact_text(task, exact_values=exact_secret_values).text,
        context_blobs=context_blobs,
        packet=redact_structure(packet, exact_values=exact_secret_values),
    )
    # Final boundary redaction protects against future packet/context fields that
    # bypass the field-level handling above.
    user_content = redact_text(user_content, exact_values=exact_secret_values).text
    system = _role_report_instruction(role)

    messages: list[dict[str, str]] = []
    prior_messages: list[dict[str, str]] = []
    session_data: dict[str, Any] | None = None
    session_path: Path | None = None
    if sid:
        session_path = _session_path(repo_root, sid)
        session_data = redact_structure(
            _load_session(session_path), exact_values=exact_secret_values
        )
        session_data["session_id"] = sid
        # Sanitize legacy turns before reuse; old wrapper versions may have
        # persisted content that now matches the stronger redaction boundary.
        for msg in session_data.get("messages") or []:
            if (
                isinstance(msg, dict)
                and msg.get("role") in {"user", "assistant", "system"}
                and isinstance(msg.get("content"), str)
            ):
                prior_messages.append(
                    {
                        "role": msg["role"],
                        "content": redact_text(
                            msg["content"], exact_values=exact_secret_values
                        ).text,
                    }
                )

    messages.extend(prior_messages)

    if not any(m.get("role") == "system" for m in messages):
        messages.insert(0, {"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})

    raw = _openrouter_chat(
        key=key,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_s=timeout_s,
    )
    choice = (raw.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        # Multimodal content parts
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    content = redact_text(str(content), exact_values=exact_secret_values).text
    used_model = str(raw.get("model") or model)

    try:
        report = _parse_model_json(content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Failed to parse model JSON: {exc}") from None
    report = _normalize_report(report, role=role, model=used_model)
    report = redact_structure(report, exact_values=exact_secret_values)

    if sid and session_path is not None and session_data is not None:
        hist = list(prior_messages)
        hist.append({"role": "user", "content": user_content})
        hist.append({"role": "assistant", "content": content})
        # Keep last N turns to bound disk size
        session_data["messages"] = hist[-40:]
        session_data["model"] = used_model
        _save_session(session_path, session_data)

    envelope = {
        "actual_model": used_model,
        "session_id": sid,
        "adapter_metadata": {
            "source": "wrapper-transport",
            "actual_model": used_model,
            "session_id": sid,
            "wrapper": "scripts/openrouter_lens.py",
        },
        "role_report": report,
    }
    return redact_structure(envelope, exact_values=exact_secret_values)


def _read_stdin_json() -> dict[str, Any] | None:
    if sys.stdin.isatty():
        return None
    raw = sys.stdin.read()
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Treat raw stdin as task text
        return {"task": raw}
    if not isinstance(data, dict):
        raise SystemExit("JSON stdin must be an object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OpenRouter plan/review lens for Elves Cobbler (read-only)"
    )
    parser.add_argument("--repo-root", default=".", help="Checkout root (default: cwd)")
    parser.add_argument(
        "--model",
        default=None,
        help=f"OpenRouter model id (default: env OPENROUTER_MODEL or {DEFAULT_MODEL})",
    )
    parser.add_argument("--prompt", default=None, help="Task / prompt text")
    parser.add_argument("--prompt-file", default=None, help="Read prompt text from file")
    parser.add_argument(
        "--context-file",
        action="append",
        default=[],
        help="Repo document to attach as context (repeatable): plan, constitution, etc.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Exact session UUID for plan→review continuity (preferred when available)",
    )
    parser.add_argument("--role", default="review", help="Role label for the report")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--new-session",
        action="store_true",
        help="Allocate a new session id and print it on stderr (value only once as id=…)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).expanduser().resolve()
    # Read the stdin envelope only when the caller did not already provide the
    # task on the command line: an inherited never-closing pipe must not block
    # a --prompt/--prompt-file invocation (see execution log, B4 hang analysis).
    envelope_in = (
        None if (args.prompt or args.prompt_file) else _read_stdin_json()
    )

    model = (
        args.model
        or (envelope_in or {}).get("requested_model")
        or os.environ.get("OPENROUTER_MODEL")
        or DEFAULT_MODEL
    )
    model = str(model).strip() or DEFAULT_MODEL

    role = str(args.role or (envelope_in or {}).get("role") or "review")
    task = args.prompt or ""
    if not task and envelope_in:
        task = str(envelope_in.get("task") or envelope_in.get("prompt") or "")
    if not task.strip() and not args.prompt_file:
        raise SystemExit("No task/prompt provided (stdin envelope, --prompt, or --prompt-file)")

    session_id = args.session_id or (envelope_in or {}).get("session_id")
    if args.new_session and not session_id:
        session_id = str(uuid.uuid4())
        print(f"session_id={session_id}", file=sys.stderr)

    packet = None
    if envelope_in and isinstance(envelope_in.get("packet"), dict):
        packet = envelope_in["packet"]

    context_files = [Path(p) for p in (args.context_file or [])]
    # Packet may list relevant file paths as strings
    if packet and isinstance(packet.get("relevant_files"), list):
        for item in packet["relevant_files"]:
            if isinstance(item, str) and item.strip():
                context_files.append(Path(item.strip()))

    result = run_lens(
        repo_root=repo_root,
        model=model,
        role=role,
        task=task,
        session_id=str(session_id) if session_id else None,
        context_files=context_files,
        packet=packet,
        max_tokens=int(args.max_tokens),
        temperature=float(args.temperature),
        timeout_s=float(args.timeout),
        prompt_file=Path(args.prompt_file) if args.prompt_file else None,
    )
    # Never include secrets in output (check env values only — not the literal "sk-" discussion).
    text = json.dumps(result, indent=2, sort_keys=True)
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if key and key in text:
        raise SystemExit("Refusing to print output that appears to contain secrets")
    for env_name in (
        "OPENROUTER_API_KEY",
        "META_API_KEY",
        "MODEL_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    ):
        val = (os.environ.get(env_name) or "").strip()
        if val and len(val) >= 8 and val in text:
            raise SystemExit("Refusing to print output that appears to contain secrets")
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
