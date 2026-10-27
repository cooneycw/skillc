# Flow run record - issue #549

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=9ee7cc9b0f6047d0b9de76b2709d477e -->
## Run 1

- Run-id:            9ee7cc9b0f6047d0b9de76b2709d477e
- Run-start:         7a10cacbcadab9311cb4e57b1095ea54a3848af6
- Issue: #549
- Base SHA: 7a10cacbcadab9311cb4e57b1095ea54a3848af6
- Necessity verdict: Still needed
- Approval: granted
- Approver: wave skillc-update orchestrator, clearance-549-selected-network-implementation.md
- Recorded at: 2026-10-27T19:37:28.269253+00:00

Root approval governs: exact seven product paths below; product1000AD inclusive future genuine receipt, workflow350AD separately. Native review/receipt filename/full/PR require later gates. Complete issue snapshot preserved; same actual run, no restamping. Action errors retain actual actions/read-only observed verdict; contradictory success/residual detail cannot clean. CLI source unchanged; both builders and normal/interrupt CLI controls required. Original Step3 candidate estimates below remain estimates, superseded only by these explicit approved ceilings.

# #549 actual fresh Step 3 - selected-attempt network recovery

Worker-02, actual native thread01a17cec-fab5-7860-b0e9-aeef446e1806/PID1102501. Fresh worktree `.`, branch `issue-549-docker-residue-egress-networks-live-test-images-in`, base/HEAD `7a10cacbcadab9311cb4e57b1095ea54a3848af6`, tree `35b3a649580fc0bf2b30b63e4d0bcf5b546b14db`, clean. Pinned CPP7f17055c92c053c153d1de1ae818a4bcd4ab8a45. Actual reconcile minted run `9ee7cc9b0f6047d0b9de76b2709d477e`; no approved record, begin-run, approval, implementation, review, receipt or product edit. Startupcross-repo/free/no existing PR/worktree conflict, verifyPASS/stashguardcurrent. Verify's transient claim1002520 was gone; bare canonical claim correctly acquired actual1102501, existing CPP Nit6426897177, not a new finding. Policy3current/EMPTY write lane; provenancehelperunknown remainsunknown.

## A. Intent in plain language

If an attempt is interrupted, its small private Docker network can survive even after its containers are gone. Today's recovery tool can then tell its caller that nothing remains, because it only looks for containers; enough leftover networks can eventually exhaust the runner's network capacity. This stage would let a caller recover both containers and networks for the exact attempt IDs it has explicitly selected and is authorized to stop, and would report what remains honestly. It would preserve other attempts and unrelated resources; it would not decide that an attempt is abandoned from its age, a missing local process, or an empty network.

This is an operational repair with its own bounded value. The owner's clarification https://github.com/cooneycw/skillc/issues/549#issuecomment-6397716583 supersedes the earlier cleanup-as-proof-prerequisite interpretation. Comparative CPP cleanup remains a separately preregistered experiment endpoint, not something this harness repair certifies. #549 remains OPEN after this selected-ID stage: live-test image ownership and interrupted-test automatic discovery remain unresolved.

## B. Necessity and current evidence

Verdict: STILL NEEDED, with the original broad orphan-sweeper suggestion narrowed to explicit owner-selected attempt recovery.

Read actual issue body, creation2026-10-24T11:56:24Z and both owner comments6397701048/6397716583. API body6848bytes/67lines/SHA62287baf145fc2a691609ce2970de89a391da3b605e11862e225bd9b5cd74d1e; native read-issue captured6849bytes/SHA80378f439d48216b94b0f4a5e63e7c8f1a829480676b49667edc64cdcc5f469e. Difference proved exactly the CLI's final newline, not changed contract. Generated speckitcontext ABSENT; issue is authority. Full body and comments saved externally; nothing truncated.

Post-filing global commits/merged PRs explicitly inspected: #558/#559/#560/#561/#562/#564/#565/#566/#567/#570/#572/#573/#575/#578/#579/#582/#583/#584/#586/#587/#588, ending7a10cac. None touching reap.py/tests_reap.py/egress.py/fake_docker.py since filing; reap last07417ec/PR91,2026-09-26. Relevant demo/CLI changes1c7c4c7/PR583,1fcf690/PR567,9a62b80/PR562,afce0e4/PR560 address completion, fixture guards or publication, not network recovery. Current #585 fixes Ruff cache production, #547 retains inputs, #544 reports honesty; none supplies reaper networks.

