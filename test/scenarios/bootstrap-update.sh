#!/bin/sh
# needs: none
set -u
. /src/test/scenarios/lib.sh

section "Bootstrap defaults and environment"
bootstrap
check "default checkout" '[ -d "$HOME/.local/share/podium/repo/.git" ]'
check "default CLI link" '[ -L "$HOME/.local/bin/podium" ] && [ "$(readlink "$HOME/.local/bin/podium")" = "$HOME/.local/share/podium/repo/bin/podium" ]'
check "bootstrap completion" 'grep -Fq "podium install: done." /tmp/bootstrap.log'

custom_home="$HOME/custom/podium"
bootstrap_ref=$(git -C /tmp/podium-src rev-parse --abbrev-ref HEAD)
PODIUM_HOME="$custom_home" PODIUM_REF="$bootstrap_ref" PODIUM_REPO_URL=/tmp/podium-src \
    sh /tmp/podium-src/install.sh >/tmp/custom-install.log 2>&1
check "PODIUM_HOME honoured" '[ -d "$custom_home/.git" ]'
check "PODIUM_REF honoured" 'grep -Fq "cloning /tmp/podium-src ($bootstrap_ref) into $custom_home" /tmp/custom-install.log'

section "Existing and non-git checkouts"
PODIUM_HOME="$custom_home" PODIUM_REF="$bootstrap_ref" PODIUM_REPO_URL=/tmp/podium-src \
    sh /tmp/podium-src/install.sh >/tmp/reinstall.log 2>&1
check "existing checkout updated" 'grep -Fq "updating existing checkout at $custom_home to $bootstrap_ref" /tmp/reinstall.log'

non_git="$HOME/non-git-podium"
mkdir -p "$non_git"
printf 'foreign\n' > "$non_git/data"
PODIUM_HOME="$non_git" PODIUM_REF=main PODIUM_REPO_URL=/tmp/podium-src \
    sh /tmp/podium-src/install.sh >/tmp/non-git.log 2>&1
check "non-git dir moved aside" 'grep -Fq "WARN $non_git exists but is not a git checkout; moving it aside" /tmp/non-git.log && find "$HOME" -maxdepth 1 -type d -name "non-git-podium.bak-*" | grep -Eq "non-git-podium\.bak-[0-9]{8}-[0-9]{6}$"'
check "non-git contents preserved" 'grep -qx foreign "$HOME"/non-git-podium.bak-*/data'

section "Fresh local origin and release selection"
origin="$HOME/origin"
mkdir -p "$origin"
(cd /tmp/podium-src && tar --exclude=.git -cf - .) | (cd "$origin" && tar -xf -)
git -C "$origin" init -q -b main
git -C "$origin" -c user.name=test -c user.email=test@example.invalid add -A
git -C "$origin" -c user.name=test -c user.email=test@example.invalid commit -qm base
git -C "$origin" tag v0.1.0
printf '\nBOOTSTRAP UPDATE V0.2 MARKER\n' >> "$origin/rules/project-rules.md"
git -C "$origin" -c user.name=test -c user.email=test@example.invalid add rules/project-rules.md
git -C "$origin" -c user.name=test -c user.email=test@example.invalid commit -qm release-v02
git -C "$origin" tag v0.2.0
printf '\nBOOTSTRAP UPDATE V0.10 MARKER\n' >> "$origin/rules/project-rules.md"
git -C "$origin" -c user.name=test -c user.email=test@example.invalid add rules/project-rules.md
git -C "$origin" -c user.name=test -c user.email=test@example.invalid commit -qm release-v010
git -C "$origin" tag v0.10.0
printf '\nNEWER MAIN COMMIT\n' >> "$origin/rules/project-rules.md"
git -C "$origin" -c user.name=test -c user.email=test@example.invalid add rules/project-rules.md
git -C "$origin" -c user.name=test -c user.email=test@example.invalid commit -qm newer-main

release_home="$HOME/releases/podium"
PODIUM_HOME="$release_home" PODIUM_REPO_URL="$origin" sh /tmp/podium-src/install.sh >/tmp/latest-install.log 2>&1
check "install selects v0.10.0" 'git -C "$release_home" describe --tags --exact-match 2>/dev/null | grep -Fxq v0.10.0'

