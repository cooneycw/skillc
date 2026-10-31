<!-- flow-run n=1 id=dc46121f5a944e8596306cd8edc65ec8 -->
## Run 1 - issue #652 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #652
- Read at:      2026-10-31T10:29:53Z
- updatedAt:    2026-10-31T10:28:25Z   (context only - moves on comments and labels)
- Body digest:  0f00ea9fce1f3d7c1aa82a6d639d94c6c8a2fc8ce35da21be72a13bfcfdd0ba7   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2300 of 2300 (cap 16384)

### Body as read
`skillc/real-docker` is red on main, and it has failed the same way on two main commits in a row. The re-pinned runner fails one of the four cases that #646 (Refs #640) added.

**Failing test:** `tests/test_inventory_oracle_live.py::test_captured_program_outcomes_from_the_real_oracle[executable]`, at line 84.

```
assert verdict['legacy-preserved'] == verdict['tests-protect'] == 'SATISFIED', oracle
AssertionError: {'status': 'ran', 'vectors': [{'id': 'legacy-set-existing', 'feature': True, 'legacy': False}, {'id': 'legacy-list-ord...
  ... {'program': 'replace', 'population_valid': True, 'ok': False, 'count': 6}, ...]}
assert 'VIOLATED' == 'SATISFIED'
```

**Runs:**
- `097c1dd`: `FAILURE: 32 executed (sha 097c1ddae5ce, runner 097c1ddae5ce)`, 2026-10-30T23:12:04Z. 1 failed, 37 passed, 1 skipped.
- `18d89c8` (#651): `FAILURE: 32 executed (sha 18d89c86319a, runner 097c1ddae5ce)`, 2026-10-30T23:47:07Z. Same test failed; same counts.

**What the failure isolates:** the `reference` and `fixture` cases pass on the same module-scoped container, and so does the containment probe. In the `executable` case, `inventory.py` is a stub that does `subprocess.call(["./helper_cli", ...])`. `helper_cli` is the reference source with a `#!/usr/bin/env python3` line, and it is written with mode `100755`. The reference logic is identical in all three cases, so the difference is probably how `helper_cli` gets executed inside the oracle container (execute bit, noexec mount, or interpreter resolution as uid 65534). That is a guess and not verified. The JUnit repr is truncated, so the full oracle output is not in the report.

**Context:** I found this while re-pinning the real-Docker runner to `097c1dd`, which brings `test_inventory_oracle_live.py` into the floor (28 -> 32 executed). The re-pin itself is complete. The runner was previously at `f4060c7` and posted `RUNNER_BEHIND` on `097c1dd`. The runner is now on `097c1dd`, and it certifies each new main head automatically. `/root/campaign-driver-v5.sh` `EXPECT_TOTAL` is now 32 (backup `.bak-640`). The JUnit from the first failure is kept on evals26 at `/tmp/rd-097c1dd-failure.xml`.

**Done when:** a timer run on main posts `SUCCESS: 32 executed (... runner 097c1ddae5ce)`, or the result of a later re-pin, if the fix changes the floor.


<!-- end of body -->
