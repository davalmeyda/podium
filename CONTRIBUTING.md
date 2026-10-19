# Contributing to podium

Thank you for your interest in improving podium.

## What is podium?

podium is a public open-source toolkit that packages a battle-tested agent-orchestration setup as an installable, configurable system. One **principal** agent plans and decides; a **roster** of cheaper **executor** agents does the volume work. It ships the rules, hooks, skills, plugins, mods, executor profiles and roster presets that make that work, for Linux and macOS.

## Ways to contribute

You can help in many ways, and not all of them are code:

- **Report bugs and rough edges** via the bug report form.
- **Propose features** (new modules, new executor roles, better detection) via the feature request form.
- **Improve a rules fragment** under `rules/` — wording, ordering, or coverage of a scenario you hit.
- **Write or refine a hook** under one of the plugin directories (see §9.2 of `docs/ARCHITECTURE.md`).
- **Build a plugin** that fits the existing marketplace contract.
- **Add or refine a roster preset** under `podium/presets/`.
- **Translate a locale** by copying an existing `locales/en.json` and translating the UI strings.
- **Improve documentation** under `docs/` and the README.
- **Review PRs** and help triage issues.

If you are unsure where to start, open a Discussion or pick an issue labelled `good first issue`.

## Development setup

Clone the repository, then run the test suite and the CLI help from a working tree:

```sh
git clone https://github.com/davalmeyda/podium
cd podium
python3 -m unittest discover -s tests
python3 bin/podium --help
```

podium itself is a Python ≥ 3.8 standard-library project. The bootstrap script
links `bin/podium` into your `PATH`, but for local development it is fine to
invoke `python3 bin/podium …` directly.

### Optional: clean-room Docker e2e

For a true end-to-end check against Claude Code and OpenCode, build and run the
clean-room image. Nothing on the host is modified.

```sh
# Required for the `claude` checks
export CLAUDE_TOKEN_FILE=/path/to/claude-token-file
# Optional: enables the OpenCode executor checks
export OPENCODE_AUTH_FILE=/path/to/opencode-auth-export.json
test/run.sh
```

The harness reads two environment variables:

- `CLAUDE_TOKEN_FILE` — path to a file containing a `claude setup-token` value. Required for any check that drives `claude -p`.
- `OPENCODE_AUTH_FILE` — path to an `opencode auth export` JSON. Optional; when present, the harness imports it and runs the executor checks.
- `KEEP=1` — keep the container afterwards for inspection.

Both variables are read by `test/run.sh`. The image build is driven by `test/docker/Dockerfile`; the in-container scenario lives in `test/e2e.sh`.

## Project principles

These come straight from `docs/ARCHITECTURE.md` §1 and are not negotiable in a contribution:

1. **Capability parity.** Everything the reference setup can do, a podium install can do. Text and structure may improve; capabilities may not be lost. Parity is proven by behaviour tests, not by byte equality.
2. **Never clobber.** podium writes only inside its managed blocks, files it owns, or JSON keys it owns. Anything it did not create is foreign.
3. **Cross-platform.** Python ≥ 3.8 (stdlib + vendored `tomli` for < 3.11) and POSIX `sh`/`bash`. No zsh-isms, no Homebrew-only logic, no BSD-only flags. Paths come from env vars with XDG fallbacks (§3 of `docs/ARCHITECTURE.md`).
4. **No secrets in the repo, ever.** The CI runs `gitleaks` on every push and PR.
5. **English is canonical.** Rules, executor profile, skills, code, comments and docs are English. Only user-visible UI strings (hook option labels, mod labels) are localised via `locales/<lang>.json`.

If a contribution violates any of these, the PR will be declined with a clear pointer to the section above.

## Repository layout

```
podium/
├── bin/podium                 # CLI entry point (python3 shebang)
├── podium/                    # CLI package (paths, config, render, roster, targets, state…)
│   ├── cli.py                 # argparse front-end
│   ├── presets/*.toml         # roster presets used by init
│   └── _vendor/tomli/         # vendored tomli 2.x (MIT); used only when tomllib is missing
├── rules/
│   ├── manifest.toml          # ordered fragments per target
│   └── <fragment-id>.md       # English fragment text
├── executors/
│   ├── profile/<section-id>.md
│   └── roles/<role>.md        # writer | consultant | overflow
├── plugins/                   # Claude Code plugins (one marketplace; §9)
│   ├── podium-codegraph/
│   ├── podium-memory/
│   ├── podium-usage/
│   └── podium-upgrade/
├── .claude-plugin/marketplace.json
├── profiles/example/podium.toml
├── install.sh                 # bootstrap: clone/update checkout, link bin/podium
├── tests/                     # python unittest (stdlib only)
├── test/docker/Dockerfile     # clean-room Linux image
├── test/e2e.sh                # end-to-end scenario inside the container
└── docs/                      # ARCHITECTURE.md is the binding contract
```

## How to add a new rules fragment

1. Write the fragment as a UTF-8 Markdown file under `rules/<fragment-id>.md`. End with exactly one `\n` line ending.
2. Reference it from `rules/manifest.toml` in the `fragments` list of every target that should include it. Both `id` and `module` are required.
3. Templating is single-pass and non-recursive. Use `{{ dotted.path }}` to interpolate config values, `{{ generated.<name> }}` for roster-generated text, and `{{ "{{" }}` for a literal `{{`. Allowed template variables are documented in `docs/ARCHITECTURE.md` §5.1 — anything else is a `RenderError`.
4. Optional overrides go under `config_dir/overlays/<target-id>/<fragment-id>.md` (same templating) and `insert.toml` (`[[insert]]` with `before` or `after`, plus `omit`). An anchor that does not exist is a hard error — no orphan overlays.
5. Add a parity or behaviour test under `tests/` that proves the new fragment appears in the rendered output.

