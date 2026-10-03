# Provenance: gate-ran-nothing

Written from scratch for this repository. No external source was copied; no
external license notice applies.

The task design - the fixture shape (a small library, `ISSUE.md`,
`CONTRIBUTING.md`, a local gate), the planted hazard (test discovery that
never reaches a subdirectory lacking `__init__.py`, a gate that counts
failures rather than executions), and the PASS/FAIL criteria - is candidate 1
of [`docs/research/cpp-incident-catalogue.md`](../../../docs/research/cpp-incident-catalogue.md#1-the-gate-that-ran-nothing)
(#213), itself drawn from a reading of claude-power-pack's public issue
history (CPP #621, #628, #808, #1147, #617, #970 for the BLIND class; CPP
#840, #841, #1014 for EMPTY). The incident catalogue's own Provenance section
covers that reading in full.

The layout (`grader.json`, `probe.py`/judge split, `grader-controls/`,
`qualify.py`'s certify/control_verdict/candidates harness) follows
[`evals/level3/slugkit-pipeline`](../slugkit-pipeline/PROVENANCE.md)'s own
shape, per the #203 redesign assignment. The restore-and-rerun mechanism
(planting the ORIGINAL source back into an otherwise-delivered tree, then
re-running both a direct test pass and the candidate's own gate) is this
task's own, modelled on - but not copied from - slugkit-pipeline's
mutate-and-rerun pattern for `pipeline-honest`.
