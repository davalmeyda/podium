#!/bin/sh
# S3a: `podium detect` shape and provider ids, `podium init` (non-interactive
# answers + interactive wizard), and the opencode-multi missing-provider
# WARNING path (present when the host has no `minimax`/`openai` creds,
# absent when it does).
#
# needs: opencode
. /src/test/scenarios/lib.sh

# Bootstraps the working tree into $HOME/.local/share/podium/repo and
# symlinks $HOME/.local/bin/podium so the rest of the scenario can call
# `podium` directly. Subsequent bootstrap calls into a different HOME are
# driven from /tmp/podium-src (the snapshot created here).
section "bootstrap"
bootstrap
check "podium on PATH" "command -v podium"
check "/tmp/podium-src snapshot exists for nested bootstrap calls" \
  "test -d /tmp/podium-src"

# ---------------------------------------------------------------------------
# detect --json: keys + provider ids from real opencode auth list
# ---------------------------------------------------------------------------
section "detect --json envelope and provider ids"
podium detect --json > /tmp/detect.json
keys=$(python3 - <<'PYEOF'
import json
with open("/tmp/detect.json") as fh:
    d = json.load(fh)
print(",".join(sorted(d.keys())))
print(",".join(sorted(d["tools"].keys())))
print(",".join(sorted(d["opencode"].keys())))
print(",".join(sorted(d["claude"].keys())))
print(",".join(sorted(d["podium"].keys())))
print(json.dumps(d["opencode"]["providers"]))
PYEOF
)
echo "$keys"
top=$(printf '%s\n' "$keys" | sed -n '1p')
tools=$(printf '%s\n' "$keys" | sed -n '2p')
okeys=$(printf '%s\n' "$keys" | sed -n '3p')
ckeys=$(printf '%s\n' "$keys" | sed -n '4p')
pkeys=$(printf '%s\n' "$keys" | sed -n '5p')
provs=$(printf '%s\n' "$keys" | sed -n '6p')
echo "DEBUG provs=[$provs]"
check "top-level keys" "[ \"$top\" = 'claude,kernel,opencode,os,podium,python,tools' ]"
check "tools keys" "[ \"$tools\" = 'claude,codegraph,git,opencode' ]"
check "opencode keys" "[ \"$okeys\" = 'agents,config_files,mcp,providers' ]"
check "claude keys" "[ \"$ckeys\" = 'legacy_hooks,plugins_installed' ]"
check "podium keys" "[ \"$pkeys\" = 'config_exists,ledger_exists' ]"
# providers come from `opencode auth list`; the real output is
# "MiniMax (minimax.io)  API key  stored" and "OpenAI  OAuth  stored", whose
# first whitespace-separated tokens lower-case to minimax and openai (defect 5).
expected_provs='["minimax", "openai"]'
check "providers are exactly minimax,openai (lower-cased first token)" \
  "[ \"\$provs\" = \"\$expected_provs\" ]"

section "detect (human output: indented key: value lines)"
podium detect > /tmp/detect.txt 2>&1
echo "--- detect human output ---"
cat /tmp/detect.txt
echo "--- end ---"
check "human output starts with 'os: ' line" "head -1 /tmp/detect.txt | grep -q '^os: '"
# providers are nested under the top-level 'opencode:' block (cli._human indents
# nested dicts/lists by two spaces per level), so the section is '  providers:'.
check "human output has 'opencode:' section" "grep -q '^opencode:' /tmp/detect.txt"
check "human output has indented 'providers:' under opencode" "grep -q '^  providers:' /tmp/detect.txt"
check "human output lists provider minimax as a list item" "grep -q '^    - minimax$' /tmp/detect.txt"
check "human output lists provider openai as a list item" "grep -q '^    - openai$' /tmp/detect.txt"
check "human output has 'podium:' section" "grep -q '^podium:' /tmp/detect.txt"
check "human output has 'claude:' section" "grep -q '^claude:' /tmp/detect.txt"
check "human output is not JSON" "! grep -q '^{' /tmp/detect.txt"

# ---------------------------------------------------------------------------
# install -> agents get a ledger entry -> detect marks them podium_owned
# ---------------------------------------------------------------------------
section "after install, detect reports rendered agents as podium_owned"
# A clean init with the opencode-multi preset; the runner-imported creds
# supply the required providers, so init writes no missing-provider WARNING.
podium_init "$(default_answers opencode-multi)" >/dev/null
check "init wrote podium.toml with the opencode-multi preset" \
  "test -s $PODIUM_TOML && grep -q '\"minimax-fast\"' $PODIUM_TOML"
