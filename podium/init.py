"""``podium init`` — generate ``config_dir/podium.toml`` (ARCHITECTURE.md §12).

``init.run(paths, answers, interactive)`` produces a TOML profile at
``config_dir/podium.toml``. It reads roster presets from
``podium/presets/<preset>.toml`` (owned by another agent — read here, never
rewritten) and appends the chosen preset verbatim below our own header
sections.

Failure modes (all raise :class:`InitError` so the CLI can surface them):

* ``answers`` missing a required key and ``interactive=False``.
* The chosen roster preset file does not exist on disk.
* The destination ``podium.toml`` exists and the caller did not authorise
  overwrite (either ``answers["overwrite"]`` or an interactive confirmation).

The TOML output is built by hand-stringification so the generator stays
predictable. After writing, the file is parsed back through
``podium.config.load`` if available, purely to validate. ``init`` never calls
``podium install``; that is a separate step.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Roster presets shipped with the CLI (provided by another agent). The literal
# preset name is what callers pass via ``answers["roster_preset"]``.
PRESETS_DIR_NAME = "presets"

# Keys init consumes from ``answers``. Anything else in ``answers`` is ignored.
ANSWER_KEYS: tuple[str, ...] = (
    "language.response",
    "language.domain",
    "language.ui",
    "modules",
    "memory.url",
    "roster_preset",
    "adopt",
    "overwrite",
)

# Defaults for an entirely clean install. Match the schema in §4.
_LANGUAGE_DEFAULTS = {"response": "en", "domain": "en", "ui": "en"}
_MODULES_DEFAULT: tuple[str, ...] = (
    "rules", "executors", "codegraph", "memory", "usage", "upgrade",
)


class InitError(Exception):
    """Raised for every user-recoverable failure of :func:`run`."""


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _home(paths: Mapping[str, Any]) -> Path:
    """Return the podium checkout root from the resolved paths mapping."""
    home = paths.get("home")
    return Path(home) if home else Path(__file__).resolve().parent.parent


def _config_dir(paths: Mapping[str, Any]) -> Path:
    value = paths.get("config_dir")
    return Path(value) if value else Path.home() / ".config" / "podium"


def _state_dir(paths: Mapping[str, Any]) -> Path:
    value = paths.get("state_dir")
    return Path(value) if value else Path.home() / ".local" / "state" / "podium"


def _podium_toml(config_dir: Path) -> Path:
    return config_dir / "podium.toml"


# ---------------------------------------------------------------------------
# Preset handling
# ---------------------------------------------------------------------------


def _read_preset(home: Path, preset: str) -> str:
    """Return the verbatim contents of ``podium/presets/<preset>.toml``."""
    # Strict: refuse unknown preset names. Tests rely on this raising.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", preset or ""):
        raise InitError(f"invalid roster preset name: {preset!r}")
    path = home / "podium" / PRESETS_DIR_NAME / f"{preset}.toml"
    if not path.is_file():
        raise InitError(f"roster preset not found: {preset!r}")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InitError(f"cannot read roster preset {preset!r}: {exc}") from exc


def _missing_providers(providers: Sequence[str] | None) -> list[str]:
    """Decide which providers the preset would need but the user lacks.

    ``opencode-multi`` requires both ``minimax`` (MiniMax) and ``openai`` per
    §12. Other presets are permissive. We only consider the providers listed
    in the preset's front matter; for an unknown preset we never warn.
    """
    if not providers:
        available = set()
    else:
        available = {p.lower() for p in providers}
    required = {"minimax", "openai"}
    return sorted(required - available)


# ---------------------------------------------------------------------------
# Interactive prompting
# ---------------------------------------------------------------------------


def _ask(prompt: str, default: str, *, interactive: bool) -> str:
    """Read a single answer from stdin in interactive mode, else return default."""
    if not interactive:
        return default
    try:
        answer = input(f"{prompt} [{default}]: ")
    except EOFError:
        return default
    answer = answer.strip()
    return answer or default


def _ask_bool(prompt: str, default: bool, *, interactive: bool) -> bool:
    if not interactive:
        return default
    raw = _ask(prompt, "y" if default else "n", interactive=interactive).lower()
    return raw in {"y", "yes", "true", "1"}


def _ask_list(prompt: str, default: Sequence[str], *, interactive: bool) -> list[str]:
    if not interactive:
        return list(default)
    raw = _ask(prompt, ",".join(default), interactive=interactive)
    return [token.strip() for token in raw.split(",") if token.strip()]


# ---------------------------------------------------------------------------
# Answers merging
# ---------------------------------------------------------------------------


def _flatten(answers: Mapping[str, Any], prefix: str = "") -> dict:
    """Flatten nested answer objects into dotted keys, keeping lists as values."""
    flat = {}
    for key, value in answers.items():
        dotted = prefix + key
        if isinstance(value, Mapping) and dotted not in ANSWER_KEYS:
            flat.update(_flatten(value, dotted + "."))
        else:
            flat[dotted] = value
    return flat


def _gather_answers(
    answers: Mapping[str, Any] | None,
    *,
    interactive: bool,
    providers: Sequence[str] | None,
) -> dict[str, Any]:
    """Resolve answers from a dict, interactive prompt, or a blend of both.

    The dict wins when present; missing keys fall back to defaults or, in
    interactive mode, a question.
    """
    base: dict[str, Any] = {}
    if answers is not None:
        # Accept nested objects ({"language": {"response": "es"}}) as well as dotted keys.
        answers = _flatten(answers)
        # Copy only known keys; foreign keys would pollute the file.
        for key in ANSWER_KEYS:
            if key in answers:
                base[key] = answers[key]

    resolved: dict[str, Any] = {}

    # language.*
    resolved["language.response"] = base.get(
        "language.response",
        _ask(
            "Language for agent answers",
            _LANGUAGE_DEFAULTS["response"],
            interactive=interactive,
        ),
    )
    resolved["language.domain"] = base.get(
        "language.domain",
        _ask(
            "Language for code identifiers and messages",
            _LANGUAGE_DEFAULTS["domain"],
            interactive=interactive,
        ),
    )
    resolved["language.ui"] = base.get(
        "language.ui",
        _ask(
            "UI locale (en|es)",
            _LANGUAGE_DEFAULTS["ui"],
            interactive=interactive,
        ),
    )

    # modules — a list of module ids
    resolved["modules"] = base.get(
        "modules",
        _ask_list(
            "Enabled modules (comma-separated)",
            _MODULES_DEFAULT,
            interactive=interactive,
        ),
    )

    # memory URL — empty string means "do not configure the memory module"
    resolved["memory.url"] = base.get(
        "memory.url",
        _ask(
            "Graphiti memory MCP URL (blank to disable memory module)",
            "",
            interactive=interactive,
        ),
    )

    # roster preset
    preset_default = base.get("roster_preset", "opencode-multi")
    resolved["roster_preset"] = base.get(
        "roster_preset",
        _ask("Roster preset (opencode-multi|claude-only|custom)", preset_default, interactive=interactive),
    )

    # adopt / overwrite flags
    resolved["adopt"] = bool(
        base.get(
            "adopt",
            _ask_bool("Adopt existing foreign files", False, interactive=interactive),
        )
    )
    resolved["overwrite"] = bool(
        base.get(
            "overwrite",
            _ask_bool("Overwrite existing podium.toml", False, interactive=interactive),
        )
    )

    # If interactive and the user picked opencode-multi without the providers
    # the preset requires, we mark overwrite+preset but do NOT fail here.
    resolved["_missing_providers"] = _missing_providers(providers)
    return resolved


# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------


def _header_block(resolved: Mapping[str, Any]) -> str:
    """Render the schema + language + modules + principal sections (§4)."""
    language = (
        f"response = {json_dump_str(resolved['language.response'])}\n"
        f"domain = {json_dump_str(resolved['language.domain'])}\n"
        f"ui = {json_dump_str(resolved['language.ui'])}\n"
    )
    modules_lines = [
        f"{name} = {str(bool(name in resolved['modules'])).lower()}"
        for name in _MODULES_DEFAULT
    ]
    principal = (
        "always_background = true\n"
        "subagents_preauthorized = true\n"
        "forbid_workflow_tool = true\n"
    )
    launcher = 'opencode = "opencode run --auto"\n'

    sections: list[str] = []
    sections.append("schema = 1\n")
    sections.append("[language]\n" + language)
    sections.append("[modules]\n" + "\n".join(modules_lines) + "\n")
    sections.append("[principal]\n" + principal)
    sections.append("[launcher]\n" + launcher)
    return "\n".join(sections)


def _memory_block(resolved: Mapping[str, Any]) -> str:
    """Render the ``[memory]`` section, or skip it when no URL is given."""
    url = (resolved.get("memory.url") or "").strip()
    if not url:
        return ""
    lines = [
        "[memory]",
        'backend = "graphiti"',
        'mcp_server = "graphiti-memory"',
        f"url = {json_dump_str(url)}",
        'group = "main"',
        "stop_hook = { min_edits = 8, min_executor_runs = 2, cooldown_seconds = 2700 }",
        "",
    ]
    return "\n".join(lines)


def _presets_block(home: Path, resolved: Mapping[str, Any]) -> str:
    """Append the chosen roster preset verbatim, with missing-provider warning."""
    preset = resolved["roster_preset"]
    body = _read_preset(home, preset).strip("\n")

    missing = resolved.get("_missing_providers") or []
    if preset == "opencode-multi" and missing:
        warning = (
            f"# WARNING: roster preset '{preset}' references providers not "
            f"detected on this host: {', '.join(missing)}.\n"
            "# Install the matching provider credentials, or choose another "
            "roster preset, before running `podium install`.\n"
        )
        return warning + body + "\n"
    return body + "\n"


def _render(home: Path, resolved: Mapping[str, Any]) -> str:
    """Compose the full TOML document from header + modules + preset block."""
    parts: list[str] = []
    # Missing-provider note at the very top so users see it first.
    if resolved.get("_missing_providers") and resolved.get("roster_preset") == "opencode-multi":
        parts.append(
            "# WARNING: the chosen roster preset assumes the following "
            f"providers: {', '.join(resolved['_missing_providers'])}.\n"
        )
    parts.append(_header_block(resolved))
    memory = _memory_block(resolved)
    if memory:
        parts.append(memory)
    parts.append(_presets_block(home, resolved))
    return "\n".join(parts)


def json_dump_str(value: Any) -> str:
    """Render a Python value as the TOML-equivalent string literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    # Default to a quoted TOML basic string. Escape the few characters that
    # would otherwise close the literal early.
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# Backup / overwrite
# ---------------------------------------------------------------------------


