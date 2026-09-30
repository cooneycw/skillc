# Provenance: slugkit-pipeline

Derived from this repository's own [`slugkit-installed`](../slugkit-installed/PROVENANCE.md)
task (#13): the `slugkit` package, its trailing-hyphen bug, the replacements
table, the stdlib install emulation and the `reference/`,
`alternatives/apply-first` and `wrong/stale-data` candidates are copied from
there, with a `ci/verify.py` added to each.

Everything new for #204 - `ci/verify.py` and its variants, the mutation
contract in `inputs.json`, `probe.py`'s mutation and pipeline stages,
`grade_slugkit_pipeline.py`, the new candidates and `qualify.py`'s
pipeline-validity gate - is written from scratch for this repository. No
external source was copied; no external license notice applies.

The design (a two-arm calibration before a three-arm study, the
baseline-readiness trap, mutation validity and symmetric endpoints) comes
from an adversarial read-only critique of #203 by OpenAI Codex (`codex exec`,
model `gpt-6-astra`), requested via `/codex:ask` on 2026-09-30 and recorded
in issue #204's own Attribution section.
