# Flow run record - issue #544

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=93d2670eccd540ddaf2004e80dc5433a -->
## Run 1

- Run-id:            93d2670eccd540ddaf2004e80dc5433a
- Run-start:         1d129f90d37c27c3122b0c3074833723e7b4ebdc

- Issue:             #544
- Base SHA:          1d129f90d37c27c3122b0c3074833723e7b4ebdc
- Necessity verdict: Still needed for bounded honesty beside-column; other items remain
- Approval:          granted
- Approver:          orchestrator, ruling-544-actual-step3-implementation.md, skillc-update
- Recorded at:       2026-10-27T15:21:42.169638+00:00

### Section A - intent
A report can say honesty was never measured even when the task's result says
honest or dishonest. Show that task's actual honesty row and summary counts
without changing task success or study scoring. Unknown roles and malformed
evidence must remain explicit rather than guessed.

### Section B - necessity evidence
Issue filed2026-10-24T11:56:20Z, read12372bytes digest556908aefd8c71376910893e41e347c4466d9de2a2c82e98a9f09da274011e31.
Actual base1d129f9 includes584/583/582. Scopedpostfiling1fcf690(567),
6b78522(570),1c7c4c7(583) leave literalflow-check-honest unchanged.
Globalhistory and mergedPRs558/559/560/561/562/564/565/566/567/570/572/573/
575/578/579/582/583/584 inspected. Helper introduced1b40509/372.
Sibling534 fixes distinct fixture_live role registry only. Issues544/20/287/
288/203/245/264/271/434/508 considered, no superseding calibration fix.
Existing publicreport temporary planning (backendprepare prohibited) gives
pipeline endpointPASS/compositeFAIL but honestyMISSING, botharmsMISSING1.
FunctionalPASS/honestyVIOLATED and converse both actual expected-honesty
assertions fail. Knownflow-check-honestpositive works. Endpointcriteria may
be functional and cannot automaticallymean honesty.
Freshnative Run93d2670e, resolververifiedactualworktree/base/claimselfPID1102501;
hostpreflightready, stashguardcurrent. No approval bypass. 548A fully delivered
and only own continuation cleaned after verified archive/mainpush1128.

### Section C - approved changes

1. `skillc/calibration_run.py` - Explicit launch-bound taskpath/graderid/revision/DIGEST honesty association for measured four identities, per-attempt actual ledger identity; parameterize both stored report callers. Precise MISSING for absent role/knownNone/unmapped; MALFORMED for duplicate/invalid/conflicting known honesty rows; unique valid mandatory row retains actual outcome; ungraded unchanged. Ignore benign functional rows, no arbitrary endpoint/prefix inference/current-filesystem lookup/primary scoring or history change.
2. `tests/test_calibration_honesty_role.py` - Real existing-public-report red first then repaired green: actual pipeline/auto6/current flow identities, functionalPASS/honestyVIOLATED and converse through both callers, digest altered/missing/mixed, None/unmapped/renamed/duplicate/conflict/malformed and benign functional rows, storedidentity/source-deletion/legacy and primary/tolerance invariants. No missing-new-API TypeError counted as red.
3. `changelog.d/544.md` - One bounded report honesty-column correction bullet.

Scope: exact3product plus thisrecord/asread; cap360nonworkflowAD includinglater
separatelygranted genuine receipt<=42. No compression; returnscopeexcess.
Association initial known task identities: gate-stops-early5 digest332318a553fdb7cfcd518d1baf0bef9a04895c7941a3ddd9307669bca15b21bc toflow-check-honest;
auto6-1 digest5f857a35e3fe6cc6351b3d9d821efc190f24d295e96a9b76844c6949fa2b9790 togate-report-honest;
slugkit-pipeline1 digest670e04a0394943a6d60b519380d5f578e94f533fb04a3f59660d3962184d8e2e topipeline-honest;
slug-small-fix2 digest3bb202eb2d274f2c8bb31dc1e618a0d076d9c3bf52e270f290a567fe51e0c5f2 explicitNone.
All use publishedtaskpath+id+revision+sha256 digest. SameID/rev changedcontent
or missing/unknown digest isunmappedMISSING; never borrow firsttrialidentity.
Currentgraderfilesystem neverread duringreconstruction. This identifies a
reviewed role forknowncontent, not broad raw-grade authenticity. Newgrader
functionalrow changesdigest andisunknown; benignfunctional rawgraderows under
knownidentity neitherselectnorconflictwithhonesty. DistinctMISSING reasons
for knownNone/unmapped/missingmappedrow; MALFORMED on duplicate/conflict/invalid.
Legacy noendpoint columns/shape preserved; frozen287375271/profile/receipt/task
bytes and oldrawreports unchanged. Corrected reconstruction isnewderivedreport.
Risks: role guessedfromfunctionalendpoint, content-substitution under same
id/revision, firstrowconflict, overstrictfunctionalrows, mutable-source
reconstruction, fixtureidentitymistake andcapexcess. Primary/evaluability/
tolerance/completion/population must remain equal outsideintendedbesidefields.
No fixture_live/agent_trial/verify/CLI/backend/547 paths, physical/client/model
probe, privatepromptaccess, hostinstall/deploy. Focusedchecks only now; review/
receipt/full/PR/merge separateheldgates. Whole544 remainsOPEN;549 and548B held.
