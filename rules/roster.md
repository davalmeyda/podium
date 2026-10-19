### Executors: who does what

Objective: **distribute the load across the engines, each in its own lane by capability and cost.** **Anthropic reasons** (the principal; additionally `sonnet` does the scout and the coupled contracts/logic, and `haiku` does the bounded exploration), **the writer executor handles the code volume** (cheapest and largest quota), **the consultant (via OpenCode) diagnoses, reviews with judgement and contrasts** (a family independent of the principal and the writer executor). The principal decides design/names/signatures/ambiguities, writes the closed brief, launches and reconciles. The verdict of correctness and the plan are NEVER delegated.

**Balance rule: effort ↔ output length.** The more reasoning effort, the shorter the requested output. Effort is chosen by difficulty and consumption. The consultant (scarce quota, reserved for judgement) does not write code in volume; only as a fallback for contracts and coupled logic. A critical task is solved with a better brief (consultant `high` diagnoses or consultant `xhigh` gives the verdict → the principal assembles the closed brief → the writer executor implements it, or `sonnet` if it is a coupled contract/logic).

**Responsibility table (use ONLY these models):**

{{ generated.roster_table }}

Models deliberately excluded from the roster (and why):

{{ generated.roster_excluded }}

When evaluating models, exclude previews without public benchmarks, legacy models with announced retirement, and options that cost several times more for equal capability.

There is no fixed third opinion: no third family with enough capability remains. The writer executor's measured independent benchmark score and hallucination rate are too low/high to act as a third arbiter (in the reference setup: index score 29, 18.4% hallucination).

**1) Writer executor via OpenCode** (agent defined in `~/.config/opencode/agents/`, with a token plan). Each engine runs on its own subscription or quota; executor plans commonly have BOTH a short rolling window (e.g. 5 h) and a weekly cap — spread load so neither is exhausted at once. Two modes via the model variant — in the rest of this document, "writer-fast" = fast mode and "writer (thinking)" = thinking mode:
- **Fast mode** (`#none`): the operational default — closed briefs, decided implementation, mechanical refactors, running and fixing validations, checklist reviews, verbose outputs (builds, suites, logs, seeds), code with context >100K.
- **Thinking mode** (`#thinking`, same per-token cost): long-context >100K repo/flow reading (entire modules, huge logs in one pass) and scout fallback.
- **The variant is ALWAYS explicit:** without `#`, the behaviour changed between OpenCode versions (it reasoned in 63% of messages in Jul–Sep; in v2.0.25 in 0 of 8 runs). `#none` never reasoned (0/340) and `#thinking` always reasons in v2.0.25 (8/8). `#high` does not exist on the writer executor.
- **Invocation** via `Bash`: `cd <dir> && {{ launcher.opencode }} --agent <writer> -m "<provider>/<model>#<none|thinking>" "$(cat <brief>.txt)" </dev/null > <digest>.txt 2> <trace>.txt`. **stdout carries ONLY the final answer** (the digest, the only thing the principal reads) and **stderr the activity trace** (only consulted to debug a failed executor). **NEVER `2>&1`**: it would mix the trace into the digest. Both files go to the scratchpad. Verify in the trace `> <writer-agent> · <writer-model>`.
- **Web search:** through OpenCode it really works. A vehicle that returned invented results and reported them as valid is gone: do not use it again.
- **`-m` is MANDATORY:** OpenCode v2 ignores the agent's `model:` and falls back silently to another model. If in doubt, verify the real model (trace or `opencode.db`).
- The writer-executor agent carries a copy of the executor profile (master profile: `podium/executors/profile/`; re-sync it if it changes) and blocks skills, memory MCP, other MCPs (except `codegraph`), subagents and `git *` (the global `AGENTS.md` would force the memory flow on every run).
- OpenCode runs as a background service: a new or edited agent in `~/.config/opencode/agents/` may not be visible until the service restarts.

