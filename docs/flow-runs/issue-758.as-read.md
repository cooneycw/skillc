<!-- flow-run n=1 id=b2371ebd7ca34f44b5adf5ec9139b0d7 -->
## Run 1 - issue #758 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #758
- Read at:      2026-11-15T14:10:47Z
- updatedAt:    2026-11-15T14:09:23Z   (context only - moves on comments and labels)
- Body digest:  1a2c5123eb5343922e3dadd23374ce6302d382a53e6144075b3633b64b22c4e0   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1895 of 1895 (cap 16384)

### Body as read
## What is wrong

`tests/test_trial_bootstrap.py::test_548_probe_reports_a_cleanup_it_could_not_confirm[sleep-rmfail-exited 1]` (lines 189-194) depends on sub-second wall-clock budgets: `timeout=0.3, settle=0.5`. A fake `docker rm -f` that should exit 1 instead runs past the 0.5 s settle under load. The probe's reason then says "timed out", where the test expects "exited 1".

## Why it is now an issue, not a Nit Store note

It has recurred three times in one day on required CI:

1. **PR pipeline 1444** (PR #744). Recorded at Nit Store #20, comments 6710615941 and 6891288243.
2. **Earlier PR runs**, same signature.
3. **Main push pipeline 1475** after #748 merged (`c7d2500`, 2026-11-15, load1 14.4 on the 32-core kyleci22). That one is the important case: the red main push opened a **`main-merge` barrier (47)**. That lock is shared with Kyle, and while the barrier is open, every merge waits. It only clears after a re-run.

Each occurrence costs a full kyleci pipeline. The barrier case can hold the shared merge lock closed. That blocks work, so it meets the bar for its own issue.

## Fix direction

Make the test independent of wall-clock speed. Drive the fake docker's timing with an injected clock or an explicit event, or widen the budgets to values with a large margin under load (e.g. `timeout=5, settle=10`) and assert on the reason's structure, not its timing. Keep what the test proves: a cleanup that could not be confirmed is reported, for both the `exited 1` and `failed` modes.

## Acceptance

- [ ] The test passes 50/50 under artificial CPU load (e.g. `stress-ng --cpu $(nproc)`) on the host.
- [ ] A negative control: a fake whose cleanup actually succeeds must NOT produce the "could not confirm" reason, so the test can still fail.
- [ ] The two parametrized modes still assert their distinct reasons.

Found while orchestrating wave skillc-work. Refs #548, #20.


<!-- end of body -->
