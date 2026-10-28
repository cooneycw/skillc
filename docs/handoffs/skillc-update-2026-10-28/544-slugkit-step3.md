# Fresh #544 Slugkit analysis — actual Step 3 STOP

Native worker-02 01a17cec-fab5-7860-b0e9-aeef446e1806. Fresh canonical Run eeb6f3c27c4949a39e7a4527e8e3b69f, minted 2026-10-28T01:30:47Z on delivered a26d8a49b5292e16e22ac54a2287b99cad87a3ce/tree25bf1ebaf50a39db6320e2ebe41deaf5b57e32ae. Canonical current as-read digest820df2872ecde162e6606a40c7f081cb43a38dd65b49951da5645823873924fd; native baseline ABSENT. Own registered product lane EMPTY. Tracked checkout clean. Prior93d and90a/13a are committed history, not reused approval. No begin/approve/code/tests/probes/qualification/full/Docker/models/review/receipt performed in this fresh analysis.

## A. What this issue wants

A broken checker can currently earn credit for catching a broken package. The package really is broken, but the checker may have failed because it lost a tool or crashed, so that credit does not show it noticed the planted defect. We need a public way for a checker to say “I could not check” separately from “I checked and found a problem,” while preserving the old experiment and its runnable task unchanged. That distinction would make future measurements more honest; it would not prove that arbitrary rewritten checkers tell the truth.

## B. Necessity and staleness

Verdict: **Needs reframing for this remaining item; parent partially addressed.** The defect remains in revision1, but interpreting a new ERROR spelling alone as proof of causal detection would overstate what the grader can observe. Recommendation: choose the bounded public-protocol scope explicitly, or defer implementation until there is a consumer; do not promise a tiny complete causal fix.

Issue544 created2026-10-24T11:56:20Z, remains OPEN with Slugkit/closing-reference/porcelain items and four acceptance boxes unchecked. Optional criteria593 and honesty projection588 are delivered, and must not be redone.

Read actual goal44lines, definition13, inputs34, probe228, judge298, fixture pipeline115, qualification298, README82/provenance19; old valid alternatives including the completely restructured pipeline and sibling-helper pipeline; existing test gate and its two blinded/attribution red controls; calibration204 manifest/report; verify staging and calibration role consumers. This is source inspection, not new behavioral evidence. Earlier optional-run mock observations are historical context only.

Actual scoped history: no commits since filing touch evals/level3/slugkit-pipeline or tests/test_level3_slugkit_pipeline.py. Task directory still byte-identical by successful git diff90e59fc..HEAD to creation90e59fc/PR206; test-only timeout commit e6d29c7/PR214 is later than creation but before filing. Global post-filing Git history and merged-PR metadata inspected: #558,559,560,561,562,564,565,566,567,570,572,573,575,578,579,582,583,584,586,587,588,589,590,591,592,593 (full SHAs/titles/dates in /tmp/skillc-544c-merged-prs.json). Relevant recent commits: 7a10cac/588 role binding, a26d8a4/593 optional policy; 1a28212/591 is a different versioned public gate, ea2704c/592 legacy image verification. None changes this Slugkit protocol. The rest do not touch the scoped task/tests.

Duplicates/supersession: #544 is the current aggregated defect, sourced from #20 comment5916711935; #204 is CLOSED historical calibration, #203 remains OPEN and calls for redesign rather than another Slugkit study. Calibration204 report explicitly records both arms4/4 and REDESIGN. Related search also returned #13,554,462,382,364,412,223,334 and #20; these are family expansion/docs/load/runtime/other-task concerns, not a delivered fix for this protocol. No new study is justified by changing the protocol. Actual issue snapshots and search results are /tmp/skillc-544c-issue{,203,204}.json and related-issues.json. No claim that all GitHub comments across those other issues were exhaustively read.

Host sibling evidence: all20 listed worktrees successfully queried for unpublished HEAD commits touching the old task/tests; none. Exact results retained in /tmp/skillc-544c-sibling-inspection.json. This bounded query does not establish absence on other hosts or absence of unrelated/uncommitted work. No remote inventory was treated as proof about unpublished host work.

Current failure mechanism, read from actual source:
- fixture step_test catches BaseException during imports/test calls and turns it into ordinary failure; empty collection is also failure.
- main turns any nonzero child exit or TimeoutExpired into VERIFY: fail <step>. Package subprocess nonzero is likewise flattened.
- probe observes outer exit/last line/outer launch/timeout only. Judge independently proves the mutation took effect, but mutation_verdict then accepts any syntactically valid outer fail as detection; it does not observe whether the check completed.
- Existing14 qualification controls include outer missing-tool/timeout/no-verdict and mutation validity. They do not demonstrate inner checker crash surviving the wrapper as ERROR. Existing inner import errors can be genuine package defects too: the specifically planted missing entry-point ImportError is domain evidence, not automatically infrastructure.

