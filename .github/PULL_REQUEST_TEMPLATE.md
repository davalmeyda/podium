## Summary

<!-- One or two sentences describing the change and why. -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds a capability)
- [ ] Breaking change (a capability stops working or its public contract changes)
- [ ] Documentation (README, docs/, comments)
- [ ] Refactor (no behaviour change)
- [ ] Test (new or improved coverage)
- [ ] Chore (build, CI, tooling, no production code change)

## Capability impact

<!-- Required for any change that touches rules/ fragment text, executors/, or a hook.
     Otherwise write "None". Reviewers will ask if this section is missing on a rule-text PR. -->

- [ ] None
- [ ] Added — describe the new capability
- [ ] Changed — describe what is different for existing users
- [ ] Removed — describe the migration path

Explain: <!-- one short paragraph -->

## Tests

Describe the tests you ran and how to reproduce them locally:

- [ ] `python3 -m unittest discover -s tests` passes on Linux
- [ ] `python3 -m unittest discover -s tests` passes on macOS
- [ ] `test/run.sh` (when Docker and credentials are available)
- [ ] Added new tests under `tests/`

Commands run and their output:

```sh
# paste the command + a couple of result lines
```

## Checklist

- [ ] Tests added or updated for every behaviour change
- [ ] `CHANGELOG.md` updated under `## [Unreleased]` (Added / Changed / Fixed / Removed)
- [ ] No secrets, personal data, personal paths or personal project names were added (gitleaks runs in CI)
- [ ] Documentation updated (`docs/`, `README.md`, `INSTALL.md`, code comments) where behaviour changes
- [ ] Verified to work on Linux and macOS — at minimum the smoke test `python3 bin/podium --help`
- [ ] If a new dependency is required, the PR body includes a sentence asking for explicit maintainer approval (do **not** add it to manifests yourself)
- [ ] If a rule-text change, the PR follows the prose-style rules in `CONTRIBUTING.md` and keeps capability parity with §1.1 of `docs/ARCHITECTURE.md`
