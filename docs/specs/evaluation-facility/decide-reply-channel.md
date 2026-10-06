# Design: a controller-owned decide-and-reply channel (#183)

- Status: Draft for review — design only; PR A (this doc, the channel module,
  and the `DockerBackend` one-socket mount) is the first implementation PR
- Date: 2026-10-06
- Refs: #183, #14 (runtime part c), #268 (item 5), #269, #64, #78, #150, #158
- Touches: new `skillc/decide_reply_channel.py`; `skillc/docker_backend.py`
  (`compose_run_argv`, `prepare()`); `docs/specs/evaluation-facility/
  managed-backend-protocol.md` (PR D, not this one)

Owner ruling (2026-10-03, verbatim): "yes to both 183 questions." (1)
`DockerBackend` may bind-mount one host-owned Unix socket into the trial
container. (2) The proxy binary may go into the pinned trial image. Decision
2 in #183's body ("what the log may claim") was left to this design — see §3.

## 0. Naming: this is not "the disruption channel"

The module and this doc are named for the MECHANISM (controller listens,
decides, logs, replies), not for Level 5's disruption trigger, which is only
its first caller. #269 depends on #183 to build its own controller-owned
witness for gate execution — a structurally identical need (a subject-side
event must be decided and recorded by the controller, never by the subject)
with different request content. One channel type, two callers. Naming it
`disruption_channel` would have made #269 either import something
disruption-specific or fork the module; `decide_reply_channel` does not.

## 1. Problem (restated from #183 and #14c's own docstring)