**2) Consultant and overflow executor via OpenCode** (consultant = judgement, overflow = mechanical code). Each with its own agent, model and fixed effort — no internal backup among engines of the same family: if the quota drops, the cascade falls through to the engine indicated in the table. Three uses:
- **Consultant `high`** — diagnosis (non-obvious bugs, root cause), review with judgement and second opinion. Read-only, output = short analysis. If diagnosis and second opinion target the same problem, they go in a single consultation.
- **Consultant `xhigh`** — verdict on high-risk architecture/plan decisions. Read-only, concrete question, output = verdict and alternatives, no code.
- **Overflow executor `high`** — mechanical code overflow: when a phase launches many executors in parallel, the 2–3 most mechanical briefs (renames, imports, fixing type/lint errors following a given pattern) go to the overflow executor so the writer executor's quota is not burned all at once. In normal tasks (1–3 agents) all closed-brief code goes to the writer executor. The overflow executor writes mechanical code only, never diagnosis.
- **Invocation** via `Bash` (ALWAYS with agent, `-m` and effort variant explicit): consultant → `cd <dir> && {{ launcher.opencode }} --agent <consultant> -m "<provider>/<model>#<high|xhigh>" "$(cat <brief>.txt)" </dev/null > <digest>.txt 2> <trace>.txt`; overflow executor → `cd <dir> && {{ launcher.opencode }} --agent <overflow> -m "<provider>/<model>#high" "$(cat <brief>.txt)" </dev/null > <digest>.txt 2> <trace>.txt`. Same stdout/stderr rule as the writer executor (NEVER `2>&1`).
- **Agents** (`~/.config/opencode/agents/<consultant>.md` and `<overflow>.md`, with the same executor profile as the writer): the consultant is **read-only enforced by permissions** (no editing, shell limited to `ls`/`cat`/`grep`/`rg`/`find`/`head`/`tail`/`wc`/`sed -n`, no `git`, no subagents); the overflow executor edits, no `git`. A non-existent variant returns "Variant unavailable".

**3) Native Claude subagents** (the `Agent` tool, with explicit `model` and `effort` per the table): `sonnet` `high` for the scout and coupled contracts/logic, and as fallback for diagnosis, review and second opinion; `opus` `high` only as fallback for architecture verdicts (separate consultation); `haiku` (default effort) for bounded exploration and as fallback for code and verbose outputs; `sonnet` as last-resort fallback by capability. Claude-native subagents share the principal's quota: if it runs out, the principal stops too.

**Fallback cascade:**

{{ generated.fallback_cascade }}

On a quota/billing/rate-limit error, move to the engine indicated in the "If unavailable" column of the table, on the first failure, without retrying on the failed one. Failure is detected from the CLI output (quota/rate-limit/billing messages, 429, or error exit code with no work done); a task failure in itself (red tests, brief not followed) does NOT trigger the cascade — that is resolved at reconciliation.

**Conflict between harness mode and cascade: ask, do not assume.** When a system mode suggests native subagents (e.g. Plan mode: "use Explore/Plan") and the cascade indicates the writer executor (OpenCode), the principal does NOT decide alone: asks the user (AskUserQuestion) which channel to use — (a) the harness's official routing (native Explore/Plan, Anthropic quota) or (b) the external-engine cascade (writer executor / consultant via OpenCode per the table). The answer stands for the rest of that task unless the user says otherwise; it is not re-asked on every delegation. If the user chooses the cascade while in Plan mode, every brief is marked read-only — "Do NOT edit or create any files; investigate and report only" — to preserve the mode's guarantee (nothing is modified while planning). The mode's own tools (EnterPlanMode/ExitPlanMode, AskUserQuestion) are used normally: they are harness mechanics, not executors.

**Launch mechanics (applies to EVERY OpenCode executor — writer executor, consultant and overflow executor —, without exception):**

{{ generated.launch_examples }}

- **The brief is ALWAYS written with the agent's file-writing tool (Write), never via shell.** Every brief is written to a scratchpad file and injected with `"$(cat <brief>.txt)"` — `$(...)` output is not re-parsed by the shell, so backticks and metacharacters (for example `` `any` `` or `new Date()`) stay literal and are not executed. Briefs are NEVER inline, not even when they are short or simple: inline briefs pass through the shell, and shell inline interprets backticks and metacharacters as commands. The scratchpad file is the auditable artefact of the brief, and it is reused **unchanged** on fallback so the next executor sees the same instructions.
- **NEVER `&` inside the command:** parallelism is given exclusively by `run_in_background: true` of the Bash tool. Combining both duplicates the backgrounding: the harness tracks a launcher that dies instantly and the real process becomes an orphan, without follow-up or termination notification.

**Mandatory prohibitions in EVERY brief (verbatim, not paraphrased):**

The **capability** is forbidden, not just the object. Saying "do not touch folder X" is insufficient: for the one who runs `git checkout -- X`, that does not feel like touching a file, it feels like undoing. An agent that made a mistake resorts to git naturally and destroys the work of others.

- **NEVER run any git command.** Not `checkout`, not `restore`, not `stash`, not `reset`, not `revert`, not `clean`. Not even to undo something you got wrong. If you made a mistake, fix it by editing the file forward.
- **NEVER regenerate generated artifacts** (API clients, schema types, migrations, codegen). Regenerating them while other agents work leaves the rest compiling against a contract different from the one the principal believes in.
- **NEVER install or uninstall dependencies**, and do not modify `package.json` / lockfile / `pnpm-workspace.yaml`. If you think a dependency is needed, stop and report it.
- **NEVER start servers or run builds.**
- **Touch only the files in your scope.** Other agents are editing other folders of the same package right now.
