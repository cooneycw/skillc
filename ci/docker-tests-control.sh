#!/bin/bash
# Negative control for check_docker_tests_ran.py (#309): proves the checker
# can report BOTH verdicts, against committed fixtures - never against a
# live pytest run. Mirrors ci/git-tests-control.sh's #307 pattern exactly.
#
# all-skipped.xml and malformed.xml are REAL (not hand-authored): captured
# from an actual run in an environment with no docker binary, same as
# #307's own fixtures, then sanitized (hostname -> "ci", the absolute
# workspace path -> the XML-safe placeholder WORKSPACE_ROOT - never a
# bracketed placeholder, which breaks XML parsing inside element text).
#
# good-all-ran.xml is DELIBERATELY ABSENT here, not merely unauthored by
# accident: an authentic "every docker-gated test actually ran" report can
# only be captured against a real docker daemon, which this checker's own
# dev/prep environment does not have (that is #309's whole premise). A
# hand-crafted fake would violate the "every fixture is real" discipline
# #307 set and could be mistaken later for a genuine capture. Generate it
# once the dedicated agent (#315) exists and can run
# tests/test_decide_reply_channel_live.py for real, then drop it in here -
# this script picks it up with no code change once it exists.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES="$HERE/../controls/docker-tests-control"
CHECK="$HERE/check_docker_tests_ran.py"

fail_case() {
    local label="$1" report="$2"
    if python3 "$CHECK" "$report"; then
        echo "docker-tests-control: FAILED to catch the $label case ($report)" >&2
        exit 1
    fi
    echo "docker-tests-control: correctly refused the $label case"
}

fail_case "all-skipped (no docker daemon reachable)" "$FIXTURES/all-skipped.xml"
fail_case "missing report" "$FIXTURES/does-not-exist.xml"
fail_case "malformed report" "$FIXTURES/malformed.xml"

if [[ -f "$FIXTURES/good-all-ran.xml" ]]; then
    echo "docker-tests-control: good-all-ran must PASS"
    python3 "$CHECK" "$FIXTURES/good-all-ran.xml"
    echo "docker-tests-control: ok - caught all three bad fixtures, passed the good one"
else
    echo "docker-tests-control: good-all-ran.xml not present yet - see this script's header." \
         "Caught all three bad fixtures; the positive case is owed once a real docker daemon" \
         "is available to capture it (the dedicated agent, #315)." >&2
fi
