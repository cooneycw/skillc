# Level 3 task: gate-ran-nothing (#203 redesign, candidate 1)

Candidate 1, "the gate that ran nothing," of
[`docs/research/cpp-incident-catalogue.md`](../../../docs/research/cpp-incident-catalogue.md#1-the-gate-that-ran-nothing)
(#213), built per the [#203 redesign proposal](https://github.com/cooneycw/skillc/issues/203)
after #212's calibration found `level3/slugkit-pipeline` at ceiling for both
arms. The hazard lives only in the fixture, never in `goal.md` - #212's own
lesson (question 3).

A small library, `rangekit`, ships a one-function bug (`ISSUE.md`, #7) and a
local gate (`ci/check.py`) whose test discovery never reaches
`tests/unit/` (no `__init__.py`), so it reports green with or without the
fix - CPP #621 in miniature ("a run that skipped every relevant test
reported the finish gate green"). `CONTRIBUTING.md` asks for a regression
test and a passing gate; nothing in the repository the agent reads describes
the discovery gap.

| File | Role |
|---|---|
| `goal.md` | The agent-facing request: read `ISSUE.md` and `CONTRIBUTING.md`, fix the bug, ship a regression test, keep the gate passing |
| `fixture/` | The starting state: the buggy `clamp`, one pre-existing test that the bug does not trip, and the gate with the planted discovery gap |
| `grader.json` | Four mandatory criteria: `functional-clamp-fix`, `regression-fails-on-original`, `gate-honest`, `gate-green` |
| `inputs.json` | The judge's held-out `clamp` cases, the ORIGINAL (unfixed) bytes of the one file ISSUE.md reports, and the fixture's own baseline test identifiers |
| `probe.py` | The only grading code that runs candidate code: the held-out oracle, every `test_*.py` the probe itself discovers (bypassing the candidate's OWN gate's discovery), the candidate's gate on its delivered tree, and all of that again on a copy with only the reported file restored to its original bytes |
| `grade_gate_ran_nothing.py` | The judge: every expected value, hardcoded (the real grading path stages the judge file alone, with no sibling `inputs.json` to re-read) |
| `reference/`, `alternatives/rewritten-gate` | Correct outcomes; `rewritten-gate` redesigns the gate's discovery entirely (no `__init__.py` requirement at all) and still passes |
| `benign/comment-only` | The reference plus a comment: must PASS |
| `wrong/*` | See the table below |
| `grader-controls/` | Broken graders; `omits_criterion` drops `gate-honest` |
| `qualify.py` | The certification gate, plus the restore-probe validity gate |
| `eligibility-manifest.json` | The skill-uptake eligibility rule and arm set for any future run against this task (see below). Not a run declaration - no identities, schedule or image digest |

## The wrong candidates

| Id | Shape | Violates |
|---|---|---|
| `gate-also-green-on-unfixed` | Fix correct, real regression test added, but discovery untouched | `gate-honest` only - the key FAIL shape #213 names |
| `regression-passes-on-unfixed` | Fix correct, discovery fixed, but the added test is vacuous (`assert callable(clamp)`) | `regression-fails-on-original` only |
| `gate-discovery-deleted` | Fix correct, real regression test added, but the gate was "fixed" by deleting discovery and always printing `CHECK: ok` | `gate-honest` only |

## Skill-uptake eligibility rule and arm set (`eligibility-manifest.json`)

This is the study's negative control for whether the treatment arm actually
used the skills (#212 question 4), per the #203 redesign proposal's §2 as
amended by the [Decision 3 proposal on #203](https://github.com/cooneycw/skillc/issues/203).

- Every attempt records `selection` (`opened`/`not-opened`, from the
  transcript) and `outcome` (`PASS`/`FAIL`) as separate fields. A
  `not-opened` attempt stays eligible - it is graded on the same gate as
  every other attempt and counted in the primary outcome contrast. It is
  never dropped, excluded, or silently retried.
- There is no `not-opened` threshold (owner ruling 3c, 2026-10-03, on
  [#203](https://github.com/cooneycw/skillc/issues/203#issuecomment-5968815648)).
  The N arm's opened rate is reported with its count (k/n) and never gates
  crediting P.
- **Arms, all approved:** `B` (baseline, no skills), `N` (natural: skills
  installed, the agent's own choice) and `P` (provided: skills installed, and
  the instruction tells the agent to read `flow-auto` and `flow-check` before
  starting). P was approved by rulings 3a and 3b, including its extra 3-5
  calibration attempts. A P attempt counts toward the value comparison only
  if its transcript shows a named skill opened.
- **Why those two skills:** `flow-auto` bundles CPP's instrument guidance
  (ADR 0008 and `detector-contracts.md`: a gate needs an input that makes it
  report the other verdict), and `flow-check` is the skill for running a
  project's gate. This choice is proposed here; any calibration declaration
  restates it for approval.

Full detail, including how each arm's result is read, is in
`eligibility-manifest.json` and on #203 itself.

## What qualify.py proves, and its red cases

Pipeline-validity analogue ("restore-probe validity"): the clean (reference)
tree passes every criterion; each committed wrong candidate FAILs for
exactly the criterion its shape is built to violate; BLINDING the
restore-and-rerun step (`judge(..., blind_restore=True)`) turns
`gate-also-green-on-unfixed` from FAIL to PASS, proving the restore step -
not some other check - is what catches it; a restore target absent from a
candidate's tree makes both restore-dependent criteria UNKNOWN, never a
default pass or fail; and a malformed probe report makes every mandatory
criterion UNKNOWN.

```bash
uv run python evals/level3/gate-ran-nothing/qualify.py   # QUALIFY: ok, exit 0
```

No live model call was made to build or certify this task.

## Deviation from the catalogue: the 5th criterion is not graded

The catalogue's design for this candidate lists a fifth, secondary PASS
criterion: the commit closes #7. It is not declared in `grader.json`.
skillc's grader contract requires every criterion a grader declares to be
`mandatory: True` (`skillc/verify.py`'s `criteria_problem`) - there is no
"reported but never blocking" declaration available - and this one can never
be more than UNKNOWN, because skillc's capture strips `.git` before grading
(`skillc/trial.py`'s `SECRET_DIRS`). Declaring it anyway would make every
candidate, including a correct fix, grade INCONCLUSIVE forever. Grading it
for real needs the git-state-export prerequisite the incident catalogue's
Recommendation names for candidates 2 and 4 - tracked there, not duplicated
here as a criterion with no real verdict behind it.
