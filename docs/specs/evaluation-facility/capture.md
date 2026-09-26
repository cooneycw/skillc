# Controller accounting and capture

- Status: Implemented as `skillc/trial.py`, #8. API only; no CLI subcommand yet.
  #10 drives it end to end in the Docker lane.
- Date: 2026-09-26
- Governing documents: [interfaces](interfaces.md), [protocol](protocol.md), [records](records.md)
- Decision: [ADR 0003](../../decisions/0003-no-external-evaluation-runtime.md) - skillc owns its runner

## What it does

interfaces.md gives the controller two contracts: the trial ledger, and the
artifact and observation bundle. This module is the controller side of both,
covering lifecycle steps 1-2 and 5-7 and step 9's cleanup. It is backend-neutral:
a subject is an argv and a working directory. No core branch names a client,
collection or container runtime.

```
plan ---------> ledger.json (once, before dispatch) + config objects
  |
allocate_workspace --> owned disposable directory (never inside the store)
run_attempt ---------> journal: dispatched, started, stopped, stop-confirmed
capture -------------> objects/<sha256> + manifest-<attempt>.json   (only after a confirmed stop)
cleanup_workspace ---> journal: cleaned (safe to repeat; refuses what it does not own)
finalize / close ----> lifecycle-<attempt>.json for EVERY planned attempt
retry ---------------> ledger revision that only appends a linked attempt
frozen_artifacts ----> re-hashed bytes: the gate before any grading (#9)
add_receipt / add_result --> records from other producers, never overwritten
```

The experiment directory is a **bundle** in records.md's sense. `skillc check-records`
reads it directly. Objects, the journal, the spool and the ledger history carry no
`.json` suffix, so a captured `task.json` is never mistaken for a record.

## Identities and the plan

The plan names trials and how many attempts each gets. The **controller** issues
every identifier: the experiment gets a label plus a random suffix, and each
attempt gets a random `a-<12 hex>` ID. No caller or subject chooses an ID that a
later record will cite. The subject is never told its attempt ID, so nothing it
writes can claim an attempt by knowing it.

Unknown fields are refused at every level of the plan, and so are loose types:
`"attempts": true` is an integer to Python and would quietly plan one attempt.
Each trial's resolved configuration is stored as a canonical-JSON object, and the
ledger binds its digest.

The ledger is written once, before dispatch. A retry is the only change allowed
afterwards, and it can only **append** a linked attempt. Every revision is kept as
an object and listed in `ledger-history.jsonl`. `Experiment.open` refuses:

- a ledger that differs from its last recorded revision;
- a revision that changed anything already planned, even when that revision was
  recorded like an honest one;
- a configuration object that no longer hashes to its digest.

## Lifecycle and the `attempt-lifecycle` record

`run_attempt` starts the subject in its own process group, spooling stdout and
stderr into controller storage. On the deadline, or when `cancel()` returns
true, it stops the whole group: SIGTERM, then SIGKILL. After a normal exit it also
stops any member the leader left behind, because a leader that exits while its
child keeps writing has not stopped. The stop is **confirmed** only once no
member of the group remains.

`finalize` derives each attempt's disposition from its journal. It never takes a
flag the subject could set:

| Journal shows | Disposition | Stop reason |
|---|---|---|
| never dispatched | `not-run`, with a reason | `never-started` |
| the subject could not be launched | `unavailable` | `launch-failed` |
| no confirmed stop | `inconclusive` | as observed, or `unobserved` |
| confirmed stop, capture failed or never happened | `inconclusive` | as observed |
| confirmed stop, captured | `captured` | `exited`, `timeout`, `operator-cancelled` |

A caller may downgrade an uncaptured attempt to `unavailable` or `inconclusive`,
with a reason: for example, a provider found unreachable. It may never declare
`captured`, and never downgrade an attempt whose bytes were captured, since that
capture may already have been graded. `close` finalizes every attempt not yet
accounted for, which is what makes "never silently drop an attempt" true.
`account` reports the population and per-disposition counts, and lists an
unfinalized attempt as `open` rather than omitting it.

A timeout is a **captured** failed completion, not an omitted attempt
(protocol.md section 3). Its grade decides the outcome.

## What capture exports

Capture is refused until the stop is confirmed, and each attempt is captured only
once. The output root is walked with `lstat` and never followed through a link.
Each file is opened with `O_NOFOLLOW`, copied into a content-addressed object,
and listed with path, type, size, digest and executable bit.

| Not exported | Recorded as |
|---|---|
| a symlink (file or directory), wherever it points | exclusion: never followed |
| a non-regular file (FIFO, device, socket) | exclusion |
| a directory in `SECRET_DIRS` (`.git`, `.ssh`, `.aws`, `.codex`, ...) - not entered | exclusion |
| a name in `SECRET_NAMES` (`.env*`, `*.pem`, `id_rsa*`, `auth.json`, ...) | exclusion |
| content matching `SECRET_CONTENT` (private key, AWS, GitHub, API, Slack tokens) | exclusion naming the pattern, never the value |
| a file outside the declared `include` scope | not listed |
| a file over the per-file bound, or over the file-count or total bound | capture failure; coverage partial |

A bound is never met by truncating. An empty capture is refused, and the attempt
becomes `inconclusive`: records.md already refuses an empty manifest.

Traversal is structural: the walk yields directory entries, so there is no path
string to smuggle `..` into. Links are what could lead outside, and links are
never followed.

## Observations and imported records