# Restricted install keeps the scenario offline-friendly (no plugin crates).
podium install --modules rules,executors > /tmp/install.log 2>&1
rc=$?
echo "install exit: $rc"
check "install exit 0" "[ $rc -eq 0 ]"
check "agents rendered (minimax/sol/luna)" \
  "grep -q 'agent minimax' /tmp/install.log && grep -q 'agent sol' /tmp/install.log && grep -q 'agent luna' /tmp/install.log"
# After install, $STATE_DIR/owned.json lists the agent files; detect now
# reports podium_owned=true for every one of them (defect 5 fix).
podium detect --json > /tmp/detect2.json
owned=$(python3 - <<'PYEOF'
import json
with open("/tmp/detect2.json") as fh:
    d = json.load(fh)
print(",".join(sorted(a["name"] for a in d["opencode"]["agents"] if a["podium_owned"])))
print(",".join(sorted(a["name"] for a in d["opencode"]["agents"] if not a["podium_owned"])))
PYEOF
)
owned_yes=$(printf '%s\n' "$owned" | sed -n '1p')
owned_no=$(printf '%s\n' "$owned" | sed -n '2p')
echo "podium_owned: $owned_yes   not: $owned_no"
check "all three rendered agents are podium_owned" "[ \"$owned_yes\" = 'luna,minimax,sol' ]"
check "no user-owned agents" "[ -z \"$owned_no\" ]"

# ---------------------------------------------------------------------------
# init: dotted vs nested produce identical podium.toml
# ---------------------------------------------------------------------------
section "init: dotted keys and nested keys produce identical podium.toml"
CFG_NESTED=$HOME/.config/podium-nested
CFG_DOTTED=$HOME/.config/podium-dotted
rm -rf "$CFG_NESTED" "$CFG_DOTTED"
PODIUM_CONFIG_DIR=$CFG_NESTED PODIUM_STATE_DIR=$CFG_NESTED/.local/state/podium \
  podium init --non-interactive --answers /dev/stdin >/dev/null <<'JSON'
{"language":{"response":"es","domain":"es","ui":"es"},"modules":["rules","executors"],"memory":{"url":""},"roster_preset":"claude-only"}
JSON
printf '%s' '{"language.response":"es","language.domain":"es","language.ui":"es","modules":["rules","executors"],"memory.url":"","roster_preset":"claude-only"}' > /tmp/ans-dotted.json
PODIUM_CONFIG_DIR=$CFG_DOTTED PODIUM_STATE_DIR=$CFG_DOTTED/.local/state/podium \
  podium init --non-interactive --answers /tmp/ans-dotted.json >/dev/null
check "nested keys wrote a non-empty podium.toml" "test -s $CFG_NESTED/podium.toml"
check "dotted keys wrote a non-empty podium.toml" "test -s $CFG_DOTTED/podium.toml"
check "nested and dotted produce byte-identical podium.toml" \
  "diff -q $CFG_NESTED/podium.toml $CFG_DOTTED/podium.toml"

section "init: missing answer keys fall back to defaults"
# Drop the modules key entirely; init must still succeed and write all six
# module booleans as true.
printf '%s' '{"language":{"response":"en","domain":"en","ui":"en"},"memory":{"url":""},"roster_preset":"claude-only"}' > /tmp/ans-min.json
CFG_MIN=$HOME/.config/podium-min
rm -rf "$CFG_MIN"
PODIUM_CONFIG_DIR=$CFG_MIN PODIUM_STATE_DIR=$CFG_MIN/.local/state/podium \
  podium init --non-interactive --answers /tmp/ans-min.json >/dev/null
check "default modules all true (rules+executors+codegraph+memory+usage+upgrade)" \
  "grep -q '^rules = true' $CFG_MIN/podium.toml && \
   grep -q '^executors = true' $CFG_MIN/podium.toml && \
   grep -q '^codegraph = true' $CFG_MIN/podium.toml && \
   grep -q '^memory = true' $CFG_MIN/podium.toml && \
   grep -q '^usage = true' $CFG_MIN/podium.toml && \
   grep -q '^upgrade = true' $CFG_MIN/podium.toml"
check "default language written" "grep -q 'response = \"en\"' $CFG_MIN/podium.toml"

# ---------------------------------------------------------------------------
# init: refuses to overwrite, then with overwrite=true backs up the old file
# ---------------------------------------------------------------------------
section "init: refuses to overwrite an existing file without overwrite=true"
printf '%s' '{"roster_preset":"claude-only"}' > /tmp/ans-ow.json
CFG_OW=$HOME/.config/podium-ow
rm -rf "$CFG_OW"
PODIUM_CONFIG_DIR=$CFG_OW PODIUM_STATE_DIR=$CFG_OW/.local/state/podium \
  podium init --non-interactive --answers /tmp/ans-ow.json >/dev/null
