# Flow run record - issue #500

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=40ab0e2ecdf5414d85869f62df948b8b -->
## Run 1

- Run-id:            40ab0e2ecdf5414d85869f62df948b8b
- Run-start:         f1681212b80b4a4bc591d9cee1b218377ea2d2fb
- Issue:             #500
- Base SHA:          f1681212b80b4a4bc591d9cee1b218377ea2d2fb
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 orchestrator (wave skillc-400, authority-model orchestrator-only), GO-WITH-CONDITIONS 2026-10-20
- Recorded at:       2026-10-21T01:40:00Z

### Section B evidence
Merged since #500 was filed: f168121 (#501, grader rev 5; touches none of these files). Duplicates/superseding: none. Code: the guard exists only inside FixtureSession (fixture_attempt.py:117,149); run_one_attempt builds one only when `fixture` is passed (agent_trial.py:2132), which calibration-run never does; the witness trigger socket exists on calibration attempts (agent_trial.py:2157-2168); the >1-transcript branch keeps no bytes (agent_trial.py:1447); the containment Stop exists only on the fixture path (fixture_live.py:417,485).

### Section C - the approved plan
1. `skillc/attempt_guard.py` - NEW: AttemptGuard, the guard half of FixtureSession without the fixture service (routes, watch, bind, finish)
2. `skillc/agent_trial.py` - codex_guard=True composes the guard on the witness socket; >1 transcript retains every file and flags; census every session (models, tokens); belt-and-braces transcript command scan for bare/absolute-path codex and non-declared --model (condition 2)
3. `skillc/trial.py` - several client-transcript observations per attempt (schema bump goes back to the orchestrator first)
4. `skillc/calibration_run.py` - codex_guard=True on EVERY live codex calibration attempt, discrimination AND improvement kinds (condition 1); refusal-expected policy; credit block and a schedule Stop on passed/suspected/unknown/bypass; report nested_codex and containment_stop
5. `tests/test_attempt_guard.py` - NEW: guard session units and reds
6. `tests/test_calibration_run.py` - append-only: guard applied to both kinds, Stop, bypass scan reds (absolute path stops; refused launch not double-counted)
7. `tests/test_agent_trial.py` - append-only: two-transcript retention, eligibility and tokens across sessions
8. `tests/test_attempt_guard_live.py` - NEW: docker no-spend proof (scripted nested codex exec --ephemeral --model other refused), under lock 1
9. `evals/calibration-287/README.md` - the pilot predates the guard; pre-registered change: the step6 review fails as reviewer-unavailable (condition 3)
10. `changelog.d/500.md` - one bullet

Scope: medium. Risks: absolute-path bypass (mitigated by the transcript scan, condition 2); egress allowlist passes nested traffic (moot when refused); measured behaviour changes versus the pilot (pre-registered in the README).
