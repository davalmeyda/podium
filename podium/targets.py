"""Writing to disk (ARCHITECTURE.md section 7): managed blocks, owned files, JSON keys, plugins.

Everything here builds a *plan* (a list of `Step`) first; applying the plan is a separate pass.
Conflicts (foreign or user-modified files, broken markers) are detected while planning so that an
install either refuses before writing anything or applies cleanly in order.
"""
from __future__ import annotations

import copy
import importlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from podium import render as render_mod
from podium import state
from podium.paths import Paths

MARKETPLACE_NAME = "podium"
PLUGIN_BY_MODULE = (
    ("codegraph", "podium-codegraph"),
    ("memory", "podium-memory"),
    ("usage", "podium-usage"),
    ("upgrade", "podium-upgrade"),
)
ALL_MODULES = ("rules", "executors", "codegraph", "memory", "usage", "upgrade")
EXEC_TIMEOUT = 180
MEMORY_SKILLS_PLUGIN = "podium-memory"


class TargetError(Exception):
    """Base class for disk-writing failures."""


class Conflict(TargetError):
    """A foreign or user-modified file, or broken markers (exit code 2)."""


class EnvError(TargetError):
    """The environment prevents the operation (exit code 3)."""


# --------------------------------------------------------------------------- plan model

@dataclass
class Ctx:
    ledger: state.Ledger
    adopt: bool = False
    force: bool = False
    now: Optional[Callable[[], datetime]] = None

    def timestamp(self) -> Optional[datetime]:
        return self.now() if self.now else None


@dataclass
class Step:
    kind: str                      # block | file | json | exec | note
    path: Optional[Path]
    action: str                    # create | update | unchanged | adopt | force | remove | keep | run | skip | conflict
    label: str
    conflict: Optional[str] = None
    apply: Optional[Callable[[], None]] = field(default=None, repr=False)

    def line(self) -> str:
        head = "[%s]" % self.action
        where = str(self.path) if self.path is not None else ""
        text = "%-11s %s" % (head, where) if where else "%-11s" % head
        detail = self.label if not self.conflict else "%s -- %s" % (self.label, self.conflict)
        return "%s  (%s)" % (text, detail)


def has_conflicts(steps: Sequence[Step]) -> bool:
    return any(step.action == "conflict" for step in steps)


def apply_steps(steps: Sequence[Step], out: Callable[[str], None] = print) -> None:
    """Apply steps in order, printing one line per step; on failure print which steps ran."""
    done: List[str] = []
    for index, step in enumerate(steps, 1):
        out(step.line())
        try:
            if step.apply is not None:
                step.apply()
        except Exception as exc:
            out("failed at step %d/%d: %s" % (index, len(steps), exc))
            out("steps applied before the failure: %s" % (", ".join(done) if done else "none"))
            raise
        done.append(str(index))


# --------------------------------------------------------------------------- managed blocks

def _marker(kind: str, target_id: str) -> str:
    return "<!-- podium:%s %s -->" % (kind, target_id)


def _locate_block(lines: List[str], target_id: str) -> Optional[Tuple[int, int]]:
    begin, end = _marker("begin", target_id), _marker("end", target_id)
    begins = [i for i, line in enumerate(lines) if line.rstrip(" \t\r") == begin]
    ends = [i for i, line in enumerate(lines) if line.rstrip(" \t\r") == end]
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        raise Conflict("duplicate or unbalanced podium markers for block %r" % target_id)
    return begins[0], ends[0]


def set_block(text: str, target_id: str, content: str) -> str:
    """Return `text` with the `target_id` block replaced (or appended); outside text is untouched."""
    body = content if content.endswith("\n") else content + "\n"
    block_lines = [_marker("begin", target_id)] + body[:-1].split("\n") + [_marker("end", target_id)]
    lines = text.split("\n")
    location = _locate_block(lines, target_id)
    if location is not None:
        lines[location[0]:location[1] + 1] = block_lines
        return "\n".join(lines)
    if text == "":
        return "\n".join(block_lines) + "\n"
    prefix = text if text.endswith("\n") else text + "\n"
    return prefix + "\n" + "\n".join(block_lines) + "\n"


def remove_block(text: str, target_id: str) -> Optional[str]:
    """Return `text` without the block, or None when there is no block."""
    lines = text.split("\n")
    location = _locate_block(lines, target_id)
    if location is None:
        return None
    first, last = location
    at_end = lines[last + 1:] in ([], [""])
    del lines[first:last + 1]
    if at_end and first > 0 and lines[first - 1] == "":
        del lines[first - 1]
    return "\n".join(lines)


