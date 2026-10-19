#!/bin/sh
set -eu
dry_run=0
skip_opencode=0
skip_claude=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --skip-opencode) skip_opencode=1 ;;
    --skip-claude) skip_claude=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
method_for() {
  path=$(command -v "$1" 2>/dev/null || true)
  [ -n "$path" ] || { echo not-installed; return; }
  brew_prefix=$(brew --prefix 2>/dev/null || echo /__no_brew__)
  npm_prefix=$(npm prefix -g 2>/dev/null || echo /__no_npm__)
  case "$path" in "$brew_prefix"/*) echo brew ;; "$npm_prefix"/*) echo npm ;; *) echo native ;; esac
}
update() { if [ "$dry_run" -eq 1 ]; then echo "$1"; else sh -c "$1"; fi; }
before_oc=$(opencode --version 2>/dev/null || true)
before_cl=$(claude --version 2>/dev/null || true)
if [ "$skip_opencode" -eq 0 ]; then
  case "$(method_for opencode)" in
    brew) update 'brew upgrade opencode' ;;
    npm) update 'npm install -g opencode-ai@latest' ;;
    # --major crosses major versions (the official installer still ships 1.x); older builds lack the flag.
    native) update 'opencode upgrade --major || opencode upgrade' ;;
    not-installed) echo 'opencode: not installed' ;;
  esac
fi
if [ "$skip_claude" -eq 0 ]; then
  case "$(method_for claude)" in
    brew) update 'brew upgrade --cask claude-code' ;;
    npm) update 'npm install -g @anthropic-ai/claude-code@latest' ;;
    native) update 'claude update' ;;
    not-installed) echo 'claude: not installed' ;;
  esac
fi
after_oc=$(opencode --version 2>/dev/null || true)
if [ "$dry_run" -eq 0 ] && [ "$skip_opencode" -eq 0 ] && [ "$before_oc" != "$after_oc" ] && opencode service --help >/dev/null 2>&1; then opencode service restart; fi
echo "opencode: $before_oc -> $after_oc"
echo "claude: $before_cl -> $(claude --version 2>/dev/null || true)"
