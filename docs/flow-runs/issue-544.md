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

<!-- flow-run n=2 id=90a23b4db8844bba848f3d740845df9b -->
## Run 2

- Run-id:            90a23b4db8844bba848f3d740845df9b
- Run-start:         20a03590055f5d38b4f7d5541c0f51cf54fd2e97

- Issue: #544
- Base SHA: 20a03590055f5d38b4f7d5541c0f51cf54fd2e97
- Necessity verdict: Partially addressed; optional criteria only
- Approval: granted
- Approver: orchestrator, clearance-544b-optional-criteria-implementation.md

## Section A - intent
A grader should retain a measured diagnostic without letting it decide whether
required work passed. Add explicit allowed optional IDs while keeping mandatory
criteria complete, nonempty and strictly typed. Earlier honesty projection was
delivered by PR588; the other three remaining items stay open.

## Section B - necessity and evidence
Issue created 2026-10-24T11:56:20Z. Fresh main20a0359 includes delivered549;
PR588/7a10cac fixed honesty projection only. Postfiling1c7c4c7/PR583 changed
completion deadlines, not criteria completeness. Scoped history inspected
90e59fc/206, a25d73b/465, 21298e6/507, f321f8c/153 and1c7c4c7/583.
Global mergedPRs558/559/560/561/562/564/565/566/567/570/572/573/575/578/
579/582/583/584/586/587/588/589/590 were considered. Related544/20/204/203/
276/475/434/37/287 inspected; no superseding optional-criteria fix.
Actual read-only old criteria_problem accepts exact mandatory rows, refuses an
extra optional row, and refuses a listed required row marked false. Records
status derivation already ignores optional rows. No pytest regression claimed
from these probes. Slugkit inner-crash credit, grammar disagreement and first
porcelain blank loss remain separately versioned concerns. Estimated WSJF3.0
versus2.0/1.5/0.75 is subjective planning, not measured performance.
Host worktrees enumerated: unpublished348/536d02c touches verifier witness
capture, not this contract; no borrowing or takeover. Known positive543
unpublished history established the audit can find commits. Actual native
Run90a23b4db8844bba848f3d740845df9b is fresh; oldRun1 is history only.
New own worktree verified at base20a, claimself, preflight local-ready,
registrypolicy3/transportverificationfalse. No client/auth readiness inferred.
Read-only prototype setup failures were corrected before observations; no
missing API, AST setup error or new-configuration refusal counts as regression.

## Section C - approved changes

1. `skillc/verify.py` - Add explicit optional_criteria allowed-ID policy beside nonempty mandatory criteria; validate distinct nonblank/nonreserved IDs/disjoint sets and literal flags. Optional omission remains not reported. Require mandatory rows exactly once and reject unknown/duplicate/invalid rows with normal evidence validation. Preserve omitted-field load/read/digest/identity/result shape exactly; opted policy affects pin including read-once/with_judge/tamper. Retain diagnostic rows in returned/stored criteria, but mandatory-only status, Graded.violated and unmet detail. Judge inputs/tiers remain mandatory only; optional rows cannot promote UNKNOWN/FAIL, evaluability or selected endpoint.
2. `tests/test_verify_optional_criteria.py` - New dedicated committed public-API controls: old Graded status-versus-violated real assertion red plus healthy mandatory twins before product edits; actual load/grade_directory/captured grade/store/fake-Judge/endpoint diagnostics and omission. Nonempty legacy grader/pin/byte inventory before/after, opt-in pin change/tamper/with_judge/read-once opposite; malformed declaration/row/evidence/refusal and empty mandatory controls. Blinded criteria guard must fail bad/good controls; no missing-API/setup/new-config refusal counted as regression. Inventory every existing consumer; preserve current all-mandatory qualifiers and known frozen pins.
3. `docs/specs/evaluation-facility/verification.md` - Define explicit opt-in allowed optional IDs, optional omission, literal flags, validation, pins, retention, mandatory scoring and endpoint limits; no allow-any optional fallback. Current frozen legacy replay contracts stay unchanged unless separately authorized.
4. `changelog.d/544-optional-criteria.md` - New bounded optional-criteria fragment; preserve shipped honesty fragment544.md byte-for-byte.

Scope: exact4product paths plus this record and issue-544.as-read.md; cap750
nonworkflow additions+deletions INCLUDING later genuine receipt if separately
granted; cap500workflow. Preserve oldRun1/asread prefixes and frozen375/271/287
pins, all evals/grader/probe/fixture/profile/declaration/historical receipts.
No records.py/judge.py/endpoint source changes or unpublished348 takeover.
If an actual consumer requires another source path, stop with concrete evidence
before widening. Judge replay's existing strict legacy contract is not silently
expanded. Preserve nonempty mandatory completeness and scoring semantics.
Risks: required rows weakened, optional flags veto qualification or contradict
PASS detail, old pins migrate, readiness collision, endpoint/tier effects,
shared consumer scope, and size growth. Alternative remains post-hoc flags;
versioned slugkit causal-attribution repair is a separate plan, not a regex fix.
Validation: real old-API behavioral red/healthy first, fixed exact population,
public consumer/store/Judge/endpoint controls, nonempty legacy/frozen pin and
byte invariance plus discriminating negative controls, focused fake-only
verifier/Judge/backend/records/endpoint suites, collection/JUnit identity match,
Ruff/mypy. Review/receipt/full/publication separately gated; no full or live
client/model/Docker/native study. Parent544 remains open.
