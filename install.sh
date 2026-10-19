#!/bin/sh
# podium bootstrap installer (ARCHITECTURE.md §3, §11).
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/davalmeyda/podium/main/install.sh | sh
#
# Environment variables:
#   PODIUM_HOME         target checkout directory (default $HOME/.local/share/podium/repo)
#   PODIUM_REF          git ref to check out (default: latest release tag, else main)
#   PODIUM_REPO_URL     git URL to clone (default https://github.com/davalmeyda/podium)
#
# No sudo, no package installs, no Homebrew-only logic.

set -eu

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

PODIUM_REPO_URL="${PODIUM_REPO_URL:-https://github.com/davalmeyda/podium}"
PODIUM_REF="${PODIUM_REF:-}"
PODIUM_HOME="${PODIUM_HOME:-$HOME/.local/share/podium/repo}"
BIN_DIR="$HOME/.local/bin"
LINK_PATH="$BIN_DIR/podium"

# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

log() {
    printf 'podium install: %s\n' "$*"
}

warn() {
    printf 'podium install: WARN %s\n' "$*" >&2
}

die() {
    printf 'podium install: ERROR %s\n' "$*" >&2
    exit 1
}

# Portable in-place sed; macOS /bin/sed needs the empty backup argument.
sed_inplace() {
    expr=$1
    file=$2
    if sed --version >/dev/null 2>&1; then
        sed -i "$expr" "$file"
    else
        sed -i '' "$expr" "$file"
    fi
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"

# Confirm python >= 3.8 via the interpreter; honours a major+minor parse.
python_major_minor=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
py_ok=0
IFS=. read -r py_major py_minor <<EOF
$python_major_minor
EOF
case "$py_major$py_minor" in
    ''|*[!0-9]*) py_ok=0 ;;
    *) if [ "$py_major" -gt 3 ] 2>/dev/null; then py_ok=1;
       elif [ "$py_major" -eq 3 ] && [ "$py_minor" -ge 8 ]; then py_ok=1;
       fi ;;
esac
[ "$py_ok" -eq 1 ] || die "python3 >= 3.8 required (found $python_major_minor)"

command -v git >/dev/null 2>&1 || die "git not found on PATH"

mkdir -p "$BIN_DIR"
mkdir -p "$(dirname "$PODIUM_HOME")"

# ---------------------------------------------------------------------------
# Clone or update the checkout
# ---------------------------------------------------------------------------

if [ -z "$PODIUM_REF" ]; then
    # Latest release tag (highest vMAJOR.MINOR.PATCH); main when nothing is released yet.
    latest=$(git ls-remote --tags --refs "$PODIUM_REPO_URL" 'v*' 2>/dev/null \
        | sed 's#.*refs/tags/v##' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' \
        | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1)
    if [ -n "$latest" ]; then PODIUM_REF="v$latest"; else PODIUM_REF=main; fi
fi

if [ -d "$PODIUM_HOME/.git" ]; then
    log "updating existing checkout at $PODIUM_HOME to $PODIUM_REF"
    if git -C "$PODIUM_HOME" fetch --depth 1 --tags origin "$PODIUM_REF" \
        && git -C "$PODIUM_HOME" checkout --quiet --detach FETCH_HEAD; then
        :
    else
        warn "update failed; re-cloning"
        rm -rf "$PODIUM_HOME"
        git clone --depth 1 --branch "$PODIUM_REF" "$PODIUM_REPO_URL" "$PODIUM_HOME"
    fi
else
    if [ -e "$PODIUM_HOME" ]; then
        warn "$PODIUM_HOME exists but is not a git checkout; moving it aside"
        mv "$PODIUM_HOME" "${PODIUM_HOME}.bak-$(date +%Y%m%d-%H%M%S)"
    fi
    log "cloning $PODIUM_REPO_URL ($PODIUM_REF) into $PODIUM_HOME"
    git clone --depth 1 --branch "$PODIUM_REF" "$PODIUM_REPO_URL" "$PODIUM_HOME"
fi

# ---------------------------------------------------------------------------
# Symlink the CLI shim
# ---------------------------------------------------------------------------

target="$PODIUM_HOME/bin/podium"
if [ ! -f "$target" ]; then
    die "expected $target after checkout; check the branch/tag ($PODIUM_REF)"
fi

# Replace an existing symlink or file. We deliberately skip dotfiles so we
# don't trample a real "$BIN_DIR/podium" directory if one exists.
if [ -L "$LINK_PATH" ] || [ -e "$LINK_PATH" ]; then
    rm -f "$LINK_PATH"
fi
ln -s "$target" "$LINK_PATH"
log "linked $LINK_PATH -> $target"

# ---------------------------------------------------------------------------
# PATH hint
# ---------------------------------------------------------------------------

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        warn "$BIN_DIR is not on PATH; add this to your shell rc:"
        warn "    export PATH=\"$BIN_DIR:\$PATH\""
        ;;
esac

# ---------------------------------------------------------------------------
# Next steps
# ---------------------------------------------------------------------------

cat <<EOF
podium install: done.

Next steps:
  1. Run 'podium init'   (interactive wizard, or pass --answers FILE)
  2. Run 'podium install' (apply the rendered config to your agent CLIs)
  3. Run 'podium doctor'  (sanity-check the result)
Or tell your agent to follow the steps in INSTALL.md.
EOF
