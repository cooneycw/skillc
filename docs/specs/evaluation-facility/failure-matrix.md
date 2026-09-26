# Failure-path matrix and trustworthy cleanup (#79)

- Status: Implemented as `skillc/lifecycle.py` (the driver) and `skillc/reap.py`
  (label-scoped reaping and snapshots), #79, sub-issue of #10.
- Date: 2026-09-26
- Governing documents: [interfaces](interfaces.md) (lifecycle steps 1-9),
  [support-matrix.md](support-matrix.md) (#80's backend conformance table -
  a sibling document, not this one: that one proves the Docker backend's OWN
  claims; this one proves the DRIVER's accounting across every way an
  attempt can end)

## What this document is

#10's addendum asked for every one of an attempt's failure paths to end in
an accounted lifecycle record, with the right disposition, and for an
infrastructure kill never to be read as the agent's own FAIL. Most of that
was already true when #79 started - built and tested across #10's earlier
PRs (PR1a/PR1b) - and this document's job is the same one #80's did for
conformance: **state, per path, which test proves it, rather than leaving
"the matrix" as an implicit claim nobody can point to.** Two real gaps were
found and closed while writing this table (teardown failure, below); the
rest cites existing, already-committed coverage.

**Proved here against `FakeBackend`** (`tests/test_lifecycle.py`): runs argv
as a real host subprocess, which proves the DRIVER's own sequencing and
accounting - never a containment boundary. The Docker backend's OWN
behaviors (composed argv, resource limits, labels, the real `docker` CLI
surface) are proved separately, against the fake `docker` CLI, in
`tests/test_docker_backend.py` and `tests/test_docker_conformance.py`
(#80). **The real daemon boundary itself remains owed to the operator's live
run (#10)** for both - a fake proves the logic that runs identically either
way, never the boundary a real daemon would or would not hold.

## The matrix

| # | Failure path | Disposition | Proven by |
|---|---|---|---|
| 1 | Success | `captured` | `test_success_is_captured_and_teardown_confirmed` |
| 2 | Semantic failure (nonzero exit, subject ran fine) | `captured` (grading, not this driver, decides PASS/FAIL) | `test_semantic_failure_still_captures_a_nonzero_exit` |
| 3 | Timeout | `captured`, `stop.reason="timeout"` | `test_a_timeout_is_captured_not_omitted` |
| 4 | Operator cancellation | `captured`, `stop.reason` reflects the cancel | `test_an_operator_cancellation_is_captured_and_reported` |
| 5 | Provider unavailable | `unavailable` | `test_provider_unavailable_before_dispatch_is_unavailable` (at `prepare()`), `test_install_failure_is_unavailable_and_still_tears_down` (at `install()`, after a handle already exists) |
| 6 | Capture failure | `captured` with `capture-failed` journaled; never silently PASSing | `test_export_failure_is_inconclusive_with_its_own_reason`, `test_baseline_export_failure_does_not_crash_the_driver` |
| 7 | Empty task selection (nothing declared to install) | `captured`, readiness reflects zero declared entries | `test_an_empty_surface_still_completes_with_readiness_reflecting_it` |
| 8 | Teardown failure | whatever disposition the SUBJECT earned - teardown failing is never read as the subject's own outcome | `test_teardown_not_confirmed_is_recorded_never_as_clean` (not confirmed, no exception); `test_a_destroy_exception_still_finalizes_the_attempt`, `test_a_confirm_absent_exception_still_finalizes_the_attempt` (**this PR** - see "The teardown-failure gap" below) |
| 9 | Launch failure | `unavailable` | `test_launch_failed_is_unavailable` |
| 10 | Kill by signal | `captured`, `stop.signal` names the exact signal, never guessed from a bare exit code (addendum item 12: exit 137 is SIGKILL, not OOM) | `test_a_signal_kill_records_the_signal_name_not_a_guess` |

Row 2 is the one place "infrastructure kill is never the agent's FAIL"
matters most: this driver's own disposition is `captured` regardless of the
exit code, and the exit code / signal are recorded as OBSERVATIONS, not
verdicts - `verify.py`'s grading is the only thing that ever turns "how did
it stop" into PASS/FAIL, and it does so from the criteria, never from a
process exit code directly (`records.derive_status`).

## The teardown-failure gap (found writing this table)

Before this PR, `run_through_backend`'s `finally` block called
`backend.destroy(handle)` then `backend.confirm_absent(handle)` with nothing
catching either. A backend whose `destroy()` or `confirm_absent()` itself
RAISED (as opposed to returning `Confirmation.NOT_CONFIRMED`/`UNKNOWN`, both
already handled) propagated that exception straight out of the function -
`trial.finalize()` and `trial.cleanup_workspace()` never ran, and the attempt
was left with **no lifecycle record at all**, whatever the subject itself
had done.

Fixed: both calls are now individually wrapped, a raise from either folds
into `backend_teardown="unknown"` (never a guessed `"confirmed"`) plus a new
`backend_teardown_error` string field, and `trial.finalize()` still runs
unconditionally. Confirmed to reproduce (both new tests failed with the
raw exception, not an assertion, before the fix) and confirmed fixed
afterward; see `skillc/lifecycle.py`'s own docstring for the reasoning.

A resource this leaves behind on the real daemon is exactly what
`skillc/reap.py`'s label-scoped sweep (below) exists to find later - this
driver's own per-attempt teardown and that independent sweep are two layers,
never one substituting for the other.

## Label-scoped reaping (`skillc/reap.py`)

Reaping is by label ONLY, never by name - `docker ps --filter
label=skillc.managed=true --filter label=skillc.attempt-id=<id>` selects the
candidates, so a foreign container that merely looks like one of ours can
never appear in that list; it is not merely unlikely to be touched, it is
structurally unreachable to `reap()`.

**UNKNOWN never reaps.** If the daemon cannot even be asked (`docker ps`
itself fails), nothing is removed and every requested attempt id is reported
`left-running` - never `already-absent`, which is a different, positive fact.

**Register-before-fail is already true, by construction, not something this
module adds.** `compose_run_argv` (#77) writes both labels onto a container
at `docker run` time - the very first step of an attempt's lifecycle, before
anything that can fail. There is no separate "intend to clean this up"
bookkeeping for a crash to lose, because the label IS that bookkeeping and it
already exists on the daemon by the time `reap()` ever runs. `reap()` is
idempotent for the same reason: asking the daemon "does anything with this
label still exist" is idempotent, and removing something already gone is
success (`already-absent`), never an error.

**Acts and confirms by container ID, never by name** (cross-model review of
this PR, HIGH). `reap()` lists, removes, and re-lists - three separate round
trips to a daemon nothing prevents from changing between them. A NAME can be
taken by a brand-new, different container the instant the original is
removed; an ID cannot, because it is unique to one container's lifetime and
is never reused. `reap()` therefore lists container IDs, issues `docker rm
-f <id>`, and confirms by checking that those SPECIFIC ids are gone - not
merely that the label filter now returns nothing, which a fresh container
that picked up the same attempt id's label in the interim would satisfy
without ever having been touched
(`test_reap_removes_by_container_id_never_by_name` asserts the actual `rm`
argv targets an id, not the declared name).

**Refuses an empty attempt population** (cross-model review, MEDIUM):
`reap(docker_bin, [])` used to report `daemon_reachable=True` having checked
nothing at all - an unexamined population is not the same fact as a
checked-and-clean one. `reap()` now raises `ValueError`
(`test_reap_refuses_an_empty_attempt_population`).

**Committed controls** (`tests/test_reap.py`):

| Control (#79's own wording) | Test |
|---|---|
| A container left running on purpose is detected, and reaping removes it | `test_a_container_left_running_on_purpose_is_detected_and_reaped` |
| A foreign container carrying a similar name but not our label is never touched | `test_a_foreign_lookalike_is_never_touched` |
| A deliberately modified declared host path is reported | `test_a_deliberately_modified_declared_host_path_is_reported` |

Supporting cases: idempotence (`test_an_already_absent_attempt_is_idempotent_not_an_error`),
UNKNOWN-never-reaps against an unreachable daemon
(`test_unknown_never_reaps_when_the_daemon_is_unreachable`), a `rm -f` that
lies about success the same way `DockerBackend.confirm_absent` already
distrusts it (`test_a_container_that_cannot_be_confirmed_removed_is_left_running`),
and the id-vs-name race
(`test_reap_removes_by_container_id_never_by_name`).

## Resource snapshots, both directions

`reap.snapshot()`/`reap.diff()` partition every container the daemon reports
into `owned` (carries the fixed ownership label) and `foreign` (everything
else), then compare a before/after pair in BOTH directions:

- **`leaked`**: an owned container present after that was not present before
  - something skillc left running. (`test_diff_flags_a_leak_in_one_direction`)
- **`foreign_vanished`**: a foreign container present before that is gone
  after - evidence a sweep reached outside its own label scope. A correctly
  label-scoped `reap()` cannot cause this, but the comparison does not
  assume that; it checks anyway. (`test_diff_flags_a_foreign_disappearance_in_the_other_direction`)

A diff computed across an unreachable snapshot is `comparable=False`, with
both sets empty by construction - **never** silently read as "no change"
(`test_diff_is_not_comparable_across_an_unreachable_snapshot`). Absence of
evidence is not evidence of absence.

**Attribution is not causation, and this document says so rather than
implying otherwise** (cross-model review, MEDIUM). `leaked`/`foreign_vanished`
answer "did something change on the daemon between these two reads", never
"did THIS run cause it": a concurrent second skillc run sharing the same
daemon can legitimately add its own container during this window (reported
as `leaked` though nothing here leaked anything) or remove its own
foreign-to-this-run container (reported as `foreign_vanished` though nothing
here reached outside its scope). Neither is a false reading of the daemon's
state - only a false claim about who caused it. Keep the snapshot window
narrow (around one attempt's own execution, on a daemon nothing else is
using concurrently) to keep that gap small; establishing causation under
real concurrency needs an isolated test daemon or a controlled execution
window, which is a separate piece of work from this comparison.

Similarly, **identity here is by container NAME, not ID** (cross-model
review, MEDIUM) - unlike `reap()` above, which acts on what it finds and
therefore needs ID identity to be safe. A container removed and replaced by
a different one under the identical name, entirely between two snapshots, is
indistinguishable from one that was never touched. For a coarse leak/scope
detector run around one attempt's own narrow window this gap is small; it
would not be if this comparison were reused as a security boundary.

## Declared host paths unchanged

`reap.snapshot_host_paths()`/`reap.diff_host_paths()` content-digest a
DECLARED set of host paths - outside the trial root, never the workspace
itself - before and after, and report any path whose digest differs,
including one that appeared or disappeared.

**Three states, not two** (cross-model review, MEDIUM - the pre-fix code
collapsed all three into one). A declared path's snapshot value is a real
sha256 digest, `None` (confirmed absent, or not a regular file), or
`UNREADABLE` (exists as a regular file but could not be read - permission
denied, and similar). `diff_host_paths` reports a path as `unresolved`,
never silently `unchanged`, when either side was `UNREADABLE`
(`test_an_unreadable_declared_path_is_unresolved_not_unchanged`) - two
identical `UNREADABLE` sentinels are not evidence the content matched, only
evidence this instrument could not check. A key present in only one
snapshot's declarations (added or removed between calls) is compared against
a distinct not-declared sentinel, never against `.get()`'s default of
`None` - which used to make it collide with the legitimate "confirmed
absent" value and vanish from the diff entirely
(`test_a_declaration_added_between_snapshots_is_reported_not_ignored`). Both
`snapshot_host_paths()` and `reap()` above refuse an empty population
outright (`ValueError`) rather than let `changed=()` read as "checked and
confirmed unchanged" (`test_snapshot_host_paths_refuses_an_empty_declaration`).

**What this cannot see, stated rather than silently assumed away**: a
declared path is hashed as a REGULAR FILE only - a directory, device or
symlink reads as absent, never walked or followed; a symlink retargeted to a
file with an IDENTICAL digest is indistinguishable from an untouched one;
permission, ownership and timestamp changes that leave the bytes unchanged
are invisible by design (this checks content, not metadata); and nothing
outside the declared list is examined at all - proving the paths you named
are unchanged is not the same claim as proving nothing on the host changed
(`test_an_unrelated_undeclared_host_path_is_never_examined` states this
limitation as a passing test, not just as prose).

## Cross-model review

`/codex:code_review` against `origin/main` found one HIGH (the id-vs-name
reaping race) and five MEDIUM findings (snapshot identity, attribution, the
empty-population gap in both `reap()` and `snapshot_host_paths()`, and the
host-path three-state collapse), all fixed above with committed regression
tests confirmed red on the pre-fix code before the fix, per this repo's
negative-control discipline.
