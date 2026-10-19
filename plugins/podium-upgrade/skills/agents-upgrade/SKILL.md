---
name: agents-upgrade
description: Research and propose a complete update to the models and roles configured in podium.toml.
disable-model-invocation: true
---

# Agents upgrade

Run this workflow only when explicitly invoked. Its purpose is to keep the user's configured model roster fit for its responsibilities, based on current evidence and actual usage. Do not hardcode providers, plans, prices, model IDs, or provider exclusions: read `[[roster]]`, `[[agents]]`, and `[roster_notes]` from the active `podium.toml`, and use live research. Never read personal history other than the upgrade-history baseline described below.

## Invariants

- Preserve the entire workflow below; do not silently skip research or decision steps.
- The current configuration is evidence to evaluate, not a constraint on the recommendation. Do not add providers without asking.
- Do not change credentials, accounts, subscriptions, or user-owned CLI configuration.
- Nothing is applied without explicit approval of the complete integral plan. The user may iterate; recalculate its balance and fallbacks before presenting it again.
- Keep user-facing responses concise and evidence-based. During phases 1–4, do not present partial results; report only blockers.
- Use a scratch directory for run artifacts. Keep persistent history outside the plugin at `$PODIUM_STATE_DIR/upgrade-history`, else `$XDG_STATE_HOME/podium/upgrade-history`, else `~/.local/state/podium/upgrade-history`.

## Phase 0 — Prepare

1. Create a unique scratch directory for briefs, research, comparison, proposals, and the report.
2. Run `scripts/preflight.sh`. Its JSON roster is the baseline. Inspect the latest history file it reports, if any, as context for the previous run; never search or read unrelated history.
3. Ask one question per provider/plan represented in the active configuration, requesting plan details only where relevant. Ask separately for user-only usage data that cannot be observed locally. Do not assume plan names, prices, or tiers.

## Phase 1 — Update CLIs and inspect catalogs

1. If preflight finds active OpenCode processes, ask whether to wait, skip that CLI update, or proceed. Explain that restarting its service may interrupt sessions.
2. Run `scripts/update-clis.sh` in the background, using the skip options chosen by the user. It detects each installation method and updates via that same method. Never mix installation methods.
3. Run `scripts/catalogs.sh` in the background. It lists provider catalogs inferred from configured OpenCode roster entries and sends a minimal check to each configured agent.
4. Investigate newly catalogued models in Phase 2. Draft research briefs while these commands run.

## Phase 2 — Parallel research

Use parallel, read-only research briefs; save each full result and its sources in the scratch directory. Use currently configured providers and models as the starting set, but investigate alternatives found in live catalogues and research. Do not rely on this skill as a source of current provider facts.

For each candidate, verify release date and status, exact usable model ID, context/output limits, modalities, reasoning modes, pricing where applicable, speed, representative comparable benchmarks, and known weaknesses. Cite source URLs and dates; cross-check official documentation and independent sources. Report conflicting values separately. For missing decision-relevant information, make multiple targeted attempts across independent sources and record what was searched.

Research plan limits and subscription value only for plans the user says they have or asks to compare: limits, model weighting, concurrency, recent changes, and measured API-equivalent value with dates and sources. Do not infer the user's actual usage from plan descriptions.

Measure local usage only from available, relevant sources with a read-only analysis; distinguish orchestration usage from unrelated personal use. Do not expose raw logs. Summarize per model and period, with token categories and peaks where the data supports them. State limitations rather than inventing data.

## Phase 3 — Compare and close evidence gaps

Compare candidates using equivalent effort levels and shared benchmark harnesses where available, plus task-relevant coding/agent evaluations. Include all model families already configured. Do not let a model verify its own provider's claims when another independent source is available. Review every decision-relevant field for source/date, contradictions, and gaps. Direct a second research pass at gaps that could change a decision; do not proceed to a final recommendation with unresolved material gaps.

## Phase 4 — Decide

Rank candidates against the capabilities each configured role actually requires, then choose the least costly candidate that meets the minimum. Compare actual usage and available quota/margins when supplied; distinguish structural limits from temporary exhaustion and unrelated use. Evaluate every role, all fallbacks, and the load balance across configured plans. Fallbacks must not share the same failure domain unnecessarily and must offer a useful capability/cost tradeoff.

Build one complete integral proposal covering every roster responsibility, model, effort/variant, fallback, and roster note. Include before/after load, evidence, contingencies for missing user-only facts, and exact configuration changes. Do not offer disconnected alternatives.

Before reading independent proposals, write the principal's complete proposal to the scratch directory. Then ask all available independent strong-opinion models in the current configuration to make their own complete proposals from the full research, without seeing the principal's proposal. Request row-by-row plans, reasons/sources, load balance, contingencies, and missing facts. If proposals differ, share them for a data-based contrast (up to three rounds while new arguments arise). Investigate any unresolved decision-changing fact. Synthesize the final plan, explaining departures from evidence-backed majority arguments.

## Phase 5 — Report and approval

Present one concise report in the conversation: CLI changes/catalogue discoveries; material research and comparison; one complete before/proposed/fallback plan; resulting exclusions/notes; load balance; contingencies; discarded candidates with reasons; and independent panel conclusions. Cite evidence sufficiently to support each decision. End by asking in plain text whether to apply this entire plan or what to adjust/research. Do not apply until explicit approval.

## Phase 6 — Apply only after approval

1. Edit **only the active `podium.toml`**. Before editing, create a sibling backup named `podium.toml.bak-podium-<YYYYMMDD-HHMMSS>-<4hex>`.
2. Run `podium install --dry-run`, show the resulting plan, and ask the user to approve that install plan. If approved, run `podium install`.
3. Never edit `CLAUDE.md`, agent files, or any other rendered/generated files. podium owns rendering those from configuration.
4. Write the final report and what was approved/adjusted to `$PODIUM_STATE_DIR/upgrade-history/<YYYY-MM-DD>.md`, using the XDG and home fallbacks above. Append to that date's file if it already exists. Never write run history inside the plugin.
