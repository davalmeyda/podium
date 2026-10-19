"""Configuration loading (ARCHITECTURE.md section 4): validate, merge defaults, expand ${VAR}."""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

try:  # Python >= 3.11
    import tomllib  # type: ignore
except ImportError:  # pragma: no cover - exercised only on Python < 3.11
    from podium._vendor import tomli as tomllib  # type: ignore

SCHEMA_VERSION = 1
CONFIG_FILENAME = "podium.toml"

MODULES = ("rules", "executors", "codegraph", "memory", "usage", "upgrade")
ROLES = ("writer", "consultant", "overflow")
LAUNCH_KINDS = ("opencode", "claude", "principal")
UI_LOCALES = ("en", "es")
LANGUAGE_NAMES = {"en": "English", "es": "Spanish"}


class ConfigError(Exception):
    """Invalid, missing or unexpandable configuration."""


class _Free:
    """Marker: a table whose keys are free-form (render.vars)."""


FREE = _Free()

DEFAULTS: Dict[str, Any] = {
    "language": {"response": "en", "domain": "en", "ui": "en"},
    "modules": {name: True for name in MODULES},
    "principal": {
        "always_background": True,
        "subagents_preauthorized": True,
        "forbid_workflow_tool": True,
    },
    "launcher": {"opencode": "opencode run --auto"},
    "roster_notes": {"excluded": [], "cascade": []},
    "memory": {
        "backend": "graphiti",
        "mcp_server": "graphiti-memory",
        "url": "",
        "group": "main",
        "headers": FREE,
        "mcp_options": FREE,
        "stop_hook": {"min_edits": 8, "min_executor_runs": 2, "cooldown_seconds": 2700},
    },
    "codegraph": {
        "gate": True,
        "nudge_every": 4,
        "roots": [],
        "extra_manifests": [],
        "extra_ignored": [],
    },
    "usage": {"model_order": ["opus", "sonnet", "haiku", "gpt", "minimax"]},
    "render": {"vars": FREE},
}

_TOP_LEVEL_KEYS = {"schema", "roster", "agents"} | set(DEFAULTS)

_ROSTER_KEYS = {"id", "engine", "model", "responsibility", "fallback", "launch"}
_ROSTER_REQUIRED = ("id", "engine", "model")
_LAUNCH_KEYS = {
    "opencode": {"kind", "agent", "model", "variant"},
    "claude": {"kind", "model", "effort"},
    "principal": {"kind"},
}
_LAUNCH_REQUIRED = {"opencode": ("agent", "model"), "claude": ("model",), "principal": ()}
_AGENT_KEYS = {"name", "role", "model", "description", "deny_mcp"}
_AGENT_REQUIRED = ("name", "role", "model")
_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


# --------------------------------------------------------------------------- loading

