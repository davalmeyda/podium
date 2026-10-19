## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim, line-numbered source plus the call paths between them, including dynamic-dispatch hops (callbacks, React re-render, JSX children) that grep cannot follow. Name a file or symbol in the query to read its current line-numbered source. If it is listed but deferred, load it by name via tool search. Treat the output as already read: do not reopen those files to understand them; Read directly only the exact file you are about to edit.
- **Shell fallback** (always works): `codegraph explore "<query>"` prints the same output. For a sub-project under a parent folder, use `codegraph explore -p <root> "<query>"`.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.

**Multi-project folders.** This rule overrides the "skip CodeGraph entirely" line above when the current folder is a parent of several projects:

- If the current folder has no `.codegraph/`, look for indexed sub-projects before skipping: `find . -maxdepth 3 -type d -name .codegraph -not -path '*/node_modules/*' -not -path '*-wt/*'`. Skip CodeGraph only if none is found.
- Query each sub-project by passing its root as `projectPath` to `codegraph_explore` (shell: `codegraph explore -p <root> "<query>"`). For a question that spans several projects, query each one and combine the answers.
- The MCP tool catches the index up on first access to a project and keeps watching it for the rest of the session, so no manual `codegraph sync` is needed before querying through the MCP.
- Never run `codegraph init` or `codegraph index` on a parent folder or the home folder.
- **Before working on a real code project** (its own manifest such as `package.json`, `composer.json`, `pyproject.toml`, `go.mod`, `pom.xml`, `Cargo.toml`, or its own `.git`) and no index covers it — none at its root or above it — **ask the user with the AskUserQuestion tool** whether to index it, before reading, editing, or delegating anything in it. The question must contain the word `CodeGraph` and the project's absolute root path, with exactly the two options the gate hook names in its denial message (they follow the configured UI language; in English, `Index now` and `Do not index`). On the index option, run `codegraph init <project root>` (in the background if large) and wait for it before working there; on the other, proceed without it. The persisted decision can be changed by the user (it is stored in the podium state dir). Name the project root, never a parent folder holding several projects or the home folder.
- Every brief for an executor working in an indexed project names the index root (`projectPath`) and the starting symbols, and says to use the CodeGraph tool before grep/read — OpenCode executors are not covered by Claude Code hooks, so the brief is what enforces it there. The Claude Code tool is named `codegraph_explore`; the OpenCode tool is named `codegraph_codegraph_explore` (call it with `projectPath` set to the index root).

This policy is enforced by the podium-codegraph gate hook, which denies reads, edits, writes, grep, glob, and shell access to an unindexed project until the user answers, and continues denying after the user chooses to index until the index exists. Never work around the gate with another tool or by delegating project reads. A subagent that hits the denial stops and reports it to the principal, who asks the user.
