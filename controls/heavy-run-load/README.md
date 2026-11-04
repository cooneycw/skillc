# Sustained load controls

`cases.json` commits four load5/time traces: below threshold, the first exact
120-second boundary, interruption resetting the timer, and a second continuous
boundary. Each sample has an expected verdict, so early aborts are detectable.
The policy aborts only when observed load5 remains at least 20 for 120 seconds.
The separate admission rule requires a fresh load5 below 12 before starting.

Run `python3 ci/check_heavy_run_load_controls.py` with each source file here.
`intact.py` must pass all four cases (exit 0). `always-continue.py` must fail the
two abort cases; `always-abort.py` must fail all four cases; `forgot-reset.py`
must fail below-threshold and both reset cases; `early-boundary.py` must fail
the first boundary and the interrupted timer case. Each bad input must exit 1. An unreadable/malformed source exits 2.

The same command can check a trusted operational supervisor source. It extracts
only its pure `step` function, so checking does not launch another heavy run or
execute the supervisor body. The committed intact function must match the one
used for the retained receipt. Real load samples, process identities, paths,
peak values and gate outcomes stay in the private operational evidence store.
These synthetic controls establish timer discrimination, not actual host load
or successful test execution. No global cleanup or runtime action is performed.
