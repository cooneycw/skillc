<!-- flow-run n=1 id=3f10e92e5cee41b7b0bfe06a7bce58b0 -->
## Run 1 - issue #765 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #765
- Read at:      2026-11-15T17:26:01Z
- updatedAt:    2026-11-15T14:53:13Z   (context only - moves on comments and labels)
- Body digest:  0ebdfc3375d61320c3e21bac7be7d3420e6a40c78c222d008692d4f681a2dc4a   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1105 of 1105 (cap 16384)

### Body as read
**Severity: MEDIUM.** Found by counter-model review pass 3 (Codex gpt-6.1-sol, read-only) on the #763 branch at a4b6ad5. Deferred under the wave rule that pass-3 findings are not fixed in the reviewed PR.

**Where:** `.claude/skills/skill-gauntlet/scripts/gauntlet.sh`, the import guard that checks the imported `skillc.gauntlet` file is under the checkout (`g.__file__.startswith(checkout + "/")`).

**Failure scenario:** the checkout's `.venv` holds a NON-editable skillc install, for example a built wheel. Its module path `.venv/lib/python3.12/site-packages/skillc/gauntlet.py` is also under the checkout, so the guard accepts it. `/skill-gauntlet` then runs packaged code that a `git pull` of the checkout does not change, so the skill reports the verdicts of stale code while the source looks current.

**Fix:** compare the resolved module paths with the checkout's exact `skillc/gauntlet.py` and `skillc/cli.py`. Red case: a non-editable skillc installed inside the checkout's environment must give the cannot-find line, exit 2. Negative control: the editable install still runs.

Refs #763, #754.

<!-- end of body -->
