<!-- flow-run n=1 id=a69e83d53ad742ce8d485ccb8002981b -->
## Run 1 - issue #317 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #317
- Read at:      2026-10-17T16:32:14Z
- updatedAt:    2026-10-06T12:38:33Z   (context only - moves on comments and labels)
- Body digest:  8b13e5cdb8f08598d67269e9681aaff63e6295a5574e196d767d136840297872   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4585 of 4585 (cap 16384)

### Body as read
## Background

#304 added an entry guard to `DockerBackend.execute()`: a second call against a handle whose container is CONFIRMED not running (via `_inspect()`) is refused with `reason="attempt-not-running"` instead of falling through to a real `docker exec` the daemon rejects (which used to read as a fabricated ordinary `reason="exited", exit_code=1`).

That guard is itself a check-then-act: the container can stop in the gap between the entry `_inspect()` and the real `docker exec` a few lines later. When that race happens, the daemon's own rejection lands as the identical "exited"/nonzero shape a legitimate subject exit produces - the same defect class #304 fixed, in a narrower window.

## Why it isn't closed yet

A first attempt at closing it reclassified the result after the fact: if the exec came back nonzero and the captured stderr contained the daemon's own "is not running" / "no such container" text, AND a second independent re-inspect confirmed the container was no longer running, the result was reclassified to `attempt-not-running`.

`codex:code_review` found this is unsafe: the stderr text is read from the SUBJECT's own output, not a trusted channel. A subject whose legitimate stderr happens to contain either phrase before exiting nonzero for its own reasons would have its real execution result silently discarded as `attempt-not-running` - a worse fabrication than the one #304 fixed (a false "nothing ran" instead of a false "something ran"). That reclassification was removed rather than shipped with a known spoofing path; the window is now documented as an open boundary in `execute()`'s docstring and the CHANGELOG, with a test (`test_execute_does_not_close_the_toctou_window_between_its_entry_check_and_the_real_exec`) proving the race still produces the daemon's unmodified rejection today.

## Candidate approach

`exec_in_attempt()` (#269) already solves an analogous provenance problem for confirming a kill: it wraps the argv as `sh -c 'echo $$ > MARKER; exec "$@"' sh <argv...>`, so a per-call marker file records the in-container PID the instant the wrapped shell actually starts - a signal the daemon's own exec-rejection path can never produce, because a rejected exec never starts a shell inside the container at all.

The same mechanism could close this window: if `execute()` wrapped its argv the same way and could confirm (via `docker cp` reading the marker back, which works against a stopped container's filesystem layer without needing it to be running) whether the wrapper shell ever started, a nonzero "exited" result with NO marker present would be a trustworthy, subject-independent signal that the daemon rejected the exec outright - safe to reclassify. A marker that IS present means the subject's own process genuinely ran, so its result (including stderr) must be reported as-is, whatever it says.

This is a bigger change than #304's scope (a new wrap/marker-read mechanism on `execute()`'s otherwise-unwrapped path, with its own tests and mutation checks) and needs its own review before building.

## Related cleanup

While building #304, found that `exec_in_attempt()`'s own entry guard (unlike `execute()`'s corrected one) still folds "daemon unreachable" (`_inspect()` returned `reachable=False`) together with "confirmed not running" into the same `attempt-not-running` reason. This is harmless today only because `gate_witness.py`'s `_NOT_STARTED_REASONS` treats `attempt-not-running` and `launch-failed` identically downstream - no current caller can tell the difference. Worth revisiting alongside this issue, since a future caller of `exec_in_attempt()` that needs to distinguish the two would inherit the same silent guess `execute()` almost shipped. See the Nit Store comment: cooneycw/skillc#20 (comment https://github.com/cooneycw/skillc/issues/20#issuecomment-6015636415).

## Acceptance

- [ ] A reviewed design for the provenance signal (marker-based or otherwise), including what `execute()`'s existing callers (`lifecycle.py`, `disruption_trigger.py`, `authority_interceptor.py`, `decide_reply_channel.py`, `verify.py`) need to stay unaffected by the wrap.
- [ ] A red case: the race from #304's own test (container stopped between entry check and real exec) must reclassify to `attempt-not-running` without any subject-controlled signal in the decision.
- [ ] A negative control: a subject whose legitimate stderr contains the daemon's own rejection wording, but which genuinely ran (marker present), must keep its real `reason="exited"` result unmodified.
- [ ] Mutation-checked.

Refs #304, #269.
