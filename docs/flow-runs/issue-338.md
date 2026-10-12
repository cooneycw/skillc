# Flow run record - issue #338

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=423c29eb9c874daf967414e9e8d72475 -->
## Run 1

- Run-id:            423c29eb9c874daf967414e9e8d72475
- Run-start:         8e83e02625cc94335d3c752fefb84baf6ed90893

- Issue: #338
- Base SHA: 450445d
- Necessity verdict: Still needed
- Approval: granted
- Approver: wave orchestrator, conditional gate ruling
- Recorded at: 2026-10-12T14:26:27.228052+00:00

### Section B evidence
Verdict: Still needed, with corrections to the parked implementation.
Issue created 2026-10-07T00:18:57Z. Current main 450445d still resolves in GateWitness and later passes the path to Docker exec -w. Parked 8e83e02 is not merged. Relevant history inspected: 9c79510 (#339), 10ff168 (#342), 0518cc0 (#349); subsequent main commits 23bb1ba (#353), 450445d (#335) do not close the race. Other inspected post-filing PRs: #340, #344, #345, #347, #350, #351, #352. Related issues #332 and #317 do not supersede #338; #317 documents the same stderr-provenance trap on execute(), not this new exec_in_attempt() path. Sibling worktrees have no unpushed commits touching the core #338 paths.
Verified findings: (1) parked live test defines outside=/work/.outside-root with confine_root=/work, so it is inside the allowed root. (2) actual parked fake-backend execution of a gate that prints the sentinel and exits 7 returns launch-failed/None. (3) scratch shell opening/checking fd9 then moving the opened directory outside root and cd-ing through fd9 preserves its identity but follows its new location. Actual backend compose_run_argv has no /work mount; candidate-owned installed child directories can be renamed. Real-daemon topology probe remains to run.


### Section C - the approved plan
1. `skillc/docker_backend.py` - fd confinement corrections, ordered pre-exec status handling, accurate limits.
2. `skillc/gate_witness.py` - pass confine_root and document identity-binding guarantee.
3. `skillc/backend.py` - optional confine_root contract, preserving unsupported behavior and explicit limits.
4. `skillc/managed_backend.py` - accept optional argument, remain unsupported.
5. `tests/test_docker_backend.py` - before-open swap and ancestor swap, after-open original-path substitution, missing dir/non-dir, non-racing env/stdin/exit/output, sentinel spoof and output-cap controls; mutation check.
6. `tests/test_gate_witness.py` - update fake signature and ASSERT actual confine_root forwarding (parked records but never asserts it).
7. `tests/test_cwd_confinement_live.py` - genuinely outside target, candidate-writable setup installed through backend, real healthy/break checks; setup errors stay hard failures.
8. `tests/test_backend.py` - compatible backend double.
9. `tests/test_lifecycle.py` - compatible backend doubles.
10. `tests/test_verify_backend.py` - compatible backend doubles.
11. `evals/level3/claims-outran-evidence/qualify.py` - compatible backend double.
12. `evals/level3/gate-stops-early/qualify.py` - compatible backend double.
13. `evals/level3/report-outran-evidence/qualify.py` - compatible backend double.
14. `ci/check_real_docker_ran.py` - retain parked eighth floor entry unless transferred to DD as below.
15. `tests/test_real_docker_verdict.py` - retain matching floor fixtures unless transferred to DD.
16. `CHANGELOG.md` - bounded behavior and verified evidence, remove atomicity overclaims.

Scope: parked 16-file implementation with bounded corrections, rebase, focused/mutation/live verification. The CI floor pair is temporarily released and removed from this diff, then reintroduced only after its current owner merges/releases it.

Conditions: direct proc-fd inspection and physical fd chdir; no atomicity or perpetual ancestry claim. Wrapper-owned bounded READY/REFUSED leading record, independently captured from user retention cap. Ordinary output and exit 125 preserved; missing/invalid status cannot fabricate refusal/success. Live target genuinely outside; setup failures remain hard failures. Mutation-check enforcement, assert GateWitness forwarding, preserve timeout/cleanup. Real-Docker runner must include new break before merge. Merge requires explicit orchestrator clearance.

Risks: shell/proc-fd semantics need real-daemon evidence; moving an open directory can change ancestry, to be documented and recorded in Nit Store after deduplication.
