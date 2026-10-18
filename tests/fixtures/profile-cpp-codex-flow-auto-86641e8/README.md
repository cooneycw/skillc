# Snapshot: CPP Codex `flow-auto` + `flow-eli5` at `86641e8`

The closure of `evals/subjects/cpp-codex-flow-auto-86641e8/profile.json`, copied
byte for byte from the subject's pinned tree so that tests can validate the profile
with `skillc profile validate --snapshot` and no CPP checkout (#434 PR 2b).

## Provenance

| | |
|---|---|
| Source | https://github.com/cooneycw/claude-power-pack |
| Revision | `86641e817711d8a7746270745a5dfa7cacf04b0c` (the profile's `subject.json` pin) |
| Author | cooneycw (claude-power-pack) |
| Licence | MIT; the upstream [`LICENSE`](LICENSE) is copied here unchanged, as its notice requires |
| What is copied | the 117 files the profile's closure reaches, unmodified, at their upstream paths. Nothing else from the repository is included |
| Upstream paths | `codex/skills/flow-auto/`, `codex/skills/flow-eli5/`, `scripts/` (the installed helpers), `lib/`, `pyproject.toml`, `uv.lock`, `.claude/commands/flow/{auto,eli5}.md` (the generated skills' sources), `CLAUDE.md` (the file the synthetic checkout marker replaces) |

`README.md` and `LICENSE` are the only files here that the profile does not reach.

## Regenerate

From a checkout at the pin, copy every source path the inventory names (each
skill's and dependency's `files[].source`, every mirror and `generated_from`
pair, and `CLAUDE.md`), then confirm the snapshot inventory equals the checkout
one in everything but the subject label:

```bash
skillc profile validate evals/subjects/cpp-codex-flow-auto-86641e8/profile.json \
  --snapshot tests/fixtures/profile-cpp-codex-flow-auto-86641e8 --out /tmp/inv.json
```

`tests/test_cpp_codex_flow_auto_86641e8.py` checks it.
