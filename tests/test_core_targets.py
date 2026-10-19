import json
import os
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "core"))

import coretest  # noqa: E402
from podium import state, targets  # noqa: E402

BACKUP_RE = re.compile(r"\.bak-podium-\d{8}-\d{6}-[0-9a-f]{4}$")


class BlockTextTest(unittest.TestCase):
    def test_append_keeps_existing_text_as_prefix(self):
        for original in ("", "# A\n", "no trailing newline", "crlf\r\nline\r\n"):
            new = targets.set_block(original, "t", "body\n")
            self.assertTrue(new.startswith(original), original)
            self.assertIn("<!-- podium:begin t -->\nbody\n<!-- podium:end t -->\n", new)

    def test_replace_is_stable_and_leaves_outside_text_alone(self):
        text = "before\n\n<!-- podium:begin t -->\nold\n<!-- podium:end t -->\n\nafter\n"
        new = targets.set_block(text, "t", "new\n")
        self.assertEqual(new, "before\n\n<!-- podium:begin t -->\nnew\n<!-- podium:end t -->\n\nafter\n")
        self.assertEqual(targets.set_block(new, "t", "new\n"), new)

    def test_other_blocks_are_independent(self):
        text = targets.set_block(targets.set_block("", "a", "A\n"), "b", "B\n")
        self.assertEqual(targets.get_block(text, "a"), "A\n")
        self.assertEqual(targets.get_block(targets.set_block(text, "a", "A2\n"), "b"), "B\n")

    def test_broken_markers_are_refused(self):
        for text in ("<!-- podium:begin t -->\nx\n", "<!-- podium:end t -->\n",
                     "<!-- podium:begin t -->\n<!-- podium:end t -->\n<!-- podium:begin t -->\n<!-- podium:end t -->\n",
                     "<!-- podium:end t -->\n<!-- podium:begin t -->\n"):
            with self.assertRaises(targets.Conflict, msg=text):
                targets.set_block(text, "t", "x\n")

    def test_remove_roundtrip(self):
        for original in ("", "# A\n", "# A\n\nmore\n"):
            self.assertEqual(targets.remove_block(targets.set_block(original, "t", "x\n"), "t"), original)
        self.assertIsNone(targets.remove_block("nothing\n", "t"))


