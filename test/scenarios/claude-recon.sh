# Calibration: where do hook outputs show up under `claude -p`, and what do the
# real CLIs print? Informs the assertions of the other real-session scenarios.
# needs: claude opencode
. /src/test/scenarios/lib.sh

bootstrap
podium_init "$(default_answers opencode-multi)" >/dev/null
podium install >/tmp/install.log 2>&1
check "install ok" "grep -q 'plugin install podium-codegraph' /tmp/install.log"

section "claude plugin list"
claude plugin list 2>&1 | head -20

section "opencode auth list / mcp list / help"
opencode auth list 2>&1 | head -15
opencode mcp list 2>&1 | head -15
opencode --help 2>&1 | head -40
opencode debug --help 2>&1 | head -20

section "gate under claude -p (stream-json)"
make_project "$HOME/work/demo"
cd "$HOME/work/demo"
claude -p "Read the file package.json and print its name field." --model haiku --max-turns 4 \
  --output-format stream-json --verbose > /tmp/stream.jsonl 2>/tmp/stream.err
echo "stream lines: $(wc -l < /tmp/stream.jsonl)"
echo "-- stream lines mentioning CodeGraph (first 3, 400 chars):"
grep -i codegraph /tmp/stream.jsonl | head -3 | cut -c1-400
echo "-- event types:"
python3 -c 'import json,sys,collections;c=collections.Counter();[c.update([json.loads(l).get("type","?")+":"+str(json.loads(l).get("subtype",""))]) for l in open("/tmp/stream.jsonl") if l.strip()];print(dict(c))'
sid=$(python3 -c 'import json;print(next(json.loads(l)["session_id"] for l in open("/tmp/stream.jsonl") if "session_id" in l))')
echo "session: $sid"
tr=$(find "$HOME/.claude/projects" -name "$sid.jsonl" | head -1)
echo "transcript: $tr"
echo "-- transcript lines mentioning CodeGraph (first 3, 400 chars):"
grep -i codegraph "$tr" | head -3 | cut -c1-400
check "deny text reached the session" "grep -q 'is not indexed with CodeGraph' /tmp/stream.jsonl || grep -q 'is not indexed with CodeGraph' $tr"
cd "$HOME"

section "init system message (plugins, skills, slash commands)"
head -1 /tmp/stream.jsonl | python3 -c 'import json,sys;d=json.loads(sys.stdin.read());print({k:(v if not isinstance(v,list) else v[:40]) for k,v in d.items() if k in ("plugins","skills","slash_commands","tools","mcp_servers")})'

section "debug log hook lines"
cd "$HOME/work/demo"
claude -p "Read package.json" --model haiku --max-turns 2 --debug > /tmp/debug.out 2>&1
grep -i "hook" /tmp/debug.out | head -15 | cut -c1-300
cd "$HOME"

section "opencode --session with an arbitrary new id"
o=$(opencode run --session ses_cc0000test0000x1 --auto --agent minimax -m "minimax/MiniMax-M3#none" "Reply with exactly: OK" </dev/null 2>/tmp/oc-sess.err)
echo "out: $o"; tail -3 /tmp/oc-sess.err
python3 - <<'EOF'
import sqlite3, os
db = os.path.expanduser("~/.local/share/opencode/opencode.db")
c = sqlite3.connect(db)
print([r[0] for r in c.execute("select name from sqlite_master where type='table'")])
for t in ("session_v2", "session"):
    try:
        print(t, c.execute(f"select id from {t} where id like 'ses_cc%'").fetchall()[:3])
    except Exception as e:
        print(t, "ERR", e)
EOF

finish
