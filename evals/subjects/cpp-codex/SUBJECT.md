# Subject: CPP native Codex skills

- Declaration: [subject.json](subject.json) - the machine form; this page explains it
- Adapter: `skillc materialize` ([materialization spec](../../../docs/specs/evaluation-facility/materialization.md))
- Evidence: [records/receipt.json](evidence/records/receipt.json) and [report.json](evidence/report.json), produced 2026-09-26 (#7)

This is the first declared subject. It has no code of its own: every CPP
convention the adapter honours is data in `subject.json`, and a second
collection needs a new declaration, not a new branch in the adapter (#11 proves
that).

## Pin

| Identity | Value |
|---|---|
| Locator | `github.com/cooneycw/claude-power-pack` |
| Revision | `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b` (origin/main on 2026-09-26) |
| Surface | `codex-skills`: the tree `codex/skills/` at that revision |
| Surface digest | recorded in the receipt's `subject.digest` (relative path, executable bit and bytes of every installed-surface file) |
| Client | `codex`, codex-cli `0.157.1` |

The Level 1 fixture is pinned separately ([PROVENANCE.md](../../level1/slug-small-fix/PROVENANCE.md));
this pin says nothing about it.

## Treatment inventory

All 74 skill directories under `codex/skills/` - every directory holding a
`SKILL.md`, which is exactly what CPP's own installer (`codex-skill-sync.py
--install`) copies to `~/.codex/skills/`. The one non-skill entry, `README.md`,
is named in the report and not installed. The full list, with each skill's file
count, checksum status and required references, is `inventory.skills` in the
report; the installed files and their digests are the receipt's `installed`.

This is the **whole-pack treatment**. A selected skill or subset is a different
treatment and needs its own `select` and its own receipt (spec.md section 3).

## Conventions declared for this subject

| Declaration | Value | Why |
|---|---|---|
| `checksum_manifest` | `scripts/SHA256SUMS` | 22 skills bundle one; each is verified, a mismatch refuses the install |
| `required_references` | ``Read `(...)` in this skill directory`` | 39 entry points defer to `reference.md` in these words; all 39 resolve |
| `external_references` | `~/.claude/scripts/*`, `${CLAUDE_PLUGIN_ROOT}/*` | host or other-client helpers the bundle points at but does not carry; 57 recorded as `external-not-materialized` |

## Capabilities

**Supported (observed in the evidence):**

- Codex lists every installed CPP skill, from the file this run installed, with
  no model call: installed and available.
- A baseline home prepared identically, minus the treatment, lists none of them;
  a single planted CPP skill IS listed, so absence is not blindness.
- Apart from the treatment, the client is given byte-identical input in both arms.

**Excluded, and why:**

- **Procedures that need host helpers.** Many skills instruct the agent to run
  `~/.claude/scripts/<helper>`. Those helpers are installed on a host by CPP's
  own repair step, are not part of `codex/skills/`, and are not materialized.
  Such a step would fail in the disposable home. That is a property of this
  treatment, recorded per reference in the receipt's `dependencies`.
- **External services and authority.** GitHub mutation, Docker, AWS secrets,
  MCP servers, deployments and network access are not provided, and trials may
  not use them (spec.md section 4).
- **Other CPP surfaces.** The Claude Code plugin, hooks, commands and
  `cpp-memory.md` are other clients' surfaces, not this one.
- **Invocation and task outcome.** No model runs here, so whether a skill is
  ever selected, and whether a task succeeds, are not observed. The report says
  `NOT_OBSERVED` and `NOT_APPLICABLE`; they are #10, #12 and #26's to measure.

## What the evidence does not show

- It is one run on one host, at one moment. Another client version, or the same
  version with other feature flags, is a different configuration.
- `codex debug prompt-input` renders what a session WOULD be given. That a model
  then reads a listed skill is not shown.
- 642 static findings (text in `.md` files that looks like a path not in the
  bundle) are recorded in the report. Most are repository paths the procedures
  talk about. They neither establish nor refute readiness, by design.
- The run used the host's `codex` binary against disposable homes, with no agent
  and no model. The host's `~/.codex` skills tree and config files were
  fingerprinted before and after and did not change; sessions and caches were
  not fingerprinted, because other sessions write them.
