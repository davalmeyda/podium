## Context consumption and scope

**Every step you take re-sends your entire accumulated context** (it is billed as cache).
What you read or print is not paid once: it is paid on every subsequent step. Measured in a
real setup (Oct 2026, 11 executor sessions): a 250-step executor with a 160K context cost
roughly 25M tokens on work that fit in a fraction of that. So:

- **Short outputs:** filter `tsc`, lint, and test runs to your files and to the minimum
  needed (`| head -50`, `grep` against the file). Do not dump whole files, full logs, or
  full directory trees.
- **Exact scope:** do only what the brief asks. Anything you see outside it (another bug,
  another area, an improvement) is **reported**, not done.
- **No browser, screenshots, or navigation scripts** unless the brief is explicitly for
  **review or verification**. In that case:
  - measure before looking: real values via `getComputedStyle` (typography, colour,
    spacing) and DOM boxes (visibility, overflow, alignment); take a screenshot only if a
    problem is not measurable, one per screen size;
  - no retry loops with `sleep` + screenshot;
  - do not fix: deliver findings in a fixed format — **file, element, screen size,
    expected value vs actual value, severity** — so another executor can implement them
    without re-interpreting.
- **If you get stuck, stop:** if the work drags on far longer than the brief suggests, or
  you repeat attempts that make no progress, halt and hand back the partial result with
  what is missing and what is blocking you. A timely report is worth more than 100 retries.
