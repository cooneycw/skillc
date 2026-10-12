# Issue 364 review

Implementer and reviewer identities were measured from their own Codex rollouts.
The standard receipt CLI has no Codex-to-Codex lane; the receipt uses its model
parser, builder and validator directly, with the implementer source recorded.
See [CPP Nit Store](https://github.com/cooneycw/claude-power-pack/issues/864#issuecomment-6129603007).

Three first-pass findings were accepted and fixed. Each new regression test
failed before its fix and passed afterward. The second pass found no defects.
The grouped producer integration and full suites run outside the read-only
review sandbox; the reviewer did not claim to have executed them.

## First pass

## Findings

### [MEDIUM] Collection artifact races with the leak scan

**File:** [.woodpecker/ci.yml:37](.woodpecker/ci.yml:37)

**Issue:** `pytest-collected.txt` is written into the shared workspace while `leak-check` runs independently. Collection includes parameter IDs from `tests/test_leak.py`; collecting that module produced 13 seeded leak findings. The artifact is not excluded, so CI can fail depending on step timing.

**Suggestion:** Add a narrow exclusion for this generated artifact and update the exclusion-parity contract.

### [MEDIUM] Grouped tests fail population matching

**File:** [ci/check_pytest_population.py:50](ci/check_pytest_population.py:50)

**Issue:** With `--dist=loadgroup`, xdist appends `@group` to grouped test node IDs, which pytest preserves in JUnit names. Independent serial collection has no suffix. A passing `test_pass` grouped as `serial` therefore reports `test_pass@serial` and fails population matching. This prevents using the proposed grouping mechanism for tests requiring serialization.

**Suggestion:** Preserve canonical identities across both producers, or normalize verified group suffixes without stripping legitimate parameter text. Add coverage using a real grouped pytest test.

### [MEDIUM] Invocation-parity check accepts narrowed or serial CI runs

**File:** [tests/test_ci_local_gate_coverage.py:201](tests/test_ci_local_gate_coverage.py:201)

**Issue:** `_parallel_contract` checks flag substrings rather than effective arguments. It returned `True` after adding `--ignore=tests/test_docker_backend.py` to both CI collection and execution, while leaving Make unchanged. The population checker would also accept that reduced population. Appending `-n 0` likewise passes despite making CI serial.

**Suggestion:** Compare normalized execution and selection arguments, reject conflicting options, and commit controls for CI-only exclusions and trailing worker overrides.

## Red cases

- **Population checker:** Committed `short.xml` omits one testcase despite declaring two. Rejected; `good.xml` accepted.
- **Identity preservation:** Replace `test_pass` with `test_other` while retaining the count. Rejected.
- **Outcome comparison:** Change `test_pass` from passed to failure against `good.xml`. Rejected.
- **Invocation parity:** Committed replacements disabling parallelism, collection, or the checker were rejected. CI-only exclusion and trailing `-n 0` were incorrectly accepted.
- **Grouped identity:** Ungrouped collection paired with JUnit `test_pass@serial` was incorrectly rejected despite complete passing evidence.
- **Make failure propagation:** Enable the committed timeout control with `SKILLC_RUN_TIMEOUT_CONTROL=1`; `make test` must exit nonzero through `tee`. Not executed because the read-only sandbox prevents its temporary-file operations.
## Second pass

## Findings

None - no defects found.

## Red cases

Verified read-only:

- Committed `short.xml`: declares two tests but contains one testcase. Rejected; `good.xml` accepted.
- Equal-count report replacing `test_pass` with `test_other`: rejected.
- Grouped name `test_pass@serial` with property `other`: rejected.
- Changed pass/failure or skip/xfail outcomes: comparison rejected.
- Empty collections, count mismatches, duplicate identities, and malformed report structures: rejected.
- CI-only `--ignore=tests/test_docker_backend.py`, appended `-n 0`, and removed population-check commands: parity contract rejected.
- Git-control fixtures with partial git skips, missing reports, and malformed XML: rejected; complete fixture accepted.

Mutation cases ran in memory. Full collection and producer integration could not be rerun because the read-only sandbox provides no writable temporary directory. No files were edited.