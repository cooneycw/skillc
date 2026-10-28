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

<!-- flow-run n=2 id=a27ef7d7ad674c4aa5d7f8606108c96d -->
## Run 2

- Run-id:            a27ef7d7ad674c4aa5d7f8606108c96d
- Run-start:         1f425b2048ae4eedf6fcd6d9c858e7144bbf2959
- Issue: #548
- Base SHA: 1f425b2048ae4eedf6fcd6d9c858e7144bbf2959
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: root orchestrator, skillc-update policy revision 3
- Recorded at: 2026-10-27T18:43:12.310165+00:00
- Actual Step 3 report SHA256: d71ad9d01cac6446419d14ef74d429ee16b3f8d08357c1339a896f79fef67d4e

ELI5 Gate: Issue #548, fresh B run a27ef7d7ad674c4aa5d7f8606108c96d
Base 1f425b2048ae4eedf6fcd6d9c858e7144bbf2959 / tree 36ab9b0e4676651852c9c707aa87eddc3a971eec. Analysis only. No approval, begin-run, product/test/doc/receipt edit, physical client/version/model/Docker probe, or full gate performed.

### Section A - intent

A study should distinguish the software it intended to run from the software its evidence actually describes. Today two readers can report different client versions from the same conversation: one takes the first version and another takes the last, so a contradictory conversation can look consistent depending on which reader is used. The larger issue also asks us to measure the actual executable inside its container; reading conversation text does not accomplish that. I recommend first making the observed conversation-version fact trustworthy and consistently reported, while keeping the task's result separate and leaving actual executable verification to its own bounded stage.

### Section B evidence
Verdict: Partially addressed.

