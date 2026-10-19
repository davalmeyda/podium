#!/bin/sh
# Scenario S9: memory-stop hook — synthetic JSONL matrix + one real Stop block.
# Header drives the runner: `# needs: claude` for the real part.
#
# Asserts:
#   * Install with memory + a memory.url, override [memory] stop_hook to
#     { min_edits = 1, min_executor_runs = 2, cooldown_seconds = 0 }, confirm
#     runtime.json carries those values.
#   * Script part: installed memory-stop.py fed stdin with synthetic
#     transcript JSONL covers thresholds (edits 0/1, executor runs 1/2 via the
#     `opencode run ` launcher regex), non-launcher Bash ignored, temp-path
#     edits ignored, reset after <mcp_server>__add_memory, cooldown honoured,
#     stop_hook_active silent, missing transcript silent, exact en+es reason
#     text, state file written.
#   * Real part: `claude -p "Create the file /home/tester/proj/a.txt containing hi"`
#     triggers the Stop hook block exactly once with reason text
#     "Substantial work happened since the last memory save (1 file edits, 0 executor runs)";
#     session ends normally (result line); state file exists.
#   * OpenCode skill copy at ~/.config/opencode/skills/project-memory/SKILL.md
#     equals the plugin's SKILL.md.
#   * opencode.json has /mcp/graphiti-memory with type=remote and the url.
#   * Defect 9 fix: `claude mcp list` and `claude mcp get graphiti-memory`
#     show the server registered at user scope.
# needs: claude
set -u
. /src/test/scenarios/lib.sh

MEM_URL="http://127.0.0.1:9/mcp"

# -----------------------------------------------------------------------------
# Helpers local to this scenario.
# -----------------------------------------------------------------------------

# Find the installed memory-stop.py (placed by `claude plugin install` under
# $PLUGIN_CACHE/cache/podium/podium-memory/<ver>/hooks/memory-stop.py).
hook_script() {
    find "$PLUGIN_CACHE" -path '*/podium-memory/*/hooks/memory-stop.py' -type f 2>/dev/null | head -n 1
}

