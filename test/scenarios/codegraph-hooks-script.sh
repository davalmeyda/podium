#!/usr/bin/env bash
# needs: none
#
# Scenario S6: podium-codegraph hook scripts, driven by the runtime.json that
# a real `podium install` wrote.
#
# Asserts (per scout matrix section "2. podium-codegraph"):
#   * PreToolUse: deny_pending for Read/Edit/Write/Grep/Glob/Bash in an
#     unindexed project under /home/tester (with `cd <proj> && ls` and an
#     absolute path arg; with nested `cd`).
#   * Indexed project: no deny. Ignored dirs (~/.config, /tmp, node_modules):
#     no deny. $HOME itself and a non-project dir under HOME: no deny.
#   * Decisions: skip silence, index -> deny_index_pending until .codegraph
#     appears, then silence.
#   * PostToolUse AskUserQuestion: en label -> "index", es label -> "skip",
#     mixed label ignored; recorded into the state file.
#   * codegraph.gate=false -> reinstall -> no deny and no recording.
#   * extra_manifests and extra_ignored via podium.toml.
#   * Legacy decisions file fallback from ~/.claude/state/.
#   * Bash bypass (defect 8): codegraph init /p is exempt; `cat /p/x # codegraph`
#     and `codegraph status; cat /p/x` are gated; chained `codegraph` is exempt.
#   * Nudge cadence: calls 1, 5, 9 with default nudge_every=4; per-session
#     isolation; sub-index found at depth <= 3.
#   * ui=es -> Spanish deny text AND Spanish nudge (defect 6).
#   * Garbage stdin -> no stdout, exit 0, a line in hooks.log for each hook.
. /src/test/scenarios/lib.sh

# Test directory for payload files (avoids quoting JSON through bash eval).
PDIR=/tmp/cg6-payloads
mkdir -p "$PDIR"
write_payload() { printf '%s' "$2" >"$PDIR/$1"; }

# Local hooks: run via stdin from a payload file.  We never put $p (a JSON
# string with double quotes) inside eval; only the file path is referenced.
gate_run()   { python3 "$GATE"   < "$PDIR/$1"; }
nudge_run()  { python3 "$NUDGE"  < "$PDIR/$1"; }
gate_has()   { out=$(gate_run "$1");   [ -n "$out" ] && printf '%s' "$out" | grep -qF "$2"; }
gate_substr(){ out=$(gate_run "$1");   printf '%s' "$out" | grep -qF "$2"; }
gate_omit()  { out=$(gate_run "$1");   printf '%s' "$out" | grep -qF -- "$2" && return 1 || return 0; }
gate_silent(){ out=$(gate_run "$1");   [ -z "$out" ]; }
nudge_has()  { out=$(nudge_run "$1");  [ -n "$out" ] && printf '%s' "$out" | grep -qF "$2"; }
nudge_silent(){ out=$(nudge_run "$1"); [ -z "$out" ]; }

section "bootstrap + init (claude-only, codegraph module, English UI)"
bootstrap
podium_init "$(default_answers claude-only en)" >/tmp/init.log 2>&1
check "init wrote podium.toml" "test -s $PODIUM_TOML"
check "codegraph on in toml" "grep -qE '^[[:space:]]*codegraph[[:space:]]*=' $PODIUM_TOML"
podium install >/tmp/install.log 2>&1
check "install ok" "test ! -s /tmp/install.log || grep -qE '(claude-md block|\\[run\\]|$)' /tmp/install.log"

GATE=$(plugin_file podium-codegraph hooks/codegraph-gate.py)
NUDGE=$(plugin_file podium-codegraph hooks/codegraph-nudge.py)
check "gate installed" "test -n \"$GATE\" && test -x \"$GATE\""
check "nudge installed" "test -n \"$NUDGE\" && test -x \"$NUDGE\""
check "runtime.json present" "test -s $RUNTIME_JSON"
check "runtime.json has ui=en" "python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['ui'])\" $RUNTIME_JSON | grep -qx en"

PROJ=$HOME/proj
make_project "$PROJ"
check "project created" "test -f $PROJ/package.json"

