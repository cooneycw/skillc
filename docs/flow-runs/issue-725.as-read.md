<!-- flow-run n=1 id=07342ece6c2145e6b97bbc86a72da4b5 -->
## Run 1 - issue #725 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #725
- Read at:      2026-11-14T20:38:37Z
- updatedAt:    2026-11-14T20:32:45Z   (context only - moves on comments and labels)
- Body digest:  9d92ebe0cb22c47088fc6df247c93ed9faa49d1f0746c7ef99c8f4e0a24798be   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 5815 of 5815 (cap 16384)

### Body as read
## Why

The skill-gauntlet (discussion #718) analyses a skill's **structure** in round 2, "Inspect". That round is free and mechanical: no model calls and no paid trials. It is #718's build step 2 ("Rounds 2 and 5 plus decay rules"). It is also the cheapest way to show the gauntlet is worth building: CPP discussion cooneycw/claude-power-pack#1830 found twelve of twelve `until #N` rules waiting on closed issues, and nothing checks for that today.

What `skillc check` checks today is **frontmatter and shape**: `name-spec`, `required-fields`, `trigger-shape`, `body-budget`, `ref-depth` and the rest. It does not check whether a skill's text has **decayed**. Nothing flags a reference to a helper that was deleted, a rule written to expire with an issue that has closed, text copied from another skill, or emphasis that has piled up.

This issue builds round 2 only. Round 1 (drafting a charter from observed behaviour, and the overlap view) is #718's build step 3. The charter and contract format is #720. Round 2 works **without a charter**, so it can run on any collection now.

## What

### 1. Decay rules for `skillc check`

Each rule follows ADR 0001: a committed `controls/<rule-id>/{bad,good}/` pair, and a selftest that shows the rule red on its bad case and green on its good one. Each bad case trips its own rule and no other (`tests/test_records.py`'s minimality test).

- **`dangling-reference`** (error): the skill's text names a file, script or flag that does not exist in the skill's own tree or in the collection it declares. The rule matches exact paths and names, never substrings; records.md's config-drift-checker trap applies here too. What counts as a reference (backticked paths, `scripts/...`, `--flag` against the named script's `--help`) is part of the design, and the PR documents its population: what it scans, and what it cannot see.
- **`expired-marker`** (warn): an `until #N` or `expires-with: #N` marker whose issue has closed.
  - With no network, or no `gh`, the rule reports `UNKNOWN` for each marker. It never reports `fine`.
  - A run where every marker is `UNKNOWN` must not read as clean.
  - A committed fixture supplies the issue states, so CI is deterministic and offline.
- **`copied-passage`** (warn): a passage at least N lines long that is identical, after whitespace normalisation, to one in another skill of the same collection. Wording-level only; meaning-level overlap belongs to round 1. N is decided and documented.
- **`emphasis-density`** (warn only, never error): the number of MUST / NEVER / CRITICAL / ALWAYS per hundred body lines, above a documented threshold.

### 2. `skillc exposure` as round 2's second input

`skillc exposure` already exists and measures what actually reaches the model. Round 2 runs it as is; it is not rebuilt here.

### 3. A/B/C/D sorting: `skillc inspect <collection>`

One command runs the decay rules and exposure, and sorts each finding into #718's four buckets:
- **A:** already enforced elsewhere (a check, test or hook covers it), so shrink it to a pointer;
- **B:** nothing enforces it, so propose a check;
- **C:** a fact the code cannot show, so keep it;
- **D:** history or a retired feature, so move it to a reference doc.

Sorting is mechanical where it can be. A closed `until #N` marker is D. A rule that names a check which exists is A. Anything else is `UNSORTED`, never guessed. Output is a report (Markdown, plus JSON), and a finding with no bucket is shown as such.

**Stops when** there is a hard error, such as a dangling reference to a deleted helper. That is a bug, not a trim; `inspect` exits non-zero and sorts nothing past it.

## Acceptance

- [ ] Each of the four decay rules is registered, documented in `docs/` with its population and blind spots, and shown by `skillc selftest` red on its bad case and green on its good one. The PR names each bad case with its verdict.
- [ ] `expired-marker` with the network unavailable reports `UNKNOWN` for every marker, and the run summary does not say clean. That case is a committed test.
- [ ] `skillc inspect` on a collection with zero skills exits non-zero with "nothing inspected", never "0 findings".
- [ ] **Real-collection proof:** `skillc inspect` on claude-power-pack at a pinned SHA. The PR shows the counts per rule and per bucket, plus three or more findings checked by hand as real.
- [ ] **Negative control for inspect:** a planted collection with one deleted helper reference and one closed `until #N` makes `inspect` stop on the first and sort the second into D. The same collection with both repaired inspects clean.
- [ ] A second collection, mattpocock/skills at a pinned SHA, inspected the same way, per #718's build order ("on CPP and on mattpocock/skills").

## Design questions to settle in the plan

- **CPP's subject surface.** CPP's Claude-facing skills are mostly commands (`.claude/commands/**.md`), with 18 skills under `.claude/skills/` and 80 generated Codex skills under `codex/skills/`. Inspecting the generated copies would count every finding twice. The plan names the source surface, and says how `inspect` reads commands, which `skillc check` does not read today.
- **What counts as "enforced elsewhere" for bucket A:** a mechanical signal, such as a named test or control that exists, versus `UNSORTED`.

## Out of scope

- Round 5 (the owner verdict). #718 pairs it with round 2 in build step 2; it can be its own issue once round 2 produces findings worth ruling on.
- Round 1, the overlap view, and any model call.
- Editing any skill. `inspect` reports and never trims (#718 fixed rule: "never changes a charter without the owner").

Refs #718. Context: cooneycw/claude-power-pack#1830, #719 (build step 1), #720 (charter and contract format).

🤖 Generated with [Claude Code](https://claude.com/claude-code)


<!-- end of body -->
