# Deploy-verification fixture (skillc#282)

Installed on top of `../cicd-local/project/` as `project/deploy/` by
`tests/test_cicd_deploy_verify_live.py`. Everything stays on 127.0.0.1 inside
the trial container (`--network none`).

- `deploy/service.py`: a release-aware loopback service on `127.0.0.1:18080`.
  It reads `current/release.json` ONCE, at start, so a process keeps serving
  its release after `current` moves. Routes: `/health` (always ok - it never
  sees a fault), `/version` (`{"release": "<id>"}`), `/calc` (2 + 3) and
  `/metrics`.
- `deploy/deploy.sh <id>`: stop the running service (bounded wait), point
  `current` at `releases/<id>`, start it, poll `/health` (bounded).
  `DEPLOY_SKIP_RESTART=1` is the planted fault: `current` moves but the old
  process keeps serving.
- `deploy/releases/<id>/release.json`: each release's FIXED faults, never a
  timing one: `calc-wrong` (`/calc` answers 6) and `metrics-500`.
- `release-probe.cicd.yml`: the certified config, CPP's real schema. Its
  `release identity` endpoint expects the INTENDED release (`@INTENDED@`),
  because CPP's verify has no release identity of its own
  (claude-power-pack#1479).
- `health-only.cicd.yml`: one health endpoint and nothing that names the
  release - the known-gap config.

Latency is ignored in both (`on_latency_regression: ignore`): timing in a
shared container is not deterministic.
