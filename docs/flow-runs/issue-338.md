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

<!-- flow-run n=2 id=d2e4e609a88b4068a9899740f0751d96 -->
## Run 2

- Run-id:            d2e4e609a88b4068a9899740f0751d96
- Run-start:         7b800c6adb1790201425bbd11f1844c15e4bb0aa
- Issue:             #338
- Base SHA:          7b800c6
- Necessity verdict: Partially addressed
- Approval:          granted
- Approver:          repository owner (interactive /flow:auto session; merge deferred to orchestrator - stop at open PR)
- Recorded at:       2026-10-13T21:00:00Z

### Section B evidence
Fix, live test and fake-CLI red cases merged in #361 (76a68a6). Remaining per issue comments 2026-10-12 and #315 operator record 2026-10-13: eighth real-Docker floor entry, matching verdict fixtures, cwd break registration. Post-#361 commits on runner/floor paths: 9bda3c5 (#363), f22d6c8 (#369), 02f1565 (#370) - none adds a cwd entry. #315 PRs: #377 merged (docs only), #357 merged (XFAIL verdict handling, preserved). No open #315 PR. Duplicates/superseding: none (#332, #315, #20 checked).

### Section C - the approved plan
1. `ci/check_real_docker_ran.py` - add tests.test_cwd_confinement_live as the eighth floor entry.
2. `tests/test_real_docker_verdict.py` - eight-file floor fixture/size pins; cwd-file-all-skipped is FAILURE test.
3. `ci/real-docker/break-lib.sh` - cwd family (cwd:confine-root-omitted, no bare form); resolve_break_spec emits eight lines.
4. `ci/real-docker/run-real-docker` - read line 8, always export SKILLC_CWD_CONFINEMENT_LIVE_BREAK, usage line.
5. `ci/real-docker/README.md` - step 8 adds the cwd run, count 22 -> 23, drop the pending-#338 caveat.
6. `tests/test_run_real_docker_break.py` - eight-value tuples, cwd family resolve/refuse/context/runner-variable tests.
7. `tests/test_property_held_xfail_pattern.py` - no-daemon marker control for the cwd live file (target XFAIL; refusal/infra/wrong-landing hard FAIL; widened-marker mutation).
8. `CHANGELOG.md` - one entry.

Scope: ~8 files, ~150-250 lines. Risks: positional-line shift across all families in resolve_break_spec; control couples to the live file's helpers. Refs #338 only; campaign/VM certification out of scope.
