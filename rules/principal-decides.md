### The principal decides, the agents execute

Decisions (design, approach, names, signatures, types, ambiguities, choice between options) are fixed in the brief. The operational work is the executor's, including the "mechanical thinking": locating the change point, running `tsc`/lint and interpreting the output, fixing its own errors until the done criterion is met.

**Balance brief vs. direct work:**
- If writing the precise brief costs equal to or more than doing the work, the principal does it directly.
- If the task produces verbose output (broad searches, logs, suites, actions against APIs/seeds), it is delegated even if simple: the output is burned in the executor's context and only the conclusion returns to the principal. A chain of dependent steps lives inside ONE executor.
- The brief is self-sufficient in *decisions*, not a step-by-step: paths to touch, decisions taken (names, signatures, patterns with repository examples), the convention already applied to the case, and a verifiable done criterion. A brief that forces the agent to *decide* is badly written.
- **Brief cost scales with scope:** for a small unit 4–6 lines are enough (files, decisions, done criterion). Having to write many small briefs is NEVER a reason to fuse them into one large one.

**Mandatory self-validation:** every executor that writes code runs `tsc --noEmit`/lint over its scope and fixes its errors before returning. Reconciliation receives finished work. **Concurrency exception:** if several executors work at the same time on the SAME package, a project-wide `tsc --noEmit` would see other people's half-written files (false errors, cross-fixes); in that case each executor validates only its own files (lint/syntax) and the full `tsc --noEmit` is run by the principal —or by a single executor— at phase reconciliation.

**Brief language:** in **English** with `{{ language.domain_name }}` literals quoted verbatim, and every brief includes: "All UI text, error messages, domain identifiers and code comments MUST be in {{ language.domain_name }}, exactly as quoted." Answers to the user are in **{{ language.response_name }}**.

**No nested orchestration:** executors are terminal. EVERY brief includes: "Do NOT spawn subagents; do all the work directly with your own tools."

**Parallelisation unit = the independent zone** (function, component, section). The unit is an independent zone, not the file: independent zones may share a file only when the brief restricts edits to the zone and forbids reformatting the whole file (see cost-model). Changes tightly coupled in one file stay in ONE executor (two on one file = collision). If B depends on A's API, before unifying, evaluate closing the contract of the frontier (see "Parallelisation by contract"): if you can and both sides are disjoint, they go in parallel; if not, they live in one executor or are split across phases. This criterion applies only to SIMULTANEOUS agents: distinct phases may touch the same files without restriction.

**Granularity: when in doubt, split finer.** One executor = one verifiable unit of work (one module, one endpoint with its DTO, one entity, one screen), NOT one layer. **PROHIBITED anti-pattern: "one agent for the backend and another for the frontend"** when within each side there exist disjoint file sets: the split is by unit of work, and inside the backend (or the front) 3–6 parallelisable units typically coexist. **Critical path:** phase time equals the slowest executor; when planning, estimate the heaviest brief and, if it is projected to be much longer than its siblings (3–4×), split it. In wide phases, also split the queue between the writer executor and the overflow executor by *throughput*, not just by quota.
