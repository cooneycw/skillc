# Flow run record - issue #568

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=9c0619a9761c49b8a70e98a96eada1f9 -->
## Run 1

- Run-id:            9c0619a9761c49b8a70e98a96eada1f9
- Run-start:         1fcf690621d6d8fb091abafa17b56a134614e786

- Issue: #568
- Base SHA: 1fcf690621d6d8fb091abafa17b56a134614e786
- Necessity verdict: Needs reframing
- Approval: granted
- Approver: skillc-proof orchestrator, gate-568A.md / durable outbox rev 2
- Recorded at: 2026-10-25T08:02:00.939310+00:00

### Section B evidence
Verdict: Needs reframing into sequential 568A and 568B; this first slice is still needed.

Issue created 2026-10-25T07:32:17Z. Fresh worktree base: origin/main 1fcf690621d6d8fb091abafa17b56a134614e786. Both global and scoped git log since creation are empty. Same-day merged PRs #562, #564, #565, #567 all predate creation (latest #567 at 03:08:02Z); none provides the requested contract. Considered related issues #203, #245, #246, #259, #264, #274, #287, #346, #424, #508, #546, #547, #548, #557, #569; they provide prior contracts, provenance, applicable identity/retention/accounting gaps, or the separate coordination task, not this representation. No superseding issue found. All 13 local worktrees were examined for unpushed commits touching calibration.py, calibration_run.py, their relevant tests and protocol.md; none were found, with no unreadable worktrees (568A-host-necessity.json). BB has proposed work, not overlapping edits; shared ownership remains root's decision.

Actual source evidence:
- calibration._outcome_endpoint requires two matched-outcome arms without instructions (calibration.py:176-208).
- parse_declaration refuses a lone provided-skill arm unless a natural arm is added (calibration.py:545-641).
- build_report refuses named-skill arguments for a common outcome (calibration_run.py:1556).
- run_calibration already appends literal declared instructions to the public goal; plan_calibration snapshots the full common-outcome declaration into every trial config.
- Root's retained root-568-parser-probe.json proves the unchanged common-outcome declaration parses, while adding only instruction/named_skills to its treated arm is refused. This is a known-good/known-bad parser probe, not a live study.


### Section C - the approved plan
1. `skillc/calibration.py` - Closed opt-in explicit-product schema; preserve legacy approval and lane semantics.
2. `skillc/calibration_run.py` - Bind exact base prompts and actual treatment manifest/population before store/backend or direct planning; observational requested use.
3. `tests/test_calibration.py` - Committed parser controls and legacy compatibility.
4. `tests/test_calibration_outcome_endpoint.py` - Identity drift, refusal ordering and all-attempt observational reporting controls.
5. `tests/fixtures/calibration-explicit-product/cases.json` - Named accepted and rejected declaration/identity/report cases.
6. `docs/specs/evaluation-facility/protocol.md` - Specify explicit-product population, prompt boundaries and observational use.
7. `changelog.d/568-a.md` - Describe bounded support, retaining 568B acceptance.

Scope: 7 product/test/documentation paths plus this workflow record and its as-read snapshot; maximum 800 non-workflow changed lines. Root-approved sequential slice 568A only.

Add only an opt-in lane named explicit-product on kind calibration-declaration. It requires common-task-outcome version 1 and exactly two arms: baseline with null subject and no instruction/named_skills/inventory, plus one treated arm with a pinned subject/profile, nonempty literal instruction, and distinct named_skills. Existing whole-name instruction checks remain: flow-auto-extra does not name flow-auto. A third arm, an unnudged natural treated arm, an expanded-instruction arm, or missing common outcome is refused in this lane. Legacy lanes keep their current rules, historical declaration digests and narrow approval exceptions; no existing declaration is rewritten or reapproved.

Freeze an exact closed top-level explicit_product object, allowed only in this lane:
  version: integer 1
  prompt_digests: object whose keys are exactly the two declared arm names and whose values are sha256 digests
  selected_skills: sorted nonempty distinct skill names, representing every skill actually installed by the treatment; named_skills must be a subset
  installed_home_digest: sha256 digest of the canonical, sorted complete treatment home-file manifest [{path, digest, mode}], hashing actual bytes with the runner's effective default file mode
No arbitrary additional keys or placeholders. Include explicit_product in identity-root validation, full-declaration approval binding and each trial's existing immutable declaration snapshot.

