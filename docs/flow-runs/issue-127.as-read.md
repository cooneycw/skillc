# Issue #127 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #127
- Read at:      2026-09-27T11:58:59Z
- updatedAt:    2026-09-27T11:58:52Z   (context only - moves on comments and labels)
- Body digest:  d829ef9babb02fb5b73f94894aabfb7bc00be63d8861c4faa28b84001fa72d5e   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2523 of 2523 (cap 16384)

## Body as read
Found while collecting #11's live-run evidence for #78, #98 and #106 (2026-09-27).

## Defect

`skillc/lifecycle.py` `run_through_backend` (origin/main, around line 468) calls `trial.finalize()` and only then `trial.cleanup_workspace()`. `finalize()` derives the persisted `attempt-lifecycle` record's `cleanup` block from the journal's `cleaned` event (`skillc/trial.py` ~1094-1101). That event does not exist yet, so every attempt run through the backend is persisted as:

```json
"cleanup": {"status": "partial", "failures": ["the workspace was never cleaned up"]}
```

The cleanup then succeeds and is journalled **after** the record is written. `trial.py`'s own contract puts cleanup first; `tests/test_trial.py:273-276` calls `cleanup_workspace()` before `finalize()` and asserts `removed`. The backend path inverts that order, and no test covers the backend path's persisted `cleanup`.

## Observed on the live runs (#126's evidence)

All three retained lifecycle records (`a-b2f835ebf45c` mattpocock-skills PASS, `a-a70dbbc1097f` cpp-codex PASS, `a-d389512e4cf1` missing-credential control) say `partial / never cleaned up`, while each journal says `{"event": "cleaned", "status": "removed", "failures": []}`, and the workspaces are in fact gone. The record contradicts the journal.

## Why it matters

- The persisted record is what a reader (and #11/#106's acceptance) consults for cleanup evidence. As written, it reports a cleanup failure on every real agent run, so it can never evidence a clean one, and a genuine cleanup failure would look identical to a success.
- Related gap: the container's `destroy()`/`confirm_absent()` outcome (`backend_teardown`) is returned in the in-memory dict but not persisted in the lifecycle record or journal, and `collection-run`'s paste-back does not print it. Container absence for these runs had to be established after the fact with a label-filtered `docker ps` (negative-controlled: a planted `skillc.managed=true` container is counted 1, 0 after removal).

## Acceptance

- [ ] `run_through_backend` cleans the workspace before finalizing, so the persisted `cleanup` reflects the real outcome (`removed` on a normal attempt).
- [ ] A regression test through the backend path (fake docker) asserting the persisted lifecycle record's `cleanup` is `removed`, shown to FAIL on the current order.
- [ ] Container teardown confirmation (`backend_teardown`) is persisted with the attempt (journal event and/or lifecycle record) and printed in `collection-run`'s paste-back.

