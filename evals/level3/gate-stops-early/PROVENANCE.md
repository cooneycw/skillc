# Provenance: `gate-stops-early` (issue #270)

**Status: fixture content only.** This file is extended at each later
milestone (grader, mutation, certification); the sections below record what
is settled so far.

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

## Not yet built

Grader, criteria, `grader-controls/`, `qualify.py`, `probe.py`,
`inputs.json`, `eligibility-manifest.json`, `expected.json` for each
variant, the `wrong/`/`benign/`/`alternatives/` trees for acceptance items
2-4, and the held-out structurally-distinct variant. These are the next
milestones.
