# Changelog

All notable changes to podium are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `install` registers the memory MCP server in Claude Code (`claude mcp add-json --scope user`), tracked in the ledger and removed on uninstall.
- `install` prunes what podium owns for modules disabled in `podium.toml` (blocks, agents, skills, MCP pointers, plugins); `--modules` partial runs never prune.
- `custom` roster preset (principal only, commented examples) for hand-edited rosters.
- Manifest fragments can declare `requires = "opencode-executors"`: Claude-only rosters no longer receive OpenCode instructions (`roster-opencode` fragment).
- Container test battery: `test/run-scenarios.sh` runs each `test/scenarios/*.sh` in its own fresh container, in parallel, including real `claude -p` and OpenCode runs when credentials are supplied.

### Changed
- Rules generalised: project typecheck instead of `tsc`, dependency manifests instead of `package.json`/pnpm only, provider-specific measurements moved out of the generic rules, shared-quota warning, verifiable web-search rule.
- `agents-upgrade` skill restored to the full workflow: complete release inventory, research floors (3 queries, 2 sources), 30-day usage analysis, budget arithmetic, panel controls, post-apply runtime verification; upgrade results go to the history file, not shared memory.
- Upgrade scripts: install method decided by package ownership (npm/brew/native), `brew upgrade --cask --greedy`, catalogue checks never abort and report the model recorded in `opencode.db`; preflight compares installed agents and table with the configured roster and excludes the OpenCode service from active sessions.
- Usage: Claude effort is accounted again (separate rows per effort); neutral default ordering; `/tokens` follows the UI language; malformed runtime/locale JSON falls back to defaults.

### Fixed
- `doctor` crashed on naive timestamps in `hooks.log` and never reported legacy hooks.
- `detect` lower-cases OpenCode provider ids and marks podium-owned agents via the ledger.
- CodeGraph gate: the Bash exemption now requires every command segment to be `codegraph` (was a substring test); Spanish nudge text; configured roots and path overrides honoured; locale fallbacks never disable a hook.
- Memory hook never emits an empty reason; locale errors are logged to the state dir.
- `catalogs.sh`: syntax error in the provider loop, `opencode` consuming the loop's stdin, `opencode models` no longer takes a provider argument, variant taken from the roster row.
- `init` validates `${VAR}` references without requiring them to be set (they expand at install time).

## [0.1.0] - 2026-10-19

Initial public release of podium.

### Added

- **CLI** (`bin/podium`): `detect`, `init`, `install`, `render`, `diff`, `migrate`, `doctor`, `uninstall`, and `update` subcommands; all idempotent; `install`, `migrate`, `uninstall` and `update` accept `--dry-run`, and `render` / `diff` preview the exact text. `update` follows release tags like `install.sh`.
- **Rules engine**: ordered fragments per target declared in `rules/manifest.toml`, single-pass `{{ dotted.path }}` templating, manifest-driven overlay system at `config_dir/overlays/<target-id>/` with `insert.toml` for `before` / `after` / `omit`.
- **Roster and executor profiles**: Markdown table, excluded lines and fallback cascade generated from `[[roster]]`; OpenCode agent files rendered from `executors/profile/` plus the role-specific preamble (`writer` / `consultant` / `overflow`), with role-specific permission skeletons.
- **Roster presets** under `podium/presets/`: `opencode-multi` and `claude-only` for the two common configurations.
- **Claude Code plugins** (one marketplace, plugin files immutable at runtime):
  - `podium-codegraph` — `codegraph-gate` (PreToolUse read/edit/grep/glob/bash + PostToolUse ask) and `codegraph-nudge` hooks.
  - `podium-memory` — `memory-stop` hook plus `project-memory` skill.
  - `podium-usage` — `token-usage` mod and `scripts/session_usage.py`.
  - `podium-upgrade` — `agents-upgrade` skill and POSIX scripts.
- **Hook runtime contract**: `config_dir/runtime.json` (schema 1), built-in defaults, `locales/<ui>.json` lookup, fail-open behaviour with `state_dir/hooks.log`, session-scoped scratch state under `state_dir/sessions/`.
- **Disk safety**: managed blocks, owned files and JSON keys, `state_dir/owned.json` ledger, atomic writes via `os.replace`, `state_dir/lock` exclusive-create serialisation, timestamped `.bak-podium-*` backups, foreign-file detection with `--adopt` (uninstall restores the adopted original) and modified-ledger detection with `--force`; agent and skill files the config no longer renders are pruned.
- **Installer flows**: agent-guided (`INSTALL.md`) primary path, which also brings Claude Code and OpenCode to their latest versions, and manual `install.sh` bootstrap that links `bin/podium` into the user's `PATH`.
- **UI locales**: `en` and `es` shipped under each plugin's `locales/` directory; `language.ui` in `podium.toml` selects one.
- **Configuration**: `podium.toml` schema 1, validated load with `${VAR}` expansion (unset variable is an error), XDG-style path resolution in `podium/paths.py`.
- **Migration** (`podium migrate`): detects and replaces legacy `codegraph-gate`, `codegraph-nudge` and `graphiti-stop` hooks from `claude_dir/settings.json` (other hooks preserved) and copies existing `codegraph-decisions.json` records into `state_dir`.
- **Testing**:
  - `tests/` — stdlib `unittest` discovery, parity tests covering every reference capability and scenario tests for hooks (temp `HOME`, `PODIUM_CONFIG_DIR`, `PODIUM_STATE_DIR`).
  - `test/docker/Dockerfile` — clean-room Linux image.
  - `test/run.sh` — host harness; reads `CLAUDE_TOKEN_FILE` (required) and `OPENCODE_AUTH_FILE` (optional); honours `KEEP=1`.
  - `test/e2e.sh` — in-container scenario driving `podium` through detect → init → install (with --dry-run) → idempotence → doctor → codegraph gate → optional executor checks → uninstall, plus an install on top of an existing setup (user CLAUDE.md, opencode.json and a foreign agent) that uninstall gives back.
  - `test/agent-install.sh` — a real `claude -p` session told only "install podium from <repo>" follows `INSTALL.md` on its own in a fresh container.
- **CI and release**:
  - `.github/workflows/ci.yml` — matrix on `ubuntu-latest` + `macos-latest`, Python 3.8 + 3.12, `unittest`, shell syntax check and CLI smoke; a parallel `secrets` job runs `gitleaks`.
  - `.github/workflows/release.yml` — triggered on `v*.*.*` tags, runs `scripts/check-versions.py --tag`, unit tests, builds the tarball, generates release notes from `CHANGELOG.md` and publishes via `gh release create`.
  - `scripts/bump-version.py` — single-shot version writer for `podium/__init__.py` and every plugin manifest.
  - `scripts/check-versions.py` — asserts all versions agree, and that an external `--tag` matches the code version.
- **Documentation**: `docs/ARCHITECTURE.md` is the binding contract for the whole project; `INSTALL.md` is written for the agent that does the install.

[Unreleased]: https://github.com/davalmeyda/podium/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/davalmeyda/podium/releases/tag/v0.1.0
