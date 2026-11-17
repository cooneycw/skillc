<!-- flow-run n=1 id=b0559b8ad7a84fef88886d3011f21245 -->
## Run 1 - issue #756 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #756
- Read at:      2026-11-16T02:24:56Z
- updatedAt:    2026-11-15T13:37:48Z   (context only - moves on comments and labels)
- Body digest:  1c0bdb1f0c648ab5d2f6bd33cea3d039695037336534dd47fac61504b77c970d   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2596 of 2596 (cap 16384)

### Body as read
Deferred from the third and final counter-model pass on #736 PR 1 (Codex, codex/gpt-6.1-sol, 3-pass ceiling). The wave orchestrator's ruling sends pass-3 findings rated MEDIUM or higher to an issue. The reviewer reproduced all four at `9029c4c`. All are in `skillc/gauntlet_trials.py`.

None of them can be reached by a real run yet: PR 1 ships only the scripted runner, and the real Docker runner is #736 PR 3. **Fix them before PR 3 runs anything.** Two of them (1 and 3) affect what a real run spends or reuses.

## 1. Task fingerprints omit metadata that changes behaviour

- **Where:** `read_task` / `_digest_files`, which hash paths and bytes only.
- **Failure:** making `fixture/run.sh` non-executable, or retargeting a directory symlink inside the fixture, leaves the ledger key unchanged. A cached grade is then reused after the agent-visible task changed.
- **Fix:** include file type, executable mode and symlink targets in the task digest, or refuse unsupported fixture entries. Add cache-invalidation controls for both cases.

## 2. Renaming a task directory changes the held-out set

- **Where:** `assignments()` sorts by directory path before the seeded shuffle.
- **Failure:** renaming the control's `a1` to `z1` moves the held-out task from `a2` to `a3`, although every task identity and the seed are unchanged. Content round 3 trained on can become round 4's held-out set through a rename.
- **Fix:** order by content identity before shuffling. Test that renames keep the assignments.

## 3. Conflicting graders are checked only within one clause

- **Where:** `load()` builds `distinct` per clause.
- **Failure:** identical agent-visible tasks with different graders in DIFFERENT clauses are accepted. Planning makes attempts for both graders, and `_counts` merges them by identity. The reviewer's reproduction made **24 scripted calls** before the round read `UNKNOWN` ("12 of 6 attempts recorded"). The outcome is safe, but **attempts are spent that a declaration-time refusal would have saved**.
- **Fix:** check task identity against grader identity across the whole declaration before planning. Add a cross-clause control.

## 4. Equivalent passage paths throw away cached attempts

- **Where:** `arm_digest()` hashes the literal `changes` keys.
- **Failure:** `SKILL.md` vs `./SKILL.md` gives a different arm digest for an identical skill, so its cached results are not reused.
- **Fix:** canonicalize passage paths (the relative path inside the skill), or derive the arm digest from the resulting tree. Test that equivalent spellings need zero new attempts.

Refs #736.

<!-- end of body -->
