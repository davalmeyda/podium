### Contract-Based Parallelism (Two Combinable Axes)

The principal combines two orthogonal axes (one, the other, nested, or neither):
- **Sequential (phases):** order work over time only when a step needs the previous step to **actually exist** (its behaviour, not just its shape).
- **Parallel by contract:** run pieces at once—even when they depend on each other—when the principal can **define their exchange contract in advance** (e.g. the frontend is built against the defined shape of an endpoint without waiting for the backend to run).

**Trigger at each boundary (not globally): "Can I close the contract now?"** Yes → parallel; no (the design is only discovered through implementation) → sequential.

**The contract governs phases** and is defined from macro to micro (widest scope first): *system* (domain, entity shape, invariants) → *umbrella* (spans and orders multiple phases) → *boundary* (the signature of one specific endpoint). Phases are time-based cuts through the contract; if the umbrella contract is weak, reconciliation becomes rework.

**In the brief**, the contract must be identical on both sides and closed down to the details: route/signature, input payload, exact response shape (including streaming: chunks and termination), error names and shapes.

**Physical consistency** (closing the contract resolves the logical dependency; it does NOT authorize two people to edit one file):
- *Disjoint files* → parallel directly, without isolation (the normal case: frontend/backend, separate modules).
- *Same tightly coupled file* → one executor or sequential phases.
