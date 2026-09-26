#!/usr/bin/env bash
# Negative control for the secret-scan step: prove gitleaks can still say LEAK.
#
# The secret-scan step reads gitleaks' green on the checked-out tree. A scan that
# had gone blind (a config that allowlists everything, a rule set that failed to
# load, a scan of the wrong directory) prints the same green, so this step copies
# the tree, plants a key, and REQUIRES the finding.
#
# Leaks exit 3 (--exit-code 3), so a crash or a bad config, which exit 1, cannot
# read as a correct refusal. Three cases, each against a copy of this tree and
# the repo's .gitleaks.toml:
#   1. a planted AWS key under tests/ -> exit 3 (the allowlist is not path-wide)
#   2. the #8 canary under tests/      -> exit 0 (the allowlist entry still holds)
#   3. the unmodified copy            -> exit 0 (matches the step's own verdict)
#
# Why the step scans the tree and not history: Woodpecker clones --depth=1, so
# `gitleaks git` would scan one commit and report green. Full-history scans are
# run by hand (`gitleaks git . --log-opts=--all`).
#
# GITLEAKS overrides the command (default `gitleaks`). It is how this script was
# shown to fail against a stub that always passes.
set -uo pipefail

read -ra GL <<< "${GITLEAKS:-gitleaks}"
root="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

fail() { echo "secret-scan-control: FAIL - $*" >&2; exit 1; }

scan() {
  "${GL[@]}" dir "$1" --config "$root/.gitleaks.toml" --exit-code 3 \
    --no-banner --redact --log-level error > "$scratch/scan.out" 2>&1
}

copy() {
  rm -rf "$scratch/tree"
  mkdir "$scratch/tree"
  tar -C "$root" --exclude=.git --exclude=.venv -cf - . | tar -C "$scratch/tree" -xf -
}

# Assembled at runtime so this file is not itself a finding.
planted="AKIA""QX7ZL2MRWT4VJN6K"

copy
echo "key = \"$planted\"" > "$scratch/tree/tests/planted_secret.py"
scan "$scratch/tree"; rc=$?
[[ $rc -eq 3 ]] || { cat "$scratch/scan.out" >&2; fail "planted key: want exit 3 (leak), got $rc"; }

copy
echo "key = \"AKIAABCDEFGHIJKLMNOP\"" > "$scratch/tree/tests/canary.py"
scan "$scratch/tree"; rc=$?
[[ $rc -eq 0 ]] || { cat "$scratch/scan.out" >&2; fail "#8 canary: want exit 0 (allowlisted), got $rc"; }

copy
scan "$scratch/tree"; rc=$?
[[ $rc -eq 0 ]] || { cat "$scratch/scan.out" >&2; fail "unmodified tree: want exit 0, got $rc"; }

echo "secret-scan-control: ok - planted key found, canary allowlisted, tree clean"