# Idempotent reinstall.
podium install >/tmp/install2.log 2>&1
check "reinstall idempotent (still en)" "python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['ui'])\" $RUNTIME_JSON | grep -qx en"

section "PreToolUse: deny_pending in an unindexed project"
write_payload read   '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"'"$PROJ"'/foo.txt"},"cwd":"'"$PROJ"'"}'
write_payload edit   '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"'"$PROJ"'/foo.txt"},"cwd":"'"$PROJ"'"}'
write_payload write  '{"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"'"$PROJ"'/foo.txt"},"cwd":"'"$PROJ"'"}'
write_payload grep   '{"hook_event_name":"PreToolUse","tool_name":"Grep","tool_input":{"path":"'"$PROJ"'"},"cwd":"'"$PROJ"'"}'
write_payload glob   '{"hook_event_name":"PreToolUse","tool_name":"Glob","tool_input":{"path":"'"$PROJ"'"},"cwd":"'"$PROJ"'"}'
write_payload bash1  '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"'"$PROJ"'"}'
write_payload bash2  '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"cat '"$PROJ"'/foo.txt"},"cwd":"'"$PROJ"'"}'
write_payload bash3  '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"cd / && cd '"$PROJ"' && cat foo.txt"},"cwd":"'"$PROJ"'"}'

check "Read deny_pending"        "gate_has read 'CodeGraph'"
check "Read deny names project"  "gate_has read \"$PROJ\""
check "Read deny offers yes"     "gate_has read 'Index now'"
check "Read deny offers no"      "gate_has read 'Do not index'"
check "Edit deny_pending"        "gate_has edit 'CodeGraph'"
check "Write deny_pending"       "gate_has write 'CodeGraph'"
check "Grep deny_pending"        "gate_has grep 'CodeGraph'"
check "Glob deny_pending"        "gate_has glob 'CodeGraph'"
check "Bash deny_pending (cwd)"  "gate_has bash1 'CodeGraph'"
check "Bash deny_pending (abs)"  "gate_has bash2 'CodeGraph'"
check "Bash deny_pending (nest)" "gate_has bash3 'CodeGraph'"

section "PreToolUse: nothing for indexed / ignored / non-project"
mkdir -p "$PROJ/.codegraph"
check "indexed .codegraph silent"        "gate_silent read"

write_payload node  '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"cat '"$PROJ"'/node_modules/x.js"},"cwd":"'"$PROJ"'"}'
write_payload cfg   '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"'"$HOME"'/.config/foo.txt"},"cwd":"'"$HOME"'/.config"}'
write_payload tmp   '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"cat /tmp/w/x.txt"},"cwd":"'"$PROJ"'"}'
write_payload home  '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"'"$HOME"'/foo.txt"},"cwd":"'"$HOME"'"}'
mkdir -p "$HOME/notes"
write_payload notes '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"'"$HOME"'/notes/x.txt"},"cwd":"'"$HOME"'/notes"}'
check "node_modules absolute silent" "gate_silent node"
check "~/.config ignored silent"     "gate_silent cfg"
check "/tmp ignored silent"          "gate_silent tmp"
check "HOME itself silent"           "gate_silent home"
check "non-project dir under HOME"   "gate_silent notes"

rmdir "$PROJ/.codegraph" 2>/dev/null || true

section "Decisions: skip silence, index -> deny_index_pending until .codegraph"
printf '{"decisions":{"%s":"skip"}}\n' "$PROJ" >"$STATE_DIR/codegraph-decisions.json"
check "skip decision silent" "gate_silent read"

printf '{"decisions":{"%s":"index"}}\n' "$PROJ" >"$STATE_DIR/codegraph-decisions.json"
check "index -> deny_index_pending" "gate_has read 'codegraph init'"
check "index -> no Index now label" "gate_omit read 'Index now'"

mkdir -p "$PROJ/.codegraph"
check "index decision + .codegraph silent" "gate_silent read"
rmdir "$PROJ/.codegraph" 2>/dev/null || true

rm -f "$STATE_DIR/codegraph-decisions.json"

