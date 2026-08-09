#!/bin/bash
# Bounded headless Oh My Pi (omp) one-shot for Elves provider shortcuts.
# CLI spelling is always `omp` (never opm). Read-only by default.
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
  echo "run_omp.sh requires Python >= 3.10 (repo floor); found $(python3 -c 'import sys; print(\"%d.%d\" % sys.version_info[:2])')" >&2
  exit 2
fi

# Optional explicit write path requires ELVES_OMP_WRITE=1 (host-authorized only).
WRITE_MODE="${ELVES_OMP_WRITE:-0}"
MODEL="${ELVES_OMP_MODEL:-}"
PROFILE="elves-omp-shortcut-$$"
MAX_WAIT="${ELVES_OMP_MAX_WAIT_SECONDS:-600}"

exec python3 - "$PROMPT_CONTENT" "$REPO_ROOT" "$WRITE_MODE" "$MODEL" "$PROFILE" "$MAX_WAIT" <<'PY'
import os
import signal
import shutil
import subprocess
import sys
import uuid

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

# Deny ambient inheritance of host agent roots by using a run-scoped profile only.
# Do not project wholesale HOME or ~/.claude/tools.
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
# Ephemeral: do not resume ambiguous sessions; no --continue.
argv.append(prompt)

# Strip potentially huge ambient secrets not required; keep only known provider keys
# already present so optional auth works without projecting host agent stores.
parent = dict(os.environ)
# Never pass OMP_PROFILE from host that could collide
parent.pop("OMP_PROFILE", None)
parent.pop("PI_PROFILE", None)

def _alarm(signum, frame):
    raise TimeoutError(f"omp shortcut exceeded {max_wait}s wall")

if hasattr(signal, "SIGALRM"):
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(max_wait)

try:
    proc = subprocess.run(
        argv,
        cwd=repo_root,
        env=parent,
        stdin=subprocess.DEVNULL,
        check=False,
    )
finally:
    if hasattr(signal, "SIGALRM"):
        signal.alarm(0)

raise SystemExit(proc.returncode)
PY
