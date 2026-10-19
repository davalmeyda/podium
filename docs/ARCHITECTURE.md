# podium — architecture and contracts

podium packages a battle-tested agent-orchestration setup as an installable,
configurable toolkit. One **principal** agent plans and decides; a **roster** of
cheaper **executor** agents does the volume work. podium ships the rules, hooks,
skills, mods and executor profiles that make that work, for Linux and macOS
(Windows later).

This document is the contract every part of the codebase follows. If code and
this document disagree, fix one of them in the same change.

## 1. Goals

1. **Capability parity.** Everything the reference setup can do, a podium
   install can do. Text and structure may improve; capabilities may not be
   lost. Parity is proven by behaviour tests (§10), not by byte equality.
2. **Never clobber.** podium writes only inside its managed blocks, files it
   owns, or JSON keys it owns. Anything it did not create is foreign.
3. **Cross-platform.** Python ≥ 3.8 (stdlib + vendored `tomli` for < 3.11) and
   POSIX `sh`/`bash`. No zsh-isms, no Homebrew-only logic, no BSD-only flags.
   Paths come from env vars with XDG fallbacks (§3).
4. **No secrets in the repo, ever.**
5. **English is canonical.** Rules, executor profile, skills, code, comments and
   docs are English. The agent's *response language* and *domain-literal
   language* are configuration. Only user-visible UI strings (hook option
   labels, mod labels) are localised, via `locales/<lang>.json` (`en`, `es`).

## 2. Repository layout

```
podium/
├── bin/podium                     # CLI entry (python3 shebang, adds repo to sys.path)
├── podium/                        # CLI package
│   ├── __init__.py                # __version__
│   ├── cli.py                     # argparse front-end (§11)
│   ├── paths.py                   # §3
│   ├── config.py                  # §4 load/validate/defaults/${VAR} expansion
│   ├── render.py                  # §5 fragments + templates + overlays
│   ├── roster.py                  # §6 roster → generated text + OpenCode agent files
│   ├── targets.py                 # §7 managed blocks, owned files, JSON merge
│   ├── state.py                   # owned.json ledger, lock, atomic write, backups
│   ├── migrate.py                 # §8 legacy hook/state migration
│   ├── doctor.py                  # §11 environment + install checks
│   ├── detect.py                  # §12 read-only environment detection
│   ├── init.py                    # §12 podium.toml generation (wizard / answers file)
│   └── presets/*.toml             # roster presets used by init
│   └── _vendor/tomli/             # tomli 2.x (MIT), used only when tomllib is missing
├── rules/
│   ├── manifest.toml              # ordered fragments per target
│   └── <fragment-id>.md           # English fragments
├── executors/
│   ├── profile/<section-id>.md    # executor profile sections (English)
│   └── roles/<role>.md            # writer | consultant | overflow preambles
├── plugins/                       # Claude Code plugins, one marketplace (§9)
│   ├── podium-codegraph/
│   ├── podium-memory/
│   ├── podium-usage/
│   └── podium-upgrade/
├── .claude-plugin/marketplace.json
├── profiles/example/podium.toml   # documented generic profile
├── install.sh                     # bootstrap: clone/update checkout, link bin/podium
├── tests/                         # python unittest (stdlib only)
├── test/docker/Dockerfile         # clean-room Linux image
├── test/e2e.sh                    # end-to-end scenario inside the container
└── docs/
```

## 3. Paths (`podium/paths.py` is the only place that resolves them)

| Name | Resolution |
|---|---|
| `claude_dir` | `$CLAUDE_CONFIG_DIR` else `~/.claude` |
| `opencode_config_dir` | `$OPENCODE_CONFIG_DIR` else `$XDG_CONFIG_HOME/opencode` else `~/.config/opencode` |
| `opencode_data_dir` | `$XDG_DATA_HOME/opencode` else `~/.local/share/opencode` |
| `config_dir` | `$PODIUM_CONFIG_DIR` else `$XDG_CONFIG_HOME/podium` else `~/.config/podium` |
| `state_dir` | `$PODIUM_STATE_DIR` else `$XDG_STATE_HOME/podium` else `~/.local/state/podium` |
| `podium_home` | the checkout running the CLI (parent of `bin/`) |

`config_dir` is **the** profile: `podium.toml` + optional `overlays/`. There is
no `--profile` flag; to use another profile, set `PODIUM_CONFIG_DIR` for both
the CLI and the agent CLIs. Hooks find their runtime file at the fixed
`config_dir/runtime.json` (§9.2).

API: `paths.resolve(env: Mapping[str,str] | None = None) -> Paths` (frozen
dataclass with the fields above as `pathlib.Path`, plus `home`).

