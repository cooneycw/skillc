# Issue #37 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #37
- Read at:      2026-09-26T15:30:21Z
- updatedAt:    2026-09-26T14:29:18Z   (context only - moves on comments and labels)
- Body digest:  c80ca6f4696e138d5949e8bfe6d1672ea0b5b6def3c63c903a4d28d190eba9c9   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2168 of 2168 (cap 16384)

## Body as read
## What is wrong

`skillc check-records` accepts a verified result whose `VIOLATED` criterion carries `"mandatory": "true"` (a string), and reports it clean with `status: PASS`.

`records.derive_status` selects mandatory criteria with `c.get("mandatory") is True`, so the string is treated as optional and the violation drops out of the population. The remaining mandatory criterion is SATISFIED, so the record derives `PASS` honestly, matches its declared `PASS`, and `derived-status` finds nothing. No rule checks that `mandatory` is a boolean (`criterion_vocabulary` checks only `outcome`).

## Reproduction (skillc 3c243a1)

```json
{"version": 2, "kind": "verified-result", "producer": "assembler",
 "attempt_id": "att-1", "trial_id": "trial-1", "result_id": "res-1",
 "grader": {"id": "g", "revision": "1"}, "graded_digests": ["sha256:00"],
 "status": "PASS",
 "criteria": [
  {"id": "ok",  "mandatory": true,   "outcome": "SATISFIED", "evidence": ["e"]},
  {"id": "bad", "mandatory": "true", "outcome": "VIOLATED",  "evidence": ["e"]}]}
```

```
skillc: 1 record(s) in 0 bundle(s) checked, 0 error(s)
rc=0
```

## Why it matters

This defeats the forged-verdict defence that `derived-status` exists for, and it does so by making evidence **disappear** rather than by contradicting anything. That is why no status-vs-criteria agreement check can catch it. A producer with one typo, or a subject that wants a PASS, gets a clean result through.

## Where it was found

CPP #1084. CPP's consumer (`scripts/check-behavioral-eval.py`) hit the same hole during its own counter-model review and now refuses a non-boolean `mandatory` as unreadable. While moving that consumer to records v2, each CPP control case was run through `skillc check-records`. This one is the only case skillc accepts that CPP refuses. The CPP fixture is `controls/behavioral-eval/cases/bad-malformed-mandatory-flag/`.

## Suggested shape

Refuse a criterion whose `mandatory` is not a real `bool` (in `criterion_vocabulary`, or a sibling rule), with a committed control. `isinstance(x, bool)`, not `isinstance(x, int)`: the same bool/int trap `record_envelope` already handles for `version`.