def get_block(text: str, target_id: str) -> Optional[str]:
    """Return the current content of a block (without markers), or None."""
    lines = text.split("\n")
    location = _locate_block(lines, target_id)
    if location is None:
        return None
    return "\n".join(lines[location[0] + 1:location[1]]) + "\n"


def _read_text(path: Path) -> Optional[str]:
    try:
        with open(str(path), "rb") as handle:
            return handle.read().decode("utf-8", "surrogateescape")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise EnvError("cannot read %s: %s" % (path, exc))


def plan_block(ctx: Ctx, path: Path, target_id: str, content: str) -> Step:
    label = "%s block" % target_id
    try:
        existing = _read_text(path)
        new_text = set_block(existing or "", target_id, content)
    except Conflict as exc:
        return Step("block", path, "conflict", label, str(exc))
    if existing is None:
        action = "create"
    elif existing == new_text:
        return Step("block", path, "unchanged", label)
    else:
        action = "update"

    def apply() -> None:
        if existing is not None:
            state.backup(path, ctx.timestamp())
        state.atomic_write(path, new_text.encode("utf-8", "surrogateescape"))

    return Step("block", path, action, label, apply=apply)


def plan_block_remove(ctx: Ctx, path: Path, target_id: str) -> Step:
    label = "%s block" % target_id
    try:
        existing = _read_text(path)
        new_text = remove_block(existing, target_id) if existing is not None else None
    except Conflict as exc:
        return Step("block", path, "conflict", label, str(exc))
    if new_text is None:
        return Step("block", path, "unchanged", label)

    def apply() -> None:
        state.backup(path, ctx.timestamp())
        state.atomic_write(path, new_text.encode("utf-8", "surrogateescape"))

    return Step("block", path, "remove", label, apply=apply)


# --------------------------------------------------------------------------- owned files

def _disk_hash(path: Path) -> Optional[str]:
    try:
        if path.is_symlink() or not path.is_file():
            return "<not-a-regular-file>" if path.exists() or path.is_symlink() else None
        return state.sha256_file(path)
    except OSError as exc:
        raise EnvError("cannot read %s: %s" % (path, exc))


def plan_file(ctx: Ctx, path: Path, data: bytes, label: str, generated: bool = False) -> Step:
    """Plan writing an owned file. `generated=True` files are always overwritten (no refusal)."""
    key = str(path)
    new_hash = state.sha256_bytes(data)
    disk = _disk_hash(path)
    recorded = ctx.ledger.files.get(key)
    backup_first = adopting = False
    if disk is None:
        action = "create"
    elif generated:
        action = "update"
    elif recorded is None:  # exists but podium never wrote it
        if disk == new_hash:
            action = "adopt"  # identical content: just record it
        elif ctx.adopt:
            action, backup_first, adopting = "adopt", True, True
        else:
            return Step("file", path, "conflict", label,
                        "foreign file (not created by podium); use --adopt to back it up and take it over")
    elif disk == recorded:
        action = "update"
    else:  # the user edited a file podium owns
        if disk == new_hash:
            action = "adopt"
        elif ctx.force:
            action, backup_first = "force", True
        else:
            return Step("file", path, "conflict", label,
                        "modified since podium wrote it; use --force to back it up and overwrite")
    needs_write = disk != new_hash
    if not needs_write and recorded == new_hash:
        return Step("file", path, "unchanged", label)
    if not needs_write:
        action = "adopt"  # content already right: only the ledger entry changes

    def apply() -> None:
        if needs_write:
            if disk is not None and backup_first:
                saved = state.backup(path, ctx.timestamp())
                if adopting:
                    ctx.ledger.adopted[key] = str(saved)
            state.atomic_write(path, data)
        ctx.ledger.files[key] = new_hash
        ctx.ledger.save()

    return Step("file", path, action, label, apply=apply)


