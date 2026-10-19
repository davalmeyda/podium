#!/usr/bin/env python3
"""Print the CHANGELOG.md section for a version (accepts "v1.2.3" or "1.2.3")."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: changelog-section.py <version>")
    version = sys.argv[1].lstrip("v")
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not match:
        sys.exit(f"CHANGELOG.md has no section for {version}")
    print(match.group(1).strip())


if __name__ == "__main__":
    main()
