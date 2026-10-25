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

<!-- flow-run n=3 id=045c0d23a4514e5ea5a8ca4b9fe5551d -->
## Run 3

- Run-id:            045c0d23a4514e5ea5a8ca4b9fe5551d
- Run-start:         357095af692b72565e4273a14d0aab6a3c8fae04

- Issue: #568
- Base SHA: 357095af692b72565e4273a14d0aab6a3c8fae04
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: skillc-proof orchestrator, gate-568B3a-BB.md, durable revision15

### Section B - approved plan evidence

The following is the exact own BB Step3 plan approved by root, SHA256
eb34171688bab0357492b83f28be84c2557a257cf8ec8cb02d9372ee058dcac7.
Its pending-approval wording is retained as historical pre-gate text; the actual
attributable approval above and gate15 now authorize only its bounded scope.

# ELI5 Gate: BB fresh #568 B3a - pending root approval

## A. Intent

A future comparison can be misleading if the workflow cannot start in a clean environment. A file list does not show that supporting commands are installed where the workflow expects them or can actually run. This slice supplies a pinned profile, meaning an audited list of skills and supporting files, and proves its limited commands inside a new disposable container. Missing real agent/reviewer evidence remains an explicit stopping point; this does not prove the complete workflow or authorize a live study.

## B. Necessity and source evidence

Verdict: Partially addressed. Issue created2026-10-25T07:32:17Z. Actual fresh base357095af692b72565e4273a14d0aab6a3c8fae04. Post-filing commits inspected:6b78522/PR570 explicit product comparisons, b246435/PR572 B1 artifact task,357095a/PR573 closed scripted coordination. These do not provide current CPP87ecb097 profile installation or cold proof. Scoped profile/materialize/new-profile history has no post-filing solution. Both actual profile/materialize blobs match B1main (43838ba09e731db0fb7d25fbd20dce6273867f80/a25b66c66ae319b07e6eedbf0a7ab4875ec4aafc). Main357 push1111 is FAILED; CC owns actual #574 repair, which must be normally integrated before final full verification. No current-main readiness claim.

Today's merged PRs inspected573,572,570,567,565,564,562; only573/572/570 follow filing. Search considered568,258,247,245,542,554,20,315. Historical266/529/525/334/505 and current553/546/547 were considered from existing public plan; none supplies this specific pin/profile/cold delivery. The #567 fixture-only flow-check resume surface and older86641e8 flow-auto profiles are different scopes.18local sibling worktrees read successfully; none has unpublished relevant profile/materialize/new-cold path commits (BB-568B3a-sibling-evidence.json). Protected archives remain unchanged.

Independently compared every declared388 source file to actual immutable CPP87ecb0970f70aace9e0323feee00c9ca57dda133 Git bytes AND modes, total8,168,295bytes. Complete source manifest SHA256a12dce75f62cd1784ff0d426ec1ecdeb9d790cc98f60b22e9c670986a7a44f1c;397path lane SHA256b0b865c2ec530573cb7d489740c6ee81cc62925fd5f613e47ea1f8e547802dc4. BB-568B3a-source-inventory-verified.json records this independent check. No source exported, image built, profile installed or product test run. Existing normal validator copies all source skill files before selection; hence387read sources plus LICENSE388 differs from planned121installed files. Existing closure result cc176f64b98e0f4bb15d1ab53e10247c083b865d28df7694a87c73648ff04cde and missing-gate-lib refusal are AA's prior source-only facts, not BB cold evidence; BB must independently rerun applicable controls after approval.

Fresh actual flow run045c0d23a4514e5ea5a8ca4b9fe5551d, native session01a16fc2-3e17-7590-b1a5-40fb3710d1d6. Creation/verify/reconcile/read helpers used ONLY canonical CLAUDE_PID1102501/CLAUDE_CODE_SESSION_ID actualnativeID. Separate literal unprefixed git status --short was EMPTY before reconcile. Verify selfclaim uses actual identity. Readissue digest3313c2da0cec25a6e59eb7dc16e2263780d74f69e36c87b13b56ec8e8aaa93f7. Registry actually updated and read back to issue568/newcwd/complete2workflowpaths;571P registry lane dropped intentionally while its worktree claim/tree42ad remains cleanownedinactive. The committed older568 flow records are history, not this run's approval. AA's reviewed plan/design and inventory are reusable facts only; old gate grants no authority to BB. Refused574 and AA568 archives remain protected.

