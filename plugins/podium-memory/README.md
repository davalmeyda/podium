# podium-memory

A Claude Code plugin that ships with podium and teaches agents to use the
shared work log (Graphiti by default).

It provides:

- `hooks/memory-stop.py` — a `Stop` hook that nudges the agent to record a
  Graphiti entry when substantial work happened since the last save
  (configurable edit and executor-run thresholds, with a cooldown so the same
  session is not nagged repeatedly).
- `hooks/_runtime.py` — runtime helper shared by every podium plugin: loads
  `runtime.json`, the locale file, appends to `hooks.log`, and manages the
  per-session scratch state under `state_dir/sessions/` (7-day cleanup).
- `skills/project-memory/SKILL.md` — the protocol agents follow to read and
  write to the shared log (which saga, which group, when to save, what
  belongs in Graphiti vs. the rules files, etc.).
- `locales/{en,es}.json` — the localised block reason and the
  "nothing to record" line.

## Contract

- `Stop` event, no matcher, timeout 15 s, exec form
  (`command: python3`, `args: ["${CLAUDE_PLUGIN_ROOT}/hooks/memory-stop.py"]`).
- Thresholds and the MCP server name come from `config_dir/runtime.json`
  (`memory.mcp_server`, `memory.min_edits`, `memory.min_executor_runs`,
  `memory.cooldown_seconds`, `executors.launcher_regex`). Defaults match
  ARCHITECTURE.md §9.2.
- Scratch state lives in `state_dir/sessions/memory-stop-<session_id>.json`.
- Fails open: any error is swallowed, one line appended to
  `state_dir/hooks.log`, no stdout.

## Loading order

The hook runs as part of every session. Agents should load the
`podium-memory:project-memory` skill when they want to read or write the
shared log — never on every turn.