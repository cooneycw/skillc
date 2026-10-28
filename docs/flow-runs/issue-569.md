# Flow run record - issue #569

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=14071fc0891f422e91c0a1b80e7e9a95 -->
## Run 1

- Run-id:            14071fc0891f422e91c0a1b80e7e9a95
- Run-start:         6b78522a9e16baca33254dfc448a8cbc59e166d1

- Issue: #569
- Base SHA: 6b78522a9e16baca33254dfc448a8cbc59e166d1
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: skillc-proof orchestrator, approved fresh issue569A delivery
- Recorded at: 2026-10-25T09:44:06.974346+00:00
- Original contribution: BB candidate701fcd85b110b4449cbbcec5002b96b59c5d3dd0/tree911c61c34272cda30d88ac98d84bfba8200f5fba. Current worker adopts six product files after fresh approval; historical reviews,54focused checks, original workflow and refused provenance remain distinct/protected.

### Section B evidence
Verdict: Partially addressed - reviewed product code exists in a protected contribution, but the current supported API is not yet shipped on main.

Fresh actual worktree: skillc-issue-569-certify-bounded-register-wave-completion-with-cont; branch issue-569-certify-bounded-register-wave-completion-with-cont; base current origin/main6b78522a9e16baca33254dfc448a8cbc59e166d1. Standalone fresh resolver returned WT_CREATED=1/LANE=cross-repo/EXIT0; a separate literal git status --short returned empty. Standalone verify reported CLAIM=self/STASH_GUARD=current; reconcile minted run14071fc0891f422e91c0a1b80e7e9a95 and read-issue recorded body digestc7869ff86d7577b9cc1d6fef3419d428625d709162b553df87f952f4982e5bd4. No begin-run/approve/product import has occurred.

Early ordinary provenance preflight, before product work: unchanged helper derived codex/gpt-6.1-sol from the COMPLETE original native thread, errornull, no manual/scoped window (CC-569A-ordinary-provenance-preflight.json). Original BB mixed whole-thread/scoped refusal remains protected, not repaired or imported.

Issue created2026-10-25T07:32:17Z. Global history since filing contains6b78522/PR570(08:40:43Z), which adds the separate explicit-product calibration contract; scoped history contains no commits touching these six paths. Same-day PRs562/564/565/567 predate filing. Considered #14/#245/#246 programme/measurement boundaries, #252/#278 recovery tasks, #279 workflow evidence, #183 disruption-contract reuse, #568's independent task preparation, and NEW OPEN#571 task attachment. #571 explicitly awaits this foundation on main and supplies the next implementation seam; it does not supersede or complete #569A. CPP1560 is now delivered/closed at merged87ecb0970f70aace9e0323feee00c9ca57dda133, with oldDD/fixed pin +manual scenario in569comment6395963565; that documentation does not make native wake measurable here.

Host inventory:15 listed worktrees, all15 readable. Exactly one sibling has relevant unpushed work: root-protected skillc-archive-bb-569-run-6823226e at701fcd85b110b4449cbbcec5002b96b59c5d3dd0/tree911c61c34272cda30d88ac98d84bfba8200f5fba. Its source commitacf28fc plus a genuine merge of current6b78522 are present; its metadata's original base1fcf690 is historical, not this fresh delivery base. All six product blobs/content hashes were independently reread from Git (CC-569A-contribution-identity.json). Original workflow records/raw reviews/refusals remain in the archive. No missing worktree was folded into a clean result and no cleanup was widened.

Actual source inspected: the entire506-line coordination_wave.py, actor, committed cases, test structure/assertions, readiness matrix, original seven review findings/fix dispositions and actual behavioral-red excerpts. Existing trial.run_attempt/capture/finalize/cleanup plus DecideReplyChannel are reused. run_wave is closed to three trusted scripted roles with pinned actor bytes, not an arbitrary agent/argv/backend fallback. Normal main lacks this module. Original final-focused log (BB-569A-final-focused.log, distinct from an earlier failed similarly named log) actually reports54PASS/10.77s with54 collected/report identities equal. Original review regressions include6actualfailed assertions before first fixes and4before second fixes; these are preserved BB executions, not newly executed here. Original contribution has never passed fullverify/finish/CI or produced a valid review receipt.


### Section C - the approved plan
1. `skillc/coordination_wave.py` - Adopt the pinned BB closed trusted-scripted wave API, controller-owned request/capture/lifecycle joins, one-wave verdict and explicit completion/publication boundary.
2. `tests/fixtures/coordination-wave/role_actor.py` - Adopt the pinned trusted isolated-import scripted actor with closed healthy/adverse modes.
3. `tests/fixtures/coordination-wave/cases.json` - Adopt committed healthy/alternative/delayed, FAIL and UNKNOWN controls with unchanged initial expectations.
4. `tests/test_coordination_wave.py` - Adopt54 focused actual process/socket/capture tests and committed setup/corruption/cancellation/deadline/publication controls; add actual reds for any review-driven in-contract fix.
5. `evals/coordination/register-wave-completion/READINESS.md` - Retain complete bounded matrix/publication semantics; add only original-contribution versus fresh-delivery attribution, actual CPP DD/87ec scenario and571 continuation.
6. `changelog.d/569.md` - Adopt the bounded offline foundation fragment, keeping569/live readiness open.