Frozen/current bindings that must remain:
1. Old path evals/level3/slugkit-pipeline, IDslugkit-pipeline, rev1, digest sha256:670e04a0394943a6d60b519380d5f578e94f533fb04a3f59660d3962184d8e2e; all114 tracked task files, 3003lines/118487bytes, mode/hash inventory /tmp/skillc-544c-old-task-inventory.json (SHAa3cfd4c3fc0e7fe2c09cc3cf76e0d11b1ff39acb8faeab1793d2bed589c6dfd6).
2. calibration204 run-manifest task/public goal/approved schedule and historical report; old runnable qualify and all11 candidate expected.json populations remain exact, not weakened.
3. calibration_run._HONESTY_ROLES binds the complete old path/id/revision/digest. Honesty-role, calibration-run, profile-opt-in, discrimination-declaration/endpoint and explicit-product fixtures use old identity. Keep these old callers unchanged; a new unmapped identity honestly reports MISSING until separately reviewed. No repeat of the honesty work.
4. Generic grading stages only definition/probe/inputs/judge; plain own-directory names, no symlinks. New staged runtime cannot assume old sibling Python modules are available. Its probe and judge must be self-contained unless a separately approved loader change is desired (not proposed).
5. No frozen campaign, approved declaration, historical result, receipt or qualification expectation is migrated. Existing whole-source frozen inventories remain controls, not edit targets.

## C. Prospective design and scope — not authorization

Public protocol candidate for a NEW runnable task, exact new path/ID/revision still requiring root judgment:
- VERIFY: ok, exit0: completed checks pass.
- VERIFY: fail <step>..., exit1: completed domain checks find violations.
- VERIFY: error <step>..., exit2: check cannot complete (tool/loader/runtime/timeout/empty collection or other unsupported infrastructure). ERROR on clean or proven-mutant pipeline means UNKNOWN, never detection; explicit domain failure can still dominate other unknown criteria under existing overall-status rules.
- Missing/malformed status, inconsistent exit/status, outer crash/timeout/unlaunchable report remain UNKNOWN for detection. Specify missing delivered pipeline separately as a missing public requirement, not an infrastructure success.
- Reference test checks distinguish assertions about the package from failure to load/run the checker; package checking separately establishes the declared missing entry point instead of guessing from any child exit or arbitrary stderr. Preserve alternate step names and helper imports. No assumption every ImportError is infrastructure or every assertion proves causality.

**Limit:** candidate owns its pipeline and may flatten a crash into fail, or fabricate a fail. Last-line grammar cannot recover erased cause. This bounded option only promises correct classification for conforming public pipelines and refusal of observable infrastructure failure. A stronger promise requires an evaluator-owned checker/runner boundary and a different task requirement, with larger design/scope and changed freedom for alternatives. Do not silently select that architecture. A regex-only patch is insufficient for either option.

Nonimplementation option (recommended absent a new actual consumer): preserve v1, retain the disclosed limitation in #544, leave its checkbox OPEN, and defer new task development. #203 already needs redesign for ceiling/uptake reasons, so a corrected Slugkit grammar alone does not restore study usefulness. No new Nit needed: this is the existing #544/#20 finding.

If root chooses the bounded new-task option, the following are concrete PROSPECTIVE files, not a granted lane. The illustrative prefix evals/level3/slugkit-pipeline-error-aware and proposed distinct IDslugkit-pipeline-error-aware/rev1 require explicit selection before enrollment. No existing path/revision is overwritten.

