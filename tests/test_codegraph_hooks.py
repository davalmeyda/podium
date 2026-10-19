"""Behaviour tests for the podium-codegraph plugin hooks.

Runs the gate and nudge hooks as subprocesses with JSON stdin under temp
HOME / PODIUM_CONFIG_DIR / PODIUM_STATE_DIR.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_HOOKS = REPO_ROOT / "plugins" / "podium-codegraph" / "hooks"
GATE = PLUGIN_HOOKS / "codegraph-gate.py"
NUDGE = PLUGIN_HOOKS / "codegraph-nudge.py"

# Reference implementation used for the parity (golden) test only.
# Optional parity check against a hand-written reference hook (set the env var to its path).
ORIGINAL_GATE = Path(os.environ.get("PODIUM_REFERENCE_GATE", "/nonexistent/codegraph-gate.py"))

# System dirs the hook treats as ignored. Matches the original behavior so the
# parity test can detect when its tempdir sits beneath one.
_SYSTEM_IGNORED = {
    "darwin": ("/private/tmp", "/tmp", "/var", "/opt", "/usr",
               "/Applications", "/System"),
    "linux": ("/tmp", "/var", "/opt", "/usr", "/proc", "/sys",
              "/run", "/snap", "/etc", "/boot"),
}


def _make_env(tmp):
    env = {
        "HOME": str(tmp / "home"),
        "PODIUM_CONFIG_DIR": str(tmp / "config"),
        "PODIUM_STATE_DIR": str(tmp / "state"),
        "CLAUDE_CONFIG_DIR": str(tmp / "home" / ".claude"),
        "XDG_CONFIG_HOME": str(tmp / "xdg-conf"),
        "XDG_STATE_HOME": str(tmp / "xdg-state"),
        "XDG_DATA_HOME": str(tmp / "xdg-data"),
        "PATH": os.environ.get("PATH", ""),
    }
    for k, v in env.items():
        if v:
            os.makedirs(v, exist_ok=True)
    return env


def _write_runtime(cfg_dir, state_dir, ui="en", gate=True, roots=None,
                   manifests=None, ignored=None, nudge_every=4,
                   home=None, claude_dir=None, opencode_data_dir=None):
    os.makedirs(cfg_dir, exist_ok=True)
    payload = {
        "schema": 1,
        "ui": ui,
        "paths": {
            "home": home or str(Path(cfg_dir).parent / "home"),
            "claude_dir": claude_dir or str(Path(cfg_dir).parent / "home" / ".claude"),
            "opencode_data_dir": opencode_data_dir or str(Path(cfg_dir).parent / "xdg-data" / "opencode"),
            "state_dir": state_dir,
        },
        "codegraph": {
            "gate": gate,
            "nudge_every": nudge_every,
            "roots": roots or [],
            "manifests": manifests or [],
            "ignored": ignored or [],
        },
    }
    with open(os.path.join(cfg_dir, "runtime.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _run_hook(hook_path, env):
    """Run a hook subprocess with stdin from STDIN_JSON env var."""
    stdin_payload = env.pop("__STDIN__", "{}")
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=stdin_payload.encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=15,
    )
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _make_project(root, name="myapp", manifest="package.json", content=None):
    p = Path(root) / name
    p.mkdir(parents=True, exist_ok=True)
    (p / manifest).write_text(content or '{"name": "x"}')
    return str(p)


def _safe_tempdir():
    """Create a tempdir NOT under any system-ignored path so the hook's
    ignored-dir short-circuit does not eat the project path."""
    base = Path.home()
    base.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="podium-cg-test-", dir=str(base))


class GateHookTests(unittest.TestCase):

    def test_denies_read_in_unindexed_project(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(project, "foo.txt")},
                "cwd": project,
            }
            env["__STDIN__"] = json.dumps(payload)
            rc, out, err = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertFalse(err.strip())
            data = json.loads(out)
            self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")
            reason = data["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertIn("CodeGraph", reason)
            self.assertIn(project, reason)
            self.assertIn("Index now", reason)
            self.assertIn("Do not index", reason)

    def test_record_yes_keeps_blocking_until_index_exists(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)

            ask = {
                "hook_event_name": "PostToolUse",
                "tool_name": "AskUserQuestion",
                "tool_input": {
                    "questions": [{
                        "question": f"Index {project} with CodeGraph now?",
                        "options": [{"label": "Index now"}, {"label": "Do not index"}],
                    }]
                },
                "tool_response": {"answers": {f"Index {project} with CodeGraph now?": "Index now"}},
            }
            env["__STDIN__"] = json.dumps(ask)
            rc, _, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)

            decisions_file = Path(state_dir) / "codegraph-decisions.json"
            self.assertTrue(decisions_file.is_file())
            data = json.loads(decisions_file.read_text())
            self.assertEqual(data["decisions"][project], "index")

            pre = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(project, "foo.txt")},
                "cwd": project,
            }
            env["__STDIN__"] = json.dumps(pre)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")
            reason = data["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertIn("codegraph init", reason)
            self.assertIn(project, reason)

            (Path(project) / ".codegraph").mkdir()
            env["__STDIN__"] = json.dumps(pre)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

    def test_record_no_unblocks_immediately(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)

            ask = {
                "hook_event_name": "PostToolUse",
                "tool_name": "AskUserQuestion",
                "tool_input": {
                    "questions": [{
                        "question": f"Index {project} with CodeGraph now?",
                        "options": [{"label": "Index now"}, {"label": "Do not index"}],
                    }]
                },
                "tool_response": {"answers": {f"Index {project} with CodeGraph now?": "Do not index"}},
            }
            env["__STDIN__"] = json.dumps(ask)
            rc, _, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)

            pre = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(project, "foo.txt")},
                "cwd": project,
            }
            env["__STDIN__"] = json.dumps(pre)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

            decisions = json.loads(Path(state_dir, "codegraph-decisions.json").read_text())
            self.assertEqual(decisions["decisions"][project], "skip")

    def test_indexed_path_is_not_blocked(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            (Path(project) / ".codegraph").mkdir()
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(project, "foo.txt")},
                "cwd": project,
            }
            env["__STDIN__"] = json.dumps(payload)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

    def test_ignored_dirs_never_blocked(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            home = tmp / "home"
            home.mkdir(parents=True, exist_ok=True)
            claude_dir = home / ".claude" / "projects" / "billing-service"
            claude_dir.mkdir(parents=True, exist_ok=True)
            (claude_dir / "package.json").write_text("{}")
            _write_runtime(str(cfg_dir), state_dir,
                            home=str(home),
                            claude_dir=str(home / ".claude"),
                            opencode_data_dir=str(tmp / "xdg-data" / "opencode"))
            env = _make_env(tmp)
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": str(claude_dir / "index.js")},
                "cwd": str(claude_dir),
            }
            env["__STDIN__"] = json.dumps(payload)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

    def test_codegraph_bash_bypass(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "codegraph init " + project},
                "cwd": project,
            }
            env["__STDIN__"] = json.dumps(payload)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

    def test_codegraph_bash_chained_is_exempt(self):
        """Defect 8: a chained `codegraph` command must be exempt. Only
        every segment being a codegraph call (or `cd`) keeps the gate open."""
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)
            for cmd in (
                "codegraph status && codegraph explore \"q\"",
                "codegraph status || codegraph init /x",
                "codegraph status; codegraph explore foo",
                "cd /x && codegraph init .",
                "/usr/local/bin/codegraph init /x",
            ):
                payload = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": cmd},
                    "cwd": project,
                }
                env["__STDIN__"] = json.dumps(payload)
                rc, out, _ = _run_hook(GATE, env)
                self.assertEqual(rc, 0, msg=cmd)
                self.assertEqual(out.strip(), "", msg=cmd)

    def test_codegraph_bash_mixed_with_other_cmands_is_gated(self):
        """Defect 8: substring matching is not enough. A command that just
        MENTIONS codegraph but runs something else must be gated normally."""
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)
            for cmd in (
                "cat /x/secret # codegraph",
                "codegraph status; cat /x/f",
                "ls /x | grep codegraph",
                "rm /x; codegraph init /x",
                "cat /x || codegraph status",
                "echo codegraph",
            ):
                payload = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": cmd},
                    "cwd": project,
                }
                env["__STDIN__"] = json.dumps(payload)
                rc, out, _ = _run_hook(GATE, env)
                self.assertEqual(rc, 0, msg=cmd)
                self.assertTrue(out.strip(), msg=cmd)
                data = json.loads(out)
                self.assertEqual(
                    data["hookSpecificOutput"]["permissionDecision"],
                    "deny",
                    msg=cmd,
                )

    def test_gate_disabled_in_runtime(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(cfg_dir), state_dir, gate=False)
            env = _make_env(tmp)
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(project, "foo.txt")},
                "cwd": project,
            }
            env["__STDIN__"] = json.dumps(payload)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

    def test_legacy_decisions_file_honoured(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            legacy = tmp / "home" / ".claude" / "state" / "codegraph-decisions.json"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text(json.dumps({"decisions": {project: "skip"}}))
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(project, "foo.txt")},
                "cwd": project,
            }
            env["__STDIN__"] = json.dumps(payload)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")
            self.assertFalse((Path(state_dir) / "codegraph-decisions.json").exists())

    def test_spanish_messages_for_es_ui(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(cfg_dir), state_dir, ui="es")
            env = _make_env(tmp)
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(project, "foo.txt")},
                "cwd": project,
            }
            env["__STDIN__"] = json.dumps(payload)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            data = json.loads(out)
            reason = data["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertIn("Indexar ahora", reason)
            self.assertIn("No indexar", reason)
            self.assertIn("CodeGraph", reason)

    def test_recognises_label_from_other_locale(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(cfg_dir), state_dir, ui="en")
            env = _make_env(tmp)
            ask = {
                "hook_event_name": "PostToolUse",
                "tool_name": "AskUserQuestion",
                "tool_input": {
                    "questions": [{
                        "question": f"¿Indexar {project} con CodeGraph ahora?",
                        "options": [{"label": "Indexar ahora"}, {"label": "No indexar"}],
                    }]
                },
                "tool_response": {"answers": {f"¿Indexar {project} con CodeGraph ahora?": "Indexar ahora"}},
            }
            env["__STDIN__"] = json.dumps(ask)
            rc, _, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            decisions = json.loads(Path(state_dir, "codegraph-decisions.json").read_text())
            self.assertEqual(decisions["decisions"][project], "index")

    def test_fail_open_on_garbage_stdin(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)
            env["__STDIN__"] = "this is not json {{{"
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")
            log = Path(state_dir) / "hooks.log"
            self.assertTrue(log.is_file())
            self.assertIn("codegraph-gate", log.read_text())

    def test_root_from_codegraph_roots_is_accepted(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            # Create the project under a tmpdir OUTSIDE HOME so HOME-only check
            # would block it; then list it as a codegraph.roots entry.
            outside_base = tmp / "external"
            outside_base.mkdir()
            project = _make_project(outside_base, "app")
            (Path(project) / ".codegraph").mkdir()
            _write_runtime(str(cfg_dir), state_dir, roots=[str(outside_base)])
            env = _make_env(tmp)
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": os.path.join(project, "foo.txt")},
                "cwd": project,
            }
            env["__STDIN__"] = json.dumps(payload)
            rc, out, _ = _run_hook(GATE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

    @unittest.skipUnless(ORIGINAL_GATE.is_file(), "reference codegraph-gate.py not present")
    def test_es_gate_parity_with_original(self):
        """Golden check: with ui='es', the deny reason must equal the original
        script's output for the same input. The original uses HOME-relative
        paths, so we point HOME at our temp dir and prepare the same project.
        Skipped if the tempdir would sit beneath a system-ignored directory."""
        with _safe_tempdir() as td:
            tmp = Path(td)
            home = tmp / "home"
            home.mkdir(parents=True, exist_ok=True)
            project = home / "billing-service"
            project.mkdir(parents=True, exist_ok=True)
            (project / "package.json").write_text("{}")
            file_path = str(project / "index.js")
            abspath = os.path.abspath(file_path)
            sys_ignored = _SYSTEM_IGNORED.get(sys.platform, ())
            if any(abspath.startswith(d + os.sep) or abspath == d for d in sys_ignored):
                self.skipTest(f"tempdir under system-ignored path {sys_ignored}")

            cfg_dir = home / ".config" / "podium"
            state_dir = home / ".local" / "state" / "podium"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)
            (cfg_dir / "runtime.json").write_text(json.dumps({
                "schema": 1, "ui": "es",
                "paths": {"home": str(home),
                            "claude_dir": str(home / ".claude"),
                            "opencode_data_dir": str(home / ".local" / "share" / "opencode"),
                            "state_dir": str(state_dir)},
                "codegraph": {"gate": True, "nudge_every": 4,
                              "roots": [], "manifests": [], "ignored": []},
            }))
            payload = {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": file_path},
                "cwd": str(project),
            }
            payload_str = json.dumps(payload)

            env = {"HOME": str(home), "PATH": os.environ.get("PATH", "")}
            env["__STDIN__"] = payload_str
            rc1, out1, _ = _run_hook(GATE, env)
            self.assertEqual(rc1, 0)

            env2 = {"HOME": str(home), "PATH": os.environ.get("PATH", "")}
            res = subprocess.run(
                [sys.executable, str(ORIGINAL_GATE)],
                input=payload_str.encode("utf-8"),
                capture_output=True, env=env2, timeout=10,
            )
            self.assertEqual(res.returncode, 0)

            self.assertTrue(out1.strip(), "our hook produced no output for parity check")
            data = json.loads(out1)
            self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertTrue(res.stdout.decode("utf-8").strip(),
                            "original produced no output for parity check")
            orig_data = json.loads(res.stdout.decode("utf-8"))
            orig_reason = orig_data["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertEqual(data["hookSpecificOutput"]["permissionDecisionReason"], orig_reason)


class NudgeHookTests(unittest.TestCase):

    def _nudge(self, tmp, payload, *, runtime_kwargs=None, session_id="s1"):
        cfg_dir = tmp / "config"
        state_dir = str(tmp / "state")
        os.makedirs(cfg_dir, exist_ok=True)
        _write_runtime(str(cfg_dir), state_dir, **(runtime_kwargs or {}))
        env = _make_env(tmp)
        payload = dict(payload)
        payload["session_id"] = session_id
        env["__STDIN__"] = json.dumps(payload)
        rc, out, err = _run_hook(NUDGE, env)
        self.assertEqual(rc, 0)
        self.assertFalse(err.strip())
        return out.strip()

    def test_fires_on_first_and_fifth_call_only(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            home = tmp / "home"
            home.mkdir(parents=True, exist_ok=True)
            project = home / "billing-service"
            project.mkdir(parents=True, exist_ok=True)
            (project / "package.json").write_text("{}")
            (project / ".codegraph").mkdir()

            for n in range(1, 9):
                payload = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Grep",
                    "tool_input": {"path": str(project)},
                    "cwd": str(project),
                }
                out = self._nudge(tmp, payload)
                should_fire = (n in (1, 5))
                if should_fire:
                    data = json.loads(out)
                    self.assertIn("additionalContext", data["hookSpecificOutput"])
                else:
                    self.assertEqual(out, "")

    def test_does_not_fire_when_no_index(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            project = _make_project(tmp / "home", "app")
            out = self._nudge(tmp, {
                "hook_event_name": "PreToolUse",
                "tool_name": "Grep",
                "tool_input": {"path": project},
                "cwd": project,
            })
            self.assertEqual(out, "")

    def test_silent_for_non_search_bash(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            project = _make_project(tmp / "home", "app")
            (Path(project) / ".codegraph").mkdir()
            out = self._nudge(tmp, {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
                "cwd": project,
            })
            self.assertEqual(out, "")

    def test_fail_open_on_garbage_stdin(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            _write_runtime(str(cfg_dir), state_dir)
            env = _make_env(tmp)
            env["__STDIN__"] = "garbage"
            rc, out, _ = _run_hook(NUDGE, env)
            self.assertEqual(rc, 0)
            self.assertEqual(out, "")
            self.assertIn("codegraph-nudge", (Path(state_dir) / "hooks.log").read_text())

    def test_respects_nudge_every_runtime_value(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            home = tmp / "home"
            home.mkdir(parents=True, exist_ok=True)
            project = home / "billing-service"
            project.mkdir(parents=True, exist_ok=True)
            (project / "package.json").write_text("{}")
            (project / ".codegraph").mkdir()

            cfg_dir = tmp / "config"
            state_dir = str(tmp / "state")
            _write_runtime(str(cfg_dir), state_dir, nudge_every=2)
            env = _make_env(tmp)
            fired = []
            for n in range(1, 6):
                env["__STDIN__"] = json.dumps({
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Grep",
                    "tool_input": {"path": str(project)},
                    "cwd": str(project),
                    "session_id": "s2",
                })
                rc, out, _ = _run_hook(NUDGE, env)
                self.assertEqual(rc, 0)
                if out.strip():
                    fired.append(n)
            self.assertEqual(fired, [1, 3, 5])

    def test_nudge_text_is_spanish_for_es_ui(self):
        """Defect 6: es.json nudge.available used to be the English string
        (identical to en.json). After the fix it must be Spanish, in voseo
        like the rest of the es strings, with the {roots} placeholder
        formatted at runtime."""
        with _safe_tempdir() as td:
            tmp = Path(td)
            home = tmp / "home"
            home.mkdir(parents=True, exist_ok=True)
            project = home / "billing-service"
            project.mkdir(parents=True, exist_ok=True)
            (project / "package.json").write_text("{}")
            (project / ".codegraph").mkdir()

            out = self._nudge(tmp, {
                "hook_event_name": "PreToolUse",
                "tool_name": "Grep",
                "tool_input": {"path": str(project)},
                "cwd": str(project),
            }, runtime_kwargs={"ui": "es"})
            data = json.loads(out)
            msg = data["hookSpecificOutput"]["additionalContext"]
            # Spanish (not English) and voseo verb forms.
            self.assertIn("Índice de CodeGraph", msg)
            self.assertIn("preferí", msg)
            self.assertIn("Usá grep", msg)
            # The English string must not be there.
            self.assertNotIn("CodeGraph index available", msg)
            self.assertNotIn("prefer `codegraph_explore`", msg)
            # The {roots} placeholder is substituted at runtime with the
            # project path that hosts the index.
            self.assertIn(str(project), msg)
            # The literal placeholder must NOT leak through; only the
            # formatted value should be present.
            self.assertNotIn("{roots}", msg)


class ConfiguredRootsAndFallbackTests(unittest.TestCase):
    """Configured roots, runtime path overrides and locale fallbacks."""

    def _hook(self, hook, env, payload):
        run_env = dict(env)
        run_env["__STDIN__"] = json.dumps(payload)
        return _run_hook(hook, run_env)

    def _read_payload(self, path):
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": path},
            "cwd": os.path.dirname(path),
        }

    def _grep_payload(self, path, session_id="s1"):
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Grep",
            "tool_input": {"path": path},
            "cwd": path,
            "session_id": session_id,
        }

    def _copy_plugin(self, tmp, locales):
        """Copy the hook scripts into a plugin tree whose locales/ holds `locales`."""
        plugin = tmp / "plugin"
        hooks = plugin / "hooks"
        hooks.mkdir(parents=True)
        for name in ("_runtime.py", "codegraph-gate.py", "codegraph-nudge.py"):
            shutil.copy(PLUGIN_HOOKS / name, hooks / name)
        (plugin / "locales").mkdir()
        for name, content in locales.items():
            (plugin / "locales" / name).write_text(content, encoding="utf-8")
        return hooks / "codegraph-gate.py", hooks / "codegraph-nudge.py"

    def test_configured_root_project_is_discovered_and_gated(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            external = tmp / "external"
            external.mkdir()
            project = _make_project(external, "app")
            _write_runtime(str(tmp / "config"), str(tmp / "state"), roots=[str(external)])
            rc, out, _ = self._hook(GATE, _make_env(tmp),
                                    self._read_payload(os.path.join(project, "foo.txt")))
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn(project, data["hookSpecificOutput"]["permissionDecisionReason"])

    def test_index_at_configured_root_is_found_from_descendant(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            external = tmp / "external"
            (external / ".codegraph").mkdir(parents=True)
            project = _make_project(external, "app")
            (Path(project) / "src").mkdir()
            _write_runtime(str(tmp / "config"), str(tmp / "state"), roots=[str(external)])
            rc, out, _ = self._hook(GATE, _make_env(tmp),
                                    self._read_payload(os.path.join(project, "src", "x.py")))
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

    def test_nudge_finds_index_at_configured_root(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            external = tmp / "external"
            (external / ".codegraph").mkdir(parents=True)
            project = _make_project(external, "app")
            _write_runtime(str(tmp / "config"), str(tmp / "state"), roots=[str(external)])
            rc, out, _ = self._hook(NUDGE, _make_env(tmp), self._grep_payload(project))
            self.assertEqual(rc, 0)
            msg = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(str(external), msg)

    def test_runtime_path_overrides_drive_gate_and_nudge_state(self):
        with _safe_tempdir() as td:
            tmp = Path(td)
            state_cfg = tmp / "state-cfg"
            project = _make_project(tmp / "home", "app")
            _write_runtime(str(tmp / "config"), str(state_cfg))
            env = _make_env(tmp)  # PODIUM_STATE_DIR points elsewhere on purpose
            question = f"Index {project} with CodeGraph now?"
            ask = {
                "hook_event_name": "PostToolUse",
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": question}]},
                "tool_response": {"answers": {question: "Do not index"}},
            }
            rc, _, _ = self._hook(GATE, env, ask)
            self.assertEqual(rc, 0)
            decisions = state_cfg / "codegraph-decisions.json"
            self.assertTrue(decisions.is_file())
            self.assertEqual(json.loads(decisions.read_text())["decisions"][project], "skip")
            self.assertFalse((tmp / "state" / "codegraph-decisions.json").exists())

            rc, _, _ = self._hook(NUDGE, env, self._grep_payload(project))
            self.assertEqual(rc, 0)
            self.assertTrue((state_cfg / "sessions" / "codegraph-nudge-s1.json").is_file())

    def test_unstructured_answer_in_other_locale_is_recorded(self):
        for label, expected in (("Indexar ahora", "index"), ("No indexar", "skip")):
            with self.subTest(label=label), _safe_tempdir() as td:
                tmp = Path(td)
                project = _make_project(tmp / "home", "app")
                state_cfg = tmp / "state-cfg"
                _write_runtime(str(tmp / "config"), str(state_cfg))
                ask = {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "AskUserQuestion",
                    "tool_input": {"questions": [
                        {"question": f"CodeGraph: should {project} be indexed"}]},
                    "tool_response": label,  # unstructured answer, Spanish label
                }
                rc, _, _ = self._hook(GATE, _make_env(tmp), ask)
                self.assertEqual(rc, 0)
                data = json.loads((state_cfg / "codegraph-decisions.json").read_text())
                self.assertEqual(data["decisions"][project], expected)

    def test_broken_locale_keeps_gate_and_nudge_working(self):
        english = (PLUGIN_HOOKS.parent / "locales" / "en.json").read_text(encoding="utf-8")
        cases = (
            ("es", {"es.json": "{not json", "en.json": "{not json"}),
            ("en", {}),
            ("es", {"es.json": '{"labels": {"yes": "Indexar ahora", "no": "No indexar"}}',
                    "en.json": english}),
        )
        for i, (ui, locales) in enumerate(cases):
            with self.subTest(case=i), _safe_tempdir() as td:
                tmp = Path(td)
                home = tmp / "home"
                gate_project = _make_project(home, "app")
                nudge_project = _make_project(home, "idx")
                (Path(nudge_project) / ".codegraph").mkdir()
                gate_hook, nudge_hook = self._copy_plugin(tmp, locales)
                _write_runtime(str(tmp / "config"), str(tmp / "state"), ui=ui)
                env = _make_env(tmp)

                rc, out, _ = self._hook(gate_hook, env,
                                        self._read_payload(os.path.join(gate_project, "foo.txt")))
                self.assertEqual(rc, 0)
                reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("AskUserQuestion", reason)
                self.assertIn("Index now", reason)
                self.assertIn(gate_project, reason)

                rc, out, _ = self._hook(nudge_hook, env, self._grep_payload(nudge_project))
                self.assertEqual(rc, 0)
                msg = json.loads(out)["hookSpecificOutput"]["additionalContext"]
                self.assertIn("CodeGraph index available", msg)


if __name__ == "__main__":
    unittest.main()