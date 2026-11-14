# `skillc inspect` on two real collections (2026-11-14, issue #725)

The real-collection proof for skill-gauntlet round 2. It covers three runs:
claude-power-pack at the SHA that #1830 Part 2 measured, which is the purpose
control; claude-power-pack at its current main; and mattpocock/skills, per
#718's build order. Every run went to a fresh clone at the pinned SHA, with
live issue states from `gh`. The rules are documented in
[docs/specs/inspect.md](../../specs/inspect.md).

## Pins and commands

| Collection | SHA | Subjects |
|---|---|---|
| cooneycw/claude-power-pack | `d5ef0a66912436925078184d1ec8e89cb40323e6` (#1830 Part 2's SHA) | 118 (100 commands + 18 skills) |
| cooneycw/claude-power-pack | `93ae85402adc58f3a3369a588547b459b62e2cc7` (main, 2026-11-14) | 118 |
| mattpocock/skills | `5863806dd4e15c63174bee4e7515a4256792ecfa` (main, 2026-11-12) | 39 |

```bash
# claude-power-pack (both SHAs): commands + Claude-facing skills; codex/skills/ is generated and excluded
skillc inspect <checkout> \
  --include '.claude/commands/**/*.md' --include '.claude/skills/*/SKILL.md' \
  --map '~/.claude/scripts/=scripts/' --map '~/.claude/commands/=.claude/commands/' \
  --repo cooneycw/claude-power-pack --out <dir>

# mattpocock/skills: the default surface (**/SKILL.md)
skillc inspect <checkout> --repo mattpocock/skills --out <dir>
```

## Purpose control: the twelve from #1830 Part 2

In Part 2, CPP was grepped at `d5ef0a66` for `until #N`, and every one of the
twelve rules found was waiting on a closed issue. Before this work could count
as an instrument, `inspect` had to re-find all twelve, read each one as CLOSED,
and sort each into D. It did. **12 of 12 were found, 12 CLOSED, 0 UNKNOWN, and
all 12 went into D.**

| Part 2 | `inspect` (D) | Pinned by tests |
|---|---|---|
| CLOSED #1014 `flow/register.md:1610` | D `flow/register.md:1610` #1014 | `test_delivery_lane_versioned.py` |
| CLOSED #1256 `cpp/update.md:1381` | D `cpp/update.md:1381` #1256 | 12 test files |
| CLOSED #1513 `flow/auto.md:729` | D `flow/auto.md:729` #1513 | 19 test files |
| CLOSED #575 `cpp/init.md:2132` | D `cpp/init.md:2132` #575 | 26 test files |
| CLOSED #575 `cpp/update.md:2026, :2031` | D both lines, #575 | 12 test files |
| CLOSED #635 `flow/wave.md:1280` | D `flow/wave.md:1280` #635 | 4 test files |
| CLOSED #663 `cpp/update.md:2280`, `flow/repair.md:81` | D both, #663 | 12 / none |
| CLOSED #699 `flow/wave.md:108` | D `flow/wave.md:108` #699 | 4 test files |
| CLOSED #788 `flow/wave.md:1044` | D `flow/wave.md:1044` #788 | 4 test files |
| CLOSED #927 `flow/doctor.md:207` | D `flow/doctor.md:207` #927 | 4 test files |

The pinned-by column is #1830 Part 4 made visible. Only `flow/repair.md:81` can
be removed without editing a test. `flow/register.md` is pinned by exactly the
test Part 4 named (`test_delivery_lane_versioned.py`).

Part 2 named one miss, and `inspect` has the same one: `wave.md:1271`, "Filed
as #640 ... until it lands". That phrase has no `until #N`, so it isn't found.
It's documented as the rule's blind spot rather than covered by widening the
pattern.

All 12 markers are bare `until #N`. None of them uses `expires-with`, so each
is also listed as a prose-only dependency note.

## Counts

All three runs had 0 UNKNOWN and every rule examined. A zero in A, B or C
means **not assigned**, never "none" (see the spec's bucket policy).

| Run | Verdict | dangling-reference | expired-marker | copied-passage | emphasis-density |
|---|---|---|---|---|---|
| CPP `d5ef0a66` | STOPPED | 6 errors | 12 | 81 pairs | 0 (max 4.32) |
| CPP `93ae8540` | STOPPED | 6 errors | 12 | 81 pairs | 0 (max 4.32) |
| mattpocock `5863806` | FINDINGS | 0 | 0 | 2 pairs | 0 (max 0.00) |

| Run | A | B | C | D | UNSORTED | Rule lines (all UNSORTED) |
|---|---|---|---|---|---|---|
| CPP `d5ef0a66` | 0 | 0 | 0 | 12 | 81 | 82 |
| CPP `93ae8540` | 0 | 0 | 0 | 12 | 81 | 82 |
| mattpocock `5863806` | 0 | 0 | 0 | 0 | 2 | 0 |

The two CPP SHAs are a few commits apart, and none of those commits changes
the decay picture.

**Population for `dangling-reference` on CPP:** it examined 48 links, 336
prefixed references and 240 flags. It counted but did not examine 166
path-like words outside any declared prefix (user-project files such as
`.claude/cicd.yml`, and unmapped `~/` paths) and 1,222 placeholder paths
(`${CLAUDE_PLUGIN_ROOT}/...`, `<name>`, globs).

**Why A is 0 on CPP.** CPP has 82 emphasised rule statements, and no
paragraph in them names its enforcer. The worktree rule at
`flow/auto.md:82` ("CRITICAL: You MUST create or enter a worktree") is guarded
by `flow-start-resolve.sh --verify`, but that sits two paragraphs later, and
`inspect` does not borrow across paragraphs because that would be a guess.
This is #1830 Part 3's point measured directly: the link between a rule and
the check that enforces it is not written down anywhere a tool can read. CPP
has 78 scripts that declare a `NEGATIVE-CONTROL:` marker, so if a rule named
its helper, it would sort into A (`test_A_when_the_named_helper_declares_an_existing_negative_control`).

## Findings checked by hand

### claude-power-pack

1. **Real, live defect.** `codex/auto.md:346`, `gemma/auto.md:384` and
   `qwen/auto.md:364` pass `--kind message` to `flow-wave-mailbox.sh send`.
   The script's option parser has no `--kind`, and its catch-all arm is
   `--*) usage_fail "unknown option: $1"`. The "still waiting on Step 3
   approval" escalation that all three delegated drivers prescribe therefore
   fails. Filed upstream as its own issue (see the PR).
2. **Real, D-class.** `cpp/update.md:274` names `scripts/skill-drift.py`,
   which was deleted in `f2ce9f5d` ("retire the dual command/skill surface +
   skill-drift + symlink installer", #480/#522). The sentence is history
   about a retired helper, so it is #1830's group D, and the reference is
   dead.
3. **Real, D-class.** `flow/wave.md:1280` reads "Until #635 settles it", and
   #635 closed on 2026-08-11 (checked with `gh issue view 635`).
4. **Real copy, deliberate, held by a control.** `gemma/auto.md` and
   `qwen/auto.md` share 7,487 words. `codex/auto.md` shares 6,305 with gemma
   and 6,276 with qwen. These are the three delegated-driver docs, which CPP
   vendors identically on purpose and holds identical with
   `controls/delegated-core-vendor`. The finding is true, and the copies are
   checked. `inspect` reports it as UNSORTED because recognising a copy under
   a vendoring control as A is not built yet (spec, blind spots).
   `cpp/init.md` and `cpp/update.md` share 1,461 words, with a longest run of
   665, and have no vendoring control. That is a drift risk of exactly the
   Part 5 kind.
5. **Ambiguous, reported honestly.** `project-deploy/SKILL.md:23,73` names
   `scripts/deploy.sh` and `scripts/deployment/deploy_chess.sh`, which are
   files in *the user's* project. The rule cannot tell those from collection
   files (see the spec, "Known ambiguity"). These two are the only reason
   CPP's run would still be STOPPED once items 1-2 are fixed.

**Measurement defect found by the counter-model review and fixed.** The first
version merged copied-run matches across alignments. On the driver-doc pairs it
reported about 214 runs with a longest of 692 words; grouped by alignment, the same
pairs give 36-47 runs with a longest of about 1,011 words (codex/gemma at main). The
shared-word totals above were unaffected, and so were the buckets.

**False-positive classes found and fixed during development** (each one now
has a test):
- a flag belonging to a wrapper's exec target (`flow-preflight.sh` execs
  `flow-preflight.py`);
- a flag belonging to a nested command (`--show-toplevel` inside
  `$(git rev-parse ...)`);
- an extensionless prose example (`scripts/foo` in `flow/register.md`).

### mattpocock/skills

1. **Real copy.** `skills/in-progress/claude-handoff/SKILL.md` and
   `skills/productivity/handoff/SKILL.md` share 46 words. A word diff shows
   they differ only in the skill name, so it is an in-progress fork of a
   published skill.
2. **Real copy.** `skills/in-progress/writing-beats/SKILL.md` and
   `writing-shape/SKILL.md` share a 45-word run: two in-progress siblings with
   one shared paragraph.
3. **Absences verified as such.** A grep for `until #N`/`expires-with` in the
   collection finds 0, and so does a grep for whole uppercase emphasis words.
   The rules' zeros match a scan that is independent of them, and selftest
   shows both rules can fire. All 32 relative links examined resolve (sampled
   by hand: `PHASE-BOUNDARIES.md`, `LOGIC.md`, `UI.md` exist beside their
   skills).

## Re-run after #731 (same SHAs)

#731 fixed four precise false verdicts (enforcer from a `bad/` input, a
single-token `$(...)`, file arguments owning flags, and a bounded copy-run
estimate). The three collections were re-run and compared with the #733 reports
finding by finding:

| Run | Errors | Buckets / rule lines | Copied-passage (pairs, numbers) | Flags examined |
|---|---|---|---|---|
| CPP `d5ef0a66` | 6, identical | identical | 81, identical; 0 estimates | 242 -> 240 examined; 1 counted unowned |
| CPP `93ae8540` | 6, identical | identical | 81, identical; 0 estimates | 242 -> 240 examined; 1 counted unowned |
| mattpocock `5863806` | 0 | identical | 2, identical; 0 estimates | 0 -> 0 |

Only population counters moved, and each delta is accounted for:
- **flags examined, 242 -> 240.**
  - `cpp/init.md:2834`, `echo "... bash ~/.claude/scripts/bash-prep.sh --check"`:
    the script is inside a quoted string passed to `echo`. Its path is still
    checked for existence, but a string has no command, so `--check` has no
    owner to check against.
  - `cpp/update.md:2017`, a prose code span `(re-run
    scripts/commands-mirror-sync.sh --write later)`: the script is not in
    command position. This is the 1 flag counted in
    `flags_after_a_non_command_path` (a listed blind spot).
- **prefixed references examined: 336 -> 336, unchanged.** An intermediate
  shlex build hid the paths inside quoted strings (-7). They are checked again,
  and a test now holds that.
- **placeholder paths not examined, 1137 -> 1092 on CPP (-45), 33 -> 30 on
  mattpocock.** This is only how shlex spells words that were never examined:
  quotes are stripped (`"$X/y"` and `$X/y` are now one spelling), and
  redirections are split (`&>/dev/null` becomes `&` plus `>/dev/null`). No
  examined reference is among them.

The shlex tokeniser is a design change, ratified by the orchestrator, with the
guard that it reads command-shaped text only and never running prose.

An earlier cut also dropped `if ! scripts/commands-mirror-sync.sh --check` and
`elif ~/.claude/scripts/speckit-context.py refresh --body-file`; shell keywords
were then added to the command prefixes, and a test now holds both.

## Reproducing

The SHAs above are public. `--issue-states` makes a run deterministic: issue
states move over time (an OPEN issue may close), so a re-run with live `gh`
can legitimately find more D items than these counts.
