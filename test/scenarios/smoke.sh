# Harness smoke test: the working tree bootstraps, inits and installs offline.
# needs: none
. /src/test/scenarios/lib.sh

section "bootstrap"
bootstrap
check "podium on PATH" "command -v podium"
check "version matches the tree" "podium --version | grep -qF \"$(sed -n 's/^__version__ = \"\(.*\)\"/\1/p' /src/podium/__init__.py)\""

section "init + install (no plugins)"
podium_init "$(default_answers claude-only)" >/dev/null
check "podium.toml written" "test -s $PODIUM_TOML"
podium install --modules rules,executors >/tmp/install.log 2>&1
check "install exit 0" "grep -q 'claude-md block' /tmp/install.log"
check "CLAUDE.md block" "grep -q 'podium:begin claude-md' $HOME/.claude/CLAUDE.md"

finish