def plan_file_remove(ctx: Ctx, path: Path, stop_dirs: Sequence[Path] = ()) -> Step:
    key = str(path)
    recorded = ctx.ledger.files.get(key)
    label = "owned file"
    disk = _disk_hash(path)

    original = ctx.ledger.adopted.get(key)

    def forget() -> None:
        ctx.ledger.files.pop(key, None)
        ctx.ledger.adopted.pop(key, None)
        ctx.ledger.save()

    if disk is None:
        return Step("file", path, "unchanged", "already absent", apply=forget)
    if disk != recorded:
        return Step("file", path, "keep", label, "modified since podium wrote it; left in place", apply=forget)
    if original is not None and os.path.isfile(original):
        def restore() -> None:
            os.replace(original, str(path))
            forget()

        return Step("file", path, "restore", "%s, from %s" % (label, original), apply=restore)

    def apply() -> None:
        os.unlink(str(path))
        forget()
        _prune_empty_dirs(path.parent, stop_dirs)

    return Step("file", path, "remove", label, apply=apply)


def _prune_empty_dirs(directory: Path, stop_dirs: Sequence[Path]) -> None:
    stops = set(str(d) for d in stop_dirs)
    current = directory
    while str(current) not in stops and str(current.parent) != str(current):
        try:
            if any(True for _ in current.iterdir()):
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent


# --------------------------------------------------------------------------- JSON keys

_MISSING = object()


def _tokens(pointer: str) -> List[str]:
    if not pointer.startswith("/") or pointer == "/":
        raise TargetError("invalid JSON pointer: %r" % pointer)
    return [tok.replace("~1", "/").replace("~0", "~") for tok in pointer[1:].split("/")]


def _json_get(doc: Any, tokens: List[str]) -> Any:
    node = doc
    for tok in tokens:
        if isinstance(node, dict) and tok in node:
            node = node[tok]
        else:
            return _MISSING
    return node


def _json_set(doc: Dict[str, Any], tokens: List[str], value: Any) -> None:
    node = doc
    for tok in tokens[:-1]:
        nxt = node.get(tok, _MISSING)
        if nxt is _MISSING:
            nxt = {}
            node[tok] = nxt
        elif not isinstance(nxt, dict):
            raise Conflict("cannot set /%s: /%s is not an object" % ("/".join(tokens), tok))
        node = nxt
    node[tokens[-1]] = copy.deepcopy(value)


def _json_delete(doc: Dict[str, Any], tokens: List[str]) -> None:
    chain = [doc]
    node: Any = doc
    for tok in tokens[:-1]:
        node = node.get(tok) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return
        chain.append(node)
    chain[-1].pop(tokens[-1], None)
    for depth in range(len(chain) - 1, 0, -1):  # prune containers emptied by the removal
        if chain[depth]:
            break
        chain[depth - 1].pop(tokens[depth - 1], None)


def _read_json_doc(path: Path) -> Tuple[Dict[str, Any], bool]:
    text = _read_text(path)
    if text is None:
        return {}, False
    try:
        doc = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise Conflict("%s is not valid JSON (%s); fix it or use plain JSON instead of JSONC" % (path, exc))
    if not isinstance(doc, dict):
        raise Conflict("%s must contain a JSON object" % path)
    return doc, True


def _dump_json(doc: Dict[str, Any]) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def plan_json(ctx: Ctx, path: Path, entries: Sequence[Tuple[str, Any]], label: str) -> Step:
    """Plan setting owned JSON pointers; remembers `before` and `applied` in the ledger."""
    try:
        doc, existed = _read_json_doc(path)
    except Conflict as exc:
        return Step("json", path, "conflict", label, str(exc))
    recorded = ctx.ledger.json.get(str(path), {})
    new_doc = copy.deepcopy(doc)
    updates: Dict[str, Dict[str, Any]] = {}
    problems: List[str] = []
    used_adopt = used_force = False
    for pointer, value in entries:
        tokens = _tokens(pointer)
        current = _json_get(doc, tokens)
        rec = recorded.get(pointer)
        write = False
        if rec is not None:
            before = rec.get("before")
            if current is _MISSING:
                write = True
            elif current == rec.get("applied"):
                write = current != value
            elif current == value:
                pass
            elif ctx.force:
                write, used_force = True, True
            else:
                problems.append("%s was modified since podium wrote it" % pointer)
                continue
        else:
            before = None if current is _MISSING else copy.deepcopy(current)
            if current is _MISSING:
                write = True
            elif current == value:
                pass
            elif ctx.adopt:
                write, used_adopt = True, True
            else:
                problems.append("%s already exists and is not managed by podium" % pointer)
                continue
        if write:
            try:
                _json_set(new_doc, tokens, value)
            except Conflict as exc:
                problems.append(str(exc))
                continue
        updates[pointer] = {"before": before, "applied": copy.deepcopy(value)}
    if problems:
        hint = "use --adopt (foreign keys) or --force (edited keys) to back up and overwrite"
        return Step("json", path, "conflict", label, "; ".join(problems) + "; " + hint)
    doc_changed = new_doc != doc or not existed
    ledger_changed = any(recorded.get(p) != rec for p, rec in updates.items())
    if not doc_changed and not ledger_changed:
        return Step("json", path, "unchanged", label)
    if not doc_changed:
        action = "adopt"
    elif not existed:
        action = "create"
    else:
        action = "force" if used_force else "adopt" if used_adopt else "update"

    def apply() -> None:
        if doc_changed:
            if existed:
                state.backup(path, ctx.timestamp())
            state.atomic_write(path, _dump_json(new_doc))
        ctx.ledger.json.setdefault(str(path), {}).update(updates)
        ctx.ledger.save()

    return Step("json", path, action, label, apply=apply)


