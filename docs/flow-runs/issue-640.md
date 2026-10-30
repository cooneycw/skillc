# Flow run record - issue #640

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=a909e2be424f436487b041a27a0419b3 -->
## Run 1

- Run-id:            a909e2be424f436487b041a27a0419b3
- Run-start:         da1d121399c171dd1efa599def44032ed6758c0f
- Issue:             #640
- Base SHA:          da1d121
- Necessity verdict: Needs reframing
- Approval:          granted
- Approver:          skillc-nhl orchestrator, GATE: GO-WITH-CONDITIONS #640 (wave mailbox outbox-worker-A rev 2, 2026-10-30T06:07:42-04:00)
- Recorded at:       2026-10-30T10:10:00Z

### Section B evidence
Since 2026-10-30T10:02:31Z: no commits on origin/main (tip da1d121, 2026-10-29); none touching
skillc/{calibration_run,collection_conformance,fixture_campaign,fixture_attempt,git_snapshot,agent_trial,verify}.py
or evals/level3/change-with-regression-568. No PRs merged since 2026-10-30. No duplicate or
superseding issue; considered #568 (parent), #621, #279, #546 (closed, satisfied by #583), #348
(closed). Host: only skillc-348-qualify-stdout-compat holds unpushed commits on these paths
(9caf33c, 536d02c; #348 closed, not covering).

### Section C - the approved plan
PR-1 of an approved split (PR-2 = 568 builder, grader, container oracle).
1. `skillc/agent_trial.py` - an EXPLICIT baseline fixture route: a fixture attempt with no gate_entrypoint is accepted only when the caller declares the baseline route; it gets an empty-gate witness session so the fixture service, shim, guard, remote and snapshot are identical. A treated or gate-declaring attempt without gate_entrypoint stays refused.
2. `skillc/collection_conformance.py` - `fixture` and baseline-route passthrough on run_level1_agent_attempt; None keeps every existing caller unchanged.
3. `skillc/git_snapshot.py` - `commit_files`: a commit's exact blob bytes and modes from loose objects under the existing budgets.
4. `skillc/fixture_attempt.py` - `fixture_digest`: canonical digest of a delivered fixture surface (paths, modes, bytes, including the bare remote).
5. `skillc/calibration_run.py` - for a task with builder/build.py: build each case once, give each attempt its own fresh copy, refuse on per-attempt digest mismatch, pass the fixture to every arm, record fixture_digest per attempt and arm, finalize a build failure as a non-start, lazily import fixture_campaign, and extend task_content_identity only for tasks with a builder.
6. `skillc/fixture_campaign.py` - only if build_case needs a hook; no behaviour change intended.
7. `tests/test_calibration_run.py` - controls through the real dispatch path: byte-identical fixtures for both arms (red on the pre-change path), a fresh copy per attempt, digest-mismatch refusal, non-start on build failure, a control per disposition, and builder-less task_content_identity byte-identical.
8. `tests/test_agent_trial_fixture.py` - replace the line-268 control: an explicit baseline-route fixture attempt is accepted with zero gates; treated or gated without gate_entrypoint is still refused; fixture plus project_gate is still refused.
9. `changelog.d/640.md` - new fragment.
Scope: about 9 files, ~600-900 lines. Risks: the changed refusal control is an instrument change (old red and both new outcomes shown); builder determinism (avoided by copying one build, with a digest check); PR-1 proves dispatch symmetry and remote capture only, not delivered-code correctness.
