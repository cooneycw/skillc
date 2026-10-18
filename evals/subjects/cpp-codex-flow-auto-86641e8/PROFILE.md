# Profile: CPP Codex `flow-auto`, at `86641e8`

- Declaration: [profile.json](profile.json) - the machine form; this page explains it
- Subject: [subject.json](subject.json) - this profile's own pin
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-17 (#434 PR 2b)
- Snapshot: [`tests/fixtures/profile-cpp-codex-flow-auto-86641e8/`](../../../tests/fixtures/profile-cpp-codex-flow-auto-86641e8/README.md), with provenance and the upstream licence

The flow:auto treatment for #434, the clean-project case. Regenerate the evidence with:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-auto-86641e8/profile.json \
  --repo <claude-power-pack checkout> \
  --out evals/subjects/cpp-codex-flow-auto-86641e8/evidence/inventory.json --overwrite
```

## Pin

| Identity | Value |
|---|---|
| Source | `github.com/cooneycw/claude-power-pack` at `86641e817711d8a7746270745a5dfa7cacf04b0c`, MIT |
| Why this revision | the pin `cpp-codex-flow-check-86641e8` and `cpp-codex-cicd-86641e8` already study, so the three treatments read one revision |
| Treatment | **targeted** (`flow-auto` plus `flow-eli5`, which flow-auto's Step 3 reads), **product** question |
| Client | `codex` 0.157.1 |

A separate profile, not an edit to either sibling: a different selection is a
different treatment, with its own inventory.

## What the closure holds

- the two skills' bundled files;
- the flow helpers `reference.md` calls at `~/.claude/scripts/<name>`: 17 scripts,
  installed from the checkout's `scripts/`. The skill bundles byte-identical
  copies, declared as `mirrors`;
- the CPP checkout at `~/Projects/claude-power-pack` (libraries, the
  checkout-run scripts, the synthetic detection marker), as the flow-check
  profile supplies it;
- the same four environment tools as flow-check (python, uv, the PyPI runtime,
  make/git/bash).

`gate_entrypoint` is the installed finish gate that Step 6 item 2 calls bare.
The harness witnesses it through `docker/fixture-service/flow-auto-gate-shim.py`
(gate `flow-auto-finish`).

## Unsupported, and why (34)

- Claude Code's plugin surface (`CLAUDE_PLUGIN_ROOT`, 11 spellings): another
  client's profile, the exit-127 fallback after the installed path.
- Alternative checkout locations (`~/.claude-power-pack`, `/opt/...`): the
  probe order finds `~/Projects/claude-power-pack` first.
- `~/Projects` and `$HOME/Projects`: flow-start-resolve's `PROJECT` lookup root.
  The task runs with no `PROJECT`, inside the fixture checkout.
- Client state and configuration: session stores, Claude Code settings and
  commands, the operator's private instructions, a fleet roster, a Claude Code
  permission hook.
- `codex-skill-sync.py`'s install-time paths: the harness installs the
  selected skills itself.
- The AWS CLI: services and network are not provided.
- Three illustrative example paths in invocation text.
- `~/.codex/skills/flow-eli5/SKILL.md`, which **is supplied** by the selection
  itself. The validator cannot resolve a reference against a selected skill's
  own install path, and a dependency there would be a second owner of the
  skill's file. The entry's reason says so; nothing is missing from the trial.

## A measured fact about this pin (D3)

`codex/skills` at `86641e8` ships no code-review skill. A codex-driven
flow:auto that reaches Step 6 therefore improvises its counter-model review, as
a raw `codex exec` or a `command -v codex` probe. In a trial, the nested-codex
guard makes that call unavailable: exit 3. The pinned `counter-model-receipt.py`
reads the result as `skipped` / `reviewer-unavailable`
(`tests/test_cpp_codex_flow_auto_86641e8.py`). Reported to CPP's nit store
(claude-power-pack#864).
