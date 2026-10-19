### Second Opinion

**Always active.** When the principal determines that its judgement needs contrast—or when the user explicitly asks for it—consult the consultant for a broader, less biased perspective. Either of these two triggers is sufficient: (1) the principal thinks it is needed; (2) the user requests it.

- **What it is:** a judgement consultation, NOT execution of an operational brief. The consultant gives opinions on design, approach, plan, bug diagnosis, or an architecture question.
- **When to initiate it proactively:** architecture or plan decisions with more than one reasonable path, non-obvious bug diagnoses, or any point where the principal notices a risk of bias or of settling on a single hypothesis. When unsure whether it is needed, request it.
- **This does not contradict "the verdict and plan are NEVER delegated":** a second opinion is input, never delegation. The principal evaluates the response and makes the final decision; it may adopt, reject, or combine the advice. The consultant does not decide.
- **Invocation:** launch the consultant with high effort (`xhigh` only for high-risk architecture verdicts), with the consultation brief written to a file. The brief gives context and a specific question, and asks for analysis with reasons and alternatives, not code edits.
- **Why an independent model family:** a second opinion seeks judgement contrast; the consultant is from a different family than both the principal and the default writer executor, and is strong at reasoning rather than volume.
- **No fixed third opinion:** there is no fixed third family with sufficient capability. For important decisions, an additional contrast can be a separate `sonnet` `high` consultation (without the principal's context), recognizing that it is the same family.
- **Fallback:** if the consultant is unavailable (quota/billing/rate limit), use `sonnet` `high` for a second opinion and `opus` `high` for an architecture verdict, both as separate consultations. The architecture-verdict fallback also runs **without the principal's context** (the verdict must be independent of the principal's framing). Do not retry; the same rules apply.
