#!/usr/bin/env bash
# The checker's own installation, verified in a clean disposable environment (#27).
#
# Distinct from #7's subject materialization: this proves what an AUTHOR gets by
# installing the packaged skillc, not what a subject skill collection gets
# installed into. Three things a wheel install must do:
#
#   1. REFUSE to certify its own rules when its redcases are absent. `controls/`
#      is fixture data for skillc's own CI, not application code, and
#      `pyproject.toml` deliberately does not package it - so `skillc selftest`
#      in a fresh install has nothing to prove itself against. A install that
#      silently skipped this, or crashed, would be indistinguishable from one
#      that correctly refuses; only the exact refusal proves the point.
#   2. CERTIFY when redcases ARE supplied. Showing only the refusal proves half
#      the claim: an installed checker that could never pass selftest under any
#      condition would refuse identically. Copying `controls/` into scratch (not
#      pointing at the source tree - that would prove nothing about the PACKAGE)
#      and requiring the SAME "N/N discriminate" the source checkout reports
#      shows the installed rule code genuinely still works.
#   3. Still CHECK skills correctly, MATCHING the source checkout's own verdict.
#      A hardcoded "trigger-shape must fire" expectation cannot tell a packaging
#      regression from an unrelated rule change to the fixture itself (both would
#      change what fires); comparing the packaged run against a same-day SOURCE
#      run of the identical fixture pair can.
#
# Not wired into Woodpecker: this issue's own scope note says CI expansion is not
# required, and the build+venv round trip is slower than the four gates CI
# already runs on every push. Run it by hand, or from a local pre-release check.
#
# COMMITTED NEGATIVE CONTROL. `CLEAN_INSTALL_CONTROL=<mode>` inverts this script's
# own verdict: the mode's job is to break the thing step 2 or step 3 checks and
# require THIS SCRIPT to notice - so the control run exits 0 only when the
# underlying probe correctly failed, and exits 1 (a control FAILURE) if the
# probe stayed green over a real defect. Two modes:
#
#   CLEAN_INSTALL_CONTROL=neuter-installed-rule bash ci/clean-install-check.sh
#     Sabotages `trigger-shape` in the INSTALLED package only (never the source
#     checkout), by regex, after install. Step 3's bad-fixture comparison must
#     then disagree with the source baseline; if it does not, the sabotage was
#     not caught and the control reports FAILURE.
#
#   CLEAN_INSTALL_CONTROL=delete-scratch-controls bash ci/clean-install-check.sh
#     Deletes the scratch controls copy right before step 2's certifying run.
#     That run must reproduce step 1's "controls directory absent" refusal
#     rather than a false certify; if it does not, the control reports FAILURE.
#
# Neither mode is run in CI (this whole script is not); run either by hand
# before trusting a change to this file or to `_controls_root`/`cmd_selftest`.
set -uo pipefail

fail() { echo "clean-install-check: FAIL - $*" >&2; exit 1; }
control_pass() { echo "clean-install-check: CONTROL ok - $*"; exit 0; }
control_fail() { echo "clean-install-check: CONTROL FAILED - $*" >&2; exit 1; }

CONTROL_MODE="${CLEAN_INSTALL_CONTROL:-}"
case "$CONTROL_MODE" in
    ""|neuter-installed-rule|delete-scratch-controls) ;;
    *) fail "unknown CLEAN_INSTALL_CONTROL '$CONTROL_MODE'; expected 'neuter-installed-rule' or 'delete-scratch-controls'" ;;
esac

root="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

command -v uv >/dev/null || fail "uv not found; this script needs uv build and uv venv"

# --- fixtures, shared by the baseline and the packaged run -------------------
mkdir -p "$scratch/bad/rotate-credential" "$scratch/good"
cp "$root/controls/trigger-shape/bad/rotate-credential/SKILL.md" "$scratch/bad/rotate-credential/"
cp -r "$root/controls/trigger-shape/good/." "$scratch/good/"

# --- baseline: the SOURCE checkout's own verdict, on the identical fixtures
# and on its own committed controls/. `--json` (this same issue's other half)
# gives a structured verdict to compare against, rather than grepping prose
# that could match for the wrong reason.
( cd "$root" && uv run skillc check "$scratch/bad" --json --strict ) > "$scratch/baseline-bad.json" 2>"$scratch/baseline-bad.err"
baseline_bad_code=$?
( cd "$root" && uv run skillc check "$scratch/good" --json --strict ) > "$scratch/baseline-good.json" 2>"$scratch/baseline-good.err"
baseline_good_code=$?
[[ $baseline_bad_code -eq 1 ]] || { cat "$scratch/baseline-bad.err" >&2; fail "source checkout exited $baseline_bad_code on the bad fixture, not 1 - fixture or rule changed, not this script's business to decide which"; }
[[ $baseline_good_code -eq 0 ]] || { cat "$scratch/baseline-good.err" >&2; fail "source checkout exited $baseline_good_code on the good fixture, not 0 - the fixture is not clean on main; this probe cannot proceed meaningfully"; }

