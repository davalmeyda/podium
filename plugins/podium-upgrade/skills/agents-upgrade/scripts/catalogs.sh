#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
roster=$(python3 "$SCRIPT_DIR/roster.py")
printf '%s\n' "$roster" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("\n".join(sorted({r["launch"]["model"].split("/",1)[0] for r in d["roster"] if r.get("launch",{}).get("kind")=="opencode" and "/" in r.get("launch",{}).get("model",""))))' | while IFS= read -r provider; do
  [ -n "$provider" ] || continue
  echo "== OpenCode models: $provider"
  opencode models "$provider"
done
printf '%s\n' "$roster" | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(a["name"]+"\t"+a["model"]+"\t"+a.get("variant","none")) for a in d["agents"] if a.get("name") and a.get("model")]' | while IFS="$(printf '\t')" read -r agent model variant; do
  echo "== Agent check: $agent ($model#$variant)"
  opencode run --agent "$agent" -m "$model#$variant" "Reply with exactly: OK"
done
