# Snapshot: CPP Codex `flow-auto` + `flow-eli5` at `ca3030d`

The closure of `evals/subjects/cpp-codex-flow-auto-ca3030d/profile.json`, copied byte for byte from the subject's pinned tree. Tests use it to validate the profile with `skillc profile validate --snapshot`, with no CPP checkout (#279's re-pin from `86641e8`).

## Provenance

| | |
|---|---|
| Source | https://github.com/cooneycw/claude-power-pack |
| Revision | `ca3030dbeba4a145166b61d714861f56e92cd034` (the profile's `subject.json` pin; CPP #1467, the fix for #1453) |
| Author | cooneycw (claude-power-pack) |
| Licence | MIT; the upstream [`LICENSE`](LICENSE) is copied here unchanged, as its notice requires |
| What is copied | the files the profile's closure reaches, unmodified, at their upstream paths. Nothing else from the repository is included |
| Upstream paths | `codex/skills/flow-auto/`, `codex/skills/flow-eli5/`, `scripts/` (the installed helpers), `lib/`, `pyproject.toml`, `uv.lock`, `.claude/commands/flow/{auto,eli5}.md` (the generated skills' sources), `CLAUDE.md` (the file the synthetic checkout marker replaces) |

`README.md` and `LICENSE` are the only files here that the profile does not reach. `pyproject.toml` and `uv.lock` are also the runtime image builder's metadata inputs (`docker/profile-trial/build_runtime.py --runtime cpp-codex-flow-auto-ca3030d`). They are byte-identical to `86641e8`'s.

## Regenerate

From a checkout at the pin, copy every source path the inventory names (each skill's and dependency's `files[].source`, every mirror and `generated_from` pair, and `CLAUDE.md`). Then confirm the snapshot inventory equals the checkout one in everything but the subject label:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-auto-ca3030d/profile.json \
  --snapshot tests/fixtures/profile-cpp-codex-flow-auto-ca3030d --out /tmp/inv.json
```

`tests/test_cpp_codex_flow_auto_ca3030d.py` checks it.
