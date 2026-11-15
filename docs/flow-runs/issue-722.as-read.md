<!-- flow-run n=1 id=13cf05965630406695f29c7ad38b3e60 -->
## Run 1 - issue #722 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #722
- Read at:      2026-11-14T23:20:41Z
- updatedAt:    2026-11-14T20:18:09Z   (context only - moves on comments and labels)
- Body digest:  ca3dea828a35d03a761769051b2db1331e259f02e86f5093f89d4acef0aacf60   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1136 of 1136 (cap 16384)

### Body as read
## What is wrong

`skillc/usage.py` `ensure_ignored()` decides whether `.skillc/usage.jsonl` is ignored by looking for a `*`, `usage.jsonl` or `/usage.jsonl` line in an existing `.skillc/.gitignore`. A later negation defeats that check. With `*\n!usage.jsonl\n`, or with `usage.jsonl` followed by `!usage.jsonl`, the guard passes but Git leaves the log unignored.

## Why it matters

The usage log is documented as local and ignored by default. Routine staging (`git add -A`) could then publish session ids, repository identity and skill history that the owner decided stay local (#718, decision 2).

## Fix

Ask Git for the effective result (`git check-ignore -q .skillc/usage.jsonl`) instead of parsing lines. When the log is not ignored, append a final `/usage.jsonl` rule and check again. Add a test that uses Git itself as the judge, with both negation shapes, and show it failing on the pre-fix code.

Found by the counter-model review (Codex, codex/gpt-6.1-sol, pass 3) of the #719 branch. The pass-2 fix for an existing `.skillc/` with no `.gitignore` already landed in #719; this is the case that fix still misses. Refs #719.


<!-- end of body -->
