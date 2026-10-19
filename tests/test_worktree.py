"""`podium worktree create|integrate|clean` end-to-end (stdlib only).

Builds throwaway git repos in a temp dir, calls the shell script directly or through the
CLI, and inspects the main checkout afterwards. The throwaway repos never touch the
host's git config: every `git init` here is followed by a `git -c` config command that
stays inside the repo, and we never call git outside that repo.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ``podium.cli`` is optional: tests that exercise the script directly do not need it.
# The CLI-backed tests import it lazily inside the runner so a half-written neighbouring
# module does not block the whole class.

SCRIPT = REPO / "scripts" / "worktree.sh"


def _git(env, *args, cwd=None):
    proc = subprocess.run(["git"] + list(args), env=env, cwd=str(cwd) if cwd else None,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _have_git_bash():
    try:
        with open("/dev/null"):
            pass
    except OSError:
        return False
    if shutil.which("git") is None or shutil.which("bash") is None:
        return False
    try:
        subprocess.run(["git", "--version"], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
        subprocess.run(["bash", "-c", "set -euo pipefail; true"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


@unittest.skipUnless(_have_git_bash(), "git and bash required")
class WorktreeTest(unittest.TestCase):
    """End-to-end coverage of `scripts/worktree.sh` and the `podium worktree` CLI."""

    maxDiff = None

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="podium-wt-"))
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.state_dir = self.root / "state"
        self.state_dir.mkdir()
        # The repo sits in a sibling dir so we can test `../<repo>-wt/<task>`.
        self.repo = self.root / "demo"
        self.repo.mkdir()
        self.env = {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PODIUM_STATE_DIR": str(self.state_dir),
            "PODIUM_CONFIG_DIR": str(self.root / "config"),
        }
        self._init_repo()

    # -- fixtures ------------------------------------------------------------

    def _init_repo(self):
        env = self.env
        code, out = _git(env, "init", "-q", cwd=self.repo)
        self.assertEqual(code, 0, out)
        code, out = _git(env, "config", "user.name", "Tester", cwd=self.repo)
        self.assertEqual(code, 0, out)
        code, out = _git(env, "config", "user.email", "t@example.test", cwd=self.repo)
        self.assertEqual(code, 0, out)
        # Tracked files: a.txt with two regions for merge testing, b.txt, c.txt.
        (self.repo / "a.txt").write_text("region1\nmain\nshared\n", encoding="utf-8")
        (self.repo / "b.txt").write_text("b\n", encoding="utf-8")
        (self.repo / "c.txt").write_text("c\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("node_modules/\n.env\n", encoding="utf-8")
        code, out = _git(env, "add", "-A", cwd=self.repo)
        self.assertEqual(code, 0, out)
        code, out = _git(env, "commit", "-q", "-m", "initial", cwd=self.repo)
        self.assertEqual(code, 0, out)
        # Real node_modules dir, populated; gitignored but real.
        nm = self.repo / "node_modules"
        nm.mkdir()
        (nm / "pkg").write_text("data\n", encoding="utf-8")

    # -- helpers -------------------------------------------------------------

    def head(self, repo=None):
        repo = Path(repo) if repo else self.repo
        code, out = _git(self.env, "rev-parse", "HEAD", cwd=repo)
        self.assertEqual(code, 0, out)
        return out.strip()

    def stored_base(self, task):
        common_rel = _git(self.env, "rev-parse", "--git-common-dir", cwd=self.repo)[1].strip()
        common = (self.repo / common_rel).resolve()
        return (common / ("wt-base-%s" % task)).read_text(encoding="utf-8").strip()

    def wt_path(self, task):
        return self.repo.parent / ("%s-wt" % self.repo.name) / task

    def branch(self, task):
        return "wt/%s" % task

    def call_script(self, action, task, *files):
        proc = subprocess.run([str(shutil.which("bash")), str(SCRIPT), action,
                               str(self.repo), task, *files],
                              env=self.env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=False)
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")

    def call_cli(self, *argv):
        # Call main() in-process so we can inject env + podium_home; per the brief this
        # is one of the supported ways to invoke the CLI from a test.
        import contextlib
        import io
        from podium import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv), env=self.env, podium_home=REPO)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def porcelain(self, repo=None):
        repo = Path(repo) if repo else self.repo
        _, out = _git(self.env, "status", "--porcelain", cwd=repo)
        return out

    # -- tests (a) -----------------------------------------------------------

    def test_a_create_preserves_main_and_links_node_modules(self):
        # Uncommitted change in main + an untracked file passed as `files`.
        (self.repo / "a.txt").write_text("region1\nmain-edited\nshared\n", encoding="utf-8")
        (self.repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
        head_before = self.head()
        status_before = self.porcelain()

        code, out, err = self.call_script("create", "alpha", ".env")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("alpha")
        self.assertTrue(wt.is_dir(), "worktree folder missing")
        self.assertEqual((wt / "a.txt").read_text(encoding="utf-8"),
                         "region1\nmain-edited\nshared\n")
        self.assertEqual((wt / ".env").read_text(encoding="utf-8"), "SECRET=1\n")
        nm_link = wt / "node_modules"
        self.assertTrue(nm_link.is_symlink(), "node_modules must be a symlink")
        self.assertEqual(os.readlink(str(nm_link)), str(self.repo / "node_modules"))
        # Main is untouched.
        self.assertEqual(self.head(), head_before)
        self.assertEqual(self.porcelain(), status_before)
        self.assertIn("next: codegraph init", out)

        # Stored base file sits in the git common dir.
        common_rel = _git(self.env, "rev-parse", "--git-common-dir", cwd=self.repo)[1].strip()
        common = (self.repo / common_rel).resolve()
        meta = common / "wt-base-alpha"
        self.assertTrue(meta.is_file())
        # branch wt/alpha exists.
        _, branches = _git(self.env, "branch", "--list", cwd=self.repo)
        self.assertIn("wt/alpha", branches)

    # -- tests (b) -----------------------------------------------------------

    def test_b_integrate_merges_non_overlapping_edits(self):
        # Main edits a.txt region 2 (uncommitted), then worktree edits region 1,
        # deletes b.txt, and adds d.txt. Every change lives in a different region.
        (self.repo / "a.txt").write_text("region1\nmain-region2\nshared\n", encoding="utf-8")
        head_before = self.head()
        code, _out, err = self.call_script("create", "beta")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("beta")

        (wt / "a.txt").write_text("wt-region1\nmain-region2\nshared\n", encoding="utf-8")
        (wt / "b.txt").unlink()
        (wt / "d.txt").write_text("d\n", encoding="utf-8")
        # The integrate stage does its own `git add -A`; calling it here would
        # accidentally stage the symlinked dependency directory before the
        # ``':!node_modules'`` exclusion runs.

        code, out, err = self.call_script("integrate", "beta")
        self.assertEqual(code, 0, err)
        self.assertIn("merged: a.txt", out)
        self.assertIn("new: d.txt", out)
        self.assertIn("deleted: b.txt", out)
        self.assertIn("clean integration", out)

        self.assertEqual((self.repo / "a.txt").read_text(encoding="utf-8"),
                         "wt-region1\nmain-region2\nshared\n")
        self.assertFalse((self.repo / "b.txt").exists())
        self.assertEqual((self.repo / "d.txt").read_text(encoding="utf-8"), "d\n")
        # Main HEAD unchanged + no new commits in the index.
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")
        # Worktree's branch tip is still the base (stash commit or HEAD); the integrate
        # path never commits anything, so no commit was created beyond that.
        self.assertEqual(self.head(repo=wt), self.stored_base("beta"))

    def test_b2_integrate_when_gitignore_matches_the_link_itself(self):
        # `node_modules` without a slash also ignores the symlink: an explicit
        # exclude pathspec for it would make `git add` fail.
        (self.repo / ".gitignore").write_text("node_modules\n.env\n", encoding="utf-8")
        _git(self.env, "add", ".gitignore", cwd=self.repo)
        _git(self.env, "commit", "-qm", "ignore without slash", cwd=self.repo)
        code, _out, err = self.call_script("create", "slash")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("slash")
        self.assertTrue((wt / "node_modules").is_symlink())
        (wt / "d.txt").write_text("d\n", encoding="utf-8")

        code, out, err = self.call_script("integrate", "slash")
        self.assertEqual(code, 0, err)
        self.assertIn("new: d.txt", out)
        self.assertNotIn("node_modules", out)
        self.assertTrue((self.repo / "node_modules").is_dir())
        self.assertFalse((self.repo / "node_modules").is_symlink())

    # -- tests (c) -----------------------------------------------------------

    def test_c_integrate_conflict_marks_main_file(self):
        # To get a real conflict, main must edit `a.txt` AFTER the worktree is created
        # — otherwise `git stash create` snapshots its edit into the base and the merge
        # collapses to a one-sided change.
        code, _out, err = self.call_script("create", "gamma")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma")
        # Main and worktree both flip line 2 of a.txt, on top of the same HEAD base.
        (self.repo / "a.txt").write_text("region1\nmain-new\nshared\n", encoding="utf-8")
        (wt / "a.txt").write_text("region1\nwt-new\nshared\n", encoding="utf-8")

        code, out, err = self.call_script("integrate", "gamma")
        self.assertEqual(code, 2, err)
        self.assertIn("CONFLICT: a.txt", out)
        body = (self.repo / "a.txt").read_text(encoding="utf-8")
        self.assertIn("<<<<<<< main", body)
        self.assertIn(">>>>>>> worktree", body)

    # -- tests (d) -----------------------------------------------------------

    def test_d_integrate_creates_worktree_copy_for_dual_add(self):
        # Same path added on both sides with different content.
        code, _out, err = self.call_script("create", "delta")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("delta")
        # Main already has e.txt (untracked, fine): reference checks `cmp -s` against disk.
        (self.repo / "e.txt").write_text("main-side\n", encoding="utf-8")
        (wt / "e.txt").write_text("wt-side\n", encoding="utf-8")

        code, out, err = self.call_script("integrate", "delta")
        self.assertEqual(code, 2, err)
        self.assertIn("CONFLICT (created on both sides): e.txt", out)
        self.assertEqual((self.repo / "e.txt").read_text(encoding="utf-8"), "main-side\n")
        self.assertEqual((self.repo / "e.txt.worktree").read_text(encoding="utf-8"), "wt-side\n")

    # -- tests (e) -----------------------------------------------------------

    def test_e_clean_removes_everything_and_prints_leftovers(self):
        # Seed a decisions file with one entry to remove and one to keep.
        decisions_path = self.state_dir / "codegraph-decisions.json"
        decisions_path.write_text(json.dumps({
            "decisions": {
                str(self.wt_path("epsilon")): {"foo": 1},
                "/elsewhere": {"bar": 2},
            },
        }), encoding="utf-8")

        code, _out, err = self.call_script("create", "epsilon")
        self.assertEqual(code, 0, err)
        self.assertTrue(self.wt_path("epsilon").exists())

        code, out, err = self.call_script("clean", "epsilon")
        self.assertEqual(code, 0, err)
        self.assertFalse(self.wt_path("epsilon").exists())
        self.assertFalse((self.repo.parent / ("%s-wt" % self.repo.name)).exists())
        _, branches = _git(self.env, "branch", "--list", cwd=self.repo)
        self.assertNotIn("wt/epsilon", branches)
        common_rel = _git(self.env, "rev-parse", "--git-common-dir", cwd=self.repo)[1].strip()
        common = (self.repo / common_rel).resolve()
        self.assertFalse((common / "wt-base-epsilon").exists())
        # main's node_modules is intact and not a symlink.
        self.assertTrue((self.repo / "node_modules").is_dir())
        self.assertFalse((self.repo / "node_modules").is_symlink())
        self.assertEqual((self.repo / "node_modules" / "pkg").read_text(encoding="utf-8"), "data\n")
        # decisions: epsilon entry gone, /elsewhere stays.
        doc = json.loads(decisions_path.read_text(encoding="utf-8"))
        self.assertNotIn(str(self.wt_path("epsilon")), doc["decisions"])
        self.assertIn("/elsewhere", doc["decisions"])
        self.assertIn("leftovers: worktrees=0 branches=0 folder=no", out)

    # -- tests (f) -----------------------------------------------------------

    def test_f_cli_rejects_files_with_integrate(self):
        # Drive the CLI directly: `files` with `integrate` must exit non-zero and create nothing.
        before_head = self.head()
        code, out, err = self.call_cli("worktree", "integrate", str(self.repo), "zeta", "extra")
        self.assertIn(code, (1, 2), err)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.head(), before_head)
        self.assertFalse(self.wt_path("zeta").exists())

    def test_cli_create_runs_the_script(self):
        # Cover the CLI path at least once end-to-end.
        code, out, err = self.call_cli("worktree", "create", str(self.repo), "eta")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("eta")
        self.assertTrue(wt.is_dir())
        # node_modules is symlinked through the same link list (default).
        self.assertTrue((wt / "node_modules").is_symlink())
        self.assertEqual(os.readlink(str(wt / "node_modules")),
                         str(self.repo / "node_modules"))


if __name__ == "__main__":
    unittest.main()
