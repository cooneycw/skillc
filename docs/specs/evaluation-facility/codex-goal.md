# Native Codex goal control (#637)

`skillc.codex_goal.GoalSession` drives the single-session control through the
0.165.0 app-server protocol. It is an adapter for a future approved attempt
runner, not a live-run command or approval. No live model call is part of its
rehearsal. #639 still owns the approved declaration, acquisition, containment,
run population and report integration. An independently graded result remains
necessary even when the native goal says `complete`.

## Caller contract

The controller must first validate its approved declaration and resolve the
declared image to an immutable ID. Run
`trial_bootstrap.probe_image_cli_version(docker_bin, image_id, "codex")` and require
exactly `codex_goal.CLIENT_VERSION`. The recipe's pin is not a measured version.
Then launch `codex_goal.APP_SERVER_ARGV` **inside the attempt container**, with
the attempt's isolated home, workspace, authentication and declared egress.
Never connect this adapter to the operator's own running Codex session.

The argv is `codex --enable goals --disable step_model_switching app-server`.
Global enablement matters: the server's ThreadGoal handler checks global config,
so a `thread/start` override alone cannot enable goals. Use a fresh home without
a finite `max_goal_token_budget`; the driver also refuses any finite budget
returned by the native goal. Native `tokenBudget: null` means keep the existing
budget, not clear an existing one. Consequently this adapter creates a new thread
and never resumes a previously budgeted thread.

Attach `JsonLineTransport` to that process's binary stdout/stdin pipes, supplying
a `wire(direction, bytes)` callback. For retained evidence, also attach the
same `codex_goal_capture.Capture` to the transport and `GoalSession`, as below. It preserves coalesced frames, refuses duplicate JSON
members and bounds frame size and transport I/O. The backend must separately
drain stderr, contain descendants, confirm process stop and finalize all capture.
The adapter does not own those backend obligations and starts no host process.

Construct `GoalSession` with the objective and exact model from the declaration,
and `comparison_sessions`, a nonempty list of exactly
`{"session": "logical-session-id", "role": "logical-role", "token_budget": 123}`
rows. Every CPP session, including its orchestrator, must appear once. The caller
must derive these rows from its frozen full declaration; the adapter cannot
discover sessions omitted by its caller. The sum is recorded as
`recorded_token_budget`. The owner's #628 ruling makes it a measurement. No
native token cap is sent and no recorded total is enforced by the driver.

`start(cwd=...)` handshakes with experimental capability, starts one pinned-model
thread, then activates its goal. Native `goal/set` immediately starts/injects its
own objective when active. The driver sends no extra `turn/start` and invents no
continuation prompts. `poll()` receives native notifications, including automatic
turns. An ordinary `turn/completed` does not terminate the goal.
`set_goal(status="paused")`, `set_goal(status="active")`,
`set_goal(objective=...)`, `refresh()` and `clear()` expose the lifecycle.
Requests, acknowledgements and all goal state notifications are retained with
ordered sequence numbers; raw frame capture retains other events too. Editing
the objective follows Codex's native accounting reset semantics. The adapter
does not choose new objectives or authorize an edit on the caller's behalf.

## Identity and outcomes

`allowProviderModelFallback: false` disables provider catalog fallback, and
`step_model_switching` is disabled globally and per thread. These are not proof
that usage-limit fallback cannot occur. No general usage-limit fallback kill
switch was established. Startup must resolve the exact declared model. Every
`model/rerouted` event is retained. After confirmed stop, pass the complete,
digest-bound rollout bytes to `report(session_record)`: its first `session_meta`
must bind the thread and pinned CLI version, and every `turn_context.model` is
checked, including changes that later return to the declared model. The caller
owns immutable capture binding, complete-stream retention and finalization;
an arbitrary prefix supplied to this library is not authenticated evidence.

`model_identity` is `CHANGED` if any observed model differs. Such an attempt has
`pool_eligible: false` and must be reported separately, never pooled with the
declared treatment. Missing, truncated, conflicting or unbound session evidence
is `UNKNOWN` and also cannot pool. Prose inside agent output supplies no identity
or lifecycle facts. A stable-model attempt without an infrastructure outcome is
eligible for the caller's remaining declaration/population checks regardless of
goal completion. Independent grading and accounting read `goal_state` and
`outcome`; `task_grade` remains `UNASSESSED`.

Native `usageLimited` and structured `usageLimitExceeded` produce
`infrastructure-usage-limit`, never task failure. Protocol/transport loss produces
`infrastructure-protocol-error`; the caller must still stop the attempt and retain
its original evidence. Stable paused, blocked, cleared, budget-limited or
still-active goals remain in the comparison population with their actual states,
including attempts stopped by the controller's deadline. Filtering them out
would bias the control arm toward its completed attempts. A finite native budget
is a protocol refusal because it violates the uncapped Codex treatment.

## Shared recipe and historical campaigns

Future #639 declarations must explicitly pin Codex 0.165.0 for both arms and
receive the owner's usual declaration approval. One shared recipe preserves
client symmetry. Before narrowing the scripted campaign checks, the native
0.157.1 declarations in the committed corpus and their linked issue dispositions
were inventoried with a known native positive control and retained-record
negative control. No pending or rerun native schedule was identified there.
Private uncommitted plans outside those sources could not be certified absent.
Historical approvals are not reused and no frozen data is rewritten.

The #271/#375/#434 deterministic campaigns execute their pinned actor and fake
client, rather than the native binary in today's recipe (#548 item 4). Their
checks retain the frozen subject/client, task, runtime, harness, candidate and
cap comparisons, and omit only the unrelated current native-recipe version
comparison. Native calibration/pilot entry points keep their recipe-version
refusals and in-image identity probes. `tests/test_scripted_recipe_identity.py`
commits controls in both directions.

