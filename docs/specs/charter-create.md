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
| `repository evidence` | each `--ref` (a discussion, issue or PR, with every comment and reply); with `--search`, also what a search of the repository for the skill's name finds | observational |
| `existing charter` | the skill's `CHARTER.md` and any `CHARTER.draft.md`, every clause, plus the charter file's git history | stated |
| `skill text` | the SKILL.md description and its MUST/ALWAYS/NEVER sentences (the `charter draft` rules), and each `--doc` | stated |
| `usage records` | the `stop_reason` tokens the skill's #719 records carry | observed |
| `existing tests` | test files in the collection (`test_*.py`, `*_test.py`, `*.test.*`, `*.bats`) that name the skill, offered as a clause's test before a new trap task is stubbed | test |

A REF is `[discussion:|issue:|pr:][owner/name]#N`. A bare number names the
`--repo` repository; without `--repo`, that is the collection's `origin`
remote when it is on GitHub. Explicit refs are read first. **The name search is
off by default**, because a search for a common word matches noisily.

### Only charter-shaped items are taken from GitHub

A discussion, issue or PR is prose, and prose is not a charter. The extractor
takes only the items under a **charter-shaped label**. The label is a heading
(`## Must never`) or a bold label on a line of its own (`**Must never**`,
`**Job:** text`), and it must be one of:

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
- `section` is a charter section. Two more values exist: `observed` (a usage
  token the owner must place) and `test` (an existing test, which has no section).
- `id`s run `e1, e2, ...` in gathering order. `charter create` (PR B) refuses a
  suggestion that has no answer, accept, edit or drop.

### Every source reports a status

Each source gets at least one row. The command asserts this before it writes.

| Status | Means |
|---|---|
| `examined` | read, and at least one suggestion came from it |
| `none found` | read in full, and nothing in it is charter-shaped (or no test names the skill) |
| `not examined: <reason>` | not read: no `gh` on PATH, a GitHub error, an unparseable charter, no `--usage` given, no `--ref` and no `--search` |

A source that could not be read is never left out. So a file with no
repository suggestions always says why: either nothing was there
(`none found`) or nothing was read (`not examined`). A thread longer than one
read fetches (100 comments, 50 replies each) is `TRUNCATED` in its detail.

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
- **Meaning.** Nothing is compared by meaning, and no model is called. Two
  suggestions that say the same thing in different words are both offered.
