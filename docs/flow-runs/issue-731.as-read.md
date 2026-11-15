<!-- flow-run n=1 id=ad311c8b07584f5bb4e0226eaaa52ed4 -->
## Run 1 - issue #731 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #731
- Read at:      2026-11-14T23:20:46Z
- updatedAt:    2026-11-14T21:26:45Z   (context only - moves on comments and labels)
- Body digest:  f9c7751054404d4efa15419a24ea8d0174cbbcb115b2712e38f4660e4aa1e1ee   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3067 of 3067 (cap 16384)

### Body as read
## Why

The counter-model review (Codex, `codex/gpt-6.1-sol`, pass 3 of 3) of the #725 branch `issue-725-skill-gauntlet-round-2-decay-rules-and-skillc-insp` found these four MEDIUM defects. Pass 3 is the review ceiling, and fixes made after it would be commits no reviewer has read. So, following the owner's ruling on #719, they were deferred rather than fixed in that PR. Each one is a precise false verdict in `skillc inspect`. None of them can write anywhere: the one writing hazard (`--out`) was fixed in pass 2 and reviewed in pass 3.

## What

- [ ] **A known-bad input is credited as an enforcer.** `skillc/inspect.py` `_red_case` accepts any existing path under `controls/<id>/` when that control has a populated `bad/`. So `You MUST reject \`controls/dangling-reference/bad/dead-link/skills/demo/SKILL.md\`` sorts into A, with that bad input named as the enforcer. Fix: a reference into `bad/` or `good/` is an input, not an enforcer, so it stays UNSORTED unless a real enforcer is named. Regression: that exact line sorts into UNSORTED.
- [ ] **A single-token `$(...)` leaves the outer command suspended.** In `skillc/decay.py` `dangling_reference`, when `$(` and `)` occur in one token (`"$(pwd)"`), the close is subtracted but the outer command is never restored. `scripts/helper.sh --verbose "$(pwd)" --absent` produces no finding. Fix: restore the outer command when a substitution opens and closes in the same token. Regression: that line fires on `--absent`.
- [ ] **A file argument takes ownership of later flags.** Every resolved file becomes the active `script`. `scripts/helper.sh references/guide.md --verbose` reports that the *guide* does not support `--verbose`, which is a false hard error and makes `inspect` STOP. Fix: track the command (the first word) separately from file arguments, which are checked for existence only. Regression: using `controls/dangling-reference/good/present`, that line is silent.
- [ ] **The 8-candidate bound in `copied-passage` can miss the maximal alignment.** With A = 60 x `same` followed by 50 distinct words, and B = 100 x `same` followed by the same 50 words, the longest run is 110 words. The rule reports 60 words and 2 runs, and the result depends on document order (shared words 110 vs 150). Fix: find maximal matches without truncating alignments, for example by trying the candidate whose alignment continues past the repeated prefix, or by extending candidates by suffix. Otherwise, label the measurement as a bounded estimate in the report. The memory bound from pass 2 (`test_repetitive_text_stays_bounded`) must still hold. Regression: the repetitive-prefix case gives 110, in either order.

## Acceptance

- [ ] Each item has a regression test that fails on the current code. Run it there first and say so in the PR.
- [ ] `skillc selftest` still reports every rule discriminating. The CPP and mattpocock runs in `docs/measurements/inspect/2026-11-14-cpp-and-mattpocock.md` re-run with any count change explained.

Refs #725.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

<!-- end of body -->
