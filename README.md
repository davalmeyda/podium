# podium

**One agent conducts, the rest play.** podium installs a multi-agent
orchestration setup for [Claude Code](https://claude.com/claude-code) and
[OpenCode](https://opencode.ai): a **principal** agent plans, decides and
reviews, while a **roster** of cheaper **executor** agents does the volume work
(code from closed briefs, long logs, test suites, second opinions).

It ships the rules, the executor profile and roles, Claude Code plugins
(hooks, skills, a token-usage mod) and the OpenCode agent files that make that
work, rendered from a single `podium.toml` so you can swap models and providers
without rewriting prose.

Linux and macOS. Windows is planned.

## Install

The easiest way is to let your agent do it. Open Claude Code (or OpenCode) and say:

> Install podium from https://github.com/davalmeyda/podium

The agent follows [INSTALL.md](INSTALL.md): it bootstraps the CLI, detects
what you already have, asks you only what it cannot detect, shows you the
plan, and lets the `podium` CLI do every write. It works on a clean machine and
on top of an existing Claude Code / OpenCode configuration.

### Manual install

```sh
curl -fsSL https://raw.githubusercontent.com/davalmeyda/podium/main/install.sh | sh
podium detect          # what is already there (read-only)
podium init            # wizard: languages, modules, roster preset
podium install --dry-run
podium install
podium doctor
```

Requirements: Python ≥ 3.8 and git. Claude Code is required; OpenCode is
optional (without it, use the `claude-only` roster preset). The installer
pins the latest release tag.

## What you get

| Module | What it installs |
|---|---|
| `rules` | A managed block in `~/.claude/CLAUDE.md` and `~/.config/opencode/AGENTS.md` with the orchestration rules: principal decides, closed briefs, parallel background executors, phases and reconciliation, read-only reviews, second opinion, cost model, context diet. |
| `executors` | The executor profile and one OpenCode agent file per roster entry (for example a writer, a read-only consultant and an overflow writer), with permissions enforced in frontmatter. |
| `codegraph` | Plugin `podium-codegraph`: hooks that steer agents to [CodeGraph](https://github.com/colbymchenry/codegraph) before grep, and gate work in unindexed projects until you decide whether to index them. |
| `memory` | Plugin `podium-memory`: the `project-memory` skill plus a stop hook that nudges agents to log milestones in a shared [Graphiti](https://github.com/getzep/graphiti) work log. |
| `usage` | Plugin `podium-usage`: tokens consumed by the session, its subagents and the OpenCode runs it launched. |
| `upgrade` | Plugin `podium-upgrade`: the `agents-upgrade` skill researches current models and updates your roster in `podium.toml`, then re-runs `podium install`. |

Every module is optional. Two roster presets ship with podium:
`opencode-multi` (Claude principal + OpenCode executors across providers) and
`claude-only` (Claude subagents only).

## It never clobbers your files

- podium writes only inside `<!-- podium:begin … -->` / `<!-- podium:end … -->`
  blocks, in files it created, or in JSON keys it owns. Text outside its
  blocks is never touched.
- An existing file podium did not create is refused unless you pass
  `--adopt`. A podium file you edited by hand is refused unless you pass
  `--force`. Both make a backup first (`<file>.bak-podium-<timestamp>-<id>`).
- Writes are atomic, runs are locked, and `podium uninstall` restores what
  was there before.
- Coming from a hand-written setup with the same hooks? `podium migrate`
  removes only the legacy hook entries podium replaces and keeps everything
  else.

## Make it yours

Your configuration lives in `~/.config/podium/` (or `$PODIUM_CONFIG_DIR`):

- `podium.toml`: languages, modules, roster (who does what, with which model
  and effort), executor agents, memory server, usage display order.
  See [profiles/example/podium.toml](profiles/example/podium.toml).
- `overlays/<target>/`: your own Markdown sections, inserted before or after
  any rules fragment, or replacing one. Personal rules stay out of the shared
  templates and survive updates.

The rules are written in English. Your agent still answers in your language
(`language.response`), and `language.domain` sets the language of UI text and
identifiers in your code. podium's own UI strings come in English and Spanish.

```sh
podium render --target claude-md   # preview a rendered file
podium diff                        # rendered vs what is on disk
podium update                      # pull the latest release and re-install
```

## Documentation

- [INSTALL.md](INSTALL.md): agent-guided installation.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the contract (paths, config schema,
  rendering, roster, disk writes, plugins, CLI).
- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, tests and the PR process.
- [CHANGELOG.md](CHANGELOG.md): releases.

## License

[MIT](LICENSE).
