# Provenance: helper-different-question

Written from scratch for this repository. No external source was copied; no
external license notice applies.

The task design is candidate 3 of
[`docs/research/cpp-incident-catalogue.md`](../../../docs/research/cpp-incident-catalogue.md#3-the-helper-that-answers-a-different-question)
(#213). That design covers the fixture shape (an approved change merged
cleanly beside a sibling that added the same step number, and a helper that
checks added lines only), the planted hazard and the PASS/FAIL criteria. It
is drawn from the catalogue's reading of claude-power-pack's public issue
history and its detector-contracts index: the "base sync" and "index rule"
rows, CPP #910 and CPP #1185. The catalogue's own Provenance section covers
that reading.

The runbook text, the ledgerd commands and the helper are invented. The
merged runbook was produced by a real `git merge` of two branches over the
invented base, which confirmed that the merge completes without a conflict.
The fixture commits the result as plain files.

The layout and the `qualify.py` harness follow
[`evals/level3/gate-ran-nothing`](../gate-ran-nothing/PROVENANCE.md), itself
modelled on `evals/level3/slugkit-pipeline`.
