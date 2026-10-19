## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim, line-numbered source plus the call paths between them, including dynamic-dispatch hops (callbacks, React re-render, JSX children) that grep cannot follow. Name a file or symbol in the query to read its current line-numbered source. If it is listed but deferred, load it by name via tool search. Treat the output as already read: do not reopen those files to understand them; Read directly only the exact file you are about to edit.
- **Shell fallback** (always works): `codegraph explore "<query>"` prints the same output. For a sub-project under a parent folder, use `codegraph explore -p <root> "<query>"`.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.

**Multi-project folders.** This rule overrides the "skip CodeGraph entirely" line above when the current folder is a parent of several projects:

- If the current folder has no `.codegraph/`, look for indexed sub-projects before skipping: `find . -maxdepth 3 -type d -name .codegraph -not -path '*/node_modules/*'`. Skip CodeGraph only if none is found.
- Query each sub-project by passing its root as `projectPath` to `codegraph_explore` (shell: `codegraph explore -p <root> "<query>"`). For a question that spans several projects, query each one and combine the answers.
- The MCP tool catches the index up on first access to a project and keeps watching it for the rest of the session, so no manual `codegraph sync` is needed before querying through the MCP.
- Never run `codegraph init` or `codegraph index` on a parent folder or the home folder.
- If the task is to understand or work on a real code project (it has its own manifest such as `package.json`, `composer.json`, `pyproject.toml`, `go.mod` or `pom.xml`, or its own `.git`) and no index covers it — none at its root or above it — **recommend once to the user, at the start of the task, to index it**: give the exact command `codegraph init <project root>`, naming the project root, never a parent folder holding several projects or the home folder. Do not run `codegraph init` yourself unless the user approves, and do not repeat the suggestion for the same project in the same conversation. Skip the suggestion for one-off questions and tiny scripts.
