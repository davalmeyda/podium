"""Tests for ``podium.doctor`` (ARCHITECTURE.md §11)."""

from __future__ import annotations

import io
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from podium import doctor  # noqa: E402


def _make_stub_dir(tmp: Path) -> Path:
    d = tmp / "stubs"
    d.mkdir()
    scripts = {
        "claude": "#!/bin/sh\necho 'claude 2.3.4'\n",
        "opencode": "#!/bin/sh\necho 'opencode 2.10.0'\n",
        "codegraph": "#!/bin/sh\necho 'codegraph 1.4.7'\n",
        "git": "#!/bin/sh\necho 'git version 2.39.0'\n",
    }
    for name, body in scripts.items():
        script = d / name
        script.write_text(body)
        script.chmod(0o755)
    return d


class _StubServer:
    """Minimal HTTP server used to exercise the memory URL probe."""

    def __init__(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            while True:
                conn, _ = self._server.accept()
                data = conn.recv(4096)
                _ = data
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                    b"Connection: close\r\n\r\nOK"
                )
                conn.close()
        except OSError:
            return

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def close(self) -> None:
        try:
            self._server.close()
        except OSError:
            pass


class _SilentServer:
    """Accepts then closes immediately so the probe times out the request."""

    def __init__(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def close(self) -> None:
        try:
            self._server.close()
        except OSError:
            pass


class DoctorRunTests(unittest.TestCase):
    """End-to-end status reporting with controllable PATH + filesystem."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="podium-doctor-"))
        self.stubs = _make_stub_dir(self.tmp)
        self._saved_path = os.environ.get("PATH")
        os.environ["PATH"] = f"{self.stubs}{os.pathsep}{self._saved_path or ''}"

    def tearDown(self) -> None:
        if self._saved_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._saved_path

    def _paths(self, runtime: bool = True) -> dict[str, str]:
        return {
            "home": str(self.tmp),
            "claude_dir": str(self.tmp / "claude"),
            "opencode_config_dir": str(self.tmp / "opencode"),
            "config_dir": str(self.tmp / "podium"),
            "state_dir": str(self.tmp / "state"),
        }

    def _capture(self, **kw) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = doctor.run(self._paths(), kw.get("config", {}))
        return rc, buf.getvalue()

    def test_python_at_least_38(self) -> None:
        rc, output = self._capture(config={})
        self.assertIn("[OK] python", output)
        # Whether FAIL or not depends on the interpreter actually being >= 3.8;
        # the contract floor is satisfied on every Python we run tests on.
        self.assertIn("python", output)

    def test_clis_present_passes(self) -> None:
        config = {
            "modules": {"rules": True, "executors": True, "codegraph": True, "usage": True},
        }
        rc, output = self._capture(config=config)
        self.assertIn("[OK] claude cli", output)
        self.assertIn("[OK] opencode cli", output)
        self.assertIn("[OK] codegraph cli", output)
        self.assertIn("[OK] usage", output)

    def test_clis_missing_returns_3(self) -> None:
        # Replace PATH with a directory that has no stubs.
        empty = self.tmp / "empty_path"
        empty.mkdir()
        os.environ["PATH"] = str(empty)
        config = {
            "modules": {"rules": True, "executors": True, "codegraph": True},
            "agents": [{"name": "writer", "role": "writer"}],
        }
        rc, output = self._capture(config=config)
        self.assertEqual(rc, 3)
        self.assertIn("[FAIL] claude cli", output)
        self.assertIn("[FAIL] opencode cli", output)
        self.assertIn("[FAIL] codegraph cli", output)

    def test_opencode_optional_for_a_claude_only_roster(self) -> None:
        empty = self.tmp / "empty_path"
        empty.mkdir()
        os.environ["PATH"] = str(empty)
        config = {
            "modules": {"rules": True, "executors": True},
            "roster": [{"id": "principal", "launch": {"kind": "principal"}}],
            "agents": [],
        }
        rc, output = self._capture(config=config)
        self.assertIn("[FAIL] claude cli", output)
        self.assertIn("[OK] opencode cli: not installed", output)

    def test_legacy_hooks_with_podium_plugin_fails(self) -> None:
        config = {
            "modules": {},
            "_legacy_hooks": ["codegraph-gate.py"],
            "_plugins_installed": ["podium-codegraph@podium"],
        }
        rc, output = self._capture(config=config)
        self.assertEqual(rc, 3)
        self.assertIn("[FAIL] hooks", output)

    def test_runtime_json_missing_fails(self) -> None:
        # Default paths point at an empty tmp dir; runtime.json is absent.
        rc, output = self._capture(config={})
        self.assertEqual(rc, 3)
        self.assertIn("[FAIL] runtime.json", output)

    def test_runtime_json_present_passes(self) -> None:
        # Write a valid runtime.json under the config_dir we pass in.
        cfg = Path(self._paths()["config_dir"])
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "runtime.json").write_text('{"schema": 1, "ui": "en"}')
        rc, output = self._capture(config={})
        self.assertIn("[OK] runtime.json", output)

    def test_opencode_json_and_jsonc_emits_warn(self) -> None:
        oc = Path(self._paths()["opencode_config_dir"])
        oc.mkdir(parents=True, exist_ok=True)
        (oc / "opencode.json").write_text("{}")
        (oc / "opencode.jsonc").write_text("{}")
        _, output = self._capture(config={})
        self.assertIn("[WARN] opencode config", output)

    def test_hooks_log_recent_activity_warns(self) -> None:
        state = Path(self._paths()["state_dir"])
        state.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (state / "hooks.log").write_text(f"{stamp} codegraph-gate oops\n")
        _, output = self._capture(config={})
        self.assertIn("[WARN] hooks.log", output)
        self.assertIn("codegraph-gate", output)

    def test_memory_url_reachable_ok(self) -> None:
        server = _StubServer()
        try:
            config = {
                "modules": {"memory": True},
                "memory": {"url": server.url()},
            }
            rc, output = self._capture(config=config)
            self.assertIn("[OK] memory", output)
        finally:
            server.close()

    def test_memory_url_unreachable_warns(self) -> None:
        # Pick a port we are confident is not bound: bind to 0, capture, close.
        probe = _SilentServer()
        probe.close()  # release immediately; client connect() will fail or hang
        config = {
            "modules": {"memory": True},
            "memory": {"url": probe.url()},
        }
        _, output = self._capture(config=config)
        self.assertIn("[WARN] memory", output)


if __name__ == "__main__":
    unittest.main()
