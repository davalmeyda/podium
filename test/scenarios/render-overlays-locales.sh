#!/bin/sh
# needs: none
#
# Scenario S6 (matrix §9): render/diff semantics, overlays through the real CLI
# (+ install), language rendering of CLAUDE.md / AGENTS.md / agent files,
# runtime.json ui, ui validation, ${VAR} expansion, module toggles, agent
# pruning on install, render.vars in overlays, and the claude-only preset
# rendering no agents.
#
# Defects fixed by other agents while this was being written that we DO assert
# here: 1, 2 (doctor, not under test here), 3 (roster_preset custom exists),
# 4, 6, 8 (plugins / scripted, not under test here), 9 (memory MCP inside
# opencode.json — we assert the opencode.json entry, the Claude-side hook
# stays for scenario memory-stop).
. /src/test/scenarios/lib.sh

# Overlay directory for claude-md, emptied before each overlay case so that a
# leftover file from an earlier case cannot change the outcome of this one.
# (A .md file in the overlay dir that no [[insert]] references is a replacement
# for a fragment id, so a stale file would fail the render.)
overlay_reset() {
  rm -rf "$HOME/.config/podium/overlays"
  mkdir -p "$HOME/.config/podium/overlays/claude-md"
}

# ---------------------------------------------------------------------------
# 0. render / diff baseline
# ---------------------------------------------------------------------------
section "render and diff: all targets separator, --target, --out, unknown exit"
# Bootstrap completes a printf-only snapshot commit of /src into /tmp/podium-src.
bootstrap
podium_init "$(default_answers opencode-multi)" >/dev/null

# render with no --target prints the per-target separator between bodies.
podium render > /tmp/render-all.out 2>&1
rc=$?
check "render (all targets) exit 0" "[ $rc -eq 0 ]"
check "render separator for claude-md" "grep -q '<!-- podium render: claude-md -->' /tmp/render-all.out"
check "render separator for opencode-agents-md" \
  "grep -q '<!-- podium render: opencode-agents-md -->' /tmp/render-all.out"
check "render separator for executor-profile" \
  "grep -q '<!-- podium render: executor-profile -->' /tmp/render-all.out"

# render --target prints only that target's body (no separator).
podium render --target claude-md > /tmp/render-one.out 2>&1
check "render --target emits no separator" \
  "! grep -q '<!-- podium render:' /tmp/render-one.out"
# opencode-multi: the claude-md roster-opencode fragment (requires an opencode
# row) and its launch examples are rendered.
check "opencode-multi claude-md has Writer executor via OpenCode" \
  "grep -qF 'Writer executor via OpenCode' /tmp/render-one.out"
check "opencode-multi claude-md has opencode run" \
  "grep -qF 'opencode run' /tmp/render-one.out"

# render --out writes files named <DIR>/<id>.md and prints "wrote <path>".
outdir=$HOME/render-out
podium render --out "$outdir" > /tmp/render-out.stdout 2>&1
check "render --out exit 0" "[ $? -eq 0 ]"
check "render --out writes claude-md.md" "test -s $outdir/claude-md.md"
check "render --out writes opencode-agents-md.md" "test -s $outdir/opencode-agents-md.md"
check "render --out writes executor-profile.md" "test -s $outdir/executor-profile.md"
check "render --out prints wrote for claude-md" "grep -q '^wrote .*/claude-md.md$' /tmp/render-out.stdout"
check "render --out prints wrote for executor-profile" \
  "grep -q '^wrote .*/executor-profile.md$' /tmp/render-out.stdout"

# unknown target -> exit 1, stderr names the target.
podium render --target nope > /tmp/render-bad.stdout 2> /tmp/render-bad.stderr
rc=$?
echo "render --target nope exit: $rc"
check "render unknown target exit 1" "[ $rc -eq 1 ]"
check "render unknown target stderr names target" \
  "grep -q 'unknown target: nope' /tmp/render-bad.stderr"
check "render unknown target stderr prefix" \
  "head -n1 /tmp/render-bad.stderr | grep -q '^podium: '"

# diff before install: no block is on disk yet, so cli.py diffs against
# /dev/null (no "[on disk]" header); the rendered side is always "[rendered]".
podium diff --target claude-md > /tmp/diff-pre.out 2>&1
check "diff before install shows [rendered] header" \
  "grep -qF '[rendered]' /tmp/diff-pre.out"
