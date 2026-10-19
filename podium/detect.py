"""Read-only environment detection (ARCHITECTURE.md §12).

``detect.run(paths)`` returns a JSON-serialisable dictionary describing the host
environment. The function never raises: every external command runs with a
timeout and any failure becomes ``None`` or ``[]``. ``detect`` never writes to
the filesystem.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

# Commands exercised by detect. A failure for any one of them is non-fatal.
_CMD_TIMEOUT_SECONDS = 5


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Run ``cmd`` and return ``(returncode, stdout, stderr)``.

    Any error (missing executable, non-zero exit, timeout) is swallowed and
    surfaced as ``(1, "", "<error message>")`` so callers can decide. The
    timeout is intentionally short: detection is best-effort.
    """
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CMD_TIMEOUT_SECONDS,
            check=False,
        )
        return (completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (1, "", str(exc))


def _which(name: str) -> str | None:
    """Return the resolved path of ``name`` or ``None``.

    Honors a caller-provided ``PATH`` by injecting it into ``os.environ`` for
    the duration of the lookup. ``shutil.which`` consults the current process
    ``PATH``; tests rely on this so they can prime the lookup with stubs.
    """
    return shutil.which(name)


def _tool_version(name: str, version_args: list[str]) -> dict[str, Any] | None:
    """Return ``{"path": ..., "version": <first useful line or raw> | None}``.

    Returns ``None`` if the binary cannot be found. Tries ``--version`` first
    and falls back to plain execution without args.
    """
    path = _which(name)
    if path is None:
        return None
    rc, out, _ = _run([path, *version_args])
    version: str | None
    if rc == 0 and out:
        # Many CLIs print "name <version> ..." on the first line of --version.
        first = out.strip().splitlines()
        version = first[0].strip() if first else None
    else:
        # Some tools exit non-zero for --version; still treat as "found".
        version = None
    return {"path": path, "version": version}


def _python_version() -> str:
    """Return the running interpreter version as ``"3.x.y"``."""
    vi = sys.version_info
    return f"{vi.major}.{vi.minor}.{vi.micro}"


def _detect_os() -> str:
    """Map :func:`sys.platform` into the contract's three-way enum."""
    name = sys.platform.lower()
    if name.startswith("linux"):
        return "linux"
    if name.startswith("darwin"):
        return "darwin"
    return "other"


# ---------------------------------------------------------------------------
# OpenCode section
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    """Best-effort JSON read returning ``None`` on any failure."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _opencode_config_files(opencode_config_dir: Path) -> list[str]:
    """Return the existing ``opencode.json``/``.jsonc`` siblings as absolute paths."""
    found: list[str] = []
    for name in ("opencode.json", "opencode.jsonc"):
        candidate = opencode_config_dir / name
        if candidate.is_file():
            found.append(str(candidate))
    return found


def _opencode_providers() -> list[str]:
    """Run ``opencode auth list`` and best-effort parse provider ids.

    The output is plain text and varies by OpenCode version. We treat any line
    that starts with an alphanumeric id (letters, digits, dot, dash) and is not
    blank or starting with ``#`` as a provider id.
    """
    path = _which("opencode")
    if path is None:
        return []
    rc, out, _ = _run([path, "auth", "list"])
    if rc != 0 or not out:
        return []
    provider_re = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
    ids: list[str] = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split()[0]
        if provider_re.match(head):
            ids.append(head)
    # Stable order, deduped.
    return list(dict.fromkeys(ids))


def _opencode_agents(opencode_config_dir: Path) -> list[dict[str, Any]]:
    """Enumerate ``opencode_config_dir/agents/*.md`` owned-by-podium heuristic.

    A podium-owned agent carries either the ``podium:agent`` marker in its
    frontmatter or matches the ``podX-<role>-...`` naming convention used by
    the roster render pass. We do not parse YAML in stdlib; the heuristic is
    intentionally simple and the marker is the source of truth.
    """
    agents_dir = opencode_config_dir / "agents"
    if not agents_dir.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        owned = False
        try:
            text = entry.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if "podium:agent" in text or re.search(r"^pod\d?-", entry.name):
            owned = True
        result.append({"name": entry.stem, "path": str(entry), "podium_owned": owned})
    return result


def _opencode_mcp(opencode_config_dir: Path) -> list[str]:
    """Return server names found in ``opencode.json``/``.jsonc`` ``/mcp`` keys."""
    names: list[str] = []
    for child in ("opencode.json", "opencode.jsonc"):
        data = _read_json(opencode_config_dir / child)
        if not isinstance(data, dict):
            continue
        mcp = data.get("mcp")
        if isinstance(mcp, dict):
            names.extend(str(k) for k in mcp.keys())
        elif isinstance(mcp, list):
            for entry in mcp:
                if isinstance(entry, dict) and "name" in entry:
                    names.append(str(entry["name"]))
    return sorted(set(names))


# ---------------------------------------------------------------------------
# Claude section
# ---------------------------------------------------------------------------

# Hook command tokens that identify a legacy CodeGraph/Memory hook fired by
# the pre-podium setup. ``migrate`` strips exactly these from ``settings.json``.
_LEGACY_HOOK_TOKENS = (
    "codegraph-gate.py",
    "codegraph-nudge.py",
    "graphiti-stop.py",
)


def _read_settings(claude_dir: Path) -> dict[str, Any]:
    data = _read_json(claude_dir / "settings.json")
    return data if isinstance(data, dict) else {}


def _read_commands(node: Any) -> list[str]:
    """Flatten a settings-node into the list of command strings it runs.

    Settings trees nest in arbitrary ways (``hooks`` is a dict of event lists,
    each event is a list of matchers, each matcher has a ``hooks`` list of
    actual commands). We treat a node as a *command descriptor* when it carries
    a ``command`` or ``args`` field; otherwise we recurse into its values so
    we eventually reach every descriptor in the tree.
    """
    out: list[str] = []
    if isinstance(node, dict):
        cmd = node.get("command")
        if isinstance(cmd, str):
            out.append(cmd)
        args = node.get("args")
        if isinstance(args, list):
            for a in args:
                if isinstance(a, str):
                    out.append(a)
        # Recurse into values so nested structures (hooks.PreToolUse[*].hooks
        # etc.) are also walked.
        for value in node.values():
            if isinstance(value, (dict, list)):
                out.extend(_read_commands(value))
    elif isinstance(node, list):
        for item in node:
            out.extend(_read_commands(item))
    elif isinstance(node, str):
        out.append(node)
    return out


def _legacy_hooks(claude_dir: Path) -> list[str]:
    """Return the commands in ``settings.json`` invoking legacy hooks."""
    settings = _read_settings(claude_dir)
    if not settings:
        return []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict) and not isinstance(hooks, list):
        return []
    legacy: list[str] = []
    for command_or_args in _read_commands(hooks):
        if any(token in command_or_args for token in _LEGACY_HOOK_TOKENS):
            legacy.append(command_or_args)
    return legacy


def _claude_plugins_installed(claude_dir: Path) -> list[str]:
    """Return the plugin ids installed in the active Claude marketplaces.

    The shape of ``settings.json`` for plugins varies; ``enabledPlugins`` is a
    flat map of ``"<plugin>@<marketplace>": true/false``. We keep the namespaced
    id and the bare plugin name both.
    """
    settings = _read_settings(claude_dir)
    enabled = settings.get("enabledPlugins")
    if not isinstance(enabled, dict):
        return []
    ids: list[str] = []
    for key, value in enabled.items():
        if value is True:
            ids.append(str(key))
    return sorted(set(ids))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(paths: Mapping[str, Any]) -> dict[str, Any]:
    """Detect the host environment and return a JSON-serialisable snapshot.

    ``paths`` is the resolved Paths dataclass (or any mapping) from
    :mod:`podium.paths`. We accept a mapping so tests can supply plain dicts.
    """
    # Resolve the interesting paths up front; tolerate any of them missing.
    home = Path(paths.get("home") or Path.home())
    claude_dir = Path(paths.get("claude_dir") or (home / ".claude"))
    opencode_config_dir = Path(
        paths.get("opencode_config_dir") or (home / ".config" / "opencode")
    )
    config_dir = Path(paths.get("config_dir") or (home / ".config" / "podium"))
    state_dir = Path(paths.get("state_dir") or (home / ".local" / "state" / "podium"))

    os_name = _detect_os()
    python = _python_version()

    tools = {
        "claude": _tool_version("claude", ["--version"]),
        "opencode": _tool_version("opencode", ["--version"]),
        "codegraph": _tool_version("codegraph", ["--version"]),
        "git": _tool_version("git", ["--version"]),
    }

    opencode_block: dict[str, Any] = {
        "config_files": _opencode_config_files(opencode_config_dir),
        "providers": _opencode_providers(),
        "agents": _opencode_agents(opencode_config_dir),
        "mcp": _opencode_mcp(opencode_config_dir),
    }

    claude_block: dict[str, Any] = {
        "legacy_hooks": _legacy_hooks(claude_dir),
        "plugins_installed": _claude_plugins_installed(claude_dir),
    }

    podium_block: dict[str, Any] = {
        "config_exists": (config_dir / "podium.toml").is_file(),
        "ledger_exists": (state_dir / "owned.json").is_file(),
    }

    # Reflect the actual binary architecture alongside the friendly enum so
    # callers don't have to re-parse sys.platform if they want the kernel.
    return {
        "os": os_name,
        "kernel": platform.release(),
        "python": python,
        "tools": tools,
        "opencode": opencode_block,
        "claude": claude_block,
        "podium": podium_block,
    }


__all__ = ["run"]
