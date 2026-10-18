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
    # $3 (optional, #276): the diagnostic this fixture exists to trigger. A
    # bad fixture refused for some OTHER reason (a module the checker newly
    # requires, say) would prove nothing about the signal it is named for.
    local label="$1" report="$2" expect="${3:-}" out
    if out=$(python3 "$CHECK" "$report" 2>&1); then
        echo "git-tests-control: FAILED to catch the $label case ($report)" >&2
        exit 1
    fi
    if [[ -n "$expect" && "$out" != *"$expect"* ]]; then
        echo "git-tests-control: the $label case was refused, but not for '$expect':" >&2
        echo "$out" >&2
        exit 1
    fi
    echo "git-tests-control: correctly refused the $label case"
}

fail_case "partial-skip (a mixed file's git-gated subset skipped)" "$FIXTURES/bad-partial-skip.xml" "skipped for a git-mentioning reason"
fail_case "jq-skip (#276: every module still executes, but its jq-gated tests skipped for jq)" "$FIXTURES/bad-jq-skip.xml" "skipped for a jq-mentioning reason"
fail_case "make-skip (#434: every module still executes, but a make-gated test skipped for make)" "$FIXTURES/bad-make-skip.xml" "skipped for a make-mentioning reason"
fail_case "missing report" "$FIXTURES/does-not-exist.xml"
fail_case "malformed report" "$FIXTURES/malformed.xml"

echo "git-tests-control: good-all-ran must PASS"
python3 "$CHECK" "$FIXTURES/good-all-ran.xml"
# #276 pass 3: a neighbour's skip whose reason merely CONTAINS a tool name
# ("digital") must not change the verdict - tools match as whole words.
echo "git-tests-control: good-unrelated-skip must PASS"
python3 "$CHECK" "$FIXTURES/good-unrelated-skip.xml"

echo "git-tests-control: ok - caught all five bad fixtures, passed both good ones"
