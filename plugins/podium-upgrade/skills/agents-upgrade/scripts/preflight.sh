#!/bin/sh
# preflight.sh - read-only context dump for the /podium-upgrade:agents-upgrade
# skill. No arguments, no side effects. Prints one section per agent / roster
# / history / sessions / versions / install methods so the principal can decide
# what to upgrade without re-running discovery commands.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# ---- shared helpers (kept in sync with update-clis.sh) ---------------------
# Detect install method by package ownership, not by executable location.
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

# ---- 1. Installed agents ---------------------------------------------------
echo "== Installed agents"
agents_dir="$HOME/.config/opencode/agents"
if [ -d "$agents_dir" ]; then
  for f in "$agents_dir"/*.md; do
    [ -f "$f" ] || continue
    # Only files that declare a `model:` line. Files without one are not part
    # of an upgrade comparison.
    if grep -q '^[[:space:]]*model:[[:space:]]' "$f"; then
      # The first `model:` line keeps the full local form (provider, id,
      # variant) so the diff against the roster is readable.
      ml=$(grep -m1 '^[[:space:]]*model:[[:space:]]' "$f")
      printf '%s: %s\n' "$f" "$ml"
    fi
  done
fi

# The installed rules table lives in the Claude block (podium block id
# `claude-md`). We must NOT depend on the rendering conventions of other
# targets; instead we look for the literal podium markers and emit every
# Markdown table row between them, or `(no installed table)` when absent.
claude_md=${CLAUDE_CONFIG_DIR:-$HOME/.claude}/CLAUDE.md
echo "-- Responsibility table (installed rules)"
if [ -f "$claude_md" ]; then
  rows=$(awk '
    /^<!-- podium:begin claude-md -->$/ { in_block=1; next }
    /^<!-- podium:end claude-md -->$/   { in_block=0; next }
    in_block && /^\|/ { print }
  ' "$claude_md")
  if [ -n "$rows" ]; then
    printf '%s\n' "$rows"
  else
    echo "(no installed table)"
  fi
else
  echo "(no installed table)"
fi

# ---- 2. Configured roster -------------------------------------------------
echo "== Configured roster"
python3 "$SCRIPT_DIR/roster.py"

# ---- 3. Latest history report ---------------------------------------------
echo "== Latest history report"
state_dir=${PODIUM_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/podium}
history_dir="$state_dir/upgrade-history"
legacy_dir="$HOME/.claude/skills/agents-upgrade/historial"
latest=""
newest_md() {
  dir=$1
  [ -d "$dir" ] || return 1
  # Pick the lexicographically newest *.md (timestamps from podium are
  # YYYY-MM-DD or YYYY-MM-DDTHH-MM-SS so lex order = chronological order).
  ls -1 "$dir"/*.md 2>/dev/null | sort | tail -n 1
}
if [ -d "$history_dir" ]; then
  latest=$(newest_md "$history_dir" || true)
fi
if [ -z "$latest" ] && [ -d "$legacy_dir" ]; then
  latest=$(newest_md "$legacy_dir" || true)
fi
if [ -n "$latest" ]; then
  echo "$latest"
else
  echo "(no history)"
fi

# ---- 4. Active sessions (excluding the OpenCode service) ------------------
# The OpenCode background service (`opencode serve --service`) sits idle most
# of the time and is not a session the user is actively working in. Including
# it would force an unnecessary "close the session" prompt on every run.
echo "== Active sessions (excluding the OpenCode service)"
# Header row then every line that names opencode or claude, except lines
# containing the OpenCode service marker. POSIX `ps -ef` is the only flag
# universally supported (busybox, alpine, gnu procps).
if command -v ps >/dev/null 2>&1; then
  ps -ef 2>/dev/null \
    | awk '
        NR == 1 { print; next }
        {
          has_opencode = index($0, "opencode") > 0
          has_claude   = index($0, "claude")   > 0
          # "claude" is a substring of "claude-md" / etc., but the second
          # field in `ps` is the command (not the username), and only real
          # executables match; the substring check is the simplest reliable
          # discriminator when no -o command column is available.
          if (has_opencode && index($0, "serve --service")) next
          if (has_opencode || has_claude) print
        }
      '
fi
echo "(end sessions)"

# ---- 5. Versions ----------------------------------------------------------
opencode_version=$(opencode --version 2>/dev/null || true)
claude_version=$(claude --version 2>/dev/null || true)
echo "== Versions"
printf 'opencode: %s\n' "$opencode_version"
printf 'claude: %s\n' "$claude_version"

# ---- 6. Install method ----------------------------------------------------
echo "== Install method"
printf 'opencode: %s\n' "$(method_for opencode)"
printf 'claude: %s\n' "$(method_for claude)"
