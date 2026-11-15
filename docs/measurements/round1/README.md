# Round 1 proof drafts: CPP `/flow:eli5` and `/flow:auto` (#726, part A)

**Draft ready for owner confirmation.** Nothing here is approved. These are
`skillc charter draft` outputs for the two claude-power-pack commands that hand
off to each other (#720's worked example). They use the owner's layout for a
slash command's charter (2026-11-15, claude-power-pack#1838): the file sits at
`charters/<ns>/<cmd>/CHARTER.md` and its `subject:` names the command file. They
can drop into CPP unchanged once #1838 lands and the owner confirms them.
**Nothing was written into CPP.**

## How they were made

- **Subject collection:** claude-power-pack at
  `3ed254698f3e32fb99adf203c955308531729a75`, with both command files clean at
  that commit.
- **Source:** the command documents `.claude/commands/flow/eli5.md` and
  `.claude/commands/flow/auto.md`, never the generated `codex/skills/` mirror.
- **Usage records:** none. CPP has no `.skillc/usage.jsonl` (the #719 hook is not
  installed there), so every stated duty reads `unknown`. Under the round-1 rule,
  no log is not evidence of non-use.
- **Repository evidence:** missing. #718 build step 4 is not built yet.
- **Model calls:** none (#726 gate: product model calls are sized, not run).

```bash
skillc charter draft <cpp>/.claude/commands/flow/eli5.md --subject .claude/commands/flow/eli5.md \
  --usage <cpp>/.skillc --out charters/flow/eli5/CHARTER.md
skillc charter draft <cpp>/.claude/commands/flow/auto.md --subject .claude/commands/flow/auto.md \
  --usage <cpp>/.skillc --out charters/flow/auto/CHARTER.md
```

## What `skillc contracts` says about them, in CPP's layout

With the two command files copied beside `charters/`, as they will sit in CPP:

- **`contract-shape`:** clean for both. The format and the `subject:` are valid.
- **`approval-present`:** warns twice. Nothing is approved.
- **`clause-backed`:** 20 errors, 10 for each charter, because no clause names a
  test. This is expected for a draft; round 3 writes the tests.

Run in this repository, where the command files are absent, both drafts fail
`contract-shape` with `subject ... does not exist`. That is correct: a charter
about a file the collection lacks certifies nothing.

## What the owner decides

1. **Each clause.** The drafts quote MUST/ALWAYS/NEVER sentences, each cut to 40
   words with a `file:line` cite. The extraction is crude: it includes a few
   descriptive sentences that merely contain "always" or "never", and it misses
   duties stated in plain prose. The owner confirms in a grilling-style dialogue
   that yields an answers file, and `skillc charter confirm` applies it
   (`docs/specs/charter-round1.md`).
2. **Where CPP's CHARTER.md goes.** This is decided: `charters/flow/{eli5,auto}/`
   in CPP, per claude-power-pack#1838. It is restated here because these files
   assume it.
3. **Whether model drafting replaces this.** Sized, not run: 2 skills x 3
   replicates = 6 calls at 8,000-15,000 input tokens each
   (`cost_estimate.size_round1`). It waits for the gauntlet budget (#747, #718
   decision 4).
