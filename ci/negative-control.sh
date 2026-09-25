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
# Three refusals, each against the same derived rule (#2 added the last two):
#   1. its control removed        -> exit 1, UNPROVEN
#   2. its good population emptied -> exit 1, EMPTY (an empty side proves nothing)
#   3. `check --rule <unknown>`    -> exit 2, "unknown rule", nothing scanned
# An unparseable bad case with a blinded rule needs a blinded rule, which a shell
# script cannot make; tests/test_checks.py holds that case.
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

# --- 2. an empty population must not certify ---------------------------------
rm -rf "${scratch:?}/controls"
cp -r "$root/controls" "$scratch/controls"
find "$scratch/controls/$rule/good" -type f -delete
[[ -d "$scratch/controls/$rule/good" ]] || fail "emptying '$rule/good' removed the directory"
[[ -z "$(find "$scratch/controls/$rule/good" -type f)" ]] || fail "'$rule/good' still holds files"

"${SK[@]}" selftest --controls "$scratch/controls" > "$scratch/empty.out" 2>&1
code=$?
cat "$scratch/empty.out"

[[ $code -eq 1 ]] || fail "selftest exited $code with '$rule/good' empty; expected 1"
grep -Eq "^EMPTY +$rule( |\$)" "$scratch/empty.out" \
    || fail "selftest did not report 'EMPTY $rule' for an empty known-good population"
! grep -q "Traceback" "$scratch/empty.out" \
    || fail "selftest raised an exception; a crash is not a refusal"
summary="skillc selftest: $((total - 1))/$total rule(s) discriminate, 1 failing"
grep -qx "$summary" "$scratch/empty.out" \
    || fail "selftest did not complete with '$summary'"

echo "negative-control: ok - selftest refused with '$rule/good' empty (exit 1, EMPTY)"

# --- 3. an unknown selector must not read as a clean check --------------------
# Baseline first: the same target under the REAL rule id passes, so the refusal
# below is attributable to the selector and not to the target.
target="$root/controls/$rule/good"
"${SK[@]}" check "$target" --rule "$rule" > "$scratch/sel-base.out" 2>&1 \
    || { cat "$scratch/sel-base.out" >&2; fail "check --rule $rule fails on its own known-good input"; }

bogus="no-such-rule-negative-control"
"${SK[@]}" check "$target" --rule "$bogus" > "$scratch/sel.out" 2> "$scratch/sel.err"
code=$?
cat "$scratch/sel.out" "$scratch/sel.err"

[[ $code -eq 2 ]] || fail "check --rule $bogus exited $code; expected 2"
grep -q "unknown rule '$bogus'" "$scratch/sel.err" \
    || fail "check --rule $bogus did not name the unknown rule on stderr"
! grep -q "checked" "$scratch/sel.out" \
    || fail "check --rule $bogus scanned before refusing"

echo "negative-control: ok - check refused unknown selector '$bogus' (exit 2)"
