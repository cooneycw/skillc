# Issue #147 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #147
- Read at:      2026-09-27T18:49:55Z
- updatedAt:    2026-09-27T18:01:47Z   (context only - moves on comments and labels)
- Body digest:  87223adacbf4b943468d4826b3a8d41c8d0968e2892d8b9d1cab3d4c5f45a774   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2507 of 2507 (cap 16384)

## Body as read
Refs #12. This is the pinned re-run of #12's matched pilot. It was moved out of #141, where it had been added as an acceptance comment (https://github.com/cooneycw/skillc/issues/141#issuecomment-5858171797), so that #141 (PR #144) covers only the launch pin and this issue covers the evidence.

## Why

#12's first run (PR #140, experiment `matched-pilot-6ab82dc6`) has two problems:
- **Model deviation:** it declared `gpt-5.1-codex` and ran `gpt-6-astra`.
- **The bundle can never check clean:** its ledger pins the grader without a digest, and it predates stored results (#139) and observation records (#142).

Per the owner's decision 2(b) on #139, that bundle stays immutable, and the gap is scoped to that one experiment (`KNOWN_GAP_EXPERIMENTS`). The clean #12 evidence has to come from a new run.

## Blocked by

- #139 (PR #146): stored verified-results on the agent path, and the grader pinned with its digest.
- #141 (PR #144): the declared model (`gpt-6-astra`) passed at launch, and a run refused if an attempt observes a different model.

## Acceptance

- [ ] Run `skillc pilot-run` from main after both have merged, against the dated `gpt-6-astra` declaration from PR #144 (`evals/matched-pilot/run-manifest-2026-09-27-gpt-6-astra.json`). The run is a NEW experiment: 3 repeats x 2 arms, the same subject, task and caps as #12's declaration, and the operator's subscription login (ADR 0005 rule 6). No judge tier is enabled.
- [ ] Every attempt's observed model is `gpt-6-astra`. Any mismatch fails the run (#141's check), and a failed run is reported as such, not retried quietly.
- [ ] The new bundle sits in its own directory beside `evals/matched-pilot/evidence/records/`, which is left untouched. It passes `skillc check-records` with zero findings, and it is not covered by `KNOWN_GAP_EXPERIMENTS`.
- [ ] The closing messages are reviewed and merged as claims (`pilot-report --claims`), as on the first run.
- [ ] The evidence README states the per-attempt table, the matched comparison, and that a task PASS is stored on the agent path as a verified-result of INCONCLUSIVE (installation readiness UNKNOWN) while the report's `graded_status` is the task grade. It makes no qualification or broad-benefit claim.
- [ ] The live run is authorized by the owner at this issue's own plan approval. The authorization for #12's first run does not carry over.

## Owner

projects-fa, the session that ran #12's first run, as agreed on 2026-09-27 with projects-b8 (#139) and projects-95 (#141).

