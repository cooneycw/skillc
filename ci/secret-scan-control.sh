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
# Then the pre-push hook (#47) in a throwaway repo: a planted key pushed to an
# existing branch and as a new branch, buried under a clean commit, is refused
# and the remote does not move,
# a push with no gitleaks is refused, a clean push lands, and the installer
# will not overwrite a pre-push it did not write.
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

# The pre-push hook (#47), against a throwaway repo and a bare remote. A push
# the hook refuses must leave the remote ref where it was.
export GITLEAKS="${GL[*]}"
export GIT_AUTHOR_NAME=control GIT_AUTHOR_EMAIL=control@invalid
export GIT_COMMITTER_NAME=control GIT_COMMITTER_EMAIL=control@invalid
repo="$scratch/repo"
git init -q --bare "$scratch/remote.git"
git init -q -b main "$repo"
mkdir -p "$repo/ci/hooks"
cp "$root/.gitleaks.toml" "$repo/"
cp "$root/ci/hooks/pre-push" "$root/ci/install-hooks.sh" "$repo/ci/hooks/"
mv "$repo/ci/hooks/install-hooks.sh" "$repo/ci/"
git -C "$repo" add -A && git -C "$repo" commit -qm base
git -C "$repo" remote add origin "$scratch/remote.git"
git -C "$repo" push -q origin main || fail "hook: base push (no hook yet) failed"
base="$(git -C "$repo" rev-parse main)"

echo "#!/bin/sh" > "$repo/.git/hooks/pre-push"
(cd "$repo" && bash ci/install-hooks.sh > /dev/null 2>&1) \
  && fail "hook: installer overwrote a pre-push it did not write"
rm "$repo/.git/hooks/pre-push"
(cd "$repo" && bash ci/install-hooks.sh > /dev/null) || fail "hook: installer failed"

remote_main() { git -C "$scratch/remote.git" rev-parse main; }

echo "key = \"$planted\"" > "$repo/leak.py"
git -C "$repo" add leak.py && git -C "$repo" commit -qm leak
# Buried under a clean commit: a hook that scans only the tip must miss it.
echo "later" > "$repo/later.txt"
git -C "$repo" add later.txt && git -C "$repo" commit -qm later
git -C "$repo" push -q origin main > "$scratch/push.out" 2>&1 \
  && fail "hook: pushed a planted key to an existing branch"
grep -q "found a secret" "$scratch/push.out" \
  || { cat "$scratch/push.out" >&2; fail "hook: refused, but not for the secret"; }
[[ "$(remote_main)" == "$base" ]] || fail "hook: remote main moved on a refused push"

git -C "$repo" push -q origin main:leaky > "$scratch/push.out" 2>&1 \
  && fail "hook: pushed a planted key as a new branch"
grep -q "found a secret" "$scratch/push.out" \
  || { cat "$scratch/push.out" >&2; fail "hook: new branch refused, but not for the secret"; }

git -C "$repo" reset -q --hard "$base"
echo "clean" > "$repo/clean.txt"
git -C "$repo" add clean.txt && git -C "$repo" commit -qm clean
GITLEAKS=no-such-gitleaks git -C "$repo" push -q origin main > /dev/null 2>&1 \
  && fail "hook: pushed with no gitleaks (must fail closed)"
git -C "$repo" push -q origin main > "$scratch/push.out" 2>&1 \
  || { cat "$scratch/push.out" >&2; fail "hook: refused a clean push"; }
[[ "$(remote_main)" == "$(git -C "$repo" rev-parse main)" ]] || fail "hook: clean push did not land"

echo "secret-scan-control: ok - planted key found, canary allowlisted, tree clean, pre-push refuses"
