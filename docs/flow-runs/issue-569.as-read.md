<!-- flow-run n=1 id=14071fc0891f422e91c0a1b80e7e9a95 -->
## Run 1 - issue #569 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #569
- Read at:      2026-10-25T09:31:21Z
- updatedAt:    2026-10-25T09:29:48Z   (context only - moves on comments and labels)
- Body digest:  c7869ff86d7577b9cc1d6fef3419d428625d709162b553df87f952f4982e5bd4   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3913 of 3913 (cap 16384)

### Body as read
Parents: #14 and #245. Related: #246, #252, #279 and CPP #871.

## Outcome

Make flow:register/flow:wave completion and timeout failures measurable with a bounded, deterministic coordination fixture before commissioning a live multi-agent comparison.

Owner direction, 2026-10-25: task-success uplift is required for flow:auto; register/wave must make multi-agent sessions complete rather than time out. The completed skillc-complete wave is operational evidence, not a controlled estimate of reduced timeouts.

## Bounded delivery

- [ ] Freeze one small dependency graph: an orchestrator, two workers, two independent artifact-producing tasks, and a final dependent integration task. Use disposable repositories and local service substitutes. Define the same project goal, permissions, worker resources and deadline for every future comparison arm.
- [ ] Document actual supported transport capabilities and the ownership of registration, assignment, delivery, acknowledgement, progress, completion and cleanup. Inventory the current skillc runner seam before implementation. If it cannot represent multiple owned sessions, deliver a bounded interface proposal and a separate implementation blocker; do not hide a new orchestration platform in this ticket.
- [ ] Deliver a model-free contract fixture through the supported seam, with controller-owned event capture. Message enqueue is not wake, wake is not worker receipt, receipt is not task completion. Acknowledgements must bind to the intended role, session/generation and assignment revision; replay cannot advance work.
- [ ] Commit healthy completion and fault cases: delayed delivery, missing wake, worker disappearance after assignment, and duplicate/stale acknowledgement. An explicitly injected recoverable event must recover within its declared allowance; unrecoverable events produce a bounded failure with retained state, never a clean completion. Use authoritative fault injection; reuse the disruption contract behind #183 where applicable, not worker-authored claims.
- [ ] Prove the completion instrument fails on unfinished integration, wrong worker acknowledgement, duplicate completion and a run that exceeds its declared deadline. Healthy output and a valid alternative work order pass. Deterministic clocks prove contract behavior only, not actual wake latency.
- [ ] Define the live measurement contract: primary outcome is correct integrated delivery within the total deadline; report timeout/abandonment counts, interventions, registration/assignment/wake/handoff latencies, recovery and all-attempt accounting separately. Count planned waves as the primary population, not individual worker successes. Retain model/client/runtime identities for every role.
- [ ] Specify later comparisons without running them: current pinned product versus a declared comparator for product benefit; old versus targeted fixed pin for repair benefit. Use matched tasks, resources and randomized order. Do not mix these causal questions or infer improvement from one successful wave. Retain every scheduled wave, including incomplete ones.

## Scope limits and exit

Reuse skillc's runner, capture, verification and reporting contracts. Keep CPP conventions in fixtures/profiles, not generic core code. This ticket delivers the deterministic fixture and a live-study readiness matrix; an unsupported runtime seam must remain visibly blocked until its separate implementation is delivered. No new live workers, paid study, host installation or retired codex-power-pack native-wave programme is implied.

Exit evidence: exact supported-path controls with known-bad and healthy verdicts, retained event/artifact joins, appropriate repository checks, and a concrete list of remaining runtime/declaration prerequisites. A subsequent live declaration must pin caps and approval under ADR 0005. Fake transport tests cannot establish native wake reliability.


<!-- end of body -->
