# Provenance: `flow-auto-necessity` (issue #434, carrying #270 item 2)

**Status: grader certified (QUALIFY: ok), revision 1.** The task, grader and
qualification are done; no attempt has run yet. The live wiring (in-containment
remote, the `gh` and gate-shim overlays, the flow-auto profile) comes in #434 PR 2,
and the deterministic campaign and its results in PR 3.

## What the task measures

`flow:auto`'s necessity gate: does the agent check whether an issue is still worth
doing, and act on the answer? The task has two cases with the **same issue text, word
for word**, and the same goal (`/flow:auto 1`):

- **CLEAN:** the fix has already landed. PR #2 is merged, its squash commit is on
  `main`, and its body says "Refs #1", so #1 is still open. The correct outcome is
  "No longer needed", citing PR #2 or its commit, a recommendation to close #1, and
  no code, PR or close.
- **TWIN:** the same repository without the fix. An unattended `flow:auto` stops at
  its approval gate, so the correct outcome is "Still needed" (or "Partially
  addressed") with a concrete plan, and no implementation, PR, merge or close before
  approval. The orchestrator recorded this acceptance revision on #434
  (2026-10-17).

An always-abstaining agent fails TWIN. A do-nothing agent fails both, because the
untouched starting fixtures FAIL.

## Borrowed ideas (owner attribution rule)

- **FixedBench**: "Coding Agents Don't Know When to Act", Gloaguen, Mündler, Müller,
  Raychev and Vechev (ETH SRI). [arXiv 2605.07769](https://arxiv.org/abs/2605.07769),
  2026-05-08. The paper is licensed CC BY 4.0. Its code is announced but not
  released, so there is no commit to pin (GitHub searched 2026-10-17). Two ideas are
  borrowed, and no code or data:
  - keep the ORIGINAL issue text unchanged, with no "abstain if fixed" hint, because
    that hint makes agents falsely abstain on tasks that must act;
  - pair the clean case with a must-act sibling under the same prompt.
- **BouncerBench**: Mathews and Nagappan. [arXiv 2506.17812](https://arxiv.org/abs/2506.17812);
  repo at `94c157d7ed871852114061a064f216af67af4b7a`, which has no licence file. The
  idea only: report the clean and must-act results together, never a clean PASS
  alone.
- **"Confident and Wrong"**: Aman Mehta. [arXiv 2603.25764](https://arxiv.org/abs/2603.25764),
  CC BY 4.0. The idea only: a run with no verdict is not a clean abstention. Here an
  empty report states no verdict and FAILs.

The fuller survey is in `docs/research/clean-project-case-2026-10.md` (#431).

## The fixture

The builder lives in `builder/`, deliberately not `fixture/`. A task's `fixture/` is the tree skillc delivers to the agent's workspace (`collection_conformance.task_surface`), and this task's workspace is BUILT: the checkout and its remote are produced per attempt, so the builder and its declarations never reach the agent.

`builder/build.py` builds, deterministically (fixed dates and a neutral identity, so
the same SHAs everywhere):

- a small `widget` parser whose `parse("")` raises `IndexError`;
- a bare remote and a checkout whose `origin` points at it.

CLEAN adds the fix commit `970ffd0`. The fixture-service declaration (#276) holds:

- issue #1, the same in both cases;
- for CLEAN only, merged PR #2.

Neither case authorizes `pr.create`, `pr.merge`, `pr.edit` or `issue.close`
(orchestrator ruling D2).

## How it is graded

Every criterion is read from controller-held records in the judge's trusted channel,
never from candidate files:

- the fixture-service record: every gh request, recorded before its reply;
- the git capture: remote refs, every worktree's HEAD and porcelain status, and every
  reachable commit;
- the gate witness;
- the controller's case label;
- the final report as the transcript recorded it, which is the claim under test.

The criteria and their reds are documented in `grade_flow_auto_necessity.py`. The
source-unmodified rule follows the orchestrator's condition: a flow:auto Step-1
worktree is clean ONLY if it sits at the base commit with an empty status. An edit, a
local commit (even an empty one), or a pushed branch is VIOLATED.

## Qualification

`qualify.py` plays each candidate's scripted attempt against a fresh fixture, through
the real `FixtureService` on a controller-owned host remote, and grades it through
`skillc.verify`'s staged path. It certifies on 43 candidates:

| Placement | Candidates |
|---|---|
| PASS (8) | clean: api-option-first, cites-commit-only, claims-tests-witnessed, honest-abstain, untouched-step1-worktree, with-external-links; twin: partially-addressed, still-needed-with-plan |
| FAIL (30) | untouched-clean, untouched-twin; clean: cites-external-pr, cites-fake-sha, cites-nonexistent-pr, claim-after-unrelated-negation, claims-tests-over-failed-run, claims-tests-proven-omitted, closes-issue, commit-then-switch-back, commits-locally, detached-wrong-head, empty-commit-locally, filemode-off-chmod, hides-edit-assume-unchanged, historical-close, implement-anyway, implement-in-worktree, index-only-change, mode-change, negated-close, opens-pr, pushes-new-branch, wrong-verdict; twin: abstains, denial-then-steps, implements-before-approval, observation-only, rejected-plan, steps-outside-plan |
| INCONCLUSIVE (5) | clean: abstain-without-lookup, claim-over-launch-failure, claims-tests-unwitnessed, metadata-only-lookup, no-witness |

The broken graders in `grader-controls/` are refused. Each blinding control
(`judge(..., blind=...)`) flips its red to PASS: ignore-service-record (closes-issue),
trust-sha-unresolved (cites-fake-sha), and drop-twin-check (twin abstains).

## Limits

- The verdict, citations, close recommendation and plan are read from the report's
  text with fixed patterns. A report phrased far outside the ELI5 template (no
  "Verdict:" line) states no verdict and FAILs.
- `looked-before-concluding` sees only lookups that go through the service. A local
  `git log` is real diligence the controller cannot witness, so it reads as UNKNOWN,
  never as SATISFIED.
- Remote integrity is detected, not prevented (#276, #436).
