<!-- flow-run n=1 id=93c6a71fad2646c4a2ebba179ce91632 -->
## Run 1 - issue #202 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #202
- Read at:      2026-09-30T15:21:09Z
- updatedAt:    2026-09-30T14:37:51Z   (context only - moves on comments and labels)
- Body digest:  28719702d075f214456dee0265062914ec818b33b7275239c852388b5baf0b63   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2243 of 2243 (cap 16384)

### Body as read
Related: #150 (live run, PR #201), which moves its discrimination item to the effectiveness issue filed alongside this one. Promoted from the Nit Store: https://github.com/cooneycw/skillc/issues/20#issuecomment-5912835510

## Problem

A `collection-run` store keeps no agent transcript. In both #150 live arms, the store's `collection-conformance-*/spool/*.stdout|stderr` were 0 bytes, and `objects/` held only the ledger and records. The only record of what the agent read or did is the heuristic `skill_invocations` detector.

As a result, the #150 NORMAL PASS / DEGRADED PASS pair could not be diagnosed. The runbook's step 5 ("check first whether the agent read flow-finish at all (transcript)") could not be done, and whether DEGRADED passed on the model's default behaviour or through retained CPP content remains unresolved (`evals/discriminating-run/README.md`). Every later comparison has the same problem.

## Outcome

Every agent attempt retains the client's own transcript (for codex, the session rollout or `--json` stream; for claude, its session transcript). It is:

- stored content-addressed in the run store and referenced from the manifest's `observations`, with its coverage stated;
- leak-checked before retention, like every other exported file;
- included in the `--evidence` bundle when the export's role allows it. A transcript can hold subject content, so export is a choice made on purpose, not a default.

## Acceptance

- [ ] A codex `collection-run` attempt's store contains a non-empty transcript object referenced from the manifest. A regression test fails on the current code (no transcript retained).
- [ ] When no transcript was captured, the store and report say so explicitly, never as silent absence. Negative control: an attempt whose client produced no transcript records `coverage` as missing, not complete.
- [ ] The transcript is leak-checked. A planted leak in a transcript is caught and the export is refused.
- [ ] `skill_invocations` can be recomputed from the retained transcript, so the heuristic is checkable after the run.

## Constraints

- ADR 0005 applies: no live run is authorized by this issue.
- ADR 0005 rule 3: no machine identities in outputs, which is why the leak check matters.

