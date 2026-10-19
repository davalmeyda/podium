"""Behaviour tests for plugins/podium-usage/scripts/session_usage.py.

Each test builds synthetic Claude transcripts, a synthetic opencode.db, an
isolated PODIUM_CONFIG_DIR (for runtime.json) and a temp plugin root (so the
locale files can be replaced without touching the real ones). The script is
run as a subprocess with `python3 -I` and the JSON output is asserted.

Stdlib only (python3 -m unittest).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "podium-usage" / "scripts" / "session_usage.py"
SRC_LOCALES = REPO_ROOT / "plugins" / "podium-usage" / "locales"


def _msg(usage, *, mid=None, model="claude-haiku-5-5", effort=None, uuid=None):
    """Build one assistant message line with the given usage (and optional effort)."""
    d = {
        "type": "assistant",
        "uuid": uuid or "u",
        "message": {
            "id": mid or "m",
            "role": "assistant",
            "model": model,
            "usage": usage,
        },
    }
    if effort is not None:
        d["message"]["effort"] = effort
        d["effort"] = effort  # also at the top level (where session_usage reads it)
    return d


def write_transcript(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def write_runtime(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def write_locales(plugin_root, en_dict, es_dict=None):
    loc_dir = plugin_root / "locales"
    loc_dir.mkdir(parents=True, exist_ok=True)
    with open(loc_dir / "en.json", "w", encoding="utf-8") as fh:
        json.dump(en_dict, fh)
    if es_dict is not None:
        with open(loc_dir / "es.json", "w", encoding="utf-8") as fh:
            json.dump(es_dict, fh)


def run_session_usage(env, sid, script=SCRIPT):
    proc = subprocess.run(
        [sys.executable, str(script), sid],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    return proc


class SessionUsageTestCase(unittest.TestCase):
    """Each test runs in an isolated temp HOME/PODIUM_CONFIG_DIR and a synthetic
    plugin root (so locale files can be replaced safely)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="podium-usage-test-")
        self.base = Path(self.tmp)
        # Synthetic plugin root with locales, mirroring the real layout.
        self.plugin_root = self.base / "plugin"
        self.env = dict(os.environ)
        self.env["HOME"] = str(self.base)
        self.env["XDG_CONFIG_HOME"] = str(self.base / "xdg-config")
        self.env["XDG_DATA_HOME"] = str(self.base / "xdg-data")
        self.env["XDG_STATE_HOME"] = str(self.base / "xdg-state")
        self.env["CLAUDE_CONFIG_DIR"] = str(self.base / "claude")
        self.env["PODIUM_CONFIG_DIR"] = str(self.base / "podium")
        # Sandbox per-test script copy under the synthetic plugin root, so the
        # script sees PLUGIN_ROOT = self.plugin_root and finds our locales.
        plugin_scripts = self.plugin_root / "scripts"
        plugin_scripts.mkdir(parents=True, exist_ok=True)
        self.script = plugin_scripts / "session_usage.py"
        shutil.copy(SCRIPT, self.script)
        # Copy the real locales by default; tests can overwrite selectively.
        locales = self.plugin_root / "locales"
        locales.mkdir(parents=True, exist_ok=True)
        shutil.copy(SRC_LOCALES / "en.json", locales / "en.json")
        shutil.copy(SRC_LOCALES / "es.json", locales / "es.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _claude_project(self, sid):
        # CLAUDE_PROJECTS = $CLAUDE_CONFIG_DIR/projects/<project>/<sid>.jsonl
        d = self.base / "claude" / "projects" / "podium-usage"
        d.mkdir(parents=True, exist_ok=True)
        return d / (sid + ".jsonl")

    def _write_runtime(self, data=None):
        path = self.base / "podium" / "runtime.json"
        write_runtime(path, data or {"schema": 1, "ui": "en"})
        return path

    def _write_opencode_db(self, sid, rows):
        """Create a synthetic opencode.db with the given (variant, tokens_json)
        pairs joined into one parent + one child session."""
        db = self.base / "xdg-data" / "opencode" / "opencode.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        prefix = "ses_cc" + sid.replace("-", "") + "x"
        parent = prefix + "abcd0"
        child = prefix + "abcd1"
        c = sqlite3.connect(str(db))
        c.execute("create table session_v2 (id text primary key, parent_id text, time_created integer)")
        c.execute("create table session_message (id text primary key, session_id text, type text, time_created integer, data text)")
        c.execute("insert into session_v2 values (?, NULL, ?)", (parent, 1_700_000_000))
        c.execute("insert into session_v2 values (?, ?, ?)", (child, parent, 1_700_000_000))
        for i, (variant, tokens_json) in enumerate(rows, start=1):
            data = json.dumps({
                "model": {"providerID": "minimax", "id": "MiniMax-M3", "variant": variant},
                "tokens": tokens_json,
            })
            c.execute("insert into session_message values (?, ?, 'assistant', ?, ?)",
                      (f"m{i}", parent, 1_700_000_000, data))
        c.commit()
        c.close()
        return db

    # ------------------------------------------------------------------
    # Effort accounting — separate rows per effort (decision 1).
    def test_claude_effort_is_separate_variant(self):
        self._write_runtime()
        sid = "ffffffff-aaaa-bbbb-cccc-111111111111"
        tf = self._claude_project(sid)
        write_transcript(tf, [
            _msg({"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                 mid="m1", model="claude-opus-5-5", effort="medium", uuid="u1"),
            _msg({"input_tokens": 20, "output_tokens": 7, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                 mid="m2", model="claude-opus-5-5", effort="high", uuid="u2"),
            _msg({"input_tokens": 30, "output_tokens": 9, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                 mid="m3", model="claude-opus-5-5", effort=None, uuid="u3"),
        ])
        proc = run_session_usage(self.env, sid, script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        opus = [r for r in d["rows"] if r["engine"] == "claude" and r["model"] == "claude-opus-5-5"]
        # Three separate buckets: medium, high, and empty (no effort).
        variants = sorted(r["variant"] for r in opus)
        self.assertEqual(variants, ["", "high", "medium"])
        # Specific buckets hold the right tokens.
        by_variant = {r["variant"]: r for r in opus}
        self.assertEqual(by_variant["medium"]["in"], 10)
        self.assertEqual(by_variant["high"]["in"], 20)
        self.assertEqual(by_variant[""]["in"], 30)

    def test_claude_effort_same_message_id_keeps_one_bucket(self):
        """The same message repeats across several lines (one block per line)
        and the script dedups by message.id. effort is read once per message too,
        so duplicate lines keep a single bucket per (model, effort)."""
        self._write_runtime()
        sid = "ffffffff-aaaa-bbbb-cccc-222222222222"
        tf = self._claude_project(sid)
        # Same message.id, same effort, different lines → one bucket.
        write_transcript(tf, [
            _msg({"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                 mid="m_same", model="claude-opus-5-5", effort="medium", uuid="u1"),
            _msg({"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                 mid="m_same", model="claude-opus-5-5", effort="medium", uuid="u2"),
        ])
        proc = run_session_usage(self.env, sid, script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        opus = [r for r in d["rows"] if r["engine"] == "claude" and r["model"] == "claude-opus-5-5"]
        self.assertEqual(len(opus), 1, opus)
        self.assertEqual(opus[0]["variant"], "medium")
        self.assertEqual(opus[0]["in"], 10)  # not 20 — deduped

    # ------------------------------------------------------------------
    # Wrong-shape runtime.json (decision 4) — falls back, one error, accounting
    # still produces JSON with rows.
    def test_runtime_json_array_falls_back_with_one_error(self):
        sid = "ffffffff-aaaa-bbbb-cccc-333333333333"
        self._write_opencode_db(sid, [("none", {"input": 5, "output": 3, "cache": {"read": 0, "write": 0}})])
        path = self._write_runtime()
        path.write_bytes(b'[5, 6, 7]')
        proc = run_session_usage(self.env, sid, script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        # Still valid JSON, runtime falls back to en, accounting produced rows.
        self.assertEqual(d["runtime"]["ui"], "en")
        self.assertEqual(d["runtime"]["usage"]["model_order"], [])
        self.assertTrue(any(r["engine"] == "opencode" for r in d["rows"]))
        # Exactly one runtime: error line.
        runtime_errs = [e for e in d["errors"] if e.startswith("runtime:")]
        self.assertEqual(len(runtime_errs), 1, d["errors"])
        self.assertIn("expected object", runtime_errs[0])

    def test_runtime_json_null_falls_back_with_one_error(self):
        sid = "ffffffff-aaaa-bbbb-cccc-444444444444"
        self._write_opencode_db(sid, [("none", {"input": 1, "output": 1, "cache": {"read": 0, "write": 0}})])
        path = self._write_runtime()
        path.write_text("null")
        proc = run_session_usage(self.env, sid, script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        runtime_errs = [e for e in d["errors"] if e.startswith("runtime:")]
        self.assertEqual(len(runtime_errs), 1, d["errors"])
        self.assertEqual(d["runtime"]["ui"], "en")

    def test_runtime_json_string_falls_back_with_one_error(self):
        sid = "ffffffff-aaaa-bbbb-cccc-555555555555"
        self._write_opencode_db(sid, [("none", {"input": 1, "output": 1, "cache": {"read": 0, "write": 0}})])
        path = self._write_runtime()
        path.write_text('"not a config"')
        proc = run_session_usage(self.env, sid, script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        runtime_errs = [e for e in d["errors"] if e.startswith("runtime:")]
        self.assertEqual(len(runtime_errs), 1, d["errors"])
        self.assertEqual(d["runtime"]["ui"], "en")

    def test_runtime_json_usage_string_falls_back_safely(self):
        """When `usage` itself is wrong-shaped (a string, not an object),
        model_order stays at the empty default; we don't crash."""
        sid = "ffffffff-aaaa-bbbb-cccc-666666666666"
        self._write_opencode_db(sid, [("none", {"input": 1, "output": 1, "cache": {"read": 0, "write": 0}})])
        path = self._write_runtime({"schema": 1, "ui": "es", "usage": "broken"})
        proc = run_session_usage(self.env, sid, script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        # ui still read (top-level dict), model_order is the empty default.
        self.assertEqual(d["runtime"]["ui"], "es")
        self.assertEqual(d["runtime"]["usage"]["model_order"], [])

    def test_locale_json_array_falls_back_with_one_error(self):
        """Locale file present but wrong shape (array, not object): one error,
        locale falls back to en built-in defaults, script keeps running."""
        sid = "ffffffff-aaaa-bbbb-cccc-777777777777"
        self._write_opencode_db(sid, [("none", {"input": 1, "output": 1, "cache": {"read": 0, "write": 0}})])
        self._write_runtime({"schema": 1, "ui": "es"})
        (self.plugin_root / "locales" / "es.json").write_text("[1, 2, 3]")
        proc = run_session_usage(self.env, sid, script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        locale_errs = [e for e in d["errors"] if e.startswith("locale(")]
        self.assertEqual(len(locale_errs), 1, d["errors"])
        self.assertIn("expected object", locale_errs[0])
        # Falls back to en's pane_title.
        self.assertEqual(d["locale"]["pane_title"], "Tokens")
        # Accounting still ran.
        self.assertTrue(any(r["engine"] == "opencode" for r in d["rows"]))

    def test_locale_json_null_falls_back_with_one_error(self):
        sid = "ffffffff-aaaa-bbbb-cccc-888888888888"
        self._write_opencode_db(sid, [("none", {"input": 1, "output": 1, "cache": {"read": 0, "write": 0}})])
        self._write_runtime({"schema": 1, "ui": "es"})
        (self.plugin_root / "locales" / "es.json").write_text("null")
        proc = run_session_usage(self.env, sid, script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        locale_errs = [e for e in d["errors"] if e.startswith("locale(")]
        self.assertEqual(len(locale_errs), 1, d["errors"])
        self.assertEqual(d["locale"]["pane_title"], "Tokens")

    def test_per_engine_isolation_when_locale_corrupt(self):
        """An opencode-side row survives a corrupt locale."""
        sid = "ffffffff-aaaa-bbbb-cccc-999999999999"
        self._write_opencode_db(sid, [("none", {"input": 100, "output": 50, "cache": {"read": 5, "write": 0}})])
        self._write_runtime()
        # Make BOTH locales corrupt so the script must use the built-in defaults.
        (self.plugin_root / "locales" / "en.json").write_text("[1, 2]")
        proc = run_session_usage(self.env, sid, script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        # Opencode accounting was not aborted.
        oc_rows = [r for r in d["rows"] if r["engine"] == "opencode"]
        self.assertEqual(len(oc_rows), 1, d["rows"])
        self.assertEqual(oc_rows[0]["in"], 100)
        self.assertEqual(oc_rows[0]["out"], 50)
        # Errors are reported for each failed locale load.
        self.assertTrue(any(e.startswith("locale(") for e in d["errors"]))

    # ------------------------------------------------------------------
    # Generic fallback (decision 2) — no personal names in the code default.
    def test_default_model_order_is_empty(self):
        # The neutral default must not carry personal roster names; the
        # display layer falls back to total-tokens order (TS side). No
        # transcripts / DB are needed: an empty sid with no DB is fine,
        # load_runtime() runs before any aggregation.
        self._write_runtime()  # also missing → no error, no model_order
        proc = run_session_usage(self.env, "no-such-sid", script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        self.assertEqual(d["runtime"]["usage"]["model_order"], [])
        self.assertEqual(d["runtime"]["ui"], "en")

    def test_runtime_with_personal_names_passes_through(self):
        # When runtime.json DOES set model_order, those fragments are passed
        # through verbatim (they are regex fragments, not strict model names).
        self._write_runtime({"schema": 1, "ui": "en", "usage": {"model_order": ["opus", "sonnet"]}})
        proc = run_session_usage(self.env, "no-such-sid", script=self.script)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        d = json.loads(proc.stdout)
        self.assertEqual(d["runtime"]["usage"]["model_order"], ["opus", "sonnet"])

    # ------------------------------------------------------------------
    # Locale `reader_error` key exists in both shipped locales (decision 3).
    def test_locales_have_reader_error_key(self):
        en = json.loads((SRC_LOCALES / "en.json").read_text())
        es = json.loads((SRC_LOCALES / "es.json").read_text())
        self.assertIn("reader_error", en)
        self.assertIn("reader_error", es)
        self.assertTrue(en["reader_error"].strip())
        self.assertTrue(es["reader_error"].strip())


if __name__ == "__main__":
    unittest.main()