# Closed wave rehearsal preparation (#626)

The approved boundary is recorded on [the issue](https://github.com/cooneycw/skillc/issues/626#issuecomment-6628924989).
Actor-only preparation remains separately preserved at `668d9e1`. The collector
is a separate component; a complete physical rehearsal is not established by
the source and focused controls here.

## Authentication and execution

`HelperTap` freezes the planned role population and full assignment bindings.
The controller opens a turn endpoint only against the captured bootstrap header
and supplies a fresh turn nonce. The endpoint object is controller context,
not serialized authority. Requests may assert the bound identity but cannot
select the role, attempt, current session, executable, environment or result.

`DecideReplyChannel.set_peer_authorizer()` is opt-in and can be fixed only before
the first connection. It receives Linux `SO_PEERCRED`, before parsing any request.
The Docker adapter checks candidate UID/GID and compares the peer's kernel PID
namespace with the independently inspected owned role container. It checks
process start identity across the probe. Host/control-process connections
carrying matching JSON do not acquire that container identity. Denied or unknown
peers count as drops, so they cannot silently preserve complete coverage.
Unobservable PID mappings or insufficient controller access to those kernel
facts are UNKNOWN, not an alternate authorization lane. Existing channels do
not change behavior unless they opt in.

`DockerHelperExecutor` installs the approved CPP helper closure, actor and task
under a root-owned path addressed by their source digests. It independently
checks candidate non-writability and re-reads the source hashes, actual role
handle, captured bootstrap, current session, actor argv and declared tap mode
before execution. Installation and dispatch consume the inherited deadline.
There is no operational host fallback.

A fixed isolated root wrapper verifies the helper pins and launches only the
declared mailbox operation with a minimal environment. The helper itself runs
as the candidate UID/GID, preventing participant-writable mailbox paths from
turning a root observer into a privileged writer. Controller effect reads use
no-follow traversal. The wrapper retains bounded execution output and verifies
the specific assignment/ack/completion effect and source pins before returning
its own result envelope. Participant stdout alone cannot produce that envelope.

## Custody, coverage and verdicts

`tap-controller/journal.json` contains controller sequence numbers, monotonic
elapsed times, bindings, operation receipts and unavailable observations.
`refusals.json` retains the refusal stream independently. Both use digest
receipts, atomic replacement and fsync before replying; loss or mutation is
preserved as UNKNOWN rather than silently overwritten. The finalizer consumes
the actual owned channels, dropped counts, drain results, operation population
and role/helper stop observations. An empty or incomplete operation population
never establishes complete coverage.

Normalized `ack` and `complete` rows require confirmed real helper execution
and its effect. Completion is a protocol signal, not delivered-task success.
`wave_tap_join.protocol_evidence()` re-reads the controller-held receipts and
matches the frozen population before replacing the verdict input's protocol
stream. It reads neither participant logs nor collection-supplied event lists.
Missing observation makes capture coverage incomplete, preventing PASS.

An authenticated, retained refusal projects as the distinct `refused-protocol`
event, which the existing wave verifier's invalid-operation rule rejects. It
never becomes a successful ack/complete. Either intact custody stream can
preserve a known violation when other coverage is lost; loss of both witnesses
cannot invent a violation. The independent delivered-remote grader still runs
under the existing verdict completeness rules. Successful signals cannot rescue
wrong or undelivered arithmetic output, and good output cannot rescue missing
trusted protocol coverage.

## Composition and remaining evidence

The fixture's `TappedWave` composes the existing DockerWave and wake driver.
Bootstrap turns only register and emit the measured scripted header/metadata.
After every role's bootstrap is observed, the controller sends assignments via
the pinned helper. Later resumes use the same session and a protected turn
nonce; measured receipt/completion calls route through that role's authenticated
channel. Registry/read diagnostics remain separate from protocol authority.
The adapter changes no shared DockerWave preparation code or runtime image pin.

`tap-install.json`, `tap-controller/` and `tap-report.json` retain the source and
collection receipts. `COMPLETE` describes observation coverage, not a wave PASS.
The report's collection elapsed time is separate from the lifecycle-only
completion marker; a full caller must include final collection, independent
task grading and clutter accounting in the same completion contract.

Focused controls exercise real helpers and sockets with modeled lifecycle
identity, plus the actual Linux peer boundary. They do not establish remote
Docker authentication or physical runtime qualification. The full thirteen-case
fault population still needs execution through the dynamic driver, confirmed
retirement and independent clutter measurement. Registry release and an actor's
local state file are not zero-clutter evidence. Physical runs, runner updates,
and live model calls require their separately coordinated authority.
