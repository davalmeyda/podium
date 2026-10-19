#!/usr/bin/env bash
# Parallel work outside the main checkout (see rules/worktrees.md).
#   worktree.sh create    <repo> <task> [untracked-file...]  spawns ../<repo>-wt/<task>
#   worktree.sh integrate <repo> <task>                     three-way merges into main
#   worktree.sh clean     <repo> <task>                     worktree, branch, base file, decisions
#
# The main checkout's branch and index are never touched and no commit is ever created.
# Anything that cannot be merged safely as text is reported as a conflict, never overwritten.
set -euo pipefail

usage() { echo "usage: worktree.sh create|integrate|clean <repo> <task> [files...]" >&2; exit 1; }

cmd=${1:-}; [ $# -ge 3 ] || usage
repo=$(cd "$2" && pwd); task=$3
case $task in
  *[!A-Za-z0-9._-]*|.*|"") echo "task must be a simple name (letters, digits, . _ -): $task" >&2; exit 1 ;;
esac
name=$(basename "$repo")
wt="$(dirname "$repo")/$name-wt/$task"
branch="wt/$task"
common=$(git -C "$repo" rev-parse --git-common-dir)
meta="$(cd "$repo" && cd "$common" && pwd)/wt-base-$task"

links=${PODIUM_WORKTREE_LINKS-node_modules}

state=${PODIUM_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/podium}
decisions="$state/codegraph-decisions.json"

# exists <path>: present as a file, directory or (possibly dangling) symlink
exists() { [ -e "$1" ] || [ -L "$1" ]; }

# same_file <a> <b>: identical symlink targets, or identical regular contents
same_file() {
  if [ -L "$1" ] || [ -L "$2" ]; then
    [ -L "$1" ] && [ -L "$2" ] && [ "$(readlink "$1")" = "$(readlink "$2")" ]
  else
    [ -f "$1" ] && [ -f "$2" ] && cmp -s "$1" "$2"
  fi
}

# matches_base <main path> <base copy> <base mode>: main still equals the base version
matches_base() {
  if [ "$3" = 120000 ]; then
    [ -L "$1" ] && [ "$(readlink "$1")" = "$(cat "$2")" ]
  else
    [ ! -L "$1" ] && [ -f "$1" ] && cmp -s "$1" "$2"
  fi
}

# put <from> <to>: copy a file or symlink as is (no dereference), mode included
put() { mkdir -p "$(dirname "$2")"; rm -f "$2"; cp -P -p "$1" "$2"; }

