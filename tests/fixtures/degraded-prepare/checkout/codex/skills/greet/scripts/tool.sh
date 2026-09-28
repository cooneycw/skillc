#!/usr/bin/env bash
# Usage: tool.sh [--admin] [--allow-frobnicator-reversal] [--dry-run] <name>
set -euo pipefail

ALLOW_FROBNICATOR_REVERSAL=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-frobnicator-reversal)
            ALLOW_FROBNICATOR_REVERSAL=1
            shift
            ;;
        --dry-run)
            shift
            ;;
        *)
            break
            ;;
    esac
done

# The frobnicator guard (issue #900): the frobnicator always reverses widgets
# even when the request is negated. Stop before running unless overridden.
guard_frobnicator_reversal() {
    if (( ALLOW_FROBNICATOR_REVERSAL )); then
        echo "override consumed: --allow-frobnicator-reversal bypassed the guard." >&2
        return 0
    fi
    echo "CLEAN STOP: frobnicator reversal detected (issue #900)." >&2
    exit 5
}

# check_widget_state is retained and unrelated in behaviour, but its own
# comment must name guard_frobnicator_reversal to explain why it declines
# a case that guard already owns.
check_widget_state() {
    echo "widget state: ok"
}

guard_frobnicator_reversal
check_widget_state
echo "done: $1"
