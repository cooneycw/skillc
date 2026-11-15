<!-- flow-run n=1 id=0e25040917c04ad9a2b9707289246259 -->
## Run 1 - issue #741 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #741
- Read at:      2026-11-15T07:34:57Z
- updatedAt:    2026-11-14T23:53:10Z   (context only - moves on comments and labels)
- Body digest:  d95ba646a3bb1307e5a405131abf241e8905f75ffff68337b1ef244698ed9890   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3452 of 3452 (cap 16384)

### Body as read
## Why

The counter-model review (Codex `codex/gpt-6.1-sol`, pass 3 of 3, full scope) of the #731 branch `issue-731-skillc-inspect-four-counter-model-pass-3-defects-e` (head `d0202b2`, reviewed against #733's head `a092ac2`) found these five MEDIUM defects. Pass 3 is the receipt ceiling, and the orchestrator ruled that pass-3 findings are deferred by severity, so they were not fixed in that PR.

**Each one is a false negative that `a092ac2` does NOT have.** The #731 branch fixes the four defects #731 filed, plus seven review findings, and introduces these five narrower misses. Three of them come from the shlex tokeniser that #731 adopted as a design change. A miss here can turn a dangling reference into a CLEAN report.

## What

- [ ] **Quoted separators lose their quote context.** In `skillc/decay.py` (the command-token loop), POSIX shlex returns `;` for both `";"` and an unquoted `;`. So `scripts/helper.sh ";" --absent` resets the command owner and `--absent` is never examined. Fix: keep whether punctuation was quoted (e.g. a `shlex` pass with `posix=False` to see the quotes, or a custom token stream), and reset only on real operators. Regression: that line fires on `--absent`.
- [ ] **A substitution hides literal paths in the same quoted argument.** `echo "$(pwd) scripts/gone.sh"` is one shlex token; the substitution branch skips the whole token before the quoted-string path check runs, so the missing `scripts/gone.sh` produces no finding. Fix: check literal path words around a substitution, never as commands. Regression: that line reports `scripts/gone.sh`.
- [ ] **A substitution does not restore wrapper state.** The `$(` stack saves the command owner but not `prefix` or `pending_operand`. In `sudo -u $(id -un; echo root) -g root scripts/helper.sh --absent`, the inner `;` clears the outer `sudo` prefix; after the restore, `root` is taken as the command and `--absent` is skipped. Fix: save and restore the full segment state. Regression: that line fires.
- [ ] **A rare anchor starves a longer repetitive match, unlabelled.** A = 70 x `same` + `t0..t19`; B = 100 x `same` + `separator` + 31 x `same` + the same tail. Phase 1 consumes the 51-word rare match before the 70-word repetitive one is considered. Both orders report `longest_words: 51` with `estimate: false`, and the consumed words hide the loss from the truncation probe (`a092ac2` reports 70). Fix: compare the bounded fallback's candidates with the anchored ones before consuming any words and accept longest first, or label the pair an estimate. Regression: both orders give 70, or are labelled.
- [ ] **`env -S` / `--split-string` operands are command text.** `env -S "bash scripts/helper.sh" --absent` runs the helper with `--absent`, but the operand is consumed as an ordinary option value; neither the flag nor an unowned flag is counted. Fix: parse the operand as command text, or count it as unexamined. Regression: either outcome is asserted.

## Acceptance

- [ ] Each item has a regression on the input above that fails on the #731 head first, and the PR says so.
- [ ] `skillc selftest` still discriminates every rule. The CPP (`d5ef0a66`, `93ae8540`) and mattpocock (`5863806`) re-runs in `docs/measurements/inspect/2026-11-14-cpp-and-mattpocock.md` are repeated, with every count change explained.

Refs #731, #733.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01CfYAiHBVaApDaofpsJoctH

<!-- end of body -->
