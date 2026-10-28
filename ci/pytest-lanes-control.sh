#!/usr/bin/env bash
# Both lane reports are required; an omitted serial invocation must never pass.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
fixtures="$root/controls/pytest-lanes"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
cd "$root"
python3 -m ci.merge_pytest_reports "$fixtures/collected.txt" "$fixtures/ordinary.xml" "$fixtures/serial.xml" "$scratch/merged.xml"
for pair in 'ordinary.xml missing.xml' 'ordinary.xml serial-dropped.xml' 'ordinary.xml serial-duplicate.xml' 'ordinary-incomplete.xml serial.xml' 'ordinary-count-mismatch.xml serial.xml'; do
    read -r ordinary serial <<< "$pair"
    set +e
    python3 -m ci.merge_pytest_reports "$fixtures/collected.txt" "$fixtures/$ordinary" "$fixtures/$serial" "$scratch/merged.xml" > "$scratch/verdict" 2>&1
    code=$?
    set -e
    cat "$scratch/verdict"
    if [[ $code -ne 1 ]] || ! grep -Fq 'pytest-lanes: FAIL' "$scratch/verdict" || [[ -e "$scratch/merged.xml" ]]; then
        echo "pytest-lanes-control: FAIL - did not refuse $pair (exit $code)" >&2
        exit 1
    fi
done
echo 'pytest-lanes-control: ok - complete pair accepted; missing, dropped, duplicate, incomplete and count-mismatched evidence refused'
