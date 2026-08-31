#!/bin/bash
# General and review tasks through the official Sakana codex-fugu launcher.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

usage() {
  cat <<'EOF'
Usage:
  run_fugu.sh [--deep|--ultra|--max] [--max-wait SECONDS] [--preflight]
              [--include PATH]... [--] <task...>
  run_fugu.sh [--deep|--cyber|--ultra|--max] [--max-wait SECONDS] [--preflight]
              [--include PATH]... review [scope...]

Profiles:
  default   fugu at high effort (10m wall) — prefer this first
  --deep    fugu at xhigh effort (20m wall)
  --cyber   fugu-cyber at xhigh effort for read-only security review (20m)
  --ultra   fugu-ultra-v1.1 at high effort with exact-session synthesis (30m)
  --max     fugu-ultra-v1.1 at max effort with exact-session synthesis and a
            long wall budget (60m), for one narrow high-stakes gate

Modes:
  task      The default. Follow the requested task without a review-only rubric.
  review    Read-only change review with ordered P0-P3 findings and exact locations.
  --preflight
            Validate launcher, profile, wall, read-only policy, and --include
            paths, then print a launch plan and exit without calling the provider.
  --max-wait SECONDS
            Cap the hard wall clock for this launch (also via
            SAKANA_FUGU_MAX_WAIT_SECONDS). Prefer this over upgrading to --deep
            when the task is narrow but the default plain wall is too short.

Safe non-ignored worktree files are eligible context by default. --include names an
exact additional repository file for the safety layer to admit or reject. Gitignored
paths fail closed before the provider launches. Use -- to treat a task beginning
with the word "review" as a general task.
EOF
}

PROFILE="routine"
MODE="task"
WRITE_MODE="0"
PREFLIGHT_MODE="0"
MAX_WAIT_OVERRIDE=""
INCLUDE_PATHS=()
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
    --cyber)
      if [ "$PROFILE" != "routine" ]; then
        echo "Error: choose only one Fugu profile." >&2
        exit 2
      fi
      PROFILE="cyber"
      shift
      ;;
    --max)
      if [ "$PROFILE" != "routine" ]; then
        echo "Error: choose only one Fugu profile." >&2
        exit 2
      fi
      PROFILE="max"
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
    --max-wait)
      if [ "$#" -lt 2 ]; then
        echo "Error: --max-wait requires a positive number of seconds." >&2
        exit 2
      fi
      MAX_WAIT_OVERRIDE="$2"
      shift 2
      ;;
    --preflight)
      PREFLIGHT_MODE="1"
      shift
      ;;
    --include)
      if [ "$#" -lt 2 ]; then
        echo "Error: --include requires one repository path." >&2
        exit 2
      fi
      INCLUDE_PATHS+=("$2")
      shift 2
      ;;
    --write)
      WRITE_MODE="1"
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
    review)
      MODE="review"
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

if [ "$WRITE_MODE" = "1" ]; then
  echo "Error: Fugu is limited to planning and read-only review; remove --write." >&2
  exit 2
fi

if [ "$PROFILE" = "cyber" ] && [ "$MODE" != "review" ]; then
  echo "Error: --cyber is only available for read-only review mode." >&2
  exit 2
fi

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
  cyber)
    MODEL="fugu-cyber"
    EFFORT="xhigh"
    DEFAULT_MAX_WAIT="1200"
    ;;
  ultra)
    MODEL="fugu-ultra-v1.1"
    EFFORT="high"
    DEFAULT_MAX_WAIT="1800"
    ;;
  max)
    MODEL="fugu-ultra-v1.1"
    EFFORT="max"
    DEFAULT_MAX_WAIT="3600"
    ;;
esac
if [ -n "$MAX_WAIT_OVERRIDE" ]; then
  MAX_WAIT="$MAX_WAIT_OVERRIDE"
else
  MAX_WAIT="${SAKANA_FUGU_MAX_WAIT_SECONDS:-$DEFAULT_MAX_WAIT}"
fi

if [ "$MODE" = "review" ] && [ "${#TASK_ARGS[@]}" -eq 0 ]; then
  TASK="Review the current repository changes against their appropriate base."
elif [ "${#TASK_ARGS[@]}" -eq 0 ]; then
  echo "Error: a general Fugu task is required. Use 'review' for the review workflow." >&2
  usage >&2
  exit 2
else
  TASK="${TASK_ARGS[*]}"
fi

TODAY=$(date +%F)
PYTHON_ARGS=(
  "$MAX_WAIT" "$PREFLIGHT_MODE" "$REPO_ROOT" "$MODEL" "$EFFORT" "$MODE" "$WRITE_MODE"
  "$TASK" "$TODAY" "$SCRIPT_DIR" "$PROFILE"
)
if [ "${#INCLUDE_PATHS[@]}" -gt 0 ]; then
  PYTHON_ARGS+=("${INCLUDE_PATHS[@]}")
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "run_fugu.sh requires Python >= 3.10 (repo floor); found $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" >&2
  exit 2
fi
FUGU_PY="$SCRIPT_DIR/cobbler_runtime/fugu.py"
if [ ! -f "$FUGU_PY" ]; then
  echo "Error: missing Fugu module: $FUGU_PY" >&2
  exit 2
fi
exec python3 "$FUGU_PY" "${PYTHON_ARGS[@]}"
