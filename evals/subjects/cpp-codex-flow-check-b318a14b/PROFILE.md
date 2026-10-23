# Profile: CPP Codex `flow-check`, at `b318a14b` (#529)

- Declaration: [profile.json](profile.json), the machine form; this page explains it
- Subject: [subject.json](subject.json), this profile's own pin
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-23 (#529)
- Snapshot: [`tests/fixtures/profile-cpp-codex-flow-check-b318a14b/`](../../../tests/fixtures/profile-cpp-codex-flow-check-b318a14b/README.md), with provenance and the upstream licence

Regenerate the evidence with:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-check-b318a14b/profile.json \
  --repo <claude-power-pack checkout at b318a14b> \
  --out evals/subjects/cpp-codex-flow-check-b318a14b/evidence/inventory.json --overwrite
```

## Pin

| Identity | Value |
|---|---|
| Source | `github.com/cooneycw/claude-power-pack` at `b318a14b9e7935f2c50c0940144a5ff0ff9389ed` (v10.0.0, `main` on 2026-10-23), MIT |
| Why this revision | CPP #1532 needs flow-check's content after #1497 (the lib/cicd closure, `c8d9ba94`). `c8d9ba94` is an ancestor of `b318a14b` and not of `ca3030d`. The one flow-check change after it is `e53132f3` (#1529). Accepted by the orchestrator (#529, Step 3) |
| Re-pin trigger | a merged CPP #1542 fix changes flow-check's gate call text, so it needs a NEW profile directory |
| Treatment | **targeted** (`flow-check`), **product** question |
| Runtime | `cpp-codex-flow-check-b318a14b`, an extra profile runtime under policy B (`skillc/runtime-policy-extra.json`). `pyproject.toml` and `uv.lock` changed since `ca3030d`, so it is not shared. The primary, cicd and `ca3030d` runtimes are unchanged |
| Client | `codex` 0.157.1 |

## The gate map, re-read at this pin

`reference.md` prescribes two calls, both BARE and cwd-relative (CPP #1408):

| reference.md | argv after the gate | witnessed gate |
|---|---|---|
| Step 2, `:54` | `--plan check --evidence flow-check` | `flow-check-plan` |
| Step 5, `:126` | `--check-summary` | `flow-check-summary` |

The exit-127 fallback (`:57-58`) names `${CLAUDE_PLUGIN_ROOT}/scripts/flow-finish-gate.sh`, else "the CPP-checkout copy".

**Routes the population offers, and how each is witnessed.**
- **The bundled copy** `.codex/skills/flow-check/scripts/flow-finish-gate.sh` is the `gate_entrypoint`, declared bundled. It runs from a root-owned mirror of the skill's `scripts/`, proven against the skill's own `SHA256SUMS`, and is witnessed as `bundled:flow-check` by `docker/fixture-service/flow-check-bundled-gate-shim.py`.
- **The checkout copy** `Projects/claude-power-pack/scripts/flow-finish-gate.sh` is declared in `checkout_gate_entrypoints` (orchestrator D1). It runs from a mirror proven against the verified closure digests, because a checkout ships no skill manifest. It is witnessed as `checkout:flow-check`.
- **The bare call from a target worktree** never reaches a shim: the shell exits 127 (measured in the pinned image, #529). It reads `not-observed`.
- **Any other argv** through a witnessed copy is refused with exit 125 and counted (#279).
- **No `~/.claude/scripts`.** At this pin `SKILL.md` and `reference.md` name no installed helper. Agents choose the installed gate when it exists (7/7 flow-auto attempts at `ca3030d`, #529), so supplying one would hide CPP #1542.

## What changed from `86641e8`

The closure went from 97 files to 71 (computed from the two committed inventories, by installed path and digest).

- **Added (3):**
  - `.codex/skills/flow-check/PROVENANCE.md`;
  - the checkout's `scripts/flow-finish-gate.sh` and `scripts/gate-lib.sh`, which make the fallback route exist and be witnessed.
- **Removed (29):**
  - the three `~/.claude/scripts` helpers;
  - 26 skill-bundled `lib/cicd` modules: after #1497 the skill bundles only `__init__`, `evidence` and `state`.
- **Changed (20):**
  - the skill's `SKILL.md`, `reference.md`, `SHA256SUMS`, `check-ignored-additions.sh`, `counter-model-receipt.py`, `flow-finish-gate.sh` and `lib/cicd/evidence.py`;
  - the checkout's `lib/cicd` (`cli`, `config`, `evidence`, `manifest`, `outcomes`, `runner`, `steps`, `verify`), `lib/security/modules/gitleaks.py`, `pyproject.toml`, `uv.lock`, `check-ignored-additions.sh` and `counter-model-receipt.py`.
- **Unchanged:** 48.

**Unsupported references.** 13 remain. The 18 that only the `86641e8` skill's full bundled `lib/cicd` reached are gone. New entries:
- `~/.qwen/projects` (#20 comment 6297430101);
- the gate's three `~/.claude/scripts` fallbacks (`:186`, `:211`, `:681`), each taken only when a sibling is missing.

**Checksum preflight.** No installed file matches the checksum signature. The same scan finds the three known consumers in `flow-auto` at `ca3030d`, so the zero is real.
