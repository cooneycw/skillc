<!-- flow-run n=1 id=22e0d31e6d704a3eb78bf36e4e7f90ce -->
## Run 1 - issue #446 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #446
- Read at:      2026-10-17T22:35:00Z
- updatedAt:    2026-10-17T22:34:36Z   (context only - moves on comments and labels)
- Body digest:  63cbc47ad0a09bf14de36493cadd84f950a829fad688bf7aacedd143b7178705   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1607 of 1607 (cap 16384)

### Body as read
## Defect

Main's push pipeline 869 (merge 296313c, #287 P1) went red in `gate`. `tests/test_qualify_scripts_run.py::test_qualify_script_certifies[gate-stops-early]` and `[verify-stops-early]` each raised `subprocess.TimeoutExpired` at exactly 180 s. P1's diff doesn't touch either script.

This is #412's **D8**. It was ruled "LEAVE until D1's CI data AND reading the scripts' declared budgets". Both conditions are now met.

## Data

Durations of `qualify.py` (gate-stops-early / verify-stops-early):

| run | gate-stops-early | verify-stops-early |
|---|---|---|
| CI 866 | 161.4 s | 71.6 s |
| CI 867 | 76 s | 75 s |
| local, load ~16 | 124 s | 99 s |
| CI 869 (main) | **180 s (cap)** | **180 s (cap)** |
| #412 D8 baseline | 72.0 s | 71.0 s |

#419 added a few judge calls to both scripts, per skillc-avail. The CI VM runs 8 xdist workers on 8 CPUs (#421).

## Declared budgets (the D8 condition)

- `grader.json`: `probe.timeout` 90 s and `judge.timeout` 60 s. These are PER CALL.
- Neither script declares a whole-run budget, so the 180 s cap is the TEST's (`_SLOW_REASON` default) and not a property of the task.
- Cost shape: `main()` runs `certify()` over about 30 committed candidates with the real judge, and then again for each of the 5 broken-grader `CONTROLS`. That's about 180 full `grade_directory` probe+judge runs in ONE subprocess, followed by the restore-probe and flow-check-honest validity checks. CI contention scales all of it.

Since 869 hit the cap, the true CI maximum is at least 180 s. A cap of 3x the observed max therefore has no upper anchor.

Refs #412 (D8), #419, #421.

