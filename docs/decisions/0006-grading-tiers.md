# ADR 0006: Grading tiers - a judge seam, never averaged with the deterministic floor

- Status: Accepted (owner ruling, 2026-09-26; the seam delivered with this record, the real adapter and cost-estimate extension in a follow-up PR, #69)
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
platform. `skillc.judge.Judge` is the seam; `skillc.judge.FakeJudge` is what
every test in the seam's own PR uses, because #69's own acceptance forbids a
real model call in the test suite.

**Delivered in the follow-up PR**: `skillc/judge_mcp_second_opinion.py`
implements `Judge` against a real `mcp-second-opinion` server, speaking MCP
as an external process - stdlib `subprocess` plus line-delimited JSON-RPC
2.0 over stdio (the `initialize` handshake, `notifications/initialized`,
one `tools/call`), no MCP SDK. Its own tests drive
`tests/fixtures/mcp-second-opinion/fake_server.py`, a committed fake
speaking the same protocol subset - still no real model call anywhere, now
enforced by an AST-walk structural test over every test file rather than
only by convention. The real tool's own schema
(`get_code_second_opinion`: `code`/`language` required, `additionalProperties:
false`) has no field for a structured criteria list, so the adapter embeds
the criteria ids as a JSON array literal inside `issue_description` and
parses the first JSON array back out of the model's free-text response - a
response that ignores the instruction produces `[]`, which flows into
`run_tier` as an honest per-criterion `UNKNOWN`, never a crash.

**Still owed**: the judge does not yet run "inside the grading boundary
delivered for #10" (a separate backend instance, no network except its
provider, no candidate write access - this issue's own "Constraints"
section). The adapter spawns the judge process directly on the host today,
bounded only by ordinary OS-level process isolation. Wiring the judge call
through a `skillc.backend.ExecutionBackend` instance is separate follow-up
work.

The cost-estimate extension for the adapter's paid calls
(`skillc/cost_estimate.py`, #12/#26) is also delivered in the follow-up PR:
see "Cost stop" below.

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

## Cost stop: judge calls counted only when enabled

`skillc.cost_estimate.estimate()` gains `judge_tiers_enabled` (0, 1 or 2),
`judge_price` and per-call token assumptions. `judge_tiers_enabled=0` (the
default) reproduces the function's pre-adapter behavior exactly - a plan
that never mentions judges is priced exactly as #26/#12's own committed
manifests already were, byte-for-byte. Enabling `N` judge tiers adds `N`
paid calls per attempt, each priced separately from the agent model, into
the same `estimated_usd` `skillc.cost_estimate.authorize()` already checks
against the operator's $5 ceiling (ADR 0005 rule 5) - so a plan comfortably
under the ceiling without judges can, and in the committed control does,
cross it once judges are enabled, and is refused in exactly that
configuration, never unconditionally.

## Consequences

- **Gained:** a real judge, `skillc.judge_mcp_second_opinion.
  McpSecondOpinionJudge`, plugs into the seam with no change to
  `verify.grade`'s result shape - the shape was already proven against
  `FakeJudge` in every configuration (both tiers, one unavailable, malformed
  output, leaked input), and the real adapter's own tests (against a fake
  MCP server, never a real one) prove the same shape survives a real wire
  protocol's failure modes: an absent binary, a failed handshake, a timeout,
  a tool-level error, and a response that ignored the schema instruction
  entirely.
- **A paid call is possible once someone installs the real
  `mcp-second-opinion` binary, enables a tier, and gets a budget approved.**
  Nothing in this codebase's own test suite can reach it: the adapter's
  default `command` names the real binary, but every test overrides it, and
  an AST-walk structural test refuses the whole suite if one ever forgets
  to. The cost stop (ADR 0005 rule 5) is the second, independent gate before
  any real spend - both must be cleared, and neither substitutes for the
  other.
- **The same-model bias is now measured, not merely disclaimed** - a
  disagreement record accumulates across every judged run, which is a
  standing dataset a future ADR or research note can read.
- **Still owed:** the judge does not yet run inside #10's grading boundary
  (a separate backend instance) - see "Judge mechanism" above.
