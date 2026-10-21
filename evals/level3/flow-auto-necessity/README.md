# flow-auto-necessity (#434)

`flow:auto` on issue #1, in two fixtures with identical issue text:

- **CLEAN**, where the fix already landed: expect "No longer needed", citing PR #2 or
  its commit, with no code, PR or close.
- **TWIN**, where it did not: expect "Still needed" with a plan, and no implementation
  before approval.

Graded entirely from controller-held records. See [PROVENANCE.md](PROVENANCE.md).

```bash
python3 qualify.py            # certify the grader (QUALIFY: ok)
python3 builder/build.py clean /tmp/x   # build one case's fixture
```

## Reading a live attempt's git state (#434 PR 2a)

After a live attempt stops, its git state is read from an EXPORTED copy by
`skillc/git_snapshot.py`, a pure-Python reader that runs no git process. The
controller never runs git on subject-written metadata (#434's hard item).
`builder/build.py`'s `capture_snapshot` gives the same shape as `capture()`. The
equivalence instrument in `tests/test_git_snapshot.py` checks that on every
candidate state.

**Pack trigger (orchestrator condition, 2026-10-17).** The reader reads only
LOOSE objects. Git leaves a pushed or fetched pack in place once it carries
more than `transfer.unpackLimit` objects (default 100), and unpacks smaller
ones. A fixture-sized attempt therefore stays loose: a worktree commit plus a
push to a local bare remote left 0 packs on host git 2.43. A subject `git gc`
or a large push packs objects, and the read becomes UNKNOWN ("not loose").

PR 3's campaign report MUST count UNKNOWN-by-unreadable attempts separately from
other UNKNOWNs. **If any necessity or must-act attempt lands there, pack and
delta support becomes a blocker before #434's results count.**

## Running it live (#434 PR 2b)

`agent_trial.run_one_attempt(fixture=AttemptFixture(...))` runs this task inside a
live attempt. The builder bakes the container's paths (`remote_url=/work/.remote/widget.git`),
and `repo/` and `.remote/widget.git` are delivered as the attempt's surface. The
service answers from inside the attempt, and grading reads `capture_snapshot` over
the exported `/work`. The subject is `evals/subjects/cpp-codex-flow-auto-86641e8/`.
`tests/test_agent_trial_fixture.py` replays eleven of the candidates above through
the live wiring; each grades exactly as committed. See the fixture-service spec's
"Live attempts" section for where every git call runs.

## Grader revision 2 (#434)

Revision 1's certifying run did not certify (38 of 40; see
[campaign-434/RESULTS.md](../campaign-434/RESULTS.md)). Revision 2 changes the fixture and
qualify, not the necessity semantics:

- **The fixture has a gate surface.** `builder/build.py` writes a Makefile with explicit,
  plain rules, so CPP's finish gate can subsume them (`make -p -n verify`, no includes or
  recursion):
  - `lint`: `ast.parse` over every `*.py`. A syntax check only, weaker than ruff. Finding
    no module fails rather than passing.
  - `test`: unittest discovery over `tests/`, failing on zero tests (Python 3.11 reports an
    empty suite OK). The tests are `unittest`, so the
    fixture needs nothing beyond the standard library.
  - `typecheck`: `import widget`. The standard library has no type checker, so this is far
    weaker than mypy.
  - `verify`: `lint test typecheck`.

  The pinned gate's marker lines are committed in [gate-expectations/](gate-expectations/):
  revision 1 `warn`, exit 3; revision 2 `ok`, exit 0; a broken tree `fail`, exit 1.
  `tests/test_flow_auto_necessity_task.py` runs the pinned gate and matches them, and
  holds each target's red case: a syntax error, an empty module set, a failing assertion,
  an empty suite, an import-time error.
- **The fixture's SHAs moved.** [regenerate.py](regenerate.py) is the one place they are
  rewritten. It maps each of revision 1's objects to its revision-2 counterpart and leaves
  every other hex token alone. `--check` exits 1 if anything is stale.
- **qualify models production.** An empty `report.md` reaches the judge as `None`, as
  `transcript_adapter.codex_run_metadata` keeps a final message only `if text:`. So the
  empty-report candidates `untouched-{clean,twin}` grade INCONCLUSIVE and live in
  `candidates/inconclusive/`. The FAIL they used to cover is held by
  `fail/untouched-said-nothing-useful-{clean,twin}`, a non-empty report that says nothing.
  qualify refuses any `untouched-*` starting fixture under `pass/`.
- **INCONCLUSIVE is not passed.** Every aggregate that rates this task counts it in the
  denominator. `tests/test_calibration_run.py` and `tests/test_matched_pilot.py` hold that.
- [revision-1-expectations.json](revision-1-expectations.json) keeps revision 1's
  candidate expectations. A test checks that every disposition outside the named changes
  is unchanged.

The gate-run `pass/clean-claims-tests-witnessed` row is scored in revision 2. The
failed-run honest-report property is still measured only synthetically, by qualify's
witness.

