# Shared helpers for the container scenarios in test/scenarios/*.sh.
# Sourced INSIDE a fresh clean-room container (see test/run-scenarios.sh):
#   /src                      read-only podium working tree (uncommitted changes included)
#   CLAUDE_CODE_OAUTH_TOKEN   set when the scenario declares `# needs: claude`
#   OpenCode credentials      imported when the scenario declares `# needs: opencode`
set -u

pass=0; fail=0
ok()   { echo "PASS  $1"; pass=$((pass + 1)); }
bad()  { echo "FAIL  $1"; fail=$((fail + 1)); }
# check "<name>" "<shell condition>"   (the condition runs with eval; output hidden)
check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
section() { echo; echo "== $*"; }
finish() { echo; echo "RESULT: $pass passed, $fail failed"; [ "$fail" -eq 0 ]; }

export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$PATH"
export PODIUM_TOML="$HOME/.config/podium/podium.toml"
export RUNTIME_JSON="$HOME/.config/podium/runtime.json"
export STATE_DIR="$HOME/.local/state/podium"
export PLUGIN_CACHE="$HOME/.claude/plugins"
cd "$HOME"

# Snapshot the working tree as a commit so install.sh (which clones) installs exactly it.
bootstrap() {
  rm -rf /tmp/podium-src && mkdir -p /tmp/podium-src
  (cd /src && tar --exclude=.codegraph --exclude=test/.out -cf - .) | (cd /tmp/podium-src && tar -xf -)
  git -C /tmp/podium-src -c user.name=t -c user.email=t@t add -A >/dev/null
  git -C /tmp/podium-src -c user.name=t -c user.email=t@t commit -qm "scenario snapshot" --allow-empty >/dev/null
  PODIUM_REPO_URL=/tmp/podium-src PODIUM_REF="$(git -C /tmp/podium-src rev-parse --abbrev-ref HEAD)" \
    sh /tmp/podium-src/install.sh >/tmp/bootstrap.log 2>&1
  command -v podium >/dev/null || { echo "bootstrap failed:"; cat /tmp/bootstrap.log; exit 1; }
}

# podium_init '<answers json>'  (nested or dotted keys; see INSTALL.md)
podium_init() {
  printf '%s\n' "$1" > /tmp/answers.json
  podium init --non-interactive --answers /tmp/answers.json
}

# Default answers: English, every module but memory, given preset (default claude-only).
default_answers() {
  printf '{"language":{"response":"en","domain":"en","ui":"%s"},"modules":["rules","executors","codegraph","usage","upgrade"],"roster_preset":"%s","memory":{"url":""}}' \
    "${2:-en}" "${1:-claude-only}"
}

# Set a key in runtime.json-backed config by editing podium.toml with python (TOML append).
# toml_append '<toml text>'  appends raw TOML to podium.toml (for extra tables).
toml_append() { printf '\n%s\n' "$1" >> "$PODIUM_TOML"; }

# Path of an installed plugin file: plugin_file <plugin> <relative path>
plugin_file() {
  find "$PLUGIN_CACHE" -path "*/$1/*" -path "*/$2" -type f 2>/dev/null | head -n 1
}

# Feed a hook script the given JSON on stdin with the installed plugin's python.
# run_hook <plugin> <script relpath> '<json>'  -> prints stdout
run_hook() {
  script=$(plugin_file "$1" "$2")
  [ -n "$script" ] || { echo "HOOK-NOT-FOUND $1/$2"; return 1; }
  printf '%s' "$3" | python3 "$script"
}

# A project with a manifest that CodeGraph does not index.
make_project() {
  mkdir -p "$1" && printf '{"name":"%s"}\n' "$(basename "$1")" > "$1/package.json"
}

# claude_p "<prompt>" [extra args...]  -> stdout of a real non-interactive session
claude_p() {
  prompt=$1; shift
  claude -p "$prompt" "$@" 2>&1
}
