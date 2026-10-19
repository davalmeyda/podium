# codegraph-real-claude: real `claude -p` sessions after `podium install`
# exercise the codegraph-gate and codegraph-nudge hooks under the
# command+args exec form. Verifies the deny text reaches the model via
# stream JSON, the skip/index decisions unblock Read, the grep nudge is
# injected, the Spanish locale is honored, and codegraph.gate=false
# disables the gate end-to-end.
# needs: claude
. /src/test/scenarios/lib.sh

# --- helpers local to this scenario --------------------------------------------

# make_proj <dir> <marker>   create a project with a unique marker in package.json
make_proj() {
  dir=$1; marker=$2
  mkdir -p "$dir"
  cat > "$dir/package.json" <<EOF
{"name":"$marker","description":"$marker unique sentinel string"}
EOF
}

# write_decision <dir> <skip|index>
write_decision() {
  dir=$1; kind=$2
  mkdir -p "$STATE_DIR"
  python3 -c "
import json, os, sys
p = os.path.expanduser('$STATE_DIR/codegraph-decisions.json')
s = {'decisions': {'$dir': '$kind'}}
if os.path.exists(p):
    try:
        with open(p) as f: s = json.load(f)
    except Exception: pass
s.setdefault('decisions', {})['$dir'] = '$kind'
with open(p, 'w') as f: json.dump(s, f, indent=1)
print(p)
"
}

# run_claude <cwd> <prompt> <stream-file> [extra args...]
run_claude() {
  cwd=$1; prompt=$2; out=$3; shift 3
  (cd "$cwd" && claude -p "$prompt" --model haiku --max-turns 4 \
    --output-format stream-json --verbose "$@" \
    > "$out" 2>/tmp/claude.err) || true
}

