# ADR 0001: Every check ships a redcase

- Status: Accepted
- Date: 2026-09-15

## Context

`skillc` exists because skills are shipped with nothing that can refuse them. The
obvious failure mode for a project like this is to become the thing it was built
to prevent: a checker that reports green because it is blind, not because the
input is clean. Those two greens are indistinguishable at the point of reading,
and the difference surfaces later, to someone relying on the result.

Re-reading a rule does not settle this. Re-reading checks what the rule MEANT.
Only a known-bad input checks what it CAN say.

## Decision

A rule is not shipped until a committed input exists that makes it report the
other verdict.

- Every rule owns `controls/<rule-id>/bad/` and `controls/<rule-id>/good/`.
- `skillc selftest` runs each rule against that pair. A rule silent on its
  known-bad input reports `BLIND`; a rule firing on its known-good input reports
  `NOISY`; both fail the run.
- A rule with no committed control reports `UNPROVEN` and fails. Absence of a
  control is never read as a pass.
- A control side with no input reports `EMPTY` and fails: a rule silent on
  nothing has not been shown silent on a good input (#2).
- Only findings raised BY the rule under test count as red. A semantic rule's
  control inputs must parse, or `UNPARSED` fails the run - otherwise a parse
  failure stands in for the rule. A parser rule (`frontmatter`,
  `record-envelope`) has the explicit opposite expectation: its known-bad input
  must include one that does not parse (#2).
- The pairing is also a test (`tests/test_checks.py`), so a rule cannot go blind
  between releases without the suite noticing.
- `skillc selftest` is itself under a negative control: a test blinds a rule on
  purpose and asserts the harness says so. A selftest that cannot fail proves
  nothing about the rules it blesses.

## Bound

This applies to rules, whose verdicts are consumed by a decision that will not
re-derive the fact. It does not extend to every internal helper: a parser bug
that the rule tests would catch does not need its own committed case, because its
correctness is not individually load-bearing.

## Consequences

Adding a rule costs two fixtures. That is the intended price, and it is the
cheapest moment to pay it: if you cannot name the input that makes a rule fire,
you have just learned the rule is not ready.

`skillc check` on a tree containing no `SKILL.md` exits non-zero rather than
reporting success, for the same reason: an empty population must not render as a
clean one.
