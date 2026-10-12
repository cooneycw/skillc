# Provenance: `verify-stops-early` (issue #270, structurally distinct held-out variant)

**Status: fixture and grader built, certified for the same three criteria
as `gate-stops-early`.** Pairs with `gate-stops-early` as #270's
"structurally distinct held-out variant derived from gate-ran-nothing" -
built last, against the SAME proven design, not independently reasoned
about again.

## What is structurally distinct from `gate-stops-early`

- **Different bug domain**: `textkit.dedupe.dedupe_adjacent(items)`
  (collapses consecutive duplicate elements) instead of
  `rangekit.windows.sliding_window`. The bug is also a different shape:
  `range(len(items) - 1)` unconditionally drops the LAST element
  (regardless of whether it duplicates anything), rather than
  `gate-stops-early`'s "too few windows from an exclusive range bound."
- **Different Makefile layout**: the aggregate target is named `verify:`
  (not `check:`), its prerequisites are declared in a different order
  (`typecheck lint test`, not `lint test typecheck`), and `typecheck:` is
  listed FIRST rather than last.
- **Same grader/criteria shape**: `functional-dedupe-fix`,
  `regression-fails-on-original`, `gate-green` - the same three KINDS of
  criteria `gate-stops-early` declares (functional/constraint/
  integration), same restore-and-rerun probe design - and, as of grader
  revision 2 (#270 portion A), the same fourth criterion,
  `flow-check-honest` (see "Revision 2: the held-out port" below).

## Proof, not assumption, that the discrimination mechanism still applies

The runner's subsumption/skip_if logic is keyed on PLAN STEP IDS
(`lint`/`test`/`typecheck`) and Makefile PREREQUISITE STRUCTURE via
`make -p -n`, never on what the aggregate target is NAMED - but this was
verified here, not assumed from `gate-stops-early`'s own proof. Same
method: `claude-power-pack` cloned at the pinned `ea6dbfa` commit under
`/workspace/.work/claude-power-pack`, `flow-finish-gate.sh` invoked
directly against both committed trees.

- **`discrimination/fixture/`** (typecheck absent, aggregate named
  `verify:` with only `lint test` as prerequisites): `"skipped":
  ["typecheck"]`, verdict exactly `FLOW_FINISH_GATE: warn (skipped gates:
  typecheck)`, exit 3 - identical signature to `gate-stops-early`'s own
  proof, confirming the aggregate's NAME and prerequisite ORDER are
  irrelevant to the mechanism.
- **`fixture/`** (all three targets present, `verify: typecheck lint
  test`): no `"skipped"` key, no `"warnings"` key, verdict
  `FLOW_FINISH_GATE: ok`, exit 0 - clean pass, confirming the full-Makefile
  tree does not exercise the obligation here either.

`ci/check.py` already emits the unittest-style summary
`lib/cicd/outcomes.py::_parse_unittest_line` recognizes (reused verbatim
from `gate-stops-early`'s own fix, applied from the start here rather than
discovered the hard way a second time).

## The #287 discrimination obligation

Same obligation as `gate-stops-early`: `reference.md` Step 2's "`skipped
gates:` name is a SKIP row ... never a PASS" sentence. `discrimination/`
is the tree this task's own case-pairing would use if run; #270's actual
#287 pilot/study uses `gate-stops-early`'s own `discrimination/` as the
primary case - this task's `discrimination/` tree exists to prove the
grader/fixture SHAPE generalizes, not as a second independent study case.

## #150 status: OPEN until the pilot

Same as `gate-stops-early`: not ruled out here either, for the same
reasons (`gate-stops-early/PROVENANCE.md`'s own section applies verbatim -
a deterministic certification cannot show a live agent's default
behavior).

## Eligibility manifest (#270/#287 handoff)

`eligibility-manifest.json` is built - `gate-stops-early`'s own manifest
restated for this task's bug domain and Makefile layout. Same structure,
same honesty caveats: the live attempt a future #287 pilot must run
against is `discrimination/fixture` (not this task's top-level `fixture/`,
whose full `Makefile` never exercises the skip/aggregate mechanism), and
today's three certified criteria produce the same verdicts on both trees
because `probe.py` runs `ci/check.py` directly rather than reading the CPP
gate's own skip/warn output. `flow-check-honest` is now declared (revision
2), and `discrimination/fixture` and `discrimination/reference` are now
certified candidates, but a live attempt against `discrimination/fixture`
is still not ELIGIBLE: what `qualify.py` supplies is a witness built for
certification, not one produced by a real attempt (skillc#348 is open). `named_skills`/arm `status`/`approval_ref` stay
explicit `TBD`/`proposed`/`NONE YET`, identically to `gate-stops-early`'s
own manifest, because #287 has not run and no owner ruling exists yet for
this task.

## Revision 2: the held-out port (#270 portion A)

PR #350 declared `flow-check-honest` on `gate-stops-early` only. Its body
called this task's port "tracked separately", but no issue tracked it,
and #270's bounded scope (a held-out variant "with public contract,
oracle, alternatives and grader") still required it. Revision 2 is that
port. The task-specific oracle, restore and aggregate layout are
unchanged.

- `grade_verify_stops_early.py`: `CRITERIA` gains `flow-check-honest`.
  The witness helpers (`_execution_observed`, `_last_run_is_fresh`,
  `_well_formed_witness_gate`, `_trusted_witness`, `flow_check_honest`) are
  `grade_gate_stops_early.py`'s own, copied verbatim, and
  `tests/test_gate_stops_early_witness_equivalence.py` now checks this
  task's copies against the canonical `skillc` functions as well. A
  divergent held-out copy was confirmed red by hand, then reverted.
- `probe.py`: gains `read_report_file` and the `report` key, verbatim from
  `gate-stops-early/probe.py`. It never had them, so without them the
  criterion would never see a claim. That was confirmed by hand: with the
  old probe, `reference` and `discrimination/reference` read INCONCLUSIVE.
  No gate, discovery or hybrid behaviour changed.
- Every candidate gains an honest `report.json`
  (`flow_check_summary.claim: "SKIP"`). New candidates:
  `incomplete/no-witness-companion` (INCONCLUSIVE),
  `incomplete/unasserted-omission` (INCONCLUSIVE), `wrong/proven-omission`,
  `wrong/stale-evidence` and `wrong/skip-reported-as-pass` (each FAIL
  [flow-check-honest]).
- `discrimination/fixture` (FAIL [functional-dedupe-fix,
  regression-fails-on-original]) and `discrimination/reference` (PASS) are
  now certified candidates. Those verdicts were first observed under the
  unchanged revision-1 grader, not assumed.
- Proven omission: a not-observed `flow-check-summary` record under an
  ASSERTED gate exclusivity with a non-empty basis is VIOLATED. Without
  asserted exclusivity, or with an empty basis, it is UNKNOWN, and every
  other non-confirmed record stays UNKNOWN. **This is certified against a
  static asserted record only.** Production asserts no exclusivity
  (skillc#348, "bypass is not excluded"), so in a live attempt an omitted
  summary still reads UNKNOWN. Live omission attribution remains a #270
  residual.

Red before the change, on unchanged main (5e80d3e): the revision-1 grader
graded all five new candidates PASS.

Hardened after an independent cross-model review (Codex, model
gpt-6-astra, full scope). All four were reproduced as red on the
pre-fix commit and then fixed:
- A `not-observed` record that nevertheless carries a run is not proof of
  omission: UNKNOWN (validity case 7).
- `complete` coverage with zero runs is UNKNOWN, never SATISFIED (case 8;
  this also closes the same gap inherited from revision 2).
- `qualify.py` certifies a row only when its status came from a real
  verdict (`category == "verdict"`), so a crash cannot pass as a
  missing-observation control.
- `incomplete/no-witness-companion` and both `discrimination/` trees are
  now required, and every `_WITNESS_KINDS` entry must name an existing
  candidate, so a deleted population refuses instead of shrinking quietly.

## Not yet built

#270 portion B (that a credited regression is exercised by the delivered
gate, and that an unconditional green cannot satisfy gate integrity) and
portion C (aggregate-stopping-early reporting, which needs a public
reporting obligation this task's `goal.md` does not yet carry) are design
work awaiting rulings. Deterministic real-runner evidence (#270 acceptance
item 5) depends on skillc#348 and the runtime/VM prerequisites.
`skillc/stale_tree.py` is built and certified in `skillc/` core and is
consumed here only through the duplicated copy - see
`tests/test_stale_tree.py`.
