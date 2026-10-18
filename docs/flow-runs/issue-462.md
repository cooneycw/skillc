# Flow run record - issue #462

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=a59f084a56ef45eda338a39de9f19185 -->
## Run 1

- Run-id:            a59f084a56ef45eda338a39de9f19185
- Run-start:         0aeb9c72da6253a6bb3aa00b4c6ffba9a726a2ad
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-18T07:10:00Z

### Section B evidence
- #462 open; members observed red under load: gate_witness stop_confirmed=False (PR CI 891), evidence_export timeout=5 attempts (the #460 hold), lifecycle 0.15 s head start, docker_backend elapsed<6.0, trial_image_tools_live docker run --rm 30 s, demo independent=reaped (#412)
- gate_witness's real dependence is PRODUCTION: docker_backend._read_in_container_pid(timeout=2.0) and the TERM grace poll
- design posted: https://github.com/cooneycw/skillc/issues/462#issuecomment-6247149240

### Section C - the approved plan (PR 1 of 3: harness + gate_witness + evidence_export)
1. `ci/load-harness.py` - stdlib CPU spinners + python-start churn in its own process group; phases <= 15 min with >= 2 min pauses; EXIT/signal kill of the group; uptime before/after each phase; loadavg samples; INVALID unless the sampled load reaches the target
2. `ci/load-repro.sh` - runs a test id REPS times under the harness and writes docs/measurements/load-462/<member>-<sha12>-<pre|post>.json
3. `tests/test_load_harness.py` - committed red: a spinners-disabled run reports INVALID; a reached-load run reports VALID; spinners gone after exit
4. `skillc/docker_backend.py` - only if the Hold-A diagnostic shows pid-None: the pid poll bounded by daemon_timeout and the exec's liveness instead of a fixed 2.0 s; old vs new stop-confirmation semantics stated in the PR
5. `tests/test_gate_witness.py` - event-based stop confirmation; existing tests unmodified or each change justified
6. `tests/test_collection_evidence_export.py` - measured attempt bound cited beside the constant; the timed-out path kept honest by a hanging fake client
7. `docs/measurements/load-462/` - pre and post measurement files
8. `changelog.d/462.md`

Conditions from the approver: host impact (phases <= 15 min, >= 2 min pause, kill on EXIT, uptime per phase, Hold A in bounded phases); the INVALID control plus its committed red; gate_witness semantics stated and existing tests kept or justified; the #412 release marker as its own production change in PR 3; order after #460 merges and #434's evals26 run completes; Hold A by direct GO; codex cap 2 per PR; every red reproduced pre-fix on main at >= 2x nproc with REPS = ceil(ln 0.01 / ln(1-p)) >= 20; no timeout raised without a measurement file.
Scope: medium (PR 1 ~8 entries). Risks: a member may not reproduce at 4x (reported, not fixed blind); harness load perturbs other sessions (bounded by lock 1 and phase caps).

<!-- flow-run n=2 id=3f55fd9668f24f4bb11798f34726d87c -->
## Run 2

- Run-id:            3f55fd9668f24f4bb11798f34726d87c
- Run-start:         a0edf35af648f33cb448af5b8c9871d81e350185
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-18T16:10:00Z

### Section B evidence
- PR 1 merged as #466 (53b93e6): the harness, and the lifecycle fix with 0 of 180 at x2 post-fix
- Hold B (main a0edf35): 0 of 20 for each of the 6 unreproduced members under a pinned kyleci profile; all phases VALID
- Hypothesis-closing comment: https://github.com/cooneycw/skillc/issues/462#issuecomment-6251986114
- Two harness false negatives were seen in Hold B: `meets_2x_nproc` ignores `--cpus`; a `docker rm` reply of "removal ... already in progress" counted as a cleanup failure

### Section C - the approved plan (PR 2, "Refs #462"; #462 stays open)
1. `ci/load_harness.py` - `meets_2x_nproc` uses the pinned core count when `--cpus` is set; an in-flight daemon removal is not a cleanup failure (the sweep must still settle empty)
2. `tests/test_load_harness.py` - a red for each fix, failing on the parent; no spinners (synthetic records and the fake docker)
3. `docs/measurements/load-462/` - Hold B phase records committed raw, summaries recomputed by the fixed `summarize`, and a Hold B README table
4. `changelog.d/462.md` - a one-bullet fragment for PR 2

Conditions from the approver: "Refs #462", not Closes; raw phase records unchanged; no load runs; the lock-1 gate hold after the #434 measurement and #279/auto6, by direct GO.
Scope: small. Risks: none beyond the harness's own tests.
