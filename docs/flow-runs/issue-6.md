# Flow run record - issue #6

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #6
- Base SHA:          f2d1a5c32d52057fa6eb799d329a1373f97b063f
- Necessity verdict: Needs reframing
- Approval:          granted
- Approver:          repository owner (cooneycw), in the interactive /flow:auto session
- Recorded at:       2026-09-26T13:36:26Z

## Section B evidence

Commits since filing (2026-09-20T16:27:39Z): 2f74b83, 857781f, c352bbe, 1c8a762,
36bc172, e02a217, b8809e0, 95fead8, c37c991, b1a1fdf, f2d1a5c - none add a Coder
Eval backend, adapter or probe. Merged PRs: #16, #17, #21, #24, #25, #29, #30, #31,
#32, #33, #34. Duplicate/superseding issues: none.

Reframing: the owner ruled on 2026-09-26 that skillc takes no runtime dependency on
Coder Eval (or Harbor), because upstream evolution is outside skillc's control. The
original probe-based qualification plan was withdrawn before any code was written.

## Section C - the approved plan

1. `docs/decisions/0003-no-external-evaluation-runtime.md` - ADR: no runtime dependency on Coder Eval or Harbor; references only; cost, attribution, revisit trigger; amends ADR 0002
2. `docs/research/coder-eval-lessons.md` - contract-by-contract map at d960de1: what Coder Eval does, what skillc builds, owning issue; lessons and pitfalls, static evidence only
3. `docs/decisions/0002-independent-goal-driven-evaluation.md` - one amended-by line
4. `PLAN.md` - decision bullet, #6 row, gate B text, critical sequence
5. `docs/specs/evaluation-facility/interfaces.md` - Coder Eval fit section becomes a pointer
6. `docs/specs/evaluation-facility/review.md` - Q4 resolved
7. `evals/README.md` - drop the pending conformance-investigation line
8. `docs/research/README.md` - link the lessons doc
9. `docs/README.md` - link the lessons doc
10. `docs/flow-runs/issue-6.md` - this record

GitHub: comment on #6 recording the revision and authority; transfer comments on #8,
#9 and #10 for the forged/stale/missing-digest controls and Docker lifecycle probes.

Scope: ~10 files, ~250-350 lines of prose, no code, no Docker, no network.
Risks: #8/#10 grow to own a runner; the lessons doc is static-only and must not
claim observed behaviour; #7's dependency on #6 is satisfied by the ADR at merge.
