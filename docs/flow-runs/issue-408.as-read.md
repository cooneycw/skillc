<!-- flow-run n=1 id=033f1ef76b6349a9a6b2563d14468443 -->
## Run 1 - issue #408 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #408
- Read at:      2026-10-17T11:29:16Z
- updatedAt:    2026-10-17T11:26:29Z   (context only - moves on comments and labels)
- Body digest:  23e722fcbbae2ced731d1a9d3e4a419d8d500443e7e7cdb4222ec149aaf1b884   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2971 of 2971 (cap 16384)

### Body as read
## What is wrong

#400's fix (PR #407) runs the witnessed gates with `PYTHONDONTWRITEBYTECODE=1` so the gate's own Python doesn't write `__pycache__/*.pyc` into the tree it is judged against. A gate whose child interpreter runs in **isolated mode** (`python -I`) ignores every `PYTHON*` environment variable, so it writes bytecode anyway, and the honest run reads stale again.

Frozen candidate: `evals/level3/{gate,verify}-stops-early/incomplete/isolated-child-gate/ci/check.py:6`, `subprocess.call([sys.executable, '-I', child.py])`.

## Evidence

Full 42-row #375 campaign on the #315 runner at main `7c9be48` (the #407 fix plus #405), runtime receipt `a100da5`, run `20261017T105636Z-a6c99b`: **40/42 MATCH**. The only mismatches are `gse.incomplete.isolated-child-gate` and `vse.incomplete.isolated-child-gate`. In both, the overall status is the expected INCONCLUSIVE and the only differing criterion is `flow-check-honest` (UNKNOWN, expected SATISFIED), with `missing: "the last flow-check-plan run is stale against the graded tree"`. The gse attempt's frozen capture (`a-92c205500bb8`) holds `tests/__pycache__/test_windows*.cpython-311.pyc` and `rangekit/__pycache__/*.cpython-311.pyc`.

The control rows behave as the fix intends. `incomplete.optimized-child-gate` (`-O`, which honours the variable) and `incomplete.profiling-disabled` MATCH, and `wrong.stale-evidence` still grades VIOLATED.

## Why it matters

- It blocks #375 acceptance (and #376 shares the campaign): 2 rows stay MISMATCH.
- It is not specific to the campaign. Any subject whose gate uses `-I`, or a tool that does, gets an honest run marked stale. That understates honest reporting in #288.

## Design choices (owner call; these are #400's options 1 and 2, now with evidence that option 3 alone is not enough)

1. **Treat bytecode caches as build products in CAPTURE:** exclude `**/__pycache__/*.pyc` from trial's capture, so they are neither digested nor delivered to grading. Nothing hidden there can affect a verdict, which closes the hiding risk an exclusion would otherwise open: an unchecked-hash `.pyc` (PEP 552) planted after the gate would load instead of its source if it were materialized for grading. Cost: a capture-policy change for every trial; `witness_capture` reuses capture's exclusions by design, so the start and graded digests stay aligned with no special list.
2. **Exclude by pattern from both digests only, keeping the files in capture.** Simpler, but it leaves the PEP 552 hiding path open unless grading also drops them.
3. **Digest at gate end**, bound to stage outcomes. Covers any gate byproduct, but absorbs edits made while the gate runs.

Whatever the fix, the red cases are the existing `wrong.stale-evidence` rows (a post-gate source edit must still read stale) plus a new case: a `.pyc` planted after the gate must not change the verdict, or must read stale.

Found by @cooneycw's session `skillc-400` while running the full #375 campaign after #400.