## C. Exact proposed file lane - pending root approval

397product paths (388unchanged pinned exports plus9authored) and2workflow paths. Each path has its own numbered description below. Pinned sources exported ONLY from the declared CPP commit, never hand edited. No arbitrary glob lane. README includes the full path/mode/digest manifest and licence/provenance.8,500,000pinned-byte ceiling and1500authored added+deleted lines INCLUDING JSON/table/provenance. Stop before expansion; no compressed unreadable JSON to evade the bound. No old profile/cold recipe/test, shared core, CLI, root Makefile or globalCI edits. Actual review receipt path separately granted only after actual independent review.

1. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/.claude/commands/flow/auto.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
2. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/.claude/commands/flow/eli5.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
3. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/CLAUDE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
4. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/LICENSE` - Copy the exact upstream87ecb097 licence notice; avoids repeating existing#553 snapshot notice gap.
5. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/README.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
6. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/browser-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
7. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/browser-session/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
8. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/browser-session/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
9. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/browser-session/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
10. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/browser-session/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
11. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/browser-session/scripts/playwright-desk.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
12. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-check/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
13. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-check/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
14. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-container/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
15. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-health/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
16. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-health/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
17. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
18. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-help/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
19. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-infra-discover/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
20. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-infra-init/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
21. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-infra-pipeline/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
22. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-init/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
23. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-init/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
24. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-pipeline/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
25. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-smoke/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
26. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-smoke/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
27. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-verify/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
28. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-verify/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
29. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-woodpecker/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
30. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cicd-woodpecker/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
31. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/claude-md-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
32. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/claude-md-lint/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
33. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/claude-md-lint/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
34. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cpp-dockers/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
35. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cpp-dockers/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
36. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cpp-happy-check/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
37. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cpp-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
38. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cpp-help/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
39. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cpp-load-best-practices/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
40. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/cpp-load-mcp-docs/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
41. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-c4/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
42. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-c4/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
43. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-c4/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
44. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-c4/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
45. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-c4/scripts/c4-mermaid.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
46. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-help/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
47. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
48. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-help/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
49. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-help/scripts/c4-mermaid.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
50. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-pptx/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
51. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-pptx/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
52. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-pptx/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
53. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-pptx/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
54. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/documentation-pptx/scripts/c4-mermaid.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
55. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-help/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
56. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
57. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-help/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
58. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-help/scripts/speckit-context.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
59. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-help/scripts/speckit-tasks-to-issues.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
60. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-issue/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
61. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-issue/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
62. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-issue/docs/agents/issue-contract.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
63. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-issue/docs/agents/knowledge-lifecycle.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
64. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-issue/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
65. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-issue/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
66. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-issue/scripts/speckit-context.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
67. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/evaluate-issue/scripts/speckit-tasks-to-issues.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
68. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
69. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
70. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/docs/agents/closing-report-contract.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
71. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/docs/agents/detector-contracts.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
72. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/docs/agents/flow-plan-record.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
73. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/docs/agents/issue-contract.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
74. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/docs/agents/knowledge-lifecycle.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
75. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/docs/decisions/0007-counter-model-review.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
76. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/docs/decisions/0008-instrument-negative-control-bound.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
77. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/docs/decisions/0009-oscillation-control.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
78. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/lib/vendor.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
79. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
80. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
81. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/check-ignored-additions.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
82. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/codex-skill-resync.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
83. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/codex-skill-sync.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
84. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/counter-model-receipt.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
85. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/counter-model-reviewer-attribution.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
86. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/eli5-vendor.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
87. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/flow-ci-status.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
88. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/flow-driver-capability.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
89. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/flow-finish-gate.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
90. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/flow-live-driver-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
91. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/flow-plan-record.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
92. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/flow-stale-check.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
93. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/flow-start-resolve.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
94. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/flow-worktree-claim.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
95. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/flow-worktree-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
96. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/friction-log.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
97. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/gate-lib.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
98. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/gh-pr-merge.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
99. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/hook-permission-census.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
100. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/nit-store-resolve.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
101. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/speckit-context.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
102. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/stash-worktree-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
103. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-auto/scripts/worktree-remove.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
104. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
105. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
106. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/lib/cicd/__init__.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
107. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/lib/cicd/evidence.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
108. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/lib/cicd/state.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
109. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
110. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
111. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/scripts/check-ignored-additions.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
112. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/scripts/counter-model-receipt.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
113. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/scripts/execution-evidence-verify.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
114. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/scripts/flow-finish-gate.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
115. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-check/scripts/gate-lib.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
116. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-cleanup/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
117. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-cleanup/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
118. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-cleanup/docs/decisions/0006-worktree-teardown-ownership.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
119. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-cleanup/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
120. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-cleanup/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
121. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-cleanup/scripts/flow-worktree-claim.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
122. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-cleanup/scripts/flow-worktree-sweep.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
123. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-cleanup/scripts/worktree-remove.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
124. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-deploy/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
125. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-deploy/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
126. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-doctor/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
127. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-doctor/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
128. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-doctor/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
129. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-doctor/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
130. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-doctor/scripts/flow-helpers-install.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
131. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-doctor/scripts/flow-worktree-claim.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
132. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-doctor/scripts/hook-mask-output.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
133. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-doctor/scripts/worktree-remove.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
134. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-eli5/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
135. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-eli5/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
136. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-eli5/docs/agents/closing-report-contract.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
137. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-eli5/docs/agents/detector-contracts.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
138. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-eli5/lib/vendor.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
139. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-eli5/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
140. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-eli5/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
141. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-eli5/scripts/eli5-core-drift.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
142. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-eli5/scripts/eli5-vendor.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
143. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
144. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
145. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/docs/agents/closing-report-contract.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
146. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/docs/agents/detector-contracts.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
147. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/docs/agents/issue-contract.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
148. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/docs/agents/knowledge-lifecycle.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
149. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/lib/vendor.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
150. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
151. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
152. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/check-ignored-additions.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
153. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/codex-skill-resync.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
154. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/codex-skill-sync.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
155. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/counter-model-receipt.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
156. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/eli5-vendor.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
157. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/flow-finish-gate.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
158. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/flow-stale-check.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
159. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/gate-lib.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
160. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/knowledge-graduation-check.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
161. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/nit-store-resolve.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
162. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-finish/scripts/speckit-context.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
163. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
164. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-help/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
165. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
166. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
167. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/docs/agents/closing-report-contract.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
168. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/docs/agents/detector-contracts.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
169. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/docs/agents/issue-contract.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
170. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/docs/agents/knowledge-lifecycle.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
171. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
172. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
173. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/scripts/counter-model-receipt.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
174. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/scripts/flow-ci-status.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
175. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/scripts/flow-finish-gate.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
176. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/scripts/flow-worktree-claim.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
177. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/scripts/friction-log.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
178. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/scripts/gate-lib.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
179. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/scripts/gh-pr-merge.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
180. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-merge/scripts/worktree-remove.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
181. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
182. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
183. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
184. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
185. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/scripts/flow-driver-capability.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
186. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/scripts/flow-vantage.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
187. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/scripts/flow-wave-lexicon.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
188. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/scripts/flow-wave-mailbox.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
189. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/scripts/flow-wave-registry.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
190. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-register/scripts/toolchain-provenance.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
191. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-repair/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
192. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-repair/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
193. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-repair/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
194. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-repair/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
195. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-repair/scripts/flow-helpers-install.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
196. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-repair/scripts/flow-live-driver-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
197. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-repair/scripts/flow-start-resolve.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
198. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-repair/scripts/stash-worktree-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
199. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
200. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
201. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
202. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
203. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/scripts/flow-live-driver-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
204. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/scripts/flow-start-resolve.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
205. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/scripts/flow-worktree-claim.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
206. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/scripts/flow-worktree-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
207. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/scripts/gate-lib.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
208. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/scripts/stash-worktree-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
209. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-start/scripts/worktree-remove.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
210. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-status/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
211. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-sync/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
212. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
213. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
214. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/docs/decisions/0006-worktree-teardown-ownership.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
215. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
216. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
217. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-driver-capability.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
218. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-pr-watch.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
219. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-vantage.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
220. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-wave-lexicon.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
221. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-wave-mailbox.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
222. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-wave-plan.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
223. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-wave-registry.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
224. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-wave-residuals.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
225. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-worktree-claim.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
226. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/flow-worktree-sweep.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
227. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/speckit-context.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
228. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/speckit-tasks-to-issues.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
229. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/toolchain-provenance.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
230. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts/worktree-remove.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
231. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
232. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-close/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
233. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-close/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
234. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-create/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
235. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-create/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
236. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-create/docs/agents/issue-contract.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
237. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-create/docs/agents/knowledge-lifecycle.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
238. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-create/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
239. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-list/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
240. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-update/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
241. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-update/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
242. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/github-issue-view/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
243. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
244. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-init/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
245. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-init/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
246. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-init/docs/agents/knowledge-lifecycle.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
247. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-init/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
248. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-init/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
249. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-init/scripts/project-init.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
250. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-init/scripts/speckit-context.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
251. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-init/scripts/speckit-tasks-to-issues.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
252. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-lite/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
253. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-lite/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
254. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
255. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
256. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/lib/project_next/__init__.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
257. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/lib/project_next/classify.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
258. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/lib/project_next/collect.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
259. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/lib/project_next/config.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
260. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/lib/project_next/models.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
261. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/lib/project_next/ownership.json` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
262. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/lib/project_next/rank.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
263. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/lib/project_next/render.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
264. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
265. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
266. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/project-next/scripts/project-next.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
267. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-help/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
268. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
269. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-help/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
270. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-help/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
271. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-help/scripts/qa-regression-export.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
272. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-test/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
273. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-test/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
274. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-test/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
275. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-test/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
276. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/qa-test/scripts/qa-regression-export.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
277. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/second-opinion-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
278. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/second-opinion-models/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
279. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/second-opinion-models/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
280. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/second-opinion-start/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
281. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/second-opinion-start/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
282. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/secrets-delete/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
283. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/secrets-get/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
284. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/secrets-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
285. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/secrets-list/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
286. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/secrets-rotate/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
287. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/secrets-run/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
288. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/secrets-set/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
289. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/secrets-ui/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
290. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/secrets-validate/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
291. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-deep/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
292. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-explain/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
293. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-help/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
294. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
295. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-help/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
296. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-help/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
297. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-help/scripts/classify-tool-risk.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
298. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-permissions/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
299. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-permissions/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
300. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-permissions/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
301. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-permissions/scripts/classify-tool-risk.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
302. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-permissions/scripts/friction-log.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
303. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-permissions/scripts/hook-permission-census.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
304. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-permissions/scripts/tool-risk-drift.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
305. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-quick/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
306. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/security-scan/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
307. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-deployment/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
308. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-deployment/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
309. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-help/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
310. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-retro/PROVENANCE.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
311. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-retro/SKILL.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
312. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-retro/reference.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
313. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-retro/scripts/SHA256SUMS` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
314. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-retro/scripts/friction-log.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
315. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-retro/scripts/hook-permission-census.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
316. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/self-improvement-retro/scripts/measurement-shape-scan.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
317. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/__init__.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
318. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/__main__.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
319. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/bootstrap.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
320. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/cli.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
321. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/config.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
322. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/container.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
323. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/coverage.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
324. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/deploy/__init__.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
325. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/deploy/docker_compose.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
326. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/deploy/guardrails.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
327. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/deploy/strategy.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
328. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/detector.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
329. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/evidence.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
330. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/failure_patterns.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
331. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/health.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
332. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/infrastructure.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
333. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/makefile.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
334. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/makefile_declaration.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
335. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/manifest.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
336. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/manifest_path.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
337. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/models.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
338. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/mypy_scope.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
339. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/outcomes.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
340. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/pipeline.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
341. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/pyproject.toml` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
342. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/runner.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
343. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/smoke.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
344. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/state.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
345. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/steps.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
346. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/cicd/verify.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
347. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/README.md` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
348. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/__init__.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
349. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/__main__.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
350. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/cli.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
351. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/config.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
352. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/explain.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
353. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/models.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
354. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/modules/__init__.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
355. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/modules/debug_flags.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
356. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/modules/env_files.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
357. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/modules/gitignore.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
358. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/modules/gitleaks.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
359. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/modules/npm_audit.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
360. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/modules/permissions.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
361. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/modules/pip_audit.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
362. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/modules/secrets.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
363. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/orchestrator.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
364. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/output/__init__.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
365. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/output/json_output.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
366. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/output/novice.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
367. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/lib/security/pyproject.toml` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
368. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/pyproject.toml` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
369. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/check-ignored-additions.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
370. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/counter-model-receipt.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
371. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/execution-evidence-verify.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
372. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/flow-ci-status.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
373. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/flow-driver-capability.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
374. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/flow-finish-gate.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
375. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/flow-live-driver-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
376. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/flow-plan-record.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
377. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/flow-stale-check.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
378. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/flow-start-resolve.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
379. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/flow-worktree-claim.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
380. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/flow-worktree-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
381. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/friction-log.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
382. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/gate-lib.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
383. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/gh-pr-merge.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
384. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/nit-store-resolve.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
385. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/speckit-context.py` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
386. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/stash-worktree-guard.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
387. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/scripts/worktree-remove.sh` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
388. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/uv.lock` - Copy exact pinned CPP source bytes and mode for the normal-validator snapshot; not a claim this file is installed.
389. `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/README.md` - Record upstream pin, licence, exact source path/mode/digest manifest and source-versus-installed proof boundary.
390. `evals/subjects/cpp-codex-flow-auto-87ecb097/subject.json` - Declare the actual87ecb097 Codex surface selection; client version remains a declared target, not runtime availability proof.
391. `evals/subjects/cpp-codex-flow-auto-87ecb097/profile.json` - Readable audited flow-auto/flow-eli5 closure, preferred and bundled stash siblings, tool probes, modes/checksums and explicit unsupported services/review boundary.
392. `evals/subjects/cpp-codex-flow-auto-87ecb097/README.md` - Document source validation, actual cold results and honest missing reviewer/session/full-workflow capability.
393. `docker/profile-flow-auto-568/Dockerfile` - Dedicated immutable-base cached/uncached cold images with Python, uv and explicit git/make/bash; public controller source inputs only, never an installed home.
394. `tests/test_profile_flow_auto_87ecb097.py` - Verify exact snapshot/source manifest, normal profile closure and committed missing/deformed declaration/source controls; no host installation.
395. `tests/test_profile_flow_auto_87ecb097_cold.py` - Opt-in serial physical Docker proof, actual in-container profile installation, ten-case accounting and bounded command/container cleanup; no live agent.
396. `evals/flow-auto-calibration-568/task-interface.md` - Record precisely what B3a proves and leaves unproven, preserving B2/546 and later runtime/prompt/selection obligations.
397. `changelog.d/568-b3a.md` - Describe the bounded current-profile/cold capability preparation, Refs#568 only.
398. `docs/flow-runs/issue-568.md` - Append this genuine BB run approval and validation history; preserve all earlier runs.
399. `docs/flow-runs/issue-568.as-read.md` - Normal helper snapshot of this BB run's actual issue read; preserve older snapshots.

