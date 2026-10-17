# Flow run record - issue #418

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=51401220caf24bc1af8ca5a97985ba32 -->
## Run 1

- Run-id:            51401220caf24bc1af8ca5a97985ba32
- Run-start:         a2ef507780af36f94afd1fbc9d1b42625732cc7c
- Issue:             #418
- Base SHA:          a2ef507780af36f94afd1fbc9d1b42625732cc7c
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T14:45:00Z

### Section B evidence
- commits since filing (2026-10-17T14:09Z) touching skillc/verify.py, skillc/trial.py, skillc/agent_trial.py: none
- merged PRs since filing: #417 (decide-reply channel only); open: #411, #403 (unrelated)
- dup/super: none; promotes Nit Store comment 6225263167

### Section C - the approved plan
1. `skillc/trial.py` - public put_object/read_object wrappers over the existing write-once and hash-checked object helpers
2. `skillc/verify.py` - store the trusted-observation bytes under the recorded digest after the post-grade integrity checks and before add_result; read_trusted_observation reader (None without a digest; Refused on absent/tampered/inconsistent); docstring corrected
3. `tests/test_trusted_observation_retention.py` - red case (recorded digest resolves on a witnessed grade), tampered and absent refused, unwitnessed unchanged, regrade behaviour pinned
4. `tests/test_agent_trial_gate_witness.py` - production path: the stored envelope re-derives each gate run's tree_digest_at_start, stages and graded_tree_digest, equal to what grading received
5. `docs/specs/evaluation-facility/verification.md` - retention and read check documented
6. `CHANGELOG.md` - entry

Conditions from the approver: regrades covered by a test (a regrade of a witnessed result records its own digest that resolves, or a test shows regrades carry no witness and the PR says so); the PR names the red run on main.
Scope: 6 files, ~150 lines; records.py untouched. Risks: few KB per witnessed attempt; orphan object on a crash between object and result, never a dangling digest; existing results not back-filled.