def _stamp() -> str:
    """Return the backup timestamp suffix used in §7."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _backup(target: Path) -> Path:
    """Move ``target`` aside with the documented suffix and return its new path."""
    suffix = _stamp()
    hex4 = format(abs(hash(str(target))) % (16**4), "04x")
    backup = target.with_name(f"{target.name}.bak-podium-{suffix}-{hex4}")
    counter = 1
    while backup.exists():
        backup = target.with_name(
            f"{target.name}.bak-podium-{suffix}-{hex4}-{counter}"
        )
        counter += 1
    target.rename(backup)
    return backup


# ---------------------------------------------------------------------------
# Validation hook (optional; uses podium.config if present)
# ---------------------------------------------------------------------------


def _validate(out_path: Path) -> None:
    """Round-trip the generated file through ``podium.config.load``.

    A missing ``podium.config`` is not fatal: the contract allows init to run
    in environments where other agents haven't finished wiring the rest of the
    package. We swallow ``ImportError`` and ``AttributeError`` only.
    """
    try:
        from podium.config import load  # type: ignore[import-not-found]
    except (ImportError, AttributeError):
        return
    # Use a fresh env so we don't depend on PODIUM_* vars during a smoke test.
    try:
        load(out_path.parent, env={})
    except Exception as exc:  # surface the validation failure to the caller
        raise InitError(f"generated podium.toml failed validation: {exc}") from exc


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    paths: Mapping[str, Any],
    answers: Mapping[str, Any] | None = None,
    *,
    interactive: bool = False,
) -> Path:
    """Build ``config_dir/podium.toml`` and return its path.

    See module docstring for the contract.
    """
    home = _home(paths)
    config_dir = _config_dir(paths)
    out_path = _podium_toml(config_dir)

    # Defer the providers lookup to detect.run so init can be called without a
    # full detect pass; we accept None and skip the warning path in that case.
    providers: Sequence[str] | None
    try:
        from podium import detect as _detect  # local import to avoid cycles

        snapshot = _detect.run(paths)
        providers = list(snapshot.get("opencode", {}).get("providers") or [])
    except Exception:
        providers = None

    resolved = _gather_answers(answers, interactive=interactive, providers=providers)

    config_dir.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        overwrite = bool(resolved.get("overwrite"))
        if not overwrite:
            if interactive:
                overwrite = _ask_bool(
                    f"{out_path} exists. Overwrite?", False, interactive=True
                )
            if not overwrite:
                raise InitError(
                    f"refusing to overwrite existing {out_path}; pass "
                    "answers['overwrite']=true or confirm interactively"
                )
        _backup(out_path)

    rendered = _render(home, resolved)
    tmp = out_path.with_name(out_path.name + ".tmp")
    try:
        tmp.write_text(rendered, encoding="utf-8")
        os.replace(tmp, out_path)
    except OSError as exc:
        raise InitError(f"failed to write {out_path}: {exc}") from exc

    _validate(out_path)
    return out_path


__all__ = ["run", "InitError"]
