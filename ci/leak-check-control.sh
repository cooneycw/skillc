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
#
# The real CI step's own command (WITH --exclude) is not re-asserted here as
# a fourth case: it already ran, in the step above this one, over the actual
# committed tree - this script's job is to show the instrument can fail, not
# to repeat the run whose green it is vouching for.
#
# SKILLC overrides the command (default `skillc`, so run under `uv run`, same
# convention as ci/negative-control.sh). It is how this script was shown to
# fail against a stub that always passes.
set -uo pipefail

read -ra SK <<< "${SKILLC:-skillc}"
root="$(cd "$(dirname "$0")/.." && pwd)"

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

echo "leak-check-control: ok - seeded fixture found, clean twin silent, unexcluded tree still leaks"
