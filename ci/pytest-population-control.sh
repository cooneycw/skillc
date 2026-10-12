#!/bin/bash
# Committed short report must fail, complete report must pass (#364).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES="$HERE/../controls/pytest-population"
if python3 "$HERE/check_pytest_population.py" "$FIXTURES/collected.txt" "$FIXTURES/short.xml"; then
    echo "pytest-population-control: FAILED to reject the short report" >&2
    exit 1
fi
python3 "$HERE/check_pytest_population.py" "$FIXTURES/collected.txt" "$FIXTURES/good.xml"
echo "pytest-population-control: ok - rejected short report, accepted complete report"
