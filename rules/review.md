### Review

- **Strict rules / checklist** → the writer executor against enumerable rules (the cheap fallback in the table).
- **Correctness / judgement** (integration bugs, positional parameters that compile but break at runtime, consistency with the backend) → the principal during reconciliation. Judgement review / evidence collection may be delegated to the consultant at the engine's judgement effort (a `sonnet` at `high` if the consultant is unavailable), read-only; the verdict and fixes remain the principal's.

**Every verification or review the user requests is READ-ONLY. No exceptions.**

When the user asks to "review," "verify," or "check that it is right," launch the executor **without write permission** (the consultant, which cannot write; or any other executor with the brief marked *investigate and report only*). Ask for a report of errors and bugs with `file:line`, and **stop there**. Apply fixes **only after the user authorizes them**, not in the same pass.

All three reasons:
- A review that also fixes things removes the user's choice: by the time the report arrives, changes have already been made and the user did not choose any of them. If work is interrupted halfway, it leaves an inconsistent state nobody requested.
- Reviewing with write access burns write quota on the wrong engine.
- **The writer executor (or `sonnet` when contracts/tightly coupled logic are involved) makes corrections, not the consultant.** The consultant is for judgement: diagnosis, review, and second opinions. Having it fix work at volume exhausts the quota that must be reserved for when contrast is needed.

**Never launch a review with write permission unless the user explicitly requested it in that same request.**

If a long review runs in the background, the executor reports no progress until it finishes, so the principal cannot promise a duration. Before launching broad work, state its scope and offer to split it into verifiable batches.
