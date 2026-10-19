## Shared Memory

{{ memory.mcp_server }} is a shared work log among all agents, so any session can continue a project from where the previous one left off. Reading is on demand; writing is your initiative, judged by value.

- **Write (proactively, judging value):** at each milestone (task completed, decision made, non-obvious bug solved), ask whether a future session would do something wrong or repeat work without the information. If yes, load the `project-memory` skill and save ONE dense entry immediately (sessions usually end with Ctrl+C). If not, do not save; each entry incurs extraction work on the server.
- **Read (on demand):** load the skill when the user wants to continue or resume work, asks what was done or remains, or asks you to remember something.
- ALWAYS load the `project-memory` skill BEFORE calling any `{{ memory.mcp_server }}` tool, and follow its procedure (it defines which log to read and how). Never query memory directly without it. OpenCode loads skills from its skills directory; the skill name there is `project-memory`, not namespaced.
- Access memory ONLY through the `{{ memory.mcp_server }}` MCP tools, never through shell commands, `curl`, or scripts, even if the MCP is disconnected.
- Do not load the skill for casual or unrelated questions.
- Preferences belong in rules files and code knowledge in CodeGraph, not in memory. Never store secrets.
- Never claim to have read or saved memory unless you actually executed the tools. If the MCP is unavailable, say so once and continue.

Executors launched by the orchestrator ignore this flow; their agent file overrides it.
