# Flow run record - issue #543

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=56213bd9b85f49ce8b12a151fbe2c1f8 -->
## Run 1

- Run-id:            56213bd9b85f49ce8b12a151fbe2c1f8
- Run-start:         7a10cacbcadab9311cb4e57b1095ea54a3848af6

- Issue: #543
- Base SHA: 7a10cacbcadab9311cb4e57b1095ea54a3848af6
- Necessity verdict: Needs reframing - independent successor preserves current frozen positives
- Approval: granted
- Approver: orchestrator, clearance-543-lean-versioned-implementation.md, skillc-update
- Recorded at: 2026-10-27T19:37:38.955674+00:00

### Section A - intent

The existing task can award full credit while the public gate fails or inspects
nothing. Deliver a separately versioned successor with actual public-gate and
nonempty observations, keeping regression-stage proof distinct and all old
approved task identities intact.

### Section B evidence

Fresh run56213bd9b85f49ce8b12a151fbe2c1f8, actualbase7a10cac.
Issuecreated2026-10-24T11:56:19Z; read11386bytes digest
ebf999ae538cb3234904a4d0959e98c765faa0ebc6d1e1eafd533461d4ca1ea0.
Scopedcommits7a10cac/1d129f9/1c7c4c7/6b78522/1fcf690 and mergedPRs
588/587/586/584/583/582/579/578/575/573/572/570/567/566/565/564/562/561/560/559/558
inspected. Related543/542/554/287/544/375/376/270/271/400/408/419/446/462/
508/529/530/250/288/431; no superseding full-gate fix. Localunpushed d3ea702
qualificationstdout patch inspected, unrelated. Current375 manifest derivation
and frozenidentity positives bind oldtask5;287 P3 currentapproval positives
requirethatpath/revision5.271 binds differenttasks/sharedfreezer, preserved.
Therefore oldtask edits rejected; corrected lean successor judged. Prior actual
API counterexample: test0/typecheck1/publicmake2 but gate-greenSATISFIED and
stagedPASS with explicitlystaticqualificationwitness; taskbytesunchanged on7a10.
Bytecode#408 alreadyfixed, cache/sourcecontrol measured; no repeated probe.
Preflightready, freshverifiedclaimedworktree, emptyinitialwrite lane; Step4
live-driverclear/stalebasecurrent. Sharedmain/usernotes untouched.

### Section C - the approved plan

1. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/CONTRIBUTING.md` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
2. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/ISSUE.md` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
3. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/Makefile` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
4. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/ci/check.py` - new delivered seed; copy original bytes/mode and harden nonempty check.
5. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/ci/lint.py` - new delivered seed; copy original bytes/mode and harden nonempty check.
6. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/expected.json` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
7. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/pyproject.toml` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
8. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/rangekit/__init__.py` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
9. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/rangekit/windows.py` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
10. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/report.json` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
11. `evals/level3/gate-stops-early-public-gate/discrimination/fixture/tests/test_windows.py` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
12. `evals/level3/gate-stops-early-public-gate/fixture/CONTRIBUTING.md` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
13. `evals/level3/gate-stops-early-public-gate/fixture/ISSUE.md` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
14. `evals/level3/gate-stops-early-public-gate/fixture/Makefile` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
15. `evals/level3/gate-stops-early-public-gate/fixture/ci/check.py` - new delivered seed; copy original bytes/mode and harden nonempty check.
16. `evals/level3/gate-stops-early-public-gate/fixture/ci/lint.py` - new delivered seed; copy original bytes/mode and harden nonempty check.
17. `evals/level3/gate-stops-early-public-gate/fixture/ci/typecheck.py` - new delivered seed; copy original bytes/mode and harden nonempty check.
18. `evals/level3/gate-stops-early-public-gate/fixture/expected.json` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
19. `evals/level3/gate-stops-early-public-gate/fixture/pyproject.toml` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
20. `evals/level3/gate-stops-early-public-gate/fixture/rangekit/__init__.py` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
21. `evals/level3/gate-stops-early-public-gate/fixture/rangekit/windows.py` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
22. `evals/level3/gate-stops-early-public-gate/fixture/report.json` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
23. `evals/level3/gate-stops-early-public-gate/fixture/tests/test_windows.py` - new delivered seed; preserve original bug/shape; publicly update CONTRIBUTING when applicable.
24. `evals/level3/gate-stops-early-public-gate/probe.py` - self-contained successor runtime, bound by GraderDef; actual public aggregate/population/detection contract and revision6.
25. `evals/level3/gate-stops-early-public-gate/grade_gate_stops_early.py` - self-contained successor runtime, bound by GraderDef; actual public aggregate/population/detection contract and revision6.
26. `evals/level3/gate-stops-early-public-gate/grader.json` - self-contained successor runtime, bound by GraderDef; actual public aggregate/population/detection contract and revision6.
27. `evals/level3/gate-stops-early-public-gate/inputs.json` - self-contained successor runtime, bound by GraderDef; actual public aggregate/population/detection contract and revision6.
28. `evals/level3/gate-stops-early-public-gate/grader-controls/always_fail.py` - copy local broken judge; with_judge binds its actual bytes; no executing legacy data as helper code.
29. `evals/level3/gate-stops-early-public-gate/grader-controls/always_pass.py` - copy local broken judge; with_judge binds its actual bytes; no executing legacy data as helper code.
30. `evals/level3/gate-stops-early-public-gate/grader-controls/crash.py` - copy local broken judge; with_judge binds its actual bytes; no executing legacy data as helper code.
31. `evals/level3/gate-stops-early-public-gate/grader-controls/no_output.py` - copy local broken judge; with_judge binds its actual bytes; no executing legacy data as helper code.
32. `evals/level3/gate-stops-early-public-gate/grader-controls/omits_criterion.py` - copy local broken judge; with_judge binds its actual bytes; no executing legacy data as helper code.
33. `evals/level3/gate-stops-early-public-gate/qualify.py` - new task-local serial split qualifier; pinned DATA loader/materializer, native witness construction, exact outcomes and broken-grader controls.
34. `evals/level3/gate-stops-early-public-gate/goal.md` - public complete successor stage/population/detection obligations and optional-all-deletion limit.
35. `evals/level3/gate-stops-early-public-gate/PROVENANCE.md` - new source/qualification identity and legacy evidence boundary; not inherited375/287qualification.
36. `evals/level3/gate-stops-early-public-gate/eligibility-manifest.json` - new successor candidate fixture choices and pending qualification; no study approval.
37. `evals/level3/gate-stops-early-public-gate/qualification-sources.sha256` - 363 explicit SHA256/executable-bit/relativepath entries for historical DATA only; fixed root and population; no wildcard.
38. `evals/level3/gate-stops-early-public-gate/qualification-expectations.json` - new exact outcomes/witness modes for all29selected historical/newlocalcases; never use oldPASSsets as authority.
39. `evals/level3/gate-stops-early-public-gate/public-gate-controls.json` - committed full healthy/empty/omitted/noop/crash/unavailable/timeout mutation payloads and exact outcomes.
40. `tests/test_stops_early_public_gate.py` - newAPI red-first and fullaggregate/detection/corpus-pin controls.
41. `tests/test_stops_early_nonempty.py` - newseed empty/nonempty and checker observation controls.
42. `tests/test_qualify_scripts_run.py` - pass explicit source-root environment to copied split qualifiers; retain every existing assertion/control/population.
43. `tests/test_gate_stops_early_witness_equivalence.py` - add successor judge to current canonical battery; retain all oldjudges/cases.
44. `skillc/calibration_run.py` - append final reviewed newpath/rev6/digest role tuple; retainold.
45. `tests/test_calibration_honesty_role.py` - new reviewed identity positive and changed/missing digest negatives; retainold.
46. `changelog.d/543.md` - bounded new successor task; parentresidual staysopen.

Scope and cost: exact46product+2workflow paths;3800productA+D INCLUDING all
copiedlines/checksumindex/mutations/publicdocs/currentrolemap/tests and future
genuine31-45line receipt (actualpath requireslatergrant);500workflowA+D separately.
Initial10minute serialoneCPU batch,15second percommand/mutation,60minute
unresolved attributioncontract STOP. Wholeprobe90second cumulativebudget needs
explicitaccounting, anyincrease returnsforscope.6-9hour delivery estimate.
Newrootgate-stops-early-public-gate, gradergate-stops-early6.363oldfiles are
readonly qualificationDATA pinnedchecksum/mode, no mutableoldPythonhelper
runtimeimports. New29case exactexpectations and explicitmutation/overlaydata;
independentnonemptyindex/candidatepopulation, duplicate/traversal/symlink/
changedbytes/mode/unlistedmembers refusal; hashSAMEmaterializedbytes. Static
nativewitness constructors clearlystatic, localbrokenjudges boundwith_judge.
Publicgoal/BOTHCONTRIBUTING state mandatorylint/test/nonempty and conditional
DELIVEREDtypecheck; deletingBOTHoptionalchecker/target cannotproveoriginal
obligation - acceptedexplicitlimit. Actualpublicaggregate separate from restored
ci/check regressionattribution; rawnonzero/crash/timeout not mutantdetection.
Source-root handoff<=20lines retainsALLoldtestassertions/population/independence.
Newpathroleentry ONLYfinalactualrevieweddigest, oldtuple retained. Frozen375/
271/287/task/approval/results untouched. Neweligibilitypending, no studyapproval.
Risks: fullaggregate falselycreditedbyomitted/noopstage, crashmisreadasdetection,
emptycoverage, historicalidentitybreak, mutablecorpus/codeescape, synthetic
witnessmisrepresented, cumulativeprobecap anddiffgrowth. Opposite controls
required. Returncheckpointcounts/evidence before review/full/receipt/PR.
No in-placelegacyedits, generalplatform, heldout/auto6/freshness/tracer,
privateHOMEreplay/physical/Docker/client/modelstudy/hostinstall/deploy.
