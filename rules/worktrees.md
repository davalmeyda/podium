### Worktrees: Parallel Work Outside the Main Checkout

**When (by judgement, not by default):** only to change code in parallel with the work running in the main checkout when doing it there would complicate things (two large changes that would collide, a structural change while executors are editing the main checkout). If the work fits in independent regions of the main checkout, no worktree is needed. Create as many as the work needs; there is no cap.

**Fixed assumption:** in each project only the user and the principal with its executors work; nobody else touches the main checkout. The principal knows and controls what is in progress there, so it neither asks nor warns about possible outside work.

**Only the principal uses git:** it creates the worktree, integrates, resolves conflicts and cleans up. Executors keep git forbidden, inside the worktree too. Never use the Agent tool's `isolation: "worktree"` (it creates worktrees outside this procedure): the principal creates the worktree and passes its path in the brief.

**Procedure: always through `podium worktree`** (it never changes the branch or the index of the main checkout and never commits):
- `podium worktree create <repo> <task> [untracked files to copy]` → the base is `git stash create` (a snapshot of the main checkout's uncommitted changes; `HEAD` when there are none), branch `wt/<task>` in the sibling folder `../<repo>-wt/<task>`. It copies the files given (environment files, a generated client, new files of the main checkout not yet added to git; decided case by case) and symlinks the dependency folders listed in `[worktrees] link` (default `node_modules`) to the main checkout's, so no disk is duplicated. If a link does not work in a particular case, install the dependencies offline inside the worktree from the package manager's global store (for example `pnpm install --offline`), which reuses that store without extra disk space; this is not blocking.

**Work in the worktree:** never start it (the only running copy of the project is the main checkout, with the right database). Validate code only: the project's typecheck and lint; no visual review and no running it. Never regenerate artefacts there (API client, schema types, ORM clients): they are regenerated in the main checkout after integrating. The brief names the worktree as the working directory.

**Integration, once the main checkout finishes its work in progress:**
1. `podium worktree integrate <repo> <task>` → a per-file three-way merge (`git merge-file` base / main / worktree) written directly onto the main checkout's files, including new and deleted files. It never uses the index and never commits.
2. If it exits with code 2, resolve in the main checkout the `<<<<<<< main` / `>>>>>>> worktree` markers (and the `*.worktree` copies of files created on both sides).
3. Verify in the main checkout: typecheck, lint and, when relevant, a visual review with the project running.

**Full cleanup (no traces left):** `podium worktree clean <repo> <task>` → removes the dependency symlinks (never touching the main checkout's folders), the worktree, the branch, the stored base, the `../<repo>-wt/` folder when it is left empty and podium's CodeGraph decision for the worktree; it prints the leftovers, which must all be zero.
