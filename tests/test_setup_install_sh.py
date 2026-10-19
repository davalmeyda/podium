"""Tests for ``install.sh`` (ARCHITECTURE.md §3, §11).

This is the only test that uses ``git``: it spins up a bare repo and the
working checkout inside a temp directory, then drives ``install.sh`` via
``PODIUM_REPO_URL`` and ``HOME``.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_bare_repo(path: Path) -> None:
    """Initialise a bare git repo at ``path`` with an empty initial commit.

    The fixture must contain ``bin/podium`` so install.sh's link step finds a
    real target (we do not exercise the actual CLI, only the symlink).
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(path)],
        check=True,
        capture_output=True,
    )

    # Seed a working copy that pushes main so the bare repo has history.
    work = path.parent / f"{path.name}-seed"
    work.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "podium",
        "GIT_AUTHOR_EMAIL": "podium@example.invalid",
        "GIT_COMMITTER_NAME": "podium",
        "GIT_COMMITTER_EMAIL": "podium@example.invalid",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    def run(*args):
        return subprocess.run(args, cwd=str(work), env=env, check=True, capture_output=True)
    run("git", "init", "--initial-branch=main")
    (work / "bin").mkdir()
    (work / "bin" / "podium").write_text("#!/bin/sh\necho podium-fixture\n")
    (work / "bin" / "podium").chmod(0o755)
    (work / "install.sh").write_text("#!/bin/sh\necho placeholder\n")
    run("git", "add", "bin/podium", "install.sh")
    run("git", "commit", "-m", "init")
    run("git", "remote", "add", "origin", str(path))
    run("git", "push", "-u", "origin", "main")


def _make_exec(path: Path) -> None:
    """chmod +x via shell so we don't depend on umask or the calling OS."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class InstallShTests(unittest.TestCase):
    """Drive install.sh against a local bare repo and assert the symlink."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="podium-install-"))

        # Fixture repository (the only place git is allowed in this task).
        self.bare = self.tmp / "remote.git"
        _make_bare_repo(self.bare)

        # Fake HOME: install.sh writes $HOME/.local/share/podium/repo and
        # $HOME/.local/bin/podium beneath it.
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()

        # Use the install.sh from the repo under test verbatim.
        self.install_sh = REPO_ROOT / "install.sh"
        self.assertTrue(self.install_sh.is_file(), self.install_sh)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _drive(self, *extra_env: tuple[str, str]) -> None:
        env = {
            **os.environ,
            "HOME": str(self.fake_home),
            "PODIUM_REPO_URL": str(self.bare),
            "PODIUM_REF": "main",
            # Force tooling checks: rely on the system PATH; install.sh
            # only needs python3 and git which every CI host has.
        }
        for key, value in extra_env:
            env[key] = value
        completed = subprocess.run(
            ["sh", str(self.install_sh)],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"install.sh failed:\nstdout={completed.stdout}\nstderr={completed.stderr}",
        )

    def test_install_succeeds_against_local_repo(self) -> None:
        self._drive()
        checkout = self.fake_home / ".local" / "share" / "podium" / "repo"
        link = self.fake_home / ".local" / "bin" / "podium"
        self.assertTrue(checkout.is_dir(), checkout)
        self.assertTrue(link.is_symlink(), link)
        target = os.readlink(link)
        self.assertTrue(target.endswith("bin/podium"), target)

    def test_install_idempotent_on_second_run(self) -> None:
        # First run creates; second run must refresh without error.
        self._drive()
        checkout = self.fake_home / ".local" / "share" / "podium" / "repo"
        self.assertTrue(checkout.is_dir())
        self._drive()
        self.assertTrue(checkout.is_dir())

    def test_install_handles_existing_checkout(self) -> None:
        # Pre-create the destination so install.sh takes the update branch.
        checkout = self.fake_home / ".local" / "share" / "podium" / "repo"
        checkout.mkdir(parents=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", str(self.bare), str(checkout)],
            check=True,
            capture_output=True,
        )
        self._drive()
        # After the update, the bin/podium fixture must be present.
        self.assertTrue((checkout / "bin" / "podium").is_file())

    def test_syntax_clean(self) -> None:
        completed = subprocess.run(
            ["sh", "-n", str(self.install_sh)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
