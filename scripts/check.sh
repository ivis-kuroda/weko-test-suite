#!/usr/bin/env bash
# Everything CI runs; run it before pushing.
#
#   scripts/check.sh
#
# Needs the sibling hub checkout (scripts/bootstrap-hub.sh) and `uv sync`.
# SPECS_DIR (default: specs) points the spec checks at another checkout (the spec-draft worktree).
# STRICT_HUB=1 (set in CI) turns "hub is not at the hub.lock commit" from a
# warning into a failure.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$REPO_ROOT"

step() { printf '\n== %s\n' "$*"; }

step "hub checkout"
if [ ! -d "$HUB_DIR/.git" ]; then
  echo "hub not found at $HUB_DIR; run scripts/bootstrap-hub.sh" >&2
  exit 1
fi
actual="$(git -C "$HUB_DIR" rev-parse HEAD)"
if [ "$actual" != "$HUB_SHA" ]; then
  echo "hub is at $actual, hub.lock pins $HUB_SHA" >&2
  [ "${STRICT_HUB:-0}" = "1" ] && exit 1
fi

step "ruff"
uv run ruff check .

step "pytest (tools, seeds, plugin and extension)"
uv run pytest -q

step "generated tests are collected (docs/stub.md F-4)"
scripts/check-generated.sh

step "fixtures manifest"
uv run python seeds/build_fixtures.py build --check

step "plugin.yaml against the hub schema"
node scripts/validate-plugin.ts "$HUB_DIR" plugin.yaml

step "specifications against the hub"
node "$HUB_DIR/scripts/check-spec-round-trip.ts" "${SPECS_DIR:-specs}"
node "$HUB_DIR/scripts/validate-specs.ts" "${SPECS_DIR:-specs}"

step "log-judgement rule on the specifications (docs/LOG-JUDGEMENT.md)"
uv run python tools/check_log_rule.py "${SPECS_DIR:-specs}"

step "SWORD mechanics rig end to end (no browser; see docs/stub.md)"
scripts/rig-e2e.sh --no-browser

step "rig: out-of-scope ERROR noise never fails a test, a missing handler line always does"
# The pre-fix ERROR line before a 4xx and an unrelated ERROR with a stack trace on every request.
scripts/rig-run.sh --faithful-log TC-SW-S5-02-NOFILE-EP2 SC-SW-S6-01 SC-SW-S5-06 >/dev/null
if scripts/rig-run.sh --no-handler-log TC-SW-S5-02-NOFILE-EP2 >/dev/null 2>&1; then
  echo "FAIL: a case passed although its expected handler line is missing from the log" >&2
  exit 1
fi
echo "ok: noise tolerated, missing handler line detected"

printf '\nall checks passed\n'