check "diff before install diffs against /dev/null" \
  "grep -qx -- '--- /dev/null' /tmp/diff-pre.out"

# Install with rules + executors to write blocks and agent files. We restrict
# the modules to avoid invoking the `claude plugin ...` commands.
podium install --modules rules,executors > /tmp/install0.log 2>&1
check "install (rules+executors) exit 0" "[ $? -eq 0 ]"
check "install wrote claude-md block" \
  "grep -q 'podium:begin claude-md' $HOME/.claude/CLAUDE.md"
check "install wrote opencode-agents-md block" \
  "grep -q 'podium:begin opencode-agents-md' $HOME/.config/opencode/AGENTS.md"
check "install wrote executor-profile" \
  "test -s $HOME/.local/state/podium/executor-profile.md"
check "install wrote agent minimax" "test -s $HOME/.config/opencode/agents/minimax.md"
check "install wrote agent sol"     "test -s $HOME/.config/opencode/agents/sol.md"
check "install wrote agent luna"    "test -s $HOME/.config/opencode/agents/luna.md"

# diff after install is clean.
podium diff > /tmp/diff-clean.out 2>&1
check "diff after install prints no differences" \
  "tail -n 1 /tmp/diff-clean.out | grep -qx 'no differences'"

# diff --target agents works for the opencode-multi preset.
podium diff --target agents > /tmp/diff-agents.out 2>&1
check "diff --target agents exit 0" "[ $? -eq 0 ]"
check "diff --target agents shows minimax up to date" \
  "grep -q 'agent minimax: up to date' /tmp/diff-agents.out"
check "diff --target agents shows sol up to date" \
  "grep -q 'agent sol: up to date' /tmp/diff-agents.out"
check "diff --target agents shows luna up to date" \
  "grep -q 'agent luna: up to date' /tmp/diff-agents.out"

# Flip the response language in podium.toml and confirm diff shows a unified
# diff. The response language reaches CLAUDE.md through principal-decides.md:
# "Answers to the user are in **{{ language.response_name }}**."
sed -i 's/^response = "en"/response = "es"/' "$PODIUM_TOML"
podium diff --target claude-md > /tmp/diff-after-edit.out 2>&1
check "diff after podium.toml change shows unified diff" \
  "grep -q '^@@' /tmp/diff-after-edit.out"
check "diff after podium.toml change shows [on disk] header" \
  "grep -qF '[on disk]' /tmp/diff-after-edit.out"
check "diff after podium.toml change has -Answers to the user in English" \
  "grep -qE '^-.*Answers to the user are in \\*\\*English\\*\\*\\.' /tmp/diff-after-edit.out"
check "diff after podium.toml change has +Answers to the user in Spanish" \
  "grep -qE '^\\+.*Answers to the user are in \\*\\*Spanish\\*\\*\\.' /tmp/diff-after-edit.out"
# Restore for the next sections.
sed -i 's/^response = "es"/response = "en"/' "$PODIUM_TOML"
podium install --modules rules,executors > /tmp/install0-restore.log 2>&1
check "install after revert exit 0" "[ $? -eq 0 ]"

# ---------------------------------------------------------------------------
# 1. Overlays through the real CLI + install
# ---------------------------------------------------------------------------
section "Overlays: replace, insert after/before, omit, errors via real CLI"

# replace a fragment with templating.
overlay_reset
printf '## Custom replace\n\nHello {{ language.response_name }}.\n' \
  > "$HOME/.config/podium/overlays/claude-md/habits.md"
podium render --target claude-md > /tmp/over-replace.out 2>&1
check "overlay replace shows custom body" \
  "grep -q 'Custom replace' /tmp/over-replace.out"
check "overlay replace gets templated language" \
  "grep -q 'Hello English' /tmp/over-replace.out"
check "overlay replace removes the original fragment" \
  "! grep -q '^# Orchestration rules' /tmp/over-replace.out"

# insert after an anchor — `cost-model` exists in the manifest. Its first
# heading is "### Consumption and time"; the fragment after it (context-diet)
# starts with "### Delegated exploration and the principal".
printf 'INSERT-AFTER-MARKER\n' \
  > "$HOME/.config/podium/overlays/claude-md/extra.md"
printf '[[insert]]\nfile = "extra.md"\nafter = "cost-model"\n' \
  > "$HOME/.config/podium/overlays/claude-md/insert.toml"
