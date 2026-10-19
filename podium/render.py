"""Rendering (ARCHITECTURE.md section 5): fragments, templates and overlays."""
from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from podium import config as config_mod

MANIFEST_RELPATH = Path("rules") / "manifest.toml"
DEFAULT_SOURCE = "rules"
INSERT_FILENAME = "insert.toml"

_EXPR_RE = re.compile(r"\{\{(.*?)\}\}")
_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_-]+)*$")


class RenderError(Exception):
    """A template, manifest or overlay problem."""


# --------------------------------------------------------------------------- manifest

def load_manifest(podium_home: Path) -> List[Dict[str, Any]]:
    """Return the `[[target]]` tables of `rules/manifest.toml`."""
    path = Path(podium_home) / MANIFEST_RELPATH
    if not path.is_file():
        raise RenderError("manifest not found: %s" % path)
    try:
        data = config_mod.load_toml(path)
    except config_mod.ConfigError as exc:
        raise RenderError(str(exc))
    targets = data.get("target", [])
    if not isinstance(targets, list):
        raise RenderError("%s: `target` must be an array of tables" % path)
    for index, target in enumerate(targets):
        if not isinstance(target, dict) or not isinstance(target.get("id"), str):
            raise RenderError("%s: target #%d has no string `id`" % (path, index))
        fragments = target.get("fragments", [])
        if not isinstance(fragments, list):
            raise RenderError("%s: target %s: `fragments` must be an array" % (path, target["id"]))
        for frag in fragments:
            if not isinstance(frag, dict) or not isinstance(frag.get("id"), str):
                raise RenderError("%s: target %s: every fragment needs a string `id`" % (path, target["id"]))
    return targets


def target_ids(podium_home: Path) -> List[str]:
    return [t["id"] for t in load_manifest(podium_home)]


def _find_target(podium_home: Path, target_id: str) -> Dict[str, Any]:
    for target in load_manifest(podium_home):
        if target["id"] == target_id:
            return target
    raise RenderError("unknown target: %s" % target_id)


# --------------------------------------------------------------------------- templates

