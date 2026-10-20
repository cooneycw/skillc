<!-- flow-run n=1 id=8751695c86374dbd8e8e0aa60a9bd2a1 -->
## Run 1 - issue #487 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #487
- Read at:      2026-10-20T16:39:27Z
- updatedAt:    2026-10-20T14:42:24Z   (context only - moves on comments and labels)
- Body digest:  39011b91dd637cd886a2a413abbabc8aef2458dd6567c70d44498420b6843751   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1241 of 1241 (cap 16384)

### Body as read
## flow-auto-necessity grader: a verdict after a "Step 3:" lead-in is not recognised ("Flow stopped at Step 3: **No longer needed**.")

**Severity:** affects #434 campaign grading. In the unofficial no-spend replay of the 2026-10-20 campaign's retained observations, 1 of 5 CLEAN attempts read `verdict` VIOLATED, although the agent stated the right verdict. It blocks an accurate re-grade or re-run.

### The shape

The report opens: `Flow stopped at Step 3: **No longer needed**.`

Grader revision 3 (#475) recognises a verdict after a `Verdict:` or `Necessity:` label, or opening a line (with an optional `Issue #N:`). Here the phrase follows a `… Step 3:` lead-in mid-line, so `_stated_verdicts` returns an empty set and `verdict` is VIOLATED with "the report states no ELI5 verdict".

### What a fix needs

- A revision-4 label form that accepts this lead-in. Questions, negations, conditionals and other issues must stay refused (the #475 reds).
- A live-shaped candidate quoting this report, and qualify re-certified.

Source: run `20261020T141529Z-3585c9` (kyle19, private); the attempt's trusted-observation object starts `48958515`.

Found by skillc-worker-A (wave skillc-400) while verifying the #434 campaign.

Refs #434 #475

