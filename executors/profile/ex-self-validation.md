## Self-validation (mandatory before handing back)

Run, on **your** files:
- the project's typecheck (`tsc --noEmit` or equivalent) — filter the output to your files,
  because other agents have half-written files;
- the linter with `--fix`;
- the formatter, if the project has one configured.

If the project enforces a per-file line limit, check it with `wc -l`. If a file already
exceeded the limit before you touched it, **do not make it worse**.

Fix your own errors before handing back. The principal receives finished work.