podium render --target claude-md > /tmp/over-insert-after.out 2>&1
order_ok=$(awk '
    index($0, "### Consumption and time") && !c { c = NR }
    index($0, "INSERT-AFTER-MARKER") && !b { b = NR }
    index($0, "### Delegated exploration and the principal") && !d { d = NR }
    END { if (c && b && d && c < b && b < d) print "ok"; else print "bad " c " " b " " d }' /tmp/over-insert-after.out)
check "insert-after places file between anchor and the fragment after it" \
  "[ \"$order_ok\" = ok ]"
after_prev=$(awk '
    /^### Delegated exploration and the principal/ { print prev; exit }
    NF { prev = $0 }' /tmp/over-insert-after.out)
check "insert-after: marker is the non-blank line right before the next fragment" \
  "[ \"$after_prev\" = INSERT-AFTER-MARKER ]"

# switch to insert before (same file, same anchor).
cat > "$HOME/.config/podium/overlays/claude-md/insert.toml" <<'EOF'
[[insert]]
file = "extra.md"
before = "cost-model"
EOF
podium render --target claude-md > /tmp/over-insert-before.out 2>&1
order_ok=$(awk '
    index($0, "### The principal decides, the agents execute") && !p { p = NR }
    index($0, "INSERT-AFTER-MARKER") && !b { b = NR }
    index($0, "### Consumption and time") && !c { c = NR }
    END { if (p && b && c && p < b && b < c) print "ok"; else print "bad " p " " b " " c }' /tmp/over-insert-before.out)
check "insert-before places file right before the anchor" \
  "[ \"$order_ok\" = ok ]"
before_next=$(awk '
    /^### Consumption and time/ { print prev; exit }
    NF { prev = $0 }' /tmp/over-insert-before.out)
check "insert-before: marker is the non-blank line right before the anchor" \
  "[ \"$before_next\" = INSERT-AFTER-MARKER ]"

# omit a fragment. Start from an empty overlay dir: extra.md is no longer
# referenced by an insert, so it must not stay behind.
overlay_reset
printf 'omit = ["cost-model"]\n' > "$HOME/.config/podium/overlays/claude-md/insert.toml"
podium render --target claude-md > /tmp/over-omit.out 2>&1
check "overlay omit exit 0" "[ $? -eq 0 ]"
check "overlay omit removes the listed fragment" \
  "! grep -qF '### Consumption and time' /tmp/over-omit.out"
check "overlay omit keeps the other fragments" \
  "grep -qF '### Delegated exploration and the principal' /tmp/over-omit.out"

# All overlay errors through the real CLI: each exits 1 and names the cause.
# Each case starts from an empty overlay dir so only its own file is present.

# 1) unknown fragment id (replaces unknown fragment).
overlay_reset
printf 'x\n' > "$HOME/.config/podium/overlays/claude-md/nonexistent.md"
podium render --target claude-md > /tmp/over-err1.out 2> /tmp/over-err1.err
rc=$?
check "overlay unknown fragment exit 1" "[ $rc -eq 1 ]"
check "overlay unknown fragment message" \
  "grep -q 'replaces unknown fragment: nonexistent' /tmp/over-err1.err"

# 2) unknown anchor in insert.toml (after <id>).
overlay_reset
printf 'X\n' > "$HOME/.config/podium/overlays/claude-md/xx.md"
cat > "$HOME/.config/podium/overlays/claude-md/insert.toml" <<'EOF'
[[insert]]
file = "xx.md"
after = "ghost"
EOF
podium render --target claude-md > /tmp/over-err2.out 2> /tmp/over-err2.err
rc=$?
check "overlay unknown anchor exit 1" "[ $rc -eq 1 ]"
check "overlay unknown anchor message" \
  "grep -q 'after anchor references unknown fragment: ghost' /tmp/over-err2.err"

# 3) missing file referenced from insert.toml.
overlay_reset
cat > "$HOME/.config/podium/overlays/claude-md/insert.toml" <<'EOF'
[[insert]]
file = "absent.md"
after = "habits"
EOF
podium render --target claude-md > /tmp/over-err3.out 2> /tmp/over-err3.err
rc=$?
check "overlay insert file missing exit 1" "[ $rc -eq 1 ]"
check "overlay insert file missing message" \
  "grep -q 'insert file not found' /tmp/over-err3.err"

# 4) both after and before in a single insert.
overlay_reset
printf 'X\n' > "$HOME/.config/podium/overlays/claude-md/xx.md"
cat > "$HOME/.config/podium/overlays/claude-md/insert.toml" <<'EOF'
[[insert]]
file = "xx.md"
after = "habits"
before = "orchestration"
EOF
podium render --target claude-md > /tmp/over-err4.out 2> /tmp/over-err4.err
rc=$?
check "overlay both after+before exit 1" "[ $rc -eq 1 ]"
check "overlay both after+before message" \
  "grep -q 'needs exactly one of' /tmp/over-err4.err"

# 5) unknown top-level key in insert.toml.
overlay_reset
cat > "$HOME/.config/podium/overlays/claude-md/insert.toml" <<'EOF'
bogus = ["x"]
EOF
podium render --target claude-md > /tmp/over-err5.out 2> /tmp/over-err5.err
rc=$?
check "overlay unknown key in insert.toml exit 1" "[ $rc -eq 1 ]"
check "overlay unknown key in insert.toml message" \
  "grep -q 'unknown key: bogus' /tmp/over-err5.err"

# Overlay through real install: fragment replace makes it onto disk.
overlay_reset
printf '## Installed replace\n\nInstalled body {{ language.response_name }}.\n' \
  > "$HOME/.config/podium/overlays/claude-md/habits.md"
podium install --modules rules,executors > /tmp/install-over.log 2>&1
check "overlay replace made it to CLAUDE.md" \
  "grep -q 'Installed replace' $HOME/.claude/CLAUDE.md"
check "overlay templating ran on the replaced fragment" \
  "grep -q 'Installed body English' $HOME/.claude/CLAUDE.md"
check "overlay replace: original 'Orchestration rules' line is gone" \
  "! grep -q '^# Orchestration rules' $HOME/.claude/CLAUDE.md"

rm -rf "$HOME/.config/podium/overlays"
podium install --modules rules,executors > /tmp/install-after.log 2>&1

# ---------------------------------------------------------------------------
# 2. Language: response / domain render Spanish into CLAUDE.md, AGENTS.md,
#    every agent file.
#    CLAUDE.md: principal-decides.md carries the response language
#    ("Answers to the user are in **<name>**.") and the domain language
#    ("... MUST be in <name>, exactly as quoted."). AGENTS.md: oc-language.md
#    ("Always answer the user in <name>."). Agent files: ex-language.md.
# ---------------------------------------------------------------------------
section "language.response=es, domain=es: Spanish in CLAUDE.md, AGENTS.md, agents"

# Reset to English so we can prove the change is what flipped the strings.
sed -i 's/^response = "es"/response = "en"/' "$PODIUM_TOML"
sed -i 's/^domain = "es"/domain = "en"/' "$PODIUM_TOML"
sed -i 's/^ui = "es"/ui = "en"/' "$PODIUM_TOML"
podium install --modules rules,executors > /tmp/install-en.log 2>&1
check "English install exit 0" "[ $? -eq 0 ]"
check "English CLAUDE.md says answers are in English" \
  "grep -qF 'Answers to the user are in **English**.' $HOME/.claude/CLAUDE.md"
check "English AGENTS.md says answer in English" \
  "grep -q 'Always answer the user in English' $HOME/.config/opencode/AGENTS.md"

sed -i 's/^response = "en"/response = "es"/' "$PODIUM_TOML"
sed -i 's/^domain = "en"/domain = "es"/' "$PODIUM_TOML"
podium install --modules rules,executors > /tmp/install-es.log 2>&1
check "Spanish install exit 0" "[ $? -eq 0 ]"
check "Spanish CLAUDE.md (principal-decides) says answers are in Spanish" \
  "grep -qF 'Answers to the user are in **Spanish**.' $HOME/.claude/CLAUDE.md"
check "Spanish AGENTS.md (oc-language fragment) says answer in Spanish" \
  "grep -q 'Always answer the user in Spanish' $HOME/.config/opencode/AGENTS.md"
# Every agent file is rendered with the executor profile, which carries the
# ex-language rule (Spanish literals must be quoted verbatim).
check "Spanish minimax.md ex-language rule (domain Spanish quoted)" \
  "grep -q 'written in Spanish' $HOME/.config/opencode/agents/minimax.md"
check "Spanish sol.md ex-language rule (domain Spanish)" \
  "grep -q 'written in Spanish' $HOME/.config/opencode/agents/sol.md"
check "Spanish luna.md ex-language rule (domain Spanish)" \
  "grep -q 'written in Spanish' $HOME/.config/opencode/agents/luna.md"
# principal-decides carries a domain-literal rule too.
check "Spanish CLAUDE.md carries the domain literal rule" \
  "grep -q 'MUST be in Spanish' $HOME/.claude/CLAUDE.md"

# ---------------------------------------------------------------------------
# 3. language.ui = es -> runtime.json ui=es; ui=fr -> exact validation error
# ---------------------------------------------------------------------------
section "language.ui=es -> runtime.json ui=es; language.ui=fr -> exit 1"
sed -i 's/^ui = "en"/ui = "es"/' "$PODIUM_TOML"
podium install --modules rules,executors > /tmp/install-ui-es.log 2>&1
check "install with ui=es exit 0" "[ $? -eq 0 ]"
check "runtime.json ui is es" \
  "python3 -c \"import json;print(json.load(open('$RUNTIME_JSON'))['ui'])\" | grep -qx es"

# ui=fr is rejected by config validation -> exit 1, exact message.
sed -i 's/^ui = "es"/ui = "fr"/' "$PODIUM_TOML"
podium install --modules rules,executors > /tmp/install-ui-fr.out 2> /tmp/install-ui-fr.err
rc=$?
echo "ui=fr install exit: $rc"
check "ui=fr install exit 1" "[ $rc -eq 1 ]"
check "ui=fr exact validation error" \
  "grep -q \"language.ui must be one of: en, es, got 'fr'\" /tmp/install-ui-fr.err"

# Reset ui to en for the rest.
sed -i 's/^ui = "fr"/ui = "en"/' "$PODIUM_TOML"

# ---------------------------------------------------------------------------
# 4. ${VAR} in memory.url expands at install; unset variable -> exact error
# ---------------------------------------------------------------------------
section '${VAR} in memory.url expands; unset variable -> exit 1'

# Re-init with opencode-multi and a memory url that uses ${PODIUM_TEST_URL}.
# `podium init` does not expand ${VAR} at write time, it leaves it literal,
# so the variable is expanded when the config is loaded at install.
# PODIUM_TEST_URL is still unset here: init must accept the literal ${VAR}.
podium_init '{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules","executors","codegraph","memory"],"roster_preset":"opencode-multi","memory":{"url":"${PODIUM_TEST_URL}"},"overwrite":true}' >/tmp/init-var.out 2>&1
rc=$?
check 'init with unset ${PODIUM_TEST_URL} exit 0' "[ $rc -eq 0 ]"
check 'init wrote memory block with literal ${PODIUM_TEST_URL}' \
  "grep -q 'url = \"\${PODIUM_TEST_URL}\"' $PODIUM_TOML"

# Set the variable and install with codegraph+memory: opencode.json must
# contain the expanded value.
PODIUM_TEST_URL="http://127.0.0.1:1234/m" \
podium install --modules rules,executors,codegraph,memory > /tmp/install-var.log 2>&1
rc=$?
echo "install code (var set): $rc"
check "install with VAR set exit 0" "[ $rc -eq 0 ]"
check "opencode.json memory MCP url is the expanded value" \
  "python3 -c \"import json;d=json.load(open('$HOME/.config/opencode/opencode.json'));print(d['mcp']['graphiti-memory']['url'])\" | grep -qx 'http://127.0.0.1:1234/m'"
check "opencode.json memory MCP type is remote" \
  "python3 -c \"import json;d=json.load(open('$HOME/.config/opencode/opencode.json'));print(d['mcp']['graphiti-memory']['type'])\" | grep -qx 'remote'"

# Now unset the variable and install again. Config load fails -> exit 1 with
# the exact error naming the variable and the dotted path.
unset PODIUM_TEST_URL
podium install --modules rules,executors,codegraph,memory > /tmp/install-novar.out 2> /tmp/install-novar.err
rc=$?
echo "install code (var unset): $rc"
check "install with VAR unset exit 1" "[ $rc -eq 1 ]"
check "install with VAR unset exact error" \
  "grep -q 'environment variable PODIUM_TEST_URL is not set (used in memory.url)' /tmp/install-novar.err"

# Restore for the next sections by giving the variable a value.
PODIUM_TEST_URL="http://127.0.0.1:1234/m" \
podium install --modules rules,executors,codegraph,memory > /tmp/install-var2.log 2>&1
check "install after restore exit 0" "[ $? -eq 0 ]"

# ---------------------------------------------------------------------------
# 5. Module toggles: rules off -> no CLAUDE.md block; codegraph off -> no MCP
# ---------------------------------------------------------------------------
section "modules.rules=false -> no CLAUDE.md block; modules.codegraph=false -> no codegraph MCP"

# rules off: the managed block in CLAUDE.md is removed.
sed -i 's/^rules = true/rules = false/' "$PODIUM_TOML"
PODIUM_TEST_URL="http://127.0.0.1:1234/m" \
podium install --modules rules,executors,codegraph,memory > /tmp/install-rules-off.log 2>&1
check "rules off install exit 0" "[ $? -eq 0 ]"
check "rules off: claude-md block absent" \
  "! grep -q 'podium:begin claude-md' $HOME/.claude/CLAUDE.md"
check "rules off: opencode-agents-md block absent" \
  "! grep -q 'podium:begin opencode-agents-md' $HOME/.config/opencode/AGENTS.md"
# Re-enable and reinstall.
sed -i 's/^rules = false/rules = true/' "$PODIUM_TOML"
PODIUM_TEST_URL="http://127.0.0.1:1234/m" \
podium install --modules rules,executors,codegraph,memory > /tmp/install-rules-on.log 2>&1
check "rules back on: claude-md block reappears" \
  "grep -q 'podium:begin claude-md' $HOME/.claude/CLAUDE.md"

# codegraph off: no /mcp/codegraph in opencode.json AND no codegraph fragment
# block on disk in CLAUDE.md (because the codegraph module is off).
sed -i 's/^codegraph = true/codegraph = false/' "$PODIUM_TOML"
PODIUM_TEST_URL="http://127.0.0.1:1234/m" \
podium install --modules rules,executors,codegraph,memory > /tmp/install-cg-off.log 2>&1
check "codegraph off install exit 0" "[ $? -eq 0 ]"
check "codegraph off: no /mcp/codegraph" \
  "python3 -c \"import json;d=json.load(open('$HOME/.config/opencode/opencode.json'));print('codegraph' in d.get('mcp',{}))\" | grep -qx False"
check "codegraph off: no codegraph fragment in CLAUDE.md" \
  "! grep -q '## CodeGraph' $HOME/.claude/CLAUDE.md"
# `claude plugin uninstall` leaves the plugin cache on disk; the installed list is what counts.
check "codegraph off: codegraph plugin uninstalled" \
  "claude plugin list >/tmp/plugins-cg-off.txt 2>&1 && grep -q 'podium-usage@podium\|podium-memory@podium' /tmp/plugins-cg-off.txt && ! grep -q 'podium-codegraph@podium' /tmp/plugins-cg-off.txt"

# Restore codegraph module.
sed -i 's/^codegraph = false/codegraph = true/' "$PODIUM_TOML"
PODIUM_TEST_URL="http://127.0.0.1:1234/m" \
podium install --modules rules,executors,codegraph,memory > /tmp/install-cg-on.log 2>&1
check "codegraph on: /mcp/codegraph present" \
  "python3 -c \"import json;d=json.load(open('$HOME/.config/opencode/opencode.json'));print(d['mcp']['codegraph']['type'])\" | grep -qx 'local'"

# ---------------------------------------------------------------------------
# 6. Removing an [[agents]] entry prunes its file on next install
# ---------------------------------------------------------------------------
section "Removing an [[agents]] entry prunes its file on the next install"
# All three agents are on disk after the previous install.
check "sol.md present before prune" "test -s $HOME/.config/opencode/agents/sol.md"

# Drop the `[[agents]] name = "sol"` block from the toml and reinstall.
python3 - "$PODIUM_TOML" <<'PY'
import sys, re
p = sys.argv[1]
text = open(p, "r", encoding="utf-8").read()
# Remove the sol agent block (single block, one line per field).
pattern = re.compile(r"\[\[agents\]\][^\[]*?name = \"sol\".*?(?=\n\[\[agents\]\]|\n\[roster_notes\]|\Z)",
                    re.DOTALL)
new = pattern.sub("", text)
open(p, "w", encoding="utf-8").write(new)
PY
check "sol [[agents]] block removed from toml" \
  "! grep -q 'name = \"sol\"' $PODIUM_TOML"

PODIUM_TEST_URL="http://127.0.0.1:1234/m" \
podium install --modules rules,executors,codegraph,memory > /tmp/install-prune.log 2>&1
check "install after agent removal exit 0" "[ $? -eq 0 ]"
check "sol.md pruned from agents dir" \
  "test ! -e $HOME/.config/opencode/agents/sol.md"
check "minimax.md still present after prune" \
  "test -s $HOME/.config/opencode/agents/minimax.md"
check "luna.md still present after prune" \
  "test -s $HOME/.config/opencode/agents/luna.md"
check "prune plan line printed [remove] for sol.md" \
  "grep -qE '^\\[remove\\] .*agents/sol\\.md' /tmp/install-prune.log"

# ---------------------------------------------------------------------------
# 7. render.vars and {{ vars.x }} in overlays
# ---------------------------------------------------------------------------
section "render.vars / {{ vars.x }} in an overlay"

# init fresh and add a custom render.vars block.
podium_init '{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules","executors"],"roster_preset":"opencode-multi","overwrite":true}' >/dev/null
# render.vars is just TOML appended; the config loader accepts unknown tables
# other than a few well-known ones, but [render] is allowed (see ARCHITECTURE §4).
printf '\n[render]\nvars = { project = "podium-tests", stage = "ci" }\n' >> "$PODIUM_TOML"
podium install --modules rules,executors > /tmp/install-vars.log 2>&1
check "install with render.vars exit 0" "[ $? -eq 0 ]"

# Overlay a fragment that uses {{ vars.project }} / {{ vars.stage }} and
# confirm the values are substituted.
overlay_reset
cat > "$HOME/.config/podium/overlays/claude-md/habits.md" <<'EOF'
## Vars demo
project={{ vars.project }} stage={{ vars.stage }}
EOF
podium render --target claude-md > /tmp/render-vars.out 2>&1
check "overlay rendered with vars.project" \
  "grep -q 'project=podium-tests' /tmp/render-vars.out"
check "overlay rendered with vars.stage" \
  "grep -q 'stage=ci' /tmp/render-vars.out"

# ---------------------------------------------------------------------------
# 8. claude-only preset renders no agents
# ---------------------------------------------------------------------------
section "roster_preset=claude-only: no [[agents]], no agent files"
rm -rf "$HOME/.config/podium/overlays"
podium_init '{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules","executors"],"roster_preset":"claude-only","overwrite":true}' >/dev/null
check "claude-only toml has no [[agents]] table" \
  "! grep -q '^\\[\\[agents\\]\\]' $PODIUM_TOML"

# claude-only: the roster-opencode fragment is gated by requires =
# "opencode-executors", so the claude-md render has no OpenCode writer section.
podium render --target claude-md > /tmp/render-claude-only.out 2>&1
check "claude-only claude-md render exit 0" "[ $? -eq 0 ]"
check "claude-only claude-md has no Writer executor via OpenCode" \
  "! grep -qF 'Writer executor via OpenCode' /tmp/render-claude-only.out"
check "claude-only claude-md has no opencode run" \
  "! grep -qF 'opencode run' /tmp/render-claude-only.out"

# drop the existing agent files so the bench starts from a clean state for
# the agent-file existence check (the previous tests created sol.md/minimax.md/
# luna.md which `podium install` would NOT remove without --force because the
# ledger says they're owned and the current config no longer renders them.
# `podium install --modules rules,executors` will not remove them silently:
# we delete them by hand to simulate the post-prune state of an external
# install.
rm -f "$HOME/.config/opencode/agents/minimax.md" \
      "$HOME/.config/opencode/agents/sol.md" \
      "$HOME/.config/opencode/agents/luna.md"
# also drop the ledger so the install does not flag them as missing owned
# files. The user is moving to a fresh preset.
rm -rf "$STATE_DIR"

podium install --modules rules,executors > /tmp/install-co.log 2>&1
check "claude-only install exit 0" "[ $? -eq 0 ]"
check "claude-only: no agent files" \
  "! ls $HOME/.config/opencode/agents/*.md >/dev/null 2>&1"
check "claude-only: claude-md block written" \
  "grep -q 'podium:begin claude-md' $HOME/.claude/CLAUDE.md"
check "claude-only: AGENTS.md block written" \
  "grep -q 'podium:begin opencode-agents-md' $HOME/.config/opencode/AGENTS.md"
check "claude-only: AGENTS.md block has the language rule" \
  "grep -q 'Always answer the user in English' $HOME/.config/opencode/AGENTS.md"

finish
