# Flow run record - issue #505

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=60120f9e47bb4b09a4b462c9667b96da -->
## Run 1

- Run-id:            60120f9e47bb4b09a4b462c9667b96da
- Run-start:         61aefe4e76207f53590534c7a52e3f30f40c1962
- Issue:             #505
- Base SHA:          61aefe4e76207f53590534c7a52e3f30f40c1962
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 orchestrator (wave skillc-400, authority-model orchestrator-only), GO-WITH-CONDITIONS 2026-10-21
- Recorded at:       2026-10-21T05:50:00Z

### Section B evidence
agent_trial.py:961 delivers extra_home_files with no mode; DockerBackend.deliver_home_file defaults to 0600. profile inventory records git mode (100644/100755) and profile.install honours it; installed_home_files drops it. Collection staging keeps the exec bit (git archive 0755/0644; tree_digest pins the x bit). Duplicates: none. Affected (Permission denied on an installed helper): #434 measurement 8097ad 2/2, rev-3 3585c9 5/10, rev-4 fab3ce 8/10, rev-5 25a382 9/10 (TWIN t4 FAIL); #287 pre-check 0/2 and pilot 0/18 (delivery affected, no observed behaviour).

### Section C - the approved plan
1. `skillc/profile.py` - installed_home_modes(inventory, tree): destination -> git mode, from the same verified records
2. `skillc/collection_conformance.py` - _collection_home_modes from the staging x bit; run_level1_agent_attempt and run_collection_agent_attempt forward extra_home_modes
3. `skillc/calibration_run.py` - Treatment.home_modes beside home_files; closure/collection mode disagreement refuses; both calibration kinds pass it
4. `skillc/fixture_live.py` - passes treatment.home_modes; actor home_extra stays 0600
5. `skillc/agent_trial.py` - extra_home_modes: 100755 -> 0700, 100644 -> 0600, absent -> 0600, other values refused; in-container verification of each verified file's x bit
6. `tests/test_agent_trial_modes.py` - NEW: delivery modes, refusal, in-container mismatch
7. `tests/test_agent_trial_modes_live.py` - NEW: real container under lock 1, no model, no-daemon skipif
8. `tests/test_calibration_run.py` - append-only: treatment modes end to end, disagreement refuses
9. `tests/test_profile.py` - append-only: installed_home_modes matches the inventory
10. `evals/level3/campaign-434-live/README.md` - harness note with the per-run counts; rev-5 TWIN t4 attributed to #505
11. `evals/calibration-287/README.md` - harness note: delivery affected, no observed behaviour
12. `changelog.d/505.md` - one bullet

Scope: medium. Risks: changes the install (future runs measure a different environment); mode only, ownership unchanged; staging x bit trusted only as far as the source digest pins it.