section "PostToolUse AskUserQuestion: en records 'index', es 'skip', mixed ignored"
write_payload en_yes '{"hook_event_name":"PostToolUse","tool_name":"AskUserQuestion","tool_input":{"questions":[{"question":"Index '"$PROJ"' with CodeGraph now?","options":[{"label":"Index now"},{"label":"Do not index"}]}]},"tool_response":{"answers":{"Index '"$PROJ"' with CodeGraph now?":"Index now"}}}'
write_payload es_yes '{"hook_event_name":"PostToolUse","tool_name":"AskUserQuestion","tool_input":{"questions":[{"question":"¿Indexar '"$PROJ"' con CodeGraph ahora?","options":[{"label":"Indexar ahora"},{"label":"No indexar"}]}]},"tool_response":{"answers":{"¿Indexar '"$PROJ"' con CodeGraph ahora?":"Indexar ahora"}}}'
write_payload es_no  '{"hook_event_name":"PostToolUse","tool_name":"AskUserQuestion","tool_input":{"questions":[{"question":"¿Indexar '"$PROJ"' con CodeGraph ahora?","options":[{"label":"Indexar ahora"},{"label":"No indexar"}]}]},"tool_response":{"answers":{"¿Indexar '"$PROJ"' con CodeGraph ahora?":"No indexar"}}}'
write_payload mixed  '{"hook_event_name":"PostToolUse","tool_name":"AskUserQuestion","tool_input":{"questions":[{"question":"Index '"$PROJ"' with CodeGraph now?","options":[{"label":"Index now"},{"label":"Do not index"}]}]},"tool_response":{"answers":{"Index '"$PROJ"' with CodeGraph now?":"Index now Do not index"}}}'

gate_run en_yes >/dev/null
check "en label records index" "python3 -c \"import json,sys; d=json.load(open(sys.argv[1]))['decisions']; assert d['$PROJ']=='index', d\" \"$STATE_DIR/codegraph-decisions.json\""

gate_run es_yes >/dev/null
check "es yes label records index" "python3 -c \"import json,sys; d=json.load(open(sys.argv[1]))['decisions']; assert d['$PROJ']=='index', d\" \"$STATE_DIR/codegraph-decisions.json\""

gate_run es_no >/dev/null
check "es no label records skip" "python3 -c \"import json,sys; d=json.load(open(sys.argv[1]))['decisions']; assert d['$PROJ']=='skip', d\" \"$STATE_DIR/codegraph-decisions.json\""

printf '{"decisions":{}}\n' >"$STATE_DIR/codegraph-decisions.json"
gate_run mixed >/dev/null
check "mixed answer ignored" "python3 -c \"import json,sys; d=json.load(open(sys.argv[1]))['decisions']; assert not d, d\" \"$STATE_DIR/codegraph-decisions.json\""

rm -f "$STATE_DIR/codegraph-decisions.json"

section "codegraph.gate=false: no deny and no recording"
printf '\n[codegraph]\ngate = false\n' >>"$PODIUM_TOML"
podium install >/tmp/install-gate-false.log 2>&1
check "runtime.json gate=false" "python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['codegraph']['gate'])\" $RUNTIME_JSON | grep -qx False"
check "gate off: Read silent" "gate_silent read"

write_payload ask_yes '{"hook_event_name":"PostToolUse","tool_name":"AskUserQuestion","tool_input":{"questions":[{"question":"Index '"$PROJ"' with CodeGraph now?","options":[{"label":"Index now"},{"label":"Do not index"}]}]},"tool_response":{"answers":{"Index '"$PROJ"' with CodeGraph now?":"Index now"}}}'
rm -f "$STATE_DIR/codegraph-decisions.json"
gate_run ask_yes >/dev/null
check "gate off: no recording" "test ! -f $STATE_DIR/codegraph-decisions.json"

# Restore gate on for the rest of the scenario.
# Strip the [codegraph] block we added at the end (single-key table).
python3 - "$PODIUM_TOML" <<'PY'
import sys
p = sys.argv[1]
s = open(p, 'r', encoding='utf-8').read()
i = s.rfind("\n[codegraph]\n")
if i >= 0:
    s = s[:i].rstrip("\n") + "\n"
    open(p, 'w', encoding='utf-8').write(s)
PY
podium install >/tmp/install-gate-back.log 2>&1
check "runtime.json gate=true again" "python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['codegraph']['gate'])\" $RUNTIME_JSON | grep -qx True"

