# #548 B2 - fresh flow:auto Step 3 STOP

Status: ANALYSIS ONLY. No implementation contract selected or approved. Worker-01 write lane is explicitly EMPTY. Root, as policy3 orchestrator-only authority, receives this report for judgment; no repeated user confirmation is requested.

Fresh startup: actual delivered main ea2704cb57c2133ffda54c962b7a5bab34de9da2, tree15c72108bd3c7177fc0ffe2fd058e469e55afac3. Canonical start-resolve548 cross-repo fresh worktree/verify0; reconcile minted NEW run78d1052bb8ed42bd95d784a0339b6544 at2026-10-28T00:39:49Z, native codex_thread01a17ce6-4b92-7802-b7c7-35181ac56d6a. Old a9cb/c302 is archived historical approval, never reused; fresh baseline file ABSENT. No begin-run/approve or tracked record edit. Fresh issue snapshot read2026-10-28T00:39:54Z: canonical digest2bfb74d9add975c5de5eea2c3626e1d4877527a3e1435f048d322757e2c7ef84/15214B; actual GitHub body091c5103bc4804ee9443783ac55e256ad91d7307b465837976db7b9e87571984/15213B (helper appends a newline). Issue remains OPEN.

Startup verify initially staked a sessionless claim against its transient parent4172071. Its ordinary owner-exited stale takeover was performed by standalone exec of the pinned canonical claim helper, without PID/session overrides/force/steal; actual owner2186472/start33985101, raw OWNER_WITNESS=matched, SELF. New claim session remains honestly '-' while RunState carries actual Codex thread. Registry uses same actual PID/address, session '-', verifiedFALSE/provenanceUNKNOWN; no identity alias used for fresh startup/recovery. This is distinct from the older accepted SID-fast-return witness clarification. No claim/native/approval file was hand-edited.

## A. What the remaining issue wants

A label saying which program should run does not show which program was actually available when the task started. Today a declared client version is compared with a build recipe, while separate checks establish the image identity and transcript facts. The remaining work would measure a supported client inside the actual task container after setup finishes, then compare that measured version with the declaration before allowing the task to start. A script actor legitimately running under a Codex-labelled experiment must stay distinguishable from a native client, and a measurement that cannot establish that distinction must say UNKNOWN rather than certify it.

This is a proposed partial improvement only. It would not certify arbitrary launch scripts, guarded calibration, Claude, historical actors, frozen studies, or the whole parent issue. No runtime measurement has been performed during this analysis.

## B. Necessity, current source and overlap

Verdict: PARTIALLY ADDRESSED; remaining binary work NEEDS REFRAMING before a bounded implementation is chosen.

Issue filed2026-10-24T11:56:24Z. Actual global and scoped post-filing histories and merged-PR query are saved beside this report. Relevant inspected commits/PRs:
- 1d129f9/#584: complete Level-3 runtime declarations and treated skill pins; delivered A, not running-client measurement.
- f0cea73/#589: B1 derives retained transcript version facts; a report observation, explicitly not qualification.
- ea2704c/#592: exact legacy tag plus image-ID guard; now delivered, no binary claim.
- 1c7c4c7/#583: shared completion deadlines through Docker/dispatch/grading; any new prelaunch operation must consume that original allowance.
- 1f425b2/#587: controller-issued prompt retention; does not measure the executable.
- 1fcf690/#567, 9a62b80/#562, a924c5f/#565, c804555/#559 and afce0e4/#560: witnessed resume/preflight/retention/backend context inspected in scoped history, not a replacement for final-handle client identity.
- Current integrated main also includes20a0359/#590 cleanup and1a28212/#591 aggregate gate qualification. Neither supplies the missing client observation.

Duplicate/superseding query returned548,247,279,20,203,287,554,4,40,7,375,434,12,315,309,10,38,288. Titles/state are saved in related-issues.txt. Considered specifically: #40 declared drift protocols, #247 client/profile context, #287 and #203 study contracts, #375 frozen actor evidence, #12 initial pilot, #309/#315 Docker provisioning, #279 resume certification and #554 docs drift. These are surrounding contracts or completed studies, not evidence of a delivered general same-final-handle measurement. No new duplicate issue is proposed.

Host overlap: all registered worktrees were queried for relevant commits on no remote. Only skillc-348-qualify-stdout-compat has such commits:536d02c and9caf33c. Their stats and selected source show controller witness capture/runtime_ready/runtime_environment including uv--version, not a client-version qualifier. Existing current source already contains these seams. Do not alter that sibling, treat its mere existence as certification, or duplicate its runtime-supply platform. No sibling was unreadable. #544 remains solely allocated combined-main integration/full; this read-only analysis took no test/Docker/full slot.

