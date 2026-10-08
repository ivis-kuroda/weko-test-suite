#!/usr/bin/env bash
# Shared by the scripts in this directory (sourced, not executed).
# Sets REPO_ROOT, HUB_DIR, HUB_REPO, HUB_SHA from hub.lock.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HUB_DIR="${HUB_DIR:-$REPO_ROOT/../agentic-test-hub}"

_lock_value() {
  grep -E "^$1=" "$REPO_ROOT/hub.lock" | head -n1 | cut -d= -f2-
}
HUB_REPO="$(_lock_value repo)"
HUB_SHA="$(_lock_value sha)"
if [ -z "$HUB_REPO" ] || [ -z "$HUB_SHA" ]; then
  echo "hub.lock is missing repo= or sha=" >&2
  exit 2
fi
