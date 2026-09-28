# Provenance: slugkit-installed fixture

## Everything here is original to this PR

The `slugkit` package, its trailing-hyphen bug, the replacements-table
mechanism, `probe.py`'s install-emulation and real-pip logic,
`grade_slugkit.py`, every `wrong/*` candidate, and `fixtures/fake-pip/` are
all written from scratch for skillc issue #13 - not copied or adapted from
any external source. No external license notice applies.

The trailing-hyphen BUG SHAPE (`.strip()` where `.strip("-")` was meant) is
the same class of defect Level 1's slug-small-fix fixture pins (see
[`evals/level1/slug-small-fix/PROVENANCE.md`](../../level1/slug-small-fix/PROVENANCE.md)
for that external pin) - reused here as a familiar, well-understood defect
so this task's NEW dimension (installed-path grading) is the only unfamiliar
thing a reader has to evaluate, not also a new kind of bug. `slugkit`'s own
code is independently written, not copied from Level 1's fixture.

## Deliberately not built

- A real pip-based grade in this repository's own environment: pip and a
  build backend are absent here and in the #78 trial/grading container
  (checked directly - see README.md); adding either is out of scope for
  this planning PR.
- A live model run through this task: out of scope (#13's own "Keep runtime
  implementation out of the planning PR"; no CLI wiring, no `agent_trial`
  changes).
