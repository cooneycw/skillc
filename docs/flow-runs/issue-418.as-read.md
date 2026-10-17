<!-- flow-run n=1 id=51401220caf24bc1af8ca5a97985ba32 -->
## Run 1 - issue #418 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #418
- Read at:      2026-10-17T14:09:52Z
- updatedAt:    2026-10-17T14:09:41Z   (context only - moves on comments and labels)
- Body digest:  a71dcc5efbec64f99eabc0819602bcfe62bbb3224bff88782bc262d39af912c9   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3686 of 3686 (cap 16384)

### Body as read
## Problem

When an attempt is graded with a controller witness, `verify` builds the **trusted observation**: the canonical JSON `{"witness": <GateWitnessRecord>, "graded_tree_digest": <files digest>}` (`skillc/verify.py`, the grade-and-store path near `:1290`). It passes those bytes to `grade_files()` and records only their **digest** in the result (`verification.containment.trusted_observation_digest` and `verification.verdicts.deterministic.trusted_observation_digest`, `:944` and `:1323`). The bytes themselves are never stored.

So a result says "graded against envelope `sha256:f312…`", and nothing in the store can show what that envelope contained. That covers:
- each witnessed gate run's `tree_digest_at_start`, exit code and coverage;
- the per-stage outcomes `flow-check-honest` was graded against;
- the `graded_tree_digest`.

Measured on #315's runner, campaign `20261017T133805Z-b22d46` (42 witnessed attempts):
- 0 files in the run directory contain `gate-witness`, `tree_digest_at_start` or `flow-check-plan`;
- the recorded digest is found neither by file name nor by content hash;
- as a control, the same content search finds a known result file.

## Why it matters

- It is the unmet part of **#375 acceptance item 6** ("retain ... witness/envelope evidence") and **#376 item 2** ("capture **and retain** controller-protected per-stage outcomes"). See the accounting: https://github.com/cooneycw/skillc/issues/375#issuecomment-6234877331 and https://github.com/cooneycw/skillc/issues/376#issuecomment-6234877654. Neither issue can close without it.
- An auditor, or a regrade, cannot re-derive a `flow-check-honest` verdict from retained evidence. The evidence that decided it exists only in memory during grading.

This was first recorded in the Nit Store as low severity: https://github.com/cooneycw/skillc/issues/20#issuecomment-6225263167. It is promoted here at the orchestrator's ruling (owner-delegated), because it blocks two acceptance items.

## Outcome (the orchestrator's ruling)

- The controller writes the envelope bytes into the attempt's evidence store (the existing content-addressed `objects/`), under the digest the result already records. They are never written from the candidate's side.
- They are verifiable on read: a reader loads the envelope by that digest and gets the exact bytes, or a refusal.
- A later reader can re-derive each gate run's `tree_digest_at_start`, its stages and `graded_tree_digest` from retained evidence alone.

## Acceptance

- [ ] **Red case:** a test that FAILS on current `main` because, for a witnessed attempt, the store holds no retrievable envelope for the result's recorded `trusted_observation_digest`. It passes after the fix.
- [ ] **Negative controls:** a tampered stored envelope (bytes no longer hash to the digest) and an absent one are each **refused** on read, never silently trusted or treated as "no witness".
- [ ] The read path re-derives each witnessed gate run's `tree_digest_at_start`, its stages and the `graded_tree_digest` from the stored envelope alone, and they equal what grading used.
- [ ] Attempts graded without a trusted observation are unchanged: no object written, and no reader error for a result that records no digest.

## Constraints

- Reuse the store's existing object discipline (`trial._put_object` / `trial._read_object`: write-once, and refused when the bytes no longer match the name). Do not add a second blob store.
- `records.py` is untouched unless a record field is unavoidable. If one is, stop and ask (claude-power-pack#1369 pins it).
- No live model trials are authorized by this issue.

Found during the #375/#376 acceptance accounting (2026-10-17).

