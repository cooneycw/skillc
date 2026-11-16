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
and it copies no round's rules, so a round changes in one place
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
| 0 usage | `usage report <log>`, per discovered log | `OBSERVED`; `UNKNOWN` when there is no log or one is unreadable (round 1 already reads missing usage as UNKNOWN columns) | never |
| 1 charter | no `CHARTER.md`: `charter draft`; with one: `contracts <collection>`, this skill's `CONTRACT` line | `PASS`: contract GOOD and owner-approved | `STOP` draft ready for owner confirmation; `STOP` an intent or authority clause not approved; `FAIL` contract BAD; `UNKNOWN` nothing to draft from, or `contracts` says its hand-off rules did NOT run (a neighbour failed contract-shape, so this contract's hand-offs are unchecked); `NOT BUILT` |
| 1 overlap | `charter overlap <collection>` | always: `EXAMINED`, `NOT EXAMINED` (no comparator), `NOT BUILT`; none is a pass | never |
| 2 inspect | `inspect <collection> --json`, filtered to this skill | `PASS`: no error and no UNKNOWN on this skill | `FAIL` an error finding on this skill; `UNKNOWN` an unreadable issue state, an unexamined rule, nothing inspected, or an `--exclude` that drops this skill |
| 3 trials | not built | never | always: `NOT BUILT` (or `NOT RUN` once the command exists: part 1 never runs paid trials) |

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
unreadable one is recorded as `unreadable` and reads UNKNOWN). Round 1's are the
skill text, its charter, the collection's files (`contracts` checks that every
declared test path exists), the aliases, the logs, and whether `charter`
exists. Round 2's are the skill text, the collection's files, the issue-state
file and the passed-through options. So editing `SKILL.md` re-runs rounds 1 and
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
Kyle stages the copy into its session image. There the host locator may not
resolve, so the launcher reads `SKILLC_CHECKOUT` FIRST: an absolute path to a
skillc checkout that Kyle provides with its environment. A relative path, a
missing directory, or one that fails #765's exact-module check reads
cannot-find (exit 2, no verdict). The Kyle side is owned by kyle-cli-helper. The skill calls its own launcher, `scripts/gauntlet.sh`,
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