Current caller inventory, checked on ea2704c rather than relying on old6840 preparation:

| Caller/source | Actual boundary | Consequence |
|---|---|---|
| skillc/trial_bootstrap.py:72 | pinned_cli_version reads checkout build pins | Intention, not runtime observation. |
| skillc/cli.py:1485,1508-1534 | pilot-run chooses default or custom argv, compares declared version to build pin, resolves image | Explicit default selection can anchor a new opt-in; custom argv cannot be silently certified. |
| skillc/matched_pilot.py:944,982-997 | run_pilot accepts arbitrary argv_for/backends and forwards declared cli_version plus shared deadline | Programmatic callers require explicit applicability too; client label alone is inadequate. |
| skillc/collection_conformance.py:689,767 | common real-or-scripted adapter forwards into run_one_attempt; project gate selected from task | New optional requirement could be forwarded; omitted must preserve existing actors. |
| skillc/agent_trial.py:2524,2807 | client spec and declared cli_version are independent of base_argv | No universal native-versus-actor qualification contract is present here. |
| skillc/calibration_run.py:663,736,855,1273,1333 | both calibration routes call common adapter; supported Codex route enables nested guard | Initial unwrapped option must exclude guarded calibration explicitly. |
| skillc/level3_campaign.py:342,405,430 | actor_argv launches an interpreter/actor.py; client label remains codex | Healthy Python actors must not receive a global missing-native-version refusal. |
| skillc/fixture_campaign.py:385,441; skillc/fixture_live.py:1117,1137 | explicit actor/rehearsal routes or supplied client argv | Actor provenance is controller-selected; never infer applicability from a basename. |
| skillc/agent_trial.py:2246,2354 | discovery/listing prepares separate throwaway containers | Matching discovery-client version cannot certify the final task handle. |
| skillc/docker_backend.py:1644 | image_id(handle) inspects actual prepared container image | Appropriate same-handle image fact, distinct from configured mutable tag. |

Bounded source-search positive controls: _preflight_in_container in agent_trial.py and docker_backend.py:1787 uv--version are actual source executions found by the search. The inspected final-launch composition still has no native Codex/Claude qualifier. This is a bounded source inventory, not an unbounded repository absence scan or a binary probe.

Final-handle/environment/deadline sequence, confirmed in current source:
1. lifecycle.py:467-501 prepares one handle, installs, records identity, then calls before_execute. Hook refusal prevents dispatch and retains normal teardown.
2. agent_trial.py:1310 calls runtime_ready BEFORE file/tool preflight and gate overlays at1323-1362. It is too early for final client selection.
3. agent_trial.py:2914-2939 adds outer witness/guard binding; project make shim is placed LAST and final PATH assigned at2923-2928. Any selected probe must wrap AFTER this outermost composition.
4. Final primary execution receives DockerBackend.agent_exec_env (agent_trial.py:2722,2767; docker_backend execution route). exec_in_attempt(handle,...,cwd,env) at2495 supports the same override and live handle. controller_output at1736 does not accept env; do not silently substitute it for final-PATH measurement. execute is one-shot/stops the container and must not be used for the auxiliary probe.
5. lifecycle.py:533-537 attaches original completion_deadline only AFTER before_execute. A new hook must explicitly use the passed original deadline in bounded Limits, check remaining time before/after, and preserve its end/clock/identity domain; never mint a fresh allowance. Mock clocks can prove policy only.
6. DockerBackend.image_id must inspect that same handle; discovery handles/default PATH/pre-overlay success cannot substitute. Post-stop observation is too late to query an executable, though it can retain an earlier bounded fact.
7. fixture_overlay.py:199-220 resolves a root-owned immutable Node/Codex/native chain and installs the guard. docker/fixture-service/skillc-codex-guard.py:168-204 emits a decision for EVERY invocation before pass-through. A naive guarded codex--version adds an accounting event. Do not suppress/subtract/fake it or call the unguarded real binary and claim the selected guard was measured.

## C. One costed option for root judgment; no implementation approval

Propose B2a only for NEW explicitly opted-in, unwrapped Codex matched-pilot launches. The option is not selected by this report. Default/omitted opt-in retains current behavior and historical UNKNOWN. Explicitly require supported controller-selected native launch provenance, declared expected client/version and expected image ID. Refuse custom/script/guard/unsupported/writable/ambiguous chains as UNKNOWN/unqualified within the opted-in required route before primary dispatch; do not infer native status from client='codex', egress/model labels, basename, or a matching version string.

After all setup/overlays, measure the selected supported launcher chain and complete zero-exit version output on the SAME final handle, cwd and effective exec environment; bind that to actual handle image and original deadline. Store only bounded controller evidence, not raw environments/credentials/host-private paths. Matching text alone is not cryptographic attestation; unsupported chains cannot become a success by printing the expected string.

