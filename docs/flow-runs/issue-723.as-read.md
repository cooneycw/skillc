<!-- flow-run n=1 id=aac930e20d174c3aacc43a3c519f5d71 -->
## Run 1 - issue #723 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #723
- Read at:      2026-11-14T23:54:11Z
- updatedAt:    2026-11-14T20:18:10Z   (context only - moves on comments and labels)
- Body digest:  4c2fc9ce07ca21dbc41accc1c24f50c275f26e93278475f29fe84e8d73f925f5   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1275 of 1275 (cap 16384)

### Body as read
## What is wrong

For the `skill-usage-fields`, `skill-usage-privacy` and `skill-usage-pairing` rules, `skillc selftest` counts any non-empty log that parses as an exercised known-good subject. Those rules only read lines the envelope accepts (`usage._readable`). So a good control whose every line has an unreadable envelope (for example `version: 2`) exercises nothing, yet the rule is still certified. A rule that refused every readable record would then pass selftest.

## Why it matters

This is the empty-population defect that #719's pass-1 fix closed for zero-byte controls, one level deeper. The positive half of "this rule discriminates" goes unproven, and selftest is the instrument every `check-records` green depends on.

## Fix

In `skillc/cli.py` `_population`, treat a usage log with zero envelope-readable entries as not exercised for every semantic usage rule, so a good side reads UNPARSED and a bad side BLIND. The envelope rule keeps its own population. Add a sabotage test that rewrites each semantic rule's good controls to `version: 2` and requires selftest to fail, and show the test failing on the pre-fix code.

Found by the counter-model review (Codex, codex/gpt-6.1-sol, pass 3) of the #719 branch. Deferred under the owner's ruling. Refs #719.


<!-- end of body -->
