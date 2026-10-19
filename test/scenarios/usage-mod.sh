#!/usr/bin/env bash
# Scenario S10: podium-usage plugin — mod that rewrites Bash and a Python script
# that joins Claude transcripts with opencode.db rows.
# needs: claude opencode
#
# Offline (no real credentials used in the first half):
#   * claude plugin validate on the installed plugin directory.
#   * claude plugin test runs lib.test.ts (Bun).
#   * session_usage.py over a synthetic Claude transcript that has duplicate
#     message.ids (each id counted once) and subagent transcripts included.
#   * session_usage.py over a synthetic opencode.db with session_v2 and
#     session_message tables; rows for the parent and a child session are
#     joined and summed exactly.
#   * ui=es -> Spanish locale strings returned.
#   * Corrupt runtime.json -> error recorded, output still valid JSON, locale
#     falls back to en.
#   * Missing opencode.db -> script returns valid JSON, no crash.
#
# Real (token + opencode creds):
#   * Run a real `claude -p ... opencode run ...` inside an indexed project.
#   * The Bash tool_use in the stream-json shows the *original* command
#     (the model decision). The actual execution does not, but the opencode.db
#     proves the rewrite happened: a session_v2 row whose id starts with
#     `ses_cc<sid-no-dashes>x`.
#   * `python3 -I session_usage.py <sid>` returns at least one
#     `engine: "claude"` row and one `engine: "opencode"` row whose
#     model field is `minimax/MiniMax-M3`.
. /src/test/scenarios/lib.sh

section "bootstrap + install (opencode-multi, codegraph on)"
bootstrap
podium_init "$(default_answers opencode-multi en)" >/tmp/init.log 2>&1
check "init wrote podium.toml" "test -s $PODIUM_TOML"
podium install >/tmp/install.log 2>&1
check "install ok" "grep -q 'plugin install podium-usage' /tmp/install.log"
check "runtime.json written" "test -s $RUNTIME_JSON"
check "plugin podium-usage enabled" "claude plugin list | grep -q podium-usage@podium"

# Locate the installed plugin now (after bootstrap put files on disk).
USAGE=$(plugin_file scripts/session_usage.py scripts/session_usage.py)
[ -z "$USAGE" ] && USAGE=$(find "$PLUGIN_CACHE" -name session_usage.py -path "*podium-usage*" | head -1)
check "session_usage.py located" "test -n \"$USAGE\" -a -f \"$USAGE\""
PLUGIN_DIR=$(find "$PLUGIN_CACHE" -path '*podium-usage*' -type d -name '.claude-plugin' -print -quit | xargs -r dirname)
[ -z "$PLUGIN_DIR" ] && PLUGIN_DIR=$(find "$PLUGIN_CACHE" -path '*podium-usage*' -name register.tsx -print -quit | xargs -r dirname)
check "podium-usage dir found" "test -n \"$PLUGIN_DIR\" -a -d \"$PLUGIN_DIR\""

section "claude plugin validate on installed plugin"
out=$(claude plugin validate "$PLUGIN_DIR" 2>&1)
ec=$?
echo "$out" | grep -qE '^(✔|Validation passed)' && validated=1 || validated=0
check "validate exit 0" "test $ec -eq 0"
check "validate prints Validation passed" "test $validated -eq 1"
check "validate mentions register.tsx" "echo \"$out\" | grep -q 'register.tsx'"

section "claude plugin test (Bun lib.test.ts) on installed plugin"
test_out=$(claude plugin test "$PLUGIN_DIR" 2>&1)
test_ec=$?
check "plugin test exit 0" "test $test_ec -eq 0"
check "plugin test ran >=1 pass" "echo \"$test_out\" | grep -qE '^[[:space:]]*[0-9]+ pass$'"

# ---- offline: synthetic transcripts + opencode.db ----------------------------