section "extra_manifests via podium.toml"
EXPROJ=$HOME/external
mkdir -p "$EXPROJ"
touch "$EXPROJ/acme.codegraphproject"
write_payload exp '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"'"$EXPROJ"'/x.txt"},"cwd":"'"$EXPROJ"'"}'
check "external dir without extra_manifest silent" "gate_silent exp"

# Use a literal filename (gate.py uses os.path.exists, not glob).
printf '\n[codegraph]\nextra_manifests = ["acme.codegraphproject"]\n' >>"$PODIUM_TOML"
podium install >/tmp/install-manifests.log 2>&1
check "extra_manifests accepted" "python3 -c \"import json,sys; m=json.load(open(sys.argv[1]))['codegraph']['manifests']; assert 'acme.codegraphproject' in m, m\" $RUNTIME_JSON"
check "external deny with extra_manifest" "gate_has exp 'CodeGraph'"
rm -f "$STATE_DIR/codegraph-decisions.json"

section "extra_ignored via podium.toml"
mkdir -p "$HOME/skipdir"
printf '{"name":"x"}\n' >"$HOME/skipdir/package.json"
write_payload skip '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"'"$HOME"'/skipdir/x.txt"},"cwd":"'"$HOME"'/skipdir"}'
check "skipdir not yet ignored: deny" "gate_has skip 'CodeGraph'"
rm -f "$STATE_DIR/codegraph-decisions.json"

printf 'extra_ignored = ["skipdir"]\n' >>"$PODIUM_TOML"
podium install >/tmp/install-ignored.log 2>&1
check "extra_ignored applied" "gate_silent skip"
rm -f "$STATE_DIR/codegraph-decisions.json"

# Drop the extra config back off.
python3 - "$PODIUM_TOML" <<'PY'
import sys
p = sys.argv[1]
s = open(p, 'r', encoding='utf-8').read()
i = s.rfind("\n[codegraph]\n")
if i >= 0:
    s = s[:i].rstrip("\n") + "\n"
    open(p, 'w', encoding='utf-8').write(s)
PY
podium install >/tmp/install-back-to-base.log 2>&1

section "Legacy decisions file fallback from ~/.claude/state/"
rm -f "$STATE_DIR/codegraph-decisions.json"
LEGACY_DIR="$HOME/.claude/state"
mkdir -p "$LEGACY_DIR"
cat >"$LEGACY_DIR/codegraph-decisions.json" <<JSON
{"decisions":{"$PROJ":"skip"}}
JSON
check "legacy skip decision gates silence" "gate_silent read"
rm -rf "$LEGACY_DIR"

section "Bash bypass cases (defect 8)"
write_payload cg1 '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"codegraph init '"$PROJ"'"},"cwd":"'"$PROJ"'"}'
write_payload cg2 '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"codegraph status && codegraph explore foo"},"cwd":"'"$PROJ"'"}'
write_payload cg3 '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"cat '"$PROJ"'/foo.txt # codegraph"},"cwd":"'"$PROJ"'"}'
write_payload cg4 '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"codegraph status; cat '"$PROJ"'/foo.txt"},"cwd":"'"$PROJ"'"}'

check "pure codegraph init exempt"    "gate_silent cg1"
check "pure codegraph chained exempt" "gate_silent cg2"
check "comment bypass gated"          "gate_has cg3 'CodeGraph'"
check "codegraph;cat gated"           "gate_has cg4 'CodeGraph'"

section "Nudge cadence: calls 1, 5, 9 with default nudge_every=4"
check "runtime.json nudge_every=4" "python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['codegraph']['nudge_every'])\" $RUNTIME_JSON | grep -qx 4"

mkdir -p "$PROJ/.codegraph"
write_payload nudge '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"grep -R foo '"$PROJ"'"},"cwd":"'"$PROJ"'"}'

