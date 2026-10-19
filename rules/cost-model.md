### Consumption and time: criterion to distribute (applies to EVERY executor, of any engine)

It holds for what is deployed through OpenCode (writer executor, overflow executor, consultant) and for native subagents (`sonnet`, `haiku`, `opus`). These are not caps: they are the cost model and the errors already seen, so the principal decides with its own criterion the optimal split in each case.

**Goal of any split: the smallest total time with the smallest consumption**, without sacrificing one entirely for the other. The cost model:
- An executor's consumption ≈ **steps × accumulated context**: each step re-sends all its context (it is billed as cache, and the writer executor's plan counts it inside the quota).
- What an agent reads or prints it pays in every subsequent step → one long agent costs much more than several short ones with small contexts.
- Each new agent pays a start-up cost (brief + reading of its zone) → splitting more also costs.
- A phase's time is its slowest executor's; more agents in parallel only help while there is independent work and quota available. Each engine runs on its own subscription or quota; executor plans commonly have BOTH a short rolling window (e.g. 5 h) and a weekly cap — spread load so neither is exhausted at once.

**The number of agents is decided by the principal** with this cost model, and is justified in one line before launching. If the user gives a scale ("launch 50"), it is a criterion to evaluate, not a blind order: it is applied if it pays off; if it does not, it is said and the useful scale is proposed with the reason.

**Distribution unit = one independent zone** (function, component, section). The unit is a zone, not the file: independent zones go in parallel even if they share a file, with the brief limiting the edit to its zone and forbidding rewriting or reformatting the whole file (the joint `tsc` is run by the principal). The sequential requires a real and written dependency. See principal-decides for the precise rule.

**Measured anti-patterns (measured in a real setup (Oct 2026, 11 executor sessions): ~146M of cache vs. 0.42M of output, 141 steps on average, context of 8K to 160K):**
1. One executor with many fixes in different zones (a backend-repo and frontend-repo run: 255 steps, ~25M of cache).
2. Review, fix and re-review in the same agent: the reviewer's context (screenshots, Figma) is resent on every code step.
3. Visual QA by trial and error inside the executor (`sleep` + screenshot + retry: 112 of 162 commands in one session).
4. "Do it like Figma" without values: that is not a closed brief; it forces interpretation and iteration.
5. Serialising independent work "just in case": it loses time without saving consumption.

**Visual work / QA (Figma, layout, responsive): separated roles that communicate through files, never nested.**
- **Review** (read-only, in parallel by section and covering the sizes requested): measure before looking — values with `getComputedStyle` and DOM boxes; capture only what is not measurable. Delivers findings in fixed format: file, element, screen size, expected vs actual, severity. Does not correct.
- If the user asked to see the list first, the principal consolidates it and waits for approval.
- **Code:** briefs with the concrete values from the findings; no browser or Figma.
- **Verification:** a new agent re-measures only what was corrected, once, and returns PASS/FAIL.
- Each zone advances on its own (review → code → verification) without waiting for the global phase to end; verifying one zone while another is edited is allowed if they do not touch each other.
- Model: review and verification with the writer executor (measuring via DOM does not require reading images); escalate to `sonnet` only the specific case that demands visual judgement without a measurable value.

**Stuck signal:** an executor that drifts far from the expected deliverable turns in the partial and reports; the principal decides whether to split the work or close the brief better. It is not left to retry.

**Native subagents (Agent tool):** they do not load the OpenCode executor profile, so their brief includes those rules in 3–4 lines: CodeGraph before grep/read (with `projectPath`), filtered outputs and reading by range, exact scope (what is outside is reported), no browser except for review/verification, and stop-and-report if stuck.