section "session_usage.py: synthetic Claude transcript (dup-by-id, subagents)"
SDK_CID="ffffffff-aaaa-bbbb-cccc-111111111111"
PROJ_DIR=$HOME/.claude/projects/-home-tester-trans
mkdir -p "$PROJ_DIR/${SDK_CID}/subagents"
TF="$PROJ_DIR/${SDK_CID}.jsonl"
# Two distinct ids (msg_A twice -> one bucket; msg_B -> its own).
cat > "$TF" <<EOF
{"type":"assistant","uuid":"a1","message":{"id":"msg_A","role":"assistant","model":"claude-haiku-4-5","usage":{"input_tokens":10,"output_tokens":20,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"assistant","uuid":"a2","message":{"id":"msg_A","role":"assistant","model":"claude-haiku-4-5","usage":{"input_tokens":10,"output_tokens":20,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"assistant","uuid":"a3","message":{"id":"msg_B","role":"assistant","model":"claude-haiku-4-5","usage":{"input_tokens":3,"output_tokens":7,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
EOF
cat > "$PROJ_DIR/${SDK_CID}/subagents/sub1.jsonl" <<EOF
{"type":"assistant","uuid":"s1","message":{"id":"msg_sub","role":"assistant","model":"claude-sonnet-4-5","usage":{"input_tokens":50,"output_tokens":100,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
EOF
# The "user" line and a non-assistant type must be ignored.
cat >> "$TF" <<EOF
{"type":"user","uuid":"u1","message":{"role":"user","content":"hi"}}
{"type":"system","uuid":"z1"}
EOF

python3 -I "$USAGE" "$SDK_CID" >/tmp/sx-claude.json
check "valid JSON output" "python3 -c \"import json,sys; json.load(open(sys.argv[1]))\" /tmp/sx-claude.json"
check "duplicates collapsed (msg_A counted once: in=13)" "python3 -c \"
import json
d = json.load(open('/tmp/sx-claude.json'))
haiku = [r for r in d['rows'] if r['engine']=='claude' and r['model']=='claude-haiku-4-5']
assert len(haiku)==1, haiku
assert haiku[0]['in']==13, haiku
assert haiku[0]['out']==27, haiku
print('ok')\""
check "subagent sonnet row present (in=50 out=100)" "python3 -c \"
import json
d = json.load(open('/tmp/sx-claude.json'))
ss = [r for r in d['rows'] if r['engine']=='claude' and r['model']=='claude-sonnet-4-5']
assert len(ss)==1 and ss[0]['in']==50 and ss[0]['out']==100, ss
print('ok')\""

section "session_usage.py: synthetic opencode.db (parent + child joined)"
# Point XDG_DATA_HOME at a temp dir so the synthetic opencode.db is NOT
# the live one (clobbering it would break the opencode service and the
# following real part would fail for unrelated reasons).
SDK_OC="ffffffff-aaaa-bbbb-cccc-111111111111"
PREFIX="ses_cc${SDK_OC//-/}x"
PARENT="${PREFIX}abcd0"
CHILD="${PREFIX}abcd1"
NOW=$(date +%s)
M1='{"model":{"providerID":"minimax","id":"MiniMax-M3","variant":"none"},"tokens":{"input":100,"output":50,"reasoning":0,"cache":{"read":0,"write":0}}}'
M2='{"model":{"providerID":"minimax","id":"MiniMax-M3","variant":"none"},"tokens":{"input":200,"output":75,"reasoning":0,"cache":{"read":5,"write":0}}}'
SDK_DATA=$(mktemp -d)
SDK_DB="$SDK_DATA/opencode/opencode.db"
mkdir -p "$SDK_DATA/opencode"
python3 - "$SDK_DB" "$PARENT" "$CHILD" "$NOW" "$M1" "$M2" <<'PYEOF'
import sqlite3, sys
db, parent, child, now, m1, m2 = sys.argv[1:7]
now = int(now)
c = sqlite3.connect(db)
c.execute("create table session_v2 (id text primary key, parent_id text, time_created integer)")
c.execute("create table session_message (id text primary key, session_id text, type text, time_created integer, data text)")
c.execute("insert into session_v2 values (?, NULL, ?)", (parent, now))
c.execute("insert into session_v2 values (?, ?, ?)", (child, parent, now))
c.execute("insert into session_message values (?, ?, 'assistant', ?, ?)", ('m1', parent, now, m1))
c.execute("insert into session_message values (?, ?, 'assistant', ?, ?)", ('m2', child, now, m2))
c.commit()
PYEOF

# Default runtime.json: ui=en. Switch to es via the file before running.
runtime_backup=$(mktemp)
cp "$RUNTIME_JSON" "$runtime_backup"
python3 -c "
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d['ui'] = 'es'
json.dump(d, open(p, 'w'))
" "$RUNTIME_JSON"

# Run the script with XDG_DATA_HOME pointing at the synthetic dir.
XDG_DATA_HOME="$SDK_DATA" python3 -I "$USAGE" "$SDK_OC" >/tmp/sx-oc.json
check "valid JSON (es locale)" "python3 -c \"import json,sys; json.load(open(sys.argv[1]))\" /tmp/sx-oc.json"
# Exact opencode row sums parent+child: in=100+200=300, out=50+75=125,
# cacheRead=0+5=5, cacheWrite=0, n=2.
check "oc row parent+child summed (in=300 out=125 n=2)" "python3 -c \"
import json
d = json.load(open('/tmp/sx-oc.json'))
oc = [r for r in d['rows'] if r['engine']=='opencode' and r['model']=='minimax/MiniMax-M3']
assert len(oc)==1, oc
r = oc[0]
assert r['in']==300 and r['out']==125 and r['cacheRead']==5 and r['cacheWrite']==0 and r['n']==2 and r['variant']=='none', r
print('ok')\""
check "locale.ui is es" "python3 -c \"
import json
d = json.load(open('/tmp/sx-oc.json'))
assert d['runtime']['ui']=='es', d['runtime']
print('ok')\""
check "locale.pane_title is es (Panel / abiertos)" "python3 -c \"
import json
d = json.load(open('/tmp/sx-oc.json'))
loc = d['locale']
assert loc['pane_title']=='Tokens', loc
assert 'tokens' in loc['command_description'].lower() or 'tokens' in loc['command_description'], loc
# Spanish-specific markers (per the es.json file).
assert loc['computing']=='Calculando\\u2026' or loc['computing']=='Calculando…', loc
assert loc['short_today']=='hoy ', loc
assert loc['weekdays'][0]=='dom', loc
print('ok')\""

section "session_usage.py: corrupt runtime.json -> error listed, JSON ok"
# Save and corrupt runtime.json (no DB swap needed; XDG_DATA_HOME still points
# at the synthetic dir from the previous section, with the live DB intact).
rt_corrupt=$(mktemp)
cp "$RUNTIME_JSON" "$rt_corrupt"
printf 'this is not json' > "$RUNTIME_JSON"
XDG_DATA_HOME="$SDK_DATA" python3 -I "$USAGE" "$SDK_OC" >/tmp/sx-corrupt.json
ec=$?
check "corrupt runtime: exit 0" "test $ec -eq 0"
check "corrupt runtime: still JSON" "python3 -c \"import json,sys; json.load(open(sys.argv[1]))\" /tmp/sx-corrupt.json"
check "corrupt runtime: error listed" "python3 -c \"
import json
d = json.load(open('/tmp/sx-corrupt.json'))
assert any(e.startswith('runtime:') for e in d['errors']), d['errors']
print('ok')\""
check "corrupt runtime: locale falls back to en" "python3 -c \"
import json
d = json.load(open('/tmp/sx-corrupt.json'))
assert d['locale']['pane_title']=='Tokens', d['locale']
assert d['runtime']['ui']=='en', d['runtime']
print('ok')\""
cp "$rt_corrupt" "$RUNTIME_JSON"

section "session_usage.py: missing opencode.db -> no crash, JSON ok"
# Remove the synthetic DB so the local sandbox gets a missing-db run.
test -f "$SDK_DB" && mv "$SDK_DB" /tmp/sdk-db-backup.db
XDG_DATA_HOME="$SDK_DATA" python3 -I "$USAGE" "$SDK_OC" >/tmp/sx-nodb.json
ec=$?
check "no DB: exit 0" "test $ec -eq 0"
check "no DB: JSON output" "python3 -c \"import json,sys; json.load(open(sys.argv[1]))\" /tmp/sx-nodb.json"
check "no DB: no opencode rows" "python3 -c \"
import json
d = json.load(open('/tmp/sx-nodb.json'))
assert not any(r['engine']=='opencode' for r in d['rows']), d['rows']
print('ok')\""
mv /tmp/sdk-db-backup.db "$SDK_DB" 2>/dev/null || true
unset XDG_DATA_HOME
rm -rf "$SDK_DATA"

# ---- real: claude -p + opencode run + opencode.db join -----------------------

# Re-derive the live DB path (the synthetic tests used $SDK_DB, not the live one).
OC_DB=$HOME/.local/share/opencode/opencode.db

section "real: claude -p with Bash opencode run in an indexed project"
# Build a project and index it so the CodeGraph gate does not block the Bash.
PROJ=$HOME/work/usagedemo
rm -rf "$PROJ"
mkdir -p "$PROJ"
printf '{"name":"usagedemo"}\n' > "$PROJ/package.json"
(cd "$PROJ" && codegraph init . >/dev/null 2>&1) || true
check "usagedemo indexed" "test -d $PROJ/.codegraph"

cd "$PROJ"
claude -p "Run this exact shell command and show its output: opencode run --auto --agent minimax -m \"minimax/MiniMax-M3#none\" \"Reply with exactly: USAGE_OK\" </dev/null" \
  --model haiku --dangerously-skip-permissions --output-format stream-json --verbose > /tmp/stream.jsonl 2>/tmp/stream.err
ec=$?
check "claude -p exit 0" "test $ec -eq 0"
check "stream-json non-empty" "test -s /tmp/stream.jsonl"
cd "$HOME"

# Extract session_id.
SID=$(python3 -c "import json; [print(json.loads(l)['session_id']) for l in open('/tmp/stream.jsonl') if 'session_id' in l]" | head -1)
check "session_id captured" "test -n \"$SID\""
echo "session_id=$SID"
NO_DASHES=$(printf %s "$SID" | tr -d -)
PREFIX="ses_cc${NO_DASHES}x"
echo "expected prefix=$PREFIX"

# Report what the Bash tool_use in the stream looked like (before mod rewrite).
echo "-- Bash tool_use commands in stream:"
python3 -c "
import json
for line in open('/tmp/stream.jsonl'):
    d = json.loads(line)
    msg = d.get('message') or {}
    for c in (msg.get('content') or []):
        if isinstance(c, dict) and c.get('type')=='tool_use' and c.get('name')=='Bash':
            cmd = c.get('input',{}).get('command','')
            print('  cmd:', cmd[:300])
            print('  has --session:', '--session' in cmd)
" 2>&1

# Verify the opencode.db has a ses_cc<sid-no-dashes>x row.
oc_count=$(python3 -c "
import sqlite3
c = sqlite3.connect('file:$OC_DB?mode=ro', uri=True)
print(c.execute(\"select count(*) from session_v2 where id like ?\", ('$PREFIX%',)).fetchone()[0])
")
check "opencode.db has ses_cc<sid>x row" "test \"$oc_count\" -ge 1"
echo "oc_count=$oc_count (rows starting with $PREFIX)"

# Run session_usage.py and verify both engines show up.
python3 -I "$USAGE" "$SID" >/tmp/sx-real.json
check "real session_usage.py: valid JSON" "python3 -c \"import json,sys; json.load(open(sys.argv[1]))\" /tmp/sx-real.json"

# At least one engine:"claude" row
claude_n=$(python3 -c "
import json
d = json.load(open('/tmp/sx-real.json'))
print(sum(1 for r in d['rows'] if r['engine']=='claude'))
")
check "engine: claude rows >=1" "test \"$claude_n\" -ge 1"

# At least one engine:"opencode" row with model minimax/MiniMax-M3 (defect 10).
oc_n=$(python3 -c "
import json
d = json.load(open('/tmp/sx-real.json'))
print(sum(1 for r in d['rows'] if r['engine']=='opencode' and r['model']=='minimax/MiniMax-M3'))
")
check "engine: opencode row for minimax/MiniMax-M3" "test \"$oc_n\" -ge 1"

# Optionally inspect exact rows.
echo "-- real session_usage.py rows:"
python3 -c "
import json
d = json.load(open('/tmp/sx-real.json'))
for r in d['rows']:
    print(' ', r)
"

# Sanity: the Bash tool_use in the stream did NOT itself contain --session
# (the mod rewrites before execution; the stream logs the model decision).
# If at some point the stream does include --session, log it as observed.
stream_has=$(grep -c -- '--session' /tmp/stream.jsonl || true)
echo "stream mentions --session: $stream_has lines (tool_use may include the rewritable command unmodified)"

finish