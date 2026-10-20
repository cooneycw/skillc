# Profile: CPP Codex `flow-auto`, Step-6 witness, at `86641e8`

- Declaration: [profile.json](profile.json) - the machine form; this page explains it
- Subject: [subject.json](subject.json) - the same pin as `cpp-codex-flow-auto-86641e8`'s, selecting
  `flow-auto` and `flow-eli5` only, so a run installs exactly the profile's two skills
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-20 (#287 option 1, PR-B)
- Snapshot: the closure is the same as `cpp-codex-flow-auto-86641e8`'s, so its snapshot
  [`tests/fixtures/profile-cpp-codex-flow-auto-86641e8/`](../../../tests/fixtures/profile-cpp-codex-flow-auto-86641e8/README.md)
  regenerates this inventory too (`tests/test_calibration_287_auto6.py`)

The treatment for #287 option 1: does flow-auto's Step-6 guidance on reading the finish
gate's verdict make an agent report its checks honestly
([`gate-stops-early-auto6`](../../level3/gate-stops-early-auto6/)). Regenerate the evidence with:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-auto-86641e8-step6/profile.json \
  --repo <claude-power-pack checkout at 86641e8> \
  --out evals/subjects/cpp-codex-flow-auto-86641e8-step6/evidence/inventory.json --overwrite
```

## What differs from `cpp-codex-flow-auto-86641e8`

Exactly three fields, and a test fails on any other difference:

- `gate_witness: flow-finish`: the witnessed gate is the bare finish call that
  `reference.md` Step 6 item 2 prescribes (gate `flow-auto-finish`, through
  `docker/fixture-service/flow-auto-gate-shim.py`, #477). A different witness is a
  different treatment, so this is its own profile; the sibling's inventory digest,
  which #434's declarations pin, is unchanged.
- `name` and `notes`.

The selection stays `flow-auto` plus `flow-eli5`, so flow-check's sibling SKIP rule
(its `reference.md:72-73`) is not delivered. Everything else (the closure, the
dependencies, the unsupported references and the D3 fact about the pin) is the sibling's;
see [its page](../cpp-codex-flow-auto-86641e8/PROFILE.md).
