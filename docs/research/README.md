# Evaluation research

- [Coder Eval contract handoff, September 20, 2026](coder-eval-skillc-contract-handoff-2026-09-20.md):
  inspected integration and result contracts, evidence-verification limits, and
  proposed reuse boundaries for skillc.
- [Coder Eval lessons and contract map, September 26, 2026](coder-eval-lessons.md):
  what skillc takes as ideas and what it avoids, after
  [ADR 0003](../decisions/0003-no-external-evaluation-runtime.md) ruled out a
  runtime dependency. Static inspection only.
- [config-drift-checker lessons and concept map, September 26, 2026](config-drift-checker-lessons.md):
  provenance, adopted and declined ideas from
  [jameskomo/config-drift-checker](https://github.com/jameskomo/config-drift-checker) at
  `0aca62b` (FSL-1.1-Apache-2.0), with their skillc owners. Static reading only.
- [mattpocock/skills lessons and concept map, September 26, 2026](mattpocock-skills-lessons.md):
  provenance and adopted concepts from
  [mattpocock/skills](https://github.com/mattpocock/skills) at `c55ee46` (MIT),
  plus the static scan baseline at that commit and which warnings are skillc
  false positives. Static reading and one `skillc check` execution.
- [CPP incident catalogue, September 30, 2026](cpp-incident-catalogue.md):
  claude-power-pack's escaped-failure record, classified item by item. It
  ranks the classes and shortlists five candidate task designs for #203, in
  answer to #204's calibration report (#211). Counts are re-derivable from
  `cpp-incident-catalogue/` with `scripts/cpp_incident_counts.py`.

## Provenance and limits

The handoff was supplied by the owner-authorized peer Codex session. It reports
static inspection, not executed trials or a complete security audit. Proposed
features are distinguished from observations; importing this document does not
accept an architecture or authorize implementation.

Inspected source: [UiPath/coder_eval at d960de1](https://github.com/UiPath/coder_eval/tree/d960de1c433a1b050d2509f04d94a60e3cabaaf0),
package version 0.12.4, by [UiPath](https://github.com/UiPath), licensed
[Apache-2.0](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/LICENSE).
Source-file references in the handoff are relative to
`src/coder_eval/` unless otherwise stated. Machine-local snapshot and earlier
handoff paths are historical provenance, not repository dependencies.

Original file: `<operator-home>/Projects/reports/coder-eval-skillc-contract-handoff-2026-09-20.md`.
Original SHA256: `1a9a287f44ae25f4fde81911017d408e9f7ddc36445424f9abffe53ab04b2ca2`.

The archived copy normalizes Unicode em and en dashes to ASCII hyphens to follow
AGENTS.md. Its content is otherwise unchanged; the original checksum therefore
identifies the source file, not the normalized copy.

## Harbor

skillc's separate-verifier design ([#9](https://github.com/cooneycw/skillc/issues/9)),
and the split of task instructions, environment and verification in
[protocol section 9](../specs/evaluation-facility/protocol.md#9-research-grounding),
take ideas from Harbor. The project is
[harbor-framework/harbor](https://github.com/harbor-framework/harbor), by the
`harbor-framework` GitHub organization (the older `laude-institute/harbor`
address redirects there), licensed Apache-2.0, with its documentation at
[harborframework.com](https://harborframework.com/).

What was read is two documentation pages, on 2026-09-20:
[task overview](https://docs.harborframework.com/core-concepts/tasks/overview) and
[separate verifier](https://docs.harborframework.com/core-concepts/tasks/separate-verifier).
**No Harbor source was inspected, so no commit is pinned.** The pages are
living documents; a later reader may see different text. For identification only,
the repository's default branch was at `d10ac31727bc4428cf976e7a8a8e5328c9055928`
when this entry was written (2026-09-26). That is not the version the ideas came from.

Per [ADR 0003](../decisions/0003-no-external-evaluation-runtime.md), skillc takes
ideas, not code, from Harbor, and a design note that introduces one names Harbor
and links this entry.
