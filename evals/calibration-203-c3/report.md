# #203 calibration report, step (b): B/N/P on `helper-different-question`

**Run 2026-10-04, 14:56-15:29Z. Result: at the FLOOR. Every one of the 18
attempts failed, in every arm, in the same way.** The first task was at
ceiling (18/18 PASS, `calibration-203`, and 6/6 at effort `low`). This one
is at floor. Neither discriminates, so neither can show whether CPP's skills
change the outcome.

## Run

- **Command:** `SKILLC_ALLOW_REAL_AGENT=1 skillc calibration-run evals/calibration-203-c3/run-manifest.json`,
  exit 0, from a fresh clone at the declared commit `fc02838`.
- **Experiment:** `calibration-09960aea`.
- **Identities:** codex-cli 0.157.1, `gpt-6-astra` effort `high` (observed on
  all 18, `model_ineligible=0`), image `sha256:eb17e8c7…`, cpp-codex @
  `85e9b03`.
- **Transcripts:** all 18 retained (`coverage: complete`), the #235 fix
  working live.

## Results

| Arm | Primary PASS | Opened a skill | Mean agent time | Mean tokens |
|---|---|---|---|---|
| `baseline` (B) | **0/6** | - | ~50 s | ~109k |
| `natural` (N) | **0/6** | 0/6 | ~51 s | ~123k |
| `provided` (P) | **0/6** | 6/6 (`flow-auto` every time) | ~83 s | ~288k |

**Every attempt** has the same shape:
- `report-verdict` and `one-section-per-step` VIOLATED;
- `approved-content-present` and `other-content-preserved` SATISFIED.

That is exactly the committed `wrong/trusted-the-helper` candidate. The
step numbers stayed `1, 2, 3, 4, 5, 5`. Each agent reported the approved
change `intact`, "including its exact text and placement". **None of the 18
final messages mentions the duplicate Step 5.**

```
1 baseline FAIL opened=false named=- agent=42s tok=108741
2 baseline FAIL opened=false named=- agent=74s tok=143174
3 natural FAIL opened=false named=- agent=45s tok=123564
4 baseline FAIL opened=false named=- agent=45s tok=108816
5 natural FAIL opened=false named=- agent=43s tok=122094
6 provided FAIL opened=true named=true agent=79s tok=327891
7 baseline FAIL opened=false named=- agent=60s tok=92125
8 natural FAIL opened=false named=- agent=50s tok=123460
9 provided FAIL opened=true named=true agent=68s tok=267755
10 provided FAIL opened=true named=true agent=68s tok=277227
11 natural FAIL opened=false named=- agent=86s tok=123747
12 provided FAIL opened=true named=true agent=89s tok=261525
13 provided FAIL opened=true named=true agent=83s tok=324845
14 natural FAIL opened=false named=- agent=45s tok=123407
15 natural FAIL opened=false named=- agent=39s tok=122350
16 provided FAIL opened=true named=true agent=109s tok=266840
17 baseline FAIL opened=false named=- agent=43s tok=108729
18 baseline FAIL opened=false named=- agent=39s tok=93725
```

## The finding inside the floor

**In all 6 P attempts, the transcript shows the agent reading `flow-auto`'s
`reference.md` and its `detector-contracts` document.** That document
records this exact failure class: an instrument whose true answer is read as
answering a wider question. All 6 then trusted the helper anyway. One wrote
that "the supplied verifier and full-context comparison both passed".

On this task, reading the relevant CPP guidance made no difference to the
outcome. It cost about 1.7x the time and about 2.6x the tokens.

## Report questions

1. **Does the grader behave?** Yes. All 18 attempts were graded on all four
   criteria, with no INCONCLUSIVE from the grading path. Every failure
   matches a committed, certified wrong candidate.
2. **Is difficulty useful?** **No: at floor.** With the first task at ceiling,
   the useful band lies between them.
3. **Uptake?** N opened a skill 0/6 times. Natural uptake is now **0/19**
   across #204, `calibration-203`, `calibration-203-low` and this run. P
   opened a named skill 6/6 times.
4. **Value (P vs B, descriptive)?** 0/6 vs 0/6. No difference is visible at
   the floor either. The transcripts add something the counts cannot: P
   read the guidance that names this class of mistake, and it still did not
   transfer.
5. **Go / redesign / stop?** **Redesign**, with a construct question to
   settle first (below). The run took about 33 minutes.

## A construct question to settle before reusing this task

An agent that **noticed** the duplicate could still argue the approved change
is "intact": its text is exact, and the clash comes from the sibling. The
grader would FAIL that too. None of these 18 agents noticed, so the question
did not decide any outcome here. It would, though, on a run where agents
start noticing. `goal.md`'s wording ("carries exactly the approved change")
and `APPROVED.md`'s ("directly after Verify health") support "changed".
Whether they support it unambiguously is the owner's call.

## Evidence

`calibration-report.json`, the store and the 18 retained transcripts stay in
the operator's private run directory. The tables above transcribe them.
