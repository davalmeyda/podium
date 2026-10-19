"""``podium doctor`` — environment + install health checks (§11, §9.2).

Returns the documented exit code (``0`` when clean, ``3`` when any ``FAIL``
line was emitted). The CLI maps other exit codes; ``doctor.run`` only owns
``0`` and ``3``. ``WARN`` is informational and does not change the exit.

The checks are deliberately read-only: ``doctor`` never modifies files and
never invokes ``opencode``/``claude``. Where a probe requires an HTTP GET
(memory MCP), it is bounded to a 5-second timeout per the contract.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

_CMD_TIMEOUT_SECONDS = 5


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------


class _Severity:
    """Tag constants for the checklist rendering."""

    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


_Failures: list[str] = []


def _record(severity: str, label: str, detail: str = "") -> None:
    """Emit one checklist line and update the rolling failure count."""
    line = f"[{severity}] {label}"
    if detail:
        line += f": {detail}"
    print(line)
    if severity == _Severity.FAIL:
        _Failures.append(label)


def _reset_failures() -> None:
    """Tests call this between assertions to keep counts isolated."""
    _Failures.clear()


# ---------------------------------------------------------------------------
# Sub-checks
# ---------------------------------------------------------------------------


def _check_python(python_str: str | None = None) -> None:
    """Require Python >= 3.8 (the contract floor for portability)."""
    text = python_str or f"{sys.version_info.major}.{sys.version_info.minor}"
    try:
        major, minor, *_ = (int(p) for p in text.split("."))
    except ValueError:
        _record(_Severity.FAIL, "python", f"unparseable version {text!r}")
        return
    if (major, minor) >= (3, 8):
        _record(_Severity.OK, "python", text)
    else:
        _record(
            _Severity.FAIL,
            "python",
            f"{text} < 3.8 (the contract floor)",
        )


def _check_module_deps(modules: Mapping[str, Any]) -> None:
    """Probe enabled modules' external dependencies.

    ``rules`` and ``executors`` need ``claude`` and ``opencode`` CLI >= 2.0.0;
    ``codegraph`` needs the ``codegraph`` CLI; ``memory`` needs a configured
    URL that answers anything within 5s; ``usage`` needs the python ``sqlite3``
    module (always present on the stdlib).
    """
    modules = modules or {}

    if modules.get("rules") or modules.get("executors"):
        for name in ("claude", "opencode"):
            # OpenCode is required only when the roster launches OpenCode executors.
            required = name == "claude" or modules.get("needs_opencode", True)
            path = shutil.which(name)
            if path is None:
                if required:
                    _record(_Severity.FAIL, f"{name} cli", "not found on PATH")
                else:
                    _record(_Severity.OK, f"{name} cli", "not installed (no OpenCode executors in the roster)")
                continue
            # The contract says >= 2; we accept anything parseable as a best
            # effort and warn unless the major version is at least 2.
            major = _major_version_from_path(path, name)
            if major is None:
                _record(_Severity.WARN, f"{name} cli", f"found at {path}; version unparseable")
                continue
            if major >= 2:
                _record(_Severity.OK, f"{name} cli", f"v{major}.x at {path}")
            else:
                _record(
                    _Severity.FAIL,
                    f"{name} cli",
                    f"v{major}.x at {path}; need >= 2",
                )

    if modules.get("codegraph"):
        path = shutil.which("codegraph")
        if path is None:
            _record(_Severity.FAIL, "codegraph cli", "not found on PATH")
        else:
            _record(_Severity.OK, "codegraph cli", path)

    if modules.get("memory"):
        url = modules.get("memory_url") or ""
        if not url:
            _record(
                _Severity.WARN,
                "memory",
                "no memory.url set in podium.toml; memory module inactive",
            )
        else:
            status = _probe_url(url)
            if status is None:
                _record(_Severity.WARN, "memory", f"{url} did not answer within 5s")
            else:
                _record(_Severity.OK, "memory", f"{url} -> {status}")

    if modules.get("usage"):
        try:
            import sqlite3  # noqa: F401

            _record(_Severity.OK, "usage", "sqlite3 importable")
        except Exception as exc:  # pragma: no cover - stdlib always loads
            _record(_Severity.FAIL, "usage", str(exc))


def _major_version_from_path(path: str, name: str) -> int | None:
    """Parse ``<binary> --version`` output for the leading major digit.

    Accepts both comma-separated (``2.3.4 (build abc)``) and space-separated
    (``opencode 2.10.0``) layouts by scanning for the first token whose leading
    character is a digit (``2.3.4``) or ``v`` followed by a digit (``v2.3.4``).
    The major component is the integer before the first dot.
    """
    import subprocess

    try:
        completed = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=_CMD_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    blob = (completed.stdout or "") + (completed.stderr or "")
    # Normalise commas to spaces and scan every whitespace-delimited token.
    for raw in blob.replace(",", " ").split():
        token = raw.lstrip("vV")
        if not token or not token[0].isdigit():
            continue
        head = token.split(".", 1)[0]
        if head.isdigit():
            try:
                return int(head)
            except ValueError:
                continue
    return None


def _probe_url(url: str) -> int | None:
    """Best-effort HTTP GET/HEAD with a 5-second timeout.

    Returns the HTTP status code on the first response, ``None`` if the host
    did not answer within the budget. We accept any status as proof of life
    (the contract says "answers anything").
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    try:
        if parsed.scheme == "https":
            import ssl

            ctx = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=_CMD_TIMEOUT_SECONDS) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    request = (
                        f"HEAD {path} HTTP/1.1\r\nHost: {host}\r\n"
                        "User-Agent: podium-doctor\r\n"
                        "Connection: close\r\n\r\n"
                    )
                    ssock.sendall(request.encode("ascii"))
                    return _read_status(ssock.recv)
        request_bytes = (
            f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
            "User-Agent: podium-doctor\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        with socket.create_connection((host, port), timeout=_CMD_TIMEOUT_SECONDS) as sock:
            sock.sendall(request_bytes)
            return _read_status(sock.recv)
    except (OSError, socket.timeout):
        return None


def _read_status(recv) -> int | None:
    """Read one HTTP status line via a chunked ``recv`` caller."""
    buf = b""
    try:
        while b"\r\n" not in buf:
            chunk = recv(1024)
            if not chunk:
                break
            buf += chunk
    except (OSError, socket.timeout):
        return None
    head = buf.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
    parts = head.split(" ", 2)
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _check_runtime_json(config_dir: Path) -> None:
    """``runtime.json`` must exist and round-trip through ``json.loads``."""
    path = config_dir / "runtime.json"
    if not path.is_file():
        _record(_Severity.FAIL, "runtime.json", f"missing at {path}")
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            json.load(fh)
    except (OSError, ValueError) as exc:
        _record(_Severity.FAIL, "runtime.json", f"corrupt: {exc}")
        return
    _record(_Severity.OK, "runtime.json", str(path))


def _check_opencode_dupes(paths: Mapping[str, Any]) -> None:
    """Warn when both ``opencode.json`` and ``opencode.jsonc`` exist (§7)."""
    opencode_config_dir = Path(
        paths.get("opencode_config_dir") or Path.home() / ".config" / "opencode"
    )
    has_json = (opencode_config_dir / "opencode.json").is_file()
    has_jsonc = (opencode_config_dir / "opencode.jsonc").is_file()
    if has_json and has_jsonc:
        _record(
            _Severity.WARN,
            "opencode config",
            "opencode.json and opencode.jsonc both present; podium writes opencode.json",
        )


def _check_legacy_hooks(claude_block: Mapping[str, Any]) -> None:
    """FAIL when legacy hooks and podium plugins both bind the same event.

    We approximate "double firing" by checking that the user has at least one
    podium plugin installed *and* ``podium.detect`` reported legacy hook
    commands in ``settings.json``. Per-event attribution would require parsing
    the full hooks tree; the contract only demands the FAIL signal.
    """
    legacy = list(claude_block.get("legacy_hooks") or [])
    plugins = list(claude_block.get("plugins_installed") or [])
    if legacy and any(name.startswith("podium-") for name in plugins):
        _record(
            _Severity.FAIL,
            "hooks",
            "legacy codegraph/memory hook commands present alongside podium plugins",
        )
    elif legacy:
        _record(
            _Severity.WARN,
            "hooks",
            f"{len(legacy)} legacy hook command(s) still in settings.json; run `podium migrate`",
        )
    else:
        _record(_Severity.OK, "hooks", "no legacy hooks detected")


def _check_hooks_log(state_dir: Path) -> None:
    """WARN when ``hooks.log`` saw lines in the last 24h; surface the latest."""
    path = state_dir / "hooks.log"
    if not path.is_file():
        _record(_Severity.OK, "hooks.log", "no log file (no hook activity recorded)")
        return
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        _record(_Severity.WARN, "hooks.log", f"cannot read: {exc}")
        return
    if not lines:
        _record(_Severity.OK, "hooks.log", "empty")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent: list[tuple[datetime, str]] = []
    for raw in lines:
        ts = _parse_iso(raw.strip())
        if ts is not None and ts >= cutoff:
            recent.append((ts, raw.strip()))

    if not recent:
        _record(_Severity.OK, "hooks.log", "no entries in last 24h")
        return
    recent.sort(key=lambda row: row[0])
    _, last_line = recent[-1]
    _record(_Severity.WARN, "hooks.log", f"recent activity: {last_line}")


def _parse_iso(line: str) -> datetime | None:
    """Parse ``2026-04-30T12:34:56Z`` style hook log timestamps."""
    head = line.split(" ", 1)[0]
    try:
        if head.endswith("Z"):
            return datetime.fromisoformat(head[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(head)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(paths: Mapping[str, Any], config: Mapping[str, Any]) -> int:
    """Run all health checks and return 0 (clean) or 3 (any FAIL).

    ``paths`` is the resolved Paths mapping; ``config`` is the loaded
    ``podium.toml`` dict (defaults merged). doctor tolerates a missing
    ``[modules]`` block by treating every module as disabled.
    """
    _reset_failures()

    home = Path(paths.get("home") or Path.home())
    claude_dir = Path(paths.get("claude_dir") or home / ".claude")
    state_dir = Path(paths.get("state_dir") or home / ".local" / "state" / "podium")
    config_dir = Path(paths.get("config_dir") or home / ".config" / "podium")

    # python version check (always)
    _check_python()

    # module-level dependency checks
    modules = config.get("modules") if isinstance(config, Mapping) else {}
    if not isinstance(modules, Mapping):
        modules = {}
    memory_section = config.get("memory") if isinstance(config, Mapping) else {}
    if isinstance(memory_section, Mapping):
        modules = {**modules, "memory_url": memory_section.get("url") or ""}
    if isinstance(config, Mapping):
        rows = config.get("roster") or []
        modules = {**modules, "needs_opencode": bool(config.get("agents")) or any(
            isinstance(row, Mapping) and isinstance(row.get("launch"), Mapping)
            and row["launch"].get("kind") == "opencode" for row in rows)}
    _check_module_deps(modules)

    # runtime.json
    _check_runtime_json(config_dir)

    # opencode.jsonc duplicate
    _check_opencode_dupes(paths)

    # legacy-vs-podium plugin overlap
    legacy: Iterable[Any] = config.get("_legacy_hooks", []) or []
    plugins: Iterable[Any] = config.get("_plugins_installed", []) or []
    _check_legacy_hooks(
        {"legacy_hooks": list(legacy), "plugins_installed": list(plugins)}
    )

    # hooks.log tail
    _check_hooks_log(state_dir)

    return 3 if _Failures else 0


__all__ = ["run"]
