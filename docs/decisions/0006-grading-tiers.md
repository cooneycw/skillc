# ADR 0006: Grading tiers - a judge seam, never averaged with the deterministic floor

- Status: Accepted (owner ruling, 2026-09-26; this record delivered with the seam, #69)
- Date: 2026-09-26
- Decision owner: Repository owner
- Delivery issue: [#69](https://github.com/cooneycw/skillc/issues/69)
- Related: [#88](https://github.com/cooneycw/skillc/pull/88) (the per-tier
  verdict schema this ADR's seam produces into), [#63](https://github.com/cooneycw/skillc/issues/63)
  (leak-check, applied to judge input), [#12](https://github.com/cooneycw/skillc/issues/12)/
  [ADR 0005](0005-runtime-scope-and-cost-rulings.md) rule 5 (the cost stop a
  real judge's paid calls must observe)

## Context

skillc grades deterministically today: structural and outcome checks, no
model call. Some goals - workflow judgment, explanation quality
(`evals/level1`'s later levels, #13-#15) - can only be judged by a model, and
the verifier had no stated place for one, and no rule for what its output
must look like.

## Decision: three tiers, named to avoid a collision skillc already has

1. **Deterministic** - today's grader (`skillc/verify.py`'s `GRADING_TIER`).
   Always runs; the floor. Needs no judge, ever.
2. **Same-model** (`skillc.judge.SAME_MODEL_TIER`) - the model that produced
   the candidate's work, judging it.
3. **Independent** (`skillc.judge.INDEPENDENT_TIER`) - a different model,
   cross-client by default (Codex judges Claude Code's work and the
   reverse).

Named "tiers", not "levels": skillc already uses "level" for TASK difficulty
(`evals/level1`, #13-#15), and reusing it here would read as a claim about
the task ladder instead of the grading mechanism.

**When judges are enabled, all enabled tiers grade together, and each
produces its own verdict.** Verdicts are recorded side by side in
`verification.verdicts`, a collection keyed by tier name - #88 delivered
this shape. None is averaged, weighted or overridden; a consumer wanting one
answer must say which tier it reads. The top-level `status`/`criteria` on a
`verified-result` are, and stay, the deterministic tier's own alone.

## What each tier does and does not establish

- **Deterministic** establishes structural/outcome facts a program can check
  without judgment - it cannot assess quality, intent or workflow adherence.
- **Same-model** establishes whether the SAME model that wrote the candidate
  judges its own work as meeting the criteria. It is informative but
  self-grading: a model with a systematic blind spot in its own output
  carries that same blind spot into judging it. This tier's verdict must
  never be read as independent confirmation.
- **Independent** establishes a second, differently-biased opinion - not a
  ground truth. Cross-client by default reduces (does not eliminate)
  correlated blind spots between the candidate and its judge.
- **Neither judge tier establishes ground truth.** Both are opinions from a
  model, schema-constrained and validated (`skillc.judge.parse_judge_verdict`)
  so a malformed one cannot corrupt the record, but not thereby made
  authoritative. The disagreement record (below) exists exactly because
  neither tier's agreement with the other is assumed.

## The same-model limitation, made a measured quantity

`verification.disagreement` (#88's reserved field, this ADR's seam fills it
in) is a per-criterion same-model-vs-independent comparison
(`skillc.judge.compute_disagreement`): for every criterion both tiers
answered, whether they agree. This turns "same-model grading may be biased"
from a stated limitation in this document into a number computed on every
judged run - `agreement_count`/`disagreement_count` and a per-criterion
breakdown. It is `{"available": false, "reason": "fewer than two judge
tiers"}` whenever fewer than two real (non-`UNAVAILABLE`) judge verdicts
exist to compare - never fabricated from one tier alone.

## Per-tier availability: unavailable is not a demotion

An unavailable judge makes ONLY its own tier's verdict `UNAVAILABLE` (with a
stated reason, from `skillc.judge.JudgeUnavailable`) - the others still
report, and nothing substitutes a lower tier's answer for a missing one.
`verdicts.<tier>.status` uses the SAME `PROTOCOL_STATUSES` vocabulary
(`records.py`) every other verdict does, so a reader never has to learn a
second vocabulary for "the judge could not be reached."

## Judge mechanism: `mcp-second-opinion`, named not merely permitted

[`cooneycw/mcp-second-opinion`](https://github.com/cooneycw/mcp-second-opinion)
is the owner-ratified mechanism for tiers 2 and 3 - a separate public
repository with its own dependencies and no references back to
claude-power-pack, so depending on it is not depending on a sibling
platform. **Not delivered in this PR**: `skillc.judge.Judge` is the seam a
real adapter implements; `skillc.judge.FakeJudge` is the only implementation
this PR ships, because #69's own acceptance forbids a real model call in the
test suite. The real adapter, the cost-estimate extension for its paid
calls (`skillc/cost_estimate.py`, #12/#26), and the calling convention that
speaks MCP to the server as an external process are a follow-up PR, kept
separate to stay reviewable.

## Structural guarantees this seam keeps

- **Schema-constrained, never coerced.** `skillc.judge.parse_judge_verdict`
  either returns a fully valid verdict or raises `MalformedJudgeOutput` - an
  invalid field never gets partial trust because another field looked fine.
  A malformed criterion becomes `UNKNOWN` with a stated reason, at the
  granularity of that one criterion - it does not take the whole tier down.
- **`skillc/` stays stdlib-only.** `skillc.judge`'s `Judge` Protocol imports
  nothing beyond the standard library; a real adapter is a SEPARATE module a
  caller supplies, never a core import (`tests/test_frontmatter.py`'s
  existing stdlib-import walk already covers `skillc/judge.py` - no new
  control was needed for this half).
- **Leak-checked before it leaves the machine.** `skillc.judge.run_tier`
  calls `skillc.judge.check_judge_input` (built on `skillc/leak.py`, #63)
  before EITHER judge call - a leak is a refusal to grade at all
  (`verify.Refused`, nothing written), never a tier-level `UNAVAILABLE`: an
  unreachable judge and a judge that must not receive this input are
  different facts, and conflating them would let a caller retry past a leak
  by simply trying a different judge.

## Consequences

- **Gained:** a real judge, once its adapter lands, plugs into this seam
  with no change to `verify.grade`'s result shape - the shape is already
  proven against `FakeJudge` in every configuration (both tiers, one
  unavailable, malformed output, leaked input).
- **Nothing here makes a paid call possible yet.** The cost stop (ADR 0005
  rule 5) still applies in full once a real adapter exists; this PR commits
  no code that could spend money even by accident.
- **The same-model bias is now measured, not merely disclaimed** - a
  disagreement record accumulates across every judged run, which is a
  standing dataset a future ADR or research note can read.
