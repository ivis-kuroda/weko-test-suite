#!/usr/bin/env bash
# Runs the generated tests against a real environment in the order of the
# specification (v4.2 section 0.6: S1 -> S16), one file per pytest process, with a
# pause between files so that two calls to EP4/EP5 on the same recid are at least
# 3 seconds apart (the Direct route locks the recid for 3 seconds, 409 / 2201 otherwise).
#
#   set -a; . ./.env; . ./.env.local; set +a
#   scripts/run-ordered.sh [--out DIR] [--gap SECONDS] [--only REGEX] [--list]
#
# --out   evidence + junit directory (default artifacts/run-<UTC timestamp>); exported as ATH_EVIDENCE_DIR
# --gap   seconds to sleep between files (default 3)
# --only  run only the files whose name matches the extended regex (e.g. 's5_0[1-4]')
# --list  print the order and exit
#
# Needs a real WEKO (see the weko-env-up skill). Against the rig use:
#   scripts/rig-run.sh --exec scripts/run-ordered.sh --gap 0
# Exit status: 0 when every file passed, 1 otherwise (all files are always run).
# Destructive groups (S14/S15) are not generated yet; when they are, they must be
# run last and only by their own group (see the sword-test-run skill).
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$REPO_ROOT"

OUT=""
GAP=3
ONLY=""
LIST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift ;;
    --gap) GAP="$2"; shift ;;
    --only) ONLY="$2"; shift ;;
    --list) LIST=1 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# Order key: S<n>-<m> as numbers, then the file name (TC before SC is irrelevant).
ordered() {
  python3 - "$@" <<'PY'
import re, sys
def key(path):
    m = re.search(r"_s(\d+)_(\d+)", path)
    return (int(m.group(1)), int(m.group(2)), path) if m else (999, 0, path)
for p in sorted(sys.argv[1:], key=key):
    print(p)
PY
}

FILES=()
while IFS= read -r f; do
  if [ -z "$ONLY" ] || printf '%s' "$f" | grep -Eq "$ONLY"; then FILES+=("$f"); fi
done < <(ordered tests/generated/test_*.py)

if [ "$LIST" = 1 ]; then printf '%s\n' "${FILES[@]}"; exit 0; fi

[ -n "$OUT" ] || OUT="artifacts/run-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT/junit"
export ATH_EVIDENCE_DIR="$OUT/evidence"
echo "output directory: $OUT (git-ignored; never commit it)"

FAILED=0
LAST=$(( ${#FILES[@]} - 1 ))
for i in "${!FILES[@]}"; do
  f="${FILES[$i]}"
  name="$(basename "$f" .py)"
  echo "== $name"
  if ! uv run pytest -c pyproject.toml --rootdir . -p no:cacheprovider -q -x \
      --junitxml "$OUT/junit/$name.xml" "$f"; then
    FAILED=$((FAILED + 1))
  fi
  if [ "$i" -lt "$LAST" ] && [ "$GAP" != 0 ]; then sleep "$GAP"; fi
done
echo
echo "files run: ${#FILES[@]}, files with a failure: $FAILED"
echo "A-5 findings (on hold):"
uv run python tools/a5_scan.py "$ATH_EVIDENCE_DIR" --rows || true
[ "$FAILED" = 0 ]
