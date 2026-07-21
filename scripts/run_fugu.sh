#!/bin/bash
# Project-aware, read-only review through the official Sakana codex-fugu launcher.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: run_fugu.sh [--deep|--ultra] [--] [review task...]

Profiles:
  default   fugu at high effort for routine repository review
  --deep    fugu at xhigh effort for harder repository review
  --ultra   fugu-ultra at high effort for compact, high-stakes review

With no task, reviews the current repository changes. A single existing file is
treated as a focus hint; codex-fugu still inspects the repository directly.
EOF
}

PROFILE="routine"
TASK_ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --deep)
      if [ "$PROFILE" != "routine" ]; then
        echo "Error: choose only one Fugu profile." >&2
        exit 2
      fi
      PROFILE="deep"
      shift
      ;;
    --ultra)
      if [ "$PROFILE" != "routine" ]; then
        echo "Error: choose only one Fugu profile." >&2
        exit 2
      fi
      PROFILE="ultra"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      TASK_ARGS+=("$@")
      break
      ;;
    -*)
      echo "Error: unknown Fugu option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      TASK_ARGS+=("$@")
      break
      ;;
  esac
done

if ! command -v codex-fugu >/dev/null 2>&1; then
  echo "Error: codex-fugu is not installed or is not on PATH." >&2
  echo "Install it from https://console.sakana.ai/get-started" >&2
  exit 127
fi
if ! REPO_ROOT=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null); then
  echo "Error: run_fugu.sh must be invoked inside a Git repository." >&2
  exit 2
fi

case "$PROFILE" in
  routine)
    MODEL="fugu"
    EFFORT="high"
    DEFAULT_MAX_WAIT="600"
    ;;
  deep)
    MODEL="fugu"
    EFFORT="xhigh"
    DEFAULT_MAX_WAIT="1200"
    ;;
  ultra)
    MODEL="fugu-ultra"
    EFFORT="high"
    DEFAULT_MAX_WAIT="1800"
    ;;
esac
MAX_WAIT="${SAKANA_FUGU_MAX_WAIT_SECONDS:-$DEFAULT_MAX_WAIT}"

if [ "${#TASK_ARGS[@]}" -eq 0 ]; then
  TASK="Review the current repository changes against their appropriate base."
elif [ "${#TASK_ARGS[@]}" -eq 1 ] && [ -f "${TASK_ARGS[0]}" ]; then
  FOCUS_DIR=$(cd "$(dirname "${TASK_ARGS[0]}")" && pwd -P)
  FOCUS_FILE="$FOCUS_DIR/$(basename "${TASK_ARGS[0]}")"
  TASK="Review $FOCUS_FILE in the context of the entire repository."
else
  TASK="${TASK_ARGS[*]}"
fi

TODAY=$(date +%F)
PROMPT="You are an independent Sakana Fugu repository reviewer. Today is $TODAY.

Work inside the repository at $REPO_ROOT. Inspect the project directly with read-only commands;
do not ask the caller to paste files or limit yourself to one supplied file. Read and follow the
applicable AGENTS.md and SKILL.md instructions. Do not edit files, create commits, push, merge,
change refs, install software, or run commands that mutate the repository or external systems.
Do not open credential stores, .env files, authentication files, or other secret-bearing files,
and never print secret values.

Review task: $TASK

Return actionable findings first, ordered P0 through P3, with exact file and line references,
concrete failure scenarios, and the smallest safe repair. If there are no actionable findings,
say exactly \"No actionable findings\" and list only residual verification risks."

exec python3 - "$MAX_WAIT" "$REPO_ROOT" "$MODEL" "$EFFORT" "$PROMPT" <<'PY'
import math
import os
import signal
import subprocess
import sys


try:
    max_wait = float(sys.argv[1])
except ValueError as exc:
    raise SystemExit("Error: SAKANA_FUGU_MAX_WAIT_SECONDS must be numeric.") from exc
if not math.isfinite(max_wait) or max_wait <= 0:
    raise SystemExit("Error: SAKANA_FUGU_MAX_WAIT_SECONDS must be finite and positive.")

repo_root, model, effort, prompt = sys.argv[2:6]
command = [
    "codex-fugu",
    "--no-update",
    "--model",
    model,
    "--config",
    f'model_reasoning_effort="{effort}"',
    "--sandbox",
    "read-only",
    "--ask-for-approval",
    "never",
    "--cd",
    repo_root,
    "exec",
    "--ephemeral",
    "--color",
    "never",
    "-",
]
child_env = os.environ.copy()
child_env["CODEX_FUGU_NO_NOTICE"] = "1"
child_env["CODEX_FUGU_NO_UPDATE"] = "1"

process = subprocess.Popen(
    command,
    env=child_env,
    stdin=subprocess.PIPE,
    text=True,
    start_new_session=True,
)
try:
    process.communicate(prompt, timeout=max_wait)
except subprocess.TimeoutExpired:
    print(
        f"Error: codex-fugu {model}/{effort} review exceeded {max_wait:g}s; terminating it.",
        file=sys.stderr,
    )
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    raise SystemExit(124)

raise SystemExit(process.returncode)
PY
