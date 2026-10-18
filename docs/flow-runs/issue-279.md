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
