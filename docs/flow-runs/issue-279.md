# Flow run record - issue #279

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=68fae56908044068bdcb3519856ffca6 -->
## Run 1

- Run-id:            68fae56908044068bdcb3519856ffca6
- Run-start:         2a2e287a74b3f40206720ea97ac749ba80718877
- Issue:             #279 (PR 1 of ~4: the controller approval-turn driver)
- Base SHA:          2a2e287
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated), "approved #279 PR1" with two required changes
- Recorded at:       2026-10-18T13:40:00Z

### Section B evidence
none - no controller multi-turn mechanism exists on main; the #434 live-wiring branch's README reserves a `turns` identity for exactly this (commit 1a92c89).

### Required changes (orchestrator)
1. Guard interaction: each resume is a new top-level `codex exec resume` launch. The expected top-level count is the delivered turns (1 + approvals), recorded in the observation, and anything above it is still nested-suspected. Reds: 2 turns with 2 top-levels is clean; 2 turns with 3 is suspected; 1 turn with 2 is suspected.
2. Turns are declared PER CASE. The schema binds turns to a case (TWIN gets the approval, CLEAN gets none), never "always after a clean exit". Red: a case declared with no turns never receives one, even after a clean exit.

### Section C - the approved plan
1. `skillc/controller_turns.py` - per-case v1 turns schema (literal texts, 0-3 per case, keys equal the declared cases); resume_argv (codex only; --sandbox becomes -c sandbox_mode=...); session id read from the turn-1 rollout
2. `skillc/lifecycle.py` - run_through_backend next_turn hook: further execs in the same container within the shared wall budget; per-turn events
3. `skillc/agent_trial.py` - run_one_attempt(turns=...): resume preflight, observation.turns, and the guard's expected top-level count
4. `skillc/codex_guard.py` - nested verdict judged against the expected top-level count (if the guard lives here)
5. `tests/test_controller_turns.py` - schema, resume argv, the scripted-actor delivered/withheld/timeout/no-session reds and the guard-count reds
6. `tests/test_agent_trial.py` - the fake codex learns `exec resume`
7. `changelog.d/279.md` - one bullet
8. `docs/specs/evaluation-facility/fixture-service.md` - a controller-turns section
9. `docs/flow-runs/issue-279.md` - this record

Scope: about 9 files, 1 PR. Risks: the guard count semantics (a looser count could hide a nested launch, so the reds pin both sides), and the shared wall budget across turns.

<!-- flow-run n=2 id=af5f4e6d1f9c44e3aa5ebe5878d60a18 -->
## Run 2

- Run-id:            af5f4e6d1f9c44e3aa5ebe5878d60a18
- Run-start:         7c1d408f18ce37e460e2c8942273581b0d6c079f
- Issue:             #279
- Base SHA:          7c1d408f18ce37e460e2c8942273581b0d6c079f
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-400 orchestrator (authority-model orchestrator-only), GATE GO-WITH-CONDITIONS #279 (R1-R5), 2026-10-20
- Recorded at:       2026-10-20T21:05:00Z

### Section B evidence
#279 OPEN, parked 2026-10-18 (6252677230); PR 1 merged #474 16732600. Since then 043279f (#482), 1eaac29 (#488), 21c20e2 (#490) touch fixture_live/controller_turns/codex_guard; none wires turns into the live path. #277 OPEN consumes the seam. Duplicates: none.

### Section C - the approved plan (this run is PR-1, no spend)
1. `skillc/fixture_live.py` - optional digest-bound `task.turns` (controller_turns.parse_turns) passed to run_one_attempt; per-attempt controller_turns in the report; turn-aware rehearsal actor; `containment.nested_codex: "refusal-expected"` (closed, explicit, digest-bound) in containment_trigger
2. `skillc/codex_guard.py` - the opt-in reading of a confirmed refused-nested launch (no stop, no credit block; counted); suspected/ancestry_unknown/passed-through still stop
3. `skillc/agent_trial.py` - the credit gate honours the opt-in only
4. `tests/test_fixture_live.py` - turns digest/delivery/guard-count reds, absent turns byte-identical, opt-in reds incl. passed-through stops, clock test
5. `tests/test_codex_guard.py` - opt-in credit reds
6. `evals/level3/flow-auto-step6-gate/` - new task: builder reusing flow-auto-necessity's by import, case twin-gate (pre-existing fix-independent lint failure), measured gate tails, README, DESIGN.md (grading S1-S5, blind-validation rule, pre-registered risks)
7. `changelog.d/279-turns-wiring.md` - one bullet

Scope: medium. Risks: G1 containment semantics; receipt-writer stall before the gate (unmeasured); 900 s may be tight for Step 6; controller clock dependency (tested).

<!-- flow-run n=3 id=c6e8c67944254c6194dd04d83068bbdf -->
## Run 3

