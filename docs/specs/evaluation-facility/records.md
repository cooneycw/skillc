# Evaluation records, version 2

- Status: Executable. `skillc check-records` refuses records and bundles this document rejects.
- Date: 2026-09-27 (version 1: 2026-09-21, slice of #4 in #17; `attempt-lifecycle` added in #8; `agent-observation` in #106)
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
| Trial ledger (lifecycle, termination, cleanup) | `kind: attempt-lifecycle` | `controller` |
| Evidence report (#12's own acceptance, not one of interfaces.md's original four) | `kind: pilot-report` | `assembler` |
| Artifact and observation bundle: a real agent's transcript conclusions (#106) | `kind: agent-observation` | `controller` |

`attempt-lifecycle` was added to version 2 by #8, `pilot-report` by #12, and
`agent-observation` by #106. All three are **additive**: no existing record
changes meaning. When `agent-observation` was added, no committed bundle held
one and no rule requires one, so no existing bundle changes verdict. The one stricter rule is
`attempt-accounting`, below.

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
| `kind` | one of the kinds above. |
| `producer` | the role that produced it. Exactly one role is authorized per kind. |
| `attempt_id`, `trial_id` | on the four attempt-bound kinds. The ledger issues them; it carries neither. |
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
claim is the assembler's business: since #9 the verifier adds a mandatory
`installation-ready` criterion that is UNKNOWN unless both facts are SATISFIED, so an
unready trial cannot PASS ([verification.md](verification.md#the-result)). The first producer,
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
outputs in interfaces.md. The ledger is immutable once dispatched, so lifecycle,
termination and cleanup live in `attempt-lifecycle` (below). A budget may be carried
as an additional trial field; its shape is not yet required.

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

### `skill-invocations`: an optional declared observation (#39)

spec.md keeps four observations distinct: files discovered, skill
installed/available, skill actually invoked, and task outcome. `installed`
already has a home (`installation-receipt`); `skill-invocations` gives
"actually invoked" one, so it never has to be re-derived from raw events
outside any rule - the state before this: "available but never invoked" was
recoverable only by someone reading raw client events by hand, and nothing
could refuse a silence standing in for "not invoked".

The idea is [config-drift-checker](../../research/config-drift-checker-lessons.md)'s
(#38, per [ADR 0003](../../decisions/0003-no-external-evaluation-runtime.md)): a
per-skill chip that reads "never invoked this run" only when transcript evidence
exists, and "invocation unknown" otherwise
([`tools/eval-report.mjs` L36-38, L252](https://github.com/jameskomo/config-drift-checker/blob/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1/config-drift-checker/tools/eval-report.mjs#L36-L38)).

**Version decision.** `skill-invocations` is an **optional** declared stream in
v2, not a v3 bump and not added to `REQUIRED_OBSERVATIONS`. The alternative the
issue posed - v3, with v2 refused - was rejected: it would refuse every v2
manifest written before this stream existed, which is disproportionate for a
"bounded follow-up; not a gate for #10" (#39's own phase note), and unlike
`attempt-lifecycle` (#8, a new *kind*, added without invalidating anything) this
change touches an *existing* kind's required-observation set, where joining
`REQUIRED_OBSERVATIONS` unconditionally would be exactly the invalidation a
version bump exists to signal - just without signalling it.

**Shape**, when declared: an `observations` entry with `stream:
"skill-invocations"`, its own `origin` and `coverage` from the same vocabulary
above (applying to the whole stream: within one attempt, the observability route
is a property of the client, not of which skill is asked about), and a `skills`
list of `{path, count}` rows, one per installed skill it reports on. `count` is
a non-negative integer or the literal string `"UNKNOWN"`.

- If `coverage` is not `complete`, every row's `count` must be `"UNKNOWN"`,
  never a number, including `0` - the same silence-is-not-absence rule this
  document already states for a whole stream, applied per skill.
- If `coverage` is `complete`, every row's `count` must be a real non-negative
  integer; `"UNKNOWN"` under complete coverage is dishonest, not cautious.
- Complete coverage naming no skills at all is refused: `installation-receipt`
  never allows an empty `installed` list, so a receipted attempt always has at
  least one installed skill, and "complete" over zero rows is the same
  silent-empty-population defect `artifact_digest` already refuses for an empty
  capture, one level up (found in cross-model review, #39).
- No path may repeat within one stream: a second row for the same skill is a
  conflicting count, and nothing here can say which is true (found in
  cross-model review, #39).
- Each `path` must be one the attempt's own `installation-receipt` actually
  installed. `observation_coverage` (a record rule) checks the stream's own
  shape; only `ledger_binding` (a bundle rule) has the receipt to check a path
  against, exactly as it already does for a stale receipt or an altered
  artifact.

**Closed by #26.** The issue's own acceptance list includes "the stream is
required by the chosen version but absent" as a refused case; #39 deferred it
because a *case* was not yet a record kind or a validated field anywhere in
this schema. #26 adds exactly one field to close it: `case.observes_selection`,
an OPTIONAL boolean on the trial ledger's existing `case` identity (`id`,
`revision`). Absent (the default) means the same as before this section: the
`skill-invocations` stream stays fully optional. Declared `true` means the
attempt's own case observes native skill selection as a criterion, and
`records.ledger_binding` then REQUIRES a `skill-invocations` observation in
that attempt's manifest - its absence is refused, not silently accepted.
`skillc/trial.py`'s `_OPTIONAL_IDENTITY` type-checks the field at plan time
(a caller writing `"observes_selection": "true"` gets a refusal naming the
type, not a silently-stringified truthy value); `records.trial_ledger`
type-checks it again on any already-written ledger record, since a producer
outside this controller could write one directly. Committed controls:
`controls/trial-ledger/{bad,good}/observes-selection*.json` (the type check)
and `controls/ledger-binding/{bad,good}/skill-invocations-*` (the requirement
itself, bad = declared but absent, good = declared and present).

**The client route is a fact each adapter declares, not one skillc infers.**
Claude Code exposes invocation as a `Skill` tool call, so its adapter can
declare `origin: observed`. How Codex reveals that a skill was used is
unestablished - #39 does not resolve this, because resolving it needs a live
run against a real Codex session, which is #7/#10 territory, not this bounded
follow-up. Until an adapter can name a real route, it declares `coverage:
unsupported` with every count `"UNKNOWN"`. **Do not substitute a file-read
heuristic** (did a skill's directory appear in a prompt, was a file under it
opened) for a real invocation signal. This project's own reading of
config-drift-checker already names the trap
([config-drift-checker-lessons.md](../../research/config-drift-checker-lessons.md),
"Traps the reading showed"): its "invoked by substring" match on any `Skill`
tool input containing the skill's directory or name, lowercased, lets a short
name such as `run` match unrelated input. A heuristic that _looks_ like
observation is worse than an honest `unsupported`, because its false positives
are silent.

## `attempt-lifecycle`

Produced by the controller ([capture.md](capture.md)), one per planned attempt: what
became of it.

| Field | Content |
|---|---|
| `disposition` | `captured`, `not-run`, `unavailable` or `inconclusive` |
| `reason` | required unless `captured`: a non-result says why |
| `stop` | `reason` (`exited`, `timeout`, `budget-exhausted`, `operator-cancelled`, `launch-failed`, `never-started`, `unobserved`) and `confirmed` (boolean) |
| `events` | non-empty, starting at `planned`; each an event from the fixed vocabulary with its time |
| `cleanup` | `status` (`removed`, `already-absent`, `not-needed`, `partial`, `refused-not-owned`) and a `failures` list |

`captured` requires a **confirmed** stop, a stop reason under which something ran,
and a `captured` event: bytes taken before the subject stopped could still have
been changing. `not-run` requires `never-started`. Only `not-run` and `unavailable`
may say `never-started`.

Why a separate kind rather than a result: a v2 result cannot say "INCONCLUSIVE,
nothing was captured". A graded result must cite graded digests, and INCONCLUSIVE
may not be declared as a run state.

## `agent-observation`

Produced by the controller (`skillc/agent_trial.py`'s `run_one_attempt`), one per
real-agent attempt, as `observation-<attempt>.json` beside
`lifecycle-<attempt>.json`. It is written on every path, including an attempt
blocked before launch, and one whose grading raised (it is persisted with the
failure as its blocked reason, and the failure then propagates). Before #106 these conclusions existed only in memory and a
printed paste-back, so a misprinted field could not be recovered: #124 repeated
two live runs for that reason.

| Field | Content |
|---|---|
| `client` | whose transcript: `claude` or `codex` |
| `status` | `observed`, `unknown` (the transcript hook failed) or `not-observed` (nothing ran to read) |
| `reason` | required unless `observed` |
| `transcript` | only when `observed`: transcript files found, `prompt_delivered` and its reason, `canary_satisfied` and its reason, `skill_invocations` and whether their detection is `structural` or `heuristic`, `skills_listed` and its source, `grading_eligible`, and a `census` of the transcript's format (client version, model, line types, unrecognized types, response items inspected) |
| `credential` | `delivered`, `source`, `remaining_seconds_at_launch`, `refresh_observed_in_container`; null where not observed |
| `grading` | `grader_supplied`, `eligible`, and either `blocked_reason` or `graded_status` with `category` and `criteria` (`id`, `mandatory`, `outcome` only) |

The schema is **closed, complete and typed** at every level. An unknown field, a
missing field, and a value of the wrong type (an object in a scalar field, say)
are all refused, so no field exists that a transcript excerpt or credential
value could be copied into. Positive conclusions (prompt delivered, canary
satisfied) must rest on exactly one transcript file. A new
observation field has to be named in `records.py` before it can be recorded,
which fails loudly. Before writing, the controller redacts the host paths it
knows, then leak-checks the record twice: each string as it reads once parsed,
and the serialized text. A record that fails is not written, and the attempt
says `observation_record: refused-leak`.

Three facts must agree inside the record:

- **Eligibility:** `grading_eligible` is exactly `prompt_delivered AND canary_satisfied`.
- **Grading account:** a supplied grader either graded or was blocked, never both
  and never neither.
- **Grade against criteria:** a `PASS` or `FAIL` agrees with what its own copied
  criteria derive.

**It is not a verdict.** The grade is an audit copy of what the driver's grader
returned. It stands in for no `verified-result`, and `attempt-accounting` still
counts only results. A captured agent attempt therefore still reads as "grading
still owed" until a result is written for it. That gap predates this kind and is
recorded in the Nit Store (#20). `agent-observation` is attempt-bound, so
`ledger-binding` and `unique-ids` apply to it: one per attempt, under the trial
the ledger planned.

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

From interfaces.md, in the order the sentences bind:

1. "An established mandatory violation remains FAIL when another criterion is
   unknown" - so any `VIOLATED` mandatory criterion yields `FAIL`, tested **before**
   unknowns **and before any declared run state**.
2. A declared `UNAVAILABLE` or `NOT_RUN` run state is honoured.
3. "missing mandatory evidence prevents PASS" - so any non-`SATISFIED` mandatory
   criterion yields `INCONCLUSIVE`.
4. Otherwise `PASS`.

Step 1 moved ahead of the run state in #130. Version 1 honoured a declared run
state first, which contradicted protocol.md section 4: UNAVAILABLE applies only
"without an already-established task failure". Honouring it first let a FAIL be
relabelled UNAVAILABLE and validate clean. A record that declares a run state
its criteria contradict is refused by `derived-status`, even when its `status`
already says FAIL.

Optional criteria never enter this computation. **No mandatory criteria yields
`INCONCLUSIVE`, never `PASS`.** The other three statuses may not be declared as a
run state, or the forged verdict would simply move from `status` into `run_state`.

## `pilot-report`

Additive in version 2 (#12). Produced by the assembler after a completed
pilot: issue #12's own acceptance list ("Report every scheduled attempt by
protocol disposition, per-criterion success, uncertainty, claim accuracy,
intervention counts, time and observed cost with missing values explicit")
had no home in the schema until this - the per-attempt records above each
carry one attempt's own account, and nothing aggregated them into the
evidence report a completed pilot's acceptance actually requires.

| Field | Content |
|---|---|
| `experiment_id` | the experiment this report covers |
| `attempts` | one entry per attempt the report covers, never empty |

Each `attempts` entry:

| Field | Content |
|---|---|
| `attempt_id`, `trial_id` | which attempt, and under which trial |
| `disposition` | the same vocabulary `attempt-lifecycle` uses (`captured`/`not-run`/`unavailable`/`inconclusive`) |
| `criteria` | `{id, outcome}` pairs, `outcome` from the same `SATISFIED`/`VIOLATED`/`UNKNOWN` vocabulary `verified-result` uses |
| `uncertainty` | a non-empty string, explicit even when there is none to report (e.g. `"none"`) - silence is not the same fact as "nothing uncertain" |
| `interventions` | a non-negative integer count |
| `cost_usd`, `time_seconds` | each an object with EXACTLY `setup`, `agent`, `grading`, `total` - #12's own "separate setup/agent/grading cost and time" |

**Missing values are explicit, never a silently absent key.** Each of
`cost_usd`/`time_seconds`'s four keys must be present; its VALUE is either a
non-negative number or the literal string `"UNKNOWN"` - the same spelling
`skill-invocations` already established for the same reason (silence is not
absence). When every one of the four is a real number, `setup + agent +
grading` must equal `total`; an "UNKNOWN" anywhere makes the sum
unverifiable, not wrong, so the check is skipped rather than guessed at.

**Completeness against the ledger is a bundle fact, not a record one**
(`ledger_binding`, #12's own control): a report that omits an attempt the
ledger scheduled, or names one it never planned, is refused. `pilot_report`
(this record's own rule) checks only each entry's shape - exactly the same
division `observation_coverage`/`ledger_binding` already draw for
`skill-invocations`.

**What this does NOT establish (found by cross-model review, #12): the
completeness check is ATTENDANCE only, by attempt_id, not agreement.** A
report entry naming a scheduled `attempt_id` satisfies it whatever
`disposition`, `trial_id` or `criteria` that entry declares - it does not
cross-check the entry's `disposition` against the attempt's own
`attempt-lifecycle` record, or its `trial_id` against the ledger's plan, the
way `ledger_binding`'s per-attempt-bound-record loop already does for
receipts and results. A pilot report could legitimately declare `captured`
for an attempt its own lifecycle record says was `not-run`, and this rule
would not catch it. Narrowing that gap is a further, separate control, not
delivered here - #12's own acceptance names only "reject a report missing a
scheduled attempt", which this rule answers exactly.

**What this does not deliver.** No code here produces a report from a real
run - that needs a live attempt loop, which does not exist yet (#10's Docker
backend implementation lifecycle bodies exist since #85, but no controller
drives a real experiment through them end to end). This is the SCHEMA a
future report must satisfy, proven against synthetic fixtures
(`controls/pilot-report/`, `controls/ledger-binding/*/pilot-report-*`), not
a generator.

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
  graded an **altered** or substituted artifact;
- if a manifest declares a `skill-invocations` observation (#39), every `skills`
  row's `path` is one the attempt's own installation receipt actually installed.
  Otherwise it names a skill this attempt never had.

**`unique-ids`.** interfaces.md makes "duplicate/conflicting IDs" an explicit
validation failure:

- no trial or attempt ID is planned twice;
- an attempt has at most one receipt, one manifest and one lifecycle. A second one
  is a conflicting account, and nothing here can say which is true;
- results may be several (a regrade is a new result), but each `result_id` is unique.

**`attempt-accounting`.** "Every planned attempt remains accounted for" (EF-07).
The controller's account is the lifecycle record (#8):

- every planned attempt has an `attempt-lifecycle`. Without one it has silently
  dropped out, whatever results exist;
- a `captured` attempt has its artifact manifest and a result. Without a result,
  grading is still owed;
- a `not-run` or `unavailable` attempt needs no result. A result it does have
  declares the matching run state (`NOT_RUN`, `UNAVAILABLE`);
- an attempt the controller did not capture carries no manifest and no graded
  result, and a captured one carries no declared non-run: the accounts would
  disagree;
- an attempt that was graded (its result declares no run state) also has its
  installation receipt and artifact manifest.

Before #8 this rule required a result for every planned attempt. It now requires a
lifecycle instead, and a result only where bytes were captured.

**`lineage`.** protocol.md: "A rerun gets a new ID and links to the original.
Regrading creates a new result linked to the unchanged original artifact ... Neither
operation erases the earlier attempt."

- A retry's `retry_of` names a different attempt in the same trial.
- A regrade's `regrade_of` names a result retained in the bundle, for the same
  attempt and with the same `graded_digests`.

## Retention boundary

The boundary below is unchanged. #8 turned it into a location, access and
retention policy, in [capture.md](capture.md#storage-access-and-retention-reviewmd-q5)
(review.md Q5):

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

`check-records` enforces nothing here beyond the `raw` digest and lineage rules.
The controller (`skillc/trial.py`) enforces the store location, write-once records
and export exclusions.

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
| `trial-ledger` | record | no trials; a trial with no attempts; missing grader identity; malformed attempt ID; `case.observes_selection` present but not a boolean (#26) |
| `artifact-digest` | record | an artifact without a digest; an empty manifest; a null `path`, `type` or `size` beside a valid digest (#130) |
| `observation-coverage` | record | a silent required stream; an unknown origin; no `capture_failures`; a `skill-invocations` count that is not `UNKNOWN` under incomplete coverage, or not a real integer under complete coverage; complete coverage naming no skills; a duplicate skill path with conflicting counts (#39) |
| `criterion-vocabulary` | record | an outcome outside the vocabulary; a non-boolean `mandatory` (`"true"` would drop a violation out of the derivation); a criterion with no `id` (#130) |
| `result-evidence` | record | SATISFIED without evidence; UNKNOWN without `missing`; no graded digests; no grader; a run state without reason; a `run_state` other than `UNAVAILABLE`/`NOT_RUN` (#130) |
| `derived-status` | record | a status copied rather than derived; an `UNAVAILABLE` or `NOT_RUN` run state declared over an established mandatory `VIOLATED` (#130) |
| `verdict-tiers` | record | a `verification.verdicts` entry for a tier absent from `verification.tiers_enabled`; an enabled tier with no entry at all; an `UNAVAILABLE` verdict with no stated reason (#69) |
| `attempt-lifecycle` | record | an unknown stop reason or disposition; a non-result without a reason; captured before a confirmed stop; no cleanup |
| `agent-observation` | record | an unknown field; a missing field; an object in a scalar field or a census map; a `mandatory` flag that is a string, an integer or absent (each would drop a VIOLATED criterion out of the derivation); positive conclusions from zero or two transcript files; eligibility that disagrees with prompt delivery and the canary; a PASS its own criteria do not derive; both a grade and a blocked reason; an unobserved status without a reason (#106) |
| `pilot-report` | record | empty attempts list; bad disposition or criterion outcome; no uncertainty; a negative intervention count; a cost/time split missing a key or whose parts do not sum to its total; a duplicate attempt ID (#12) |
| `ledger-binding` | bundle | cross-trial receipt; stale receipt; attempt the ledger never issued; altered artifact; unplanned grader; a `skill-invocations` path the attempt's receipt never installed (#39); a trial declaring `case.observes_selection: true` whose manifest has no `skill-invocations` stream (#26/#39); a `pilot-report` that omits a scheduled attempt or names one the ledger never planned (#12) |
| `unique-ids` | bundle | duplicate attempt ID; conflicting receipts; duplicate result ID |
| `attempt-accounting` | bundle | planned attempt with no lifecycle; captured with no result; graded without receipt; graded without manifest; captured but declared NOT_RUN; graded but not captured; manifest but not captured |
| `lineage` | bundle | retry reusing its own ID; regrade whose original was erased; regrade of different bytes |

Record and bundle rules live in the **same registry and the same selftest loop** as
the `SKILL.md` rules. Only the subject-loading step knows the family.
`test_an_uncontrolled_record_rule_is_UNPROVEN` and
`test_an_uncontrolled_bundle_rule_is_UNPROVEN` establish that no arm was split off.

## Boundary

This completes #4's contract versioning. What it deliberately does not do:

- **No runtime here.** This module validates. The controller that writes the
  ledger, lifecycle and manifests is `skillc/trial.py` (#8,
  [capture.md](capture.md)); the verifier and result assembler is
  `skillc/verify.py` (#9, [verification.md](verification.md)). Runtime packages
  stay outside `skillc/`, which the stdlib import walk in `tests/test_frontmatter.py`
  enforces with its own negative control.
- **No authentication.** Digests are checked for agreement between records, never
  against the bytes they name, and `producer` is declared. Both need the trusted host.
- **One ledger per bundle.** An experiment spread across bundles is checked bundle by
  bundle. No rule yet asks whether two bundles planned the same attempt.
- **Readiness gates a PASS when grading, not here.** `check-records` still does not
  refuse a PASS over a receipt whose discovery canary failed. The verifier (#9)
  never writes one: its `installation-ready` criterion makes such a trial
  INCONCLUSIVE ([verification.md](verification.md#the-result)). A case whose goal is
  the installation itself (protocol.md section 3) is not yet declarable.
- **The grader pin is enforced when grading, not here.** A trial ledger's `grader`
  may carry a `digest` (#9); `ledger-binding` still binds a result by grader id and
  revision only.
