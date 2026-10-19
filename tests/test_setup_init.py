"""Tests for ``podium.init`` (ARCHITECTURE.md §12).

We use a temporary ``config_dir``/``state_dir`` and a tiny roster preset that
lives inside the tree the test itself creates. The preset is read by
``init.run`` verbatim; we do not require a real preset TOML to round-trip.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from podium import init  # noqa: E402


def _make_paths(tmp: Path) -> dict[str, str]:
    """Build a minimal paths mapping rooted at the test tmp directory."""
    return {
        # ``home`` is the repo root: init uses it to find presets.
        "home": str(tmp / "podium-home"),
        "config_dir": str(tmp / "podium-home" / ".config" / "podium"),
        "state_dir": str(tmp / "podium-home" / ".local" / "state" / "podium"),
    }


def _install_preset(home: Path, name: str, body: str) -> None:
    """Drop a fake preset file into ``podium/presets/<name>.toml``."""
    presets = home / "podium" / "presets"
    presets.mkdir(parents=True, exist_ok=True)
    (presets / f"{name}.toml").write_text(body)


def _install_stubs(home: Path) -> Path:
    """Plant an ``opencode`` stub that prints no provider names.

    We force a deterministic empty provider list so the "missing providers"
    warning path is exercised regardless of the host's real credentials.
    """
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "opencode"
    stub.write_text(
        "#!/bin/sh\n"
        "# Stub: prints nothing for `auth list` so providers come back empty.\n"
        "if [ \"$1\" = \"auth\" ] && [ \"$2\" = \"list\" ]; then\n"
        "    exit 0\n"
        "fi\n"
        "# Anything else: pretend the binary exits and emits no output.\n"
        "exit 0\n"
    )
    stub.chmod(0o755)
    return bin_dir


def _baseline_answers(preset: str) -> dict:
    """A complete answers dict that should always succeed in non-interactive mode."""
    return {
        "language.response": "en",
        "language.domain": "en",
        "language.ui": "en",
        "modules": ["rules", "executors", "codegraph", "memory", "usage", "upgrade"],
        "memory.url": "",
        "roster_preset": preset,
        "adopt": False,
        "overwrite": False,
    }


class InitBase(unittest.TestCase):
    """Common setup: install a stub opencode that lists no providers."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="podium-init-"))
        self.paths = _make_paths(self.tmp)
        self._saved_path = os.environ.get("PATH")
        self.stub_bin = _install_stubs(Path(self.paths["home"]))
        # Prepend the stub dir so the fake opencode wins over any host binary.
        os.environ["PATH"] = f"{self.stub_bin}{os.pathsep}{self._saved_path or ''}"

    def tearDown(self) -> None:
        if self._saved_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._saved_path


class InitRealPresetTests(InitBase):
    """The shipped presets must combine with init's header into valid TOML."""

    def _run_with(self, preset: str) -> dict:
        repo = Path(__file__).resolve().parents[1]
        body = (repo / "podium" / "presets" / f"{preset}.toml").read_text(encoding="utf-8")
        _install_preset(Path(self.paths["home"]), preset, body)
        out = init.run(self.paths, _baseline_answers(preset))
        from podium.config import load_toml

        return load_toml(out)

    def test_opencode_multi(self) -> None:
        data = self._run_with("opencode-multi")
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["language"]["response"], "en")
        self.assertEqual(sorted(a["name"] for a in data["agents"]), ["luna", "minimax", "sol"])

    def test_claude_only(self) -> None:
        data = self._run_with("claude-only")
        self.assertEqual(data["schema"], 1)
        self.assertNotIn("agents", data)

    def test_custom_preset(self) -> None:
        # Defect 3: `roster_preset = "custom"` must work end to end with the
        # shipped ``podium/presets/custom.toml`` (no schema/language/modules/
        # principal/launcher, only the principal roster row, commented examples
        # and a roster_notes block). The resulting ``podium.toml`` must load
        # via ``config.load`` and render exactly one roster row.
        data = self._run_with("custom")
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["language"]["response"], "en")
        # No `[[agents]]` in the preset means config.load returns no agents key.
        self.assertNotIn("agents", data)
        self.assertEqual(len(data["roster"]), 1)
        self.assertEqual(data["roster"][0]["id"], "principal")
        self.assertEqual(data["roster"][0]["launch"]["kind"], "principal")


