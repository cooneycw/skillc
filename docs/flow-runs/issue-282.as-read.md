<!-- flow-run n=1 id=ed24dd72b70c4c6d9192642d6bcc59bc -->
## Run 1 - issue #282 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #282
- Read at:      2026-10-18T01:24:41Z
- updatedAt:    2026-10-04T16:32:36Z   (context only - moves on comments and labels)
- Body digest:  c354bd0019ace0c96521420ca4bdccd37cff00cc68d6993f8fa6b2cad56913c2   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2301 of 2301 (cap 16384)

### Body as read
**Type:** scope:task - one bounded issue run after its prerequisites.
**Wave:** [skillc #261](https://github.com/cooneycw/skillc/issues/261).
**Outcome contract:** [skillc #253](https://github.com/cooneycw/skillc/issues/253).
**Depends on:** [skillc #280](https://github.com/cooneycw/skillc/issues/280), [skillc #276](https://github.com/cooneycw/skillc/issues/276), [skillc #268](https://github.com/cooneycw/skillc/issues/268)

## Outcome

A deployment recommendation follows observed release identity, health and smoke changes.

## Bounded scope

A development/held-out local-service pair for cicd-health/smoke/verify.

The parent issue's constraints and acceptance remain binding. This ticket delivers only the slice below; closing it does not close the workstream or establish live capability. The named files/mechanism are implementation starting points; an equivalent design may substitute while preserving the outcome, constraints and evidence.

## Acceptance

- [ ] Cover regression, pre-existing failure, recovery, absent baseline, empty probe set and mismatched release identity using pinned contract semantics.
- [ ] Judge actual baseline/current observations and correct proceed/review/rollback recommendation, not the existence of a report.
- [ ] Separate recommendation from execution; rollback effects are permitted only in an explicitly authorized disposable scenario.
- [ ] Use deterministic faults and bounded readiness polling, avoiding narrow timing thresholds or live network dependencies.
- [ ] Certify controls, valid alternatives, grader faults and runner integration; no observation means unknown assurance.

## Completion evidence

Actual local HTTP/probe execution and protected state transitions with reproducible baseline comparisons.

Run repository checks appropriate to the change. Report exactly which acceptance items were demonstrated and retain known-bad/unknown controls; a broad green suite is not a substitute for the named evidence.

## Excluded from this run

No production deployment, cloud infrastructure or universal latency benchmark.

No live model trials are authorized by this issue. A separately approved declaration is required under skillc ADR 0005. Existing approvals and the cooneycw/skillc#203 / cooneycw/skillc#237 priority ruling are unchanged.