# tool_use_line <name> <count> <input template>
#   Print a single JSONL assistant line with N tool_use blocks. For Bash the
#   template fills `command`; otherwise it fills `file_path`. %d is replaced.
tool_use_line() {
    python3 -c '
import json, sys
name, count, tmpl = sys.argv[1], int(sys.argv[2]), sys.argv[3]
content = []
for i in range(count):
    if name == "Bash":
        inp = {"command": tmpl.replace("%d", str(i))}
    elif name.endswith("__add_memory"):
        inp = {"name": "save"}
    else:
        inp = {"file_path": tmpl.replace("%d", str(i)), "content": "x"}
    content.append({"type": "tool_use", "name": name, "id": "tu_%d" % i, "input": inp})
print(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": content}}))
' "$1" "$2" "$3"
}

# write_lines <path> <line...>
write_lines() {
    p=$1; shift
    : > "$p"
    for ln in "$@"; do printf '%s\n' "$ln" >> "$p"; done
}

# payload_json <sid> <transcript> [<extra-json>]
payload_json() {
    python3 -c '
import json, sys
sid, transcript, extra = sys.argv[1], sys.argv[2], sys.argv[3]
doc = {"session_id": sid, "transcript_path": transcript}
if extra:
    doc.update(json.loads(extra))
print(json.dumps(doc))
' "$1" "$2" "$3"
}

# run_hook <sid> <transcript> [<extra-json>]  -> stdout of the installed hook
run_hook() {
    script=$(hook_script)
    [ -n "$script" ] || { echo "HOOK-NOT-FOUND"; return 1; }
    pay=$(payload_json "$1" "$2" "${3:-}")
    printf '%s' "$pay" | python3 "$script"
}

# run_hook_env <base> <sid> <transcript> [<extra-json>]
#   Runs the hook with HOME/PODIUM_*/CLAUDE_*/XDG_* pointed at <base> so we
#   can use an isolated runtime.json (e.g. ui=es or cooldown>0).
run_hook_env() {
    base=$1; sid=$2; transcript=$3; extra=${4:-}
    script=$(hook_script)
    [ -n "$script" ] || { echo "HOOK-NOT-FOUND"; return 1; }
    pay=$(payload_json "$sid" "$transcript" "$extra")
    # The env applies to the hook process itself (python3), not to printf.
    printf '%s' "$pay" | ( cd "$base" && \
      env HOME="$base" \
          PODIUM_CONFIG_DIR="$base/config" \
          PODIUM_STATE_DIR="$base/state" \
          CLAUDE_CONFIG_DIR="$base/claude" \
          XDG_DATA_HOME="$base/xdg-data" \
          XDG_STATE_HOME="$base/xdg-state" \
          XDG_CONFIG_HOME="$base/xdg-config" \
      python3 "$script" )
}

# write_runtime <base> <ui> <cooldown>
write_runtime() {
    base=$1; ui=$2; cd_s=$3
    mkdir -p "$base/config" "$base/state" "$base/claude" \
             "$base/xdg-data" "$base/xdg-state" "$base/xdg-config"
    python3 -c '
import json, sys
base, ui, cd = sys.argv[1], sys.argv[2], int(sys.argv[3])
mem = {
    "schema": 1,
    "ui": ui,
    "memory": {
        "mcp_server": "graphiti-memory",
        "min_edits": 1,
        "min_executor_runs": 2,
        "cooldown_seconds": cd,
    },
    "executors": {"launcher_regex": r"\bopencode\s+run\s"},
}
with open(f"{base}/config/runtime.json", "w") as fh:
    json.dump(mem, fh)
' "$base" "$ui" "$cd_s"
}

# True if the path is a non-empty file.
is_nonempty() { test -s "$1"; }

clear_state() { rm -rf "$STATE_DIR/sessions"; }

# ===========================================================================
section "bootstrap + memory-enabled install"
# ===========================================================================
bootstrap

ANSWERS='{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules","executors","codegraph","memory","usage","upgrade"],"roster_preset":"claude-only","memory":{"url":"'"$MEM_URL"'"}}'
podium_init "$ANSWERS" >/tmp/init.log 2>&1
check "podium.toml written" "test -s $PODIUM_TOML"
check "memory module on in podium.toml" "grep -q '^memory = true' $PODIUM_TOML"

# Override the auto-written stop_hook thresholds in-place (TOML rejects
# duplicate [memory] tables, so we rewrite the line directly).
python3 - "$PODIUM_TOML" <<'PY'
import re, sys
path = sys.argv[1]
src = open(path).read()
src = re.sub(
    r"^stop_hook\s*=\s*\{[^}]*\}\s*$",
    "stop_hook = { min_edits = 1, min_executor_runs = 2, cooldown_seconds = 0 }",
    src,
    count=1,
    flags=re.M,
)
with open(path, "w") as fh:
    fh.write(src)
PY
check "toml override applied" "grep -q 'min_edits = 1' $PODIUM_TOML"

podium install >/tmp/install.log 2>&1
check "install exit 0" "[ $? -eq 0 ]"
check "memory plugin install attempted" "grep -q 'claude plugin install podium-memory@podium --scope user' /tmp/install.log"

HOOKS_JSON=$(find "$PLUGIN_CACHE" -path '*/podium-memory/*/hooks/hooks.json' | head -n 1)
if [ -z "$HOOKS_JSON" ]; then HOOKS_JSON=/dev/null; fi
check "memory-stop hook wired in plugin hooks.json" "grep -q 'memory-stop.py' '$HOOKS_JSON'"

# runtime.json must carry the overridden values.
RTK=$(python3 -c "
import json
d=json.load(open('$RUNTIME_JSON'))['memory']
print(d['min_edits'], d['min_executor_runs'], d['cooldown_seconds'], d['mcp_server'])
")
set -- $RTK
check "runtime.json min_edits=1" "[ $1 -eq 1 ]"
check "runtime.json min_executor_runs=2" "[ $2 -eq 2 ]"
check "runtime.json cooldown=0" "[ $3 -eq 0 ]"
check "runtime.json mcp_server=graphiti-memory" "[ \"$4\" = graphiti-memory ]"

LR=$(python3 -c "import json;print(json.load(open('$RUNTIME_JSON'))['executors']['launcher_regex'])")
check "runtime.json launcher_regex contains 'opencode run '" \
    "printf '%s' \"$LR\" | grep -Fq 'opencode run '"

# Skill copy + opencode.json MCP entries (installed files under $HOME).
OC_SKILL="$HOME/.config/opencode/skills/project-memory/SKILL.md"
check "opencode skill copy exists" "test -s \"$OC_SKILL\""
PLUGIN_SKILL="$HOME/.local/share/podium/repo/plugins/podium-memory/skills/project-memory/SKILL.md"
check "opencode skill copy equals plugin SKILL.md" "cmp -s \"$OC_SKILL\" \"$PLUGIN_SKILL\""

OC_JSON="$HOME/.config/opencode/opencode.json"
[ -f "$OC_JSON" ] || OC_JSON="$HOME/.config/opencode/opencode.jsonc"
MEM_OK=$(python3 -c "
import json, sys
p='$OC_JSON'
try: d=json.load(open(p))
except Exception: sys.exit(1)
e=d.get('mcp',{}).get('graphiti-memory')
ok=isinstance(e,dict) and e.get('type')=='remote' and e.get('url')=='$MEM_URL'
print('OK' if ok else 'BAD')
")
check "opencode.json mcp.graphiti-memory type=remote + url" "[ \"$MEM_OK\" = OK ]"

CG_OK=$(python3 -c "
import json, sys
p='$OC_JSON'
try: d=json.load(open(p))
except Exception: sys.exit(1)
e=d.get('mcp',{}).get('codegraph',{})
print('OK' if e.get('type')=='local' and isinstance(e.get('command'),list) else 'BAD')
")
check "opencode.json mcp.codegraph type=local" "[ \"$CG_OK\" = OK ]"

# ===========================================================================
section "synthetic transcript: thresholds, ignores, reset, cooldown, locale"
# ===========================================================================

# 1) one Write at a non-temp path -> BLOCK (min_edits=1).
clear_state
TR="$HOME/tr_one.jsonl"
L=$(tool_use_line Write 1 "/home/tester/proj/%d.txt")
write_lines "$TR" "$L"
OUT=$(run_hook "sessA" "$TR")
REASON_A=$(printf '%s' "$OUT" | python3 -c '
import json, sys
try: d = json.loads(sys.stdin.read())
except Exception:
    print(""); sys.exit(0)
if d.get("decision") == "block":
    print(d.get("reason",""))
else:
    print("")
')
# Dynamic values (reasons contain backticks and quotes) are tested with plain
# if/else, never interpolated into an eval'd check string.
if printf '%s' "$REASON_A" | grep -q '^Substantial work happened since the last memory save (1 file edits, 0 executor runs)'; then
    ok "edits=1 -> block with exact reason prefix"
else
    bad "edits=1 -> block with exact reason prefix (got '$REASON_A')"
fi
is_nonempty "$STATE_DIR/sessions/memory-stop-sessA.json" \
    && ok "state file written for sessA" \
    || bad "state file missing for sessA"

# 2) zero edits/zero executor runs -> silent.
clear_state
TR="$HOME/tr_zero.jsonl"
L=$(tool_use_line Read 1 "/home/tester/proj/%d.txt")
write_lines "$TR" "$L"
OUT=$(run_hook "sessB" "$TR")
[ -z "$OUT" ] && ok "read-only -> silent" || bad "read-only -> silent (got '$OUT')"

# 3) one Write under tempfile.gettempdir() -> silent.
clear_state
TR="$HOME/tr_tmp.jsonl"
TMP=$(python3 -c 'import tempfile;print(tempfile.gettempdir())')
L=$(tool_use_line Write 1 "$TMP/scratch_%d.py")
write_lines "$TR" "$L"
OUT=$(run_hook "sessC" "$TR")
[ -z "$OUT" ] && ok "tempdir edits ignored" || bad "tempdir edits ignored (got '$OUT')"

# 4) /private/tmp/ -> silent.
clear_state
TR="$HOME/tr_priv.jsonl"
L=$(tool_use_line Write 1 "/private/tmp/priv_%d.py")
write_lines "$TR" "$L"
OUT=$(run_hook "sessD" "$TR")
[ -z "$OUT" ] && ok "/private/tmp edits ignored" || bad "/private/tmp edits ignored (got '$OUT')"

# 5) Non-launcher Bash -> silent.
clear_state
TR="$HOME/tr_plain.jsonl"
L=$(tool_use_line Bash 3 'ls -l | head -n 1')
write_lines "$TR" "$L"
OUT=$(run_hook "sessE" "$TR")
[ -z "$OUT" ] && ok "non-launcher bash ignored" || bad "non-launcher bash ignored (got '$OUT')"

# 6) one `opencode run` -> silent (below min_executor_runs=2).
clear_state
TR="$HOME/tr_one_opencode.jsonl"
L=$(tool_use_line Bash 1 'opencode run --auto --agent x --model y')
write_lines "$TR" "$L"
OUT=$(run_hook "sessF" "$TR")
[ -z "$OUT" ] && ok "1 executor run -> silent" || bad "1 executor run -> silent (got '$OUT')"

# 7) two `opencode run` -> BLOCK.
clear_state
TR="$HOME/tr_two_opencode.jsonl"
L1=$(tool_use_line Bash 1 'opencode run --auto --agent x --model y')
L2=$(tool_use_line Bash 1 'opencode run --auto --agent x --model z')
write_lines "$TR" "$L1" "$L2"
OUT=$(run_hook "sessG" "$TR")
REASON_G=$(printf '%s' "$OUT" | python3 -c '
import json, sys
try: d = json.loads(sys.stdin.read())
except Exception:
    print(""); sys.exit(0)
print(d.get("reason","") if d.get("decision")=="block" else "")
')
# Two Bash launcher lines and no Edit/Write: 0 file edits, 2 executor runs.
if printf '%s' "$REASON_G" | grep -q '^Substantial work happened since the last memory save (0 file edits, 2 executor runs)'; then
    ok "2 executor runs -> block with exact counts"
else
    bad "2 executor runs -> block with exact counts (got '$REASON_G')"
fi
is_nonempty "$STATE_DIR/sessions/memory-stop-sessG.json" \
    && ok "executor block writes state" \
    || bad "executor block writes state (missing $STATE_DIR/sessions/memory-stop-sessG.json)"

# 8) stop_hook_active=True -> silent (no state file).
clear_state
TR="$HOME/tr_act.jsonl"
L=$(tool_use_line Write 5 "/home/tester/proj/%d.txt")
write_lines "$TR" "$L"
OUT=$(run_hook "sessH" "$TR" '{"stop_hook_active": true}')
[ -z "$OUT" ] && ok "stop_hook_active silent" || bad "stop_hook_active silent (got '$OUT')"
[ ! -e "$STATE_DIR/sessions/memory-stop-sessH.json" ] \
    && ok "stop_hook_active writes no state" \
    || bad "stop_hook_active writes no state (file exists)"

# 9) Missing transcript path -> silent.
OUT=$(run_hook "sessI" "/home/tester/does-not-exist.jsonl")
[ -z "$OUT" ] && ok "missing transcript silent" || bad "missing transcript silent (got '$OUT')"

# 10) Reset after graphiti-memory__add_memory — count past the save starts fresh.
#     Run the test against an isolated base that uses the DEFAULT min_edits=8
#     so the post-reset count is below the threshold and silence is observable.
RESET_BASE="$HOME/reset-base"
write_runtime "$RESET_BASE" en 0
python3 - <<PY
import json, sys
p = "$RESET_BASE/config/runtime.json"
d = json.load(open(p))
d["memory"]["min_edits"] = 8  # default; 3 edits after reset stays below
json.dump(d, open(p, "w"))
PY
TR="$HOME/tr_reset.jsonl"
L_A=$(tool_use_line Write 10 "/home/tester/proj/%d.txt")
L_S=$(tool_use_line graphiti-memory__add_memory 1 "")
L_B=$(tool_use_line Write 3 "/home/tester/proj/%d.txt")
write_lines "$TR" "$L_A" "$L_S" "$L_B"
OUT=$(run_hook_env "$RESET_BASE" "sessJ" "$TR")
[ -z "$OUT" ] && ok "reset after add_memory -> silent" || bad "reset after add_memory -> silent (got '$OUT')"

# 11) Cooldown blocks a second block within the same session.
CD_BASE="$HOME/cd-base"
write_runtime "$CD_BASE" en 3600
TR="$HOME/tr_cd.jsonl"
L=$(tool_use_line Write 1 "/home/tester/cd_%d.txt")
write_lines "$TR" "$L"
OUT1=$(run_hook_env "$CD_BASE" "sessK" "$TR")
if printf '%s' "$OUT1" | grep -q '"decision": "block"'; then
    ok "cooldown>0 first run blocks"
else
    bad "cooldown>0 first run blocks (got '$OUT1')"
fi
OUT2=$(run_hook_env "$CD_BASE" "sessK" "$TR")
[ -z "$OUT2" ] && ok "cooldown>0 second run silent" || bad "cooldown>0 second run silent (got '$OUT2')"

# 12) en reason exact text — entire prefix must match for sub=1/run=0.
clear_state
TR="$HOME/tr_en.jsonl"
L=$(tool_use_line Write 1 "/home/tester/proj/zzz_%d.txt")
write_lines "$TR" "$L"
OUT=$(run_hook "sessEN" "$TR")
R=$(printf '%s' "$OUT" | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["reason"])')
if printf '%s' "$R" | grep -q '^Substantial work happened since the last memory save (1 file edits, 0 executor runs)'; then
    ok "en: reason starts with exact prefix"
else
    bad "en: reason starts with exact prefix (got '$R')"
fi
if printf '%s' "$R" | grep -q 'podium-memory:project-memory'; then
    ok "en: mentions podium-memory:project-memory"
else
    bad "en: mentions podium-memory:project-memory"
fi
if printf '%s' "$R" | grep -q 'Nothing to record in memory'; then
    ok "en: nothing-to-record phrase"
else
    bad "en: nothing-to-record phrase"
fi

# 13) es reason — isolate ui=es via a second alternate base.
ES_BASE="$HOME/es-base"
write_runtime "$ES_BASE" es 0
TR="$HOME/tr_es.jsonl"
L=$(tool_use_line Write 1 "/home/tester/proj/es_%d.txt")
write_lines "$TR" "$L"
ES_OUT=$(run_hook_env "$ES_BASE" "sessES" "$TR")
if printf '%s' "$ES_OUT" | grep -q '"decision": "block"'; then
    ok "es: decision block"
else
    bad "es: decision block (got '$ES_OUT')"
fi
ES_R=$(printf '%s' "$ES_OUT" | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["reason"])')
if printf '%s' "$ES_R" | grep -q '^Hubo trabajo importante desde el último guardado en Graphiti (1 ediciones de archivos, 0 corridas del ejecutor)'; then
    ok "es: reason starts with 'Hubo trabajo' exact prefix"
else
    bad "es: reason starts with 'Hubo trabajo' exact prefix (got '$ES_R')"
fi
if printf '%s' "$ES_R" | grep -q 'podium-memory:project-memory'; then
    ok "es: mentions podium-memory:project-memory"
else
    bad "es: mentions podium-memory:project-memory"
fi
if printf '%s' "$ES_R" | grep -q 'Nada que registrar en Graphiti'; then
    ok "es: nothing-to-record phrase"
else
    bad "es: nothing-to-record phrase"
fi

# ===========================================================================
section "real Stop block via claude -p"
# ===========================================================================

mkdir -p "$HOME/proj"
rm -f "$HOME/proj/a.txt"

cd "$HOME/proj"
claude -p --model haiku --max-turns 4 --dangerously-skip-permissions \
    --output-format stream-json --verbose \
    "Create the file /home/tester/proj/a.txt containing hi" \
    </dev/null >/tmp/claude-stream.jsonl 2>/tmp/claude-stream.err
CLAUDE_EXIT=$?
cd "$HOME"

check "claude -p exited 0" "[ $CLAUDE_EXIT -eq 0 ]"
check "real file written" "test -s $HOME/proj/a.txt"

# Look for the exact reason text in the stream.
HITS=$(python3 -c '
import json
needle = "Substantial work happened since the last memory save (1 file edits, 0 executor runs)"
n = 0
with open("/tmp/claude-stream.jsonl") as fh:
    for ln in fh:
        ln = ln.strip()
        if not ln: continue
        try: d = json.loads(ln)
        except Exception: continue
        if needle in json.dumps(d):
            n += 1
print(n)
')
check "reason text present in stream-json (>=1)" "[ $HITS -ge 1 ]"
check "stop hook blocked exactly once" "[ $HITS -eq 1 ]"

# Same phrase must also appear in the saved transcript (per brief).
TRANSCRIPT_GLOB="$HOME/.claude/projects"
TR_HIT=0
if [ -d "$TRANSCRIPT_GLOB" ]; then
    TR_HIT=$(grep -rl "$TRANSCRIPT_GLOB" -e "Substantial work happened since the last memory save (1 file edits, 0 executor runs)" 2>/dev/null | wc -l | tr -d ' ')
fi
check "reason text found in saved transcript" "[ $TR_HIT -ge 1 ]"

# The session must end normally (a `result` event in the stream).
check "stream-json ends with a result event" "grep -q '\"type\":\"result\"' /tmp/claude-stream.jsonl"

# State file for the session must exist under state_dir/sessions/.
check "state file written by real run" \
    "ls \"$STATE_DIR/sessions/memory-stop-\"*.json >/dev/null 2>&1"

# ===========================================================================
section "defect 9: claude MCP registration for graphiti-memory"
# ===========================================================================

MCP_LIST=$(claude mcp list 2>&1) || MCP_LIST=""
MCP_LIST_HIT=$(printf '%s' "$MCP_LIST" | python3 -c '
import json, sys, re
text = sys.stdin.read()
# accept a JSON object {"mcpServers": {...}} or a plain text listing
try:
    d = json.loads(text)
    servers = d.get("mcpServers") if isinstance(d, dict) else None
    if isinstance(servers, dict) and "graphiti-memory" in servers:
        print("HIT"); sys.exit(0)
except Exception:
    pass
print("HIT" if "graphiti-memory" in text else "MISS")
')
check "claude mcp list mentions graphiti-memory" "[ \"$MCP_LIST_HIT\" = HIT ]"

MCP_GET=$(claude mcp get graphiti-memory 2>&1) || MCP_GET=""
if printf '%s' "$MCP_GET" | grep -Fq "$MEM_URL"; then
    ok "claude mcp get shows the configured URL"
else
    bad "claude mcp get shows the configured URL"
fi
if printf '%s' "$MCP_GET" | grep -Eqi 'user[[:space:]]*scope|scope[[:space:]]*:[[:space:]]*user|scope[[:space:]]+user'; then
    ok "claude mcp get shows user scope"
else
    bad "claude mcp get shows user scope"
fi

finish
