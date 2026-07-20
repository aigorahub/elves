#!/bin/bash
# Headless Grok Build task with bounded, non-bypass permissions.
set -euo pipefail

PROMPT_CONTENT="$*"
if [ -z "$PROMPT_CONTENT" ]; then
  echo "Usage: run_grok.sh <instructions>" >&2
  exit 2
fi
if ! command -v grok >/dev/null 2>&1; then
  echo "Error: Grok Build CLI not found." >&2
  exit 127
fi

exec grok \
  --no-auto-update \
  --cwd "$PWD" \
  --permission-mode dontAsk \
  --reasoning-effort high \
  --output-format plain \
  --check \
  --single "$PROMPT_CONTENT"
