#!/usr/bin/env python3
"""CodeGraph nudge hook for Claude Code.

PreToolUse (Grep|Glob|Bash): remind the user to use CodeGraph when the repo
is indexed. Never blocks. String comes from locales/<ui>.json. Scratch state
moves to <state_dir>/sessions/<hook>-<session_id>.json with 7-day cleanup.
"""
import json
import os
import re
import sys

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runtime  # noqa: E402


_SKIP_DIRS = {"node_modules", "Library", ".git", "dist", "build", ".next", "vendor"}


def ancestors_index(path, roots):
    """Walk up from `path` looking for a .codegraph/ inside HOME or roots."""
    d = os.path.abspath(path)
    for top in (os.path.expanduser("~"),) + tuple(roots or ()):
        if not top:
            continue
        top_abs = os.path.abspath(os.path.expanduser(top))
        if not (d == top_abs or d.startswith(top_abs + os.sep)):
            continue
        cur = d
        while cur.startswith(top_abs + os.sep) and cur != top_abs:
            if os.path.isdir(os.path.join(cur, ".codegraph")):
                return [cur]
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    return []


def sub_indexes(root, depth=3):
    found = []
    root = os.path.abspath(root)
    base = root.count(os.sep)
    home = os.path.expanduser("~")
    for d, dirs, _ in os.walk(root):
        if ".codegraph" in dirs and d != home:
            found.append(d)
        if d.count(os.sep) - base >= depth - 1:
            dirs[:] = []
        else:
            dirs[:] = [x for x in dirs if x not in _SKIP_DIRS and not x.startswith(".")]
    return found


def main():
    paths, runtime = _runtime.resolve_paths()
    try:
        data = json.load(sys.stdin)
    except Exception as exc:
        _runtime.log_error(paths["state_dir"], "codegraph-nudge", f"stdin json: {exc}")
        return

    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    codegraph_cfg = runtime.get("codegraph", {}) or {}
    period = codegraph_cfg.get("nudge_every", 4) or 4
    roots = codegraph_cfg.get("roots") or ()

    if tool == "Bash":
        cmd = inp.get("command", "")
        if "codegraph" in cmd or not re.search(r"(^|[\s|;&(])(grep|rg|ag|ack|find)\s", cmd):
            return

    target = inp.get("path") or cwd
    if not os.path.isabs(target):
        target = os.path.join(cwd, target)
    if os.path.isfile(target):
        target = os.path.dirname(target)

    state_path = _runtime.session_scratch(
        paths["state_dir"], "codegraph-nudge", data.get("session_id", "x"))
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {"n": 0, "idx": {}}

    key = os.path.abspath(target)
    if key not in state["idx"]:
        state["idx"][key] = ancestors_index(target, roots) or sub_indexes(target)
    idx = state["idx"][key]
    if idx:
        state["n"] += 1
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as exc:
        _runtime.log_error(paths["state_dir"], "codegraph-nudge", f"scratch write: {exc}")

    if not idx or (state["n"] - 1) % period != 0:
        return

    locale = _runtime.load_locale(runtime.get("ui", "en"), _PLUGIN_ROOT)
    roots_str = ", ".join(idx[:6])
    msg = locale["nudge"]["available"].format(roots=roots_str)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": msg,
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            state_dir = os.environ.get("PODIUM_STATE_DIR") or os.path.join(
                os.path.expanduser("~"), ".local", "state", "podium")
            _runtime.log_error(state_dir, "codegraph-nudge", f"top-level: {exc}")
        except Exception:
            pass