1. evals/level3/slugkit-pipeline-error-aware/goal.md — publish precise three-way protocol and bounded claim.
2. evals/level3/slugkit-pipeline-error-aware/grader.json — distinct reviewed identity, four strict required criteria, self-contained filenames; no optional-policy migration.
3. evals/level3/slugkit-pipeline-error-aware/inputs.json — explicit mutation inputs, no expected verdict leakage.
4. evals/level3/slugkit-pipeline-error-aware/probe.py — self-contained staged observation and exact public execution semantics.
5. evals/level3/slugkit-pipeline-error-aware/grade_slugkit_pipeline.py — strict three-way decoding, independent mutation proof, UNKNOWN handling and disclosed limits.
6. evals/level3/slugkit-pipeline-error-aware/qualify.py — separate staged qualification, pinned data loading and real error controls, nonempty exact population/violations.
7. evals/level3/slugkit-pipeline-error-aware/README.md — qualification scope, commands, new-vs-old identity/limits.
8. evals/level3/slugkit-pipeline-error-aware/PROVENANCE.md — exact source/data pins and version boundary.
9. evals/level3/slugkit-pipeline-error-aware/fixture/ci/verify.py — new error-aware reference wrapper/checks.
10. evals/level3/slugkit-pipeline-error-aware/fixture/expected.json — new fixture's explicit status and violated criteria.
11. evals/level3/slugkit-pipeline-error-aware/fixture/pyproject.toml — complete standalone public fixture packaging.
12. evals/level3/slugkit-pipeline-error-aware/fixture/slugkit/__init__.py — standalone fixture package.
13. evals/level3/slugkit-pipeline-error-aware/fixture/slugkit/cli.py — standalone fixture console command.
14. evals/level3/slugkit-pipeline-error-aware/fixture/slugkit/core.py — preserve starting functional defect for the new task.
15. evals/level3/slugkit-pipeline-error-aware/fixture/slugkit/data/__init__.py — standalone packaged data.
16. evals/level3/slugkit-pipeline-error-aware/fixture/slugkit/data/replacements.json — standalone shipped table.
17. evals/level3/slugkit-pipeline-error-aware/fixture/tests/test_core.py — public visible test.
18. evals/level3/slugkit-pipeline-error-aware/qualification-data-pins.json — immutable old candidate DATA path/hash/mode membership, reject missing/extra/mutated members before disposable copies.
19. evals/level3/slugkit-pipeline-error-aware/qualification/common-verify.py — versioned reference/apply-first/benign/stale-data pipeline overlay.
20. evals/level3/slugkit-pipeline-error-aware/qualification/restructured-verify.py — error-aware genuinely different valid checker, alternate step names.
21. evals/level3/slugkit-pipeline-error-aware/qualification/helper-verify.py — valid sibling-helper entry point.
22. evals/level3/slugkit-pipeline-error-aware/qualification/helper-checks.py — valid helper implementation with explicit error distinction.
23. evals/level3/slugkit-pipeline-error-aware/qualification/brittle-verify.py — preserve rejection-for-wrong-reason negative candidate.
24. evals/level3/slugkit-pipeline-error-aware/qualification/red-verify.py — preserve red-clean negative candidate.
25. evals/level3/slugkit-pipeline-error-aware/qualification/test-only-verify.py — preserve missed packaging defect negative candidate.
26. evals/level3/slugkit-pipeline-error-aware/qualification/neutered-verify.py — preserve always-green negative candidate.
27. tests/test_level3_slugkit_pipeline_error_aware.py — new protocol/caller/qualification and blinded-gate controls; old test untouched.
28. changelog.d/544-slugkit-error-protocol.md — new fragment, preserve shipped honesty/optional fragments.
29. evals/README.md — index the new bounded task separately without revising historical claims.
30. docs/flow-runs/issue-544.md — later append genuine new run/ABC/approval; preserve Run1/Run2 prefixes.
31. docs/flow-runs/issue-544.as-read.md — later append fresh snapshot under canonical lifecycle; preserve prior history.

Cost: measured old task114files/3003lines; eight top-level corefiles1016lines, twelve candidate pipeline/helperfiles1063lines, remaining94 DATA files924lines. Reusing those94 immutable files read-only avoids copying package/expected/data bytes; it DOES NOT reuse old executable qualification or grader semantics. New qualification materializes disposable candidates and explicit version-specific pipeline overlays; old expected sets remain unchanged, and new sets are independently justified rather than silently relaxed. Five old broken-grader controls can be pinned as control DATA/executable fixtures for the new harness, not imported as trusted implementation. The standalone new public fixture still needs its own complete files.

Prospective cost for the enumerated bounded design:29 product paths, approximately2600–3400 product A+D, plus2 append-only workflow paths approximately180–300 A+D; any future genuine receipt adds its actual leaf/lines only under a separate grant. These are planning ranges, NOT chosen caps or authority. Exact fixture bytes/data pin population and overlays must be agreed before code; whole directory duplication is an alternative measured base3003lines plus new controls/docs, likely3500–4100 A+D/115+paths, with greater maintenance cost. No 750-line optional budget is reused. Strong evaluator-owned boundary is unestimated and requires another design ruling.

Future controls if implementation is approved (NONE RUN NOW):
- Genuine old behavioral red: actual inner child loader/tool/crash/timeout on a proven mutant gets falsely credited under v1, with a healthy defect-catching twin. New configuration refusal alone is not the regression. Preserve raw old/error/healthy source and exits.
- New protocol matrix: real success; real assertion/domain violation; checker import/tool/runtime timeout/empty collection; each on clean, defect and harmless copies; exact exit/status consistency and unsupported infrastructure UNKNOWN.
- Preserve both planted domain defects, two benign twins including forwarding shape, alternate checker layouts/helper imports, nonempty candidate/criterion membership and exact violated sets. Do not turn all ImportErrors into UNKNOWN and lose the planted missing-entrypoint proof.
- Commit a blinded decoder/error-propagation opposite: disabling ERROR refusal or flattening inner errors must make the validity gate fail; the healthy gate must pass. Commit missing-control/population controls so zero cases cannot qualify.
- Pin all114 old runnable files/modes and old grader digest, historical declaration/report/role binding; verify staged new runtime independently without old imports. New identity must differ; no frozen metadata editing or report recomputation.
- This establishes bounded classification controls, not truthfulness against arbitrary malicious candidate reports. Report that limitation beside results.

Subjective WSJF (value+urgency+risk reduction divided by size, ordinal planning only): bounded Slugkit protocol (2+1+3)/8=0.75; no consumer urgency. Smaller closing-ref/porcelain issues may have higher raw ratios but frozen/version constraints still need their own fresh analysis; no takeover authorized. #538 retains the next exclusive full, B2 worker01 stays standby. No heavy work competes with either.

Step3: STOP. Await root substantive judgment selecting defer/bounded/stronger redesign and exact scope/versioning; EMPTY lane and baselineABSENT maintained. This is the report required by the current ruling, not a request for repeated approval of delivered optional work.
