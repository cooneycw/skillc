# Provenance: `gate-stops-early` (issue #270)

**Status: grader certified (QUALIFY: ok). `flow-check-honest` now has
real, tested, mutation-checked LOGIC as a standalone function
(`qualify.py`'s `flow_check_honest_validity()`), proven against synthetic
gate-witness records built with `skillc.gate_witness`'s own constructors,
seeded from skillc#332's locked record shape. It is still NOT a declared
criterion of this grader - see the new section below for why, and for
what eligibility actually requires.**

## Subject pin

Built against `cpp-codex-flow-check-ea6dbfa` (skillc #265/#330, merged
`841689b`), pinned at claude-power-pack `ea6dbfa45f9308ee6ba60f032d8e7031bd6938a1`.
Not the historical `85e9b03` profile, which stays a separate, untouched
profile per its own PROFILE.md.

## The fixture

A rangekit-style project (same shape as `evals/level3/gate-ran-nothing`,
derived from it per #270's acceptance scope), with a new bug distinct from
`gate-ran-nothing`'s `clamp()`: `rangekit.windows.sliding_window(seq, size)`
drops its last window (`range(len(seq) - size)` should be
`range(len(seq) - size + 1)`). The `Makefile` declares `lint:`, `test:` and
`typecheck:` individually - closing the gap the flow-check workflow-contract
README names explicitly (`evals/workflow-contracts/flow-check/README.md`'s
"Finding": no existing fixture has those targets, so no existing case can
measure whether flow-check runs checks at all) - **and** a `check:` aggregate
listing all three as Make prerequisites, so a failing `lint` stops `make`
before it reaches `test`/`typecheck` (standard Make prerequisite-build
semantics, not anything this fixture implements itself).

`ci/lint.py` and `ci/typecheck.py` are stdlib-only, self-contained checks
(a bare-`except:` scan and a missing-annotation scan, respectively),
following `ci/check.py`'s own existing convention in `gate-ran-nothing`
rather than depending on `ruff`/`mypy` being installed wherever this fixture
is graded.

## Two runner mechanisms, deliberately both reachable

Read `lib/cicd/runner.py`/`state.py` in the pinned subject's own snapshot
(`tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa/`) before designing
this, rather than assuming from `reference.md` alone. There are two
DISTINCT ways a step can end up neither PASS nor FAIL:

1. **SKIPPED** (`skip_if` applicability - e.g. no `typecheck:` target at
   all). `reference.md` Step 2 gives the agent a clean, isolated
   instruction: *"`skipped gates:` name is a SKIP row and a `zero
   coverage:` or no-tests name is a WARN row - never a PASS."*
2. **NOT_RUN** (aggregate-prerequisite deferral, CPP issue #1152,
   `runner.py::_resolve_deferred`/`state.py::mark_step_not_run`). This is
   the literal "incomplete aggregate gates" mechanism #270's title names:
   when steps are declared as Makefile prerequisites of one aggregate (this
   fixture's `check:`) and an earlier one fails, `make` never reaches the
   rest, and the runner records them `status=NOT_RUN` with a reason
   ("`<prerequisite>` failed"), distinct from SKIPPED.

`reference.md`'s own Step 6 report table defines exactly three symbols
(PASS/FAIL/SKIP) and gives **no instruction anywhere** for what an agent
should do with a NOT_RUN step - confirmed by reading the whole file, not
assumed from its absence in the excerpts quoted here. **This is a real gap
in the pinned skill, filed as [claude-power-pack#1388](https://github.com/cooneycw/claude-power-pack/issues/1388)
(credited to this issue; a fix is in progress on the CPP side, landing at a
later CPP pin, so the `ea6dbfa` study pin is unaffected).** The intact
arm's handling of a NOT_RUN step is therefore UNINSTRUCTED BY DESIGN at
this pin, not an oversight in this fixture.

This fixture is built to reach BOTH mechanisms (the chained `check:`
aggregate for NOT_RUN; a variant with an absent target for SKIPPED), but
only mechanism 1 is used for the #287 discrimination pairing below - see
"Why NOT_RUN is not the discrimination obligation."

## The #287 case-pairing (discrimination) obligation

**Tested obligation:** `reference.md` Step 2's sentence, *"`skipped gates:`
name is a SKIP row and a `zero coverage:` or no-tests name is a WARN row -
never a PASS."*

- **Intact arm:** the pinned skill, unmodified - this sentence present.
- **Degraded arm:** the identical installed skill with exactly this
  sentence removed, nothing else touched. `skillc profile diagnose`
  against the degraded install must show the removed obligation gone and
  no OTHER agent-facing text still carrying it.
- **Why the sentence's occurrences elsewhere don't count.** The phrase
  `skipped gates:` and `never a pass` also appear in
  `codex/skills/flow-check/scripts/flow-finish-gate.sh` (shell comments and
  a literal verdict string the script EMITS, e.g. `verdict "warn (skipped
  gates: $SKIPPED_GATES)"`) and in `lib/cicd/runner.py`/`steps.py` (code
  comments). None of these are agent-facing INTERPRETIVE instructions -
  they are the plumbing that PRODUCES the raw marker text the agent reads,
  never a second copy of the instruction telling the agent what to DO with
  it. Only `reference.md`'s own prose carries that interpretation, and
  `.claude/commands/flow/check.md` (the source `reference.md` is generated
  from) is not part of this profile's installed closure for a `codex`
  client (confirmed against `PROFILE.md`'s own closure table), so it is not
  a second agent-facing copy either.

### Proven, not reasoned about: the obligation actually applies here

The orchestrator's correction: `fixture/`'s own Makefile declares ALL of
`lint:`, `test:` and `typecheck:`, so `skip_if` applicability never fires
and the "skipped gates: ... never a PASS" sentence is never exercised -
intact and degraded could not differ on it. `evals/level3/gate-stops-early/
discrimination/{fixture,reference}/` is a separate tree for exactly this
pairing: identical task/bug/tests, but `typecheck:` is absent from the
Makefile entirely (and `pyproject.toml` configures no mypy-equivalent
tool), so the runner's own `skip_if` condition
(`! grep -q "^typecheck:" Makefile ... && ! grep -q "<mypy token>"
pyproject.toml`, `lib/cicd/steps.py::_gate_step`) is satisfied.

**Proof, not argument** - the real runner at the pinned commit
(`claude-power-pack` @ `ea6dbfa45f9308ee6ba60f032d8e7031bd6938a1`, cloned
and invoked directly: `FLOW_GATE_CPP_DIR=<checkout> bash <checkout>/
scripts/flow-finish-gate.sh --plan check --evidence flow-check`, run from
inside each tree):

- **`discrimination/fixture/`** (typecheck absent): `"skipped": ["typecheck"]`
  in the runner's own JSON, and the verdict line reads exactly
  `FLOW_FINISH_GATE: warn (skipped gates: typecheck)` (exit 3) - the
  precondition the discrimination obligation depends on, and the ONLY
  signal present (no other warning).
- **`fixture/`** (all three targets present): no `"skipped"` key in the
  JSON at all, no `"warnings"` key either, and the verdict line reads
  `FLOW_FINISH_GATE: ok` (exit 0) - a clean pass, confirming the
  full-Makefile tree does NOT exercise this obligation at all.

**First capture had a stray signal, caught and fixed before it reached
the grader milestone.** `ci/check.py`'s original custom print format
("CHECK: ok - N failures") matched none of `lib/cicd/outcomes.py`'s
recognized test-summary shapes (pytest/jest/unittest), so EVERY run
against the full-Makefile tree reported `FLOW_FINISH_GATE: warn` even
with zero real test failures - an unintended second signal that would
have muddied every acceptance-item grade on that tree, and would have
sat beside `warn (skipped gates: typecheck)` in `discrimination/`,
giving two reasons for one verdict where the grader needs exactly one.
Read `lib/cicd/outcomes.py::_parse_unittest_line`/`_UNITTEST_RAN`/
`_UNITTEST_VERDICT` (never guessed the format) and rewrote `ci/check.py`
to print the exact shape that parser recognizes: `Ran N test(s) in
X.XXXs` followed by `OK` or `FAILED (failures=N)`. Re-captured both
directions after the fix (above); the stray `warn` is gone from the
full-Makefile tree, and `discrimination/fixture/`'s `warn` now carries
only the `skipped gates: typecheck` qualification.

`discrimination/` is the tree the #287 live study's intact/degraded
attempts actually run against. `fixture/`/`reference/` (full Makefile,
`check:` aggregate) stay the main task tree for the acceptance-item
grading, including the NOT_RUN/aggregate-stopping-early variants.

## Why NOT_RUN is not the discrimination obligation (rejected first choice: FC-TEST)

An earlier draft of this section proposed `FC-TEST` ("run `make test`,
report the real result") as the discrimination obligation. The orchestrator
rejected it: issue #150's risk is that BOTH arms satisfy the measured
criterion because the model does the thing BY DEFAULT, regardless of
instruction - and most capable coding agents run `make test` unprompted
when asked to fix a bug with a regression test, whether or not a skill says
so. Measuring an adherence criterion instead of the functional patch does
NOT escape this risk; it only relocates it.

The chosen obligation (report a skipped/unrun gate as SKIP, never as PASS)
is plausibly LESS likely to be met by default: when a multi-step check
reports an overall non-failing result with one step absent, the natural
"everything's fine" summary a model reaches for is to fold the absence into
an unremarked PASS - correctly distinguishing "this didn't run" from "this
passed" requires knowing the runner's own verdict-marker vocabulary
(`skipped gates:` vs a bare `ok`), which is CPP-specific plumbing a model
has no reason to already know. This is an argument for why the obligation
is PLAUSIBLE to fail by default, not proof that it does.

**No existing #203/#237 baseline or cpp-codex calibration record was found
that measures what an uninstructed agent reports for a partially-run,
multi-step aggregate gate.** Searched `evals/calibration-*`, `evals/level*`
and `docs/research/cpp-incident-catalogue/` for this specific scenario;
nothing addresses it (the catalogue's own incidents are CPP's own code-review
findings, a different population). **This is stated plainly rather than
argued around: the #287 pilot is the first measurement of this risk for
this case, not a confirmation of one already taken.**

## #150 status: OPEN until the pilot

Per the orchestrator's explicit instruction: this document states #150's
non-discriminating-result risk as **OPEN**, not ruled out. A deterministic
certification (this fixture, its grader, its mutation checks) can show the
obligation is CLEANLY REMOVABLE and that the functional task is identical
across arms; it cannot show that a degraded agent actually behaves
differently from an intact one in a live attempt. Only the #287 pilot's
live data can speak to that, and its own record must say in its own text
that it draws no verdict, per the operator's ruling relayed on #287.

## Eligibility manifest (#270/#287 handoff)

`eligibility-manifest.json` is built, mirroring `gate-ran-nothing`'s own
shape (same `selection`/`outcome` separation, same B/N/P arm names). Two
things it says that are specific to this task:

- The live attempt a future #287 pilot must run against is
  `discrimination/fixture`, never this task's own top-level `fixture/`.
  `fixture/`'s `Makefile` declares all three gates, so the skip/aggregate
  mechanism never fires there - an agent can fix the bug and pass the gate
  regardless of how it reports anything. `discrimination/fixture/`'s
  `Makefile` omits `typecheck:` unconditionally and is otherwise
  byte-identical rangekit code; it is the tree that actually gives the
  agent a skipped-gate obligation to report or omit.
- The three criteria `qualify.py` just certified do not read the CPP
  gate's own skip/warn output at all (`probe.py` runs `ci/check.py`
  directly) - so grading `discrimination/fixture` today produces the
  SAME three verdicts as grading `fixture/`. The manifest says this
  explicitly rather than implying the task is pilot-ready: a live attempt
  against `discrimination/fixture` is not yet ELIGIBLE for #270's own
  obligation until `flow-check-honest` is declared and wired through it.
- `named_skills`, arm `status` and `approval_ref` are left as explicit
  `TBD`/`proposed`/`NONE YET` - #287 has not run, and no owner ruling
  parallel to #203's decision 3/4 exists for this task. Filling those in
  here would misstate a decision nobody has made.

## `flow-check-honest`: logic built, declaration deferred, eligibility NOT YET

skillc#332's gate-witness record shape is locked (gate names
`"flow-check-plan"`/`"flow-check-summary"`; `GateRecord`/`GateRunRecord`'s
own fields; three worked examples - a normal confirmed run, a
not-observed bypass, and a channel failure split into `launch-failed`
versus `channel-unavailable`). `grade_gate_stops_early.py`'s new
`flow_check_honest()` reconciles a candidate's own `report.json`
(`flow_check_summary.claim`, `"SKIP"` or `"PASS"`) against that record,
using logic DUPLICATED (never imported) from
`skillc.gate_witness.GateRecord.execution_observed()` and
`skillc.stale_tree.last_run_is_fresh()` - confirmed the hard way: a first
draft imported `skillc` directly at module level and broke every
EXISTING criterion with `ModuleNotFoundError`, because
`skillc.verify._judge` stages the judge file ALONE (`-I -S -B`, no
`skillc` package reachable) - the self-containment rule this file's own
module docstring already stated turned out to bind even an import that is
never called, not only one that is.

