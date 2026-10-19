#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
echo "== Configured roster and agents"
python3 "$SCRIPT_DIR/roster.py"
detect() {
  tool=$1
  path=$(command -v "$tool" 2>/dev/null || true)
  [ -n "$path" ] || { echo "$tool: not installed"; return; }
  brew_prefix=$(brew --prefix 2>/dev/null || echo /__no_brew__)
  npm_prefix=$(npm prefix -g 2>/dev/null || echo /__no_npm__)
  case "$path" in "$brew_prefix"/*) method=brew ;; "$npm_prefix"/*) method=npm ;; *) method=native ;; esac
  printf '%s: %s [%s]\n' "$tool" "$($tool --version 2>/dev/null || true)" "$method"
}
echo "== CLI versions and install methods"
detect claude
detect opencode
detect codegraph
echo "== Active OpenCode processes"
ps -eo pid,command | awk 'NR == 1 || /opencode/ { print }'
echo "== Latest upgrade history"
state_dir=${PODIUM_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/podium}
latest=$(find "$state_dir/upgrade-history" -type f -name '*.md' -print 2>/dev/null | sort | tail -n 1 || true)
[ -n "$latest" ] && echo "$latest" || echo "(no history)"
