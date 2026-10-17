# Flow run record - issue #400

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=4b10f8338bf243b49d57d4cac720abcd -->
## Run 1

- Run-id:            4b10f8338bf243b49d57d4cac720abcd
- Run-start:         410801b83c434dac00ba44d97f7cef10cc36fe5d
- Issue:             #400
- Base SHA:          410801b83c434dac00ba44d97f7cef10cc36fe5d
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive "approved" in the /flow:auto session
- Recorded at:       2026-10-16T00:00:00Z

### Section B evidence
- commits: none touching skillc/agent_trial.py, skillc/gate_witness.py or the level-3 graders since 2026-10-15T19:28:29Z
- PRs: #397, #398, #401 merged since filing; none touch freshness
- dup/super: none (#400 the only hit)
- Diagnosis correction: by code reading, gate-written bytecode is the only post-plan-start write in `fresh` mode; `.skillc-canary-result` and `agent-touched.txt` are written by the fake client before the plan gate.

### Section C - the approved plan
Option 3 (PYTHONDONTWRITEBYTECODE=1 in the declared gate env), mirroring verify.py:415.
1. `skillc/agent_trial.py` - `_WitnessSession.bind_and_check` declares the measured env plus `PYTHONDONTWRITEBYTECODE=1` for both gates, comment citing #400 and verify.py:415.
2. `tests/test_agent_trial_gate_witness.py` - test that the declared gate env carries the variable and preserves every measured key; shown red on pre-fix code.

Scope: 2 files, ~40 lines, plus a partial live campaign on evals26 (reference rows PASS, wrong.stale-evidence rows still stale).
Risks: gate env no longer byte-identical to the measured supply; post-gate writes by a real model (own pytest run, late canary) remain uncovered (nit store); witness record not persisted in the store (nit store).
