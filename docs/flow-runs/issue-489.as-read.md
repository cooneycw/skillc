<!-- flow-run n=1 id=f129a2fad5174424b170b282a92b2171 -->
## Run 1 - issue #489 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #489
- Read at:      2026-10-24T22:54:11Z
- updatedAt:    2026-10-24T22:43:51Z   (context only - moves on comments and labels)
- Body digest:  151441f7f36b3218b714fe08f83df941f3c5e68ee7fe0fa8715ef870a3e4e165   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2861 of 2861 (cap 16384)

### Body as read
## Why

claude-power-pack's finish gate (`lib/cicd/outcomes.py`) sums the counts of
deliberate negative-control invocations into run-level `failed`, when they
share a step with the real suite. This repo's own `make verify` reported
`"failed": 311` next to `"status": "success"` (see PR #401's test-plan
note: "the gate's 311 'failed' are the deliberately red negative-control
invocations"). The real suite in that run was 4017 passed, 0 failed - the
311 is entirely attributable to this repo's own negative-control
invocations inside `ci/negative-control.sh` / `tests/test_negative_control.py`.

claude-power-pack#1503 fixed the CPP side: `lib/cicd/outcomes.py` now
recognizes a "control fence" convention and strips/relabels a fenced
invocation's counts instead of summing them into the real suite's
`failed`/`passed`. A harness wrapping ONE negative-control invocation
prints:

    ::cicd-negative-control:BEGIN:<BAD|GOOD>:<name>::
    <raw output of the invocation, unexamined>
    ::cicd-negative-control:END:<BAD|GOOD>:<name>::

`<BAD|GOOD>` is the harness's OWN declared expectation for that one
invocation (BAD = "this fixture should discriminate as bad", GOOD = "this
fixture should stay clean"). `<name>` is any label with no colons (e.g. the
control/rule name). The CPP-side parser DERIVES whether the fence behaved
as declared from the segment's own text - it does not trust the harness's
exit code alone - so a sloppy wrap still gets caught.

This repo's negative-control counts will keep inflating `make verify`'s
reported `failed` until `ci/negative-control.sh` (and/or
`tests/test_negative_control.py`'s own subprocess wrapping) emits these
fences around each of its per-rule invocations.

## Acceptance

- `ci/negative-control.sh` (or whatever wraps each rule's negative-control
  check) prints the BEGIN/END fence around each invocation's own captured
  output, with the correct declared BAD/GOOD and a stable per-rule name.
- After this, a `make verify`-equivalent run's reported `failed` no longer
  includes these invocations' counts; they appear instead under the new
  `control_*` fields (see claude-power-pack#1503's diff to
  `lib/cicd/outcomes.py` for the exact field names and derivation rules).
- A case where a fence's own declared verdict does NOT match what actually
  happened (e.g., a BAD-declared invocation that unexpectedly stayed clean)
  must still be visible in the output, not silently absorbed - this is
  derived automatically by the CPP-side parser once the fence is emitted
  correctly, nothing extra needed on this repo's side beyond wrapping
  correctly.

## Context

- claude-power-pack#1503 (the CPP-side fix this issue follows up on)
- claude-power-pack PR implementing it: see that issue for the merged PR
  number once available
- Originally reported via this repo's own PR #401's test-plan line quoted
  above
