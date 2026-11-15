# Skill-gauntlet round 5: the verdict (#737)

Round 5 turns rounds 0-4 into the gauntlet's one output (#718): a single
proposal, **keep**, **trim** or **retire**, and a single `NEXT:` line. It decides
nothing alone. It drafts a patch and PR text and stops. The owner rules.

```bash
skillc gauntlet verdict <collection> <skill> --round3 R3.json --round4 R4.json \
    --declaration DECL.json --inspect INSPECT.json --overlap OVERLAP.json [--draft-dir DIR]
skillc gauntlet rule <collection> <skill> accept|reject|amend --verdict-digest SHA [--date YYYY-MM-DD] [--note TEXT]
```

It is offline and pure. It reads files, and makes no model call and no subprocess.

## Inputs, and the fields read

| Input | From | Read |
|---|---|---|
| GAUNTLET.json | `gauntlet run` (#764), beside the charter | rounds `0`, `1`, `2` and their `verdict` |
| `--round3`, `--round4` | `gauntlet round3/round4 --json` (#736): exactly `dataclasses.asdict(RoundReport)` | `round`, `verdict`, `recommendation`, `per_clause`, `variants{arm: {removes, source, passes, remove_sha256}}` |
| `--declaration` | #736's declaration | `variants[]{arm, file, remove}` |
| `--inspect` | `inspect --json` (#725) | `kind`; `findings[]`, `rule_lines[]` and `errors[]` on this skill: `bucket` D and B |
| `--overlap` | round 1 overlap (#726 part B) | `examined`, `incomplete`, `duties[]{contract, id}`, `overlaps[]{kind, duties}` |

The field names are pinned in ONE place, `ROUND_FIELDS`, `VARIANT_FIELDS`,
`PASSAGE_DIGEST` and `OVERLAP_FIELDS` in `skillc/gauntlet_verdict.py`. A rename upstream breaks this
reader on purpose: `test_the_real_round_report_carries_every_field_read` reads
the real `RoundReport` class. That test is skipped, loudly, until #736 PR 1 is
on main. Until then the controls plant reports in that shape. Part B's overlap
has no JSON on main either, so its shape is planted the same way.

## The rules, in order

1. **Rounds 0-2 must have passed** in the record: `0` OBSERVED, `1` PASS, `2`
   PASS. Anything else is **UNKNOWN**, and NEXT names that round. The
   recorded rounds 1 and 2 must also have read the skill, its charter and the
   collection as they are now (their recorded input digests). A skill changed
   since `gauntlet run` is UNKNOWN: its PASS is evidence about another revision.
2. **Rounds 3 and 4** must be present, the right round, and `COMPLETE`.
   Otherwise UNKNOWN, naming the round.
3. **No `--overlap`, or an overlap that does not cover this skill:** retire is
   NOT EXAMINED, so the verdict is UNKNOWN, and NEXT names round 1 overlap. This
   is never keep by default (must-never 3, gate ruling). The report must carry
   every `OVERLAP_FIELDS` field, read `examined: true` with `incomplete: []`, and
   list at least one duty of this skill's contract; anything else is UNKNOWN.
4. **No `--inspect`, or one that did not inspect this skill:** the file must be
   an `inspect-report` with at least one entry on this skill's text, and the
   engine's own round-2 reading of it (`gauntlet.read_round2`, one place) must
   be PASS: an error or UNKNOWN on this skill, or an unexamined rule, is
   UNKNOWN, naming round 2.
5. **retire:** every duty of this skill's contract appears in a `shared` or
   `shadowed` overlap with another charter. The verdict names the owner of each
   duty.
6. **trim:** round 4 recommends trim, and a variant passes. The passing variant
   that removes the most words is drafted.
   - Its report row (`removes`, written as `"<file>: <first 80 chars>"`) must
     match the declaration. If they disagree, UNKNOWN.
   - `removes` holds only 80 characters, so a longer passage is bound by the
     row's `remove_sha256` (sha256 of the whole passage, requested of #736).
     Absent or different: UNKNOWN. Without it, a declaration sharing only the
     first 80 characters would be drafted as the passage round 4 tested.
   - Its file must be a regular file inside the skill, reached through no
     symlink; `..`, an absolute path or a symlink is UNKNOWN. A command skill
     owns its one file: a neighbouring command or file is UNKNOWN.
   - It must not include a round 2 **B** line: that prose stays until its check
     exists, so such a trim is UNKNOWN.
   - Its passage must occur **exactly once** in the file. Zero or several
     occurrences are UNKNOWN.
   - Every clause in `per_clause` must carry intact and variant counts, with at
     least one evaluable variant attempt. Missing counts are UNKNOWN: a trim is
     never claimed without per-clause evidence.
   - The drafted diff only removes text (must-always 3), and the before and after
     pass counts are shown per clause.
7. **keep:** otherwise.

Round 2's **D** items are listed as removal candidates. **B** items become
**proposed checks** naming the missing check (`missing_check`), and their prose
stays until the check exists. Round 2 names the check, not a case it must fail
on, so each says its bad input is NOT CONSTRUCTED rather than inventing one. The evidence is labelled observational, never causal.

**Not examined:** the second retire path, "no clause has any observed use",
needs per-clause usage, and no round stores that yet. It is neither built nor
claimed.

## Outputs

`verdict` writes into the engine's draft location
(`<main checkout>/.skillc/gauntlet/<skill>/`, or `--draft-dir`). It uses the
engine's own writer, so #759's symlink and exclusive-create rules apply:

- `round5.json`: the verdict, its digest and its fingerprint: the skill folder
  (without the record), rounds 0-2 as recorded, and the sha256 of each input
  file. The digest covers the fingerprint;
- `round5-pr.md`: the PR text;
- `round5.patch`: for trim only. An older trim's patch is removed when a later
  verdict is not a trim.

It never pushes, opens a PR, edits the skill, or edits its CHARTER.md
(must-never 1), and it writes no date. A re-run with the same inputs leaves
these files and GAUNTLET.json byte-identical.

## The owner's ruling

`gauntlet rule` writes `rounds.5` into GAUNTLET.json: `{verdict, ruling,
ruled_on, note, inputs: {verdict: <digest>, <input>: <sha256>...}}`. `ruled_on` is the record's ONLY
dated field (gate ruling), taken from `--date`, which defaults to today in UTC.

It refuses (exit 1):
- a `--verdict-digest` that is not the drafted verdict's, so a ruling never
  lands on a verdict the owner did not read;
- a skill or record that changed since the verdict was drafted. The draft
  location is shared by every worktree of the checkout, so this is also what
  stops a verdict drafted in one worktree being ruled on from another;
- an UNKNOWN verdict;
- a skill with no record.

The engine carries `rounds.5` across re-runs (`KEPT_ROUNDS`); it never re-derives it.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | `verdict`: keep, trim or retire proposed. `rule`: recorded |
| 1 | `rule` refused: a stale digest, an UNKNOWN verdict, or no record |
| 2 | usage: an unreadable input, or no place for the drafts |
| 3 | `verdict` UNKNOWN: never a pass |

## Not in #737

- **Engine wiring:** `gauntlet run` -> verdict goes with #736 PR 3. `run` stops at round 3 until rounds 3-4 can run.
- **Real proof still open:** the proof on CPP `flow/wave.md` needs real round 3/4 runs and owner-confirmed rounds.
