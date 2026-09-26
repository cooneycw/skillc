# Evaluation work

The current roadmap is [PLAN.md](../PLAN.md), with the
[facility specification](../docs/specs/evaluation-facility/spec.md),
[interface contracts](../docs/specs/evaluation-facility/interfaces.md) and
[evaluation protocol](../docs/specs/evaluation-facility/protocol.md).

## Tasks

| Task | Level | Status |
|---|---|---|
| [slug small-fix](level1/slug-small-fix/README.md) | 1 - Basic execution | Grader certified by `qualify.py` against a fixture, reference, alternatives, wrong outputs and broken-grader controls (#5); no model trial run |

## Subjects

| Subject | Surface | Status |
|---|---|---|
| [CPP native Codex skills](subjects/cpp-codex/SUBJECT.md) | 74 `codex/skills/` directories at a pinned revision | Materialized by `skillc materialize` with every readiness fact SATISFIED through codex-cli 0.157.1 (#7); invocation and task outcome not observed |

## Probes

| Probe | Status |
|---|---|
| [Selection probe](selection-probe/README.md) | Three predeclared cases plan through the real controller and a cost estimate is committed (#26); no live attempt has run - `run-manifest.json`'s `execution` stays `"incomplete"` pending an approved budget (ADR 0005) |
| [Matched pilot](matched-pilot/README.md) | The predeclared experiment record, treatment-vs-baseline plan and cost estimate are committed, reusing #26's estimator (#12); the evidence-report schema (`pilot-report`, #12) is defined and its bundle control is committed - no live attempt has run, `execution` stays `"incomplete"` |

No behavioral runner is implemented here yet. The former example plugin command
and YAML were unverified research, not an executable contract. skillc depends on
no external evaluation runtime ([ADR 0003](../docs/decisions/0003-no-external-evaluation-runtime.md));
its controller is `skillc/trial.py` (#8) and the Docker runner arrives with #10. This directory does not promise
compatibility with a particular CLI.

Static validity, skill invocation and successful delivery are distinct measurements.
Matched with/without comparisons test benefit on the selected tasks. Equal results
on a small sample do not prove a skill has no value. Every authoritative grader
needs known-good/bad controls, and the evaluator must detect its own broken checks.