def _scalar_text(value: Any, dotted: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(_scalar_text(item, dotted) for item in value)
    raise RenderError("`%s` is a table and cannot be rendered as text" % dotted)


def _lookup(config: Mapping[str, Any], dotted: str) -> Any:
    parts = dotted.split(".")
    node: Any = config
    if parts[0] == "vars":  # {{ vars.<key> }} is shorthand for render.vars.<key>
        node = config.get("render", {}).get("vars", {})
        parts = parts[1:]
    for part in parts:
        if not isinstance(node, Mapping) or part not in node:
            raise RenderError("unknown template variable: %s" % dotted)
        node = node[part]
    return node


class _Generated:
    """Lazy `roster.generated(config)` so templates without it never import roster."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self._config = config
        self._data: Optional[Mapping[str, str]] = None

    def get(self, name: str) -> str:
        if self._data is None:
            roster = importlib.import_module("podium.roster")
            self._data = roster.generated(self._config)
        if name not in self._data:
            raise RenderError("unknown generated block: generated.%s" % name)
        return self._data[name]


def render_text(text: str, config: Mapping[str, Any], generated: Optional[_Generated] = None) -> str:
    """Single-pass `{{ path }}` / `{{ generated.x }}` substitution; `{{ "{{" }}` is a literal `{{`."""
    if generated is None:
        generated = _Generated(config)

    def repl(match: "re.Match[str]") -> str:
        expr = match.group(1).strip()
        if expr == '"{{"':
            return "{{"
        if not _PATH_RE.match(expr):
            raise RenderError("invalid template expression: {{ %s }}" % expr)
        if expr.startswith("generated."):
            return generated.get(expr[len("generated."):])
        return _scalar_text(_lookup(config, expr), expr)

    return _EXPR_RE.sub(repl, text)


def _read_text(path: Path) -> str:
    try:
        with open(str(path), "rb") as handle:
            raw = handle.read()
        return raw.decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise RenderError("cannot read %s: %s" % (path, exc))


# --------------------------------------------------------------------------- overlays

def _load_inserts(overlay_dir: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    path = overlay_dir / INSERT_FILENAME
    if not path.is_file():
        return [], []
    try:
        data = config_mod.load_toml(path)
    except config_mod.ConfigError as exc:
        raise RenderError(str(exc))
    for key in data:
        if key not in ("insert", "omit"):
            raise RenderError("%s: unknown key: %s" % (path, key))
    inserts = data.get("insert", [])
    omit = data.get("omit", [])
    if not isinstance(inserts, list) or not isinstance(omit, list):
        raise RenderError("%s: `insert` must be an array of tables and `omit` an array" % path)
    for item in inserts:
        if not isinstance(item, dict) or not isinstance(item.get("file"), str):
            raise RenderError("%s: every [[insert]] needs a string `file`" % path)
        for key in item:
            if key not in ("file", "after", "before"):
                raise RenderError("%s: unknown key in [[insert]]: %s" % (path, key))
        anchors = [k for k in ("after", "before") if k in item]
        if len(anchors) != 1 or not isinstance(item[anchors[0]], str):
            raise RenderError(
                "%s: [[insert]] %s needs exactly one of `after` / `before` (a fragment id)"
                % (path, item["file"])
            )
    if not all(isinstance(i, str) for i in omit):
        raise RenderError("%s: `omit` must be an array of fragment ids" % path)
    return inserts, omit


def render_target(
    target_id: str,
    config: Mapping[str, Any],
    podium_home: Path,
    config_dir: Path,
) -> str:
    """Render one target: manifest fragments (module-filtered) + overlays, joined by blank lines."""
    podium_home = Path(podium_home)
    target = _find_target(podium_home, target_id)
    source = podium_home / target.get("source", DEFAULT_SOURCE)
    overlay_dir = Path(config_dir) / "overlays" / target_id
    modules = config.get("modules", {})

    # Ordered entries: (fragment id, path or None for inserts, enabled)
    entries: List[Dict[str, Any]] = []
    known = set()
    for frag in target.get("fragments", []):
        module = frag.get("module")
        if module is not None and module not in config_mod.MODULES:
            raise RenderError("fragment %s: unknown module: %s" % (frag["id"], module))
        enabled = True if module is None else bool(modules.get(module, False))
        entries.append({"id": frag["id"], "enabled": enabled, "text": None})
        known.add(frag["id"])

    replaced: Dict[str, str] = {}
    omit: List[str] = []
    inserted_files = set()
    if overlay_dir.is_dir():
        inserts, omit = _load_inserts(overlay_dir)
        for frag_id in omit:
            if frag_id not in known:
                raise RenderError("overlay %s: omit references unknown fragment: %s" % (target_id, frag_id))
        for item in inserts:
            inserted_files.add(item["file"])
        for md in sorted(overlay_dir.glob("*.md")):
            frag_id = md.stem
            if md.name in inserted_files:
                continue
            if frag_id not in known:
                raise RenderError(
                    "overlay %s: replaces unknown fragment: %s (no such fragment in the manifest)"
                    % (target_id, frag_id)
                )
            replaced[frag_id] = _read_text(md)
        for item in inserts:
            file_path = overlay_dir / item["file"]
            if not file_path.is_file():
                raise RenderError("overlay %s: insert file not found: %s" % (target_id, file_path))
            anchor_kind = "after" if "after" in item else "before"
            anchor = item[anchor_kind]
            if anchor not in known:
                raise RenderError(
                    "overlay %s: %s anchor references unknown fragment: %s" % (target_id, anchor_kind, anchor)
                )
            new_entry = {"id": "insert:" + item["file"], "enabled": True, "text": _read_text(file_path)}
            index = _index_of(entries, anchor)
            if anchor_kind == "before":
                entries.insert(index, new_entry)
            else:
                # Keep file order among inserts that share the same `after` anchor.
                position = index + 1
                while position < len(entries) and entries[position].get("after_of") == anchor:
                    position += 1
                new_entry["after_of"] = anchor
                entries.insert(position, new_entry)
        omit_set = set(omit)
        entries = [e for e in entries if e["id"] not in omit_set]

    generated = _Generated(config)
    chunks: List[str] = []
    for entry in entries:
        if not entry["enabled"]:
            continue
        if entry["text"] is not None:
            text = entry["text"]
        elif entry["id"] in replaced:
            text = replaced[entry["id"]]
        else:
            frag_path = source / (entry["id"] + ".md")
            if not frag_path.is_file():
                raise RenderError("fragment not found: %s" % frag_path)
            text = _read_text(frag_path)
        text = render_text(text, config, generated).strip("\n")
        if text:
            chunks.append(text)
    return "\n\n".join(chunks) + "\n"


def _index_of(entries: List[Dict[str, Any]], frag_id: str) -> int:
    for index, entry in enumerate(entries):
        if entry["id"] == frag_id:
            return index
    raise RenderError("unknown fragment: %s" % frag_id)  # pragma: no cover - guarded by `known`
