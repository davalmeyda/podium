import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "core"))

import coretest  # noqa: E402
from podium import config, render  # noqa: E402


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="podium-render-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.home = self.tmp / "podium_home"
        shutil.copytree(str(coretest.FIXTURE_HOME), str(self.home))
        self.config_dir = self.tmp / "cfg"
        self.config_dir.mkdir()
        patcher = mock.patch.dict(sys.modules, {"podium.roster": coretest.fake_roster()})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = config.from_dict({"language": {"response": "es"}, "render": {"vars": {"team": "acme"}},
                                     "roster_notes": {"cascade": ["a", "b"]}}, {})

    def render(self, target="claude-md", cfg=None):
        return render.render_target(target, cfg or self.cfg, self.home, self.config_dir)

    def overlay(self, target, name, text):
        path = self.config_dir / "overlays" / target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    # -- base rendering
    def test_fragments_joined_by_exactly_one_blank_line_and_one_trailing_newline(self):
        text = self.render()
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))
        self.assertIn("{{ not a variable }}\n\n## Beta\n", text)
        self.assertNotIn("\n\n\n", text)
        self.assertNotIn("\r", text)

    def test_substitutions(self):
        text = self.render()
        self.assertIn("Answer in Spanish; domain language is English.", text)
        self.assertIn("Background: true.", text)
        self.assertIn("| fake |", text)  # generated.roster_table
        self.assertIn("team acme, cascade: a, b.", text)  # vars.* shorthand and list rendering
        self.assertIn("nudge every 4 calls", text)

    def test_escape_and_single_pass(self):
        self.assertIn("Escaped: {{ not a variable }}", self.render())
        cfg = config.from_dict({"render": {"vars": {"team": "{{ language.response }}"}}}, {})
        self.assertIn("team {{ language.response }},", self.render(cfg=cfg))

    def test_disabled_module_skips_its_fragments(self):
        cfg = config.from_dict({"modules": {"memory": False}}, {})
        text = self.render(cfg=cfg)
        self.assertNotIn("Gamma", text)
        self.assertIn("Delta", text)

    def test_requires_opencode_executors(self):
        rules = self.home / "rules"
        with (rules / "manifest.toml").open("a", encoding="utf-8") as fh:
            fh.write('\n[[target]]\nid = "req"\nfragments = [\n'
                     '  { id = "req-oc", requires = "opencode-executors" },\n  { id = "req-all" },\n]\n')
        (rules / "req-oc.md").write_text("OpenCode part\n", encoding="utf-8")
        (rules / "req-all.md").write_text("Common part\n", encoding="utf-8")
        claude_only = {"roster": [{"id": "p", "launch": {"kind": "principal"}}]}
        with_opencode = {"roster": [{"id": "w", "launch": {"kind": "opencode", "agent": "w"}}]}
        self.assertEqual(self.render("req", claude_only), "Common part\n")
        self.assertEqual(self.render("req", with_opencode), "OpenCode part\n\nCommon part\n")
        with (rules / "manifest.toml").open("a", encoding="utf-8") as fh:
            fh.write('\n[[target]]\nid = "bad"\nfragments = [ { id = "req-all", requires = "nope" } ]\n')
        with self.assertRaisesRegex(render.RenderError, "unknown requirement: nope"):
            self.render("bad", with_opencode)

    def test_empty_generated_block_leaves_no_blank_run(self):
        self.overlay("claude-md", "alpha.md", "Head\n\n{{ vars.empty }}\n\nTail\n")
        cfg = config.from_dict({"render": {"vars": {"empty": "", "team": "acme"}}}, {})
        self.assertIn("Head\n\nTail", self.render(cfg=cfg))

    def test_other_targets_and_sources(self):
        self.assertEqual(self.render("opencode-agents-md").count("# Alpha"), 1)
        profile = self.render("executor-profile")
        self.assertTrue(profile.startswith("# Executor profile\n\nDomain language: English.\n\n## Report"))

    def test_template_errors(self):
        self.assertRaises(render.RenderError, render.render_text, "{{ nope.here }}", self.cfg)
        self.assertRaises(render.RenderError, render.render_text, "{{ generated.nope }}", self.cfg)
        self.assertRaises(render.RenderError, render.render_text, "{{ memory }}", self.cfg)  # a table
        self.assertRaises(render.RenderError, render.render_text, "{{ not valid! }}", self.cfg)
        self.assertRaises(render.RenderError, self.render, "no-such-target")
        self.assertEqual(render.render_text("a {{ vars.team }} b {{ modules.rules }}", self.cfg),
                         "a acme b true")

    def test_generated_is_not_loaded_unless_used(self):
        with mock.patch.dict(sys.modules, {"podium.roster": None}):
            self.assertEqual(render.render_text("plain {{ language.ui }}", self.cfg), "plain en")

    # -- overlays
    def test_overlay_replaces_a_fragment_with_templating(self):
        self.overlay("claude-md", "beta.md", "## Custom\n\nHello {{ language.response_name }}\n")
        text = self.render()
        self.assertIn("## Custom\n\nHello Spanish\n\n## Gamma", text)
        self.assertNotIn("## Beta", text)

    def test_insert_after_before_keeps_file_order(self):
        self.overlay("claude-md", "one.md", "ONE\n")
        self.overlay("claude-md", "two.md", "TWO\n")
        self.overlay("claude-md", "three.md", "THREE\n")
        self.overlay("claude-md", "insert.toml",
                     '[[insert]]\nfile = "one.md"\nafter = "alpha"\n'
                     '[[insert]]\nfile = "two.md"\nafter = "alpha"\n'
                     '[[insert]]\nfile = "three.md"\nbefore = "alpha"\n')
        text = self.render()
        order = [text.index(word) for word in ("THREE", "# Alpha", "ONE", "TWO", "## Beta")]
        self.assertEqual(order, sorted(order))

    def test_omit(self):
        self.overlay("claude-md", "insert.toml", 'omit = ["beta", "gamma"]\n')
        text = self.render()
        self.assertNotIn("## Beta", text)
        self.assertNotIn("Gamma", text)
        self.assertIn("Delta", text)

    def test_orphan_replacement_is_an_error(self):
        self.overlay("claude-md", "nonexistent.md", "x\n")
        with self.assertRaises(render.RenderError) as ctx:
            self.render()
        self.assertIn("nonexistent", str(ctx.exception))

    def test_orphan_anchor_and_omit_are_errors(self):
        self.overlay("claude-md", "x.md", "X\n")
        self.overlay("claude-md", "insert.toml", '[[insert]]\nfile = "x.md"\nafter = "ghost"\n')
        with self.assertRaises(render.RenderError) as ctx:
            self.render()
        self.assertIn("ghost", str(ctx.exception))
        self.overlay("claude-md", "insert.toml", 'omit = ["ghost"]\n')
        with self.assertRaises(render.RenderError):
            self.render()

    def test_insert_validation(self):
        self.overlay("claude-md", "x.md", "X\n")
        for body in ('[[insert]]\nfile = "x.md"\n',
                     '[[insert]]\nfile = "x.md"\nafter = "alpha"\nbefore = "beta"\n',
                     '[[insert]]\nfile = "missing.md"\nafter = "alpha"\n',
                     '[[insert]]\nfile = "x.md"\nafter = "alpha"\nextra = 1\n'):
            self.overlay("claude-md", "insert.toml", body)
            with self.assertRaises(render.RenderError, msg=body):
                self.render()

    def test_overlay_on_disabled_module_is_not_an_error(self):
        cfg = config.from_dict({"modules": {"memory": False}}, {})
        self.overlay("claude-md", "gamma.md", "Custom gamma\n")
        self.assertNotIn("Custom gamma", self.render(cfg=cfg))

    def test_overlays_are_per_target(self):
        self.overlay("claude-md", "beta.md", "## Custom\n")
        self.assertNotIn("Custom", self.render("opencode-agents-md"))

    def test_utf8_roundtrip(self):
        self.overlay("claude-md", "beta.md", "## Respuesta en español — ¿qué?\n")
        self.assertIn("español — ¿qué?", self.render())


if __name__ == "__main__":
    unittest.main()
