import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podium import config  # noqa: E402


def load_text(text, env=None):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "podium.toml").write_text(text, encoding="utf-8")
        return config.load(Path(tmp), env or {})


class ConfigTest(unittest.TestCase):
    def test_empty_config_gets_every_default(self):
        cfg = load_text("schema = 1\n")
        self.assertEqual(cfg["language"]["response"], "en")
        self.assertTrue(all(cfg["modules"].values()))
        self.assertEqual(cfg["launcher"]["opencode"], "opencode run --auto")
        self.assertEqual(cfg["memory"]["stop_hook"], {"min_edits": 8, "min_executor_runs": 2,
                                                      "cooldown_seconds": 2700})
        self.assertEqual(cfg["codegraph"]["nudge_every"], 4)
        self.assertEqual(cfg["usage"]["model_order"], ["opus", "sonnet", "haiku", "gpt", "minimax"])
        self.assertEqual(cfg["roster"], [])
        self.assertEqual(cfg["agents"], [])
        self.assertEqual(cfg["render"]["vars"], {})

    def test_user_values_override_and_partial_tables_merge(self):
        cfg = load_text('schema = 1\n[memory.stop_hook]\nmin_edits = 3\n[modules]\nusage = false\n')
        self.assertEqual(cfg["memory"]["stop_hook"]["min_edits"], 3)
        self.assertEqual(cfg["memory"]["stop_hook"]["cooldown_seconds"], 2700)
        self.assertFalse(cfg["modules"]["usage"])
        self.assertTrue(cfg["modules"]["rules"])

    def test_derived_language_names(self):
        cfg = load_text('[language]\nresponse = "es"\ndomain = "fr"\n')
        self.assertEqual(cfg["language"]["response_name"], "Spanish")
        self.assertEqual(cfg["language"]["domain_name"], "fr")
        self.assertEqual(load_text("schema = 1\n")["language"]["response_name"], "English")

    def test_unknown_top_level_key(self):
        with self.assertRaises(config.ConfigError) as ctx:
            load_text("schema = 1\nbogus = 1\n")
        self.assertIn("bogus", str(ctx.exception))

    def test_unknown_nested_key_names_the_dotted_path(self):
        with self.assertRaises(config.ConfigError) as ctx:
            load_text("[memory.stop_hook]\nbogus = 1\n")
        self.assertIn("memory.stop_hook.bogus", str(ctx.exception))
        with self.assertRaises(config.ConfigError) as ctx:
            load_text("[codegraph]\nroot = []\n")
        self.assertIn("codegraph.root", str(ctx.exception))

    def test_type_errors(self):
        for text in ('[modules]\nrules = "yes"\n', "[codegraph]\nnudge_every = true\n",
                     "[codegraph]\nroots = [1]\n", "[language]\nresponse = 3\n",
                     "[launcher]\nopencode = []\n"):
            with self.assertRaises(config.ConfigError, msg=text):
                load_text(text)

    def test_schema_and_ui_validation(self):
        with self.assertRaises(config.ConfigError):
            load_text("schema = 2\n")
        with self.assertRaises(config.ConfigError):
            load_text('[language]\nui = "de"\n')
        self.assertEqual(load_text('[language]\nui = "es"\n')["language"]["ui"], "es")

    def test_missing_file_and_invalid_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(config.ConfigError):
                config.load(Path(tmp), {})
        with self.assertRaises(config.ConfigError):
            load_text("schema = = 1")

    def test_env_expansion_in_strings_and_lists(self):
        cfg = load_text('[memory]\nurl = "https://${HOST}/mcp"\n[codegraph]\nroots = ["${ROOT}/a", "/b"]\n',
                        {"HOST": "m.example", "ROOT": "/srv"})
        self.assertEqual(cfg["memory"]["url"], "https://m.example/mcp")
        self.assertEqual(cfg["codegraph"]["roots"], ["/srv/a", "/b"])

    def test_unset_variable_is_an_error_naming_it(self):
        with self.assertRaises(config.ConfigError) as ctx:
            load_text('[memory]\nurl = "${PODIUM_TEST_UNSET_VAR}"\n', {})
        self.assertIn("PODIUM_TEST_UNSET_VAR", str(ctx.exception))
        self.assertIn("memory.url", str(ctx.exception))

    def test_empty_but_set_variable_is_fine(self):
        self.assertEqual(load_text('[memory]\nurl = "${V}"\n', {"V": ""})["memory"]["url"], "")

    def test_render_vars_are_free_form_and_expanded(self):
        cfg = load_text('[render.vars]\nteam = "${T}"\ncount = 3\nflags = ["a", "b"]\n', {"T": "acme"})
        self.assertEqual(cfg["render"]["vars"], {"team": "acme", "count": 3, "flags": ["a", "b"]})

    def test_roster_and_agents(self):
        cfg = load_text(
            '[[roster]]\nid = "r"\nengine = "E"\nmodel = "M"\n'
            'launch = { kind = "opencode", agent = "a", model = "p/m", variant = "none" }\n'
            '[[roster]]\nid = "c"\nengine = "E"\nmodel = "M"\nlaunch = { kind = "claude", model = "sonnet", effort = "high" }\n'
            '[[roster]]\nid = "p"\nengine = "E"\nmodel = "M"\n'
            '[[agents]]\nname = "a"\nrole = "writer"\nmodel = "p/m"\n')
        self.assertEqual(cfg["roster"][0]["launch"], {"kind": "opencode", "agent": "a", "model": "p/m",
                                                      "variant": "none"})
        self.assertEqual(cfg["roster"][1]["launch"]["effort"], "high")
        self.assertEqual(cfg["roster"][2]["launch"], {"kind": "principal"})
        self.assertEqual(cfg["roster"][2]["fallback"], "")
        self.assertEqual(cfg["agents"][0], {"name": "a", "role": "writer", "model": "p/m",
                                            "description": "", "deny_mcp": []})

    def test_roster_and_agent_errors(self):
        bad = [
            '[[roster]]\nid = "r"\nengine = "E"\nmodel = "M"\nlaunch = { kind = "bogus" }\n',
            '[[roster]]\nid = "r"\nengine = "E"\nmodel = "M"\nlaunch = { kind = "opencode", agent = "a" }\n',
            '[[roster]]\nid = "r"\nengine = "E"\nmodel = "M"\nextra = 1\n',
            '[[roster]]\nid = "r"\nengine = "E"\n',
            '[[agents]]\nname = "a"\nrole = "boss"\nmodel = "m"\n',
            '[[agents]]\nname = "../evil"\nrole = "writer"\nmodel = "m"\n',
            '[[agents]]\nname = "a"\nrole = "writer"\nmodel = "m"\n[[agents]]\nname = "a"\nrole = "writer"\nmodel = "m"\n',
            '[[agents]]\nname = "a"\nrole = "writer"\nmodel = "m"\ndeny_mcp = "x"\n',
        ]
        for text in bad:
            with self.assertRaises(config.ConfigError, msg=text):
                load_text(text)

    def test_unknown_roster_key_reports_indexed_path(self):
        with self.assertRaises(config.ConfigError) as ctx:
            load_text('[[roster]]\nid = "r"\nengine = "E"\nmodel = "M"\nextra = 1\n')
        self.assertIn("roster[0].extra", str(ctx.exception))

    def test_vendored_tomli_parses_like_tomllib(self):
        from podium._vendor import tomli
        data = tomli.loads('a = 1\n[t]\nb = ["x"]\n')
        self.assertEqual(data, {"a": 1, "t": {"b": ["x"]}})
        self.assertTrue((Path(tomli.__file__).parent / "LICENSE").is_file())

    def test_module_enabled(self):
        cfg = load_text("[modules]\nusage = false\n")
        self.assertTrue(config.module_enabled(cfg, "rules"))
        self.assertFalse(config.module_enabled(cfg, "usage"))


if __name__ == "__main__":
    unittest.main()
