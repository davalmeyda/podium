---
name: project-memory
description: Shared work log in Graphiti, common to every agent (Claude Code, OpenCode). Use it to resume work where a previous session or another agent left off ("where did we leave off", "what's pending", "what's next"), to bring the log of another folder or project, when the user asks you to remember something, and to record progress right after finishing a meaningful piece of work. Not for preferences (those live in the rules files) and not for code questions (use CodeGraph). Do not load it for unrelated or casual questions.
---

# Project Memory (shared work log)

The memory MCP server configured in podium (default `graphiti-memory`) holds a
shared work log, so any agent can pick up where the last session stopped
without carrying a huge context. It is NOT mandatory at conversation start and
it is NOT a rulebook.

## What goes here (and what does not)

| Kind | Where it lives |
|---|---|
| Progress: done, pending, next step, decisions taken | The memory MCP server — log entry |
| Durable facts about the environment: servers, ports, where something is deployed, what was installed or removed | The memory MCP server — environment fact |
| Anything the user explicitly asks to remember | The memory MCP server — note |
| User preferences and ways of working | Rules files (`CLAUDE.md` / `AGENTS.md`), NOT Graphiti |
| Code structure, symbols, how code works | CodeGraph / the repository, NOT Graphiti |
| Secrets, tokens, passwords, API keys, personal data | NOWHERE |

If you notice the user correcting the same behavior repeatedly, suggest adding
it to their rules file instead of saving it here.

## Which log (saga) this conversation uses

A log belongs to the **folder** where the session was opened, not to a Git
repository. Resolve it once per conversation with:

```sh
d="$PWD"; key=""
while :; do
  if [ -f "$d/.project-memory" ]; then key=$(head -n1 "$d/.project-memory" | tr -d '[:space:]'); break; fi
  if [ "$d" = "$HOME" ] || [ "$d" = "/" ]; then break; fi
  d=$(dirname "$d")
done
if [ -z "$key" ]; then if [ "$PWD" = "$HOME" ]; then key=general; else key="${PWD#$HOME/}"; fi; fi
echo "log:$key"
```

- `.project-memory` marker (optional): a one-line file with a log name, placed
  in the top folder of a project (e.g. the folder holding back and front). Any
  subfolder resolves to that name, and it survives moving the folder or using
  another machine. Only create it when the user asks.
- Home folder → `log:general` (casual chats, nothing project-specific).
- Otherwise → `log:<path relative to home>`, e.g. `log:work/acme`.
- **Switching on request:** "bring the log of X" → read that log; "keep
  recording in X" → use that log for the rest of the conversation. Find the
  exact name through the log index (below). If several logs match, ask which
  one.

## Fixed conventions

- **Group:** the group configured in podium (default `main`). No other groups
  are used by default.
- **Header:** every episode body starts with one line:
  `[log: <key> | scope: log|global | type: log-entry|environment|note|log-index]`
  - `log` = where it was recorded (origin).
  - `scope` = who it applies to. `log` only applies to that log's work;
    `global` applies everywhere. Log entries are always `scope: log`.
    Environment facts are usually `global`.
- **Qualified names:** inside the text, name things with their log or project
  ("the auth module of acme-api", not just "the auth module"), so the graph
  does not merge entities from different projects.
- Write episodes in English; quote domain literals verbatim.

## Reading (on demand, never forced)

Read when the user wants to continue or resume work, asks about past progress
or decisions, asks for another log, or when you are about to start substantive
work and prior progress would change what you do. Skip it for casual or
unrelated questions.

1. `summarize_saga(saga_name="log:<key>", group_id="<group>")` → the overall
   picture. "No saga named …" means nothing was logged there yet (stop here).
2. `get_episodes(group_ids=["<group>"], max_episodes=30)` → keep only episodes
   whose content starts with `[log: <key> |` and `type: log-entry`, and read
   the 2-3 most recent ones in full. The summary is LLM-compressed and drops
   details; the latest entries carry the exact Pending and Next step lists.
   When they disagree, the latest entry wins.