Scope: six product paths plus own fresh workflow/as-read and one later exact generated review receipt; ceiling1400 nonworkflow changed lines. Initial five product blobs unchanged; READINESS only bounded attribution/pin note. In-contract review fixes require actual pre-fix red proof; broader API/scope returns to root.

- Exactly one planned wave is primary; three role attempts are diagnostics, including non-starts. Two independent captured worker artifacts precede integration, whose bytes must name both actual captured digests. No expected-solution substitution or completion-claim-only PASS.
- Three active roles,128 requests/events,4KiB requests,16KiB pinned actor source, two values at most256UTF8bytes, one finite deadline0<d<=30s, first-offer defer0<=delay<=1s. The single deferred offer is later released; repeated polls are not a resend, transport retry or missing-wake recovery.
- Controller-host trusted fixture only: actor source is caller-pinned/copied, Python-I launch, process groups/sockets/resources owned; no hostile same-UID authentication/isolation. Requests/decisions and participant receipt claims do not observe native delivery, wake, tool execution or downstream client activity. Native_wake staysUNOBSERVED.
- Positive protocol/artifact violation isFAIL; unavailable launch/capture/channel/cleanup evidence isUNKNOWN; independently witnessed task failure survives later observation loss. Setup exceptions preserve planned accounting/nonpassing evidence and re-raise after owned resources close.
- Completion deadline starts before validation/setup and covers actors, artifact/channel capture, final evidence joins, confirmed cleanup and INITIAL NONPASS provisional evidence. Immutable completion_elapsed is sampled afterward. FINALdecision staging/atomic replacement is outside that completion deadline; failed publication raises and leaves authoritative nonPASS evidence, never a stalePASS. This does not certify final publication duration or forcibly interrupt host filesystem/callback operations. Adopt this exact boundary explicitly; do not call it full end-to-end wall-clock certification.
- Current profile has no disposable Git/service task, native client startup, missing-wake observer or matched live arms. Those are explicit#571/future569 readiness prerequisites. The actual delivered CPP documentation pin is available but is not installed or evaluated as a treatment by this slice.

Verification/review/controls:
- Compare copied source/fixture/test/changelog blobs against the exact protected candidate; READINESS differs only by approved provenance/pin/continuation note. Normal post-approval file-level reuse is counted by current run-start compliance. declare-salvage is inapplicable because the sibling candidate is not an ancestor of freshHEAD; do not manufacture ancestry or import workflow records.
- Run selftest before trusting skillc check. Run make test PYTEST_ARGS=tests/test_coordination_wave.py with independent collected/JUnit identity equality; run lint/type checks. These are new observed controls only after execution, not assumed54PASS from the archive.
- Healthy/default and alternate work order plus deferred single offer mustPASS. Wrong source-role/session/generation/wave/task/attempt/revision/nonce, boolean lookalikes, duplicate/unregistered/unreceived operations, claim without artifact, missing integration, natural disappearance and witnessed deadline mustFAIL. Resource/launch/channel/capture/cleanup unavailability mustUNKNOWN. All preserve planned accounting, final joins and owned-process/workspace cleanup.
- Retain replay/partial setup/staged actor failure, request129, handler drain, post-relay corruption, deleted/replaced channel, natural-exit/timeout with later infrastructure loss, slow provisional publication and failed final staging/replacement cases. Known-bad inputs are committed. Existing original behavioral reds are attributed to BB; do not label missing API/import failures onmain as regression proof. Any new substantive defect fix gets an actual red run on pre-fix adopted code, then green.
- One fresh independent delivery review is requested; a second only for accepted fixes under the normal two-pass cap. Preserve original BB two reviews/seven fixes as history, not a third review of that run or new work credit. Derive actual current whole-thread/reviewer identity and actual receipt; early current whole-thread preflight already passed.
- Request root's shared-host full-test slot after review. Run mandatory bare finish first; if its actual plan executes COMPLETE required makeverify with all required outcomes, do not duplicate the identical suite. Preserve any actual failure/context/resume limits, all-negative-control results and population identities. No test deselection/cache assertion to replace required full verification. Ordinary exact-head requiredCI/separate merge clearance remains necessary.
- No live agents/model study, host install, retired native-wave engine, production timeout recommendation or effect-size claim. Deterministic/injected clocks prove policy only. Keep#569OPEN; publish actual shipped API/pin to#571 only after delivery so that implementation can proceed on realmain.

Risk/challenge:
The generic wave instrument can be mistaken for a full native task benchmark; its explicit trusted-host/request-claim/capture/publication bounds must stay prominent. Final decision emission outside completion deadline and uninterruptible hostI/O preclude a hard end-to-end deadline claim. Preserve default public API and exact publication semantics for#571; a need to change either returns to root. Actual artifact task attachment remains an active bounded dependency, not an excuse to claim readiness or revive a platform.


Boundary: no oldworkflowapproval/receipt imported, artificialancestry/inapplicablesalvage, liveagents/modelstudy/nativeprobe,hostinstall,newsessionengine or readiness/efficacyclaim. Parent569 remainsOPEN; actualshippedAPI/pin goes571 onlyafterdelivery.
