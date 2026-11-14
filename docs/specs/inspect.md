# `skillc inspect`: skill-gauntlet round 2 (decay rules and A/B/C/D sorting)

Issue #725, build step 2 of the skill-gauntlet (skillc discussion #718). The
concepts and the four groups come from
[claude-power-pack discussion #1830](https://github.com/cooneycw/claude-power-pack/discussions/1830),
"Graduate rules into checks instead of trimming them".

The organising rule is #1830's:

> prose comes out only when a check already guards against the same mistake,
> and that check has been shown to fail on its known-bad case.

`inspect` is the instrument that applies that rule to a collection. It never
trims anything itself.

## Charter

The charter (#1830 Part 1) that this command is held to. Each line has a test
in `tests/test_inspect.py` or `tests/test_decay.py`.

```md
Job: sort a collection's decay findings into A/B/C/D, or UNSORTED with a reason.
Must always:
  - report what it scanned and what it could not see (every rule's population)
  - give every finding a bucket, or UNSORTED with the reason no bucket applies
  - say UNKNOWN when it could not tell
Must never:
  - edit a skill
  - report UNKNOWN as fine
  - assign C, or B, by guess
  - call an empty collection clean
```

| Charter line | Test | Kind |
|---|---|---|
| never edit a skill | `test_inspect_never_writes_into_the_collection` | negative control |
| never report UNKNOWN as fine | `test_with_no_network_every_marker_is_UNKNOWN_and_the_run_is_not_clean`, `test_gh_missing_is_UNKNOWN_never_OPEN`, `test_a_failing_gh_is_UNKNOWN` | negative control |
| never assign C or B by guess | `test_C_is_never_assigned_and_the_report_says_why`, `test_B_only_for_a_named_check_that_does_not_exist` | negative control |
| never call an empty collection clean | `test_zero_subjects_is_nothing_inspected_never_zero_findings`, `test_a_single_subject_collection_is_incomplete_not_clean` | negative control |
| always report the population | every rule's `population` in `report.json`; `test_placeholders_globs_and_extensionless_names_are_counted_not_fired` | purpose control |
| always give a bucket or a reason | `test_every_finding_has_a_bucket_or_UNSORTED_with_a_reason` | purpose control |
| always find real decay | the CPP run at `d5ef0a66` must re-find #1830 Part 2's twelve closed `until #N` rules and sort them into D ([measurement](../measurements/inspect/2026-11-14-cpp-and-mattpocock.md)) | purpose control |

## The four groups

| Group | #1830's meaning | When `inspect` assigns it |
|---|---|---|
| **A** | Already enforced by a test, gate or helper. The text can go after that check's failing case is run. | The rule statement names an enforcer that exists **and** whose known-bad case exists: a `controls/<id>/` directory with `bad/`, or a file that declares `NEGATIVE-CONTROL: <path>` for a path that exists. |
| **B** | Not enforced, and the mistake has happened again. Becomes a check. | Only when the statement names a check path (under an enforcement root) that does not exist. #1830's B also needs **recurrence**, which is friction and history evidence that round 2 does not read. Every other unenforced statement stays UNSORTED, with that reason. |
| **C** | A current fact the code cannot show. Stays, shortened. | Never mechanically. Only the owner can rule that a fact must stay. |
| **D** | Incident history or a superseded explanation. Moves to a reference doc. | An `until #N` or `expires-with: #N` marker whose issue has closed. |
| **UNSORTED** | | Anything else, always with its reason. |

A zero in the C or B column means **not assigned**, never "none". The report
says so.

A file *inside* a control's `bad/`, `good/` or `targets/` is an input the check
runs on, never the enforcer: naming `controls/x/bad/case/SKILL.md` sorts
UNSORTED, while naming the control itself (`controls/x/`) can sort A (#731).

"A check exists" is not "a check goes red" (#1830 Part 3). An enforcer that is
named but has no red case found is UNSORTED: *enforcer named, but no known-bad
case found - run its failing case before trimming*.

**Rule statements.** Every line that carries emphasis
(`MUST`/`NEVER`/`CRITICAL`/`ALWAYS`/`IMPORTANT`) is treated as a rule statement
and gets a bucket. A statement is sorted on its **paragraph**: the contiguous
non-blank lines around it, at most 12 either side, with a fence line ending it.
CPP rarely names the enforcer on the emphasised line itself. An enforcer in the
*next* paragraph is not borrowed, because that would be a guess
(`test_a_rule_line_does_not_borrow_an_enforcer_from_the_next_paragraph`).

**Pinned by** (#1830 Part 4). Each A or D item lists the test files that name
its document, matched on the path or its last two path components, never a bare
basename. A test that greps a doc's wording holds that wording in place, so the
trim will need a test edit as well. This is an annotation only, never a rule.

**Hard errors stop the sort.** A `dangling-reference` is a bug, not a trim. Any
error-severity finding makes the verdict `STOPPED` (exit 1), and nothing is
trim-ready until it is fixed. The other findings are still listed with their
buckets, so the owner can see them (#725's negative control requires both).

## Verdicts and exit codes

| Verdict | Exit | When |
|---|---|---|
| `NOTHING-INSPECTED` | 2 | The collection has no subject. This is not a clean result. |
| `STOPPED` | 1 | Any hard error (`dangling-reference`). |
| `INCOMPLETE` | 1 | Any UNKNOWN (an issue state that could not be read), or a rule that could not be examined (`copied-passage` on fewer than two subjects). The summary says "NOT clean". |
| `FINDINGS` | 0 (1 with `--strict`) | Warnings only. |
| `CLEAN` | 0 | Every rule examined, no finding, no UNKNOWN. |

An unreadable `--exposure` report, an invalid issue-state file or `--repo` is
refused with exit 2 before anything is inspected.

## Subject surface

A collection is a root plus include globs (default `**/SKILL.md`, which is the
population `skillc check` reads) minus exclude globs. A command file is read as
Markdown. Frontmatter that parses is stripped, and frontmatter that does not
parse is **kept as body text**, never dropped. `skillc check` owns frontmatter
errors.

For claude-power-pack, the source surface is its commands and its Claude-facing
skills. The generated Codex copies under `codex/skills/` are not included,
because they would count every finding twice:

```bash
skillc inspect ~/Projects/claude-power-pack \
  --include '.claude/commands/**/*.md' --include '.claude/skills/*/SKILL.md' \
  --map '~/.claude/scripts/=scripts/' --map '~/.claude/commands/=.claude/commands/' \
  --repo cooneycw/claude-power-pack --out <dir>
```

The decay rules sit in the same registry as every other rule (`skillc rules`,
`skillc selftest`), but they run under `inspect`, not `skillc check`. `check`
stays one SKILL.md at a time and network-free. These rules take no `--target`:
nothing they read depends on which client loads the text.

## The rules: population and blind spots

Each rule ships `controls/<rule-id>/{bad,good}/`. Every case directory is one
collection, declared by its own `collection.json`
(`include`/`exclude`/`map`/`own_prefixes`/`repo`/`issue_states`/`enforcement_roots`)
and loaded **offline**. A good case in which the rule examined nothing (no
reference, no marker, no pair) is refused as not exercised, never counted green
(`decay.not_exercised`). This closes #723's empty-population defect for this
family.

### `dangling-reference` (error) - #1830 Part 2, "a dead rule pointing at a deleted helper"

**Examines.** Three kinds of reference:
- Relative Markdown link targets, resolved from the document's own directory.
- Words in inline code spans and fenced-block lines that start with an
  *own prefix* (default `scripts/`, `references/`, `assets/`). These resolve
  against the document's directory, then the collection root.
- Words that start with a declared `--map FROM=TO` install prefix
  (`~/.claude/scripts/=scripts/`).

A reference is satisfied only by that **exact path**, inside the collection.
A neighbour's name never satisfies it, and neither does `../` out of the root
(the config-drift-checker trap in records.md). A `--flag` written after a
resolved script, in the same span or line, is looked up in the script's
**source text**, plus any sibling file the script names. A wrapper such as
`flow-preflight.sh` that execs `flow-preflight.py "$@"` takes the flags its
target defines.

**How command text is split into words** (#731, a design change). Inline code
spans and fenced-block lines - command-shaped text only, never running prose,
where two apostrophes ("don't ... isn't") would pair up and swallow a reference
- are tokenised with stdlib `shlex` (posix, `punctuation_chars=";&|"`). A
quoted argument stays one word, so `"$(printf x);"` is a value and its `;` no
separator, while an unquoted `;`, `|` or `&&` is a token of its own. A quoted
argument that holds several words is a STRING: each of its paths must still
exist, but none of them is a command or owns a flag. Text whose quotes do not
balance falls back to plain whitespace words, the reading used before shlex.

**Which command a flag belongs to** (#731). A flag belongs to its segment's
COMMAND: the first word after any interpreter or shell keyword (`bash`,
`python3`, `env`, `if`, `elif`, `!`, ...), its options and their values
(`sudo -u root`, `sudo --user root`, `env --unset VAR`; a substitution can
be that value, `sudo -u "$(id -un)"`), and any `VAR=value`. A path seen later
in the segment is an argument - it must exist, but never takes the flags (so
`scripts/helper.sh references/guide.md --verbose` checks `--verbose` against the
helper, not the guide). A separator (`|`, `;`, `&&`) ends the command - after
the word it trails, so `--bad;` is still checked. `$(...)` is a command of its
own, and the outer command resumes when it closes, including when it opens and
closes in one token (`"$(pwd)"`), and a separator after it (`"$(pwd)"; echo
--x`) ends that command too. A flag that follows a path which is NOT the
command (an unknown wrapper: `mystery --opt scripts/x.sh --flag`) has no known
owner: it is never fired on, and it is counted in
`population.flags_after_a_non_command_path` rather than dropped silently. The rule never runs a collection's script: `--help` would
execute repository-controlled code on the host.

**Cannot see, and counts instead of firing** (`population` in the report):
- path-like words under no own prefix or map (`path_like_not_examined`), for
  example a user-project file such as `.claude/cicd.yml`, or an unmapped `~/`
  path;
- paths containing placeholders, globs or variables, such as
  `${CLAUDE_PLUGIN_ROOT}/scripts/x`, `scripts/<name>.sh` or `scripts/*.sh`
  (`placeholder_paths_not_examined`). This is where #1830 Part 2's retired
  `${CLAUDE_PLUGIN_ROOT}` fallbacks fall. They are well formed, and only their
  distribution is retired, so that one is a D fact for the owner;
- prefixed words with no file extension, such as `scripts/foo`, which are as
  often prose examples as references;
- references in prose without backticks, flags assembled at run time, and
  directories referenced without a trailing `/`;
- a script that is not in command position: `a.sh b.sh --x` checks `--x`
  against `a.sh` (shell semantics; approved on #731), a script named inside an
  `echo "..."` string, and a script named mid-sentence in a prose code span
  (`(re-run scripts/x.sh --write later)`) - their flags are not examined.

**Known ambiguity.** In a skill about *the user's* project, `scripts/deploy.sh`
names a file in that project, not in the collection. The rule reports it,
because it cannot tell the two apart. The real-collection measurement shows the
two such hits in CPP's `project-deploy` skill.

### `expired-marker` (warn) - #1830 Part 2, "the rule is still there, the reason isn't"

**Examines.** `until #N`, `until owner/name#N` and `expires-with: #N`, matched
case-insensitively. A bare `#N` belongs to `--repo`, or to the root's `origin`
remote (main checkout or linked worktree). Issue states come from
`--issue-states FILE` (offline and deterministic, used by every control and
test) or from `gh`. With `--offline`, no `gh`, no network, a failed call or an
unknown repository, the marker is **UNKNOWN**, never OPEN, and the run is
INCOMPLETE.

A closed marker fires and sorts into D. Following #1830 Part 2's proposal
("fail on any bare `until #N` that has no marker"), a bare `until` with no
`expires-with` on its line is listed as a **note** (prose-only dependency), not
a finding.

**Cannot see.** A dependency phrased any other way: "once #N lands",
"pending #N", or #1830's own example, "Filed as #640 ... until it lands".
Widening the pattern would turn the rule into guessing.

### `copied-passage` (warn) - #1830 Parts 5 and 7, "summaries are lossy copies"

**Examines.** Runs of at least **40** identical words (whitespace-normalised,
so re-wrapping changes nothing) shared by two different documents. One finding
per pair, giving the number of runs, the longest run, and the total words
shared, as Part 7 measured. It is reported as a drift risk: a rule held in N
places has to be changed in N places.

**N = 40**, against Part 7's measure of 10-word runs: 10 is right for
*measuring* sharing, but as a *finding* floor it fires on shared idioms and
one-line commands. 40 is a paragraph or a pasted block. Exactly 39 does not
fire, and 40 does (`test_a_run_one_word_short_of_the_floor_does_not_fire`).

**How a run is measured** (#731). Matching anchors on windows that are RARE
in the other document (at most 8 occurrences) and extends each match backward
and forward, then accepts the runs longest first - so a repetitive prefix is
recovered whole from the first distinctive word after it, and an early short
match never starves a later longer one, in either document order. Only what no anchor
reached - purely repetitive text - falls back to the first 8 starting points,
forward only. A pair is an **estimate** exactly when a candidate search was
cut while a free alignment beyond the cut existed - whether or not the cut
search then accepted a run - and that finding and the report summary say
**bounded estimate**; `population.estimated_pairs` counts them. No word on either side is counted
in two runs. Memory stays bounded on repetitive text (no occurrence
cross-product).

**Cannot see.** Paraphrase, and meaning-level overlap. Both belong to round 1's
overlap view (#726). It also cannot tell a deliberate, checked copy from a
drifting one. CPP's three driver docs are vendored identically on purpose and
held by `controls/delegated-core-vendor`, and they still report as UNSORTED.
Recognising "this copy is under a vendoring control" as A is a later signal.

### `emphasis-density` (warn only) - #1830's outside evidence

Lydia Hallie (Anthropic): capital-letter emphasis can push the model off
track. And when everything is emphasised, nothing stands out.

**Examines.** Whole, uppercase `MUST`/`NEVER`/`CRITICAL`/`ALWAYS`/`IMPORTANT`
per 100 body lines, with 50 lines as the smallest denominator, so a 10-line
file with three MUSTs does not read as 30.

**Threshold 5.0.** On 2026-11-14 the highest density was 4.32 in CPP
(`security/help.md`), and 0.0 in mattpocock/skills. 5.0 sits just above both,
so the rule flags an outlier against the two collections it was measured on.
Neither collection fires, which is a measured result and not a blind rule:
`skillc selftest` shows the rule red on `controls/emphasis-density/bad`.

**Cannot see.** Emphasis by bold or italics alone, and lowercase "must".

## Exposure (round 2's second input)

`skillc exposure` measures what reaches the model, and `inspect` does not
re-run it. `--exposure REPORT.json` folds the HIDDEN, TRUNCATED and UNMEASURED
items from a `skillc exposure` report into the sort as UNSORTED. Without the
flag, the report says `exposure: not supplied - what reaches the model was not
measured`. A report recording a refused run is refused.

## Out of scope

Round 5 (the owner's verdict), round 1 and the overlap view, any model call,
and editing any skill.
