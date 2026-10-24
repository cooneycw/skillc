<!-- flow-run n=1 id=73aa8ae3b1a343c0850c47461dab0068 -->
## Run 1 - issue #28 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #28
- Read at:      2026-10-24T23:24:23Z
- updatedAt:    2026-09-28T14:08:42Z   (context only - moves on comments and labels)
- Body digest:  6d6411d765f178a93a7f2452ab81edba994a923679c60888f02df7ed2e2c2864   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3584 of 3584 (cap 16384)

### Body as read
Parent: #1
Source: #22
Phase: follow-up after retained experiment evidence exists.
Depends on: #8 and the first useful experiment evidence from #26 or #12.
Does not block #2-#12 or require formal level qualification.

## Decision and smallest useful scope

Can a maintainer reproduce one observed failure, and does evidence still describe
the configuration now under consideration? Select one eligible failure from the
retained evidence, preserve its source attempt identity and sanitize it into a
small development fixture with public acceptance. Establish that the fixture
retains the relevant failure distinction using independent bad/good outcomes.
Keep the development case separate from held-out comparisons; do not claim it
is fresh evidence of generalized improvement after tuning against it.

Produce one readable comparison between that evidence's tested identities and
a deliberately changed configuration. Identify changes to selected skills,
transitive helpers and client/version/configuration that put the new configuration
outside the old claim; consult task, grader and environment identities too.
Use the existing installation receipt and ledger identities rather than a second
registry. Preserve the original evidence as historical for the original inputs.
Recommend a scoped rerun or regrade only with reasons; neither is automatic and
neither overwrites the old result. No watcher, new schema or universal expiry
period is required.

## Governing contracts

- [Protocol: held-out separation, evidence and lineage](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/protocol.md)
- [Interfaces: authority, observations and regrading](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/interfaces.md)
- [Records boundary: structural validation only](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/records.md#boundary)
- [Spec: configuration-bounded evidence](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/spec.md#1-objective)

#8's retention/export policy governs sanitization. Do not publish private evidence
or secrets to make a regression reproducible.

## Resource bounds and stopping conditions

One source failure, one sanitized case and one changed-configuration example.
Prefer deterministic local replay; predeclare attempt/time/storage limits in
this delivery. Actual live-run budgets, if needed, are set and authorized here,
not in #22. Stop if sanitization cannot preserve the tested distinction or if
the source evidence is insufficient. Report the reason and leave case delivery
incomplete until an eligible failure exists; do not invent a real failure or
spend on new trials merely to obtain one. Apply the declared caps to any replay.

## Observable completion evidence

- A source-linked sanitized development fixture and independent good/bad control
  results demonstrating the relevant distinction, with redaction limits stated.
- A replay record with original lineage preserved and an explicit separation
  from held-out task material.
- A worked unchanged/changed identity comparison that bounds the earlier claim,
  names the next evidence needed and states whether the product decision is
  settled or unresolved.

Null, negative and inconclusive results are valid. Reproducing a failure does
not require a favorable skill comparison; inability to reproduce is reported
and does not count as a delivered regression. Invocation alone is never outcome
success. Propose any subject repair separately; this issue does not edit subjects.


