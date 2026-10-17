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
