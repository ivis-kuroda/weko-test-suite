#!/usr/bin/env bash
# Generates the Python test for one case or scenario.
#
#   scripts/gen-test.sh TC-SWORD-001 [--force]
#   SPECS_DIR=../weko-test-suite-spec/specs scripts/gen-test.sh TC-SW-S5-01
#
# SPECS_DIR (default: specs) lets the generation read the specifications from
# another checkout, e.g. the spec-draft worktree, whose files then receive the
# automation write-back while the test code lands here.
#
# Output goes to tests/generated/test_<module>.py, where <module> is the id as a
# Python identifier (TC-SWORD-001 -> test_tc_sword_001.py). The test_ prefix is what
# pytest collects by default (docs/stub.md finding F-4). Extra arguments are passed
# to ath-generate-test. A generated case is written back to specs/ as
# automation.status=generated; review and commit that change with the test.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ $# -lt 1 ]; then
  echo "usage: scripts/gen-test.sh <TC-id|SC-id> [ath-generate-test options]" >&2
  exit 2
fi
id="$1"
shift

if [ ! -f "$HUB_DIR/packages/cli/bin/generate-test.ts" ]; then
  echo "hub not found at $HUB_DIR; run scripts/bootstrap-hub.sh" >&2
  exit 1
fi

# Same slug the CLI uses for its default file name.
module="$(printf '%s' "$id" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g')"

cd "$REPO_ROOT"
exec node "$HUB_DIR/packages/cli/bin/generate-test.ts" "$id" \
  --specs "${SPECS_DIR:-specs}" \
  --plugin plugin.yaml \
  --plugin-root . \
  --lang python \
  --python-extensions-module weko_suite_ext \
  --out "tests/generated/test_${module}.py" \
  "$@"
