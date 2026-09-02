#!/bin/bash
# Bounded headless Oh My Pi (omp) one-shot for Elves provider shortcuts.
# CLI spelling is always `omp` (never opm). Read-only snapshot isolation.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
PROMPT_CONTENT="$*"
if [ -z "$PROMPT_CONTENT" ]; then
  echo "Usage: run_omp.sh <instructions>" >&2
  exit 2
fi
# omp is an optional review route. Every non-zero exit, including the ones before
# Python starts, tells the host driver to select another reviewer.
route_unavailable() {
  # The directive is built on stdout so a broken interpreter cannot turn a
  # missing-tool message into a stack trace on the route's stderr.
  local directive
  directive=$(python3 - "$1" "$SCRIPT_DIR" <<'ROUTEPY' 2>/dev/null
import sys
sys.path.insert(0, sys.argv[2])
from cobbler_runtime.review_routes import route_unavailable_directive
print(route_unavailable_directive("omp", sys.argv[1]))
ROUTEPY
) || return 0
  if [ -n "$directive" ]; then
    printf '%s\n' "$directive" >&2
  fi
  return 0
}
if ! command -v omp >/dev/null 2>&1; then
  echo "Error: omp (Oh My Pi) CLI not found on PATH." >&2
  route_unavailable runner
  exit 127
fi
if ! REPO_ROOT=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null); then
  echo "Error: run_omp.sh must be invoked inside a Git repository." >&2
  exit 2
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "run_omp.sh requires Python >= 3.10 (repo floor); found $(python3 -c 'import sys; print(\"%d.%d\" % sys.version_info[:2])')" >&2
  exit 2
fi

WRITE_MODE="${ELVES_OMP_WRITE:-0}"
MODEL="${ELVES_OMP_MODEL:-}"
PROFILE="elves-omp-shortcut-$$"
MAX_WAIT="${ELVES_OMP_MAX_WAIT_SECONDS:-600}"

exec python3 - "$PROMPT_CONTENT" "$REPO_ROOT" "$WRITE_MODE" "$MODEL" "$PROFILE" "$MAX_WAIT" "$SCRIPT_DIR" <<'PY'
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

prompt, repo_root_s, write_mode, model, profile, max_wait_s, script_dir = sys.argv[1:8]
repo_root = Path(repo_root_s).resolve()
try:
    max_wait = int(max_wait_s)
except ValueError as exc:
    raise SystemExit("Error: ELVES_OMP_MAX_WAIT_SECONDS must be an integer.") from exc
if max_wait < 1:
    raise SystemExit("Error: ELVES_OMP_MAX_WAIT_SECONDS must be >= 1.")

if write_mode in {"1", "true", "yes", "yolo"}:
    raise SystemExit(
        "Error: ELVES_OMP_WRITE is not supported on the omp shortcut. "
        "Use the parked full-run omp-cli worker for implementation labor."
    )

sys.path.insert(0, str(Path(script_dir).resolve()))
from cobbler_runtime.isolation import (
    IsolationSpec,
    context_bundle_report,
    isolated_lane,
    wrap_argv_with_sandbox,
)
from cobbler_runtime.review_routes import (
    classify_review_route_failure,
    route_unavailable_directive,
)
from cobbler_runtime.schema import ValidationIssue


def _route_unavailable(status: int, text: str = "") -> None:
    """omp is an optional review route; tell the host driver to reroute."""
    if status == 0:
        return
    reason = classify_review_route_failure(exit_code=status, text=text) or "provider"
    print(route_unavailable_directive("omp", reason), file=sys.stderr)


def _route_exit(message: str, reason: str, status: int = 2) -> None:
    """Report an optional-route failure, then exit. Never a silent hard stop."""
    print(message, file=sys.stderr)
    print(route_unavailable_directive("omp", reason), file=sys.stderr)
    raise SystemExit(status)


omp = shutil.which("omp")
if not omp:
    _route_exit("Error: omp CLI not found.", "runner", 127)

parent = dict(os.environ)
parent_path = parent.get("PATH", "/usr/bin:/bin")

