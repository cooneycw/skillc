# Issue #129 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #129
- Read at:      2026-09-27T13:09:12Z
- updatedAt:    2026-09-27T13:09:02Z   (context only - moves on comments and labels)
- Body digest:  63a3675fdfbeacaa305e069f81b683e33dd38b86fff822ba609e97a106d27ce3   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2680 of 2680 (cap 16384)

## Body as read
Found while merging PR #128 (#127). This blocks merges: skillc's required CI check hangs intermittently.

## Symptom

PR #128's pipelines 258 and the restart 259 both stalled in the `gate` step for 35+ and 10+ minutes. Both times the output stopped right after `tests/test_judge.py` completed, so the stall is inside `tests/test_judge_mcp_second_opinion.py`. Pipeline 257 ran the same code minus a CHANGELOG line and passed the gate in 3m27s. The required check stays PENDING indefinitely, so `gh-pr-merge.sh` refuses to merge (correctly).

## Defect

`skillc/judge_mcp_second_opinion.py` `_write` (~line 238-258) polls `select.select([], [stdin], [], remaining)` and then calls `os.write(stdin.fileno(), payload[sent:sent + _CHUNK_SIZE])` with `_CHUNK_SIZE = 65536` on a **blocking** fd. On Linux, a pipe reports writable when *any* space is free (one page), not when a whole chunk fits. A blocking `os.write` of 64 KiB into a pipe with less free space than that waits until all of it is written. If the child has stopped reading, which is precisely the case `test_a_stalled_reader_is_a_write_timeout` exercises, it never returns, and the deadline is never checked again.

## Reproduction of the mechanism (no skillc code)

```python
import os, select, fcntl
r, w = os.pipe()
fl = fcntl.fcntl(w, fcntl.F_GETFL); fcntl.fcntl(w, fcntl.F_SETFL, fl | os.O_NONBLOCK)
try:
    while True: os.write(w, b"x" * 4096)
except BlockingIOError: pass
os.read(r, 4096)                          # one page free, then the reader stalls
fcntl.fcntl(w, fcntl.F_SETFL, fl)         # blocking, as subprocess gives it
print(select.select([], [w], [], 1)[1])   # -> [w]  "writable"
os.write(w, b"y" * 65536)                 # hangs forever
```

Measured on the dev host: `select says writable: True`, then the write hung until `timeout 10` killed it (exit 124). Whether the test hits it depends on how full the pipe is after the handshake, which explains 40/40 local passes and the CI stalls.

## Why it matters

- CI: the required check hangs at random and blocks every PR's merge.
- Product: a real `mcp-second-opinion` judge that stops reading can wedge a grading run past its `call_timeout`. That is exactly the failure the deadline was written to bound.

## Acceptance

- [ ] `_write` cannot block past its deadline: set the fd `O_NONBLOCK` for the write loop (treat `BlockingIOError` as "wait again on select"), or write at most `select.PIPE_BUF` per ready event.
- [ ] A deterministic regression test that pre-fills the child's stdin pipe to leave less than one chunk free and asserts `JudgeUnavailable` within the deadline, shown to HANG or FAIL (under a bounded timeout) on the current code.