- Run-id:            c6e8c67944254c6194dd04d83068bbdf
- Run-start:         7cdf37af481a5568f42a102fe1df28306ed2a781
- Issue:             #279
- Base SHA:          7cdf37af481a5568f42a102fe1df28306ed2a781
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-400 orchestrator (authority-model orchestrator-only), GATE GO-WITH-CONDITIONS #279 PR-2 (R1-R5), 2026-10-20
- Recorded at:       2026-10-20T22:20:00Z

### Section B evidence
#279 OPEN; PR-1 #495 (7cdf37a) left residuals (1)-(5) recorded in evals/level3/flow-auto-step6-gate/DESIGN.md. Nothing merged since touches them. Duplicates: none. Existing #434 records are not retro-fitted (they predate the counter and never reach Step 6).

### Section C - the approved plan (this run is PR-2a, the recording layer; the grader is PR-2b)
1. `skillc/ordering.py` - a per-attempt, lock-guarded, controller-owned monotonic counter
2. `skillc/source_digest.py` - sha256 over sorted (path, git mode, git blob id) of the gated repository root, minus .git and .claude/friction.jsonl, ignore rules not applied
3. `skillc/fixture_service.py` - event["order"] when a counter is supplied
4. `skillc/gate_witness.py` - run order_requested/order_completed and source digest at start when supplied
5. `skillc/lifecycle.py` - controller-turn records carry order when supplied
6. `skillc/agent_trial.py` - one counter per attempt, only when turns are declared; turn orders in the trusted observation
7. `skillc/fixture_attempt.py` - the counter reaches the fixture service
8. `skillc/git_snapshot.py` - source digests of shipped heads (remote ref heads) without a git process
9. `skillc/fixture_campaign.py` - builder cache keyed by the resolved builder path
10. `skillc/fixture_live.py` - closed task registry (task.path selects cases, identities, rehearsal candidates)
11. `evals/level3/flow-auto-step6-gate/builder/build.py` - capture records shipped source digests
12. tests (append-only on existing hot-path modules): `tests/test_ordering.py`, `tests/test_source_digest.py`, `tests/test_fixture_service.py`, `tests/test_gate_witness.py`, `tests/test_fixture_live.py`, `tests/test_fixture_campaign.py`, `tests/test_flow_auto_step6_gate_task.py`
13. `changelog.d/279-recording-layer.md` - one bullet

Scope: large. Risks: shared hot-path stamping (turns-only, byte-identical controls, existing tests unmodified); population rule (mismatch reads UNKNOWN in PR-2b, never SATISFIED).

<!-- flow-run n=4 id=3c1c966a03234f1db488c9e042c7e011 -->
## Run 4

- Run-id:            3c1c966a03234f1db488c9e042c7e011
- Run-start:         a282164b5a64e6036efec849187d1f6c70d03f41
- Issue:             #279
- Base SHA:          a282164b5a64e6036efec849187d1f6c70d03f41
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-400 orchestrator (authority-model orchestrator-only), GATE GO-WITH-CONDITIONS #279 PR-2b (Deltas 1-3), 2026-10-21
- Recorded at:       2026-10-21T07:00:00Z

### Section B evidence
PR-2a merged #496 (d5903e5): order on service events, witness runs (order_requested/completed, source_digest_at_start), controller-turn records; remote_ref_sources of FINAL heads only, captured post-stop. Applied pr.create/pr.merge effects record head_oid. git pushes never pass the service. Duplicates: none.

### Section C - the approved plan (this run is PR-2b, the grader)
1. `skillc/fixture_service.py` - on ship requests (pr.create/pr.merge) in attempts with an ordering counter, an injected stamper records `ship_stamp`: the source digest and gate-definition digest of head_oid, computed at the request; absent or unreadable stays visible
2. `skillc/source_digest.py` - the gate-definition file set and its digest over the same population
3. `skillc/fixture_attempt.py` - the stamper wired from the exported remote (no git process)
4. `evals/level3/flow-auto-step6-gate/grade_gate_stops_early_step6.py` - NEW stdlib judge, S1-S5 per Deltas 1-3; prose recorded, never scored
5. `evals/level3/flow-auto-step6-gate/grader.json` - NEW
6. `evals/level3/flow-auto-step6-gate/probe.py` - NEW
7. `evals/level3/flow-auto-step6-gate/inputs.json` - NEW
8. `evals/level3/flow-auto-step6-gate/qualify.py` - NEW: scripted-timeline harness on the real FixtureService, GateWitness and Order; broken-grader and blinding controls
9. `evals/level3/flow-auto-step6-gate/candidates/` - NEW: SATISFIED/VIOLATED/UNKNOWN per criterion, the S3 ordering reds
10. `evals/level3/flow-auto-step6-gate/grader-controls/` - NEW: always_pass, always_fail, crash, no_output, omits_criterion
11. `skillc/fixture_live.py` - REHEARSAL_BY_TASK twin-gate entries
12. `tests/test_flow_auto_step6_gate_task.py` - append-only
13. `tests/test_fixture_service.py` - append-only stamp reds
14. `evals/level3/flow-auto-step6-gate/DESIGN.md` - Deltas 1-3, residuals, the #505 executable-helpers note
15. `evals/level3/flow-auto-step6-gate/README.md` - the grader
16. `changelog.d/279-grader.md` - one bullet

