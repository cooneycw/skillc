# Level 1 task: slug small-fix

The first goal-based task (#5): repair a slug function against published
requirements. It is a **measurement canary**. Its job is to calibrate the grader
and the measurement path before any model is run. It is not meant to show that
CPP, or any scaffold, is better.

| File | Role |
|---|---|
| `goal.md` | The agent-facing request. Identical for every arm. |
| `fixture/src/slugify.py` | Pinned starting state; see [PROVENANCE.md](PROVENANCE.md) |
| `grader.json` | The grader definition (revision 2): required criteria, probe, inputs, judge. Its digest is what a ledger pins |
| `probe.py` | Runs the candidate on `inputs.json` and reports what `slugify` returned. The only grading code that runs candidate code |
| `inputs.json` | The reported example and held-out inputs, without their answers |
| `grade_slug.py` | The judge: holds the answers and emits the criteria. Never shown to the agent |
| `reference/` | A correct outcome |
| `alternatives/*/` | Other correct implementations; each must PASS |
| `wrong/*/` | Plausible wrong outputs; each must FAIL |
| `*/expected.json` | Each candidate's required status and the exact criteria it must violate |
| `grader-controls/` | Broken graders: always-pass, always-fail, crash, no-output, omits-criterion |
| `qualify.py` | Certification gate over all of the above |

```bash
uv run python evals/level1/slug-small-fix/qualify.py   # QUALIFY: ok, exit 0
```

`tests/test_level1_slug.py` runs the same gate in the suite and CI.

`qualify.py` grades every candidate through skillc's verifier
(`skillc.verify.grade_directory`, #9), the same staged path that grades a real
attempt. The probe runs on a disposable copy under a supervisor that sweeps every
process the candidate started. The judge starts only after that sweep. skillc then
derives the status. So the grader that is certified here is the grader that
grades. A broken-grader control replaces the judge; the probe and inputs stay the
task's own. See [verification.md](../../../docs/specs/evaluation-facility/verification.md).

## Public acceptance

`goal.md` states the reported example and four requirements, R1-R4. The grader
reports one mandatory criterion each for `R4-interface`, `reported-example`, `R1`,
`R2` and `R3`, as SATISFIED, VIOLATED or UNKNOWN with evidence. `qualify.py`
turns those into a protocol status with skillc's own `records.derive_status`, so
this task uses the same verified-result rules as every other result.

- **Development example.** `goal.md` publishes only `"Hello, World!"`.
- **Held-out variations.** `grade_slug.HELD_OUT` lists 14 inputs, each tagged
  with the one requirement it tests. None appears in `goal.md`, and none tests
  anything `goal.md` does not state. The test suite checks both properties.
  Each input is chosen so the other rules hold trivially: R1 inputs have no
  separator runs or boundary separators, R2 and R3 inputs are already
  lowercase, and R3 inputs have no internal separator. A one-defect candidate therefore violates only its own rule, and
  `expected.json` pins that attribution. A rule with no held-out cases reports
  UNKNOWN, not SATISFIED.
- **Standard library only.** The candidate runs with `python -I -S`, which
  disables site-packages. A dependency import therefore fails and violates
  R4. `wrong/third-party` imports `pytest`, which skillc's dev environment
  does have installed, so this check is not vacuous here.
- **Alternatives pass.** The grader compares only returned values. A regex,
  character loop or `findall` join all pass. The interface is checked by
  behaviour (a callable `slugify` returning `str`), not by source shape.
- **Candidate failures versus grader failures.** A candidate that raises, hangs,
  returns a non-string or has no `slugify` VIOLATES `R4-interface`, and so does a
  probe report that is not exactly one returned value per input (candidate code
  can write that report). A judge that exits non-zero or prints nothing yields
  INCONCLUSIVE. A crash is never read as a detected defect.

## What qualify.py proves, and its red cases

| Gate input | Required verdict | Observed |
|---|---|---|
| `fixture/` (the unfixed start) | FAIL | FAIL (`reported-example`, `R3`) |
| `reference/`, `alternatives/*` | PASS | PASS |
| `wrong/example-only` (special-cases the reported example) | FAIL | FAIL (`R3`) |
| `wrong/trailing-only` (`rstrip("-")`, passes the reported example) | FAIL | FAIL (`R3`) |
| `wrong/no-collapse` | FAIL | FAIL (`reported-example`, `R2`) |
| `wrong/keeps-spaces` (trims ends, keeps internal spaces) | FAIL | FAIL (`reported-example`, `R2`) |
| `wrong/no-lowercase` | FAIL | FAIL (`reported-example`, `R1`) |
| `wrong/renamed`, `wrong/third-party` | FAIL | FAIL (`R4-interface`) |
| `always_pass` grader | refused, PASS throughout | refused: fixture and wrong outputs PASS |
| `always_fail` grader | refused, FAIL throughout | refused: reference and alternatives FAIL |
| `crash` grader | refused, INCONCLUSIVE throughout | refused, every candidate INCONCLUSIVE |
| `no_output` grader | refused, INCONCLUSIVE throughout | refused, every candidate INCONCLUSIVE |
| `omits_criterion` grader (drops R1, R2) | refused, INCONCLUSIVE throughout | refused: the report lacks required criteria |

The gate refuses outright in these cases:
- a candidate is missing `src/slugify.py` or `expected.json`;
- an expectation contradicts where the candidate is placed;
- the candidate population is empty.

A broken-grader control only counts if its file exists, it is refused, and it
produces the status and failure path its name promises on every candidate. The
failure path is one of: non-zero exit, empty output, or missing criteria.
`crash` and `no_output` both give INCONCLUSIVE, so the path is what stops one
from standing in for the other. A missing or misbehaving control therefore
fails `qualify.py`.

`wrong/example-only` and `wrong/trailing-only` are the reported-example-only
fixes. Both satisfy the one example the task names and fail only on held-out
inputs. The suite also mutates a copy of the reference and requires the gate to
refuse it.

## Audit of the historical arms

CPP ran this fixture in three cells (`scripts/run-delivery-pilots.py`,
`docs/agents/delivery-pilots.md` at the pinned commit). The differences were:

| Cell | Prompt | Difference from the others |
|---|---|---|
| `baseline` | `task.md` | "Edit `src/slugify.py` only" forbids extra files |
| `open` | `task-open.md` | "Fix it in `src/slugify.py`" has no prohibition |
| `guided` | CPP guidance + `task-open.md` | For its first three runs, the workspace held `task.md` while the prompt used `task-open.md` |

Three confounds follow, and none is inherited:

1. **`baseline` versus `guided`** changed the file prohibition and the guidance
   together. CPP's own report found the prohibition explained the difference.
   Here, one `goal.md` serves every arm, and only the scaffold under study may
   differ (protocol section 2).
2. **Contradictory inputs.** In those early `guided` runs, the workspace task
   and the prompt disagreed. Here, the arm-facing text is one file.
3. **Unpublished requirements.** Neither CPP task stated the required behaviour.
   It appeared only in the source docstring, but CPP's hidden check tested
   leading separators, runs and already-clean titles. Here, R1-R3 are stated,
   so held-out inputs vary published requirements rather than adding secret ones.

`goal.md` neither requires nor forbids extra files. Whether an agent adds a test
or a plan is not graded here; ceremony is a separate observation, not Level 1
acceptance.

## Expected ceiling effects and scope

The fix is one line, and the requirements are stated. A capable model should
pass with or without a scaffold, so equal results are the expected outcome.
Per protocol section 8, that supports "no observed benefit on this task",
never "the scaffold is useless". This task calibrates the grader and the
measurement path. It is **not** evidence of broad CPP superiority, and a null
result from it is valid.

No live model call was made to build or certify this task.

## Deliberately unprobed

- **Non-ASCII titles.** R2 defines separators as anything other than ASCII
  `a-z0-9`, but no held-out input probes it. An `isalnum()` implementation would
  differ only there. That edge belongs to a later constraint-handling variant.
- **Answer-key confidentiality on the host.** Since #9 the expected outputs live
  only in the judge, which runs after every candidate process is gone. So no
  candidate can write the verdict. The judge's file is still readable on disk by
  same-user candidate code that searches for it, and the Docker lane (#10) is what
  removes that. See the trust assumptions in
  [verification.md](../../../docs/specs/evaluation-facility/verification.md#trust-assumptions).
