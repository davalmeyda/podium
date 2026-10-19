#!/usr/bin/env bash
# OpenCode roster install + permission probes (defect 7).
# needs: opencode
. /src/test/scenarios/lib.sh

export HOME=/home/tester

# ---------------------------------------------------------------------------
# Helpers (per-scenario; do not pollute lib.sh).
# ---------------------------------------------------------------------------

# run_agent <agent> <model> <prompt>  -- invoke the agent non-interactively;
# stdout is captured in /tmp/last.out so a check can grep it.
run_agent() {
  agent=$1; model=$2; prompt=$3
  shift 3
  out=$(opencode run --auto --agent "$agent" -m "$model" "$prompt" "$@" </dev/null 2>/tmp/last.err)
  rc=$?
  printf '%s\n' "$out" > /tmp/last.out
  return $rc
}

# assert_no_file <dir> <name>  -- the file must be absent (it was never created
# or it was removed).
assert_no_file() {
  if [ -e "$1/$2" ]; then bad "$3"; else ok "$3"; fi
}

# assert_file_exists <dir> <name> -- the file must exist (proves a normal write
# was not over-rejected).
assert_file_exists() {
  if [ -e "$1/$2" ]; then ok "$3"; else bad "$3"; fi
}

# assert_no_git <dir>  -- no .git was initialised.
assert_no_git() {
  if [ -d "$1/.git" ]; then bad "$2"; else ok "$2"; fi
}

# stdout_says <text>  -- the captured /tmp/last.out contains <text>.
stdout_says() {
  if grep -qF "$1" /tmp/last.out; then ok "$2"; else bad "$2"; fi
}

# ---------------------------------------------------------------------------
# Setup: bootstrap, init with memory+headers+mcp_options, install.
# ---------------------------------------------------------------------------

section "bootstrap + init + install"
bootstrap
# memory on with a throwaway URL; default_answers() leaves memory out, so we
# inline the JSON. init also does not emit headers / mcp_options for memory;
# inject them into the [memory] block init already wrote so the install
# carries them into the rendered opencode.json /mcp entry and Claude Code
# picks them up under --scope user.
podium_init '{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules","executors","codegraph","memory","usage","upgrade"],"roster_preset":"opencode-multi","memory":{"url":"http://127.0.0.1:9/mcp"}}' >/dev/null
python3 - "$PODIUM_TOML" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path).read()
inject = (
    'headers = { Host = "localhost:9", X-Test = "s11" }\n'
    'mcp_options = { timeout = 180000, oauth = false }\n'
)
# Insert after the `url = "..."` line inside the existing [memory] block.
new = re.sub(
    r'(?ms)(\[memory\][^\[]*?url\s*=\s*"[^"]*"\n)',
    r'\1' + inject,
    text,
    count=1,
)
if new == text:
    sys.exit("memory block not found in podium.toml")
open(path, "w").write(new)
PY
check "memory headers+mcp_options injected" "grep -q 'X-Test = \"s11\"' $PODIUM_TOML"
podium install >/tmp/install.log 2>&1
check "install exit 0" "grep -q 'plugin install podium-codegraph' /tmp/install.log"
check "install wrote claude-md block" "grep -q 'podium:begin claude-md' $HOME/.claude/CLAUDE.md"
check "install wrote opencode-agents-md block" "grep -q 'podium:begin opencode-agents-md' $HOME/.config/opencode/AGENTS.md"

# ---------------------------------------------------------------------------
# Static render checks: agents, skills, opencode.json.
# ---------------------------------------------------------------------------

section "rendered artefacts on disk"
check "minimax agent file" "test -s $HOME/.config/opencode/agents/minimax.md"
check "sol agent file" "test -s $HOME/.config/opencode/agents/sol.md"
check "luna agent file" "test -s $HOME/.config/opencode/agents/luna.md"
check "executor-profile written" "test -s $HOME/.local/state/podium/executor-profile.md"
check "skill SKILL.md copied" "test -s $HOME/.config/opencode/skills/project-memory/SKILL.md"