baseline_selftest="$(cd "$root" && uv run skillc selftest 2>&1)"
baseline_selftest_code=$?
[[ $baseline_selftest_code -eq 0 ]] || { echo "$baseline_selftest" >&2; fail "the source checkout's own selftest is not green; cannot use it as a baseline"; }
baseline_selftest_summary="$(echo "$baseline_selftest" | grep -E '^skillc selftest: ')"
[[ -n "$baseline_selftest_summary" ]] || fail "could not read the source checkout's selftest summary line"

# --- build -----------------------------------------------------------------
( cd "$root" && uv build --out-dir "$scratch/dist" ) > "$scratch/build.out" 2>&1 \
    || { cat "$scratch/build.out" >&2; fail "uv build failed"; }
wheel="$(find "$scratch/dist" -maxdepth 1 -name '*.whl' | head -1)"
[[ -n "$wheel" ]] || fail "uv build produced no wheel"

# --- install into a fresh, disposable venv ----------------------------------
uv venv "$scratch/venv" > "$scratch/venv.out" 2>&1 \
    || { cat "$scratch/venv.out" >&2; fail "uv venv failed"; }
uv pip install --python "$scratch/venv/bin/python" "$wheel" > "$scratch/install.out" 2>&1 \
    || { cat "$scratch/install.out" >&2; fail "uv pip install failed"; }
skillc="$scratch/venv/bin/skillc"
[[ -x "$skillc" ]] || fail "no skillc console script in the installed venv"

# Nothing from the source tree on the path OR ON CWD: a defect this probe
# exists to catch is a wheel that quietly works only because the repo checkout
# is still importable from where the venv's Python is invoked. `env -i` clears
# the environment; running from `$neutral_cwd` (holding no `skillc/` package of
# its own) closes the OTHER half - `python -c` prepends CWD to `sys.path`,
# `env -i` does not touch that. Found the hard way: an earlier draft of this
# script called the venv's `python -c 'import skillc...'` directly from the
# repo checkout's own directory, which put the SOURCE `skillc/checks.py` on
# `sys.path` ahead of the installed copy - the later "sabotage the installed
# package" control step then edited the checked-out source file, not the
# venv's site-packages copy, and the corruption was silent until the control
# mode failed to detect its own sabotage.
neutral_cwd="$scratch/neutral-cwd"
mkdir -p "$neutral_cwd"
run() { env -i HOME="$HOME" PATH="$(dirname "$skillc")" "$skillc" "$@"; }
runpy() { ( cd "$neutral_cwd" && env -i HOME="$HOME" "$scratch/venv/bin/python" "$@" ); }

# --- retained identity record (issue #63: logical values only, no scratch
# paths, no hostnames - only the wheel's own content digest, versions, and the
# source commit this build came from). Printed to stdout; a caller who wants it
# kept redirects this script's stdout to a file of their own naming.
wheel_sha256="$(sha256sum "$wheel" | awk '{print $1}')"
skillc_version="$(runpy -c 'import importlib.metadata as m; print(m.version("skillc"))')"
python_version="$(runpy --version 2>&1)"
uv_version="$(uv --version)"
source_commit="$(cd "$root" && git rev-parse HEAD)"
python3 - "$wheel_sha256" "$skillc_version" "$python_version" "$uv_version" "$source_commit" <<'PY'
import json
import sys

wheel_sha256, skillc_version, python_version, uv_version, source_commit = sys.argv[1:]
print(json.dumps({
    "schema": 1,
    "wheel_sha256": wheel_sha256,
    "skillc_version": skillc_version,
    "python_version": python_version,
    "uv_version": uv_version,
    "source_commit": source_commit,
}, indent=1))
PY

# --- 1. absent packaged controls refuse certification -----------------------
out="$(run selftest 2>&1)"
code=$?
echo "$out"
[[ $code -eq 2 ]] || fail "selftest exited $code in a clean install; expected 2 (controls absent)"
echo "$out" | grep -q "controls directory absent" \
    || fail "selftest did not name the absent controls directory"
! echo "$out" | grep -q "Traceback" \
    || fail "selftest raised an exception; a crash is not a refusal"

echo "clean-install-check: ok - selftest refuses without packaged controls (exit 2)"

# --- 2. WITH controls supplied, the installed checker certifies, matching the
# source checkout's own count. A FRESH COPY, never the source tree's own
# controls/ directory: pointing at the source would prove the SOURCE rules
# work, which step 0 above (the baseline) already established, not that the
# INSTALLED package's rule code does.
controls_copy="$scratch/controls-copy"
cp -r "$root/controls" "$controls_copy"

if [[ "$CONTROL_MODE" == "delete-scratch-controls" ]]; then
    rm -rf "$controls_copy"
