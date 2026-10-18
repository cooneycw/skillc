# Flow run record - issue #446

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=22e0d31e6d704a3eb78bf36e4e7f90ce -->
## Run 1

- Run-id:            22e0d31e6d704a3eb78bf36e4e7f90ce
- Run-start:         296313cd80e4cfcab5f41aceffb53ac228df332f
- Issue:             #446
- Base SHA:          296313cd80e4cfcab5f41aceffb53ac228df332f
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T22:35:31Z

### Section B evidence
#446 filed 2026-10-17 from main push pipeline 869 (merge 296313c) red: both qualify params TimeoutExpired at 180 s. Fulfils #412 D8's conditions (D1 CI data from #421; declared budgets read: grader.json probe 90 s / judge 60 s per call, no whole-run budget, so 180 s is the test's cap). No merged PR or open issue addresses it.

### Section C - the approved plan
1. `evals/level3/gate-stops-early/qualify.py` and `evals/level3/verify-stops-early/qualify.py` - add `--list-parts` and `--part <name>`; parts are `certify`, `control:<k>` for each CONTROLS key, and `validity` (restore-probe, flow-check discrimination, flow-check controls); each part prints `QUALIFY: ok part=<name>` under the same fail conditions; the no-arg run is unchanged.
2. `tests/test_qualify_scripts_run.py` - parametrize (script, part) for scripts answering `--list-parts`; others run whole under the unchanged caps; a membership guard asserts each parts list equals {certify} + {control:<k> for k in CONTROLS} + {validity}, derived from the script's own CONTROLS; an independence test runs every part in a fresh subprocess in a shuffled order, each passing alone.
3. RED (in the PR, not committed): a sitecustomize shim delays verify.grade_directory by a fixed amount; the whole-script run exceeds 180 s before, and every part passes after.

Scope: small (~60 eval-script, ~50 test lines). Risks: a part silently dropping a check (membership guard); hidden cross-part state (independence test). No skillc/ change, so no changelog entry.
Approver conditions: (1) parts INDEPENDENT - no part relies on in-process state from another; a test runs each part in a fresh subprocess, shuffled order, each passing alone.
