# Level 3 task: cicd-pipeline (#281)

Certify generated CI artifacts through an executable consuming path. The
agent gives a fresh claude-power-pack `/project:init` Python project its
Makefile, `.claude/cicd.yml` and BOTH provider pipelines with CPP's cicd
skills; the grader then **executes** those generated pipelines - locally, not
on a hosted CI service - and checks that every required stage really runs and
that the right stage rejects each planted fault.

Level 3 by the spec's own table (`docs/specs/evaluation-facility/spec.md`:
"3 - Integration ... The installed consuming path works, not only isolated
functions"), the same family as [slugkit-pipeline](../slugkit-pipeline/README.md).

| File | Role |
|---|---|
| `goal.md` | The agent-facing request |
| `fixture/` | The starting state: CPP's real `/project:init` Step 2 output (patched, see PROVENANCE.md) |
| `grader.json` | Five mandatory criteria (below); probe timeout 1500 s |
| `inputs.json` | The planted faults and each one's bare-tool precondition |
| `probe.py` | The only grading code that runs candidate code: parses each generated pipeline, classifies every command against a CLOSED table, runs the obligations in provider order (stopping at the first failure), plants each fault in a fresh copy |
| `grade_cicd_pipeline.py` | The judge: every expected value, including each plant's stage and the starting tree's digests |
| `qualify.py` | The certification gate, through the cicd project runtime |
| `reference/`, `alternatives/*`, `benign/*` | Must PASS |
| `unpatched-real/` | CPP's real, unpatched output (#1477/#1478): the known-bad control, must FAIL |
| `wrong/*` | Must FAIL, each on exactly its `expected.json` criteria |
| `grader-controls/` | Broken judges the gate must refuse |
| `derive_candidates.py` | How every alternative/benign/wrong tree is derived from `reference/` |
| `patches/` | The two declared CPP fixes (PROVENANCE.md) |

## Criteria

| Criterion | SATISFIED when |
|---|---|
| `artifacts-present` | Makefile, `.claude/cicd.yml` declaring the instance's `pipeline.provider`, and every provider pipeline the instance requires (dev: both; held-out: Woodpecker), each actually observed |
| `pipeline-covers-required-checks` | every provider runs lint, test and typecheck each as its OWN `make <target>`; no step can pass whatever it ran (`|| true`, `continue-on-error`, `failure: ignore`, `; exit 0`, `set +e`) or is conditional (`if:`, step `when:`); an unknown command is UNKNOWN |
| `pipeline-green` | on the clean tree every provider's obligations pass, with work evidence (>= 1 test ran, >= 1 file type-checked); an install the warmed cache cannot serve offline is UNKNOWN, any other failed install VIOLATES |
| `pipeline-honest` | each plant, after its precondition is proven with the bare tool, is rejected FIRST by its own stage; passing it is a miss, failing an earlier stage a misattribution; not-run stages are never credited; UNKNOWN when the clean pipeline is not green |
| `behavior-preserved` | every starting file other than the generated artifacts is unchanged, nothing beyond the CI/CD artifacts was added, and running the pipeline changed no file |

## Local execution, not hosted CI

Every report carries that label. Provider setup has a declared local
equivalent (`pip install uv` -> the runtime's pinned uv; `uv sync` -> `uv sync
--offline --locked`; checkout/setup-python/cache -> the workspace, the
runtime's interpreter, the warmed cache). NOT modelled, and never claimed:
provider images (`python:3.12`; the runtime is 3.11), matrix rows other than
the runtime interpreter, triggers (`on:`, `when:` branches/events), secrets,
caching and the actions' own behaviour. YAML structure is read only to find
the commands; nothing is certified from YAML text alone.

## Certification

| Candidate | Required | Violated |
|---|---|---|
| `fixture/` | FAIL | `artifacts-present`, `pipeline-covers-required-checks` |
| `reference/`, `alternatives/handwritten-makefile`, `alternatives/reordered-pipeline`, `benign/comment-only` | PASS | none |
| `unpatched-real/` | FAIL | `pipeline-green`, `behavior-preserved` |
| `wrong/disabled-stage` (GitHub `if: false`, Woodpecker step removed) | FAIL | coverage, honest |
| `wrong/unconditional-success` (`make test || true`) | FAIL | coverage, honest |
| `wrong/missing-target` (`make tset`) | FAIL | coverage, green |
| `wrong/omitted-discovery` (`pytest --collect-only`) | FAIL | green |
| `wrong/early-stop` (one `make verify` whose aggregate stops after lint) | FAIL | coverage, honest |
| `wrong/unrelated-change` (the project's test gutted) | FAIL | `behavior-preserved` |
| `wrong/missing-provider` (the GitHub pipeline deleted) | FAIL | `artifacts-present` |
| `wrong/extra-tool-config` (an added `mypy.ini` narrowing discovery) | FAIL | `behavior-preserved` |
| held-out `fixture/` / `reference/` | FAIL / PASS | as fixture / none |

Every broken grader (`always_pass`, `always_fail`, `crash`, `no_output`,
`omits_criterion`) must produce the status its name promises on `reference/`
and `unpatched-real/` and be refused. The judge's validity reds (unproven
plant, unapplied plant, timeouts, uv's real wrapped offline-miss wording,
unknown commands, ignored failures, misses, misattributions, a run that
changes a file) run offline on a recorded real probe report in
`tests/test_level3_cicd_pipeline.py`.

```bash
# full matrix (run-real-docker, under run.lock): every case, count-checked
python3 qualify.py --receipt RECEIPT --full     # QUALIFY: ok full (26 of 26)
# declared subset (local / unlocked runs)
python3 qualify.py --receipt RECEIPT            # QUALIFY: ok subset (6 of 26)
```

RECEIPT is a `cicd-project-runtime` receipt (`docker/cicd-project-trial/`)
whose warmed lock is `reference/uv.lock`; `tests/test_level3_cicd_pipeline_live.py`
builds the chain and runs this. No live model call was made to build or
certify this task.
