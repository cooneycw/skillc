# Second-collection conformance, through the real Docker backend (#11)

Issue #11 asks whether skillc's evaluation interfaces are generic. Showing that
they work for CPP is not enough, so the same interfaces must also work for a
second collection, independently authored and laid out differently. The two
declared subjects are [cpp-codex](../subjects/cpp-codex/SUBJECT.md) (the whole
74-skill pack) and [mattpocock-skills](../subjects/mattpocock-skills/SUBJECT.md)
(`tdd`, `diagnosing-bugs`).

**Executed.** [`evidence/README.md`](evidence/README.md) holds the live
output. [`run-manifest.json`](run-manifest.json) cites that output line by
line, and `tests/test_second_collection_conformance.py` fails if a cited line
is missing from the evidence or is attributed to the wrong collection.

## What ran, per collection

1. **`skillc demo --subject <name>`** (no model call; the operator's #10 run
   at main 8e06030). The collection is cloned at its pin and installed into a
   real container. Every installed file is re-hashed inside the container
   against the installation receipt. The client's own listing then reports
   which skills it discovered. Both collections: 10/10 MET, digests matched,
   every selected skill discovered.
2. **`skillc collection-run <name>`** (one real codex agent attempt; #11,
   2026-09-27). The same Level 1 task (`evals/level1/slug-small-fix`), the
   same client (codex-cli 0.157.1), the same contract
   (`agent_trial.run_one_attempt`, skill-free canary mode) and the same grader
   (the fixture's `grader.json`, in a separate `network=none` container). The
   only difference is which collection is installed in the agent's home. Both
   collections: captured, graded **PASS**.

The control, a run with the credential deliberately absent, was `unavailable`
and blocked before the agent launched, with exit 1.

## Acceptance, against #11's four bullets

| Bullet | Status | Backed by |
|---|---|---|
| 1. Independent collection, different layout, compatible scope, provenance and licence | MET | `evals/subjects/mattpocock-skills/SUBJECT.md` (#71) |
| 2. Same client, Level 1 fixture, contract and grader; installation contained in the adapter | MET | evidence section 2; the subject declaration is data, and `skillc/collection_conformance.py` names no subject |
| 3. No project-name branch in the core; unsupported formats refused before selection | MET | `tests/test_materialize.py` genericity guard (every `skillc/*.py`, #94) and `test_a_malformed_subject_declaration_is_refused` |
| 4. Conformance evidence for both collections and a bounded compatibility statement; no second benchmark | MET | evidence sections 1-2, and the statement below; one attempt per collection on the existing canary |

## The bounded compatibility statement

**Shown by execution, for both collections, on one host:**

- The collection installs intact into a real trial container. The files are
  re-hashed in the container, and the client's own listing discovers every
  selected skill.
- A real agent works the Level 1 canary with that collection installed. The
  pipeline carries it from launch through transcript, prompt-delivery check,
  liveness canary, capture and independent grading to a verdict, through the
  same code path for both collections.

**Shown by static proof, not by execution:** no core module carries a
subject-name branch (the #94 AST guard). Neither collection can have been
special-cased.

**Not shown, and not claimed:**

- **Which collection helps an agent more, or whether either helps.** Both
  passed a ceiling-prone canary once each. This is not a comparison; that
  question belongs to #12's matched pilot.
- **Skill selection.** In the skill-free run the agent invoked
  `diagnosing-bugs` on its own. This is one observation from Codex's
  heuristic detection, not a measurement; that question belongs to #26.
- **Claude Code.** Both subjects declare codex. The Claude Code arm, with
  one run per collection on the same task, contract and grader, is
  [evals/claude-code-agent-arm](../claude-code-agent-arm/README.md) (#124).
- **mattpocock-skills' 23 unselected skills.** This includes the 14 hidden by
  invocation policy, for which discovery is not policy-aware; the gap is in
  the Nit Store (#20).
- **Contained egress.** By owner ruling (recorded on #11), the agent container
  had open network (`agent_network=bridge`) so that it could reach its
  provider. The grading container stayed `network=none`.
- **Repeatability, or a third collection.** One attempt per collection, two
  collections. #11 asks for no more ("do not build a second large benchmark").

The agent runs used the operator's normal Codex subscription login, quoted
from the ruling on #98 and ADR 0005 rule 6: "Normal Claude and codex". They
were not metered API spend and not gated by the #12 $5 judge-call ceiling.
