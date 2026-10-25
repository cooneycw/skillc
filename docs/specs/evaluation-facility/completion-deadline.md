# Selected completion deadlines

`CompletionDeadline.after(seconds, clock=monotonic)` owns one finishing time.
The selected pilot, calibration and discrimination controllers create or inherit
it before their own validation, planning and setup. A child only shortens its
parent endpoint. An earlier acquisition step is covered only when its caller
provides the already-started parent. This is the selected shared-budget slice of
#546; cap equality, operator signals, egress stops and a recovery CLI remain open.

`remaining(cap)` uses the original clock immediately before actual execution,
after journal/spool creation, backend setup, local staging or controller hooks.
It clips the next process/turn/probe/judge allowance without editing the declared
grader identity. Stop/reap grace is cleanup slack and cannot earn completion
credit. Filesystem operations and backend calls have no hard interrupt promise.

Bounds must be positive finite nonbool numbers. Every clock observation must be
finite, numeric, nonbool and nondecreasing; equal ticks are valid. Invalid time
poisons the shared locked clock domain, including its children, and prevents
further launch/credit. Cleanup still runs. Injected clocks establish policy
behavior only, never host or native-client latency. An inherited wave uses its
parent domain even if the caller also supplies a different clock.

The explicit `run_attempt_with_deadline(scheduled, budget, deadline)` scheduler
route keeps the legacy two-argument callback route separate. Direct primitive
`completion_deadline=None` retains the prior contract. Built-in declared-total
controllers select the deadline-aware route. They construct each child's
`trial.OwnedAttemptIds(experiment, parent_attempt)` before backend factories.

This caller-visible append-capable list is the SAME object through collection,
agent, discovery and every ordinary/receipt grading wrapper. A task controller
may capture it and the endpoint in its own post-capture closure. Actual generated
IDs are synchronously journaled before `prepare`; persistence failure prevents
preparation. Duplicate/conflicting ownership and wrong-parent bindings refuse.
Probe and discovery cleanup confirmation comes only from an actual handle's
backend result. Failed prepare without a handle retains the ID but leaves
absence UNKNOWN. Cache hits create no new ID; host probes create no backend ID.
This collector supplies evidence, not a global reaper.

The verifier preserves its evidence-store snapshot check. During owned grading,
only exact bytes appended by that bound collector may extend the original
parent journal prefix. An unauthorized prefix/suffix or another store change
still refuses. The expected suffix comes from trusted writes, not by reading a
mutable journal and accepting event names found there.

A durable opt-in marker binds the intended attempt, original endpoint/budget,
clock kind and completion scope before selected preparation. Raw task criteria,
immutable verified results and the closed agent-observation schema remain task
facts. Whole completion is sampled after lifecycle capture/finalization,
discovery, final grading, integrity/trusted object writes, result storage and
confirmed cleanup of the agent and registered resources. Grading-phase evidence
alone cannot certify later storage. Observed task FAIL remains FAIL beside
unavailable completion; a raw task PASS with late/unconfirmed completion loses
completion credit.

The completion sample is immutable. Final qualification journal, observation and
private-outcome publication are outside that interval. This excludes their
duration from the measured promise; missing final publication cannot recover as
PASS. There is no hard total publication-duration guarantee.

Supplied outcomes, lifecycle-only recovery, generic outcome readback and direct
reports join private completion data against the actual durable opt-in and final
qualification. Missing, malformed, copied or mismatched attempt/budget/clock/scope
evidence becomes UNKNOWN. Omitting fields cannot turn an opted attempt into a
legacy one. Unopted legacy outcomes retain their prior interpretation. Both
calibration endpoint branches combine completion after deriving honest raw
criteria, and discrimination retains the raw task grader beside its qualified
endpoint. No planned slot or denominator is filtered out.
