#!/usr/bin/env python3
"""CodeGraph gate hook for Claude Code.

PreToolUse (Read|Edit|Write|Grep|Glob|Bash): if the path falls inside a real
project (manifest or .git) with no .codegraph and no recorded decision, BLOCK
the tool and demand an AskUserQuestion from the user.

PostToolUse (AskUserQuestion): record the user's answer. Only the two allowed
answers unlock: the locale's "yes" label (keep blocking until the index exists)
or "no" (allow immediately).

Strings come from locales/<ui>.json. Fails open (exit 0, no stdout) on any
error and appends one line to state_dir/hooks.log.
"""
import json
import os
import re
import shlex
import sys

# Resolve plugin_root from this script's location so locale files travel with it.
_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runtime  # noqa: E402


_BUILTIN_MANIFESTS = (
    ".git", "package.json", "composer.json", "pyproject.toml",
    "go.mod", "pom.xml", "Cargo.toml",
    "Gemfile", "build.gradle", "build.gradle.kts", "pubspec.yaml",
    "mix.exs", "deno.json",
)

_BUILTIN_HOME_IGNORED = (".claude", ".config", ".cache", ".local", ".npm")
_SYSTEM_DIRS = {
    "darwin": ("/private/tmp", "/tmp", "/var", "/opt", "/usr",
               "/Applications", "/System"),
    "linux": ("/tmp", "/var", "/opt", "/usr", "/proc", "/sys",
              "/run", "/snap", "/etc", "/boot"),
    "win32": (),
}


def _labels(runtime):
    locale = _runtime.load_locale(runtime.get("ui", "en"), _PLUGIN_ROOT)
    yes = locale["labels"]["yes"]
    no = locale["labels"]["no"]
    return locale, yes, no


def _ignored_set(home, extras):
    ignored = []
    for p in _BUILTIN_HOME_IGNORED:
        ignored.append(os.path.join(home, p))
    if sys.platform == "darwin":
        ignored.append(os.path.join(home, "Library"))
    for d in _SYSTEM_DIRS.get(sys.platform, ()):
        ignored.append(d)
    for extra in extras or ():
        if extra and os.path.isabs(extra):
            ignored.append(extra)
        elif extra:
            ignored.append(os.path.join(home, extra))
    return tuple(ignored)


def _manifests(extras):
    return tuple(_BUILTIN_MANIFESTS) + tuple(extras or ())


def _decisions_path(state_dir):
    return os.path.join(state_dir, "codegraph-decisions.json")


def _legacy_decisions_path(paths):
    """Read-only legacy location under paths.home/.claude/state/."""
    return os.path.join(paths["home"], ".claude", "state", "codegraph-decisions.json")


