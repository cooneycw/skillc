# Skill contracts: `CHARTER.md` and `skillc contracts` (#720)

A skill's `SKILL.md` says what to do. Its `CHARTER.md` says what it **promises**:
why it exists, what it delivers and to whom, what it needs first, what it must
never do, and what needs the owner. With contracts, "improve this skill" has a
definition, and a hand-off between two skills can be checked from **both sides**.

This is skill-gauntlet build step 2 (#718). The format and its worked example come
from #718's "Contracts: charters with hand-offs"; owner decision 1 there puts a
`CHARTER.md` beside each `SKILL.md`, in the skill's own repository.

## The file

`CHARTER.md` starts with a YAML block between `---` lines, followed by prose for
the owner. `skillc contracts` reads only the block.

```yaml
---
contract: flow-eli5          # required: lowercase, dash-separated, unique in the collection
version: 3                   # required: positive integer
intent:                      # required: text (a draft), or a clause the owner approves
  id: eli5.intent
  what: >
    The owner approves a plan only after seeing, in plain language, what will
    change, whether it is still needed, and where the claim will be exercised.
  approved: 2026-11-14
purpose: A plain-language plan and proposed changes, for the owner to approve.   # required
owner: owner                 # required
scope:
  in: [eli5.section-c]       # duties this contract owns
  out: [plan-record.approve] # duties it deliberately leaves to another contract
consumes:
  - plan-record.approve@1    # <clause-id>@<version> this contract takes from another
provides:
  - id: eli5.section-c
    what: proposed changes and a lane answer for every lane
    readers: [flow-plan-record.approve, owner]
    test: checks/eli5-section-c/{bad,good}
requires:
  - id: eli5.issue-readable
    on_false: stop with UNKNOWN, never a guessed summary
    test: checks/eli5-issue-readable/{bad,good}
invariants:
  always: []
  never:
    - id: eli5.never-guess
      test: checks/eli5-never-guess/{bad,good}
authority:
  - id: eli5.no-self-approval
    what: never approves its own plan
    approved: 2026-11-14
    test: checks/eli5-no-self-approval/{bad,good}
failure: []
---
```

Only the fields above are allowed. An unknown top-level field (`provide:`) is a
`contract-shape` error, never ignored. A clause is a mapping in `requires`,
`provides`, `invariants.always`, `invariants.never`, `authority` or `failure`.
Each clause has an **`id`** (unique within its contract) and a **`test`** (a path,
or a list of paths). `version`, `readers` (on `provides`) and `approved` are
optional clause fields, and any other clause field (`what`, `on_false`) is free
text for the owner.

### Where a charter lives, and `subject:`

Owner decision, 2026-11-15 (#726, claude-power-pack#1838):

- **A native skill** keeps `CHARTER.md` beside its `SKILL.md`. `subject:` is
  optional there, but if it is given it must name that `SKILL.md`.
- **A slash command** gets `charters/<ns>/<cmd>/CHARTER.md` at the collection
  root, with a **required** `subject:` naming the command file, for example
  `subject: .claude/commands/flow/auto.md`.
- **Never in a generated mirror** (such as a `codex/skills/` copy).

`subject:` resolves from the collection root. Each of these is a
`contract-shape` error with a named reason:
- a missing subject under `charters/`;
- a subject that does not exist, or is not a file;
- a subject outside the collection;
- a subject beside a `SKILL.md` that names some other file.

Committed cases: `controls/contract-shape/bad/{subject-missing,subject-dangling}` and
`controls/contract-shape/good/subject-command`. This reuses `contract-shape`
rather than adding a rule, so the selftest count is unchanged.

### The YAML subset

The block uses the same small YAML subset as skill frontmatter
([docs/frontmatter.md](../frontmatter.md)), **plus** two shapes that SKILL.md
frontmatter still refuses:

- **a list of mappings** (`- id: a` with the clause's keys under it, lined up
  under the first key as YAML requires - #739);
- **a one-line flow list of scalars** (`[a, b, "c"]`).

Anything else is refused by name as `contract-shape`, never silently misread. That
covers a nested flow collection, a flow list continued onto the next line, and a
plain value **wrapped onto an indented next line**. Wrap long text in a `>` block.
#718's own example wraps a plain `what:`, which this subset refuses; that is a
correction to the discussion text, not to this format.

In a flow list, quotes are honoured: `['a, b']` is one item, as YAML reads it. A quoted item must be the whole item, and a `#` inside the brackets is refused, so `["owner"#x"]` is refused rather than read as `["owner"]`. A trailing comment after the closing `]` is fine.

## The two rules that make it a contract

1. **Every clause needs a test that can fail.** A clause with no test, or whose
   test path does not exist, is **unbacked**. This is the negative-control rule
   applied to promises.
2. **Both sides of a hand-off agree.** A consumer names the clause it takes and the
   version it expects (`eli5.section-c@2`). The provider must exist and must be at
   that version now. When `flow-eli5` adds lane answers and moves `eli5.section-c`
   to version 3, a `flow-auto` still consuming `@2` is reported, which is the
   2026-11-14 lanes miss (CPP #1830, Part 5).

A clause's version is its own `version:` when it declares one, and otherwise its
contract's `version:`.

## What `skillc contracts` checks, and what it does not

| Rule | Severity | Reports BAD when | Committed bad cases (`controls/<rule>/bad/`) |
|---|---|---|---|
| `contract-shape` | error (parser rule) | the block does not parse or uses unsupported YAML; a required field is missing; an unknown field; a field of the wrong type; a duplicate contract name or clause id (the intent's id counts as a clause id, #749); a missing or dangling `subject:` | `unparseable`, `no-intent`, `wrapped-plain-scalar`, `dash-spacing`, `unknown-field`, `duplicate-provider`, `subject-missing`, `subject-dangling`, `intent-id-collision` |
| `clause-backed` | error | a clause has no `test`; a test path does not exist; a brace expansion yields a missing path; more than one brace group; a path outside the collection | `no-test`, `missing-path`, `brace-one-missing`, `two-brace-groups` |
| `negative-backed` | error | a `never` or `authority` clause names no test path with a `bad` segment | `never-good-only`, `authority-good-only` |
| `handoff-bilateral` | error | a `consumes` names a clause no contract `provides` | `nothing-provides` |
| `handoff-version` | error | a `consumes` version differs from the provider's current version | `provider-moved-on`, `clause-override-ignored` |
| `reader-exists` | error | a `readers` entry is not `owner`, not a contract, and not `<contract>.<clause>` where **both** exist | `contract-typo`, `clause-typo` |
| `scope-owned` | error | a `scope.out` duty is in no other contract's `scope.in` (an orphan) | `orphan-out` |
| `duty-single-owner` | error | two contracts list the same `scope.in` duty | `two-owners` |
| `approval-present` | **warn only** | an `intent` or `authority` clause has no owner `approved: YYYY-MM-DD` | `intent-string`, `authority-unapproved` |

`skillc selftest` proves each rule BAD on its bad cases and GOOD on its good cases,
and `tests/test_records.py` proves each bad case trips its own rule and no other. A control case whose contract fails `contract-shape` is UNPARSED for every other rule, because those rules skip it and a skipped evaluation is not a pass.

**Test paths** resolve from the collection root (the path given to `skillc
contracts`), never from the `CHARTER.md` file. Expansion of `{a,b}` is **one
level**: `checks/x/{bad,good}` means `checks/x/bad` and `checks/x/good`, and
**every** path it yields must exist. One missing path makes the clause unbacked,
not partly backed.

**The `bad` segment is a naming convention. It proves a negative case is PRESENT,
not that it can fail.** `negative-backed` checks that a safety line (`never`,
`authority`) names at least one test path containing a segment named exactly `bad`.
Whether that test can actually go red is rounds 3 and 4 of the gauntlet (#718),
which run the tests. No `skillc contracts` result, including a green one, says a
clause's test can fail.

**A directory discovery cannot read refuses certification.** Any contract inside it is unexamined, so the collection is reported as a `contract-shape` error (exit 1), never as a smaller clean population.

**Hand-off rules run only when every contract has a valid shape.** If any
contract fails `contract-shape`, `handoff-bilateral`, `handoff-version`,
`reader-exists`, `scope-owned` and `duty-single-owner` do not run, and the output
says so. A hand-off whose provider failed to parse would otherwise read as
"nothing provides it", which blames the wrong contract.

## Output and exit codes

```bash
skillc contracts <collection>
```

The command prints every finding, then one `CONTRACT <name> (<path>): GOOD|BAD`
line per contract, then a `CONTRACTS:` summary and the line naming what was not
examined.

| Exit | Meaning |
|---|---|
| `0` | every contract is clean (warnings allowed) |
| `1` | at least one error finding |
| `2` | usage error: the collection directory does not exist |
| `3` | **none declared**: no `CHARTER.md` under the collection, and every directory was read, so nothing was checked. Never `0`: an empty population is not a clean one. A directory discovery could not read makes the run `1` instead, even with no contract found: an unexamined collection is not an empty one (#739) |

Run on CPP at `3ed254698f3e` (34 SKILL.md files, no CHARTER.md yet), it prints
`CONTRACTS: none declared` and exits 3.

## Fixture

`evals/subjects/contracts-example/` holds three contracts modelled on `/flow:eli5`
-> `/flow:auto`: a composite and two parts. As committed it carries the `@2`/`@3`
mismatch (`handoff-version` BAD). Fixing the consumer's version makes it clean;
`tests/test_contracts.py` runs both.

## Out of scope (#720)

- Writing contracts for CPP skills: round 1 of the gauntlet (#726), with the owner.
- Drafting contracts from observed behaviour, and the meaning-based overlap view:
  model calls with their own negative control (#726).
- Running the tests clauses name: rounds 3 and 4.