def plan_json_remove(ctx: Ctx, path: Path) -> List[Step]:
    """Revert every owned pointer of `path` whose current value still equals `applied`."""
    recorded = ctx.ledger.json.get(str(path))
    if not recorded:
        return []
    label = "owned JSON keys"
    try:
        doc, existed = _read_json_doc(path)
    except Conflict as exc:
        return [Step("json", path, "conflict", label, str(exc))]
    new_doc = copy.deepcopy(doc)
    kept: List[str] = []
    for pointer, rec in recorded.items():
        tokens = _tokens(pointer)
        current = _json_get(new_doc, tokens)
        if current is _MISSING:
            continue
        if current != rec.get("applied"):
            kept.append(pointer)
            continue
        if rec.get("before") is None:
            _json_delete(new_doc, tokens)
        else:
            _json_set(new_doc, tokens, rec["before"])

    def apply() -> None:
        if new_doc != doc:
            state.backup(path, ctx.timestamp())
            state.atomic_write(path, _dump_json(new_doc))
        ctx.ledger.json.pop(str(path), None)
        ctx.ledger.save()

    detail = "kept (edited since podium wrote them): %s" % ", ".join(kept) if kept else ""
    action = "remove" if new_doc != doc else "unchanged"
    return [Step("json", path, action, label, detail or None, apply=apply)]


# --------------------------------------------------------------------------- external commands

def find_claude(env: Mapping[str, str]) -> Optional[str]:
    return shutil.which("claude", path=env.get("PATH", os.defpath))


