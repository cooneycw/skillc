# Evaluation records, version 1

- Status: Executable. `skillc check-records` refuses records this document rejects.
- Date: 2026-09-21
- Governing documents: [interfaces](interfaces.md), [protocol](protocol.md), [specification](spec.md)
- Decision: [ADR 0001](../../decisions/0001-every-check-ships-a-redcase.md)

## What this document is, and what it is not

[interfaces.md](interfaces.md) already names four contracts, their producers, their
required outputs and their independent checks, and already fixes the vocabularies.
This document does not choose any of that. It gives **two of those four rows an
executable form** so that something can refuse a malformed instance:

| Contract row in interfaces.md | Executable form here |
|---|---|
| Artifact and observation bundle | `kind: artifact-manifest` |
| Verified result | `kind: verified-result` |

The other two rows - installation receipts and the trial ledger - are **not**
versioned here and remain open work on issue #4. See "Boundary" below.

A record that passes validation is **well formed and internally consistent**. It is
not true. interfaces.md puts it plainly: "Structure checks establish that fields are
well formed and consistent." PLAN.md puts it more sharply: "A valid JSON record,
hash or echoed config alone does not authenticate success." `skillc check-records`
prints what it examined on **every** run, including passing ones, so a green cannot
be quoted as verification by someone who did not read this page.

## Envelope

Every record is a JSON object carrying:

| Field | Meaning |
|---|---|
| `version` | integer. This build understands `1`. A newer version is REFUSED, never read on a guess - interfaces.md makes incompatible versions an explicit validation failure. |
| `kind` | `artifact-manifest` or `verified-result`. |
| `attempt_id` | the attempt this record belongs to. **Opaque here** - see Boundary. |

interfaces.md permits "a versioned local envelope [that] can wrap an upstream record
while preserving its raw bytes for inspection", so a backend's native record may be
carried alongside these fields rather than replaced by them.

## `artifact-manifest`

`artifacts`: a non-empty list. Each entry carries `path`, `type`, `size` and
`digest`. An empty list is refused: a capture that recorded nothing is not a capture
that found nothing, and an empty population must not render as a clean one.

## `verified-result`

`criteria`: a list. Each entry carries an `id`, a `mandatory` flag and an `outcome`
of `SATISFIED`, `VIOLATED` or `UNKNOWN` - the vocabulary interfaces.md fixes.

`status`: one of `PASS`, `FAIL`, `UNAVAILABLE`, `INCONCLUSIVE`, `NOT_RUN`. It is
**derived**, and a record whose `status` does not follow from its own `criteria` is
refused.

`run_state`: optional, and only `UNAVAILABLE` or `NOT_RUN` may be declared. The
other three statuses are derived and may not be asserted - otherwise the forged
verdict simply moves from `status` into `run_state`.

### Derivation

From interfaces.md, in the order the sentences bind:

1. A declared `UNAVAILABLE` or `NOT_RUN` run state is honoured.
2. "An established mandatory violation remains FAIL when another criterion is
   unknown" - so any `VIOLATED` mandatory criterion yields `FAIL`, tested **before**
   unknowns.
3. "missing mandatory evidence prevents PASS" - so any non-`SATISFIED` mandatory
   criterion yields `INCONCLUSIVE`.
4. Otherwise `PASS`.

"Optional quality scores cannot average away mandatory failures", so optional
criteria never enter this computation at all. **No mandatory criteria yields
`INCONCLUSIVE`, never `PASS`**: an empty population must not render as a clean one.

### Why the derivation is here and not in a later slice

The record's central field IS the derived status, and the forged-verdict case is a
status COPIED from a subject rather than derived from evidence. A shape that left
derivation elsewhere would define a container whose most important value nobody may
compute - and could not refuse the forgery it exists to refuse.

## Rules and their controls

Each rule below ships a committed pair under `controls/<rule-id>/{bad,good}/`, per
ADR 0001. `skillc selftest` reports `BLIND`, `NOISY` or `UNPROVEN` and fails the run.

| Rule | Refuses |
|---|---|
| `record-envelope` | an unreadable record, a missing or non-integer version, a version newer than this build, an unknown kind |
| `attempt-binding` | a record citing no attempt |
| `artifact-digest` | an artifact entry missing `path`, `type`, `size` or `digest`; an empty manifest |
| `criterion-vocabulary` | an outcome outside `SATISFIED` / `VIOLATED` / `UNKNOWN` |
| `derived-status` | a status that does not follow from the record's own criteria |

Record rules live in the **same registry and the same selftest loop** as the
`SKILL.md` rules. The coverage check, the counters and the exit code never learn
which family a rule came from; only the subject-loading step does. Splitting "a
check with no control is UNPROVEN" across two arms is how one arm later stops being
enforced, and `tests/test_records.py::test_an_uncontrolled_record_rule_is_UNPROVEN`
is what establishes that it was not split.

## Boundary

This is a slice of issue #4, which stays OPEN.

**Versioned here:** the artifact manifest and the verified result; protocol status
derivation; incompatible-version handling for this envelope.

**Not versioned here:** installation receipts; the trial ledger and planned
trials/attempts; producer and authority assignment; retry and regrade lineage;
observation requirements and the retention boundary.

**The attempt identifier is opaque here, deliberately.** It is issued by the trial
ledger, which this slice does not own. So these rules check that a record CITES an
attempt - not that the attempt exists, and not that a receipt is current. interfaces.md
requires the artifact bundle to "Bind to the ledger and actual attempt"; the binding
half that a record can establish about ITSELF is enforced here, and the half only a
ledger can establish about it is not. Concretely, issue #4's "stale/cross-trial
receipts" case is therefore **half** covered: a record citing no attempt is refused,
and a stale receipt cannot be detected without the ledger.
