**Native Claude subagents** (the `Agent` tool, with explicit `model` and `effort` per the table): `sonnet` `high` for the scout and coupled contracts/logic, and as fallback for diagnosis, review and second opinion; `opus` `high` only as fallback for architecture verdicts (separate consultation); `haiku` (default effort) for bounded exploration and as fallback for code and verbose outputs; `sonnet` as last-resort fallback by capability. Claude-native subagents share the principal's quota: if it runs out, the principal stops too.

**Fallback cascade:**

{{ generated.fallback_cascade }}

On a quota/billing/rate-limit error, move to the engine indicated in the "If unavailable" column of the table, on the first failure, without retrying on the failed one. Failure is detected from the CLI output (quota/rate-limit/billing messages, 429, or error exit code with no work done); a task failure in itself (red tests, brief not followed) does NOT trigger the cascade — that is resolved at reconciliation.

**Mandatory prohibitions in EVERY brief (verbatim, not paraphrased):**

The **capability** is forbidden, not just the object. Saying "do not touch folder X" is insufficient: for the one who runs `git checkout -- X`, that does not feel like touching a file, it feels like undoing. An agent that made a mistake resorts to git naturally and destroys the work of others.

- **NEVER run any git command.** Not `checkout`, not `restore`, not `stash`, not `reset`, not `revert`, not `clean`. Not even to undo something you got wrong. If you made a mistake, fix it by editing the file forward.
- **NEVER regenerate generated artifacts** (API clients, schema types, migrations, codegen). Regenerating them while other agents work leaves the rest compiling against a contract different from the one the principal believes in.
- **NEVER install or uninstall dependencies**, and do not modify dependency manifests, lockfiles or workspace files (`package.json`, `pnpm-workspace.yaml`, `pyproject.toml`, `go.mod`, …). If you think a dependency is needed, stop and report it.
- **NEVER start servers or run builds.**
- **Touch only the files in your scope.** Other agents are editing other folders of the same package right now.
