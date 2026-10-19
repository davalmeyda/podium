# Exercise the installed podium-upgrade skill scripts and phase-6 workflow.
# needs: opencode
. /src/test/scenarios/lib.sh

check "scenario shell syntax" "sh -n /src/test/scenarios/upgrade-scripts.sh"

section "bootstrap and install"
bootstrap
podium_init "$(default_answers opencode-multi)" >/dev/null
podium install >/tmp/upgrade-install.log 2>&1
check "install succeeded" "test $? -eq 0"

preflight=$(plugin_file podium-upgrade skills/agents-upgrade/scripts/preflight.sh)
scripts=$(dirname "$preflight")
plugin_dir=$(dirname "$(dirname "$(dirname "$scripts")")")
skill="$plugin_dir/skills/agents-upgrade/SKILL.md"
check "installed scripts found" "test -n '$preflight' && test -f '$scripts/roster.py'"
check "skill installed and explicit-only" "test -f '$skill' && grep -q '^disable-model-invocation: true$' '$skill'"

section "preflight and roster"
sh "$preflight" >/tmp/upgrade-preflight.log 2>&1
check "preflight installs section" "grep -q '^== Installed agents' /tmp/upgrade-preflight.log && grep -Eq '^-- Responsibility table' /tmp/upgrade-preflight.log"
check "preflight roster section" "grep -q '^== Configured roster' /tmp/upgrade-preflight.log"
check "preflight history section" "grep -q '^== Latest history report' /tmp/upgrade-preflight.log"
check "preflight sessions section" "grep -q '^== Active sessions (excluding the OpenCode service)' /tmp/upgrade-preflight.log && grep -Fxq '(end sessions)' /tmp/upgrade-preflight.log"
check "preflight versions section" "grep -q '^== Versions' /tmp/upgrade-preflight.log && grep -Eq '^opencode: [^[:space:]]' /tmp/upgrade-preflight.log && grep -Eq '^claude: [^[:space:]]' /tmp/upgrade-preflight.log"
check "preflight install method section" "grep -q '^== Install method' /tmp/upgrade-preflight.log && grep -Eq '^opencode: (brew|npm|native|missing)$' /tmp/upgrade-preflight.log && grep -Eq '^claude: (brew|npm|native|missing)$' /tmp/upgrade-preflight.log"
check "native install methods in container" "grep -Eq '^claude: native$' /tmp/upgrade-preflight.log && grep -Eq '^opencode: native$' /tmp/upgrade-preflight.log"
python3 "$scripts/roster.py" >/tmp/upgrade-roster.json
check "roster JSON matches config" "python3 -c 'import json,tomllib; a=json.load(open(\"/tmp/upgrade-roster.json\")); b=tomllib.load(open(\"$PODIUM_TOML\",\"rb\")); assert a == {k:b.get(k,d) for k,d in ((\"roster\",[]),(\"agents\",[]),(\"roster_notes\",{}))}'"

section "update-clis dry runs"
claude_before=$(claude --version 2>/dev/null)
opencode_before=$(opencode --version 2>/dev/null)
sh "$scripts/update-clis.sh" --dry-run >/tmp/upgrade-dry.log 2>&1
check "native update commands" "grep -Fq '[dry-run] opencode upgrade --major || opencode upgrade' /tmp/upgrade-dry.log && grep -Fxq '[dry-run] claude update' /tmp/upgrade-dry.log"
check "dry-run leaves versions unchanged" "[ \"$(claude --version 2>/dev/null)\" = \"$claude_before\" ] && [ \"$(opencode --version 2>/dev/null)\" = \"$opencode_before\" ] && grep -Fq \"opencode: $opencode_before -> $opencode_before\" /tmp/upgrade-dry.log && grep -Fq \"claude: $claude_before -> $claude_before\" /tmp/upgrade-dry.log"
sh "$scripts/update-clis.sh" --dry-run --skip-opencode >/tmp/upgrade-skip-oc.log 2>&1
sh "$scripts/update-clis.sh" --dry-run --skip-claude >/tmp/upgrade-skip-claude.log 2>&1
check "skip-opencode omits update" "! grep -q 'opencode upgrade' /tmp/upgrade-skip-oc.log && grep -Fxq '[dry-run] claude update' /tmp/upgrade-skip-oc.log"
check "skip-claude omits update" "grep -Fq '[dry-run] opencode upgrade --major || opencode upgrade' /tmp/upgrade-skip-claude.log && ! grep -Fxq '[dry-run] claude update' /tmp/upgrade-skip-claude.log"
sh "$scripts/update-clis.sh" --not-an-option >/tmp/upgrade-unknown.out 2>/tmp/upgrade-unknown.err
unknown_status=$?
check "unknown option exits 2" "[ '$unknown_status' -eq 2 ] && grep -Fxq 'Unknown option: --not-an-option' /tmp/upgrade-unknown.err"

section "real CLI update"
sh "$scripts/update-clis.sh" >/tmp/upgrade-real.log 2>&1
real_status=$?
claude_after=$(claude --version 2>/dev/null)
opencode_after=$(opencode --version 2>/dev/null)
check "real updates succeed and do not downgrade" "[ '$real_status' -eq 0 ] && python3 -c 'import re,sys; v=lambda s: tuple(map(int,re.findall(r\"\\d+\",s))); assert v(sys.argv[2]) >= v(sys.argv[1]); assert v(sys.argv[4]) >= v(sys.argv[3])' \"$claude_before\" \"$claude_after\" \"$opencode_before\" \"$opencode_after\""

