# Flow run record - issue #758

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=b2371ebd7ca34f44b5adf5ec9139b0d7 -->
## Run 1

- Run-id:            b2371ebd7ca34f44b5adf5ec9139b0d7
- Run-start:         8e0e02e7bd387c1755cea4bc05c3a1b0ff370c2e
- Issue:             #758
- Base SHA:          8e0e02e (main, #755)
- Necessity verdict: Needs reframing (a member batch of the open umbrella #462)
- Approval:          granted (with conditions)
- Approver:          skillc-orch (wave skillc-work, policy rev 1, orchestrator-only), outbox rev 46, "GATE: GO-WITH-CONDITIONS #758"
- Recorded at:       2026-11-15T14:20:00Z (before the first implementation edit)

### Section B evidence
- commits since filing (2026-11-15T13:51:46Z): 8e0e02e (#755), touching none of the affected paths
- PRs: #755 since filing; the day's earlier merges (#735, #740, #742, #743, #744, #746, #748, #751, #753) touch none of these tests
- dup/super: #462 OPEN (the umbrella: canonical flake list, load harness, acceptance rules); closed members #174, #382, #410, #412
- this host: skillc-348-qualify-stdout-compat holds an unpushed 9caf33c (2026-10-12, #348) adding to tests/test_docker_backend.py; it is unrelated, a conflict risk only
- inventory (a scratch AST scanner): tests/ 1,113 bounds, with 104 functions < 1 s in 33 files and 340 functions 1-5 s in 67 files; 620 fixture hits; 19 skillc/ defaults <= 5 s. The negative control found 4 of today's 5 failures at their lines; the 5th is an exercised production default.

### Section C - the approved plan
1. `ci/timing_inventory.py` - the scanner over tests/ and skillc/ defaults, plus a `--check` ratchet: a new time-ish literal < 1 s in tests/ that is not in the baseline fails unless annotated `# timing: must-fire - <why>` (an empty reason fails)
2. `ci/timing-baseline.txt` - the baseline: one `path::function::kind::value` line per existing sub-second bound
3. `tests/test_timing_inventory.py` - negative controls: a planted file with all 9 shapes found, a clean twin empty, today's 4 literal failures found at their lines, and `--check` red on an added unannotated literal, green on an annotated one, red on an empty reason
4. `Makefile` - a `timing-check` target, wired into `verify`
5. `.woodpecker/ci.yml` - run `make timing-check` in CI
6. `tests/conftest.py` - one shared must-beat constant (TEST_SETUP_BOUND), with the measured reasoning
7. `tests/test_trial_bootstrap.py` - test_548 bounds split by role: F stays small with blocking fakes; B uses TEST_SETUP_BOUND; both modes keep their distinct reasons
8. `tests/test_docker_backend.py` - the stalled-events test runs prepare() under TEST_SETUP_BOUND and applies 0.2 s only to the events call under test
9. `tests/test_authority_interceptor.py` - a condition instead of interval-vs-sleep, AFTER an investigation; if it is a real interceptor race, STOP and route to the orchestrator
10. `tests/test_inventory_runtime.py` - the oracle budget becomes a must-beat bound; the timeout-fires tests stay small
11. `tests/test_inventory_calibration.py` - find the exercised default first (a no-load diagnosis), then fix it by role
12. `docs/measurements/timing-inventory/2026-11-15.md` - the inventory, roles and per-member results. The load-462 harness output is deferred by the gate (no host load runs)
13. `changelog.d/758.md` - release note
Fixture fakes under `tests/fixtures/` may change where a fake must block (role F); any such path is named in the PR.

Conditions (orchestrator): PR A only; no bulk timeout raises; NO load runs (on proxVMkyle19 ever, or on kyleci until kyle-cli-helper and the owner agree). The load proof is recorded NOT RUN, and the 50/50 item stays open on #758 and #462. A per-bound negative control (F: a prompt fake goes red; B: an over-bound fake goes red). Items 9 and 11 are investigated first. The ratchet's red and green cases are committed. Today's 5 members go on #462's flake list. Note the 9caf33c conflict. At most 3 counter-model passes, pass-3 findings deferred. Push after PUSH HOLD over, with fewer than 2 skillc pipelines running, counting main pushes.
Scope: ~13 files, ~500-800 lines. Risks: a role misread hiding a real bug (item 9); ratchet friction; the 9caf33c conflict.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable |
| Run placement | will test: woodpecker ci (the timing-check step and the suite) and host make verify (the targeted set); not real-docker runner vm; host load runs NOT RUN (deferred by the gate) |
| Execution backend | will test: DockerBackend via the fake docker CLI; real daemon and ManagedBackend not applicable |
| Agent client | not applicable |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | not applicable |
| Subject installation | not applicable |
| skillc distribution | will test: source checkout; built wheel not applicable (ci/ and tests/ do not ship) |
| Python version | will test: 3.12 tested |
