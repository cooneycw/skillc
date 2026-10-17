<!-- flow-run n=1 id=8e022ebb4fa34398a5f4faa53ecc9834 -->
## Run 1 - issue #276 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #276
- Read at:      2026-10-17T18:38:42Z
- updatedAt:    2026-10-04T16:32:31Z   (context only - moves on comments and labels)
- Body digest:  db542cce500dc5a614da053421047924ffe25115b0140aa2c6ec7627591c347f   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2313 of 2313 (cap 16384)

### Body as read
**Type:** scope:task - one bounded issue run after its prerequisites.
**Wave:** [skillc #260](https://github.com/cooneycw/skillc/issues/260).
**Outcome contract:** [skillc #248](https://github.com/cooneycw/skillc/issues/248).
**Depends on:** [skillc #268](https://github.com/cooneycw/skillc/issues/268), [skillc #183](https://github.com/cooneycw/skillc/issues/183)

## Outcome

Lifecycle tests can inspect real controlled issue/PR state transitions independently of agent prose.

## Bounded scope

A minimal local service implementing only create/read/update/merge/close/status semantics needed by the declared tasks, using the existing authoritative channel.

The parent issue's constraints and acceptance remain binding. This ticket delivers only the slice below; closing it does not close the workstream or establish live capability. The named files/mechanism are implementation starting points; an equivalent design may substitute while preserving the outcome, constraints and evidence.

## Acceptance

- [ ] Declare supported request semantics and persist server-owned state/events bound to attempt, repository and sequence.
- [ ] Expose commit/PR/merge payloads and actual closure effects; subject logs and wrappers cannot rewrite the service history.
- [ ] Support deterministic lost-response and stale-state controls without letting the subject choose the scored fault point.
- [ ] Certify valid transitions, wrong repository, duplicate create, unauthorized transition, forged history, missing coverage and bypass behavior.
- [ ] Retain isolation and report simulator limitations; no claim of production GitHub conformance.

## Completion evidence

API transition tests plus adversarial deterministic clients through the isolated path; actual observed effects must match the server record.

Run repository checks appropriate to the change. Report exactly which acceptance items were demonstrated and retain known-bad/unknown controls; a broad green suite is not a substitute for the named evidence.

## Excluded from this run

No real GitHub writes or separate replacement for #183.

No live model trials are authorized by this issue. A separately approved declaration is required under skillc ADR 0005. Existing approvals and the cooneycw/skillc#203 / cooneycw/skillc#237 priority ruling are unchanged.

