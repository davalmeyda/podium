### Phases and reconciliation

Work is organised in phases when needed. On closing each phase, the principal reconciles before starting the next:
- Verify that the phase's objectives are met.
- Review only the changes and effects of the current phase.
- Validate the integration between the results of the different agents.
- Apply adjustments/refactors that are a direct consequence of the phase and resolve emerging dependencies, even on artifacts outside the original scope.
- **Last step: evaluate whether the phase leaves anything for the shared memory log** (decisions, pending items, next step, non-obvious problem solved). If it does, ONE entry (skill `podium-memory:project-memory`); if not, nothing. Same when closing a task without phases.

Do not expand validation to historical debt or pre-existing problems. No phase starts until the previous one is reconciled.

**A green compiler proves nothing on its own.** Before reading the error count, the principal verifies that the verifier is measuring against reality:

- **Generated artifacts: check synchronisation, do not trust.** If the project validates against generated code (API client, schema types), regenerate it and compare the hash: if it changes, every previous `tsc` was invalid and the error list must be re-read. An obsolete generated artifact turns the compiler into an accomplice: it validates the code against a contract that no longer exists and reports 0 errors while the code would fail at runtime.
- **Coverage of the split.** The union of scopes must cover the entire list of affected files (the compiler's errors, or a grep of the symbol that changed). Splitting by folder almost never covers shared `components/` or `lib/`; what is left without an owner stays broken and nobody notices.
- **Hand-written wrappers.** Any file that hand-duplicates a backend contract (an axios/fetch wrapper with its own interface) is invisible to the compiler and therefore does not appear in the error list. Update that interface first so it reflects reality: that turns a silent runtime bug into a compilation error.
- **Signature changes with positional arguments.** When a method gains a parameter at the front, existing calls shift one place and **compile** if the types happen to be compatible — doing something completely different. After any signature change, audit each call against its real signature, including those that already compile. It is pure fan-out: it is delegated to a read-only agent with a CORRECT/WRONG verdict per call.
- **Final grep of the symbol.** After reconciling, search in the WHOLE repository what was removed or renamed, not only in the distributed scopes.
