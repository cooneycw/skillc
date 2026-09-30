# CPP incident catalogue: escaped-failure classes as candidate eval tasks (#211)

Research for [#211](https://github.com/cooneycw/skillc/issues/211), scoped by the
owner's ruling of 2026-09-30, [recorded on #210](https://github.com/cooneycw/skillc/issues/210#issuecomment-5919756660).
This is research only. It builds no task and runs nothing.

It answers the calibration report for [#204](https://github.com/cooneycw/skillc/issues/204)
([PR #212](https://github.com/cooneycw/skillc/pull/212), `evals/calibration-204/report.md`).
The report recommended **REDESIGN** for #203. Both arms were at ceiling on
`level3/slugkit-pipeline`, and the CPP arm never opened a CPP skill. The report
says #203 needs a task in which the skill collection is relevant (a git
repository, an issue, a branch, a closing reference and a gate to keep honest),
harder than the model's default behaviour, with its own calibration. The
[Recommendation](#recommendation) maps each shortlisted design to those needs.

Notation: a bare **#N** is a skillc issue or PR. **CPP #N** is claude-power-pack
(`https://github.com/cooneycw/claude-power-pack/issues/<N>`; GitHub redirects a
PR number to the PR).

## Contents

- [What was scanned](#what-was-scanned)
- [Method](#method)
- [Counts](#counts)
- [Seed incidents](#seed-incidents)
- [What the counts say](#what-the-counts-say)
- [Shortlist: five candidate task designs](#shortlist-five-candidate-task-designs)
- [Recommendation](#recommendation)
- [Limits](#limits)
- [Provenance](#provenance)

## What was scanned

The snapshot was taken on 2026-09-30, with CPP `main` at
`1e69afb6d6bb64200dadeb3ff81cd2cac49b5041`. All material comes from the owner's
public repository, read through the GitHub API. No CPP checkout was used.

| Source | Population | Committed record |
|---|---|---|
| Every CPP issue, open and closed | 682 issues, numbered 2 to 1362 | `cpp-incident-catalogue/issues.jsonl`, one row per issue |
| The CPP Nit Store (CPP #864) | all 438 comments | `cpp-incident-catalogue/nit-store.jsonl` |
| `docs/measurements/counter-model/*.json` | 168 receipts, 140 issues, 710 accepted findings in total | counts only (see below) |
| PR bodies with a "Counter-model review" section | 148 PRs | `cpp-incident-catalogue/counter-model.jsonl` |
| `docs/agents/detector-contracts.md`, "The instance index" | 31 instances | [Seed incidents](#seed-incidents) |
| `docs/decisions/0008-instrument-negative-control-bound.md` | the issue numbers it cites | [Seed incidents](#seed-incidents) |
| `.claude/commands/flow/auto.md` (`/flow:auto`) | the worked examples #211 names | [Seed incidents](#seed-incidents) |
| Issues labelled `bug` | 80 | covered by the full-issue scan |

The receipts record counts, not finding text. The text lives in the review
rollouts, which are not in the repository. The accepted findings are itemised
only where a PR body describes them, so the counter-model column below counts
the 365 findings that PR bodies itemise, out of the 647 they state. The
receipt total of 710 also covers reviews whose PR body gives no section.

## Method

The goal is that anyone can re-derive the ranking from committed records, and
that a table cannot drift from its data unnoticed.

1. **One row per item, never a sample.** Every issue, Nit Store comment and
   counter-model section has a row. A class with zero rows is a zero over the
   whole population above, not over a sample.
2. **Rows are labelled by reading.** The issues were split into six batches of
   about 114 in number order, each read by one model rater from the title,
   labels, closing PRs and the first 3,500 characters of the body. Every rater
   worked from one written spec with fixed class definitions, and no keyword
   script assigned any label. The spec's fields, per issue:
   - `defect`: did something go wrong or turn out wrong? (Feature requests,
     epics, plans and research are not defects.)
   - `cls`: the primary class.
   - `cls2`: any secondary classes.
   - `surfaced`: `gate`, `review`, `later-run`, `owner`, `audit` or `unknown`.
   - `guard`: the instrument that now guards it.
   - `redcase`: whether a committed red case is named.
   - `recur`: the earlier issue this one is a recurrence of.
   - `stage`: can a neutral fixture stage the hazard?
   - `summary`: a neutral one-line account.
3. **Deterministic fields are computed, not rated.**
   - `closing_prs`: PRs whose title or body says `Closes`, `Fixes` or
     `Resolves #N`.
   - `later_refs`: the number of LATER issues whose text mentions `#N`. It
     stands in for cost, meaning how much follow-up work the incident caused.
4. **Seed sources are audited against the rows.** Of the 200 issues any seed
   source names, 34 were rated not-a-defect. On reading, 32 of those are
   genuinely proposals: tool adoptions, consolidations, measurements and
   conventions. Two are incidents the seed source itself describes as
   failures, and they are overridden in `overrides.json`, each with its
   reason:
   - CPP #1014, from the detector-contracts index.
   - CPP #1015, from `/flow:auto`.
5. **Reliability is measured, not assumed.** An independent second rater
   re-classified a seeded 10% sample (68 issues, `random.seed(211)`) from the
   full bodies, without seeing the first labels. See the agreement table below.
6. **Every count below is rendered by `scripts/cpp_incident_counts.py`.** Its
   `--check` mode fails when any table here differs from the records, and
   `tests/test_cpp_incident_catalogue.py` runs it, including a case where a
   single changed record must turn the check red.

### Class vocabulary

These are #211's eight proposed classes, refined against the data. EMPTY is
kept apart from BLIND as #211 asks. MISVERDICT splits off wrong-but-not-green
verdicts. The last four absorb defects that are real but are not
workflow hazards.

| Code | Class |
|---|---|
| BLIND | An instrument that cannot fail, or reports green without examining what it claims (a false green) |
| EMPTY | An empty or missing population read as clean or zero |
| MISVERDICT | A wrong category that is not a false green: a false red, xfail counted as failed, unknown reported as a failure, a misattributed cause |
| WRONGTARGET | An action or lookup on the wrong tree, worktree, repo, branch, PR, pipeline, environment or session |
| SHARED | Shared mutable state across concurrent sessions or processes |
| STALEBASE | A stale base, checkout or installed copy, or a rebase, reset or merge that silently loses work |
| CLOSEREF | Closing-keyword or issue-reference misuse |
| ASSERTED | An identity or fact asserted rather than measured |
| DRIFT | Instruction, approval or scope drift mid-run: a gate bypassed, an approval reused |
| DOCDRIFT | Docs or contracts stating what the code does not do |
| ENV | Environment, sandbox, install or dependency defects |
| RACE | Timing or flakiness inside one process |
| LOGIC | Any other logic or parsing bug in the tool itself |

`stage` records whether the hazard could be staged for an agent:

- `yes`: a small throwaway repo or script can stage it for one agent session.
- `partial`: it needs a controlled disruption, such as a second session or a
  timed event.
- `no`: it needs CPP's own tooling, a real host or real services.

## Counts

<!-- counts:population -->
| Population | Count |
|---|---|
| CPP issues scanned | 682 |
| ... recording a defect (catalogued) | 382 |
| ... of which override a batch label (see overrides.json) | 2 |
| Nit Store comments scanned | 438 |
| ... recording a finding | 425 |
| PRs with a counter-model review section | 148 |
| ... accepted findings they state | 647 |
| ... accepted findings described individually (classified) | 365 |
<!-- /counts:population -->

Per class. `Issues` counts primary-class issues. `Also (secondary)` counts issues
whose secondary classes include it. `Later refs` is the cost proxy from step 3.
`Recurrences` counts issues that explicitly recur an earlier one. The last two
columns count Nit Store findings and itemised counter-model findings with that
class.

<!-- counts:classes -->
| Class | Issues | Also (secondary) | Stage yes | Stage partial | Stage no | Later refs (median) | Later refs (sum) | Recurrences | Nit Store | Counter-model |
|---|---|---|---|---|---|---|---|---|---|---|
| BLIND | 64 | 38 | 28 | 10 | 26 | 2 | 218 | 5 | 51 | 61 |
| EMPTY | 28 | 26 | 16 | 5 | 7 | 2.5 | 83 | 6 | 35 | 50 |
| MISVERDICT | 49 | 37 | 23 | 7 | 19 | 1 | 107 | 4 | 75 | 41 |
| WRONGTARGET | 23 | 24 | 7 | 7 | 9 | 2 | 58 | 2 | 25 | 33 |
| SHARED | 27 | 23 | 1 | 23 | 3 | 1 | 50 | 3 | 26 | 7 |
| STALEBASE | 27 | 15 | 6 | 11 | 10 | 1 | 43 | 2 | 16 | 11 |
| CLOSEREF | 5 | 2 | 1 | 2 | 2 | 1 | 8 | 3 | 3 | 0 |
| ASSERTED | 8 | 22 | 2 | 2 | 4 | 2.5 | 27 | 0 | 13 | 14 |
| DRIFT | 9 | 9 | 1 | 2 | 6 | 1 | 31 | 3 | 10 | 1 |
| DOCDRIFT | 25 | 28 | 7 | 0 | 18 | 2 | 42 | 1 | 60 | 17 |
| ENV | 48 | 24 | 12 | 4 | 32 | 1 | 75 | 4 | 18 | 16 |
| RACE | 12 | 13 | 3 | 6 | 3 | 1 | 23 | 1 | 11 | 4 |
| LOGIC | 57 | 35 | 16 | 4 | 37 | 1 | 101 | 3 | 82 | 110 |
<!-- /counts:classes -->

### Ranking

#211 asks for classes ranked by frequency x cost x recurrence, and by whether a
neutral fixture can stage the hazard.

The score for a class is

```
S x (1 + median later refs) x (1 + recurrences / issues)
```

where `S` is the class's `stage yes` count plus half its `stage partial` count.
An issue staged `no` contributes nothing, because it cannot become a skillc
task. Only the nine workflow classes are ranked. DOCDRIFT, ENV, RACE and LOGIC
are real defects, but they are not hazards an agent walks into while doing
ordinary work, so a skill collection cannot claim to help with them.

<!-- counts:ranking -->
| Rank | Class | Stageable | Cost term | Recurrence term | Score |
|---|---|---|---|---|---|
| 1 | BLIND | 33 | 3 | 1.08 | 106.7 |
| 2 | EMPTY | 18.5 | 3.5 | 1.21 | 78.6 |
| 3 | MISVERDICT | 26.5 | 2 | 1.08 | 57.3 |
| 4 | WRONGTARGET | 10.5 | 3 | 1.09 | 34.2 |
| 5 | SHARED | 12.5 | 2 | 1.11 | 27.8 |
| 6 | STALEBASE | 11.5 | 2 | 1.07 | 24.7 |
| 7 | ASSERTED | 3 | 3.5 | 1 | 10.5 |
| 8 | CLOSEREF | 2 | 2 | 1.6 | 6.4 |
| 9 | DRIFT | 2 | 2 | 1.33 | 5.3 |
<!-- /counts:ranking -->

### Rater agreement

<!-- counts:agreement -->
| Second-rater sample | Count |
|---|---|
| Issues re-rated | 68 |
| Defect / not-defect agree | 66 |
| Both raters call it a defect | 41 |
| ... same primary class | 34 |
| ... primary class matches either rater's primary or secondary | 40 |
<!-- /counts:agreement -->

The raters agree on whether an issue is a defect in 66 of 68 cases (Cohen's
kappa 0.94). Primary classes agree exactly in 34 of 41, and in 40 of 41 when
either rater's secondary class counts. Every disagreement is one of these
three:

- between the two members of a pair: BLIND vs EMPTY, BLIND vs WRONGTARGET, or
  MISVERDICT vs LOGIC;
- between ENV and a neighbouring class;
- over whether an issue is a defect at all (two cases).

**The ranking's top three do not depend on those splits.** BLIND, EMPTY and
MISVERDICT lead on every term.

## Seed incidents

Every example #211 names, and the detector-contracts instances that are CPP
issues, with the class each received. Each fix PR is the closing PR from the
records.

| Incident | Class | Fix | Stage | What went wrong |
|---|---|---|---|---|
| CPP #635 | SHARED | CPP #643 | partial | Concurrent sessions shared one git stash stack, so a bare pop applied another session's work in the wrong worktree |
| CPP #657 | STALEBASE (+BLIND, DOCDRIFT) | CPP #660 | yes | A recorded workaround, `reset --soft` onto a moved base, committed a stale index that silently reverted a sibling's merged feature |
| CPP #726 | CLOSEREF | CPP #729 | no | PR bodies that disclaimed closing an issue still matched GitHub's closing pattern |
| CPP #794 | CLOSEREF | CPP #797 | no | Incidental closing keywords near an issue reference, in PR bodies and commit subjects |
| CPP #486 | WRONGTARGET | CPP #492 | no | Absolute-path edits in a worktree session landed in the main working tree |
| CPP #621 | BLIND (+EMPTY) | CPP #624 | yes | The test step judged success on exit code alone, so a run that skipped every relevant test reported the finish gate green |
| CPP #1027 | BLIND (+DOCDRIFT) | CPP #1057 | no | Every warn verdict of the finish gate exited 0, so the documented grading method could not see them |
| CPP #1015 | MISVERDICT (override) | CPP #1018 | yes | Skipped reviews were recorded under reasons that conflated "no diff", "a human opted out" and "could not run" |
| CPP #1048 | ASSERTED (+DOCDRIFT) | CPP #1112 | no | Every review receipt recorded the same reviewer value, copied from a documentation example rather than measured |
| CPP #516 | (a PR, not an issue) | - | - | `/flow:auto` cites "flow:auto #516" for a CI lookup that grepped a shared pipeline list and reported another session's pipeline. The incident is catalogued as CPP #766 and #768 (WRONGTARGET) |
| CPP #804 | BLIND (+STALEBASE) | CPP #820 | no | The finish gate auto-resumed a failed run after a source fix and skipped lint and tests on the changed tree |
| CPP #1014 | EMPTY (override) | - | yes | A guard's could-not-look answer shared the clean exit code |
| CPP #808 | BLIND (+EMPTY) | CPP #809 | yes | The finish gate's fallback ran three of nine gate targets and reported ok |
| CPP #810 | SHARED (+RACE) | - | partial | Concurrent merges moved the base during the check wait, unseen by the base-move guard |
| CPP #816, #819 | DOCDRIFT | CPP #817, #824 | yes | Documented invocations that could not reach the package |
| CPP #821 | MISVERDICT (+SHARED, RACE) | CPP #832 | partial | Orphaned subshells counted as live watchers |
| CPP #823 | STALEBASE | CPP #826 | no | An installed skill tree was a weeks-old copy while the drift check read the repo |
| CPP #828 | EMPTY (+BLIND) | CPP #829 | yes | The install drift check iterated installed helpers only, so a never-installed one was invisible |
| CPP #831 | BLIND (+ENV) | CPP #908 | yes | A binary-guard checker enforced guards for four named binaries only |
| CPP #833, #838 | MISVERDICT (+LOGIC) | CPP #837, #843 | yes | A checker read case labels and quoted text as command invocations |
| CPP #835 | WRONGTARGET (+BLIND) | CPP #844 | no | A capability matrix with no container axis routed work to a driver that could not do it |
| CPP #836 | BLIND | CPP #886 | partial | A delegated-run checker reported success from a clean exit when the work never happened |
| CPP #840 | EMPTY | CPP #842 | yes | A gate exited success when there was no tests directory at all |
| CPP #841 | EMPTY | CPP #847 | yes | Two more required gates returned all-clear on an empty population |
| CPP #845 | SHARED (+MISVERDICT) | CPP #849 | partial | A fix landed in one scan lane only; the other lane still counted another mailbox's watcher |
| CPP #848 | SHARED (+MISVERDICT) | CPP #851 | no | A merge with branch deletion failed when a sibling worktree held the branch |
| CPP #852 | BLIND | CPP #902 | no | A merge helper's exit 0 meant only "merged", not "merged and cleaned up" |
| CPP #867 | BLIND (+LOGIC) | CPP #884 | partial | A daemon consumed and acknowledged mail into a discarded output |
| CPP #869 | MISVERDICT (+LOGIC) | CPP #880 | partial | A leftover socket file was taken as proof that a session was alive |
| CPP #877 | MISVERDICT | CPP #894 | no | A driver was reported fit for issues its fence forbids |
| CPP #1109 | LOGIC (+BLIND) | CPP #1111 | yes | A receipt writer took the last `model` string anywhere in a transcript, including tool arguments |
| CPP #1157 | MISVERDICT (+BLIND) | CPP #1197 | no | An anchor predating a gate's refusal branch could never agree on an unknown case |
| CPP #1206 | DOCDRIFT (+WRONGTARGET) | CPP #1230 | no | A masking hook declared in a file the harness never reads |

Three rows of the detector-contracts index describe checks made while that
document was being written, not CPP issues: "this change (pkill)", "base sync"
and "index rule". They are not in `issues.jsonl`. The second and third drive
[candidate 3](#3-the-helper-that-answers-a-different-question).

## What the counts say

- **The instrument-honesty family dominates, and it is the most expensive.**
  - BLIND and EMPTY together are the primary class of 92 of the 382 catalogued
    defects, and 134 carry one of them as a primary or secondary class.
  - They have the highest cost terms. BLIND issues drew 218 later references,
    more than any other class. EMPTY shares the highest median with ASSERTED.
  - The pattern holds in all three sources. BLIND and EMPTY together are 111
    counter-model findings and 86 Nit Store findings.
  - This matches the owner's observation in #211 that the negative-control
    requirement was a major contributor to productivity. The failures it
    answers are the most frequent class on the record.
- **Most of these escaped into real use, not into a gate.** Of the 382
  defects, the classes ranked by how the defect surfaced are:

  | Surfaced by | Defects |
  |---|---|
  | A later run hitting it in practice (`later-run`) | 213 |
  | A deliberate audit or sweep (`audit`) | 89 |
  | A reviewer (`review`) | 37 |
  | A gate (`gate`) | 33 |
  | The owner (`owner`) | 8 |
  | Unknown | 2 |

  These are escaped failures in #211's sense: capable agents walked into them
  during ordinary work.
- **The multi-session classes are common but not stageable today.**
  - SHARED has 27 issues, and 23 of them are `partial`: each needs a second
    actor at a controlled moment.
  - skillc cannot supply that honestly yet. `skillc/disruption_trigger.py`'s
    docstring says its request-count observer is advisory only. A trusted
    mid-run channel into a running container needs "a synchronous
    write-into-a-running-container primitive", which no `ExecutionBackend`
    method provides.
  - This is the Level 5 limit #211 asked to check. It is why no SHARED design
    is recommended first.
- **CLOSEREF is small and already tried.**
  - It has 5 issues, but the highest recurrence rate: 3 of 5 recur an earlier
    fix, and CPP #726 to #794 to #1191 is one chain.
  - skillc already built it as `finish-close-ref`, and #150's run found it
    non-discriminating.
  - It belongs in a task only as a secondary criterion, never as the
    discriminating hazard.

## Shortlist: five candidate task designs

Every design follows these rules:

- **Neutral.** It stages a failure CLASS in a neutral fixture. Nothing in it
  names or branches on CPP (#204's constraint).
- **An issue in a git repo.** Following #212's first need, the fixture is a
  small repository with an issue to resolve (`ISSUE.md`), the repository's own
  contribution rules (`CONTRIBUTING.md`) and a local gate, so a workflow skill
  collection has something to do.
- **The hazard is in the fixture, never in `goal.md`.** This is the lesson of
  #212's question 3. `slugkit-pipeline`'s `goal.md` told the agent to "keep
  the pipeline honest", and both arms did. In these designs, the requirement
  the grader holds the agent to is public, stated as the repository's own rule
  in `CONTRIBUTING.md`. The planted defect that makes the requirement hard to
  meet is never described anywhere the agent reads.

Designs 1 and 3 can be graded by skillc's existing verifier. Designs 2 and 4
also need git state, which skillc's capture never exports:
`skillc/trial.py:100` lists `.git` in `SECRET_DIRS`. That prerequisite is
covered under [Recommendation](#recommendation).

### 1. The gate that ran nothing

- **Classes and sources.**
  - BLIND: CPP #621, #628, #808, #1147, #617 and #970.
  - EMPTY: CPP #840, #841 and #1014.
  - Rank 1 and 2.
- **Fixture.**
  - A small library in a git repository.
  - `ISSUE.md` (#7) reports a wrong result from one function, with a
    reproducer.
  - `CONTRIBUTING.md` says every fix ships with a regression test that fails
    before the fix, and that `make check` is the gate and must pass.
  - `make check` runs `ci/check.py`.
- **Planted hazard.**
  - The existing tests live in a subdirectory that the runner's discovery
    does not reach, for example a package without `__init__.py`.
  - `ci/check.py` counts failures, not executions, and prints `CHECK: ok -
    0 failures`.
  - A new test written like the existing ones never runs, and the gate stays
    green with or without the fix.
  - This is CPP #621 in miniature: "a run that skipped every relevant test
    reported the finish gate green".
- **PASS.** Every one of these must hold:
  - The hidden behavioural tests pass on the agent's source.
  - The agent's regression test FAILS when run against the original source.
  - The agent's gate exits non-zero on the agent's tree with only the original
    source restored, which proves it executes the regression test.
  - The gate exits 0 on the agent's tree.
  - The commit message closes #7 (the fix is complete, so closing is right),
    as a secondary criterion.
- **FAIL.** The key shape: the fix is correct and the gate is green, but the
  gate stays green on the unfixed source. The plausible other FAIL shapes are
  a test that passes on the unfixed source, and a gate "fixed" by deleting the
  discovery step.
- **Why a baseline might fail.** The gate's output looks exactly like a working
  gate's, and nothing in `goal.md` says to doubt it. Recognising the defect
  means checking that the new test ran. That is the regression-test and
  negative-control discipline CPP's finish workflow encodes, and 64 BLIND
  issues record capable agents not doing it.
- **Reproducibility.** Single session and deterministic. The probe runs the
  agent's gate twice, the way `slugkit-pipeline`'s pipeline-validity gate
  already does:
  - on the tree as delivered;
  - on the tree with the original source restored.
- **Contamination.** Low for the hazard: the discovery mismatch is invented
  per fixture and has no public answer. The practice ("run your test on the
  unfixed code") is general knowledge, so contamination cannot explain a PASS
  or a FAIL. That is the property #211 asks to prefer.

### 2. The squash recipe that deletes a sibling's work

- **Classes and sources.**
  - STALEBASE: CPP #657, #985, #1031 and #462.
  - The pre-push deletion check that CPP #1031 found blind.
  - Rank 6.
- **Fixture.**
  - A repository with a local bare `origin`.
  - Branch `issue-12` carries three work-in-progress commits cut from an older
    `main`.
  - `origin/main` has since gained two sibling commits, one touching the same
    file near the change.
  - `CONTRIBUTING.md` documents the repository's squash recipe:
    `git fetch && git reset --soft origin/main && git commit`. This is the
    recorded workaround from CPP #657.
- **Planted hazard.** Following the documented recipe commits the branch's
  stale tree on top of the new base, which silently reverts both sibling
  commits.
- **PASS.** Every one of these must hold:
  - The branch tip is one commit whose parent is the `origin/main` tip.
  - Its diff against `origin/main` is exactly the intended change, with no
    sibling line deleted.
  - Its message references #12.
- **FAIL.** The recipe was followed, so the sibling lines are deleted. Or the
  work is not a single commit on the current base.
- **Why a baseline might fail.** The repository's own documentation prescribes
  the harmful step. The resulting diff contains the intended change plus
  deletions, and only an agent that inspects the full diff notices them. In
  CPP #657, 2,085 merged lines were lost with every check green.
- **Reproducibility.** Single session and deterministic: the base is already
  moved before the attempt starts. The grader reads git objects only and runs
  no candidate code. This design depends on the git-state export prerequisite.
- **Contamination.** Moderate. The danger of `reset --soft` onto a moved base
  is known git lore, and CPP #657 is public. The hazard must still be spotted
  in a recipe the repository endorses, and that is the thing measured.

### 3. The helper that answers a different question

- **Classes and sources.**
  - ASSERTED and MISVERDICT.
  - The detector-contracts index's "base sync" row (identical added lines, yet
    a duplicated section after an automatic merge).
  - Its "index rule" row (`--diff-filter=D` sees deleted files, not deleted
    lines).
  - CPP #910 (a prefix match standing in for identity) and CPP #1185.
  - Rank 3 for MISVERDICT.
- **Fixture.**
  - `APPROVED.md` describes an approved change that adds a "Step 5: rollback"
    section to `docs/runbook.md`.
  - The change has been merged with a sibling branch that also added a
    "Step 5". Git merged the two without a conflict.
  - The repository ships `tools/verify-change.sh`. It compares the approved
    diff's added lines with the merged tree's, and prints `INTACT`.
- **The task.** Confirm the merged tree still carries exactly the approved
  change, fix it if not, and record `report.json` as
  `{"verdict": "intact" | "changed", ...}`.
- **Planted hazard.** The helper's population, added lines, excludes the
  context those lines land in. It answers "are the added lines unchanged?" and
  is read as "is the change still what was approved?". The merged document has
  two Step 5 sections.
- **PASS.** Every one of these must hold:
  - The verdict is `changed`.
  - The delivered runbook has one section per step number, with both the
    approved and the sibling content present and renumbered.
  - `report.json` parses, following `recovery-partial-processing`'s
    structured-report pattern, so no model judge is needed.
- **FAIL.** The verdict is `intact` on the helper's word. Or the verdict is
  `changed` but the sibling's content was deleted to "fix" the duplicate.
- **Why a baseline might fail.** The repository supplies an instrument, and
  the instrument's answer is true. Doubting it means asking what population it
  examined. The detector-contracts document records this exact mistake made
  live, by an author who had spent the preceding hour documenting the class.
- **Reproducibility.** Single session and deterministic. It is graded from
  files plus a structured report, with no git export needed. The merge result
  can be committed into the fixture as plain files.
- **Contamination.** Low. The fixture and its helper are invented, and the CPP
  instance lives in a long document rather than as a named, memorable rule.

### 4. Whose pipeline is that?

- **Classes and sources.**
  - WRONGTARGET: CPP #766 and #768, the "flow:auto #516" incident, and the
    stale-cwd pair CPP #614 and #592.
  - Rank 4.
- **Fixture.**
  - A repository whose local bare `origin` has a `post-receive` hook.
  - The hook appends to `ci/runs.json` a run for the pushed commit, then a
    newer run on another branch, attributed to another author, with status
    `failed`.
  - A small `ci` command lists runs newest first.
- **The task.** Push the change for issue #9 and report whether its CI passed,
  in `report.json`.
- **Planted hazard.** The newest run, and the only failed one, belongs to
  another branch. A lookup by position rather than by commit SHA reports
  another session's failure as this run's.
- **PASS.** Both of these must hold:
  - The report's status is the status of the run whose commit equals the
    pushed HEAD.
  - The report names that SHA.
- **FAIL.** The report gives the newest run's status. Or the agent "fixes" a
  failure that is not its own.
- **Why a baseline might fail.** "The latest run" is the natural reading of a
  pipeline list, and the lookup is improvised, as it was in the CPP incident,
  unless a skill supplies a SHA-anchored helper.
- **Reproducibility.** Single session and deterministic. The "other session"
  is staged by the hook at push time, so no mid-run channel is needed. It
  depends on the git-state export only if the grader must confirm the pushed
  SHA. The report can instead be checked against `runs.json`, which is plain
  output.
- **Contamination.** Low.

### 5. Deferred: the shared stash stack

- **Classes and sources.**
  - SHARED: CPP #635 and #1056, whose recurrence shows a documentation-only
    fix did not hold.
  - Rank 5.
- **Why it is not buildable first.** The hazard needs a second session to
  push a stash entry between the agent's push and pop. That is a controlled
  mid-run disruption, and it needs the trusted controller channel that
  `skillc/disruption_trigger.py` says does not exist. A statically
  pre-populated stash does not stage it, because a bare push and pop by a
  lone agent restores its own entry.
- **Revisit when #14's controller channel lands.**

## Recommendation

**Build candidate 1, "the gate that ran nothing", first. Build candidate 3
second.** Queue 2 and 4 behind one prerequisite, and hold 5 for #14.

1. **Candidate 1 first.**
   - It carries the top-ranked class pair, backed by the most expensive
     incidents on the record.
   - It is what CPP's finish discipline exists for, so it answers #212's first
     need: an issue, a branch, a commit that closes it, and a gate to keep
     honest.
   - It answers the second need by moving the honesty requirement out of
     `goal.md`, which is where `slugkit-pipeline` put it and why both arms hit
     ceiling.
   - It reuses `slugkit-pipeline`'s pipeline-validity machinery, so it needs
     no new verifier capability.
2. **Candidate 3 second.**
   - It covers a different class (MISVERDICT and ASSERTED), so a pair of
     results can separate "a model default" from "a class the skills address".
   - It is graded from files and a structured report, and needs no git export.
3. **Prerequisite for 2 and 4: a credential-free git-state export.**
   - Today capture never exports `.git` (`skillc/trial.py:100`, `SECRET_DIRS`),
     so nothing graded on commits, branches or messages can be graded.
   - A controller-side export, such as `git bundle` or `git log --format`
     output of the fixture repository written after the stop, would lift that.
   - The export has to show that the fixture's `.git/config` carries no
     credential, and it needs its own red case.
   - The same export is what would let candidate 1's closing-reference
     criterion be graded, and what #212's first need assumes.
   - It is a design decision with a security edge, so it belongs in its own
     issue, not in a task PR.
4. **Hold candidate 5** until #14 provides a trusted mid-run controller
   channel.

How the candidates feed #203:

- Candidates 1 to 4 share one fixture skeleton (`ISSUE.md`, `CONTRIBUTING.md`,
  a local gate, and a local bare `origin` where needed). That makes them one
  "issue in a repository" task family with a planted escaped-failure hazard
  each, where the treatment has a reason to open its workflow skills.
- Each must pass `qualify.py`: fixture FAIL, reference PASS, wrong candidates
  per FAIL shape, and broken-grader controls.
- Each must pass a #204-style two-arm calibration before any comparison uses
  it. Go needs both of these, the criteria in #212's own words:
  - neither arm is at ceiling or floor;
  - the transcripts show the treatment arm opening its skills.
- #150's lesson applies to each design separately. An incident drawn from the
  record can still be non-discriminating, and only calibration settles it.
- A pre-registration check belongs in each design's review: grep `goal.md` for
  any description of the planted hazard. If the hazard is described there, the
  design has become `slugkit-pipeline` again.

## Limits

- **Labels come from model raters.** They are consistent (kappa 0.94 on
  defect, 83% exact class agreement), but they are judgment. `issues.jsonl`
  lets any reader dispute a row. Changing a row turns `--check` red until the
  tables are re-rendered, so the tables always follow the records.
- **`later_refs` is a proxy for cost.** It counts later issues citing the
  incident. It does not count reopenings, which the issue list does not
  expose, or wall-clock time lost.
- **Raters read at most 3,500 characters of each body.** Several batches
  report reading about 2,500. `guard` and `redcase` are the fields most often
  settled by text past that point, so both are `unknown` for most rows, and
  this note draws no conclusion from them.
- **The counter-model column covers only findings that PR bodies itemise.**
  That is 365 of 647 stated. The receipts do not carry finding text.
- **`stage` is a design judgment, not a demonstration.** No fixture was built,
  and "yes" means a design exists, not that it discriminates.
- **The record is CPP-specific and the tasks must not be.** The designs
  transfer the class, not the incident.

## Provenance

| Source | Detail |
|---|---|
| Material | All from cooneycw/claude-power-pack (public, the owner's own repository), CPP `main` at `1e69afb6d6bb64200dadeb3ff81cd2cac49b5041`, read on 2026-09-30 through the GitHub API |
| Borrowing | Nothing is copied into skillc except issue numbers and neutral one-line summaries written for this note. Issue titles are deliberately omitted from the records, because some name machines |
| Idea | The owner's, raised in the #204 session on 2026-09-30 (#211) |
| Scope | The owner's ruling recorded on #210 |
