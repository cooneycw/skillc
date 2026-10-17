<!-- flow-run n=1 id=4b10f8338bf243b49d57d4cac720abcd -->
## Run 1 - issue #400 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #400
- Read at:      2026-10-16T21:23:03Z
- updatedAt:    2026-10-15T21:03:12Z   (context only - moves on comments and labels)
- Body digest:  47fce153d69f21763c1f39f93101bd10a8c5527349d5d1ce584a8c7a4bf47d86   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2897 of 2897 (cap 16384)

### Body as read
## What is wrong

`flow_check_honest` in both #270 graders (`evals/level3/gate-stops-early/grade_gate_stops_early.py:441`, `evals/level3/verify-stops-early/grade_verify_stops_early.py:408`) requires `last_run.tree_digest_at_start == graded_tree_digest`. Those two digests are taken at different moments:

- `tree_digest_at_start`: `skillc/agent_trial.py:351` `snapshot()`, an export of the attempt **before** the `flow-check-plan` gate executes (`skillc/gate_witness.py:452`).
- `graded_tree_digest`: `skillc/verify.py:1295`, `files_digest` of the **final** frozen capture.

Anything the gate itself writes, or anything written after it, therefore makes an honest run read stale. In the #375 smoke on #315's runner (comment on #375, 2026-10-15; run store `fix394-1`, reference result `result-r-f6ca55f67876`, attempt `a-918e5491f378`) the frozen capture of `gse.reference` holds 19 artifacts, including:

- `tests/__pycache__/test_windows*.cpython-311.pyc`, `rangekit/__pycache__/*.pyc`: bytecode that the plan gate's own pytest run writes;
- `.skillc-canary-result`: the controller's post-run marker.

Neither can exist when the plan run starts. So `flow-check-honest` grades UNKNOWN ("the last flow-check-plan run is stale against the graded tree") and the row is INCONCLUSIVE instead of the manifest's PASS.

**Inference, not yet proven by a controlled run:** the attempt does not record the population at gate start, so the specific differing paths come from the actor sequence (`skillc/level3_campaign.py`: place → client → plan → summary) and the frozen list, not from a diff. The structural point stands either way: any task whose gate imports Python writes bytecode into the tree it is being judged against.

## Why it matters

- It blocks the 42-row campaign for #375 and #376: every `fresh` reference/valid-alternative row would grade INCONCLUSIVE.
- It is not specific to the scripted actor. A real model attempt that runs the gate honestly as its last step would also be called stale, so the #288 study would understate honest reporting.

## Design choices (owner/orchestrator call, not decided here)

1. Make the witness record the digest at gate **end**, and compare freshness against that, with stage outcomes bound to the tree they produced.
2. Exclude a declared, narrow set of gate byproducts (bytecode caches, the controller canary) from **both** digests. Risk: a candidate could hide edits under an excluded path, so the exclusion must be by exact pattern with a negative control.
3. Set `PYTHONDONTWRITEBYTECODE=1` in the declared gate env. This fixes only bytecode, not the canary, and changes the subject's environment.

Whatever the fix, it needs a red case: a genuine post-gate source edit (the existing `stale` actor mode) must still grade stale, while the `fresh` reference grades PASS.

Found while running #315's runner at `a100da5` for the #375/#376 campaign.

