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
#   2. Still CHECK skills correctly. The packaged rule code (not the controls
#      directory) must still discriminate a known-bad SKILL.md from a known-good
#      one - one committed pair copied in, not the whole `controls/` tree.
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

# --- 2. the packaged rule code still discriminates --------------------------
mkdir -p "$scratch/bad/rotate-credential" "$scratch/good"
cp "$root/controls/trigger-shape/bad/rotate-credential/SKILL.md" "$scratch/bad/rotate-credential/"
cp -r "$root/controls/trigger-shape/good/." "$scratch/good/"

run check "$scratch/bad" --strict > "$scratch/bad.out" 2>&1
code=$?
cat "$scratch/bad.out"
[[ $code -eq 1 ]] || fail "check on the known-bad fixture exited $code; expected 1"
grep -q "trigger-shape" "$scratch/bad.out" || fail "the packaged checker did not fire trigger-shape"

run check "$scratch/good" --strict > "$scratch/good.out" 2>&1
code=$?
cat "$scratch/good.out"
[[ $code -eq 0 ]] || fail "check on the known-good fixture exited $code; expected 0"

echo "clean-install-check: ok - the packaged checker still discriminates good from bad"
