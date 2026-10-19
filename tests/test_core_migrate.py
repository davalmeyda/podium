import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "core"))

import coretest  # noqa: E402
from podium import migrate  # noqa: E402

LEGACY = [
    {"matcher": "Read|Edit|Write|Grep|Glob|Bash",
     "hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/codegraph-gate.py"}]},
    {"matcher": "Grep|Glob|Bash",
     "hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/codegraph-nudge.py"},
               {"type": "command", "command": "python3 ~/.claude/hooks/my-own-hook.py"}]},
]
SETTINGS = {
    "model": "opus",
    "permissions": {"allow": ["Bash(ls:*)"]},
    "hooks": {
        "PreToolUse": LEGACY + [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/bin/audit.sh"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/graphiti-stop.py"}]},
                 {"hooks": [{"type": "command", "command": "~/bin/notify.sh"}]}],
        "SessionStart": [{"hooks": [{"type": "command", "command": "python3",
                                     "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/codegraph-gate.py"]}]}],
    },
    "env": {"A": "1"},
}


class MigrateTest(coretest.CoreCase):
    def setUp(self):
        super().setUp()
        self.claude_dir.mkdir(parents=True)
        self.settings = self.claude_dir / "settings.json"
        self.settings.write_text(json.dumps(SETTINGS, indent=2))

    def test_find_legacy_hooks(self):
        found = migrate.find_legacy_hooks(SETTINGS)
        self.assertEqual(sorted(i["script"] for i in found),
                         ["codegraph-gate.py", "codegraph-nudge.py", "graphiti-stop.py"])

    def test_removes_only_the_three_legacy_hook_entries(self):
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 0, out + err)
        result = json.loads(self.settings.read_text())
        expected = json.loads(json.dumps(SETTINGS))
        pre = expected["hooks"]["PreToolUse"]
        del pre[0]  # group with only the gate
        pre[0]["hooks"] = [{"type": "command", "command": "python3 ~/.claude/hooks/my-own-hook.py"}]
        del expected["hooks"]["Stop"][0]
        self.assertEqual(result, expected)
        self.assertEqual(list(result), list(SETTINGS))  # top-level order preserved
        self.assertEqual(len(self.backups(self.claude_dir)), 1)
        self.assertEqual(json.loads((self.claude_dir / self.backups(self.claude_dir)[0]).read_text()), SETTINGS)

    def test_plugin_hooks_are_not_touched_and_empty_containers_dropped(self):
        only_legacy = {"hooks": {"Stop": [{"hooks": [{"type": "command",
                                                      "command": "python3 /x/graphiti-stop.py"}]}]}, "k": 1}
        self.settings.write_text(json.dumps(only_legacy))
        self.assertEqual(self.run_cli("migrate")[0], 0)
        self.assertEqual(json.loads(self.settings.read_text()), {"k": 1})

    def test_second_run_is_a_no_op(self):
        self.assertEqual(self.run_cli("migrate")[0], 0)
        before = self.snapshot()
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 0)
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_writes_nothing(self):
        legacy_state = self.claude_dir / "state" / "codegraph-decisions.json"
        legacy_state.parent.mkdir()
        legacy_state.write_text('{"/p": "yes"}')
        before = self.snapshot()
        code, out, err = self.run_cli("migrate", "--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("codegraph-gate.py", out)
        self.assertIn("dry-run", out)
        self.assertFalse(self.state_dir.exists())

    def test_decisions_are_copied_and_podium_decisions_win(self):
        legacy_state = self.claude_dir / "state" / "codegraph-decisions.json"
        legacy_state.parent.mkdir()
        legacy_state.write_text(json.dumps({"/a": "yes", "/b": "no", "nested": {"x": 1, "y": 1}}))
        target = self.state_dir / "codegraph-decisions.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"/b": "yes", "nested": {"y": 2}}))
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(target.read_text()),
                         {"/a": "yes", "/b": "yes", "nested": {"x": 1, "y": 2}})
        self.assertEqual(len(self.backups(self.state_dir)), 1)
        self.assertTrue(legacy_state.exists())  # never deletes legacy files
        self.assertIn(str(legacy_state), out)

    def test_decisions_copied_when_podium_has_none(self):
        legacy_state = self.claude_dir / "state" / "codegraph-decisions.json"
        legacy_state.parent.mkdir()
        legacy_state.write_text('{"/a": "no"}')
        self.assertEqual(self.run_cli("migrate")[0], 0)
        self.assertEqual(json.loads((self.state_dir / "codegraph-decisions.json").read_text()), {"/a": "no"})

    def test_legacy_scripts_are_reported_not_deleted(self):
        hooks = self.claude_dir / "hooks"
        hooks.mkdir()
        (hooks / "codegraph-gate.py").write_text("# old")
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 0)
        self.assertTrue((hooks / "codegraph-gate.py").exists())
        self.assertIn("left in place", out)

    def test_invalid_settings_json_is_a_user_error(self):
        self.settings.write_text("{nope")
        code, out, err = self.run_cli("migrate")
        self.assertEqual(code, 1)
        self.assertEqual(self.settings.read_text(), "{nope")

    def test_without_settings_it_is_fine(self):
        self.settings.unlink()
        self.assertEqual(self.run_cli("migrate")[0], 0)


if __name__ == "__main__":
    unittest.main()
