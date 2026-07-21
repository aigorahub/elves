#!/bin/bash
# Private Manus research with optional Cobbler-managed Wide Research orchestration.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
exec python3 "$SCRIPT_DIR/cobbler_runtime/manus.py" "$@"
