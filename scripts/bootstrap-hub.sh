#!/usr/bin/env bash
# Makes the sibling agentic-test-hub checkout ready to generate tests.
#
#   scripts/bootstrap-hub.sh
#
# - Clones the hub next to this repository when it is absent, checked out at
#   the commit in hub.lock. HUB_DIR overrides the location.
# - Never moves an existing checkout: someone may be working in it. If it is
#   at another commit this only warns; use `git -C <hub> checkout <sha>` when
#   you do want the pinned one.
# - Installs the hub's Node dependencies. The hub has no build step (Node runs
#   its TypeScript directly), so install is all the CLI needs.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ ! -d "$HUB_DIR/.git" ]; then
  echo "cloning $HUB_REPO into $HUB_DIR"
  git clone "$HUB_REPO" "$HUB_DIR"
  git -C "$HUB_DIR" checkout --detach "$HUB_SHA"
fi

actual="$(git -C "$HUB_DIR" rev-parse HEAD)"
if [ "$actual" != "$HUB_SHA" ]; then
  echo "warning: $HUB_DIR is at $actual, hub.lock pins $HUB_SHA" >&2
fi

# Node runs the hub's .ts files itself; type stripping is on by default
# from 22.18. The hub declares >=26 and pnpm only warns below that.
node_version="$(node --version | sed 's/^v//')"
IFS=. read -r major minor _ <<<"$node_version"
if [ "$major" -lt 22 ] || { [ "$major" -eq 22 ] && [ "$minor" -lt 18 ]; }; then
  echo "Node $node_version is too old to run TypeScript directly; need >= 22.18 (hub wants 26)" >&2
  exit 1
fi

(cd "$HUB_DIR" && pnpm install --frozen-lockfile)

# Smoke test: the CLI starts and reports usage.
# (A captured variable, not a pipe: the CLI exits 2 on purpose.)
usage="$(node "$HUB_DIR/packages/cli/bin/generate-test.ts" 2>&1 || true)"
if [[ "$usage" == *"usage: ath-generate-test"* ]]; then
  echo "hub ready: $HUB_DIR @ $actual"
else
  echo "the hub CLI did not start" >&2
  exit 1
fi
