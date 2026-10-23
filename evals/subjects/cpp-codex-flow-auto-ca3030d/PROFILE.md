# Profile: CPP Codex `flow-auto`, at `ca3030d` (#279 re-pin)

- Declaration: [profile.json](profile.json), the machine form; this page explains it
- Subject: [subject.json](subject.json), this profile's own pin
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-22 (#279)
- Snapshot: [`tests/fixtures/profile-cpp-codex-flow-auto-ca3030d/`](../../../tests/fixtures/profile-cpp-codex-flow-auto-ca3030d/README.md), with provenance and the upstream licence

Regenerate the evidence with:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-auto-ca3030d/profile.json \
  --repo <claude-power-pack checkout at ca3030d> \
  --out evals/subjects/cpp-codex-flow-auto-ca3030d/evidence/inventory.json --overwrite
```

## Pin

| Identity | Value |
|---|---|
| Source | `github.com/cooneycw/claude-power-pack` at `ca3030dbeba4a145166b61d714861f56e92cd034`, MIT |
| Why this revision | the minimal descendant of `86641e8` (25 commits) that carries CPP #1467, the fix for #1453. A Codex implementer can now record `skipped / reviewer-unavailable`; at `86641e8` it could not, which stopped 1 of 2 sizing-3 attempts before the gate. CPP `main` was ruled out: it carries the v10.0.0 release (orchestrator, #279) |
| Treatment | **targeted** (`flow-auto` plus `flow-eli5`), **product** question, the same closure shape as `cpp-codex-flow-auto-86641e8` |
| Runtime | `cpp-codex-flow-auto-ca3030d`, the second supported profile runtime (`skillc/runtime-policy-extra.json`, orchestrator policy B). The 86641e8 runtime and the cicd runtime are unchanged |
| Client | `codex` 0.157.1 |

## What changed from `86641e8`, and what it costs

From CPP #1408 (`50261ddd`), every generated Codex skill runs its **bundled** `scripts/flow-finish-gate.sh`. This profile therefore declares it:

- **`bundled_gate_entrypoints`:** flow-auto's own bundled gate, plus the bundled gates of `flow-check`, `flow-finish` and `flow-merge`. The subject selects `all`, so those skills are delivered too, and each invokes its own copy (#525's delivered-home check). Each is witnessed by the flow-auto shim as `via: bundled:<skill>`.
- **Two declared deviations** (orchestrator, #279):
  1. **Checksum (#525).** Each witnessed bundled copy is replaced by the shim. Its real copy runs from a root-owned mirror verified against the skill's own `SHA256SUMS`, so the installed skill fails that manifest on exactly that file.
  2. **125 parity.** The flow-auto shim's closed map accepts only the bare finish call. A flow-check-shaped call (`--plan check …`, `--check-summary`) through any witnessed copy exits 125 before the channel, exactly as through `86641e8`'s installed-path shim. That is behaviour the subject would not meet in real use, so every such refusal is **counted** in the attempt record and the report's headline, and its S2/S3 are flagged.
- **`checksum_consumers`:** each file that matches the checksum signature in the delivered home, with the reason, measured at this pin, that it does not verify a shimmed skill on the Step-6 path.
- The installed `~/.claude/scripts/flow-finish-gate.sh` stays installed and witnessed (`gate_entrypoint`). Its dependency carries an `unreferenced_reason`: the skill no longer names it, but a subject that still reaches it reads witnessed.
