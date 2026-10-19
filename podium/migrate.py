"""Migration from a hand-written setup (ARCHITECTURE.md section 8)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from podium import state
from podium.paths import Paths

LEGACY_SCRIPTS = ("codegraph-gate.py", "codegraph-nudge.py", "graphiti-stop.py")
DECISIONS_NAME = "codegraph-decisions.json"

_LEGACY_RE = re.compile(
    r"""(?:^|[\s/\\"'])(%s)(?:$|[\s"'])""" % "|".join(re.escape(n) for n in LEGACY_SCRIPTS)
)


class MigrateError(Exception):
    """settings.json or a decisions file cannot be migrated safely."""


def _command_text(hook: Dict[str, Any]) -> str:
    parts = [str(hook.get("command", ""))]
    args = hook.get("args")
    if isinstance(args, list):
        parts.extend(str(a) for a in args)
    return " ".join(parts)


def legacy_script(hook: Any) -> Optional[str]:
    """Name of the legacy script a hook entry runs, or None (plugin hooks are never legacy)."""
    if not isinstance(hook, dict):
        return None
    text = _command_text(hook)
    if "CLAUDE_PLUGIN_ROOT" in text:
        return None
    match = _LEGACY_RE.search(text)
    return match.group(1) if match else None


def find_legacy_hooks(settings: Dict[str, Any]) -> List[Dict[str, str]]:
    """List legacy hook entries in a parsed settings.json: event, matcher, command, script."""
    found: List[Dict[str, str]] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return found
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []) if isinstance(group.get("hooks"), list) else []:
                script = legacy_script(hook)
                if script:
                    found.append({"event": event, "matcher": str(group.get("matcher", "")),
                                  "command": _command_text(hook), "script": script})
    return found


def strip_legacy_hooks(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of `settings` without the legacy hook entries; emptied containers are dropped."""
    result = copy.deepcopy(settings)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                inner = [h for h in group["hooks"] if legacy_script(h) is None]
                if len(inner) != len(group["hooks"]):
                    if not inner:
                        continue  # the group only held legacy hooks
                    group = dict(group)
                    group["hooks"] = inner
            kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        del result["hooks"]
    return result


def _merge_decisions(legacy: Any, current: Any) -> Any:
    """Recursive merge where `current` (podium) wins over `legacy` on conflicts."""
    if isinstance(legacy, dict) and isinstance(current, dict):
        merged = dict(legacy)
        for key, value in current.items():
            merged[key] = _merge_decisions(legacy[key], value) if key in legacy else value
        return merged
    return current


def _read_json(path: Path) -> Any:
    try:
        with open(str(path), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except ValueError as exc:
        raise MigrateError("%s is not valid JSON: %s" % (path, exc))
    except OSError as exc:
        raise MigrateError("cannot read %s: %s" % (path, exc))


def run(paths: Paths, dry_run: bool = False, out: Callable[[str], None] = print,
        now: Optional[Callable[[], Any]] = None) -> int:
    """Migrate legacy hooks and decisions. Returns 0; raises MigrateError on unreadable input."""
    stamp = (lambda: now()) if now else (lambda: None)
    settings_path = paths.claude_dir / "settings.json"
    legacy_state = paths.claude_dir / "state" / DECISIONS_NAME
    podium_state = paths.state_dir / DECISIONS_NAME
    actions: List[Callable[[], None]] = []
    left_behind: List[str] = []

    # 1. legacy hook entries in settings.json
    if settings_path.is_file():
        settings = _read_json(settings_path)
        if not isinstance(settings, dict):
            raise MigrateError("%s must contain a JSON object" % settings_path)
        legacy = find_legacy_hooks(settings)
        if legacy:
            for item in legacy:
                out("remove hook: %s %s -> %s" % (item["event"], item["matcher"] or "(any)", item["script"]))
            cleaned = strip_legacy_hooks(settings)

            def write_settings(cleaned: Dict[str, Any] = cleaned) -> None:
                state.backup(settings_path, stamp())
                state.atomic_write(settings_path, json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n")

            actions.append(write_settings)
        else:
            out("no legacy hook entries in %s" % settings_path)
    else:
        out("no settings.json at %s" % settings_path)

    # 2. CodeGraph gate decisions
    if legacy_state.is_file():
        legacy_data = _read_json(legacy_state)
        current_data: Any = _read_json(podium_state) if podium_state.is_file() else {}
        if not isinstance(legacy_data, dict) or not isinstance(current_data, dict):
            raise MigrateError("%s and %s must both contain JSON objects" % (legacy_state, podium_state))
        merged = _merge_decisions(legacy_data, current_data)
        if merged != current_data:
            out("copy decisions: %s -> %s" % (legacy_state, podium_state))

            def write_decisions(merged: Dict[str, Any] = merged) -> None:
                if podium_state.is_file():
                    state.backup(podium_state, stamp())
                state.atomic_write(podium_state, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")

            actions.append(write_decisions)
        else:
            out("decisions already present in %s" % podium_state)
        left_behind.append(str(legacy_state))
    else:
        out("no legacy decisions file at %s" % legacy_state)

    # 3. legacy scripts are never deleted; report what remains
    for name in LEGACY_SCRIPTS:
        script = paths.claude_dir / "hooks" / name
        if script.exists():
            left_behind.append(str(script))
    for item in left_behind:
        out("left in place (not deleted): %s" % item)

    if dry_run:
        out("dry-run: nothing written")
        return 0
    if actions:
        with state.lock(paths.state_dir):
            for action in actions:
                action()
    return 0
