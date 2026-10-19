"""Tests for ``podium.detect`` (ARCHITECTURE.md §12).

The detect function is read-only and never raises. We exercise it with a fake
``PATH`` populated by tiny shell scripts that print the version lines each CLI
emits, and verify the function reports the right shape both with and without
the tools present.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# Make ``podium`` importable when the tests are run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from podium import detect  # noqa: E402


def _make_stub_dir(tmp: Path) -> Path:
    """Create a directory of fake CLI stubs and return its path."""
    d = tmp / "stubs"
    d.mkdir()
    # Make every stub executable on disk.
    for name, body in _STUBS.items():
        script = d / name
        script.write_text(body)
        script.chmod(0o755)
    return d


_STUBS = {
    "claude": "#!/bin/sh\necho 'claude 2.3.4 (build abc)'\n",
    "opencode": "#!/bin/sh\necho 'opencode 2.10.0'\n",
    "codegraph": "#!/bin/sh\necho 'codegraph 1.4.7'\n",
    "git": "#!/bin/sh\necho 'git version 2.39.0'\n",
}


class DetectShapeTests(unittest.TestCase):
    """The output envelope must match the contract key-for-key."""

    def setUp(self) -> None:
        self.tmp = Path(self._temp())
        self.stubs = _make_stub_dir(self.tmp)
        self._saved_path = os.environ.get("PATH")
        os.environ["PATH"] = f"{self.stubs}{os.pathsep}{self._saved_path or ''}"

    def tearDown(self) -> None:
        if self._saved_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._saved_path

    def _temp(self) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="podium-detect-")

    def _paths(self) -> dict[str, str]:
        return {
            "home": str(self.tmp),
            "claude_dir": str(self.tmp / ".claude"),
            "opencode_config_dir": str(self.tmp / ".config" / "opencode"),
            "config_dir": str(self.tmp / ".config" / "podium"),
            "state_dir": str(self.tmp / ".local" / "state" / "podium"),
        }

    def test_envelope_keys(self) -> None:
        snapshot = detect.run(self._paths())
        self.assertEqual(
            set(snapshot),
            {"os", "kernel", "python", "tools", "opencode", "claude", "podium"},
        )
        # Round-trip through JSON to make sure it's serialisable.
        json.dumps(snapshot)

    def test_os_is_a_known_value(self) -> None:
        snapshot = detect.run(self._paths())
        self.assertIn(snapshot["os"], {"linux", "darwin", "other"})

    def test_python_matches_running_interpreter(self) -> None:
        snapshot = detect.run(self._paths())
        self.assertEqual(snapshot["python"], detect._python_version())

    def test_tools_present_with_stubs(self) -> None:
        snapshot = detect.run(self._paths())
        for name in ("claude", "opencode", "codegraph", "git"):
            entry = snapshot["tools"][name]
            self.assertIsNotNone(entry, name)
            self.assertTrue(entry["path"].startswith(str(self.stubs)))
            self.assertIn(name, entry["version"])

    def test_tools_absent_when_no_stubs(self) -> None:
        # Replace PATH with an empty directory.
        empty_dir = self.tmp / "empty"
        empty_dir.mkdir()
        os.environ["PATH"] = str(empty_dir)
        snapshot = detect.run(self._paths())
        for name in ("claude", "opencode", "codegraph", "git"):
            self.assertIsNone(snapshot["tools"][name], name)


class DetectOpencodeSectionTests(unittest.TestCase):
    """Populate a fake OpenCode config and check the opencode block."""

    def setUp(self) -> None:
        self.tmp = Path(self._temp())
        self.stubs = _make_stub_dir(self.tmp)
        self._saved_path = os.environ.get("PATH")
        os.environ["PATH"] = f"{self.stubs}{os.pathsep}{self._saved_path or ''}"

    def tearDown(self) -> None:
        if self._saved_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._saved_path

    def _temp(self) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="podium-detect-")

    def _paths(self, opencode: Path) -> dict[str, str]:
        return {
            "home": str(self.tmp),
            "claude_dir": str(self.tmp / ".claude"),
            "opencode_config_dir": str(opencode),
            "config_dir": str(self.tmp / ".config" / "podium"),
            "state_dir": str(self.tmp / ".local" / "state" / "podium"),
        }

    def test_config_files_lists_existing_only(self) -> None:
        cfg = self.tmp / "opencode_cfg"
        cfg.mkdir()
        (cfg / "opencode.json").write_text("{}")
        # .jsonc missing on purpose
        snapshot = detect.run(self._paths(cfg))
        self.assertEqual(snapshot["opencode"]["config_files"], [str(cfg / "opencode.json")])

    def test_mcp_server_names_extracted(self) -> None:
        cfg = self.tmp / "opencode_cfg"
        cfg.mkdir()
        (cfg / "opencode.json").write_text(
            '{"mcp": {"graphiti-memory": {}, "codegraph": {}}}'
        )
        snapshot = detect.run(self._paths(cfg))
        self.assertEqual(
            snapshot["opencode"]["mcp"], ["codegraph", "graphiti-memory"]
        )

    def test_agents_mark_podium_owned(self) -> None:
        cfg = self.tmp / "opencode_cfg"
        agents = cfg / "agents"
        agents.mkdir(parents=True)
        (agents / "minimax.md").write_text("---\ndescription: test\nmode: primary\nmodel: minimax/MiniMax-M3\n---\n# podium:agent\n")
        (agents / "user-agent.md").write_text("# user-owned\n")
        snapshot = detect.run(self._paths(cfg))
        agents_map = {
            entry["name"]: entry["podium_owned"]
            for entry in snapshot["opencode"]["agents"]
        }
        self.assertTrue(agents_map["minimax"])
        self.assertFalse(agents_map["user-agent"])


class DetectClaudeSectionTests(unittest.TestCase):
    """``claude.legacy_hooks`` and ``claude.plugins_installed``."""

    def setUp(self) -> None:
        self.tmp = Path(self._temp())
        self._saved_path = os.environ.get("PATH")
        os.environ["PATH"] = self.tmp.as_posix()

    def tearDown(self) -> None:
        if self._saved_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._saved_path

    def _temp(self) -> str:
        import tempfile

        return tempfile.mkdtemp(prefix="podium-detect-")

    def _paths(self, claude: Path) -> dict[str, str]:
        return {
            "home": str(self.tmp),
            "claude_dir": str(claude),
            "opencode_config_dir": str(self.tmp / ".config" / "opencode"),
            "config_dir": str(self.tmp / ".config" / "podium"),
            "state_dir": str(self.tmp / ".local" / "state" / "podium"),
        }

    def test_legacy_hooks_detected(self) -> None:
        claude = self.tmp / "claude"
        claude.mkdir()
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3",
                                "args": [
                                    "$HOME/.claude/hooks/codegraph-gate.py"
                                ],
                            }
                        ]
                    }
                ]
            },
            "enabledPlugins": {
                "podium-codegraph@podium": True,
                "@podium": True,
            },
        }
        (claude / "settings.json").write_text(json.dumps(settings))
        snapshot = detect.run(self._paths(claude))
        legacy = " ".join(snapshot["claude"]["legacy_hooks"])
        self.assertIn("codegraph-gate.py", legacy)
        self.assertIn("podium-codegraph@podium", snapshot["claude"]["plugins_installed"])

    def test_no_legacy_when_settings_absent(self) -> None:
        claude = self.tmp / "claude"
        claude.mkdir()
        snapshot = detect.run(self._paths(claude))
        self.assertEqual(snapshot["claude"]["legacy_hooks"], [])
        self.assertEqual(snapshot["claude"]["plugins_installed"], [])


class DetectRunsNoRaiseTests(unittest.TestCase):
    """detect.run() must never raise, even on a totally broken filesystem."""

    def test_missing_paths_do_not_raise(self) -> None:
        # POINT to a directory tree that is empty; every optional file is gone.
        snapshot = detect.run(
            {
                "home": "/nonexistent/podium-home",
                "claude_dir": "/nonexistent/podium-home/.claude",
                "opencode_config_dir": "/nonexistent/podium-home/.config/opencode",
                "config_dir": "/nonexistent/podium-home/.config/podium",
                "state_dir": "/nonexistent/podium-home/.local/state/podium",
            }
        )
        # Even with nothing to find, the shape holds.
        self.assertEqual(snapshot["podium"]["config_exists"], False)
        self.assertEqual(snapshot["podium"]["ledger_exists"], False)
        self.assertEqual(snapshot["opencode"]["agents"], [])
        self.assertEqual(snapshot["opencode"]["mcp"], [])


if __name__ == "__main__":
    unittest.main()
