# Issue #26 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #26
- Read at:      2026-09-27T17:15:21Z
- updatedAt:    2026-09-27T14:32:29Z   (context only - moves on comments and labels)
- Body digest:  b27c07cc89a54b8f6b7794cce6d13e2ad8ea2978b55996fec9cde800036cdff1   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4065 of 4065 (cap 16384)

## Body as read
Parent: #1
Source: #22
Phase: exploratory follow-up after the minimum execution path; not an initial milestone gate.
Depends on: #7 and #10. Does not block #2-#12 or require #13-#15 qualification.

## Decision and smallest useful scope

Should the maintainer revise the selected skills' applicability descriptions or
keep their current selection behavior for the tested requests? Use one pinned
collection and supported native client with three predeclared cases: intended
use, a near miss where no skill is needed, and a choice between two overlapping
skills. Respect manual-only declarations. Publish allowed choices before observing
results; allow more than one justified choice where applicability overlaps.

Use the existing execution path and matched minimal baseline. Grade the public
task outcome independently of observed selection. Installed, available, invoked
and successful remain distinct; unknown invocation stays unknown. A correct
result without unnecessary invocation can be valid. Invocation alone is never
outcome success. No subject repository edits or new selection engine are in scope.

## Governing contracts

- [Spec: subject acquisition and applicability](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/spec.md#subject-acquisition)
- [Protocol: preparation, comparison, accounting and qualification](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/protocol.md)
- [Interfaces: observation coverage and independent grading](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/interfaces.md)
- [PLAN](https://github.com/cooneycw/skillc/blob/main/PLAN.md#supplemental-decision-traceability)

These documents own semantics; this issue selects cases, not a new result schema.

## Resource bounds and stopping conditions

Stay within the three cases, one collection and one client configuration. Set
repeat count, arm order, per-attempt and total time/cost caps, retention and
interaction policy in this delivery's manifest before running. Actual live
budgets are set and authorized here, not by #22 or by filing this issue. Stop at
the declared limits; do not keep adding cases or repeats until a benefit appears.
Unavailable native selection observations limit the selection conclusion; do not
substitute prompted invocation. Without an approved live budget, the manifest can
be prepared but execution remains incomplete.

## Observable completion evidence

- A pinned manifest with the three public case contracts, allowed selection
  behavior, matched arms, independent outcome graders and discriminating controls.
- A complete attempt inventory linked to installation receipts, observations and
  verified outcomes, with selection and task success reported separately.
- A report of outcome, interventions and observed resource use, missing evidence
  and uncertainty, identifying what can inform description revision and what
  remains unresolved. Link concrete follow-up proposals without editing subjects.

Null, negative and inconclusive results are valid. A completed experiment need
not settle the maintainer's decision. Do not claim benefit outside the tested
requests/configuration or level qualification from this probe.


## Folded in from the Nit Store (#20), 2026-09-27

- [ ] **A `coverage: complete` skill-invocations stream can omit an installed skill** (`records.py` `_skill_invocations` / `_skill_invocation_binding`). The bundle rule checks that reported paths belong to the receipt, but never that every installed path appears. Reproduced at `70ead2c`: a second installed skill with no invocation row gives exit 0, 0 errors. This limits this issue's per-skill selection/non-selection reporting. Require the row set to cover the receipt's installed set for `complete`, define missing-row semantics for partial/unsupported coverage, and commit a two-skill red case missing one row plus its complete green twin. (https://github.com/cooneycw/skillc/issues/20#issuecomment-5848531649) *Note for PR #114: this was folded in after the PR opened.*

