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
  integration), same restore-and-rerun probe design, same deliberate
  non-declaration of `flow-check-honest` pending skillc#332.

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
gate's own skip/warn output - so a live attempt against
`discrimination/fixture` is not yet ELIGIBLE for #270's obligation until
`flow-check-honest` lands. `named_skills`/arm `status`/`approval_ref` stay
explicit `TBD`/`proposed`/`NONE YET`, identically to `gate-stops-early`'s
own manifest, because #287 has not run and no owner ruling exists yet for
this task.

## Not yet built

`flow-check-honest` (pending skillc#332's confirmed record shape, to be
relayed once the shim's records are final) and the remaining
`wrong/`/`benign/` variants for acceptance items 2-4.
`skillc/stale_tree.py` (the tree-identity comparison `flow-check-honest`
will consume) is already built and certified in `skillc/` core - see
`tests/test_stale_tree.py`.
