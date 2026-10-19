#!/usr/bin/env bash
# Run every test/scenarios/*.sh in its OWN fresh container, in parallel, and summarise.
# Nothing on the host is modified; logs go to test/.out/<scenario>.log.
#
#   test/run-scenarios.sh [name ...]   run only these scenarios (default: all)
#   CLAUDE_TOKEN_FILE    `claude setup-token` token, for scenarios declaring `# needs: claude`
#   OPENCODE_AUTH_FILE   `opencode auth export` JSON, for scenarios declaring `# needs: opencode`
#   MAX_JOBS             parallel containers (default 8)
#   NO_BUILD=1           reuse the existing podium-test:latest image
#   KEEP=1               keep containers for inspection
set -u

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
out="$here/.out"
mkdir -p "$out"
max_jobs=${MAX_JOBS:-8}

if [ "${NO_BUILD:-0}" != 1 ]; then
  docker build --build-arg CACHE_BUST="$(date +%s)" -t podium-test:latest "$here/docker" >"$out/build.log" 2>&1 \
    || { echo "image build failed, see $out/build.log"; exit 3; }
fi

if [ "$#" -gt 0 ]; then
  names="$*"
else
  names=$(cd "$here/scenarios" && ls ./*.sh | sed 's#^\./##; s#\.sh$##' | grep -v '^lib$')
fi

run_one() {
  name=$1
  file="$here/scenarios/$name.sh"
  log="$out/$name.log"
  needs=$(sed -n 's/^# needs: //p' "$file" | head -n 1)
  cname="podium-sc-$name-$$"
  token=""
  case " $needs " in *" claude "*)
    [ -n "${CLAUDE_TOKEN_FILE:-}" ] || { echo "SKIP (needs CLAUDE_TOKEN_FILE)" >"$log"; return 0; }
    token=$(cat "$CLAUDE_TOKEN_FILE") ;;
  esac
  docker run -d --name "$cname" -e CLAUDE_CODE_OAUTH_TOKEN="$token" \
    -v "$repo:/src:ro" podium-test:latest sleep infinity >/dev/null
  case " $needs " in *" opencode "*)
    if [ -z "${OPENCODE_AUTH_FILE:-}" ]; then
      echo "SKIP (needs OPENCODE_AUTH_FILE)" >"$log"; docker rm -f "$cname" >/dev/null; return 0
    fi
    docker cp "$OPENCODE_AUTH_FILE" "$cname:/tmp/oc.json"
    docker exec -u root "$cname" chown tester /tmp/oc.json
    docker exec "$cname" bash -c 'opencode auth import /tmp/oc.json >/dev/null && rm -f /tmp/oc.json' ;;
  esac
  start=$(date +%s)
  docker exec "$cname" bash "/src/test/scenarios/$name.sh" >"$log" 2>&1
  code=$?
  echo "EXIT=$code SECONDS=$(( $(date +%s) - start ))" >>"$log"
  [ "${KEEP:-0}" = 1 ] || docker rm -f "$cname" >/dev/null
}

# (bash 3.2 on macOS has no `wait -n`: throttle by polling the running jobs)
for name in $names; do
  while [ "$(jobs -rp | wc -l)" -ge "$max_jobs" ]; do sleep 1; done
  run_one "$name" &
done
wait

echo
printf '%-28s %-8s %s\n' SCENARIO STATUS DETAIL
status=0
for name in $names; do
  log="$out/$name.log"
  if grep -q '^SKIP' "$log" 2>/dev/null; then
    printf '%-28s %-8s %s\n' "$name" SKIP "$(head -n 1 "$log")"; continue
  fi
  result=$(grep '^RESULT:' "$log" | tail -n 1)
  if grep -q '^EXIT=0 ' "$log" && [ -n "$result" ]; then
    printf '%-28s %-8s %s\n' "$name" PASS "$result"
  else
    status=1
    printf '%-28s %-8s %s\n' "$name" FAIL "${result:-no RESULT line} (see $log)"
    grep '^FAIL' "$log" | sed 's/^/    /'
  fi
done
exit $status
