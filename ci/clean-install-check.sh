#!/usr/bin/env bash
# The checker's own installation, verified in a clean disposable environment (#27).
#
# Distinct from #7's subject materialization: this proves what an AUTHOR gets by
# installing the packaged skillc, not what a subject skill collection gets
# installed into. Two things a wheel install must do:
#
#   1. REFUSE to certify its own rules when its redcases are absent. `controls/`
#      is fixture data for skillc's own CI, not application code, and
#      `pyproject.toml` deliberately does not package it - so `skillc selftest`
#      in a fresh install has nothing to prove itself against. A install that
#      silently skipped this, or crashed, would be indistinguishable from one
#      that correctly refuses; only the exact refusal proves the point.
#   2. Still CHECK skills correctly, MATCHING the source checkout's own verdict.
#      A hardcoded "trigger-shape must fire" expectation cannot tell a packaging
#      regression from an unrelated rule change to the fixture itself (both would
#      change what fires); comparing the packaged run against a same-day SOURCE
#      run of the identical fixture pair can. Codex cross-model review (#27)
#      found the hardcoded form indistinguishable from that neighbour case.
#
# Not wired into Woodpecker: this issue's own scope note says CI expansion is not
# required, and the build+venv round trip is slower than the four gates CI
# already runs on every push. Run it by hand, or from a local pre-release check.
set -uo pipefail

fail() { echo "clean-install-check: FAIL - $*" >&2; exit 1; }

root="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

command -v uv >/dev/null || fail "uv not found; this script needs uv build and uv venv"

# --- fixtures, shared by the baseline and the packaged run -------------------
mkdir -p "$scratch/bad/rotate-credential" "$scratch/good"
cp "$root/controls/trigger-shape/bad/rotate-credential/SKILL.md" "$scratch/bad/rotate-credential/"
cp -r "$root/controls/trigger-shape/good/." "$scratch/good/"

# --- baseline: the SOURCE checkout's own verdict on the identical fixtures ---
# `--json` (this same issue's other half) gives a structured verdict to compare
# against, rather than grepping prose that could match for the wrong reason.
( cd "$root" && uv run skillc check "$scratch/bad" --json --strict ) > "$scratch/baseline-bad.json" 2>"$scratch/baseline-bad.err"
baseline_bad_code=$?
( cd "$root" && uv run skillc check "$scratch/good" --json --strict ) > "$scratch/baseline-good.json" 2>"$scratch/baseline-good.err"
baseline_good_code=$?
[[ $baseline_bad_code -eq 1 ]] || { cat "$scratch/baseline-bad.err" >&2; fail "source checkout exited $baseline_bad_code on the bad fixture, not 1 - fixture or rule changed, not this script's business to decide which"; }
[[ $baseline_good_code -eq 0 ]] || { cat "$scratch/baseline-good.err" >&2; fail "source checkout exited $baseline_good_code on the good fixture, not 0 - the fixture is not clean on main; this probe cannot proceed meaningfully"; }

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

# Nothing from the source tree on the path: a defect this probe exists to catch
# is a wheel that quietly works only because the repo checkout is still on
# PYTHONPATH or CWD. `env -i` refuses that by construction.
run() { env -i HOME="$HOME" PATH="$(dirname "$skillc")" "$skillc" "$@"; }

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

# --- 2. the packaged rule code matches the source baseline ------------------
run check "$scratch/bad" --json --strict > "$scratch/packaged-bad.json" 2>"$scratch/packaged-bad.err"
packaged_bad_code=$?
run check "$scratch/good" --json --strict > "$scratch/packaged-good.json" 2>"$scratch/packaged-good.err"
packaged_good_code=$?
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
labels = ["bad", "bad", "good", "good"]
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
