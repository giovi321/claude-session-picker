#!/usr/bin/env bash
# Launcher for ccpick.py. Symlink this onto your PATH (e.g. ~/.local/bin/ccpick)
# and run `ccpick` from anywhere. Passes all arguments through to the script.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || command -v python)"
exec "$PY" "$DIR/ccpick.py" "$@"