## 4. Configuration: `config_dir/podium.toml`

```toml
schema = 1

[language]
response = "en"          # language the agents answer the user in
domain = "en"            # language for UI text, error messages and domain identifiers in code
ui = "en"                # locale of hook/mod UI strings: "en" | "es"

[modules]
rules = true
executors = true
codegraph = true
memory = true
usage = true
upgrade = true
worktrees = false        # opt-in; every other module defaults to true

[worktrees]              # only read when the worktrees module is on
link = ["node_modules"]  # folders symlinked from the main checkout into each worktree

[principal]
always_background = true          # launch every agent in background (keeps the main thread free)
subagents_preauthorized = true    # principal may spawn executors without asking
forbid_workflow_tool = true       # orchestration stays in the main thread

[launcher]
opencode = "opencode run --auto"  # prefix for every OpenCode executor launch

[[roster]]                        # one row per engine/model/role (table in the rules)
id = "minimax-fast"
engine = "MiniMax fast"           # display label
model = "MiniMax-M3 #none"        # display model
responsibility = "Code from a closed brief, mechanical refactors, run and fix validations, checklist reviews"
fallback = "haiku → luna"         # display text of the fallback chain
launch = { kind = "opencode", agent = "minimax", model = "minimax/MiniMax-M3", variant = "none" }
# launch kinds: "opencode" {agent, model, variant} | "claude" {model, effort} | "principal" {}

[[agents]]                        # OpenCode executor agent files (§6)
name = "minimax"
role = "writer"                   # writer | consultant | overflow
model = "minimax/MiniMax-M3"
description = "MiniMax-M3 executor — default code executor of the cascade."
deny_mcp = ["chrome-devtools_*"]  # extra MCP globs denied, rendered in this order

[roster_notes]
excluded = []                     # "model — reason" lines rendered under the table
cascade = []                      # "task: a → b → c" lines rendered as the fallback cascade

[memory]
backend = "graphiti"
mcp_server = "graphiti-memory"
url = "${PODIUM_GRAPHITI_URL}"    # ${VAR} expands from the environment at install time
group = "main"
headers = {}                      # extra HTTP headers for the memory MCP server (e.g. { Host = "localhost:8000" })
mcp_options = {}                  # extra scalar keys copied into the OpenCode MCP entry (e.g. { timeout = 180000, oauth = false })
stop_hook = { min_edits = 8, min_executor_runs = 2, cooldown_seconds = 2700 }

[codegraph]
gate = true
nudge_every = 4
roots = []                        # extra project roots besides HOME (e.g. "/srv", "/mnt/work")
extra_manifests = []
extra_ignored = []

[usage]
model_order = ["opus", "sonnet", "haiku", "gpt", "minimax"]   # regex fragments, display order

[render]
vars = {}                         # free values for templates: {{ vars.<key> }}
```

Rules: unknown keys are errors; every section has defaults (an empty
`podium.toml` with `schema = 1` is valid); `${VAR}` with an unset variable is an
error naming the variable. `load` adds derived keys usable in templates:
`language.response_name`, `language.domain_name` (`en`→`English`,
`es`→`Spanish`, otherwise the code itself). API:
`config.load(config_dir: Path, env=None) -> dict` (defaults merged, validated,
expanded) and `config.ConfigError(Exception)`.

## 5. Rendering

### 5.1 Templates
- Files are UTF-8, `\n` line endings, end with exactly one `\n`.
- `{{ dotted.path }}` → value from the loaded config. Lists render as
  comma-separated; booleans as `true`/`false`. Unknown path = `RenderError`.
- `{{ generated.<name> }}` → text from `roster.generated(config)` (§6).
- Substitution is single-pass and non-recursive. A literal `{{` is written `{{ "{{" }}`.
- No conditionals or loops. Variation = manifest selection + overlays.

### 5.2 Manifest `rules/manifest.toml`
```toml
[[target]]
id = "claude-md"
title = "podium rules"
fragments = [ { id = "habits", module = "rules" }, ... ]
```
`source` (optional) is the fragment directory relative to `podium_home`
(default `rules`). Fragments of a disabled module are skipped. A fragment may also carry
`requires = "<predicate>"`: `opencode-executors` renders it only when some roster row launches through
OpenCode (`launch.kind = "opencode"`), so a Claude-only roster never receives OpenCode instructions;
`worktrees` / `no-worktrees` render it only when the `worktrees` module is on / off (used to swap the
last-resort isolation text for the worktree procedure).
Fragments are joined with exactly one blank line between them.