### Implementation and exact proof boundary

Use normal subject/profile/DirTree validate against the exact snapshot; source-only checks may run on host, but EVERY actual profile.install call is inside the fresh container. Never install skills/tools/native home on host. Profile selects flow-auto and flow-eli5 with actual transitive helpers/references, preferred plus bundled stash sibling and literal tool probes. Record source count, selected surface,121installed files/modes separately from installed execution. Services and actual agent/reviewer execution remain unsupported.

Dedicated Dockerfile linux/amd64 immutable Python base python@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a and uv0.9.7 source ghcr.io/astral-sh/uv@sha256:68d029b921923c7234ef0178e669d6d253c8356153f1b54316df8cc3e15f5c01, subject to actual build identity confirmation. Explicit cached AND uncached build targets, common git/make/bash. Record actual package versions/image IDs, never call recipe a frozen study runtime. Public bounded context only: exact snapshot/profile and actual committed branch HEAD skillc controller bytes through Git export/byte checks; no installed home/private config/credentials/sessions. No bind mounts in positive runs. Cached alone warms uv sync --locked --no-install-project using exact CPP lock; record actual lock SHA in THAT layer. Uncached empty. CPP pyproject SHA256fe4b57ddb90f92793e0a1e45092d51bc28a7cfc048ae73ec00905cfed9ab00ed and lock0d7606bfd0efa1f58d5fa38386bde45cd63d75812c03cd0324bcd6f422ba6c32 independently bound by source export. Do not infer cache validity from tag. Build failures infrastructureUNKNOWN.

