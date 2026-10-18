# Profile: CPP Codex local CI/CD (`cicd-*`), at `86641e8`

- Declaration: [profile.json](profile.json) - the machine form; this page explains it
- Subject: [subject.json](subject.json) - the same pin as `cpp-codex-flow-check-86641e8`
- Validator: `skillc profile validate` ([profiles spec](../../../docs/specs/evaluation-facility/profiles.md#the-local-cicd-profile-280))
- Evidence: [evidence/inventory.json](evidence/inventory.json), generated 2026-10-17 (#280) from a real git checkout at the pin
- Snapshot: `tests/fixtures/profile-cpp-codex-cicd-86641e8/` (55 files), reproducible with `scripts/freeze_cpp_fixture.py`

The local CI/CD capability profile for ONE Python project: what CPP's
`project:init` and `cicd:*` skills actually install, generate and run, so the
evaluations that build on it (#281, #282) exercise CPP's real integration
rather than a toy. A separate profile; the flow-check profile, its evidence and
every receipt bound to it are untouched.

Regenerate the evidence and check the snapshot with:

```bash
skillc profile validate evals/subjects/cpp-codex-cicd-86641e8/profile.json \
  --repo <claude-power-pack checkout> \
  --out evals/subjects/cpp-codex-cicd-86641e8/evidence/inventory.json --overwrite
python3 scripts/freeze_cpp_fixture.py check profile-cpp-codex-cicd-86641e8 --cpp <claude-power-pack checkout>
```

## Pin and selection

| Identity | Value |
|---|---|
| Source | `github.com/cooneycw/claude-power-pack` at `86641e817711d8a7746270745a5dfa7cacf04b0c` |
| Why this revision | The flow-check study pin. Sharing it means sharing that pin's locked PyPI runtime (pydantic, pyyaml) instead of building a second one. |
| Treatment | **targeted** (`cicd-init`, `cicd-check`, `cicd-health`, `cicd-smoke`, `cicd-verify`, `cicd-pipeline`), **product** question |
| Not selected | `cicd-container`, `cicd-woodpecker`, `cicd-infra-*`: Docker, a Woodpecker server or a cloud account. `cicd-help` only prints. |
| Client | `codex` 0.157.1 |

## The closure

| Dependency | What it is | Why |
|---|---|---|
| `checkout-libraries` | `lib/cicd`, `pyproject.toml`, `uv.lock` at `Projects/claude-power-pack` | every skill runs `PYTHONPATH="$CPP_DIR:$PYTHONPATH" uv run --project "$CPP_DIR" python -m lib.cicd <command>` |
| `checkout-detection-marker` | synthetic `CLAUDE.md` | each skill's `Locate CPP Source` step tests `-f "$dir/CLAUDE.md"`; marker text, not CPP's agent instructions (#303) |
| `checkout-templates` | `templates/Makefile.example`, `templates/makefiles/`, `templates/cicd.yml.example` | `cicd-init` copies a framework Makefile from there and generates the project's cicd.yml from the cicd template (named only as a bare relative path, so declared, not discovered); `cicd-check` points at the Makefile example |
| `tool-python`, `tool-uv`, `tool-make-git-bash`, `tool-pypi-runtime` | as in the flow-check profile | the same runtime |
| `tool-curl` | `curl >=7.0`, supplied by the cicd runtime layer | `lib/cicd/health.py` shells out to `curl` for every HTTP health check; without it each check FAILs "curl not found in PATH", which a verdict cannot tell apart from a dead service |

`helper` and `startup-context` are declared empty: the cicd skills call no
installed helper script, and CPP's Codex installer writes only skill
directories at this pin. Unsupported: `/opt/claude-power-pack` and
`~/.claude-power-pack` (later probes in the skills' own order; the first
succeeds), and `/usr/local/bin` (an `echo`ed remote-deploy hint in the Go and
Rust Makefile templates).

## Runtime

`runtime_supply.selected_runtime` selects `cicd-runtime` for this closure: no
gate, the supported pin, the policy project's import probe and a curl command
probe, with the pin's metadata digests or a refusal. `docker/cicd-trial/`
builds that runtime as one curl layer on a validated flow-check
`profile-runtime` receipt (measured: curl 7.88.1 on the bookworm base). The
flow-check runtime and its selection are unchanged.

## Local semantics, exactly

| Concern | What this profile means locally | What it does NOT claim |
|---|---|---|
| Project | `tests/fixtures/cicd-local/project`: stdlib-only, `pyproject.toml` with no dependencies, a zero-dependency `uv.lock`; the Makefile has all eight targets `lib.cicd check` recommends, each through `uv run` | any project with third-party test or lint tools (ruff, pytest, mypy need PyPI, which trials do not have) |
| Build/test/check | `lib.cicd check` (8/8) and `lib.cicd run --plan check` (lint, test, typecheck) | the `finish` or `deploy` plans |
| Network | the attempt runs `--network none`; the runner's github.com probe fails at name resolution, so it treats itself as offline without `CPP_OFFLINE` | that a networked trial behaves the same |
| Services | one loopback HTTP service (`127.0.0.1:18080`) started inside the attempt's own container | any hosted service, Docker-in-trial, systemd units or process probes (`ss`/`lsof`/`pgrep` are not in the image) |
| Health/smoke/verify | `health` and `smoke` against that service; `verify --baseline` then `verify` → PROCEED; the service stopped → ROLLBACK (exit 1) | latency-regression behaviour (loopback probes sit under the 100 ms floor) |
| No probes | `templates/cicd.yml.example`'s shape configures ZERO probes (claude-power-pack#1476): `health` prints "no checks configured" and exits 0 in its default mode (1 with `--json`/`--summary`); `verify` says REVIEW | a pass |
| Provider | `lib.cicd pipeline --write` with `pipeline.provider: both` emits `.github/workflows/ci.yml` and `.woodpecker.yml`; both are parsed, and their make targets equal the ones the local plan ran | that either pipeline runs: their `pip install uv`, `uv sync` and container images are provider-only and never executed |
| Deploy | the project's `deploy` target is local only | any real deployment |

## Evidence

- `tests/test_cicd_profile_live.py` (real Docker, `ci/check_real_docker_ran.py`
  floor): the whole table above in a cold `--network none` container, each CPP
  command taken from the INSTALLED skill text. Break family `cicdprofile:`
  (`no-curl`, `old-curl`, `service-down`, `no-probes`), each strict XFAIL on
  its own property.
- `tests/test_cpp_codex_cicd_86641e8.py` (offline): clean closure, evidence ==
  snapshot bytes, removed dependency and undeclared ambient checkout are
  unresolved, missing and too-old curl are `violated`, a probe-less tool is
  refused before any container call, and each real closure selects its own
  runtime.
- `tests/test_cicd_trial_image.py` and `tests/test_runtime_supply.py`: the
  layer's binding checks and receipt schema, and the flow-check selection and
  build inputs unchanged.
