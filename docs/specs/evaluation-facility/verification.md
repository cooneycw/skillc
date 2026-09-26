# Independent grading and result assembly

- Status: Implemented as `skillc/verify.py`, #9. API only; no CLI subcommand yet.
  #10 drives it end to end in the Docker lane.
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
separator, or a file that is a link, is refused. `GraderDef.digest()` covers
every field and the bytes of all three files.

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

The probe's report and stderr are opened non-blocking and without following a
link, and read only if they are regular files, within a bound. A FIFO swapped in
for the report would otherwise block the verifier forever, after every deadline
had passed.

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
| Candidate kills the supervisor | -> INCONCLUSIVE, `containment` | - |
| ... and stays alive | -> killed by the fallback sweep; the verifier quarantines and refuses the next run until cleared | after `clear_quarantine`, the reference PASSes |
| Evaluator credentials, inheritance | a secret in the verifier's environment is absent from the candidate's `os.environ` | the dump holds `PATH` (it ran) |
| Evaluator credentials, confidentiality | **a limit, pinned**: candidate code reads the token from an ancestor's `/proc/<pid>/environ` | - |
| Stale receipt, missing digest | no receipt, a planted stale receipt, no pin, a wrong pin, a modified object -> refused | - |
| Readiness | canary VIOLATED + correct -> INCONCLUSIVE; + wrong -> FAIL | - |
| Status derived | a judge claiming `status: PASS` beside violated criteria -> FAIL | - |
| Always-pass/always-fail/crash/no-output graders | crash, no-output, omits-criterion -> stored INCONCLUSIVE with their category; always-pass and always-fail are refused by `qualify.py` through this path | - |
| Deterministic regrading lineage | a regrade with another judge -> refused (pin) | regrade -> same criteria, linked, original retained |

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
- a blocking read of the report (the verifier hung on the FIFO).

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
  `test_an_ancestors_environment_is_NOT_hidden` pins that. Keeping credentials
  away from candidate code needs a separate user: the Docker lane (#10). Until
  then, run grading from a process tree that holds no credential. Only
  non-inheritance is established here.
- **Candidate code runs as the evaluator's own user.**
  - A write to the evidence store, the ledger or the grader's files is therefore
    **detected** (snapshot and digest), not **prevented**.
  - The answer key is not in the probe's directory, argv, stdin or environment,
    but its file on disk is readable by a candidate that searches for it.
  - Prevention needs a separate user or a container: the Docker lane (#10).
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