def load_toml(path: Path) -> Dict[str, Any]:
    """Parse a TOML file with tomllib (or the vendored tomli)."""
    try:
        with open(str(path), "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc))
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError("invalid TOML in %s: %s" % (path, exc))


def load(config_dir: Path, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Load, validate and expand `config_dir/podium.toml`; returns the merged dict."""
    if env is None:
        env = os.environ
    path = Path(config_dir) / CONFIG_FILENAME
    if not path.is_file():
        raise ConfigError("config not found: %s (run `podium init`)" % path)
    return from_dict(load_toml(path), env)


def from_dict(raw: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Validate a parsed TOML mapping, merge defaults, expand ${VAR}, add derived keys."""
    if env is None:
        env = os.environ
    if not isinstance(raw, Mapping):
        raise ConfigError("config must be a table")
    for key in raw:
        if key not in _TOP_LEVEL_KEYS:
            raise ConfigError("unknown key: %s" % key)

    schema = raw.get("schema", SCHEMA_VERSION)
    if isinstance(schema, bool) or schema != SCHEMA_VERSION:
        raise ConfigError("unsupported schema: %r (expected %d)" % (schema, SCHEMA_VERSION))

    merged: Dict[str, Any] = {"schema": SCHEMA_VERSION}
    for section, defaults in DEFAULTS.items():
        merged[section] = _merge(defaults, raw.get(section, {}), section)
    merged["roster"] = _validate_roster(raw.get("roster", []))
    merged["agents"] = _validate_agents(raw.get("agents", []))

    _validate_semantics(merged)
    expanded = _expand(merged, env, "")
    lang = expanded["language"]
    lang["response_name"] = LANGUAGE_NAMES.get(lang["response"], lang["response"])
    lang["domain_name"] = LANGUAGE_NAMES.get(lang["domain"], lang["domain"])
    return expanded


# --------------------------------------------------------------------------- validation

def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "table"
    return type(value).__name__


def _check_scalar(default: Any, value: Any, dotted: str) -> Any:
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ConfigError("%s must be a boolean, got %s" % (dotted, _type_name(value)))
    elif isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError("%s must be an integer, got %s" % (dotted, _type_name(value)))
        if value < 0:
            raise ConfigError("%s must not be negative" % dotted)
    elif isinstance(default, str):
        if not isinstance(value, str):
            raise ConfigError("%s must be a string, got %s" % (dotted, _type_name(value)))
    elif isinstance(default, list):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ConfigError("%s must be an array of strings" % dotted)
        return list(value)
    return value


def _default_of(default: Any) -> Any:
    if default is FREE:
        return {}
    if isinstance(default, dict):
        return {key: _default_of(value) for key, value in default.items()}
    return copy.deepcopy(default)


def _merge(defaults: Any, user: Any, dotted: str) -> Any:
    if defaults is FREE:
        if not isinstance(user, dict):
            raise ConfigError("%s must be a table" % dotted)
        for key, value in user.items():
            _check_free_value(value, "%s.%s" % (dotted, key))
        return copy.deepcopy(user)
    if isinstance(defaults, dict):
        if not isinstance(user, dict):
            raise ConfigError("%s must be a table, got %s" % (dotted, _type_name(user)))
        for key in user:
            if key not in defaults:
                raise ConfigError("unknown key: %s.%s" % (dotted, key))
        return {
            key: _merge(default, user[key], "%s.%s" % (dotted, key))
            if key in user
            else _default_of(default)
            for key, default in defaults.items()
        }
    return _check_scalar(defaults, user, dotted)


def _check_free_value(value: Any, dotted: str) -> None:
    if isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list) and all(isinstance(i, (str, int, float, bool)) for i in value):
        return
    raise ConfigError("%s must be a string, number, boolean or array of those" % dotted)


def _check_keys(table: Any, allowed: set, required: tuple, dotted: str) -> None:
    if not isinstance(table, dict):
        raise ConfigError("%s must be a table, got %s" % (dotted, _type_name(table)))
    for key in table:
        if key not in allowed:
            raise ConfigError("unknown key: %s.%s" % (dotted, key))
    for key in required:
        if key not in table:
            raise ConfigError("missing required key: %s.%s" % (dotted, key))


def _str_field(table: Dict[str, Any], key: str, dotted: str, default: str = "") -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigError("%s.%s must be a string, got %s" % (dotted, key, _type_name(value)))
    return value


def _validate_roster(rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        raise ConfigError("roster must be an array of tables")
    out: List[Dict[str, Any]] = []
    seen = set()
    for index, row in enumerate(rows):
        dotted = "roster[%d]" % index
        _check_keys(row, _ROSTER_KEYS, _ROSTER_REQUIRED, dotted)
        item: Dict[str, Any] = {
            "id": _str_field(row, "id", dotted),
            "engine": _str_field(row, "engine", dotted),
            "model": _str_field(row, "model", dotted),
            "responsibility": _str_field(row, "responsibility", dotted),
            "fallback": _str_field(row, "fallback", dotted),
        }
        if not item["id"]:
            raise ConfigError("%s.id must not be empty" % dotted)
        if item["id"] in seen:
            raise ConfigError("duplicate roster id: %s" % item["id"])
        seen.add(item["id"])
        item["launch"] = _validate_launch(row.get("launch", {"kind": "principal"}), dotted + ".launch")
        out.append(item)
    return out


def _validate_launch(launch: Any, dotted: str) -> Dict[str, Any]:
    if not isinstance(launch, dict):
        raise ConfigError("%s must be a table, got %s" % (dotted, _type_name(launch)))
    kind = launch.get("kind")
    if kind not in LAUNCH_KINDS:
        raise ConfigError("%s.kind must be one of: %s" % (dotted, ", ".join(LAUNCH_KINDS)))
    _check_keys(launch, _LAUNCH_KEYS[kind], _LAUNCH_REQUIRED[kind], dotted)
    result: Dict[str, Any] = {"kind": kind}
    for key in sorted(_LAUNCH_KEYS[kind] - {"kind"}):
        if key in launch or key in ("variant", "effort"):
            result[key] = _str_field(launch, key, dotted)
    return result


def _validate_agents(rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        raise ConfigError("agents must be an array of tables")
    out: List[Dict[str, Any]] = []
    seen = set()
    for index, row in enumerate(rows):
        dotted = "agents[%d]" % index
        _check_keys(row, _AGENT_KEYS, _AGENT_REQUIRED, dotted)
        item: Dict[str, Any] = {
            "name": _str_field(row, "name", dotted),
            "role": _str_field(row, "role", dotted),
            "model": _str_field(row, "model", dotted),
            "description": _str_field(row, "description", dotted),
        }
        if not _AGENT_NAME_RE.match(item["name"]):
            raise ConfigError("%s.name is not a valid file name: %r" % (dotted, item["name"]))
        if item["role"] not in ROLES:
            raise ConfigError("%s.role must be one of: %s" % (dotted, ", ".join(ROLES)))
        if item["name"] in seen:
            raise ConfigError("duplicate agent name: %s" % item["name"])
        seen.add(item["name"])
        deny = row.get("deny_mcp", [])
        if not isinstance(deny, list) or not all(isinstance(g, str) for g in deny):
            raise ConfigError("%s.deny_mcp must be an array of strings" % dotted)
        item["deny_mcp"] = list(deny)
        out.append(item)
    return out


def _validate_semantics(cfg: Dict[str, Any]) -> None:
    if cfg["language"]["ui"] not in UI_LOCALES:
        raise ConfigError(
            "language.ui must be one of: %s, got %r" % (", ".join(UI_LOCALES), cfg["language"]["ui"])
        )
    for key in ("response", "domain"):
        if not cfg["language"][key]:
            raise ConfigError("language.%s must not be empty" % key)


# --------------------------------------------------------------------------- expansion

def _expand_string(value: str, env: Mapping[str, str], dotted: str) -> str:
    def repl(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in env:
            raise ConfigError(
                "environment variable %s is not set (used in %s)" % (name, dotted or "config")
            )
        return env[name]

    return _VAR_RE.sub(repl, value)


def _expand(value: Any, env: Mapping[str, str], dotted: str) -> Any:
    if isinstance(value, str):
        return _expand_string(value, env, dotted)
    if isinstance(value, list):
        return [_expand(item, env, "%s[%d]" % (dotted, i)) for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {
            key: _expand(item, env, "%s.%s" % (dotted, key) if dotted else key)
            for key, item in value.items()
        }
    return value


# --------------------------------------------------------------------------- helpers

def module_enabled(config: Mapping[str, Any], name: str) -> bool:
    """True when `[modules] <name>` is enabled in a loaded config."""
    return bool(config.get("modules", {}).get(name, False))