# No `set -e` here: it would abort the scenario silently on the expected failure.
PODIUM_CONFIG_DIR=$CFG_OW PODIUM_STATE_DIR=$CFG_OW/.local/state/podium \
  podium init --non-interactive --answers /tmp/ans-ow.json >/tmp/ow.out 2>/tmp/ow.err
rc=$?
echo "second init exit: $rc"
echo "stderr: $(cat /tmp/ow.err)"
check "second init exit code is 1" "[ $rc -eq 1 ]"
check "second init error says 'refusing to overwrite'" \
  "grep -q 'refusing to overwrite' /tmp/ow.err"
check "second init error points at answers['overwrite']=true" \
  "grep -qE \"answers\\['overwrite'\\]=true\" /tmp/ow.err"

section "init: overwrite=true creates a .bak-podium-<stamp>-<4hex> backup"
printf '%s' '{"roster_preset":"claude-only","overwrite":true}' > /tmp/ans-ow2.json
PODIUM_CONFIG_DIR=$CFG_OW PODIUM_STATE_DIR=$CFG_OW/.local/state/podium \
  podium init --non-interactive --answers /tmp/ans-ow2.json >/dev/null
bak=$(ls "$CFG_OW"/podium.toml.bak-podium-* 2>/dev/null | head -1)
echo "backup: $bak"
check "exactly one backup file created" \
  "[ \$(ls '$CFG_OW'/podium.toml.bak-podium-* 2>/dev/null | wc -l) = 1 ]"
check "backup name matches the documented pattern (bak-podium-YYYYMMDD-HHMMSS-XXXX)" \
  "echo '$bak' | grep -Eq '/podium\\.toml\\.bak-podium-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}\$'"

# ---------------------------------------------------------------------------
# init: unknown preset -> 'roster preset not found', exit 1
# ---------------------------------------------------------------------------
section "init: unknown preset -> 'roster preset not found', exit 1"
printf '%s' '{"roster_preset":"does-not-exist"}' > /tmp/ans-bad.json
CFG_BAD=$HOME/.config/podium-bad
rm -rf "$CFG_BAD"
PODIUM_CONFIG_DIR=$CFG_BAD PODIUM_STATE_DIR=$CFG_BAD/.local/state/podium \
  podium init --non-interactive --answers /tmp/ans-bad.json >/tmp/bad.out 2>/tmp/bad.err
rc=$?
echo "bad preset exit: $rc"
echo "stderr: $(cat /tmp/bad.err)"
check "unknown preset exits 1" "[ $rc -eq 1 ]"
check "unknown preset message is 'roster preset not found'" \
  "grep -q 'roster preset not found' /tmp/bad.err"

# ---------------------------------------------------------------------------
# init: preset 'custom' writes one roster row, podium render ok (defect 3 fix)
# ---------------------------------------------------------------------------
section "init: roster_preset='custom' works end-to-end"
printf '%s' '{"roster_preset":"custom","modules":["rules","executors"]}' > /tmp/ans-custom.json
CFG_CUSTOM=$HOME/.config/podium-custom
rm -rf "$CFG_CUSTOM"
PODIUM_CONFIG_DIR=$CFG_CUSTOM PODIUM_STATE_DIR=$CFG_CUSTOM/.local/state/podium \
  podium init --non-interactive --answers /tmp/ans-custom.json >/dev/null
check "custom preset wrote schema = 1" "grep -q 'schema = 1' $CFG_CUSTOM/podium.toml"
check "custom preset wrote no [[agents]] block" \
  "! grep -q '^\\[\\[agents\\]\\]' $CFG_CUSTOM/podium.toml"
# Round-trip the file through `podium render` to prove it is loadable.
PODIUM_CONFIG_DIR=$CFG_CUSTOM PODIUM_STATE_DIR=$CFG_CUSTOM/.local/state/podium \
  podium render --target executor-profile > /tmp/render.out 2>&1
rc=$?
check "podium render --target executor-profile exit 0" "[ $rc -eq 0 ]"
check "rendered executor-profile has the 'executor' preamble" \
  "grep -q 'You are an \\*\\*executor\\*\\*' /tmp/render.out"