class InitCleanTests(InitBase):
    """init on a completely empty config_dir must write a usable podium.toml."""

    def setUp(self) -> None:
        super().setUp()
        _install_preset(
            Path(self.paths["home"]),
            "opencode-multi",
            '[[agents]]\nname = "minimax-fast"\nrole = "writer"\n'
            'model = "minimax/MiniMax-M3"\ndescription = "m"\n',
        )

    def test_writes_podium_toml(self) -> None:
        out = init.run(self.paths, _baseline_answers("opencode-multi"))
        self.assertTrue(out.is_file())
        text = out.read_text(encoding="utf-8")
        # The header sections we own must be present…
        self.assertIn("schema = 1", text)
        self.assertIn("[language]", text)
        self.assertIn("[modules]", text)
        self.assertIn("[principal]", text)
        # …and the preset body must be appended verbatim after them.
        self.assertIn('name = "minimax-fast"', text)
        self.assertIn('role = "writer"', text)

    def test_creates_config_dir(self) -> None:
        cfg = Path(self.paths["config_dir"])
        self.assertFalse(cfg.exists())
        init.run(self.paths, _baseline_answers("opencode-multi"))
        self.assertTrue(cfg.is_dir())

    def test_opencode_multi_with_missing_providers_adds_warning(self) -> None:
        # The stub opencode prints no provider names, so the warning path fires.
        out = init.run(self.paths, _baseline_answers("opencode-multi"))
        text = out.read_text(encoding="utf-8")
        self.assertIn("# WARNING", text)
        self.assertIn("minimax", text)
        self.assertIn("openai", text)

    def test_claude_only_preset_emitted_verbatim_without_warning(self) -> None:
        _install_preset(
            Path(self.paths["home"]),
            "claude-only",
            '[[roster]]\nid = "claude-main"\nengine = "Claude"'
            '\nmodel = "claude-sonnet-4"\n',
        )
        out = init.run(self.paths, _baseline_answers("claude-only"))
        text = out.read_text(encoding="utf-8")
        self.assertNotIn("# WARNING", text)
        self.assertIn('id = "claude-main"', text)


class InitOverwriteTests(InitBase):
    """init must refuse or back up when the target file already exists."""

    def setUp(self) -> None:
        super().setUp()
        _install_preset(
            Path(self.paths["home"]),
            "opencode-multi",
            '[[agents]]\nname = "minimax-fast"\nrole = "writer"\n'
            'model = "minimax/MiniMax-M3"\ndescription = "m"\n',
        )
        # Pre-create the destination file so the overwrite branch fires.
        out_dir = Path(self.paths["config_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "podium.toml").write_text("schema = 1\n")

    def test_refuses_to_overwrite_without_consent(self) -> None:
        with self.assertRaises(init.InitError):
            init.run(self.paths, _baseline_answers("opencode-multi"))

    def test_overwrite_creates_backup(self) -> None:
        answers = _baseline_answers("opencode-multi")
        answers["overwrite"] = True
        out = init.run(self.paths, answers)
        out_dir = Path(self.paths["config_dir"])
        backups = [
            p for p in out_dir.iterdir()
            if p.name.startswith("podium.toml.bak-podium-")
        ]
        self.assertTrue(backups, f"no backup created in {out_dir}")
        self.assertTrue(out.is_file())
        self.assertIn("[language]", out.read_text(encoding="utf-8"))


class InitValidationTests(InitBase):
    """Missing preset or empty answers key must surface as InitError."""

    def test_unknown_preset_raises(self) -> None:
        with self.assertRaises(init.InitError):
            init.run(self.paths, _baseline_answers("does-not-exist"))

    def test_invalid_preset_name_raises(self) -> None:
        with self.assertRaises(init.InitError):
            init.run(self.paths, _baseline_answers("../escape"))


if __name__ == "__main__":
    unittest.main()
