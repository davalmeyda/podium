"""Shared helpers for the test_core_* modules (not a test module itself)."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
FIXTURE_HOME = HERE / "home"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from podium import cli  # noqa: E402

BASE_CONFIG = """\
schema = 1

[language]
response = "es"
domain = "en"

[memory]
url = "${TEST_MEMORY_URL}"

[render.vars]
team = "acme"

[roster_notes]
cascade = ["code: a -> b"]

[[roster]]
id = "writer-fast"
engine = "Fast"
model = "Model-X #none"
responsibility = "Code from a closed brief"
fallback = "haiku"
launch = { kind = "opencode", agent = "writer", model = "prov/Model-X", variant = "none" }

[[agents]]
name = "writer"
role = "writer"
model = "prov/Model-X"
description = "Writer fixture."
deny_mcp = ["browser_*"]

[[agents]]
name = "reviewer"
role = "consultant"
model = "prov/Model-Y"
"""

FAKE_CLAUDE = """\
#!/bin/sh
echo "$@" >> "$FAKE_CLAUDE_LOG"
if [ -n "$FAKE_CLAUDE_FAIL" ]; then
  case "$*" in
    *"$FAKE_CLAUDE_FAIL"*) echo "boom" >&2; exit 1 ;;
  esac
fi
if [ "$1" = "mcp" ]; then
  exec "$FAKE_CLAUDE_PY" "${0%/*}/claude-mcp.py" "$@"
fi
exit 0
"""

# Stands in for `claude mcp add-json|remove` at user scope: edits `<config dir>/.claude.json` like the real CLI.
FAKE_CLAUDE_MCP = """\
import json
import os
import sys

args = sys.argv[2:]
base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~")
path = os.path.join(base, ".claude.json")
try:
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
except (OSError, ValueError):
    doc = {}
servers = doc.setdefault("mcpServers", {})
if args[:1] == ["add-json"]:
    if args[1] in servers:
        sys.stderr.write("MCP server %s already exists in user config\\n" % args[1])
        sys.exit(1)
    servers[args[1]] = json.loads(args[2])
elif args[:1] == ["remove"]:
    if args[1] not in servers:
        sys.stderr.write('No MCP server found with name: "%s"\\n' % args[1])
        sys.exit(1)
    del servers[args[1]]
else:
    sys.exit(2)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(doc, handle, indent=2)
"""


def fake_roster():
    module = types.ModuleType("podium.roster")
    module.generated = lambda config: {"roster_table": "| Engine |\n|---|\n| fake |", "roster_excluded": "",
                                       "fallback_cascade": "", "launch_examples": ""}
    module.render_agent = lambda agent, config, podium_home: (
        "---\ndescription: %s\n---\nagent %s role %s\n" % (agent["description"], agent["name"], agent["role"]))
    return module


class CoreCase(unittest.TestCase):
    """A temp HOME/XDG/PODIUM_* tree, a fake roster module and a CLI runner."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="podium-test-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.claude_log = self.tmp / "claude.log"
        self.env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_STATE_HOME": str(self.home / ".local" / "state"),
            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
            "OPENCODE_CONFIG_DIR": str(self.home / ".config" / "opencode"),
            "PODIUM_CONFIG_DIR": str(self.home / ".config" / "podium"),
            "PODIUM_STATE_DIR": str(self.home / ".local" / "state" / "podium"),
            "PATH": str(self.bin),
            "TEST_MEMORY_URL": "https://memory.example.test/mcp",
            "FAKE_CLAUDE_LOG": str(self.claude_log),
            "FAKE_CLAUDE_PY": sys.executable,
        }
        self.claude_dir = Path(self.env["CLAUDE_CONFIG_DIR"])
        self.oc_dir = Path(self.env["OPENCODE_CONFIG_DIR"])
        self.config_dir = Path(self.env["PODIUM_CONFIG_DIR"])
        self.state_dir = Path(self.env["PODIUM_STATE_DIR"])
        patcher = mock.patch.dict(sys.modules, {"podium.roster": fake_roster()})
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- fixtures
    def write_config(self, text=BASE_CONFIG):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "podium.toml").write_text(text, encoding="utf-8")

    def add_fake_claude(self):
        path = self.bin / "claude"
        path.write_text(FAKE_CLAUDE, encoding="utf-8")
        path.chmod(0o755)
        (self.bin / "claude-mcp.py").write_text(FAKE_CLAUDE_MCP, encoding="utf-8")

    def claude_json(self):
        """Claude's user config as the fake claude wrote it (`{}` when absent)."""
        import json
        path = self.claude_dir / ".claude.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def mcp_calls(self):
        return [call for call in self.claude_calls() if call.startswith("mcp ")]

    def claude_calls(self):
        if not self.claude_log.exists():
            return []
        return self.claude_log.read_text(encoding="utf-8").splitlines()

    def run_cli(self, *argv, **env_extra):
        env = dict(self.env)
        env.update(env_extra)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv), env=env, podium_home=FIXTURE_HOME)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def snapshot(self, root=None):
        """Map of every file under root (default: the temp HOME) to its bytes."""
        root = Path(root) if root else self.tmp
        return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}

    def backups(self, directory):
        return sorted(p.name for p in Path(directory).glob("*.bak-podium-*"))
