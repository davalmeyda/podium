# worktrees: the opt-in module end to end. Install with worktrees on (rules
# rendered, runtime flag, doctor), the full `podium worktree` lifecycle on a
# real repo with uncommitted work in the main checkout (create, integrate,
# conflicts, clean with zero leftovers), the CodeGraph gate blocking a
# worktree in a real `claude -p` session until `codegraph init`, and the
# opt-out path (worktrees off restores the last-resort rule and the normal ask).
# needs: claude
. /src/test/scenarios/lib.sh

# answers <ui> <worktrees true|false>
answers() {
  printf '{"language":{"response":"en","domain":"en","ui":"%s"},"modules":["rules","executors","codegraph","usage","upgrade"],"roster_preset":"claude-only","memory":{"url":""},"worktrees":%s,"overwrite":true}' "$1" "$2"
}

# run_claude <cwd> <prompt> <stream-file>
run_claude() {
  (cd "$1" && claude -p "$2" --model haiku --max-turns 4 \
    --output-format stream-json --verbose > "$3" 2>/tmp/claude.err) || true
}

# tool results and assistant text of a stream-json transcript
flatten() {
  python3 - "$1" <<'PY'
import json, sys
out = []
for line in open(sys.argv[1], encoding="utf-8"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    msg = d.get("message") if isinstance(d, dict) else None
    if not isinstance(msg, dict):
        continue
    for c in msg.get("content", []) or []:
        if isinstance(c, dict) and c.get("type") == "tool_result":
            out.append("[tool_result]" + str(c.get("content", "")))
        elif isinstance(c, dict) and c.get("type") == "text":
            out.append("[text]" + str(c.get("text", "")))
print("\n".join(out))
PY
}

# gate_read <file>  -> gate hook output for a Read of <file>
gate_read() {
  run_hook podium-codegraph hooks/codegraph-gate.py \
    "{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Read\",\"tool_input\":{\"file_path\":\"$1\"},\"cwd\":\"$(dirname "$1")\"}"
}

g() { git -C "$APP" "$@"; }

section "1. install with worktrees on"
bootstrap
podium_init "$(answers en true)" >/dev/null
check "podium.toml enables worktrees" "grep -q '^worktrees = true' $PODIUM_TOML"
check "podium.toml has the link table" "grep -q '^link = \\[\"node_modules\"\\]' $PODIUM_TOML"
podium install >/tmp/install.log 2>&1
check "install ok" "grep -q 'plugin install podium-codegraph' /tmp/install.log"
CMD=$HOME/.claude/CLAUDE.md
check "CLAUDE.md has the Worktrees section" "grep -q '^### Worktrees' $CMD"
check "CLAUDE.md names podium worktree create" "grep -q 'podium worktree create' $CMD"
check "CLAUDE.md sends structural overlap to a worktree" "grep -qF 'that side moves to a **worktree**' $CMD"
check "CLAUDE.md has the CodeGraph worktree note" "grep -q 'Worktrees and CodeGraph' $CMD"
check "CLAUDE.md forbids isolation: worktree" "grep -qF 'Never use the Agent tool' $CMD"
check "CLAUDE.md drops the last-resort text" "! grep -q 'Exception / last resort' $CMD"
check "CLAUDE.md keeps one Invariants paragraph" "test \$(grep -c '^\\*\\*Invariants:\\*\\*' $CMD) -eq 1"
check "runtime.json codegraph.worktrees = true" \
  "python3 -c 'import json,sys; sys.exit(0 if json.load(open(\"$RUNTIME_JSON\"))[\"codegraph\"][\"worktrees\"] is True else 1)'"
podium doctor >/tmp/doctor.log 2>&1 || true
check "doctor checks git for worktrees" "grep -q 'git cli' /tmp/doctor.log"

section "2. create from a main checkout with uncommitted work"
APP=$HOME/work/app
mkdir -p "$APP/src" "$APP/node_modules/dep"
printf '{"name":"app"}\n' > "$APP/package.json"
printf 'node_modules\n.env\n' > "$APP/.gitignore"
printf 'line1\nline2\nline3\nline4\nline5\nline6\n' > "$APP/src/a.js"
printf 'keep\n' > "$APP/src/b.js"
printf 'shared\n' > "$APP/src/c.js"
printf 'dep\n' > "$APP/node_modules/dep/index.js"
g init -q -b main && g -c user.name=t -c user.email=t@t add -A && g -c user.name=t -c user.email=t@t commit -qm init
printf 'line1\nline2\nline3\nline4\nline5\nline6\nmain-uncommitted\n' > "$APP/src/a.js"
printf 'SECRET=1\n' > "$APP/.env"
HEAD0=$(g rev-parse HEAD); STATUS0=$(g status --porcelain)
WT=$HOME/work/app-wt/feat
podium worktree create "$APP" feat .env >/tmp/create.log 2>&1
check "create exit 0" "grep -q '^worktree: $WT' /tmp/create.log"
check "create says codegraph init is next" "grep -q 'next: codegraph init $WT' /tmp/create.log"
check "worktree folder is the sibling ../app-wt/feat" "test -d $WT/src"
check "worktree carries main's uncommitted change" "grep -q main-uncommitted $WT/src/a.js"
check "worktree got the untracked .env copy" "grep -q SECRET=1 $WT/.env"
check "node_modules is a symlink to main's" "test -L $WT/node_modules && test \"\$(readlink $WT/node_modules)\" = $APP/node_modules"
check "worktree is on branch wt/feat" "test \"\$(git -C $WT rev-parse --abbrev-ref HEAD)\" = wt/feat"
check "main is still on main" "test \"\$(g rev-parse --abbrev-ref HEAD)\" = main"
check "main HEAD unchanged" "test \"\$(g rev-parse HEAD)\" = $HEAD0"
check "main status unchanged" "test \"\$(g status --porcelain)\" = \"$STATUS0\""
check "create twice refuses" "! podium worktree create $APP feat"

section "3. integrate: three-way merge onto main, no commits"
sed -i 's/^line1$/line1-from-worktree/' "$WT/src/a.js"
rm "$WT/src/b.js"
printf 'new file\n' > "$WT/src/d.js"
sed -i 's/^line6$/line6-from-main/' "$APP/src/a.js"
podium worktree integrate "$APP" feat >/tmp/integrate.log 2>&1; rc=$?
check "integrate exit 0" "test $rc -eq 0"
check "integrate reports a clean integration" "grep -q 'clean integration' /tmp/integrate.log"
check "main keeps its own edit" "grep -q line6-from-main $APP/src/a.js"
check "main gets the worktree edit" "grep -q line1-from-worktree $APP/src/a.js"
check "main keeps the earlier uncommitted line" "grep -q main-uncommitted $APP/src/a.js"
check "deleted file removed from main" "test ! -e $APP/src/b.js"
check "new file copied to main" "grep -q 'new file' $APP/src/d.js"
check "no commit created on main" "test \"\$(g rev-parse HEAD)\" = $HEAD0"
check "main index untouched" "test -z \"\$(g diff --cached --name-only)\""
check "main still on main" "test \"\$(g rev-parse --abbrev-ref HEAD)\" = main"
check "node_modules never merged into main" "! grep -q node_modules /tmp/integrate.log"

section "4. conflicts: exit 2 with markers and .worktree copies"
WT2=$HOME/work/app-wt/clash
podium worktree create "$APP" clash >/dev/null 2>&1
sed -i 's/^line3$/line3-worktree/' "$WT2/src/a.js"
sed -i 's/^line3$/line3-main/' "$APP/src/a.js"
printf 'from worktree\n' > "$WT2/src/e.js"
printf 'from main\n' > "$APP/src/e.js"
podium worktree integrate "$APP" clash >/tmp/clash.log 2>&1; rc=$?
check "conflicting integrate exits 2" "test $rc -eq 2"
check "conflict markers in main's file" "grep -q '^<<<<<<< main' $APP/src/a.js && grep -q '^>>>>>>> worktree' $APP/src/a.js"
check "file created on both sides -> .worktree copy" "grep -q 'from worktree' $APP/src/e.js.worktree && grep -q 'from main' $APP/src/e.js"
check "conflict still made no commit" "test \"\$(g rev-parse HEAD)\" = $HEAD0"

section "5. clean leaves no trace"
python3 - "$STATE_DIR/codegraph-decisions.json" "$WT" <<'PY'
import json, os, sys
os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
json.dump({"decisions": {sys.argv[2]: "index", "/home/other": "skip"}}, open(sys.argv[1], "w"))
PY
podium worktree clean "$APP" feat >/tmp/clean1.log 2>&1
podium worktree clean "$APP" clash >/tmp/clean2.log 2>&1
check "clean reports zero leftovers" "grep -q 'leftovers: worktrees=0 branches=0 folder=no' /tmp/clean1.log && grep -q 'leftovers: worktrees=0 branches=0 folder=no' /tmp/clean2.log"
check "worktree folders gone" "test ! -e $WT && test ! -e $WT2"
check "empty ../app-wt removed" "test ! -e $HOME/work/app-wt"
check "wt/* branches gone" "test -z \"\$(g branch --list 'wt/*')\""
check "git worktree list shows only main" "test \$(g worktree list | wc -l) -eq 1"
check "stored bases gone" "test -z \"\$(ls $APP/.git | grep wt-base)\""
check "main's node_modules intact" "test -d $APP/node_modules && ! test -L $APP/node_modules && grep -q dep $APP/node_modules/dep/index.js"
check "CodeGraph decision for the worktree removed" "! grep -q app-wt $STATE_DIR/codegraph-decisions.json"
check "other CodeGraph decisions kept" "grep -q /home/other $STATE_DIR/codegraph-decisions.json"

section "6. real claude: a worktree is blocked without asking, until indexed"
g checkout -q -- . && rm -f "$APP/src/e.js" "$APP/src/e.js.worktree" "$APP/src/d.js"
printf '{"name":"WT_MARKER_QQ"}\n' > "$APP/package.json"
g -c user.name=t -c user.email=t@t commit -qam marker
WT3=$HOME/work/app-wt/gate
podium worktree create "$APP" gate >/dev/null 2>&1
check "hook denies the worktree with the worktree text" "gate_read $WT3/package.json | grep -q 'is a git worktree'"
check "hook does not ask the user about the worktree" "! gate_read $WT3/package.json | grep -q 'has not decided'"
check "hook still asks about the unindexed main repo" "gate_read $APP/package.json | grep -q 'has not decided'"
run_claude "$WT3" "Read package.json and tell me the name field." /tmp/g1.json
check "claude: Read in the worktree is denied with the worktree text" "flatten /tmp/g1.json | grep -q 'is a git worktree'"
echo "--- transcript (first 1500 chars) ---"; flatten /tmp/g1.json | head -c 1500; echo; echo "--- end ---"
check "claude: file content never returned" "flatten /tmp/g1.json > /tmp/g1.txt && ! grep -q '\\[tool_result\\].*WT_MARKER_QQ' /tmp/g1.txt"
if command -v codegraph >/dev/null 2>&1; then
  (cd "$WT3" && codegraph init . >/tmp/cg.log 2>&1) || true
  check "codegraph init created the worktree index" "test -d $WT3/.codegraph"
  check "hook allows the indexed worktree" "test -z \"\$(gate_read $WT3/package.json)\""
  run_claude "$WT3" "Read package.json and tell me the name field." /tmp/g2.json
  check "claude: Read works once the worktree is indexed" "flatten /tmp/g2.json | grep -q WT_MARKER_QQ"
else
  bad "codegraph CLI missing in the image"
fi
podium worktree clean "$APP" gate >/tmp/clean3.log 2>&1
check "indexed worktree cleans to zero leftovers" "grep -q 'leftovers: worktrees=0 branches=0 folder=no' /tmp/clean3.log"

section "7. opt-out: worktrees off restores the default rules and the ask"
podium_init "$(answers en false)" >/dev/null
check "podium.toml disables worktrees" "grep -q '^worktrees = false' $PODIUM_TOML"
podium install >/tmp/install2.log 2>&1
check "CLAUDE.md has no Worktrees section" "! grep -q '^### Worktrees' $CMD"
check "CLAUDE.md has no podium worktree" "! grep -q 'podium worktree' $CMD"
check "CLAUDE.md has the last-resort text back" "grep -q 'Exception / last resort' $CMD"
check "runtime.json codegraph.worktrees = false" \
  "python3 -c 'import json,sys; sys.exit(0 if json.load(open(\"$RUNTIME_JSON\"))[\"codegraph\"][\"worktrees\"] is False else 1)'"
WT4=$HOME/work/app-wt/off
podium worktree create "$APP" off >/dev/null 2>&1
check "worktrees off: the gate asks about a worktree like any project" "gate_read $WT4/package.json | grep -q 'has not decided'"
podium worktree clean "$APP" off >/dev/null 2>&1

section "8. Spanish locale"
podium_init "$(answers es true)" >/dev/null
podium install >/tmp/install3.log 2>&1
WT5=$HOME/work/app-wt/es
podium worktree create "$APP" es >/dev/null 2>&1
check "es: worktree deny text in Spanish" "gate_read $WT5/package.json | grep -q 'es un worktree de git'"
podium worktree clean "$APP" es >/dev/null 2>&1
check "nothing left in the sibling folder" "test ! -e $HOME/work/app-wt"

finish
