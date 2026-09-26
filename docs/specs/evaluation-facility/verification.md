# Independent grading and result assembly

- Status: Implemented as `skillc/verify.py`, #9. API only; no CLI subcommand yet.
  #10 PR2 adds an optional execution-backend seam for the probe stage (below);
  #10's Docker backend, which would actually drive it end to end, does not
  exist in this repository yet.
- Date: 2026-09-26
- Governing documents: [interfaces](interfaces.md), [protocol](protocol.md), [records](records.md), [capture](capture.md)
- Decisions: [ADR 0001](../../decisions/0001-every-check-ships-a-redcase.md), [ADR 0003](../../decisions/0003-no-external-evaluation-runtime.md)

## What it does

interfaces.md gives the verified result to "an independent verifier and controller
result assembler". `skillc/verify.py` is both. It grades what the controller
froze, and it writes the only `verified-result` records. That covers lifecycle
step 8 ("Verify in a fresh environment using a disposable copy and trusted
grader inputs") and protocol.md section 4's derivation.

```
grade(experiment, attempt, grader)
  refuse unless: ledger pins this grader's digest; attempt captured; receipt present and not stale
  frozen_artifacts ------------> bytes re-hashed (#8's gate)
  snapshot the experiment store
  1. PROBE   (untrusted)  fresh root: disposable copy + probe harness + inputs only
                          supervisor = child subreaper; sweeps every descendant
  2. JUDGE   (trusted)    new directory, created after the sweep: judge file only
  3. ASSEMBLE             exact criterion set, record contract, derive_status,
                          + verifier's own `installation-ready` criterion
  re-check: grader digest == pin; store == snapshot; ledger == history; bytes
  add_result ------------------> result-<id>.json (admission rules of #8)
```

## A grader is three files and a definition

`evals/level1/<task>/grader.json` declares a grader. Every field is required and
unknown fields are refused:

| Field | Meaning |
|---|---|
| `id`, `revision` | The identity the ledger plans |
| `criteria` | The exact set of mandatory criteria every report must carry |
| `probe.file`, `probe.inputs`, `probe.timeout` | The harness that runs candidate code, the inputs it is given, its time limit |
| `judge.file`, `judge.timeout` | The program that holds the answers and emits the criteria |

Files are plain names in the grader's own directory. A name with a path
separator, or a file that is a link, is refused. `GraderDef.digest()` covers the
bytes of `grader.json` itself, every field as loaded, the names of the three
files and their bytes. So rewriting only the definition, or pointing it at a
different file with the same bytes, changes the pin.

**The pin.** The ledger's `grader` identity carries that digest
(`{"id", "revision", "digest"}`), written by the controller before dispatch. The
verifier reads the three files **once**, before any candidate code runs, and
refuses to grade when the pin is missing or does not match those bytes. The probe
and the judge are then written from those bytes, never from the grader's files.
After grading, it re-reads the files and refuses the result if they changed. A
missing digest is refused, never warn-and-proceed.

Executing the pinned bytes, and not only re-checking the files afterwards, is
load-bearing. A candidate can swap in a judge that prints PASS and restores the
original when it runs. Re-read from disk, that judge would run, and the files
would match again by the time they were checked. The counter-model review found
this; `test_a_self_restoring_judge_is_never_what_runs` pins it.

## The three stages

**1. Probe: the only stage that runs candidate code.**

- A fresh owned root, outside the evidence store and the grader directory,
  receives:
  - a **disposable copy** of the frozen artifacts, written from the controller's
    content-addressed objects rather than from the subject's workspace;
  - the probe harness;
  - the inputs.
- The answer key is not there. The probe reports what the candidate did. It never
  sees what it should have done.
- The environment is exactly `PATH`, a `HOME` inside the root, `LANG` and
  `PYTHONDONTWRITEBYTECODE`. Nothing is **inherited**, so no evaluator credential
  is handed to candidate code. That is not confidentiality: see "Trust
  assumptions".
- Manifest paths are rechecked before they are written. A stored bundle is
  untrusted input (lesson 6 below), and a `..` part is refused.

The probe runs under a **supervisor** (`python -I -S -B -c SUPERVISOR`):

- It makes itself a Linux **child subreaper** (`prctl(PR_SET_CHILD_SUBREAPER)`).
  Every descendant of the probe is reparented to it, including one that called
  `setsid` and left every process group #8's controller could see.
- When the probe exits or times out, it SIGKILLs every child until none remains.
- It reports the outcome **through its exit code**:

| Exit | Meaning |
|---|---|
| 0 | The probe exited; every descendant is gone |
| 10 | The probe timed out; every descendant is gone |
| 20 | Descendants survived the sweep |
| 21 | This host cannot contain the probe (no `prctl` or `/proc`) |
| other, or a signal | The supervisor did not finish, or candidate code killed it |

The exit code is the one channel candidate code cannot write. It can write any
file or pipe the supervisor holds, but it cannot choose the supervisor's exit
status. Only 0 and 10 count as a confirmed sweep. Anything else is recorded as a
`containment` failure: every required criterion is UNKNOWN and the result is
INCONCLUSIVE.

When containment is lost (anything but 0, 10 or 21), the verifier makes a best-effort
second sweep. It SIGKILLs every process whose working directory is inside the
probe's directory, or whose `HOME` is the probe's, and records the count as
`fallback_killed`. Nothing then establishes that every candidate process is gone,
so the verifier **quarantines itself**: every later grading run in that process
refuses until an operator calls `verify.clear_quarantine()`. A survivor could
otherwise write into the next run's store or judge.

Every file candidate code could have replaced is opened non-blocking and without
following a link, and read only if it is a regular file, within a bound. That
covers the probe's report and stderr, the grader's files when they are re-read
after grading, and the disposable root's ownership marker at cleanup
(`materialize.cleanup`, which #8's workspace cleanup shares). A FIFO swapped in for
any of them would otherwise block the verifier forever, after every deadline had
passed. A replaced marker makes cleanup report `refused-not-owned` and leave the
root in place, and the result records that.

**What the probe prints is an observation.** Candidate code shares the probe's
process and can write the probe's report. It gains nothing it could not gain by
returning values. The judge reads the report strictly: anything but a
well-formed report of returned values, one per input, is an interface violation
by the candidate.

**2. Judge: trusted, and started last.** The judge directory is created **after**
the sweep, and holds only the judge file. It runs as
`python -I -S -B JUDGE --judge`, with the envelope
`{"observations", "timed_out"}` on stdin and its report on stdout. No candidate
process is alive to write on that stdout, the success channel. Its outcomes are
classified as follows:

| Outcome | Category |
|---|---|
| exit 0 with a JSON object | `verdict` |
| non-zero exit | `exit-nonzero` |
| exit 0, nothing printed | `no-output` |
| not JSON, not an object | `unparseable` |
| over its time limit | `timeout` |

**3. Assemble: in the verifier's own process.**

- The report must carry exactly the definition's criteria, each mandatory, each
  once (`criteria-set`). It must also pass records.md's `criterion-vocabulary` and
  `result-evidence` rules (`contract`).
- Only then do its criteria stand. Otherwise each required criterion becomes
  UNKNOWN, naming why.
- The judge's own `status`, `grader` or any other claim is dropped. The status
  is `records.derive_status` over the criteria.

## The result

`grade` stores one `verified-result`, `producer: assembler`, through
`trial.add_result`, so #8's admission rules still apply:

- `grader` is `{id, revision, digest}` from the pin.
- `graded_digests` lists every frozen artifact.
- `criteria` holds the grader's criteria plus the verifier's own
  `installation-ready`.
- `status` is derived.
- `verification` records the category, a detail line, the containment
  observation (supervisor exit, confirmed, timed out, cleanup) and the host's
  Yama `ptrace_scope`.

**Readiness gates PASS.** This resolves the boundary records.md and capture.md
left to #9. `installation-ready` is SATISFIED only when the attempt's receipt
reports both `discovery_canary` and `baseline_absence` SATISFIED, and otherwise
UNKNOWN. So a trial whose installation was not established cannot PASS: it did
not measure the subject as installed. An observed task violation still derives
FAIL, because VIOLATED is tested before UNKNOWN. A case whose goal IS the
installation (protocol.md section 3) would need that role declared per case.
That is not supported yet, and every case is currently read as setup-not-goal.

**Refused, and nothing written**, when:

- the ledger pins no grader digest, or a different one, or plans another grader
  id or revision;
- the attempt is not a finalized `captured` attempt;
- the attempt has no installation receipt, or its receipt names another subject,
  client, attempt or trial (a stale receipt);
- a frozen object no longer matches its digest (#8's `frozen_artifacts`);
- after grading, the grader's digest, the experiment store's contents (a snapshot
  of every file, link and directory) or the ledger's history differ from before;
- the verifier is quarantined after lost containment.

The store snapshot covers the whole experiment, so a legitimate concurrent write,
such as another attempt's capture landing mid-grade, is refused exactly like
tampering. That is fail-closed: a false refusal, never a false PASS. The
refusal says so, and grading needs an experiment nothing else is writing. No lock
enforces that yet.

A refusal is loud: the attempt stays owed a grade, and `attempt-accounting` says
so. A grader that gives no verdict is **not** refused. That result is stored as
INCONCLUSIVE, with its category, because "the grader crashed" is a fact about
the trial that the record must keep.

**Regrading.** `regrade(experiment, result_id, grader)` grades the same frozen
bytes again, as a new result with `regrade_of` set. The original is retained.
The grader must still be the pinned one, so a deterministic grader repeats its
outcomes. The test compares the two results' criteria. A new grader revision
would need a new pin, which this build does not provide.

## The level-1 slug grader

`evals/level1/slug-small-fix/` is split along these lines (revision 2):

- `probe.py` runs the candidate on `inputs.json`.
- `grade_slug.py --judge` holds `HELD_OUT` with its answers.
- `qualify.py` now certifies through `verify.grade_directory`, the same staged
  path. A broken-grader control replaces the judge (`GraderDef.with_judge`), and
  its digest differs, so a ledger pinned to the real grader refuses it.

## How each acceptance item is shown

Every case runs end to end: `tests/test_verify.py` plans an experiment with
`trial.py`, runs `tests/fixtures/trial-subject/fake_subject.py`, captures and
grades.

| Acceptance (#9, #6 transfer) | Red case | Green case |
|---|---|---|
| Known-good/bad outputs | `wrong/no-collapse` -> FAIL on exactly `reported-example`, `R2` | reference -> PASS; both bundles pass `check-records` |
| Forged prose/JSON, contract echo, stdout framing | wrong candidate + forged `task.json`, PASS sentinel, success prose -> FAIL | the same forgeries beside a correct candidate -> PASS |
| Modified local tests, checker or pass file | wrong candidate + trivial tests, an always-pass `grade_slug.py`, `grader.json`, `expected.json` -> FAIL | - |
| Candidate writes verifier output | a forged verdict on the probe's report channel -> FAIL (`R4-interface` "malformed"); a planted `result-*.json` or an edited ledger -> refused; an edited judge file -> refused | the same body without the write -> PASS |
| Candidate outlives the probe | a `setsid` process -> swept, pid dead, result stands | - |
| Candidate replaces the judge with a self-restoring always-pass | -> refused; the swapped judge never ran | - |
| Candidate replaces the report with a FIFO | -> FAIL (`R4-interface`), no hang | - |
| Candidate replaces a grader file or the ownership marker with a FIFO | grader file -> refused; marker -> cleanup `refused-not-owned`; neither hangs | - |
| Candidate rewrites only `grader.json` | -> refused | - |
| Candidate kills the supervisor | -> INCONCLUSIVE, `containment` | - |
| ... and stays alive | -> killed by the fallback sweep; the verifier quarantines and refuses the next run until cleared | after `clear_quarantine`, the reference PASSes |
| Evaluator credentials, inheritance | a secret in the verifier's environment is absent from the candidate's `os.environ` | the dump holds `PATH` (it ran) |
| Evaluator credentials, confidentiality | **a limit, pinned**: candidate code reads the token from an ancestor's `/proc/<pid>/environ` | - |
| Stale receipt, missing digest | no receipt, a planted stale receipt, no pin, a wrong pin, a modified object -> refused | - |
| Readiness | canary VIOLATED + correct -> INCONCLUSIVE; + wrong -> FAIL | - |
| Status derived | a judge claiming `status: PASS` beside violated criteria -> FAIL | - |
| Always-pass/always-fail/crash/no-output graders | crash, no-output, omits-criterion -> stored INCONCLUSIVE with their category; always-pass and always-fail are refused by `qualify.py` through this path | - |
| Deterministic regrading lineage | a regrade with another judge -> refused (pin) | regrade -> same criteria, linked, original retained |
| Backend-driven probe (#10 PR2) | `confirm_stopped()` UNKNOWN/NOT_CONFIRMED -> INCONCLUSIVE, never treated as confirmed; `BackendUnavailable` from `prepare()`/`install()` -> INCONCLUSIVE, never a silent fall-back to the bare-subprocess path | a `FakeBackend` that runs as an ordinary host subprocess (proves the driver's sequencing only, never a boundary - see below) -> PASS, `verification.verdicts.deterministic.backend` names it |

Each protection was also removed once, and the test that names it went red:

- no subreaper -> the escaped pid stayed alive;
- no store snapshot;
- environment inherited;
- no grader re-check;
- no pin required;
- status copied;
- no readiness criterion;
- a crash read as FAIL;
- the supervisor's exit trusted blindly;
- the judge re-read from disk (the self-restoring judge PASSed);
- no fallback sweep (the survivor stayed alive);
- no quarantine;
- a blocking read of the report, of a grader file, or of the marker (each hung);
- `grader.json`, or the file names, left out of the pin.

## Trust assumptions

The following are assumed, not shown:

- **The controller host, this package and the Python standard library are
  trusted.** interfaces.md places them inside the trusted system. The verifier
  process imports `skillc`; a subject that rewrites installed Python files is
  outside what is checked here.
- **Evaluator credentials must not be in the verifier's environment.** The
  environment is not inherited, but same-user candidate code can walk its
  ancestors and read `/proc/<pid>/environ` of any of them. Whatever started the
  verifier started with is readable.
  `test_an_ancestors_environment_is_NOT_hidden` pins that as a LIMIT, not a bug:
  it asserts the token IS found, and its own docstring says to update it if a
  host ever reports "hidden". Keeping credentials away from candidate code
  needs a separate process/user namespace boundary - #10 PR2 lets the probe run
  through an `ExecutionBackend` instead of a bare subprocess (see "Execution
  backend for the probe" below), but no concrete backend exists in this
  repository at this commit, so this test cannot flip yet: doing so needs an
  actual container run, not a fake backend standing in for one (lesson E17,
  below). Until a real backend demonstrates otherwise, run grading from a
  process tree that holds no credential. Only non-inheritance is established
  here.
- **Candidate code runs as the evaluator's own user, UNLESS a backend is
  given.** This is the bare-subprocess (`backend=None`) default:
  - A write to the evidence store, the ledger or the grader's files is therefore
    **detected** (snapshot and digest), not **prevented**.
  - The answer key is not in the probe's directory, argv, stdin or environment,
    but its file on disk is readable by a candidate that searches for it.
  - Prevention needs a separate user or a container. Given an `ExecutionBackend`
    (#10 PR2), prevention becomes whatever THAT backend's own `describe()`
    claims - never this module's own claim, and never assumed true merely
    because a backend was supplied. This module's detection-based checks above
    still run regardless, as defense in depth.
- **The judge is correct.** `qualify.py` certifies it against committed good and
  bad candidates and broken-grader controls. The verifier does not re-run that
  certification, and cannot tell a blind grader from a working one on one
  candidate. A ledger should pin a digest `qualify.py` certified; nothing yet
  records that link.
- **Ptrace.** The supervisor's exit code and the verifier's memory are out of
  reach only because candidate code cannot ptrace its ancestors. That holds
  under Yama `ptrace_scope` 1 or higher. With scope 0 a same-user process can
  attach to any process. The scope is recorded in each result as observed, not
  enforced.
- **Linux.** The sweep needs `prctl` and `/proc`. Elsewhere the supervisor exits
  21 and the result is INCONCLUSIVE.
- **Quarantine is per process.** It stops the verifier that lost containment. A
  different process on the same host is not told, and a survivor that left the
  probe's directory and changed its `HOME` escapes the fallback sweep.

## Unobserved properties

The following are not checked, and should not be read as held:

- **What candidate code read.** Nothing observes file reads during the probe, so
  a candidate that read the answer key and returned the right values is
  indistinguishable from a correct one.
- **Network access.** The probe is not network-isolated. Held-out answers are not
  online, but a candidate could reach a service.
- **Effects outside the store and the grader.** A write anywhere else on the host
  is not snapshotted, and a signal sent to an unrelated process is not seen.
- **Grader determinism beyond one regrade.** A single regrade reproduced the
  outcomes. That is one observation, not a proof for every candidate.
- **Integrity of the store between graded runs.** Detection covers the grading
  window. Earlier or later edits are #8's history and digest checks, which bind
  the subject, not the operator.
- **`check-records` does not verify the grader digest.** A result is bound to its
  ledger by grader id and revision, as before. The pin is enforced when grading,
  not when a bundle is read back.
- **A backend's isolation claims, when no real backend exists yet.** #10 PR2's
  tests exercise the probe-via-backend DRIVER (sequencing, refusal on
  `BackendUnavailable`, non-confirmed handling) against a fake backend that
  runs as an ordinary host subprocess and says so in its own `describe()`.
  That proves the driver correctly drives ANY conforming backend through the
  steps; it proves nothing about confidentiality or write-prevention, which
  are properties only a real, isolating backend has. See the next section.

## Execution backend for the probe (#10 PR2)

`grade`/`grade_files` accept an optional `backend: ExecutionBackend | None`.
`None` (the default) is everything above, unchanged. Given a backend, only
stage 1 (the probe) changes: it runs inside a fresh, SEPARATE instance of that
backend (interfaces.md step 8), through `skillc/backend.py`'s Protocol -
`prepare` / `install` / `execute` / `confirm_stopped` / `export` / `destroy` /
`confirm_absent` - the same seam `skillc/lifecycle.py` drives for agent
execution. Stage 2 (the judge) is unchanged either way: it is trusted code,
never candidate code, so it needs no container.

**Surface convention for probe use.** `install()`'s `surface` parameter has no
Protocol-fixed key set (`Mapping[str, object]`); #7/`lifecycle.py`'s
agent-execution callers use a skill-materialization vocabulary, and probe
callers use a different one, agreed directly with the Docker backend's author
(#10, mailbox coordination): every surface entry whose value is `bytes` is
written into the backend's fixed workspace root at that relative path (the
grader's probe file, `inputs`, and `candidate/<path>` per candidate file).
Nothing here requires a Protocol change.

**`confirm_stopped()` is the sole containment authority** when a backend is
used - never the bare-subprocess supervisor's exit code, which does not exist
in this path. `UNKNOWN` and `NOT_CONFIRMED` are both treated as NOT contained,
exactly as the bare-subprocess path already treats an unswept probe: criteria
go UNKNOWN, the judge never runs.

**`BackendUnavailable` is a refusal, never a silent fall-back** to the
bare-subprocess path - matching `backend.py`'s own rule for agent execution,
generalized to grading. A caller that wants the fallback behaviour asks for it
explicitly by passing `backend=None`; this module never chooses that for them.

**What this establishes, and what it does not.** This module's OWN guarantees
(non-inheritance of environment, detection via snapshot/digest, quarantine on
lost containment) apply regardless of whether a backend is used - defense in
depth, never removed. A backend's OWN claims - confidentiality, write
prevention - are exactly what its `describe()` states, no more; this module
never asserts them on the backend's behalf. **No concrete backend exists in
this repository at this commit** (`skillc/docker_backend.py` is not written
yet), so every claim a real backend WOULD make is OWED TO THE LIVE RUN (issue
#10 comment 5848522578, lesson E17: "unit tests on a fake backend prove the
lifecycle, never the boundary") until #10's Docker backend lands and is
actually run this way, against a real trial, on a real Docker host.

## Grading tiers (#69)

Three tiers, owner-ratified as the target architecture (issue #69) - only the
first is built:

1. **Deterministic** (built, this is `GRADING_TIER`). Structural/outcome
   checks, no model call. Everything above this section describes it.
2. **LLM-judge + deterministic** (not built; #69). A model call added on top,
   using whichever model is configured. If that model is the same one that
   produced the candidate's work, this is the weaker, "generic" case: it
   reintroduces the self-assessment bias independent grading exists to avoid.
   A verdict record from this tier MUST say so in the record itself, not only
   in documentation, so a same-model grade is never read as an independent one.
3. **Independent-llm-judge + deterministic** (not built; #69). The judge call
   is routed to a DIFFERENT, independently configured model -
   [`mcp-second-opinion`](https://github.com/cooneycw/mcp-second-opinion) is
   the owner-named planned mechanism (#69), a standalone public tool with no
   coupling to this project; skillc does not vendor or depend on it (ADR 0003).

### Verdicts are a keyed collection, never a single value (owner ruling on #69)

The first cut of this PR gave every result a single `verification.grading_tier`
field. A fresh owner ruling superseded that before any real trial record ever
existed: when more than one tier is enabled, a trial is graded by ALL of them
together, each with its OWN verdict - never averaged, weighted, or overridden.
So the shape is a collection keyed by tier name, not one value:

- **`verification.tiers_enabled`** is the list of tier names this result
  actually requested, e.g. `["deterministic"]` today. A tier absent from this
  list was never asked for.
- **`verification.verdicts`** is an object keyed by tier name, with **exactly
  one entry per enabled tier - never more, never fewer.** Each entry carries
  its own `status` (one of the closed `PROTOCOL_STATUSES`), its own
  `criteria`, and a `backend` identity where one applies (`describe()`'s
  claim, or `None` for the bare-subprocess path); tiers 2/3 add a `judge`
  sub-record (model + version) beside those. `check-records`' `verdict-tiers`
  rule checks BOTH directions (orchestrator review of PR #88, ffae7eb, after
  the first cut checked only one): **an entry for a tier not in
  `tiers_enabled` is refused**, and **an enabled tier with no entry at all is
  equally refused** - the same silent drop #69 forbids ("one judge
  unavailable gives that tier `unavailable` while the others still report"),
  just facing the other way. An unavailable judge therefore still writes its
  own entry, `status: "UNAVAILABLE"`, and that entry MUST state why
  (`reason`) - a bare absence is never read as "unavailable", and neither is
  an `UNAVAILABLE` status with no stated reason.
- **`verification.disagreement`** is reserved for the per-criterion
  same-model-vs-independent comparison tiers 2/3 make possible. Today it is
  always `{"available": false, "reason": "fewer than two judge tiers"}`:
  comparing needs two independently-graded verdicts, and there is exactly one
  tier, ever, in this build. This build never fabricates a comparison to fill
  the field.
- **The top-level `status`/`criteria` are unchanged, and today are exactly the
  deterministic tier's own** - the same values as
  `verification.verdicts.deterministic.status`/`.criteria`, literally, not a
  recomputation that could drift. Existing consumers that only read the
  top-level fields keep working unmodified. Once tiers 2/3 exist, the
  top-level fields **must keep coming from the deterministic tier alone** -
  never a blend of tiers - and this document is the place that says so, so a
  later PR does not have to re-derive the rule under deadline.
- **This is a reshape, not a new envelope version.** `verification.grading_tier`
  and `verification.probe_backend` (this PR's own first cut) are removed
  outright rather than kept alongside the new shape: nothing outside this
  build's own tests ever produced or consumed a record carrying them, so there
  is no real consumer a version bump would protect. records.md's own rule for
  an additive version-2 change (`attempt-lifecycle`, added by #8) does not
  apply here for the same reason it did not have to apply there - no v2 bundle
  existed outside the committed controls when either change landed.

Rules that apply once tiers 2/3 exist, recorded now so #69 does not have to
re-derive them:

- **Tier 1 must keep working with no judge at all.** Nothing in `skillc/`
  imports or requires a judge mechanism; tiers 2/3 are additive.
- **An unavailable judge yields `UNKNOWN` for that tier's criteria, and that
  tier's own entry in `verdicts` reflects it. It never silently falls back to
  a lower tier** - the same rule this PR already applies to an unavailable
  execution backend, generalized to judges. An unavailable judge makes only
  ITS OWN tier unavailable; it never removes or degrades another tier's entry.
- **A model-backed judge takes schema-constrained output only** (addendum item
  60): validate every field; a malformed response fails the grade whole, with
  no partial credit. Candidate text reaching a judge is untrusted, and a judge
  with tool access can be steered.
- **A model-backed judge call is a paid call**, so it is subject to the same
  cost-stop discipline as `lifecycle.py`'s real-agent guard (addendum item 51):
  nothing in this build's test suite may make one, by construction.
- Anything sent to an external judge passes the machine-identity leak check
  (#63) first.

Not implemented in this PR: no judge mechanism is called anywhere, and no
`judge` sub-record exists yet. This section is the contract #69 builds
against, not a promise this PR keeps.

## Issue #10 addendum items owned by grading (9-13, 57-61)

The assignment scoped these fourteen items to the grading side (the trial
lifecycle's items are w1's). Not every item fits a single PR; this states
which are satisfied, which are out of scope for what this grader shape even
does, and which are deferred with a reason, rather than leaving the gap
implicit.

| Item | Status | Why |
|---|---|---|
| 9. Parse every result, not the last one | Satisfied by construction, not new work | `grade` operates on exactly one attempt; `_judge` reads exactly one report. There is no "last of several" for a single grading run to get wrong. |
| 10. An observation failure is UNKNOWN, never clean | Already satisfied, verified not introduced | Every `_judge` failure category (timeout/exit-nonzero/no-output/unparseable/criteria-set/contract) routes through `_unknown()`, never a fabricated SATISFIED. |
| 11. Four verdicts (PASS/FAIL/UNKNOWN/BLOCKED), each with a positive control | Partially - vocabulary gap noted, not closed here | skillc's existing five statuses (PASS/FAIL/INCONCLUSIVE/UNAVAILABLE/NOT_RUN, records.md) predate this PR and were not designed against this addendum item. UNAVAILABLE and INCONCLUSIVE together cover UNKNOWN/BLOCKED's intent (an unavailable backend or judge is UNAVAILABLE; a lost probe is INCONCLUSIVE), but there is no status literally named BLOCKED. Widening `records.py`'s closed status vocabulary is a bigger, separate decision than this PR's scope; noted here rather than decided unilaterally. |
| 12. Infra-kill is not a grade; exit 137 is SIGKILL, not OOM | Improved (bare-subprocess path); already correct (backend path) | `_abnormal_exit_reason` now decodes a negative `Popen.returncode` to its exact signal name instead of guessing "candidate code may have killed it". The backend path never had this gap: `ExecuteResult.signal` is explicit by the Protocol's own design (`backend.py`). |
| 13. Never compare a record to itself | Already satisfied, verified not introduced | `grade` snapshots the experiment store and re-derives the ledger BEFORE grading, and compares both AFTER - never a record against its own later self, always two independently taken snapshots. |
| 57. Grade from transcript structure, not text matching | Out of scope for this grader shape | Today's graders (the level-1 slug task) grade candidate CODE, not an agent's transcript/tool-use log. There is no transcript being graded anywhere in `verify.py`; this item applies to a future transcript-shaped grader, not this PR's probe/judge boundary. |
| 58/59. A "found nothing" needs a planted hit; "never exercised" is UNKNOWN | Applied to this PR's own new code, not solved in general | Every new path here (backend unavailable at prepare/install, unconfirmed stop, export failure) has a committed test that plants the exact failure and confirms it is caught (`tests/test_verify_backend.py`), verified BLIND-then-green by hand for the core case. The backend BOUNDARY itself remains unexercised against a fake - stated as owed to the live run throughout this document, never conflated with "proven". |
| 60. An LLM grader takes schema-constrained output only | Stated as a contract, not implemented | See "Grading tiers" above - this is tier 2/3's rule, recorded in this document for #69 to build against. Nothing in this PR calls a judge model. |
| 61. Redaction covers retained copies | Not implemented; stated as a known gap | `containment["stderr"]`/`containment["error"]` (either grading path) are truncated, never redacted - if a probe or candidate printed something sensitive it read from elsewhere, it is not scrubbed before being written into the stored `verified-result`. Left for #69 or a dedicated follow-up; not attempted here without a stated redaction policy to build against. |

## Credit

Ideas distinctive to other projects, cited under ADR 0003's credit rule. No code
was copied.

- **A separate verifier environment** is from [Harbor](https://github.com/harbor-framework/harbor)
  (Apache-2.0; [provenance](../../research/README.md#harbor)). It documents an
  opt-in verifier environment separate from the agent's
  ([separate verifier](https://docs.harborframework.com/core-concepts/tasks/separate-verifier)).
  Here the probe and the judge each get a fresh directory, and the judge starts
  only after the probe's descendants are gone.
- From [Coder Eval](https://github.com/UiPath/coder_eval/tree/d960de1c433a1b050d2509f04d94a60e3cabaaf0)
  (UiPath, `d960de1`, Apache-2.0), per the [lessons note](../../research/coder-eval-lessons.md):
  - **Lesson 2, execute versus grade with later regrade.** Running and grading are
    separate operations, and a stored run can be regraded
    ([`orchestration/regrade.py`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/orchestration/regrade.py)).
    Here: `grade` after capture, `regrade` as a linked new result.
  - **Lesson 4, digest the answer key before grading and check it again**
    ([`orchestrator.py:1396`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/orchestrator.py#L1396),
    [`orchestrator.py:1429`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/orchestrator.py#L1429)).
    Here: the ledger pins `GraderDef.digest()` and grading re-checks it.
  - **Lesson 6, a stored bundle is untrusted input to the verifier**
    ([`orchestration/regrade.py:309-347`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/orchestration/regrade.py#L309-L347),
    [`425-455`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/orchestration/regrade.py#L425-L455)).
    Here: no command is taken from a stored record, only from the pinned grader
    definition, and manifest paths are rechecked before the copy is written.
- **The traps refused here**, from its pinned source:
  - pitfall 1, a container-authored result: the success channel is written only
    by a judge that starts after every candidate process is gone;
  - pitfall 4, warn-and-proceed on a missing digest
    ([`orchestration/regrade.py:485-493`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/orchestration/regrade.py#L485-L493)):
    a missing pin, receipt or artifact digest is refused;
  - pitfall 6, a grader with the subject's powers: the judge never runs candidate
    code, and neither stage inherits the evaluator's environment.

A child subreaper, an exact environment and a directory snapshot are common
engineering practice and need no credit.
