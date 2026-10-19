#!/usr/bin/env python3
"""Shared runtime helpers for the podium-codegraph plugin.

Loads runtime.json from the podium config directory (per ARCHITECTURE §3 / §9.2),
falls back to safe defaults when missing, loads the active locale, appends
errors to state_dir/hooks.log, and manages session-scoped scratch state under
state_dir/sessions/ with a 7-day opportunistic cleanup.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


# --- paths ----------------------------------------------------------------

def _expand(value, env):
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        var = value[2:-1]
        return env.get(var, "")
    return value


def _xdg(env, var_name, default):
    value = env.get(var_name)
    if value:
        return Path(value)
    xdg = env.get("XDG_" + var_name.split("_")[0].replace("STATE", "STATE").replace("CONFIG", "CONFIG") + "_HOME")
    if xdg:
        return Path(xdg)
    return Path(default)


def resolve_paths(env=None):
    """Return (paths, runtime) for this plugin. Always returns something usable."""
    env = env if env is not None else os.environ
    home = Path(env.get("HOME") or str(Path.home())).expanduser()
    paths = {
        "home": str(home),
        "claude_dir": env.get("CLAUDE_CONFIG_DIR") or str(home / ".claude"),
        "opencode_data_dir": (
            env.get("XDG_DATA_HOME") and str(Path(env["XDG_DATA_HOME"]) / "opencode")
            or str(home / ".local" / "share" / "opencode")
        ),
        "state_dir": (
            env.get("PODIUM_STATE_DIR")
            or (env.get("XDG_STATE_HOME") and str(Path(env["XDG_STATE_HOME"]) / "podium"))
            or str(home / ".local" / "state" / "podium")
        ),
        "config_dir": (
            env.get("PODIUM_CONFIG_DIR")
            or (env.get("XDG_CONFIG_HOME") and str(Path(env["XDG_CONFIG_HOME"]) / "podium"))
            or str(home / ".config" / "podium")
        ),
    }
    runtime_path = Path(paths["config_dir"]) / "runtime.json"
    runtime = _default_runtime(paths)
    if runtime_path.is_file():
        try:
            with open(runtime_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            runtime = _merge_runtime(runtime, loaded, env)
        except Exception:
            log_error(paths["state_dir"], "_runtime", "runtime.json unreadable, using defaults")
    return paths, runtime


def _default_runtime(paths):
    return {
        "schema": 1,
        "ui": "en",
        "paths": paths,
        "codegraph": {
            "gate": True,
            "nudge_every": 4,
            "roots": [],
            "manifests": [],
            "ignored": [],
        },
        "memory": {"mcp_server": "graphiti-memory", "min_edits": 8,
                   "min_executor_runs": 2, "cooldown_seconds": 2700},
        "executors": {"launcher_regex": "opencode run "},
        "usage": {"model_order": ["opus", "sonnet", "haiku", "gpt", "minimax"]},
    }


def _merge_runtime(base, extra, env):
    out = dict(base)
    if not isinstance(extra, dict):
        return out
    for key, value in extra.items():
        if isinstance(value, str) and value.startswith("${"):
            value = _expand(value, env)
        if key == "paths" and isinstance(value, dict):
            merged_paths = dict(base["paths"])
            for pk, pv in value.items():
                if isinstance(pv, str) and pv.startswith("${"):
                    pv = _expand(pv, env)
                if pv:
                    merged_paths[pk] = pv
            out["paths"] = merged_paths
        elif key == "codegraph" and isinstance(value, dict):
            merged_cg = dict(base["codegraph"])
            for ck, cv in value.items():
                if cv is None:
                    continue
                if isinstance(cv, list):
                    merged_cg[ck] = list(cv)
                else:
                    merged_cg[ck] = cv
            out["codegraph"] = merged_cg
        elif key in ("memory", "executors", "usage") and isinstance(value, dict):
            merged = dict(base.get(key, {}))
            for ck, cv in value.items():
                if cv is None:
                    continue
                merged[ck] = cv
            out[key] = merged
        elif key == "ui":
            if isinstance(value, str) and value:
                out["ui"] = value
        elif key == "schema":
            out["schema"] = value
    return out


# --- locale ---------------------------------------------------------------

def load_locale(ui, plugin_root):
    """Load locales/<ui>.json; fall back to en; fall back to built-in minimum."""
    ui = ui if ui in ("en", "es") else "en"
    plugin_root = Path(plugin_root)
    candidate = plugin_root / "locales" / f"{ui}.json"
    if not candidate.is_file() and ui != "en":
        candidate = plugin_root / "locales" / "en.json"
    if candidate.is_file():
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return _minimal_locale(ui)


def _minimal_locale(ui):
    if ui == "es":
        return {
            "options": {"index_now": "Indexar ahora", "no_index": "No indexar"},
            "labels": {"yes": "Indexar ahora", "no": "No indexar"},
        }
    return {
        "options": {"index_now": "Index now", "no_index": "Do not index"},
        "labels": {"yes": "Index now", "no": "Do not index"},
    }


# --- logging --------------------------------------------------------------

def log_error(state_dir, hook_name, message):
    try:
        log_path = Path(state_dir) / "hooks.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts} {hook_name} {message}\n")
    except Exception:
        pass  # logging must never fail the hook


# --- session scratch ------------------------------------------------------

def session_scratch(state_dir, hook_name, session_id):
    """Return a Path to a session-scoped JSON scratch file, cleaning old ones."""
    base = Path(state_dir) / "sessions"
    try:
        base.mkdir(parents=True, exist_ok=True)
        _cleanup_sessions(base, max_age_days=7)
    except Exception:
        pass
    safe_sid = "".join(c for c in (session_id or "x") if c.isalnum() or c in "-_") or "x"
    return base / f"{hook_name}-{safe_sid}.json"


def _cleanup_sessions(base, max_age_days):
    cutoff = time.time() - (max_age_days * 86400)
    for entry in base.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except Exception:
            continue