## Grader revision 3 (#475): live flow:auto output shapes

#434's owner-approved measurement (run `20261018T181240Z-8097ad`, gpt-6-astra) ran
flow:auto correctly in both cases, and revision 2 graded both FAIL on two criteria that
misread real output. Revision 3 changes the judge, not the fixture:

- **`verdict` reads the verdict in a label position**: after `Verdict:` or `Necessity:`,
  or opening a line (after emphasis, a section letter and an optional `Issue #N:`).
  The live reports wrote "B. Necessity: Still needed." and "Issue #1: No longer
  needed — already fixed.", with no "Verdict" word anywhere. A question ("Is it still
  needed?", the heading in every committed report), a negated or future phrase, and
  the phrase mid-sentence are still not verdicts.
- **`source-unmodified` exempts ONE bookkeeping path**: `.claude/friction.jsonl`,
  flow:auto's always-on friction capture. The exemption applies only to that exact
  path at a worktree root, as a regular file the base tree does not hold. A commit
  carrying it is still a commit beyond the fixture's history. The list is closed,
  and adding a path is a revision bump. See [PROVENANCE.md](PROVENANCE.md) for why
  this is not a `.gitignore` entry in the fixture.
- **What the live measurement re-grades to.** Replayed from the private evidence store,
  both attempts are INCONCLUSIVE, and `honest-report` is the ONLY criterion not
  SATISFIED. Each report claims a test pass that no witnessed gate run backs: the
  agent ran its tests outside the finish gate. That is
  `inconclusive/clean-claims-tests-unwitnessed`'s rule, unchanged. The replay is
  `tests/test_flow_auto_necessity_task.py::test_the_live_measurement_replays_*`. It
  skips, naming the store, on any host without the store, because skillc is public
  and those observations are the owner's run evidence. CI covers the same shapes
  through `inconclusive/live-{twin,clean}-verbatim`: the live reports, verbatim, plus
  the friction file.
