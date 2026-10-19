#!/usr/bin/env python3
"""Stop hook: when substantial work happened since the last memory save,
ask the agent (once per cooldown) to load project-memory and save a single
dense entry, or reply with the locale's "nothing to record" line.

Generalised version of graphiti-stop.py. All thresholds, paths and the MCP
server name come from runtime.json (see ARCHITECTURE.md §9.2).
"""

import json
import os
import re
import sys
import tempfile
import time

from _runtime import (
    cleanup_scratch,
    load_locale,
    load_runtime,
    log_hook_error,
    read_scratch,
    resolve_paths,
    scratch_path,
    write_scratch,
)


HOOK_NAME = "memory-stop"


def main():
    paths = resolve_paths()
    runtime = load_runtime(paths)
    locale = load_locale(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        runtime.get("ui", "en"),
    )

    # also run in tmp paths, /tmp/, /private/tmp/ (macOS), and the claude projects cache
    tmpdir = tempfile.gettempdir()
    ignored_prefixes = (
        tmpdir + os.sep,
        "/tmp/",
        "/private/tmp/",
        os.path.join(paths["claude_dir"], "projects") + os.sep,
    )

    try:
        data = json.load(sys.stdin)
    except Exception as exc:
        log_hook_error(paths, HOOK_NAME, f"stdin: {exc}")
        return

    if data.get("stop_hook_active"):
        return

    transcript = data.get("transcript_path")
    session_id = data.get("session_id") or "session"
    if not transcript or not os.path.exists(transcript):
        return

    uses = parse_uses(transcript)
    if not uses:
        return

    mem_cfg = runtime.get("memory") or {}
    mcp_server = mem_cfg.get("mcp_server") or "graphiti-memory"
    min_edits = int(mem_cfg.get("min_edits", 8))
    min_executor_runs = int(mem_cfg.get("min_executor_runs", 2))
    cooldown = int(mem_cfg.get("cooldown_seconds", 2700))

    launcher_re = re.compile(runtime.get("executors", {}).get(
        "launcher_regex", r"\bopencode\s+run\s"
    ))

    state_file = scratch_path(paths, HOOK_NAME, session_id)
    state = read_scratch(state_file)
    last_nudge = int(state.get("at", 0))
    last_ts = float(state.get("ts", 0))

    now = time.time()
    if now - last_ts < cooldown:
        return

    # advance past the most recent save by the configured MCP server
    start = last_nudge
    add_suffix = mcp_server + "__add_memory"
    for i, (name, _) in enumerate(uses):
        if name.endswith(add_suffix):
            start = max(start, i + 1)

    edits, executors = count_work(
        uses[start:], ignored_prefixes, launcher_re
    )

    if edits < min_edits and executors < min_executor_runs:
        return

    cleanup_scratch(paths, now=now)
    write_scratch(
        state_file, {"at": len(uses), "ts": now}
    )

    template = (
        locale.get("stop", {}).get("reason")
        or locale.get("reason")
        or ""
    )
    reason = template.format(edits=edits, executors=executors)

    # emit block decision on stdout (Claude Code hook protocol)
    try:
        sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
        sys.stdout.write("\n")
    except Exception as exc:
        log_hook_error(paths, HOOK_NAME, f"emit: {exc}")


def parse_uses(transcript):
    """Walk the transcript and return [(tool_name, input_dict), ...]."""
    uses = []
    try:
        with open(transcript, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "assistant":
                    continue
                content = (
                    (d.get("message") or {}).get("content") or []
                )
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") != "tool_use":
                        continue
                    uses.append(
                        (c.get("name", ""), c.get("input") or {})
                    )
    except Exception:
        return []
    return uses


def count_work(uses, ignored_prefixes, launcher_re):
    edits = 0
    executors = 0
    for name, inp in uses:
        if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            fp = (
                inp.get("file_path", "")
                or inp.get("notebook_path", "")
                or ""
            )
            if not fp.startswith(ignored_prefixes):
                edits += 1
        elif name == "Bash" and launcher_re.search(
            inp.get("command", "") or ""
        ):
            executors += 1
    return edits, executors


try:
    main()
except Exception as exc:
    # fail open: no stdout, but log it
    try:
        paths = resolve_paths()
    except Exception:
        paths = {"state_dir": ""}
    log_hook_error(paths, HOOK_NAME, repr(exc))