fi

out="$(run selftest --controls "$controls_copy" 2>&1)"
code=$?
echo "$out"

if [[ "$CONTROL_MODE" == "delete-scratch-controls" ]]; then
    if [[ $code -eq 2 ]] && echo "$out" | grep -q "controls directory absent"; then
        control_pass "deleting the controls copy correctly reproduces step 1's absent-controls refusal, rather than a false certify"
    fi
    control_fail "deleting the controls copy did NOT reproduce the absent-controls refusal (exit $code) - the certifying step below does not genuinely depend on the copy"
fi

[[ $code -eq 0 ]] || fail "installed selftest with a controls copy exited $code; expected 0 (certifying)"
selftest_summary="$(echo "$out" | grep -E '^skillc selftest: ')"
[[ "$selftest_summary" == "$baseline_selftest_summary" ]] \
    || fail "installed selftest summary '$selftest_summary' does not match the source checkout's '$baseline_selftest_summary'"

echo "clean-install-check: ok - the installed checker certifies with a controls copy ($selftest_summary)"

# --- 3. the packaged rule code matches the source baseline ------------------
if [[ "$CONTROL_MODE" == "neuter-installed-rule" ]]; then
    site_pkg="$(runpy -c 'import skillc.checks as m; print(m.__file__)')"
    # MUST resolve under the venv, never under $root: if this ever printed the
    # SOURCE checkout's checks.py, the sed below would sabotage skillc's own
    # working tree instead of the installed copy - exactly the defect this
    # control mode exists to rule out (see the neutral_cwd comment above).
    case "$site_pkg" in
        "$scratch/venv"/*) ;;
        *) control_fail "the installed skillc.checks resolved to '$site_pkg', not under the venv - refusing to sabotage it" ;;
    esac
    [[ -f "$site_pkg" ]] || control_fail "could not find the installed checks.py to sabotage"
    sed -i "s/TRIGGER_RE.search(description)/True/" "$site_pkg"
fi

run check "$scratch/bad" --json --strict > "$scratch/packaged-bad.json" 2>"$scratch/packaged-bad.err"
packaged_bad_code=$?
run check "$scratch/good" --json --strict > "$scratch/packaged-good.json" 2>"$scratch/packaged-good.err"
packaged_good_code=$?

if [[ "$CONTROL_MODE" == "neuter-installed-rule" ]]; then
    if [[ $packaged_bad_code -ne $baseline_bad_code ]]; then
        control_pass "the sabotaged installed package was correctly caught (bad-fixture exit $packaged_bad_code, source checkout exited $baseline_bad_code)"
    fi
    control_fail "the sabotaged installed package was NOT caught (bad-fixture exit $packaged_bad_code matches the source checkout) - the probe is blind"
fi

cat "$scratch/packaged-bad.err" "$scratch/packaged-good.err" >&2
[[ $packaged_bad_code -eq $baseline_bad_code ]] \
    || fail "packaged check on the bad fixture exited $packaged_bad_code; source checkout exited $baseline_bad_code"
[[ $packaged_good_code -eq $baseline_good_code ]] \
    || fail "packaged check on the good fixture exited $packaged_good_code; source checkout exited $baseline_good_code"

# Compare the STRUCTURED verdict, not just the exit code: same rules, same
# skills_checked count. python3 (stdlib only) rather than adding a jq dependency.
python3 - "$scratch/baseline-bad.json" "$scratch/packaged-bad.json" "$scratch/baseline-good.json" "$scratch/packaged-good.json" <<'PY'
import json
import sys

paths = sys.argv[1:]
docs = [json.load(open(p, encoding="utf-8")) for p in paths]
baseline_bad, packaged_bad, baseline_good, packaged_good = docs

for label, baseline, packaged in (
    ("bad", baseline_bad, packaged_bad),
    ("good", baseline_good, packaged_good),
):
    b_rules = sorted(f["rule"] for f in baseline["findings"])
    p_rules = sorted(f["rule"] for f in packaged["findings"])
    if b_rules != p_rules:
        print(f"clean-install-check: FAIL - {label} fixture: source found {b_rules}, "
              f"packaged found {p_rules}", file=sys.stderr)
        sys.exit(1)
    if baseline["skills_checked"] != packaged["skills_checked"]:
        print(f"clean-install-check: FAIL - {label} fixture: source checked "
              f"{baseline['skills_checked']}, packaged checked {packaged['skills_checked']}",
              file=sys.stderr)
        sys.exit(1)
    if packaged["skills_checked"] < 1:
        print(f"clean-install-check: FAIL - {label} fixture: packaged run checked 0 skills; "
              f"an empty population is not a proof of matching behaviour", file=sys.stderr)
        sys.exit(1)

print("clean-install-check: ok - packaged findings match the source checkout, rule for rule")
PY

echo "clean-install-check: ok - the packaged checker matches the source baseline on both fixtures"
