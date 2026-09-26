# ADR 0003: No external evaluation runtime dependency

- Status: Accepted
- Date: 2026-09-26
- Decision owner: Repository owner
- Amends: [ADR 0002](0002-independent-goal-driven-evaluation.md), its "Evaluate
  pinned Coder Eval first as a replaceable execution/measurement backend" clause
- Delivery issue: [#6](https://github.com/cooneycw/skillc/issues/6)
- Lessons: [Coder Eval lessons and contract map](../research/coder-eval-lessons.md)

## Context

ADR 0002 left backend selection open and named Coder Eval
([UiPath/coder_eval](https://github.com/UiPath/coder_eval), inspected at
`d960de1c433a1b050d2509f04d94a60e3cabaaf0`, version 0.12.4) as the first
candidate. Issue #6 was filed to qualify it through bounded Docker probes and
then adopt, wrap or reject it.

The static reading already showed that adoption as-is was not possible: its
Docker lane trusts the result record the container writes, treats an echoed
container contract as a compatibility check rather than authentication, and lets
a missing reference digest warn and proceed. skillc's
[record contracts](../specs/evaluation-facility/records.md) exist to refuse
exactly those cases. The live question was therefore wrap or reject.

On 2026-09-26 the owner ruled that skillc takes no runtime dependency on it:
skillc has no control over how that project will evolve. The ruling was made
before any probe was built or run.

## Decision

skillc depends on no external evaluation runtime. Neither Coder Eval nor Harbor
is installed, imported, vendored, wrapped or invoked by skillc code, tests or CI.
Both remain design references.

- **Ideas, not code.** Where skillc adopts an idea first seen in either project,
  the design note that introduces it names the source. No source file is copied.
- **One runner, owned here.** The controller, ledger and capture of
  [#8](https://github.com/cooneycw/skillc/issues/8), the verifier of
  [#9](https://github.com/cooneycw/skillc/issues/9) and the Docker lifecycle of
  [#10](https://github.com/cooneycw/skillc/issues/10) are implemented in skillc
  against its own contracts. There is no adapter seam to a third-party record
  format to maintain.
- **Stdlib boundary unchanged.** The static checker in `skillc/` stays
  stdlib-only. Any evaluation runner that needs dependencies lives outside
  `skillc/` and declares them as optional, as ADR 0002 already requires.
- **Harbor is not a fallback.** #6 allowed a Harbor comparison only if a named
  requirement stayed unmet by Coder Eval. The reason for this decision applies to
  Harbor equally, so that comparison is not triggered.

## Consequences

- Given up: a ready-made multi-agent runner, agent adapters, timing and token
  capture, repeated A/B variants and HTML/JUnit reports. None of these is needed
  for the first bounded pilot ([#12](https://github.com/cooneycw/skillc/issues/12)),
  which is one client, one task and a small matched comparison.
- Taken on: #8 and #10 grow to include a minimal container runner - start, time
  limit, cancellation, candidate export, cleanup - and its failure accounting.
  That cost is real and is the price of controlling every authoritative fact.
- Removed: upstream schema drift, upstream behaviour changes between pinned
  revisions, and an adapter that must re-derive trust from records produced by
  code skillc does not own.
- #6's probe and forgery acceptance items do not disappear; they move to the
  issues that now own the machinery. The transfers are recorded as comments on
  #6, #8, #9 and #10.
- [#7](https://github.com/cooneycw/skillc/issues/7) depended on #6 for a backend
  choice. That choice is this ADR.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Adopt Coder Eval as-is | Its result path trusts container-authored records; fails skillc's own record contracts by design, per the static reading |
| Wrap Coder Eval behind a skillc adapter | Workable, but binds skillc to an external schema and behaviour it cannot control; every upstream release would need re-qualification |
| Vendor a pinned copy | Removes drift but inherits a large codebase (hundreds of files) that skillc would then maintain alone |
| Harbor instead | Same dependency reason; its separate-verifier model is kept as a reference |

## Revisit triggers

- The skillc runner built for #8/#10 costs more to maintain than re-qualifying a
  pinned external runner would, measured over at least two subject collections
  ([#11](https://github.com/cooneycw/skillc/issues/11)).
- A requirement arrives that needs broad client coverage (several agent CLIs)
  that skillc cannot reasonably own.

Either trigger reopens the question with evidence; neither reverses this ADR by
itself.

## Evidence and limits

All statements about Coder Eval here and in the lessons document come from static
inspection of the pinned revision. No Coder Eval code was run for this decision
and no forgery was attempted against it. Nothing here claims how Coder Eval
behaves at run time.
