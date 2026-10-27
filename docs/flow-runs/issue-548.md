# Flow run record - issue #548

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=4ee3a6da7cc246e8b646161d535ad2ef -->
## Run 1

- Run-id:            4ee3a6da7cc246e8b646161d535ad2ef
- Run-start:         5d04193feaa17194172ae37740ed5d4480b0b711
- Issue:             #548
- Base SHA:          5d04193feaa17194172ae37740ed5d4480b0b711
- Necessity verdict: Partially addressed; Level-3 A remains needed
- Approval:          granted
- Approver:          orchestrator, skillc-update gate38; actual native Step3 Run4ee3 accepted
- Recorded at:       2026-10-27T13:57:04.774866+00:00

### Section A - intent
The checker can approve an execution setup whose identity fields were omitted.
Runs with skills installed also omit the fingerprints already measured for those
bytes. Require complete setup details and carry existing skill pins into every
new treated row, retaining old frozen campaigns and readable historical ledgers.

### Section B evidence
Issue548 filed2026-10-24T11:56:24Z. Post-filing global/scoped history and merged
PRs558/559/560/561/562/564/565/566/567/570/572/573/575/578/579/582 inspected;
none touches the two existing A files. Latest scoped commits ffa9668(#510),
41407f9(#448),4bab8d3(#403),c9cce59(#395). Closed424/432 and existing354 supply
the pin validator;434 fixes the sibling fixture route only. Duplicate/adjacent
issues548/20/568/434/375/287/475/376/529/288/545/547/546 considered. Actual base
5d04193 includes582; relevant file blobs equal028dde5. Pure existing load/check
accepts healthy, empty, four missing-key and extra-null runtime cases, while a
known wrong runtime_id reports a real mismatch. No backend/client/model ran.
The old287 MEDIUM premise is obsolete: approved historical reference.md mutation
is derived with fresh tree/recheck hashes and unchanged SKILL.md pins; actual
SKILL.md mutations are refused. Preserve that approval and432 enforcement.

### Section C - the approved plan

1. `skillc/level3_campaign.py` - Requireexactruntime_id/subject_revision/pyproject_sha256/lock_sha256 keys with nonblankstringvalues atload and directcheck_frozen; returnusefulproblems fordirectinvalidruntime insteadofemptycomparison. Keepactualpolicy/task/subject/capscomparison. CarryexistingTreatment.skill_digests throughrun_rows/plan intoeverytreatedledgerrow, includingtaskno-op actors; refuseemptypinsbeforebackendallocation. Useexistingtrial/recordpinvalidation, nofixture_campaign importcycle/newinventoryschema.
2. `tests/test_level3_campaign.py` - Addbehavioralempty/missing/extra-null/blank/nonstring/directManifest controls versuscompletehealthy/knownwrongruntime. ExerciseEXISTINGrun_rows to inspectrealplannedledgerpins andemptyTreatmentrefusalbeforebackend; givehealthyfixtureactualmatchingSKILLbytes/pins. Proveoldcodefailsacceptance/missing-ledgerpin assertions, NOTmissing-helper/keywordTypeError. Reuse354/424/432 validators foractualsubstitution, no duplicateverifier.
3. `changelog.d/548.md` - Oneordinarybullet forboundedruntimevalidation andtreatedpinpropagation.

Scope: exact3 product paths, two canonical workflow artifacts; later exact receipt
requires a separate grant. Cap260 TOTAL nonworkflow added+deleted lines INCLUDING
genuine receipt<=42, expected~245. No compression to fit; return actual excess.
Tests first on unchanged existing APIs: retain actual false-acceptance/missing-pin
red XML/log, then fixed green and independently collected/JUnit identities.
Reject empty/missing/unknown-null/blank/nonstring runtime at loader and direct
Manifest checker; retain healthy/known-wrong policy discrimination. Existing
run_rows must record actual Treatment pins for every treated row including task
no-op and reject empty pins before backend allocation. Reuse354/424/432 schema.

Compatibility: schema1 manifests and recordv2 optional pins unchanged; complete
375/271 manifest/receipt bytes and old ledgers stay readable. New treated plans
intentionally tighten missing-pin behavior. No actor/freeze/profile/records/CLI/
agent_trial/fixture_campaign/native-engine/runtime-version change. Whole548 stays
open; B needs its separate executable-binding and completion/retention gate.
A is disjoint from546/547 and not a568B2 dispatch prerequisite.

Risks: direct Manifest bypass, hand-built Treatment test fixtures need matching
bytes/pins, accidental frozen-artifact rewrite, and cap exhaustion. Small pure
focused checks/selftest/types/lint only while other worker owns heavy full slot.
Review/full finish/push/PR/merge/physical/version/client/model/host-install/deploy
remain separate held gates. No owner reconfirmation or approval bypass was used.

### Current-run receipt and integration grant
Root gate-548a-receipt-integrate.md approved the exact following row after the
independent CLEAN one-pass review of bd6ba0f versus actual5d04. Original A approval
and source remain historical; this current-run addition precedes receipt copying.

4. `docs/measurements/counter-model/2026-10-27T142704Z-issue-548.json` - Copy the unchanged genuine31-line native gpt-6-astra receipt from the outside-source writer, actual implementer gpt-6.1-sol; scoped validation only.

Net product123+receipt31=154AD; conservative charged125+31=156AD, cap260.
Ordinary checkpoint and merge actualmain1c7c4c73b22c666131d0bb38a3a7ccc79999b756
are authorized. Preserve all three reviewed A files, exact receipt and frozen
375/271/profile evidence. Full quality still awaits post-integration clearance;
no second review, B, push, PR, physical/client/model study or deployment grant.
