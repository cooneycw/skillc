# Profile: CPP Codex `flow-check`

- Declaration: [profile.json](profile.json) - the machine form; this page explains it
- Subject: [cpp-codex](../cpp-codex/SUBJECT.md), unchanged - this profile layers on it
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-04 (#265)
- Obligations: #264's flow-check case contract (`evals/workflow-contracts/flow-check/`)

Regenerate the evidence with:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-check/profile.json \
  --repo <claude-power-pack checkout> \
  --out evals/subjects/cpp-codex-flow-check/evidence/inventory.json --overwrite
```

## Pin

| Identity | Value |
|---|---|
| Source | `github.com/cooneycw/claude-power-pack` at `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b` |
| Why this revision | the cpp-codex subject's historical pin, which #264's case contract also pins and cites line numbers in. The profile and the obligation matrix describe the same bytes. |
| Treatment | **targeted** (`flow-check` only), **product** question (the skill as installed, prose plus helpers) |
| Client | `codex` 0.157.1, the subject's own |

`flow-check` changed substantially on CPP's main after this pin (it now bundles
`lib/cicd`). A later pin is a new profile with its own inventory, not an edit
to this one.

## The closure

From `SKILL.md`, the walk reaches:

| Dependency | Kind | Installed at | Reached from |
|---|---|---|---|
| `reference.md` and the four bundled scripts | reference (the skill itself) | `~/.codex/skills/flow-check/` | the selection |
| `flow-finish-gate.sh` | helper | `~/.claude/scripts/` | `reference.md:130` |
| `gate-lib.sh` | helper | `~/.claude/scripts/` | `flow-finish-gate.sh` (transitive) |
| `counter-model-receipt.py` | helper | `~/.claude/scripts/` | `flow-finish-gate.sh` (transitive; finish path only) |
| `pyproject.toml`, `uv.lock`, `lib/cicd`, `lib/security` | library | `~/Projects/claude-power-pack/` | `reference.md:36`, `flow-finish-gate.sh` |
| `scripts/check-ignored-additions.sh`, `scripts/counter-model-receipt.py` | helper | `~/Projects/claude-power-pack/scripts/` | `$CPP_DIR/...` in `reference.md` and the gate |
| python >=3.11, uv, make, git, bash | tool | supplied by the image | command words |
| pydantic, pyyaml (from `uv.lock`) | tool, **external** | resolved by uv | the library |

63 installed files in all; the receipt-style digest of that surface is
`installed_surface.digest` in the inventory. The four bundled scripts are
verified byte- and mode-identical to their upstream `scripts/` sources.
`SKILL.md` and `reference.md` are generated from
`.claude/commands/flow/check.md` by a transform: both digests are recorded and
their freshness is not claimed.

## Declared unsupported

| Reference | Why |
|---|---|
| `/opt/claude-power-pack` | absolute; no disposable home can hold it. The first probe location is supplied instead |
| `~/.claude-power-pack`, `$HOME/.claude-power-pack` | third probe location; the first already succeeds |
| `${CLAUDE_PLUGIN_ROOT}/scripts...` (three spellings) | the Claude Code plugin surface: another client |
| `~/.codex/sessions`, `~/.claude/projects` | live client session stores read by the receipt writer; never materialized |

## Interaction with #264's obligation matrix

#264's case contract declares an `environment_assumption`: a trial home with no
`~/.claude/scripts/flow-finish-gate.sh` and no CPP checkout. Under that
assumption, FC-SECURITY, FC-COMPLETENESS and FC-IGNORED are `NOT_APPLICABLE` in
every arm.

**This profile installs both.** A declaration that materializes it (#266, then
#274) runs in a different environment from the one the contract assumed:

- those three obligations become applicable;
- by the contract's own rule, `applies_when` must be re-evaluated before
  scheduling;
- an arm given this profile and an arm without it are different treatments
  (helper parity), never a matched pair.

Both environments are legitimate. They answer different questions, and the
declaration has to say which one it asks.

The two inventories are cross-checked, not compared by eye. Every file record
here carries its `git_blob`, and `tests/test_profile.py` asserts the
`flow-check` blobs equal those the case contract cites (`reference.md` at
`7419d94`, whose line numbers the obligations quote).

## Client profiles

`codex` is **declared** - described here, not proven. `claude-code`, `browser`,
`security-scanner` and `services` are **unsupported** until their own
readiness proofs (#283, #285, and spec.md section 4 for services). A Codex
inventory says nothing about Claude parity.

## Known limits

- **The library is not traversed.** `lib/cicd` and `lib/security` are Python
  packages whose dependencies are imports, not path text. At this pin they
  import only themselves and PyPI packages; whether they import cleanly in a
  disposable home is #266's proof.
- **PyPI resolution is external.** `uv run --project` resolves pydantic and
  pyyaml from an index on first run, and trials have no network. #266 must
  pre-supply a filled cache or report that gate step unavailable.
- **Tool versions are mostly unpinned by the subject.** Only Python's floor is
  declared at the source. #266 pins the rest in the image.
- **Startup context is declared empty.** CPP's Codex installer at this pin
  writes skill directories only (no `AGENTS.md`, no config). The client's
  listing metadata is the skill's own description, recorded as
  `description_digest`.
