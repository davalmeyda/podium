#!/bin/sh
# update-clis.sh [--dry-run] [--skip-opencode] [--skip-claude]
#
# Installs or upgrades opencode and claude code. The install method is decided
# by package ownership (npm registry, brew formula, brew cask, native installer),
# never by the location of the executable on PATH. This keeps the behaviour
# predictable when one tool shadows another (e.g. an npm-prefixed claude that
# happens to live inside the brew prefix).
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

# Detect the installed cask name for claude. The cask ships as either
# `claude-code` (older) or `claude-code@latest` (newer Homebrew formulae). The
# contract requires we pass whichever the user has installed to
# `brew upgrade --cask --greedy`.
claude_cask_installed() {
  brew list --cask 2>/dev/null \
    | awk '{ for (i=1; i<=NF; i++) if ($i == "claude-code" || $i == "claude-code@latest") { print $i; exit } }'
}

# Install method decided by package ownership:
#   - missing: the executable is not on PATH
#   - npm:     `npm ls -g --depth=0` lists the package of the same name
#   - brew:    `brew list --formula|cask` shows it (formula or cask)
#   - native:  the executable exists but is not owned by either package manager
# The checks are independent: an npm-installed binary that happens to live
# inside the brew prefix still resolves to npm.
method_for() {
  tool=$1
  path=$(command -v "$tool" 2>/dev/null || true)
  [ -n "$path" ] || { echo missing; return; }
  case "$tool" in
    opencode)
      npm ls -g --depth=0 opencode-ai >/dev/null 2>&1 && { echo npm; return; }
      if brew list --formula opencode >/dev/null 2>&1; then
        echo brew; return
      fi
      echo native
      ;;
    claude)
      npm ls -g --depth=0 @anthropic-ai/claude-code >/dev/null 2>&1 && { echo npm; return; }
      if brew list --cask 2>/dev/null \
            | grep -Eq '^(claude-code|claude-code@latest)$'; then
        echo brew; return
      fi
      echo native
      ;;
    *)
      echo native
      ;;
  esac
}

update() { if [ "$dry_run" -eq 1 ]; then printf '[dry-run] %s\n' "$1"; else sh -c "$1"; fi; }
before_oc=$(opencode --version 2>/dev/null || true)
before_cl=$(claude --version 2>/dev/null || true)

if [ "$skip_opencode" -eq 0 ]; then
  case "$(method_for opencode)" in
    brew) update 'brew upgrade opencode' ;;
    npm) update 'npm install -g opencode-ai@latest' ;;
    # --major crosses major versions (the official installer still ships 1.x);
    # older builds lack the flag, so fall back to a plain upgrade on any
    # failure.
    native) update 'opencode upgrade --major || opencode upgrade' ;;
    missing) echo 'opencode: not installed' ;;
  esac
fi

if [ "$skip_claude" -eq 0 ]; then
  claude_method=$(method_for claude)
  case "$claude_method" in
    brew)
      # Pass whichever cask name Homebrew actually has installed.
      cask=$(claude_cask_installed)
      [ -n "$cask" ] || cask=claude-code
      update "brew upgrade --cask --greedy $cask"
      ;;
    npm) update 'npm install -g @anthropic-ai/claude-code@latest' ;;
    native) update 'claude update' ;;
    missing) echo 'claude: not installed' ;;
  esac
fi

after_oc=$(opencode --version 2>/dev/null || true)
if [ "$dry_run" -eq 0 ] && [ "$skip_opencode" -eq 0 ] \
     && [ "$before_oc" != "$after_oc" ] \
     && opencode service --help >/dev/null 2>&1; then
  opencode service restart
fi
echo "opencode: $before_oc -> $after_oc"
echo "claude: $before_cl -> $(claude --version 2>/dev/null || true)"