Scope: large. Risks: a stamp on the hot service path (turns-only, additive, existing tests unmodified); the judge must reproduce the digest algorithm stdlib-only; pre-approval pushes unorderable (residual, nit store).

<!-- flow-run n=5 id=21cdf81893d247059a643ad1c80f62a5 -->
## Run 5

- Run-id:            21cdf81893d247059a643ad1c80f62a5
- Run-start:         ffa966844d267f651518b676d8f1fc17945cf96e
- Issue:             #279
- Base SHA:          ffa966844d267f651518b676d8f1fc17945cf96e
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-400 orchestrator (authority-model orchestrator-only), GATE GO-WITH-CONDITIONS #279 PR-3 (C1-C5), 2026-10-21
- Recorded at:       2026-10-21T10:00:00Z

### Section B evidence
- `REHEARSAL_BY_TASK[step6]` is `{}`; `TURN_ACTOR_SOURCE`'s resume turn only runs `codex --version`.
- S4 is identity-based (`FIX_BLOBS`), not prose-based. The orchestrator accepted this pushback.
- `run_live` already forwards `home_modes` (#505) and fixture attempts carry the guard (#500); neither is ENFORCED at dispatch.
- verify's probe runs in the grading container only when a backend is given; on the host otherwise (qualify).

### Section C - the approved plan (PR-3)
1. A turn-aware `STEP6_ACTOR_SOURCE`, separate from `fc.ACTOR_SOURCE` (pinned by digest, with a one-byte red).
   - `REHEARSAL_BY_TASK[step6]` gains `twin-gate`.
   - Rehearsal records are marked in the store and excluded from campaign tallies (C4 red).
   - A live rehearsal test under lock 1: the credited path, and ship-past-red.
2. The S4 behavioural oracle. The step6 capture extracts `widget/core.py` bytes (worktrees, plus remote main after a merge) without executing them.
   - C1: the controller runs held-out cases in a throwaway trial-image container (network none, no mounts, non-root, read-only rootfs plus tmpfs, memory/pid/time limits, cases over stdin).
   - The trusted capture carries outputs only; the judge (revision 2) compares them with its expected values.
   - C2: a merge result takes precedence.
   - C3: cases are held out from the agent's tree but public in skillc.
   - Qualify uses committed container-computed outcomes (regenerable under docker), so no host execution.
   - Reds: comment-only, a reworded correct fix, a broken other case, an infinite loop, merge-fail with worktree-pass, side effects, and the host backend refused.
3. Dispatch enforcement in `fixture_live` for a step6 (turns) declaration:
   - `containment.nested_codex` is required;
   - every executable helper, derived from the SOURCE git mode, must have its mode delivered (C5 reds).
4. A DRAFT declaration under `evals/level3/flow-auto-step6-live/`: digest computed, C1-C5 bindings from rev5's identities, model and effort UNKNOWN, no approval.
5. Tests append-only; docs; changelog.

Scope: large. Risks:
- `fixture_attempt`/`fixture_live` are hot paths; changes are additive;
- the oracle container is new controller infrastructure;
- the #434 pinned identities must not move (pinned).

<!-- flow-run n=6 id=10efc6fffda24f128c63d00a6fa1f749 -->
## Run 6

- Run-id:            10efc6fffda24f128c63d00a6fa1f749
- Run-start:         f4060c7e483020406d58e2baad662b48fdd2e9e2
- Issue:             #279
- Base SHA:          f4060c7e483020406d58e2baad662b48fdd2e9e2
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-400 orchestrator (authority-model orchestrator-only), small assignment (mailbox rev 10), 2026-10-21
- Recorded at:       2026-10-21T11:40:00Z

### Section B evidence
PR-3 (#511) delivered the unapproved Step-6 campaign draft. The orchestrator wants an exact sizing digest to show the owner. Its token figure (0.45-0.53M per attempt) was measured at Step 3 only.

### Section C - the approved plan (PR-4, declarations only, no spend)
1. `evals/level3/flow-auto-step6-live/sizing-declaration-draft.json` (NEW): the campaign draft's task, turns, containment and C1-C5, with these changes:
   - attempts_per_case 2;
   - per_attempt_seconds 1800, total_seconds 3600;
   - model gpt-6-astra, effort high (the orchestrator's pending recommendation);
   - run_store step6-live/sizing-1;
   - a derived case_order;
   - sizing purpose and caps comments;
   - no approval.
2. `declaration-draft.json`: _comment_caps corrected (Step-3-only figure; the caps are set from the sizing run).
3. README: both digests.
4. A test that each draft parses and that require_approved refuses it (sizing: no approval; campaign: placeholders), plus its pass control.
