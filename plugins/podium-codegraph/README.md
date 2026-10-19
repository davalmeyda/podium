# podium-codegraph

Claude Code plugin that wires two CodeGraph hooks:

| Hook | Events | Purpose |
|---|---|---|
| `codegraph-gate` | PreToolUse `Read\|Edit\|Write\|Grep\|Glob\|Bash`, PostToolUse `AskUserQuestion` | Block tool calls inside a real project that has no `.codegraph/` and no recorded decision; record the user's `AskUserQuestion` answer. |
| `codegraph-nudge` | PreToolUse `Grep\|Glob\|Bash` | Periodically remind the user to prefer `codegraph_explore` over `grep`/`find`/`Read` when the repo is indexed. Never blocks. |

## What it does

### gate
For every `Read|Edit|Write|Grep|Glob|Bash` invocation, the hook extracts up to
eight targets (file path, or `cd`/`abs-path` tokens from a `Bash` command; a
`Bash` command containing `codegraph` is never blocked). For each target it
walks up looking for a project root — any directory holding a known manifest
(`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`,
`composer.json`, `Gemfile`, `build.gradle`, `build.gradle.kts`, `pubspec.yaml`,
`mix.exs`, `deno.json`, or `.git`) — and checks whether that root has a
`.codegraph/` ancestor under `$HOME` or one of `codegraph.roots`. If the path
is inside a project without an index and no decision is recorded, the hook
denies the tool and demands an `AskUserQuestion` containing the word
`CodeGraph` and the project path with the two locale option labels.

The `PostToolUse AskUserQuestion` handler records the user's answer for the
referenced project. "Yes" (any of the shipped locales) keeps the gate closed
until `.codegraph/` exists; "No" opens it immediately.

### nudge
For every `Grep|Glob|Bash` invocation in an indexed project (or one whose
subdirectory is indexed, walked up to depth 3), the hook increments a
session-scoped counter and, every `nudge_every` calls, prints an
`additionalContext` reminder. The session scratch state lives at
`<state_dir>/sessions/codegraph-nudge-<session_id>.json` and is purged after
7 days.

## Strings

All user/model-visible strings come from `locales/<ui>.json` (`en`, `es`).
The shipped `es.json` is a verbatim copy of the original Spanish text from
the reference hook. The `ui` value comes from `runtime.json` written by
`podium install`.

## Configuration keys (from `runtime.json`)

```json
{
  "codegraph": {
    "gate": true,
    "nudge_every": 4,
    "roots": [],
    "manifests": [],
    "ignored": []
  },
  "paths": {
    "home": "/abs",
    "claude_dir": "/abs",
    "opencode_data_dir": "/abs",
    "state_dir": "/abs"
  },
  "ui": "en"
}
```

| Key | Default | Meaning |
|---|---|---|
| `codegraph.gate` | `true` | When `false`, the gate hook exits `0` without inspecting. |
| `codegraph.nudge_every` | `4` | Nudge reminder period in calls. |
| `codegraph.roots` | `[]` | Extra project roots besides `$HOME` (e.g. `/srv`, `/mnt/work`). |
| `codegraph.manifests` | `[]` | Extra manifest filenames, appended to the built-in list. |
| `codegraph.ignored` | `[]` | Extra ignored paths, appended to the platform-aware list. |
| `paths.state_dir` | (required) | Where the decisions file and `hooks.log` are written. |
| `paths.home` | (required) | Legacy decisions fallback (`<home>/.claude/state/codegraph-decisions.json`, read-only). |
| `ui` | `"en"` | Active locale for hook messages. |

## State

- `<state_dir>/codegraph-decisions.json` — `{"decisions": {root: "index" | "skip"}}`.
- `<state_dir>/hooks.log` — one line per internal error.
- `<state_dir>/sessions/codegraph-nudge-<session_id>.json` — session counter.
  Deleted after 7 days.

## Failure mode

Every code path is fail-open: a parse error, missing file, broken manifest,
or unexpected exception exits `0` with no stdout and appends one line to
`hooks.log`. A failing hook must never block the user's work.