def load_decisions(paths):
    """Load decisions from the new location, falling back to legacy once."""
    path = _decisions_path(paths["state_dir"])
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "decisions" in data:
                return data
            return {"decisions": data if isinstance(data, dict) else {}}
        except Exception:
            return {"decisions": {}}
    legacy = _legacy_decisions_path(paths)
    if os.path.isfile(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "decisions" in data:
                return data
            return {"decisions": data if isinstance(data, dict) else {}}
        except Exception:
            return {"decisions": {}}
    return {"decisions": {}}


def save_decisions(paths, state):
    path = _decisions_path(paths["state_dir"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, path)


def is_worktree(root):
    """True when `root` looks like a git worktree: a `<root>/.git` file whose
    content is a `gitdir: .../.git/worktrees/<name>` pointer. Any OSError while
    reading the pointer (missing, unreadable, or `<root>/.git` is a directory)
    returns False: only the git worktree layout should be detected here."""
    try:
        with open(os.path.join(root, ".git"), "r", encoding="utf-8") as f:
            return "/worktrees/" in f.read()
    except OSError:
        return False


def worktree_main(root):
    """Main checkout of the git worktree at `root` (the folder holding the
    `.git/worktrees/<name>` its pointer names), or None."""
    try:
        with open(os.path.join(root, ".git"), "r", encoding="utf-8") as f:
            pointer = f.read().strip()
    except OSError:
        return None
    gitdir = pointer[len("gitdir:"):].strip() if pointer.startswith("gitdir:") else ""
    marker = os.sep + ".git" + os.sep + "worktrees" + os.sep
    if marker not in gitdir:
        return None
    return gitdir.split(marker, 1)[0] or None


def indexed(path, roots, home):
    """True if `path` has a .codegraph ancestor (or itself) inside HOME, which
    is exclusive, or inside a configured root, which is inclusive."""
    abspath = os.path.abspath(path)
    for top, inclusive in _runtime.search_tops(abspath, home, roots):
        d = abspath
        while _runtime.within_top(d, top, inclusive):
            if os.path.isdir(os.path.join(d, ".codegraph")):
                return True
            if d == top:
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return False


def project_root(path, manifests, ignored, home, roots):
    """Closest project (manifest or .git) containing the path, searched within
    HOME (exclusive) and the configured roots (inclusive); never the home."""
    abspath = os.path.abspath(path)
    if any(abspath == i or abspath.startswith(i + os.sep) for i in ignored):
        return None
    if "/node_modules/" in abspath:
        return None
    d = abspath if os.path.isdir(abspath) else os.path.dirname(abspath)
    tops = _runtime.search_tops(abspath, home, roots)
    while any(_runtime.within_top(d, top, inclusive) for top, inclusive in tops):
        if any(os.path.exists(os.path.join(d, m)) for m in manifests):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return None


def _split_bash_segments(cmd):
    """Split a shell command into the list of non-empty segments a human
    would recognise, so we can reason about which side of a `;`/`&&`/`||`/`|`
    is the actual call."""
    if not cmd:
        return []
    text = cmd
    out = []
    start = 0
    i = 0
    quote = None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and i + 1 < len(text):
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            i += 1
            continue
        if c in (";", "|"):
            out.append(text[start:i])
            start = i + 1
            i += 1
            continue
        if c == "&" and i + 1 < len(text) and text[i + 1] == "&":
            out.append(text[start:i])
            start = i + 2
            i += 2
            continue
        if c == "\n":
            out.append(text[start:i])
            start = i + 1
            i += 1
            continue
        i += 1
    tail = text[start:]
    if tail.strip():
        out.append(tail)
    return [s.strip() for s in out if s and s.strip()]


def _classify_segment(segment):
    """Return one of: 'codegraph' (runs codegraph), 'cd' (just `cd <dir>`,
    which does not run anything), or 'other' (runs something else).

    A `cd <dir>` segment is treated as a neutral no-op for the purpose of
    deciding whether a whole command is a pure CodeGraph invocation."""
    if not segment:
        return None
    try:
        words = shlex.split(segment, posix=True)
    except ValueError:
        words = segment.split()
    if not words:
        return None
    if words[0] == "cd":
        # A pure `cd <dir>` segment never invokes anything on its own; any
        # follow-up command lives in the NEXT segment after the `&&`.
        return "cd"
    first = words[0]
    if first == "codegraph" or first.endswith("/codegraph"):
        return "codegraph"
    return "other"


def _is_pure_codegraph_command(cmd):
    """A command is exempt from gating only when EVERY non-empty shell
    segment is either a `cd <dir>` no-op or a codegraph invocation.
    `cat secret # codegraph` and `codegraph status; cat /x/f` are NOT
    exempt; `codegraph init /x`, `codegraph status && codegraph explore "q"`,
    and `cd /x && codegraph init .` are."""
    segments = _split_bash_segments(cmd)
    if not segments:
        return False
    for s in segments:
        kind = _classify_segment(s)
        if kind is None or kind == "codegraph" or kind == "cd":
            continue
        return False
    return True


def targets(tool, inp, cwd):
    """Return up to 8 paths to check for the current tool invocation."""
    if tool in ("Read", "Edit", "Write"):
        return [inp.get("file_path", "")]
    if tool in ("Grep", "Glob"):
        return [inp.get("path") or cwd]
    cmd = inp.get("command", "")
    if _is_pure_codegraph_command(cmd):
        return []  # indexing or querying CodeGraph is never blocked
    found = [cwd]
    try:
        words = shlex.split(cmd, posix=True)
    except ValueError:
        words = cmd.split()
    for i, w in enumerate(words):
        if w == "cd" and i + 1 < len(words):
            found.append(os.path.expanduser(words[i + 1]))
        elif w.startswith(("/", "~/")):
            found.append(os.path.expanduser(w))
    return found[:8]


def gate(data, paths, runtime, locale, yes, no):
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    state = load_decisions(paths)
    manifests = _manifests(runtime.get("codegraph", {}).get("manifests") or ())
    ignored = _ignored_set(paths["home"], runtime.get("codegraph", {}).get("ignored") or ())
    roots = runtime.get("codegraph", {}).get("roots") or ()
    for t in targets(tool, inp, cwd):
        if not t:
            continue
        if not os.path.isabs(t):
            t = os.path.join(cwd, t)
        root = project_root(t, manifests, ignored, paths["home"], roots)
        if not root or indexed(t, roots, paths["home"]):
            continue
        decision = state["decisions"].get(root)
        if decision == "skip":
            continue
        if runtime.get("codegraph", {}).get("worktrees", False) and is_worktree(root):
            # a worktree inherits the user's "do not index" for its main checkout
            if state["decisions"].get(worktree_main(root)) == "skip":
                continue
            reason = locale["gate"]["deny_worktree"].format(root=root)
        elif decision == "index":
            reason = locale["gate"]["deny_index_pending"].format(root=root)
        else:
            reason = locale["gate"]["deny_pending"].format(root=root, yes=yes, no=no)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
        return


def _decide(text, yes_set, no_set):
    """'index' or 'skip' when exactly one side's label appears in the text, else None."""
    matched_yes = any(label in text for label in yes_set)
    matched_no = any(label in text for label in no_set)
    if matched_yes and not matched_no:
        return "index"
    if matched_no and not matched_yes:
        return "skip"
    return None


def record(data, paths, runtime, yes, no):
    """PostToolUse AskUserQuestion handler. Labels of EVERY shipped locale are
    recognised, both in structured answers and in the unstructured fallback."""
    inp = data.get("tool_input") or {}
    resp = data.get("tool_response") or {}
    answers = resp.get("answers") if isinstance(resp, dict) else None
    if not isinstance(answers, dict):
        answers = inp.get("answers") if isinstance(inp.get("answers"), dict) else {}

    # Union of yes/no labels across all shipped locales so a label from any
    # language is recognised.
    yes_set, no_set = _all_labels(_PLUGIN_ROOT)

    if not answers:
        blob = json.dumps(resp, ensure_ascii=False) if not isinstance(resp, str) else resp
        questions = [q.get("question", "") for q in inp.get("questions") or [] if isinstance(q, dict)]
        answers = {q: blob for q in questions
                   if "CodeGraph" in q and _decide(blob, yes_set, no_set) is not None}

    state = load_decisions(paths)
    changed = False
    for question, answer in answers.items():
        if "CodeGraph" not in question:
            continue
        candidates = [p.rstrip(".,;:'\"`)") for p in re.findall(r"(/[^\s'\"`]+)", question)]
        manifests = _manifests(runtime.get("codegraph", {}).get("manifests") or ())
        ignored = _ignored_set(paths["home"], runtime.get("codegraph", {}).get("ignored") or ())
        roots = runtime.get("codegraph", {}).get("roots") or ()
        root = next((c for c in candidates
                     if project_root(c, manifests, ignored, paths["home"], roots) == c), None)
        if not root:
            continue
        decision = _decide(str(answer), yes_set, no_set)
        if decision is None:
            continue
        state["decisions"][root] = decision
        changed = True
    if changed:
        try:
            save_decisions(paths, state)
        except Exception as exc:
            _runtime.log_error(paths["state_dir"], "codegraph-gate", f"save_decisions: {exc}")


def _all_labels(plugin_root):
    """Return (yes_labels, no_labels) across every locale shipped in the plugin."""
    yes_set, no_set = set(), set()
    locales_dir = os.path.join(plugin_root, "locales")
    if os.path.isdir(locales_dir):
        for entry in os.listdir(locales_dir):
            if not entry.endswith(".json"):
                continue
            try:
                with open(os.path.join(locales_dir, entry), "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            labels = data.get("labels") or {}
            if labels.get("yes"):
                yes_set.add(labels["yes"])
            if labels.get("no"):
                no_set.add(labels["no"])
    return yes_set, no_set


def main():
    paths, runtime = _runtime.resolve_paths()
    if not runtime.get("codegraph", {}).get("gate", True):
        return  # gate disabled
    try:
        data = json.load(sys.stdin)
    except Exception as exc:
        _runtime.log_error(paths["state_dir"], "codegraph-gate", f"stdin json: {exc}")
        return
    locale, yes, no = _labels(runtime)
    if data.get("hook_event_name") == "PostToolUse":
        try:
            record(data, paths, runtime, yes, no)
        except Exception as exc:
            _runtime.log_error(paths["state_dir"], "codegraph-gate", f"record: {exc}")
    else:
        try:
            gate(data, paths, runtime, locale, yes, no)
        except Exception as exc:
            _runtime.log_error(paths["state_dir"], "codegraph-gate", f"gate: {exc}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # _runtime already imported; default state_dir fallback
        try:
            state_dir = os.environ.get("PODIUM_STATE_DIR") or os.path.join(
                os.path.expanduser("~"), ".local", "state", "podium")
            _runtime.log_error(state_dir, "codegraph-gate", f"top-level: {exc}")
        except Exception:
            pass