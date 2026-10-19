# worktrees-agent: does a real principal follow the installed worktree rule?
# A `claude -p` session (sonnet, permissions bypassed inside this throwaway
# container) gets the rendered CLAUDE.md with the worktrees module on.
#   A. A structural rename that collides with uncommitted work in progress in
#      the main checkout: it must go through `podium worktree create`,
#      index the worktree, integrate, clean, and never commit or use git
#      directly on main.
#   B. A small independent change: it must NOT create a worktree.
# Assertions read the filesystem and the commands the agent actually ran.
# needs: claude
. /src/test/scenarios/lib.sh

# commands <stream>  -> one line per Bash command and per Agent call the session made
commands() {
  python3 - "$1" <<'PY'
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    msg = d.get("message") if isinstance(d, dict) else None
    if not isinstance(msg, dict):
        continue
    for c in msg.get("content", []) or []:
        if isinstance(c, dict) and c.get("type") == "tool_use":
            inp = c.get("input") or {}
            if c.get("name") == "Bash":
                print("BASH " + " ".join(str(inp.get("command", "")).split()))
            elif c.get("name") in ("Agent", "Task"):
                print("AGENT " + json.dumps(inp)[:300])
PY
}

# run_principal <cwd> <prompt> <stream>
run_principal() {
  (cd "$1" && claude -p "$2" --model sonnet --max-turns 60 --permission-mode bypassPermissions \
    --output-format stream-json --verbose > "$3" 2>/tmp/principal.err) || true
}

g() { git -C "$APP" "$@"; }

section "setup: install with worktrees on, project with work in progress"
bootstrap
podium_init '{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules","executors","codegraph","usage","upgrade"],"roster_preset":"claude-only","memory":{"url":""},"worktrees":true}' >/dev/null
podium install >/tmp/install.log 2>&1
check "rules installed with the Worktrees section" "grep -q '^### Worktrees' $HOME/.claude/CLAUDE.md"

APP=$HOME/work/shop
mkdir -p "$APP/src" "$APP/node_modules/left-pad"
printf '{"name":"shop","version":"1.0.0"}\n' > "$APP/package.json"
printf 'node_modules\n' > "$APP/.gitignore"
printf 'module.exports = (s) => s;\n' > "$APP/node_modules/left-pad/index.js"
cat > "$APP/src/price.js" <<'EOF'
function formatPrice(cents) {
  return "$" + (cents / 100).toFixed(2);
}
module.exports = { formatPrice };
EOF
cat > "$APP/src/cart.js" <<'EOF'
const { formatPrice } = require("./price");
function cartTotal(items) {
  const cents = items.reduce((sum, item) => sum + item.cents, 0);
  return formatPrice(cents);
}
module.exports = { cartTotal };
EOF
cat > "$APP/src/invoice.js" <<'EOF'
const { formatPrice } = require("./price");
function invoiceLine(name, cents) {
  return name + ": " + formatPrice(cents);
}
module.exports = { invoiceLine };
EOF
g init -q -b main && g -c user.name=t -c user.email=t@t add -A && g -c user.name=t -c user.email=t@t commit -qm init
(cd "$APP" && codegraph init . >/tmp/cg-main.log 2>&1) || true
check "main checkout indexed" "test -d $APP/.codegraph"
# Work in progress in main (uncommitted), "owned by an executor still running".
cat > "$APP/src/cart.js" <<'EOF'
const { formatPrice } = require("./price");
// WIP-DISCOUNT: discounts in progress in the main checkout
function cartTotal(items, discountCents = 0) {
  const cents = items.reduce((sum, item) => sum + item.cents, 0) - discountCents;
  return formatPrice(cents);
}
module.exports = { cartTotal };
EOF
HEAD0=$(g rev-parse HEAD)

section "A. structural change colliding with main's work in progress"
run_principal "$APP" "In this repo an executor of yours is still editing src/cart.js in the main checkout (uncommitted discount work, marked WIP-DISCOUNT); do not disturb it. In parallel, make a structural change: rename the function formatPrice to formatMoney everywhere in src/ (definition, export, imports and every call). It is a small change, so do the edits yourself instead of launching subagents. Treat the executor's work in main as finished once your rename is ready, then bring the rename into the main checkout and leave no traces of any temporary setup. Do not commit." /tmp/a.json
commands /tmp/a.json > /tmp/a.cmds
echo "--- commands run in A ---"; cat /tmp/a.cmds | cut -c1-200; echo "--- end ---"
check "A: used podium worktree create" "grep -q 'podium worktree create' /tmp/a.cmds"
check "A: indexed the worktree with codegraph init" "grep -E -q 'codegraph init.*shop-wt|cd [^ ]*shop-wt[^ ]* && codegraph init' /tmp/a.cmds"
check "A: integrated with podium worktree integrate" "grep -q 'podium worktree integrate' /tmp/a.cmds"
check "A: cleaned with podium worktree clean" "grep -q 'podium worktree clean' /tmp/a.cmds"
check "A: no Agent isolation worktree" "! grep -q 'isolation' /tmp/a.cmds"
check "A: never ran git commit/merge/stash/checkout/reset itself" \
  "! grep -E -q '^BASH .*git( -C [^ ]+)? (commit|merge|stash|checkout|reset|rebase|cherry-pick)' /tmp/a.cmds"
check "A: rename landed in main" "grep -q 'function formatMoney' $APP/src/price.js && grep -q formatMoney $APP/src/invoice.js && grep -q formatMoney $APP/src/cart.js"
check "A: no formatPrice left in main" "! grep -rq formatPrice $APP/src"
check "A: main's WIP survived" "grep -q WIP-DISCOUNT $APP/src/cart.js && grep -q discountCents $APP/src/cart.js"
check "A: no commit on main" "test \"\$(g rev-parse HEAD)\" = $HEAD0"
check "A: main index untouched" "test -z \"\$(g diff --cached --name-only)\""
check "A: no conflict markers left" "! grep -rq '^<<<<<<<\\|^>>>>>>>' $APP/src"
check "A: no worktree folder left" "test ! -e $HOME/work/shop-wt"
check "A: no wt/* branch left" "test -z \"\$(g branch --list 'wt/*')\""
check "A: only main in git worktree list" "test \$(g worktree list | wc -l) -eq 1"
check "A: main node_modules intact" "test -d $APP/node_modules/left-pad && ! test -L $APP/node_modules"

section "B. small independent change: no worktree"
run_principal "$APP" "Add a file docs/NOTES.md with the single line 'Prices are stored in cents.' Do it yourself, without subagents. Do not commit." /tmp/b.json
commands /tmp/b.json > /tmp/b.cmds
echo "--- commands run in B ---"; cat /tmp/b.cmds | cut -c1-200; echo "--- end ---"
check "B: file created in main" "grep -q 'stored in cents' $APP/docs/NOTES.md"
check "B: no worktree for a small independent change" "! grep -q 'podium worktree' /tmp/b.cmds"
check "B: still no commit" "test \"\$(g rev-parse HEAD)\" = $HEAD0"

finish
