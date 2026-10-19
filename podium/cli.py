"""podium command line (ARCHITECTURE.md section 11).

Exit codes: 0 ok, 1 user/config error, 2 conflict (foreign or modified file), 3 environment error.
"""
from __future__ import annotations

import argparse
import dataclasses
import difflib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from podium import __version__
from podium import config as config_mod
from podium import migrate as migrate_mod
from podium import paths as paths_mod
from podium import render as render_mod
from podium import state, targets

EXIT_OK, EXIT_USER, EXIT_CONFLICT, EXIT_ENV = 0, 1, 2, 3


class _Parser(argparse.ArgumentParser):
    """argparse exits with 2 on usage errors; podium reserves 2 for conflicts, so use 1."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("%s: error: %s\n" % (self.prog, message))
        raise SystemExit(EXIT_USER)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="podium", description="Install and manage the podium agent-orchestration toolkit.")
    parser.add_argument("--version", action="version", version="podium %s" % __version__)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    p = sub.add_parser("detect", help="read-only environment detection")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = sub.add_parser("init", help="create podium.toml (wizard or answers file)")
    p.add_argument("--non-interactive", action="store_true", help="never prompt")
    p.add_argument("--answers", metavar="FILE", help="JSON answers file")

    p = sub.add_parser("install", help="render and write everything")
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    p.add_argument("--adopt", action="store_true", help="take over foreign files (backup first)")
    p.add_argument("--force", action="store_true", help="overwrite files edited since podium wrote them (backup first)")
    p.add_argument("--modules", metavar="a,b", help="only act on these modules")

    p = sub.add_parser("render", help="render targets to stdout or a directory")
    p.add_argument("--target", metavar="ID")
    p.add_argument("--out", metavar="DIR")

    p = sub.add_parser("diff", help="diff rendered output against what is on disk")
    p.add_argument("--target", metavar="ID")

    p = sub.add_parser("migrate", help="migrate a hand-written setup")
    p.add_argument("--dry-run", action="store_true")

    sub.add_parser("doctor", help="check the environment and the install")

    p = sub.add_parser("uninstall", help="remove what podium wrote")
    p.add_argument("--dry-run", action="store_true")

    sub.add_parser("update", help="pull the checkout and re-run install")
    return parser


# --------------------------------------------------------------------------- helpers

def _err(message: str) -> None:
    sys.stderr.write("podium: %s\n" % message)


def _paths(env: Mapping[str, str], podium_home: Optional[Path]) -> paths_mod.Paths:
    resolved = paths_mod.resolve(env)
    if podium_home is not None:
        resolved = dataclasses.replace(resolved, podium_home=Path(podium_home))
    return resolved


def _import(name: str) -> Any:
    try:
        return importlib.import_module("podium.%s" % name)
    except ImportError as exc:
        raise targets.EnvError("module podium.%s is not available: %s" % (name, exc))


def _human(value: Any, indent: int = 0) -> List[str]:
    pad = "  " * indent
    lines: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append("%s%s:" % (pad, key))
                lines.extend(_human(item, indent + 1))
            else:
                lines.append("%s%s: %s" % (pad, key, json.dumps(item) if isinstance(item, (dict, list)) else item))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append("%s-" % pad)
                lines.extend(_human(item, indent + 1))
            else:
                lines.append("%s- %s" % (pad, item))
    else:
        lines.append("%s%s" % (pad, value))
    return lines


# --------------------------------------------------------------------------- commands

def _paths_mapping(paths: paths_mod.Paths) -> dict:
    """detect/doctor take a plain mapping of the resolved paths."""
    return {field.name: getattr(paths, field.name) for field in dataclasses.fields(paths)}


def cmd_detect(args: argparse.Namespace, paths: paths_mod.Paths, env: Mapping[str, str]) -> int:
    report = _import("detect").run(_paths_mapping(paths))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("\n".join(_human(report)))
    return EXIT_OK


def cmd_init(args: argparse.Namespace, paths: paths_mod.Paths, env: Mapping[str, str]) -> int:
    answers = None
    if args.answers:
        try:
            with open(args.answers, "r", encoding="utf-8") as handle:
                answers = json.load(handle)
        except (OSError, ValueError) as exc:
            _err("cannot read answers file %s: %s" % (args.answers, exc))
            return EXIT_USER
        if not isinstance(answers, dict):
            _err("answers file %s must contain a JSON object" % args.answers)
            return EXIT_USER
    interactive = (not args.non_interactive) and answers is None and sys.stdin.isatty()
    # init's "home" is the podium checkout (it reads presets from there).
    init_paths = {"home": paths.podium_home, "config_dir": paths.config_dir, "state_dir": paths.state_dir}
    init_mod = _import("init")
    try:
        written = init_mod.run(init_paths, answers, interactive=interactive)
    except getattr(init_mod, "InitError", ()) as exc:
        _err("error: %s" % exc)
        return EXIT_USER
    print("wrote %s" % written)
    return EXIT_OK


def cmd_install(args: argparse.Namespace, paths: paths_mod.Paths, env: Mapping[str, str]) -> int:
    config = config_mod.load(paths.config_dir, env)
    modules = [m.strip() for m in args.modules.split(",") if m.strip()] if args.modules else None

    def plan(ledger: state.Ledger) -> List[targets.Step]:
        ctx = targets.Ctx(ledger, adopt=args.adopt, force=args.force)
        return targets.build_install_steps(paths, config, ctx, env, modules, paths.podium_home)

    if args.dry_run:
        steps = plan(state.Ledger.load(paths.state_dir))
        for step in steps:
            print(step.line())
        if targets.has_conflicts(steps):
            print("dry-run: install would be refused (conflicts above); nothing written")
            return EXIT_CONFLICT
        print("dry-run: nothing written")
        return EXIT_OK

    with state.lock(paths.state_dir):
        steps = plan(state.Ledger.load(paths.state_dir))
        if targets.has_conflicts(steps):
            for step in steps:
                print(step.line())
            _err("install refused: conflicts found; nothing was written")
            return EXIT_CONFLICT
        targets.apply_steps(steps)
    return EXIT_OK


def cmd_uninstall(args: argparse.Namespace, paths: paths_mod.Paths, env: Mapping[str, str]) -> int:
    def run(ledger: state.Ledger, write: bool) -> int:
        steps = targets.build_uninstall_steps(paths, targets.Ctx(ledger), env)
        if not write:
            for step in steps:
                print(step.line())
            print("dry-run: nothing written")
            return EXIT_CONFLICT if targets.has_conflicts(steps) else EXIT_OK
        if targets.has_conflicts(steps):
            for step in steps:
                print(step.line())
            _err("uninstall refused: conflicts found; nothing was removed")
            return EXIT_CONFLICT
        targets.apply_steps(steps)
        if ledger.is_empty():
            ledger.delete()
        return EXIT_OK

    if args.dry_run:
        return run(state.Ledger.load(paths.state_dir), write=False)
    with state.lock(paths.state_dir):
        return run(state.Ledger.load(paths.state_dir), write=True)


def cmd_render(args: argparse.Namespace, paths: paths_mod.Paths, env: Mapping[str, str]) -> int:
    config = config_mod.load(paths.config_dir, env)
    ids = [args.target] if args.target else render_mod.target_ids(paths.podium_home)
    texts = [(t, render_mod.render_target(t, config, paths.podium_home, paths.config_dir)) for t in ids]
    if args.out:
        out_dir = Path(args.out)
        for target_id, text in texts:
            state.atomic_write(out_dir / ("%s.md" % target_id), text)
            print("wrote %s" % (out_dir / ("%s.md" % target_id)))
        return EXIT_OK
    for target_id, text in texts:
        if len(texts) > 1:
            print("<!-- podium render: %s -->" % target_id)
        sys.stdout.write(text)
    return EXIT_OK


def cmd_diff(args: argparse.Namespace, paths: paths_mod.Paths, env: Mapping[str, str]) -> int:
    config = config_mod.load(paths.config_dir, env)
    changed = False
    for label, path, rendered, current in targets.rendered_for_diff(paths, config, paths.podium_home, args.target):
        if current == rendered:
            print("%s: up to date (%s)" % (label, path))
            continue
        changed = True
        old = (current or "").splitlines(True)
        new = rendered.splitlines(True)
        name = "%s (%s)" % (label, path)
        sys.stdout.writelines(difflib.unified_diff(
            old, new, fromfile="%s [on disk]" % name if current is not None else "/dev/null",
            tofile="%s [rendered]" % name))
        if not new or not new[-1].endswith("\n"):
            print()
    if not changed:
        print("no differences")
    return EXIT_OK


def cmd_migrate(args: argparse.Namespace, paths: paths_mod.Paths, env: Mapping[str, str]) -> int:
    try:
        return migrate_mod.run(paths, dry_run=args.dry_run)
    except migrate_mod.MigrateError as exc:
        _err(str(exc))
        return EXIT_USER


def cmd_doctor(args: argparse.Namespace, paths: paths_mod.Paths, env: Mapping[str, str]) -> int:
    config = config_mod.load(paths.config_dir, env)
    return int(_import("doctor").run(_paths_mapping(paths), config))


def _git(git: str, home: Path, *args: str, env: Mapping[str, str]) -> Tuple[int, str]:
    try:
        proc = subprocess.run([git, "-C", str(home)] + list(args), env=dict(env),
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise targets.EnvError("git %s failed: %s" % (args[0], exc))
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def _latest_release(git: str, home: Path, env: Mapping[str, str]) -> Optional[str]:
    """Highest vMAJOR.MINOR.PATCH tag on origin, or None when nothing is released."""
    code, out = _git(git, home, "ls-remote", "--tags", "--refs", "origin", "v*", env=env)
    if code != 0:
        raise targets.EnvError("cannot list release tags: %s" % out)
    best: Optional[Tuple[int, int, int]] = None
    for line in out.splitlines():
        match = re.search(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$", line)
        if match:
            version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            best = version if best is None or version > best else best
    return "v%d.%d.%d" % best if best else None


def cmd_update(args: argparse.Namespace, paths: paths_mod.Paths, env: Mapping[str, str]) -> int:
    """Move the checkout to PODIUM_REF (default: latest release, else main), as install.sh does."""
    home = paths.podium_home
    if not (home / ".git").exists():
        raise targets.EnvError("%s is not a git checkout; update it manually" % home)
    git = shutil.which("git", path=env.get("PATH", os.defpath))
    if git is None:
        raise targets.EnvError("git is not installed")
    ref = env.get("PODIUM_REF") or _latest_release(git, home, env) or "main"
    for step in (("fetch", "--depth", "1", "--tags", "origin", ref),
                 ("checkout", "--quiet", "--detach", "FETCH_HEAD")):
        code, out = _git(git, home, *step, env=env)
        if out:
            print(out)
        if code != 0:
            raise targets.EnvError("git %s exited with %d" % (step[0], code))
    print("podium checkout at %s" % ref)
    # Run the freshly checked-out CLI: this process still holds the old code.
    launcher = home / "bin" / "podium"
    if launcher.is_file():
        return subprocess.run([sys.executable, str(launcher), "install"], env=dict(env)).returncode
    install_args = argparse.Namespace(dry_run=False, adopt=False, force=False, modules=None)
    return cmd_install(install_args, paths, env)


COMMANDS = {
    "detect": cmd_detect,
    "init": cmd_init,
    "install": cmd_install,
    "render": cmd_render,
    "diff": cmd_diff,
    "migrate": cmd_migrate,
    "doctor": cmd_doctor,
    "uninstall": cmd_uninstall,
    "update": cmd_update,
}


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None,
         podium_home: Optional[Path] = None) -> int:
    """Run the CLI. `env` and `podium_home` exist so tests can point it at a temp tree."""
    if env is None:
        env = os.environ
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        paths = _paths(env, podium_home)
        return COMMANDS[args.command](args, paths, env)
    except (config_mod.ConfigError, render_mod.RenderError) as exc:
        _err("error: %s" % exc)
        return EXIT_USER
    except targets.Conflict as exc:
        _err("conflict: %s" % exc)
        return EXIT_CONFLICT
    except (targets.EnvError, state.StateError) as exc:
        _err("environment error: %s" % exc)
        return EXIT_ENV
    except targets.TargetError as exc:
        _err("error: %s" % exc)
        return EXIT_USER
    except OSError as exc:
        _err("environment error: %s" % exc)
        return EXIT_ENV
    except KeyboardInterrupt:
        _err("interrupted")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