def _exec_step(label: str, argv: List[str], env: Mapping[str, str], fatal: bool,
               tolerate: Sequence[str] = ()) -> Step:
    def apply() -> None:
        try:
            proc = subprocess.run(argv, env=dict(env), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=EXEC_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            if fatal:
                raise EnvError("%s failed: %s" % (" ".join(argv), exc))
            print("  warning: %s failed: %s" % (" ".join(argv), exc))
            return
        if proc.returncode == 0:
            return
        output = proc.stdout.decode("utf-8", "replace").strip()
        if any(word in output.lower() for word in tolerate):
            return
        tail = " | ".join(output.splitlines()[-3:])
        if fatal:
            raise EnvError("%s exited with %d: %s" % (" ".join(argv), proc.returncode, tail))
        print("  warning: exit %d: %s" % (proc.returncode, tail))

    return Step("exec", None, "run", " ".join(argv), apply=apply)


# --------------------------------------------------------------------------- install plan

def block_targets(paths: Paths) -> Dict[str, Path]:
    return {
        "claude-md": paths.claude_dir / "CLAUDE.md",
        "opencode-agents-md": paths.opencode_config_dir / "AGENTS.md",
    }


def profile_path(paths: Paths) -> Path:
    return paths.state_dir / "executor-profile.md"


def runtime_path(paths: Paths) -> Path:
    return paths.config_dir / "runtime.json"


def agent_path(paths: Paths, name: str) -> Path:
    return paths.opencode_config_dir / "agents" / ("%s.md" % name)


def _memory_mcp_entry(memory: Mapping[str, Any]) -> Dict[str, Any]:
    """OpenCode remote MCP entry for the memory server (headers/options only when set)."""
    entry: Dict[str, Any] = {"type": "remote", "url": memory["url"], "enabled": True}
    if memory.get("headers"):
        entry["headers"] = dict(memory["headers"])
    for key, value in (memory.get("mcp_options") or {}).items():
        entry.setdefault(key, value)
    return entry


def opencode_json_path(paths: Paths) -> Path:
    return paths.opencode_config_dir / "opencode.json"


def effective_modules(config: Mapping[str, Any], selected: Optional[Sequence[str]]) -> List[str]:
    """Modules to act on: enabled in the config and (when given) named in `--modules`."""
    enabled = [m for m in ALL_MODULES if config["modules"].get(m, False)]
    if selected is None:
        return enabled
    unknown = [m for m in selected if m not in ALL_MODULES]
    if unknown:
        raise TargetError("unknown module(s): %s (valid: %s)" % (", ".join(unknown), ", ".join(ALL_MODULES)))
    return [m for m in enabled if m in selected]


def launcher_regex(launcher: str) -> str:
    tokens = launcher.split()
    if not tokens:
        return ""
    if "run" in tokens:
        tokens = tokens[:tokens.index("run") + 1]
    else:
        tokens = tokens[:1]
    return " ".join(tokens) + " "


def runtime_document(paths: Paths, config: Mapping[str, Any]) -> Dict[str, Any]:
    """The hook runtime contract (ARCHITECTURE.md section 9.2)."""
    cg, mem, hook = config["codegraph"], config["memory"], config["memory"]["stop_hook"]
    return {
        "schema": 1,
        "ui": config["language"]["ui"],
        "paths": {
            "home": str(paths.home),
            "claude_dir": str(paths.claude_dir),
            "opencode_data_dir": str(paths.opencode_data_dir),
            "state_dir": str(paths.state_dir),
        },
        "codegraph": {
            "gate": cg["gate"],
            "nudge_every": cg["nudge_every"],
            "roots": list(cg["roots"]),
            "manifests": list(cg["extra_manifests"]),
            "ignored": list(cg["extra_ignored"]),
        },
        "memory": {
            "mcp_server": mem["mcp_server"],
            "min_edits": hook["min_edits"],
            "min_executor_runs": hook["min_executor_runs"],
            "cooldown_seconds": hook["cooldown_seconds"],
        },
        "executors": {"launcher_regex": launcher_regex(config["launcher"]["opencode"])},
        "usage": {"model_order": list(config["usage"]["model_order"])},
    }


def _skill_files(podium_home: Path) -> List[Tuple[str, Path]]:
    root = podium_home / "plugins" / MEMORY_SKILLS_PLUGIN / "skills"
    found: List[Tuple[str, Path]] = []
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            full = Path(dirpath) / name
            found.append((full.relative_to(root).as_posix(), full))
    return found


def _prune_stale(ctx: Ctx, directory: Path, wanted: Set[str]) -> List[Step]:
    """Remove files podium owns under `directory` that the current config no longer renders."""
    prefix = str(directory) + os.sep
    stale = [key for key in sorted(ctx.ledger.files) if key.startswith(prefix) and key not in wanted]
    return [plan_file_remove(ctx, Path(key), [directory]) for key in stale]


def build_install_steps(
    paths: Paths,
    config: Mapping[str, Any],
    ctx: Ctx,
    env: Mapping[str, str],
    modules: Optional[Sequence[str]] = None,
    podium_home: Optional[Path] = None,
) -> List[Step]:
    """Ordered install plan: blocks, profile, agents, skills, opencode.json, runtime.json, plugins."""
    podium_home = Path(podium_home) if podium_home is not None else paths.podium_home
    active = effective_modules(config, modules)
    steps: List[Step] = []

    def render(target_id: str) -> str:
        return render_mod.render_target(target_id, config, podium_home, paths.config_dir)

    if "rules" in active:
        for target_id, path in block_targets(paths).items():
            steps.append(plan_block(ctx, path, target_id, render(target_id)))

    if "executors" in active:
        profile = render("executor-profile")
        steps.append(plan_file(ctx, profile_path(paths), profile.encode("utf-8"), "executor-profile"))
        wanted = set()
        if config["agents"]:
            roster = importlib.import_module("podium.roster")
            for agent in config["agents"]:
                text = roster.render_agent(agent, config, podium_home)
                wanted.add(str(agent_path(paths, agent["name"])))
                steps.append(plan_file(ctx, agent_path(paths, agent["name"]), text.encode("utf-8"),
                                       "agent %s" % agent["name"]))
        steps.extend(_prune_stale(ctx, paths.opencode_config_dir / "agents", wanted))

    if "memory" in active:
        skills_root = paths.opencode_config_dir / "skills"
        wanted = set()
        for rel, source in _skill_files(podium_home):
            with open(str(source), "rb") as handle:
                data = handle.read()
            wanted.add(str(skills_root / rel))
            steps.append(plan_file(ctx, skills_root / rel, data, "OpenCode skill %s" % rel.split("/")[0]))
        steps.extend(_prune_stale(ctx, skills_root, wanted))

    entries: List[Tuple[str, Any]] = []
    if "memory" in active and config["memory"]["url"]:
        entries.append(("/mcp/%s" % config["memory"]["mcp_server"].replace("~", "~0").replace("/", "~1"),
                        _memory_mcp_entry(config["memory"])))
    if "codegraph" in active:
        entries.append(("/mcp/codegraph",
                        {"type": "local", "command": ["codegraph", "serve", "--mcp"], "enabled": True}))
    if entries:
        steps.append(plan_json(ctx, opencode_json_path(paths), entries, "OpenCode MCP servers"))

    runtime = (json.dumps(runtime_document(paths, config), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    steps.append(plan_file(ctx, runtime_path(paths), runtime, "hook runtime", generated=True))

    plugins = [plugin for module, plugin in PLUGIN_BY_MODULE if module in active]
    if plugins:
        claude = find_claude(env)
        if claude is None:
            steps.append(Step("note", None, "skip", "claude not found on PATH; Claude Code plugins not installed"))
        else:
            steps.append(_exec_step("marketplace", [claude, "plugin", "marketplace", "add", str(podium_home)],
                                    env, fatal=True, tolerate=("already",)))
            for plugin in plugins:
                steps.append(_exec_step(plugin, [claude, "plugin", "install",
                                                 "%s@%s" % (plugin, MARKETPLACE_NAME), "--scope", "user"],
                                        env, fatal=False, tolerate=("already",)))
    return steps


def build_uninstall_steps(paths: Paths, ctx: Ctx, env: Mapping[str, str]) -> List[Step]:
    """Ordered uninstall plan, driven by the ledger and the managed markers."""
    steps: List[Step] = []
    ledger = ctx.ledger
    if not ledger.is_empty():
        claude = find_claude(env)
        if claude is not None:
            for _module, plugin in PLUGIN_BY_MODULE:
                steps.append(_exec_step(plugin, [claude, "plugin", "uninstall",
                                                 "%s@%s" % (plugin, MARKETPLACE_NAME), "--scope", "user"],
                                        env, fatal=False, tolerate=("not installed", "not found")))
            steps.append(_exec_step("marketplace", [claude, "plugin", "marketplace", "remove", MARKETPLACE_NAME],
                                    env, fatal=False, tolerate=("not found", "not installed")))
    for target_id, path in block_targets(paths).items():
        steps.append(plan_block_remove(ctx, path, target_id))
    stops = [paths.opencode_config_dir, paths.claude_dir, paths.state_dir, paths.config_dir, paths.home]
    for key in sorted(ledger.files):
        steps.append(plan_file_remove(ctx, Path(key), stops))
    for key in sorted(ledger.json):
        steps.extend(plan_json_remove(ctx, Path(key)))
    return steps


# --------------------------------------------------------------------------- diff support

def rendered_for_diff(paths: Paths, config: Mapping[str, Any], podium_home: Path,
                      target: Optional[str]) -> List[Tuple[str, Path, str, Optional[str]]]:
    """(label, path, rendered text, current text or None) for blocks, the profile and agents."""
    items: List[Tuple[str, Path, str, Optional[str]]] = []
    known = render_mod.target_ids(podium_home)
    if target is not None and target not in known and target != "agents":
        raise render_mod.RenderError("unknown target: %s" % target)
    for target_id, path in block_targets(paths).items():
        if target in (None, target_id) and target_id in known:
            text = render_mod.render_target(target_id, config, podium_home, paths.config_dir)
            current = _read_text(path)
            items.append((target_id, path, text, get_block(current, target_id) if current is not None else None))
    if target in (None, "executor-profile") and "executor-profile" in known:
        text = render_mod.render_target("executor-profile", config, podium_home, paths.config_dir)
        items.append(("executor-profile", profile_path(paths), text, _read_text(profile_path(paths))))
    if target in (None, "agents") and config["agents"]:
        roster = importlib.import_module("podium.roster")
        for agent in config["agents"]:
            path = agent_path(paths, agent["name"])
            items.append(("agent %s" % agent["name"], path,
                          roster.render_agent(agent, config, podium_home), _read_text(path)))
    return items
