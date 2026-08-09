#!/bin/bash
# Bounded headless Oh My Pi (omp) one-shot for Elves provider shortcuts.
# CLI spelling is always `omp` (never opm). Read-only by default.
# Isolation: private HOME/XDG tree; never ambient host agent roots.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
PROMPT_CONTENT="$*"
if [ -z "$PROMPT_CONTENT" ]; then
  echo "Usage: run_omp.sh <instructions>" >&2
  exit 2
fi
if ! command -v omp >/dev/null 2>&1; then
  echo "Error: omp (Oh My Pi) CLI not found on PATH." >&2
  exit 127
fi
if ! REPO_ROOT=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null); then
  echo "Error: run_omp.sh must be invoked inside a Git repository." >&2
  exit 2
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "run_omp.sh requires Python >= 3.10 (repo floor); found $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" >&2
  exit 2
fi

WRITE_MODE="${ELVES_OMP_WRITE:-0}"
MODEL="${ELVES_OMP_MODEL:-}"
PROFILE="elves-omp-shortcut-$$"
MAX_WAIT="${ELVES_OMP_MAX_WAIT_SECONDS:-600}"

exec python3 - "$PROMPT_CONTENT" "$REPO_ROOT" "$WRITE_MODE" "$MODEL" "$PROFILE" "$MAX_WAIT" <<'PY'
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

prompt, repo_root, write_mode, model, profile, max_wait_s = sys.argv[1:7]
try:
    max_wait = int(max_wait_s)
except ValueError as exc:
    raise SystemExit("Error: ELVES_OMP_MAX_WAIT_SECONDS must be an integer.") from exc
if max_wait < 1:
    raise SystemExit("Error: ELVES_OMP_MAX_WAIT_SECONDS must be >= 1.")

omp = shutil.which("omp")
if not omp:
    raise SystemExit("Error: omp CLI not found.")

# Private disposable home: deny host HOME / XDG agent roots / ~/.claude/tools.
private = Path(tempfile.mkdtemp(prefix="elves-omp-shortcut-"))
try:
    home = private / "home"
    xdg_config = home / ".config"
    xdg_data = home / ".local" / "share"
    xdg_cache = home / ".cache"
    for path in (home, xdg_config, xdg_data, xdg_cache):
        path.mkdir(parents=True, mode=0o700)

    # Minimal empty tools dir so omp does not inherit host Claude binary tools.
    claude_tools = home / ".claude" / "tools"
    claude_tools.mkdir(parents=True, mode=0o700)

    approval = "yolo" if write_mode in {"1", "true", "yes"} else "always-ask"
    argv = [
        omp,
        "--mode",
        "json",
        "--cwd",
        repo_root,
        "--profile",
        profile,
        "--approval-mode",
        approval,
        "--thinking",
        "medium",
    ]
    if model.strip():
        argv.extend(["--model", model.strip()])
    argv.append(prompt)

    # Allowlist env: path/locale + explicitly present provider API keys only.
    parent = os.environ
    allowed_prefix = (
        "PATH",
        "LANG",
        "LC_",
        "TERM",
        "TMPDIR",
        "TMP",
        "TEMP",
        "USER",
        "LOGNAME",
        "SHELL",
    )
    provider_key_names = (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_OAUTH_TOKEN",
        "OPENAI_API_KEY",
        "XAI_API_KEY",
        "OPENROUTER_API_KEY",
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY",
        "ZAI_API_KEY",
        "MINIMAX_API_KEY",
        "CEREBRAS_API_KEY",
    )
    child_env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_DATA_HOME": str(xdg_data),
        "XDG_CACHE_HOME": str(xdg_cache),
        "OMP_PROFILE": profile,
        "PI_PROFILE": profile,
        "PATH": parent.get("PATH", "/usr/bin:/bin"),
        "LANG": parent.get("LANG", "C.UTF-8"),
    }
    for key, value in parent.items():
        if key in provider_key_names and value:
            child_env[key] = value
        elif key.startswith("LC_") or key in {"TERM", "TMPDIR", "TMP", "TEMP"}:
            child_env[key] = value

    def _alarm(signum, frame):
        raise TimeoutError(f"omp shortcut exceeded {max_wait}s wall")

    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(max_wait)
    try:
        proc = subprocess.run(
            argv,
            cwd=repo_root,
            env=child_env,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
    raise SystemExit(proc.returncode)
finally:
    shutil.rmtree(private, ignore_errors=True)
PY
