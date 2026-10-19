import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/podium-upgrade/skills/agents-upgrade/scripts"


class UpgradeScriptsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.config = self.home / "config"
        self.config.mkdir()
        (self.config / "podium.toml").write_text(
            '[[roster]]\nid="writer"\nlaunch={kind="opencode", agent="writer", model="sample/model", variant="fast"}\n'
            '[[agents]]\nname="writer"\nmodel="sample/model"\nvariant="fast"\n'
            '[roster_notes]\nexcluded=[]\n', encoding="utf-8"
        )
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.home),
            "PODIUM_HOME": str(Path(__file__).resolve().parent.parent),
            "PODIUM_CONFIG_DIR": str(self.config),
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
        })

    def tearDown(self):
        self.temp.cleanup()

    def executable(self, name, text):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + text + "\n", encoding="utf-8")
        path.chmod(0o755)

    def run_script(self, script, *args):
        return subprocess.run(["sh", str(PLUGIN / script), *args], env=self.env,
                              text=True, capture_output=True, check=True).stdout

    def test_roster_json(self):
        result = subprocess.run(["python3", str(PLUGIN / "roster.py")], env=self.env,
                                text=True, capture_output=True, check=True)
        roster = json.loads(result.stdout)
        self.assertEqual(roster["agents"][0]["name"], "writer")
        self.assertEqual(roster["roster"][0]["launch"]["model"], "sample/model")

    def test_preflight_detects_npm_and_native(self):
        self.executable("npm", 'echo "$HOME/npm"')
        self.executable("brew", 'echo "$HOME/brew"')
        npm_prefix = self.home / "npm"
        brew_prefix = self.home / "brew"
        npm_prefix.mkdir()
        brew_prefix.mkdir()
        self.executable("npm", f'echo "{npm_prefix}"')
        self.executable("brew", f'echo "{brew_prefix}"')
        (npm_prefix / "claude").write_text("#!/bin/sh\necho 1\n")
        (npm_prefix / "claude").chmod(0o755)
        self.env["PATH"] = str(npm_prefix) + os.pathsep + str(self.bin) + os.pathsep + os.environ.get("PATH", "")
        self.executable("opencode", 'echo 1')
        output = self.run_script("preflight.sh")
        self.assertIn("claude: 1 [npm]", output)
        self.assertIn("opencode: 1 [native]", output)

    def test_update_dry_run_by_install_method(self):
        prefix = self.home / "brew"
        prefix.mkdir()
        self.executable("brew", f'[ "$1" = --prefix ] && echo "{prefix}" || exit 1')
        self.executable("npm", 'echo /not/npm')
        for tool in ("opencode", "claude"):
            path = prefix / tool
            path.write_text("#!/bin/sh\necho 1\n")
            path.chmod(0o755)
        self.executable("opencode", 'echo 1')
        self.executable("claude", 'echo 1')
        # Put brew-installed stubs first while retaining the update-command stubs.
        self.env["PATH"] = f"{prefix}:{self.bin}:" + os.environ.get("PATH", "")
        output = self.run_script("update-clis.sh", "--dry-run")
        self.assertIn("brew upgrade opencode", output)
        self.assertIn("brew upgrade --cask claude-code", output)

    def test_update_dry_run_native(self):
        self.executable("brew", "exit 1")
        self.executable("npm", "echo /not/npm")
        self.executable("opencode", "echo 1")
        self.executable("claude", "echo 1")
        output = self.run_script("update-clis.sh", "--dry-run")
        self.assertIn("opencode upgrade --major || opencode upgrade", output)
        self.assertIn("claude update", output)

    def test_update_dry_run_npm(self):
        prefix = self.home / "npm-global"
        (prefix / "bin").mkdir(parents=True)
        self.executable("brew", "exit 1")
        self.executable("npm", f'[ "$1" = prefix ] && echo "{prefix}" || exit 1')
        for tool in ("opencode", "claude"):
            path = prefix / "bin" / tool
            path.write_text("#!/bin/sh\necho 1\n")
            path.chmod(0o755)
        self.env["PATH"] = f"{prefix / 'bin'}:{self.bin}:" + os.environ.get("PATH", "")
        output = self.run_script("update-clis.sh", "--dry-run")
        self.assertIn("npm install -g opencode-ai@latest", output)
        self.assertIn("npm install -g @anthropic-ai/claude-code@latest", output)


if __name__ == "__main__":
    unittest.main()
