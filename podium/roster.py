"""Roster rendering for podium.

Implements ARCHITECTURE.md §6:
- ``generated(config) -> dict[str, str]`` returns the four text fragments
  used by the rules manifest as ``{{ generated.<name> }}``.
- ``render_agent(agent, config, podium_home) -> str`` returns the full
  OpenCode agent file (YAML frontmatter + role preamble + executor
  profile) for one ``[[agents]]`` entry.

This module is the only place that knows the shape of ``[[roster]]``,
``[[agents]]``, ``[roster_notes]`` and ``[launcher]``. Other modules
(route, init, install) only read its output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping


# ---------------------------------------------------------------------------
# Roster table fragments (ARCHITECTURE.md §6)
# ---------------------------------------------------------------------------

_TABLE_HEADER = "| Engine | Model | Responsibility | If unavailable |"
_TABLE_SEPARATOR = "|---|---|---|---|"


def _escape_cell(text: str) -> str:
    """Escape ``|`` so the cell does not break the Markdown table."""
    return text.replace("|", "\\|")


def _format_model_cell(model: str) -> str:
    """Render the model column.

    If the display model contains a literal ``" #"`` the part before it
    is wrapped in one backtick span and the part after (``#suffix``) in
    another (e.g. ``"MiniMax-M3 #none"`` becomes
    ``"`MiniMax-M3` `#none`"``). Otherwise the whole string is wrapped
    in a single pair of backticks.
    """
    token = " #"
    if token in model:
        head, tail = model.split(token, 1)
        return f"`{head}` `#{tail}`"
    return f"`{model}`"


def _format_launch_command(launch: Mapping[str, object], launcher_prefix: str) -> str:
    """Format the ``sh`` example for a single opencode roster row.

    Uses the exact template from ARCHITECTURE.md §6, with literal
    placeholders ``<dir>``, ``<brief>``, ``<digest>``, ``<trace>``.
    """
    agent = str(launch.get("agent", ""))
    model = str(launch.get("model", ""))
    variant = str(launch.get("variant", ""))
    return (
        "cd <dir> && "
        f"{launcher_prefix} --agent {agent} "
        f'-m "{model}#{variant}" '
        '"$(cat <brief>.txt)" '
        "</dev/null > <digest>.txt 2> <trace>.txt"
    )


def _bullet_block(lines):
    """Render a ``- line`` block joined by ``\\n``; empty list -> empty string."""
    if not lines:
        return ""
    return "\n".join(f"- {line}" for line in lines)


def generated(config: Mapping[str, object]) -> dict:
    """Return the four ``{{ generated.<name> }}`` text fragments."""
    roster = list(config.get("roster") or [])
    notes = config.get("roster_notes") or {}
    launcher = config.get("launcher") or {}
    launcher_prefix = str(launcher.get("opencode", "opencode run --auto"))

    # roster_table ----------------------------------------------------------
    table_lines = [_TABLE_HEADER, _TABLE_SEPARATOR]
    for row in roster:
        engine = _escape_cell(str(row.get("engine", "")))
        model = _format_model_cell(str(row.get("model", "")))
        responsibility = _escape_cell(str(row.get("responsibility", "")))
        fallback = _escape_cell(str(row.get("fallback", "")))
        table_lines.append(
            f"| {engine} | {model} | {responsibility} | {fallback} |"
        )
    roster_table = "\n".join(table_lines)

    # roster_excluded / fallback_cascade -----------------------------------
    roster_excluded = _bullet_block(list(notes.get("excluded") or []))
    fallback_cascade = _bullet_block(list(notes.get("cascade") or []))

    # launch_examples -------------------------------------------------------
    seen = set()
    commands = []
    for row in roster:
        launch = row.get("launch") or {}
        if launch.get("kind") != "opencode":
            continue
        command = _format_launch_command(launch, launcher_prefix)
        if command in seen:
            continue
        seen.add(command)
        commands.append(command)
    if commands:
        launch_examples = "```sh\n" + "\n".join(commands) + "\n```"
    else:
        launch_examples = ""

    return {
        "roster_table": roster_table,
        "roster_excluded": roster_excluded,
        "fallback_cascade": fallback_cascade,
        "launch_examples": launch_examples,
    }


# ---------------------------------------------------------------------------
# Per-agent frontmatter (ARCHITECTURE.md §6 role permission skeletons)
# ---------------------------------------------------------------------------

_WRITER_BASH = {"*": "allow", "git *": "deny"}

_CONSULTANT_BASH = {
    "*": "deny",
    "ls *": "allow",
    "cat *": "allow",
    "head *": "allow",
    "tail *": "allow",
    "wc *": "allow",
    "grep *": "allow",
    "rg *": "allow",
    "find *": "allow",
    "sed -n *": "allow",
}


def _yaml_indent(value: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else line for line in value.split("\n"))


def _format_deny_mcp(globs):
    """Format ``deny_mcp`` entries as ``"<glob>": deny`` in stable order."""
    return [f'"{glob}": deny' for glob in globs]


def _render_frontmatter(agent: Mapping[str, object], config: Mapping[str, object]) -> str:
    """Render only the YAML frontmatter block (the ``---\n...\n---`` lines)."""
    role = str(agent.get("role", "writer"))
    description = str(agent.get("description", ""))
    model = str(agent.get("model", ""))

    memory_mcp_server = (
        (config.get("memory") or {}).get("mcp_server") or "graphiti-memory"
    )
    deny_mcp = list(agent.get("deny_mcp") or [])

    permission_lines = [
        "  skill: deny",
        "  task: deny",
    ]
    if role == "consultant":
        permission_lines.append("  edit: deny")
    permission_lines.append(f'  "{memory_mcp_server}_*": deny')
    permission_lines.append('  "codegraph_*": allow')
    permission_lines.extend(f"  {line}" for line in _format_deny_mcp(deny_mcp))

    if role == "consultant":
        bash_value = _CONSULTANT_BASH
    else:
        bash_value = _WRITER_BASH

    bash_entries = ", ".join(
        f'"{key}": {value}' for key, value in bash_value.items()
    )
    permission_lines.append(f"  bash: {{{bash_entries}}}")

    permission_block = "\n".join(permission_lines)

    return (
        "---\n"
        f"description: {description}\n"
        "mode: primary\n"
        f"model: {model}\n"
        "permission:\n"
        f"{permission_block}\n"
        "---"
    )


def _read_role_preamble(podium_home, agent: Mapping[str, object], config: Mapping[str, object]) -> str:
    """Return the role preamble from ``executors/roles/<role>.md``, templated like any fragment."""
    from podium import render as _render

    role = str(agent.get("role", "writer"))
    path = Path(podium_home) / "executors" / "roles" / f"{role}.md"
    if not path.is_file():
        return ""
    return _render.render_text(path.read_text(encoding="utf-8"), config).rstrip("\n")


def _read_executor_profile(config: Mapping[str, object], podium_home) -> str:
    """Return the rendered executor profile text (errors propagate: an agent
    file without its profile would silently lose every executor rule)."""
    from podium import render as _render

    config_dir = None
    paths = config.get("_paths") if isinstance(config, Mapping) else None
    if isinstance(paths, Mapping):
        config_dir = paths.get("config_dir")
    if config_dir is None:
        from podium import paths as _paths

        config_dir = _paths.resolve().config_dir
    return _render.render_target("executor-profile", config, podium_home, config_dir).rstrip("\n")


def render_agent(
    agent: Mapping[str, object],
    config: Mapping[str, object],
    podium_home,
) -> str:
    """Return the full OpenCode agent file for one ``[[agents]]`` entry."""
    frontmatter = _render_frontmatter(agent, config)
    role_preamble = _read_role_preamble(podium_home, agent, config)
    executor_profile = _read_executor_profile(config, podium_home)

    body_sections = []
    if role_preamble:
        body_sections.append(role_preamble)
    if executor_profile:
        body_sections.append(executor_profile)
    if not body_sections:
        return frontmatter + "\n"

    parts = [frontmatter]
    for section in body_sections:
        parts.append("")
        parts.append(section)
    return "\n".join(parts) + "\n"
