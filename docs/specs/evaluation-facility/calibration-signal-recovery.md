# Real-Docker calibration signal/recovery reproduction (#613)

`tests/test_calibration_signal_recovery_live.py` retains the production
calibration scheduler, lifecycle and public `calibration-report` recovery path.
Only the attempt's client is replaced with a deterministic Python script,
delivered through `deliver_home_file`. Containers use `network=none`; no model,
credential or provider is involved. Finite fixture timeouts bound stalled tests.

Each fresh run plans four slots, completes and checkpoints the first, then pauses
the second before durable dispatch, after dispatch, during actual container
execution, or after execution but before lifecycle publication. Container-home
readiness and release travel through `read_home_file`/`deliver_home_file`.
Timeouts fail with controller diagnostics; they never certify a timing outcome.

Six SIGINT cases pair default startup with inherited `SIG_IGN` at the three
post-dispatch seams. The parent signals the controller PID alone. Default startup
must interrupt without launching slots three/four, preserve all outcomes, and
confirm native owned-container retirement before independent recovery cleanup.
Inherited-ignore must continue only after explicit release and capture all four.

Four SIGKILL cases include the before-dispatch opposite. Recovery must leave the
checkpoint bytes unchanged, retain all four planned identities and journal
prefixes, report never-dispatched as not-run and dispatched as inconclusive.
A Linux child subreaper retains and reaps exact launcher PID/start-time pairs.
The parent saves inspected immutable resource IDs before signalling and invokes
`skillc.reap` for only its attempt IDs, confirming cleanup independently.

## Qualification and evidence

On the authorized Linux real-Docker runner, execute the ten-case population with
`uv run pytest -n 0 -m real_docker -q tests/test_calibration_signal_recovery_live.py`
and retain its JUnit report and private pytest case directories. A prebuilt trial
image may be selected through `SKILLC_TRIAL_IMAGE`; the controller launches only
its resolved immutable digest, retaining the tag as provenance. A focused
stable-tag/retagged-registry control exercises the actual backend run composition
without a daemon; the retagged case failed before digest-only launch was applied.
Otherwise the module builds
and removes its own image using the existing trial-image helper. Image build
failure is a failure. A missing daemon reports UNAVAILABLE via skips, which the
certifying floor refuses. Installing a runner with the new floor remains a
separate reviewed deployment.

Each private directory retains source commit, probe digest, image ID, startup
signal policy, named timing seam, ready/execution receipts, pre-signal journal and
resource inventory, checkpoint prefix, recovered report and cleanup confirmations.
Container readiness demonstrates execution, not model-token spending. Preserve
these private files before pytest or runner scratch cleanup. Publish a redacted
receipt naming the exact executed population, source/image identities and each
outcome. Do not publish local machine or fleet identities from raw evidence.

`controls/calibration-signal-floor/` commits ten-pass, missing, all-skipped,
failure and error JUnit inputs. The new verdict tests failed against the old
floor before registration; all unrelated floor files pass in these controls.
Removing just the new entry falsely accepts each bad population. These are
synthetic floor controls, not daemon reproduction results.

The ten cases are reproduction probes. Until they execute on a real daemon,
neither original signal/accounting symptom is reproduced or ruled out. Any
production fix still requires an actual pre-fix red on that daemon. Qualification
must also demonstrate that suppressing default PID SIGINT or hiding durable
dispatch is detected; inherited-ignore and never-dispatched remain opposites.
The separate #613 real-proxy schedule-stop acceptance remains outstanding; this
slice does not remove its release-note caveat or close #613.

The committed `reproduction-controls.json` names two separate expected-red
runner executions. Set `SKILLC_SIGNAL_REPRO_CONTROL=suppress-sigint` and run only
the listed default/during-execution node; it releases without sending SIGINT,
so continuation must fail the interrupt-exit assertion. Set the variable to
`forget-dispatch` and run only the listed SIGKILL/after-dispatch node; it removes
only that private fixture journal's dispatched event before public recovery,
which must fail the inconclusive assertion. Keep sabotage receipts distinct
from intact observations. Never enable either mode in an intact qualification.
