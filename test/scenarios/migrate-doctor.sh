#!/usr/bin/env bash
# needs: none
. /src/test/scenarios/lib.sh

section "bootstrap and fixture"
bootstrap
mkdir -p "$HOME/.claude/hooks" "$HOME/.claude/state" "$STATE_DIR" \
  "$HOME/.config/opencode" "$HOME/bin"
cat > "$HOME/.claude/settings.json" <<'JSON'
{
  "theme": "dark",
  "enabledPlugins": {"podium-codegraph@podium": true},
  "hooks": {
    "PreToolUse": [
      {"matcher":"Bash", "hooks":[
        {"command":"python3 ~/.claude/hooks/codegraph-gate.py"},
        {"command":"python3", "args":["~/.claude/hooks/codegraph-nudge.py"]},
        {"command":"python3", "args":["${CLAUDE_PLUGIN_ROOT}/hooks/plugin.py"]},
        {"command":"echo", "args":["keep me"]}
      ]}
    ],
    "Stop": [{"hooks":[{"command":"python3 ~/.claude/hooks/graphiti-stop.py"}]}]
  }
}
JSON
cat > "$HOME/.claude/state/codegraph-decisions.json" <<'JSON'
{"decisions":{"/project":{"answer":"legacy","legacy":true},"/legacy":{"answer":"keep"}}}
JSON
printf '%s\n' '{"decisions":{"/project":"podium"}}' > "$STATE_DIR/codegraph-decisions.json"
for name in codegraph-gate.py codegraph-nudge.py graphiti-stop.py; do : > "$HOME/.claude/hooks/$name"; done

section "migrate dry-run and migration"
podium migrate --dry-run > /tmp/migrate-dry.log 2>&1
check "dry hook lines" "grep -q 'remove hook: PreToolUse Bash -> codegraph-gate.py' /tmp/migrate-dry.log && grep -q 'remove hook: PreToolUse Bash -> codegraph-nudge.py' /tmp/migrate-dry.log && grep -q 'remove hook: Stop (any) -> graphiti-stop.py' /tmp/migrate-dry.log"
check "dry copy and untouched" "grep -q 'copy decisions:' /tmp/migrate-dry.log && grep -q 'dry-run: nothing written' /tmp/migrate-dry.log"
check "dry settings unchanged" "grep -q 'codegraph-gate.py' $HOME/.claude/settings.json && test ! -f $STATE_DIR/codegraph-decisions.json.bak-podium-*"
podium migrate > /tmp/migrate.log 2>&1
check "real report and backup" "grep -q 'left in place (not deleted):' /tmp/migrate.log && grep -q 'codegraph-gate.py' /tmp/migrate.log && ls $HOME/.claude/settings.json.bak-podium-* >/dev/null"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); h=d["hooks"]["PreToolUse"][0]["hooks"]; assert h == [{"command":"python3","args":["${CLAUDE_PLUGIN_ROOT}/hooks/plugin.py"]},{"command":"echo","args":["keep me"]}]; assert d["theme"] == "dark"' "$HOME/.claude/settings.json" >/dev/null 2>&1
check "plugin and user hooks survive" "test $? -eq 0"
check "decisions merged podium wins" "python3 -c 'import json,sys; d=json.load(open(sys.argv[1]))[\"decisions\"]; assert d == {\"/project\":\"podium\",\"/legacy\":{\"answer\":\"keep\"}}' $STATE_DIR/codegraph-decisions.json"
check "empty event removed" "python3 -c 'import json,sys; h=json.load(open(sys.argv[1]))[\"hooks\"]; assert \"Stop\" not in h' $HOME/.claude/settings.json"
printf '{broken' > "$HOME/.claude/settings.json"
podium migrate > /tmp/migrate-invalid.log 2>&1; migrate_code=$?
check "invalid settings exits one" "test $migrate_code -eq 1 && grep -q 'is not valid JSON' /tmp/migrate-invalid.log"
cat > "$HOME/.claude/settings.json" <<'JSON'
{"enabledPlugins":{"podium-codegraph@podium":true}}
JSON

section "doctor checks"
podium_init "$(default_answers claude-only)" >/dev/null
sed -e 's/^memory = false$/memory = true/' "$PODIUM_TOML" > /tmp/podium.toml
mv /tmp/podium.toml "$PODIUM_TOML"
mkdir -p "$HOME/.config/podium"
printf '{' > "$RUNTIME_JSON"
cat > "$HOME/bin/claude" <<'SH'
#!/bin/sh
echo '1.9.0'
SH
cat > "$HOME/bin/opencode" <<'SH'
#!/bin/sh
echo 'unparseable version'
SH
chmod +x "$HOME/bin/claude" "$HOME/bin/opencode"
export PATH="$HOME/bin:$PATH"
touch "$HOME/.config/opencode/opencode.json" "$HOME/.config/opencode/opencode.jsonc"
podium doctor > /tmp/doctor.log 2>&1; doctor_code=$?
grep -E '^\[(OK|WARN|FAIL)\] (claude cli|opencode cli|runtime.json|hooks|memory|hooks.log):' /tmp/doctor.log
check "cli versions and runtime failure" "grep -q '^\\[FAIL\\] claude cli:' /tmp/doctor.log && grep -q '^\\[WARN\\] opencode cli:' /tmp/doctor.log && grep -q '^\\[FAIL\\] runtime.json:' /tmp/doctor.log"
check "duplicate config warning" "grep -q '^\\[WARN\\] opencode config:' /tmp/doctor.log"
check "missing tools checks" "PATH=$HOME/bin:/usr/bin:/bin command -v claude >/dev/null && grep -q 'codegraph cli' /tmp/doctor.log"
toml_append '[memory]
url = "http://127.0.0.1:9/"'
cat > "$HOME/.claude/settings.json" <<'JSON'
{"enabledPlugins":{"podium-codegraph@podium":true},"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"command":"python3 ~/.claude/hooks/codegraph-gate.py"}]}]}}
JSON
printf '{"ok":true}' > "$RUNTIME_JSON"
printf '%s codegraph-gate stdin json: invalid input\n' "$(date '+%Y-%m-%dT%H:%M:%S')" > "$STATE_DIR/hooks.log"
podium doctor > /tmp/doctor-hooks.log 2>&1; hooks_code=$?
grep -E '^\[(OK|WARN|FAIL)\] (claude cli|opencode cli|runtime.json|hooks|memory|hooks.log):' /tmp/doctor-hooks.log
check "naive timestamp warns without traceback" "grep -q '^\\[WARN\\] hooks.log: recent activity:' /tmp/doctor-hooks.log && ! grep -qi traceback /tmp/doctor-hooks.log"
check "unreachable memory warns" "grep -q '^\\[WARN\\] memory:' /tmp/doctor-hooks.log"
check "doctor reports legacy hook with plugin" "test $hooks_code -eq 3 && grep -q '^\\[FAIL\\] hooks:' /tmp/doctor-hooks.log"
rm -f "$HOME/.claude/settings.json" "$STATE_DIR/hooks.log"
cat > "$HOME/bin/claude" <<'SH'
#!/bin/sh
echo '2.0.0'
SH
cat > "$HOME/bin/opencode" <<'SH'
#!/bin/sh
echo '2.0.0'
SH
podium doctor > /tmp/doctor-clean.log 2>&1; clean_code=$?
grep -E '^\[(OK|WARN|FAIL)\] (claude cli|opencode cli|runtime.json|hooks|memory|hooks.log):' /tmp/doctor-clean.log
check "clean doctor exit zero" "test $clean_code -eq 0"

finish
