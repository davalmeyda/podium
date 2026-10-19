#!/usr/bin/env bash
# Build a fresh clean-room image (latest Claude Code / OpenCode / CodeGraph) and run
# test/e2e.sh in a brand-new container. Nothing on the host is modified.
#
#   CLAUDE_TOKEN_FILE   file with a `claude setup-token` token (required for the claude checks)
#   OPENCODE_AUTH_FILE  optional `opencode auth export` JSON to import (enables executor checks)
#   KEEP=1              keep the container afterwards for inspection
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
name="podium-e2e-$(date +%s)"

docker build --build-arg CACHE_BUST="$(date +%s)" -t podium-test:latest "$here/docker" >/dev/null

token=""
[ -n "${CLAUDE_TOKEN_FILE:-}" ] && token=$(cat "$CLAUDE_TOKEN_FILE")

docker run -d --name "$name" -e CLAUDE_CODE_OAUTH_TOKEN="$token" \
  -v "$repo:/src:ro" podium-test:latest sleep infinity >/dev/null
trap '[ "${KEEP:-0}" = 1 ] || docker rm -f "$name" >/dev/null' EXIT

oc=0
if [ -n "${OPENCODE_AUTH_FILE:-}" ]; then
  docker cp "$OPENCODE_AUTH_FILE" "$name:/tmp/oc.json"
  docker exec -u root "$name" chown tester /tmp/oc.json
  docker exec "$name" bash -c 'opencode auth import /tmp/oc.json >/dev/null && rm -f /tmp/oc.json'
  oc=1
fi

docker exec -e PODIUM_E2E_OPENCODE="$oc" "$name" bash /src/test/e2e.sh
