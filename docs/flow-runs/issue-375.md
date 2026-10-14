# Flow run record - issue #375

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=fd571ca0cf9f4980aa6515a51bd4d56b -->
## Run 1

- Run-id:            fd571ca0cf9f4980aa6515a51bd4d56b
- Run-start:         3f873954ccb8ebbf063b5c9fdb4f3824d91ade53
- Issue:             #375
- Base SHA:          3f87395
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          cooneycw (owner, interactive session); decisions taken as recommended: no-op = (a) untouched fixture graded FAIL; #376 aggregate-stop rows folded in
- Recorded at:       2026-10-14T15:30:00Z

### Section B evidence
Since filing: 558fe76 (#386), 3f87395 (#391), d94beb9 (#389), 6844ec5 (#388), cf6563d (#379), b6e238b (#378); none implements a production-path campaign. #376 item 6 shares the harness. #315 certified by campaign 2. PROVENANCE.md, eligibility-manifest.json and issue-270-271-completion.md all record the deterministic real-runner campaign as owed.

### Section C - the approved plan
PR A (this run):
1. `skillc/level3_campaign.py` - harness: scripted actor + candidate delivered into home, production run_one_attempt (closure, preflight, witness, capture, grade), per-row evidence and MATCH/MISMATCH
2. `skillc/cli.py` - `skillc level3-campaign --manifest --out`
3. `evals/level3/campaign-375/manifest.json` - frozen identities, caps, rows with exact expected per-criterion outcomes
4. `evals/level3/campaign-375/README.md` - how to run; claim bounds
5. `tests/test_level3_campaign.py` - offline fake-Docker rehearsal and red cases (wrong expectation MISMATCH, dropped witness UNKNOWN, real credential/agent refused)
6. `CHANGELOG.md` - entry
Then VM run; PR B: `docs/flow-runs/issue-375-campaign.md` record (+ any repair with its own pre-fix failure).
Population per task: PASS reference, 6 alternatives, benign/extra-comment; FAIL no-op(a), regression-outside-discovery, unconditional-green, swallowed-failure, swallowed-with-helper; INCONCLUSIVE profiling-disabled, isolated-child-gate, optimized-child-gate; plus #376 rows early-stop-reported-as-passed, skip-reported-as-pass, typecheck-failure-omitted, stale-evidence, proven-omission.
Scope: large (~600-900 lines PR A, ~1h VM).
Risks: production flow-check-honest may differ from qualification's synthetic witness (freeze from committed expectations + offline rehearsal before the VM run; disagreement investigated, never relabelled); dummy credential only, real-agent guard kept, refusal test; first non-test 86641e8 image build; multi-PR.
