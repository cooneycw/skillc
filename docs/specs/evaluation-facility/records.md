# Evaluation records, version 2

- Status: Executable. `skillc check-records` refuses records and bundles this document rejects.
- Date: 2026-09-26 (version 1: 2026-09-21, slice of #4 in #17)
- Governing documents: [interfaces](interfaces.md), [protocol](protocol.md), [specification](spec.md)
- Decision: [ADR 0001](../../decisions/0001-every-check-ships-a-redcase.md)

## What this document is, and what it is not

[interfaces.md](interfaces.md) already names four contracts, their producers, their
required outputs and their independent checks, and already fixes the vocabularies.
This document does not choose any of that. It gives **each of the four rows an
executable form** so that something can refuse a malformed instance:

| Contract row in interfaces.md | Executable form here | Authorized producer |
|---|---|---|
| Installation receipt | `kind: installation-receipt` | `subject-adapter`, `checked_by: controller` |
| Trial ledger | `kind: trial-ledger` | `controller` |
| Artifact and observation bundle | `kind: artifact-manifest` | `controller` |
| Verified result | `kind: verified-result` | `assembler` (the controller's result assembler) |

A record that passes validation is **well formed and internally consistent**, and a
bundle that passes is **consistent with its own ledger**. Neither is true because of
that. interfaces.md: "Structure checks establish that fields are well formed and
consistent." PLAN.md: "A valid JSON record, hash or echoed config alone does not
authenticate success." `skillc check-records` prints what it examined on **every**
run, including passing ones, so a green cannot be quoted as verification by someone
who did not read this page.

## Two subjects: a record, and a bundle

Most rules read **one record**. Some facts exist only **between** records: that a
receipt belongs to the attempt the ledger planned, that no planned attempt went
missing, that a regrade's original was not erased. Those rules read a **bundle**.

A bundle is **a directory whose own `*.json` files include a trial ledger**. Its
records are those files; subdirectories are separate bundles. A record in no bundle
is checked alone, and `check-records` says how many were, in words that cannot be
read as "bound correctly": `checked alone - NOT against any ledger`. Selecting a
bundle rule with `--rule` where there is no bundle exits 2, because a bundle rule
with nothing to read checked nothing.

`selftest` uses the same definition of a bundle as `check-records`, so a control
cannot be proven under a looser notion than real evidence is checked under.

## Envelope

Every record is a JSON object carrying:

| Field | Meaning |
|---|---|
| `version` | integer `2`. See "Versions" below. |
| `kind` | one of the four kinds above. |
| `producer` | the role that produced it. Exactly one role is authorized per kind. |
| `attempt_id`, `trial_id` | on the three attempt-bound kinds. The ledger issues them; it carries neither. |
| `raw` | optional: `{ref, digest}` pointing at the backend's original record. |

### Identifiers

Every identifier (`experiment_id`, `trial_id`, `attempt_id`, `result_id`) matches
`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`: no whitespace, no path separator, bounded
length. IDs reach file names and log lines, so `att 1/../x` is refused. The
**controller** creates attempt IDs in the ledger; every other record cites one.

### Versions

This build reads exactly the versions in `SUPPORTED_VERSIONS`, currently `{2}`. It
is an exact set, not a ceiling:

- a newer version is refused rather than read on a guess;
- **version 1 is refused** with its reason: it predates producer authority and
  ledger binding, so a v1 record lacks exactly the fields the v2 rules exist to
  check, and no migration is defined;
- `0`, negatives, non-integers and `true` are refused. `true` needs its own test
  because Python treats a boolean as an integer; before v2 it was read as version 1.

A future build that reads two versions lists both; nothing is inferred from order.

### Backend raw data

interfaces.md permits "a versioned local envelope [that] can wrap an upstream record
while preserving its raw bytes for inspection". The upstream record stays in its own
file, and `raw` points at it with a digest. A `raw` with no digest is refused:
protocol.md calls "a path to an overwritten directory" insufficient, and a ref
without a digest is exactly that.

## `installation-receipt`

Produced by the subject adapter, and it must say `checked_by: controller`. An
adapter's unchecked account of its own install is a claim, not a receipt.

| Field | Content |
|---|---|
| `subject` | `locator`, `revision`, `digest` |
| `surface` | the selected native surface, e.g. `codex-skills` |
| `adapter`, `client` | `name`, `version` each |
| `layers` | effective instruction/configuration layers (list) |
| `dependencies` | dependency closure (list) |
| `allowed_writes` | paths the trial may write (list) |
| `installed` | non-empty list of `{path, digest}` |
| `readiness` | `discovery_canary` and `baseline_absence`, each `SATISFIED`/`VIOLATED`/`UNKNOWN` |

An empty `installed` list is refused: "A file count, checkout path or adapter boolean
alone cannot prove a usable install", and an install that recorded nothing is not a
ready one. For the three lists, an empty list means *none*, while a missing list
means *unknown*, and unknown is refused.

Readiness is **reported**, not required to be satisfied: a receipt whose discovery
canary failed is a valid, useful receipt. What readiness then allows the result to
claim is the grader's and assembler's business (#9). The first producer,
`skillc materialize` (#7), adds `ordinary_parity`, `source_unchanged` and
`host_unchanged` beside the two required facts; see [materialization.md](materialization.md).

## `trial-ledger`

Produced by the controller. It is the **expected population**: every trial and every
attempt the experiment planned, created before dispatch.

`experiment_id`, and `trials`: a non-empty list. Each trial carries `trial_id` and
these identities, which every record for its attempts is bound to:

| Identity | Keys |
|---|---|
| `case` | `id`, `revision` |
| `grader` | `id`, `revision` |
| `subject` | `digest` |
| `client` | `name`, `version` |
| `image` | `digest` |
| `config` | `digest` |

and `attempts`: a non-empty list of `{attempt_id}`, optionally with `retry_of`.
protocol.md: "Empty selections refuse." A ledger with no trial, or a trial with no
attempt, has an expected population of zero, and nothing measured against it could
ever go missing.

Budgets, lifecycle, termination and cleanup observations are required ledger
outputs in interfaces.md, but the runtime that records them is #8. Version 2 permits
them as additional fields and does not yet require their shape.

## `artifact-manifest`

Produced by the controller.

`artifacts`: a non-empty list. Each entry carries `path`, `type`, `size` and
`digest`. An empty list is refused: a capture that recorded nothing is not a capture
that found nothing.

`observations`: each entry names a `stream`, its `origin` and its `coverage`:

| Vocabulary | Values | Source |
|---|---|---|
| origin | `observed`, `client-reported`, `model-asserted` | interfaces.md: "externally observed process events, client reports and model-authored assertions differ" |
| coverage | `complete`, `partial`, `unsupported` | "Record unsupported or incomplete event coverage explicitly" |

**Initial observation requirement.** Every manifest declares `client-events` and
`process-lifecycle`, even when that declaration is `unsupported`. Silence about a
stream is refused: "Missing events cannot prove a forbidden action never happened",
and an undeclared stream reads exactly like one that saw nothing. `capture_failures`
must be present as a list, empty when there were none.

These two streams are the initial set, not a census. Cost/token observation and
nested-worker coverage are named in interfaces.md and join this list when a producer
can report them (#8, #12).

## `verified-result`

Produced by the assembler.

| Field | Content |
|---|---|
| `result_id` | this result's own identifier |
| `grader` | `id`, `revision` |
| `graded_digests` | the artifact digests it graded. Required unless a run state is declared. |
| `criteria` | each with `id`, `mandatory` (a JSON boolean), `outcome` (`SATISFIED`/`VIOLATED`/`UNKNOWN`) |
| `status` | `PASS`/`FAIL`/`UNAVAILABLE`/`INCONCLUSIVE`/`NOT_RUN`, **derived** |
| `run_state` | optional, only `UNAVAILABLE` or `NOT_RUN`, with a `reason` |
| `regrade_of` | optional, the `result_id` this regrades |

### Missing evidence is explicit

interfaces.md requires "criterion outcomes/evidence references ... and explicit
missing evidence":

- a `SATISFIED` or `VIOLATED` criterion cites a non-empty `evidence` list;
- an `UNKNOWN` criterion names what is `missing`;
- a declared run state gives its `reason`.

A mandatory `SATISFIED` criterion with no evidence is **missing mandatory evidence**.
Without this rule it would derive PASS.

### Derivation

Unchanged from version 1. From interfaces.md, in the order the sentences bind:

1. A declared `UNAVAILABLE` or `NOT_RUN` run state is honoured.
2. "An established mandatory violation remains FAIL when another criterion is
   unknown" - so any `VIOLATED` mandatory criterion yields `FAIL`, tested **before**
   unknowns.
3. "missing mandatory evidence prevents PASS" - so any non-`SATISFIED` mandatory
   criterion yields `INCONCLUSIVE`.
4. Otherwise `PASS`.

Optional criteria never enter this computation. **No mandatory criteria yields
`INCONCLUSIVE`, never `PASS`.** The other three statuses may not be declared as a
run state, or the forged verdict would simply move from `status` into `run_state`.

## Producers and authority

`producer-authority` refuses a record whose declared producer is not the one role
authorized for its kind (table at the top). A verified result with
`producer: subject` is the **forged subject verdict**: the subject declared its own
success. It is refused.

**What this does not establish.** `producer` is a declared field. It catches a
subject-authored verdict that says where it came from, and a record routed to the
wrong producer. It cannot catch a forger who writes `assembler`. Authenticating the
producer belongs to the trusted controller host, collectors and grader, which
interfaces.md already places inside the trusted system (#8, #9). `check-records`
says so on every run.

## Binding, accounting and lineage (bundle rules)

**`ledger-binding`.** A bundle has exactly one ledger. Every attempt-bound record:

- cites an attempt the ledger issued;
- names the trial the ledger planned that attempt under. Otherwise it is a
  **cross-trial** record;
- if a receipt, carries the trial's planned `subject.digest` and `client` name and
  version. Otherwise it is a **stale** receipt, produced for a configuration this
  trial does not run;
- if a result, names the trial's planned grader `id` and `revision`. A regrade may
  carry a new revision, but not a different grader;
- if a result, cites only digests its attempt's manifest captured. Otherwise it
  graded an **altered** or substituted artifact.

**`unique-ids`.** interfaces.md makes "duplicate/conflicting IDs" an explicit
validation failure:

- no trial or attempt ID is planned twice;
- an attempt has at most one receipt and one manifest. A second one is a conflicting
  account, and nothing here can say which is true;
- results may be several (a regrade is a new result), but each `result_id` is unique.

**`attempt-accounting`.** "Every planned attempt remains accounted for" (EF-07):

- every planned attempt has a result. A non-start is accounted as `NOT_RUN`, never
  dropped;
- an attempt that was graded (its result declares no run state) also has its
  installation receipt and artifact manifest.

**`lineage`.** protocol.md: "A rerun gets a new ID and links to the original.
Regrading creates a new result linked to the unchanged original artifact ... Neither
operation erases the earlier attempt."

- A retry's `retry_of` names a different attempt in the same trial.
- A regrade's `regrade_of` names a result retained in the bundle, for the same
  attempt and with the same `graded_digests`.

## Retention boundary

The initial boundary, which #8 turns into a location, access and retention policy
before any real private or model evidence exists (review.md Q5):

- Evidence is **local and private**, in controller-owned storage. Nothing is
  published automatically.
- Records carry **identities and digests**, never credential values. Configuration
  is recorded as a digest plus the metadata needed to reproduce it.
- Backend raw data is **retained** and referenced by `raw.ref` plus `raw.digest`,
  not replaced by the envelope.
- Retries and regrades **add** records; the originals are retained, and `lineage`
  refuses a bundle that erased one.
- Records never live in the subject's writable environment. That is a property of
  the controller (#8, #9), not something a record can show about itself.

No part of this boundary is enforced beyond the `raw` digest and lineage rules above.

## Rules and their controls

Each rule ships a committed pair under `controls/<rule-id>/{bad,good}/`, per ADR 0001.
For a bundle rule, each case is a bundle directory. `skillc selftest` reports
`BLIND`, `NOISY`, `EMPTY`, `UNPARSED` or `UNPROVEN` and fails the run. Every bad
case fires its own rule **and no other**; `tests/test_records.py` checks that for
bundle cases as well, including against every record rule.

| Rule | Subject | Refuses (committed bad cases) |
|---|---|---|
| `record-envelope` | record | unreadable; missing, v1, v3, `true` or `0` version; `raw` without digest |
| `producer-authority` | record | forged subject verdict; unchecked receipt; adapter-produced ledger |
| `attempt-binding` | record | no attempt; malformed attempt ID; no trial |
| `installation-receipt` | record | empty install; no readiness; subject without digest |
| `trial-ledger` | record | no trials; a trial with no attempts; missing grader identity; malformed attempt ID |
| `artifact-digest` | record | an artifact without a digest; an empty manifest |
| `observation-coverage` | record | a silent required stream; an unknown origin; no `capture_failures` |
| `criterion-vocabulary` | record | an outcome outside the vocabulary; a non-boolean `mandatory` (`"true"` would drop a violation out of the derivation) |
| `result-evidence` | record | SATISFIED without evidence; UNKNOWN without `missing`; no graded digests; no grader; a run state without reason |
| `derived-status` | record | a status copied rather than derived |
| `ledger-binding` | bundle | cross-trial receipt; stale receipt; attempt the ledger never issued; altered artifact; unplanned grader |
| `unique-ids` | bundle | duplicate attempt ID; conflicting receipts; duplicate result ID |
| `attempt-accounting` | bundle | planned attempt with no result; graded without receipt; graded without manifest |
| `lineage` | bundle | retry reusing its own ID; regrade whose original was erased; regrade of different bytes |

Record and bundle rules live in the **same registry and the same selftest loop** as
the `SKILL.md` rules. Only the subject-loading step knows the family.
`test_an_uncontrolled_record_rule_is_UNPROVEN` and
`test_an_uncontrolled_bundle_rule_is_UNPROVEN` establish that no arm was split off.

## Boundary

This completes #4's contract versioning. What it deliberately does not do:

- **No runtime.** Nothing here produces a record. The controller that writes the
  ledger, captures artifacts and assembles results is #8 and #9. Runtime packages
  stay outside `skillc/`, which the stdlib import walk in `tests/test_frontmatter.py`
  enforces with its own negative control.
- **No authentication.** Digests are checked for agreement between records, never
  against the bytes they name, and `producer` is declared. Both need the trusted host.
- **One ledger per bundle.** An experiment spread across bundles is checked bundle by
  bundle. No rule yet asks whether two bundles planned the same attempt.
- **Readiness does not yet gate a PASS.** A PASS over a receipt whose discovery
  canary failed is not refused here. That judgement needs the case's declared role
  for setup (protocol.md section 3) and belongs with #9. #7 now PRODUCES readiness
  ([materialization.md](materialization.md)); it does not gate on it.
