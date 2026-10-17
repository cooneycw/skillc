<!-- flow-run n=1 id=27570ba3452143d0bf8e675af044365b -->
## Run 1 - issue #280 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #280
- Read at:      2026-10-17T18:38:19Z
- updatedAt:    2026-10-04T16:32:35Z   (context only - moves on comments and labels)
- Body digest:  dd9b67fa63386e543d64c83b9ad94430ab079cffbd3173926dfb048372803517   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2027 of 2027 (cap 16384)

### Body as read
**Type:** scope:task - one bounded issue run after its prerequisites.
**Wave:** [skillc #261](https://github.com/cooneycw/skillc/issues/261).
**Outcome contract:** [skillc #247](https://github.com/cooneycw/skillc/issues/247).
**Depends on:** [skillc #266](https://github.com/cooneycw/skillc/issues/266)

## Outcome

CI/deployment tasks have a reproducible installed CPP/tool environment before testing behavior.

## Bounded scope

Extend the existing profile with the required cicd skills/libraries, one CI provider representation and a controlled local HTTP service.

The parent issue's constraints and acceptance remain binding. This ticket delivers only the slice below; closing it does not close the workstream or establish live capability. The named files/mechanism are implementation starting points; an equivalent design may substitute while preserving the outcome, constraints and evidence.

## Acceptance

- [ ] Pin tool/dependency/context inventories and resolve the installed cicd helper consuming path in a cold container.
- [ ] Exercise build/test/check and baseline/health/smoke/verify APIs with deterministic projects and local endpoints.
- [ ] Missing tool, wrong version, no probes and unreachable service produce explicit readiness/coverage outcomes.
- [ ] Record exact supported provider/local semantics and cleanup evidence; no hosted-CI or cloud capability claim.

## Completion evidence

Manifest controls and non-model container smoke tests through actual installed CPP helpers.

Run repository checks appropriate to the change. Report exactly which acceptance items were demonstrated and retain known-bad/unknown controls; a broad green suite is not a substitute for the named evidence.

## Excluded from this run

No new task grader, hosted pipeline execution or real deployment.

No live model trials are authorized by this issue. A separately approved declaration is required under skillc ADR 0005. Existing approvals and the cooneycw/skillc#203 / cooneycw/skillc#237 priority ruling are unchanged.

