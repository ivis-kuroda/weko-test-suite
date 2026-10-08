#!/usr/bin/env bash
# Everything CI runs; run it before pushing.
#
#   scripts/check.sh
#
# Needs the sibling hub checkout (scripts/bootstrap-hub.sh) and `uv sync`.
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

step "fixtures manifest"
uv run python seeds/build_fixtures.py build --check

step "plugin.yaml against the hub schema"
node scripts/validate-plugin.ts "$HUB_DIR" plugin.yaml

step "specifications against the hub"
node "$HUB_DIR/scripts/check-spec-round-trip.ts" specs
node "$HUB_DIR/scripts/validate-specs.ts" specs

printf '\nall checks passed\n'
