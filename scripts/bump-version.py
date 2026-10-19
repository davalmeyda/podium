#!/usr/bin/env python3
"""Set one version everywhere: the CLI and every plugin manifest.

Usage: scripts/bump-version.py 0.2.0
Then add a "## [0.2.0]" section to CHANGELOG.md, commit, and tag v0.2.0.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def main():
    if len(sys.argv) != 2 or not SEMVER.match(sys.argv[1]):
        sys.exit("usage: bump-version.py <MAJOR.MINOR.PATCH>")
    version = sys.argv[1]

    init = ROOT / "podium" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    text, count = re.subn(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{version}"', text)
    if count != 1:
        sys.exit("podium/__init__.py has no __version__ assignment")
    init.write_text(text, encoding="utf-8")

    for manifest in sorted(ROOT.glob("plugins/*/.claude-plugin/plugin.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["version"] = version
        manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{manifest.relative_to(ROOT)} -> {version}")
    print(f"podium/__init__.py -> {version}")


if __name__ == "__main__":
    main()
