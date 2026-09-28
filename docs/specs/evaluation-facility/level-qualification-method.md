# Level qualification: the method, worked once against Level 1

- Status: Planning baseline, not an implemented gate or threshold
- Date: 2026-09-28
- Governing scope: EF-09 ([spec.md](spec.md#6-progressive-difficulty)),
  [protocol.md §7](protocol.md#7-aggregation-and-progression)
- Refs #15 (Refs #139, #150-D, #12, #147)

This is #15's planning half: "closing this issue requires its acceptance
evidence, not merely code or document presence," and that evidence does not
exist yet above Level 1. This document states the qualification METHOD
generically, from protocol.md §7's own requirement, then applies it once
against the one real dataset the project has - the #12/#147 matched pilot -
to show what the method can and cannot conclude from it. It closes nothing:
no threshold is proposed, no level is claimed qualified, and #15 stays open.
Runtime implementation stays out of this PR, per the issue's own instruction.

## 1. What #15 depends on, and what state each dependency is actually in

Corrected against an earlier, wrong draft of this document: it is easy to
read "the mechanism landed" as "the evidence exists," and they are different
claims.

- **#150-D is unmerged.** It narrows #139's B1 ruling (an agent-trial arm
  that installs a declared collection can write a real installation
  receipt instead of staying on the agent-observation stand-in) but it is
  still waiting on the operator's attestation answer as of this writing.
  Even once merged, **it produces no pilot data by itself** - it is a
  mechanism a live run can use, not a run. The retained bundle below
  predates it and stays exactly as recorded; #150-D cannot retroactively
  change what that bundle's stored results say.
- **#13 has landed one task each for Level 2 and Level 3**
  (`evals/level2/slug-constrained/`, `evals/level3/slugkit-installed/`,
  each `qualify.py`-certified against its own known-good/bad controls). No
  pilot distribution exists yet - no agent attempts have run against
  either - and, same as Level 1 below, ONE task is not yet a declared
  FAMILY (§2's own "predefined task population" requirement asks for
  more than a single case).
- **#14 has landed one case each for Level 4 and Level 5**
  (`evals/level4/instruction-conflict-config-secret/`,
  `evals/level5/recovery-partial-processing/`), explicitly planning-only:
  both PROVENANCE.md files name a known gap (a forged controller-log
  candidate the current judge cannot catch, committed and reproduced by
  `qualify.py`'s own gap check rather than hidden), and no runtime
  implementation - fixture services, real agent attempts, live runs - is
  included. Same shape as #13: one task, no pilot data.
- **Level 6** (adaptive delivery, spec.md's own ladder) has no task defined
  at all yet, in any issue.
- **Every declared level - 1 through 5 - currently has exactly one task.**
  This is not a Level-1-specific gap; it is the project's current shape
  everywhere, and §3's finding (one task is not a population) generalizes
  across all five rather than singling Level 1 out. Level 1 is worked
  through directly below only because it is the one level with a real
  retained RUN, from the closed #12 and its #147 re-run - #13/#14's tasks
  have no attempts against them yet to work through at all.

## 2. The qualification method (protocol.md §7, restated for this project)

Protocol.md §7 states the requirement directly: "Qualification requires a
predefined task population, repeat policy, controlled graders, mandatory
acceptance and regression evidence from relevant earlier levels. Report
levels as not evaluated, exploratory, qualified or regressed, with
supporting configuration and evidence." Every clause below is that sentence,
expanded to what it asks a level's evidence to actually show, generically,
before any concrete number is proposed:

| Requirement | What it asks for | Where the project already has a building block |
|---|---|---|
| Predefined task population | A declared FAMILY of tasks at that level's difficulty, not one task repeated - protocol.md §1's "reserve claims about broader capability for representative task families" | `slug-small-fix` is one task; a Level 1 family does not exist yet (see §3) |
| Development vs. held-out split | Declared and versioned BEFORE scored runs (protocol.md §1, §15 acceptance item 3), so a grader cannot be tuned against the same cases it is later judged on | `slug-small-fix`'s grader already separates development cases from held-out R1/R2/R3 sets at the single-task level; #15 needs this declared at the TASK-FAMILY level, which does not exist yet |
| Repeat policy and sampling plan | How many repeats per task, and what conclusion a given repeat count can support - protocol.md §7: "Statistical intervals and promotion thresholds need a justified sampling plan after pilot calibration; none is specified for the first experiment" | None declared project-wide yet; §3 shows why this is not optional |
| Controlled graders | Known-good/bad pairs per protocol.md §5, plus the evaluator's own handling of a grader that always passes, always fails, crashes, or emits nothing | `slug-small-fix`'s grader has this; #15's method requires it be true of every task in a qualifying family, not spot-checked |
| Mandatory acceptance that cannot be averaged away | Protocol.md §4: "Mandatory constraints cannot be averaged away by optional quality," and §8's own qualification examples ("Passing one unfamiliar task while repeatedly failing simple fixes is an uneven exploratory profile, not a qualified result") | Already enforced at the single-attempt level by `verify.READINESS_CRITERION` and the derived-status rule (one mandatory UNKNOWN or VIOLATED criterion caps the whole result); #15 needs the same discipline applied across a POPULATION, not one attempt |
| Regression evidence from earlier levels | A level cannot be reported qualified while an earlier, simpler level is failing or unevaluated | Not yet meaningful: no level, including Level 1, has reached "qualified" under this method (§3) |
| Four-way reporting | Every level is reported as `not evaluated`, `exploratory`, `qualified`, or `regressed` - never a single blended score, never a public badge or leaderboard (protocol.md §7; #15 acceptance item 5) | This document adopts the same four labels below rather than inventing a fifth |

Nothing in this table is new policy. It is protocol.md §7 read level-by-level,
with a column naming what already exists toward each requirement and what
does not.

## 3. Worked example: applying the method to Level 1's only real data

**The dataset.** [`evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/`](../../../evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/README.md)
(experiment `matched-pilot-64396611`, #147's re-run of #12, model
`gpt-6-astra` pinned). Six attempts: three matched treatment/baseline pairs
on `slug-small-fix` revision 2, codex 0.157.1. All six graded `PASS` (5/5
task criteria SATISFIED); all six stored `verified-result.status` is
`INCONCLUSIVE`, because `installation-ready` is a mandatory `UNKNOWN` under
B1 - the agent path has no installation receipt for this bundle (it predates
#150-D, and #150-D produces no NEW data for an already-retained bundle
regardless - see §1). This split is exactly the one the #28 worked example
([`configuration-boundary-example.md`](configuration-boundary-example.md))
warns against conflating: `graded_status` is the task grade alone;
`verified-result.status` is the derived, mandatory-criteria-inclusive one,
and protocol.md's four result labels (§4 of protocol.md) apply to the
latter, not the former.

**Applying the method:**

- *Predefined task population* - this bundle is ONE task (`slug-small-fix`),
  not a family. Level 1's task population (spec.md: "Complete one clear,
  bounded job") is not yet declared as a family of several such tasks, so
  there is no POPULATION to report qualification over yet, independent of
  outcome.
- *Repeat policy / sampling plan* - n=3 matched pairs, with no stated
  sampling plan (the bundle's own README says so: "At n = 3 this describes
  the sample; it doesn't support an inference about the pack"). Zero
  observed failures at n=3 does not support a failure-rate bound of any
  kind - protocol.md §7 is explicit that intervals need "a justified
  sampling plan after pilot calibration," and none exists for this project
  yet. **This is the central, useful result of applying the method here: the
  right conclusion from 3-for-3 is "no failure observed in three attempts,"
  never "the failure rate is below X%."** Reporting the latter from this
  data would be exactly the fabricated precision protocol.md exists to
  refuse.
- *Controlled graders* - `slug-small-fix`'s grader has known-good/bad
  coverage at the single-task level (protocol.md §5's requirement is met
  for this one task); this says nothing about coverage across a Level 1
  family that does not exist yet.
- *Mandatory acceptance, not averaged away* - all six attempts have their
  mandatory `installation-ready` criterion `UNKNOWN`, so all six are
  `INCONCLUSIVE` at the stored-result level, whatever the task grade says.
  A method that reported this population "qualified" because every task
  grade was PASS would be exactly protocol.md §4's forbidden move -
  averaging away (here, ignoring) a mandatory criterion's actual state.
- *Regression evidence from earlier levels* - not applicable; Level 1 is the
  floor.

**Verdict, in protocol.md §7's own four labels: Level 1 is `not evaluated`
under this method** - not `exploratory` and certainly not `qualified`. It is
not `exploratory` either, in the method's strict sense, because an
exploratory reading would still need a declared task family to describe
breadth over, and this bundle covers one task. What exists is a single
canary, honestly reported as exactly that by its own README, which already
does everything this section asks of it - this document's contribution is
showing that the general method, applied mechanically, reaches the same
place a careful human reading already reached by hand.

## 4. What would change this verdict, per level

Named rather than left implicit, per #15's own instruction ("remaining
dependencies and unavailable evidence stay explicit"):

- **Level 1 -> reportable as `exploratory` at all**: a declared FAMILY of
  Level 1 tasks (spec.md's own ladder), each with dev/held-out cases
  declared before scored runs, run with a stated repeat policy - not
  necessarily large, but stated, so a report can say what n attempts
  supports rather than imply more.
- **Level 1 -> `qualified`**: the above, plus enough repeats under a
  justified sampling plan to support whatever claim is made, and every
  attempt's mandatory criteria (task AND installation-readiness, once
  #150-D lands and a live run exists to exercise it) `SATISFIED`.
- **Level 2/3**: #13's one task each is a start, not yet a family - the
  same widening Level 1 itself needs, PLUS a pilot distribution (real
  attempts) once a family exists, exactly the two-step shape Level 1
  needs above.
- **Level 4/5**: #14's one case each, same two-step shape as #13's, with
  its own committed known-gap (the self-declared provenance log) to close
  before any attempt against it could count toward a mandatory criterion
  the way this method requires.
- **Level 6**: no task exists yet in any issue; #15's acceptance item
  1 ("introduce unfamiliar repositories and legitimate ambiguity... with
  public acceptance and scripted interactions") describes what such a
  family would need to declare, but nothing here proposes one.

## 5. What this document does not do

No threshold, breadth number, repeat count, or qualification claim is
proposed for any level, including Level 1. No badge, blocking statistical
gate, or public leaderboard is introduced (#15 acceptance item 5). This is
rationale and limits, published before any of those exist - the ordering
#15 itself asks for.
