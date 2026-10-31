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
a `wire(direction, bytes)` callback that writes every exact frame into private,
controller-owned capture. It preserves coalesced frames, refuses duplicate JSON
members and bounds frame size and transport I/O. The backend must separately
drain stderr, contain descendants, confirm process stop and finalize all capture.
The adapter does not own those backend obligations and starts no host process.

Construct `GoalSession` with the objective and exact model from the declaration,
and `cpp_sessions`, a nonempty list of exactly
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
or lifecycle facts. A complete goal with stable evidence is eligible for the
caller's remaining declaration/population checks, not automatically a successful
task. `task_grade` remains `UNASSESSED`.

Native `usageLimited` and structured `usageLimitExceeded` produce
`infrastructure-usage-limit`, never task failure. Protocol/transport loss produces
`infrastructure-protocol-error`; the caller must still stop the attempt and retain
its original evidence. Paused, blocked, cleared, budget-limited or still-active
goals do not pool as completed attempts. A finite native budget is a protocol
refusal because it violates the uncapped Codex treatment.

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