## Rehearsal and provenance

Run `uv run pytest -q tests/test_codex_goal.py`. The committed stdio peer at
`tests/fixtures/codex-goal/peer.py` never invokes a model, client or network.
`cases.json` commits both verdicts: healthy completion versus changed model,
usage limit, ordinary turn completion, foreign-thread events, unsolicited
responses, native cap, RPC refusal and wrong startup model. Other tests exercise
the whole lifecycle, transcript-only drift, missing/duplicate/truncated evidence,
frame buffering, I/O timeout and over-limit accounting. The healthy peer consumes
5,000 tokens against a recorded total of 300 and still completes, demonstrating
that the recorded budget does not enforce a stop.

Protocol checked against the published 0.165.0 npm package, its offline
`app-server generate-json-schema --experimental` output, and
`codex features list` in an empty temporary home. The
[official app-server documentation](https://developers.openai.com/codex/app-server)
describes stdio JSONL, experimental initialization and ThreadGoal messages.
Tagged upstream implementation inspection confirmed global feature gating and
automatic goal activation (`openai/codex`, `rust-v0.165.0`,
`codex-rs/app-server/src/request_processors/thread_goal_processor.rs:138`,
`:149`, `:192`, `:249`; `codex-rs/ext/goal/src/runtime.rs:436`). No upstream
implementation code was copied.

The permitted kyle sources were examined at
`4021172f70d9cfab533f82987159d82447fc644c`:
`core/native_launch.py:1` and `core/native_mailbox_wake.py:1`. They implement a
managed TUI/container lifecycle and queue wake, rather than ThreadGoal stdio;
no code from them was copied or imported.

The pin recipe now resolves 0.165.0. A real image rebuild and the image-level
identity probe are still required evidence; offline schema generation and the
scripted peer cannot substitute for them. No frozen declaration or retained
historical client pin is rewritten.

## Durable goal custody (#637 residual)

`codex_goal_capture` follows the controller-owned append/seal/reference pattern
of `wave_wake_capture`. It adds no second goal driver. Before constructing the
transport, create `Capture(private_new_root, Context(...))`. Its frozen context
names the attempt, approved declaration digest, pinned client version, model,
initial objective and recorded CPP-session token total. This binds the supplied
total; exhaustive derivation from the frozen declaration still belongs to #639.
A context containing an approval digest is not evidence that approval was given.

Pass `capture=capture` to both `JsonLineTransport` and `GoalSession`. A captured
session requires that exact transport and capture object; sharing a writer across
connections or sessions refuses. Existing uncaptured calls remain diagnostic and
do not provide retained custody. The context must match the driver's normalized
objective, version, model and validated recorded total before initialization.

Every exact raw frame (base64 encoded in the journal) and structured goal event
is appended with a sequence and previous-line hash, and fsynced before its caller
can consume it. Outbound frames are flushed **before dispatch**: `sent` records a
dispatch intention, not proof that the peer received any bytes. Each successful
raw read is additionally flushed as `received-chunk` before buffering; this
retains coalesced bytes even when a later poll never consumes them. Frame and
chunk observations overlap and must not be concatenated as one transcript.
Partial incoming
bytes are retained as `received-partial` before EOF, timeout or oversized-frame
refusal. An observation may contain malformed JSON; custody retains those bytes
without upgrading them to a valid goal. The transport still bounds I/O and the
existing driver still classifies protocol loss. A write/fsync failure poisons the
capture; it cannot subsequently produce a seal. Goal state is not exposed before
its event append succeeds. The private writer is exclusive and cannot resume.

After the backend confirms process stop and drains its streams, call `seal()`.
The returned `Reference` binds version, context digest, object digest and byte
size. The journal includes a seal with record/event/frame counts, is copied into
a read-only content-addressed object, fsynced along with its directory, verified,
and closed. Retain the reference and expected context independently of the
capture/report. `verify(root, reference, expected_context)` rereads bounded,
nonsymlink regular-file bytes and checks the reference, complete chain, exact
context, ordered event sequence and seal counts. Missing objects, unsealed tails,
truncation, alteration, reordering and misbinding yield `UNKNOWN`. It returns
`CAPTURED` with the retained events/frames only when those custody checks hold.

`CAPTURED` does not witness process stop, a complete rollout, stable model
identity, declaration approval, complete CPP population, or task achievement.
The existing driver and independent grading retain those separate contracts;
#639 still owns the contained process, stderr draining and final rollout binding.
No report-supplied reference may replace the independently retained one. This is
controller storage custody, not a signature against a compromised controller.

Bounds are 64 MiB per journal, 65,536 records, and a maximum 16 MiB transport frame
plus one 65,536-byte read of refusal evidence. Exhaustion fails custody, not the
model's token budget; the native treatment remains uncapped. Only a separately
approved live runner can decide how to stop and account for such an attempt.

`controls/codex-goal-custody/cases.json` commits healthy, tampered, truncated,
reordered and misbound cases. `tests/test_codex_goal_capture.py` qualifies those
cases against the verifier and compiled always-CAPTURED / always-UNKNOWN blind
variants. These are new-instrument qualification controls, not regressions
against a nonexistent API. The two existing-transport regressions in
`tests/test_codex_goal_custody_regression.py` fail on actual `20bfbd4`: dispatch
preceded a failed capture callback, and partial EOF bytes were lost. Scripted
peer cases now also include disappearance and a malformed ThreadGoal. The public
custody input wrong-type sweep is in `tests/test_codex_goal_capture_types.py`.
