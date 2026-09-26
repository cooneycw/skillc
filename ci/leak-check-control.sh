#!/usr/bin/env bash
# Negative control for the leak-check CI step: prove `skillc leak-check` can
# still say LEAK (issue #63).
#
# The leak-check step reads a green scan of the checked-out tree. A scan that
# had gone blind (a regex that stopped matching, a step scanning the wrong
# path, an --exclude that swallowed more than intended) prints the same green,
# so this proves three things against the real repository, not a copy:
#
#   1. controls/leak-check/bad/  -> exit 1 (the seeded fixture still fires)
#   2. controls/leak-check/good/ -> exit 0 (the clean twin stays silent)
#   3. the WHOLE tree WITHOUT --exclude -> exit 1 (the seeded fixture is
#      really there and really matches; a green here would mean --exclude in
#      the real CI step is hiding something rather than narrowly steering
#      around one fixture on purpose)
#   4. THE PRODUCTION --exclude FLAGS, against a scratch tree holding both an
#      excluded fixture AND a leak OUTSIDE it -> exit 1, attributed to the
#      outside file BY NAME. Cross-model review: cases 1-3 never exercise the
#      real CI command's own --exclude list, so `--exclude docs` (or any
#      exclusion wider than intended) would hide a real leak under docs/ while
#      1-3 still pass unchanged - this is what would have caught that.
#
# SKILLC and SKILLC_EXCLUDE_ARGS override the command and the production
# --exclude list (defaults: `skillc`, run under `uv run` same convention as
# ci/negative-control.sh; and the exact flags the leak-check step passes,
# kept in sync with .woodpecker/ci.yml by hand). Overriding SKILLC is how this
# script was shown to fail against a stub that always passes.
set -uo pipefail

read -ra SK <<< "${SKILLC:-skillc}"
read -ra EXCLUDE_ARGS <<< "${SKILLC_EXCLUDE_ARGS:---exclude controls/leak-check/bad --exclude tests/test_leak.py --exclude ci/leak-check-control.sh}"
root="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

fail() { echo "leak-check-control: FAIL - $*" >&2; exit 1; }

"${SK[@]}" leak-check "$root/controls/leak-check/bad" > /dev/null 2>&1
rc=$?
[[ $rc -eq 1 ]] || fail "seeded bad/ fixture: want exit 1 (leak), got $rc"

"${SK[@]}" leak-check "$root/controls/leak-check/good" > /dev/null 2>&1
rc=$?
[[ $rc -eq 0 ]] || fail "clean good/ fixture: want exit 0, got $rc"

"${SK[@]}" leak-check "$root" > /dev/null 2>&1
rc=$?
[[ $rc -eq 1 ]] || fail "whole tree without --exclude: want exit 1 (the fixture is really there), got $rc"

mkdir -p "$scratch/tree/controls/leak-check/bad" "$scratch/tree/tests"
echo "/home/exampleuser" > "$scratch/tree/controls/leak-check/bad/fake-leak.txt"
echo "nothing here" > "$scratch/tree/tests/test_leak.py"
echo "/home/exampleuser" > "$scratch/tree/outside-leak.txt"
echo "nothing here" > "$scratch/tree/padding.txt"  # so excluding outside-leak.txt
# alone still leaves something scannable (exit 0, not 3) - the failure this
# case exists to catch must read as "too wide", not as "nothing left to scan"
out="$("${SK[@]}" leak-check "$scratch/tree" "${EXCLUDE_ARGS[@]}" 2>&1)"
rc=$?
[[ $rc -eq 1 ]] || { echo "$out" >&2; fail "production exclude list: want exit 1 (an outside leak exists), got $rc"; }
echo "$out" | grep -q "outside-leak.txt" \
  || { echo "$out" >&2; fail "production exclude list: found A leak but not the outside one - too wide"; }
echo "$out" | grep -q "fake-leak.txt" \
  && { echo "$out" >&2; fail "production exclude list: reported the excluded fixture - not narrow enough to trust as a control"; }

echo "leak-check-control: ok - seeded fixture found, clean twin silent, unexcluded tree still leaks, production --exclude stays narrow"
