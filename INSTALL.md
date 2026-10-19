# Installing podium — instructions for AI agents

You are an AI coding agent (Claude Code, OpenCode, or similar) and your user
asked you to install podium. Follow these steps in order. The `podium` CLI does
every write; **you never hand-edit the user's configuration files**
(`CLAUDE.md`, `AGENTS.md`, `settings.json`, `opencode.json`, agent files).

## 1. Bootstrap the CLI

```sh
curl -fsSL https://raw.githubusercontent.com/davalmeyda/podium/main/install.sh | sh
```

This clones podium to `~/.local/share/podium/repo` and links
`~/.local/bin/podium`. If `podium` is not found afterwards, call it by its full
path `~/.local/bin/podium` for the rest of this session and tell the user to
add `~/.local/bin` to their `PATH`.

## 1b. Make sure Claude Code and OpenCode are current

podium targets the latest Claude Code and OpenCode 2. Preview the update, which
uses the same method each CLI was installed with (native installer, npm or Homebrew):

```sh
sh ~/.local/share/podium/repo/plugins/podium-upgrade/skills/agents-upgrade/scripts/update-clis.sh --dry-run
```

Show the user the commands and run the script without `--dry-run` once they
agree. If OpenCode is not installed and the user wants executors, offer the
official installer, then the jump to the current major:

```sh
curl -fsSL https://opencode.ai/install | bash
opencode upgrade --major
```

## 2. Detect what is already there

```sh
podium detect --json
```

Read the JSON. It tells you the OS, which CLIs exist (`claude`, `opencode`,
`codegraph`), which OpenCode providers are authenticated, existing OpenCode
agents and MCP servers, legacy hooks that podium would replace, and whether
podium is already installed.

Summarise it for the user in a few lines, in the user's language.

## 3. Ask only what detection cannot answer

Ask the user, in one round, with sensible defaults pre-selected:

1. **Languages**: language you should answer in (`language.response`), language
   for UI text and identifiers in their code (`language.domain`), language of
   podium's own UI strings (`language.ui`: `en` or `es`).
2. **Modules** to enable (default: all): `rules`, `executors`, `codegraph`,
   `memory`, `usage`, `upgrade`. Recommend turning `codegraph` off if the
   `codegraph` CLI is missing and the user does not want to install it, and
   `memory` off if they have no memory MCP server.
3. **Memory server URL** (only if `memory` is on), e.g. a Graphiti MCP endpoint.
4. **Roster preset**: `opencode-multi` (a Claude principal plus OpenCode
   executors such as MiniMax and GPT; recommend it when those providers are
   authenticated), `claude-only` (Claude principal + Claude subagents), or
   `custom` (they will edit `podium.toml` themselves).
5. If detection found existing OpenCode agents or files podium would own:
   **adopt** them (podium backs them up and takes over) or keep them untouched.

Skip any question whose answer is already clear from detection.

## 4. Write the configuration

Write the answers to a temporary JSON file, for example:

```json
{
  "language": {"response": "es", "domain": "es", "ui": "es"},
  "modules": ["rules", "executors", "codegraph", "memory", "usage", "upgrade"],
  "memory": {"url": "https://memory.example.com/mcp"},
  "roster_preset": "opencode-multi",
  "adopt": false
}
```

then run:

```sh
podium init --non-interactive --answers /path/to/answers.json
```

## 5. Show the plan, then install

```sh
podium install --dry-run
```

Show the user the planned actions (files and blocks that will be written,
plugins that will be installed). Install only after they agree:

```sh
podium install            # add --adopt if the user chose to adopt existing files
```

If detection reported legacy hooks, also run `podium migrate --dry-run`,
show the result, and run `podium migrate` after the user agrees, so the old and
new hooks never fire twice.

Exit code `2` means a conflict (a foreign or user-modified file): explain which
file and offer `--adopt` or `--force`; never pick one without asking.

## 6. Verify

```sh
podium doctor
```

Report every `WARN`/`FAIL` line with the fix. Finally tell the user to restart
their agent sessions (or run `/reload-plugins` in Claude Code) so the new rules,
hooks and skills load.

## Updating and removing

- `podium update` moves podium to the latest release and re-applies the configuration.
- `podium uninstall --dry-run`, then `podium uninstall`, removes podium's blocks,
  files and JSON keys and restores what it replaced.
