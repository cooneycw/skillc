<!-- flow-run n=1 id=64b3d00cdde94acc9f43ed33edcee24a -->
## Run 1 - issue #720 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #720
- Read at:      2026-11-14T22:57:14Z
- updatedAt:    2026-11-14T19:56:15Z   (context only - moves on comments and labels)
- Body digest:  5ceeb1d32305512a3a601b0d270c853068fbab641f8ffb37d8aa33af095efcdd   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4759 of 4759 (cap 16384)

### Body as read
## Why

The skill-gauntlet (#718) needs a contract for every skill: its intent, purpose, scope, pre- and postconditions, hand-offs, invariants, authority, failure behaviour and version. With contracts, "improve" has a definition, and a hand-off between two skills can be checked from both sides. The format and its worked example are in https://github.com/cooneycw/skillc/discussions/718 under "Contracts: charters with hand-offs".

A concrete failure this would have caught: on 2026-11-14, CPP's `/flow:auto` ran an ELI5 gate and its report left out the lane rows. `eli5.md` required them. `auto.md` carried an old summary of what ELI5 produces, and nothing compared the two (cooneycw/claude-power-pack#1830, Part 5).

This step needs no model calls and no paid trials. It comes after #719 in the build order.

## What

### 1. The contract format

- A YAML block at the top of `CHARTER.md` beside each `SKILL.md`, documented in a new `docs/specs/contracts.md`.
- Fields: `contract`, `version`, `intent`, `purpose`, `scope` (`in` / `out`), `requires`, `provides` (with `readers`), `consumes` (`<clause-id>@<version>`), `invariants` (`always` / `never`), `authority`, `failure`, `owner`.
- Every clause has an `id` and a `test` (one or more paths to a control or eval task).
- Clauses of kind `intent` and `authority` carry `approved: <date>` or are treated as drafts.

### 2. `skillc contracts <collection>`: static checks across a whole collection

Each rule has committed bad and good cases under `controls/`, so `skillc selftest` proves the rule can report either verdict:

| Rule | Reports BAD when | Bad case |
|---|---|---|
| `contract-shape` | the block doesn't parse, or a required field is missing | a contract with no `intent` |
| `clause-backed` | a clause has no `test`, or its test path doesn't exist | a `provides` clause with no test (**unbacked**) |
| `negative-backed` | a `never` or `authority` clause has no bad case among its tests | a `never` backed only by a good case |
| `handoff-bilateral` | a `consumes` names a clause that no contract `provides` | `consumes: eli5.section-c@2` where nothing provides it |
| `handoff-version` | a `consumes` version differs from the provider's current version | provider at `@3`, consumer still at `@2`, **the lanes-miss case** |
| `reader-exists` | a `provides.readers` entry names no contract and isn't `owner` | `readers: [flow-plan-recrod.approve]` (typo) |
| `scope-owned` | a `scope.out` item isn't in any contract's `scope.in` | an `out` duty nobody owns (an **orphan**) |
| `duty-single-owner` | two contracts list the same `scope.in` id | two skills both owning `eli5.section-c` |
| `approval-present` | an `intent` or `authority` clause has no `approved` date (warn only, never error) | an unapproved intent clause |

Output: one verdict line per contract and a `CONTRACTS:` summary line. A collection with **no** contracts reports `CONTRACTS: none declared`, never `0 problems`.

### 3. A worked example, committed as test material, not shipped

`evals/subjects/contracts-example/` holds a small fixture collection with three skills: one composite and two parts. It is modelled on `/flow:eli5` -> `/flow:auto` and includes the exact `@2`/`@3` version mismatch. Running `skillc contracts` on it must report `handoff-version` BAD. With the version fixed, it must report GOOD.

## Acceptance

- [ ] `docs/specs/contracts.md` documents the format, including the both-sides rule and the "every clause needs a test that can fail" rule.
- [ ] Every rule in the table has committed bad and good cases. `skillc selftest` shows each one reporting BAD on its bad case and GOOD on its good case, with the verdicts quoted in the PR.
- [ ] The fixture collection reports `handoff-version` BAD at the mismatch and GOOD once it's fixed. Both runs are shown in the PR.
- [ ] Running on a collection with no `CHARTER.md` files prints `CONTRACTS: none declared` and exits with its own code (not 0), which is documented.
- [ ] Running on CPP at a pinned revision, with no contracts written yet, reports `none declared`. This shows the command runs on a real collection without inventing findings.

## Out of scope

- Writing contracts for CPP skills. That's round 1 of the gauntlet, done with the owner, starting with `/flow:eli5` and `/flow:auto`.
- Drafting contracts from observed behaviour, and the meaning-based overlap view. Both need model calls and have their own negative control (see #718).
- Running the tests that clauses point to. That belongs to rounds 3 and 4. This issue only checks that each test exists and that each `never` or `authority` clause has a bad case.

Refs #718, #719. Context: cooneycw/claude-power-pack#1830.

🤖 Generated with [Claude Code](https://claude.com/claude-code)


<!-- end of body -->
