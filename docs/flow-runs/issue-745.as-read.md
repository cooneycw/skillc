<!-- flow-run n=1 id=d66562df541646c7b8df1d204e3fe218 -->
## Run 1 - issue #745 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #745
- Read at:      2026-11-15T11:54:57Z
- updatedAt:    2026-11-15T08:25:32Z   (context only - moves on comments and labels)
- Body digest:  6c213c1c686a9491a40480881a03b81ba54e14906da324f1f8b5f05f13e14a36   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2239 of 2239 (cap 16384)

### Body as read
## Why

The counter-model review (Codex `codex/gpt-6.1-sol`, pass 3 of 3, full scope) of the #741 branch `issue-741-skillc-inspect-five-counter-model-pass-3-false-neg` (head `c99773b`, reviewed against base `1cf7bc1`) found these two MEDIUM defects. Pass 3 is the receipt ceiling, and the orchestrator ruled that pass-3 findings are deferred (MEDIUM+ to an issue), so they were not fixed on that branch. Each one lets a real bad flag produce a CLEAN `dangling-reference` verdict. Item 1 is a regression against `1cf7bc1`.

## What

- [ ] **A fully quoted option skips its flag check.** `scripts/helper.sh "--absent=x y"` gives no finding and `flags_examined: 0`. It has exactly the same shell arguments as `scripts/helper.sh --absent="x y"`, which is still checked. Cause: in `skillc/decay.py` (the command-token loop), a word that opens with a quote and holds whitespace is taken as a string and `continue`d before the flag check. Fix: when a script owner is established and the de-quoted word is a recognisable option (`FLAG_RE` on its name), check it against the owner before treating the rest as a string. Regression: `"--absent=x y"` and `'--absent=x y'` both fire, and `"-> see scripts/x.sh"` (a string, not an option) still has its path checked.
- [ ] **Flags inside an `env -S` value are invisible.** `env -S "bash scripts/helper.sh --absent"` checks the helper's path but counts the flag neither as examined nor as unowned, and `--split-string="..."` behaves the same. Fix: tokenise the split-string value as command text, recursively through the same command logic, so its flags are checked against their owner, or else count them in `flags_after_a_non_command_path`. Cover both operand forms. Regression: either a finding on `--absent`, or a count of 1, is asserted.

## Acceptance

- [ ] Each item has a regression on the input above that fails on the #741 head first, and the PR says so.
- [ ] The CPP (`d5ef0a66`, `93ae8540`) and mattpocock (`5863806`) re-runs in `docs/measurements/inspect/2026-11-14-cpp-and-mattpocock.md` are repeated, with every changed count reconciled span by span.

Refs #741.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01CfYAiHBVaApDaofpsJoctH

<!-- end of body -->
