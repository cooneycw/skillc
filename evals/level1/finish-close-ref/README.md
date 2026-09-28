# Level 1 task: finish-close-ref

Skillc #150 acceptance item 1: a Level-1 task whose fixture and grader make
**one specific CPP skill or instruction necessary to pass**, graded
deterministically on an artifact, certified the way
[slug-small-fix](../slug-small-fix/README.md) is certified.

| File | Role |
|---|---|
| `goal.md` | The agent-facing request. Identical for every arm. |
| `fixture/src/TODO.md` | The starting state: acceptance items for a fictional issue #42, two open |
| `grader.json` | The grader definition (revision 1): required criteria, probe, inputs, judge |
| `probe.py` | Reads `src/commit_message.txt` and reports its text. The only grading code that reads a candidate-controlled artifact |
| `inputs.json` | The one file name the probe reads: `["commit_message.txt"]` |
| `grade_ref.py` | The judge: holds the closing-keyword rule and emits the criteria. Never shown to the agent |
| `reference/`, `alternatives/*/` | Correct outcomes; each must PASS |
| `wrong/*/` | Plausible wrong outputs; each must FAIL |
| `*/expected.json` | Each candidate's required status and the exact criteria it must violate |
| `grader-controls/` | Broken graders: always-pass, always-fail, crash, no-output, omits-criterion |
| `qualify.py` | Certification gate over all of the above |
| `PROVENANCE.md` | The rule this task depends on, where it lives (five locations, not one), and the corrections made to the initial sketch |

```bash
uv run python evals/level1/finish-close-ref/qualify.py   # QUALIFY: ok, exit 0
```

`tests/test_level1_finish_close_ref.py` runs the same gate in the suite and CI.

`qualify.py` grades every candidate through skillc's verifier
(`skillc.verify.grade_directory`, #9), the same staged path that grades a real
attempt: the probe runs on a disposable copy under a supervisor that sweeps
every process the candidate started, the judge starts only after that sweep.
skillc then derives the status. A broken-grader control replaces the judge;
the probe and inputs stay the task's own.

## Public acceptance

`goal.md` asks for a commit message, on `src/commit_message.txt`, that
references issue #42, states plainly that #42 stays open with what remains,
and follows the `flow-finish` skill's rule for how a commit references an
issue - without restating that rule (see PROVENANCE.md, "Selection is held
fixed on purpose"). The grader reports four mandatory criteria:
`artifact-present`, `issue-ref`, `stays-open`, `no-closing-match`, each
SATISFIED, VIOLATED or UNKNOWN with evidence.

- **The discriminating case.** A careful agent WITHOUT the flow-finish rule,
  told the issue must stay open, plausibly writes "This does not close #42" -
  correct, careful English, and exactly what GitHub's matcher still closes on.
  `wrong/negated-close` is that candidate. An agent that never reads any
  finishing convention just as plausibly appends a reflex `Closes #42`
  trailer regardless of the body (`wrong/reflex-trailer`). Both FAIL only
  `no-closing-match`; both are readable, unremarkable text, not a strawman.
- **GitHub's actual closing grammar, not an arbitrary window.**
  `no-closing-match` matches a keyword, an optional colon, optional
  whitespace, then `#42` or `OWNER/REPO#42`, ANYWHERE in the text - no
  clause-boundary or negation logic, because GitHub's own matcher has none
  either (`wrong/negated-close`, `wrong/not-yet-negation`,
  `wrong/cross-repo-form`, `wrong/colon-form` each isolate one shape).
  `alternatives/stays-open-phrase` ("#42 stays open; closing it waits on
  items 3-4") PASSes: "closing" is not one of the nine keyword forms, and
  nothing follows it that looks like an issue reference.
- **Generous on "stays open".** `stays-open` accepts any of
  open/remain(s)/remaining/incomplete/unfinished/outstanding/pending/left -
  deliberately wide (operator ruling on this task's design) so it
  never fails a reference answer while still catching a message that names
  #42 and nothing else (`wrong/no-remaining-info`).
- **Candidate failures versus grader failures.** A missing or empty
  `commit_message.txt` VIOLATES `artifact-present`, and the other three
  criteria report UNKNOWN, never SATISFIED or VIOLATED - the grader did not
  examine text that was not there. A judge that exits non-zero or prints
  nothing yields INCONCLUSIVE. A crash is never read as a detected defect.

## What qualify.py proves, and its red cases

| Gate input | Required verdict | Observed |
|---|---|---|
| `fixture/` (nothing written yet) | FAIL | FAIL (`artifact-present`) |
| `reference/`, `alternatives/*` | PASS | PASS |
| `wrong/reflex-trailer` (body is fine, trailer is `Closes #42`) | FAIL | FAIL (`no-closing-match`) |
| `wrong/negated-close` ("does not close #42") | FAIL | FAIL (`no-closing-match`) |
| `wrong/not-yet-negation` ("does not yet resolve #42") | FAIL | FAIL (`no-closing-match`) |
| `wrong/colon-form` ("Fixes: #42") | FAIL | FAIL (`no-closing-match`) |
| `wrong/cross-repo-form` ("closes cooneycw/x#42") | FAIL | FAIL (`no-closing-match`) |
| `wrong/no-issue-ref` (never mentions #42) | FAIL | FAIL (`issue-ref`) |
| `wrong/no-remaining-info` ("Refs #42.", nothing else) | FAIL | FAIL (`stays-open`) |
| `wrong/empty-file` (`commit_message.txt` exists, empty) | FAIL | FAIL (`artifact-present`) |
| `always_pass` grader | refused, PASS throughout | refused: fixture and every wrong candidate PASS |
| `always_fail` grader | refused, FAIL throughout | refused: reference and every alternative FAIL |
| `crash` grader | refused, INCONCLUSIVE throughout | refused, every candidate INCONCLUSIVE |
| `no_output` grader | refused, INCONCLUSIVE throughout | refused, every candidate INCONCLUSIVE |
| `omits_criterion` grader (drops `issue-ref`, `stays-open`) | refused, INCONCLUSIVE throughout | refused: the report lacks required criteria |

`tests/test_level1_finish_close_ref.py::test_a_mutated_reference_turns_the_gate_red`
is this gate's own negative control (ADR 0001/ADR 0008 shape): it plants a
`Closes #42` trailer onto a copy of `reference/`, a candidate that should now
FAIL, and asserts `qualify.certify` reports exactly that - the committed proof
that the gate is not blind, run on deliberately broken input before trusting
its green.

## Audit of the design

- **Selection is deliberately not tested here.** See PROVENANCE.md; #26 owns
  that measurement.
- **The `flow-finish` rule is not confined to `flow-finish`.** It also lives
  in `flow-merge` and `flow-auto`'s reference docs and both skills' bundled
  `gh-pr-merge.sh`. A degraded arm (#150-B) that mutates only
  `flow-finish/reference.md` does not discriminate; PROVENANCE.md lists every
  location the mutation must reach.
- **`GH-42` is not real GitHub syntax.** The orchestrator's initial sketch
  proposed it as a FAIL candidate; checked against GitHub's docs and dropped
  rather than added, because grading it as a violation would itself be a
  false claim about what closes an issue.
- **One line is one line.** Unlike slug-small-fix's held-out-input design (14
  cases probing one function), this task grades one short text file against
  four criteria on one candidate population; there is no per-input held-out
  set to keep confidential, so nothing here is "deliberately unprobed" in
  that sense.

No live model call was made to build or certify this task.
