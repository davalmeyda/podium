# install-lifecycle: dry-run plan and ordering, conflicts, --adopt/--force,
# --modules limits and unknown exit, idempotence, lock held/stale, opencode.jsonc
# handling, plugin install/uninstall through the real claude CLI, and uninstall.
# needs: none
. /src/test/scenarios/lib.sh

# --- helpers local to this scenario --------------------------------------------

# Take a snapshot of $HOME (minus the podium checkout and state lock) for
# "nothing written".  The checkout is the live source tree that podium runs
# from, and a dry-run can trigger Python to drop a .pyc into its __pycache__.
snap() {
  (cd "$HOME" && find . -xdev \
    ! -path './.local/state/podium/lock' \
    ! -path './.local/state/podium/lock*' \
    ! -path './.local/share/podium' \
    ! -path './.local/share/podium/*' \
    ! -path './.local/state/podium' \
    ! -path './.local/state/podium/*' \
    ! -path './.config/podium' \
    ! -path './.config/podium/*' \
    ! -path './.claude/plugins' \
    ! -path './.claude/plugins/*' \
    ! -path './.claude.json' \
    -printf '%p %s %T@\n' 2>/dev/null | sort) > "/tmp/snap.$1"
}

snap_diff() {
  diff -q "/tmp/snap.$1" "/tmp/snap.$2" >/dev/null 2>&1
}

bootstrap
podium_init "$(default_answers opencode-multi)" >/dev/null

# ============================================================================
section "dry-run plan lines and filesystem snapshot"
# ============================================================================

snap before
podium install --dry-run --modules rules,executors,codegraph,usage,upgrade \
  > /tmp/plan.txt 2>&1
code=$?
check "dry-run exit 0" "[ $code -eq 0 ]"
check "dry-run: nothing written trailer" \
  "tail -n 1 /tmp/plan.txt | grep -qx 'dry-run: nothing written'"
check "plan starts with claude-md block" \
  "sed -n '1p' /tmp/plan.txt | grep -q '\\[create\\].*CLAUDE\\.md.*claude-md block'"
check "plan has opencode-agents-md block" \
  "grep -q '\\[create\\].*AGENTS\\.md.*opencode-agents-md block' /tmp/plan.txt"
check "plan has executor-profile" \
  "grep -q 'executor-profile' /tmp/plan.txt"
check "plan has opencode.json MCP servers" \
  "grep -q 'opencode\\.json.*OpenCode MCP servers' /tmp/plan.txt"
check "plan has runtime.json" \
  "grep -q 'runtime\\.json.*hook runtime' /tmp/plan.txt"
check "plan has plugin marketplace add" \
  "grep -q 'claude plugin marketplace add' /tmp/plan.txt"
check "plan has plugin install codegraph" \
  "grep -q 'claude plugin install podium-codegraph@podium --scope user' /tmp/plan.txt"
check "plan has plugin install usage" \
  "grep -q 'claude plugin install podium-usage@podium --scope user' /tmp/plan.txt"
check "plan has plugin install upgrade" \
  "grep -q 'claude plugin install podium-upgrade@podium --scope user' /tmp/plan.txt"