section "live catalogs and agent variants"
sh "$scripts/catalogs.sh" >/tmp/upgrade-catalogs.log 2>&1
catalog_status=$?
sed -n '1,45p' /tmp/upgrade-catalogs.log
check "catalog command succeeds" "[ '$catalog_status' -eq 0 ]"
check "catalogs run dir printed" "head -n 1 /tmp/upgrade-catalogs.log | grep -Eq '^run dir: '"
check "ping prompt file written" "ping_file=\$(head -n 1 /tmp/upgrade-catalogs.log | sed 's/^run dir: //'); [ -f \"\$ping_file/ping.txt\" ] && grep -Fxq 'Reply with the single word OK. Do NOT use any tools.' \"\$ping_file/ping.txt\""
check "provider catalogs listed" "grep -q '^== OpenCode models: minimax$' /tmp/upgrade-catalogs.log && grep -q '^== OpenCode models: openai$' /tmp/upgrade-catalogs.log"
check "provider catalogs list real model ids" "grep -q '^minimax/' /tmp/upgrade-catalogs.log && grep -q '^openai/' /tmp/upgrade-catalogs.log && ! grep -q '^FAIL models' /tmp/upgrade-catalogs.log"
check "every agent check carries the variant from the roster" "grep -Eq '^== Agent check: minimax [(]minimax/MiniMax-M3#none[)]$' /tmp/upgrade-catalogs.log && grep -Eq '^== Agent check: sol [(]openai/gpt-6.1-sol#high[)]$' /tmp/upgrade-catalogs.log && grep -Eq '^== Agent check: luna [(]openai/gpt-6-luna#high[)]$' /tmp/upgrade-catalogs.log"
check "minimax agent checked with none" "grep -Fq '== Agent check: minimax (minimax/MiniMax-M3#none)' /tmp/upgrade-catalogs.log"
check "sol agent checked with high" "grep -Fq '== Agent check: sol (openai/gpt-6.1-sol#high)' /tmp/upgrade-catalogs.log"
check "luna agent checked with high" "grep -Fq '== Agent check: luna (openai/gpt-6-luna#high)' /tmp/upgrade-catalogs.log"
check "all agent checks answer OK" "awk '/^answer: OK([[:space:]]*|$)/ { found++ } END { exit found == 3 ? 0 : 1 }' /tmp/upgrade-catalogs.log"
check "opencode.db section shows a real model per agent" "grep -Fq '== Actual model recorded (opencode.db)' /tmp/upgrade-catalogs.log && grep -E '^minimax -> MiniMax-M3#' /tmp/upgrade-catalogs.log >/dev/null && grep -E '^sol -> gpt-6.1-sol#' /tmp/upgrade-catalogs.log >/dev/null && grep -E '^luna -> gpt-6-luna#' /tmp/upgrade-catalogs.log >/dev/null"
check "every recorded agent is one we pinged" "awk -F' -> ' '/^[[:alpha:]-]+ -> / { print \$1 }' /tmp/upgrade-catalogs.log | sort -u > /tmp/upgrade-db-agents; for a in minimax sol luna; do grep -Fxq \"\$a\" /tmp/upgrade-db-agents || { echo missing \$a; exit 1; }; done"

section "phase 6 install preview and apply"
cp "$PODIUM_TOML" "$PODIUM_TOML.bak-podium-20261019-120000-abcd"
python3 - <<'PY'
from pathlib import Path

path = Path.home() / ".config/podium/podium.toml"
text = path.read_text()
start = text.index('name = "minimax"', text.index("[[agents]]"))
end = text.find("[[agents]]", start + 1)
if end < 0:
    end = len(text)
agent = text[start:end]
old = 'model = "minimax/MiniMax-M3"'
assert old in agent
path.write_text(text[:start] + agent.replace(old, 'model = "minimax/MiniMax-M3-phase6"', 1) + text[end:])
PY
check "phase-6 backup created" "test -f '$PODIUM_TOML.bak-podium-20261019-120000-abcd'"
podium install --dry-run >/tmp/upgrade-phase6-dry.log 2>&1
grep -E '^\[(update|create|unchanged|conflict)\]|agents/' /tmp/upgrade-phase6-dry.log | head -20
check "dry-run updates minimax agent only" "grep -Fq '[update]    /home/tester/.config/opencode/agents/minimax.md' /tmp/upgrade-phase6-dry.log && [ \"$(grep -Fc '[update]' /tmp/upgrade-phase6-dry.log)\" -eq 1 ]"
podium install >/tmp/upgrade-phase6-install.log 2>&1
apply_status=$?
check "phase-6 install succeeds" "[ '$apply_status' -eq 0 ] && grep -Fq 'minimax.md' /tmp/upgrade-phase6-install.log"
check "phase-6 model rendered" "grep -Fq 'model: minimax/MiniMax-M3-phase6' '$HOME/.config/opencode/agents/minimax.md'"
podium diff >/tmp/upgrade-phase6-diff.log 2>&1
check "phase-6 diff clean" "grep -q 'no differences' /tmp/upgrade-phase6-diff.log"

finish