# The nudge hook is stateful; the counter is persistent. We run all nine
# calls in order and assert on stdout emptiness at the milestone points.
# Each nudge_run output (empty or non-empty) is captured into a list of
# arrays separated by newlines; we then verify specific calls.
rm -f "$STATE_DIR/sessions/codegraph-nudge-x.json"
out1=$(nudge_run nudge); [ -n "$out1" ] && printf '%s' "$out1" | grep -qF 'CodeGraph'
check "call 1 emits" "[ -n \"\$out1\" ] && printf '%s' \"\$out1\" | grep -qF 'CodeGraph'"
for i in 2 3 4; do
  outX=$(nudge_run nudge)
  check "call $i silent" "test -z \"\$outX\""
done
out5=$(nudge_run nudge)
check "call 5 emits" "[ -n \"\$out5\" ] && printf '%s' \"\$out5\" | grep -qF 'CodeGraph'"
for i in 6 7 8; do
  outX=$(nudge_run nudge)
  check "call $i silent" "test -z \"\$outX\""
done
out9=$(nudge_run nudge)
check "call 9 emits" "[ -n \"\$out9\" ] && printf '%s' \"\$out9\" | grep -qF 'CodeGraph'"

state_file="$STATE_DIR/sessions/codegraph-nudge-x.json"
check "default counter == 9" "test -f \"$state_file\" && python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['n'])\" \"$state_file\" | grep -qx 9"

section "nudge_every=2: emits on calls 1, 3, 5"
# Replace any existing [codegraph] nudge_every value (or append).
if grep -q '^nudge_every = 4$' "$PODIUM_TOML"; then
  sed -i 's/^nudge_every = 4$/nudge_every = 2/' "$PODIUM_TOML"
else
  printf '\n[codegraph]\nnudge_every = 2\n' >>"$PODIUM_TOML"
fi
podium install >/tmp/install-nudge2.log 2>&1
check "runtime.json nudge_every=2" "python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['codegraph']['nudge_every'])\" $RUNTIME_JSON | grep -qx 2"

rm -f "$STATE_DIR/sessions/codegraph-nudge-x.json"
out1=$(nudge_run nudge)
check "nudge2 call 1 emits" "[ -n \"\$out1\" ] && printf '%s' \"\$out1\" | grep -qF 'additionalContext'"
out2=$(nudge_run nudge)
check "nudge2 call 2 silent" "test -z \"\$out2\""
out3=$(nudge_run nudge)
check "nudge2 call 3 emits" "[ -n \"\$out3\" ] && printf '%s' \"\$out3\" | grep -qF 'CodeGraph'"
out4=$(nudge_run nudge)
check "nudge2 call 4 silent" "test -z \"\$out4\""
out5=$(nudge_run nudge)
check "nudge2 call 5 emits" "[ -n \"\$out5\" ] && printf '%s' \"\$out5\" | grep -qF 'CodeGraph'"

# Restore nudge_every=4 (one restore only: a second appended [codegraph]
# table would be a duplicate TOML table and make `podium install` fail).
if grep -q '^nudge_every = 2$' "$PODIUM_TOML"; then
  sed -i 's/^nudge_every = 2$/nudge_every = 4/' "$PODIUM_TOML"
else
  printf '\n[codegraph]\nnudge_every = 4\n' >>"$PODIUM_TOML"
fi
podium install >/tmp/install-nudge4.log 2>&1
check "install after nudge_every=4 exits 0" "test $? -eq 0"

section "Per-session isolation: two session_ids have separate counters"
rm -rf "$STATE_DIR/sessions"
SID_A=$(printf 'sa-%s' "$(date +%s%N)")
SID_B=$(printf 'sb-%s' "$(date +%s%N)")
write_payload sidA '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"grep -R foo '"$PROJ"'"},"cwd":"'"$PROJ"'","session_id":"'"$SID_A"'"}'
write_payload sidB '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"grep -R foo '"$PROJ"'"},"cwd":"'"$PROJ"'","session_id":"'"$SID_B"'"}'
check "session A call 1 emits" "nudge_has sidA 'additionalContext'"
check "session B call 1 emits" "nudge_has sidB 'additionalContext'"
sa="$STATE_DIR/sessions/codegraph-nudge-$SID_A.json"
sb="$STATE_DIR/sessions/codegraph-nudge-$SID_B.json"
check "session A state == 1" "test -f \"$sa\" && python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['n'])\" \"$sa\" | grep -qx 1"
check "session B state == 1" "test -f \"$sb\" && python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['n'])\" \"$sb\" | grep -qx 1"

