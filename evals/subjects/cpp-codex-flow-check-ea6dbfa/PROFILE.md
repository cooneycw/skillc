# Profile: CPP Codex `flow-check`, re-declared at `ea6dbfa`

- Declaration: [profile.json](profile.json) - the machine form; this page explains it
- Subject: [subject.json](subject.json) - this profile's OWN pin, never `../cpp-codex/subject.json`
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-06 (#265/#287), regenerated 2026-10-07 (#334: the four `tool`-kind dependencies gained explicit `probes` - see below), regenerated again 2026-10-07 (#334 mailbox 5944 fix 1: `tool-pypi-runtime`'s `python-import` probe gained `uv_project`, so the import is checked through the checkout's own `uv` environment, the way the real runner runs it, rather than through a bare system interpreter)
- Obligations: #264's flow-check case contract (`evals/workflow-contracts/flow-check/`) - cites `reference.md` line numbers at the OLDER `85e9b03` pin; this profile's content moved, so those citations describe [the other profile](../cpp-codex-flow-check/PROFILE.md), not this one

**This is a SEPARATE profile from
[`evals/subjects/cpp-codex-flow-check/`](../cpp-codex-flow-check/PROFILE.md),
not an edit to it** - that profile's own PROFILE.md anticipated exactly this:
"`flow-check` changed substantially on CPP's main after this pin... a later
pin is a new profile with its own inventory, not an edit to this one." The
85e9b03 profile, its evidence and #264's citations against its blobs stay
untouched and valid.

Regenerate the evidence with:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-check-ea6dbfa/profile.json \
  --repo <claude-power-pack checkout> \
  --out evals/subjects/cpp-codex-flow-check-ea6dbfa/evidence/inventory.json --overwrite
```

## Pin

| Identity | Value |
|---|---|
| Source | `github.com/cooneycw/claude-power-pack` at `ea6dbfa45f9308ee6ba60f032d8e7031bd6938a1` |
| Why this revision | claude-power-pack#1370 found the `85e9b03` profile stale on both content and dependency axes against current CPP main - a precondition for skillc#287. `ea6dbfa` is current CPP main, confirmed (via `git merge-base --is-ancestor`) to carry #1380's "selective description" fix (`9661967`) as an ancestor. |
| Treatment | **targeted** (`flow-check` only), **product** question (the skill as installed, prose plus helpers) - unchanged from the 85e9b03 profile |
| Client | `codex` 0.157.1, the subject's own - unchanged |

## The closure

From `SKILL.md`, the walk reaches the same shape as the 85e9b03 profile, at
new line numbers (verified by reading the actual `ea6dbfa` source, not
assumed from the old profile's citations):

| Dependency | Kind | Installed at | Reached from |
|---|---|---|---|
| `reference.md` and the bundled scripts (now including `execution-evidence-verify.py`) | reference (the skill itself) | `~/.codex/skills/flow-check/` | the selection |
| `flow-finish-gate.sh` | helper | `~/.claude/scripts/` | `reference.md:54` (`--plan check --evidence flow-check`) and `:117` (`--check-summary`) |
| `gate-lib.sh` | helper | `~/.claude/scripts/` | `flow-finish-gate.sh` (transitive) |
| `counter-model-receipt.py` | helper | `~/.claude/scripts/` | `flow-finish-gate.sh:643-646` (transitive; finish path only - probe order: beside-self, then `~/.claude/scripts`, then `CLAUDE_PLUGIN_ROOT`, then `$CPP_DIR`) |
| `pyproject.toml`, `uv.lock`, `lib/cicd`, `lib/security` | library | `~/Projects/claude-power-pack/` | `reference.md:24`, `flow-finish-gate.sh` |
| `scripts/check-ignored-additions.sh`, `scripts/counter-model-receipt.py`, `scripts/execution-evidence-verify.py` | helper | `~/Projects/claude-power-pack/scripts/` | `$CPP_DIR/...` in `reference.md:138-139,161` and the gate |
| python >=3.11, uv, make, git, bash | tool | supplied by the image | command words |
| pydantic, pyyaml (from `uv.lock`) | tool, **external** | resolved by uv | the library |

`skillc profile diagnose`/`validate` both report **zero problems, closed** at
this pin (27 unsupported references, 10 dependencies). Install-level claims
the 85e9b03 PROFILE.md records (actual host installs, canary isolation,
#303's marker proof) were NOT re-verified at this pin when this profile was
first declared - that re-declaration's bounded scope was reaching zero
unresolved references under `diagnose`, not re-running #266/#274's install
proofs. #266's own work since then confirmed, standalone and against THIS
pin's committed fixture (`tests/fixtures/profile-cpp-codex-flow-check-
ea6dbfa/`, no network): `profile.install()` succeeds (4 tools checked),
`checkout-detection-marker` installs with the exact #303 content, and the
installed `uv.lock` digest matches the fixture's own. The cold-container
run itself - `tests/test_profile_install_cold_container_live.py`, exercising
all of this inside a real `--network none` container with zero bind mounts -
is CODE, reviewed, not yet EXECUTED: no Docker daemon in the implementation
environment, so real-daemon execution remains owed to the operator's
real-Docker runner (#315), same as every other live test in this
repository.

## Declared unsupported (27 entries)

Grouped by mechanism (`profile.json` has the full list, one entry per
reference, each with its own specific reason per orchestrator review):

| Group | Count | Why |
|---|---|---|
| Alternative checkout/plugin locations (carried from the 85e9b03 profile) | 8 | unchanged - see the other profile's PROFILE.md |
| `${CLAUDE_PLUGIN_ROOT}/scripts/flow-finish-gate.sh` | 1 | the exit-127 fallback path (`reference.md:58`) - same "another client's surface" class as the carried entries |
| `lib/cicd/cli.py` print-help-text | 2 | shown to a human only when no Makefile/config is found; never read by the skill |
| `lib/cicd/container.py` generated-Dockerfile literals | 4 | `COPY --from=builder` lines for a DOWNSTREAM project's generated image; never a path on the trial's own host |
| `lib/cicd/manifest.py` + `lib/cicd/steps.py` code comment | 1 | both restate claude-power-pack issue #534's fix; prose in both files, one `unsupported` entry (keyed on the reference string) |
| `lib/cicd/pipeline.py` package-manager cache-path lookup table | 9 | generates OTHER projects' CI cache-key config; never read or written by flow-check |
| `lib/cicd/runner.py` docstring | 1 | explains a cache-default choice (claude-power-pack #534); prose |
| `lib/cicd/steps.py` code comment | 1 | illustrates a regex parsing edge case; never executed |

All 19 of the last five rows are new at this pin (claude-power-pack#1370's 21
unresolved references; one string, `${HOME}/Projects`, occurs in two files
and gets one entry, hence 19 entries for 20 occurrences plus the two carried
`CLAUDE_PLUGIN_ROOT` + checkout-scripts fixes = 21 total resolved).

## Client profiles

Unchanged from the 85e9b03 profile: `codex` **declared**; `claude-code`,
`browser`, `security-scanner`, `services` **unsupported** pending their own
readiness proofs.

## Known limits

- **The cold-container proof's boundary (orchestrator condition, #266).**
  `tests/test_profile_install_cold_container_live.py` proves an OFFLINE
  install from a pin-matched `uv` cache - the cache is pre-warmed from this
  profile's own pinned `uv.lock` at image-build time
  (`docker/profile-cold-install/Dockerfile`), and a run-time digest check
  refuses to trust it if that lockfile ever drifts from the one actually
  being installed. It does NOT prove, and does not claim to prove, how a
  live trial container (which needs the network, for the model API)
  behaves - that remains #237's own path, unchanged by this issue.
- **PyPI resolution is still external to the PROFILE itself.** The offline
  guarantee above comes from the cold-install image's own pre-warmed cache,
  not from anything this profile declares - a caller installing this
  profile WITHOUT that image (the plain host install `tests/test_profile_
  install.py` already proves) still needs the network the first time it
  resolves `pydantic`/`pyyaml` from the lock, exactly as the 85e9b03
  profile's own PROFILE.md already states for itself.

## Regression evidence

`tests/test_cpp_codex_flow_check_redeclare.py`, with a committed real-source
snapshot (`tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa/`, the
`codex/skills/flow-check/` tree plus checkout-root dependency sources at this
pin, trimmed to exactly what diagnosing needs): the 85e9b03 profile's frozen
copy against this snapshot reports the exact set of 20 distinct
unresolved-reference strings (21 occurrences); this profile against the same
snapshot reports zero.

`tests/test_profile_closure_preflight_live.py` (#334): the installed-
closure proof against a REAL container built from `docker/trial` - not a
dedicated test image, since #334's own acceptance claim is about the
production trial image. Currently refuses at preflight in its intact
mode (the image has no `uv`/`make` yet, tracked separately as #343); the
two break modes (`missing-closure`, `tampered-closure`) pass today
regardless, since they prove the preflight's own refusal correctness,
which does not depend on #343.
