# `skillc gauntlet run`: the skill-gauntlet engine, part 1 (#754)

One entry point for the skill-gauntlet (discussion #718): run it on one skill,
then do what its `NEXT:` line says. Part 1 covers the free rounds, 0 to 2.
Rounds 3 to 5 are not built yet (#736, #737), so every run stops by round 3 and
none gives a keep, trim or retire verdict.

```bash
skillc gauntlet run <collection> <skill> [--usage PATH]... [--alias NAME]...
    [--offline] [--issue-states FILE] [--repo OWNER/NAME]
    [--include GLOB]... [--exclude GLOB]... [--map FROM=TO]... [--draft-dir DIR]
```

`<skill>` is a skill directory holding `SKILL.md`, or a command `.md` file under a
`commands/` directory, relative to the collection.

## It orchestrates only

The engine runs each round's own command as a subprocess
(`python -P -m skillc.cli <command>`; `-P` keeps the collection off `sys.path`,
so a collection holding its own `skillc/` package is read, never executed). It reads that command's exit code, its
verdict lines or its report JSON, and nothing else. It imports no round module,
except three pure parser names for the plain report (below), and it copies no
round's rules, so a round changes in one place
(cooneycw/claude-power-pack#1830 Part 7). `tests/test_gauntlet.py` holds both
to it: an AST check of the engine's imports, and a `skillc inspect` check that
the skill text shares no passage with the round specs.

A command this skillc does not have reads `NOT BUILT`. This is how rounds 3 to 5
read today, and how round 1 reads until `skillc charter` (#726) lands.

## Rounds

Each round reached prints one `ROUND` line. The run continues or stops. A run
prints exactly one `NEXT:` line and a final `GAUNTLET:` line saying "no trials
ran; this is not a keep/trim/retire verdict".

| Round | Command | Continues on | Stops on |
|---|---|---|---|
| 0 usage | `usage report <log>`, per discovered log | `OBSERVED` only when the logs record THIS skill (its names: directory, frontmatter `name`, command name, `--alias`, as `charter draft` matches them); `UNKNOWN` when there is no log, one is unreadable, its report has no per-skill block this engine reads, or no log records the skill (#760) | never |
| 1 charter | no `CHARTER.md`: `charter draft`; with one: `contracts <collection>`, this skill's `CONTRACT` line | `PASS`: contract GOOD and owner-approved | `STOP` draft ready for owner confirmation; `STOP` an intent or authority clause not approved; `FAIL` contract BAD; `UNKNOWN` nothing to draft from, or `contracts` says its hand-off rules did NOT run (a neighbour failed contract-shape, so this contract's hand-offs are unchecked); `NOT BUILT` |
| 1 overlap | `charter overlap <collection>` | always: `EXAMINED`, `NOT EXAMINED` (no comparator), `NOT BUILT`; none is a pass | never |
| 2 inspect | `inspect <collection> --json`, filtered to this skill | `PASS`: no error and no UNKNOWN on this skill | `FAIL` an error finding on this skill; `UNKNOWN` an unreadable issue state, an unexamined rule, nothing inspected, or an `--exclude` that drops this skill |
| 3 trials | not built | never | always: `NOT BUILT` (or `NOT RUN` once the command exists: part 1 never runs paid trials) |

Round 5, the verdict (#737), is reached by `skillc gauntlet verdict`, which reads
this record plus round 3/4 reports ([gauntlet-verdict.md](gauntlet-verdict.md)).
`run` does not call it yet: it stops at round 3, and the wiring goes with #736 PR 3.
A ruling recorded by `gauntlet rule` (`rounds.5`) is carried across `run`s, never
re-derived.

Round 2 runs `inspect` on the whole collection, never on this skill alone:
`copied-passage` needs at least two subjects, so a one-skill run would always
read as not examined. The skill's own path is added as an `--include`, so a
passed-through surface that misses it cannot yield a zero that only means "not
looked at". With an `--exclude`, inspect itself is asked (a one-subject probe
using inspect's own matcher) whether the skill survives it; if not, round 2
reads UNKNOWN. A symlinked `SKILL.md` is refused at the start (exit 2), because
inspect skips symlinked files. Both `findings` and the skill's classified rule
statements (`rule_lines`) are shown and counted. Its findings for this skill are then listed by group. A D
item is a stale rule the owner may move or delete; the run trims nothing.

Round 1 never confirms or writes a charter (#718: "never changes a charter
without the owner"). With no `CHARTER.md`, it writes a draft into the draft
location below and names it in `NEXT:`.

## The plain report (#783)

Owner, 2026-11-15: "Output is engine-speak." So `gauntlet run` prints a
plain-English report FIRST, then the machine lines below, unchanged:

- a first line, **Where it stands**: one sentence on the skill's position;
- for each round reached: **Checked** (what the round looks at, in owner terms),
  **Found** (the result, with counts and names), **Means** (what it implies for
  a verdict) and **Do next** (one action naming a command or file; a round that
  passed says "nothing for this round");
- a closing line: no trials ran, and the machine lines follow.

All of its wording lives in `skillc/gauntlet_report.py`, in one table keyed by
(round, reason). Every non-pass round carries a `reason` code and `facts`
(counts and names). Both are kept beside the finding lines in the host-local
display cache, so a cached round reports the same. Neither is ever in
`GAUNTLET.json` or a cache key. The report shows no internal rule id
(`clause-backed` reads "a promise names no test that exists"). A reason with no
entry shows the round's own detail and points at its ROUND line, never another
reason's advice. Do next names `/charter-create` (#778) only when this skillc
has `charter create`; otherwise it names the draft-and-confirm path, with a note.

To read the charter's promise counts, the engine takes exactly three pure parser
names from round modules: `contracts.load`, `contracts.expand` and
`charter.skill_names` (orchestrator ruling). `tests/test_gauntlet.py` refuses
any other.

`--plain-only` prints only the report and `--machine-only` only the machine
lines. One golden per fixture stop pins each part
(`tests/fixtures/gauntlet-report/`). The machine goldens were captured before
#783 and must never need rewriting.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | a complete keep/trim/retire run. Unreachable in part 1 |
| 1 | a round failed: a contract BAD, or an error finding on this skill |
| 2 | usage: no such collection or skill, a usage path that does not exist, or no place for the draft |
| 3 | stopped at an owner point, `UNKNOWN` or `NOT BUILT` |

## The record: `GAUNTLET.json`

The owner ruled (2026-11-15, on #754) that the record is committed beside the
skill's `CHARTER.md`: beside `SKILL.md` for a native skill, or at
`charters/<ns>/<cmd>/GAUNTLET.json` for a command.

- **Before a confirmed charter exists**, the draft (`CHARTER.draft.md`) and the
  record go to `<collection main checkout>/.skillc/gauntlet/<skill>/`. A linked
  worktree resolves to its main checkout, and `.skillc/` ignores itself.
  `--draft-dir` overrides this; a collection outside git needs it. Nothing lands
  beside the skill until a charter does.
- **The engine writes the record and never stages, commits or pushes it.**
  Committing it is the owner's act. That is the one file the gauntlet writes into
  a skill's repository, and it writes it only on change.
- **It is deterministic.** It has sorted keys and no wall-clock time, and it is
  rewritten only when its bytes would change. An unchanged re-run leaves it
  byte-identical.
- **It is safe to publish.** It holds digests and verdicts only: each round's
  name, verdict, one-line detail, whether the run continued, and the sha256 of
  each input (the passed-through options too, so an absolute `--map` path is
  hashed, never copied). It holds no usage row or count, no session id, no host
  path and no host name.
- **It is never written through a link.** A symlinked or non-regular record
  path is refused (exit 2), and the write replaces the path itself (temp file,
  then rename), so it cannot land in the file a link points at. A symlinked
  component of the draft location (`.skillc`, `gauntlet`, the skill's directory)
  is refused too, as is a `--draft-dir` that is a symlink or holds one, and any
  symlinked component between the collection root and the skill or its charter
  (#759). Each state file is written through a temp file created exclusively,
  then renamed over the path, as #733 writes its reports.

  The default draft location, the main checkout's `.skillc/`, can sit outside
  the collection directory (a nested collection, or a linked worktree). That is
  the approved design (orchestrator ruling on #759): it is where the usage log
  lives, it is ignored by git, and nothing lands beside the skill before a
  charter exists.

**Resume.** A round whose recorded input digests equal the current ones is not
re-run; its line reads `(cached)`. Round 0's inputs are the usage logs (an
unreadable one is recorded as `unreadable` and reads UNKNOWN) and the aliases.
Round 1's are the skill text, its charter, the collection's files (`contracts`
checks that every declared test path exists), every declared test path by
content wherever it lives (under `.skillc/` or `.venv/` too; a missing one reads
`absent`), the aliases, the logs, and whether `charter` exists. Round 2's are
the skill text, the collection's files, a digest of the raw `origin` URL (inspect
infers its repository from it), the files inspect could add from the skipped
directories (include-glob matches under `.venv`, `node_modules`, `.skillc`,
`__pycache__`; names listed, only matches hashed), the issue-state file and the
passed-through options (#760).

- **The origin is keyed raw, not parsed** (orchestrator ruling): a cosmetic URL
  change, such as `.git` added, re-runs round 2. Round 2 is free, so
  over-invalidating is the safe direction, and no copy of inspect's parser is
  kept here.
- **The skipped-directory walk has a cap** (`SKIPPED_WALK_CAP`, 20,000 entries).
  Past it round 2 reads UNKNOWN and says why, rather than scanning on. So editing `SKILL.md` re-runs rounds 1 and
2 and leaves round 0 cached. A cached "draft ready" whose draft has been deleted
is drafted again.

Every round's inputs also carry the skillc implementation's digest (its
package source, rounds and engine alike), so an upgraded skillc re-runs every
round. The collection digest covers directories and symlink targets as well as
file contents.

Two things are never served from cache. Round 2 reading **live** issue states
(no `--issue-states`, no `--offline`) re-runs every time, because an issue that
closes changes no file. And the finding lines a cached round shows come from a
LOCAL display cache beside the draft (`.skillc/gauntlet/<skill>/display.json`,
ignored), never from the published record; on a host without it, a cached
round 2 says its lines are not here.

## Usage logs

A skill's usage is recorded in the repository where it ran (#719), which is
usually not its own collection. The engine reads:

- the collection main checkout's own `.skillc/usage.jsonl`, when it exists;
- every `--usage` file, and every `usage.jsonl` under a `--usage` directory.

It never opens a log. It hands the paths to `usage report` and
`charter draft --usage`, and the record keeps only each log's sha256, numbered
in digest order. The log stays local (#718 decision 2).

## From any session (#763, #774)

`make install-skill` writes a REAL COPY of the main checkout's
`.claude/skills/skill-gauntlet` to `~/.claude/skills/skill-gauntlet`
(`scripts/install_skill.py`), never a link: Kyle's deploy stages that directory
and refuses symlinks (#774). The copy carries a locator, `.skillc-checkout`
(the main checkout, `~/`-relative under $HOME) and a marker, `.skillc-install`
(kind, schema, digest).

**Kyle containers** (owner, 2026-11-16: "make it work in Kyle containers"):
Kyle stages the copy into its session image, in private containers only. The
contract:

- **The checkout:** pinned and READ-ONLY at `/opt/kyle/session-tooling/skillc`,
  named by `SKILLC_CHECKOUT`. The launcher reads it FIRST, before the locator
  (which may not resolve in a container). It must be an absolute path to a
  directory holding a skillc checkout; anything else reads cannot-find (exit 2,
  no verdict).
- **The runtime:** `$SKILLC_RUNTIME` if set (an ABSOLUTE path, else
  cannot-find), otherwise `<checkout>/.venv`, where Kyle stages its frozen
  runtime. The caller's `UV_PROJECT_ENVIRONMENT` is ignored and never passed on:
  uv applies it to every project, so a session-wide value names the worker's
  project, never this checkout. Kyle sets ONLY `SKILLC_CHECKOUT` session-wide.
  The runtime must import the CHECKOUT's own `skillc/gauntlet.py` and
  `skillc/cli.py` (an editable or path install): #765's exact-module check
  refuses a non-editable wheel, by design.
- **No writes in the checkout:** the launcher sets `PYTHONDONTWRITEBYTECODE=1`,
  and the engine writes only into the collection it reviews (the record beside
  the charter, the draft dir under the collection's `.skillc/`).
- **The Kyle side** (staging the checkout and runtime) is owned by Kyle's master. The skill calls its own launcher, `scripts/gauntlet.sh`,
which finds skillc through the locator when there is one, and otherwise
through its own real path (the repository's copy). It then checks that the checkout's environment (`.venv`, or
`UV_PROJECT_ENVIRONMENT` resolved against the checkout, as uv resolves it)
imports THIS checkout's gauntlet engine, and runs it directly:
`<env>/bin/python -P -m skillc.cli gauntlet run`. It drops a caller's
`PYTHONPATH`, never uses a `skillc` from PATH, and needs no `uv` at run time, so
it works from any working directory. No path is committed; every path is
derived at run time.

Two failure cases, ruled on #763:

- **The checkout moved or was deleted.** The locator names a missing
  checkout, so the launcher prints the cannot-find line, exit 2, with no ROUND
  line. (`test_a_wrong_or_missing_locator_gives_cannot_find_and_no_verdict`.)
- **The copy is stale** (a `git pull` since the install): one
  `SKILL_GAUNTLET: warning: ...` line on stderr; the verdict and exit code are
  the engine's, unchanged. Refresh with `make install-skill`.
- **The checkout is present but skillc cannot run** (no gauntlet engine, no
  synced environment, or an environment that does not import this checkout's
  engine). The launcher prints `SKILL_GAUNTLET: cannot find
  a usable skillc (<reason>)` and exits 2, with no ROUND line.

## Out of scope (part 1)

Rounds 3 to 5 and the keep/trim/retire ruling (#736, #737), GitHub ingestion
(#718 build step 4), and registering `/skill-gauntlet` through CPP. The skill
lives in this repository at `.claude/skills/skill-gauntlet/`.