class StateTest(unittest.TestCase):
    def setUp(self):
        import tempfile, shutil
        self.tmp = Path(tempfile.mkdtemp(prefix="podium-state-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

    def test_atomic_write_creates_dirs_replaces_and_leaves_no_temp_files(self):
        target = self.tmp / "a" / "b" / "f.txt"
        state.atomic_write(target, "one")
        state.atomic_write(target, b"two")
        self.assertEqual(target.read_bytes(), b"two")
        self.assertEqual([p.name for p in target.parent.iterdir()], ["f.txt"])

    def test_atomic_write_keeps_the_mode_of_an_existing_file(self):
        target = self.tmp / "f"
        target.write_text("x")
        target.chmod(0o600)
        state.atomic_write(target, "y")
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_backup_name_and_content(self):
        target = self.tmp / "CLAUDE.md"
        target.write_text("keep me")
        copy = state.backup(target)
        self.assertTrue(BACKUP_RE.search(copy.name), copy.name)
        self.assertTrue(copy.name.startswith("CLAUDE.md.bak-podium-"))
        self.assertEqual(copy.read_text(), "keep me")
        self.assertNotEqual(state.backup(target), copy)

    def test_lock_is_exclusive_and_released(self):
        with state.lock(self.tmp):
            with self.assertRaises(state.StateError):
                with state.lock(self.tmp):
                    pass
        self.assertFalse((self.tmp / "lock").exists())
        with state.lock(self.tmp):
            pass

    def test_stale_lock_is_taken_over_after_ten_minutes(self):
        lock_file = self.tmp / "lock"
        lock_file.write_text("999\n")
        old = time.time() - 601
        os.utime(str(lock_file), (old, old))
        with state.lock(self.tmp):
            pass
        lock_file.write_text("999\n")
        recent = time.time() - 300
        os.utime(str(lock_file), (recent, recent))
        with self.assertRaises(state.StateError):
            with state.lock(self.tmp):
                pass

    def test_ledger_roundtrip_and_corruption(self):
        ledger = state.Ledger.load(self.tmp)
        self.assertTrue(ledger.is_empty())
        ledger.files["/x"] = "abc"
        ledger.json["/j"] = {"/mcp/a": {"before": None, "applied": 1}}
        ledger.save()
        again = state.Ledger.load(self.tmp)
        self.assertEqual((again.files, again.json), (ledger.files, ledger.json))
        (self.tmp / "owned.json").write_text("{not json")
        with self.assertRaises(state.StateError):
            state.Ledger.load(self.tmp)


class InstallTest(coretest.CoreCase):
    def setUp(self):
        super().setUp()
        self.write_config()
        self.claude_md = self.claude_dir / "CLAUDE.md"
        self.agents_md = self.oc_dir / "AGENTS.md"
        self.opencode_json = self.oc_dir / "opencode.json"
        self.writer = self.oc_dir / "agents" / "writer.md"
        self.reviewer = self.oc_dir / "agents" / "reviewer.md"
        self.profile = self.state_dir / "executor-profile.md"
        self.runtime = self.config_dir / "runtime.json"
        self.skill = self.oc_dir / "skills" / "project-memory" / "SKILL.md"

    def install(self, *flags, **env):
        return self.run_cli("install", *flags, **env)

    def ledger(self):
        return json.loads((self.state_dir / "owned.json").read_text())

    # -- blocks
    def test_block_is_appended_to_an_existing_claude_md_byte_for_byte(self):
        original = "# My own rules\r\nkeep this exactly\n\n<!-- CODEGRAPH_START -->\ncg\n<!-- CODEGRAPH_END -->"
        self.claude_md.parent.mkdir(parents=True)
        self.claude_md.write_bytes(original.encode())
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        data = self.claude_md.read_bytes()
        self.assertTrue(data.startswith(original.encode()))
        text = data.decode()
        self.assertIn("<!-- podium:begin claude-md -->\n# Alpha", text)
        self.assertTrue(text.rstrip("\n").endswith("<!-- podium:end claude-md -->"))
        self.assertEqual(len(self.backups(self.claude_dir)), 1)
        self.assertEqual(Path(self.backups(self.claude_dir)[0]).name.split(".bak-podium-")[0], "CLAUDE.md")
        backup = self.claude_dir / self.backups(self.claude_dir)[0]
        self.assertEqual(backup.read_bytes(), original.encode())

    def test_missing_files_are_created_without_backups(self):
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        self.assertTrue(self.claude_md.read_text().startswith("<!-- podium:begin claude-md -->\n"))
        self.assertTrue(self.agents_md.is_file())
        self.assertEqual(self.backups(self.claude_dir), [])

    def test_second_install_is_idempotent(self):
        self.claude_md.parent.mkdir(parents=True)
        self.claude_md.write_text("mine\n")
        self.opencode_json.parent.mkdir(parents=True)
        self.opencode_json.write_text('{"theme": "x"}\n')
        self.assertEqual(self.install()[0], 0)
        before = self.snapshot()
        backups = (self.backups(self.claude_dir), self.backups(self.oc_dir))
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((self.backups(self.claude_dir), self.backups(self.oc_dir)), backups)
        self.assertNotIn("[update]", out)
        self.assertNotIn("[create]", out)

    def test_config_change_updates_block_in_place(self):
        self.assertEqual(self.install()[0], 0)
        self.claude_md.write_text("top\n\n" + self.claude_md.read_text() + "\nbottom\n")
        self.write_config(coretest.BASE_CONFIG.replace('response = "es"', 'response = "en"'))
        self.assertEqual(self.install()[0], 0)
        text = self.claude_md.read_text()
        self.assertTrue(text.startswith("top\n\n<!-- podium:begin claude-md -->"))
        self.assertTrue(text.endswith("<!-- podium:end claude-md -->\n\nbottom\n"))
        self.assertIn("Answer in English", text)
        self.assertEqual(text.count("podium:begin claude-md"), 1)

    def test_unbalanced_markers_refuse_the_whole_install(self):
        self.claude_md.parent.mkdir(parents=True)
        self.claude_md.write_text("<!-- podium:begin claude-md -->\nunfinished\n")
        before = self.snapshot()
        code, out, err = self.install()
        self.assertEqual(code, 2)
        self.assertIn("markers", out)
        self.assertEqual(self.snapshot(), before)  # nothing else was written either

    # -- owned files
    def test_foreign_agent_file_is_refused_then_adopted(self):
        self.writer.parent.mkdir(parents=True)
        self.writer.write_text("my own agent\n")
        before = self.snapshot()
        code, out, err = self.install()
        self.assertEqual(code, 2)
        self.assertIn("foreign", out)
        self.assertIn("--adopt", out)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.writer.read_text(), "my own agent\n")

        code, out, err = self.install("--adopt")
        self.assertEqual(code, 0, out + err)
        self.assertIn("agent writer", self.writer.read_text())
        backups = self.backups(self.writer.parent)
        self.assertEqual(len(backups), 1)
        self.assertEqual((self.writer.parent / backups[0]).read_text(), "my own agent\n")
        self.assertIn(str(self.writer), self.ledger()["files"])
        # once adopted it is ours: plain installs work again
        self.assertEqual(self.install()[0], 0)

    def test_uninstall_restores_an_adopted_file(self):
        self.writer.parent.mkdir(parents=True)
        self.writer.write_text("my own agent\n")
        self.assertEqual(self.install("--adopt")[0], 0)
        self.assertIn(str(self.writer), self.ledger()["adopted"])
        code, out, err = self.run_cli("uninstall")
        self.assertEqual(code, 0, out + err)
        self.assertIn("[restore]", out)
        self.assertEqual(self.writer.read_text(), "my own agent\n")
        self.assertEqual(self.backups(self.writer.parent), [])  # the backup became the file again

    def test_modified_owned_file_is_refused_then_forced(self):
        self.assertEqual(self.install()[0], 0)
        self.reviewer.write_text("hand edited\n")
        before = self.snapshot()
        code, out, err = self.install()
        self.assertEqual(code, 2)
        self.assertIn("modified", out)
        self.assertIn("--force", out)
        self.assertEqual(self.snapshot(), before)

        code, out, err = self.install("--force")
        self.assertEqual(code, 0, out + err)
        self.assertIn("agent reviewer", self.reviewer.read_text())
        backups = self.backups(self.reviewer.parent)
        self.assertEqual([(self.reviewer.parent / b).read_text() for b in backups], ["hand edited\n"])

    def test_adopt_does_not_override_user_modifications(self):
        self.assertEqual(self.install()[0], 0)
        self.reviewer.write_text("hand edited\n")
        self.assertEqual(self.install("--adopt")[0], 2)

    def test_owned_file_update_when_config_changes_needs_no_backup(self):
        self.assertEqual(self.install()[0], 0)
        self.write_config(coretest.BASE_CONFIG.replace("Writer fixture.", "Writer fixture v2."))
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        self.assertIn("v2.", self.writer.read_text())
        self.assertEqual(self.backups(self.writer.parent), [])

    def _drop_reviewer(self):
        config = coretest.BASE_CONFIG
        self.write_config(config[:config.index('[[agents]]\nname = "reviewer"')])

    def test_agent_removed_from_config_is_pruned(self):
        self.assertEqual(self.install()[0], 0)
        self._drop_reviewer()
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        self.assertIn("[remove]", out)
        self.assertFalse(self.reviewer.exists())
        self.assertTrue(self.writer.exists())
        self.assertNotIn(str(self.reviewer), self.ledger()["files"])

    def test_pruning_keeps_an_agent_the_user_edited(self):
        self.assertEqual(self.install()[0], 0)
        self.reviewer.write_text("hand edited\n")
        self._drop_reviewer()
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.reviewer.read_text(), "hand edited\n")
        self.assertNotIn(str(self.reviewer), self.ledger()["files"])

    def test_skills_are_copied_from_the_memory_plugin(self):
        self.assertEqual(self.install()[0], 0)
        self.assertIn("Fixture skill body.", self.skill.read_text())
        self.assertEqual((self.skill.parent / "references" / "notes.md").read_text(), "Reference file.\n")
        self.assertIn(str(self.skill), self.ledger()["files"])

    def test_ledger_has_sha256_of_every_owned_file(self):
        self.assertEqual(self.install()[0], 0)
        files = self.ledger()["files"]
        for path in (self.writer, self.reviewer, self.profile, self.runtime, self.skill):
            self.assertEqual(files[str(path)], state.sha256_file(path), path)
        self.assertNotIn(str(self.claude_md), files)  # blocks are not in the files ledger

    def test_agents_and_profile_content(self):
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(self.writer.read_text(),
                         "---\ndescription: Writer fixture.\n---\nagent writer role writer\n")
        self.assertTrue(self.profile.read_text().startswith("# Executor profile"))

    # -- JSON
    def test_json_merge_keeps_user_keys_order_and_format(self):
        self.opencode_json.parent.mkdir(parents=True)
        self.opencode_json.write_text(json.dumps({"zeta": 1, "mcp": {"mine": {"type": "local"}}, "alpha": [1]}))
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        raw = self.opencode_json.read_text()
        doc = json.loads(raw)
        self.assertEqual(list(doc), ["zeta", "mcp", "alpha"])
        self.assertEqual(list(doc["mcp"]), ["mine", "graphiti-memory", "codegraph"])
        self.assertEqual(doc["mcp"]["graphiti-memory"],
                         {"type": "remote", "url": "https://memory.example.test/mcp", "enabled": True})
        self.assertEqual(doc["mcp"]["codegraph"],
                         {"type": "local", "command": ["codegraph", "serve", "--mcp"], "enabled": True})
        self.assertTrue(raw.endswith("}\n"))
        self.assertIn('\n  "zeta": 1,', raw)
        self.assertEqual(len(self.backups(self.oc_dir)), 1)

    def test_json_file_is_created_when_missing_and_jsonc_alone_is_left_untouched(self):
        self.oc_dir.mkdir(parents=True)
        jsonc = self.oc_dir / "opencode.jsonc"
        jsonc.write_text('{ // comment\n "theme": "x" }\n')
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(jsonc.read_text(), '{ // comment\n "theme": "x" }\n')
        self.assertIn("codegraph", json.loads(self.opencode_json.read_text())["mcp"])
        self.assertEqual(self.backups(self.oc_dir), [])

    def test_memory_server_only_with_memory_on_and_non_empty_url(self):
        self.write_config(coretest.BASE_CONFIG.replace('url = "${TEST_MEMORY_URL}"', 'url = ""'))
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(list(json.loads(self.opencode_json.read_text())["mcp"]), ["codegraph"])

    def test_json_foreign_key_refused_adopted_and_restored_on_uninstall(self):
        previous = {"type": "local", "command": ["my-codegraph"], "enabled": False}
        self.opencode_json.parent.mkdir(parents=True)
        self.opencode_json.write_text(json.dumps({"mcp": {"codegraph": previous}}, indent=2) + "\n")
        before = self.snapshot()
        code, out, err = self.install()
        self.assertEqual(code, 2)
        self.assertIn("/mcp/codegraph", out)
        self.assertEqual(self.snapshot(), before)

        self.assertEqual(self.install("--adopt")[0], 0)
        doc = json.loads(self.opencode_json.read_text())
        self.assertEqual(doc["mcp"]["codegraph"]["command"], ["codegraph", "serve", "--mcp"])
        record = self.ledger()["json"][str(self.opencode_json)]["/mcp/codegraph"]
        self.assertEqual(record["before"], previous)
        self.assertEqual(record["applied"], doc["mcp"]["codegraph"])
        self.assertIsNone(self.ledger()["json"][str(self.opencode_json)]["/mcp/graphiti-memory"]["before"])

        code, out, err = self.run_cli("uninstall")
        self.assertEqual(code, 0, out + err)
        doc = json.loads(self.opencode_json.read_text())
        self.assertEqual(doc, {"mcp": {"codegraph": previous}})

    def test_uninstall_leaves_a_json_key_the_user_changed(self):
        self.assertEqual(self.install()[0], 0)
        doc = json.loads(self.opencode_json.read_text())
        doc["mcp"]["codegraph"]["enabled"] = False
        self.opencode_json.write_text(json.dumps(doc))
        self.assertEqual(self.run_cli("uninstall")[0], 0)
        left = json.loads(self.opencode_json.read_text())
        self.assertEqual(list(left["mcp"]), ["codegraph"])
        self.assertFalse(left["mcp"]["codegraph"]["enabled"])

    def test_modified_json_key_is_refused_then_forced(self):
        self.assertEqual(self.install()[0], 0)
        doc = json.loads(self.opencode_json.read_text())
        doc["mcp"]["codegraph"]["enabled"] = False
        self.opencode_json.write_text(json.dumps(doc))
        self.assertEqual(self.install()[0], 2)
        self.assertEqual(self.install("--force")[0], 0)
        self.assertTrue(json.loads(self.opencode_json.read_text())["mcp"]["codegraph"]["enabled"])

    def test_invalid_json_is_a_conflict(self):
        self.opencode_json.parent.mkdir(parents=True)
        self.opencode_json.write_text("{ not json")
        code, out, err = self.install()
        self.assertEqual(code, 2)
        self.assertEqual(self.opencode_json.read_text(), "{ not json")

    # -- runtime.json
    def test_runtime_json_shape(self):
        self.write_config(coretest.BASE_CONFIG + '\n[codegraph]\nroots = ["/srv"]\nextra_manifests = ["m.toml"]\n'
                          'extra_ignored = ["vendor"]\n')
        self.assertEqual(self.install()[0], 0)
        runtime = json.loads(self.runtime.read_text())
        self.assertEqual(runtime["schema"], 1)
        self.assertEqual(runtime["ui"], "en")
        self.assertEqual(runtime["paths"], {
            "home": str(self.home), "claude_dir": str(self.claude_dir),
            "opencode_data_dir": str(self.home / ".local" / "share" / "opencode"),
            "state_dir": str(self.state_dir)})
        self.assertEqual(runtime["codegraph"], {"gate": True, "nudge_every": 4, "roots": ["/srv"],
                                                "manifests": ["m.toml"], "ignored": ["vendor"]})
        self.assertEqual(runtime["memory"], {"mcp_server": "graphiti-memory", "min_edits": 8,
                                             "min_executor_runs": 2, "cooldown_seconds": 2700})
        self.assertEqual(runtime["executors"], {"launcher_regex": "opencode run "})
        self.assertEqual(runtime["usage"], {"model_order": ["opus", "sonnet", "haiku", "gpt", "minimax"]})

    def test_runtime_json_is_regenerated_even_if_edited(self):
        self.assertEqual(self.install()[0], 0)
        self.runtime.write_text("{}")
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(json.loads(self.runtime.read_text())["schema"], 1)

    # -- dry run
    def test_dry_run_writes_nothing_and_prints_the_ordered_plan(self):
        self.claude_md.parent.mkdir(parents=True)
        self.claude_md.write_text("mine\n")
        self.add_fake_claude()
        before = self.snapshot()
        code, out, err = self.install("--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.state_dir.exists())
        self.assertFalse(self.runtime.exists())
        self.assertEqual(self.claude_calls(), [])
        lines = [line for line in out.splitlines() if line.startswith("[")]
        order = [out.index(str(p)) for p in (self.claude_md, self.agents_md, self.profile, self.writer,
                                              self.reviewer, self.skill, self.opencode_json, self.runtime)]
        self.assertEqual(order, sorted(order))
        self.assertGreater(len(lines), 8)
        self.assertIn("claude plugin marketplace add", out)
        self.assertIn("podium-memory@podium", out)
        self.assertIn("nothing written", out)

    def test_dry_run_reports_conflicts_with_exit_2(self):
        self.writer.parent.mkdir(parents=True)
        self.writer.write_text("mine\n")
        code, out, err = self.install("--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("[conflict]", out)
        self.assertEqual(self.writer.read_text(), "mine\n")

    # -- plugins
    def test_plugins_are_installed_in_order_with_claude_on_path(self):
        self.add_fake_claude()
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        calls = [c for c in self.claude_calls() if not c.startswith("mcp ")]
        self.assertEqual(calls[0], "plugin marketplace add %s" % coretest.FIXTURE_HOME)
        self.assertEqual(calls[1:], ["plugin install %s@podium --scope user" % name for name in
                                     ("podium-codegraph", "podium-memory", "podium-usage", "podium-upgrade")])

    def test_disabled_modules_are_not_installed(self):
        self.add_fake_claude()
        self.write_config(coretest.BASE_CONFIG + "\n[modules]\nusage = false\nupgrade = false\n")
        self.assertEqual(self.install()[0], 0)
        plugin_calls = [c for c in self.claude_calls() if not c.startswith("mcp ")]
        installs = [c for c in plugin_calls[1:] if c.startswith("plugin install")]
        self.assertEqual([c.split()[2] for c in installs], ["podium-codegraph@podium", "podium-memory@podium"])
        # disabled modules get their plugin uninstalled (tolerated when not installed)
        self.assertEqual([c for c in plugin_calls[1:] if c.startswith("plugin uninstall")],
                         ["plugin uninstall podium-usage@podium --scope user",
                          "plugin uninstall podium-upgrade@podium --scope user"])

    def test_missing_claude_warns_and_skips(self):
        code, out, err = self.install()
        self.assertEqual(code, 0, out + err)
        self.assertIn("claude not found", out)
        self.assertTrue(self.runtime.is_file())

    def test_marketplace_failure_is_fatal(self):
        self.add_fake_claude()
        code, out, err = self.install(FAKE_CLAUDE_FAIL="marketplace")
        self.assertEqual(code, 3)
        self.assertIn("marketplace", err)
        self.assertIn("steps applied before the failure", out)
        self.assertEqual(len(self.claude_calls()), 1)

    def test_plugin_install_failure_is_reported_not_fatal(self):
        self.add_fake_claude()
        code, out, err = self.install(FAKE_CLAUDE_FAIL="podium-usage")
        self.assertEqual(code, 0, out + err)
        self.assertIn("warning", out)
        self.assertEqual(len([c for c in self.claude_calls() if not c.startswith("mcp ")]), 5)

    # -- modules
    def test_modules_flag_restricts_the_actions(self):
        code, out, err = self.install("--modules", "rules")
        self.assertEqual(code, 0, out + err)
        self.assertTrue(self.claude_md.is_file())
        self.assertFalse(self.writer.exists())
        self.assertFalse(self.opencode_json.exists())
        self.assertTrue(self.runtime.is_file())
        code, out, err = self.install("--modules", "bogus")
        self.assertEqual(code, 1)

    # -- uninstall
    def test_uninstall_removes_everything_podium_wrote(self):
        self.claude_md.parent.mkdir(parents=True)
        self.claude_md.write_text("# mine\n\nkeep\n")
        self.opencode_json.parent.mkdir(parents=True)
        self.opencode_json.write_text(json.dumps({"theme": "x"}) + "\n")
        self.add_fake_claude()
        self.assertEqual(self.install()[0], 0)
        code, out, err = self.run_cli("uninstall")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.claude_md.read_text(), "# mine\n\nkeep\n")
        self.assertEqual(json.loads(self.opencode_json.read_text()), {"theme": "x"})
        for path in (self.writer, self.reviewer, self.profile, self.runtime, self.skill, self.agents_md.parent / "agents",
                     self.oc_dir / "skills", self.state_dir / "owned.json"):
            if path.name == "AGENTS.md":
                continue
            self.assertFalse(path.exists(), path)
        self.assertIn("plugin uninstall podium-memory@podium --scope user", "\n".join(self.claude_calls()))

    def test_uninstall_keeps_modified_owned_files(self):
        self.assertEqual(self.install()[0], 0)
        self.writer.write_text("edited\n")
        code, out, err = self.run_cli("uninstall")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.writer.read_text(), "edited\n")
        self.assertFalse(self.reviewer.exists())
        self.assertIn("[keep]", out)

    def test_uninstall_dry_run_writes_nothing(self):
        self.assertEqual(self.install()[0], 0)
        before = self.snapshot()
        code, out, err = self.run_cli("uninstall", "--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("[remove]", out)

    def test_uninstall_without_install_is_a_no_op(self):
        code, out, err = self.run_cli("uninstall")
        self.assertEqual(code, 0, out + err)

    def test_lock_held_by_another_run_gives_exit_3(self):
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "lock").write_text("1\n")
        code, out, err = self.install()
        self.assertEqual(code, 3)
        self.assertIn("another podium run", err)


if __name__ == "__main__":
    unittest.main()
