import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/podium-upgrade/skills/agents-upgrade/scripts"


class UpgradeScriptsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.config = self.home / "config"
        self.config.mkdir()
        (self.config / "podium.toml").write_text(
            '[[roster]]\nid="writer"\nlaunch={kind="opencode", agent="writer", model="sample/model", variant="fast"}\n'
            '[[agents]]\nname="writer"\nmodel="sample/model"\nvariant="fast"\n'
            '[roster_notes]\nexcluded=[]\n', encoding="utf-8"
        )
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.home),
            "PODIUM_HOME": str(Path(__file__).resolve().parent.parent),
            "PODIUM_CONFIG_DIR": str(self.config),
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
        })

    def tearDown(self):
        self.temp.cleanup()

    def executable(self, name, text):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + text + "\n", encoding="utf-8")
        path.chmod(0o755)

    def run_script(self, script, *args):
        return subprocess.run(["sh", str(PLUGIN / script), *args], env=self.env,
                              text=True, capture_output=True, check=True).stdout

    def test_roster_json(self):
        result = subprocess.run(["python3", str(PLUGIN / "roster.py")], env=self.env,
                                text=True, capture_output=True, check=True)
        roster = json.loads(result.stdout)
        self.assertEqual(roster["agents"][0]["name"], "writer")
        self.assertEqual(roster["roster"][0]["launch"]["model"], "sample/model")

    def test_preflight_detects_npm_and_native(self):
        """preflight.sh's `== Install method` section prints one
        `opencode: <method>` and one `claude: <method>` line, where `<method>`
        is decided by package ownership: `npm` when npm claims the package,
        `brew` when brew lists the formula/cask, otherwise `native`."""
        self.executable("npm", (
            # npm claims `@anthropic-ai/claude-code` (so claude → npm) but
            # claims neither `opencode-ai` nor anything else.
            'case " $* " in\n'
            '  *claude-code*) exit 0 ;;\n'
            '  *) exit 1 ;;\n'
            'esac'
        ))
        self.executable("brew", "exit 1")
        (self.home / "claude").write_text("#!/bin/sh\necho 1\n")
        (self.home / "claude").chmod(0o755)
        (self.home / "opencode").write_text("#!/bin/sh\necho 1\n")
        (self.home / "opencode").chmod(0o755)
        self.env["PATH"] = f"{self.home}:{self.bin}:" + os.environ.get("PATH", "")
        output = self.run_script("preflight.sh")
        self.assertIn("claude: npm\n", output)
        self.assertIn("opencode: native\n", output)

    def test_update_dry_run_by_install_method(self):
        """When brew owns both tools, update-clis must emit the brew
        commands. Brew's opencode is a formula; brew's claude is a cask."""
        prefix = self.home / "brew"
        prefix.mkdir()
        self.executable("brew", (
            f'[ "$1" = --prefix ] && echo "{prefix}"\n'
            # `brew list --formula opencode` succeeds (formula), so the
            # script classifies opencode as brew.
            f'[ "$1" = list ] && [ "$2" = --formula ] && [ "$3" = opencode ] && exit 0\n'
            # Default answer to `brew list --cask`: print `claude-code`
            # (older cask name). Use a one-shot stub for negative queries.
            f'[ "$1" = list ] && [ "$2" = --cask ] && echo claude-code\n'
            'exit 1'
        ))
        # npm claims nothing.
        self.executable("npm", "exit 1")
        for tool in ("opencode", "claude"):
            path = prefix / tool
            path.write_text("#!/bin/sh\necho 1\n")
            path.chmod(0o755)
        self.executable("opencode", 'echo 1')
        self.executable("claude", 'echo 1')
        self.env["PATH"] = f"{prefix}:{self.bin}:" + os.environ.get("PATH", "")
        output = self.run_script("update-clis.sh", "--dry-run")
        self.assertIn("brew upgrade opencode", output)
        self.assertIn("brew upgrade --cask --greedy claude-code", output)

    def test_update_dry_run_native(self):
        """When neither npm nor brew owns the tools, the updater falls back
        to the native installer commands."""
        self.executable("brew", "exit 1")
        self.executable("npm", "exit 1")
        self.executable("opencode", "echo 1")
        self.executable("claude", "echo 1")
        output = self.run_script("update-clis.sh", "--dry-run")
        self.assertIn("opencode upgrade --major || opencode upgrade", output)
        self.assertIn("claude update", output)

    def test_update_dry_run_npm(self):
        """When npm owns both packages, the updater must use the npm
        `install -g <pkg>@latest` form (not the brew or native commands),
        regardless of where the executable lives on disk."""
        prefix = self.home / "npm-global"
        (prefix / "bin").mkdir(parents=True)
        self.executable("brew", "exit 1")
        self.executable("npm", (
            # npm claims both packages.
            'case " $* " in\n'
            '  *opencode-ai*) exit 0 ;;\n'
            '  *claude-code*) exit 0 ;;\n'
            '  *) exit 1 ;;\n'
            'esac'
        ))
        for tool in ("opencode", "claude"):
            path = prefix / "bin" / tool
            path.write_text("#!/bin/sh\necho 1\n")
            path.chmod(0o755)
        self.env["PATH"] = f"{prefix / 'bin'}:{self.bin}:" + os.environ.get("PATH", "")
        output = self.run_script("update-clis.sh", "--dry-run")
        self.assertIn("npm install -g opencode-ai@latest", output)
        self.assertIn("npm install -g @anthropic-ai/claude-code@latest", output)

    def test_catalogs_uses_variant_from_matching_roster_row(self):
        """Defect 4: catalogs.sh used to call `a.get('variant','none')` on
        the [[agents]] row, but agents in podium.toml have NO `variant` key
        (the schema forbids it). The variant lives on the [[roster]] row's
        launch, and must be looked up by `launch.agent == agent.name`. An
        agent with no matching roster row gets no `#variant` suffix (never
        `#none`, which is not an OpenCode value)."""
        # Replace the default podium.toml with one that exercises the fix.
        (self.config / "podium.toml").write_text(
            '[[roster]]\n'
            'id="writer"\n'
            'launch={kind="opencode", agent="writer", model="minimax/MiniMax-M3", variant="none"}\n'
            '[[roster]]\n'
            'id="sol"\n'
            'launch={kind="opencode", agent="sol", model="openai/gpt-6.1-sol", variant="high"}\n'
            '[[roster]]\n'
            'id="orphan"\n'
            'launch={kind="opencode", agent="orphan-agent", model="openai/extra"}\n'
            '[[agents]]\n'
            'name="writer"\nmodel="minimax/MiniMax-M3"\n'
            '[[agents]]\n'
            'name="sol"\nmodel="openai/gpt-6.1-sol"\n'
            '[[agents]]\n'
            'name="lone"\nmodel="openai/gpt-6.1-lone"\n'
            '[roster_notes]\nexcluded=[]\n',
            encoding="utf-8",
        )
        # Stub `opencode` whose argv captures the call shape used by
        # `catalogs.sh`: `opencode run --auto --agent <name> -m <spec>
        # "<prompt>" </dev/null > out 2> err`. We log every argv and the
        # whole command, then exit 0 so the script can keep going.
        log = self.bin / "opencode.log"
        self.executable("opencode", (
            'echo CMD "$0" "$@" >> "$PODIUM_OPENCODE_LOG"\n'
            'for a in "$@"; do printf \'%s\\n\' "$a" >> "$PODIUM_OPENCODE_LOG"; done'
        ))
        self.env["PODIUM_OPENCODE_LOG"] = str(log)

        result = subprocess.run(
            ["sh", str(PLUGIN / "catalogs.sh")],
            env=self.env, text=True, capture_output=True,
        )
        # catalog.sh calls `opencode run ...`; if a `-m` spec is wrong the
        # stub still exits 0, so we read the log.
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        recorded = log.read_text().splitlines()
        # Build (agent, model_spec) pairs from the log. The argv layout in
        # the new contract is
        #   run --auto --agent <name> -m <spec> <prompt>
        pairs = []
        i = 0
        while i < len(recorded):
            # We are looking at a "run" subcommand line; the next lines
            # carry `--auto`, `--agent`, `<name>`, `-m`, `<spec>`, ... in
            # order.
            if recorded[i] == "run" and i + 5 < len(recorded) \
                    and recorded[i + 1] == "--auto" \
                    and recorded[i + 2] == "--agent" \
                    and recorded[i + 4] == "-m":
                pairs.append((recorded[i + 3], recorded[i + 5]))
                i += 6
            else:
                i += 1
        # sol comes from a roster row with variant="high" → "#high"
        self.assertIn(("sol", "openai/gpt-6.1-sol#high"), pairs)
        # writer comes from a roster row with variant="none" → "#none"
        self.assertIn(("writer", "minimax/MiniMax-M3#none"), pairs)
        # lone has no matching roster row → no variant suffix.
        self.assertIn(("lone", "openai/gpt-6.1-lone"), pairs)
        # None of the calls should use the bogus "#none" suffix on lone.
        for agent, spec in pairs:
            if agent == "lone":
                self.assertNotIn("#", spec)
        # Spot-check the prompt file is what the contract says.
        # `run dir: ...` is always the first line of stdout from the script.
        first = result.stdout.splitlines()[0]
        self.assertTrue(first.startswith("run dir: "), msg=first)
        run_dir = first[len("run dir: "):].strip()
        ping_file = Path(run_dir) / "ping.txt"
        self.assertTrue(ping_file.exists())
        self.assertEqual(
            ping_file.read_text().strip(),
            "Reply with the single word OK. Do NOT use any tools.",
        )

    def test_catalogs_continues_on_failing_agent(self):
        """A failing ping for one agent must not stop later agent checks.
        The script (no `set -e`) prints `FAIL <agent> (exit N, see ...)`
        and moves on to the next agent."""
        (self.config / "podium.toml").write_text(
            '[[roster]]\n'
            'id="writer"\n'
            'launch={kind="opencode", agent="writer", model="sample/writer", variant="fast"}\n'
            '[[roster]]\n'
            'id="critic"\n'
            'launch={kind="opencode", agent="critic", model="sample/critic", variant="high"}\n'
            '[[agents]]\nname="writer"\nmodel="sample/writer"\n'
            '[[agents]]\nname="critic"\nmodel="sample/critic"\n'
            '[roster_notes]\nexcluded=[]\n',
            encoding="utf-8",
        )
        # `opencode` stub: succeed for `writer`, fail for `critic`. Exit code
        # is recorded per call so the FAIL line gets a real exit number.
        self.executable("opencode", (
            'for a in "$@"; do printf \'%s\\n\' "$a" >> "$PODIUM_OPENCODE_LOG"; done\n'
            # If the agent name is `critic`, fail with exit 7 to make the
            # FAIL line non-trivial. Anything else (services, model listing)
            # exits 0.
            'for a in "$@"; do [ "$a" = critic ] && exit 7; done\n'
            'exit 0'
        ))
        log = self.bin / "opencode.log"
        self.env["PODIUM_OPENCODE_LOG"] = str(log)

        result = subprocess.run(
            ["sh", str(PLUGIN / "catalogs.sh")],
            env=self.env, text=True, capture_output=True,
        )
        # The script itself must NOT abort on the failed ping; both the
        # `writer` and `critic` sections must have appeared, and the FAIL
        # line must reference the per-agent .err trace.
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = result.stdout
        self.assertIn("== Agent check: writer (sample/writer#fast)", out)
        self.assertIn("== Agent check: critic (sample/critic#high)", out)
        # critic's run failed with exit 7; the FAIL line must surface it
        # and the per-agent .err file path. The line goes to stderr so the
        # scenario's `^FAIL` outline parser cannot mistake it for a test
        # failure (the principal still sees it on the skill's invocation).
        self.assertIn("FAIL critic (exit 7", result.stderr)
        run_dir = out.splitlines()[0][len("run dir: "):].strip()
        err_path = Path(run_dir) / "ping-critic.err"
        self.assertIn(str(err_path), result.stderr)
        # writer's run succeeded and still gets an `answer:` line.
        self.assertIn("answer: ", out)

    def test_update_method_is_npm_when_npm_owns_claude_under_brew_prefix(self):
        """The detect heuristic must follow package ownership, not executable
        location. A global npm install of `@anthropic-ai/claude-code` whose
        binary happens to live inside the brew prefix must still be classified
        npm, so update-clis emits `npm install -g` (not `brew upgrade`)."""
        brew_prefix = self.home / "brew"
        brew_prefix.mkdir()
        npm_prefix = self.home / "npm-global"
        (npm_prefix / "bin").mkdir(parents=True)

        # `command -v claude` and `command -v opencode` must resolve to the
        # brew prefix subdir — the awkward real-world case the user had.
        (brew_prefix / "bin").mkdir()
        for tool in ("opencode", "claude"):
            target = brew_prefix / "bin" / tool
            target.write_text("#!/bin/sh\nexit 0\n")
            target.chmod(0o755)
        # npm says it owns both packages; brew owns nothing.
        self.executable("npm", (
            f'[ "$1" = prefix ] && echo "{npm_prefix}"\n'
            # Anything that looks like an `npm ls ...` query: succeed.
            'case " $* " in\n'
            '  *opencode-ai*) exit 0 ;;\n'
            '  *claude-code*) exit 0 ;;\n'
            '  *) exit 1 ;;\n'
            'esac'
        ))
        self.executable("brew", (
            f'[ "$1" = --prefix ] && echo "{brew_prefix}" || exit 1\n'
            # brew has neither formula nor cask installed.
            'exit 1'
        ))
        # Keep the brewed binaries first on PATH so `command -v` finds them.
        self.env["PATH"] = f"{brew_prefix / 'bin'}:{self.bin}:" + os.environ.get("PATH", "")

        output = self.run_script("update-clis.sh", "--dry-run")
        self.assertIn("[dry-run] npm install -g opencode-ai@latest", output)
        self.assertIn(
            "[dry-run] npm install -g @anthropic-ai/claude-code@latest", output,
        )
        self.assertNotIn("brew upgrade --cask", output)

    def test_update_brew_cask_claude_code_latest(self):
        """When brew installed `claude-code@latest`, the updater must use the
        exact installed cask name (not the bare `claude-code`), and pass
        `--greedy` so Homebrew pulls the latest app version."""
        brew_prefix = self.home / "brew"
        (brew_prefix / "bin").mkdir(parents=True)
        for tool in ("opencode", "claude"):
            target = brew_prefix / "bin" / tool
            target.write_text("#!/bin/sh\nexit 0\n")
            target.chmod(0o755)
        # Brew has `claude-code@latest` as a cask. We split the
        # `brew list --cask` / `--formula` calls into a dedicated stub so
        # the negative path of `--formula` doesn't accidentally succeed.
        cask_stub = self.bin / "brew-cask-stub.sh"
        cask_stub.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = list ] && [ "$2" = --cask ]; then\n'
            '  echo "claude-code@latest"\n'
            '  exit 0\n'
            'fi\n'
            'exit 1\n',
            encoding="utf-8",
        )
        cask_stub.chmod(0o755)
        formula_stub = self.bin / "brew-formula-stub.sh"
        formula_stub.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = list ] && [ "$2" = --formula ]; then\n'
            '  exit 1\n'
            'fi\n'
            'exit 1\n',
            encoding="utf-8",
        )
        formula_stub.chmod(0o755)
        self.executable("brew", (
            f'[ "$1" = --prefix ] && echo "{brew_prefix}"\n'
            f'[ "$1" = list ] && [ "$2" = --cask ] && exec "{cask_stub}" list --cask\n'
            f'[ "$1" = list ] && [ "$2" = --formula ] && exec "{formula_stub}" list --formula\n'
            'exit 1'
        ))
        # npm owns neither tool, so detection falls through to brew.
        self.executable("npm", "exit 1")
        self.env["PATH"] = f"{brew_prefix / 'bin'}:{self.bin}:" + os.environ.get("PATH", "")

        output = self.run_script("update-clis.sh", "--dry-run")
        self.assertIn(
            "[dry-run] brew upgrade --cask --greedy claude-code@latest", output,
        )

    def test_preflight_excludes_opencode_service(self):
        """A fake `ps` listing with the OpenCode service line and an active
        opencode run must keep the service line out of the active-sessions
        block. The header row of ps is preserved so the principal can see
        what was filtered out."""
        (self.config / "podium.toml").write_text(
            '[[roster]]\nlaunch={kind="opencode", agent="writer", model="sample/writer"}\n'
            '[[agents]]\nname="writer"\nmodel="sample/writer"\n'
            '[roster_notes]\nexcluded=[]\n',
            encoding="utf-8",
        )
        # Stub a `ps` that emits a header, the OpenCode service line, a real
        # opencode run, and an unrelated process for noise.
        self.executable("ps", (
            "echo 'UID PID PPID C STIME TTY TIME CMD'\n"
            "echo 'tester 100 1 0 10:00 ? 00:00:00 opencode serve --service /var/run/oc.sock'\n"
            "echo 'tester 101 1 0 10:01 ? 00:00:00 opencode run --auto --agent writer -m sample/writer OK'\n"
            "echo 'tester 102 1 0 10:02 ? 00:00:00 /usr/bin/sleep 60'\n"
        ))
        # `opencode` and `claude` stubs for the versions/install-method
        # sections: any non-empty string is fine.
        self.executable("opencode", "echo 1.2.3-test")
        self.executable("claude", "echo 1.2.3-test")
        self.executable("brew", "exit 1")
        self.executable("npm", "exit 1")

        output = self.run_script("preflight.sh")
        # The sessions section must mention the running session but skip the
        # service line.
        sess_idx = output.index("== Active sessions (excluding the OpenCode service)")
        end_idx = output.index("(end sessions)")
        sess_block = output[sess_idx:end_idx]
        self.assertIn("opencode run --auto", sess_block)
        self.assertNotIn("serve --service", sess_block)
        self.assertNotIn("sleep 60", sess_block)
        # The contract's roster header is `== Configured roster` (no longer
        # the legacy `== Configured roster and agents` wording).
        self.assertIn("== Configured roster\n", output)
        # And the install method line must say `native` when neither npm
        # nor brew claims ownership.
        self.assertIn("opencode: native\n", output)
        self.assertIn("claude: native\n", output)

    def test_preflight_falls_back_to_legacy_history(self):
        """If the podium state-dir history is empty but a legacy file lives
        under `~/.claude/skills/agents-upgrade/historial/`, preflight must
        print its path (newest *.md) instead of `(no history)`."""
        state_history = (
            Path(self.env["HOME"]) / ".local/state/podium/upgrade-history"
        )
        legacy_history = (
            Path(self.env["HOME"]) / ".claude/skills/agents-upgrade/historial"
        )
        state_history.mkdir(parents=True)
        legacy_history.mkdir(parents=True)
        # A legacy report from before this feature landed.
        legacy_report = legacy_history / "2025-08-12.md"
        legacy_report.write_text("# prior plan", encoding="utf-8")
        (self.config / "podium.toml").write_text(
            '[[roster]]\nlaunch={kind="opencode", agent="writer", model="sample/writer"}\n'
            '[[agents]]\nname="writer"\nmodel="sample/writer"\n'
            '[roster_notes]\nexcluded=[]\n',
            encoding="utf-8",
        )
        # Stubs for versions / install method.
        self.executable("opencode", "echo 1.2.3-test")
        self.executable("claude", "echo 1.2.3-test")
        self.executable("brew", "exit 1")
        self.executable("npm", "exit 1")
        self.executable("ps", "echo 'header-only'")  # no active sessions

        output = self.run_script("preflight.sh")
        self.assertIn(str(legacy_report), output)
        self.assertNotIn("(no history)", output)

    def test_catalogs_reports_opencode_db_when_missing(self):
        """catalogs.sh must say `(opencode.db not found)` instead of crashing
        when the DB is absent (fresh install, no agent run yet)."""
        # Minimal podium.toml so the python filter does not error.
        (self.config / "podium.toml").write_text(
            '[[agents]]\nname="writer"\nmodel="sample/writer"\n'
            '[roster_notes]\nexcluded=[]\n',
            encoding="utf-8",
        )
        # Stub `opencode` so the script does not actually hit the network.
        self.executable("opencode", (
            "case \"$1\" in\n"
            "  models) echo \"opencode/sample-model\" ;;\n"
            "  run)    echo OK ;;\n"
            "  *)      exit 0 ;;\n"
            "esac"
        ))
        # Point HOME at a clean tempdir with no opencode directory tree, so
        # the script's hard-coded `$HOME/.local/share/opencode/opencode.db`
        # resolves to nothing.
        self.env["HOME"] = str(self.temp.name)

        result = subprocess.run(
            ["sh", str(PLUGIN / "catalogs.sh")],
            env=self.env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("== Actual model recorded (opencode.db)", result.stdout)
        # The DB is absent in this fresh tree.
        self.assertIn("(opencode.db not found)", result.stdout)

if __name__ == "__main__":
    unittest.main()
