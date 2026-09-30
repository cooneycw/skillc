# #204 calibration report

**Recommendation for #203: REDESIGN.** The measurement works: the grader
behaves, and the baseline can reach the endpoint on equal terms. But this task
cannot inform a comparison. Both arms were at ceiling (4/4 PASS each), and the
CPP arm never opened a CPP skill in any of its four attempts. #203 needs a task
that is harder AND gives the skill collection something to do. See "What #203
needs" below.

## The run

| Field | Value |
|---|---|
| Declaration | `run-manifest.json`, approved by the owner 2026-09-30 (#208) |
| Runner | `skillc calibration-run` at `4a2528e` (#207 / PR #209), `SKILLC_ALLOW_REAL_AGENT=1` |
| Experiment | `calibration-3f950fbd`, private run `20260930T204233Z-36b4ff` under `~/.local/share/skillc/calibration-runs/` |
| When | 2026-09-30 16:42:33 to 17:03:25 EDT (about 21 minutes for all 8 attempts) |
| Client, model | codex-cli 0.157.1, `gpt-6-astra`, effort `high`: declared, pinned at launch, and observed on all 8 (0 ineligible) |
| Image | `skillc-trial:latest` `sha256:d1b2ced9...`, as declared |
| Login | codex `auth_mode: chatgpt` (subscription; no API key); no judge calls |
| Task | `evals/level3/slugkit-pipeline`, grader `slugkit-pipeline` revision 1 |
| Arms | `full-cpp`: `cpp-codex` at `85e9b03`, real installation receipt. `baseline`: nothing installed, readiness stand-in |

An earlier launch, the same minute (`20260930T204213Z-dc432e`), was refused
before any agent started: `SKILLC_ALLOW_REAL_AGENT` was unset. No container ran
and no quota was used. It is kept as the record of that refusal.

## Per attempt

Primary endpoint = the four task criteria (`calibration.primary_endpoint`).
Readiness and verified status are shown beside it (`readiness_beside`).

| # | Arm | Attempt | Primary | Installation-ready | Verified status | Agent s | Wall s | Grading s | Input tokens (cached) | Output tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | full-cpp | a-e2124fea65c6 | PASS | SATISFIED | PASS | 149 | 174 | 15 | 121,801 (109,440) | 4,055 |
| 2 | baseline | a-bad787703385 | PASS | UNKNOWN | INCONCLUSIVE | 146 | 153 | 5 | 163,309 (149,760) | 3,965 |
| 3 | baseline | a-58a7c83c1a8b | PASS | UNKNOWN | INCONCLUSIVE | 96 | 107 | 10 | 120,066 (110,464) | 3,551 |
| 4 | full-cpp | a-8452b5c30895 | PASS | SATISFIED | PASS | 184 | 229 | 36 | 240,175 (210,432) | 4,371 |
| 5 | full-cpp | a-f76c3e6f1a63 | PASS | SATISFIED | PASS | 143 | 157 | 4 | 158,264 (145,792) | 3,852 |
| 6 | baseline | a-4b7a762dc78a | PASS | UNKNOWN | INCONCLUSIVE | 138 | 143 | 4 | 142,076 (129,152) | 3,891 |
| 7 | full-cpp | a-d554a2fd0b5b | PASS | SATISFIED | PASS | 131 | 144 | 4 | 154,945 (138,240) | 3,206 |
| 8 | baseline | a-b9fa34978a0c | PASS | UNKNOWN | INCONCLUSIVE | 135 | 140 | 4 | 120,059 (110,464) | 3,501 |

Every attempt was `captured`, with its transcript retained (`coverage: complete`).

## The five questions

### 1. Does the grader behave? Yes.

- **Certified:** `qualify.py` on main: `QUALIFY: ok`. 11 committed candidates graded as designed, 5 broken graders refused, 14 pipeline-validity controls held. These cover the malformed-mutation, unproven-defect, syntax-broken, no-verdict, lookalike-verdict, timeout and missing-tool paths, each UNKNOWN, never a detection.
- **In the run:** every attempt's `pipeline-honest` evidence reads `detected: 2, accepted: 2`. Both planted defects were proven and then rejected. Both benign changes, the comment and the forwarding wrapper, were proven and then accepted. No attempt produced an UNKNOWN.

### 2. Can the baseline reach the primary endpoint? Yes: 4/4 PASS.

This is also the trap #204 was built to avoid, observed live. Every baseline
attempt satisfied all four task criteria, yet its stored verified status is
INCONCLUSIVE, because `installation-ready` stays UNKNOWN on the stand-in.
Comparing verified statuses would have scored this run 4-0 to CPP. The primary
endpoint scores it 4-4.

### 3. Is difficulty useful? No: both arms at ceiling.

- 8/8 PASS on every criterion. The endpoint cannot move, so no treatment effect can show.
- The agents also exceeded the task. One baseline's closing message reports that it "strengthened the pipeline to check installed console output, exit status, and translation-file swaps".
- For a model at this level, the pipeline-honesty requirement is well inside its reach when stated publicly in `goal.md`.

### 4. Did the CPP arm select and use CPP? No.

Measured from the retained transcripts, not only the heuristic detector:

- **Exposure:** every full-cpp transcript carries CPP's skill listing (`flow-auto`, `flow-finish`, `flow-eli5`, `flow-merge`, ...). Every baseline transcript lists only codex's built-in `.system` skills. The treatment was delivered.
- **Use:** in all 4 full-cpp attempts, no tool call opened a `SKILL.md` or any path under the skills directory. The only "skill"-matching commands were writes of the liveness canary file `.skillc-canary-result`. The heuristic detector agrees: `skill_invocations: []` on all 8.
- **Likely reason:** the likely reason is that nothing in the task matches what CPP's skills are for. CPP's codex skills are issue-and-PR workflow procedures (worktree, ELI5 gate, finish, merge). The fixture has no `.git`, and `goal.md` names no issue, branch or PR, so there was nothing for those skills to apply to. This is an inference from the task's shape; the transcripts show the non-use but not the agent's reason.

### 5. Per-attempt cost, to size #203

| | Median | Range |
|---|---|---|
| Agent time | 140 s | 96-184 s |
| Wall per attempt (setup + agent + teardown) | 148 s | 107-229 s |
| Grading | 4.5 s | 4-36 s |
| Input tokens | 148,500 | 120k-240k; 90% of all input was cached |
| Output tokens | 3,870 | 3.2k-4.4k |

- **Whole run:** 8 attempts in about 21 minutes, far inside the 1,200 s per-attempt and 10,800 s total caps.
- **Cost:** subscription quota only. There is no per-attempt dollar price, and there were no judge calls.
- **Arm difference:** none worth reading at n=4. The full-cpp arm's median input was slightly higher (156k vs 131k), plausibly the size of the skill listing. The largest attempt (#4, 240k) was a full-cpp attempt.

A #203-sized study of, say, 3 arms x 10 attempts on a task of this size would
take roughly 70 minutes of agent time (30 x the 140 s median). The binding constraint is the task, not
the budget.

## What #203 needs

1. **A task where the skill collection is relevant.** The task should ask for work CPP's skills exist for: a git repository, an issue to resolve, a branch and a closing reference, and a gate to keep honest. It must stay subject-independent: the task asks for the WORK, never for CPP. Otherwise a null result means "unused", not "unhelpful", as it did here.
2. **A task harder than the model's default.** It needs failure modes a capable model does not avoid unprompted. #211 (mining CPP's escaped-failure history) is the proposed source. #150's `finish-close-ref` shows that a real incident alone is not enough; each candidate needs its own calibration.
3. **Keep what worked.** Keep the symmetric primary endpoint, the approved-declaration gate, the model pin and transcript retention. This run validated all four.
4. **Calibrate the new task before comparing.** Repeat this two-arm calibration on it. Go only when neither arm is at ceiling or floor, AND the transcripts show the treatment arm opening its skills.

## Scope

A calibration, not a comparison. Four attempts per arm support none of these
claims: that CPP helps, that CPP does not help, or that the arms differ. Raw
evidence (the store, transcripts and final messages) stays in the private run
directory. The numbers above are copied from it: `outcomes.json`, the stored
`result-*.json` and `observation-*.json` records, and the retained transcripts.
