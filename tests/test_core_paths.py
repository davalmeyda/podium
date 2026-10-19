import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podium import paths  # noqa: E402


class PathsTest(unittest.TestCase):
    def test_defaults_from_home(self):
        p = paths.resolve({"HOME": "/h"})
        self.assertEqual(p.home, Path("/h"))
        self.assertEqual(p.claude_dir, Path("/h/.claude"))
        self.assertEqual(p.opencode_config_dir, Path("/h/.config/opencode"))
        self.assertEqual(p.opencode_data_dir, Path("/h/.local/share/opencode"))
        self.assertEqual(p.config_dir, Path("/h/.config/podium"))
        self.assertEqual(p.state_dir, Path("/h/.local/state/podium"))

    def test_xdg_variables(self):
        p = paths.resolve({"HOME": "/h", "XDG_CONFIG_HOME": "/x/c", "XDG_DATA_HOME": "/x/d",
                           "XDG_STATE_HOME": "/x/s"})
        self.assertEqual(p.opencode_config_dir, Path("/x/c/opencode"))
        self.assertEqual(p.opencode_data_dir, Path("/x/d/opencode"))
        self.assertEqual(p.config_dir, Path("/x/c/podium"))
        self.assertEqual(p.state_dir, Path("/x/s/podium"))

    def test_specific_variables_win_over_xdg(self):
        p = paths.resolve({"HOME": "/h", "XDG_CONFIG_HOME": "/x/c", "CLAUDE_CONFIG_DIR": "/cl",
                           "OPENCODE_CONFIG_DIR": "/oc", "PODIUM_CONFIG_DIR": "/pc",
                           "PODIUM_STATE_DIR": "/ps"})
        self.assertEqual(p.claude_dir, Path("/cl"))
        self.assertEqual(p.opencode_config_dir, Path("/oc"))
        self.assertEqual(p.config_dir, Path("/pc"))
        self.assertEqual(p.state_dir, Path("/ps"))

    def test_relative_xdg_is_ignored_and_empty_counts_as_unset(self):
        p = paths.resolve({"HOME": "/h", "XDG_CONFIG_HOME": "relative/dir", "CLAUDE_CONFIG_DIR": ""})
        self.assertEqual(p.config_dir, Path("/h/.config/podium"))
        self.assertEqual(p.claude_dir, Path("/h/.claude"))

    def test_tilde_is_expanded_against_home(self):
        p = paths.resolve({"HOME": "/h", "PODIUM_CONFIG_DIR": "~/cfg"})
        self.assertEqual(p.config_dir, Path("/h/cfg"))

    def test_podium_home_is_the_checkout_and_paths_are_frozen(self):
        p = paths.resolve({"HOME": "/h"})
        self.assertTrue((p.podium_home / "bin" / "podium").is_file())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.home = Path("/other")  # type: ignore[misc]

    def test_default_env_is_os_environ(self):
        self.assertIsInstance(paths.resolve().home, Path)


if __name__ == "__main__":
    unittest.main()
