# Profile: CPP Codex `flow-auto` at `86641e8`, bundled gate witnessed (#525)

- Declaration: [profile.json](profile.json), the machine form; this page explains it
- Subject: [subject.json](subject.json), the same pin as `cpp-codex-flow-auto-86641e8`
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-22 (#525)

The same closure as [`cpp-codex-flow-auto-86641e8`](../cpp-codex-flow-auto-86641e8/PROFILE.md), file for file, plus two declarations. Regenerate the evidence with:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-auto-86641e8-bundled/profile.json \
  --repo <claude-power-pack checkout at 86641e8> \
  --out evals/subjects/cpp-codex-flow-auto-86641e8-bundled/evidence/inventory.json --overwrite
```

## Why it exists

From CPP #1408 on, a generated Codex skill runs its **bundled** gate, `scripts/flow-finish-gate.sh` in its own skill directory, not the installed `~/.claude/scripts/flow-finish-gate.sh`. The harness only witnessed the installed path, so on any such pin the gate ran unwitnessed (#525).

At `86641e8` the skill still invokes the installed gate. This profile proves the bundled-gate witness end to end before a later pin is studied: the `--rehearse actor-bundled` actor runs the bundled copy, and its run must read witnessed.

It is a separate profile because `cpp-codex-flow-auto-86641e8`'s inventory digest is pinned by approved declarations.

## The two declarations

- **`bundled_gate_entrypoints`:** `.codex/skills/flow-auto/scripts/flow-finish-gate.sh`.
  - The harness mirrors that skill's whole `scripts/` directory root-owned, so the real script's `BASH_SOURCE`-relative siblings are the skill's own.
  - It moves the real gate into the mirror, places the witness shim (with its `_VIA` line set) in its place, and proves the mirror passes `sha256sum -c` against the skill's own `SHA256SUMS`.
  - The in-place skill then fails its checksum on exactly that file. That is a **declared treatment deviation**, in each attempt's record and in the report's headline.
- **`checksum_consumers`:** every installed file matching a checksum-verification signature, each with the reason, measured at this pin, that it does not verify the installed skill on the Step-6 path. A file the preflight finds that is not declared refuses the profile, and the deviation goes back to the orchestrator.
