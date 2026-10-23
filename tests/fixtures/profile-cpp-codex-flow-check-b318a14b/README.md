# Snapshot: CPP Codex `flow-check` at `b318a14b`

The closure of `evals/subjects/cpp-codex-flow-check-b318a14b/profile.json`, copied byte for byte from the subject's pinned tree. Tests use it to validate the profile with `skillc profile validate --snapshot`, with no CPP checkout (#529).

## Provenance

| | |
|---|---|
| Source | https://github.com/cooneycw/claude-power-pack |
| Revision | `b318a14b9e7935f2c50c0940144a5ff0ff9389ed` (the profile's `subject.json` pin; v10.0.0, after CPP #1497's lib/cicd closure) |
| Author | cooneycw (claude-power-pack) |
| Licence | MIT; the upstream [`LICENSE`](LICENSE) is copied here unchanged, as its notice requires |
| What is copied | the files the profile's closure reaches, unmodified, at their upstream paths. Nothing else from the repository is included |
| Upstream paths | `codex/skills/flow-check/`, `scripts/` (the checkout helpers and the checkout gate copy), `lib/cicd/`, `lib/security/`, `pyproject.toml`, `uv.lock`, `.claude/commands/flow/check.md` (the generated skill's source), `CLAUDE.md` (the file the synthetic checkout marker replaces) |

`README.md` and `LICENSE` are the only files here that the profile does not reach. `pyproject.toml` and `uv.lock` are also the runtime image builder's metadata inputs (`docker/profile-trial/build_runtime.py --runtime cpp-codex-flow-check-b318a14b`).

## Regenerate

From a checkout at the pin, copy every source path the inventory names (each skill's and dependency's `files[].source`, every mirror and `generated_from` pair, and `CLAUDE.md`). Then confirm the snapshot inventory equals the checkout one in everything but the subject label:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-check-b318a14b/profile.json \
  --snapshot tests/fixtures/profile-cpp-codex-flow-check-b318a14b --out /tmp/inv.json
```

`tests/test_cpp_codex_flow_check_b318a14b.py` checks it.
