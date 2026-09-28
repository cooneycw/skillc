# Level 2 task: slug constrained (#13)

Extends Level 1's slug small-fix (`evals/level1/slug-small-fix/`, unchanged -
Level 1 stays its own calibration canary) with three PUBLIC constraints on
top of the same functional bug fix: interface stability, a dependency
restriction, and data preservation. `#13`'s acceptance line "Report
functional, constraint and integration outcomes separately" is answered by
naming every criterion `functional-*` or `constraint-*` (Level 3 adds
`integration-*`) - a report groups by this prefix. No schema change: a
grader's `criteria` list is still a flat list of strings
(`skillc/verify.py`'s `GraderDef`/`criteria_problem`).

| File | Role |
|---|---|
| `goal.md` | The agent-facing request. States R1-R4 (Level 1's rules) and C1-C3 (this task's new constraints) - every constraint is PUBLIC, per #13's own "keep public requirements" |
| `fixture/src/slugify.py`, `fixture/NOTES.md` | Pinned starting state - same bug as Level 1; `NOTES.md` is the companion file C3 protects |
| `grader.json` | Grader definition: 8 criteria, functional-* and constraint-* bucket-prefixed |
| `probe.py` | Runs the candidate; reports functional outputs AND the three new static/structural observations (imports found by `ast.parse`, `inspect.signature`, `NOTES.md`'s digest). The only grading code that runs candidate code |
| `inputs.json` | The reported example and held-out inputs for R1-R4, without answers |
| `grade_constrained.py` | The judge: holds every answer (including the one hardcoded expected `NOTES.md` digest) and emits the criteria. Never shown to the agent |
| `reference/`, `alternatives/*` | Correct outcomes, differently shaped |
| `wrong/*` | One candidate per new constraint, each passing R1-R4 and violating exactly its own constraint |
| `*/expected.json` | Each candidate's required status and the exact criteria it must violate |
| `grader-controls/` | Broken graders: always-pass, always-fail, crash, no-output, omits-criterion (the last one drops the two constraints THIS task adds, C2 and C3, proving the required-criteria-set check covers new criteria too, not only Level 1's inherited ones) |
| `qualify.py` | Certification gate, copied from Level 1's generic harness (only `REQUIRED_CRITERIA` and file names differ) |

```bash
uv run python evals/level2/slug-constrained/qualify.py   # QUALIFY: ok, exit 0
```

## Held-out variations, per new criterion

Each is stated here, and lives only in `grade_constrained.py` - never in
`goal.md` or `fixture/` - so a fix tuned to the visible example cannot pass
by accident.

- **C1 (`constraint-interface-stability`).** Held out: `inspect.signature`
  applied to the candidate's own `slugify`, checked structurally (every
  parameter after the first must default). goal.md's own example never
  shows a multi-argument call, so a fix that quietly adds a REQUIRED second
  parameter would still satisfy the one worked example while breaking every
  other 1-argument caller - exactly `wrong/extra-required-param`.
  Note: because this check and the functional criteria both call `slugify`
  with one positional argument, a signature that breaks 1-arg calls also
  cascades into VIOLATED functional-* criteria on the SAME candidate (see
  `wrong/extra-required-param/expected.json` - it names all eight). The two
  checks are not redundant in general, only on this specific known-bad: a
  signature change with a working DEFAULT (e.g. `def slugify(title,
  strict=False)`) would pass every functional case and this check alike, so
  C1's real job is catching a signature that is not obviously broken by a
  single held-out CALL - a syntax-level guarantee about the FUNCTION, not
  about any one input.
- **C2 (`constraint-dependency`).** There is no held-out INPUT in the usual
  sense - this is a structural check of the source file, not an input/output
  pair, so the "held-out variation" framing does not map 1:1 onto it. The
  held-out ELEMENT is the adversarial construction itself:
  `wrong/deferred-import` imports a non-stdlib module inside a branch none
  of R1-R4's held-out inputs ever reaches. goal.md's own worked example
  gives the agent no reason to anticipate that this exact shape would be
  checked. This is why C2 is a STATIC check (`ast.parse` on the source
  text, never executing it) rather than relying on functional-interface's
  own dynamic `-S` (site-packages-disabled) enforcement, inherited unchanged
  from Level 1: a dynamic check only ever sees an import that is actually
  REACHED by some run, so it is blind to exactly this shape by
  construction - not a gap in this task's controls, but the reason a second,
  independent check exists at all.
- **C3 (`constraint-data-preservation`).** Held out: the exact verification
  method (a full-byte sha256 digest of `NOTES.md`, computed once from
  `fixture/NOTES.md` and hardcoded in the judge - never re-read from disk at
  grade time). goal.md states the constraint ("do not modify NOTES.md")
  but not how it is checked. `wrong/notes-touched` changes only a trailing
  newline - proving the check is not lenient about whitespace-only edits, a
  failure mode a line-count or fuzzy-diff check would miss and only a full
  digest catches.

## What qualify.py proves, and its red cases

| Gate input | Required verdict | Observed |
|---|---|---|
| `fixture/` (unfixed start) | FAIL | FAIL (`functional-reported-example`, `functional-R3`) |
| `reference/`, `alternatives/char-loop` | PASS | PASS |
| `wrong/extra-required-param` (C1: required 2nd param) | FAIL | FAIL (all six functional-*/constraint-interface-stability - the cascade explained above) |
| `wrong/deferred-import` (C2: import in an unreached branch) | FAIL | FAIL (`constraint-dependency` only - every functional-* criterion SATISFIED, proving the static check catches what the dynamic one misses) |
| `wrong/notes-touched` (C3: whitespace-only edit to NOTES.md) | FAIL | FAIL (`constraint-data-preservation` only) |
| `always_pass` grader | refused, PASS throughout | refused: fixture and every wrong/* PASS |
| `always_fail` grader | refused, FAIL throughout | refused: reference and alternatives FAIL |
| `crash` grader | refused, INCONCLUSIVE throughout | refused, every candidate INCONCLUSIVE |
| `no_output` grader | refused, INCONCLUSIVE throughout | refused, every candidate INCONCLUSIVE |
| `omits_criterion` grader (drops constraint-dependency, constraint-data-preservation) | refused, INCONCLUSIVE throughout | refused: the report lacks required criteria |

Every wrong candidate's `expected.json` names EXACTLY the criteria the real
grader violates - not merely "some failure" - so a FAIL for the wrong reason
(e.g. `wrong/deferred-import` blamed on a functional rule instead of
`constraint-dependency`) would show as a mismatch, not a pass.

## No live model call was made to build or certify this task.

## Scope

This task adds constraint-handling dimensions on top of Level 1's own
functional rules; it does not re-derive R1-R4's own design reasoning (see
Level 1's README for that). `#13` itself stays open after this PR for its
"compare matched configurations" and "report separately" acceptance items,
which are owed to an actual run through `collection-run`/`agent_trial` -
explicitly out of scope here (no CLI wiring, no live runs; see PROVENANCE.md
and the top-level PR).