Evidence since issue creation 2026-10-24T11:56:24Z:
- PR #584, 1d129f90d37c27c3122b0c3074833723e7b4ebdc, already delivered exact/nonblank Level-3 runtime declaration keys and treated skill pins. Its #548 handoff comment is https://github.com/cooneycw/skillc/issues/548#issuecomment-6445882664. Items 5-7 are checked; the old degraded-arm premise was ruled out there. The existing 548.md fragment and original approved Run 1 remain history.
- PR #587, 1f425b2048ae4eedf6fcd6d9c858e7144bbf2959, delivered private exact controller inputs independently of transcript success; #547 is CLOSED. PR #583, 1c7c4c73b22c666131d0bb38a3a7ccc79999b756, delivered shared completion endpoints. PR #586, 42e367b6bea4eb6fdce5037250b733157f392095, fixed the Ruff fixture-cache producer. These are incoming main, not new B work.
- Scoped post-filing history also inspected 1fcf690621d6d8fb091abafa17b56a134614e786 (#567), 9a62b80979bf3e374049d0933f7e6822bb9d9cda (#562), c80455538d4412391a375b76202f8c4ec6338be7 (#559), afce0e4 and merge 84ab2ab. The complete post-filing merged-PR query is preserved in merged-after-filing.json: #558-#562, #564-#567, #570, #572-#573, #575, #578-#579, #582-#584, #586-#587. None added consistent version population assessment or actual native executable measurement.
- Related issues inspected/search results: #548 owns this remainder; #141 covers observed MODEL equality, not this client-version issue; #78 pins bootstrap declarations; #40 records a drift arm; #547 covers prompt retention; #546/#580 cover completion timing. Broader #249/#247 and #554 do not supersede this code defect. No duplicate/superseding runtime-version ticket was found in the bounded search; the issue's existing four unchecked items remain open.
- Local worktree evidence: all listed worktrees were readable. Only skillc-348-qualify-stdout-compat has an unpushed relevant commit, 9caf33c452efb9c1da5b3b0714677d2e9f1db5d6, which adds runtime/witness readiness and does not change version population selection. Inspected its agent_trial/test diff. No other local unpublished relevant source commit was found. This host-only fact does not cover another machine. host-overlap.json records every inspected checkout.
- Current source: agent_trial.transcript_census at :290-354 chooses FIRST nonempty version (:327/:341); transcript_adapter.codex_run_metadata at :523-581 chooses LAST string (:559-561). matched_pilot.build_report :748 displays the metadata value. credit_block :223-271 has no declared client/version input; the only production callers are run_one_attempt and fixture_live.judge_replay. This is not repaired by #547's retention APIs.
- Disposable existing-public-API observations used ONLY committed sanitized transcript fixtures plus generated version headers. All 20 cases had genuinely confirmed prompt/canary facts; missing, wrong, conflicting-both-orders, blank, and nontext versions currently pass the existing credit gate, just as healthy matching/duplicate matching cases do. The independent known-bad format-drift case was refused, proving that gate can report a block. The exact observations are in public-api-observations.json. These are analysis observations, NOT committed regression tests, a full gate, a real attempt execution, or proof of a runtime binary. An initial observation run incorrectly supplied a build-pin object instead of its version string; preserved invalid-pin-shape.json is explicitly excluded from healthy matching evidence. The corrected run checks actual string matches.

Important correction to the earlier seven-path proposal:
- Level3 and fixture campaign actors launch Python/scripted clients through the SAME run_one_attempt and ledger client=codex/version pin. Their frozen fake_agent_client normally emits NO version header. Existing tests also deliberately use ledger client=fake/version=1. Globally blocking missing versions would reject healthy model-free populations or require editing frozen actor/fixture bytes. A basename, PATH heuristic, test-only exemption, or arbitrary wrapper self-report is no solution. No such block or fixture rewrite is proposed.

Choice: B1 observed-fact consistency FIRST, explicitly narrower than the former B1 credit gate. B2 executable measurement remains necessary before runtime-identity qualification; B1 does not close any actual-binary item or the whole parent. B1 is independently useful because current diagnostics demonstrably disagree on the same retained text. It supplies honest evidence without changing grading or pretending a transcript version proves a binary.

### Section C - the approved plan

Contract to approve:
- A version observation is present only when the entire parsed version-bearing population has one exact, nonblank text value. Repeated identical values are healthy. Different values, a present missing/blank/nontext value, or malformed/partial JSON input makes the version UNKNOWN/null; a later matching value cannot erase an earlier contradiction. Codex examines session_meta.cli_version; Claude examines its version-bearing records. No unrelated metadata/model/token/closing-message semantics change, and no version string normalization or guessed build default is introduced.
- Reuse the EXISTING census client_version:null/text and run_metadata cli_version:null/text vocabulary. Do not put version uncertainty into the general census-error field: the existing credit gate reads that field, so doing so would silently create the forbidden global grading block. No new closed agent-observation field or records.py schema revision is needed.
- Reports display the census-derived observed version (UNKNOWN for absent/ambiguous/incompatible census evidence), with the expected client name/version read from experiment.trial_of(attempt_id).client as a separate declaration. Do not choose the first/last metadata fallback when evidence disagrees. No client-match/qualified boolean, no binary-measurement claim, and no new pass/fail eligibility predicate is introduced in B1. The proposed declared/observed display fields are diagnostics, not an attestation.
- Preserve raw task grades, criteria, dispositions, model eligibility, matched-pair rules, live success, and rehearsal rules. There is no edit to credit_block, succeeded, model_eligibility, summarize's membership rules, or the CLI's decisions. No reinterpretation of original carried grades: replay continues to re-decide only the current eligible adapter-dependent population, while its re-derived version facts may be shown separately. Original report/store bytes remain unchanged.
- A historical scalar version is a historical observation, not newly proved population consistency. A fresh current observation can be re-derived only through the existing retained-transcript API when bytes are available; missing evidence stays UNKNOWN. B1 must not advertise legacy first/last fields as newly qualified runtime identity. Frozen records, 375/271/287 inputs, approvals, actor/fixture source and #547 private input bytes remain untouched.

Exact proposed product files, with estimate of added+deleted lines (A+D), not a measured patch:
1. `skillc/transcript_adapter.py` - one bounded shared version-consistency reducer, and use it for Codex metadata instead of last-wins; preserve every other metadata field. ~30 AD.
2. `skillc/agent_trial.py` - use the same consistency decision for Codex/Claude census; preserve observation/grading behavior and existing closed census shape. ~45 AD.
3. `skillc/matched_pilot.py` - canonical census-derived version display and separate per-attempt ledger-declared client identity; contradictory/missing metadata cannot supply a false observed string. No eligibility or task-status change. ~25 AD.
4. `skillc/fixture_live.py` - expose the same diagnostic observed/declared version fields in live/replay report construction; keep carry/re-decide/containment/success decisions unchanged. ~15 AD.
5. `tests/test_transcript_adapter.py` - existing-API pre-fix red cases for both conflict orders, present-invalid values, identical duplicates and other metadata remaining unchanged. ~95 AD.
6. `tests/test_agent_trial.py` - Codex and Claude parsed transcript populations, live-hook/pure parity, unknown vs healthy duplicate, grading/raw-task compatibility and unchanged private prompt-input retention. ~100 AD.
7. `tests/test_matched_pilot.py` - existing report's contradictory metadata case, per-attempt declared identity, missing/legacy evidence, and unchanged grades/model/pair accounting. ~70 AD.
8. `tests/test_fixture_live.py` - fresh live/replay diagnostic parity, historical carry preservation, no global missing-version grade/containment block, and byte-identical original store/report. ~55 AD.
9. `docs/specs/evaluation-facility/records.md` - document version-observation consistency/null semantics and diagnostic report identity boundaries; explicitly keep the closed AO schema and historical compatibility. ~22 AD.
10. `docs/specs/evaluation-facility/trial-bootstrap.md` - distinguish build pin, transcript observation, declared identity, and not-yet-delivered same-handle executable measurement; state B1 adds no runtime qualification. ~18 AD.
11. `changelog.d/548-observed-client-version.md` - NEW fragment for this PR, preserving PR584's changelog.d/548.md. ~6 AD.

Source measurement supporting the estimate: existing targeted definitions are 59 lines (metadata), 65 (census), 109 (pilot report), 138 (live report); exact AST locations and test/module sizes are in source-scope-facts.json. About 481 product AD is estimated above, plus a future ordinary 31-line review receipt = ~512 AD; propose a 600-AD product ceiling including that receipt, not an inherited 600/860 authority. Eleven product paths above plus the receipt, two existing workflow paths below. Estimated effort 2-3 focused implementation/review cycles (roughly 2-4 hours including required later full/CI waits); this is a planning estimate, not elapsed execution.
12. `docs/flow-runs/issue-548.md` - only AFTER approval, canonical begin-run appends this genuine run's complete approved A/B/C section; preserve all prior Run 1 history.
13. `docs/flow-runs/issue-548.as-read.md` - only AFTER approval, canonical append of this run's actual issue snapshot; retain old snapshot/history.
Future receipt reserve: one standard genuine counter-model receipt after actual authorized review; exact leaf path is separately granted after the writer supplies its real UTC timestamp. Receipt lines count inside 600 product AD. No review/receipt has run yet.
Workflow is excluded from product AD but should have an explicit later cap (~220 AD); estimate is subject to the root's scope/cap judgment. No source/test/doc path is currently granted. If the tests require any fixture-file edit, another caller, a records.py schema edit, new consumer predicate, or wider version contract, return that exact scope delta before code rather than fitting it into a false small plan.

Regressions and controls to execute AFTER approval:
- Run the FINAL intended assertions through existing transcript_census/codex_run_metadata/build_report on immutable 1f source: conflicting versions must currently produce a non-null first/last string, proving a behavioral red. Both conflict orders and matching-wrong-matching must fail. New diagnostic fields have good/bad controls but are not mislabeled regressions if they merely fail with absent-field errors on old code.
- Committed opposite inputs: matching singleton and repeated SAME version vs wrong/blank/nontext/missing/conflicting population, for both client formats, plus malformed JSON and unchanged model/token/count coverage. Wrong version alone remains an OBSERVED string in B1, shown beside the distinct ledger declaration; it does not become UNKNOWN merely because it differs, nor silently change task grade.
- Whole-pipeline task preservation controls: the same captured PASS/FAIL result and census-unknown model-free record keep raw grades, model eligibility and existing comparison behavior; original live/replay artifacts and #547 prompt bytes remain identical. Report disagreement must render UNKNOWN without inventing a binary failure.
- Use targeted tests/lint/type checks first. No full run or physical/native/version/Docker probe is authorized by this analysis. Root must separately grant implementation, review, and full quality stages. No historical/private prompt evidence is needed for the proposed tests.

B2 residual and why it is separate:
- B2 needs an explicit supported native-executable launch contract and a real qualification consumer bound to that SAME attempt's ledger client/image. Measure executable resolution/version only after final home/PATH overlays, using exec_in_attempt/controller_output on the live handle and sharing CompletionDeadline; execute itself is one-shot teardown. runtime_ready runs before later guard/make overlays and is too early. controller_output accepts no env argument while exec_in_attempt does, so choose the latter or a reviewed wrapper instead of measuring the wrong environment. Validate actual handle image identity independently; wrong image is not the wrong-version negative control.
- Distinguish top-level native client, Python/scripted actor, and separately measured discovery client. An arbitrary wrapper cannot be certified by probing a bare codex elsewhere, nor by matching its basename or self-reported version. This requires a declared/verifiable support boundary before a new runtime-eligible gate. Preserve raw task outcomes even when that separate qualification is UNKNOWN.
- Items 1/2/4 actual executable/image/version observation and comparison remain open. Legacy same-ID alternate-tag is a separate label contract (item 3), not new image bytes; no tag change is included. No physical proof/install/re-pin/deploy/paid study is authorized here.

Risks and alternative:
- Main risk: silently turning observation uncertainty into task-grade rejection through existing census error handling; explicitly prohibited and covered by healthy missing-version/scripted controls.
- Historical reports lack a version-consistency certificate. B1 does not mint one or requalify historical grades; a stronger consumer requires retained-byte re-derivation and its own declared gate.
- Calling this B1 a runtime fix would undermine the intended evidence standard. Alternative: skip B1 and freeze B2 executable binding first, but that is larger and still needs a sound transcript diagnostic. Root may choose that ordering; the proposed source list is not authority for B2.
- No material need for a new blocker issue: this is the existing #548 identity remainder. No new Nit Store finding is filed for its in-scope first/last or scripted-population constraints.

Approval: granted by root orchestrator under policy revision 3, with the full conditions below controlling this implementation.

### Root conditions governing the approved plan

GATE: GO-WITH-CONDITIONS #548
- Root read actualStep3 /tmp/skillc-update-worker01-548-analysis/step3-report.md SHAd71ad9d01cac6446419d14ef74d429ee16b3f8d08357c1339a896f79fef67d4e, freshnativea27ef7d7ad674c4aa5d7f8606108c96d/base1f425b2048ae4eedf6fcd6d9c858e7144bbf2959/readissue2ae9ea6e30e8ac0c2b3bff340802295f030dfec996ce3c3a993f40e8e8d3c4db. ApproveNARROWB1FACTconsistencyfirst, NOTearlierglobalcreditgate. B2actualsame-handle/finalPATH/image/executablequalification remainsowedandparent548OPEN.
- Exact11productpaths: skillc/transcript_adapter.py;skillc/agent_trial.py;skillc/matched_pilot.py;skillc/fixture_live.py;tests/test_transcript_adapter.py;tests/test_agent_trial.py;tests/test_matched_pilot.py;tests/test_fixture_live.py;docs/specs/evaluation-facility/records.md;docs/specs/evaluation-facility/trial-bootstrap.md;NEWchangelog.d/548-observed-client-version.md. Ownworkflowdocs/flow-runs/issue-548.md andissue-548.as-read.md only, preserveprior548ARun1history. Initial13rolepaths; laterexactgenuinereceipt separatelygranted.600productADINCLUDINGreceipt; workflowseparatelymeasuredceiling350ADtoallowFULLcanonicalsnapshot(no truncation/compression). Returnconcreteexcess/extra pathsbeforeedit.
- Root inspected currentfunctions: actualEXISTINGcensuskeyis transcript_client_version, metadata keycli_version; preservetheirnames/closedshape. Sharedboundedstate reducer producesexactunique nonblankstringorNone, duplicatessamehealthy/conflictsinANYorderinvalid, no normalization/defaultpin/first-last fallback. Codexsession_meta andClaudeversion-bearingrecordsexplicitlyscoped; ordinaryClauderecordswithoutaversionfieldmustnotvetoarealhealthyheader. Explicitinvalidbearingvalue/malformedpartialJSON versionUNKNOWN; othermodel/effort/token/closingmessage/censuscounts/errorsemantics unchanged.
- NO versionuncertainty insertedintogeneralcensus-errororcredit_block/succeeded/model_eligibility/matched-pair/summarize/CLIdecision. No runtimequalified/matchboolean,binaryproof,recordsv2schema, frozenfixture/actor/declaration edits, or test-only/pathheuristic exemption. PreserveRAWtaskgrades/criteria/dispositions/eligibility andprivate547inputs; comparematching-WRONG-matchingpopulation, notmerelyfirst!=last.
- HistoricalambiguityMUSTNOTgetnewconsistencycreditfromoldscalarorfromcensus==metadata alone. For anyreportfieldclaimingcurrentpopulationconsistency,re-derivefromavailableexistingtrustedretained-transcriptAPIs/actualbytes usingperattemptclient; ifunavailable/malformed/incompatible keepUNKNOWN. Do notinferfreshnessfromcurrentcode/time/versionstringornew-fieldabsence. Preservehistoricalcarriedrawgrades/sourcebytes, no privatepromptaccessinanalysis/tests. Ifthisneedsnewjournalcertificate/schema/trial.py/calleroutside11paths, returnconcretedeltabeforeedit.
- Declaredclientname/versiondisplaycomesfromTHISattempt'sledger(identitycopied, no buildpin/firsttrial/currentfilesystemfallback); observedfactseparateandnotqualification. Existingnewreportdiagnosticfieldsneedcommittedaccepted/refusedcontrols, notabsent-keyoldcodeclaimedasregression.
- FirstwriteexistingPUBLICAPIbehavioralregressionsonunchanged1f: census FIRST/metadataLAST conflictvaluesinbothorders andmatching-WRONG-matchingmustshowactualnonnullwrongfactsbeforefix. Knownhealthyrealfixture/duplicatematchingandbad-formatcontrolproveextractor/gatecan distinguish. Commitbothclientformats/invalidvalues/malformed/legacyretention/perattemptidentity/missing+wrongfactdisplay/fullrawgrading+pair+replay/store/promptpreservationoppositeinputs. Setupbad-pinshapeexcludedfromregressionclaims. Existingwrongversionalone isobservedstringbesidedeclaration, NOTunknownmerelybecausemismatch.
- Clearcanonicalbegin-run/approvedrecord BEFOREproductedits, exactpathswithoutliteralnewannotations, oldhistory/baselinepreserved. Implement/focusedchecks only. No independentreview/receipt/full/PR/merge/newphysicalnativeCLIversion/Docker/modelstudy/hostinstall/re-pin/deploy.544ownsfulluntilterminal(nowGREENpublication); no548heavyjobyet. Requirednewblockersfirst.
LEDGER
delivered:Actualfresh548Step3judged; safeFACTdiagnosticscontractselectedafterinvalidglobalgradegatepremisecorrected.
in-scope:Exact11product+2workflow600productADinclfuturegenuinereceipt/350workflowcap, genuineprefixedbehavioralreds thenfocusedimplementation.
residual:B1review/receipt/full/publicationlater;B2actualruntimebinding+legacylabel/discoveryitemsremain548OPEN;543publictaskrevisionand549queued.

<!-- flow-run n=3 id=a9cb7bf1270d47c3bc967208e3d1a4cc -->
## Run 3

- Run-id:            a9cb7bf1270d47c3bc967208e3d1a4cc
- Run-start:         f0cea733298ebd5730907999f075e5256c12130d
- Issue: #548
- Base SHA: f0cea733298ebd5730907999f075e5256c12130d
- Necessity verdict: Still needed - bounded legacy literal image-tag contract
- Approval: granted
- Approver: skillc-update root orchestrator, clearance-548-legacy-tag-implementation.md
- Recorded at: 2026-10-27T20:52:50.806580+00:00

## Section B

Actual Step3 report SHA25648d141f0bd6c8fc4db164a641f1a6677db9fd46a36d67cffe86b66ddebd1e06e. Fresh native runa9cb7bf1270d47c3bc967208e3d1a4cc. Current cli.main on the real approved204 declaration accepts an alternate tag with the same resolved ID, reaching a sentinel before private_root creates anything. Matching tag+ID and omitted-default healthies reach that sentinel; both wrong-ID twins exit2. One true assertion red, no Docker/client/model calls; initial import setup failure is separately preserved, not a regression. PR454/68a7e10 intentionally left legacy ID-only; present548 authorizes this narrow extension. Three named historical approvals all declare skillc-trial:latest, the existing default. Prior548PR584 and589 delivered other slices, not this guard. B1 source and original Run1/2 records remain history. GH legacy+tag search returned548/279/20/287; bounded history found no shipped tag fix.

## Section C

1. `skillc/cli.py` - Require nonempty string declared shared.image.tag and literal effective args.image-or-existing-default agreement ONLY for nonrehearsal no-receipt legacy calibration. Keep existing resolved-ID refusal independently before private_root/acquisition/artifacts; preserve receipt binding and rehearsal skip. Public help/docstring states the exact tag contract, no alias normalization/default adoption or binary attestation.
2. `tests/test_calibration_run.py` - Existing-CLI alternate-tag/same-ID regression on immutable f0cea before production edits, paired matching/default/wrong-ID controls and no private artifacts. Missing/malformed tag controls must reach this guard or disclose prior refusal. Normal synthetic approval stamps only. Realign only synthetic fake tag before stamp_approval and existing committed-declaration wrong-ID test's image argument so it still isolates ID refusal. Preserve receipt/rehearsal controls and frozen originals.
3. `changelog.d/548-legacy-image-tag.md` - New one-bullet fragment describing bounded literal legacy image tag binding; leave older548fragments untouched.

Scope: exact three product paths plus the two canonical workflow records. Product cap220 added+deleted lines INCLUDES a genuine future receipt; workflow cap350. Estimate25CLI+110tests+2fragment+31receipt=168. Actual later receipt path needs separate exact grant after genuine review, no invented timestamp. No calibration_run/schema/frozen/pin/Docker/probe/shared-conftest edit. Return facts before widening.

## Validation and stop conditions

Commit bad alternate-tag/same-ID and healthy declared-tag/same-ID controls; run the regression on immutable pre-fix f0cea and retain real behavioral failure. Fake-only focused calibration_run/p3_bindings/approval_binding/discrimination_run plus relevant receipt-swap checks, real collected/JUnit IDs, Ruff/mypy/selftest. Keep all three historical default tags and wrong-ID dispositions; receipt-backed behavior unchanged; rehearsal starts no container and discloses skipped identity checks. Empty or malformed tag cannot silently pass. Two synthetic arrangements change only to preserve the layers their assertions test. No physical Docker/client/model/paid study, private campaign inspection or host installation.

Root owns later checkpoint/review/receipt/full/publication gates;549 owns the exclusive full now. Return focused proof/counts/hashes before checkpoint or review. Parent548 stays OPEN, same-handle actual executable/image qualification B2 remains separately owed. Existing invocation-reader Nit6450901506 stays outside this slice. No new approval/history restamp or previous-run edits.

<!-- flow-run n=4 id=ee0a27b0f70f4c86adab33f853e35eb7 -->
## Run 4

- Run-id:            ee0a27b0f70f4c86adab33f853e35eb7
- Run-start:         192a7fd2a67b27b46bbf5d77045787610e29f591
- Issue:             #548
- Base SHA:          192a7fd2a67b27b46bbf5d77045787610e29f591
- Necessity verdict: Needs reframing
- Approval:          granted
- Approver:          owner (cooneycw), in-session reply "approved" to the Step-3 report
- Recorded at:       2026-10-28T15:40:00Z
- Note:              recorded after the first implementation edits (ordering slip, disclosed in the PR); the plan below is the one approved before any edit

### Section B evidence
Delivered since filing: 1d129f9/#584 (items 19, 22), f0cea73/#589 (transcript version reporting, not a gate), ea2704c/#592 (item 13); item 25 checked. Inspected ea2704c..192a7fd (#593-#614): only #594, #596, #601, #610 touch cli.py/docker_backend.py/matched_pilot.py, none adds a binary probe. No open PR for #548. Related issues considered (parked analysis): #40, #247, #279, #287, #203, #375, #12, #309, #315, #554 - none supersedes. Item 16 ruled out: level3 campaigns run a scripted actor/fake client pinned by harness_digest, never the codex binary.

### Section C - the approved plan
1. `skillc/trial_bootstrap.py` - probe_image_cli_version: `docker run --rm --network none --pull never --entrypoint <bin> <image_id> --version`, bounded; strict parser; UNKNOWN with reason
2. `skillc/cli.py` - pilot-run, calibration-run, level3-live, uptake-study refuse a mismatched or UNKNOWN measured client after the image binds; checkout-pin check unchanged; rehearsal/dry modes skip
3. `tests/test_trial_bootstrap.py` - probe and parser cases with a fake docker, incl. timeout cleanup
4. `tests/test_matched_pilot_run.py` - pilot-run CLI regression and fixture probe stubs
5. `tests/test_calibration_run.py` - calibration-run CLI regression (wrong-client case)
6. `tests/test_fixture_live_cli.py` - level3-live CLI regression
7. `tests/test_uptake_study.py` - uptake-study CLI regression
8. `tests/test_calibration_run_profile_closure.py` - fixture probe stub
9. `tests/test_calibration_outcome_endpoint.py` - fixture probe stub
10. `docs/specs/evaluation-facility/trial-bootstrap.md` - what is measured, what is not, UNKNOWN refuses
11. `changelog.d/548-image-client-version-probe.md` - scope note

Scope: ~11 files, 250-400 lines, mostly tests. Risks: fixture churn on fake-docker CLI tests; fail-closed on a daemon hiccup during the probe (deliberate, no bypass); version text is not attestation (the image-ID pin is); no Docker in skillc CI, so fakes only.