Prompt semantics are frozen without changing legacy bytes: baseline receives the goal text as currently loaded; treated receives goal.rstrip() + two LF + the literal instruction + one LF. One helper composes these exact base-prompt bytes for both binding and execution. Their digests must equal prompt_digests before any run store/backend is opened. The instruction and named_skills are already bound literally by the whole-declaration digest. selected_skills must equal treatment.receipt_context.declared, installed_home_digest must match every delivered treatment home file/mode, and current per-skill body/description pins remain required. Missing receipt context or added/removed/mutated treatment bytes is refused. The direct planner must also require the actual Treatment for this lane and perform identity validation before creating a plan. Common inputs/caps stay in shared; the normal arm schema continues refusing per-arm models/tools/permissions/budgets.

This binds the declared agent goal and explicit-use suffix, including the evaluated installed selection. It does not claim to retain the later controller-generated canary instruction or subsequent approval turns: actual full prompt capture belongs to 568B and #547's applicable remaining slice. No runtime, image or client identity is invented in 568A.

Report semantics: derive the requested skill names from the bound declaration. Existing CLI callers may supply only that exact mapping; a conflicting or augmented post-run mapping is refused. Display named_skill_opened as an observation only. Failure to open the requested skill neither changes the task result nor removes the attempt from the primary denominator. Model/containment validity and all scheduled task outcomes retain current handling. Existing common-outcome lanes still refuse post-run named-skill eligibility. This is an explicit product-plus-instruction comparison, not a natural discovery or skill-value-only claim.


- Positive: new two-arm explicit-product declaration parses; common result can PASS even if named_skill_opened is false/unknown; named opening remains visible beside the result.
- Known-bad parser cases: implicit default lane with provided-only treatment; third/natural/expanded arms; missing endpoint; baseline contamination; missing/empty instruction or names; substring naming; extra/duplicate/unsorted fields or invalid digest; named skill absent from selected population; per-arm model/budget/tool overrides.
- Known-bad identity cases: goal, instruction, prompt digest, selected population, installed bytes/mode or approval digest drift, and missing installed receipt. All refuse before backend creation; run-path cases additionally assert no store is opened, and direct planner cases assert no plan is created.
- Known-bad report cases: conflicting post-run requested names, altered bound declaration, duplicated/missing outcomes handled according to existing reconciliation; correct code plus missing skill opening remains primary PASS and in denominator.
- Legacy golden declarations and existing tests continue accepting/rejecting their old shapes with unchanged digests/approval semantics. New-mode positive tests must fail on unmodified base due to refusal; report/regression tests are also run against pre-fix code. Save actual red results, not just a source inspection. Commit each gate's rejected input so another session can reproduce both verdicts.
- Run focused calibration tests, then the required project verification in root's shared-host slot. Existing selftest analysis run is 31/31; it is not credited as coverage of this future change.

Risks and challenge:
A permissive exception inside the old lane could silently change historical claims or approvals; a closed new lane avoids that. Treating skill opening as eligibility would select favorable treated attempts; observational-only reporting avoids that. Treatment.digest currently describes acquired source, not the full helper closure, so it cannot substitute for the new actual delivered-home manifest digest. Prompt base binding must not be mislabeled full prompt retention. Broadening this PR into paired GitHub fixtures or a new runtime would conceal the work still needed; keep that at a fresh 568B gate.


Outstanding: all 568B task/grader/profile/runtime/full-prompt/paired-execution/declaration/sizing/holdout acceptance; #568 stays OPEN. No live study, image approval, host install or deployment. Separate exact-head merge clearance required.

<!-- flow-run n=2 id=e83b7c171c574f7796007498759a85b2 -->
## Run 2

- Run-id:            e83b7c171c574f7796007498759a85b2
- Run-start:         6b78522a9e16baca33254dfc448a8cbc59e166d1

- Issue: #568
- Base SHA: 6b78522a9e16baca33254dfc448a8cbc59e166d1
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-proof root orchestrator, GO-WITH-CONDITIONS for B1 only, durable outbox revision 7
- Recorded at: 2026-10-25T08:51:59.607621+00:00

### Section B evidence

PR570 merged6b78522 after issue568 creation2026-10-25T07:32:17Z; it supplies
explicit-product comparison validation, not this artifact task or paired fixture
route. Inspected570 heads fe58347/a82a8af, prior main1fcf690 and earlier
PR567/565/564/562; those do not supply this new task. Related inspected203/204,
28,557,248,245/246,287,434 and505 do not supersede the bounded B1 slice.
All13 readable registered sibling worktrees had no relevant unpushed commits.
CPP621/624 database acceptance skips and CPP657 completeness loss ground the
failure class;557's floor remains ambiguity-bounded, without CPP causality.

