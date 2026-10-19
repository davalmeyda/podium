"""Path resolution (ARCHITECTURE.md section 3). This is the only module that resolves them."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


@dataclass(frozen=True)
class Paths:
    home: Path
    claude_dir: Path
    opencode_config_dir: Path
    opencode_data_dir: Path
    config_dir: Path
    state_dir: Path
    podium_home: Path


def _env_path(env: Mapping[str, str], key: str, home: Path) -> Optional[Path]:
    value = env.get(key)
    if not value:
        return None
    if value == "~" or value.startswith("~/"):
        return home / value[2:] if value != "~" else home
    return Path(value)


def _xdg(env: Mapping[str, str], key: str, home: Path) -> Optional[Path]:
    """XDG base dirs must be absolute; relative values are ignored (per the XDG spec)."""
    value = _env_path(env, key, home)
    if value is not None and value.is_absolute():
        return value
    return None


def resolve(env: Optional[Mapping[str, str]] = None) -> Paths:
    """Resolve every directory podium uses from the environment (default: os.environ)."""
    if env is None:
        env = os.environ
    home_value = env.get("HOME")
    home = Path(home_value) if home_value else Path(os.path.expanduser("~"))

    xdg_config = _xdg(env, "XDG_CONFIG_HOME", home) or (home / ".config")
    xdg_data = _xdg(env, "XDG_DATA_HOME", home) or (home / ".local" / "share")
    xdg_state = _xdg(env, "XDG_STATE_HOME", home) or (home / ".local" / "state")

    claude_dir = _env_path(env, "CLAUDE_CONFIG_DIR", home) or (home / ".claude")
    opencode_config_dir = _env_path(env, "OPENCODE_CONFIG_DIR", home) or (xdg_config / "opencode")
    opencode_data_dir = xdg_data / "opencode"
    config_dir = _env_path(env, "PODIUM_CONFIG_DIR", home) or (xdg_config / "podium")
    state_dir = _env_path(env, "PODIUM_STATE_DIR", home) or (xdg_state / "podium")
    podium_home = Path(__file__).resolve().parent.parent

    return Paths(
        home=home,
        claude_dir=claude_dir,
        opencode_config_dir=opencode_config_dir,
        opencode_data_dir=opencode_data_dir,
        config_dir=config_dir,
        state_dir=state_dir,
        podium_home=podium_home,
    )
