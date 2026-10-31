# Live wave verdict

`skillc.live_wave` implements #620's offline verdict boundary over live role
captures. It launches nothing and grants no authority to run a model, access a
remote VM, or spend a budget. Live runs still require an approved declaration
under ADR 0005. `docker_wave.DockerWave` remains a lifecycle-only runtime seam.

The primary observation is one **planned wave**, including a wave that never
started. Role sessions are diagnostics. `report(plans, evidence, grader)` walks
the complete frozen plan list and emits one result per plan; missing evidence
is UNKNOWN. Empty plans, duplicate wave IDs, and undeclared extra waves refuse.
Two successful workers do not replace the integrated-delivery verdict.

## Caller and capture contract

Before observing protocol actions, the controller freezes a `WavePlan` with the
wave ID, common deadline, integrator, and each role's attempt, task, generation,
revision, nonce, session ID and required artifact paths. The session ID comes
from controller-held client startup evidence, not participant prose. A non-start
can have no session ID; it still occupies its planned role and wave row.

`RoleEvidence` joins the controller's role/attempt/session inventory to:

- A captured, newline-terminated session transcript whose initial session
  metadata agrees with the bound session. A later session rebind refuses it.
- A captured protocol JSONL stream. Each controller-observed `ack` or `complete`
  row contains the entire wave/role/attempt/session/task/generation/revision/nonce
  binding, plus `elapsed`. This is a normalized controller observation stream,
  **not** acknowledgements extracted from arbitrary agent text. Its completeness
  must be confirmed by the collector; parsing a transcript cannot supply that
  claim. Malformed, truncated, duplicate-key or digest-mismatched capture is
  UNKNOWN, while an observed wrong-role or stale binding is FAIL.
- Captured artifacts, with their controller inventory SHA256 values. A missing
  capture is UNKNOWN; a missing required file in a complete, naturally finished
  capture is FAIL. Bad bytes with an inventory digest mismatch are corruption,
  not evidence of an incorrect task artifact.
- Controller-held poke count, tokens, wall time, stop reason and cleanup
  confirmation. No observation is inferred from an agent's own success claim.

The `Blob` data and digest are supplied from the controller's captured inventory.
The caller must bound capture and preserve that inventory independently of
participants. The digest detects capture corruption; it does not authenticate a
participant-writable transcript or turn a self-report into trusted evidence.
This module does not implement the collector or discover live resources.

The independent `ArtifactGrader` receives captured bytes for **all** planned
roles, including the integrator, and returns a `DeliveryGrade`. It must implement
the declared task's integrated-delivery criteria. The model-free control grader
compares the integration with both independent worker outputs; no worker score
is substituted for that comparison. An unavailable grader yields UNKNOWN.
The declaration/caller is responsible for pinning the grader and task contract.

## Time, infrastructure and precedence

All event, stop, grading and infrastructure times are seconds from the same
controller-owned monotonic origin. `WaveEvidence.completion_elapsed` covers
capture and confirmed cleanup. `DeliveryGrade.completed_elapsed` is the measured
completion of artifact grading. The result's completion boundary is the maximum
of those times; final report emission is outside that boundary. Missing timing
evidence cannot earn PASS. An event after capture completion, or grading before
observed role completion, is inconsistent evidence and yields UNKNOWN.

PASS needs complete, on-time role evidence, valid protocol, correct integrated
delivery and confirmed cleanup. Exact deadline equality is allowed; anything
after it cannot earn PASS. A separately witnessed deadline is FAIL even if
cleanup confirmation is subsequently lost. A deadline caused by an earlier
infrastructure cancellation does not become a task failure. The controller must
record `infrastructure_failed_at` and `deadline_witnessed_at` independently;
no task timeout is inferred merely because cleanup finished late.

A natural nonzero exit or an unfinished natural exit is a task failure only
when it precedes infrastructure cancellation. If infrastructure timing is
missing, the module conservatively avoids that inference. Similarly, incorrect
partial artifacts graded after infrastructure cancellation remain UNKNOWN.
An independently observed positive protocol violation or artifact failure from
before the infrastructure problem remains FAIL. FAIL takes precedence over
unrelated missing evidence, with both reasons retained in the result.

## Diagnostic metrics and downstream seams

Each role row retains its declared binding, transcript/protocol digests, artifact
digests, started/stop state, poke count, tokens and wall time. Missing metrics are
null, never invented zeroes. Aggregate tokens are present only when every role
has an observation. Wave wall time includes the completion boundary. Timeout and
abandonment are reported separately from delivery and infrastructure reasons.

The proposed #622 poke seam is `PokeCount(role, session_id, pokes)`, where
`pokes` is a nonnegative controller count or null. Missing or mismatched required
poke capture is UNKNOWN. This seam is fixture-backed until the #622 producer
interface is agreed; it does not claim that live integration has run.

Optional #623 handoff timings and #619 clutter count stay null when unobserved;
their absence does not block PASS. They are separate metrics and provide no
delivery credit. Invalid supplied measurements are flagged UNKNOWN. There is no
claim of native wake fidelity, role isolation, model identity or live cost proof.

## Committed controls

`controls/live-wave/healthy.json` holds a complete synthetic controller capture;
`cases.json` records explicit patches and expected verdicts. It includes healthy
and alternative worker order PASS, unfinished integration, wrong-role and stale
acknowledgements, duplicate completion, bad integration and missed deadline FAIL,
and missing capture, launch failure, uncertain cleanup and infrastructure
cancellation UNKNOWN. Combined cases preserve a positive violation despite
unrelated missing evidence and distinguish infrastructure-before-deadline from
deadline-before-cleanup-loss.

Run `uv run --no-sync pytest -q tests/test_live_wave.py`. Additional controls
exercise capture corruption, ambiguous identities, deadline equality, late
grading, optional metrics and population reconciliation. These are model-free
fixtures, not live session evidence or a live-run declaration.
