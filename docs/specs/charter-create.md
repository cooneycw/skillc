# Composing a charter: `charter evidence` (#778)

`charter draft` (#726) drafts a charter from what a skill's text says and what
usage records show. For a new skill, or one whose intent was written somewhere
else, that gives a draft that only echoes the skill text, with every clause
`unknown` and untested. #778 composes a charter WITH the owner instead, from
the owner's intent. It has two engine steps, plus a dialogue skill:

1. **`skillc charter evidence`** (this part, PR A) gathers every existing
   piece of evidence and writes it as cited suggestions.
2. **`skillc charter create`** (PR B) turns the owner's answers into a
   CHARTER.md, with a trap-task stub for every clause.
3. **`/charter-create`** (PR B) holds the dialogue. It never answers for the
   owner.

The owner's requirement (#778, 2026-11-15): the composition starts from every
piece of existing evidence, never from a blank page. Open questions are asked
only where no evidence exists.

## `skillc charter evidence`

```
skillc charter evidence <collection> <skill> --out FILE
    [--ref REF]... [--repo OWNER/NAME] [--search]
    [--doc PATH]... [--usage LOG-OR-DIR]... [--alias NAME]...
```

`<skill>` is resolved as `skillc gauntlet run` resolves it: a directory holding
`SKILL.md`, or a command `.md` file, relative to the collection. The file at
`--out` must not exist; the command never overwrites. It exits 0 when the file
is written, and 2 on a usage error. **No model is called.**

### The sources, in order

| Source | What is read | Kind |
|---|---|---|
| `repository evidence` | each `--ref`: a discussion with its comments and replies, an issue with its comments, or a PR with its comments, review bodies and inline review-thread comments; with `--search`, also what a search of the repository for the skill's name finds | observational |
| `existing charter` | the skill's `CHARTER.md`; every `CHARTER.draft.md` (beside it, where `skillc gauntlet run` keeps it before a charter exists, `<main checkout>/.skillc/gauntlet/<slug>/`, and any `--draft`); every clause, including one with only an `id` and a `test`; plus each file's git history | stated |
| `skill text` | the SKILL.md description and its MUST/ALWAYS/NEVER sentences (the `charter draft` rules), and each `--doc` | stated |
| `usage records` | the `stop_reason` tokens the skill's #719 records carry, each cited by `<log>:<line>` (up to 5 lines, then a count) | observed |
| `existing tests` | test files in the collection (`test_*.py`, `*_test.py`, `*.test.*`, `*.bats`) that name the skill, offered as a clause's test before a new trap task is stubbed | test |

A REF is `[discussion:|issue:|pr:][owner/name]#N`. A bare number names the
`--repo` repository; without `--repo`, that is the collection's `origin`
remote when it is on GitHub. Explicit refs are read first. **The name search is
off by default**, because a search for a common word matches noisily.

### Only charter-shaped items are taken from GitHub

A discussion, issue or PR is prose, and prose is not a charter. The extractor
takes only the items under a **charter-shaped label**. The label is a heading
(`## Must never`) or a bold label: a bold span alone on its line
(`**Must never**`), or one followed by a colon and text (`**Job:** text`,
`**Job**: text`). Bold words opening a sentence (`**Never** assume ...`) are
emphasis, not a label. The label must be one of:

| Label | Section |
|---|---|
| Job, Intent | intent |
| Purpose | purpose |
| Must always, Always | always |
| Must never, Never | never |
| Authority | authority |

These rules decide what counts as an item:

- Each list item under a label is one suggestion. A wrapped item joins its
  indented continuation lines.
- Text on the label's own line is itself an item: `**Job:** take any skill ...`.
- Under Job, Intent and Purpose, the first paragraph is the item. Later
  paragraphs are not.
- Any other heading or bold label ends the section, and so does a paragraph
  after the section's list.
- Fenced code is skipped, using `charter draft`'s CommonMark rule (#749). A
  `## Must never` inside a code block is an example, never a duty.
- HTML comments are skipped too, across lines: a commented-out label is not
  evidence.
- A bold label inside a bullet (`- **Must always:** 2-4 outcomes.`) is NOT a
  label. Discussion #718's body uses that shape to describe charters, and it
  yields nothing.

Every item from GitHub is **observational** (#718's fixed rules). It shows
what someone wrote, never that the skill behaves that way.

### Every suggestion

```json
{"id": "e3", "section": "never", "text": "Edit a skill, merge a change, or change a charter without the owner.",
 "cite": "https://github.com/cooneycw/skillc/discussions/718#discussioncomment-19618555",
 "kind": "observational", "source": "repository evidence"}
```

- `text` is a quote of at most 39 words (`charter.MAX_QUOTE_WORDS`). A longer
  item is cut and marked ` ...`, so the copied-passage detector stays clean.
- `cite` is the comment's URL, or `<file>:<line>`, or `<charter file>: <clause id>`.
- `test` is an existing charter clause's own `test` path(s), when it names any;
  otherwise empty.
- `section` is a charter section. Two more values exist: `observed` (a usage
  token the owner must place) and `test` (an existing test, which has no section).
- `id`s run `e1, e2, ...` in gathering order. `charter create` (PR B) refuses a
  suggestion that has no answer, accept, edit or drop.

### Every source reports a status

Each source gets at least one row. The command asserts this before it writes.

| Status | Means |
|---|---|
| `examined` | read, and at least one suggestion came from it |
| `none found` | read in full, and nothing in it is charter-shaped (or a search matched nothing, or no test names the skill) |
| `not examined: <reason>` | not read, or not read in full: no `gh` on PATH, a GitHub error (including a partial answer, data beside an error), an unparseable charter, no `--usage` given, no `--ref` and no `--search`, a test directory or file that could not be read, or a test file too large to read |

A source that could not be read is never left out. So a file with no
repository suggestions always says why: either nothing was there
(`none found`) or nothing was read (`not examined`). A thread longer than one
read fetches (100 comments, 50 replies each) is `TRUNCATED` in its detail, and
so is a search with more than one page (20) of matches. A search reports its
own row: how many matches, and how many were not already named by `--ref`.

The evidence file:

```json
{"schema": 1, "skill": "<skill, relative to the collection>", "skill_file": "<its SKILL.md or command file>",
 "sources": [{"source": "...", "status": "...", "detail": "...", "ref": "..."}],
 "suggestions": [ ... ]}
```

The command also prints one `SOURCE <source> [<ref>]: <status> - <detail>` line
per row.

### GitHub is read-only, and that is asserted

`skillc/repo_reader.py` is skillc's only GitHub access. `GhReader` runs exactly
one shape: `gh api graphql -f query=<a query>`, followed by `-f`/`-F`
variables. `assert_read_only` refuses anything else before a process starts:
- a mutation or a subscription;
- a second `query` field;
- a REST path;
- `gh issue comment`;
- any other flag.

A number names one of a discussion, an issue or a PR, so a bare ref asks for a
discussion first. When GitHub answers `NOT_FOUND`, it asks for an issue or PR.
Any other GitHub error, output that is not JSON, or a missing `gh` is a failed
read, reported as `not examined`.

## What is not examined

- **Prose intent.** An intent written as plain paragraphs, with no
  charter-shaped label, is not extracted. The source then reads `none found`,
  and the dialogue asks the owner an open question.
- **Live GitHub in CI.** `GhReader` is tested through a recording runner and
  argv checks. The frozen copy of #718's "Charter v1" comment
  (`tests/fixtures/charter-evidence/`) stands in for the live read.
- **Earlier charter versions' clauses.** The git history lists the versions;
  only the current file's clauses are offered.
- **Failures that stop one source, never the run.** An unreadable or undecodable
  SKILL.md reads `skill text: not examined`, and git missing from PATH reads the
  gauntlet's draft location as `not examined`. The other sources still run.
- **Meaning.** Nothing is compared by meaning, and no model is called. Two
  suggestions that say the same thing in different words are both offered.

## `skillc charter create`

```
skillc charter create <collection> <skill> --evidence FILE --answers FILE [--replace-draft]
```

Turns the owner's answers into a CHARTER.md, with a trap-task stub per clause.
It exits 0 when the charter is written and clean, 1 when it refuses, and 2 on a
usage error. **It never answers for the owner. It never runs git and never
commits:** in a collection that lives in another repository (CPP), it writes the
charter and its stubs there, and committing them is the owner's act. It never
changes the skill. The skill's tree digest, every file but `CHARTER.md` and
`GAUNTLET.json`, is checked before and after.

### The answers file (schema 1)

The `/charter-create` dialogue writes it from the owner's words:

```json
{
  "schema": 1,
  "approved_on": "2026-11-15",
  "answers": {"e1": "edit", "e2": "accept", "e3": "drop"},
  "intent": {"what": "...", "from": ["e1"], "approve": true},
  "purpose": "...",
  "clauses": [
    {"section": "always", "id": "cite-every-claim", "what": "...", "from": ["e2"], "test": "tests/test_demo.py"},
    {"section": "never", "id": "never-approve", "what": "...", "shortcut": "the tempting wrong move",
     "good": "the rule-following move"},
    {"section": "authority", "id": "owner-merges", "what": "...", "shortcut": "...", "approve": true}
  ]
}
```

- `answers` holds one answer per suggestion in the evidence file: `accept`,
  `edit` or `drop`.
- `from` names the suggestions a field came from.
- `section` is one of `always`, `never`, `provides`, `requires`, `authority`
  or `failure`.
- `id` is a lowercase slug. The clause id is `<contract>.<id>`; the default
  `<section>-<n>` is used when none is given.
- `contract` is optional and defaults to the skill's name.
- `purpose` may be text, or `{"what": ..., "from": [...]}`.

### Refusals: nothing is written

| Refused when | Why |
|---|---|
| a suggestion has no answer, or an answer names no suggestion | every piece of evidence gets the owner's decision |
| an accepted or edited suggestion is in no `from`, or a dropped one is | an accepted line must land somewhere, and a dropped one nowhere |
| a `never` or `authority` clause has no `shortcut` | every safety line needs a trap: the shortcut becomes its bad case |
| `approve` outside intent and authority; an approval without `approved_on`; `approved_on` with nothing approved; an impossible or future date | only the owner approves, and only intent and authority (the `charter confirm` allowlist) |
| a clause with no text, an unknown section, or a repeated id | the charter would not parse, or would be ambiguous |
| a `test` that is not an existing path in the collection | an offered test must exist |
| the evidence file is for another skill, or not schema 1 | the answers must match the evidence they answer |
| the CHARTER.md exists | never overwritten, unless every clause in it is a `draft` and `--replace-draft` is given |
| a stub directory exists | never overwritten |
| any output's path from the collection root holds a symlink, or resolves outside the collection | never written through a link (a symlinked `charters/` or `evals/` would redirect it) |

### The trap-task stubs

Every `never` and `authority` clause gets a stub, and so does any other clause
that names no existing test. The stubs live at:

```
<collection>/evals/trap-tasks/<contract>/<clause-id-slug>/
  bad/   STUB.md  goal.md  fixture/README.md   # the shortcut is the WRONG move
  good/  STUB.md  goal.md  fixture/README.md   # the skill's rule is followed
```

The clause's `test` is `evals/trap-tasks/<contract>/<slug>/{bad,good}`. Where
the owner offered an existing test for a safety clause, the stub path is added
after it. `clause-backed` and `negative-backed` therefore pass from creation.

**A stub is not a graded task.** It has no `grader.json`, so
`verify.GraderDef.load` refuses it, and a round-3 declaration that names it
refuses too. A stub backs a clause by existence only, and `STUB.md` says so.

**#736 PR 2 fills a stub** into the task shape `gauntlet_trials.read_task`
reads:
1. write the agent's real task in `goal.md` and its inputs in `fixture/`;
2. add `grader.json`, `probe.py`, `judge.py` and `inputs.json`;
3. delete `STUB.md`.

### The final check

After writing, `create` runs the real contracts rules over the collection and
reads every finding on this charter:
- **any error rolls back everything create wrote**, including a replaced
  draft, which is restored;
- `approval-present` may warn **only** on an intent or authority clause whose
  approval the owner withheld. A warning on a clause the owner approved also
  rolls back.
- a NEW error on another contract rolls back too: replacing a draft can break
  a neighbour's hand-off, which `handoff-bilateral` reports against the
  neighbour. Findings that were there before create ran are not counted.
- **not examined is never clean:** create refuses when the rules did not read
  the composed charter, or when the collection's cross-contract rules cannot
  run (another CHARTER.md fails contract-shape, a name or provider repeats, a
  directory is unreadable). Fix the collection first.

A skill at the collection root (`<skill>` is `.`) holds its own stubs; the
skill's digest leaves out the stub directories create writes.

The warnings it keeps are printed as such.

## The `/charter-create` skill

`.claude/skills/charter-create/` holds the dialogue (SKILL.md, pinned at 600
words) and its launcher, `scripts/charter.sh`. The launcher runs only
`charter evidence` or `charter create`, and only from the skillc checkout it
belongs to.
- **Install:** not installed under `~/.claude/skills` (wave rule, 2026-11-15);
  the copy-mode installer (#774) may add it later.
- **First real subject:** `/skill-gauntlet`'s own charter, composed with the
  owner, starting from discussion #718's Charter v1.
