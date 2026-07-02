#!/usr/bin/env bash
# Install ccpick as a shell quick command.
#
# Adds (or updates) a `ccpick` function in your shell rc (zsh/bash) that runs
# ccpick.py from this folder. Re-runnable: the managed block between the ccpick
# markers is replaced in place.
#
# Usage:
#   ./install.sh              # auto-detect rc from $SHELL (zsh -> ~/.zshrc)
#   ./install.sh --rc PATH    # write to a specific rc file
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$DIR/ccpick.py"
[ -f "$SCRIPT" ] || { echo "ccpick.py not found next to installer: $SCRIPT" >&2; exit 1; }

RC=""
if [ "${1:-}" = "--rc" ] && [ -n "${2:-}" ]; then RC="$2"; fi
if [ -z "$RC" ]; then
  case "$(basename "${SHELL:-}")" in
    zsh)  RC="${ZDOTDIR:-$HOME}/.zshrc" ;;
    bash) RC="$HOME/.bashrc" ;;
    *)    RC="${ZDOTDIR:-$HOME}/.zshrc"; [ -f "$RC" ] || RC="$HOME/.profile" ;;
  esac
fi

command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || \
  echo "warning: no python3/python on PATH; the ccpick function will not run until one exists" >&2

BEGIN='# >>> ccpick >>>'
END='# <<< ccpick <<<'
BLOCK="$BEGIN
# Interactive Claude Code session picker (personal-helpers). Managed by install.sh.
ccpick() {
  if command -v python3 >/dev/null 2>&1; then python3 \"$SCRIPT\" \"\$@\"
  else python \"$SCRIPT\" \"\$@\"; fi
}
$END"

touch "$RC"
# Strip any existing managed block, then append a fresh one.
tmp="$(mktemp)"
awk -v b="$BEGIN" -v e="$END" '
  $0==b {skip=1}
  skip==0 {print}
  $0==e {skip=0}
' "$RC" > "$tmp"
printf '%s\n\n%s\n' "$(cat "$tmp")" "$BLOCK" > "$RC"
rm -f "$tmp"

chmod +x "$DIR/ccpick.sh" 2>/dev/null || true

echo "Installed ccpick function into: $RC"
echo "Reload it with:  source \"$RC\"   (or open a new terminal), then run:  ccpick"
