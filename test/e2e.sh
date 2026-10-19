#!/usr/bin/env bash
# End-to-end check of a fresh podium install, run INSIDE the clean-room container
# (see test/run.sh). Expects:
#   /src                         read-only git checkout of podium (committed state is what gets installed)
#   CLAUDE_CODE_OAUTH_TOKEN      for `claude -p`
#   OpenCode credentials already imported (test/run.sh does it) when PODIUM_E2E_OPENCODE=1
set -u

pass=0; fail=0
ok()   { echo "PASS  $1"; pass=$((pass + 1)); }
bad()  { echo "FAIL  $1"; fail=$((fail + 1)); }
check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }

export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$PATH"
cd "$HOME"

echo "== bootstrap"
PODIUM_REPO_URL=/src sh /src/install.sh
check "podium on PATH" "command -v podium"
check "podium --help" "podium --help"

echo "== detect"
podium detect --json > /tmp/detect.json
check "detect is valid JSON" "python3 -m json.tool /tmp/detect.json"
check "detect sees claude" "python3 -c 'import json;assert json.load(open(\"/tmp/detect.json\"))[\"tools\"][\"claude\"]'"

echo "== init"
cat > /tmp/answers.json <<'EOF'
{"language": {"response": "en", "domain": "en", "ui": "en"},
 "modules": ["rules", "executors", "codegraph", "usage", "upgrade"],
 "roster_preset": "opencode-multi", "adopt": false}
EOF
podium init --non-interactive --answers /tmp/answers.json
check "podium.toml written" "test -s $HOME/.config/podium/podium.toml"

echo "== install (dry run writes nothing)"
podium install --dry-run > /tmp/plan.txt
check "dry-run left CLAUDE.md absent" "test ! -e $HOME/.claude/CLAUDE.md || ! grep -q 'podium:begin' $HOME/.claude/CLAUDE.md"

echo "== install"
podium install
check "CLAUDE.md has podium block" "grep -q 'podium:begin claude-md' $HOME/.claude/CLAUDE.md"
check "AGENTS.md has podium block" "grep -q 'podium:begin opencode-agents-md' $HOME/.config/opencode/AGENTS.md"
for a in minimax sol luna; do
  check "agent $a rendered" "grep -q '^mode: primary' $HOME/.config/opencode/agents/$a.md"
done
check "runtime.json written" "python3 -m json.tool $HOME/.config/podium/runtime.json"
check "no unrendered template tags" "! grep -rq '{{' $HOME/.claude/CLAUDE.md $HOME/.config/opencode/AGENTS.md $HOME/.config/opencode/agents"
for p in podium-codegraph podium-usage podium-upgrade; do
  check "plugin $p installed" "claude plugin list 2>/dev/null | grep -q $p"
done

echo "== idempotence"
cp $HOME/.claude/CLAUDE.md /tmp/claude-1.md
podium install
check "second install changes nothing" "cmp -s /tmp/claude-1.md $HOME/.claude/CLAUDE.md"
check "podium diff clean" "podium diff"

echo "== doctor"
podium doctor; echo "(doctor exit $?)"

echo "== codegraph gate (real claude session)"
mkdir -p "$HOME/work/demo" && echo '{"name":"demo-app"}' > "$HOME/work/demo/package.json"
cd "$HOME/work/demo"
out=$(claude -p "Read the file package.json in the current directory and print the value of its name field." --allowedTools Read 2>&1 || true)
echo "$out" | tail -5
check "gate blocked the read of an unindexed project" "echo \"\$out\" | grep -qi codegraph"
cd "$HOME"

if [ "${PODIUM_E2E_OPENCODE:-0}" = "1" ]; then
  echo "== executors through OpenCode"
  o=$(opencode run --auto --agent minimax -m "minimax/MiniMax-M3#none" "Reply with exactly: PODIUM_WRITER_OK" </dev/null 2>/tmp/oc.err)
  check "writer agent answers" "echo \"\$o\" | grep -q PODIUM_WRITER_OK"
  o=$(opencode run --auto --agent sol -m "openai/gpt-6.1-sol#high" "Reply with exactly: PODIUM_CONSULTANT_OK" </dev/null 2>/tmp/oc2.err)
  check "consultant agent answers" "echo \"\$o\" | grep -q PODIUM_CONSULTANT_OK"
fi

echo "== uninstall"
podium uninstall
check "block removed from CLAUDE.md" "! grep -q 'podium:begin' $HOME/.claude/CLAUDE.md"
check "agents removed" "test ! -e $HOME/.config/opencode/agents/minimax.md"

check "podium plugins removed" "! claude plugin list 2>/dev/null | grep -q '@podium'"

echo "== existing setup (install on top of the user's files, uninstall gives them back)"
mkdir -p "$HOME/.claude" "$HOME/.config/opencode/agents"
printf '# My rules\n\nkeep me\n' > "$HOME/.claude/CLAUDE.md"
cat > "$HOME/.config/opencode/opencode.json" <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "model": "openai/gpt-6-luna",
  "mcp": {"mine": {"type": "local", "command": ["true"], "enabled": false}}
}
EOF
echo "my own minimax agent" > "$HOME/.config/opencode/agents/minimax.md"
cp "$HOME/.claude/CLAUDE.md" /tmp/mine-claude.md
cp "$HOME/.config/opencode/opencode.json" /tmp/mine-oc.json
podium install > /tmp/conflict.txt 2>&1; code=$?
check "foreign agent refused without --adopt (exit 2)" "[ $code -eq 2 ] && grep -q 'use --adopt' /tmp/conflict.txt"
check "the refused install wrote nothing" "cmp -s /tmp/mine-claude.md $HOME/.claude/CLAUDE.md && cmp -s /tmp/mine-oc.json $HOME/.config/opencode/opencode.json"
podium install --adopt > /tmp/adopt.txt 2>&1
check "user text kept next to the podium block" "grep -q 'keep me' $HOME/.claude/CLAUDE.md && grep -q 'podium:begin claude-md' $HOME/.claude/CLAUDE.md"
check "user opencode.json keys kept, podium keys added" "python3 -c 'import json;d=json.load(open(\"$HOME/.config/opencode/opencode.json\"));assert d[\"model\"]==\"openai/gpt-6-luna\" and \"mine\" in d[\"mcp\"] and \"codegraph\" in d[\"mcp\"]'"
check "adopted agent backed up" "ls $HOME/.config/opencode/agents/ | grep -q 'minimax.md.bak-podium-'"
podium uninstall > /tmp/uninstall2.txt 2>&1
check "CLAUDE.md is the user's original again" "cmp -s /tmp/mine-claude.md $HOME/.claude/CLAUDE.md"
check "opencode.json is the user's original again" "python3 -c 'import json;assert json.load(open(\"/tmp/mine-oc.json\"))==json.load(open(\"$HOME/.config/opencode/opencode.json\"))'"
check "adopted agent restored" "grep -qx 'my own minimax agent' $HOME/.config/opencode/agents/minimax.md"

echo
echo "RESULT: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