### Section C - the approved plan

1. `evals/level3/change-with-regression-568/README.md` - Freeze the complete public CLI/API/validation/atomicity/history/testing contract from v2, control populations, artifact-only status and missing runtime bridge.
2. `evals/level3/change-with-regression-568/goal.md` - Describe the desired project feature/delivery result without CPP procedure; label which later service requirement is not certified by B1.
3. `evals/level3/change-with-regression-568/fixture/Makefile` - Run the common stdlib unittest suite without CPP-specific receipts or external database.
4. `evals/level3/change-with-regression-568/fixture/inventory.py` - Existing correct SQLite put/list API+CLI and deterministic schema initialization, with new batch feature absent.
5. `evals/level3/change-with-regression-568/fixture/tests/test_legacy.py` - Existing API/metadata/audit behavior through public interfaces, not private implementation details.
6. `evals/level3/change-with-regression-568/oracle.py` - Independently observe semantic outputs and database state; bounded exact-remote extraction using existing SafeTree/GitDir for trusted constructed export controls. No host mode for arbitrary candidate paths.
7. `evals/level3/change-with-regression-568/controls.json` - Literal public input/golden/expected dimensions and exact mutation preconditions/source references. Do not bury full Python programs in JSON or derive expectations from candidate code.
8. `evals/level3/change-with-regression-568/qualify.py` - Fixed24-case certification, expected population validation and strict process/output/temp/deadline/cleanup bounds; known blinding graders must be refused.
9. `evals/level3/change-with-regression-568/candidates/reference.py` - Literal reviewed full correct implementation using prevalidation and quantity-only transactional upsert.
10. `evals/level3/change-with-regression-568/candidates/alternative.py` - Literal independently structured correct UPDATE/INSERT+rollback strategy, satisfying the same public interfaces.
11. `evals/level3/change-with-regression-568/candidates/test_import.py` - Literal shared feature/property tests for both formats, late-invalid rollback and audit/history preservation; used with each valid implementation, not an implementation-pattern test.
12. `tests/test_change_with_regression_568.py` - Qualification controls, known-red pre-fix/mutant executions, alternate valid strategies, process-tree cleanup and remote-vs-local target proof.
13. `evals/flow-auto-calibration-568/holdout-reservation.md` - Disjoint expression-language family metadata, custodian pending/access boundary, no task body or held-out proof.
14. `evals/flow-auto-calibration-568/task-interface.md` - Source-grounded later paired-service/full-prompt/selection/retention blockers and B2/B3 boundaries, not a completed declaration.
15. `changelog.d/568-b1.md` - Artifact certification only and the specific next prerequisite, without calibration/live benefit claims.

Scope:15 product paths, at most2000 nonworkflow changed lines; required normal
workflow/as-read/receipt provenance separately accounted. No shared core, global
registry, root Makefile, profile/image/declaration/service-engine changes.
Exactly24 top-level controls,24 public semantic vectors per valid strategy,
six-implementation test-protection pack, four separately reported resource probes
and below-limit twins. Public semantics from the reviewed B1 contract are fixed.
Host execution only of reviewed committed fixture sources, never arbitrary
candidate code. Process groups/deadlines/output and parent staging budgets must
have actual controls; this is not an OS hostile-process/filesystem sandbox.
Risks: expectation coupling, implementation-coupled tests, clipped populations,
and constructed remote extraction confused with a dispatched paired service.
B2 service bridge and B3 full-prompt/runtime-selection/freeze/rehearsal remain;
reservation custodian pending, no held-out proof, no live study or automatic203GO.
Root reviewed plan SHA256446b3c0cdefa63bb8c1e9f8557f6b869e1237aaf0d5dd88f3a8a5f5d099fb3d8.

The genuine mint's optional stored session field is empty: the creation/claim
calls carried the actual native session, but reconcile did not. Root explicitly
authorized retaining this actual ID without state rewrite/remint; original native
events remain caller evidence. Subsequent begin/approve supply actual session.
CC run1 remains immutable history; this approval authorizes only run2/B1.
Workflow-only checkpoint and read-only original-rollout attribution preflight
were specifically authorized before substantive work. No synthetic review receipt.
