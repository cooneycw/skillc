# ADR 0004: Evaluate the exposed knowledge surface, not only the skill files

- Status: Accepted (owner, 2026-09-26)
- Date: 2026-09-26
- Decision owner: Repository owner
- Amends: [ADR 0002](0002-independent-goal-driven-evaluation.md), its treatment of
  instruction and memory files as held-constant environment rather than subject
- Delivery issue: [#55](https://github.com/cooneycw/skillc/issues/55) (rung-2 exposure check)

## Context

skillc evaluates "a collection of skills". `skillc check` reads `SKILL.md` files,
`skillc materialize` proves the client lists what was installed, and the planned
task levels measure outcomes. Everything else the model is given (instruction
files, memory indexes, other clients' surfaces) is recorded as environment to hold
constant. The #7 receipt records `CODEX_HOME/AGENTS.md` and `config.toml` as
absent, and the CPP subject excludes `CLAUDE.md` and `cpp-memory.md` as "other
clients' surfaces".

A model does not work from a collection of files. It works from **layered,
exposed knowledge**. Some of it is always in context: instruction files, a memory
index, the skill listing. Some is loaded when a skill is selected (its body).
Some is loaded only when the model follows a route (references, topic hubs,
scripts). Each client decides what reaches each layer, under its own size limits,
truncation rules and invocation policies. The author's files and the model's
input are different objects, and nothing currently reports the difference.

One working session (2026-09-26) produced four specimens of the same failure
class, **exposure**. None was visible from the files alone:

| Specimen | What the author wrote | What the model received | Where recorded |
|---|---|---|---|
| Claude Code memory index | 388 index lines, 61 KB | the first 186 lines; the loader cut at about 25 KB | owner's memory store (restructured the same day) |
| Codex invocation policy | a user-invoked skill, installed | omitted from the model-visible listing | [#11](https://github.com/cooneycw/skillc/issues/11#issuecomment-5848007297) |
| Codex and `disable-model-invocation` | "user-invoked" in `SKILL.md` frontmatter | ignored by Codex; only `agents/openai.yaml` counts | [#50](https://github.com/cooneycw/skillc/issues/50), [openai/codex#29989](https://github.com/openai/codex/issues/29989) |
| Plugin manifest | 38 skill directories | 25 installed by the plugin | [#53](https://github.com/cooneycw/skillc/issues/53) |

The first specimen is not a skill at all. The same property (content silently
beyond what the model receives) applies to every layer, so the unit of evaluation
has to include the layers.

## Decision

The evaluated subject is a **knowledge surface**: every artifact a client exposes
to the model, the layer at which it is exposed, and the routes between layers.
A skill collection is one kind of surface. Instruction files, memory indexes and
their on-demand targets are others. A declaration names the surface's layers the
same way `subject.json` names a skill tree today.

Effectiveness is measured on a ladder. Each rung is a separate measurement, and
no rung is inferred from another:

1. **Valid:** the artifacts parse and follow their specification (`skillc check`).
2. **Exposed:** what actually reaches the model at session start, measured from
   the client's **rendered input**, never from the files. It is reported per
   layer as present, truncated or hidden, with the client, version and limit
   in effect.
3. **Reachable:** from the always-loaded layer, every declared route to a deeper
   layer resolves. That covers index to hub, description to body, and body to
   reference.
4. **Selected:** when a task needs a deeper layer, the model opens it. This is
   observed, never inferred from silence (as #39 requires for skills).
5. **Effective:** a task outcome improves against a matched baseline (ADR 0002's
   levels).

A claim of effectiveness needs rungs 4 and 5. Rungs 2 and 3 need no model call,
cost little, and are prerequisites: an unexposed or unreachable layer makes a
rung-4 or rung-5 result uninterpretable.

The discipline of ADR 0001 applies to every rung. An exposure check ships a
planted marker beyond each limit it claims to detect, and must report that marker
missing. A reachability check ships a dangling route. A selection check ships a
matched arm where the same knowledge sits in an always-loaded layer.

## Consequences

- **Gained:** a failure class that is invisible to file checks and expensive to
  find behaviourally becomes cheap to detect before any trial. A trial's result
  can be attributed: "not selected" is distinguishable from "never exposed".
- **Scope grows:** the subject stops being CPP's skills alone. Instruction and
  memory layers become treatments that can be varied, not only held constant.
  The ADR 0002 boundary (CPP left undisturbed; subjects are pinned external
  inputs) is unchanged.
- **Per-client cost:** rung 2 needs a way to render each client's input. Codex
  has `codex debug prompt-input` (used in #7). An equivalent for Claude Code has
  **not been verified**; identifying one is part of the delivery issue. If a
  client offers no render, rung 2 for that client is reported as unmeasured,
  never as clean.
- **Stdlib boundary unchanged:** the static checker stays stdlib-only. Rendering
  a client's input calls that client and belongs with `materialize`.
- **Open:** how a memory store is declared as a subject (it is per-user and
  mutable; pinning it means snapshotting it). Whether rung 4 for non-skill layers
  can be observed at all (a file read has no receipt unless the harness records
  tool calls).
