#!/usr/bin/env bash
# Guards tests/generated against silently collecting nothing (docs/stub.md F-4).
#
#   scripts/check-generated.sh
#
# - Every Python file under tests/generated must be named test_*.py (pytest's
#   default), otherwise it is never collected and "pytest tests/generated"
#   would pass vacuously.
# - Collecting tests/generated must yield at least one test per file (no files
#   at all is fine: nothing has been generated yet).
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$REPO_ROOT"

dir=tests/generated
[ -d "$dir" ] || { echo "no $dir: nothing generated yet"; exit 0; }

shopt -s nullglob
bad=()
files=()
for f in "$dir"/*.py; do
  case "$(basename "$f")" in
    test_*.py) files+=("$f") ;;
    __init__.py) ;;
    *) bad+=("$f") ;;
  esac
done
if [ "${#bad[@]}" -gt 0 ]; then
  echo "files pytest will not collect (rename to test_*.py): ${bad[*]}" >&2
  exit 1
fi
if [ "${#files[@]}" -eq 0 ]; then
  echo "no generated tests yet"
  exit 0
fi

collected="$(uv run pytest "$dir" --collect-only -q -p no:cacheprovider 2>&1)" || {
  printf '%s\n' "$collected" >&2
  echo "collection of $dir failed" >&2
  exit 1
}
count="$(printf '%s\n' "$collected" | grep -c '::test_' || true)"
if [ "$count" -lt "${#files[@]}" ]; then
  printf '%s\n' "$collected" >&2
  echo "collected $count tests from ${#files[@]} files: a generated file collects nothing" >&2
  exit 1
fi
echo "collected $count tests from ${#files[@]} generated files"
