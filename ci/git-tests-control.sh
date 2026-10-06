#!/bin/bash
# Negative control for check_git_tests_ran.py (#307): proves the checker can
# report BOTH verdicts, against committed fixtures - never against a live
# pytest run, so this is fast and has nothing to do with whether git is
# actually installed right now.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES="$HERE/../controls/git-tests-control"
CHECK="$HERE/check_git_tests_ran.py"

fail_case() {
    local label="$1" report="$2"
    if python3 "$CHECK" "$report"; then
        echo "git-tests-control: FAILED to catch the $label case ($report)" >&2
        exit 1
    fi
    echo "git-tests-control: correctly refused the $label case"
}

fail_case "partial-skip (a mixed file's git-gated subset skipped)" "$FIXTURES/bad-partial-skip.xml"
fail_case "missing report" "$FIXTURES/does-not-exist.xml"
fail_case "malformed report" "$FIXTURES/malformed.xml"

echo "git-tests-control: good-all-ran must PASS"
python3 "$CHECK" "$FIXTURES/good-all-ran.xml"

echo "git-tests-control: ok - caught all three bad fixtures, passed the good one"