Contract decisions root must make before granting any paths: exact explicit opt-in boundary/flag, supported immutable launcher chain, evidence schema and UNKNOWN disposition. If runtime measurement is authoritative in that opt-in, the old checkout-version equality must not refuse it before measurement; propose retaining client-name validation and preserving the entire old static check for omitted opt-in, with the opted-in branch relying on declared expected version plus required runtime result. That is a consequential source-of-truth change requiring explicit approval, not an incidental implementation detail.

Prospective exact product paths, NONE currently enrolled:
1. skillc/agent_trial.py - optional requirement, final outer hook, same-handle/env measurement, original-deadline refusal and bounded evidence (80-120 A+D).
2. skillc/collection_conformance.py - optional forwarding, no implicit native classification (8-16).
3. skillc/matched_pilot.py - explicit new-run requirement and expected image/version propagation; preserve arbitrary-argv ordinary callers (10-20).
4. skillc/cli.py - explicit pilot-only opt-in, default/custom boundary, version-check source selection and honest help (10-25).
5. tests/test_agent_trial.py - mock final-handle/PATH/image/version/deadline/unsupported/evidence opposites (100-160).
6. tests/test_matched_pilot_run.py - API/CLI propagation, omitted opt-in and actor/historical compatibility (45-75).
7. docs/specs/evaluation-facility/trial-bootstrap.md - bounded applicability, measurement meaning, UNKNOWN and residuals (15-25).
8. changelog.d/548-native-pilot-qualification.md - partial scope note (1-3).

Estimated eight product paths/269-444 A+D before a genuine later receipt; prospective total product ceiling500 INCLUDING receipt, workflow ceiling350, both pending root judgment. No lifecycle/backend/guard/protocol/frozen-source edits in this option. If required guarantees cannot fit existing seams or this ceiling, return to root rather than expand. Actual run records/receipt paths would need separate future enrollment only after approval/review, never during this EMPTY lane.

Proposed controlled mock opposites (NOT RUN):
- Supported final launcher + exact version + actual expected handle image qualifies/dispatches; same facts with different version refuses/no primary execute.
- Identical tag but wrong final image refuses; matching discovery handle does not rescue it.
- Overlay changes PATH after runtime_ready: final unsupported/wrong launcher remains UNKNOWN/refused despite earlier match.
- Equal text from writable/custom/Python/shell/guard launcher remains UNKNOWN; supported complete successful output differs from nonzero/empty/malformed/ambiguous/truncated/incomplete/oversize output.
- Deadline exhausted during setup/probe prevents launch; fast success retains original deadline end/domain for dispatch, publication and cleanup. No new clock allowance.
- Python actor labelled codex and omitted opt-in makes zero probe calls and preserves existing grades; opted-in incompatible actor refuses only within that selected route.
- Guard selected: reject unsupported BEFORE its version invocation; no extra guard decision, no event subtraction. Existing B1 transcript facts, receipt discovery and credit/accounting remain independent.
- A committed known-bad input must demonstrate any new load-bearing instrument's other verdict; existing public regression must actually fail on immutable pre-fix source after root grants testing. No red/probe performed now.

Risks: applicability mistakes could reject healthy actors; stale PATH could measure the wrong program; an extra probe could change guarded counts or exceed allowance; version-text spoofing and candidate-writable chains limit authenticity; a false global-certification claim would overstate coverage. The alternative is conservative UNKNOWN/OWED with no implementation until a trustworthy native boundary is approved. That alternative preserves truthful delivered B1/legacy facts and all frozen375/271/287/CPP87ec evidence.

Cost/priority: analysis performed with source/Git reads only, zero tests/Docker/native/version/model/paid-study execution. Future option roughly one engineering session (3-5h plus one bounded independent review and one scheduled canonical full), no physical/paid qualification included or budget authorized. Illustrative WSJF assumptions: business value3 + time criticality1 + risk reduction3 =7; size5 =>1.4. These are planning estimates, not measured economic data or a scheduling grant. It remains below already allocated #544 delivery/full; no heavy slot requested now.

Delivered: A/static completeness, B1 retained-version reporting, legacy exact-tag+ID contract and exact delivery handoff.
In scope now: this fresh native/source-only analysis and Step3 report, EMPTY write lane.
Residual: three binary/runtime items and four acceptance boxes remain OPEN. No broad missing-version gate, guard-accounting rewrite, frozen migration, live/native/model/physical experiment, extra review/receipt/full/publication or whole548closure is approved.

ACTUAL STEP3: STOPPED pending root judgment of this new Section C. No begin-run, approve, implementation, tests, probes, Docker, native/version client, model call or study performed.
