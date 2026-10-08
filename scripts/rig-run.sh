#!/usr/bin/env bash
# Runs generated Tier-1 tests against the SWORD mechanics rig (tools/sword-stub).
#
#   scripts/rig-run.sh TC-SW-S5-01 SC-SW-S6-01 ...   # these ids
#   scripts/rig-run.sh --all                         # every generated test
#   scripts/rig-run.sh --no-evidence ...             # skip evidence saving
#   scripts/rig-run.sh --faithful-log ...            # the stub logs an ERROR line before every 4xx
#                                                    # (what the code did before the fix, A-5): coded 4xx cases must then fail
#   scripts/rig-run.sh --exec <command...>           # run any command with the rig's environment
#
# The rig is NOT WEKO (docs/stub.md). A pass means "the generated test and the
# hub's plumbing work" (multipart, env tokens, {{step.x}}, produces, cleanup,
# assertions on the error JSON, masked evidence), not that WEKO conforms; a
# failure may only mean that the stub is not WEKO (docs/TIER1-STATUS.md).
#
# Rig-only configuration lives here and in tools/sword-stub/rig-tier1.json; the
# plugin and the specifications are used as they are. Exit status is pytest's.
# The work directory (stub log, evidence, junit) is printed at the end.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$REPO_ROOT"

ALL=0
EVIDENCE_ON=1
FAITHFUL=0
IDS=()
EXEC=()
while [ $# -gt 0 ]; do
  arg="$1"
  shift
  case "$arg" in
    --exec) EXEC=("$@"); break ;;
    --all) ALL=1 ;;
    --no-evidence) EVIDENCE_ON=0 ;;
    --faithful-log) FAITHFUL=1 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) IDS+=("$arg") ;;
  esac
done
if [ "$ALL" = 0 ] && [ "${#IDS[@]}" -eq 0 ] && [ "${#EXEC[@]}" -eq 0 ]; then
  echo "usage: scripts/rig-run.sh [--all] [--no-evidence] <TC-id|SC-id>..." >&2
  exit 2
fi

FILES=()
if [ "${#EXEC[@]}" -gt 0 ]; then
  :
elif [ "$ALL" = 1 ]; then
  FILES=(tests/generated)
else
  for id in "${IDS[@]}"; do
    module="$(printf '%s' "$id" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g')"
    f="tests/generated/test_${module}.py"
    [ -f "$f" ] || { echo "no generated test for $id ($f)" >&2; exit 2; }
    FILES+=("$f")
  done
fi

STUB_DIR="tools/sword-stub"
WORK="${RIG_WORK:-$(mktemp -d "${TMPDIR:-/tmp}/rig-run.XXXXXX")}"
EVIDENCE="$WORK/evidence"
mkdir -p "$EVIDENCE"

uv run python seeds/build_fixtures.py build --out fixtures/generated --manifest "$WORK/manifest.json" >/dev/null

# rig-tier1.json simulates the fixed behaviour (a 4xx logs only a WARNING). --faithful-log turns
# the stub's pre-fix behaviour back on (an ERROR line before every 4xx) in a copy of the config.
CONFIG="$STUB_DIR/rig-tier1.json"
if [ "$FAITHFUL" = 1 ]; then
  uv run python - "$CONFIG" "$WORK/rig.json" <<'PY'
import json, sys
config = json.load(open(sys.argv[1]))
config["settings"]["faithful_log"] = True
json.dump(config, open(sys.argv[2], "w"))
PY
  CONFIG="$WORK/rig.json"
fi
uv run python "$STUB_DIR/stub_server.py" --config "$CONFIG" --port 0 \
  --port-file "$WORK/port" --log-file "$WORK/app.log" 2> "$WORK/stub.stderr" &
STUB_PID=$!
trap 'kill "$STUB_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do
  [ -s "$WORK/port" ] && break
  sleep 0.1
done
[ -s "$WORK/port" ] || { echo "stub did not start" >&2; cat "$WORK/stub.stderr" >&2; exit 1; }
export STUB_URL="http://127.0.0.1:$(cat "$WORK/port")"

mkdir -p "$WORK/bin"
printf '#!/bin/sh\nexec "%s" "%s" "$@"\n' "$(uv run python -c 'import sys; print(sys.executable)')" \
  "$REPO_ROOT/$STUB_DIR/fake_docker.py" > "$WORK/bin/docker"
chmod +x "$WORK/bin/docker"
export PATH="$WORK/bin:$PATH"

# What a real environment gets from .env / .env.local (docs/BASELINE.md), pointed at the rig.
export WEKO_BASE_URL="$STUB_URL"
export WEKO_WEB_CONTAINER=weko-web-1 WEKO_DB_CONTAINER=weko-db-1 WEKO_REDIS_CONTAINER=weko-redis-1
export SW_TOKEN_1=RIGTOKEN-1 SW_TOKEN_2=RIGTOKEN-2 SW_TOKEN_5=RIGTOKEN-5
export SW_TOKEN_REVOKED=RIGTOKEN-REVOKED SW_TOKEN_W=RIGTOKEN-W SW_TOKEN_W2=RIGTOKEN-W2
export SW_TOKEN_ROLE_SYSADMIN=RIGTOKEN-1 SW_TOKEN_ROLE_REPOADMIN=RIGTOKEN-ROLE-REPOADMIN
export SW_TOKEN_ROLE_COMADMIN=RIGTOKEN-ROLE-COMADMIN SW_TOKEN_ROLE_CONTRIBUTOR=RIGTOKEN-ROLE-CONTRIBUTOR
export SW_TOKEN_ROLE_GENERAL=RIGTOKEN-ROLE-GENERAL
for n in 1 2 3 4 5 6 7 8 9; do export "SW_R$n=$((900000 + n))"; done
export SW_USER_SYSADMIN=wekosoftware@nii.ac.jp SW_ITEM_TYPE_ID=30001 SW_REDIS_DB=1

if [ "$EVIDENCE_ON" = 1 ]; then export ATH_EVIDENCE_DIR="$EVIDENCE"; fi
set +e
if [ "${#EXEC[@]}" -gt 0 ]; then
  "${EXEC[@]}"
  STATUS=$?
else
uv run pytest -c pyproject.toml --rootdir . -p no:cacheprovider -q -rA \
  --junitxml "$WORK/junit.xml" "${FILES[@]}"
STATUS=$?
fi
set -e
if [ "$EVIDENCE_ON" = 1 ] && [ "${#EXEC[@]}" -eq 0 ]; then
  if grep -rqE 'RIGTOKEN-' "$EVIDENCE"; then
    echo "FAIL: a raw rig token appears in the saved evidence (masking is broken)" >&2
    STATUS=1
  elif ! grep -rq 'REDACTED' "$EVIDENCE"; then
    echo "FAIL: no masked value found in the saved evidence" >&2
    STATUS=1
  else
    echo "evidence ok: no raw token in $EVIDENCE, masked values present"
  fi
fi
printf '\nwork directory: %s (rig only: nothing here says anything about WEKO)\n' "$WORK"
exit "$STATUS"
