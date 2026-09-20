# Evaluation work

The current roadmap is [PLAN.md](../PLAN.md), with the
[facility specification](../docs/specs/evaluation-facility/spec.md),
[interface contracts](../docs/specs/evaluation-facility/interfaces.md) and
[evaluation protocol](../docs/specs/evaluation-facility/protocol.md).

No behavioral runner is implemented here yet. The former example plugin command
and YAML were unverified research, not an executable contract. Backend selection
now requires a conformance investigation, starting with the pinned Coder Eval
research. This directory does not promise compatibility with a particular CLI.

Static validity, skill invocation and successful delivery are distinct measurements.
Matched with/without comparisons test benefit on the selected tasks. Equal results
on a small sample do not prove a skill has no value. Every authoritative grader
needs known-good/bad controls, and the evaluator must detect its own broken checks.
