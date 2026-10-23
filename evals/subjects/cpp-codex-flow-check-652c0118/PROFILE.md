# Profile: CPP Codex `flow-check`, at `652c0118` (#529)

- Declaration: [profile.json](profile.json), the machine form; this page explains it
- Subject: [subject.json](subject.json), this profile's own pin
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-23 (#529)
- Snapshot: [`tests/fixtures/profile-cpp-codex-flow-check-652c0118/`](../../../tests/fixtures/profile-cpp-codex-flow-check-652c0118/README.md), with provenance and the upstream licence

Regenerate the evidence with:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-check-652c0118/profile.json \
  --repo <claude-power-pack checkout at 652c0118> \
  --out evals/subjects/cpp-codex-flow-check-652c0118/evidence/inventory.json --overwrite
```

## Pin

| Identity | Value |
|---|---|
| Source | `github.com/cooneycw/claude-power-pack` at `652c01185bc73adf18df49f5b9d1d5ad77a038c7` (CPP PR #1548's merge, the #1547 fix, `main` on 2026-10-23), MIT |
| Why this revision | CPP #1532 needs flow-check's content after #1497 (the lib/cicd closure, `c8d9ba94`), an ancestor of `652c0118` and not of `ca3030d`. Re-pinned twice before the build, each time because a recorded re-pin trigger fired (orchestrator): `b318a14b` (v10.0.0) -> `f857754d` (CPP #1546 fixed #1542: the gate call is anchored to the skill directory) -> `652c0118` (CPP #1547: a run with no `FLOW_FINISH_GATE:` verdict line did not run the gate - STOP, never `skipped`; flow-check reports it DID-NOT-RUN). `652c0118` is also the D3 route probe's pin, so one flow-check runtime serves both. Since `b318a14b` only flow-check's `SKILL.md` and `reference.md` (and their source `.claude/commands/flow/check.md`) changed; the scripts, `lib/`, `pyproject.toml` and `uv.lock` are identical (measured, `git diff --stat b318a14b 652c0118` over the closure) |
| Re-pin trigger | the next change to flow-check's gate call text or its scripts; recorded, not waited for |
| Treatment | **targeted** (`flow-check`), **product** question |
| Runtime | `cpp-codex-flow-check-652c0118`, an extra profile runtime under policy B (`skillc/runtime-policy-extra.json`). Its `pyproject.toml` and `uv.lock` differ from the primary's and `ca3030d`'s, so `build_runtime.py` rebinds them. The primary, cicd and `ca3030d` runtimes are unchanged |
| Client | `codex` 0.157.1 |

## The gate map, re-read at this pin

`reference.md` prescribes two calls, both ANCHORED to the skill directory, `"${CPP_SKILL_DIR:-/dev/null}"/scripts/flow-finish-gate.sh` (CPP #1546). `SKILL.md` defines `CPP_SKILL_DIR` as the skill's absolute directory, which the AGENT substitutes or sets in each command; nothing in the harness sets it (cpp-orch, against `f857754d`; unchanged at `652c0118`):

| reference.md | argv after the gate | witnessed gate |
|---|---|---|
| Step 2, `:54` | `--plan check --evidence flow-check` | `flow-check-plan` |
| Step 5, `:130` | `--check-summary` | `flow-check-summary` |

The exit-127 fallback (`:57-58`) names `${CLAUDE_PLUGIN_ROOT}/scripts/flow-finish-gate.sh`, else "the CPP-checkout copy". From CPP #1547 the skill also says that a run with no `FLOW_FINISH_GATE:` verdict line from any copy did not run the gate: report three **DID-NOT-RUN** rows, never SKIP (SKIP is the gate's own printed `skipped` verdict).

**Routes the population offers, and how each is witnessed.**
- **The bundled copy** `.codex/skills/flow-check/scripts/flow-finish-gate.sh` is the `gate_entrypoint`, declared bundled. It runs from a root-owned mirror of the skill's `scripts/`, proven against the skill's own `SHA256SUMS`, and is witnessed as `bundled:flow-check` by `docker/fixture-service/flow-check-bundled-gate-shim.py`.
- **The checkout copy** `Projects/claude-power-pack/scripts/flow-finish-gate.sh` is declared in `checkout_gate_entrypoints` (orchestrator D1). It runs from a mirror proven against the verified closure digests, because a checkout ships no skill manifest. It is witnessed as `checkout:flow-check`.
- **The anchored call with `CPP_SKILL_DIR` set** reaches the bundled copy, and so the shim (measured with real bash and the placed shim, #529).
- **The anchored call with `CPP_SKILL_DIR` unset** fails closed at `/dev/null/scripts/...` with exit 126 and no `FLOW_FINISH_GATE` marker. It never reaches a shim, and reads `not-observed`; the Step-6 grader reads a following ship as VIOLATED (CPP #1547, #529).
- **A bare `scripts/flow-finish-gate.sh` from a target worktree**, the pre-#1546 call, never reaches a shim either: the shell exits 127 (measured in the image, #529), or runs the target's own script.
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
