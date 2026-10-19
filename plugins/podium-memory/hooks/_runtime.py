"""Hook runtime helpers shared by podium plugins.

Implements the runtime contract documented in ARCHITECTURE.md §9.2:

- resolve the podium config_dir (with the same env vars the CLI uses)
- load runtime.json from config_dir, falling back to built-in defaults
- load locales/<ui>.json from a plugin directory (fallback to "en")
- append one "<iso-time> <hook> <error>" line to state_dir/hooks.log
- give each session its own scratch state file under state_dir/sessions,
  cleaning up files older than 7 days opportunistically.

Failures here are swallowed and logged; callers stay simple.
"""

import json
import os
import sys
import time
from pathlib import Path


# --- path resolution (mirrors podium/paths.py, no import) ---

def _env(name, fallback):
    val = os.environ.get(name)
    return val if val else fallback


def resolve_paths(env=None):
    """Resolve the platform paths a hook needs. Returns a plain dict."""
    env = env if env is not None else os.environ
    home = Path.home()

    claude_dir = Path(_env("CLAUDE_CONFIG_DIR", str(home / ".claude")))
    opencode_data_dir = Path(
        _env("XDG_DATA_HOME", str(home / ".local" / "share")) + "/opencode"
    )
    config_dir = Path(
        _env(
            "PODIUM_CONFIG_DIR",
            _env("XDG_CONFIG_HOME", str(home / ".config")) + "/podium",
        )
    )
    state_dir = Path(
        _env(
            "PODIUM_STATE_DIR",
            _env("XDG_STATE_HOME", str(home / ".local" / "state")) + "/podium",
        )
    )

    podium_home = Path(__file__).resolve()
    # walk up until we find a directory containing bin/podium, or fall back
    for parent in [podium_home, *podium_home.parents]:
        if (parent / "bin" / "podium").exists():
            podium_home = parent
            break
    else:
        podium_home = podium_home.parent

    return {
        "home": str(home),
        "podium_home": str(podium_home),
        "claude_dir": str(claude_dir),
        "opencode_data_dir": str(opencode_data_dir),
        "config_dir": str(config_dir),
        "state_dir": str(state_dir),
    }


# --- runtime.json ---

_BUILTIN_DEFAULTS = {
    "schema": 1,
    "ui": "en",
    "paths": {},
    "codegraph": {
        "gate": True,
        "nudge_every": 4,
        "roots": [],
        "manifests": [],
        "ignored": [],
    },
    "memory": {
        "mcp_server": "graphiti-memory",
        "min_edits": 8,
        "min_executor_runs": 2,
        "cooldown_seconds": 2700,
    },
    "executors": {
        "launcher_regex": r"\bopencode\s+run\s",
    },
    "usage": {
        "model_order": ["opus", "sonnet", "haiku", "gpt", "minimax"],
    },
}


def _deep_merge(defaults, overrides):
    """Merge overrides into defaults recursively; lists/scalars are replaced."""
    out = dict(defaults)
    for key, val in (overrides or {}).items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(val, dict)
        ):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_runtime(paths, env=None):
    """Load runtime.json from config_dir with built-in defaults."""
    env = env if env is not None else os.environ
    cfg_path = Path(paths["config_dir"]) / "runtime.json"
    data = {}
    if cfg_path.is_file():
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            log_hook_error(paths, "runtime-load", str(exc))
    cfg = _deep_merge(_BUILTIN_DEFAULTS, data)
    cfg["paths"] = _deep_merge(paths, cfg.get("paths") or {})
    cfg["ui"] = cfg.get("ui") or env.get("PODIUM_UI") or "en"
    return cfg


# --- locales ---

def load_locale(plugin_dir, ui):
    """Load locales/<ui>.json from a plugin directory, fallback to 'en'."""
    plugin_dir = Path(plugin_dir)
    for lang in (ui, "en"):
        candidate = plugin_dir / "locales" / f"{lang}.json"
        if candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:
                log_hook_error(
                    {"state_dir": str(plugin_dir.parent.parent)},
                    "locale-load",
                    f"{lang}: {exc}",
                )
    return {}


# --- hooks.log ---

def log_hook_error(paths, hook_name, message):
    """Append one error line to state_dir/hooks.log; never raises."""
    try:
        state_dir = Path(paths["state_dir"])
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / "hooks.log", "a", encoding="utf-8") as fh:
            fh.write(
                "{0} {1} {2}\n".format(
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                    hook_name,
                    message.replace("\n", " "),
                )
            )
    except Exception:
        # last-ditch: try stderr
        try:
            print(message, file=sys.stderr)
        except Exception:
            pass


# --- session scratch ---

SCRATCH_TTL_SECONDS = 7 * 24 * 60 * 60


def scratch_path(paths, hook_name, session_id):
    """Path to the per-session scratch file for a given hook."""
    safe = re_safe(session_id or "session")
    return (
        Path(paths["state_dir"])
        / "sessions"
        / f"{hook_name}-{safe}.json"
    )


def re_safe(text):
    """Make a session id safe to use as a filename."""
    out = []
    for ch in text:
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "session"


def cleanup_scratch(paths, now=None):
    """Delete session scratch files older than SCRATCH_TTL_SECONDS."""
    now = now if now is not None else time.time()
    sessions = Path(paths["state_dir"]) / "sessions"
    if not sessions.is_dir():
        return
    for entry in sessions.iterdir():
        try:
            if not entry.is_file():
                continue
            if now - entry.stat().st_mtime > SCRATCH_TTL_SECONDS:
                entry.unlink()
        except OSError:
            continue


def read_scratch(path):
    """Read a scratch JSON file; return {} on any failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def write_scratch(path, data):
    """Atomically write a scratch JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)