### 5.3 Overlays `config_dir/overlays/<target-id>/`
- `<fragment-id>.md` replaces that fragment (same templating).
- `insert.toml`: `[[insert]] file = "x.md"` with exactly one of
  `after = "<id>"` / `before = "<id>"`; `omit = ["<id>"]`. Inserts with the
  same anchor keep file order. An anchor or replaced id that does not exist
  is a `RenderError` (no orphan overlays).

API: `render.render_target(target_id, config, podium_home, config_dir) -> str`
and `render.RenderError(Exception)`.

## 6. Roster

`roster.generated(config) -> dict[str, str]` returns at least:
- `roster_table` — Markdown table `| Engine | Model | Responsibility | If unavailable |`
  from `[[roster]]` in order.
- `roster_excluded` — bullet list from `roster_notes.excluded` ("" if empty).
- `fallback_cascade` — bullet list from `roster_notes.cascade`.
- `launch_examples` — one fenced `sh` block with the exact command per
  `kind = "opencode"` roster row:
  `cd <dir> && {launcher.opencode} --agent <agent> -m "<model>#<variant>" "$(cat <brief>.txt)" </dev/null > <digest>.txt 2> <trace>.txt`

`roster.render_agent(agent: dict, config, podium_home) -> str` returns a full
OpenCode agent file: YAML frontmatter (`description`, `mode: primary`, `model`,
`permission` — role-specific skeleton below, then `deny_mcp` entries) + the
role preamble `executors/roles/<role>.md` + the executor profile rendered from
`executors/profile/` in the order of the `executor-profile` target.

Role permission skeletons (in this key order):
- writer/overflow: `skill: deny`, `task: deny`, `"<memory.mcp_server>_*": deny`,
  `"codegraph_*": allow`, deny_mcp…, `bash: {"*": allow, "git *": deny}`
- consultant: as writer plus `edit: deny` after `task`, and
  `bash: {"*": deny, "ls *"|"cat *"|"head *"|"tail *"|"wc *"|"grep *"|"rg *"|"find *"|"sed -n *": allow}`

## 7. Writing to disk (`targets.py`, `state.py`)

| Target | File | Mode |
|---|---|---|
| `claude-md` | `claude_dir/CLAUDE.md` | managed block |
| `opencode-agents-md` | `opencode_config_dir/AGENTS.md` | managed block |
| `executor-profile` | `state_dir/executor-profile.md` | owned file |
| agents | `opencode_config_dir/agents/<name>.md` | owned file |
| OpenCode skills | `opencode_config_dir/skills/<skill>/` | owned dir (copied from the plugin) |
| OpenCode MCP | `opencode_config_dir/opencode.json` | owned JSON keys |
| Claude Code MCP (memory) | `$CLAUDE_CONFIG_DIR/.claude.json` (else `~/.claude.json`), pointer `/mcpServers/<mcp_server>` | owned JSON key, written only through `claude mcp` |

- **Managed block**: lines `<!-- podium:begin <target-id> -->` …
  `<!-- podium:end <target-id> -->`. Outside text is never touched. Missing
  block → appended at the end. Duplicate/unbalanced markers → refuse.
- **Owned file/dir**: ledger `state_dir/owned.json`
  `{"files": {abs_path: sha256}, "json": {abs_path: {json_pointer: {"before": <value|null>, "applied": <value>}}}, "adopted": {abs_path: backup_path}}`
  (`adopted` only when non-empty: foreign files taken over with `--adopt`; uninstall puts the backup back).
  A path not in the ledger that already exists is **foreign**: refuse unless
  `--adopt` (backup, then record). A ledger file whose hash changed was edited
  by the user: refuse unless `--force` (backup first). Owned agent and skill
  files the current config no longer renders are removed on install (left in
  place, and forgotten, if the user edited them).
- **Pruning disabled modules**: a module is *disabled* when `modules.<m> = false`
  (a module that is enabled but left out of `--modules` is untouched; a partial
  run only acts on the modules it names). After the install steps of the enabled
  modules and before the plugin steps, `install` removes what the ledger says
  podium owns for each disabled module, with the same keep/restore rules as
  `uninstall` (edited files are kept and forgotten, adopted files are restored
  from their backup): `rules` → both managed blocks; `executors` → owned agent
  files and the executor profile; `memory` → owned OpenCode skill files, the
  `/mcp/<mcp_server>` pointer and the Claude Code memory MCP entry (`claude mcp
  remove`); `codegraph` → the `/mcp/codegraph` pointer. With `memory` enabled but
  `memory.url` empty, only the two memory MCP entries are removed. For every
  disabled module that has a Claude plugin, `claude plugin uninstall
  <plugin>@podium --scope user` runs (non-fatal; "not installed"/"not found" is
  tolerated); without `claude` there is one `[skip]` note. The marketplace is
  added only while some plugin module is enabled and is never removed by
  `install`. Dry-run lists all of these as usual.
