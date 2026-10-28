# #546 exact checkpoint and ONE independent review

## Findings FIRST

**0 in-scope correctness/regression findings** in the whole three-product reporting change.

**1 supplemental P2, pre-existing and outside the diff:** `scripts/description_optimizer.py:151` ranks variants using `score or -9`, so a legitimate0.0 score is treated as missing and ranked below-0.5. With published-0.25, line165 can then incorrectly keep published and skip confirmation. The reviewer executed the actual exported AST ranking expression with synthetic0.0/-0.5 scores: variant-b(-0.5) ranked first, and published-0.25 beat the incorrectly selected score. This is a bounded source-expression result, not a study rerun or current campaign claim.

The distinct finding was delivered to root FIRST by native queue message01a18166-b7c4-7650-a2ef-0db2a162816d before this packet was sealed. No fix, new review, issue or Nit Store comment was made: this gate prohibits issue edits and directs findings to root for disposition. Do not silently drop it or represent it as recorded on GitHub. Root judges whether it becomes a required front-queue issue or supplemental disposition.

**New concrete control proposal families:1**, separate from findings/file/command/author-case counts: optimizer zero-score ordering, requiring0.0 to outrank negative scores and preventing erroneous keep with published-0.25. This was proposed by the reviewer, NOT an authorized repair or an executed regression suite. No receipt coverage mapping/preparation was performed.

## Exact checkpoint

- Commit `084c6880a56e5e925dd1c5760bf8a1fc137714b6`.
- Tree `0ce13507a4ce94c6690a5c551097d93fea9db6af`.
- Sole parent `16c6b4b65b5e0d35d72ae811163625d7cd8347a7`.
- Branch `issue-546-uptake-report-accounting`; run `7bdf309f5ea846c69b5e445e70109edf`.
- Exactly five paths, ordinary commit, no amend: skillc/uptake_study.py; tests/test_uptake_study.py; changelog.d/546-uptake-not-run-accounting.md; docs/flow-runs/issue-546.md; docs/flow-runs/issue-546.as-read.md.
- Tested five file hashes preserved; Git modes100644, no source edits after root acceptance. Product145A+D, workflow176, future receipt still unallocated with60-line reserve (205/300 product;176/250 workflow). Current worktree CLEAN before and after review.
- Canonical current-run `head-check 546 --head HEAD` was invoked AFTER creating the actual084c688 commit and BEFORE review launch; exit0/present with this run's section. HEAD resolved to084c688 then, not old base or an index/tree stand-in. No check was demanded on a nonexistent new section in base HEAD.
- Precommit normal guards: SELF; repo/exact5/policy3; default BLOCKING ignored0; strict worktree no-leak0; plan file agreement3planned/5touched and stability unchanged; issue drift clean; lane exact5/zero extra/ungranted/unclaimed/contested. Actual direct fragment_problem returned None for the new direct bullet. No tests/static checks were rerun merely for checkpoint.
- Physical checks before commit matched accepted five bytes/modes, offlane6231, strict389 physical membership/bytes/modes, and old Run1/Run2 prefixes. Old546 WIP was not mutated. No integration of incoming12db/main or changes to scope/baseline/approval timestamp.

## ONE actual independent review and provenance

Implementer identity was read from its canonical own rollout turn_context: native thread01a17cec-fab5-7860-b0e9-aeef446e1806, actual `gpt-6.1-sol`, effortmedium (latest context2026-10-28T07:18:30.839Z). Not a registry/request-only inference.

Reviewer launched ONCE with `codex exec`, requested `gpt-6-astra` and high reasoning, read-only configuration, fresh isolated exported source cwd. Actual reviewer native thread **01a18163-2345-7962-ae50-c7d8cf0243fc**. Canonical reviewer rollout turn_context independently observed by owner confirms actual **gpt-6-astra/high**, cwd `/tmp/skillc-546-reporting-review1/source`, approval_policynever, sandbox_policyread-only. The reviewer itself correctly noted it had not independently authenticated its own model; the owner's separate canonical-metadata check supplies that observation. Models genuinely differ.

Owner PTY/session **99664**; reviewer OS PID3038034/start37667739; supervisor PID3038031/start37667735. Launch argv/cwd/UTC/promptSHA and parent/supervisor witnesses retained. Actual raw stream has one thread.started, one turn.completed and no turn.failed/error; canonical rollout has one task_complete. Supervisor recorded actual OS exit0 at2026-10-28T07:25:12.489350Z, and the owner polled its session to terminal REVIEW_OS_EXIT=0. No interrupted process was converted to success.

Review artifacts are under `/tmp/skillc-546-reporting-review1`: full raw JSONL, stderr, final reviewer.md, task_complete event, actual model contexts, OS launch/terminal witnesses, all command items, scope prompt, checkpoint/source hashes and immutable source.tar. Source export contains6236 tracked files, byte/membership/readonly-mode checked after review. Actual five original working-tree files and bounded evidence copies remain unchanged. No original repo source writes, helper edits, native identity overrides, delegation or second review.

Configured read-only and read-only exported modes are observed controls, NOT proof of a global physical/network fence. Scope/network **UNVERIFIED**, credentials **UNKNOWN**. Some credential-related environment key names were removed and Git config isolated; this does not prove no credentials existed or network was impossible. Native actual source/provenance are retained without pretending stronger containment.

## Coverage and executed versus inspected evidence

Reviewer read ALL of uptake_study.py, test_uptake_study.py and the new changelog, plus the complete three-product diff. Inspected actual matched_pilot DISPATCHED/model_eligibility, calibration observation_confirmed/_opened, CLI uptake caller, optimizer and its tests. Explicitly assessed raw decided BOOL versus nullable cohort applicability; captured/inconclusive/known nonrun/unknown/unhashable dispositions; no execution/spend inference; unchanged selection/model/cells/primary statistics; both report branches; valid/legacy/partial-counter text behavior.

Author evidence was INSPECTED, NOT rerun: genuine old public API value red assert2vs1 + healthy twin; same2IDs green; actual partition-disabled2F1P incl text; force-all-decided3F; final103PASS exact collected/JUnit identities including optimizer compatibility; scoped static results; physical prefix/offlane/frozen proofs. No suites, project tests, qualification, full gate, Docker/client/model/version study, installs or network operations were launched by the reviewer.

There were18 completed command items, chiefly source/evidence reads, and exactly ONE tiny executed Python source-expression probe. Its exact command and output are preserved as command item19 in executed-command-provenance.json. It parses actual scripts/description_optimizer.py, extracts the `ranked` assignment expression, evaluates it on two synthetic variants and prints the ranking/published comparison. It does not execute the optimizer study, inspect private campaigns or infer model spend.

The approved preproduction timestamp correction and BOTH original/final stamps were included in the review prompt/evidence and inspected; finalbaselinecda68b92 stays unchanged. The accepted original blocking ignored3/exact own6-record5484B diagnostic archive/unlink proof was inspected without repeating cleanup. Source-only review is not independent runtime or historical physical verification.

## Stop

Checkpoint and ONE review are complete. No autorepair, review2, receipt prep/copy, integration, full, push/PR, issue edit, cleanup or claim release. Incoming main changes and broader546 residuals remain separate. Return this clean checkpoint plus findings for root judgment.
