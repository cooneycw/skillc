# Split-suite controls (#462)

`collected.txt` is the independent population authority. `ordinary.xml` and
`serial.xml` are its exact, disjoint union. `ci/pytest-lanes-control.sh` accepts
that pair and refuses all five committed bad pairs:

- `ordinary.xml` + absent `missing.xml`: the serial invocation/report is omitted.
- `ordinary.xml` + `serial-dropped.xml`: its selected serial ID disappeared.
- `ordinary.xml` + `serial-duplicate.xml`: a test was counted in both lanes.
- `ordinary-incomplete.xml` + `serial.xml`: ordinary output was truncated.
- `ordinary-count-mismatch.xml` + `serial.xml`: declared count disagrees with cases.

A rejected pair cannot leave a stale merged success report. The same merger is
used by the gate runner, and its exit status reaches both make (through pipefail)
and CI. Declared XML counts must also agree with the testcase population.
`tests/test_pytest_lanes.py` checks these cases through the runner, the actual
CLI, and real path/`-k` selections with either lane empty.

## Forced contention and ordering proof

The pre-fix full gate on `9175d3ab6337a36cf4c68f2c8fa7fad39272be16`
failed only `tests/test_load_harness.py::test_busy_workers_are_attributed_their_cpu_time`
under full-suite contention (8,396 passed, 105 skipped, one failed). The unchanged
ID passed alone. The fix is scheduling, not weaker attribution or a load skip.

Run the committed experiment explicitly in a Linux container with a CPU quota
of at most two CPUs:

```bash
uv run python3 -m ci.reproduce_load_lanes contended --report-dir reports/contended
uv run python3 -m ci.reproduce_load_lanes split --report-dir reports/split
```

The first mode keeps four external busy loops alive while the real attribution
test runs. It must still report INVALID and fail; the wrapper accepts only that
expected red and then terminates/reaps its competing loops.

The second mode selects `workload.py` as ordinary work plus the same real
attribution test. The workload starts four busy loops, proves them live, then
terminates and reaps them. Its XML contains the reap time. The gate receipt
must order that time before ordinary pytest's reaped exit and then serial
pytest's start. Both selected tests must pass. Committed wrong-order and
unreaped receipt inputs in `tests/test_pytest_lanes.py` prove that the ordering
check rejects the opposite condition.

These explicit experiments do not authorize a full suite, retry a failed harness
measurement, or claim to protect against external host contention.
