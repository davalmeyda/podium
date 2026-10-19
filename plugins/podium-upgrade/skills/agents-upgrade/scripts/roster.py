#!/usr/bin/env python3
"""Print the active podium roster and agents as JSON."""
import json
import os
import shutil
import sys
from pathlib import Path


def _podium_home():
    """The podium checkout: $PODIUM_HOME, else the target of the `podium` CLI link, else the default."""
    if os.environ.get("PODIUM_HOME"):
        return Path(os.environ["PODIUM_HOME"])
    cli = shutil.which("podium")
    if cli:
        return Path(os.path.realpath(cli)).parent.parent
    return Path.home() / ".local/share/podium/repo"

def main():
    try:
        import tomllib
    except ImportError:
        sys.path.insert(0, str(_podium_home()))
        try:
            import tomli as tomllib
        except ImportError:
            from podium._vendor import tomli as tomllib
    config_dir = Path(os.environ.get("PODIUM_CONFIG_DIR", Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "podium"))
    with (config_dir / "podium.toml").open("rb") as stream:
        config = tomllib.load(stream)
    result = {key: config.get(key, default) for key, default in (("roster", []), ("agents", []), ("roster_notes", {}))}
    print(json.dumps(result, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