# Map model pin (or ambient key uniqueness) to a single provider credential grant.
PROVIDER_KEYS = {
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN"),
    "openai": ("OPENAI_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "grok": ("XAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "zai": ("ZAI_API_KEY",),
    "minimax": ("MINIMAX_API_KEY",),
    "cerebras": ("CEREBRAS_API_KEY",),
}


def resolve_credential(model_id: str) -> tuple[str, str]:
    model_l = (model_id or "").strip().lower()
    family = model_l.split("/", 1)[0] if model_l else ""
    if family in PROVIDER_KEYS:
        for name in PROVIDER_KEYS[family]:
            value = parent.get(name, "")
            if value:
                return name, value
        _route_exit(
            f"Error: model `{model_id}` requires one of "
            f"{', '.join(PROVIDER_KEYS[family])} in the environment.",
            "authentication",
        )
    present = [
        (name, parent[name])
        for names in PROVIDER_KEYS.values()
        for name in names
        if parent.get(name)
    ]
    # de-dupe by name
    seen: dict[str, str] = {}
    for name, value in present:
        seen[name] = value
    if len(seen) == 1:
        name, value = next(iter(seen.items()))
        return name, value
    if not seen:
        _route_exit(
            "Error: set ELVES_OMP_MODEL=provider/model and the matching provider API key "
            "(e.g. GEMINI_API_KEY).",
            "authentication",
        )
    _route_exit(
        "Error: multiple provider API keys present; set ELVES_OMP_MODEL to select one "
        f"(found: {', '.join(sorted(seen))}).",
        "unconfigured",
    )


credential_name, credential_value = resolve_credential(model)

try:
    with isolated_lane(
        IsolationSpec(
            repo_root=repo_root,
            lane_id=f"omp-shortcut-{os.getpid()}",
            include_instructions_as_data=True,
            credential_grants={credential_name: credential_value},
            base_env={"PATH": parent_path, "LANG": parent.get("LANG", "C.UTF-8")},
            require_fs_sandbox=True,
        )
    ) as lane:
        for line in context_bundle_report(lane, label="omp"):
            print(line, file=sys.stderr)
        home = lane.home
        # Empty tools dir so omp does not scan host Claude binary trees.
        claude_tools = home / ".claude" / "tools"
        claude_tools.mkdir(parents=True, mode=0o700)

        argv = [
            str(Path(omp).resolve()),
            "--mode",
            "json",
            "--cwd",
            str(lane.snapshot),
            "--profile",
            profile,
            "--approval-mode",
            "always-ask",
            "--thinking",
            "medium",
        ]
        if model.strip():
            argv.extend(["--model", model.strip()])
        argv.append(prompt)

        lane.env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "OMP_PROFILE": profile,
                "PI_PROFILE": profile,
                credential_name: credential_value,
            }
        )
        command = wrap_argv_with_sandbox(argv, lane, mount_proc=False)

        def _alarm(signum, frame):
            raise TimeoutError(f"omp shortcut exceeded {max_wait}s wall")

        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(max_wait)
        try:
            proc = subprocess.run(
                command,
                cwd=str(lane.snapshot),
                env=lane.env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)

        # Validate JSONL when present; exit zero alone is insufficient.
        stdout = proc.stdout or ""
        if proc.returncode == 0 and stdout.strip():
            try:
                from cobbler_runtime.adapters import decode_omp_jsonl

                decode_omp_jsonl(stdout)
            except Exception as exc:  # noqa: BLE001 — surface decoder as nonzero exit
                sys.stderr.write(f"omp shortcut transport invalid: {exc}\n")
                if stdout:
                    sys.stdout.write(stdout)
                _route_unavailable(2, f"transport invalid: {exc}")
                raise SystemExit(2) from exc
        if stdout:
            sys.stdout.write(stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        _route_unavailable(proc.returncode, proc.stderr or "")
        raise SystemExit(proc.returncode)
except ValidationIssue as exc:
    _route_unavailable(2, f"{exc.code}: {exc.message}")
    raise SystemExit(f"Error: omp shortcut isolation failed: {exc}") from exc
except TimeoutError as exc:
    _route_unavailable(124, str(exc))
    raise SystemExit(str(exc)) from exc
PY
