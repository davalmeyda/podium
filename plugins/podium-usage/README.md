# podium-usage

Claude Code mod that shows the tokens consumed in this session — Claude (with
subagents and compactions) and the `opencode run` calls it launched — and tags
every `opencode run` with the Claude session that launched it.

## Layout

```
plugins/podium-usage/
├── .claude-plugin/plugin.json   # name "podium-usage", MIT, version 0.1.0
├── hooks/
│   ├── hooks.json               # registers ./register.tsx
│   ├── register.tsx             # event handlers
│   ├── lib.ts                   # pure helpers (tagging, formatting, ordering)
│   └── lib.test.ts              # Bun tests
├── scripts/session_usage.py     # reads transcripts + opencode.db + runtime.json + locale
├── types/index.d.ts             # shared TS types
├── locales/
│   ├── en.json
│   └── es.json
└── README.md
```

## Configuration

`runtime.json` at `$PODIUM_CONFIG_DIR` (else `$XDG_CONFIG_HOME/podium` else
`~/.config/podium`) drives two things — see `docs/ARCHITECTURE.md` §9.2:

- `usage.model_order` (list of regex fragments): display order for models in
  the pane; anything not matched falls to the end.
- `ui` (`"en" | "es"`): locale of all visible labels.

Missing file → built-in defaults (model_order
`["opus","sonnet","haiku","gpt-6.1-sol","gpt-6-luna","gpt","minimax"]`, ui `"en"`).

## Paths

Resolved by `scripts/session_usage.py` per `docs/ARCHITECTURE.md` §3:

- OpenCode DB → `$XDG_DATA_HOME/opencode/opencode.db` else
  `~/.local/share/opencode/opencode.db`.
- Claude transcripts → `$CLAUDE_CONFIG_DIR/projects` else
  `~/.claude/projects`.

## Behaviour

- `/tokens` opens a pane with per-model input/output, compactions summed by
  model, and `5h` / `7d` rate-limit reads from Claude.
- Status line shows `Claude <in>↓ <out>↑` and, when there is OpenCode usage,
  `OpenCode <in>↓ <out>↑`, the session cost, and the 5-hour percentage.
- Refresh every 30 s; one in-flight refresh at a time.
- `session.compact` events are recorded in the plugin store under
  `compact:<sessionId>` because their usage never reaches the transcript.
- Every `Bash` command whose argv matches `opencode run` (without
  `--session|-s|--continue|-c`) is rewritten to add
  `--session ses_cc<sessionId>x<ts><n>` so the OpenCode DB join can find the
  children of this Claude session.

## Tests

```
cd plugins/podium-usage && bun test
```

If `claude-code/testing` cannot be resolved outside Claude Code, fall back to
`bun build --no-bundle hooks/lib.ts` (or `deno check hooks/lib.ts`) for syntax
sanity. The Python script validates with `python3 -m py_compile`.

## License

MIT.