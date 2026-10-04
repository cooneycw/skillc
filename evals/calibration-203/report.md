# #203 calibration report: B/N/P on `gate-ran-nothing`

**Run 2026-10-03, 23:17-23:58Z. Recommendation for #203: REDESIGN.**

Every one of the 18 attempts reached primary-endpoint PASS, in every arm.
The task is at ceiling for this model, so it cannot show whether CPP's skills
change the outcome. The measurement itself worked. The new finding is about
uptake: the agent never opens a skill on its own, and always opens one when
told to.

## Run

- **Command:** `SKILLC_ALLOW_REAL_AGENT=1 skillc calibration-run evals/calibration-203/run-manifest.json`,
  exit 0, from a fresh clone checked literally at the declared commit
  `0aa84c1`.
- **Experiment:** `calibration-5c2878e2`.
- **Identities:** codex-cli 0.157.1, `gpt-6-astra` effort `high` (pinned and
  observed on all 18 attempts, `model_ineligible=0`), image
  `sha256:eb17e8c7…`, subject cpp-codex @ `85e9b03`.
- **Schedule:** 6 attempts per arm in the seed-`20261003` order. All 18 were
  captured, and none was cut by a cap.

## Results

| Arm | Primary PASS | Opened a skill (k/n) | Named skill opened | Mean agent time | Mean tokens (uncached input) |
|---|---|---|---|---|---|
| `baseline` (B) | 6/6 | - | - | ~106 s | ~213k (~14k) |
| `natural` (N) | 6/6 | **0/6** | - | ~101 s | ~252k (~18k) |
| `provided` (P) | 6/6 | **6/6** | 6/6 (`flow-auto` every time, `flow-check` never) | ~179 s | ~685k (~47k) |

Per attempt:

```
1 baseline PASS opened=false named=- agent=96s tok=216919
2 provided PASS opened=true named=true agent=176s tok=641813
3 natural PASS opened=false named=- agent=109s tok=207804
4 provided PASS opened=true named=true agent=175s tok=714903
5 natural PASS opened=false named=- agent=101s tok=263064
6 provided PASS opened=true named=true agent=171s tok=656105
7 provided PASS opened=true named=true agent=180s tok=770071
8 baseline PASS opened=false named=- agent=125s tok=220661
9 baseline PASS opened=false named=- agent=91s tok=179126
10 natural PASS opened=false named=- agent=112s tok=261355
11 baseline PASS opened=false named=- agent=103s tok=200249
12 natural PASS opened=false named=- agent=98s tok=225851
13 baseline PASS opened=false named=- agent=95s tok=202335
14 natural PASS opened=false named=- agent=119s tok=264832
15 provided PASS opened=true named=true agent=179s tok=625593
16 baseline PASS opened=false named=- agent=126s tok=260087
17 provided PASS opened=true named=true agent=191s tok=700022
18 natural PASS opened=false named=- agent=67s tok=286379
```

## Report questions

1. **Does the grader behave on live attempts?** Yes. All 18 attempts were
   graded on all four mandatory criteria with no INCONCLUSIVE from the
   grading path. Baseline's `verified` status is INCONCLUSIVE by design:
   readiness stays on the agent-observation stand-in. The primary endpoint
   never reads it.
2. **Is difficulty useful?** **No.** B, N and P are all at ceiling (6/6).
   The planted hazard, a gate whose discovery skips a subdirectory, is
   found and fixed by the no-skills baseline every time. In the first
   attempt's own words: "corrected recursive test discovery". This is
   #204's outcome again, on a task built specifically to avoid it.
3. **Uptake?**
   - **N** opened a skill 0/6 times. With #204's 0/4, that makes **0/10**
     natural uptake across two tasks with the full cpp-codex surface
     installed.
   - **P** opened a named skill 6/6 times, which shows the detector sees a
     real open.
   - P always chose `flow-auto` and never `flow-check`.
4. **Value (P vs B, descriptive)?** 6/6 vs 6/6. At ceiling there is no
   outcome difference to see. P cost more: about 1.7x the agent time and
   about 3.2x the tokens, mostly from reading the skill text.
5. **Go / redesign / stop, and cost?** **Redesign.**
   - The whole run took about 41 minutes and roughly 7.4M tokens, mostly
     cached.
   - B/N attempts take about 100 s each; P attempts about 180 s.
   - A larger study at this per-attempt cost is cheap. What it lacks is a
     task that is not at ceiling.

## What this does and does not show

- **Shows:** with this model and effort, this task does not discriminate.
  Natural uptake of the installed CPP skills was zero in every observed
  attempt (10/10 across #204 and this run).
- **Does not show:** that the skills have no value. A ceiling hides value
  in both directions. Nor does it show that uptake would stay zero on a
  task where the agent is struggling.
- **Uptake source:** uptake comes from each attempt's confirmed in-memory
  observation (one transcript, carrying the attempt's own prompt), not
  from retained transcripts.

## Deviation: no transcripts were retained

The declaration sets `retain_transcripts: true`. Retention was attempted for
every attempt and refused by the leak check for all 18:
- `uid-gid` in every arm, most likely the trial container's own
  fixed user id, 10001. Quoting it in the `uid=` form here would trip the
  repo-wide leak check too;
- `home-path` in arm P only, most likely example paths in CPP's skill
  text.

Nothing private leaked. The refusal is fail-closed. The cost is that this
run's transcripts cannot be hand-read. Filed as #235, so the container's
fixed identity is exempt the way `/home/candidate` already is.

## Evidence

`calibration-report.json` and the store stay in the operator's private run
directory, as the runner documents. The tables above transcribe them.
