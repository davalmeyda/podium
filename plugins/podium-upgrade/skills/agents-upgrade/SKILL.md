---
name: agents-upgrade
description: Update the executor CLIs, research the models and subscription plans of every configured provider in depth, compare them with real usage, and propose one integral plan of models and roles for podium.toml that the user approves or iterates as a whole. Run only when explicitly invoked.
disable-model-invocation: true
---

# Agents upgrade

Goal: keep the configured roster on the best available model for each role, with every decision backed by data (capability, cost, plan quota, real usage). Run this workflow only when explicitly invoked. Do not hardcode providers, plans, prices, model IDs or exclusions: read `[[roster]]`, `[[agents]]` and `[roster_notes]` from the active `podium.toml`, and use live research. Roles below (principal, writer executor, consultant, overflow executor, native subagents) are the roster's roles, whatever models fill them.

## Scope (invariant)

- **Only models are touched:** model IDs, efforts/variants, the responsibility table, exclusions, the fallback cascade, minimum CLI versions, and any roster text that says which model does what. **No other rule is touched:** language, hooks, permissions, prohibitions, modules, orchestration and review rules stay exactly as they are.
- **The current rules and the heuristics of this skill are evaluated, not obeyed.** No current model rule (responsibility table, exclusions, cascade, "model X only for task Y") limits the proposal. The principal decides with its own judgment and data; if data contradicts a rule, propose replacing it and give the new text. Following a rule is never a justification for an assignment. Do not add providers on your own initiative; if one looks worthwhile, mention it as a separate suggestion.
- **The principal finishes the whole job, configuration included.** Every correction that follows from the run (the cause of an exhaustion, a default model of an agent or CLI, a model filter) is part of the plan and is applied by the principal in Phase 6, with a backup and verification. Never leave it to the user as a pending task. Ask the user only for what the principal cannot do: pay or enable extra usage, log in, or data only they can see (usage screens, plan usage percentages).
- **Credentials, accounts and the user's own usage are never touched without asking.** Removing a provider or model from orchestration means removing it from the rules, cascade and orchestration agents; never log it out, delete its credential or restrict its interactive use. User-owned CLI configuration (defaults, model filters, recent models, personal agents) changes only with explicit user approval and a backup.
- **Temporary exhaustion is not an evaluation or discard criterion.** A model or plan exhausted today (monthly quota, 5-hour window, rate limit) keeps its row and its weight. Evaluate on capability, cost and structural margin (the orchestration's own consumption, separated from unrelated usage that exhausted it). Use exhaustion only to find the cause and to state what the cascade does meanwhile. If a panel model is exhausted, tell the user and ask whether to wait for the reset or enable extra usage; never close the plan as if its proposal did not exist.
- **Nothing is applied without explicit approval of the complete integral plan.** The user approves or iterates it as a whole; after any change, recalculate the load balance and the cascade of the entire plan before presenting it again.
- Responses to the user are brief and technical: tables and data, no filler, nothing omitted.

## Execution rules

- Anything that can take more than a few seconds (updates, catalogues, executors) runs in the background. While it runs, advance with what does not depend on it, such as writing briefs.
- Use the mechanical steps in `scripts/`, not hand-built commands.
- **Silence until the end:** during Phases 1-4 show no partial results, executor digests or intermediate tables. Speak only for the Phase 0 questions, the active-sessions question (if applicable) and, if something blocks the run, one line naming the blocker. Everything is reported in Phase 5.
- **One question = one topic.** Never two providers or two decisions in one question. Questions of the same moment go in one call; different moments go in separate calls (plans first, then active sessions).
- Run artifacts live in a unique scratch directory. Persistent history lives outside the plugin at `$PODIUM_STATE_DIR/upgrade-history`, else `$XDG_STATE_HOME/podium/upgrade-history`, else `~/.local/state/podium/upgrade-history`.

## Phase 0 - Prepare (principal)

1. Create the scratch directory `agents-upgrade-<YYYYMMDD-HHMM>/` for briefs, digests, proposals and the report.
2. Run `scripts/preflight.sh` (read-only). Its sections are the baseline:
   - `== Installed agents` and `-- Responsibility table (installed rules)`: the **installed reality** (agent files and the responsibility table as actually installed).
   - `== Configured roster`: the desired configuration.
   - `== Latest history report`, `== Active sessions (excluding the OpenCode service)`, `== Versions`, `== Install method`.
   The baseline is installed reality compared against the configured roster. Any drift between them (a rendered file out of sync with `podium.toml`) is reported in Phase 5 and handled in Phase 6.
3. If a history report exists (the script falls back to the legacy folder `~/.claude/skills/agents-upgrade/historial/`), read it: plans the user declared, what was approved or discarded, and preview models left pending review. Never search or read unrelated history.
4. **Plan questions:** one AskUserQuestion call with **one question per provider that has a subscription** in the active configuration. Do not assume plan names, prices or tiers; resolve exact names from live research. If history has previous plans, the first option of each question is "Same as last time (<plan>)".
5. **Real margin:** use the local usage log if the tooling keeps one. Otherwise ask, in the same message and as plain text (not an options question), for the usage screen/percentages of each CLI and of each subscription account: it is the only source of a plan's real percentage. The run continues meanwhile.

## Phase 1 - Update CLIs and catalogues (principal)

1. **Active sessions:** if preflight lists active sessions, make **a separate** AskUserQuestion call, one question per affected CLI: wait for them to finish / skip that CLI's update / update anyway (state that restarting the OpenCode service cuts connected sessions). With no active sessions, ask nothing. If the user skips a CLI, pass `--skip-opencode` or `--skip-claude` to `update-clis.sh`; if they wait, re-run preflight until clear.
2. Run `scripts/update-clis.sh` **in the background** (first with `--dry-run` if any install method is unclear). It updates each CLI with its own install method (npm, brew, native); never mix methods. Capture versions before -> after. If an install method changed, report it instead of mixing.
3. Then run `scripts/catalogs.sh <run-dir>` **in the background**. It prints the model catalogue per provider (`== OpenCode models: <provider>`) and checks each agent (`== Agent check: <agent> (<spec>)`: `answer:` or `FAIL <agent> ...`, never aborting), then lists the model actually recorded (`== Actual model recorded (opencode.db)`). Keep its output in the run directory.
4. Every model in a catalogue and not in the baseline is investigated in Phase 2. While steps 2-3 run, write the Phase 2 briefs.

## Phase 2 - Research (executors in parallel, background, read-only)

### Research vehicles (confirm in every run)

- Choose, from the roster, the executor with the cheapest quota as the main research engine (a writer executor in thinking mode if it has one), and a different-family executor for the second round and as research fallback. Reserve the consultant for judgment.
- **Verify in the trace of every run that the research executor really searched the web** (search tool calls present, sources cited with URLs). An executor that answers without searching is not a research vehicle: discard its output and switch to the fallback. Fallback vehicle: a native subagent that has web search.
- Check the trace for the model actually used, and for a newly tested model, check its variants (a nonexistent variant fails with "Variant unavailable").
- If the roster models change, use the current roster IDs, not the ones this skill happens to mention.

### Units (all at once, in one message)

| # | Unit |
|---|---|
| R1..Rn | One per provider in the roster: its models, every tier (latest version of each) |
| Rp | Plans and quotas of every provider with a subscription |
| L1 | Real token consumption from local logs |

Segment by provider; a model never verifies data about its own family (the second round in Phase 3 uses a different family, or a native subagent if no other option exists; if there is truly no other option, flag it in the report). Do not research providers the user has no subscription or API access to; if they subscribe again, add their unit and plan question.

### Model research brief (R*): template, in English

```
Research task (read-only). Do NOT edit or create any files; investigate and report only.
Do NOT spawn subagents; do all the work directly with your own tools.
NEVER run any git command.

Provider: <PROVIDER>. Our current models: <IDs from baseline>. Today: <date>.
1. Build the COMPLETE list of models this provider released from <oldest current model> up to today
   (all tiers/sizes, GA and preview, API and subscription-only). Do not search for specific names:
   search the official changelog/release notes/model docs AND independent trackers, and cross-check
   them. Include models announced but not yet available, marked as such.
2. For EVERY model in that list (plus our current ones) collect:
   - release date, status (GA / preview / deprecated), exact API/CLI model ID
   - context window, max output, modalities, reasoning/effort modes
   - price per 1M tokens: input / output / cache read (and cache write if billed)
   - speed: output tokens/s and TTFT (Artificial Analysis, OpenRouter or similar)
   - benchmarks, each value with source and date. Prefer benchmarks reported for many models
     (comparable across providers): SWE-bench Verified and Pro, Terminal-Bench, LiveCodeBench,
     Aider Polyglot, GPQA Diamond, Humanity's Last Exam, tau-bench / tau2, long-context (MRCR, RULER or
     similar), Artificial Analysis Intelligence Index, LMArena, plus any other widely cited one.
   - known weaknesses (verbosity/token usage, hallucination, tool-call reliability), with source.
3. Persistence: for every missing value try at least 3 different queries and 2 independent sources
   before giving up. If still missing write "NOT FOUND" plus the queries tried. Never write "unknown"
   without that.
4. When sources conflict give every value with its source; do not average them.

Output (Markdown only, no prose intro):
- Table 1: model list (ID, date, status, context, price in/out/cache, speed).
- Table 2: benchmarks (rows = models, columns = benchmarks, cells = value [source#]).
- Notes: weaknesses, conflicts, NOT FOUND items.
- Numbered source list with URL and publication date.
```

### Plan brief (Rp): points to cover

For each provider, for **the user's plan and the plan immediately above and immediately below it**: monthly price, limits per 5-hour window and per week, how each model consumes inside the plan (multiplier or relative weight), what that equals in tokens or messages by the most recent source (official first, then community measurements, all dated), maximum concurrency, and recent limit changes. Also **the plan's dollar value**: recent studies and measurements of how much API-priced usage each plan covers, with model used, date and source. Same persistence floor (3 queries, 2 independent sources) and same conflicting-source rule as the model briefs. Do not infer the user's actual usage from plan descriptions.

### Real consumption brief (L1): points to cover

A local, read-only script (run with isolated Python, e.g. `python3 -I`, saved in the run directory so it can be re-run) that reads the session logs and usage databases of every configured CLI. **First inspect the real format of each source** before parsing; handle fields that are recorded as zero (for example reasoning tokens counted separately) by reading them from their own record type. Return, **for the last 30 days, per model and per day**: input tokens, output tokens, cache read and cache write tokens, and the **peak per rolling 5-hour window** and per week. Distinguish orchestration usage from unrelated personal use by origin. Return only the summary tables, never raw logs; **the final answer must include the tables** (not just a description of the script). State limitations rather than inventing data.

## Phase 3 - Compare with one criterion and close gaps (principal)

**Mandatory comparison round** (not only when there are gaps). For the candidates of each role (current ones and alternatives from all families, including native subagents), launch:

- G1: Artificial Analysis index of the current version **at the effort levels actually used (not only the maximum)**, with cost per task, tokens used and speed at each level.
- G2: coding benchmarks with the **same harness** for all (Terminal-Bench from the AA or tbench.ai leaderboards, DeepSWE, FrontierCode, Vals Index, AA Coding Agent Index), plus evaluations on specified tasks (for example framework agent evals), which resemble closed-brief use.
- G3: whatever is missing from the provider of the executor that researched it (cross-check).

No model verifies the data of its own family; if there is no alternative, mark it in the report. Then check that every model has every field and that every datum has source and date. Every gap or important contradiction goes to a **directed second round**, with a brief containing only the gaps, run by a different-family executor than the first pass. Accept "NOT FOUND" only when the second round also fails, stating what was searched. **Do not enter Phase 4 with missing data that would change a decision.**

## Phase 4 - Analysis and decision (principal)

1. **Single ranking across providers** (native subagents included), by capability on each axis the roles use (closed-brief coding, diagnosis/reasoning, judgment/architecture, long context, tool use) and by cost.
2. **Dollar value of each plan:** real 30-day consumption (L1) x the API price of each model, **category by category** (input, output, cache read, cache write) = dollar equivalent of each subscription's usage. Compare it with the plan price and with the Rp value studies. From that compute the **marginal cost of moving a role** to each subscription (estimated role volume x destination model price) and **what fraction of the plan's value** it represents.
3. **Real margin of each plan:** the plan percentages the user supplied (or the local usage log) against L1 consumption. Without that data, say so explicitly and show how the decision would change.
4. **Assignment by margin** (cross each model's weight inside its plan with the user's real consumption):
   - If a provider has spare margin, its cheaper models may take roles of external engines when they perform equally or better. Margin does not make consumption irrelevant: among candidates that meet the capability the role needs, the lowest-consumption one wins; a more expensive one enters only if its capability advantage is necessary, justified with numbers.
   - If a provider is at its limit, every token of its cheaper models takes quota from its stronger ones: keep the load on the other subscriptions.
   - The same for every subscription: never assign load a plan cannot sustain.
5. **Role-by-role evaluation:** for each row of the responsibility table, the current model against the best candidate of each family, with capability (G1/G2), marginal cost and margin. All models are candidates for all rows; none is discarded by the role the current rule gives it. For each row, first fix the minimum capability the role needs, then choose the cheapest candidate that meets it.
6. **Starting heuristics (questionable, not fixed):** apply them unless data shows something better; **breaking one requires naming the heuristic and the numbers that justify it**.
   - Aliased models (always pointing to the latest version) are researched for the ranking, but their IDs need no change.
   - Always use the newest version of each tier; the most expensive tier stays excluded unless data shows an advantage that justifies the cost.
   - A preview model does not enter a main role; note it for later review.
   - "Higher reasoning, shorter output": a high-reasoning model is never assigned to write code in volume.
7. **Build ONE integral plan, not loose proposals.** The principal decides; the user is never asked to choose between options or approve pieces separately. The plan is the complete responsibility table (every row, with its cascade) designed as a whole:
   - **Load balance per subscription:** per plan, which roles are loaded there (principal and fallbacks) and the estimated consumption before -> after. No subscription may end with more load than its margin supports; the tightest plan receives no new roles if another with margin performs similarly.
   - **Cause before symptom:** if a plan was exhausted, determine what exhausted it (L1 by origin: orchestration or the user's own use) before removing roles. If the cause is unrelated to orchestration, fix the cause and keep the role.
   - **The cascade absorbs peaks:** if a plan exceeds its cap only at peaks, the cascade to a plan with margin already solves it; **recommend a higher plan only when the AVERAGE volume does not fit**, never for a peak.
   - **Cascade coherence:** in every row, the fallback **can never share a quota with the engine it backs up nor with the principal** (if one falls, the other falls), cannot be more expensive without gaining needed capability, and must prefer subscriptions with margin. Review all rows, not only those that change.
   - **Precomputed contingencies:** for every missing datum (for example real margin), state which row changes and to what, depending on how the datum turns out. The principal does not hand the decision to the user.
8. **Panel of independent proposals.** All **strong-opinion models in the current roster** take part (those of the second-opinion and verdict rows, **including the verdict fallback** as a separate consultation without the principal's context). Each builds **its own integral plan** from the full research; none evaluates the principal's.
   - **The principal's proposal first and blind:** write the step-7 plan to `proposal-principal.md` in the run directory BEFORE reading any panel proposal, and do NOT send it in round 1.
   - **Round-1 brief (identical for all):** data and rules of the game only, no conclusions or leading questions. Data: paths to ALL run reports (Rp, L1, G1-G3, R*, catalogues, preflight baseline, user-supplied usage data saved to file), with the order to read them completely; never a summary built by the principal. Context: paths to the current model rules (what is being evaluated) and to this skill (Scope and Phase 4, steps 1-7). Rules of the game: model-only scope; current rules do not restrict; minimum capability per role, then the cheapest; load balance per subscription; row-by-row cascade coherence; cause before symptom; no new providers; no preview in a main role without data. Fixed deliverable: complete table (responsibility | model | effort | fallbacks | why, with numbers and source), exclusions, before -> after balance per subscription, contingencies, replacement rule texts, and **the data the participant lacks** to decide better.
   - **Round 2 (contrast, if proposals differ):** send each participant the others' proposals (the principal's included) and ask, row by row where they differ, to defend or revise with data and to point out data or reasoning errors in the others. Iterate while new arguments with data appear (maximum 3 rounds).
   - **Missing data:** if a proposal depends on data nobody has, launch a directed investigation (Phase 3 rules) before deciding.
   - **Controls:** every participant runs at **high effort**, whatever its roster row says. **Only effort changes, never the model** (never swap a model for a stronger tier). Launch all at once, in the background, read-only, with read access to the run directory. **If one is unavailable (quota, error) it is not replaced by another model: record that it was missing**, and handle quota exhaustion as the Scope rule says (ask wait or extra usage).
   - **Synthesis by the principal:** compare all proposals row by row and build the final plan with the principal's judgment weighted most, but every row where it departs from the majority or from an argument backed by data carries the explicit reason. The final decision is the principal's.
9. **Check before the report** (everything must be "yes"; otherwise go back to the missing phase): CLIs updated and catalogues read; new models of every provider with date and status; AA index at the real effort of each candidate and same-harness benchmarks; specified-task evaluations; real consumption (L1) with tables; dollar value of each plan and marginal cost of each change; real margin (or its declared absence and impact); every role evaluated with all families as candidates; before -> after balance with no overloaded subscription; cascade coherent in all rows; contingencies for each missing datum; principal's proposal written before reading the panel's; independent proposals of every strong model at `high` from the full reports; contrast rounds until arguments are exhausted; data gaps investigated.

## Phase 5 - Report and approval

1. **The report goes in the chat**, in one final message; do not create a separate report file for the user. **Brief, but with all the information needed to understand each decision.** Do not number proposals ("P1, P2"): present **one plan**. Structure:
   1. **Update** (1 line): versions before -> after, install-method notes, baseline drift, new models in catalogues.
   2. **New models** (1 line per provider): what was released and whether it affects the IDs.
   3. **Capability** (short table): candidates with the same index and harness, at the efforts actually used, and cost per task.
   4. **Proposed plan** (ONE table with every row of the responsibility table): responsibility | today | proposed | if unavailable | why (key numbers, only on rows that change). Unchanged rows carry "=". Below it, the resulting exclusions.
   5. **Balance per subscription** (table): plan | dollar value of real usage | peak vs limit | roles before -> after | estimated load before -> after.
   6. **Contingencies** (1 line each): "if `<datum>` is X, row Y becomes Z".
   7. **Discarded** (1 line each, with the reason in numbers).
   8. **Panel** (row-by-row table: the proposal of every model and of the principal, and the final choice with the reason where they differ; then 1 line per model with what it changed during the rounds; **state every participant that was unavailable**).
   9. **Outside the rules** (1 line each: plan, usage habits).
   Exact rule texts, full tables and sources are given only if the user asks (the run digests have everything).
2. End with an **open question in plain text** (not AskUserQuestion): apply the plan, or what to adjust or research. Without explicit approval nothing is applied.

## Phase 6 - Apply (only with the approved plan)

1. Edit **only the active `podium.toml`**, and only model, effort/variant, role, exclusion, cascade and minimum-CLI-version fields. Before editing, create a sibling backup named `podium.toml.bak-podium-<YYYYMMDD-HHMMSS>-<4hex>`.
2. Run `podium install --dry-run`, show the resulting plan, and ask the user to approve it. If approved, run `podium install`. Never edit `CLAUDE.md`, agent files or any other rendered file by hand: podium renders them. If a model changes version or ID, update **every** place it appears in `podium.toml` (roster, agents, invocation specs, variants, notes), not only the table: no CLI guarantees using the new version by itself, and OpenCode ignores an agent's `model:` and uses each command's `-m`. Confirm the new ID and its effort variants in the catalogue before fixing it.
3. **User-owned CLI configuration** that the run's findings require changing (defaults, model filters, personal agents) is changed by the principal only with the user's explicit approval for that specific change and a prior timestamped backup; then verified like the rest.
4. **Verify at runtime** (the pre-change catalogue check does not prove the new assignments run):
   - Re-run `scripts/catalogs.sh <run-dir>` and confirm every new ID and variant is valid in the catalogue.
   - Search the installed files (agent files, installed rules, `podium.toml`) for the replaced IDs: none may remain, except those moved to the exclusion list.
   - Run a minimal invocation (one trivial query) of each executor that changed and prove the **actual** model: the trace and the `== Actual model recorded (opencode.db)` lines of the check (`<agent> -> <model id>#<variant>`), not the agent file.
   - If the trace or database still shows the old model after an agent was edited, restart the OpenCode service (it runs in the background and can keep the old configuration cached), then repeat the invocation.
5. Write the final report and what was approved or adjusted to `$PODIUM_STATE_DIR/upgrade-history/<YYYY-MM-DD>.md` (XDG and home fallbacks as above), **appending** to that date's file if it exists; never write run history inside the plugin. This file is only the baseline for the next run; do not offer it to the user as a way to read the report. The scratch directory disappears with the session, so the history is the next run's baseline. **Upgrade results are not saved in shared memory** unless the user explicitly asks.
