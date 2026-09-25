#!/usr/bin/env bash
# Negative control for the CI gate: prove `skillc selftest` can still say NO.
#
# The gate step runs selftest on the shipped controls and reads its green. A
# selftest that had gone blind would print the same green, so this step hands it
# a controls tree with one rule's control removed and REQUIRES the refusal.
#
# The verdict is exit 1, an `UNPROVEN <rule>` line, the COMPLETED summary naming
# exactly one unproven rule and no failing one, and no traceback. Exit 1 alone is
# not enough: an uncaught Python exception also exits 1, and one raised AFTER the
# UNPROVEN line (in the summary, say) must not read as a correct refusal.
# tests/test_negative_control.py holds the committed red cases.
#
# Today this covers the one case selftest detects: a missing control. Empty
# populations, an unparseable bad case and an unknown --rule join it with #2.
#
# SKILLC overrides the command (default `skillc`, so run under `uv run`). It is
# how this script was shown to fail against a stub selftest that always passes.
set -uo pipefail

read -ra SK <<< "${SKILLC:-skillc}"
root="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

fail() { echo "negative-control: FAIL - $*" >&2; exit 1; }

# Derived, not hardcoded: a renamed rule must not silently empty this case.
"${SK[@]}" rules > "$scratch/rules.out" || fail "\`skillc rules\` failed"
rule="$(awk 'NF { print $2; exit }' "$scratch/rules.out")"
total="$(awk 'NF' "$scratch/rules.out" | wc -l)"
[[ -n "$rule" ]] || fail "\`skillc rules\` listed no rule; nothing to remove"

cp -r "$root/controls" "$scratch/controls"
[[ -d "$scratch/controls/$rule" ]] || fail "rule '$rule' has no control directory to remove"

# Baseline: the unmodified copy must pass, so the red below is attributable to
# the removal and not to a broken copy.
"${SK[@]}" selftest --controls "$scratch/controls" > "$scratch/baseline.out" 2>&1 \
    || { cat "$scratch/baseline.out" >&2; fail "selftest fails on an unmodified copy"; }

rm -rf "${scratch:?}/controls/$rule"
"${SK[@]}" selftest --controls "$scratch/controls" > "$scratch/red.out" 2>&1
code=$?
cat "$scratch/red.out"

[[ $code -eq 1 ]] || fail "selftest exited $code with '$rule' uncontrolled; expected 1"
grep -Eq "^UNPROVEN +$rule( |\$)" "$scratch/red.out" \
    || fail "selftest exited 1 without reporting 'UNPROVEN $rule' (a crash is not a refusal)"
! grep -q "Traceback" "$scratch/red.out" \
    || fail "selftest raised an exception; a crash is not a refusal"
summary="skillc selftest: $((total - 1))/$total rule(s) discriminate, 1 unproven"
grep -qx "$summary" "$scratch/red.out" \
    || fail "selftest did not complete with '$summary'"

echo "negative-control: ok - selftest refused with '$rule' uncontrolled (exit 1, UNPROVEN)"
