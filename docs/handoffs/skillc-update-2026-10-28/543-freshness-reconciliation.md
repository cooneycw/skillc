# F0 production-path reconciliation — completed, no implementation disposition

Exact delivered source: `1a2821256e1d5089afc1bd87afa03384714b9a6c`. All 912 exported public source files match their pinned Git blob identities and their before-execution SHA256s. Lagging primary HEAD remains `1c7c4c73b22c666131d0bb38a3a7ccc79999b756`; no primary modules executed. External system Python ran with `-I -S -B`; no install, Docker, live/native model, suite, qualification, new flow/claim, issue write, or repository source change.

## Reused executed evidence, not rerun

Accepted final51c canonical full JUnit `/tmp/skillc-543-final-full-51c5337a/pytest/pytest-report.xml`, SHA256 `c8494389d13d1102ca98a977c4d409fdbe0047991a693f8f8cdd88c6c491d2ce`. Its tested source tree is delivered1a282. `reused-408-JUnit.json` records five actual PASS test IDs in `tests.test_capture_bytecode_cache`: cache exclusion/reason; sourceless and other cache-dir retention; cache-vs-code freshness; isolated-child gate-stops-early; isolated-child verify-stops-early. Also reused 21 actual PASS `tests.test_witness_capture` cases, including source/mode/population changes, projection/final identity, refusal, cleanup and duplicate boundaries. Zero repeated test executions. Historical #408 controls already distinguish cached bytecode from retained executable input. The old regular `__pycache__/*.pyc` allegation is not a current demonstrated defect.

## Actual path and consumer semantics

`agent_trial._WitnessSession.bind_and_check` exports controller-owned workspace output then calls `witness_capture.capture_digest`; `gate_environment` suppresses bytecode writes as an additional protection. Capture projection reuses `trial._export`, with the same exclusions and limits as final `trial.capture`. `trial.frozen_artifacts` validates frozen objects; `verify.witness_envelope` computes the graded identity with `witness_capture.files_digest(files)`. There was no raw `materialize.tree_digest(live_tree)` substitute in this diagnostic.

`GateWitness._decide_run_gate` snapshots immediately before execution and stores start identity plus actual backend completion. `stale_tree.last_run_is_fresh` compares the LAST run's start identity with the frozen grading identity. The old gate, verify and public-gate task duplicates compare the same identities. Their stage-attribution checks separately refuse stale runs before consuming stage records; equality is necessary, not a complete PASS predicate. Optional source_snapshot/source_digest is a different population and was not substituted.

## Ten named scenarios, each executed once

The ledger preserves every before/after digest, final frozen digest, captured path/content/mode population, stop evidence and available witness record. Nine populated scenarios used real `trial.plan`, allocation, confirmed-stop `run_attempt`, `trial.capture`, validated `frozen_artifacts`, and `files_digest`. All NINE final frozen digests equal their actual post-change capture projections. Diagnostic trial IDs are explicitly offline capture artifacts, not campaign or qualification results.

| # | Actual contrast | Result |
|---|---|---|
| 1 | Unchanged source plus actual fake-client canary and fixture report placed BEFORE gate | Real GateWitness + scripted backend subprocess exit0; freshness TRUE; three task duplicate checks TRUE |
| 2 | Add regular `__pycache__/module.cpython-311.pyc` | Identity unchanged; final manifest excludes it and records the bytecode-cache reason |
| 3 | Source edit after initial projection | Identity changed; final capture retains changed source; capture-only, no claimed actual preceding gate |
| 4 | Source edit INSIDE nominal-success backend execution | Real GateWitness start captured; subprocess exit0; final identity changed; freshness FALSE; all three duplicates FALSE |
| 5 | Owner executable bit change, same bytes | Identity changed; final mode `x` |
| 6 | Sourceless sibling `module.pyc` | Identity changed; bytecode retained |
| 7 | Non-pyc `__pycache__/note.txt` | Identity changed; file retained |
| 8 | Actual committed fake client writes canary from actual composed first-action instruction | File and agent-touch marker retained; unchanged subsequent projection/final capture; no gate execution |
| 9 | Change existing fixture report to observed-outcome-shaped report after projection | Identity changed; report retained; synthetic timing contrast only, NOT an honest full-task rejection reproduction |
| 10 | Empty population / deliberately over-budget file | Actual projection refuses both: empty population / incomplete projection; no fabricated digest or run |

Exactly TWO witness executions (scenarios1,4), ZERO complete grading executions, TWO standalone committed fake-client invocations (scenarios1,8; only scenario1 enters a witness execution). Nine trivial confirmed-stop capture-lifecycle subprocesses do not run candidate gates or graders. No retries. The backend adapter is an external explicit scripted diagnostic around actual bounded subprocess execution, not Docker or a replacement production transport. It exercises the actual public `GateWitness.decide` API. Witnesses have no staged gate capture and no controller output object sink: retained output is correctly marked missing. They establish freshness behavior only. In particular, scenario1's fixture report is not claimed semantically correct for its dummy command, and no complete candidate PASS is claimed.

## Canary/report producer ordering and disposition

Actual `trial_bootstrap.compose_canary_instruction` orders the tool write BEFORE ANYTHING ELSE. The committed fake client parses that instruction and writes `.skillc-canary-result` (plus `agent-touched.txt`) before returning. Actual `level3_campaign.ACTOR_SOURCE` normal/fresh ordering is `place(); client(); run_gate(plan-check); run_gate(summary)`; its stale mode deliberately puts gates before placement/client. Lifecycle canary verification reads the exported result; it does not produce a new candidate file after gates. Thus a synthetic late canary edit does not reproduce the supported instructed workflow. Both executed fake clients exit0 and leave the exact actual canary filename/content; retention alone creates no divergence when it precedes the gate.

The delivered public goal requires `report.json` to describe observed checks on the final tree. Its checker does not write the report. Report bytes are retained in both projections, so a candidate that changes those bytes after the LAST measured gate changes the identity being attested. Scenario9 measures that property, but does not execute an honest whole candidate or produce an actual task failure. The normal committed actor places candidate report bytes before its gates. This is a report-ordering/desired-contract question, not evidence that whole-capture equality itself is defective. A gate-time source change remains conservatively stale even with exit0, as the actual negative witness shows. Replacing start identity with only an end identity would lose that distinction.

No live desired-contract gap is established by F0. No source exclusion, semantic projection, end-only digest, bytecode patch, tracer patch or version increment is proposed as an authorized implementation. #543 remains open and its body/checklists unchanged.

## Limits and next scope

This was small offline production-capture reconciliation, not container integration, real-agent behavior, authenticated stages, complete grading or a relative-loader experiment. No absent-last-run runtime contrast was added beyond the ten-scenario cap; its None behavior was source-read only. No scenario was repeated to obtain green. Existing full JUnit supplies the already-executed isolated-child controls; this phase does not create new full evidence.

Smallest next step is a root contract decision: should a report updated after the measured checks invalidate whole-tree attribution, or should a future version explicitly attest a narrower, declared semantic population? Only if root selects and authorizes a changed contract should a separate Step3 scope freeze the precise population, task/runtime versioning, paths and real complete-candidate red/healthy controls. F0 supplies no basis to estimate patch paths/cost responsibly or to authorize it. Relative-loader T1 remains separate, awaiting its origin/versioning contract and actual red/healthy evidence. No further execution is needed in F0; #548/#544 reservations remain untouched.
