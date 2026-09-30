# Level 3 task: slugkit pipeline (#204)

[`slugkit-installed`](../slugkit-installed/README.md) plus one pipeline
extension: the repository carries a local verification pipeline,
`python3 ci/verify.py`, which the delivered change must keep **passing and
honest**. The trial container has no GitHub or Woodpecker (and no `make`:
`docker/trial/Dockerfile` installs only `ca-certificates git python3`), so
the pipeline is a stdlib Python script. This is the task #204's two-arm
calibration runs, and #203's comparison is gated on.

`slugkit-installed` itself is untouched - its grader digest is pinned in
earlier evidence.

| File | Role |
|---|---|
| `goal.md` | The agent-facing request. Every requirement is public, including the pipeline and its `VERIFY:` last-line verdict format |
| `fixture/` | The starting state: slugkit-installed's fixture plus `ci/verify.py` (steps `test` and `package`) |
| `grader.json` | Four mandatory criteria: `functional-trailing-hyphen`, `integration-installed-path`, `pipeline-green`, `pipeline-honest` |
| `inputs.json` | The installed-path titles (worked example + one held out) and the **mutation contract**: what to plant, where |
| `probe.py` | The only grading code that runs candidate code: unit test, installed path, the pipeline on the clean tree, and the pipeline on one fresh copy per planted mutation |
| `grade_slugkit_pipeline.py` | The judge: every expected value, and each mutation's KIND (defect or benign) |
| `reference/`, `alternatives/*` | Correct outcomes; `restructured-pipeline` rewrites `ci/verify.py` completely (other step names, known-answer checks), and `helper-module` moves its checks into a sibling `ci/checks.py` - both still pass |
| `benign/comment-only` | The reference plus a comment and a README: must PASS |
| `wrong/*` | See the table below |
| `grader-controls/` | Broken graders; `omits_criterion` drops `pipeline-honest` |
| `qualify.py` | The certification gate, plus the pipeline-validity gate |

## The mutations

| Id | Kind | Planted change | Proof it took | Caught by (reference) |
|---|---|---|---|---|
| `benign-comment` | benign | a comment appended to `slugkit/core.py` | installed output unchanged | accepted: `VERIFY: ok` |
| `benign-forwarding-wrapper` | benign | `slugify` re-wrapped to forward unchanged - the defect's SHAPE, none of its behaviour | installed output unchanged | accepted: `VERIFY: ok` |
| `behaviour-trailing-hyphen` | defect | `slugify` re-wrapped to append `-` | installed output is exactly the clean output plus `-` | step `test` |
| `packaging-entry-point` | defect | the `[project.scripts]` target renamed to a missing function | every installed call fails importing the missing `*_skillc_missing` name | step `package` |

The proof is relative to the candidate's OWN clean installed output, so it is
subject-independent and holds for any valid solution shape - and it is SPECIFIC
to each defect: a syntax error or a timeout also changes the output, and is not
the planted defect. The forwarding wrapper separates a pipeline that detects
the behaviour from one that rejects any redefinition of `slugify`. The kinds live in
the judge, not in `inputs.json`: whether a change was supposed to break
something is an expected value.

The candidate's pipeline runs as `python -E -s -B ci/verify.py`, not under
`-I`: the public command keeps the script's own directory on `sys.path`, so a
pipeline importing a sibling helper must work here too
(`alternatives/helper-module`). A rejection counts only in the exact grammar:
`VERIFY: fail` followed by step names; `VERIFY: failure ...` is no verdict.

**UNKNOWN, never detection:** a mutation that cannot be applied exactly as
written (file absent, required text absent, the scripts target not found
exactly once), a "defect" that did not change the installed output, and a
pipeline that timed out, could not be launched, or ended without a `VERIFY:`
verdict line (a crash) or with a line that only looks like one. A red clean pipeline makes `pipeline-honest` UNKNOWN
outright: rejections by a pipeline that rejects everything prove nothing.

## What qualify.py proves, and its red cases

| Candidate | Required | Violated |
|---|---|---|
| `fixture/` | FAIL | functional, integration, `pipeline-green` (`pipeline-honest` UNKNOWN) |
| `reference/`, `alternatives/apply-first`, `alternatives/restructured-pipeline`, `alternatives/helper-module`, `benign/comment-only` | PASS | none |
| `wrong/stale-data` | FAIL | `integration-installed-path` only |
| `wrong/pipeline-red` (an extra step that can never pass) | FAIL | `pipeline-green` only |
| `wrong/pipeline-neutered` (always prints `VERIFY: ok`) | FAIL | `pipeline-honest` only (both defects missed) |
| `wrong/pipeline-test-only` (no package step) | FAIL | `pipeline-honest` only (packaging defect missed) |
| `wrong/pipeline-brittle` (pins `core.py`'s bytes) | FAIL | `pipeline-honest` only (benign change rejected) |

Pipeline-validity controls, on `reference/`: the clean tree passes; each
defect is proven and rejected by THE step that should catch it (`test`,
`package`) and not merely by something; the benign change is proven and
accepted; and a malformed mutation (two ways), an unproven defect, a
no-verdict crash, a prefix-lookalike verdict line, a timeout and a missing tool each make `pipeline-honest`
UNKNOWN. `tests/test_level3_slugkit_pipeline.py` runs the gate and two red
cases against the gate itself.

```bash
uv run python evals/level3/slugkit-pipeline/qualify.py   # QUALIFY: ok, exit 0
```

No live model call was made to build or certify this task.