3. Only if a specific detail is needed: `search_memory_facts` /
   `search_nodes` with `group_ids=["<group>"]` and the log key in the query.

Answer with: the overall picture (1), then Pending and Next step taken
literally from the latest entry (2).

Applying what you read:
- Apply `scope: global` facts anywhere; apply `scope: log` facts ONLY when
  working on that same log.
- Memory can be stale. The repository and the live system are the source of
  truth; verify before acting on a remembered fact.
- Keep it short: bring back what matters for the task, never dump the log.

## Writing (automatic, as you go, no confirmation needed)

Sessions usually end with Ctrl+C, so there is no "end of session" moment:
save at the milestone itself, not later. Every save costs LLM extraction on
the memory server, so **save by value, not by activity**. Before saving, ask:
*would a future session do something wrong or redo work without this?*

- **Save** when there is: a feature/phase/fix completed, a decision with its
  reason, pending work or a next step that would be lost, a non-obvious problem
  solved (cause + fix), or a durable environment fact.
- **Do not save**: exploration with no conclusion, small edits, questions
  answered, refactors with nothing pending, anything already logged.
- Prefer **few dense entries** (one per milestone, merging everything since the
  last save) over many small ones.

**Log entry:**

```
add_memory(
  name="<YYYY-MM-DD>-<short topic>",
  group_id="<group>",
  saga="log:<key>",
  source="text",
  episode_body="""[log: <key> | scope: log | type: log-entry]
Done: ...
Pending: ...
Next step: ...
Decisions: <decision> — because <reason>"""
)
```

Only what a future session needs to continue. No logs, no transcripts, no
failed attempts without a lesson.

**Log index (first entry of a new log only):** before the first save of a
conversation, call `summarize_saga` for the log. If it answers "No saga
named …", the log is new: also save, without saga,

```
[log: <key> | scope: global | type: log-index]
Project log "log:<key>" exists. Folder: <absolute folder>. About: <one line on what this project is>.
```

so "bring the log of X" can find it later with `search_memory_facts` (query:
"project log" plus the user's words).

**Environment fact** — when you verify a durable, non-secret fact about the
user's setup, save it with `type: environment` (usually `scope: global`, no
saga).

**Explicit note** — when the user says "remember this" or similar, save it
with `type: note`, in the current log's saga. `scope: log` only if the user
ties it to this work; otherwise `global`.

After saving, tell the user in one line what was recorded.

## Memory-server behavior to keep in mind

- **Never pass `uuid` to `add_memory`**: it means "update the existing episode
  with that uuid", and with a new one the episode is silently discarded.
- `add_memory` only queues the episode; it usually becomes searchable and part
  of the saga summary within about a minute (up to ~2 minutes). Do not claim
  it is integrated before that, and do not wait for it unless confirmation
  matters.
- While an episode is being processed, searches slow down. Avoid searching in
  a loop right after saving.

## Corrections and deletion

- To correct something, save a NEW entry stating what it replaces. Do NOT
  delete episodes to correct: the saga summary is stored separately and keeps
  showing the deleted content.
- Ask for explicit authorization before `delete_episode`,
  `delete_entity_edge`, or `clear_graph`. Never use `clear_graph`.

## Access only through the MCP

Read and write memory ONLY through the configured memory MCP tools (default
`graphiti-memory`). NEVER access it with shell commands, curl, HTTP requests,
or scripts of any kind, not even as a workaround when the MCP is disconnected.
(The only shell command in this skill is the folder-to-log snippet above,
which does not touch the memory server.)

## Failures

If the memory server does not respond or the MCP is disconnected, say so ONCE,
suggest reconnecting it (`/mcp` in Claude Code), and continue without memory.
Do not work around it. Never claim you read or saved memory without actually
executing the tools.