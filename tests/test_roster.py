"""Tests for ``podium.roster``.

Covers ARCHITECTURE.md §6 (``generated`` and ``render_agent``) plus the
two presets (``opencode-multi``, ``claude-only``) and the example
profile. Designed to be run in isolation while sibling tests for other
modules are still being written.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT))

import podium.roster as roster  # noqa: E402  (path munging above)
from podium.render import render_text as _real_render_text  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_config():
    """A baseline config matching the opencode-multi preset shape."""
    return {
        "launcher": {"opencode": "opencode run --auto"},
        "memory": {"mcp_server": "graphiti-memory"},
        "roster": [
            {
                "id": "minimax-fast",
                "engine": "MiniMax fast",
                "model": "MiniMax-M3 #none",
                "responsibility": "Code",
                "fallback": "haiku → luna",
                "launch": {
                    "kind": "opencode",
                    "agent": "minimax",
                    "model": "minimax/MiniMax-M3",
                    "variant": "none",
                },
            },
            {
                "id": "claude-row",
                "engine": "Claude native",
                "model": "haiku",
                "responsibility": "Info only",
                "fallback": "—",
                "launch": {"kind": "claude", "model": "haiku"},
            },
        ],
        "roster_notes": {
            "cascade": ["Code: MiniMax → haiku"],
            "excluded": ["opus — capacity held in reserve"],
        },
    }


def _install_fake_render(text):
    """Return a ``podium.render`` stub whose ``render_target`` returns ``text``.

    Returns the fake module so callers can keep a reference if needed.
    """
    fake = types.ModuleType("podium.render")

    def render_target(target_id, config, podium_home, config_dir):
        return text

    fake.render_target = render_target
    fake.render_text = _real_render_text
    fake.RenderError = type("RenderError", (Exception,), {})
    sys.modules["podium.render"] = fake
    # In Python 3.12+, ``import podium.render`` first consults the package
    # attribute, so we mirror the stub into the live ``podium`` package.
    import podium  # noqa: WPS433
    podium.render = fake  # type: ignore[attr-defined]
    return fake


# ---------------------------------------------------------------------------
# ``generated``: roster table
# ---------------------------------------------------------------------------


class RosterTableTests(unittest.TestCase):
    def test_header_and_separator(self):
        text = roster.generated(_basic_config())["roster_table"]
        lines = text.splitlines()
        self.assertEqual(
            lines[0], "| Engine | Model | Responsibility | If unavailable |"
        )
        self.assertEqual(lines[1], "|---|---|---|---|")

    def test_first_opencode_row(self):
        text = roster.generated(_basic_config())["roster_table"]
        self.assertIn(
            "| MiniMax fast | `MiniMax-M3` `#none` | Code | haiku → luna |",
            text.splitlines(),
        )

    def test_claude_row_uses_single_backtick_span(self):
        cfg = _basic_config()
        text = roster.generated(cfg)["roster_table"]
        self.assertIn(
            "| Claude native | `haiku` | Info only | — |",
            text.splitlines(),
        )

    def test_pipe_in_fallback_is_escaped(self):
        cfg = _basic_config()
        cfg["roster"][0]["fallback"] = "haiku | with note"
        text = roster.generated(cfg)["roster_table"]
        self.assertIn("haiku \\| with note", text)

    def test_pipe_in_engine_is_escaped(self):
        cfg = _basic_config()
        cfg["roster"][0]["engine"] = "MiniMax fast | A"
        text = roster.generated(cfg)["roster_table"]
        self.assertIn("MiniMax fast \\| A", text)


# ---------------------------------------------------------------------------
# ``generated``: excluded / cascade / launch_examples
# ---------------------------------------------------------------------------


class BulletAndLaunchTests(unittest.TestCase):
    def test_excluded_non_empty(self):
        cfg = _basic_config()
        text = roster.generated(cfg)["roster_excluded"]
        self.assertEqual(text, "- opus — capacity held in reserve")

    def test_excluded_empty_returns_empty_string(self):
        cfg = _basic_config()
        cfg["roster_notes"]["excluded"] = []
        self.assertEqual(roster.generated(cfg)["roster_excluded"], "")

    def test_cascade_multi_line_joined_by_newline(self):
        cfg = _basic_config()
        cfg["roster_notes"]["cascade"] = ["Code: A → B", "Overflow: C → D"]
        text = roster.generated(cfg)["fallback_cascade"]
        self.assertEqual(text, "- Code: A → B\n- Overflow: C → D")

    def test_cascade_empty_returns_empty_string(self):
        cfg = _basic_config()
        cfg["roster_notes"]["cascade"] = []
        self.assertEqual(roster.generated(cfg)["fallback_cascade"], "")

    def test_launch_examples_single_opencode_row(self):
        cfg = _basic_config()
        cfg["roster"] = [cfg["roster"][0]]
        cfg["roster_notes"] = {"cascade": [], "excluded": []}
        text = roster.generated(cfg)["launch_examples"]
        expected = (
            "```sh\n"
            "cd <dir> && opencode run --auto --agent minimax "
            '-m "minimax/MiniMax-M3#none" '
            '"$(cat <brief>.txt)" '
            "</dev/null > <digest>.txt 2> <trace>.txt\n"
            "```"
        )
        self.assertEqual(text, expected)

    def test_launch_examples_dedupes_identical_commands(self):
        cfg = {
            "launcher": {"opencode": "opencode run --auto"},
            "roster": [
                {
                    "engine": "A",
                    "model": "m #none",
                    "responsibility": "r",
                    "fallback": "—",
                    "launch": {
                        "kind": "opencode",
                        "agent": "minimax",
                        "model": "minimax/MiniMax-M3",
                        "variant": "none",
                    },
                },
                {
                    "engine": "B",
                    "model": "m #none",
                    "responsibility": "r",
                    "fallback": "—",
                    "launch": {
                        "kind": "opencode",
                        "agent": "minimax",
                        "model": "minimax/MiniMax-M3",
                        "variant": "none",
                    },
                },
            ],
            "roster_notes": {"cascade": [], "excluded": []},
        }
        text = roster.generated(cfg)["launch_examples"]
        self.assertEqual(text.count("opencode run --auto"), 1)

    def test_launch_examples_skips_claude_rows(self):
        cfg = _basic_config()
        cfg["roster_notes"] = {"cascade": [], "excluded": []}
        text = roster.generated(cfg)["launch_examples"]
        self.assertEqual(text.count("opencode run --auto"), 1)

    def test_launch_examples_empty_when_no_opencode_rows(self):
        cfg = _basic_config()
        cfg["roster"] = [cfg["roster"][1]]
        cfg["roster_notes"] = {"cascade": [], "excluded": []}
        self.assertEqual(roster.generated(cfg)["launch_examples"], "")


# ---------------------------------------------------------------------------
# ``render_agent``: frontmatter byte equality
# ---------------------------------------------------------------------------


WRITER_AGENT = {
    "name": "minimax",
    "role": "writer",
    "model": "minimax/MiniMax-M3",
    "description": "MiniMax-M3 executor — default code executor of the cascade.",
    "deny_mcp": ["chrome-devtools_*"],
}

CONSULTANT_AGENT = {
    "name": "sol",
    "role": "consultant",
    "model": "openai/gpt-6.1-sol",
    "description": (
        "GPT-6.1 Sol consultant — diagnosis, review with judgement, "
        "second opinion, and architecture verdict."
    ),
    "deny_mcp": ["chrome-devtools_*"],
}


CONFIG_WITH_MEMORY = {
    "memory": {"mcp_server": "graphiti-memory"},
}


class RenderAgentTests(unittest.TestCase):
    """Run ``render_agent`` against a controlled ``podium_home`` tmpdir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.roles_dir = self.tmp / "executors" / "roles"
        self.roles_dir.mkdir(parents=True)
        self._installed_render = None

    def tearDown(self):
        # Restore the original render module if we swapped it.
        if self._installed_render is not None:
            sys.modules.pop("podium.render", None)
            import podium  # noqa: WPS433
            if hasattr(podium, "render"):
                del podium.render  # type: ignore[attr-defined]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_role(self, role, text):
        (self.roles_dir / f"{role}.md").write_text(text, encoding="utf-8")

    def _render(self, agent, profile_text):
        if self._installed_render is None:
            self._installed_render = _install_fake_render(profile_text)
        return roster.render_agent(agent, CONFIG_WITH_MEMORY, self.tmp)

    def test_writer_frontmatter_only(self):
        # No role file: body is just the executor profile.
        text = self._render(WRITER_AGENT, "## Executor profile\n\nbe brief.")
        expected = (
            "---\n"
            "description: MiniMax-M3 executor — default code executor of the cascade.\n"
            "mode: primary\n"
            "model: minimax/MiniMax-M3\n"
            "permission:\n"
            "  skill: deny\n"
            "  task: deny\n"
            '  "graphiti-memory_*": deny\n'
            '  "codegraph_*": allow\n'
            '  "chrome-devtools_*": deny\n'
            '  bash: {"*": allow, "git *": deny}\n'
            "---\n"
            "\n"
            "## Executor profile\n"
            "\n"
            "be brief.\n"
        )
        self.assertEqual(text, expected)

    def test_consultant_frontmatter_only(self):
        text = self._render(CONSULTANT_AGENT, "## Profile")
        expected = (
            "---\n"
            "description: GPT-6.1 Sol consultant — diagnosis, review with judgement, second opinion, and architecture verdict.\n"
            "mode: primary\n"
            "model: openai/gpt-6.1-sol\n"
            "permission:\n"
            "  skill: deny\n"
            "  task: deny\n"
            "  edit: deny\n"
            '  "graphiti-memory_*": deny\n'
            '  "codegraph_*": allow\n'
            '  "chrome-devtools_*": deny\n'
            '  bash: {"*": deny, "ls *": allow, "cat *": allow, "head *": allow, "tail *": allow, "wc *": allow, "grep *": allow, "rg *": allow, "find *": allow, "sed -n *": allow}\n'
            "---\n"
            "\n"
            "## Profile\n"
        )
        self.assertEqual(text, expected)

    def test_role_preamble_then_executor_profile(self):
        self._write_role("writer", "## Writer role\nBe focused.\n")
        text = self._render(WRITER_AGENT, "## Profile body")
        expected = (
            "---\n"
            "description: MiniMax-M3 executor — default code executor of the cascade.\n"
            "mode: primary\n"
            "model: minimax/MiniMax-M3\n"
            "permission:\n"
            "  skill: deny\n"
            "  task: deny\n"
            '  "graphiti-memory_*": deny\n'
            '  "codegraph_*": allow\n'
            '  "chrome-devtools_*": deny\n'
            '  bash: {"*": allow, "git *": deny}\n'
            "---\n"
            "\n"
            "## Writer role\n"
            "Be focused.\n"
            "\n"
            "## Profile body\n"
        )
        self.assertEqual(text, expected)


    def test_role_preamble_is_templated(self):
        self._write_role("writer", "Skip the {{ memory.mcp_server }} tools.\n")
        text = self._render(WRITER_AGENT, "## Profile body")
        self.assertIn("Skip the graphiti-memory tools.", text)
        self.assertNotIn("{{", text)