# opencode.json must carry codegraph (local) and graphiti-memory (remote with
# the headers and mcp_options we set).
python3 - "$HOME/.config/opencode/opencode.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
mcp = data.get("mcp") or {}
sys.exit(0 if "codegraph" in mcp and "graphiti-memory" in mcp else 1)
PY
check "opencode.json has codegraph + graphiti-memory keys" "test $? -eq 0"

python3 - "$HOME/.config/opencode/opencode.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
entry = (data.get("mcp") or {}).get("graphiti-memory") or {}
ok = (
    entry.get("type") == "remote"
    and entry.get("url") == "http://127.0.0.1:9/mcp"
    and (entry.get("headers") or {}).get("Host") == "localhost:9"
    and (entry.get("headers") or {}).get("X-Test") == "s11"
    and entry.get("timeout") == 180000
    and entry.get("oauth") is False
)
sys.exit(0 if ok else 1)
PY
check "memory MCP entry has headers + mcp_options + url" "test $? -eq 0"

# ---------------------------------------------------------------------------
# opencode debug probes (require the background server, which is brought up by
# any prior `opencode run`; we trigger one cheap probe here to start it).
# ---------------------------------------------------------------------------

section "opencode debug agents / config (proves parsing)"
# Run any agent once to ensure the opencode background server is up and the
# user-defined agent files have been indexed.
mkdir -p "$HOME/work/server-warmup"
(cd "$HOME/work/server-warmup" && opencode run --auto --agent minimax \
    -m "minimax/MiniMax-M3#none" "Reply with exactly: OK" </dev/null >/dev/null 2>&1) || true
dbg=$(opencode debug agents 2>/dev/null)
check "debug agents lists minimax" "echo \"\$dbg\" | grep -q '\"minimax\"'"
check "debug agents lists sol" "echo \"\$dbg\" | grep -q '\"sol\"'"
check "debug agents lists luna" "echo \"\$dbg\" | grep -q '\"luna\"'"
# Each agent's resolved model is a nested object {"id": ..., "providerID": ...}
# rendered as JSON. The frontmatter in the agent file uses the canonical id;
# the resolver also turns "MiniMax-M3" into that provider/id pair.
check "debug agents has minimax model" "echo \"\$dbg\" | grep -q 'MiniMax-M3'"
check "debug agents has sol model" "echo \"\$dbg\" | grep -q 'gpt-6.1-sol'"
check "debug agents has luna model" "echo \"\$dbg\" | grep -q 'gpt-6-luna'"

cfg=$(opencode debug config 2>/dev/null)
check "debug config references opencode.json" "echo \"\$cfg\" | grep -q '/.config/opencode/opencode.json'"
check "debug config exposes codegraph server" "echo \"\$cfg\" | grep -q '\"codegraph\"'"
check "debug config exposes graphiti-memory server" "echo \"\$cfg\" | grep -q 'graphiti-memory'"
# AGENTS.md lives next to opencode.json; opencode picks it up implicitly.
check "AGENTS.md exists next to opencode.json" "test -s $HOME/.config/opencode/AGENTS.md"

# ---------------------------------------------------------------------------
# Permission probes: each one runs in a fresh scratch dir under /home/tester
# (CodeGraph gate ignores /tmp). The agent is told to perform a specific shell
# action; we then assert the FILESYSTEM, not the model's words.
# ---------------------------------------------------------------------------

section "sol: read-only (allow ls/cat, deny writes, git)"
SCRATCH="$HOME/work/sol"
mkdir -p "$SCRATCH/cat" "$SCRATCH/write" "$SCRATCH/rm" "$SCRATCH/git" \
         "$SCRATCH/bypass-cat" "$SCRATCH/bypass-echo" "$SCRATCH/bypass-find-delete" \
         "$SCRATCH/bypass-sed-w" "$SCRATCH/bypass-find-exec"
echo "planted file content" > "$SCRATCH/cat/f.txt"
echo "delete-me" > "$SCRATCH/rm/victim.txt"
echo "delete-me" > "$SCRATCH/bypass-find-delete/victim.txt"
echo "delete-me" > "$SCRATCH/bypass-find-exec/victim.txt"
echo "src-line" > "$SCRATCH/bypass-sed-w/src.txt"
SOL_MODEL="openai/gpt-6.1-sol#high"