Related/duplicate dispositions considered: #79 CLOSED is original label-scoped recovery contract; #414 CLOSED deliberately forbids unlocked snapshot-based image deletion; #540 OPEN protects never-started conformance residue until producer identified; #551 OPEN owns unrelated fake path remapping/exec PID/FIFO fidelity; #546/#568 OPEN do not make this repair a comparative-proof prerequisite. No superseding network-reaper delivery found. No resources belonging to those issues were inspected or removed.

Current source:
- reap.py:82 `_list` queries only `docker ps`; :244 `reap` takes explicit IDs, loops inventory/mutation per ID, confirms only old container IDs, and can return `already-absent` without asking about networks.
- docker_backend.py:1149 `_start_egress` and egress.py:212 create labelled networks/proxies before risky calls; normal `_stop_egress`/confirm_absent account for them. Both ownership labels already exist; no producer or liveness schema change needed.
- fake_docker.py:1099 has network create/connect/rm/inspect, no network ls, no stable network ID, no real endpoint-refusal model; container IDs are12hex. It must be extended narrowly to test this new actual protocol, not treated as already faithful.

Actual SMALL existing-API observations rerun at7a10, stdlib unittest.mock only, no Docker subprocess/daemon:
`/tmp/skillc-549-native-analysis/existing-api-observations.json`.
1. Healthy no resources -> already-absent.
2. Network-only selected residue -> SAME already-absent, network still present; command log contains only ps.
3. Known container positive -> reaped, target gone; actual rm-ID and confirming query observed.
These are disposable observations, not a committed regression suite or daemon proof. Future actual regression will use current public reap API against a seeded fixture network and run on old production before modification; no missing-new-helper/enum exception counts as red.

### ALL report/caller/exit consumers inspected

- ReapReport:208-240 has four allowed outcome spellings and separate reaped/left_running/unknown projections; no complete clean/nonclean aggregate.
- demo.py:625 `_subject_acceptance_items` and :700 `_acceptance_items` both use reachable && !left_running && !unknown. A constructor-supported prospective `left-present` outcome actually produces MET in today's latter builder; direct existing-API observation confirms this without any missing API error. Arbitrary unknown spelling does too. New consumer controls must cover BOTH builders, empty population and invalid outcome, not only the new enum's existence.
- demo.py:667-672 and :849-852 serialize outcomes; latter hardcodes 'four possible values' and must be updated. Subject/general labels currently promise only containers and must name selected resources honestly.
- demo.py:1105/1110 timeout control, :1279/:1305 cancel control and :1438/:1440 orphan control use positive success spellings (reaped/already-absent or reaped), so left-present stays refusal. :1053 cleanup-pair regex accepts arbitrary outcome text. These remain unchanged except documentation wording if necessary; tests exercise these assumptions.
- demo.py:595 subject and :975 run_demo call recovery only with their recorded IDs. Result.ok derives from acceptance items. No auto-selection API exists.
- cli.py:840 interrupt recovery prints every outcome without enumerating spellings, shields a second SIGINT and unconditionally returns1 (:853); no clean-success branch exists there. Normal demo/control CLI :797/:810 derives exit from result.ok/control.ok, hence complete demo verdict is load-bearing. CLI source change NOT needed; tests in existing test_demo.py must prove normal residue exit1, clean twin0 and interrupt1 with emitted network residue. If implementation exposes a missed CLI contract, return before expanding the lane.
- Whole skillc search found no other ReapReport/reap.reap/outcome_for consumer. snapshot/diff remain explicitly container-only observations; no fleet-network sweep/claim is added. Tests importing reap for host snapshots are unaffected.

## C. Proposed implementation, approved with conditions

### Exact behavior to freeze

Selection is a nonempty explicitly supplied list of attempt IDs, deduplicated without broadening. The caller authorizes stopping those attempts; the reaper does NOT prove their controller is dead. No labels/PID/age/empty-endpoint inference, fleet autodiscovery, host scan, image prune or forced network disconnect.

Before ANY mutation, complete both resource lists and required ID/label/endpoint metadata for ALL selected IDs. Use --no-trunc and full64hex immutable IDs. Candidate lists carry both label filters; independently inspect returned labels and require the exact managed=true AND selectedattempt conjunction before scheduling removal, rather than relying on generic filter-combination assumptions. Missing labels/wrong values are excluded and preserved; malformed/partial/duplicate-conflicting metadata or query failure is uncertainty. Complete remaining initial observations as practical, then report UNKNOWN for the batch with ZERO rm calls if any initial inventory is uncertain. Empty resource inventory is clean only when both queries and all relevant metadata succeeded; empty requested population is refused.