# One roster row in the parsed config.
rows=$(PODIUM_CONFIG_DIR=$CFG_CUSTOM python3 - <<'PYEOF'
import sys
sys.path.insert(0, "/home/tester/.local/share/podium/repo")
from podium.config import load
import os
cfg_dir = os.environ["PODIUM_CONFIG_DIR"]
data = load(cfg_dir, env={})
print(len(data["roster"]))
print(",".join(r["id"] for r in data["roster"]))
PYEOF
)
rows_n=$(printf '%s\n' "$rows" | sed -n '1p')
rows_ids=$(printf '%s\n' "$rows" | sed -n '2p')
echo "roster rows: $rows_n ids: $rows_ids"
check "custom preset has exactly one [[roster]] row (the principal)" "[ \"$rows_n\" = 1 ]"
check "custom preset roster row id is 'principal'" "[ \"$rows_ids\" = 'principal' ]"

# ---------------------------------------------------------------------------
# init with real creds: NO missing-provider WARNING for opencode-multi
# ---------------------------------------------------------------------------
section "init opencode-multi with real creds: no missing-provider WARNING"
rm -f "$PODIUM_TOML"
podium_init '{"roster_preset":"opencode-multi","modules":["rules","executors"]}' >/dev/null
check "podium.toml exists after init" "test -s $PODIUM_TOML"
check "opencode-multi init WITH creds has zero '# WARNING' blocks" \
  "! grep -q '^# WARNING' $PODIUM_TOML"
check "opencode-multi preset body is present" \
  "grep -q '\"minimax-fast\"' $PODIUM_TOML"

# ---------------------------------------------------------------------------
# init in a second HOME without OC creds: WARNING blocks appear
# ---------------------------------------------------------------------------
section "init opencode-multi in a second HOME without creds: WARNING appears"
# The runner already imported creds into the main HOME. Build a brand-new HOME
# at /tmp/nocreds-home and bootstrap podium there. The bootstrap is a local
# clone from /tmp/podium-src so it is fast and offline-friendly.
NOCRED_HOME=/tmp/nocreds-home
rm -rf "$NOCRED_HOME"
HOME="$NOCRED_HOME" \
  PODIUM_REPO_URL=/tmp/podium-src \
  PODIUM_REF="$(git -C /tmp/podium-src rev-parse --abbrev-ref HEAD)" \
  sh /tmp/podium-src/install.sh >/tmp/nocreds-install.log 2>&1
# install.sh lives at the bootstrap tree, available throughout the scenario.
NOCRED_BIN="$NOCRED_HOME/.local/bin/podium"
check "podium was linked into the new HOME" "test -x $NOCRED_BIN"
mkdir -p "$NOCRED_HOME/.config/podium" "$NOCRED_HOME/.local/state/podium"
printf '%s' '{"roster_preset":"opencode-multi","modules":["rules","executors"]}' > /tmp/ans-nocred.json
HOME="$NOCRED_HOME" \
  PODIUM_CONFIG_DIR="$NOCRED_HOME/.config/podium" \
  PODIUM_STATE_DIR="$NOCRED_HOME/.local/state/podium" \
  PATH="$NOCRED_HOME/.local/bin:$NOCRED_HOME/.opencode/bin:$PATH" \
  "$NOCRED_BIN" init --non-interactive --answers /tmp/ans-nocred.json
NOCRED_TOML="$NOCRED_HOME/.config/podium/podium.toml"
check "nocreds init wrote podium.toml" "test -s $NOCRED_TOML"
warn_count=$(grep -c '^# WARNING' "$NOCRED_TOML" 2>/dev/null || echo 0)
echo "WARNING count: $warn_count"
check "two '# WARNING' blocks present" "[ \"$warn_count\" = 2 ]"
check "WARNING lists 'minimax'" "grep -q 'minimax' $NOCRED_TOML"
check "WARNING lists 'openai'" "grep -q 'openai' $NOCRED_TOML"

# ---------------------------------------------------------------------------
# Interactive wizard: drive `podium init` through a pty via `script -qfec`
# ---------------------------------------------------------------------------
section "wizard via pty: pressing Enter everywhere yields all defaults"
WIZ_HOME=/tmp/wizard-home
rm -rf "$WIZ_HOME"
HOME="$WIZ_HOME" \
  PODIUM_REPO_URL=/tmp/podium-src \
  PODIUM_REF="$(git -C /tmp/podium-src rev-parse --abbrev-ref HEAD)" \
  sh /tmp/podium-src/install.sh >/tmp/wiz-install.log 2>&1