Request/receive serialized Docker slot before build/container execution. Actual in-container source validation/install/verify from immutable inputs, fresh tiny repo/worktrees for both preferred/bundled flow-start --verify. Observe each real sibling's STASH_GUARD; one route cannot conceal the other's missing guard. In writable cache tmpfs copy only that image's warmed cache; offline uv sync verifies actual installed/baked lock identities. Tiny active-test project invokes real lib.cicd check/check-plan, including failing-test twin. This is not full flow:auto finish.

### Ten committed cases and discrimination

1. source-valid-closure: exact388source path/mode/digests/licence and planned121installed files; mutated/missing/extra/empty source-manifest twins refuse the SAME classifier as positive.
2. source-missing-dependency: literal gate-lib dependency omitted => normal validate refuses; correct declaration passes. Independently execute, do not merely copy AA result.
3. cold-install-clean: actual container-only fresh install/files/modes, no host binds/inheritedoperatorhome/skills/MCP/secrets, only declared tmpfs. Actual install receipt is not model review evidence.
4. cold-sibling-route: BOTH installed preferred and bundled verify paths require installed/current stash protection. Missing-sibling twin at either route observes unknown despite other intact route. Preserve actual consuming-call red on committed120file pre-fix declaration before adding preferred guard for121file green; do not use only manifest count or APIabsence.
5. cold-content-drift: mutate installed helper byte, actual verify_installed violated; unchanged bytes positive. Pinned source unchanged.
6. cold-mode-drift: remove installed executable bit, actual verify_installed violated; original mode positive.
7. cold-offline-runner: actual lock agreement/offline imports/real nonempty check-plan green; deliberately failing tiny test red. Report command/tool evidence, not whole flow completion.
8. cold-cache-unavailable: uncached image yields specific absent offline distribution diagnostic; stale-lock marker refuses before resolution. Generic Docker failure cannot satisfy intended negative.
9. cold-forbidden-mount: bind ONLY owned synthetic sentinel; SAME actual inspect classifier rejects, no-bind positive. Omitted required resource/mount settings also challenge classifier. Never mount real operator data.
10. cold-review-evidence-absent: intentionally enrolled tiny repo without actual review receipt fails real finish gate. Actual receipt writer lacking implementer rollout refuses and writes no receipt; no fake ID/rollout/model/receipt, copied unrelatedreceipt or enrollment bypass. This is truthful fullflowUNPROVEN boundary.