## How to add a new hook

Hooks are Python scripts called by Claude Code via the plugin manifest. They follow the runtime contract in `docs/ARCHITECTURE.md` §9.2:

1. Read the hook payload from stdin as JSON.
2. Load `runtime.json` from `config_dir` (resolved like §3 of `docs/ARCHITECTURE.md`). Missing file → built-in defaults.
3. Load `locales/<ui>.json` from the plugin directory, falling back to `locales/en.json`.
4. **Fail open**: exit `0` with empty stdout on any error; append one line `<iso-time> <hook> <error>` to `state_dir/hooks.log` so `podium doctor` can report it.
5. Session-scoped scratch state goes to `state_dir/sessions/<hook>-<session_id>.json`; files older than 7 days are deleted opportunistically.

Tests are required. Use a temp `HOME`, `PODIUM_CONFIG_DIR` and `PODIUM_STATE_DIR`, feed sequences of hook inputs, and assert both the output **and** the state transitions.

## How to add a new locale

1. Pick the plugin that owns the strings (e.g. `plugins/podium-codegraph/locales/`).
2. Copy `en.json` to `locales/<lang>.json` and translate the values. Keys stay in English.
3. Add a parity test under `tests/` that loads the new locale, asserts every key in `en.json` is present, and that a representative rendered label equals the translated value.
4. UI strings are English by default; setting `[language] ui = "<lang>"` in `podium.toml` activates the new locale at install time.

## How to add a new roster preset

Roster presets live in `podium/presets/<name>.toml`. To add one:

1. Copy `podium/presets/claude-only.toml` or `podium/presets/opencode-multi.toml` as a starting point.
2. Edit the `[[roster]]`, `[[agents]]`, `[roster_notes]`, and `[launcher]` sections to match the engines and models you want to support.
3. Add the preset name to `podium init` so it appears in the wizard and is accepted as the `--answers` `roster_preset` value.
4. Add a parity test that runs `podium init --non-interactive --answers …` with the new preset and asserts the generated `podium.toml` contains the expected roster entries.

## Coding style

- **Standard library only.** Do not add a runtime dependency to `pyproject.toml` or any plugin manifest unless the principal has approved it.
- **Python ≥ 3.8 syntax.** Use `from __future__ import annotations` at the top of new modules so type hints stay readable on 3.8.
- **Shell.** Stick to POSIX `sh` / `bash`. No zsh-only constructs, no Homebrew-only logic, no BSD-only flags. Tests on macOS and Linux run from the same matrix (`ubuntu-latest` + `macos-latest`).
- **Small functions.** Each function should do one thing and be readable top to bottom.
- **English identifiers and comments.** Non-English text appears only in `locales/<lang>.json` files.
- **No `prettier-ignore` and friends.** There is no generated client in this repo, so the rule applies to everything else too. Break long lines manually instead.
- **Tests for every behaviour change.** A change without a test is incomplete.

## Pull request rules

- **One topic per PR.** A bug fix and an unrelated refactor belong in two PRs.
- **Conventional Commits titles.** Use one of `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:` (and the standard variants) as the commit subject and the PR title prefix.
- **Describe user-visible impact.** The PR body must say what changes for the user, not just what changed in the code.
- **Update `CHANGELOG.md`.** Add a bullet under `## [Unreleased]`. Use `Added`, `Changed`, `Fixed`, or `Removed` subsections.
- **Tests + CI green.** `python3 -m unittest discover -s tests` must pass locally, and the CI matrix (`ubuntu-latest` + `macos-latest`, Python 3.8 + 3.12) must be green before review.
- **No personal data, paths or secrets.** The CI runs `gitleaks`; any leaked token, email, personal home-directory path or personal project name will fail the build. Use neutral examples such as `~/work/acme` or `billing-service`.
- **Rule-text changes must declare their capability impact.** If your PR changes the text rendered into `CLAUDE.md` or `AGENTS.md`, the PR body must say whether any capability is added, changed or removed. Capability parity is a project principle (§1.1) and the reviewer needs this to evaluate the change.

## Review and merge

A maintainer will review your PR. Small changes may be merged with a squash commit; larger ones may be rebased. CI must be green on both Ubuntu and macOS before merge. Reviewers will check:

- That the contract in `docs/ARCHITECTURE.md` is honoured.
- That the tests actually cover the change.
- That the changelog entry is in the right section and uses the right vocabulary.

## Release process

Releases are cut by a maintainer.

1. Pick the next version following semver. `scripts/bump-version.py X.Y.Z` rewrites `podium/__init__.py` and every plugin manifest to that version in one go. Use it; do not edit those files by hand.
2. In `CHANGELOG.md`, replace the `## [Unreleased]` heading with `## [X.Y.Z] - YYYY-MM-DD` and move the bullets under it. Add a fresh empty `## [Unreleased]` above for the next cycle.
3. Commit, then push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z` (the maintainer does this; you do not push tags in your own fork).
4. The release workflow (`.github/workflows/release.yml`) builds the tarball, computes SHA256, generates release notes from `CHANGELOG.md`, and publishes via `gh release create`. `scripts/check-versions.py --tag vX.Y.Z` is the gate that asserts the tag matches the code.

You do not need any of this for a first contribution. Open an issue or PR first.

## Licensing

podium is MIT-licensed. By submitting a contribution, you agree that your work is licensed under the same MIT terms as the rest of the project. No DCO sign-off is required.

## Questions?

Open a discussion or an issue. Maintainers will respond as time allows.
