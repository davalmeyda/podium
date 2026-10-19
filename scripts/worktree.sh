#!/usr/bin/env bash
# Parallel work outside the main checkout (see rules/worktrees.md).
#   worktree.sh create    <repo> <task> [untracked-file...]  spawns ../<repo>-wt/<task>
#   worktree.sh integrate <repo> <task>                     three-way merges into main
#   worktree.sh clean     <repo> <task>                     worktree, branch, base file, decisions
#
# The main checkout's branch and index are never touched and no commit is ever created.
set -euo pipefail

cmd=${1:?usage: worktree.sh create\|integrate\|clean <repo> <task> [files...]}; repo=$(cd "${2:?repo}" && pwd); task=${3:?task}
name=$(basename "$repo")
wt="$(dirname "$repo")/$name-wt/$task"
branch="wt/$task"
common=$(git -C "$repo" rev-parse --git-common-dir)
meta="$(cd "$repo" && cd "$common" && pwd)/wt-base-$task"

links=${PODIUM_WORKTREE_LINKS-node_modules}

state=${PODIUM_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/podium}
decisions="$state/codegraph-decisions.json"

usage() { echo "usage: worktree.sh create|integrate|clean <repo> <task> [files...]" >&2; exit 1; }

case $cmd in
  create)
    if [ -e "$wt" ]; then echo "already exists: $wt" >&2; exit 1; fi
    base=$(git -C "$repo" stash create)
    base=${base:-$(git -C "$repo" rev-parse HEAD)}
    git -C "$repo" worktree add -q -b "$branch" "$wt" "$base"
    printf "%s" "$base" > "$meta"
    shift 3
    for f in "$@"; do mkdir -p "$wt/$(dirname "$f")"; cp -R "$repo/$f" "$wt/$f"; done
    for l in $links; do
      if [ -d "$repo/$l" ]; then ln -s "$repo/$l" "$wt/$l"; fi
    done
    echo "worktree: $wt"
    echo "base: $base"
    echo "next: codegraph init $wt (required before working there)"
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
    while IFS=$'\t' read -r status path; do
      case $status in
        D)
          rm -f "$repo/$path"
          echo "deleted: $path"
          ;;
        A)
          if [ -e "$repo/$path" ] && ! cmp -s "$wt/$path" "$repo/$path"; then
            cp "$wt/$path" "$repo/$path.worktree"
            echo "CONFLICT (created on both sides): $path"
            conflicts=1
          else
            mkdir -p "$(dirname "$repo/$path")"
            cp "$wt/$path" "$repo/$path"
            echo "new: $path"
          fi
          ;;
        *)
          old=$(mktemp)
          git -C "$wt" show "$base:$path" > "$old"
          if [ ! -e "$repo/$path" ]; then cp "$old" "$repo/$path"; fi
          if git merge-file -L main -L base -L worktree "$repo/$path" "$old" "$wt/$path"; then
            echo "merged: $path"
          else
            echo "CONFLICT: $path"
            conflicts=1
          fi
          rm -f "$old"
          ;;
      esac
    done < <(git -C "$wt" diff --cached --no-renames --name-status "$base")
    git -C "$wt" reset -q
    if [ "$conflicts" -eq 0 ]; then
      echo "clean integration"
    else
      echo "conflicts: resolve them in the main checkout (markers <<<<<<< main / >>>>>>> worktree)"
      exit 2
    fi
    ;;
  clean)
    wt_count=0
    branch_count=0
    folder=no
    for l in $links; do
      if [ -L "$wt/$l" ]; then rm "$wt/$l"; fi
    done
    if [ -d "$wt" ]; then
      git -C "$repo" worktree remove --force "$wt" || true
    fi
    if git -C "$repo" show-ref --verify --quiet "refs/heads/$branch"; then
      git -C "$repo" branch -D -q "$branch" || true
    fi
    git -C "$repo" worktree prune
    rm -f "$meta"
    parent="$(dirname "$wt")"
    if [ -d "$parent" ] && [ -z "$(ls -A "$parent" 2>/dev/null || true)" ] && [ "$parent" != "$repo" ]; then
      rmdir "$parent" 2>/dev/null || true
    fi
    if [ ! -e "$wt" ]; then folder=no; else folder=yes; fi
    wt_count=$(git -C "$repo" worktree list --porcelain | grep -c "^worktree $wt$" || true)
    branch_count=$(git -C "$repo" for-each-ref --format='%(refname:short)' refs/heads/ | grep -c "^$branch$" || true)
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
data["decisions"] = decisions
parent = os.path.dirname(path) or "."
os.makedirs(parent, exist_ok=True)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=1)
os.replace(tmp, path)
EOF
    echo "leftovers: worktrees=$wt_count branches=$branch_count folder=$folder"
    ;;
  *) usage ;;
esac
