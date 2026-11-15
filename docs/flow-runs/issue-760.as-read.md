<!-- flow-run n=1 id=5608388be35747b9aa8fe7556e5ff254 -->
## Run 1 - issue #760 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #760
- Read at:      2026-11-15T21:53:58Z
- updatedAt:    2026-11-15T13:58:36Z   (context only - moves on comments and labels)
- Body digest:  50f73bd0aa4a52e161a432c878ab5a762389749d2ccde5713f94932fe077426f   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1716 of 1716 (cap 16384)

### Body as read
Three MEDIUM findings from counter-model review pass 3 (Codex gpt-6.1-sol, read-only) on the #754 branch at 383636b. They were deferred under the wave rule that pass-3 findings are not fixed in the reviewed PR. Each says the run claims more than its input supports, and each needs a red case.

1. **Resume fingerprints omit inputs the rounds read.** `skillc/gauntlet.py` `_tree_digest` skips `.skillc`, `.venv` and `node_modules`, but `contracts` can read a declared test path there and `inspect` can include subjects there. Deleting a declared `.skillc/check.py` can leave a cached contract PASS. Round 2 can also infer its repository from git's origin URL, but neither `.git` nor the effective repository is in its inputs, so changing origin can leave classifications cached against the wrong repository.
   - Fix: fingerprint what each command actually consumes, including declared paths and the effective repo.
   - Red: change one of those inputs while the skill and charter stay the same, and the round must re-run.
2. **Round 0 says OBSERVED for an unrelated skill.** It reads only `usage report`'s exit code, so a log holding only `beta` reads OBSERVED for `alpha`. Aliases are ignored.
   - Fix: read the report's per-skill lines for the skill and its aliases, or rename the verdict to what it measures (a log was readable) and keep this skill's population UNKNOWN.
3. **NEXT does not address the actual blocker.** Distinct UNKNOWN stops share generic advice. A neighbour's broken charter gets "give the skill a description ... or a usage log"; an --exclude that drops the skill gets "supply issue states".
   - Fix: carry a structured stop reason into `_next_line`, with one action per reason.

Refs #754.

<!-- end of body -->
