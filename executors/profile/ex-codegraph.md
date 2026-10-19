## CodeGraph: your default reading tool

**Before any `grep` / `rg` / `find` / Glob, or before opening files to understand or locate
code, look for a CodeGraph index.** If the repo has `.codegraph/` (in the current folder,
in a parent, or in a sub-project: `find . -maxdepth 3 -type d -name .codegraph -not -path '*/node_modules/*'`):

- Use the MCP tool `codegraph_explore` (in OpenCode it is called `codegraph_codegraph_explore`;
  pass `projectPath` = the sub-project root). One call returns the literal, line-numbered
  source of the symbols plus the call paths between them. Treat that output as already
  read: do not reopen those files.
- To edit, read only the file you are about to touch, and **by line range**, not the whole
  file.
- If the MCP is unavailable: `codegraph explore -p <root> "<symbols or question>"` via shell.
- Use direct `grep` / Read ONLY for what CodeGraph does not cover: non-code files (config,
  `.http`, JSON, Markdown), literal text (UI messages, strings), or the exact file you are
  about to edit next.
- Never run `codegraph init` or `codegraph index`.

If there is no `.codegraph/` anywhere → fall back to the normal tools.
