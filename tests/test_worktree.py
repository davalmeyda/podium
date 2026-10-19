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
        self.assertNotIn("codegraph init", out)  # main is not indexed in this fixture

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

    # -- tests edge cases ----------------------------------------------------

    def test_g_deleted_in_worktree_changed_in_main_conflicts(self):
        # Worktree deletes b.txt while main has uncommitted edits to b.txt.
        # `git stash create` snapshots the edit so the base = edited b.txt;
        # main's later edit is the "changed" side and the worktree drops the
        # file, hence the deleted/changed conflict.
        code, _out, err = self.call_script("create", "gamma1")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma1")
        # Main edits b.txt AFTER create so the edit does not end up in the base.
        (self.repo / "b.txt").write_text("b-main-changed\n", encoding="utf-8")
        head_before = self.head()
        (wt / "b.txt").unlink()

        code, out, err = self.call_script("integrate", "gamma1")
        self.assertEqual(code, 2, err)
        self.assertIn("CONFLICT (deleted in worktree, changed in main): b.txt", out)
        # main's b.txt is kept with main's content.
        self.assertTrue((self.repo / "b.txt").exists())
        self.assertEqual((self.repo / "b.txt").read_text(encoding="utf-8"),
                         "b-main-changed\n")
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")

    def test_g2_deleted_in_worktree_untouched_in_main(self):
        # Worktree deletes b.txt; main has not touched it. The merge removes
        # the file from main and prints `deleted: b.txt`.
        code, _out, err = self.call_script("create", "gamma2")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma2")
        head_before = self.head()
        (wt / "b.txt").unlink()

        code, out, err = self.call_script("integrate", "gamma2")
        self.assertEqual(code, 0, err)
        self.assertIn("deleted: b.txt", out)
        self.assertFalse((self.repo / "b.txt").exists())
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")

    def test_g3_changed_in_worktree_deleted_in_main_conflicts(self):
        # Worktree edits c.txt; main deletes c.txt AFTER create. The script
        # places the worktree's content next to main as `c.txt.worktree` and
        # reports a deleted/changed conflict from the worktree's perspective.
        code, _out, err = self.call_script("create", "gamma3")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma3")
        (wt / "c.txt").write_text("c-wt-edited\n", encoding="utf-8")
        head_before = self.head()
        (self.repo / "c.txt").unlink()

        code, out, err = self.call_script("integrate", "gamma3")
        self.assertEqual(code, 2, err)
        self.assertIn("CONFLICT (changed in worktree, deleted in main): c.txt", out)
        # c.txt is absent in main, the worktree copy sits next to the path.
        self.assertFalse((self.repo / "c.txt").exists())
        self.assertTrue((self.repo / "c.txt.worktree").exists())
        self.assertEqual((self.repo / "c.txt.worktree").read_text(encoding="utf-8"),
                         "c-wt-edited\n")
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")

    def test_g4_rename_in_worktree_with_main_edit_conflicts(self):
        # Worktree deletes a.txt and creates a2.txt with the same content
        # (a git-style rename). Main edits a.txt AFTER create. With
        # `--no-renames` git reports a delete of a.txt and an add of a2.txt;
        # main's edit makes a.txt a deleted/changed conflict.
        code, _out, err = self.call_script("create", "gamma4")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma4")
        (self.repo / "a.txt").write_text("region1\nmain-edit\nshared\n",
                                        encoding="utf-8")
        head_before = self.head()
        # Git-style rename: drop a.txt, add a2.txt with the same content.
        (wt / "a.txt").unlink()
        (wt / "a2.txt").write_text("region1\nmain\nshared\n",
                                   encoding="utf-8")

        code, out, err = self.call_script("integrate", "gamma4")
        self.assertEqual(code, 2, err)
        self.assertIn("CONFLICT (deleted in worktree, changed in main): a.txt", out)
        self.assertIn("new: a2.txt", out)
        # Main keeps its edit on a.txt; a2.txt materialises from the worktree.
        self.assertTrue((self.repo / "a.txt").exists())
        self.assertEqual((self.repo / "a.txt").read_text(encoding="utf-8"),
                         "region1\nmain-edit\nshared\n")
        self.assertTrue((self.repo / "a2.txt").exists())
        self.assertEqual((self.repo / "a2.txt").read_text(encoding="utf-8"),
                         "region1\nmain\nshared\n")
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")

    def test_g5_binary_one_sided_change(self):
        # Commit a binary file with NUL bytes only for this test; main stays
        # untouched, the worktree replaces the bytes. `matches_base` is true on
        # the main side, so the merge copies the worktree bytes into main.
        bin_bytes = b"\x00bin\x00side\x00v1\n"
        alt_bytes = b"\x00bin\x00side\x00v2\n"
        (self.repo / "bin.dat").write_bytes(bin_bytes)
        _git(self.env, "add", "bin.dat", cwd=self.repo)
        _git(self.env, "commit", "-qm", "add binary", cwd=self.repo)

        code, _out, err = self.call_script("create", "gamma5")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma5")
        (wt / "bin.dat").write_bytes(alt_bytes)
        head_before = self.head()

        code, out, err = self.call_script("integrate", "gamma5")
        self.assertEqual(code, 0, err)
        self.assertIn("merged: bin.dat", out)
        self.assertEqual((self.repo / "bin.dat").read_bytes(), alt_bytes)
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")

    def test_g6_tracked_symlink_repointed_in_worktree(self):
        # Tracked symlink `link` points at a.txt; the worktree repoints it at
        # b.txt while main is untouched. The integrate must rewrite the
        # symlink in main without touching a.txt through the link.
        (self.repo / "link").symlink_to("a.txt")
        _git(self.env, "add", "link", cwd=self.repo)
        _git(self.env, "commit", "-qm", "add symlink", cwd=self.repo)
        a_before = (self.repo / "a.txt").read_text(encoding="utf-8")

        code, _out, err = self.call_script("create", "gamma6")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma6")
        # Repoint the symlink in the worktree (unlink first, then symlink).
        (wt / "link").unlink()
        (wt / "link").symlink_to("b.txt")
        head_before = self.head()

        code, out, err = self.call_script("integrate", "gamma6")
        self.assertEqual(code, 0, err)
        self.assertIn("merged: link", out)
        # main's link is a symlink to b.txt (not a regular file) and a.txt is
        # untouched -- the merge must not have written through the link.
        self.assertTrue((self.repo / "link").is_symlink())
        self.assertEqual(os.readlink(str(self.repo / "link")), "b.txt")
        self.assertEqual((self.repo / "a.txt").read_text(encoding="utf-8"),
                         a_before)
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")

    def test_g7_executable_bit_only_change_is_carried(self):
        # Worktree toggles only the executable bit on c.txt; the integrate
        # should propagate that mode change to main without a content diff.
        code, _out, err = self.call_script("create", "gamma7")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma7")
        wt_c = wt / "c.txt"
        wt_c.chmod(0o755)
        head_before = self.head()

        code, out, err = self.call_script("integrate", "gamma7")
        self.assertEqual(code, 0, err)
        c_mode = (self.repo / "c.txt").stat().st_mode
        self.assertTrue(c_mode & 0o111, "main's c.txt must be executable")
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")

    def test_g8_paths_with_spaces_and_tab(self):
        # Names with spaces and an embedded TAB character round-trip through
        # the integrate's NUL-delimited raw output and both files land in main.
        space_name = "my file.txt"
        tab_name = "tab\tname.txt"
        (self.repo / space_name).write_text("space-original\n", encoding="utf-8")
        (self.repo / tab_name).write_text("tab-original\n", encoding="utf-8")
        _git(self.env, "add", space_name, tab_name, cwd=self.repo)
        _git(self.env, "commit", "-qm", "add names with space and tab",
             cwd=self.repo)

        code, _out, err = self.call_script("create", "gamma8")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma8")
        head_before = self.head()
        (wt / space_name).write_text("space-wt\n", encoding="utf-8")
        (wt / tab_name).write_text("tab-wt\n", encoding="utf-8")

        code, out, err = self.call_script("integrate", "gamma8")
        self.assertEqual(code, 0, err)
        self.assertIn("merged: %s" % space_name, out)
        self.assertIn("merged: %s" % tab_name, out)
        self.assertEqual((self.repo / space_name).read_text(encoding="utf-8"),
                         "space-wt\n")
        self.assertEqual((self.repo / tab_name).read_text(encoding="utf-8"),
                         "tab-wt\n")
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")

    def test_g9_create_rejects_invalid_task_names(self):
        # `feature/x` carries a slash and `../x` starts with a dot; both must
        # be rejected with exit 1, the canonical message, and no side effects.
        for bad in ("feature/x", "../x"):
            head_before = self.head()
            code, out, err = self.call_script("create", bad)
            self.assertEqual(code, 1, "%s: %s" % (bad, err))
            self.assertIn("task must be a simple name", err)
            # no folder for that name; the sibling `-wt` dir does not exist.
            wt_candidate = self.repo.parent / ("%s-wt" % self.repo.name) / bad
            self.assertFalse(wt_candidate.exists(),
                             "%s must not have created a folder" % bad)
            # no branch with that name.
            _, branches = _git(self.env, "branch", "--list", cwd=self.repo)
            self.assertNotIn("wt/%s" % bad, branches.split())
            self.assertEqual(self.head(), head_before)
            _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
            self.assertEqual(diff, "")

    def test_g10_nested_link_in_link_list(self):
        # `pkg/a/node_modules` is in the link list next to `node_modules`;
        # create links both as symlinks, clean leaves both main folders as
        # real directories with their original content.
        nested = self.repo / "pkg" / "a" / "node_modules"
        nested.mkdir(parents=True)
        (nested / "pkg").write_text("nested-data\n", encoding="utf-8")
        # Both folders are ignored so the integrate never tries to stage them
        # through the (broken) explicit-pathspec path.
        (self.repo / ".gitignore").write_text("node_modules\n.env\n",
                                              encoding="utf-8")
        _git(self.env, "add", ".gitignore", cwd=self.repo)
        _git(self.env, "commit", "-qm", "ignore node_modules without slash",
             cwd=self.repo)
        self.env["PODIUM_WORKTREE_LINKS"] = "node_modules pkg/a/node_modules"

        code, _out, err = self.call_script("create", "gamma10")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma10")
        self.assertTrue((wt / "node_modules").is_symlink())
        self.assertEqual(os.readlink(str(wt / "node_modules")),
                         str(self.repo / "node_modules"))
        nested_link = wt / "pkg" / "a" / "node_modules"
        self.assertTrue(nested_link.is_symlink())
        self.assertEqual(os.readlink(str(nested_link)), str(nested))

        code, out, err = self.call_script("clean", "gamma10")
        self.assertEqual(code, 0, err)
        self.assertIn("leftovers: worktrees=0 branches=0 folder=no", out)
        # main's two folders are real dirs again and keep their content.
        self.assertTrue((self.repo / "node_modules").is_dir())
        self.assertFalse((self.repo / "node_modules").is_symlink())
        self.assertEqual((self.repo / "node_modules" / "pkg").read_text(
            encoding="utf-8"), "data\n")
        self.assertTrue(nested.is_dir())
        self.assertFalse(nested.is_symlink())
        self.assertEqual((nested / "pkg").read_text(encoding="utf-8"),
                         "nested-data\n")

    def test_g11_integrate_output_omits_node_modules(self):
        # node_modules is gitignored, so the integrate's diff never lists it
        # even though both worktrees point at the same real folder through a
        # symlink.
        head_before = self.head()
        code, _out, err = self.call_script("create", "gamma11a")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma11a")
        (wt / "d.txt").write_text("d\n", encoding="utf-8")
        code, out, err = self.call_script("integrate", "gamma11a")
        self.assertEqual(code, 0, err)
        self.assertIn("new: d.txt", out)
        self.assertNotIn("node_modules", out)
        self.assertEqual(self.head(), head_before)
        _, diff = _git(self.env, "diff", "--cached", cwd=self.repo)
        self.assertEqual(diff, "")

    def test_g11b_create_hints_codegraph_only_when_index_present(self):
        # Sub-case A: no .codegraph in main -> no `next:` hint.
        code, out_a, err = self.call_script("create", "gamma11b")
        self.assertEqual(code, 0, err)
        self.assertNotIn("next: codegraph init", out_a)
        # Sub-case B: .codegraph in main -> the hint appears with the worktree
        # path so the executor can index it before working there.
        (self.repo / ".codegraph").mkdir()
        code, out_b, err = self.call_script("create", "gamma11c")
        self.assertEqual(code, 0, err)
        self.assertIn("next: codegraph init", out_b)

    def test_g12_clean_removes_a_locked_worktree(self):
        # `git worktree lock` would normally block `worktree remove`; the
        # script passes `--force --force` so even a locked worktree disappears
        # and the leftovers line is all zero.
        code, _out, err = self.call_script("create", "gamma12")
        self.assertEqual(code, 0, err)
        wt = self.wt_path("gamma12")
        code, out = _git(self.env, "worktree", "lock", str(wt), cwd=self.repo)
        self.assertEqual(code, 0, out)

        code, out, err = self.call_script("clean", "gamma12")
        self.assertEqual(code, 0, err)
        self.assertFalse(wt.exists())
        self.assertIn("leftovers: worktrees=0 branches=0 folder=no", out)


if __name__ == "__main__":
    unittest.main()
