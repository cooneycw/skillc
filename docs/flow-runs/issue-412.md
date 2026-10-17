# Flow run record - issue #412

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=2a2ccd0ca018475ea4ebecd125df73e4 -->
## Run 1

- Run-id:            2a2ccd0ca018475ea4ebecd125df73e4
- Run-start:         a2ef507780af36f94afd1fbc9d1b42625732cc7c
- Issue:             #412 (PR 1 of 2: disposition D1 only)
- Base SHA:          a2ef507
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated) - #412 rulings 2026-10-17, "D1 APPROVED, FIRST AND SEPARATE"
- Recorded at:       2026-10-17T15:10:00Z

### Section B evidence
- Measurement posted on #412 (comment 6235175437, correction 6235188379): per-test CI durations are not recorded by the gate step, so the 806 reds could not be placed in time; CI VM (labels host=kyleci) state was never measured.
- Commits on main since #412 was filed: #413 (c1d6212), #415 (371d19c), #417 (a2ef507) - none touch .woodpecker/ci.yml or the Makefile test target.
- No duplicate issue; #416 is separate (prepare cleanup).

### Section C - the approved plan
1. `.woodpecker/ci.yml` - gate step: first command prints `nproc` and `uptime` and sets an EXIT trap printing them again at step end (exit status preserved); pytest gains `--durations=0`.
2. `Makefile` - `test` target pytest gains `--durations=0`, keeping the CI/local argument parity the contract test enforces.
3. `tests/test_ci_local_gate_coverage.py` - expected parallel-contract args include `--durations=0`; a new test pins the gate's host-state start line and EXIT trap, with a red case (trap removed -> rejected).

Scope: small; CI config plus its contract test.
Risks: Woodpecker must run a step's commands in one shell for the trap to fire - proven or disproven by the PR pipeline's log; verdict/exit code must not change, shown by a local red/green trap check and by comparing the PR pipeline's counts with 814.

<!-- flow-run n=2 id=2cd7cc5ab3a545188760a5565058c3f3 -->
## Run 2

- Run-id:            2cd7cc5ab3a545188760a5565058c3f3
- Run-start:         e9afd864aa8a103b3152a8d153ea355d96103ecd
- Issue:             #412 (PR 2 of 2: dispositions D3, D4, D5, D6 plus the approved interrupt-timing assertion)
- Base SHA:          e9afd86
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated) - #412 rulings 2026-10-17 ("PR 2 = D3+D4+D5+D6, one test-only PR") and the follow-up approving option (ii)
- Recorded at:       2026-10-17T15:30:00Z

### Section B evidence
- Measurement and correction on #412 (comments 6235175437, 6235188379); PR 1 (#421, e9afd86) merged, CI VM shown to have nproc=8.
- D3 gating red run on the scratch branch: timeout=30 healthy passes (1.05 s); SIGINT handler broken -> FAILS (interrupt_line=ABSENT exit=0).
- SIGINT-ignoring child probe: exits 4.2 s after SIGINT (normal child 0.2 s), so "exited after SIGINT < sleep" separates them.
- #416 merged (8466aa5): the live_docker_budget reds are owned there (D2, no change here).

### Section C - the approved plan
1. `tests/test_demo.py` - cancellation seed at timeout=30 (D3; sleep=4 kept); new assertion that the child exited after SIGINT in less than `sleep`, parsed from the evidence and failing loudly when the wording is absent; committed red: a SIGINT-ignoring child (child_command) fails it; run-control (D4) unchanged, inherits D3.
2. `tests/test_docker_backend.py` - symlink-at-observations runs its subject under Limits(timeout=FAKE_DOCKER_DAEMON_TIMEOUT) (D5); read_home_tree slow-cp/nominal run setup (prepare, deliver_home_file) on FAKE_DOCKER_DAEMON_TIMEOUT and the read under test on daemon_timeout=5.0 via dataclasses.replace (D6).

Scope: small, test-only.
Risks: the interrupt-timing red costs about 4.5 s of suite time; D6's second backend instance must use the same state dir and handle - if read_home_tree depends on per-instance state the test reds loudly, not silently.