Each manifest observation carries the attempt ID, its origin, its coverage, and a
`ref` plus `digest` for its raw bytes:

- `client-events` and `client-stderr`: the spooled streams, origin
  `client-reported`. A stream over its bound is truncated **and** marked `partial`,
  with a capture failure.
- `process-lifecycle`: the controller's journal, origin `observed`. It is
  `partial` when the stop was not confirmed.
- imported records (`Import`): a record a client or collector produced, offered
  with the digest its transport reported.

An import is **refused**, and listed in `capture_failures`, never silently dropped
and never trusted, when:

- it has no transport digest;
- its bytes do not match that digest;
- its payload, top level or any JSONL line, claims a **different** attempt ID. That
  is a stale record from another run.

An accepted import is still only an observation with the origin it was declared
with. A `"status": "PASS"` inside it is something the client said.

**Nothing the subject wrote is authority.** A `task.json` claiming PASS, a config
echoed back, a sentinel line on stdout: each is captured as bytes and none
becomes a result or a provenance claim. `tests/test_trial.py` drives a hostile
fake subject through all three, and then shows the attempt is still owed a grade.

## From capture to a verified result

`frozen_artifacts` is the gate before grading. It re-hashes every object,
re-checks its size, and requires the manifest to name this attempt under the
trial the ledger planned. `add_result` calls it first. So a modified artifact, a
digest nobody captured, or a mismatched manifest cannot become a verified result.

Graded results are only accepted for a finalized `captured` attempt. Results and
receipts are written once. A regrade must name a result already stored, which is
retained. The result itself is #9's to produce.

## Storage, access and retention (review.md Q5)

This is the policy, chosen before any real private or model evidence exists.

- **Location.** An explicit local directory the operator names, opened with
  `open_store`. It is refused:
  - inside a host client home (`~/.codex`, `~/.claude`, `~/.agents`,
    `$CODEX_HOME`), always, or inside the subject's source, which the caller
    passes as a forbidden root;
  - inside any **git work tree**, because evidence inside a work tree is one
    `git add` from being published;
  - in a non-empty directory that is not already a store.
- **Separation.** A workspace is never allocated inside the store. The subject
  works one level below its ownership marker, so the marker is not among its
  outputs.
- **Access.** Directories are `0700`, and records and objects `0400`. Evidence is
  never published or uploaded automatically.
- **Content.** Records carry identities and digests, never credential values.
  Configuration is stored as the resolved object the caller supplied, so callers
  resolve configuration **without secrets** before planning. Secret-looking
  outputs are excluded at export, as above.
- **Retention.** Everything is kept until an operator deletes it. There is no
  automatic expiry. Retries and regrades add records, and originals are never
  overwritten. Deleting an experiment is a manual operator act on the whole
  directory, never a per-record edit.
- **Committed evidence.** Deterministic-fixture evidence may be committed
  deliberately, as `evals/subjects/*/evidence` is today. Real private or model
  evidence is not committed without a separate decision.

## Limits

- **The controller host is trusted** (interfaces.md). The digests detect subject
  or accidental change, not an operator who rewrites the store and its history
  together. `0400` does not stop root.
- **A confirmed stop covers the process group.** A process that calls `setsid`
  leaves the group and is not seen: `test_a_process_that_leaves_the_group_is_NOT_seen`
  pins this. Containment is the Docker lane's job (#10).
- **The secret filter is a list, not a census.** A credential in an unlisted name
  and an unrecognized shape is exported. The patterns reduce accidents. They do not
  certify that the output is clean.
- **POSIX only**: process groups and `O_NOFOLLOW`.
- **Budgets are recorded, not enforced.** A trial's `budget` is stored in the
  ledger. Only the wall-clock `timeout` passed to `run_attempt` is enforced.
- **Readiness does not gate dispatch.** The receipt is stored as #7 produced it.
  Whether a failed canary prevents a PASS is still #9's judgement (records.md).

## Credit

Ideas distinctive to [Coder Eval](https://github.com/UiPath/coder_eval/tree/d960de1c433a1b050d2509f04d94a60e3cabaaf0)
(UiPath, `d960de1`, Apache-2.0), per ADR 0003 and the
[lessons note](../../research/coder-eval-lessons.md). No code was copied.

- **A missing result is a record, not a gap** (lesson 7). Coder Eval writes a
  synthetic record when the container returns no `task.json`
  ([`isolation/docker_runner.py:967`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/isolation/docker_runner.py#L967)).
  Here every planned attempt gets an `attempt-lifecycle` record, whatever happened.
- **The traps refused here**, from its pinned source:
  - pitfall 1, a container-authored result on a writable mount
    ([`isolation/docker_runner.py:1303-1306`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/isolation/docker_runner.py#L1303-L1306));
  - pitfall 2, an echoed contract read as proof
    ([`isolation/docker_runner.py:878-913`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/isolation/docker_runner.py#L878-L913));
  - pitfall 3, stdout framing read as authentication
    ([`streaming/wire.py:39`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/streaming/wire.py#L39));
  - pitfall 4, a missing digest that warns and proceeds
    ([`orchestration/regrade.py:485-493`](https://github.com/UiPath/coder_eval/blob/d960de1c433a1b050d2509f04d94a60e3cabaaf0/src/coder_eval/orchestration/regrade.py#L485-L493)).

Refusing unknown fields and writing atomically with `O_EXCL | O_NOFOLLOW` are
common engineering practice (lessons 1 and 5) and need no credit under the owner's
rule.
