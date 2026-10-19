import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "core"))

import coretest  # noqa: E402
from podium.targets import _memory_mcp_entry  # noqa: E402


class MemoryMcpEntryTests(unittest.TestCase):
    def test_minimal_entry(self):
        entry = _memory_mcp_entry({"url": "http://m.example/mcp", "headers": {}, "mcp_options": {}})
        self.assertEqual(entry, {"type": "remote", "url": "http://m.example/mcp", "enabled": True})

    def test_headers_and_options(self):
        entry = _memory_mcp_entry({
            "url": "http://m.example/mcp",
            "headers": {"Host": "localhost:8000"},
            "mcp_options": {"timeout": 180000, "oauth": False, "enabled": False},
        })
        self.assertEqual(entry["headers"], {"Host": "localhost:8000"})
        self.assertEqual(entry["timeout"], 180000)
        self.assertIs(entry["oauth"], False)
        self.assertIs(entry["enabled"], True)  # options never override the core keys


URL = "https://memory.example.test/mcp"
ENTRY = {"type": "http", "url": URL}
ADD = "mcp add-json graphiti-memory %s --scope user" % json.dumps(ENTRY, separators=(",", ":"))
REMOVE = "mcp remove graphiti-memory --scope user"


class ClaudeMemoryMcpTests(coretest.CoreCase):
    """The memory server is registered in Claude Code at user scope through the claude CLI."""

    def setUp(self):
        super().setUp()
        self.write_config()
        self.add_fake_claude()
        self.config = self.claude_dir / ".claude.json"

    def seed(self, servers):
        self.claude_dir.mkdir(parents=True, exist_ok=True)
        self.config.write_text(json.dumps({"numStartups": 3, "mcpServers": servers}), encoding="utf-8")

    def ledger(self):
        return json.loads((self.state_dir / "owned.json").read_text())["json"].get(str(self.config))

    def test_absent_entry_is_added_through_the_cli(self):
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.mcp_calls(), [ADD])
        self.assertEqual(self.claude_json()["mcpServers"], {"graphiti-memory": ENTRY})
        self.assertEqual(self.ledger(), {"/mcpServers/graphiti-memory": {"before": None, "applied": ENTRY}})

    def test_headers_are_part_of_the_entry(self):
        self.write_config(coretest.BASE_CONFIG.replace('url = "${TEST_MEMORY_URL}"',
                                                       'url = "${TEST_MEMORY_URL}"\nheaders = { Host = "localhost:8000" }'))
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.claude_json()["mcpServers"]["graphiti-memory"],
                         {"type": "http", "url": URL, "headers": {"Host": "localhost:8000"}})

    def test_second_install_runs_nothing_for_the_mcp(self):
        self.assertEqual(self.run_cli("install")[0], 0)
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.mcp_calls(), [ADD])
        self.assertIn("[unchanged]", out)

    def test_foreign_entry_is_a_conflict_and_adopt_replaces_it(self):
        foreign = {"type": "sse", "url": "http://other.example/sse"}
        self.seed({"graphiti-memory": foreign})
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 2, out + err)
        self.assertIn("already exists and is not managed by podium", out)
        self.assertEqual(self.mcp_calls(), [])
        self.assertEqual(self.claude_json()["mcpServers"], {"graphiti-memory": foreign})
        code, out, err = self.run_cli("install", "--adopt")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.mcp_calls(), [REMOVE, ADD])
        self.assertEqual(self.claude_json()["mcpServers"], {"graphiti-memory": ENTRY})
        self.assertEqual(self.claude_json()["numStartups"], 3)
        self.assertEqual(self.ledger()["/mcpServers/graphiti-memory"], {"before": foreign, "applied": ENTRY})

    def test_identical_foreign_entry_is_recorded_without_running_the_cli(self):
        self.seed({"graphiti-memory": ENTRY})
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.mcp_calls(), [])
        self.assertEqual(self.ledger()["/mcpServers/graphiti-memory"], {"before": ENTRY, "applied": ENTRY})

    def test_edited_entry_is_a_conflict_unless_forced(self):
        self.assertEqual(self.run_cli("install")[0], 0)
        edited = {"type": "http", "url": "http://edited.example/mcp"}
        self.seed({"graphiti-memory": edited})
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 2, out + err)
        self.assertIn("was modified since podium wrote it", out)
        self.assertEqual(self.claude_json()["mcpServers"], {"graphiti-memory": edited})
        code, out, err = self.run_cli("install", "--force")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.mcp_calls(), [ADD, REMOVE, ADD])
        self.assertEqual(self.claude_json()["mcpServers"], {"graphiti-memory": ENTRY})
        self.assertIsNone(self.ledger()["/mcpServers/graphiti-memory"]["before"])

    def test_changed_config_replaces_an_owned_entry(self):
        self.assertEqual(self.run_cli("install")[0], 0)
        self.write_config(coretest.BASE_CONFIG.replace("${TEST_MEMORY_URL}", "https://new.example.test/mcp"))
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 0, out + err)
        new = {"type": "http", "url": "https://new.example.test/mcp"}
        self.assertEqual(self.mcp_calls(), [ADD, REMOVE,
                                            "mcp add-json graphiti-memory %s --scope user"
                                            % json.dumps(new, separators=(",", ":"))])
        self.assertEqual(self.claude_json()["mcpServers"], {"graphiti-memory": new})
        self.assertEqual(self.ledger()["/mcpServers/graphiti-memory"], {"before": None, "applied": new})

    def test_uninstall_removes_an_owned_entry(self):
        self.seed({"other": {"type": "http", "url": "http://o.example"}})
        self.assertEqual(self.run_cli("install")[0], 0)
        code, out, err = self.run_cli("uninstall")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.mcp_calls(), [ADD, REMOVE])
        self.assertEqual(self.claude_json()["mcpServers"], {"other": {"type": "http", "url": "http://o.example"}})
        self.assertFalse((self.state_dir / "owned.json").exists())

    def test_uninstall_restores_the_adopted_before_value(self):
        foreign = {"type": "sse", "url": "http://other.example/sse"}
        self.seed({"graphiti-memory": foreign})
        self.assertEqual(self.run_cli("install", "--adopt")[0], 0)
        code, out, err = self.run_cli("uninstall")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.mcp_calls()[2:], [REMOVE, "mcp add-json graphiti-memory %s --scope user"
                                                % json.dumps(foreign, separators=(",", ":"))])
        self.assertEqual(self.claude_json()["mcpServers"], {"graphiti-memory": foreign})

    def test_uninstall_keeps_an_edited_entry(self):
        self.assertEqual(self.run_cli("install")[0], 0)
        edited = {"type": "http", "url": "http://edited.example/mcp"}
        self.seed({"graphiti-memory": edited})
        code, out, err = self.run_cli("uninstall")
        self.assertEqual(code, 0, out + err)
        self.assertIn("[keep]", out)
        self.assertEqual(self.mcp_calls(), [ADD])
        self.assertEqual(self.claude_json()["mcpServers"], {"graphiti-memory": edited})
        self.assertFalse((self.state_dir / "owned.json").exists())

    def test_memory_off_or_empty_url_runs_no_mcp_steps(self):
        self.write_config(coretest.BASE_CONFIG + "\n[modules]\nmemory = false\n")
        self.assertEqual(self.run_cli("install")[0], 0)
        self.write_config(coretest.BASE_CONFIG.replace('url = "${TEST_MEMORY_URL}"', 'url = ""'))
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(self.mcp_calls(), [])
        self.assertFalse(self.config.exists())

    def test_modules_flag_without_memory_runs_no_mcp_steps(self):
        self.assertEqual(self.run_cli("install", "--modules", "rules")[0], 0)
        self.assertEqual(self.mcp_calls(), [])

    def test_dry_run_lists_run_steps_and_executes_nothing(self):
        before = self.snapshot()
        code, out, err = self.run_cli("install", "--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertIn("[run]", out)
        self.assertIn("claude mcp add-json graphiti-memory", out)
        self.assertEqual(self.claude_calls(), [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_cli("install")[0], 0)
        before = self.snapshot()
        calls = self.claude_calls()
        code, out, err = self.run_cli("uninstall", "--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertIn("claude mcp remove graphiti-memory --scope user", out)
        self.assertEqual(self.claude_calls(), calls)
        self.assertEqual(self.snapshot(), before)

    def test_without_claude_on_path_there_is_one_skip_note_and_no_ledger_entry(self):
        (self.bin / "claude").unlink()
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out.count("claude not found"), 1)
        self.assertIn("memory MCP", out)
        self.assertNotIn(str(self.config), (self.state_dir / "owned.json").read_text())

    def test_failed_cli_call_is_fatal_and_not_recorded(self):
        code, out, err = self.run_cli("install", FAKE_CLAUDE_FAIL="add-json")
        self.assertEqual(code, 3, out + err)
        self.assertNotIn(str(self.config), (self.state_dir / "owned.json").read_text())

    def test_claude_config_dir_unset_uses_home_dot_claude_json(self):
        env = dict(self.env)
        del env["CLAUDE_CONFIG_DIR"]
        self.env = env
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads((self.home / ".claude.json").read_text())["mcpServers"],
                         {"graphiti-memory": ENTRY})


if __name__ == "__main__":
    unittest.main()