WIZ_BIN="$WIZ_HOME/.local/bin/podium"
check "wizard HOME has podium linked" "test -x $WIZ_BIN"
mkdir -p "$WIZ_HOME/.config/podium"
# Nine Enters (one per prompt); input goes via stdin to the pty child.
# The env must be set on `script` itself (the piped printf does not get it).
printf '\n\n\n\n\n\n\n\n\n' | \
  HOME="$WIZ_HOME" \
  PATH="$WIZ_HOME/.local/bin:$WIZ_HOME/.opencode/bin:$PATH" \
  script -qfec "$WIZ_BIN init" /dev/null > /tmp/wizard-defaults.log 2>&1
echo "--- wizard transcript (defaults run) ---"
cat /tmp/wizard-defaults.log
echo "--- end transcript ---"
WIZ_TOML="$WIZ_HOME/.config/podium/podium.toml"
check "wizard wrote podium.toml" "test -s $WIZ_TOML"
# Defaults: language all 'en', all six modules true, memory URL empty,
# roster_preset=opencode-multi (the principal roster row + the opencode rows).
check "wizard default language.response = en" "grep -q 'response = \"en\"' $WIZ_TOML"
check "wizard default language.domain = en"  "grep -q 'domain = \"en\"' $WIZ_TOML"
check "wizard default language.ui = en"      "grep -q 'ui = \"en\"' $WIZ_TOML"
check "wizard default memory module is on" "grep -q '^memory = true' $WIZ_TOML"
check "wizard default upgrade module is on" "grep -q '^upgrade = true' $WIZ_TOML"
check "wizard default worktrees module is off (opt-in)" "grep -q '^worktrees = false' $WIZ_TOML"
check "wizard default wrote no [worktrees] table" "! grep -q '^\\[worktrees\\]' $WIZ_TOML"
check "wizard default preset body contains the minimax-fast entry" \
  "grep -q '\"minimax-fast\"' $WIZ_TOML"
check "wizard default wrote no [memory] URL block" \
  "! grep -q '\\[memory\\]' $WIZ_TOML"

section "wizard via pty: explicit answers are honoured"
WIZ2_HOME=/tmp/wizard-home2
rm -rf "$WIZ2_HOME"
HOME="$WIZ2_HOME" \
  PODIUM_REPO_URL=/tmp/podium-src \
  PODIUM_REF="$(git -C /tmp/podium-src rev-parse --abbrev-ref HEAD)" \
  sh /tmp/podium-src/install.sh >/tmp/wiz2-install.log 2>&1
WIZ2_BIN="$WIZ2_HOME/.local/bin/podium"
check "wizard2 HOME has podium linked" "test -x $WIZ2_BIN"
mkdir -p "$WIZ2_HOME/.config/podium"
# Nine explicit answers: language es/es/es, modules rules+executors only,
# memory URL https://example.test, preset claude-only, worktrees=y, adopt=n, overwrite=n.
printf 'es\nes\nes\nrules,executors\nhttps://example.test\nclaude-only\ny\nn\nn\n' | \
  HOME="$WIZ2_HOME" \
  PATH="$WIZ2_HOME/.local/bin:$WIZ2_HOME/.opencode/bin:$PATH" \
  script -qfec "$WIZ2_BIN init" /dev/null > /tmp/wizard-explicit.log 2>&1
echo "--- wizard transcript (explicit) ---"
cat /tmp/wizard-explicit.log
echo "--- end transcript ---"
WIZ2_TOML="$WIZ2_HOME/.config/podium/podium.toml"
check "explicit wizard wrote podium.toml" "test -s $WIZ2_TOML"
check "explicit wizard language.response = es" "grep -q 'response = \"es\"' $WIZ2_TOML"
check "explicit wizard language.domain = es"  "grep -q 'domain = \"es\"' $WIZ2_TOML"
check "explicit wizard language.ui = es"      "grep -q 'ui = \"es\"' $WIZ2_TOML"
check "explicit wizard rules = true" "grep -q '^rules = true' $WIZ2_TOML"
check "explicit wizard executors = true" "grep -q '^executors = true' $WIZ2_TOML"
check "explicit wizard turned off codegraph" "grep -q '^codegraph = false' $WIZ2_TOML"
check "explicit wizard asked about worktrees" "grep -q 'develop in git worktrees' /tmp/wizard-explicit.log"
check "explicit wizard enabled worktrees" "grep -q '^worktrees = true' $WIZ2_TOML"
check "explicit wizard wrote the [worktrees] link" "grep -q 'link = \\[\"node_modules\"\\]' $WIZ2_TOML"
check "explicit wizard wrote the memory URL" \
  "grep -q 'url = \"https://example.test\"' $WIZ2_TOML"
check "explicit wizard wrote the claude-only preset body" \
  "grep -q '\"sonnet-coupled\"' $WIZ2_TOML"

finish