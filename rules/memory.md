## Shared Memory

{{ memory.mcp_server }} is a shared work log among all agents, so any session can continue a project from where the previous one left off. **Reading** is on demand; **writing is automatic and based on value.**

- **Write (proactively, judging value):** at each milestone, save only if a future session needs the information (decision + reason, pending work, next step, non-obvious problem solved, environment fact). Prefer a few dense entries, not many small ones. The podium-memory Stop hook prompts this evaluation after substantial unrecorded work; respond by saving or with one line saying there is nothing to record—never ignore it. Save immediately: sessions usually end with Ctrl+C.
- **Read (on demand):** load the skill when the user wants to continue or resume work, asks what was done or what remains, asks you to remember something, or before substantive work where previous progress would change what you do.
- ALWAYS load the skill `podium-memory:project-memory` BEFORE using any `{{ memory.mcp_server }}` tool, and follow its procedure (it defines which log to read and how). Never query memory without it.
- Access memory ONLY through the `{{ memory.mcp_server }}` MCP tools, never through shell commands, `curl`, or scripts—even if the MCP is disconnected (in that case, warn and continue without memory).
- Do not load the skill for casual or unrelated questions.
- Preferences belong in rules files and code knowledge in CodeGraph, not in memory. Never store secrets.
- Never claim to have read or saved memory unless you actually executed the tools. If the MCP is unreachable, warn once and continue.
