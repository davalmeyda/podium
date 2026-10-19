import json
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "core"))

import coretest  # noqa: E402


class CliTest(coretest.CoreCase):
    def setUp(self):
        super().setUp()
        self.write_config()

    def test_help_and_version(self):
        code, out, err = self.run_cli("--help")
        self.assertEqual(code, 0)
        for command in ("detect", "init", "install", "render", "diff", "migrate", "doctor", "uninstall", "update"):
            self.assertIn(command, out)
        code, out, err = self.run_cli("--version")
        self.assertEqual((code, out.startswith("podium ")), (0, True))

    def test_bin_podium_help_runs(self):
        proc = subprocess.run([sys.executable, str(coretest.REPO / "bin" / "podium"), "--help"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("install", proc.stdout)

    def test_usage_errors_exit_1(self):
        self.assertEqual(self.run_cli("bogus")[0], 1)
        self.assertEqual(self.run_cli("install", "--nope")[0], 1)
        self.assertEqual(self.run_cli()[0], 1)

    def test_config_errors_exit_1_with_dotted_key(self):
        self.write_config('schema = 1\n[memory]\nbogus = 1\n')
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 1)
        self.assertIn("memory.bogus", err)

    def test_unknown_config_key_error_and_unset_variable_error(self):
        self.write_config('schema = 1\nmystery = true\n')
        code, out, err = self.run_cli("render")
        self.assertEqual(code, 1)
        self.assertIn("mystery", err)
        self.write_config('schema = 1\n[memory]\nurl = "${NO_SUCH_VARIABLE_ZZ}"\n')
        code, out, err = self.run_cli("render")
        self.assertEqual(code, 1)
        self.assertIn("NO_SUCH_VARIABLE_ZZ", err)

    def test_missing_config_exit_1(self):
        (self.config_dir / "podium.toml").unlink()
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 1)
        self.assertIn("podium init", err)

    def test_render_to_stdout_and_target(self):
        code, out, err = self.run_cli("render", "--target", "claude-md")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("# Alpha"))
        self.assertTrue(out.endswith("\n") and not out.endswith("\n\n"))
        code, out, err = self.run_cli("render")
        self.assertIn("<!-- podium render: executor-profile -->", out)
        self.assertEqual(self.run_cli("render", "--target", "nope")[0], 1)

    def test_render_out_dir(self):
        out_dir = self.tmp / "rendered"
        code, out, err = self.run_cli("render", "--out", str(out_dir))
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()),
                         ["claude-md.md", "executor-profile.md", "opencode-agents-md.md"])
        self.assertFalse(self.claude_dir.exists())

    def test_diff_shows_changes_and_then_none(self):
        code, out, err = self.run_cli("diff", "--target", "claude-md")
        self.assertEqual(code, 0, err)
        self.assertIn("+# Alpha", out)
        self.assertEqual(self.run_cli("install")[0], 0)
        code, out, err = self.run_cli("diff")
        self.assertEqual(code, 0, err)
        self.assertIn("no differences", out)
        self.write_config(coretest.BASE_CONFIG.replace('response = "es"', 'response = "en"'))
        code, out, err = self.run_cli("diff", "--target", "claude-md")
        self.assertIn("-Answer in Spanish", out)
        self.assertIn("+Answer in English", out)
        self.assertEqual(self.run_cli("diff", "--target", "nope")[0], 1)

    def test_detect_init_doctor_delegate_to_their_modules(self):
        calls = {}
        detect = types.ModuleType("podium.detect")
        detect.run = lambda paths: calls.setdefault("detect", paths) and {"os": "linux", "tools": {"claude": None}}
        init = types.ModuleType("podium.init")

        def fake_init(paths, answers=None, *, interactive=False):
            calls["init"] = (answers, interactive)
            calls["init_home"] = paths["home"]
            return paths["config_dir"] / "podium.toml"

        init.run = fake_init
        doctor = types.ModuleType("podium.doctor")
        doctor.run = lambda paths, config: calls.setdefault("doctor", config["language"]["response"]) and 4
        with mock.patch.dict(sys.modules, {"podium.detect": detect, "podium.init": init, "podium.doctor": doctor}):
            code, out, err = self.run_cli("detect", "--json")
            self.assertEqual((code, json.loads(out)["os"]), (0, "linux"))
            code, out, err = self.run_cli("detect")
            self.assertIn("os: linux", out)
            answers = self.tmp / "answers.json"
            answers.write_text(json.dumps({"language.response": "es"}))
            code, out, err = self.run_cli("init", "--answers", str(answers))
            self.assertEqual(code, 0, err)
            self.assertEqual(calls["init"], ({"language.response": "es"}, False))
            self.assertIn("wrote", out)
            self.assertEqual(self.run_cli("init", "--non-interactive")[0], 0)
            self.assertEqual(calls["init"], (None, False))
            self.assertEqual(self.run_cli("init", "--answers", str(self.tmp / "missing.json"))[0], 1)
            self.assertEqual(self.run_cli("doctor")[0], 4)
            self.assertEqual(calls["doctor"], "es")
        self.assertEqual(calls["detect"]["home"], self.home)
        self.assertEqual(calls["init_home"], coretest.FIXTURE_HOME)

    def test_detect_and_init_run_for_real(self):
        """No stubs: the CLI must call the real detect/init with the signatures they define."""
        repo = Path(__file__).resolve().parents[1]
        import contextlib, io
        from podium import cli
        sys.modules.pop("podium.roster", None)  # the fixture's fake roster would shadow the real one
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["detect", "--json"], env=self.env, podium_home=repo), 0)
        self.assertIn("tools", json.loads(out.getvalue()))
        answers = self.tmp / "answers.json"
        answers.write_text(json.dumps({"roster_preset": "claude-only", "memory": {"url": ""}}))
        self.write_config()
        code, _, err = self.run_cli("init", "--answers", str(answers))
        self.assertEqual(code, 1)  # an existing podium.toml is never overwritten silently
        self.assertIn("refusing to overwrite", err)
        answers.write_text(json.dumps({"roster_preset": "claude-only", "memory": {"url": ""}, "overwrite": True}))
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["init", "--answers", str(answers)], env=self.env, podium_home=repo)
        self.assertEqual(code, 0)
        self.assertIn("[[roster]]", (self.config_dir / "podium.toml").read_text())
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["doctor"], env=self.env, podium_home=repo)
        self.assertIn(code, (0, 3))  # health verdict, never a crash

    def test_missing_optional_module_is_an_environment_error(self):
        with mock.patch.dict(sys.modules, {"podium.detect": None}):
            code, out, err = self.run_cli("detect")
        self.assertEqual(code, 3)

    def test_exit_codes_conflict_and_environment(self):
        agent = self.oc_dir / "agents" / "writer.md"
        agent.parent.mkdir(parents=True)
        agent.write_text("foreign\n")
        self.assertEqual(self.run_cli("install")[0], 2)
        self.assertEqual(self.run_cli("install", "--adopt")[0], 0)
        (self.state_dir / "lock").write_text("1\n")
        self.assertEqual(self.run_cli("install")[0], 3)

    def test_install_end_to_end_then_uninstall(self):
        self.add_fake_claude()
        code, out, err = self.run_cli("install")
        self.assertEqual(code, 0, out + err)
        self.assertTrue((self.claude_dir / "CLAUDE.md").is_file())
        self.assertEqual(self.run_cli("uninstall")[0], 0)
        self.assertEqual((self.claude_dir / "CLAUDE.md").read_text(), "")

    def test_update_requires_a_git_checkout(self):
        code, out, err = self.run_cli("update")
        self.assertEqual(code, 3)
        self.assertIn("not a git checkout", err)

    def _update(self, git_script, extra_env=None):
        import contextlib, io, shutil
        from podium import cli
        checkout = self.tmp / "checkout"
        shutil.copytree(str(coretest.FIXTURE_HOME), str(checkout))
        (checkout / ".git").mkdir()
        git = self.bin / "git"
        git.write_text(git_script)
        git.chmod(0o755)
        env = dict(self.env, **(extra_env or {}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["update"], env=env, podium_home=checkout)
        return code, checkout, out.getvalue()

    def test_update_checks_out_latest_release_then_installs(self):
        script = (
            '#!/bin/sh\necho "git $@" >> "$FAKE_CLAUDE_LOG"\n'
            'if [ "$3" = ls-remote ]; then\n'
            '  printf "a\\trefs/tags/v0.9.0\\nb\\trefs/tags/v0.10.1\\nc\\trefs/tags/v0.10.0-rc1\\n"\n'
            'fi\n'
        )
        code, checkout, out = self._update(script)
        self.assertEqual(code, 0)
        self.assertEqual(self.claude_calls(), [
            "git -C %s ls-remote --tags --refs origin v*" % checkout,
            "git -C %s fetch --depth 1 --tags origin v0.10.1" % checkout,
            "git -C %s checkout --quiet --detach FETCH_HEAD" % checkout,
        ])
        self.assertIn("podium checkout at v0.10.1", out)
        self.assertTrue((self.claude_dir / "CLAUDE.md").is_file())

    def test_update_honours_podium_ref_and_falls_back_to_main(self):
        script = '#!/bin/sh\necho "git $@" >> "$FAKE_CLAUDE_LOG"\n'
        code, checkout, _ = self._update(script, {"PODIUM_REF": "v0.1.0"})
        self.assertEqual(code, 0)
        self.assertNotIn("ls-remote", " ".join(self.claude_calls()))
        self.assertIn("git -C %s fetch --depth 1 --tags origin v0.1.0" % checkout, self.claude_calls())

    def test_update_without_releases_uses_main(self):
        script = '#!/bin/sh\necho "git $@" >> "$FAKE_CLAUDE_LOG"\n'
        code, checkout, _ = self._update(script)
        self.assertEqual(code, 0)
        self.assertIn("git -C %s fetch --depth 1 --tags origin main" % checkout, self.claude_calls())

    def test_update_stops_when_fetch_fails(self):
        script = '#!/bin/sh\necho "git $@" >> "$FAKE_CLAUDE_LOG"\n[ "$3" = fetch ] && exit 1\nexit 0\n'
        code, _, _ = self._update(script)
        self.assertEqual(code, 3)
        self.assertFalse((self.claude_dir / "CLAUDE.md").exists())

if __name__ == "__main__":
    unittest.main()
