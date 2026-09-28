# Provenance: slug-constrained fixture

## Base bug and R1-R4

The trailing-hyphen bug and R1-R4 are the SAME rules Level 1's slug-small-fix
task already pins - see
[`evals/level1/slug-small-fix/PROVENANCE.md`](../../level1/slug-small-fix/PROVENANCE.md)
for that fixture's own external source, pinned commit and license notice.
`fixture/src/slugify.py`, `reference/src/slugify.py` and
`alternatives/char-loop/src/slugify.py` here are re-typed by hand from that
same rule set (not a byte-identical copy of Level 1's own files - this task
adds `NOTES.md` beside `src/`, which Level 1's fixture does not carry), so no
external pin applies to them beyond Level 1's own.

## New content, original to this PR

Everything else in this directory - the three constraints (C1-C3), `NOTES.md`
and its content, `probe.py`'s static/structural checks, `grade_constrained.py`,
and every `wrong/*` candidate - is original content written for skillc
issue #13, not copied or adapted from any external source. No external
license notice applies.

## Deliberately not built

- A held-out-INPUT-style probe for C2 (constraint-dependency): as README.md
  states, a static source check has no natural "input" to hold out: the
  held-out element is the adversarial construction itself
  (`wrong/deferred-import`'s unreached branch), not a value.
- A live model run through this task: out of scope for this PR (#13's own
  "Keep runtime implementation out of the planning PR"; no CLI wiring, no
  agent_trial changes).
