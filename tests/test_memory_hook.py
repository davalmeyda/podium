"""Behaviour tests for the podium-memory stop hook.

Each test builds a synthetic Claude Code transcript in a temp file, runs
``hooks/memory-stop.py`` as a subprocess with isolated PODIUM_CONFIG_DIR,
PODIUM_STATE_DIR and CLAUDE_CONFIG_DIR, and asserts the JSON output plus the
scratch state under state_dir/sessions/.

Stdlib only (python3 -m unittest).
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "plugins" / "podium-memory" / "hooks" / "memory-stop.py"


def _msg(tool_uses):
    """Build one assistant message line containing the given tool_uses."""
    content = []
    for name, inp in tool_uses:
        content.append({"type": "tool_use", "name": name, "input": inp})
    return {"type": "assistant", "message": {"content": content}}


def _user(text="hi"):
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}


def write_transcript(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _set_env(env, base):
    env["PODIUM_CONFIG_DIR"] = str(base / "config")
    env["PODIUM_STATE_DIR"] = str(base / "state")
    env["CLAUDE_CONFIG_DIR"] = str(base / "claude")
    env["HOME"] = str(base)
    env["XDG_DATA_HOME"] = str(base / "xdg-data")
    env["XDG_STATE_HOME"] = str(base / "xdg-state")
    env["XDG_CONFIG_HOME"] = str(base / "xdg-config")
    env.pop("PODIUM_UI", None)
    return env


def _write_runtime(base, ui="en", **mem_overrides):
    (base / "config").mkdir(parents=True, exist_ok=True)
    cfg = {
        "schema": 1,
        "ui": ui,
        "memory": {
            "mcp_server": "graphiti-memory",
            "min_edits": 8,
            "min_executor_runs": 2,
            "cooldown_seconds": 0,  # tests want no cooldown by default
        },
        "executors": {"launcher_regex": r"\bopencode\s+run\s"},
    }
    if mem_overrides:
        cfg["memory"].update(mem_overrides)
    with open(base / "config" / "runtime.json", "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)


class MemoryHookTestCase(unittest.TestCase):
    """Each test runs in an isolated temp HOME/PODIUM_STATE_DIR."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="podium-mem-test-")
        self.base = Path(self.tmp)
        self.env = _set_env(dict(os.environ), self.base)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    def run_hook(self, transcript, payload_extra=None, session="s1"):
        payload = {
            "session_id": session,
            "transcript_path": str(transcript),
        }
        if payload_extra:
            payload.update(payload_extra)
        proc = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.env,
            timeout=20,
        )
        return proc

    def _make_transcript(self, tools, extras=()):
        path = self.base / "transcript.jsonl"
        lines = [_user()] + list(extras)
        # bundle the tool calls in one assistant message — graphiti-stop.py
        # collects them per message; multiple messages also work.
        for batch in tools:
            lines.append(_msg(batch))
        write_transcript(path, lines)
        return path

    def _scratch(self, session="s1"):
        return self.base / "state" / "sessions" / f"memory-stop-{session}.json"

    # ------------------------------------------------------------------
    # threshold: 8 edits → block, 7 → no block
    def test_block_at_eight_edits(self):
        _write_runtime(self.base)
        edits = [("Write", {"file_path": "/repo/a.py"})] * 8
        tr = self._make_transcript([edits])
        proc = self.run_hook(tr)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out["decision"], "block")
        self.assertIn("podium-memory:project-memory", out["reason"])
        self.assertIn("8", out["reason"])
        # scratch state recorded
        st = json.loads(self._scratch().read_text())
        self.assertEqual(st["at"], 8)

    def test_no_block_at_seven_edits(self):
        _write_runtime(self.base)
        edits = [("Write", {"file_path": "/repo/a.py"})] * 7
        tr = self._make_transcript([edits])
        proc = self.run_hook(tr)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")
        # no scratch file yet
        self.assertFalse(self._scratch().exists())

    # ------------------------------------------------------------------
    # executor threshold: 2 launcher commands
    def test_block_at_two_executor_runs(self):
        _write_runtime(self.base)
        runs = [("Bash", {"command": "opencode run --agent a"})] * 2
        tr = self._make_transcript([runs])
        proc = self.run_hook(tr)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out["decision"], "block")
        self.assertIn("2", out["reason"])

    def test_no_block_at_one_executor_run(self):
        _write_runtime(self.base)
        runs = [("Bash", {"command": "opencode run --agent a"})]
        tr = self._make_transcript([runs])
        proc = self.run_hook(tr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_non_launcher_bash_does_not_count(self):
        _write_runtime(self.base)
        # 5 plain bash calls → still under threshold
        plain = [("Bash", {"command": "ls -l" * i}) for i in range(1, 6)]
        tr = self._make_transcript([plain])
        proc = self.run_hook(tr)
        self.assertEqual(proc.stdout.strip(), "")

    # ------------------------------------------------------------------
    # reset after add_memory tool call
    def test_reset_after_add_memory(self):
        _write_runtime(self.base)
        # 10 edits, then 1 add_memory, then 5 edits → threshold on the
        # 5 after the save should NOT trigger (only 5 after, threshold 8).
        edits_a = [("Write", {"file_path": "/repo/a.py"})] * 10
        save = [("graphiti-memory__add_memory", {"name": "x"})]
        edits_b = [("Write", {"file_path": "/repo/b.py"})] * 5
        tr = self._make_transcript([edits_a, save, edits_b])
        proc = self.run_hook(tr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_block_only_after_reset_when_threshold_crossed_again(self):
        _write_runtime(self.base)
        edits_a = [("Write", {"file_path": "/repo/a.py"})] * 10
        save = [("graphiti-memory__add_memory", {"name": "x"})]
        edits_b = [("Write", {"file_path": "/repo/b.py"})] * 9
        tr = self._make_transcript([edits_a, save, edits_b])
        proc = self.run_hook(tr)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out["decision"], "block")

    # ------------------------------------------------------------------
    # cooldown suppresses a second block
    def test_cooldown_suppresses_second_block(self):
        _write_runtime(self.base, cooldown_seconds=3600)
        edits = [("Write", {"file_path": "/repo/a.py"})] * 8
        tr = self._make_transcript([edits])
        first = self.run_hook(tr)
        self.assertEqual(first.returncode, 0)
        self.assertIn("block", first.stdout)

        # second invocation with another transcript → cooldown suppresses
        tr2 = self._make_transcript([edits], extras=[_user("again")])
        proc = self.run_hook(tr2, session="s1")
        self.assertEqual(proc.stdout.strip(), "")

    def test_cooldown_zero_allows_re_block(self):
        _write_runtime(self.base, cooldown_seconds=0)
        edits = [("Write", {"file_path": "/repo/a.py"})] * 8
        tr = self._make_transcript([edits])
        first = self.run_hook(tr)
        self.assertIn("block", first.stdout)
        # cooldown=0 → second invocation with another 8 edits beyond the
        # previous nudge point also blocks
        more = [("Write", {"file_path": "/repo/x.py"})] * 8
        tr2 = self._make_transcript([edits, more], extras=[_user("again")])
        proc = self.run_hook(tr2, session="s1")
        self.assertIn("block", proc.stdout)

    # ------------------------------------------------------------------
    # stop_hook_active returns nothing
    def test_stop_hook_active_returns_nothing(self):
        _write_runtime(self.base)
        edits = [("Write", {"file_path": "/repo/a.py"})] * 12
        tr = self._make_transcript([edits])
        proc = self.run_hook(tr, payload_extra={"stop_hook_active": True})
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertFalse(self._scratch().exists())

    # ------------------------------------------------------------------
    # ignored temp paths not counted
    def test_tempfile_paths_ignored(self):
        _write_runtime(self.base)
        import tempfile as tf
        tmpdir = tf.gettempdir()
        # build 10 edits all under tempfile.gettempdir()
        edits = [
            ("Write", {"file_path": f"{tmpdir}/scratch_{i}.py"})
            for i in range(10)
        ]
        tr = self._make_transcript([edits])
        proc = self.run_hook(tr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_private_tmp_ignored_on_macos(self):
        _write_runtime(self.base)
        edits = [
            ("Write", {"file_path": f"/private/tmp/x_{i}.py"})
            for i in range(10)
        ]
        tr = self._make_transcript([edits])
        proc = self.run_hook(tr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_claude_projects_dir_ignored(self):
        _write_runtime(self.base)
        claude_dir = self.base / "claude"
        # CLAUDE_CONFIG_DIR = base/paths; .claude/projects/ is on the
        # ignored list per the contract.
        edits = [
            ("Write", {"file_path": f"{claude_dir}/projects/foo/{i}.md"})
            for i in range(10)
        ]
        tr = self._make_transcript([edits])
        proc = self.run_hook(tr)
        self.assertEqual(proc.stdout.strip(), "")

    # ------------------------------------------------------------------
    # custom MCP server name honoured
    def test_custom_mcp_server_name(self):
        _write_runtime(self.base, mcp_server="podium-memory")
        # save uses the configured name → count resets
        edits_a = [("Write", {"file_path": "/repo/a.py"})] * 10
        save = [("podium-memory__add_memory", {"name": "x"})]
        edits_b = [("Write", {"file_path": "/repo/b.py"})] * 5
        tr = self._make_transcript([edits_a, save, edits_b])
        proc = self.run_hook(tr)
        # 5 edits after reset → below threshold of 8
        self.assertEqual(proc.stdout.strip(), "")

        # a save with the default name should NOT reset when the configured
        # server is "podium-memory"
        save_default = [("graphiti-memory__add_memory", {"name": "y"})]
        edits_c = [("Write", {"file_path": "/repo/c.py"})] * 8
        tr2 = self._make_transcript(
            [edits_a, save_default, edits_c]
        )
        proc2 = self.run_hook(tr2, session="s2")
        out = json.loads(proc2.stdout.strip())
        self.assertEqual(out["decision"], "block")

    # ------------------------------------------------------------------
    # locale text: en and es
    def test_en_locale_text(self):
        _write_runtime(self.base, ui="en")
        edits = [("Write", {"file_path": "/repo/a.py"})] * 8
        tr = self._make_transcript([edits])
        proc = self.run_hook(tr)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out["decision"], "block")
        self.assertIn("podium-memory:project-memory", out["reason"])
        self.assertIn("Nothing to record in memory", out["reason"])

    def test_es_locale_text(self):
        _write_runtime(self.base, ui="es")
        edits = [("Write", {"file_path": "/repo/a.py"})] * 8
        tr = self._make_transcript([edits])
        proc = self.run_hook(tr)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out["decision"], "block")
        # Spanish reason must contain the literal "Nada que registrar en Graphiti."
        self.assertIn("Nada que registrar en Graphiti.", out["reason"])
        # And the namespaced skill
        self.assertIn("podium-memory:project-memory", out["reason"])

    # ------------------------------------------------------------------
    # fail-open: malformed stdin → no stdout, no crash
    def test_malformed_stdin_fails_open(self):
        _write_runtime(self.base)
        proc = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json",
            capture_output=True,
            text=True,
            env=self.env,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_missing_transcript_fails_open(self):
        _write_runtime(self.base)
        proc = self.run_hook(None)  # never written
        self.assertEqual(proc.stdout.strip(), "")

    # ------------------------------------------------------------------
    # launcher_regex from runtime is honoured
    def test_custom_launcher_regex(self):
        _write_runtime(self.base)
        # customise regex to a non-default pattern
        rt_path = self.base / "config" / "runtime.json"
        cfg = json.loads(rt_path.read_text())
        cfg["executors"]["launcher_regex"] = r"claude\s+run\s"
        rt_path.write_text(json.dumps(cfg))

        # "opencode run " is the default, but our regex now matches
        # "claude run " — opencode calls should NOT count
        edits = [("Bash", {"command": "opencode run --agent a"})] * 3
        tr = self._make_transcript([edits])
        proc = self.run_hook(tr)
        self.assertEqual(proc.stdout.strip(), "")

        # "claude run " should count
        claude_runs = [("Bash", {"command": "claude run --model x"})] * 2
        tr2 = self._make_transcript([claude_runs])
        proc2 = self.run_hook(tr2, session="s2")
        out = json.loads(proc2.stdout.strip())
        self.assertEqual(out["decision"], "block")


if __name__ == "__main__":
    unittest.main()