before=$(git -C "$release_home" rev-parse HEAD)
PODIUM_HOME="$release_home" PODIUM_REPO_URL="$origin" \
    "$release_home/bin/podium" update --dry-run >/tmp/update-dry.log 2>&1
check "update dry-run names latest tag" 'grep -Fq "would move to v0.10.0" /tmp/update-dry.log'
check "update dry-run unchanged" '[ "$(git -C "$release_home" rev-parse HEAD)" = "$before" ]'

printf '{"language":{"response":"en","domain":"en","ui":"en"},"modules":["rules"],"roster_preset":"claude-only","memory":{"url":""}}\n' > /tmp/release-answers.json
PODIUM_HOME="$release_home" PODIUM_REPO_URL="$origin" PODIUM_REF=v0.10.0 \
    "$release_home/bin/podium" init --non-interactive --answers /tmp/release-answers.json >/tmp/release-init.log 2>&1
PODIUM_HOME="$release_home" PODIUM_REPO_URL="$origin" PODIUM_REF=v0.10.0 \
    "$release_home/bin/podium" install >/tmp/release-install.log 2>&1
PODIUM_HOME="$release_home" PODIUM_REPO_URL="$origin" PODIUM_REF=v0.2.0 \
    "$release_home/bin/podium" update >/tmp/update-v02.log 2>&1
check "PODIUM_REF update selects tag" 'git -C "$release_home" describe --tags --exact-match 2>/dev/null | grep -Fxq v0.2.0'
check "updated checkout install uses new rules" 'grep -Fq "BOOTSTRAP UPDATE V0.2 MARKER" "$HOME/.claude/CLAUDE.md" && ! grep -Fq "BOOTSTRAP UPDATE V0.10 MARKER" "$HOME/.claude/CLAUDE.md"'

section "Update failure and PATH diagnostics"
bad_origin="$HOME/unreachable-origin"
mkdir -p "$bad_origin"
git -C "$release_home" remote set-url origin "$bad_origin"
before=$(git -C "$release_home" rev-parse HEAD)
set +e
PODIUM_HOME="$release_home" "$release_home/bin/podium" update >/tmp/update-failed.log 2>&1
update_status=$?
set -e
check "unreachable origin exits 3" '[ "$update_status" -eq 3 ] && grep -Fq "environment error:" /tmp/update-failed.log'
check "failed update unchanged" '[ "$(git -C "$release_home" rev-parse HEAD)" = "$before" ]'

path_home="$HOME/path-hint/podium"
PATH=/usr/bin:/bin PODIUM_HOME="$path_home" PODIUM_REF=main PODIUM_REPO_URL=/tmp/podium-src \
    sh /tmp/podium-src/install.sh >/tmp/path-hint.log 2>&1
check "PATH hint printed" 'grep -Fq "$HOME/.local/bin is not on PATH; add this to your shell rc:" /tmp/path-hint.log && grep -Fq "export PATH=\"$HOME/.local/bin:\$PATH\"" /tmp/path-hint.log'

section "Missing tool diagnostics"
make_tool_path() {
    tool_path=$1
    missing=$2
    mkdir -p "$tool_path"
    for tool in sh python3 git mkdir dirname sed grep sort tail date rm mv ln cat; do
        [ "$tool" = "$missing" ] && continue
        tool_location=$(command -v "$tool" 2>/dev/null || true)
        [ -n "$tool_location" ] && ln -sf "$tool_location" "$tool_path/$tool"
    done
}
python_path="$HOME/no-python-bin"
make_tool_path "$python_path" python3
set +e
PATH="$python_path" /bin/sh /tmp/podium-src/install.sh >/tmp/no-python.log 2>&1
python_status=$?
set -e
check "python3 missing error" '[ "$python_status" -eq 1 ] && grep -Fq "podium install: ERROR python3 not found on PATH" /tmp/no-python.log'

git_path="$HOME/no-git-bin"
make_tool_path "$git_path" git
set +e
PATH="$git_path" /bin/sh /tmp/podium-src/install.sh >/tmp/no-git.log 2>&1
git_status=$?
set -e
check "git missing error" '[ "$git_status" -eq 1 ] && grep -Fq "podium install: ERROR git not found on PATH" /tmp/no-git.log'

finish