# extract assistant text and user tool_result content into a single body
flatten_stream() {
  python3 - <<'PY' "$1"
import json, sys
path = sys.argv[1]
chunks = []
for line in open(path, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    msg = d.get("message") or {}
    for c in msg.get("content", []) or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "tool_result":
            chunks.append("[tool_result]" + str(c.get("content", "")))
        elif c.get("type") == "text":
            chunks.append("[text]" + str(c.get("text", "")))
sys.stdout.write("\n".join(chunks))
PY
}

# Returns 0 (true) if any tool_result content contains the PreToolUse deny
# header; otherwise 1.
has_deny() {
  flatten_stream "$1" | grep -q 'PreToolUse:Read hook error:'
}

# Returns 0 (true) if the marker appears inside any tool_result content
# (i.e. Read actually returned the file body).
has_marker() {
  flatten_stream "$1" | grep -qF "$2"
}

# --- 0. bootstrap and install ---------------------------------------------------
bootstrap
podium_init "$(default_answers claude-only)" >/dev/null
podium install >/tmp/install.log 2>&1
check "install ok" "grep -q 'plugin install podium-codegraph' /tmp/install.log"
check "runtime.json present" "test -s $RUNTIME_JSON"
check "runtime gate=true" "grep -q '\"gate\": true' $RUNTIME_JSON"

# --- 1. Read in unindexed project: deny + file content NEVER returned -----------
section "1. Read in unindexed project is denied"
make_proj "$HOME/work/demo" "DEMO_AAA"
run_claude "$HOME/work/demo" \
  "Read package.json and tell me the name field." /tmp/p1.json
check "deny text in stream"  "has_deny /tmp/p1.json"
check "deny text names project root" \
  "flatten_stream /tmp/p1.json | grep -qF 'is not indexed with CodeGraph and the user has not decided'"
check "deny text includes the root path" \
  "flatten_stream /tmp/p1.json | grep -qF '/home/tester/work/demo'"
check "deny text names the yes/no options" \
  "flatten_stream /tmp/p1.json | grep -qF \"exactly these two options:\""
check "file content NEVER returned in any tool_result" \
  "! has_marker /tmp/p1.json DEMO_AAA"

# --- 2. skip decision for the same root: Read succeeds -------------------------
section "2. skip decision unblocks Read"
write_decision "$HOME/work/demo" skip
check "decisions file written" "test -s $STATE_DIR/codegraph-decisions.json"
run_claude "$HOME/work/demo" \
  "Read package.json and tell me the name field." /tmp/p2.json
check "no deny in stream" "! has_deny /tmp/p2.json"
check "file content appears in a tool_result" "has_marker /tmp/p2.json DEMO_AAA"

# --- 3. codegraph init + index decision on a second project: Read succeeds -----
section "3. index decision + codegraph init on a second project"
make_proj "$HOME/work/indexed" "IDX_BBB"
write_decision "$HOME/work/indexed" index
codegraph init "$HOME/work/indexed" >/tmp/cg-init.log 2>&1
check "codegraph init exit 0" "[ -d $HOME/work/indexed/.codegraph ]"
run_claude "$HOME/work/indexed" \
  "Read package.json and tell me the name field." /tmp/p3.json
check "no deny in stream" "! has_deny /tmp/p3.json"
check "file content appears in a tool_result" "has_marker /tmp/p3.json IDX_BBB"

# --- 4. grep in the indexed project fires the nudge ---------------------------
section "4. grep in the indexed project fires the nudge"
# The nudge counts only calls where an index was found, and emits on call
# number n when (n-1) % nudge_every == 0 (default 4). The first Grep should
# emit; use --include-hook-events so the hook output is on the stream.
run_claude "$HOME/work/indexed" \
  "Use the Grep tool to find the line containing 'IDX_BBB' under the current directory, then print the matching line." \
  /tmp/p4.json --include-hook-events
# Hook output (additionalContext) appears in the stream as a PreToolUse
# hookSpecificOutput entry; the nudge text is the en locale's "CodeGraph
# index available" string with a parenthesised roots list.
check "nudge text in stream" \
  "grep -qF 'CodeGraph index available' /tmp/p4.json"
check "nudge references a real root" \
  "grep -qF '/home/tester/work/indexed' /tmp/p4.json"

# --- 5. ui=es + reinstall: Spanish deny text in the stream --------------------
section "5. ui=es: Spanish deny text"
# Re-init overwriting the toml with ui=es, then reinstall so runtime.json
# reflects the new locale. Use a fresh project root.
podium_init '{"language":{"response":"es","domain":"es","ui":"es"},"modules":["rules","executors","codegraph","usage","upgrade"],"roster_preset":"claude-only","memory":{"url":""},"overwrite":true}' \
  >/dev/null
podium install >/tmp/install-es.log 2>&1
check "runtime ui=es" "grep -q '\"ui\": \"es\"' $RUNTIME_JSON"
make_proj "$HOME/work/es" "ES_CCC"
# Wipe decisions for the new root so it counts as a fresh, unindexed project.
python3 -c "
import json, os
p = os.path.expanduser('$STATE_DIR/codegraph-decisions.json')
if os.path.exists(p):
    s = json.load(open(p))
    s.get('decisions', {}).pop('/home/tester/work/es', None)
    open(p, 'w').write(json.dumps(s, indent=1))
"
run_claude "$HOME/work/es" \
  "Read package.json and tell me the name field." /tmp/p5.json
check "es deny header in stream" "has_deny /tmp/p5.json"
check "es deny text in Spanish" \
  "flatten_stream /tmp/p5.json | grep -qF 'no está indexado con CodeGraph'"
check "es deny options are Spanish" \
  "flatten_stream /tmp/p5.json | grep -qF \"'Indexar ahora'\" \
   && flatten_stream /tmp/p5.json | grep -qF \"'No indexar'\""
check "es: file content never returned" "! has_marker /tmp/p5.json ES_CCC"

# --- 6. codegraph.gate=false + reinstall: no deny at all ----------------------
section "6. codegraph.gate=false: gate disabled, no deny"
# Switch to ui=en to make the absence-of-deny check unambiguous.
podium_init '{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules","executors","codegraph","usage","upgrade"],"roster_preset":"claude-only","memory":{"url":""},"overwrite":true}' \
  >/dev/null
# Append a [codegraph] table — the rendered toml has none, so this is the
# only place the key appears and overrides nothing.
toml_append '[codegraph]
gate = false
'
podium install >/tmp/install-nogate.log 2>&1
check "runtime gate=false" "grep -q '\"gate\": false' $RUNTIME_JSON"
make_proj "$HOME/work/nogate" "NOGATE_DDD"
run_claude "$HOME/work/nogate" \
  "Read package.json and tell me the name field." /tmp/p6.json
check "no deny in stream" "! has_deny /tmp/p6.json"
check "file content returned" "has_marker /tmp/p6.json NOGATE_DDD"

finish