The Docker network ls docs expose --no-trunc and label filters; rm accepts IDs and ordinary network removal requires disconnected endpoints. Sources: https://docs.docker.com/reference/cli/docker/network/ls/ and https://docs.docker.com/reference/cli/docker/network/rm/. Use one immutable ID per action, never batch network rm (it can continue after a failed member). These docs are protocol references, not observations of this host.

After complete healthy inventory, remove selected container/proxy IDs first, then selected network IDs with ordinary rm. Networks with foreign/unselected endpoint IDs are preserved and classified known residue; no endpoint disconnection. A new foreign endpoint racing after preflight makes ordinary network removal refuse; it is not forcibly detached. FullID/name-reuse/newselectedreplacement controls prove a new instance is neither chased nor erased.

On first action OSError/timeout/nonzero, STOP further mutations; retain actual per-resource action attempts/results and finish read-only confirmation where possible. Do not imply rollback or 'nothing touched' after prior successful actions. Proposed final outcome remains an observation: confirmed all resources absent can be reaped even if a removal reply failed, with action error retained; confirmed known residue is nonclean, unconfirmable absence is UNKNOWN. Unattempted resources after that stop remain known-present when confirmation succeeds. Root must ratify this observation-vs-action-error contract; an action error alone is not falsely asserted to mean residual absence or presence.

Confirm both exact targets and fresh selected-label inventories for both classes; any newly observed selected resource is known nonclean and not acted on by this call. Known remaining containers retain legacy `left-running`; known remaining networks use additive `left-present` (mixed residue prefers left-running with both remaining sets retained). Uncertain confirmation -> unknown. Keep existing positional ReapOutcome(attempt_id,outcome) constructors working through default additive detail fields for remaining container/network IDs and actual action errors. No success is fabricated from a successful rm exit.

Add ReapReport.nonclean covering ALL nonsuccess/invalid outcome entries and ReapReport.clean requiring daemon_reachable, NONEMPTY outcomes and no nonclean. Make both acceptance builders consume clean. Existing artificial 'captured + empty outcomes means MET' good fixture in test_demo.py:1591 must become a genuine one-attempt healthy report; empty itself becomes a committed refused-clean control. Preserve unavailable/not-exercised distinction. Existing left_running and unknown projections retain their old meanings; callers gain complete clean semantics.

### Exact prospective product paths (7), plus later genuine receipt

1. `skillc/reap.py` - dual-resource/ALL-selected preflight, strict immutable IDs/label conjunction, scoped actions, confirmation/races/action detail, additive left-present + complete nonclean/clean. Container-only snapshot/diff and host-path snapshots unchanged.
2. `skillc/demo.py` - both acceptance verdicts use complete clean; resource wording/five-outcome paste-back truthful. Existing positive-success controls/regex stay compatible; no client or lifecycle changes.
3. `tests/test_reap.py` - actual old-public-API network-only red run + healthy absence/container twins; committed scope/filter/fullID/inventory-failure/zero-removal/endpoint/race/action-error/confirmation cases. Update its existing12hex fake-ID expectation to64 for the same full-ID contract, not blanket test changes.
4. `tests/test_demo.py` - both builders reject known network residue, UNKNOWN, invalid outcomes and empty populations; genuine clean twins pass. Existing CLI entrypoint normal0/1 and interrupt1 output controls, old success-spelling controls preserved. Prospectivenewenum consumer probe is separately identified, not substituted for the real old-reaper regression.
5. `tests/fixtures/docker-backend/fake_docker.py` - ONLY stable64hex IDs, no-trunc/filter/query shape, ID-based selected label inspection, network ls/inspect ID+labels+endpoint facts, ID resolution/name-reuse and active-endpoint refusal plus narrow injected failures needed above. Preserve existing subnet -f contract and saved internal/labels fields. Realistic container label-query template may be added separately from existing status-inspect branch; no general exec/path/FIFO/image repair from #551.
6. `docs/specs/evaluation-facility/failure-matrix.md` - revise the actual existing four-outcome/reap/UNKNOWN contract to selected container+network recovery, all-selected preflight, action-error distinction, complete clean verdict, ownership/live/race limitations and fake-vs-daemon evidence limits. This REPLACES the old proposal's trial-bootstrap.md path: the former already owns the reaper's acceptance contract; unrelated bootstrap documentation need not grow.
7. `changelog.d/549.md` - NEW valid fragment for bounded explicit-ID network recovery only.
Future genuine `docs/measurements/counter-model/<actual-time>-issue-549.json` - reserved as required workflow instrumentation AFTER actual independent review; no fabricated filename/model/count/timestamp now. Its actual lines count toward product cap.

