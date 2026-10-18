#!/usr/bin/env bash
# Reproduce a load-sensitive test under the #462 load harness, in bounded phases.
#
#   ci/load-repro.sh MEMBER TEST_ID REPS pre|post [CPU] [CHURN] [-- PYTEST_ARGS...]
#
# Runs TEST_ID REPS times (fresh pytest each rep) under CPU spinners (default
# 2x nproc) plus CHURN interpreter-start loops (default 0), split into phases of
# at most LOAD_PHASE_SECONDS (default and cap 900 s) with LOAD_PAUSE_SECONDS
# (default and floor 120 s) of no load between them. A phase whose load did not
# reach its target is INVALID and its reps do not count; after LOAD_MAX_PHASES
# (default 6) phases the run stops with whatever it counted.
#
# Writes docs/measurements/load-462/MEMBER-<sha12>-LABEL.json via
# `load_harness.py summarize`. Run ONLY inside a lock-1 hold.
set -euo pipefail

if [ $# -lt 4 ]; then
    sed -n '2,15p' "$0" >&2
    exit 2
fi
MEMBER=$1 TEST_ID=$2 REPS=$3 LABEL=$4
shift 4
NPROC=$(nproc)
CPU=$((2 * NPROC)) CHURN=0
if [ $# -gt 0 ] && [ "$1" != "--" ]; then CPU=$1; shift; fi
if [ $# -gt 0 ] && [ "$1" != "--" ]; then CHURN=$1; shift; fi
if [ $# -gt 0 ] && [ "$1" = "--" ]; then shift; fi
PHASE_SECONDS=${LOAD_PHASE_SECONDS:-900}
PAUSE_SECONDS=${LOAD_PAUSE_SECONDS:-120}
MAX_PHASES=${LOAD_MAX_PHASES:-6}
TARGET=${LOAD_TARGET:-$CPU}
if [ "$PAUSE_SECONDS" -lt 120 ]; then
    echo "load-repro: LOAD_PAUSE_SECONDS=$PAUSE_SECONDS is under the 120 s floor" >&2
    exit 2
fi

ROOT=$(git rev-parse --show-toplevel)
SHA12=$(git -C "$ROOT" rev-parse --short=12 HEAD)
PY="$ROOT/.venv/bin/python"
HARNESS="$ROOT/ci/load_harness.py"
OUT=${LOAD_OUT:-"$ROOT/docs/measurements/load-462/$MEMBER-$SHA12-$LABEL.json"}
WORK=$(mktemp -d "${TMPDIR:-/tmp}/load-repro-$MEMBER.XXXXXX")

HARNESS_PID=""
cleanup() {
    # The harness kills its own load group on SIGTERM; this makes sure it gets one.
    if [ -n "$HARNESS_PID" ] && kill -0 "$HARNESS_PID" 2>/dev/null; then
        kill -TERM "$HARNESS_PID" 2>/dev/null || true
        wait "$HARNESS_PID" 2>/dev/null || true
    fi
    echo "load-repro: exit $(date -Is) $(uptime)" >&2
}
trap cleanup EXIT
trap 'exit 143' TERM INT HUP

counted() {
    "$PY" - "$WORK" <<'EOF'
import json, sys
from pathlib import Path
n = 0
for p in Path(sys.argv[1]).glob("phase-*.json"):
    ph = json.loads(p.read_text())
    if ph.get("verdict") == "VALID":
        n += sum(r["outcome"] != "truncated" for r in ph["reps"])
print(n)
EOF
}

echo "load-repro: $MEMBER $LABEL $TEST_ID reps=$REPS cpu=$CPU churn=$CHURN target=$TARGET sha=$SHA12" >&2
phase_n=0
while :; do
    have=$(counted)
    [ "$have" -ge "$REPS" ] && break
    [ "$phase_n" -ge "$MAX_PHASES" ] && { echo "load-repro: stopped at $MAX_PHASES phases with $have of $REPS reps" >&2; break; }
    if [ "$phase_n" -gt 0 ]; then
        echo "load-repro: pause ${PAUSE_SECONDS}s $(uptime)" >&2
        sleep "$PAUSE_SECONDS"
    fi
    phase_n=$((phase_n + 1))
    "$PY" "$HARNESS" phase --cpu "$CPU" --churn "$CHURN" --target "$TARGET" \
        --reps $((REPS - have)) --max-seconds "$PHASE_SECONDS" \
        --out "$WORK/phase-$phase_n.json" -- \
        "$PY" -m pytest -p no:cacheprovider -q "$@" "$TEST_ID" &
    HARNESS_PID=$!
    wait "$HARNESS_PID" || true
    HARNESS_PID=""
done

mkdir -p "$(dirname "$OUT")"
"$PY" "$HARNESS" summarize --member "$MEMBER" --test-id "$TEST_ID" --label "$LABEL" \
    --sha "$SHA12" --out "$OUT" "$WORK"/phase-*.json
rm -rf "$WORK"
