"""`podium install` prunes what podium owns for modules the config disables."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "core"))

import coretest  # noqa: E402

SERVER = "graphiti-memory"
ALL = ("rules", "executors", "memory", "codegraph")


class PruneDisabledModulesTests(coretest.CoreCase):
    def setUp(self):
        super().setUp()
        self.add_fake_claude()
        self.write_modules()

    def write_modules(self, url=None, **modules):
        text = coretest.BASE_CONFIG
        if url is not None:
            text = text.replace('url = "${TEST_MEMORY_URL}"', 'url = "%s"' % url)
        flags = "".join("%s = %s\n" % (name, "true" if on else "false") for name, on in modules.items())
        self.write_config(text + "\n[modules]\n" + flags)

    def tree(self):
        """Every file under the temp tree except the fake claude's call log."""
        return {k: v for k, v in self.snapshot().items() if k != str(self.claude_log)}

    def install(self, *argv):
        code, out, err = self.run_cli("install", *argv)
        self.assertEqual(code, 0, out + err)
        return out

    def opencode_mcp(self):
        path = self.oc_dir / "opencode.json"
        return json.loads(path.read_text(encoding="utf-8")).get("mcp", {}) if path.exists() else {}

    def present(self):
        """Which module artefacts exist on disk right now."""
        blocks = [self.claude_dir / "CLAUDE.md", self.oc_dir / "AGENTS.md"]
        mcp = self.opencode_mcp()
        return {
            "rules": any(p.exists() and "podium:begin" in p.read_text(encoding="utf-8") for p in blocks),
            "executors": (self.oc_dir / "agents" / "writer.md").exists()
            or (self.state_dir / "executor-profile.md").exists(),
            "memory-skills": (self.oc_dir / "skills" / "project-memory" / "SKILL.md").exists(),
            "memory-opencode": SERVER in mcp,
            "memory-claude": SERVER in self.claude_json().get("mcpServers", {}),
            "codegraph": "codegraph" in mcp,
        }

    FULL = {"rules": True, "executors": True, "memory-skills": True, "memory-opencode": True,
            "memory-claude": True, "codegraph": True}

    def test_full_install_creates_everything(self):
        self.install()
        self.assertEqual(self.present(), self.FULL)

    def test_disabling_each_module_removes_exactly_its_artefacts(self):
        gone = {
            "rules": ("rules",),
            "executors": ("executors",),
            "memory": ("memory-skills", "memory-opencode", "memory-claude"),
            "codegraph": ("codegraph",),
        }
        plugin = {"memory": "podium-memory", "codegraph": "podium-codegraph"}
        for module in ALL:
            with self.subTest(module=module):
                self.setUp()
                self.install()
                self.claude_log.write_text("")
                self.write_modules(**{module: False})
                self.install()
                expected = dict(self.FULL)
                for key in gone[module]:
                    expected[key] = False
                self.assertEqual(self.present(), expected)
                calls = self.claude_calls()
                uninstalls = [c for c in calls if c.startswith("plugin uninstall")]
                if module in plugin:
                    self.assertEqual(uninstalls, ["plugin uninstall %s@podium --scope user" % plugin[module]])
                else:
                    self.assertEqual(uninstalls, [])
                # the other plugins are not touched by the module that is off
                self.assertFalse(any("plugin uninstall podium-usage" in c for c in calls))
                if module == "memory":
                    self.assertIn("mcp remove %s --scope user" % SERVER, calls)
                # a second run is a no-op
                self.claude_log.write_text("")
                self.install()
                self.assertEqual(self.present(), expected)
                self.assertEqual([c for c in self.mcp_calls()], [])

    def test_ledger_forgets_pruned_artefacts(self):
        self.install()
        self.write_modules(memory=False, codegraph=False, executors=False)
        self.install()
        ledger = json.loads((self.state_dir / "owned.json").read_text())
        self.assertEqual(sorted(ledger["files"]), [str(self.config_dir / "runtime.json")])
        self.assertNotIn(str(self.claude_dir / ".claude.json"), ledger["json"])
        self.assertNotIn(str(self.oc_dir / "opencode.json"), ledger["json"])

    def test_partial_run_never_prunes_enabled_modules(self):
        self.install()
        before = self.tree()
        self.claude_log.write_text("")
        self.install("--modules", "rules")
        self.assertEqual(self.present(), self.FULL)
        self.assertEqual([c for c in self.claude_calls() if "uninstall" in c or "remove" in c], [])
        self.assertEqual(self.tree(), before)

    def test_partial_run_does_not_prune_disabled_modules_it_does_not_name(self):
        self.install()
        self.write_modules(codegraph=False)
        self.install("--modules", "rules")
        self.assertTrue(self.present()["codegraph"])
        self.install("--modules", "rules,codegraph")
        self.assertFalse(self.present()["codegraph"])

    def test_user_modified_agent_file_is_kept(self):
        self.install()
        agent = self.oc_dir / "agents" / "writer.md"
        agent.write_text(agent.read_text(encoding="utf-8") + "my edit\n", encoding="utf-8")
        self.write_modules(executors=False)
        out = self.install()
        self.assertTrue(agent.exists())
        self.assertIn("my edit", agent.read_text(encoding="utf-8"))
        self.assertFalse((self.oc_dir / "agents" / "reviewer.md").exists())
        self.assertIn("left in place", out)
        ledger = json.loads((self.state_dir / "owned.json").read_text())
        self.assertNotIn(str(agent), ledger["files"])

    def test_emptying_memory_url_removes_the_memory_pointers_only(self):
        self.install()
        self.write_modules(url="")
        self.install()
        state = self.present()
        self.assertFalse(state["memory-opencode"])
        self.assertFalse(state["memory-claude"])
        self.assertTrue(state["memory-skills"])
        self.assertTrue(state["codegraph"])
        self.assertIn("mcp remove %s --scope user" % SERVER, self.claude_calls())
        self.assertEqual([c for c in self.claude_calls() if c.startswith("plugin uninstall")], [])

    def test_foreign_entries_are_never_removed(self):
        self.oc_dir.mkdir(parents=True)
        (self.oc_dir / "opencode.json").write_text(json.dumps({"mcp": {"codegraph": {"type": "mine"}}}))
        self.write_modules(codegraph=False)
        self.install()
        self.assertEqual(self.opencode_mcp()["codegraph"], {"type": "mine"})

    def test_dry_run_lists_removals_and_writes_nothing(self):
        self.install()
        self.write_modules(rules=False, memory=False, codegraph=False)
        before = self.tree()
        self.claude_log.write_text("")
        code, out, err = self.run_cli("install", "--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertIn("[remove]", out)
        self.assertIn("plugin uninstall podium-codegraph@podium", out)
        self.assertIn("plugin uninstall podium-memory@podium", out)
        self.assertIn("mcp remove %s --scope user" % SERVER, out)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.claude_calls(), [])

    def test_without_claude_one_skip_note_and_files_still_pruned(self):
        self.install()
        (self.bin / "claude").unlink()
        self.write_modules(memory=False, codegraph=False)
        out = self.install()
        self.assertEqual(out.count("[skip]"), 1, out)
        self.assertFalse(self.present()["memory-skills"])
        self.assertFalse(self.present()["codegraph"])


if __name__ == "__main__":
    unittest.main()