All10top-level expected/executed identities and per-case/substep counts must match exactly; empty/missing/extra/duplicate/skipped physical population cannot certify. Knownbad/healthy inputs committed with loadbearing classifier. Infrastructure/capture/cleanup uncertainty UNKNOWN; intended observed bad condition distinguishes negative from unavailable. Default opt-in physical skips name precise reason, never count as cold proof. Actual delivery must run physical selection in granted slot.

### Budget, containment and evidence

ONE1800s monotonic endpoint begins BEFORE source/build staging, includes both builds, all cases, final evidence AND cleanup. Build cap300s each, case60s each, othercommand30s, clipped at every actual launch to SAME remaining; no launch after expiry, no success after late publication.1MiB per stdout/stderr file-backed stream,64MiB parent-owned staging/retention; exact bytes/count. Actual timeout/outputoverflow/expired-publication planted substeps with healthy twins must fail same wrapper, within ten cases rather than fabricated extra population. Per-case controller operations and subprocesses must share the case bound, not reset it. Teardown grace cannot earn completionPASS.

Serial actual runtime containers: networknone/read-onlyroot; memory512MiB AND memory+swap512MiB hard combined cap, CPU1,pids128. Exact tmpfs home256MiB, work/cache256MiB, tinyproject32MiB,tmp64MiB; sum608MiB mount maxima is NOT physical memory beyond512MiB. Inspect real settings including memoryswap/tmpfs; allocation failure honestUNKNOWN. No operator binds. Each image/container owned nonce+purpose labels, record actual IDs immediately, use measured immutable IDs, cleanup ONLY confirmed owned IDs/tags, confirm containers stopped/absent. No globalprune/daemonrestart/unrelatedimages/sharedcheckoutinstall. Build daemon/cache has no OSdiskquota/universalinterrupt claim; timed-outbuild without confirmed stop/ownedleftovers accounting =>UNKNOWN and return. Retain all early/failure cleanup outcomes.