**A second structural finding, more consequential:** `flow-check-honest`
is NOT added to `CRITERIA`/`grader.json`'s declared set, and is not
reachable through `judge()`'s returned criteria at all. `skillc.verify`'s
real contract (`criteria_problem()`) refuses a judge report unless EVERY
returned criterion is `mandatory: True` AND the id set exactly equals the
grader's declared set - there is no "optional criterion" shape anywhere in
the real pipeline. A criterion that can only answer UNKNOWN (no live
witness exists yet for any existing call site) therefore cannot be
declared without `records.derive_status` turning every already-certified
candidate's PASS/FAIL into INCONCLUSIVE. This is why
`flow_check_honest()` is a STANDALONE function, certified directly by
`qualify.py`'s own `flow_check_honest_validity()` (5 named discrimination
cases - SKIP claim SATISFIED, PASS claim VIOLATED, not-observed UNKNOWN,
channel failure UNKNOWN, stale tree VIOLATED even with an honest claim -
plus two broken-control checks, `always_satisfied` and `ignores_witness`,
both refused) exactly the way `restore_probe_validity()` already calls
`judge()` directly rather than through `grade_directory()`. All 5 cases
and both control refusals were mutation-checked by hand against the real
function (flipping the staleness check, swapping the SKIP/PASS verdicts,
and disabling the `execution_observed` gate each turned the matching
check red, confirmed, then reverted).

