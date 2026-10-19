#!/usr/bin/env python3
"""Fail unless the CLI and every plugin declare the same version (and match --tag if given)."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def versions():
    init = (ROOT / "podium" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    found = {"podium/__init__.py": match.group(1) if match else None}
    for manifest in sorted(ROOT.glob("plugins/*/.claude-plugin/plugin.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        found[str(manifest.relative_to(ROOT))] = data.get("version")
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="release tag such as v1.2.3")
    args = parser.parse_args()
    found = versions()
    distinct = set(found.values())
    if len(distinct) != 1 or None in distinct:
        for path, version in found.items():
            print(f"{path}: {version}")
        sys.exit("versions differ: run scripts/bump-version.py <version>")
    version = distinct.pop()
    if args.tag and args.tag != f"v{version}":
        sys.exit(f"tag {args.tag} does not match code version {version}")
    print(version)


if __name__ == "__main__":
    main()
