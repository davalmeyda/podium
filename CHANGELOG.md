# Changelog

All notable changes to podium are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-19

Initial public release of podium.

### Added

- **CLI** (`bin/podium`): `detect`, `init`, `install`, `render`, `diff`, `migrate`, `doctor`, `uninstall`, and `update` subcommands; all idempotent, and `install`, `migrate` and `uninstall` accept `--dry-run`.
- **Rules engine**: ordered fragments per target declared in `rules/manifest.toml`, single-pass `{{ dotted.path }}` templating, manifest-driven overlay system at `config_dir/overlays/<target-id>/` with `insert.toml` for `before` / `after` / `omit`.
- **Roster and executor profiles**: Markdown table, excluded lines and fallback cascade generated from `[[roster]]`; OpenCode agent files rendered from `executors/profile/` plus the role-specific preamble (`writer` / `consultant` / `overflow`), with role-specific permission skeletons.
- **Roster presets** under `podium/presets/`: `opencode-multi` and `claude-only` for the two common configurations.
- **Claude Code plugins** (one marketplace, plugin files immutable at runtime):
  - `podium-codegraph` — `codegraph-gate` (PreToolUse read/edit/grep/glob/bash + PostToolUse ask) and `codegraph-nudge` hooks.
  - `podium-memory` — `memory-stop` hook plus `project-memory` skill.
  - `podium-usage` — `token-usage` mod and `scripts/session_usage.py`.
  - `podium-upgrade` — `agents-upgrade` skill and POSIX scripts.
- **Hook runtime contract**: `config_dir/runtime.json` (schema 1), built-in defaults, `locales/<ui>.json` lookup, fail-open behaviour with `state_dir/hooks.log`, session-scoped scratch state under `state_dir/sessions/`.
- **Disk safety**: managed blocks, owned files and JSON keys, `state_dir/owned.json` ledger, atomic writes via `os.replace`, `state_dir/lock` exclusive-create serialisation, timestamped `.bak-podium-*` backups, foreign-file detection with `--adopt` and modified-ledger detection with `--force`.
- **Installer flows**: agent-guided (`INSTALL.md`) primary path and manual `install.sh` bootstrap that links `bin/podium` into the user's `PATH`.
- **UI locales**: `en` and `es` shipped under each plugin's `locales/` directory; `language.ui` in `podium.toml` selects one.
- **Configuration**: `podium.toml` schema 1, validated load with `${VAR}` expansion (unset variable is an error), XDG-style path resolution in `podium/paths.py`.
- **Migration** (`podium migrate`): detects and replaces legacy `codegraph-gate`, `codegraph-nudge` and `graphiti-stop` hooks from `claude_dir/settings.json` (other hooks preserved) and copies existing `codegraph-decisions.json` records into `state_dir`.
- **Testing**:
  - `tests/` — stdlib `unittest` discovery, parity tests covering every reference capability and scenario tests for hooks (temp `HOME`, `PODIUM_CONFIG_DIR`, `PODIUM_STATE_DIR`).
  - `test/docker/Dockerfile` — clean-room Linux image.
  - `test/run.sh` — host harness; reads `CLAUDE_TOKEN_FILE` (required) and `OPENCODE_AUTH_FILE` (optional); honours `KEEP=1`.
  - `test/e2e.sh` — in-container scenario driving `podium` through detect → init → install (with --dry-run) → idempotence → doctor → codegraph gate → optional executor checks → uninstall.
- **CI and release**:
  - `.github/workflows/ci.yml` — matrix on `ubuntu-latest` + `macos-latest`, Python 3.8 + 3.12, `unittest`, shell syntax check and CLI smoke; a parallel `secrets` job runs `gitleaks`.
  - `.github/workflows/release.yml` — triggered on `v*.*.*` tags, runs `scripts/check-versions.py --tag`, unit tests, builds the tarball, generates release notes from `CHANGELOG.md` and publishes via `gh release create`.
  - `scripts/bump-version.py` — single-shot version writer for `podium/__init__.py` and every plugin manifest.
  - `scripts/check-versions.py` — asserts all versions agree, and that an external `--tag` matches the code version.
- **Documentation**: `docs/ARCHITECTURE.md` is the binding contract for the whole project; `INSTALL.md` is written for the agent that does the install.

[Unreleased]: https://github.com/davalmeyda/podium/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/davalmeyda/podium/releases/tag/v0.1.0
