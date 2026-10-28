# Artifact qualification lane controls (#462)

The full collection contains an ordinary test, a load-harness test and a
`change-with-regression-568` qualifier consumer. `ordinary.xml` plus `serial.xml`
is the exact, disjoint union. The production `ci/pytest-lanes-control.sh` accepts
that pair and refuses an absent serial report, a dropped qualifier identity, or
a duplicated qualifier identity. The existing population controls still cover
incomplete XML and declared-count mismatches.

The committed classifier and real-collection regressions fail against the old
#608 routing: the qualifier identity returns false for serial classification,
its real pytest collection remains in the ordinary lane, and the healthy report
pair is refused. After the routing change the same cases pass. No frozen file,
artifact requirement, grader rule, probe deadline or resource control changes.

## Observed red and measured cost

On unchanged main `e6160e9ee187ffa84ae6e88acd8aa7f7ce899ed1` in a two-CPU quota:

- Idle `qualify()` certified in 42.775 seconds (359 managed processes). Its
  slowest five-second project-test probe took 0.687 seconds.
- Four owned busy loops did NOT reproduce the red: qualification still certified
  in 95.037 seconds; the slowest project-test probe took 1.432 seconds.
- Sixteen owned, CPU-active busy loops reproduced all three module-fixture setup
  errors in 388.807 seconds. The reference project-test probe raised
  `Unavailable('probe timeout; parent reaped and owned group signalled')` at
  5.099 seconds, before the whole 450-second qualification deadline.

The three consumers were `test_fixed_population_discriminates_artifacts`,
`test_actual_feature_and_regression_test_reds`, and
`test_resources_have_real_refusal_and_positive_twins`. This supplements the
observed four-xdist-worker container failure on `14ff662` reported under #462;
it does not pretend that four external loops reproduced that scheduler state.

Qualification's observed 43-95 seconds now contribute to the serial phase,
plus this module's other checks. This is a measured gate cost, not a claim that
total gate time always rises by that amount: ordinary-phase overlap also changes.

## Reproduction

Use a Linux container with a quota of at most two CPUs:

```bash
uv run python3 -m ci.reproduce_oracle_lane contended --report-dir reports/oracle-red
uv run python3 -m ci.reproduce_oracle_lane split --report-dir reports/oracle-green
```

The first command holds sixteen owned competitors through the unchanged
qualifier and returns pytest's own verdict. Inspect its retained JUnit errors;
other unavailability is not evidence of the five-second project-test timeout.
All competing children are terminated and reaped on exit.

The second command runs sixteen CPU-active competitors as ordinary work,
reaps them and their pytest process, then runs the three real qualifier
consumers serially. The resulting exact four-ID union must pass. The ordinary
XML supplies its workload reap time, checked against the lane receipt by the
same ordering validator whose overlapping/unreaped negative cases are committed
in `tests/test_pytest_lanes.py`. The existing resource consumer checks that the
explicit 0.3-second slow control still reads UNKNOWN and its healthy twin passes.