# Verify ordering: claude-md -> opencode-agents-md -> profile -> agents ->
# opencode.json -> runtime.json -> marketplace
order_ok=$(awk '
    /claude-md block/ {b1=NR}
    /opencode-agents-md block/ {b2=NR}
    /executor-profile[^.]/ {b3=NR}
    /agent / {b4=NR}
    /OpenCode MCP servers/ {b5=NR}
    /hook runtime/ {b7=NR}
    /marketplace add/ {b8=NR}
    END { if (b1<b2 && b2<b3 && (b4==0 || (b3<b4 && b4<b5)) && b5<b7 && b7<b8) print "ok"; else print "bad " b1 " " b2 " " b3 " " b4 " " b5 " " b7 " " b8 }' /tmp/plan.txt)
check "plan order: blocks -> profile -> agents -> opencode.json -> runtime.json -> marketplace" \
  "[ \"$order_ok\" = ok ]"

snap after
check "dry-run filesystem unchanged" "snap_diff before after"

# ============================================================================
section "conflict dry-run refuses with exit 2"
# ============================================================================

# Place a foreign file where podium would write the executor-profile.
profile="$HOME/.local/state/podium/executor-profile.md"
mkdir -p "$(dirname "$profile")"
printf 'foreign profile content\n' > "$profile"
snap cbefore
podium install --dry-run --modules executors >/tmp/cdryrun.txt 2>&1
code=$?
check "conflict dry-run exit 2" "[ $code -eq 2 ]"
check "conflict dry-run trailer" \
  "tail -n 1 /tmp/cdryrun.txt | grep -qx 'dry-run: install would be refused (conflicts above); nothing written'"
check "conflict dry-run mentions --adopt" \
  "grep -q 'use --adopt' /tmp/cdryrun.txt"
check "conflict dry-run file untouched" 'cmp -s "$profile" <(printf "foreign profile content\n")'

snap cafter
check "conflict dry-run filesystem unchanged" "snap_diff cbefore cafter"

# ============================================================================
section "real conflict refuses with exit 2 and nothing written"
# ============================================================================

# Use the same foreign file from the previous section; run a REAL install.
snap rbefore
podium install --modules executors >/tmp/creal.txt 2>&1
code=$?
check "real conflict exit 2" "[ $code -eq 2 ]"
check "real conflict stderr message" \
  "grep -qx 'podium: install refused: conflicts found; nothing was written' /tmp/creal.txt"
check "real conflict plan printed" \
  "grep -q 'use --adopt' /tmp/creal.txt"
check "real conflict: no ledger" \
  "test ! -e $STATE_DIR/owned.json"

snap rafter
check "real conflict filesystem unchanged" "snap_diff rbefore rafter"

# ============================================================================
section "--adopt: backup name pattern + ledger adopted entry"
# ============================================================================

snap abefore
podium install --modules executors --adopt >/tmp/adopt.txt 2>&1
code=$?
check "adopt exit 0" "[ $code -eq 0 ]"
# After --adopt, the backup (not the live file) holds the original foreign content.
check "adopt: backup preserves the foreign content" \
  'grep -q "foreign profile content" "$(ls "$profile".bak-podium-* | head -n1)"'
check "adopt: backup file with .bak-podium-YYYYMMDD-HHMMSS-xxxx" \
  'ls "$profile".bak-podium-* | head -n1 | grep -qE "profile\.md\.bak-podium-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$"'
# ledger content
ledger="$STATE_DIR/owned.json"
check "ledger has adopted key for profile" \
  "python3 -c \"import json;d=json.load(open('$ledger'));print(bool(d.get('adopted'))) \" | grep -qx True"
check "ledger adopted points at a backup file" \
  "python3 -c \"import json,os;d=json.load(open('$ledger'));bk=list(d['adopted'].values())[0];print(bk.endswith('.bak-podium-' + '-'.join(bk.split('-')[-3:-1]) + '-' + bk.split('-')[-1]) and os.path.isfile(bk))\" | grep -qx True"

# ============================================================================
section "--force: backup name pattern when user edits an installed file"
# ============================================================================

# Append a line to the now-owned profile and rerun with --force.
printf 'user-edit\n' >> "$profile"
podium install --modules executors --force >/tmp/force.txt 2>&1
code=$?
check "force exit 0" "[ $code -eq 0 ]"
check "force: backup of edited profile" \
  'ls "$profile".bak-podium-* | grep -qE "profile\.md\.bak-podium-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$"'
check "force: backup content has user-edit" \
  'grep -q "user-edit" "$(ls -t "$profile".bak-podium-* | head -n1)"'
check "force: profile rewritten by podium (no user-edit in profile)" \
  '! grep -q "user-edit" "$profile"'

# ============================================================================
section "--modules rules limits actions and unknown module gets exit 1"
# ============================================================================

snap mbefore
podium install --dry-run --modules rules >/tmp/modrules.txt 2>&1
check "modules rules: only block lines (no plugins, no opencode.json, no agents, no profile)" \
  "grep -qE 'claude-md block|opencode-agents-md block' /tmp/modrules.txt && \
   ! grep -q 'OpenCode MCP servers' /tmp/modrules.txt && \
   ! grep -q 'plugin install' /tmp/modrules.txt && \
   ! grep -q 'agent ' /tmp/modrules.txt && \
   ! grep -q 'executor-profile' /tmp/modrules.txt"

# Unknown module: exit 1 and the documented message.
podium install --modules rules,nosuch >/tmp/badmod.txt 2>&1
code=$?
check "unknown module exit 1" "[ $code -eq 1 ]"
check "unknown module message" \
  "grep -q 'unknown module' /tmp/badmod.txt && \
   grep -q 'rules, executors, codegraph, memory, usage, upgrade' /tmp/badmod.txt"

snap mafter
check "modules filesystem unchanged" "snap_diff mbefore mafter"

# ============================================================================
section "idempotent second run reports [unchanged]"
# ============================================================================

podium install >/tmp/idem.log 2>&1
check "idempotent exit 0" "[ $? -eq 0 ]"
check "idempotent: ledger has at least 5 files" \
  "python3 -c \"import json;d=json.load(open('$ledger'));print(len(d['files']) >= 5)\" | grep -qx True"

podium install >/tmp/idem2.log 2>&1
check "second run exit 0" "[ $? -eq 0 ]"
# Many steps should be unchanged on the second run; at least the blocks are.
check "second run: every block step is [unchanged]" \
  "grep -q '\\[unchanged\\].*claude-md block' /tmp/idem2.log && grep -q '\\[unchanged\\].*opencode-agents-md block' /tmp/idem2.log"

# ============================================================================
section "lock held gives exit 3, stale lock is taken over"
# ============================================================================

mkdir -p "$STATE_DIR"
# Held lock: fresh, owned by us.
printf '%d\n' "$$" > "$STATE_DIR/lock"
podium install >/tmp/held.log 2>&1
code=$?
check "held lock exit 3" "[ $code -eq 3 ]"
check "held lock stderr message" \
  "grep -q 'another podium run is in progress' /tmp/held.log"

# Stale lock: touch it 15 minutes into the past.
touch -d '15 minutes ago' "$STATE_DIR/lock"
podium install >/tmp/stale.log 2>&1
check "stale lock taken over: exit 0" "[ $? -eq 0 ]"
check "stale lock: no longer present after run" \
  "test ! -e $STATE_DIR/lock"

# ============================================================================
section "opencode.jsonc only -> untouched, opencode.json created"
# ============================================================================

# Reset state and start a fresh tree.
rm -rf "$STATE_DIR"
podium uninstall --dry-run >/dev/null 2>&1 || true
# Drop only the files opencode owns under ~/.config/opencode, keep the rest.
rm -f "$HOME/.config/opencode/opencode.json"
rm -f "$HOME/.config/opencode/opencode.jsonc"
printf '// user JSONC only\n{\n  "user": "kept"\n}\n' > "$HOME/.config/opencode/opencode.jsonc"

podium install --modules codegraph >/tmp/ocsonly.log 2>&1
check "iocsonly exit 0" "[ $? -eq 0 ]"
check "opencode.jsonc untouched (user content still present)" \
  "grep -q 'user.*kept' \"$HOME/.config/opencode/opencode.jsonc\""
check "opencode.json created with codegraph MCP entry" \
  "python3 -c \"import json;d=json.load(open('$HOME/.config/opencode/opencode.json'));print(d.get('mcp',{}).get('codegraph',{}).get('type')=='local' and d['mcp']['codegraph'].get('command')==['codegraph','serve','--mcp'])\" | grep -qx True"

# Now create opencode.json too and re-run doctor.
printf '{\n  "user": "json user"\n}\n' > "$HOME/.config/opencode/opencode.json"
podium doctor >/tmp/docdup.txt 2>&1 || true
check "doctor WARN when both opencode.json and opencode.jsonc" \
  "grep -q '\\[WARN\\].*opencode config.*opencode\\.json and opencode\\.jsonc both present' /tmp/docdup.txt"

# ============================================================================
section "claude plugin list shows enabled @podium plugins"
# ============================================================================

# Re-init with memory enabled (memory plugin only installs when memory module
# is on AND memory.url is non-empty; the matrix expects all four plugins).
podium uninstall >/dev/null 2>&1 || true
rm -rf "$STATE_DIR" "$HOME/.config/opencode/opencode.json" "$HOME/.config/opencode/opencode.jsonc"
rm -rf "$HOME/.claude/plugins" 2>/dev/null
rm -rf "$HOME/.claude.json" 2>/dev/null
podium_init '{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules","executors","codegraph","memory","usage","upgrade"],"roster_preset":"opencode-multi","memory":{"url":"http://127.0.0.1:1/"},"overwrite":true}' >/dev/null
podium install >/tmp/fresh.log 2>&1
check "fresh install exit 0" "[ $? -eq 0 ]"
# The plugin commands must have actually run (no warning lines about plugin install failure).
check "plugin install no warnings" \
  "! grep -q 'warning:.*plugin install' /tmp/fresh.log"
check "plugin list shows podium-codegraph enabled" \
  "claude plugin list | grep -q 'podium-codegraph@podium'"
check "plugin list shows podium-memory enabled" \
  "claude plugin list | grep -q 'podium-memory@podium'"
check "plugin list shows podium-usage enabled" \
  "claude plugin list | grep -q 'podium-usage@podium'"
check "plugin list shows podium-upgrade enabled" \
  "claude plugin list | grep -q 'podium-upgrade@podium'"

# ============================================================================
section "uninstall --dry-run writes nothing"
# ============================================================================

snap ubefore
podium uninstall --dry-run >/tmp/udryrun.txt 2>&1
code=$?
check "uninstall --dry-run exit 0" "[ $code -eq 0 ]"
check "uninstall --dry-run trailer" \
  "tail -n 1 /tmp/udryrun.txt | grep -qx 'dry-run: nothing written'"
check "uninstall --dry-run: plugin uninstall plan lines" \
  "grep -q 'claude plugin uninstall.*--scope user' /tmp/udryrun.txt"
check "uninstall --dry-run: marketplace remove plan line" \
  "grep -q 'claude plugin marketplace remove' /tmp/udryrun.txt"
check "uninstall --dry-run: claude-md block remove" \
  "grep -q '\\[remove\\].*CLAUDE\\.md.*claude-md block' /tmp/udryrun.txt"
check "uninstall --dry-run: opencode-agents-md block remove" \
  "grep -q '\\[remove\\].*AGENTS\\.md.*opencode-agents-md block' /tmp/udryrun.txt"
snap uafter
check "uninstall --dry-run filesystem unchanged" "snap_diff ubefore uafter"

# ============================================================================
section "uninstall removes plugins, marketplace, blocks, files, JSON keys"
# ============================================================================

# Sanity: blocks are present before uninstall.
check "pre-uninstall: claude-md block present" \
  "grep -q 'podium:begin claude-md' \"$HOME/.claude/CLAUDE.md\""
check "pre-uninstall: ledger has files" \
  "python3 -c \"import json;d=json.load(open('$ledger'));print(len(d.get('files',{})))\" | grep -qvx 0"

podium uninstall >/tmp/uninst.log 2>&1
check "uninstall exit 0" "[ $? -eq 0 ]"
check "uninstall: claude-md block gone" \
  "! grep -q 'podium:begin claude-md' \"$HOME/.claude/CLAUDE.md\""
check "uninstall: opencode-agents-md block gone" \
  "! grep -q 'podium:begin opencode-agents-md' \"$HOME/.config/opencode/AGENTS.md\""
check "uninstall: ledger file removed (empty)" \
  "test ! -e $ledger"
check "uninstall: opencode.json keys removed (file is {} or gone)" \
  '! grep -q codegraph "$HOME/.config/opencode/opencode.json" 2>/dev/null && ! grep -q graphiti-memory "$HOME/.config/opencode/opencode.json" 2>/dev/null'
check "uninstall: podium-codegraph plugin gone" \
  "! claude plugin list | grep -q 'podium-codegraph@podium'"
check "uninstall: podium-memory plugin gone" \
  "! claude plugin list | grep -q 'podium-memory@podium'"
check "uninstall: podium-usage plugin gone" \
  "! claude plugin list | grep -q 'podium-usage@podium'"
check "uninstall: podium-upgrade plugin gone" \
  "! claude plugin list | grep -q 'podium-upgrade@podium'"
# Marketplace removed: re-adding should succeed without 'already' tolerance hitting.
check "uninstall: marketplace removed (no podium marketplace)" \
  "! claude plugin marketplace list 2>/dev/null | grep -q 'podium'"

# ============================================================================
section "uninstall restores adopted file and keeps edited files"
# ============================================================================

# Reset: fully uninstall so no podium-owned files remain in the ledger.
podium uninstall >/dev/null 2>&1 || true
rm -rf "$STATE_DIR" "$HOME/.config/opencode/opencode.json" "$HOME/.config/opencode/opencode.jsonc"
rm -rf "$HOME/.claude/plugins" 2>/dev/null
rm -rf "$HOME/.claude.json" 2>/dev/null
podium_init '{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules","executors","codegraph","memory","usage","upgrade"],"roster_preset":"opencode-multi","memory":{"url":"http://127.0.0.1:1/"},"overwrite":true}' >/dev/null

# Place a foreign file BEFORE install; install will adopt it with --adopt.
profile="$HOME/.local/state/podium/executor-profile.md"
mkdir -p "$(dirname "$profile")"
printf 'foreign profile\n' > "$profile"
podium install --modules executors --adopt >/dev/null 2>&1
# Sanity: the ledger should record this file as adopted.
check "ledger marked profile as adopted before uninstall" \
  "python3 -c \"import json;d=json.load(open('$STATE_DIR/owned.json'));print(bool(d.get('adopted'))) \" | grep -qx True"

# Edit an owned file (the claude-md block keeps user content outside the block;
# a non-block owned file is what surfaces as "[keep]" in the uninstall plan).
claude_md="$HOME/.claude/CLAUDE.md"
printf 'user edit after install\n' >> "$claude_md"
# Pick an owned agent file (executor-profile.md is the adopted one; minimax.md
# is owned and not adopted, so editing it produces a "[keep]" line).
edited_agent="$HOME/.config/opencode/agents/minimax.md"
printf '\nuser edit after install\n' >> "$edited_agent"

podium uninstall >/tmp/u2.log 2>&1
check "uninstall-2 exit 0" "[ $? -eq 0 ]"
check "uninstall: adopted file restored from backup" \
  'test -f "$profile" && grep -q "foreign profile" "$profile"'
check "uninstall: edited agent file kept (not removed)" \
  'test -f "$edited_agent" && grep -q "user edit after install" "$edited_agent"'
check "uninstall: edited CLAUDE.md block removed (block goes, surrounding text kept)" \
  'grep -q "user edit after install" "$claude_md" && ! grep -q "podium:begin claude-md" "$claude_md"'
check "uninstall plan printed [keep] for edited agent file" \
  "grep -q 'modified since podium wrote it; left in place' /tmp/u2.log"
check "uninstall plan printed [restore] for adopted file" \
  "grep -q '\\[restore\\]' /tmp/u2.log"

# ============================================================================
section "uninstall leaves podium.toml and the checkout"
# ============================================================================

check "uninstall: podium.toml still present" "test -s $PODIUM_TOML"
check "uninstall: podium checkout directory still present" \
  "test -d $HOME/.local/share/podium/repo"
check "uninstall: podium symlink still present" \
  "test -L $HOME/.local/bin/podium"

finish