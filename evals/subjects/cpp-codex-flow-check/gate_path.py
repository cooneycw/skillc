"""Subject-scoped interpretation of captured gate output."""

from typing import Literal

# Read from scripts/flow-finish-gate.sh at
# 85e9b03ad2af1c41020ff6d92d36fa257bdacd2b.
# Every re-pin must re-verify BOTH strings appear verbatim in that script,
# or this classifier can silently go blind.
REAL = "flow-finish-gate: running deterministic gate (lib.cicd run --plan"
FALLBACK_NOTE = "NOTE: deterministic runner unavailable"
FALLBACK_ACTION = "using Makefile fallback"


def classify_gate_output(text: str) -> Literal["real-runner", "fallback", "unknown"]:
    lines = text.splitlines()
    real = any(REAL in line for line in lines)
    fallback = any(FALLBACK_NOTE in line and FALLBACK_ACTION in line for line in lines)
    if real and not fallback:
        return "real-runner"
    if fallback and not real:
        return "fallback"
    return "unknown"