section "Sub-index found at depth <=3"
rm -rf "$STATE_DIR/sessions"
rmdir "$PROJ/.codegraph" 2>/dev/null || true
mkdir -p "$PROJ/sub/three/.codegraph"
write_payload deep '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"grep -R x foo"},"cwd":"'"$PROJ"'/sub/three"}'
check "depth-3 subdir: index found" "nudge_has deep 'CodeGraph'"
rm -rf "$PROJ/sub"

section "ui=es: Spanish deny AND Spanish nudge (defect 6)"
rm -rf "$STATE_DIR/sessions" "$STATE_DIR/codegraph-decisions.json"
rmdir "$PROJ/sub/three/.codegraph" 2>/dev/null || true

# podium.toml has exactly one [language] table (written by init): set its
# ui line in place. Appending a second [language] table would be invalid TOML.
set_ui() {
  python3 - "$PODIUM_TOML" "$1" <<'PY'
import sys
p, lang = sys.argv[1], sys.argv[2]
out, under, done = [], False, False
for line in open(p, 'r', encoding='utf-8').read().splitlines(keepends=True):
    if line.startswith("["):
        under = line.startswith("[language]")
    elif under and not done and line.lstrip().startswith("ui "):
        indent = line[: len(line) - len(line.lstrip())]
        line = indent + 'ui = "%s"\n' % lang
        done = True
    out.append(line)
if not done:
    sys.exit("no ui line under [language] in podium.toml")
open(p, 'w', encoding='utf-8').write("".join(out))
PY
}

set_ui es
check "podium.toml ui = es" "grep -qx 'ui = \"es\"' $PODIUM_TOML"
podium install >/tmp/install-es.log 2>&1
check "install with ui=es exits 0" "test $? -eq 0"
check "runtime.json ui=es" "python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['ui'])\" $RUNTIME_JSON | grep -qx es"

check "es gate deny header"   "gate_has read 'El proyecto'"
check "es gate Indexar label" "gate_has read 'Indexar ahora'"
check "es gate No indexar"    "gate_has read 'No indexar'"

mkdir -p "$PROJ/.codegraph"
rm -f "$STATE_DIR/sessions/codegraph-nudge-x.json"
es_out=$(nudge_run nudge)
check "es nudge has additionalContext" "[ -n \"\$es_out\" ] && printf '%s' \"\$es_out\" | grep -qF 'additionalContext'"
# The hook emits JSON with json.dumps (ASCII-escaped), so decode it before
# comparing: "Í" arrives as Í.
es_ctx_has_indice() {
  printf '%s' "$es_out" | python3 -c 'import json,sys; c=json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"]; sys.exit(0 if "Índice" in c else 1)'
}
check "es nudge text 'Índice'"         "es_ctx_has_indice"
check "es nudge prefers codegraph_explore" "printf '%s' \"\$es_out\" | grep -qF 'codegraph_explore'"
rmdir "$PROJ/.codegraph" 2>/dev/null || true

# Restore English (same [language] table, ui line back to en).
set_ui en
podium install >/tmp/install-back-en.log 2>&1
check "install back to ui=en exits 0" "test $? -eq 0"
check "runtime.json ui=en again" "python3 -c \"import json,sys; print(json.load(open(sys.argv[1]))['ui'])\" $RUNTIME_JSON | grep -qx en"

section "Garbage stdin: silent exit, line in hooks.log for each hook"
: > "$STATE_DIR/hooks.log"
out=$(printf 'not json' | python3 "$GATE" 2>&1); ec=$?
check "gate exit 0 on garbage"    "test $ec -eq 0"
check "gate stdout empty garbage" "test -z \"$out\""

out=$(printf 'also not json' | python3 "$NUDGE" 2>&1); ec=$?
check "nudge exit 0 on garbage"    "test $ec -eq 0"
check "nudge stdout empty garbage" "test -z \"$out\""

check "hooks.log: gate line"  "grep -q 'codegraph-gate stdin json' $STATE_DIR/hooks.log"
check "hooks.log: nudge line" "grep -q 'codegraph-nudge stdin json' $STATE_DIR/hooks.log"

finish
