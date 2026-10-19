### Executors: who does what

Objective: **distribute the load across the engines, each in its own lane by capability and cost.** **Anthropic reasons** (the principal; additionally `sonnet` does the scout and the coupled contracts/logic, and `haiku` does the bounded exploration), **the writer executor handles the code volume** (cheapest and largest quota), **the consultant diagnoses, reviews with judgement and contrasts** (ideally a family independent of the principal and the writer executor). The principal decides design/names/signatures/ambiguities, writes the closed brief, launches and reconciles. The verdict of correctness and the plan are NEVER delegated.

**Balance rule: effort ↔ output length.** The more reasoning effort, the shorter the requested output. Effort is chosen by difficulty and consumption. The consultant (scarce quota, reserved for judgement) does not write code in volume; only as a fallback for contracts and coupled logic. A critical task is solved with a better brief (consultant `high` diagnoses or consultant `xhigh` gives the verdict → the principal assembles the closed brief → the writer executor implements it, or `sonnet` if it is a coupled contract/logic).

**Responsibility table (use ONLY these models):**

{{ generated.roster_table }}

{{ generated.roster_excluded }}

When evaluating models, exclude previews without public benchmarks, legacy models with announced retirement, and options that cost several times more for equal capability.

Each engine runs on its own subscription or quota. Plans commonly have BOTH a short rolling window (e.g. 5 h) and a weekly cap: spread the load so neither is exhausted at once. When two roles share one quota (for example an overflow executor and the consultant on the same subscription), every brief sent to one spends the other's quota: keep the shared role to its narrow use and watch that window.