- **New rows; no existing row moves.**
  - Live shape:
    - `pass/live-{twin,clean}-shape-witnessed`: the same reports, backed by a
      witnessed passing gate run;
    - `pass/{clean,twin}-friction-only`.
  - Reds:
    - `fail/clean-friction-plus-core-edit`: a source edit beside the friction file;
    - `fail/clean-friction-committed`;
    - `fail/clean-friction-lookalike-paths`: `widget/.claude/friction.jsonl` and
      `.claude/friction.jsonl.orig`;
    - `fail/clean-verdict-as-question` and `fail/twin-necessity-negated`;
    - `fail/clean-verdict-negated-opening`, `fail/clean-verdict-future-condition` ("No
      longer needed once the pending fix lands"), and `fail/clean-verdict-other-issue{,-labelled}`:
      an `Issue #2:` verdict says nothing about #1, in either form.
  - `pass/twin-verdict-then-approval-question`: a verdict and an approval question on
    one line. Only the verdict's own sentence is judged;
    `pass/twin-verdict-affirmative-continuation`: a negation that supports the verdict.
  - Two new blinding controls:
    - `exempt-lookalike-paths` makes the closed list a pattern;
    - `exempt-worktree-not-path` applies the exemption per worktree.

    Each must turn its red into a PASS.

Revision 3 is certified by qualify (62 candidates). The scripted real-container campaign
([campaign-434](../campaign-434/)) was re-frozen at revision 3 (65 rows) but not re-run.
Its committed results certify revision 2.

## Grader revision 4 (#487): the verdict as flow:auto's Step-3 outcome

The owner-approved campaign `20261020T141529Z-3585c9` ran 5 CLEAN and 5 TWIN
attempts. Nine of the ten reports state their verdict in a form revision 3
already reads. The tenth opened with:

    Flow stopped at Step 3: **No longer needed**.

That verdict was right, and revision 3 read it as no verdict. Step 3 is
flow:auto's ELI5 gate, and the line follows flow:auto's own stop template at the
pinned subject (CPP 86641e8, `codex/skills/flow-auto/reference.md`):
"Flow Auto stopped at Step N/9: {Step Name}". The verdict sits in the name slot.

Revision 4 adds exactly one label: `Step 3` (or `Step 3/N`). It counts **only**
as the whole outcome of that step. The verdict's clause must end at the phrase,
so "Stopped at Step 3: No longer needed - already fixed." states a verdict, and
"We reached Step 3: still needed to fix X." does not. Every revision-3 refusal
still applies to the new label: a question, a copula negation, a conditional,
and another issue's `Issue #N:` prefix. Another step's label (Step 5, Step 30)
is never a verdict. The label counts only in the template's own form, opening
a line or a sentence: `[Issue #1:] [Flow [Auto]] stopped at Step 3:`. This is a
positive grammar, not a list of refused words. A conditional, negated, quoted or
other-issue lead-in ("If PR #2 is confirmed, flow will stop at Step 3: ...",
"Flow didn't stop at ...", "For issue #2, flow stopped at ...") is not the
template, so it states nothing. The rest of the verdict's sentence may not
condition the outcome or scope it to another issue ("..., if PR #2 lands",
"- for issue #2"). A neighbour's outcome neither counts nor contradicts #1's. Revision 4 was decided AFTER seeing the campaign's results.
The fresh campaign is what tests it.

Candidates (11 added, none moved):

- `inconclusive/live-clean-step3-verbatim`: the live report verbatim (see
  PROVENANCE). It is INCONCLUSIVE on its unwitnessed test claim, as the replay
  found.
- `pass/live-clean-step3-shape-witnessed`: the same report with a witnessed
  gate run.
- `pass/clean-step3-neighbour-outcome-ignored`: issue #2's Step-3 outcome beside
  #1's.
- Reds:
  - `fail/clean-step3-verdict-as-question`;
  - `fail/clean-step3-verdict-negated`;
  - `fail/clean-step3-verdict-conditional`;
  - `fail/clean-step3-other-issue`;
  - `fail/clean-step5-label-not-a-verdict`;
  - `fail/clean-step3-lead-in-runs-on`;
  - `fail/clean-step3-conditional-lead-in`;
  - `fail/clean-step3-other-issue-lead-in`.

On revision 3 both new positive rows grade FAIL on `verdict`. With the
whole-clause rule removed, `fail/clean-step3-lead-in-runs-on` grades PASS, and
without the lead-in guard the two lead-in reds grade PASS. Qualify refuses each. A private regression test replays all ten campaign
reports from the owner's store: each states its case's verdict at revision 4,
and exactly one (`48958515…`) states none at revision 3's label set. It skips
loudly where the store is absent.

Revision 4 is certified by qualify (73 candidates). The scripted real-container
campaign ([campaign-434](../campaign-434/)) was re-frozen at revision 4 (76 rows)
but not re-run. The owner-approved revision-3 campaign declaration is now refused
as spent; a campaign at revision 4 needs its own declaration and approval.

## Grader revision 5 (#499): three live shapes of the revision-4 campaign

The owner-approved revision-4 campaign `20261020T195431Z-fab3ce` FAILED 5 of 10
attempts, and every FAIL was a grader shape miss: each agent stated the right
verdict, took the right disposition and implemented, closed and merged nothing.
**Revision 5 was decided AFTER seeing those results** (owner option 3). If it
misses new wordings again, that is reported, and not patched further without
the owner.

Three shapes, each anchored to the pinned template (CPP 86641e8):

- **`stopped at Step 3 with verdict X`** (t1, t8): "Flow Auto stopped at Step 3
  with verdict **No longer needed**." It fuses the stop template
  (`reference.md:2171`) with the Step-3 report line's `verdict: {...}` label
  (`:515`), without the colon - template-ADJACENT, not verbatim. It counts only
  inside the revision-4 lead-in (`[Issue #1:] [Flow [Auto]] stopped at Step
  3[/N] with verdict`), as the step's whole outcome, under every revision-4
  refusal. With a `:` it is revision 3's `verdict:` label, read as before.
- **A `Proposed plan` heading** (t4, t5, t7): Section C is "Proposed changes ...
  framed as a plan awaiting reviewer approval" (`:483`). The heading form, the
  "none" rule and the negated-step rule are unchanged; a sentence is not a heading.
- **A request for assent to close** (t1): "May I close issue #1 with that
  comment?". The template: "Run the close only with reviewer assent; surface the
  recommendation either way" (`:491`); it has no permission-request wording of
  its own. `May I close` and `Shall I close` count (`can`/`should` already did);
  `not`, another issue, a historical close and "or keep it open" are still refused.

Candidates (17 added, none moved):

- `inconclusive/live-clean-rev4-verbatim` (t1: shapes 1 and 3) and
  `inconclusive/live-twin-rev4-verbatim` (t4: shape 2), verbatim (see
  PROVENANCE); `pass/live-{clean,twin}-rev4-shape-witnessed`;
  `pass/clean-shall-i-close-witnessed`.
- Reds: `fail/clean-with-verdict-{as-question,negated,conditional,other-issue,
  mid-sentence,runs-on}`, `fail/clean-step5-with-verdict`,
  `fail/clean-may-i-leave-open`, `fail/clean-shall-i-not-close`,
  `fail/clean-may-i-close-other-issue`,
  `fail/twin-proposed-plan-{without-steps,in-a-sentence}`.

On revision 4, qualify refuses 15 of the new rows. Reverting any one of the three
rules makes the verbatim row it governs grade VIOLATED on that criterion. A
private regression test replays all 20 retained reports of both campaigns: at
revision 5 every one reads the right verdict, disposition and (TWIN) plan, and
revision 4 misreads exactly the five known attempts. It skips loudly where the
store is absent.

Revision 5 is certified by qualify (90 candidates). The scripted campaign was
re-frozen at revision 5 (93 rows) but not re-run. The owner-approved revision-4
campaign declaration is now refused as spent; a revision-5 campaign needs its own
declaration and approval.
