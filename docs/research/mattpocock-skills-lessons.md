# mattpocock/skills lessons and concept map

- Date: 2026-09-26
- Issue: [#49](https://github.com/cooneycw/skillc/issues/49)
- Source: [mattpocock/skills at c55ee46](https://github.com/mattpocock/skills/tree/c55ee46073ed923f86ce59a5eb3b6d895095d1b7),
  by [Matt Pocock](https://github.com/mattpocock), plugin version 1.2.3, committed
  2026-09-18. Inspected 2026-09-26
- Licence: [MIT](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/LICENSE)
- Precedent: [config-drift-checker-lessons.md](config-drift-checker-lessons.md) (#38)

## What this document is

skillc's README has always credited this repository's `writing-for-agents` skill
as the basis for its description, trigger, progressive-disclosure and pruning
rules, but with no pinned revision and no provenance note. This document is that
note, pinned at `c55ee46073ed923f86ce59a5eb3b6d895095d1b7`, and it records the
static scan baseline four later issues (#50, #51, #52, #53) cite against that
same commit.

skillc does not run, import, wrap or vendor this repository. **Everything below
is static reading** of the pinned source, plus one execution: `skillc check`
against its `skills/` tree, using skillc's own checker. No code from
mattpocock/skills was run. Paths are repository-root relative at `c55ee46`.

Borrowing an idea listed here is allowed and expected. **Name this document, the
upstream project and the pinned commit** in the design note, spec section or ADR
that introduces it. Do not copy source, fixtures or prose beyond short attributed
quotations. Terms of use follow [ADR 0003](../decisions/0003-no-external-evaluation-runtime.md):
ideas, not code.

## Adopted concepts

| Concept | Upstream location (pinned) | skillc owner | Translation |
|---|---|---|---|
| A description states a triggering condition, not just a capability, because the model reads it to decide whether to fire | [`skills/productivity/writing-for-agents/SKILL.md` L14-17](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/writing-for-agents/SKILL.md#L14-L17) ("Context pointers": "list the **branches** that should trigger reaching it") | `trigger-shape` (`skillc/checks.py:139-147`) | A `WARN` when a description has no triggering phrase. #51 found the rule's premise does not hold for a user-invoked skill, whose description this same repository's convention keeps human-facing (see the next row) |
| A user-invoked skill's description is human-facing, not a model trigger, and should have its trigger lists stripped | [`skills/productivity/writing-for-agents/SKILL-MECHANICS.md` L10](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/writing-for-agents/SKILL-MECHANICS.md#L10) ("the `description` becomes human-facing: a one-line summary, trigger lists stripped") | #51 | Proposed in #51: narrow `trigger-shape` to skip a skill declaring `disable-model-invocation: true` under `--target claude-code`, where that field is documented. Not yet landed; the exact behaviour is still being decided in that PR |
| Progressive disclosure keeps a document's top legible by pushing branch-specific material behind a pointer, one level down | [`skills/productivity/writing-for-agents/SKILL.md` L29-43](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/writing-for-agents/SKILL.md#L29-L43) (the information hierarchy: in-file step, in-file reference, disclosed reference) | `ref-depth` (`skillc/checks.py:185-201`), `body-budget` (`skillc/checks.py:177-182`) | `ref-depth` warns when a reference chain goes deeper than one hop; `body-budget` warns when the body itself sprawls past a line budget instead of disclosing. #52 found `ref-depth` over-counts a chain that loops back to `SKILL.md` or re-visits an already-linked sibling |
| Pruning: keep one authoritative place per meaning, and cut a line that no longer bears on the task | [`skills/productivity/writing-for-agents/SKILL.md` L76-81](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/writing-for-agents/SKILL.md#L76-L81) ("Pruning": single source of truth, relevance, no-ops) | `body-budget` (`skillc/checks.py:177-182`) | Translated as a line-budget ceiling rather than a semantic duplication check; skillc has no rule yet that detects restated meaning directly |
| User- vs model-invoked is the one axis every skill declares, and each harness excludes a user-invoked skill from the model's reach in its own field | [`.agents/invocation.md` L5, L10](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/.agents/invocation.md#L5-L10) (L5: `disable-model-invocation` / `policy.allow_implicit_invocation`; L10: "Keep the two in sync: a skill is user-invoked in both harnesses or neither") | #50 | Proposed in #50: a new `invocation-consistency` rule reading both the Claude Code frontmatter field and Codex's `agents/openai.yaml`, refusing to treat an unreadable second-client file as agreement. Not yet landed |
| A distributable collection ships a declared subset, named in the client's own manifest, not every `SKILL.md` under the tree | [`.claude-plugin/plugin.json` `skills` array](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/.claude-plugin/plugin.json) (25 entries, engineering/ and productivity/ only); [`CLAUDE.md`](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/CLAUDE.md) states the promoted-bucket convention this manifest encodes | #53 | `skillc check --manifest <plugin.json>` scopes the scan to declared entries and reports the undeclared remainder as a count, rather than mixing shipped and draft skills into one total |

## Static scan baseline at c55ee46

Run against skillc `64cde403b6e869e6f0422f00e1a2acbe0756485c` (2026-09-26), using
skillc's own checker (not a throwaway script), against the full `skills/` tree
of mattpocock/skills at the pinned commit:

```
$ skillc check <mattpocock/skills>/skills --target portable
skillc: 38 skill(s) checked, 0 error(s), 52 warning(s)

$ skillc check <mattpocock/skills>/skills --target claude-code
skillc: 38 skill(s) checked, 0 error(s), 26 warning(s)
```

Per-rule breakdown:

| Rule | `--target portable` | `--target claude-code` |
|---|---|---|
| `unknown-field` / `claude-code-field` | 26 | 0 |
| `trigger-shape` | 22 | 22 |
| `ref-depth` | 4 | 4 |

Both totals match the ad hoc figures #51, #52 and #53 cite: those were first
taken by an ad hoc run of `skillc check` itself at skillc `6afaca8`, earlier
the same day (only #50's `openai.yaml` agreement check used a throwaway
script, not `skillc check`). Re-running `skillc check` at `64cde40` reproduces
the `6afaca8` figures exactly, so this baseline is a reproduction, not a new
measurement.

### Which warnings are false positives, and which issue owns each

- **`trigger-shape` (22 of 22 are false positives).** The 22 flagged skills are
  *exactly* the 22 skills carrying `disable-model-invocation: true` (verified
  by set comparison: the two lists are identical). Every one is user-invoked,
  so per `.agents/invocation.md` L5 and `SKILL-MECHANICS.md` L10 its description
  is deliberately human-facing with trigger phrasing stripped - the condition
  `trigger-shape`'s rationale assumes ("the model reads this to decide whether
  to fire the skill") does not hold, because the model cannot fire it at all.
  Owned by #51.
- **`ref-depth` (4 of 4 are false positives).** All four flagged chains resolve
  to a file that is not, in fact, a second hop of new material:

  | skill | chain flagged | why it is not deeper |
  |---|---|---|
  | `engineering/codebase-design` | `DEEPENING.md` -> `SKILL.md` | back-link to the entry point |
  | `engineering/prototype` | `LOGIC.md` -> `UI.md` | `SKILL.md:15` links `UI.md` directly |
  | `productivity/teach` | `./RESOURCES-FORMAT.md` -> `./SKILL.md` | back-link |
  | `productivity/writing-for-agents` | `SKILL-MECHANICS.md` -> `SKILL.md` | back-link |

  Owned by #52.
- **`unknown-field` (26 under `--target portable`, correctly scoped, not false
  positives).** All 26 are Claude Code extensions this repository declares by
  convention: `disable-model-invocation` (22, one per user-invoked skill) and
  `argument-hint` (4: `claude-handoff`, `loop-me`, `handoff`, `teach`). Checking
  with `--target claude-code` makes all 26 disappear, which is the documented
  escape hatch `unknown-field`'s own message names - included here for
  completeness, not as a defect.
- **Declared-subset mismatch (not a rule finding today; #53's gap).**
  `.claude-plugin/plugin.json` declares 25 skills - the `engineering/` (18) and
  `productivity/` (7) buckets, which this repository's own `CLAUDE.md` calls the
  "promoted" buckets. The tree holds 38: the other 13 (`in-progress/` 9,
  `misc/` 4) are unshipped drafts by the same convention. `skillc check` has no
  manifest scoping yet, so today's 52/26 totals mix warnings on shipped skills
  with warnings on drafts the plugin never installs. #53 adds
  `--manifest .claude-plugin/plugin.json` to separate them.

## Evidence and limits

Every statement here comes from reading the pinned source and from one
execution: `skillc check` run twice (both target profiles) against the pinned
tree, on 2026-09-26. No mattpocock/skills code was run, imported or vendored.
The false-positive counts above are a property of skillc's current rules
against this one collection at this one commit; they are not a general claim
about either project.
