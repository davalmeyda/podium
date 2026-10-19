### Models: Subagents Are Always Economical

The principal uses the session model. Claude subagents ALWAYS use economical models:
- **`haiku`** (default effort): bounded exploration, extraction, informational questions; code fallback for a closed brief, verbose outputs, and long contexts. Long contexts (> ~100K tokens) are disproportionately expensive on small Claude models: route that work to the writer executor.
- **`sonnet`** (`high`): pre-distribution scout, contracts, and tightly coupled logic; final fallback for capability.
- No subagent inherits the session model. If a subtask seems to need the expensive model, it requires decisions → it belongs to the principal.