- **JSON merge**: set only owned pointers (`/mcp/<server>`,
  `/permission/<glob>`). Uninstall restores `before` only if the current value
  still equals `applied`. If both `opencode.json` and `opencode.jsonc` exist,
  podium writes `opencode.json` and `doctor` warns.
- **Claude Code MCP**: when `memory` is on, `memory.url` is non-empty and
  `claude` is on PATH, install registers `{"type":"http","url":<memory.url>}`
  (plus `headers` when set) at user scope with `claude mcp add-json <mcp_server>
  '<json>' --scope user`. podium never edits `.claude.json` (Claude rewrites it
  concurrently); it only reads it to compare, with the same ledger semantics as
  above (absent → add; foreign and different → conflict unless `--adopt`, which
  runs `claude mcp remove` then `add-json` and records `before`; owned but
  edited → conflict unless `--force`; owned and config changed → remove +
  `add-json`). Uninstall removes it (and re-adds `before`) only if the current
  value still equals `applied`. Dry-run lists the `[run]` steps; without
  `claude` there is one `[skip]` note and no ledger change.
- **Safety**: every write is atomic (temp file + `os.replace`); a lock
  `state_dir/lock` (exclusive create, stale after 10 min) serialises runs;
  backups are `<file>.bak-podium-<YYYYMMDD-HHMMSS>-<4 hex>`; an install is a
  plan applied in order and a failure stops and prints which steps ran.
- **Other writers**: the CodeGraph block (`<!-- CODEGRAPH_START -->` …) belongs
  to `codegraph` and is never inside a podium block. `agents-upgrade` edits
  `podium.toml` and then runs `podium install`; it never edits rendered files.

## 8. Migration from a hand-written setup (`podium migrate`)

- Hooks: removes from `claude_dir/settings.json` only hook entries whose command
  runs `codegraph-gate.py`, `codegraph-nudge.py` or `graphiti-stop.py` (backup
  first); everything else is preserved. `doctor` fails if a podium hook and a
  legacy hook bind the same event.
- State: copies `~/.claude/state/codegraph-decisions.json` decisions into
  `state_dir/codegraph-decisions.json` (existing podium decisions win).
- Never deletes the user's old files; prints what it left behind.

## 9. Claude Code plugins

### 9.1 Marketplace
`.claude-plugin/marketplace.json` (name `podium`) lists:

| Plugin | Contents |
|---|---|
| `podium-codegraph` | hooks `codegraph-gate` (PreToolUse `Read\|Edit\|Write\|Grep\|Glob\|Bash` + PostToolUse `AskUserQuestion`), `codegraph-nudge` (PreToolUse `Grep\|Glob\|Bash`) |
| `podium-memory` | hook `memory-stop` (Stop), skill `project-memory` |
| `podium-usage` | mod `token-usage` + `scripts/session_usage.py` |
| `podium-upgrade` | skill `agents-upgrade` + POSIX scripts |

Hook commands use exec form: `"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py"]`.
Plugin files are immutable at runtime: nothing writes into a plugin directory.
Plugin skills are namespaced by Claude Code (`/podium-upgrade:agents-upgrade`);
docs and rules use the namespaced name.

### 9.2 Hook runtime contract
1. Read stdin JSON (Claude Code hook input).
2. Load `runtime.json` from `config_dir` (resolved like §3 with the same env
   vars). Missing → built-in defaults. Shape:
   ```json
   {"schema": 1, "ui": "en",
    "paths": {"home": "/abs", "claude_dir": "/abs", "opencode_data_dir": "/abs", "state_dir": "/abs"},
    "codegraph": {"gate": true, "nudge_every": 4, "roots": [], "manifests": [], "ignored": [], "worktrees": false},
    "memory": {"mcp_server": "graphiti-memory", "min_edits": 8, "min_executor_runs": 2, "cooldown_seconds": 2700},
    "executors": {"launcher_regex": "opencode run "},
    "usage": {"model_order": ["opus","sonnet","haiku","gpt","minimax"]}}
   ```
   `manifests`/`ignored` are the *extra* entries; built-in lists live in the hook.
   `codegraph.worktrees` mirrors the `worktrees` module: the gate then never asks about a git
   worktree (`.git` is a file pointing into `.../worktrees/`) and denies work there until it is indexed.
