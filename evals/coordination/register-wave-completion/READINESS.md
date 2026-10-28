# Register-wave completion: bounded offline foundation (#569A)

This slice supplies a Python API (`skillc.coordination_wave.run_wave`) and
committed deterministic subprocess fixtures. Full #569 remains open. It does
not certify a live agent workflow or establish a timeout recommendation.

The original foundation was prepared by BB in preserved candidate
`701fcd85b110b4449cbbcec5002b96b59c5d3dd0`. Its54focused checks, seven accepted
review fixes and behavioral red runs are historical contribution evidence.
Fresh delivery approval, review and verification are recorded separately in
`docs/flow-runs/issue-569.md` and the delivery's counter-model receipt.

CPP#1560's documentary old/fixed pins are
`dd988219e056ddf23fb7ef5ba55e93979c07b61a` and merged
`87ecb0970f70aace9e0323feee00c9ca57dda133`; the manual scenario is retained in
[the preparation handoff](https://github.com/cooneycw/skillc/issues/569#issuecomment-6395963565).
These are not evaluated runtime treatments. Active#571 supplies the next bounded
project-task attachment after this API ships; native/runtime/live readiness
remains separate.

One predeclared wave is the primary unit. Three role attempts are diagnostics:
two workers produce independent captured artifacts, then the orchestrator
produces a captured map of their exact digests. Three exited processes, three
completion claims, and an aggregate acknowledgement cannot earn PASS.

| Boundary | Evidence in this slice | Limit |
| --- | --- | --- |
| Subject identity | Actor source digest and closed mode checked before setup; copied pinned source launched with Python `-I` (isolated import mode) | Trusted controller-host fixture; caller-selected source is trusted, not authenticated as a built-in participant |
| Ownership | One planned attempt, workspace and process group per role; real Unix sockets | No hostile same-UID isolation or role authentication |
| Routing and receipt | Role/session/generation/attempt/wave joins; task/revision/nonce receipt claims checked | Actor receives its attempt ID explicitly; this profile does not inherit `run_attempt`'s subject-ID secrecy property |
| Delivery | Controller requests/decisions and participant receipt claims remain separate | No observation of native wake, reply delivery, tool invocation or downstream client execution |
| Dependencies | Both worker artifact captures precede the integration offer; final integration bytes identify both captured digests | No disposable Git repository, service readiness or native client task yet |
| Capture | Channels finalized after process stop and before event import; complete request/decision joins and final object/manifest/lifecycle re-read | Failed handler drain is UNKNOWN; a retained event prefix is explicitly marked unfinalized |
| Cleanup | Process-group stop confirmed, allocated workspace removed, every planned attempt finalized | Unconfirmed stop/cleanup is UNKNOWN; no guessing from leader exit |
| Deadline | One monotonic deadline starts before declaration validation/setup, covers actors, capture, final verification, cleanup and initial non-PASS provisional evidence | Host filesystem I/O and Python callbacks cannot be forcibly interrupted; teardown may run late and cannot earn PASS |

The public result reports PASS only for complete, on-time evidence. Positive
protocol/artifact violations produce FAIL. Missing observation, launch failure,
capture corruption, failed channel drain or uncertain cleanup produce UNKNOWN.
An infrastructure failure's induced cancellation or late cleanup does not
become a task failure. An independently witnessed wrong-role request remains
FAIL even if later capture is unavailable. Setup exceptions preserve accounting
and a non-passing report, then re-raise the original exception.

The orchestrator explicitly amended publication semantics after review: sample
immutable `completion_elapsed` after all required work/evidence/cleanup and the
initial non-PASS provisional report. Final decision-record emission is outside
that completion deadline. Stage the complete final decision, then atomically
replace the provisional report. Failed staging/replacement raises and leaves
authoritative non-PASS evidence; a staged candidate is never authoritative.
The verdict file does not certify its own final publication duration.

The approved plan's "one recoverable delayed-offer retry" is clarified here:
the controller defers the first eligible offer once, then releases that single
offer after the declared delay. Repeated bounded polls observe availability;
there is no resend, transport retry, missing-wake recovery or deadline extension.
This clarification was accepted by the wave orchestrator. Limits are three
active roles, 128 events/requests, 4 KiB requests, deadline at most 30 seconds,
and initial offer delay at most one second. The controller cancels when a bound
is reached; handlers use bounded request/drain waits. These are fixture bounds,
not measured production latency estimates. An injected clock is labeled
`injected-policy-only`; it establishes expiry policy, not native latency.

Committed adverse controls run the actual process/socket/capture path:

- Wrong role, session, generation, revision, wave, task, attempt or nonce;
  boolean identity/revision lookalikes; duplicate registration, receipt or completion;
  a completion without an artifact; and a missing integration artifact fail.
- A hung role reaches the common deadline; a disappeared role fails. Healthy,
  alternate worker order and a deferred single offer pass.
- Launch unavailability, missing/corrupt captures, corruption after dependency
  relay, blocked in-flight decisions, and cleanup-confirmation loss are UNKNOWN.
- Partial channel setup and participant-thread setup retain all three lifecycle
  records and close owned resources before re-raising.
- Actor staging and journaled partial allocation failures preserve all planned
  attempts. Teardown publication loss cannot skip other channel closures or
  replace the original setup exception. Retained channel deletion/replacement
  is UNKNOWN. A natural code-7 exit remains FAIL across another role's
  infrastructure cancellation; an exit induced by its own controller refusal
  does not create an independent failure. Real request floods hit the resource
  bounds; a separate policy control exercises request 129 explicitly.
- Stalled capture crossing the deadline remains UNKNOWN; the same fault after
  an independently witnessed wrong-role request remains FAIL. Slow report
  writing cannot preserve an earlier provisional PASS.
- A real common-deadline cancellation of an acknowledged unfinished task remains
  FAIL after later cleanup uncertainty; infrastructure cancellation first stays
  UNKNOWN. Injected policy clocks force both causal orders through main-loop
  and allocation-side expiry without replacing the real runner cancellation callback.

Development verification uses `make test PYTEST_ARGS=tests/test_coordination_wave.py`
with collection/JUnit population equality, plus `make lint typecheck`. Behavioral
red runs on the earlier draft exposed launch misclassification, missing partial
setup accounting, post-relay corruption, causal deadline misclassification and
late report publication; each control subsequently passed. New-profile adverse
cases are negative controls, not claimed regressions against a missing API.

Remaining readiness work is explicit: #569B needs a disposable repository or
service task with independently established final success and the complete
fault matrix, including missing-wake/recovery behavior. Native session startup,
wake observations, client/runtime identity, exact runnable subject pins and an
approved live declaration are separate prerequisites. No live participants,
model trials, runtime installation, native worker launch or external task were
run here. Historical evidence and the frozen #557 runtime remain unchanged.