Source/export/build/control/publication rows and report actual counts/digests/imageIDs/toolversions/limits privately, no host paths in committed reports. Final authoritative success only after identity joins/case accounting and cleanup inside originalbudget. Unknown or missing observations never replaced with expected values. At most2actual different-model review passes on authored diff +complete pinnedmanifest/exportequalityproof, full local source available; no claim to rereview all upstream semantics. Root must accept this review boundary for BB. Full verification serialized slot; normally integrate CC574 actual main repair before finalfullchecks, review conflicts with root. Exact-head CI/merge clearance separate.

### Workflow order, risks and residual

STOP at this ownStep3 until root reviews concrete plan. On approval: genuine begin-run, append approved fields/completeexactfileplan, helper approve/asread, workflow-only commit, supported ordinary+freshscope IDpreflight against COMPLETE ORIGINAL native rollout before ANY product export/build/install/tests. Ordinarymixed historicalmodel refusal may coexist with supported genuinefreshscope; stop on scopedrefusal, no aliases/remint/window/assertedmodel/historyrepair. No reviewreceipt fabricated. Early preflight is not countermodel review. Actual future receipt filename needs exactgrant.

Risks: 8MBsource includes every skill source read during discovery, not every installedfile; preserve source/install distinction. Readable manifest adds authoredlines;1500includes it. Coldcache/tag/skip can conceal unexecutedproof; actual immutable/offline and exactpopulation controls address it. Missing preferredsiblings require actual route, not bundledfallback green. Daemoncleanup/hostI/O not hardinterruptible; uncertainty remainsUNKNOWN. Existing snapshot notice/defaultstage rough edges already recorded under553/NitStore; do not widen this slice to oldfixtures. No material need for sharedcore expansion found.

B1artifact preparation shipped but main1111repair remainsCC574. B2services wait selected546 and real paired isolatedremotegrading. Fullflow actual model/client/reviewer/runtime, prompt/selection/equaltools/reviewcosts, sample sizing/rehearsal, heldoutcustodian and exactunapproveddeclaration/liveapproval remain. #568 and parents203/245 remainOPEN; Refs568 only. No task-success/latency/efficacy/readiness/live-study/consumerinstall/deploy claim or authorization. Keep571P42ad cleanownedinactive.

Approval REQUIRED from root on this BB run. No product work before exact gate.