# ---------------------------------------------------------------------------
# Preset files: parse with tomllib / vendored tomli, only allowed sections.
# ---------------------------------------------------------------------------


def _load_toml():
    try:
        import tomllib  # type: ignore[import-not-found]
        return ("tomllib", tomllib)
    except Exception:
        pass
    try:
        sys.path.insert(0, str(REPO_ROOT / "podium" / "_vendor"))
        import tomli  # type: ignore[import-not-found]
        return ("tomli", tomli)
    except Exception:
        return None


_TOML = _load_toml()


@unittest.skipIf(_TOML is None, "no tomllib / vendored tomli available")
class PresetFileTests(unittest.TestCase):
    # init writes schema/[language]/[modules]/[principal]/[launcher] itself and
    # appends the preset verbatim, so a preset may only carry these sections.
    ALLOWED_TOP_KEYS = {"roster", "agents", "roster_notes"}

    @staticmethod
    def _load(rel_path):
        name, loader = _TOML
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        return loader.loads(text)

    def test_opencode_multi_parses_and_sections(self):
        data = self._load("podium/presets/opencode-multi.toml")
        for key in data:
            self.assertIn(
                key,
                self.ALLOWED_TOP_KEYS,
                f"unexpected top-level key in opencode-multi preset: {key}",
            )
        agent_names = sorted(a["name"] for a in data["agents"])
        self.assertEqual(agent_names, ["luna", "minimax", "sol"])
        roles = [a["role"] for a in data["agents"]]
        self.assertEqual(roles, ["writer", "consultant", "overflow"])
        for agent in data["agents"]:
            self.assertIn("chrome-devtools_*", agent["deny_mcp"])

    def test_claude_only_parses_and_has_no_agents(self):
        data = self._load("podium/presets/claude-only.toml")
        for key in data:
            self.assertIn(
                key,
                self.ALLOWED_TOP_KEYS,
                f"unexpected top-level key in claude-only preset: {key}",
            )
        self.assertNotIn("agents", data)
        kinds = {row["launch"]["kind"] for row in data["roster"]}
        self.assertEqual(kinds, {"claude", "principal"})

    def test_example_profile_parses(self):
        data = self._load("profiles/example/podium.toml")
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["language"]["response"], "en")
        self.assertEqual(data["language"]["domain"], "en")
        self.assertEqual(data["language"]["ui"], "en")
        for module_name, enabled in data["modules"].items():
            self.assertTrue(
                enabled, f"example profile must enable {module_name}"
            )
        self.assertEqual(data["memory"]["url"], "${PODIUM_GRAPHITI_URL}")


if __name__ == "__main__":
    unittest.main()
