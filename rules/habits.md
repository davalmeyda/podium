# Orchestration rules (podium)

## Two habits that always apply (before anything else)

1. **Reading code = CodeGraph first.** To understand or locate code in a repository with `.codegraph/` (in the folder, a parent, or a subproject), the first tool is `codegraph_explore` (`projectPath` = index root), not Grep/Glob/`grep`/`find`/Read. It is also the cheapest reading for the context diet: it returns only the relevant symbols. Grep/Read directly only for literal text, non-code files, or the exact file about to be edited. Detail in the CodeGraph section at the end.
2. **Memory: evaluate and save what matters without the user asking.** At the close of a milestone (reconciled phase, finished task, decision taken, non-obvious bug solved), ask: *would a future session do something wrong or repeat work without this?* If yes, load skill `podium-memory:project-memory` and save ONE dense entry right then (sessions end with Ctrl+C). If not, do not save: each entry costs LLM extraction on the server. Detail at the end.