case $cmd in
  create)
    if exists "$wt"; then echo "already exists: $wt" >&2; exit 1; fi
    base=$(git -C "$repo" stash create)
    base=${base:-$(git -C "$repo" rev-parse HEAD)}
    git -C "$repo" worktree add -q -b "$branch" "$wt" "$base"
    printf "%s" "$base" > "$meta"
    shift 3
    for f in "$@"; do mkdir -p "$wt/$(dirname "$f")"; cp -R "$repo/$f" "$wt/$f"; done
    for l in $links; do
      [ -d "$repo/$l" ] || continue
      if exists "$wt/$l"; then echo "not linked (already present in the worktree): $l"; continue; fi
      mkdir -p "$(dirname "$wt/$l")"
      ln -s "$repo/$l" "$wt/$l"
    done
    echo "worktree: $wt"
    echo "base: $base"
    if [ -d "$repo/.codegraph" ]; then
      echo "next: codegraph init $wt (required before working there)"
    fi
    ;;
  integrate)
    if [ ! -e "$meta" ]; then echo "no worktree base for $task" >&2; exit 1; fi
    base=$(cat "$meta")
    # Exclude the linked folders, except those .gitignore already covers:
    # git rejects an explicit pathspec naming an ignored path.
    exclude_args=()
    for l in $links; do
      git -C "$wt" check-ignore -q "$l" || exclude_args+=(":!$l")
    done
    git -C "$wt" add -A -- . ${exclude_args[@]+"${exclude_args[@]}"}  # bash 3.2: empty array under set -u
    conflicts=0
    old=$(mktemp)
    trap 'rm -f "$old"' EXIT
    conflict() { echo "CONFLICT ($1): $2"; conflicts=1; }
    # NUL-delimited raw records: ":<old mode> <new mode> <old sha> <new sha> <status>" then the path
    while IFS= read -r -d '' rec && IFS= read -r -d '' path; do
      set -- $rec
      omode=${1#:}; nmode=$2; status=$5
      m="$repo/$path"; w="$wt/$path"
      if [ "$omode" = 160000 ] || [ "$nmode" = 160000 ]; then
        conflict "submodule, integrate it by hand" "$path"; continue
      fi
      [ "$omode" = 000000 ] || git -C "$wt" cat-file --filters "$base:$path" > "$old"
      case $status in
        D)
          if ! exists "$m"; then echo "deleted: $path (already absent in main)"
          elif matches_base "$m" "$old" "$omode"; then rm -f "$m"; echo "deleted: $path"
          else conflict "deleted in worktree, changed in main" "$path"; fi
          ;;
        A)
          if ! exists "$m"; then put "$w" "$m"; echo "new: $path"
          elif same_file "$w" "$m"; then echo "new: $path (already identical in main)"
          else put "$w" "$m.worktree"; conflict "created on both sides" "$path"; fi
          ;;
        *)
          if ! exists "$m"; then
            put "$w" "$m.worktree"; conflict "changed in worktree, deleted in main" "$path"
          elif same_file "$w" "$m"; then
            echo "merged: $path (already identical in main)"
          elif matches_base "$m" "$old" "$omode"; then
            put "$w" "$m"; echo "merged: $path"
          elif [ -L "$m" ] || [ -L "$w" ] || [ "$omode" = 120000 ]; then
            put "$w" "$m.worktree"; conflict "symlink changed on both sides" "$path"
          else
            rc=0; git merge-file -q -L main -L base -L worktree "$m" "$old" "$w" || rc=$?
            if [ "$rc" -eq 0 ]; then echo "merged: $path"
            elif [ "$rc" -lt 128 ]; then echo "CONFLICT: $path"; conflicts=1
            else put "$w" "$m.worktree"; conflict "not mergeable as text" "$path"; fi
          fi
          # carry an executable-bit change made in the worktree
          if [ -f "$m" ] && [ ! -L "$m" ] && [ "$omode" != "$nmode" ]; then
            if [ "$nmode" = 100755 ]; then chmod +x "$m"; elif [ "$nmode" = 100644 ]; then chmod -x "$m"; fi
          fi
          ;;
      esac
    done < <(git -C "$wt" diff --cached --no-renames --raw -z "$base")
    git -C "$wt" reset -q
    if [ "$conflicts" -eq 0 ]; then
      echo "clean integration"
    else
      echo "conflicts: resolve them in the main checkout (markers <<<<<<< main / >>>>>>> worktree, *.worktree copies)"
      exit 2
    fi
    ;;
  clean)
    for l in $links; do
      if [ -L "$wt/$l" ]; then rm "$wt/$l"; fi
    done
    if [ -d "$wt" ]; then
      # twice --force also removes a locked worktree; on failure keep the base and branch
      git -C "$repo" worktree remove --force --force "$wt" || { echo "could not remove $wt; nothing else was cleaned" >&2; exit 1; }
    fi
    git -C "$repo" worktree prune
    if git -C "$repo" show-ref --verify --quiet "refs/heads/$branch"; then
      git -C "$repo" branch -D -q "$branch"
    fi
    rm -f "$meta"
    parent="$(dirname "$wt")"
    if [ -d "$parent" ] && [ -z "$(ls -A "$parent" 2>/dev/null || true)" ]; then
      rmdir "$parent" 2>/dev/null || true
    fi
    python3 - "$wt" "$decisions" <<'EOF' || true
import json, os, sys
target, path = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)
decisions = data.get("decisions") if isinstance(data, dict) else None
if not isinstance(decisions, dict) or target not in decisions:
    sys.exit(0)
decisions.pop(target, None)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=1)
os.replace(tmp, path)
EOF
    folder=no; exists "$wt" && folder=yes
    wt_count=$(git -C "$repo" worktree list --porcelain | grep -c -x -F "worktree $wt" || true)
    branch_count=$(git -C "$repo" for-each-ref --format='%(refname:short)' refs/heads/ | grep -c -x -F "$branch" || true)
    echo "leftovers: worktrees=$wt_count branches=$branch_count folder=$folder"
    ;;
  *) usage ;;
esac
