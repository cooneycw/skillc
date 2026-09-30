<!-- flow-run n=1 id=2372c9da146e46bd9d8d2972bd77abd6 -->
## Run 1 - issue #204 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #204
- Read at:      2026-09-30T17:16:44Z
- updatedAt:    2026-09-30T15:25:49Z   (context only - moves on comments and labels)
- Body digest:  fc5f1f649427b7f4734ca6b8d1b53024a544152dbd68d9928c46d2c0aa09c7e9   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4657 of 4657 (cap 16384)

### Body as read
Precedes #203 (the effectiveness study, which is gated on this issue). Depends on #202 (transcript retention). No live run is authorized by this issue (ADR 0005).

## Why

Two of the last three live experiments ran before anyone checked that they could inform:

- #150's pair was non-discriminating: the task was too easy, and it could not be diagnosed (PR #201).
- #12's rerun passed the task but stored inconclusive results (`evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/`).
- #26 recorded no spontaneous skill invocation, with heuristic detection.

A comparison study (#203) run on an uncalibrated measurement risks spending its budget to learn that the task was too easy or the endpoint unreachable. This issue checks the measurement cheaply first. **It passes when the measurement is shown to be informative, not when CPP wins.**

## A comparison trap to fix first: baseline readiness is asymmetric

On the agent-trial path, an arm that installs nothing stays on the `AGENT_OBSERVATION_READINESS` stand-in (`skillc/agent_trial.py:630-645`, ADR 0005's "yes, narrow B1"). Its `installation-ready` is a mandatory UNKNOWN, so its verified result cannot reach PASS. Only `collection_conformance` opts into a real installation receipt (`skillc/agent_trial.py:805-818`); `matched_pilot` and `selection_probe` keep the stand-in.

So comparing verified PASS rates between a CPP arm and a baseline arm would manufacture a CPP advantage out of grading plumbing.

## Scope

**Arms:** two only, **full CPP** vs **minimal baseline**. They share model, effort, client, tools, permissions, public requirements, budgets and image, and arm order is randomized. No ablation here; that is deferred to #203 once there is a credible mechanism question.

**Task:** the existing Level 3 integration work (`evals/level3/slugkit-installed`) **plus one pipeline extension**. The repository carries a local verification pipeline (for example a Makefile `verify` target) that the delivered change must keep honest. The trial container has no GitHub or Woodpecker, so the pipeline runs locally.

**Endpoints** must be symmetric: reachable by both arms on equal terms.
- The primary endpoint is the task's graded criteria plus the pipeline checks.
- `installation-ready` is reported separately. It is never a hidden precondition that only one arm can meet.

## Acceptance

- [ ] **Symmetric eligibility.** Either the baseline arm gets a readiness receipt it can satisfy (for example an in-container empty-listing check proving nothing is installed), or the primary endpoint excludes `installation-ready` and readiness is reported beside it. A test shows a baseline attempt that meets the task criteria reaches the primary endpoint's PASS. Red case: that test fails on the current code.
- [ ] **Pipeline-check validity.**
  - The clean tree passes.
  - Each planted defect (at least one type or test failure, and one packaging or wrong-artifact omission) is proven to have actually introduced its defect, then rejected by the gate that should catch it.
  - A benign-change control is *not* rejected, and a valid alternative solution passes.
  - Missing tools, malformed mutations and grader crashes count as UNKNOWN, never as detection.
- [ ] **A predeclared calibration run**, separately approved before it starts:
  - About 3-5 attempts per arm on the one task.
  - Identities, caps and arm order recorded first.
  - Transcripts retained (#202).
- [ ] **A calibration report** answering each question with evidence:
  - (1) Does the grader behave (controls green and red as designed)?
  - (2) Can the baseline reach the primary endpoint?
  - (3) Is difficulty useful: not both arms at ceiling, not both at floor?
  - (4) Did the CPP arm actually select and use CPP, from transcripts rather than the heuristic alone?
  - (5) What is the per-attempt time and quota cost, to size #203?
- [ ] **A go / redesign / stop recommendation** for #203, based on (1)-(5). Any direction of CPP-vs-baseline result is acceptable here; it is not the question.

## Constraints

- ADR 0005: no live run without recorded, approved arms, identities, schedule and caps.
- ADR 0002: the runtime stays in skillc.
- Task definitions, graders and mutation contracts stay subject-independent. Nothing here may branch on CPP.

## Attribution

This design comes from an adversarial read-only critique of #203 by OpenAI Codex (`codex exec`, model `gpt-6-astra`), requested via `/codex:ask` on 2026-09-30: the two-arm calibration before a three-arm study, the baseline-readiness trap, mutation validity and symmetric endpoints. The readiness asymmetry was then confirmed in code at the lines cited above.