Explicitly unchanged: skillc/cli.py (consumer audited, unconditional interrupt failure/normal derived result contract tested), docker_backend.py, egress.py, all label producers, model/client/instrumented subject files, Docker configs, image ownership and historical/frozen fixtures/campaign evidence. No extra committed fixture tree/framework unless root separately grants one; bad/good inputs live in meaningful existing suite cases.

### Controls and cost

Genuine old-production regression: seed a selected network with current supported fake network-create operation (or independent valid fake state), call existing public reap, require that actual network absent/confirmed clean. Existing production returns already-absent leaving it present; healthy empty and container-positive twins prove the instrument sees more than zeros. Run this red before production edits, preserve full raw outcomes, then green on repaired production.

Committed discriminating populations: selected network-only and containers+proxy+network; idempotent second call; two selected IDs and unselected/live/unknown/foreign/missing-one-label sentinels; foreign endpoint preserved. Inventory container failure/network failure/later-selected-ID failure/malformed IDs/truncated IDs/bad metadata/timeouts/nonzero/OSError -> UNKNOWN+ZERO removals, with healthy populated twins. RemovedID replaced under same name, originalID disappears/newselectedID appears -> preserved replacement/nonclean/not chased. rm success lies -> known residue; first action error -> stop later actions/actual earlier action retained; confirmation failure ->UNKNOWN. Report clean/reaped/absent twins vs every nonclean/invalid/empty outcome in BOTH builders and normal/interrupt CLI behavior.

Estimate 7 product paths plus future receipt, roughly800-900 nonworkflow AD inclusive documentation/fragment/real31-ish-line receipt, about4-6h through review/full/CI. Approved cap1000AD including future genuine receipt; workflow350AD separately; do not compress controls or slip extra paths to fit, return if evidence demands more. Approximate allocation: reap260, fake170, reap tests250, demo35, demo tests80, existing-contract docs50, fragment1, receipt31 =877AD. These are estimates, NOT numeric/path authority.

Two future workflow paths only AFTER actual approval: docs/flow-runs/issue-549.md and issue-549.as-read.md. Full6849byte native source snapshot/67bodylines remains untruncated; full Step3 report currently external and can be committed verbatim/faithfully without dropping evidence. Workflow AD measured separately when actual native begin-run writes wrappers/history; do not count workflow as product or hide product in workflow. No approval/begin-run now.

Focused future checks: reap/demo/egress and affected fake-backend consumers, actual collect/JUnit population matched, committed bad/good inputs for each changed verdict. Independent counter-model review then one root-serialized canonical full only after separate authorization. Real daemon pair boundary remains separately gated; fake/mocked observations do not prove Docker behavior or authorize host cleanup.

### Risks / residual acceptance

Caller must supply only IDs it owns and intends to stop. The reaper cannot distinguish a live controller that shares that selected ID, so no abandoned-owner claim is supportable. All-selected preflight is not a transaction: external races remain; immutable identity and ordinary endpoint refusal limit action, report preserves partial actions/uncertainty. Full64-ID fake changes may expose fixture assumptions; only necessary narrow changes are proposed, no #551 repair authority. Adding report semantics is load-bearing; every consumer must refuse network/invalid/empty residue before shipping.

Whole549 stays OPEN: image ownership/sweeper and interrupted-test automatic discovery, comparative CPP cleanup endpoint, protected540 residue, shared resources and unknown ownership all remain unimplemented. No Docker inventory/process/probe/deletion, host install, model study, tests/full/review, tracked product/workflow edit or issue mutation has occurred in this startup. Only essential current-API in-memory observations were executed.

Final optional native drift observation: `ISSUE_DRIFT: unresolved (no as-read snapshot on this branch)`, exit4. The read-issue evidence exists in native git metadata; the committed snapshot is deliberately absent before authorized Step4 begin-run. Do not interpret this as clean drift or manufacture a tracked snapshot to erase it. Actual API body plus CLI newline independently matches the recorded read digest exactly.

Original Step3 STOP: actual A/B/C returned to orchestrator before begin-run/approval/product edits, under flow-eli5/reference.md Step3 and wavepolicy3/orchestrator-only authority. Pending: ratify seven paths + real receipt allowance,900AD candidate, fullID+label preflight, left-present/completeclean/empty behavior and postaction-error observation contract.

LEDGER
delivered: Fresh549native startup/currentmain/issue+ownerclarification/source+history/ALLconsumerinventory, controlled existingAPI failure/healthy observations, exact revisedpath/cost/control proposal.
in-scope: Actual freshStep3analysisONLY, write laneEMPTY.
residual: Rootjudgmentbeforeimplementation; other549items/comparativeendpoint remainOPEN; no resourceactionorcodeauthority.
