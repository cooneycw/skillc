# Flow run record - issue #536

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=bfaff44c62344e6b94602cebda83b6f2 -->
## Run 1

- Run-id:            bfaff44c62344e6b94602cebda83b6f2
- Run-start:         c80455538d4412391a375b76202f8c4ec6338be7

- Issue: #536
- Base SHA: c80455538d4412391a375b76202f8c4ec6338be7
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-complete orchestrator, GO-WITH-CONDITIONS for PR A items 1/2 only; B held, item 3 conditional
- Recorded at: 2026-10-24T22:30:36.719155+00:00

### Section B evidence
Verdict: Still needed for items 1, 2 and 4. Item 3 retains its explicit conditional disposition.

Since filing 2026-10-24T10:42:32Z:
- Commits/merged PRs: only 237ab8f / #558 since filing on main; it fixes a separate make-test environment and does not address these items. No post-filing commits touch fixture_live.py, agent_trial.py or gate_witness.py. Earlier inspected changes 80eca1d/#523, bbfb55d/#524, 653353e/#527, d846a69/#531, f280331/#532 and 5ece908/#534 explain the current steward, witness and report behavior but leave these gaps.
- Related issues inspected: #279 (open Step-6 work), #530 (closed flow-check route guard), #547 / pending #559 (retention dependency), #556 / #557 (export and owner's repeat, distinct work), #434 (CLOSED 2026-10-21T13:00:04Z; no resume authorization), #334 (closed earlier preflight/runtime gap), #26 and #287 (other studies). No superseding fix found. #309 is unrelated Docker-CI design, not gate-state inheritance.
- Host sibling evidence: the earlier wave-wide worktree inspection found only old unpushed 9caf33c (#348) touching witness plumbing; it implements runtime transport/readiness, not these items. Own #547 work adds diagnostic retention, not opt-in preflight, scan report fields or state inheritance. AA's CLI/export lane is active and must be coordinated before a CLI edit.
- No-spend reproductions on main: the real lifecycle guard refuses ['codex','exec'] without SKILLC_ALLOW_REAL_AGENT, and accepts exact value '1', without launching anything. There is no tracked live-launch opt-in preflight entrypoint; actor rehearsal substitutes actor argv before reaching the guard.
- Pure real report reproduction: build_report receives a record with transcript_codex_invocations=[] and transcript_files_found=1, but neither key appears in its attempt row.
- Real GateWitness state reproduction with a scripted backend: first plan starts clean with a readable source digest, the backend leaves .git/cpp-runs/check-witnessed.json, and the immediately following summary records 'unreadable: resumable gate state present at .git/cpp-runs'. The current guard has no witnessed-end-state distinction.


### Section C - the approved PR A plan
1. `skillc/fixture_live.py` - share the exact model/effort-pinned real argv builder between run_live and a no-launch preflight helper; that helper invokes lifecycle._refuse_real_agent against the actual current launch environment. Add transcript_codex_invocations and transcript_files_found to every attempt report row next to nested_codex. Preserve [] versus null and 0 versus null; never rescan or synthesize historical observations while building a report.
2. `skillc/cli.py` - add a narrowly named level3-live --preflight-launch-env path, before private-directory/image/credential/backend/run allocation. It checks the actual default real-client argv through the shared helper and exits; its output claims only the opt-in guard condition, never 'all preflight passed'. Reject combination with actor/dry rehearsal flags rather than test actor argv and call that real-launch readiness. Default live/rehearsal behavior and the launch-time guard remain intact.
3. `tests/test_fixture_live.py` - report regressions for observed zero, positive/unreadable scans, multiple transcript files and absent observation; pure guard preflight tests for missing/wrong/exact opt-in and exact pinned argv. Demonstrate the report omission red before changing production.
4. `tests/test_fixture_live_cli.py` - CLI missing/wrong opt-in refusal and exact-'1' success; assert no client subprocess, backend, credential, image lookup or private run directory is touched. Prove the live guard still checks again if the environment changes after a successful preflight.
5. `tests/fixtures/fixture-preflight/cases.json` - committed absent/empty/'0'/'true'/'1' environment inputs, with positive and refusal verdicts exercised by the real CLI/helper. Do not store a real environment or credentials.
6. `docs/specs/evaluation-facility/fixture-service.md` - narrowly scoped preflight meaning, same-environment usage and report field/unknown semantics.
7. `README.md` - document the no-launch flag next to level3-live; no claim that it authorizes a paid trial.
8. `changelog.d/536.md` - one issue-fragment bullet for items 1/2.

Privacy condition for item 2: scan hits include argv_head from RAW transcript input. Do not blindly copy credential-bearing free text into a retained report. Apply the existing retention/leak checks before persistence; retain the exact ordinary scan when safe. If unsafe/unreadable, write null plus an explicit bounded retention/coverage reason, never [] or a partial list pretending to be complete. Keep the live in-memory credit calculation unchanged. Add an unsafe-argv regression and do not print the unsafe value in diagnostics. V2 record schemas remain unchanged; these are additive report fields.

Scope: 8 planned files plus automatic workflow artifacts, approximately 300-500 lines.
Risks: unsafe raw argv text must not be persisted; preflight must claim only current opt-in and perform no launch side effects; zero and unknown must remain distinct. AA released the CLI lane; #560 keeps merge priority. No material concern beyond those conditions.


### Execution evidence (approved PR A scope unchanged)

Observed red before production edits: 11 regression failures, covering all five
CLI opt-in cases (the new flag was unsupported) and six report cases (fields
absent). Committed environment inputs cover absent, empty, `0`, `true` and
exact `1`; the actual CLI refuses the first four and accepts only the last.
The real lifecycle driver refuses after a successful preflight if the opt-in
is then removed. No image, credential, backend, private store or client is
used. Scan controls cover observed zero, safe positive, missing, unreadable,
malformed, unsafe identity and synthetic credential input, plus a safety-check
read failure; unsafe or unreadable input never becomes an empty clean scan.

Focused suites: 274 passed. Final strengthened CLI side-effect controls: 9
passed. Selftest: 31/31 discriminating. Lint, types, negative controls, type
scope control, leak check and controls, README drift, and secret scan/control
passed. No paid evaluation was run. Full-suite validation follows the wave's
shared slot and exact-head CI policy.

Counter-model review: measured `codex/gpt-6-astra`, reviewer thread
`01a1700e-2656-7282-a18d-9103f6af89ad`; no defects found. Report digest:
`sha256:5565289115d59d88f9b0af2dcf009dd40ce5f7dbb7d980e6bef3d43d2bd0aeb6`.
Scope probe: unverified (reviewer did read surrounding repository files);
network probe: blocked; repository-local credentials: absent. Under the
orchestrator's existing truthful-attribution disposition for this mixed-model
worker thread, no single-implementer receipt is fabricated: registration
included `gpt-6-astra`, while implementation is `gpt-6.1-sol`. The helper's
whole-thread attribution limitation is recorded in CPP Nit Store #864,
comment 6389865902. The review was performed, not skipped. This appended
execution evidence leaves the approved Section C unchanged; the plan stability
checker will truthfully flag the appended note.

### Actual receipt completion after CPP1558

The merged helper generated schema3 ran receipt docs/measurements/counter-model/2026-10-25T005520Z-issue-536.json
from the original fresh-run and review traces. Implementer codex/gpt-6.1-sol;
reviewer codex/gpt-6-astra; scope unverified, network blocked, local credentials
absent. Initial cleanliness remains unmeasured and approval execution unverified;
no anchors were reconstructed. Six whole report entries are proposed, zero
credited as already covered under the verified pre-first-proposal/all-subcases
standard. Zero does not claim that no existing controls covered those cases.
The prior full make verify EXIT0 and original outer missing-receipt EXIT1 remain
separate historical outcomes. Current-base integration and final CI remain held
until the #563 prerequisite merges.

Current main a924c5f00a9da21b87357764a979c9c6868340a5, including the merged
#563 trigger-directory correction, integrated cleanly. Approved product/test
bytes remain identical to the original reviewed head. Targeted integration
checks pass284/284 exact collected/JUnit identities via make test; raw log
/tmp/skillc-536-integration-check.txt. Original full make verify EXIT0 remains
retained; no redundant full rerun for metadata/disjoint base. Actual merged-helper
enrollment exits0 and audit-flow verifies the original captured prefix after
integration. Final remote full required CI and fresh exact-head/root/base
clearance remain necessary; no inherited merge permission.

<!-- flow-run n=2 id=623c5a4ddb334afba9b5769b019b7e13 -->
## Run 2

- Run-id:            623c5a4ddb334afba9b5769b019b7e13
- Run-start:         79fbaaffe5c22606d5356d268d0b42b74201f885

- Issue:             #536, item 4 only
- Base SHA:          79fbaaffe5c22606d5356d268d0b42b74201f885
- Necessity verdict: Partially addressed
- Approval:          granted
- Approver:          wave orchestrator, gate-536B-fresh.md, exact fresh base/run/103 paths
- Recorded at:       2026-10-25T01:58:03.889708+00:00

### Section B evidence

Items 1/2 landed in #562 at9a62b80979bf3e374049d0933f7e6822bb9d9cda.
Producer prerequisite CPP#1555/#1559 merged dd988219e056ddf23fb7ef5ba55e93979c07b61a
with full requiredPRCI3351 and main3352 SUCCESS. Item3 remains conditional on434
resume. Old profiles,536A history and frozen557 evidence remain historical.
New source closure is73upstream files/1511995bytes plusREADME; prospective profile
metadata is not a validated enriched inventory. Root verified allsource identities.
Fresh creation/independentemptyprobe/selfclaim/currentbase/newrun were measured.
PlannerEXIT0 retains historical issue-body contention fixture_live.py:[536,547];
no active file-lane collision exists. This scope excludes fixture_live.py and
no547parallelwork or scope expansion is authorized.

### Section C - the approved plan

1. `skillc/gate_state.py` - New stdlib-only bounded protocol validator, no-link state snapshots, attempt-local admission ledger and prior-stage reconciliation. No persistent trust registry.
2. `skillc/stage_capture.py` - Expose a shared strict single-document reader for the selected protocol mode, rejecting duplicate keys; preserve legacy defaults and keep carried rows null until the controller supplies matching prior facts.
3. `skillc/gate_witness.py` - Capture pre/end state under the existing execution lock, retain output before admission, bind witness order/stop/source/repository, attach optional state evidence and reconciled stages atomically; invalidate provisional leases on every late failure.
4. `skillc/agent_trial.py` - Pass the explicit optional protocol into the witness, export declared state paths at actual run boundaries, and keep source digest independent in opted-in mode. Preserve the old nonempty-state refusal for every legacy profile.
5. `skillc/profile.py` - One bounded optional gate_state_protocol block; validate version/family/plan/operation map against declared gate support and emit it only when declared, leaving historical inventories byte-identical.
6. `skillc/calibration_run.py` - Carry validated metadata through existing closure/Treatment only; build_treatment default-refuses protocol opt-in unless the private fixture capability is explicitly allowed. Normal calibration, discrimination and degradation APIs reject manually reused opted-in Treatments; no generic cc forwarding claim.
7. `skillc/fixture_campaign.py` - Forward the optional block only on supported fixture attempt_kwargs; preserve exact legacy kwargs when absent. Reject opted-in Treatment in unsupported campaign run_rows before scheduling. Document that argument parity with closed cc excludes the fixture-only capability.
8. `tests/test_gate_state.py` - New protocol/snapshot/admission controls driven by committed cases and real producer results, including every identity key and late failure.
9. `tests/test_gate_witness.py` - Real witness integration for execution-order serialization, queued operations with late retention failure, stale-generation invalidation, stop, partial execution, summary preservation and cross-run attribution.
10. `tests/test_agent_trial_gate_witness.py` - Exercise controller exports and protocol opt-in at the real session seam, including old-profile conservative behavior.
11. `tests/test_stage_capture.py` - Duplicate/malformed/unknown metadata and carried-stage contradiction controls; legacy output compatibility.
12. `tests/test_profile.py` - Closed optional field validation, missing/unknown opt-in, operation/argv mismatch, and unchanged old inventory controls.
13. `tests/test_calibration_run_profile_closure.py` - Verify inventory-to-Treatment binding, default refusal, allowed fixture capability and normal/discrimination/degradation API refusals without backend/agent/credit; preserve legacy behavior.
14. `tests/test_fixture_campaign.py` - Prove supported direct fixture propagation and unsupported direct campaign refusal; distinguish legacy cc parity without sending an unsupported keyword.
15. `tests/test_flow_check_route_task.py` - Semantic honest plan->plan regression with committed producer fixed; baseline must reach existing witness/reader/grader and fail SATISFIED, not fail from a new import/keyword. Exercise all four exact item-4 cases.
16. `tests/test_cpp_codex_flow_check_resume_v1.py` - New profile/snapshot identity, closure and licence checks at the actual merged producer revision.
17. `tests/fixtures/gate-state/cases.json` - Committed safe/bad inputs for shape, joins, seeded/no-op/replay/swaps, failure, export, output retention and cleanup controls.
18. `tests/fixtures/gate-state/README.md` - Describe which cases exercise actual producer+consumer and which inject a controller failure, including the trust bound.
19. `docs/specs/evaluation-facility/gate-witness.md` - Document state evidence/admission, inspection-only summary, exact source/key/stage bindings, bounds and explicit unsupported/forgery limits.
20. `docs/specs/evaluation-facility/profiles.md` - Document the optional bounded protocol/operation declaration, explicit opt-in and unchanged historical behavior.
21. `changelog.d/536-b.md` - Record item-4 consumer delivery only; item 3 remains conditional on #434 resume.
22. `evals/subjects/cpp-codex-flow-check-resume-v1/subject.json` - New immutable subject pin to the actual merged #1555 CPP commit; never retarget an existing profile.
23. `evals/subjects/cpp-codex-flow-check-resume-v1/profile.json` - Separate closure and explicit v1 operation declaration for the two exact supported gate calls.
24. `evals/subjects/cpp-codex-flow-check-resume-v1/PROFILE.md` - Pin provenance, gate map, source differences, explicit development-only scope without a live runtime claim, licensing and no retrospective credit.
25. `evals/subjects/cpp-codex-flow-check-resume-v1/evidence/inventory.json` - Generate from that exact merged source with normal profile validation; no hand-edited hashes.
26. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/.claude/commands/flow/check.md` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
27. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/CLAUDE.md` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
28. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/LICENSE` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
29. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/PROVENANCE.md` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
30. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/SKILL.md` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
31. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/lib/cicd/__init__.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
32. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/lib/cicd/evidence.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
33. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/lib/cicd/state.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
34. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/reference.md` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
35. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/scripts/SHA256SUMS` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
36. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/scripts/check-ignored-additions.sh` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
37. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/scripts/counter-model-receipt.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
38. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/scripts/execution-evidence-verify.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
39. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/scripts/flow-finish-gate.sh` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
40. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/codex/skills/flow-check/scripts/gate-lib.sh` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
41. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/__init__.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
42. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/__main__.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
43. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/bootstrap.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
44. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/cli.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
45. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/config.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
46. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/container.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
47. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/coverage.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
48. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/deploy/__init__.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
49. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/deploy/docker_compose.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
50. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/deploy/guardrails.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
51. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/deploy/strategy.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
52. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/detector.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
53. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/evidence.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
54. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/failure_patterns.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
55. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/health.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
56. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/infrastructure.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
57. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/makefile.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
58. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/makefile_declaration.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
59. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/manifest.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
60. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/manifest_path.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
61. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/models.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
62. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/mypy_scope.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
63. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/outcomes.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
64. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/pipeline.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
65. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/pyproject.toml` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
66. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/runner.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
67. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/smoke.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
68. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/state.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
69. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/steps.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
70. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/cicd/verify.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
71. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/README.md` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
72. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/__init__.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
73. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/__main__.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
74. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/cli.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
75. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/config.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
76. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/explain.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
77. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/models.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
78. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/modules/__init__.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
79. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/modules/debug_flags.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
80. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/modules/env_files.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
81. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/modules/gitignore.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
82. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/modules/gitleaks.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
83. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/modules/npm_audit.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
84. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/modules/permissions.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
85. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/modules/pip_audit.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
86. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/modules/secrets.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
87. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/orchestrator.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
88. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/output/__init__.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
89. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/output/json_output.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
90. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/output/novice.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
91. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/lib/security/pyproject.toml` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
92. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/pyproject.toml` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
93. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/scripts/check-ignored-additions.sh` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
94. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/scripts/counter-model-receipt.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
95. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/scripts/execution-evidence-verify.py` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
96. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/scripts/flow-finish-gate.sh` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
97. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/scripts/gate-lib.sh` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
98. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/uv.lock` - Copy exact final merged upstream bytes/mode; verify source identity. This is part of the new profile snapshot, not an edit to any historical snapshot.
99. `tests/fixtures/profile-cpp-codex-flow-check-resume-v1/README.md` - Record actual upstream source commit, closure-generation commands and MIT provenance; include the copied upstream LICENSE and bundled PROVENANCE notices.
100. `skillc/cli.py` - Only the existing fixture-live build_treatment call permits the private fixture capability; normal/discrimination/campaign/uptake defaults refuse protocol-opted profiles. Add no public option, declaration, runtime or actor behavior.
101. `tests/test_fixture_live_cli.py` - Test exact fixture-context permission and unchanged legacy CLI; unsupported contexts never acquire the permission or dispatch an agent. Do not falsely claim no earlier acquisition directory exists.
102. `skillc/uptake_study.py` - Reject any protocol-opted Treatment arm in the public run_study API before store/planning/backends/agent dispatch, including a manually reused fixture Treatment; do not drop metadata into closed cc dispatch.
103. `tests/test_uptake_study.py` - Negative direct-API reused fixture Treatment and unknown/empty opt-in cases must raise StudyRefused with no store/backend/agent/credit; legacy no-protocol twin remains supported.

Cost: 103 implementation paths, including every one of 74 snapshot files and
1,511,995 exact upstream source bytes, plus two automatic issue-536 run/as-read
records and one actual counter-model receipt. Estimate 1,000-1,600 authored lines
in source/tests/docs/profile metadata plus copied bytes. This is a concrete new
proposal, not an expansion of an old approval. Any extra path or materially
larger implementation returns to root before editing.

## Semantic red run with the producer held fixed

Place the acceptance regression in the existing test_flow_check_route_task.py
so baseline collection imports only old, existing APIs. Both before/after runs
execute the SAME committed producer snapshot at dd988219 and the same fixture
inputs; assert loaded producer module origin and bytes. Use isolated subprocesses
with an explicit snapshot import root and fresh bytecode cache, no host CPP
checkout, installed helper or unrelated lib-package fallback.

Build a disposable repository with deterministic real lint/test/typecheck commands.
First plan earns lint then fails test and leaves resumable state. A fixture-owned
external permit/counter makes the second invocation recover without a source
edit; assert that precondition and equal actual source hashes. Run the real
producer load/save and stages, not manually populated expected stage output.
Assert first generated identity equals the actual second consumed buffer, file
population, full retained output and confirmed gate stop before checking credit.

The regression driver uses the existing witness/session/reader/report APIs and
an explicit compatibility adapter only for activating the new optional context:
on old source, omit the unsupported new keyword rather than raising TypeError;
on new source, select the declared fixture capability. Do not import new product
modules unconditionally on the baseline. Baseline must reach semantic report
reconciliation and yield UNKNOWN/unattributable carried stages, causing the same
`report-honest == SATISFIED` expectation to FAIL. Record that actual assertion and
its reason. After implementation the identical producer and semantic expectation
must PASS. A missing module/import/keyword, skipped test or synthetic expected
output is not an acceptable red run.

Run baseline in a disposable archive of the pre-consumer source, copying only
the same test inputs/producer snapshot/semantic driver needed for that case.
The existing historical builder, grader and old-profile source stay unchanged.
Plan->summary may already preserve earlier plan facts on old source; report it
as acceptance/preservation coverage, not a fabricated regression fixed by B.

## Committed controls and concurrency

Exercise actual production producer + consumer boundaries with committed inputs:
- All four exact item-4 cases, including valid failed-state admission and honest
  current/inherited outcomes, with every stage reconciled rather than totals.
- Seeded first plan/summary, prior fact absent/wrong status, foreign repository,
  source, plan, profile or attempt, unsupported/null/empty/missing opt-in.
- Swap before actual load then restore before export; swap after actual save
  before export; change disk after selected load. Hash actual producer buffers.
- Unchanged seed/no-op and identical earlier stream cannot mint predecessors;
  safe no-op/summary preserve only a qualifying prior lease.
- Malformed/duplicate JSON/keys, missing/unknown fields/version, unsafe logical
  identity, boolean counts/version, overflow, unreadable/partial export, extra
  file, missing output/metadata, stop unknown and failed/short/later-failed save.
- State-error envelope diagnostics cannot credit stages; normal failed result
  with earned stages is its positive twin. Successful cleanup clears the lease;
  failed cleanup or recreated file does not prove surviving trustworthy state.
- Deterministic threading.Event barriers queue a different declared operation
  behind a run blocked in retention. Prove no second snapshot/exec/admission or
  premature inheritance while unresolved; late retention failure is processed
  before the next executes. A later valid generation survives a stale-sequence
  invalidation attempt. Include retention-success twin, and distinguish existing
  concurrent-same-gate refusal from genuinely queued operations. Test aliases
  stay test declarations; the real profile only grants its exact two calls.
- Normal/discrimination/degradation/campaign/uptake direct APIs refuse manually
  reused opted-in Treatments; default CLI construction cannot silently grant
  capability. Legacy twins remain supported. No unsupported backend/model launch.

Every negative fixture asserts its precondition. Wire-invalid cases and fault
injections are labelled; real producer accounting is never replaced by a stub.
These are offline deterministic development controls, not held-out effectiveness
or new trial results. New load-bearing behavior ships committed bad/good cases.

## Checks, review and stopping gate

After fresh approval: append this exact approved plan to a NEW run section and
stamp its baseline without changing #536A history. Implement only granted paths.
Normal profile validation generates the protocol-enriched inventory from the
actual merge pin; copy upstream files/modes and LICENSE exactly. Run source/
snapshot/installed-profile consistency, focused semantic reds/greens, selftest
and seeded privacy/security controls. Then coordinate a heavy slot for normal
full make verify; this new consumer implementation has no producer-only local
full exception. Exact-head required CI and root source/lineage review precede
merge. No bypass or fabricated identity.

Request ordinary independent counter-model review, at most two actual passes
for this new consumer implementation if root grants them, separately from the
zero behavioral-trial budget. Receipt counts only its actual new passes/findings;
prior #536A history remains separate. Enumerate whole review proposals and all
adversarial subcases; credit pre-proposal execution only with retained verified
mapping, otherwise zero. Default actual whole-thread identities must derive;
refusal is not a reason to invent scoped fields or skip.

No new runtime descriptor, invalid/null live declaration, image/receipt claim,
actor change, model/API judge trial, installation or deployment is included.
A future live run needs separately scoped actual runtime registration, image/
receipt/declaration/budget; these tests make no live-readiness claim. Keep CPP
producer checkout, BB archive and frozen #557/private evidence until their own
reader/cleanup authority permits otherwise.

STOP before begin/approval/product copying/review until root rules on this fresh
base/run, actual pin/closure and full 103-path scope. Extra paths, unsupported
source/route or inability to obtain a semantic pre-fix red returns to root rather
than silently widening or substituting a missing-API failure.


### Root approved conditions and contention disposition

GATE: GO-WITH-CONDITIONS #536
- Root approves the concrete103-path fresh536B Step3 at skillc base79fbaaffe5c22606d5356d268d0b42b74201f885, run623c5a4ddb334afba9b5769b019b7e13, producerdd988219e056ddf23fb7ef5ba55e93979c07b61a. Approved plan SHA256: 9cd32ebb24b1dabdf05db3ecf0154c09f86d8dace7c6574f179a80f5c6fdaa1a. Root read the full semantic plan and source call seams, independently verified fresh cleanHEAD/currentmain and all73 upstream modes/lengths/hashes (1511995bytes); merged producer tree equals reviewed6b74 treec531eb58. Prerequisites562/1559 are actually merged.
- Before begin, register the complete proposed103 implementation paths plus two workflow records with explicit skillc repo; add only the actual emitted receipt path later. AA/BB product lanes are empty. Preserve landed536A history; begin/approve/stamp this NEW run and retain exact approved Section C plus these conditions. No product scope beyond this plan; extra paths or materially larger implementation return to root. No host/helper installation or archive cleanup.
- Fixture-only support is the chosen boundary. Normal validator must produce the new inventory AFTER implementation from the exact source pin; prospective metadata is not validated evidence. Bind attempt/repository/source/profile-inventory/producer identity/family/plan/actual execution order through the actual verified closure route. The private factory capability alone is not identity evidence. Default/malformed/null/empty/unknown opt-in cannot silently activate or disappear. Normal/discrimination/degradation/campaign/uptake direct APIs must refuse reused opted-in Treatments before store/scheduling/backend/agent work; legacy behavior and inventories stay unchanged. Only existing fixture-live construction explicitly permits the fixture capability; no generic closed collection_conformance forwarding claim.
- Follow actual backend semantics: normal exited with non-bool integer exit and complete retained streams may admit with stop_confirmed None (N/A) or True; explicit False, malformed flags, non-exited/disrupted runs and incomplete output do not admit. Test the real production backend normal-result path preserving None, plus timeout None/False/True and invalid exit/output twins. No backend scope expansion or whole-candidate quiescence/authentication claim.
- Admission and all publication/invalidation remain under the existing execution lock through output retention/end export/completion stamp. Prior exact consumed/generated/state/source joins and actual attributable per-stage facts are mandatory; generated bytes alone earn nothing. Seeded/tampered/foreign/missing/unknown/error-envelope/no-op/replayed output must not invent fresh facts. Summary is inspection only. Deterministic queued late-retention failure and success twins must demonstrate no premature inheritance and no stale-generation invalidation of a newer lease.
- Required semantic regression holds the SAME real committed producer fixed and reaches old witness/reader/grader, failing the honest plan-to-plan SATISFIED assertion for unattributable carried evidence, then passing new consumer. Missing APIs/imports/keywords/skips are not a red. The compatibility adapter may only activate the new context when available. Assert unchanged source and actual load/save identity preconditions; external deterministic permit/counter is an explicit test fixture, not an effectiveness claim. All four item4 acceptance cases and committed bad/good wire/state/retention/route controls are required. Never substitute handcrafted successful stage output for the real producer.
- Root explicitly requests ordinary independent review of this NEW substantive consumer implementation, up to two actual CC passes only if the normal fix/review cycle requires the second. Reason for potential additional issue-level pass:536A already had one separate review of disjoint preflight/census work; this new consumer boundary needs its own review and, if findings require it, confirmation. Thus issue total is one historical BB plus one or two actual CC passes (max3), with actual CC receipt counting only its own passes and history/PR separately naming the total/reason. No fourth issue-level review without a fresh root ruling. Whole-entry pre-proposal execution credit requires retained verified mapping; otherwise record0, not static-inspection credit. Actual default whole-thread attribution/normal enrollment required, no fabricated fallback.
- CC owns the now-free local heavy verification slot after focused controls/selftest pass. Run the normal FULL make verify for this substantive new consumer; producer staged-local exception does not apply. Root source/control/lineage review, exact final-head required ci/woodpecker/pr/ci SUCCESS and strict currentbase remain merge prerequisites; merge clearance is separate. New failures require triage, no blind retries/bypass. No new behavioral/model/API-judge trial, runtime descriptor/build, declaration, actor change or deployment.
- PR must reference536 item4, not auto-close the full issue. After eventual merge check only item4; item3 stays conditional on434 resume and536 remains OPEN. Keep547 remainder/1367 advisory distinctions. Preserve old profiles, frozen557 checkout/private evidence and BB1555 protected archive. Producer/helper checkout cleanup waits until active readers finish and owned guards permit it.

The fresh planner exits0 but retains path_contention_active skillc/fixture_live.py:[536,547]. This is an issue-body-level warning, not an empty warning set. Root initially summarized the plan as clear; the precise disposition is that no live file-lane collision exists. Current536B approved103 paths do NOT include skillc/fixture_live.py; the issue body still includes already-merged536A items1/2.547firstthree delivered and remainingfour explicitly unassigned/parked; AA/BB registry product files are empty. No second worker may start547 or widen536B into fixture_live.py under this ruling. Re-plan on scope/assignment change. No ignored implementation collision or dependency waiver.


### Authorized test prerequisite amendment

The original approved103-path plan and approval baseline above are preserved. Root separately approved adding pyproject.toml and uv.lock (105implementation paths, plus two workflow records). This creates an expected plan-stability delta; it does not replace or silently restamp the original approval. Exact authorization:

GATE: GO-WITH-CONDITIONS #536
- Bounded scope amendment to gate-536B-fresh.md: add ONLY pyproject.toml and uv.lock, bringing implementation paths103to105. Root verified skillc AGENTS.md explicitly allows test/lint dependencies while requiring stdlib-only skillc/. Real committed CPP summary imports declared Pydantic, absent from current skillc dev environment; an import-failed summary is not acceptance evidence. CPP frozen uv.lock pins Pydantic2.12.5 and pydantic-core2.41.5; lib/cicd declares pydantic>=2.0. This is a test prerequisite, not a new product/runtime dependency.
- pyproject.toml may add pydantic==2.12.5 to existing optional dev dependencies with its snapshot-test purpose. Production dependencies remain empty and skillc/ remains stdlib-only. uv.lock must be generated normally, retain unrelated existing pins and include only necessary resolved dependency changes; no broad upgrade. Normal project-local uv sync/CI installation is authorized, no global/host helper install or image build. No dependency stubs, skipped acceptance or environment fallback to host CPP.
- The same pyproject path also needs the exact new vendored snapshot directory added to the existing mypy fixture-data exclusion list, since it contains repeated upstream lib/cicd modules just like the already excluded pinned snapshots. Scope ONLY ^tests/fixtures/profile-cpp-codex-flow-check-resume-v1/; do not narrow skillc/tests/ci authored-code scope or blanket-exclude new tests. Run normal typecheck and existing committed typecheck-control red/green to preserve that boundary. No other checker relaxation.
- Append this explicit amendment and its reason to the current run, preserve original103-path approval/baseline bytes/history, and register the COMPLETE105+2workflow lane before edits. Do not silently restamp away the original approved plan or claim unchanged stability when the authorized scope changed. Report exact scope delta/expected stability finding and manual authorized comparison if normal helpers require it. Actual receipt path remains routine later addition.
- Preserve semantic pre-fix red and the separate actual wrapper observation: first plan1/fail, resumed rawCLI0 becomes wrapper3/warn. Add real wrapper honest resume and summary acceptance after dependency setup; actual wrapper alone determines verdict. A transport launcher shim may route uv/python to the pinned snapshot, but cannot fabricate verdicts/stages. Import-failed summary remains a failed setup observation, not satisfied acceptance.
- All prior gate conditions remain: fixed producer pin, fixture-only route/refusals, true normalstopNone semantics, committedcontrols, fullmakeverify, boundedreview accounting, exact finalCI/rootmergeclearance,536item3open, no new trial/runtime/host/archive changes. Any further missing dependency/path returns with concrete evidence; independent already-approved stdlib consumer work may continue.


### Authorized review-control size amendment

The original estimate and approval remain preserved. Root separately approved the bounded size increase below for actual producer-boundary controls and namespace invalidation, with the same105-path ceiling:

GATE: GO-WITH-CONDITIONS #536
- Bounded implementation-size amendment only. The existing 105 implementation paths plus two workflow records remain the ceiling (actual emitted receipt may be added routinely later). Root read first independent review's two MEDIUM findings and concrete test plan; both concern the already approved admission/producer-boundary contract.
- Original estimated1000-1600 authored additions is exceeded to supply real producer load/save/cleanup fault joins and repository-state namespace invalidation controls. Current raw additions excluding vendored sources, workflow history and generated inventory are2075, including336 profile declaration lines and135 generated lock lines; remaining1604. CC projects1850-1950 additions excluding those declaration/lock categories after200-300 test fault-hook/control lines. Root authorizes that bounded size increase for these concrete controls and the narrow namespace fix, not a generic framework or new product capability. Report exact final counts and any material further growth.
- Producer snapshot bytes remain immutable. Fault injection lives in the isolated test launcher, invokes actual producer operations and retains their actual output; no fabricated successful stage/verdict substituted. Distinguish semantic pre-fix regression from new contract control, and preserve the observed namespace red cases.
- Preserve original plan/approval and append this amendment/reason. All prior fresh gate, dependency amendment, full verification, truthful review accounting and final exact-head CI/merge-clearance conditions remain. First review is static; whole-entry pre-proposal executed coverage gets zero unless supported by actual retained execution mapping. A second new CC review is already authorized after fixes; no third new CC review without a separate ruling.


### Authorized declarative protocol correction after full-gate failure

The first full make verify failed:7130passed5failed5skipped. The genericity guard correctly caught subject family/state literals, and the new early protocol guard displaced the legacy None precondition refusal. Original plan and failed verification remain preserved. The exact root amendment follows:

GATE: GO-WITH-CONDITIONS #536
- Root reviewed the full local failure:7130 passed,5 failed,5 skipped. Four failures correctly enforce the repository's generic-core invariant; one exposes legacy precondition ordering for intact=None. Preserve that failed run. No subject-guard exemption, skip, allowlist, string-obfuscation or checker change is authorized.
- Use the declarative option within the same105 implementation paths. Protocol version1 keeps the same closed runner wire format, operation vocabulary, plan check and exact two fixture routes. Move subject-specific family and state-directory identity into the validated profile: family is a bounded safe nonempty identifier, and add one mandatory state_path string restricted to a safe single directory below .git (no absolute path, traversal, links, empty or multi-path widening). The new pinned CPP profile explicitly declares family cpp-run-state and state_path .git/cpp-runs. Both fields flow from the revalidated inventory into immutable Protocol and its content-bound identity.
- Core validation compares producer metadata.family to the declared Protocol.family exactly; its closed version/field/status grammar remains unchanged. Ledger keys use the declared family. Dispatch compares the exact fixture.gate_state_paths tuple to the one declared safe protocol path, preserving all existing argv/stage/source-digest restrictions. Do not infer family/path from basename or silently default absent malformed fields. No existing profile opts in and no old profile/inventory changes. This changes where convention is declared, not permission to accept unmatched producer families or arbitrary runtime paths.
- Add committed controls for missing/unsafe state_path, malformed family, producer family different from declared family, and fixture state path different from the verified profile. Keep real-producer healthy resume/summary and seeded/tampered/fault controls. Revalidate the new inventory normally against immutable CPPdd988219; producer copies remain exact. Confirm genericity positive and planted-negative tests across all core modules now pass without modifying the guard.
- For run_discrimination, retain early rejection of a real opted-in Treatment; explicitly allow the legacy None test double to reach the existing precondition refusal. Do not weaken approval/precondition checks or permit consequential work with an invalid treatment. Existing failing test must go green unchanged.
- Append this architectural amendment and failure cause to run history; preserve original exact-family/path plan and disclose the move into declarations. No third new model review is authorized by this ruling. Root will independently inspect the narrowed propagation and controls; full normal make verify must be rerun after fixes, followed by exact-head required CI and separate merge clearance. Report any further path or material scope growth before extending it.