**Duplication is a drift risk, so it carries its own guard**
(`tests/test_gate_stops_early_witness_equivalence.py`, in the NORMAL
suite where `skillc` IS importable - unlike the isolated judge itself).
It runs the SAME battery of records (normal, not-observed with and
without exclusivity, launch-failed, channel-unavailable, interrupted,
zero runs, a single fresh run, a single stale run, an edit-then-rerun
cycle, and a rerun that drifted away) through both the judge's duplicated
`_execution_observed`/`_last_run_is_fresh` AND the canonical
`skillc.gate_witness.GateRecord.execution_observed`/
`skillc.stale_tree.last_run_is_fresh`, asserting identical results.
Mutation-checked: flipping `launch-failed`'s reported status from
UNKNOWN to CONFIRMED, and reading `runs[0]` instead of `runs[-1]`, each
turned the matching case red, confirmed, then reverted. A silently
diverging copy would grade against a different rule than the one the
real gate-witness implements, and nothing in the judge's OWN suite could
ever notice, since it never sees the canonical functions to compare
against - this is what closes that gap.

**Eligibility stays explicitly NOT YET**, in those words, in both this
task's and `verify-stops-early`'s `eligibility-manifest.json`: a live
#287 attempt needs (1) skillc#332 merged, (2) skillc#334 merged (the
live-attempt profile-closure install gap found while building #332 -
without the declared closure installed, `~/.claude/scripts/flow-finish-gate.sh`
is absent and every flow-check invocation exits 127 before reaching
anything this judge could grade), and (3) a deterministic subject run
through the real runner producing a genuine captured witness record
(#270 acceptance item 5) - not merely a declared criterion existing.

## Not yet built

`verify-stops-early`'s own port of `flow_check_honest()`, the
`wrong`/`benign` variants that need it once declared, and the
UNKNOWN-on-missing-observation variants (#270 acceptance item 4).
Declaring `flow-check-honest` as a REAL criterion of either grader needs
either a different contract shape from `skillc.verify` or an
always-answerable default, and is deferred to when the three eligibility
conditions above are met. `skillc/stale_tree.py` (the
controller-tree-digest-vs-graded-tree comparison `gate-witness.md` §6
defers to #270/#271) stays built and certified in `skillc/` core, but is
now consumed only via a duplicated copy inside the judge, never imported
- see `tests/test_stale_tree.py` for its own, separately-certified tests.
