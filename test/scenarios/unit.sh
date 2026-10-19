# The whole unittest suite and shell syntax checks, in a clean container.
# (Python 3.8 compatibility is covered by CI: .github/workflows/ci.yml.)
# needs: none
. /src/test/scenarios/lib.sh

section "unittest"
rm -rf /tmp/w && cp -r /src /tmp/w
(cd /tmp/w && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests) >/tmp/unit.log 2>&1
tail -n 3 /tmp/unit.log
check "unit tests pass" "tail -n 1 /tmp/unit.log | grep -q '^OK'"

section "shell syntax"
for f in /src/install.sh /src/test/*.sh /src/test/scenarios/*.sh $(find /src/plugins -name '*.sh'); do
  check "sh -n $(basename "$f")" "bash -n $f"
done

finish