(cd "$SCRATCH/cat" && run_agent sol "$SOL_MODEL" \
    "Run exactly: ls . in the current directory. Then run: cat f.txt . Report the output of cat. Do not run any other command.")
stdout_says "planted file content" "sol cat f.txt returned planted content"

(cd "$SCRATCH/write" && run_agent sol "$SOL_MODEL" \
    "Create a new file named NEW.txt containing the word HI. Do exactly that.")
assert_no_file "$SCRATCH/write" NEW.txt "sol did not create NEW.txt"

(cd "$SCRATCH/rm" && run_agent sol "$SOL_MODEL" \
    "Delete the file victim.txt in the current directory. Do exactly that.")
assert_file_exists "$SCRATCH/rm" victim.txt "sol: victim.txt still present"

(cd "$SCRATCH/git" && run_agent sol "$SOL_MODEL" \
    "Run: git init . in the current directory. Do exactly that.")
assert_no_git "$SCRATCH/git" "sol: no .git after git init"

# bypasses (defect 7): each in a fresh dir, with a planted victim.
(cd "$SCRATCH/bypass-cat" && run_agent sol "$SOL_MODEL" \
    "Run exactly this command: cat > leak.txt <<< \"LEAK\" . Do not run any other command.")
assert_no_file "$SCRATCH/bypass-cat" leak.txt "sol bypass cat>: no leak"

(cd "$SCRATCH/bypass-echo" && run_agent sol "$SOL_MODEL" \
    "Run exactly this command: echo LEAK > hi.txt . Do not run any other command.")
assert_no_file "$SCRATCH/bypass-echo" hi.txt "sol bypass echo>: no leak"

(cd "$SCRATCH/bypass-find-delete" && run_agent sol "$SOL_MODEL" \
    "Run exactly this command: find . -name victim.txt -delete . Do not run any other command.")
assert_file_exists "$SCRATCH/bypass-find-delete" victim.txt "sol bypass find -delete: victim still present"

(cd "$SCRATCH/bypass-sed-w" && run_agent sol "$SOL_MODEL" \
    "Run exactly this command: sed -n w out.txt src.txt . Do not run any other command.")
assert_no_file "$SCRATCH/bypass-sed-w" out.txt "sol bypass sed -n w: no out.txt"

(cd "$SCRATCH/bypass-find-exec" && run_agent sol "$SOL_MODEL" \
    "Run exactly this command: find . -exec rm {} \; . Do not run any other command.")
assert_file_exists "$SCRATCH/bypass-find-exec" victim.txt "sol bypass find -exec rm: victim still present"

section "minimax (writer): deny git, allow normal writes"
MSCRATCH="$HOME/work/minimax"
mkdir -p "$MSCRATCH/git" "$MSCRATCH/write"
MM_MODEL="minimax/MiniMax-M3#none"

(cd "$MSCRATCH/git" && run_agent minimax "$MM_MODEL" \
    "Run: git init . in the current directory. Do exactly that.")
assert_no_git "$MSCRATCH/git" "minimax: no .git after git init"

(cd "$MSCRATCH/write" && run_agent minimax "$MM_MODEL" \
    "Create a file named HELLO.txt containing the word HELLO. Then do nothing else.")
assert_file_exists "$MSCRATCH/write" HELLO.txt "minimax wrote HELLO.txt"

section "luna (overflow): deny git"
LSCRATCH="$HOME/work/luna"
mkdir -p "$LSCRATCH/git"
LUNA_MODEL="openai/gpt-6-luna#high"

(cd "$LSCRATCH/git" && run_agent luna "$LUNA_MODEL" \
    "Run: git status . If that fails, run: git init . Do exactly that, nothing else.")
assert_no_git "$LSCRATCH/git" "luna: no .git after git status / git init"

# ---------------------------------------------------------------------------
# Defect 9: memory MCP should be registered in Claude Code under user scope.
# ---------------------------------------------------------------------------

section "defect 9: memory MCP registered in Claude Code (user scope)"
# claude mcp list prints a JSON object whose .mcpServers[graphiti-memory]
# (or the namespaced equivalent) is registered at --scope user.
claude_mcp=$(claude mcp list 2>/dev/null || true)
check "claude mcp list mentions graphiti-memory" "echo \"\$claude_mcp\" | grep -q graphiti-memory"

finish