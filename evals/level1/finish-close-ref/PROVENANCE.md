# Provenance: finish-close-ref (skillc #150, acceptance item 1)

Built for [#150](https://github.com/cooneycw/skillc/issues/150), which needs
"one Level-1 task whose fixture and grader make ONE specific CPP skill or
instruction necessary to pass". This task is that: whether a produced commit
message avoids GitHub's issue-closing keyword trap depends on knowing a rule
that `codex/skills/flow-finish` (and its neighbours) states and general
GitHub/git competence does not.

## The rule, and where it lives

**GitHub's issue-closing matcher is not grammar-aware.** A literal keyword
(`close`/`closes`/`closed`/`fix`/`fixes`/`fixed`/`resolve`/`resolves`/
`resolved`), an optional colon, then an issue reference, closes that issue on
merge to the default branch - even when the surrounding prose negates it.
"This does not close #42" closes #42. Confirmed against GitHub's own docs,
["Linking a pull request to an issue using a keyword"](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue),
fetched 2026-09-28: the same page states the reference forms `#ISSUE-NUMBER`
(same repo) and `OWNER/REPOSITORY#ISSUE-NUMBER` (cross-repo), and that the
keyword may carry a colon or be uppercase. It does **not** document a `GH-N`
shorthand or a full-URL closing form; this task's grader does not model either.

**claude-power-pack's own merge guard is the pinned CPP instance of this
rule.** At `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b`,
`scripts/gh-pr-merge.sh`'s `guard_negated_close_keywords` (~line 986) and
`guard_incidental_close_keywords` (~line 1155) both refuse a squash whose
title, body, or any commit subject carries a keyword-plus-`#N` match,
regardless of negation or incidental adjacency - because GitHub's matcher does
not care either. `keyword_re='(?i)\b(?:close(?:s|d)?|fix(?:es|ed)?|resolve(?:s|d)?)\b:?\s*#[[:digit:]]+'`
is narrower than the documented grammar (bare `#N` only, no `OWNER/REPO#N`);
`grade_ref.py`'s `KEYWORD_RE` extends it with the cross-repo form so the
"closes cooneycw/x#42" candidate below grades correctly. That gap is recorded
as a supplemental finding on claude-power-pack's Nit Store
(cooneycw/claude-power-pack#864), not fixed here - out of scope for #150.

**The materialized skill teaches the consequence, not the mechanism.**
`codex/skills/flow-finish/reference.md` (~lines 307-337, "Closing must agree
with that judgement" / "Wording an unresolved report"): default to the
non-closing `Refs #N` (or "part of #N"); never print a closing keyword beside
an issue number "even to illustrate what to remove", because the merge helper
"rejects negated and incidental forms too... it cannot tell an example from an
instruction." An agent that reads this and nothing else still has to notice
that a careful disclaimer like "does not close #42" is itself the trap - the
skill only tells it that such phrasing is unsafe, not to fabricate.

## The rule is NOT confined to one skill file

Before writing the mutation statement for #150-B, the whole pinned collection
was grepped for the rule (positive control: the same grep, run now, finding
the passage known to be there):

```
grep -rn "negated\|does not close #\|closing keyword" --include="*.md" codex/skills .claude/skills
```

At `85e9b03a` this rule's prose appears in three CODEX skills (the surface
`evals/subjects/cpp-codex` installs; `.claude/skills`, the
`cpp-claude-code` surface, has zero hits):

| File | What it carries |
|---|---|
| `codex/skills/flow-finish/reference.md:307-337` | the rule this task's `goal.md` points at by name |
| `codex/skills/flow-merge/reference.md:125-180` | the same rule, restated for the merge step |
| `codex/skills/flow-auto/reference.md:867-1511` | the same rule again, restated for the end-to-end flow |
| `codex/skills/flow-merge/scripts/gh-pr-merge.sh` | the actual `guard_negated_close_keywords` / `guard_incidental_close_keywords` regex and comments |
| `codex/skills/flow-auto/scripts/gh-pr-merge.sh` | byte-identical copy of the same script |

`codex/skills/flow-finish` bundles no `gh-pr-merge.sh` of its own. Because the
cpp-codex subject's selection is `"all"` (every one of the 74 skills is
listed and discoverable), a degraded arm that mutates only
`flow-finish/reference.md` leaves the rule reachable through `flow-merge` or
`flow-auto`. **A real degraded arm must remove every row in the table above**,
mutating or deleting the stated passage/regex in all five locations, or the
case does not discriminate. This list, with line ranges, was handed to the
session building #150-B and to the orchestrator.

## Selection is held fixed on purpose

`goal.md` directs the agent to the rule **by skill name** - "follow the
project's `flow-finish` skill's rules for how a commit references an issue" -
rather than restating the rule's content, so the task measures whether CPP's
instructions decide the outcome once read, not whether the agent selects the
right skill to read in the first place. Skill selection/discovery on the
agent-trial path is a separate, already-tracked question (#26's selection
probe measured codex opening no installed skill even when one plainly
applied); this task does not re-measure it and both arms (#150-A's normal
subject, #150-B's degraded one) get byte-identical `goal.md` text.

## Corrections made to the initial task sketch

The orchestrator's go-ahead proposed certifying against
a `GH-42` reference form. Checked against GitHub's docs (above) and CPP's own
guard (neither recognizes it): `GH-42` is not documented closing syntax, so it
was dropped from the candidate population rather than added as a FAIL case -
grading it as a violation would itself be wrong, not conservative.

## Fixture

`fixture/src/TODO.md` is authored for this task (not a pinned upstream blob):
four acceptance items for a fictional issue #42, two checked, two open. It
carries no `commit_message.txt` - the agent writes that file itself, so the
starting state (nothing written) is the honest "unfixed" candidate, not a
fabricated wrong file.
