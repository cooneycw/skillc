# Skill-gauntlet round 1: drafting and confirming a charter (#726, part A)

Round 1 answers **"what is this skill for?"** Every later round measures a skill
against its charter (#718). This part builds two commands:

- `skillc charter draft <skill>` proposes a `CHARTER.md` from evidence.
- `skillc charter confirm <draft> --answers FILE --out FILE` turns that
  proposal into a charter, **only** from the owner's own answers.

The overlap view (shared, shadowed and orphan duties across a collection) is
part B. Its comparison is by meaning, so it is a model call.

## No model call, by ruling

The orchestrator's gate on #726 holds: skillc's own model calls stay **sized,
not run** until the owner sets the gauntlet budget (#747, #718 decision 4). So
drafting here is deterministic, and crude in two stated ways:

- **A stated duty** is a sentence of the skill's text that contains `MUST`,
  `ALWAYS`, `NEVER` or `MUST NOT`. Fenced code and HTML comments are skipped,
  and wrapped lines are joined back into their sentence. A duty stated in plain
  prose is missed, so the stated column **undercounts**.
- **An observation** is a usage record's `stop_reason` token, the only field of
  #719's schema that says what a run did. The `TokenMatcher` matches a token to
  a stated duty when every word of the token appears in the sentence:
  `approval-gate` matches "You MUST stop at the approval gate". A model matcher
  can replace it behind the `Matcher` protocol.

`size_round1()` in `skillc/cost_estimate.py` counts the model runs round 1 would
make. It never authorizes anything:

| Run | Calls | Input tokens per call |
|---|---|---|
| overlap controls | 2 cases x 3 replicates = 6 | 2,000-4,000 |
| collection overlap (CPP) | ~34 skills x 3 replicates = 102 | 8,000-15,000 |
| proof drafting | 2 skills x 3 replicates = 6 | 8,000-15,000 |
| **total** | **114** | **~0.9-1.6M** |

## The columns

| Column | Means |
|---|---|
| `observed-and-stated` | the text states it, and a usage record shows it |
| `stated-not-observed` | the text states it, and **complete-coverage** records for this skill never show it |
| `unknown` | the text states it, but nothing could have shown it either way |
| `observed-not-stated` | a record shows it, and the text never states it: confirm it, or forbid it |

**`unknown`, never "never observed"**, unless at least one record **for this
skill** was written under `complete` coverage. Every one of these reads `unknown`:

- no usage log;
- an empty log (an empty log is not evidence of non-use; the hook may not be
  installed);
- an unreadable log;
- a log with records only for other skills;
- a log whose only records for this skill are `partial` or `unsupported`
  (Codex).

Coverage limits what an *absence* means, never what a presence means: a
`partial` record that shows a duty still counts as seen. The committed cases are
in `evals/subjects/charter-draft/`, one per trigger, plus the flip case: one
complete record without the token gives `stated-not-observed`.

## The draft

The output is #720's format (`docs/specs/contracts.md`):

- the description, or the opening paragraph if there is no frontmatter, as the
  `intent`;
- up to 4 must-always and 6 must-never candidates as `invariants` clauses.
  Capitalised keywords come first, then document order. Every other candidate
  is listed in the body;
- every clause carries `draft: true`, a `column`, and `evidence` (a `file:line`
  cite, plus what the usage records showed);
- no clause has an `approved` date;
- every quote is cut to 40 words, so `skillc inspect`'s copied-passage rule
  stays quiet on reports that hold drafts.

A draft **passes `contract-shape`**, **warns `approval-present`** (nothing is
approved), and **fails `clause-backed`**: no clause names a test yet, and round 3
writes them. That failure is expected, and `tests/test_charter.py` asserts it so
it is never read as a regression.

For a slash command, pass `--subject .claude/commands/<ns>/<cmd>.md` and place
the draft at `charters/<ns>/<cmd>/CHARTER.md`, the owner's layout (see
`docs/specs/contracts.md`). The command is matched to usage records as
`<ns>:<cmd>`. Use `--alias` for any other name.

| `charter draft` exit | Meaning |
|---|---|
| 0 | drafted |
| 2 | usage: no skill text at that path, or `--out` already exists (it never overwrites) |
| 3 | **nothing to draft from**: no description, no stated duty, and no usage record. An empty charter is never printed |

## Owner confirmation

The owner works through the draft clause by clause in their own session, in the
style of the `grilling` skill: one clause at a time, the evidence shown, and the
owner's words recorded. The result is an answers file:

```text
approved-on: 2026-11-15          # optional; defaults to today (UTC)
flow-eli5.intent: edit: The owner approves a plan only after reading it in plain language.
flow-eli5.always-1: accept
flow-eli5.always-2: drop
flow-eli5.observed-retry-loop: forbid
```

`charter confirm` applies it, and refuses (exit 1, nothing written) when:

- there is **no answers file at all**. It never approves by itself;
- a clause in the draft is unanswered (an answer is never defaulted);
- an answer names a clause the draft does not hold;
- a line cannot be read, a clause is answered twice, or an `edit` has no wording;
- the intent is dropped or forbidden (a contract requires one: edit it);
- `--out` already exists.

`approved: <date>` is stamped **only on `intent` and `authority` clauses**, where
#718 says approval counts. An accepted `invariants` clause loses `draft`, but is
never dated: it is backed by a test, not by an approval. `forbid` moves the duty
to `invariants.never`, worded "Never: ...".

## What this does not do

- It does not hold the dialogue. The owner's session does; this applies the result.
- It does not read repository evidence (GitHub issues and PRs). That is #718
  build step 4, and every draft lists it as a missing source.
- It does not compare duties across skills. That is part B.
- It writes nothing into the skill's own repository. The proof drafts for CPP
  live under `docs/measurements/round1/`.
