#!/usr/bin/env bash
# Agent-guided install check: a real `claude -p` session is told only
# "install podium from <repo>" and must follow INSTALL.md on its own, inside a
# fresh container. Nothing on the host is modified.
#
#   CLAUDE_TOKEN_FILE   file with a `claude setup-token` token (required)
#   OPENCODE_AUTH_FILE  optional `opencode auth export` JSON (lets the agent pick the multi-provider roster)
#   PODIUM_REPO         repo URL to install from (default: https://github.com/davalmeyda/podium)
#   KEEP=1              keep the container afterwards for inspection
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo_url="${PODIUM_REPO:-https://github.com/davalmeyda/podium}"
name="podium-agent-$(date +%s)"

docker build --build-arg CACHE_BUST="$(date +%s)" -t podium-test:latest "$here/docker" >/dev/null
docker run -d --name "$name" -e CLAUDE_CODE_OAUTH_TOKEN="$(cat "$CLAUDE_TOKEN_FILE")" \
  podium-test:latest sleep infinity >/dev/null
trap '[ "${KEEP:-0}" = 1 ] || docker rm -f "$name" >/dev/null' EXIT

if [ -n "${OPENCODE_AUTH_FILE:-}" ]; then
  docker cp "$OPENCODE_AUTH_FILE" "$name:/tmp/oc.json"
  docker exec -u root "$name" chown tester /tmp/oc.json
  docker exec "$name" bash -c 'opencode auth import /tmp/oc.json >/dev/null && rm -f /tmp/oc.json'
fi

prompt="Install podium from $repo_url. This is a disposable test machine and I am not \
available to answer questions: whenever INSTALL.md says to ask me or to wait for my \
agreement, take the recommended default, state it, and continue. Languages: English. \
When you finish, print the last lines of 'podium doctor'."

docker exec -w /home/tester "$name" bash -c \
  "claude -p \"$prompt\" --dangerously-skip-permissions" || echo "(claude exited with $?)"

echo "== verification"
docker exec "$name" bash -c '
  pass=0; fail=0
  ok()  { echo "PASS  $1"; pass=$((pass + 1)); }
  bad() { echo "FAIL  $1"; fail=$((fail + 1)); }
  check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
  export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$PATH"
  check "podium CLI installed" "command -v podium"
  check "podium.toml written by init" "test -s $HOME/.config/podium/podium.toml"
  check "CLAUDE.md has the podium block" "grep -q \"podium:begin claude-md\" $HOME/.claude/CLAUDE.md"
  check "podium doctor passes" "podium doctor"
  check "podium plugins installed" "claude plugin list 2>/dev/null | grep -q \"@podium\""
  check "no file was hand-edited (diff clean)" "podium diff | grep -q \"no differences\""
  grep -A3 "^\[\[agents\]\]" $HOME/.config/podium/podium.toml | grep "^name" | sed "s/^/roster agent: /"
  echo "RESULT: $pass passed, $fail failed"
  [ "$fail" -eq 0 ]'
