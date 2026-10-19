#!/usr/bin/env python3
"""Tokens of ONE Claude Code session: its transcript, its subagents and the
`opencode run` calls it launched (OpenCode sessions ses_cc<sid>x...).
Also loads runtime.json (usage.model_order, ui) and the locale bundle from
the plugin's locales/<ui>.json so the mod can render the pane.
Stdlib only; intended to be run with `python3 -I`.

Output JSON on stdout."""
import glob
import json
import os
import sqlite3
import sys

# --- Path resolution (ARCHITECTURE.md §3) -----------------------------------

def _xdg(env_var, default_under_home):
    val = os.environ.get(env_var)
    if val:
        return val
    return os.path.join(os.path.expanduser("~"), default_under_home)

OPENCODE_DB = os.path.join(
    _xdg("XDG_DATA_HOME", ".local/share"),
    "opencode", "opencode.db",
)
CLAUDE_PROJECTS = os.path.join(
    _xdg("CLAUDE_CONFIG_DIR", ".claude"),
    "projects",
)
PODIUM_CONFIG = _xdg("PODIUM_CONFIG_DIR", _xdg("XDG_CONFIG_HOME", ".config") + "/podium")

# The plugin root is the parent of the directory holding this script.
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES_DIR = os.path.join(PLUGIN_ROOT, "locales")

DEFAULT_UI = "en"
DEFAULT_MODEL_ORDER = ["opus", "sonnet", "haiku", "gpt-6.1-sol", "gpt-6-luna", "gpt", "minimax"]
EN_LOCALE = {
    "pane_title": "Tokens",
    "command_description": "Show the tokens consumed in this session, per model.",
    "command_opened": "Token pane opened.",
    "computing": "Computing…",
    "header_session": "Tokens · this session",
    "header_input": "input",
    "header_output": "output",
    "group_claude": "Claude Code",
    "group_opencode": "OpenCode (from this session)",
    "empty_rows": "No usage yet.",
    "cost_session": "Session cost: $",
    "engine_claude": "Claude ",
    "engine_opencode": "OpenCode ",
    "limit_5h": "5h",
    "limit_7d": "7d",
    "limit_resets": " (resets ",
    "limit_resets_close": ")",
    "quota_exhausted": "⚠ quota exhausted ",
    "no_variant": "no variant",
    "compaction_suffix": "compaction ×",
    "short_today": "today ",
    "weekdays": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
}


def load_runtime():
    """Read runtime.json from the podium config dir. Missing or unreadable →
    built-in defaults. Invalid → defaults + a recorded error."""
    errors = []
    ui = DEFAULT_UI
    model_order = list(DEFAULT_MODEL_ORDER)
    path = os.path.join(PODIUM_CONFIG, "runtime.json")
    try:
        with open(path, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
    except FileNotFoundError:
        pass  # missing → defaults, no error
    except (OSError, ValueError) as e:
        errors.append(f"runtime: {e}")
    else:
        usage = data.get("usage") or {}
        if isinstance(usage.get("model_order"), list):
            fragments = [str(x) for x in usage["model_order"] if isinstance(x, str)]
            if fragments:
                model_order = fragments
        if data.get("ui") in ("en", "es"):
            ui = data["ui"]
    return ui, model_order, errors


def load_locale(ui):
    """Load locales/<ui>.json; fall back to en; fall back to built-in defaults."""
    errors = []
    for try_ui in (ui, DEFAULT_UI):
        path = os.path.join(LOCALES_DIR, try_ui + ".json")
        try:
            with open(path, "rb") as fh:
                data = json.loads(fh.read().decode("utf-8"))
        except (OSError, ValueError) as e:
            errors.append(f"locale({try_ui}): {e}")
            continue
        weekdays = data.get("weekdays")
        if not isinstance(weekdays, list) or len(weekdays) != 7:
            errors.append(f"locale({try_ui}): weekdays must be a 7-element list")
            continue
        return data, errors
    return dict(EN_LOCALE), errors


# --- Token aggregation -----------------------------------------------------

def bump(rows, engine, model, variant, i, o, cr, cw):
    r = rows.setdefault((engine, model, variant or ""), {"in": 0, "out": 0, "cacheRead": 0, "cacheWrite": 0, "n": 0})
    r["in"] += i; r["out"] += o; r["cacheRead"] += cr; r["cacheWrite"] += cw; r["n"] += 1


def claude(sid, rows):
    files = glob.glob(os.path.join(CLAUDE_PROJECTS, "*", sid + ".jsonl"))
    files += glob.glob(os.path.join(CLAUDE_PROJECTS, "*", sid, "subagents", "*.jsonl"))
    seen = {}
    for path in files:
        with open(path, "rb") as fh:
            for line in fh:
                if b'"usage"' not in line or b'"assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue  # line written halfway
                m = d.get("message") or {}
                u = m.get("usage")
                if d.get("type") != "assistant" or not u or not m.get("model") or m["model"] == "<synthetic>":
                    continue
                # the same message repeats across several lines (one block per line)
                seen[m.get("id") or d.get("uuid")] = (m["model"], d.get("effort"), u)
    for model, effort, u in seen.values():
        bump(rows, "claude", model, None, u.get("input_tokens", 0), u.get("output_tokens", 0),
             u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0))


def opencode(sid, rows, quota):
    if not os.path.exists(OPENCODE_DB):
        return
    con = sqlite3.connect(f"file:{OPENCODE_DB}?mode=ro", uri=True)
    prefix = "ses_cc" + sid.replace("-", "") + "x"
    con.execute("""create temp table tagged as
        with recursive t(id) as (select id from session_v2 where substr(id, 1, ?) = ?
          union select s.id from session_v2 s join t on s.parent_id = t.id) select id from t""",
                (len(prefix), prefix))
    for prov, model, variant, tok, err, at in con.execute(
            """select json_extract(data,'$.model.providerID'), json_extract(data,'$.model.id'),
                      json_extract(data,'$.model.variant'), json_extract(data,'$.tokens'),
                      json_extract(data,'$.error.type'), time_created
               from session_message where type='assistant' and session_id in (select id from tagged)"""):
        key = f"{prov}/{model}"
        if err == "provider.quota":
            quota[("opencode", key, variant or "")] = at
        if not tok:
            continue
        t = json.loads(tok)
        c = t.get("cache") or {}
        if t.get("input", 0) + t.get("output", 0) + c.get("read", 0) == 0:
            continue
        bump(rows, "opencode", key, variant, t.get("input", 0), t.get("output", 0) + t.get("reasoning", 0),
             c.get("read", 0), c.get("write", 0))


def main():
    sid = sys.argv[1]
    rows, quota, errors = {}, {}, []
    ui, model_order, runtime_errors = load_runtime()
    errors.extend(runtime_errors)
    locale, locale_errors = load_locale(ui)
    errors.extend(locale_errors)
    for name, fn in (("claude", lambda: claude(sid, rows)), ("opencode", lambda: opencode(sid, rows, quota))):
        try:
            fn()
        except Exception as e:
            errors.append(f"{name}: {e}")
    out_rows = [{"engine": e, "model": m, "variant": v, **r, "quotaAt": quota.get((e, m, v))}
                for (e, m, v), r in sorted(rows.items())]
    json.dump({
        "sessionId": sid,
        "rows": out_rows,
        "errors": errors,
        "runtime": {"ui": ui, "usage": {"model_order": model_order}},
        "locale": locale,
    }, sys.stdout)


main()