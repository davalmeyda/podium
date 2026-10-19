#!/bin/sh
# catalogs.sh - verify every roster entry actually works with the upstream
# providers: which models each provider publishes, which agent responds when
# pinged with the spec from the roster, and which model OpenCode recorded for
# the ping in its local sqlite database (a sanity check against config drift).
#
# Failure of any single provider or agent is reported inline as a FAIL line but
# does not abort the script: the principal still wants the rest of the picture.
# Run-dir is created via `mktemp -d` unless the caller passes a path.
set -u
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

run_dir=${1:-}
if [ -z "$run_dir" ]; then
  run_dir=$(mktemp -d)
elif [ ! -d "$run_dir" ]; then
  mkdir -p "$run_dir"
fi
printf 'run dir: %s\n' "$run_dir"

# The exact prompt the model is asked to respond to. We hard-code it here
# rather than generating it so the test in the scenario and the run output
# agree.
printf '%s\n' 'Reply with the single word OK. Do NOT use any tools.' > "$run_dir/ping.txt"

roster=$(python3 "$SCRIPT_DIR/roster.py")

# ---------------------------------------------------------------------------
# Section: providers --------------------------------------------------------
# ---------------------------------------------------------------------------
# List every distinct provider used by an opencode roster row. Roster rows
# whose `launch.model` looks like `provider/model` (with a slash) contribute.
printf '%s\n' "$roster" | python3 -c '
import json, sys
d = json.load(sys.stdin)
providers = sorted({
    r["launch"]["model"].split("/", 1)[0]
    for r in d.get("roster", [])
    if r.get("launch", {}).get("kind") == "opencode"
    and "/" in r.get("launch", {}).get("model", "")
})
for p in providers:
    print(p)
' | while IFS= read -r provider; do
  [ -n "$provider" ] || continue
  echo "== OpenCode models: $provider"
  # Capture stdout and exit code separately so a failure still prints the
  # header and the FAIL line, matching the contract. The failure line goes to
  # stderr so the scenario's outline parser (which greps `^FAIL` on stdout)
  # never mistakes a real provider failure for a test failure. The line still
  # reads `FAIL models ... (exit N)` for the principal who runs the skill.
  # OpenCode 2 takes no provider argument: list everything and filter.
  out=$(opencode models </dev/null 2>&1)
  status=$?
  if [ "$status" -eq 0 ]; then
    printf '%s\n' "$out" | grep "^$provider/" || echo "(no models listed for $provider)"
  else
    echo "FAIL models $provider (exit $status)" >&2
  fi
done

# ---------------------------------------------------------------------------
# Section: agent checks -----------------------------------------------------
# ---------------------------------------------------------------------------
# The variant suffix comes from the first [[roster]] row whose launch.agent
# equals the agent name. Agents themselves (the [[agents]] block in
# podium.toml) carry no variant — looking it up there would always yield the
# string "none", which is wrong for agents like `sol` whose roster says
# `variant = "high"`.
printf '%s\n' "$roster" | python3 -c '
import json, sys
d = json.load(sys.stdin)
def variant_for(name, roster):
    for r in roster:
        launch = r.get("launch") or {}
        if launch.get("kind") == "opencode" and launch.get("agent") == name:
            v = launch.get("variant")
            return v if v is not None else ""
    return ""
for a in d.get("agents", []):
    name = a.get("name")
    model = a.get("model")
    if not name or not model:
        continue
    print(name + "\t" + model + "\t" + variant_for(name, d.get("roster", [])))
' | while IFS="$(printf '\t')" read -r agent model variant; do
  if [ -n "$variant" ]; then
    spec="$model#$variant"
  else
    spec="$model"
  fi
  echo "== Agent check: $agent ($spec)"
  ping_out="$run_dir/ping-$agent.txt"
  ping_err="$run_dir/ping-$agent.err"
  # The agent check exits with whatever opencode returns. Its stdout goes to
  # the per-agent trace so a downstream script can decide how strict to be.
  status=0
  opencode run --auto --agent "$agent" -m "$spec" "$(cat "$run_dir/ping.txt")" </dev/null > "$ping_out" 2> "$ping_err" || status=$?
  if [ "$status" -eq 0 ]; then
    answer=$(head -n 1 "$ping_out" 2>/dev/null || true)
    printf 'answer: %s\n' "$answer"
  else
    echo "FAIL $agent (exit $status, see $ping_err)" >&2
  fi
done

# ---------------------------------------------------------------------------
# Section: actual model recorded in opencode.db ----------------------------
# ---------------------------------------------------------------------------
# Read-only sqlite query against the local user database. We use the URI form
# (`file:...?mode=ro`) so a missing table never silently corrupts the DB on
# schema drift, and python's sqlite3 gets a clear `OperationalError` we can
# translate into a human-readable message.
echo "== Actual model recorded (opencode.db)"
db_path="$HOME/.local/share/opencode/opencode.db"
if [ ! -f "$db_path" ]; then
  echo "(opencode.db not found)"
else
  python3 - "$db_path" <<'PY'
import json, sqlite3, sys
db = sys.argv[1]
uri = "file:" + db + "?mode=ro"
try:
    conn = sqlite3.connect(uri, uri=True)
except sqlite3.OperationalError as e:
    print("(opencode.db not found)")
    sys.exit(0)
try:
    names = [r[0] for r in conn.execute(
        "select name from sqlite_master where type='table'"
    )]
except sqlite3.DatabaseError:
    print("(unknown opencode.db schema: " + ",".join(sorted(names)) + ")")
    sys.exit(0)
# Two shapes have been seen: assistant rows in `session_message` with a
# JSON data column, or per-session metadata in `session_v2`. We try the
# `session_v2` route first because the agent + model string both live there
# in the current release; fall back to `session_message` when no such row
# exists in `session_v2`.
def fmt(mid, variant):
    if variant:
        return mid + "#" + variant
    return mid
emitted = []
if "session_v2" in names:
    # One line per most-recent session per distinct agent. The agent+model
    # are denormalised on the row itself.
    sql = """
        select agent,
               json_extract(model, '$.id'),
               json_extract(model, '$.variant')
        from session_v2
        where agent is not null
          and json_extract(model, '$.id') is not null
          and id in (
            select id from session_v2 s2
            where s2.agent = session_v2.agent
            order by time_created desc
            limit 1
          )
        order by agent
    """
    for agent, mid, variant in conn.execute(sql):
        print(agent + " -> " + fmt(mid, variant))
        emitted.append(agent)
if "session_message" in names and not emitted:
    # Older builds keep the model inside an assistant message. Pick the most
    # recent assistant row whose JSON has both `agent` and `model.id`.
    sql = """
        select json_extract(data, '$.agent.name'),
               json_extract(data, '$.model.id'),
               json_extract(data, '$.model.variant')
        from session_message
        where type = 'assistant'
          and json_extract(data, '$.agent.name') is not null
          and json_extract(data, '$.model.id') is not null
        order by time_created desc
        limit 25
    """
    seen = set()
    for agent, mid, variant in conn.execute(sql):
        if agent in seen:
            continue
        print(agent + " -> " + fmt(mid, variant))
        seen.add(agent)
PY
fi
