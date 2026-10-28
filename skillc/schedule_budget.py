"""Minimum schedule overhead and exact pre-correction declarations (#546)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

# Twelve committed live attempts in:
# evals/matched-pilot/evidence/records/report.json
# evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/records/report.json
# Their total minus actual agent time equals setup plus grading. The maximum
# is 15.622 s (a-1c41825dc59e), rounded up to 16 s. This is an observed minimum
# allowance, not a worst-case guarantee; the agent limit was not exhausted.
MIN_ATTEMPT_OVERHEAD_SECONDS = 16

# These published declarations predate the correction. Preserve their frozen
# parsing/approval identities rather than rewriting historical studies. Each
# canonical WHOLE-declaration digest binds every field, including comments and
# approval. Paths are explanatory labels, never inputs to exception selection.
# Any mutation must meet the new allowance; no date/path/opt-in flag exempts it.
_HISTORICAL_NO_OVERHEAD = {
    'f3f0f43ed2b942846d4e534630ad3911f86a499570770cd73fd3845f02e12460': 'evals/calibration-203/run-manifest.json',
    'b16ed3375a4d504de49b6e7b608420701c103ce5b77ef9b8aa7d89c10b2d0d05': 'evals/calibration-203-c3/run-manifest.json',
    '61391eaaf78cba5b9cf9afbc805442e0d665378fd1f8003247f68c60cb9ad53d': 'evals/calibration-203-low/run-manifest.json',
    '32244df917158d708936129b784cf0717be6d37b031c755f3f8cffa81ab3b757': 'evals/calibration-287/auto6-pilot-declaration.json',
    '4eb7ba311256e82715f7cbbc0170de8910a5a27ed4cae7244f1a3fd0fdf49cd6': 'evals/calibration-287/auto6-precheck-declaration.json',
    '1c8fce7639383417e250e777ffc73b64ce360923e26109f756c832ec83be9734': 'evals/calibration-287/pilot-discrimination-declaration.json',
    '47a702e5b0fea516386e48448fdb81b45d20e3eb90ab1feea5421508fec1e9b6': 'evals/calibration-287/pilot-improvement-declaration.json',
    '7071d7a93c4525c4445cda35b44541f9934f429d63bbceee553dc3801986d6d2': 'evals/calibration-557-repeat/run-manifest.json',
    '7e0c90e8b31ceb4b9fc000a3cda9f70da5b94ebfe09d3968ce72028f6c2f47c7': 'evals/description-probe/agreement-broad/run-manifest.json',
    '50bc78bf76937cd4506563f30810ea826ba20718955e59a2b905fd669829e5d4': 'evals/description-probe/agreement-selective/run-manifest.json',
    'd0ab29961d8939231650f02821cb87bd80440220c176ab6e5b295f7d1f34ccba': 'evals/uptake-study/run-manifest.json',
    '5aba67d48be589b8a3c0ef924f4cdd784c38e25acd119690226c55a2cba32bd1': 'evals/uptake-study/selective/run-manifest.json',
}


def refusal_reason(declaration: Mapping[str, object], *, attempts: int,
                   per_attempt: float, total: float) -> str | None:
    """Return the budget refusal, retaining only exact frozen declarations."""
    required_overhead = attempts * MIN_ATTEMPT_OVERHEAD_SECONDS
    # Subtract before comparing so floating-point addition cannot erase the
    # allowance and accidentally accept equality for an enormous agent limit.
    if total - attempts * per_attempt >= required_overhead:
        return None
    try:
        encoded = json.dumps(dict(declaration), sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        # A non-JSON object cannot be one of the frozen JSON declarations.
        digest = None
    else:
        digest = hashlib.sha256(encoded.encode()).hexdigest()
    if digest in _HISTORICAL_NO_OVERHEAD:
        return None
    minimum = attempts * per_attempt + required_overhead
    return (f"shared.total_seconds {total:g} cannot cover {attempts} attempts of {per_attempt:g}s "
            f"plus {MIN_ATTEMPT_OVERHEAD_SECONDS}s per-attempt overhead (requires at least {minimum:g}s)")