3. Load `locales/<ui>.json` from its own plugin directory (fallback `en`).
4. Fail open (exit 0, no stdout) on any error, but append one line
   `<iso-time> <hook> <error>` to `state_dir/hooks.log`; `doctor` reports it.
5. Session-scoped scratch state goes to `state_dir/sessions/<hook>-<session_id>.json`;
   files older than 7 days are deleted opportunistically.

## 10. Tests

- `tests/` — stdlib `unittest`, run with `python3 -m unittest discover -s tests`.
- Hooks: scenario tests feed sequences of hook inputs (with a temp `HOME`,
  `PODIUM_CONFIG_DIR`, `PODIUM_STATE_DIR`) and assert outputs **and** state
  transitions (gate: deny → answer recorded → still deny until `.codegraph`
  exists → allow; stop hook: thresholds, cooldown, reset after memory save).
- Parity: `tests/parity/` holds the reference behaviours as scenarios; each
  capability of the reference setup has at least one test.
- E2E: `test/e2e.sh` inside the Docker image installs podium from the mounted
  checkout and drives `claude -p` / `opencode run` through real scenarios.

## 11. CLI

```
podium detect    [--json]
podium init      [--non-interactive] [--answers FILE]
podium install   [--dry-run] [--adopt] [--force] [--modules a,b]
podium render    [--target ID] [--out DIR]
podium diff      [--target ID]
podium migrate   [--dry-run]
podium doctor
podium uninstall [--dry-run]
podium update    [--dry-run]
podium worktree  create|integrate|clean <repo> <task> [files...]
```

`install` = validate config → render all targets → write runtime.json →
apply plan (§7) → `claude plugin marketplace add <podium_home>` +
`claude plugin install <plugin>@podium --scope user` per enabled module →
`claude mcp add-json <mcp_server> … --scope user` for the memory server (§7).
`update` = move the checkout to `PODIUM_REF` (default: the highest
`vX.Y.Z` tag on origin, else `main`) with fetch + detached checkout, exactly
like `install.sh`, then run the new checkout's `podium install`.
`worktree` runs `scripts/worktree.sh` (bash + git) with `PODIUM_STATE_DIR` and
`PODIUM_WORKTREE_LINKS` (from `[worktrees] link`): `create` makes `../<repo>-wt/<task>` on
branch `wt/<task>` from `git stash create` (or `HEAD`), copies the listed untracked files and
symlinks the link folders; `integrate` three-way merges every changed, new or deleted file onto
the main checkout's working tree (exit 2 on conflicts: markers `<<<<<<< main` / `>>>>>>> worktree`
for text, a `<file>.worktree` copy for files created on both sides, changed in the worktree but
deleted in main, binaries or symlinks changed on both sides; a file deleted in the worktree but
changed in main is kept; submodule changes are reported, never merged; executable-bit changes
carry over); `clean` removes the worktree, branch, stored
base, empty sibling folder and the CodeGraph decision. It never commits and never touches the main
checkout's branch or index.
All commands except `worktree` are idempotent; `--dry-run` writes nothing. Exit codes: 0 ok,
1 user/config error, 2 conflict (foreign or modified file), 3 environment error.

## 12. Installation flows

The model decides, the CLI writes. Agents never hand-edit the user's config files.

1. **Agent-guided (primary).** The README says: *"Tell your agent: install
   podium from https://github.com/davalmeyda/podium"*. The agent reads
   `INSTALL.md` (instructions written for agents): run `install.sh`, run
   `podium detect --json`, ask the user only what detection cannot answer,
   write `podium.toml` via `podium init --answers <file>`, show
   `podium install --dry-run`, then `podium install`, then `podium doctor`.
2. **Manual.** `curl -fsSL .../install.sh | bash` then `podium init`
   (interactive wizard with the same detection) then `podium install`.

`podium detect --json` (read-only) reports: OS, Python, which of `claude`,
`opencode`, `codegraph` exist and their versions; OpenCode authenticated
providers (`opencode auth list`); existing `opencode.json`/`.jsonc` MCP servers
and agents (marking which look like podium's); existing Claude hooks that
`migrate` would replace; existing podium install (ledger). `init` turns that
plus answers into a `podium.toml`: roster/agents only for providers the user
actually has, memory module only if an MCP URL is given, etc. Both work on a
clean machine (nothing configured) and on an existing setup.

Answers file (JSON) keys: `language.response`, `language.domain`,
`language.ui`, `modules` (list), `memory.url`, `roster_preset`
(`"opencode-multi"` | `"claude-only"` | `"custom"`), `adopt` (bool).