`skillc/disruption_trigger.py` (#14c) polls `ExecutionBackend.export()` and
counts lines in a subject-writable request log. Its own module docstring
already states why that is advisory only, precisely: the subject shares the
log-writer's uid, so it can write any number of lines with zero real tool
calls behind them, unconditionally, on every attempt — "the count IS the
claim, and the claim is unenforced end to end." That module is correct and
is not changed by this design; it remains advisory and is never passed as
`trusted_observation`.

The fix the #14c docstring itself names and this design builds: give the
CONTROLLER a way to be both decider and logger for an event a subject-side
process reports, over a channel the subject cannot be on the recording side
of, no matter what it does to its own process, its own filesystem, or its
own copy of the request.

## 2. Design: one host-owned Unix socket per attempt, controller as the only listener

### 2a. Transport and framing

- **One Unix domain socket per attempt**, bind-mounted read-write into the
  container at a FIXED in-container path: `/run/skillc/trigger.sock` (a
  directory baked into the image, `0700 candidate`, mirroring the
  `~/.claude`/`~/.codex` precedent — no new convention). The HOST-side path
  is derived from `attempt_id` alone (`_Handle` already has this; see §2b),
  never from anything host-identifying — the neutral-identity rule applies
  to this socket exactly as it does to the container name.
- **The controller is the server.** It creates the socket, `listen()`s,
  and `accept()`s on a background thread for the lifetime of one
  `execute()` call — the same thread-lifecycle shape `DisruptionTrigger`
  and `AuthorityInterceptor` already use (`start()` / background loop /
  `stop_and_finalize()`), so a caller already familiar with either reads
  this one the same way.
- **One connection per request**, matching `skillc/managed_backend.py`'s
  existing convention exactly rather than inventing a second shape in one
  repository: open, write one line, read one line, close. No multiplexing,
  no persistent session. #268's coordination with this design confirmed
  that #269's witness need does not care whether this is one-shot or
  multiplexed — one-shot is simpler to implement and mutation-test, so it
  is what ships.
- **Framing: one JSON object per line** (`\n`-terminated, UTF-8), the same
  shape `managed_backend.py` and its protocol page already use.

### 2b. The decide-log-then-reply sequence

For each accepted connection, in this exact order:

1. Read one line, parse as JSON. A line that is not valid JSON, or whose
   `op` is not one this channel instance was configured to answer, gets
   `{"ok": false, "error": "..."}` and the connection is closed — refused,
   never silently ignored (closed-schema discipline, matching
   `managed_backend.py`'s own both-directions rule).
2. **Decide.** The configured decision function is called with the
   request's content. For the disruption trigger's own use: a strictly
   increasing per-attempt sequence number, compared against a `fail_after`
   threshold set when the channel was constructed.
3. **Log the decision — before any byte is written back to the subject.**
   The controller appends one record to its OWN in-process log (never a
   file inside the container, never anything `export()` would see) carrying
   the sequence number, the decision, and a wall-clock timestamp. This
   ordering is the entire point of the design: nothing about the reply lets
   a subject reconstruct or pre-empt the decision, because the decision was
   already durable in the controller's process before the subject sees
   anything.
4. Reply `{"ok": true, "result": {"decision": "pass" | "fail"}}` and close.

A subject that never calls the socket at all produces an empty log —
handled explicitly, not as an absence of data (§3, §5).

### 2c. The `DockerBackend` mount — a constrained parameter, not a passthrough

`compose_run_argv`'s own docstring is explicit and, until this change,
correct: "a FIXED, closed set of flags... nothing here can ever mount the
docker socket... NO BIND MOUNT for the workspace or home." This design adds
exactly one exception and keeps every other refusal standing:

- A new, **optional** `trigger_socket_host_path: Path | None` parameter on
  `compose_run_argv` and on `DockerBackend.prepare()`. When `None` (the
  default — every existing caller, every other backend construction),
  `compose_run_argv`'s emitted argv is byte-for-byte unchanged from today.
- When given, exactly one flag pair is added: `--mount
  type=bind,source=<trigger_socket_host_path>,target=/run/skillc/
  trigger.sock`. `target` is the single hardcoded constant
  `TRIGGER_SOCKET_PATH = "/run/skillc/trigger.sock"` — never a parameter,
  so there is no way to ask this function to mount at a different
  in-container path. `source` is a value `prepare()` itself derives from
  `attempt_id` (next bullet) — never accepted from an arbitrary caller-
  supplied path, so the "caller-chosen host path" case the orchestrator
  named has no code path to reach `compose_run_argv` at all other than
  through `prepare()`'s own derivation.
- `prepare()` derives the host-side socket path as
  `self.base_dir / "trigger-sockets" / f"{_container_name(attempt_id)}.sock"`
  (reusing `base_dir`, the same root the docstring already requires backends
  to keep host-side state under — no new host directory convention) and
  creates the socket there itself (via the new channel module, §2a) before
  composing `_keepalive_run_argv`. `_Handle` gains a `trigger_socket_path:
  Path | None = field(default=None, repr=False)` — `repr=False` for the
  same reason `env` already is: a handle's string form must never leak a
  host path (neutral-identity rule, `backend.py` §"NEUTRAL IDENTITY").
- **This is opt-in per `DockerBackend` instance** (a new frozen-dataclass
  field, default `False` or `None`, following `disk_limit`'s own "opt-in,
  not a default" shape), not a parameter threaded through every `prepare()`
  call — Level 5's own caller constructs a `DockerBackend` with the channel
  enabled; every other caller's `DockerBackend` is unaffected and its argv
  is provably identical (test, §6).

Everything else `compose_run_argv` already refuses — a second mount, a
`--privileged`, a `docker` binary, an arbitrary extra flag — stays refused.
No general passthrough is added anywhere in this change.

### 2d. What the log may claim (decision 2)

**The log claims exactly one thing: "the controller received this many
requests on this attempt's socket, and decided as follows for each" — never
"the subject invoked a tool this many times."** A grader may conclude:

- a lower bound on how many times SOMETHING with access to the mounted
  socket connected and sent a well-formed request, timestamped at the
  moment the controller decided, not reconstructed after the fact;
- which of those the controller decided `fail` for, and that the decision
  predates the reply (§2b) — so the subject cannot have influenced which
  decision it received by anything done after seeing it.

A grader may **not** conclude:

- that any particular tool call happened — the channel knows nothing about
  tools, only about requests arriving on its socket. A subject whose tool
  wrapper calls the socket once per real tool invocation makes that
  correspondence true BY CONSTRUCTION of the fixture, same as #14c's
  advisory log always required — the channel does not and cannot verify
  that correspondence itself, any more than `AuthorityInterceptor`
  verifies that a file path corresponds to a real edit versus a touch;
- that the subject could not bypass the socket entirely. It plainly can —
  nothing requires the subject's process to connect at all. §5's red case
  is exactly this: bypass must be visible as an absence, never as a silent
  pass.

This mirrors #268's own item 5 framing exactly: the channel
produces a controller-authored, timestamped-before-reply witness fact. #268
represents that fact as a tri-state `execution_observed`
(`CONFIRMED`/`NOT_CONFIRMED`/`UNKNOWN`), kept separate from criterion
outcomes. For THIS channel's own first caller (the disruption trigger),
the equivalent three-way read is:

| Controller observed | Read as |
|---|---|
| ≥1 request, decisions logged | the disruption point is the logged `fail` sequence number — trustworthy, because logged before any reply |
| zero requests (bypass) | `UNKNOWN`, reason `no-controller-witness` — never `NOT_CONFIRMED`, because a bypass does not positively establish non-execution, it only establishes nothing was reported (#268's own framing, adopted here) |
| socket present but unreachable for the whole attempt (channel construction failed) | `UNKNOWN`, reason `channel-unavailable` — the same `Confirmation.UNKNOWN`-never-guessed discipline `backend.py` already states for `confirm_stopped`/`confirm_absent` |

### 2e. What #269 may build on

#269's acceptance needs "controller-owned execution records" binding a
requested gate to its actual start/completion, unforgeable by the subject.
This channel gives #269, without any change to this module:

- the same socket-per-attempt, bind-mount-one-socket mechanism (§2c) — #269
  does not need its own `DockerBackend` change;
- the same decide-log-then-reply ordering (§2b), with #269 supplying its
  OWN decision function and its OWN request/response content (e.g. `{"op":
  "gate_start", "gate": "lint"}` / `{"op": "gate_complete", "gate": "lint",
  "exit_code": 0}` — #269's to define, not fixed here);
- the same three-way read in §2d's table, generalized: any channel
  instance either has ≥1 logged request (trustworthy, timestamped before
  reply), zero requests (`UNKNOWN`/`no-controller-witness`), or was
  unavailable (`UNKNOWN`/`channel-unavailable`) — #269 is free to name its
  own reasons, but should keep the same three-way shape rather than
  collapsing bypass into a guessed `NOT_CONFIRMED`, for the reason §2d
  gives.
- a retained, controller-side log file that can be handed to `export()`'s
  caller as `raw` data with a `{ref, digest}` pair, matching `records.md`'s
  existing convention for backend raw data (§"Records carry identities and
  digests... Backend raw data is retained and referenced by raw.ref plus
  raw.digest") — so #269's own witness record can cite this channel's log
  the same way any other backend-sourced record is cited, with no new
  retention convention invented for it.

#269 is NOT required to reuse the disruption trigger's specific decision
function, request shape, or log schema — only the transport (§2a) and the
ordering guarantee (§2b). This is what §0's naming choice is for.

**"#269 needs no `DockerBackend` change" holds only while an #269 attempt
does not ALSO carry L5's disruption trigger in the same attempt** — only
one host socket bind mount is authorized per attempt (§6's own limit,
above), so a single attempt cannot run both channel purposes without
either multiplexing over one socket or a new owner ruling. No current
task needs both at once, so this is a named limit, not yet a gap.

### 2f. Socket access control (orchestrator review)

A decide-and-reply channel's socket is the one new privilege boundary this
design adds, and it is the part most likely to go wrong silently — a
misconfigured permission either breaks the channel (subject can't connect,
reads as a false bypass) or over-shares it (a different host process or
attempt connects where it shouldn't). Four questions, each with a code
change and a mutation-checked test (`test_docker_backend.py`,
`test_decide_reply_channel.py`):

**(a) Directory and socket modes/ownership.** `trigger_socket_dir`
(`DEFAULT_TRIGGER_SOCKET_DIR` or a caller override) is never trusted blindly.
`_ensure_private_trigger_dir()` creates it at mode `0o700` if absent; if it
already exists, the directory's owner and mode are checked and the WHOLE
ATTEMPT is refused (`BackendUnavailable`) on either mismatch — never widened
to match, never used anyway on the assumption it is probably fine. This is
the real access-control boundary: directory traversal permission is checked
by the kernel before a file's own permission bits, for every syscall that
resolves a path through it, so a private, owner-verified directory means no
OTHER host process can even reach the socket's host-side path, regardless of
that socket's own mode.

**(b) Subject connect permission without world-openability.** The subject
runs as the fixed `CANDIDATE_UID:CANDIDATE_GID`, essentially never this
controller process's own uid, so `DecideReplyChannel`'s own generic default
(`0o600`, owner-only — correct for a caller that IS its own subject) would
make the subject's `connect()` fail with `EACCES`, breaking the channel
outright for every real use. `DockerBackend` passes `TRIGGER_SOCKET_MODE =
0o666` (owner/group/other all rw) instead. Granting "other" (and "group")
looks wide in isolation; it is not the operative boundary. (a)'s directory
is: nothing on the host other than this controller process can resolve the
socket's HOST path to open it at all, so widening the FILE's own
permission bits changes nothing about who can reach it — only (a) does.
GROUP is granted too, not zeroed (correction, cross-model review: an
earlier draft granted OTHER only, reasoning that GROUP
would need `CAP_CHOWN` to set to `CANDIDATE_GID` — true, but irrelevant,
since the socket's actual group is whatever this process's own primary
group already is, essentially never `CANDIDATE_GID` either way; zeroing
GROUP bought nothing and would needlessly deny a deployment where the two
groups happen to coincide). The container's OWN view of the bind-mounted
file is governed by the image's `/run/skillc/` directory (a #78/PR-B
concern) plus this file's own mode — never by the host directory around
it, since a single-FILE bind
mount exposes only that one file, never its host-side neighbours.

**(c) Can the subject unlink or replace the socket?** Reasoned, not tested
— no real daemon is available in this container, and this is specifically
a live-kernel-and-Docker question `describe()`'s `unobserved` already
marks this backend's boundary for elsewhere. A FILE bind mount's target dentry is pinned by the active mount;
Linux refuses `unlink()` on a path something has bind-mounted onto, in the
mount namespace doing the unmounting, with `EBUSY` — the subject cannot
simply replace the file out from under the mount while it is active. What
this does NOT cover: whether the subject's own mount namespace view differs
in some Docker-specific way, and whether a different attack (e.g.
overwriting through the fd rather than the path) is possible. Both are
named as owed to the operator's live run (#10), the same convention
`describe()`'s `unobserved` already uses for every other daemon-only claim
in this module — not simulated here.

**(d) Two attempts racing for the same hashed filename.** REFUSED, never
silently shared. `DecideReplyChannel._clear_stale_path()` (called from
`start()`, before the bind) distinguishes three states for whatever already
exists at the socket path: nothing (proceed); a SOCKET with nothing
answering (a stale orphan from a prior attempt whose listener was killed
rather than cleanly finalized — `stop_and_finalize()` unlinks on a clean
exit, but a killed process cannot — safe to clear and rebind); a SOCKET with
something actively accepting the connection (another live channel already
owns this path — refused with `OSError`, never adopted, because two channels
sharing one log could not attribute a decision to either attempt). Anything
at the path that is NOT a socket at all (a regular file, a directory) is
refused outright too — this channel creates nothing but sockets at its own
path, so anything else is either a different caller's mistake or an
adversarial pre-creation, and guessing which is not this method's job.

### 2g. Further hardening from cross-model review

`/codex:code_review` (reviewing model `gpt-6.1-sol`, diff-only scope — this
container's sandbox cannot start) found six real issues in the first PR A
draft, none of them in §2f's own access-control design — all in the
channel's concurrency and lifecycle handling. Each is fixed and
mutation-checked (five mechanically; the sixth is a documentation
correction with a pinning test, since there was no code behavior to flip):

1. **Finalization did not wait for an in-flight handler.** `_Server` sets
   `daemon_threads = True` (so a stuck handler cannot hang interpreter
   exit), and `socketserver`'s own join-on-close explicitly skips daemon
   threads — so `stop_and_finalize()` could return a "finalized" log
   while a handler still inside `decide()` was about to append to it.
   Fixed with explicit handler-count tracking: `stop_and_finalize()` now
   drains to zero (bounded by `handler_drain_timeout`, default 5s) before
   snapshotting, and raises rather than returning a log that might still
   grow if a handler outlives that bound.
2. **No bound on concurrent connections, request size, or idle time.**
   The subject's own resource limits (`--pids-limit`, `--memory`, …)
   bound ITS side of this socket, never the controller's — an adversarial
   or merely buggy subject could exhaust controller-side threads or
   memory with no limit at all. `max_concurrent_handlers` (32),
   `max_request_bytes` (64 KiB) and `request_timeout` (5s) bound all
   three; each is a constructor parameter, not a hardcoded constant.
3. **A TOCTOU race in stale-socket detection.** `ConnectionRefusedError`
   on a probe `connect()` does not by itself prove an orphan: another
   channel may have `bind()`'d but not yet `listen()`'d, and a probe
   racing exactly that window would misread a channel mid-`start()` as
   dead and unlink its socket out from under it. Fixed by serializing the
   whole decide-then-act sequence (`_clear_stale_path()` through bind and
   `chmod`) under an exclusive, non-blocking `flock()` on a sibling
   `.lock` file — a second `start()` racing the same path during that
   window is refused outright, never left to guess.
4. **The socket mode zeroed GROUP while granting OTHER** (§2f(b)) for no
   real benefit, since the file's actual group is essentially never
   `CANDIDATE_GID` either way. Changed `TRIGGER_SOCKET_MODE` from `0o606`
   to `0o666` — (a)'s directory remains the real boundary; this removes
   an asymmetry that bought nothing.
5. **A `chmod()` failure after a successful bind left the listener
   open**, uncaught and untracked (`_Server.__init__` already self-closes
   on a bind/listen failure via stdlib `TCPServer.__init__`'s own
   try/except — this gap was specifically the step AFTER that succeeds).
   Fixed by explicitly closing the server on a chmod failure before
   re-raising. (The separate "`_started` set before the server exists"
   half of this same finding was already resolved as a side effect of
   fix 3's restructuring, which moved `self._started = True` to after the
   whole bind-and-chmod section succeeds.)
6. **Logged request/result mappings were stored by reference**, not
   copied — a `decide` function returning the same mutable dict across
   calls, or a consumer mutating a dict retrieved from the log, could
   rewrite an entry already presented as finalized, breaking the
   advertised immutable, append-only record. Fixed with `copy.deepcopy`
   at the point of logging.
7. **The module claimed sequence numbers reflect arrival order; they
   reflect completion order** — `decide` runs outside the log's lock, so
   a request that arrives first but whose `decide` call takes longer is
   numbered after one that arrives second but returns first. Corrected
   throughout (module docstring, tests, this doc); added a test that
   pins the actual (completion-order) behavior rather than leaving it
   implicit.

## 3. Image interaction (#78) — explicitly held, not in this PR

The proxy binary the subject's tool wrapper calls into (to turn a tool call
into a socket request and the reply into pass/fail for the calling fixture
code) belongs to PR B, not this one. PR A adds no file under `docker/trial/`
and does not change `_keepalive_run_argv`'s placeholder command. This
mirrors #158's own landing order exactly (its design doc §7: the supervisor
design merged well before the image change that activates it), for the same
reason: the image is pinned and shared (the #237 uptake study is currently
running real attempts against `skillc-trial:latest`, under an orchestrator-
imposed image-tag fence), so nothing in this PR may require or assume a changed image.
`DockerBackend` with `trigger_socket_host_path` set against TODAY's image
produces a mounted socket nothing inside the container ever connects to —
inert, not broken, exactly the "fail-open on an old image" shape §2c's
opt-in default already gives for free.

## 4. Managed-backend protocol (#64) interaction — PR D, not this one

#64's protocol (status: Proposed, no implementer) will need an equivalent
capability for a platform-backed attempt: a declared in-container path at
which a platform-provided decide-and-reply channel is reachable, named
platform-neutrally (never "bind-mount a socket," which is Docker-specific
vocabulary the protocol page must not assume). This is a doc-only change
plus one new optional `prepare` request/response field and a matching stub
server update — low priority, done last, tracked here as owed rather than
designed in this document, since #64 has no implementer to validate the
field against yet.

## 5. The red case (#183 acceptance item 2)

**A subject that fabricates requests or bypasses the proxy cannot move the
controller-recorded disruption point, or is graded `INCONCLUSIVE`
(`UNKNOWN`/`no-controller-witness`, §2d).** Concretely: a candidate fixture
that writes directly to `.disruption/requests.log` (today's #14c advisory
path) and never connects to the socket at all. Per the group's regression-
test rule, this case is run against PRE-CHANNEL code first: today, nothing
distinguishes that candidate from a cooperating one, because no
`trusted_observation` exists for Level 5 at all yet (confirmed: L5's
`qualify.py` has no live caller, only hand-placed `trusted-disruption-log.
json` fixtures) — so the pre-fix run is expected to show this case passing
clean, which is the red this design is meant to turn into the documented
`UNKNOWN`. PR C is where this case and its pre-fix run land, together with
the live conformance test; this design doc only commits to the shape of the
result (§2d's table), not yet the test.

## 6. Accepted limitations (stated, not silently solved)

- **The channel proves a request arrived; it does not and cannot prove a
  real tool call caused it**, same limitation §2d already states. Fixture-
  level correspondence between "tool call" and "socket request" is the
  fixture's obligation, not this module's.
- **A subject that floods the socket with well-formed requests but no real
  work behind them still gets decisions logged for each one.** This channel
  removes the SUBJECT-AS-LOGGER problem (#14c's actual gap); it does not
  and cannot establish that each request corresponds to genuine work,
  because nothing on the controller side can see what triggered the
  subject's call. Out of scope for #183, same as it was for #14c.
- **This is `DockerBackend`-specific plumbing in PR A.** `ManagedBackend`
  gets no channel capability until PR D lands, and PR D is doc-only even
  then (§4) — a platform-backed attempt cannot use this design's channel
  until some platform actually implements #64's protocol, which nothing
  does today.
- **One socket, one decision function, one attempt** — and the owner's
  ruling on #183 authorizes exactly one host socket bind mount per
  attempt, not a general mount capability (§2c's own `compose_run_argv`
  signature and its mutation-checked tests refuse a second mount
  structurally). This design does not attempt to multiplex several
  distinct channel PURPOSES (disruption trigger, #269's gate witness,
  anything else) over that one socket. No current task needs two channel
  purposes in one attempt — L5's disruption trigger and #269's gate
  witness belong to different task families — so this is not yet a real
  gap, only a named limit: an attempt that ever needed two would require
  either multiplexing over the one socket, or a new owner ruling
  extending the one-socket exception. Neither is in scope here (correction,
  orchestrator design review on PR #298 — an earlier draft of this bullet
  proposed "open two sockets against two mount points," which the code
  this design describes structurally refuses and the owner never
  approved).

## 7. Mapping to #183's acceptance criteria

1. "A reviewed design for the channel, answering the three decisions
   above." — this document. Decision 1 (bind mounts): §2c, owner-approved.
   Decision 2 (log claims): §2d. Decision 3 (image): §3, held to PR B.
2. "A red case: a subject that fabricates requests or bypasses the proxy
   cannot move the controller-recorded disruption point, or gets graded
   INCONCLUSIVE." — shape committed in §5; PR C delivers the test itself
   (`test_disruption_channel_bypass_red_case.py`), run against the
   pre-#183 mechanism directly (no commit checkout needed, since
   `disruption_trigger.py` is unmodified by this issue) rather than
   against a commit checkout.
3. "L5 wired to `trusted_observation` only through that channel." — THREE
   separate claims, split across two PRs, decided (orchestrator ruling):
   - that the channel mechanism itself works, including against a real
     daemon — PR C (`test_decide_reply_channel_live.py`), with a
     mutation-checkable live test rather than a checkout-based one (see
     that file's own docstring for why "the file is new" is not a red).
   - that a real subject's tool wrapper calls through the channel instead
     of writing the old subject-writable log, AND that `qualify.py`
     actually consumes this channel's output as `trusted_observation`
     while the old advisory path stops feeding grading — BOTH PR B's,
     deliberately not split: the fixture rewiring and the grading wiring
     are one L5 change, because splitting them would leave a window
     where the fixture calls the channel but grading still reads the old
     log, silently ungraded by the thing it was switched to use. PR B's
     own red case: the old advisory log ALONE (no channel output at all)
     must no longer produce a `trusted_observation` - shown failing on
     pre-PR-B code (where it still does) and passing on PR B (where it
     no longer can).

## 8. Landing order

1. **PR A** (this doc, bundled — orchestrator direction):
   `skillc/decide_reply_channel.py` (§2a, §2b), the `DockerBackend`/
   `compose_run_argv` constrained mount (§2c), and `test_docker_backend.py`
   cases proving every refusal in §2c's last paragraph still holds, each
   shown to go red under a mutation that removes the specific constraint
   it protects. Does not touch `docker/trial/`.
2. **PR B**: the proxy binary in the trial image (#78), the L5 fixture's
   tool wrapper calling it instead of writing `.disruption/requests.log`
   directly, AND `qualify.py`'s own wiring to this channel's output as
   `trusted_observation` (§7 item 3's decided split — one L5 change, not
   two, so there is never a window where the fixture calls the channel
   while grading still reads the old log). PR B's own red case: the old
   advisory log alone must no longer produce a `trusted_observation` -
   shown failing on pre-PR-B code and passing on PR B. Held until the
   orchestrator clears the #237 image-tag fence; builds a distinct tag,
   never `skillc-trial:latest`.
3. **PR C**: the live-Docker conformance test for the channel mechanism
   itself (`test_decide_reply_channel_live.py` — a real `DockerBackend`
   attempt, real socket, real identity, with three independently
   breakable properties so "the file is new" is never mistaken for a red
   case) and §5's red case (`test_disruption_channel_bypass_red_case.py`,
   run against `disruption_trigger.py` directly rather than a commit
   checkout, since that module is #183's own unmodified "before"). Does
   NOT itself connect to `qualify.py` — that is PR B's, per §7 item 3.
4. **PR D**: the managed-backend protocol (#64) doc update (§4). Low
   priority, done last, still under #183 per the owner's ruling text.

Only PR D (the last PR) carries "Closes #183"; A/B/C each carry "Refs
#183" and state in their body which acceptance items they deliver.

## 9. Decisions from review

1. **One-shot connections, not a persistent session** (§2a) — simplest
   shape that satisfies both this channel's own need and #269's stated
   indifference to one-shot vs. multiplexed (#268's own coordination).
2. **The mount is a `DockerBackend`-instance-level opt-in, not a per-call
   parameter** (§2c) — matches `disk_limit`'s existing shape, and keeps
   every caller that does not ask for this channel provably unaffected.
3. **The log never leaves the controller's own process/host state during
   the attempt** (§2b) — it is not written through `export()` and is not
   inside the container at all, so `install()`'s baseline-absence check
   never needs to special-case it, mirroring #158's design doc §8 decision
   2 for its own control socket.
4. **Named `decide_reply_channel`, not `disruption_channel`** (§0) — so
   #269 can depend on the mechanism without depending on Level 5's
   vocabulary.
5. **The private directory, not the socket file, is the real access-control
   boundary** (§2f(a)/(b)) — directory traversal is checked before a file's
   own permission bits, so an owner-verified `0o700` directory makes the
   socket file's own "other" bit (needed for the candidate uid to connect
   at all) safe to grant, rather than requiring `CAP_CHOWN` to narrow it to
   a group instead.
6. **An existing directory or socket path is verified, never trusted or
   silently widened** (§2f(a)/(d)) — a wrong owner or mode on the directory,
   or an already-live listener on the socket path, each refuse the whole
   attempt (`BackendUnavailable`/`OSError`) rather than proceeding on the
   assumption it is probably fine. Only a confirmed-dead orphan (a socket
   nothing answers on) is cleared and reused.
