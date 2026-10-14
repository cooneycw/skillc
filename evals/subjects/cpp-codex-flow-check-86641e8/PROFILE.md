# Profile: CPP Codex `flow-check`, repinned at `86641e8`

- Declaration: [profile.json](profile.json) - the machine form; this page explains it
- Subject: [subject.json](subject.json) - this profile's OWN pin
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-14 (#376)
- Previous pin: [`cpp-codex-flow-check-ea6dbfa`](../cpp-codex-flow-check-ea6dbfa/PROFILE.md), unchanged

**A SEPARATE profile from the `ea6dbfa` one, not an edit to it** - the rule
the `85e9b03` profile set and #265/#330 followed. The `ea6dbfa` profile, its
inventory (`profile.inventory_digest` `sha256:eb9cad6f...`), the #203 results
and the #270 stage-sample evidence recorded against it stay as they are.

Regenerate the evidence with:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-check-86641e8/profile.json \
  --repo <claude-power-pack checkout> \
  --out evals/subjects/cpp-codex-flow-check-86641e8/evidence/inventory.json --overwrite
```

## Pin

| Identity | Value |
|---|---|
| Source | `github.com/cooneycw/claude-power-pack` at `86641e817711d8a7746270745a5dfa7cacf04b0c` |
| Why this revision | #376 needs the stage states an aggregate gate reports after an early stop. CPP `8e0a34fb` gives NOT_RUN its own `flow-check` report state (`reference.md`: "NOT_RUN - Never executed because an earlier step in the same aggregate..."), distinct from SKIP; `ea6dbfa` predates it. `86641e8` contains `8e0a34fb` (`git merge-base --is-ancestor`) and is the next study pin CPP itself recorded (claude-power-pack `0c6ffd7a`: "CPP 86641e8 is the next study's pin, when skillc will cut cpp-codex-flow-check-86641e8"). |
| Not CPP main | CPP main had moved on to `63e06985`, which also drops the skill's bundled `lib/cicd` copy (#1408). That reshapes the closure and belongs to its own later profile. |
| Treatment | **targeted** (`flow-check` only), **product** question - unchanged |
| Client | `codex` 0.157.1 - unchanged |

## What changed from `ea6dbfa`

The closure has **the same shape**: 96 files at both pins, none added or
removed, so `profile.json` keeps every dependency, probe, `gate_entrypoint`
and all 27 unsupported references. 21 closure files changed content:

- `reference.md` and `scripts/SHA256SUMS` in the skill;
- `lib/cicd/{evidence,failure_patterns,outcomes,pipeline,runner,state}.py`, both the
  checkout copy and the skill's bundled mirror;
- `lib/security/{cli,orchestrator,modules/secrets}.py`;
- `check-ignored-additions.sh` and `counter-model-receipt.py`, checkout and bundled.

`pyproject.toml` and `uv.lock` are **byte-identical** at both pins, so the
offline runtime supply resolves the same packages; only its `runtime_id` and
`subject_revision` move. `lib/cicd/steps.py` (the skip/aggregate mechanism
`evals/level3/*/PROVENANCE.md` proved at `ea6dbfa`) is unchanged.

`profile.json` differs from the `ea6dbfa` declaration in its `notes` and in
six `reference.md` line citations, re-read against this pin's source. The
`ea6dbfa` declaration's copies of those citations still carried `85e9b03`
line numbers; its PROFILE.md table had them right.

## The closure

| Dependency | Kind | Installed at | Reached from |
|---|---|---|---|
| `reference.md` and the bundled scripts | reference (the skill itself) | `~/.codex/skills/flow-check/` | the selection |
| `flow-finish-gate.sh` | helper | `~/.claude/scripts/` | `reference.md:54` (`--plan check --evidence flow-check`) and `:126` (`--check-summary`) |
| `gate-lib.sh` | helper | `~/.claude/scripts/` | `flow-finish-gate.sh` (transitive) |
| `counter-model-receipt.py` | helper | `~/.claude/scripts/` | `flow-finish-gate.sh:643-646` (transitive; finish path only) |
| `pyproject.toml`, `uv.lock`, `lib/cicd`, `lib/security` | library | `~/Projects/claude-power-pack/` | `reference.md:24`, `flow-finish-gate.sh` |
| `scripts/check-ignored-additions.sh`, `scripts/counter-model-receipt.py`, `scripts/execution-evidence-verify.py` | helper | `~/Projects/claude-power-pack/scripts/` | `$CPP_DIR/...` in `reference.md:147-148,170` and the gate |
| python >=3.11, uv, make, git, bash | tool | supplied by the image | command words |
| pydantic, pyyaml (from `uv.lock`) | tool, **external** | resolved by uv | the library |

`skillc profile diagnose`/`validate` both report **zero problems, closed** at
this pin (27 unsupported references, 10 dependencies).

The declared-unsupported groups, the client profiles and the known limits
are those the [`ea6dbfa` PROFILE.md](../cpp-codex-flow-check-ea6dbfa/PROFILE.md)
records; nothing in this pin's delta changes them.

## What moved to this profile

The live runtime supply (`skillc/runtime-policy.json`, `docker/profile-trial/`),
the live tests that build or install it, and the two #287 draft declarations
(approvals still `null`) select this profile. There is one runtime policy, so
an `ea6dbfa` live attempt no longer receives runtime supply; its evidence
stays readable as recorded.

Not established here: a trial image built from this pin, its receipt, or a
real-Docker run against it. Those belong to the #315 re-certification after
this change merges.

## Regression evidence

`tests/test_cpp_codex_flow_check_86641e8.py`, with the committed snapshot
`tests/fixtures/profile-cpp-codex-flow-check-86641e8/` (the same 97 paths as
the `ea6dbfa` snapshot, filled from this pin):

- this profile is clean against its own snapshot;
- this snapshot defines NOT_RUN, and the `ea6dbfa` snapshot does not (red case);
- every live selector names this subject; one stale selector fails it;
- the degraded #287 arm's `mutated_digest` is recomputed from this pin's
  `reference.md`, and the same method over `ea6dbfa` gives the previous value;
- the `ea6dbfa` inventory digest is unchanged.
