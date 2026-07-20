#!/bin/bash
# Read-only, high-effort review through the configured Sakana Fugu Ultra profile.
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "Usage: run_fugu.sh <file>" >&2
  exit 2
fi
if ! command -v codex-fugu >/dev/null 2>&1; then
  echo "Error: codex-fugu is not installed or is not on PATH." >&2
  exit 127
fi
if [ ! -f "$1" ]; then
  echo "Error: review target is not a regular file: $1" >&2
  exit 2
fi

TARGET_DIR=$(cd "$(dirname "$1")" && pwd -P)
TARGET_FILE="$TARGET_DIR/$(basename "$1")"
if REPO_ROOT=$(git -C "$TARGET_DIR" rev-parse --show-toplevel 2>/dev/null); then
  :
else
  REPO_ROOT="$TARGET_DIR"
fi

PROMPT="Perform an independent, read-only, ultra-high-thinking audit of this exact file: $TARGET_FILE

Inspect the file directly. Check correctness, hidden assumptions, security and reliability risks,
edge cases, and missing validation. Report concrete findings first with file/line references,
then residual risks. Do not edit files or run mutating commands."

exec codex-fugu --no-update exec \
  --model fugu-ultra \
  -c 'model_reasoning_effort="xhigh"' \
  --sandbox read-only \
  --ephemeral \
  --color never \
  -C "$REPO_ROOT" \
  "$PROMPT"
