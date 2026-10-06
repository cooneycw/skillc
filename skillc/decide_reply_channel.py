"""A controller-owned decide-and-reply channel (#183).

See `docs/specs/evaluation-facility/decide-reply-channel.md` for the full
design and the two decisions review settled: what this channel's log may be
read as (its own `TrustedLog.read_as` docstring below carries the same
table), and why it is named for the MECHANISM rather than for Level 5's
disruption trigger, its first caller (#14 part c, `skillc/disruption_trigger.
py`) - #269 depends on reusing this same mechanism for an unrelated witness.

ONE SOCKET, ONE DECISION FUNCTION, ONE ATTEMPT. The controller is the
server: it `listen()`s on a Unix domain socket bind-mounted into the trial
container (`skillc/docker_backend.py`'s `compose_run_argv` /
`trigger_socket_host_path`) and is the ONLY process that ever writes to this
channel's log. One connection per request - open, one JSON line in, one JSON
line out, close - matching `skillc/managed_backend.py`'s existing framing
convention rather than inventing a second shape in this repository.

DECIDE, THEN LOG, THEN REPLY - in that exact order, enforced by this
module's own call sequence, never by caller discipline. By the time any byte
reaches the subject, the decision is already durable in `self._log`: nothing
about the reply lets a subject reconstruct, predict, or pre-empt a decision
it has not yet been told.

THE CONTROLLER NUMBERS REQUESTS, NEVER THE SUBJECT. Any `seq`-shaped field
in an incoming request is part of the request content handed to `decide`,
never used as this channel's own sequence number - that number is an
internal counter, incremented once per request in COMPLETION order (the
order `decide` calls RETURN, assigned under the same lock that protects
the log), not necessarily the order requests ARRIVED - `decide` runs
concurrently across connections, outside that lock, so a request that
arrives first but whose `decide` call takes longer can be numbered after
one that arrived second but returned first (cross-model review finding -
an earlier draft of this paragraph claimed arrival order, which was
simply wrong). A subject cannot claim an out-of-order or
duplicate position for its own request, whichever order this turns out
to be.

A SUBJECT THAT NEVER CONNECTS IS A REAL, NAMED CASE, NOT A MISSING ONE. See
`TrustedLog.read_as`.

Stdlib only (`socket`, `socketserver`, `json`, `threading`, `fcntl`), per
AGENTS.md. `fcntl.flock` is POSIX/Linux-only, matching this module's own
AF_UNIX dependency - neither works on a platform this backend does not
target anyway.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import socket
import socketserver
import stat
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

#: What a caller may conclude from a channel's finalized log, and what it
#: may not - decision 2 from #183's body, settled in the design doc's §2d.
#: Never read as "the subject invoked a tool this many times"; only as "the
#: controller received this many well-formed requests on this attempt's
#: socket, and decided as follows for each, before any reply was sent."
READ_AS_NOTE = (
    "This log records requests the controller RECEIVED and decisions it "
    "MADE, each logged before its reply - never tool invocations, and "
    "never a claim that no bypass occurred (see 'no-controller-witness')."
)


class ChannelRefusal(Exception):
    """Raised by a caller-supplied `decide` function to refuse a request as
    malformed or out of scope for this channel instance - mapped to
    `{"ok": false, "error": str(exc)}`, never logged as a decision (a
    refusal is not a decision; see the module docstring's ordering rule).
    Any OTHER exception from `decide` is a bug in the caller's decision
    function, not a protocol-level refusal, and is left to propagate."""


@dataclass(frozen=True)
class LoggedDecision:
    """One entry in a channel's finalized log - immutable once appended,
    matching `DisruptionTrigger`'s own append-only discipline. `seq` is
    this channel's own counter (see the module docstring), never anything
    read from the request. `logged_at` is `time.time()` at the moment this
    entry was appended - strictly BEFORE the reply for the same request was
    sent (the module's whole ordering guarantee); a reader cannot use
    `logged_at` to infer anything about when the REQUEST arrived, only
    about when the DECISION became durable."""

    seq: int
    request: Mapping[str, object]
    result: Mapping[str, object]
    logged_at: float


DecideFn = Callable[[Mapping[str, object]], Mapping[str, object]]


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        channel: DecideReplyChannel = self.server.channel  # type: ignore[attr-defined]
        if not channel._handler_started():
            # Over capacity (`max_concurrent_handlers`) - refused before
            # reading a single byte, never queued behind existing
            # handlers, and never counted as admitted - `_handler_finished()`
            # below is skipped for exactly this reason. No reply is sent: a
            # caller reading an abrupt close as "malformed"/refused either
            # way is the same observable outcome as every other refusal
            # path here.
            return
        try:
            self._handle_admitted(channel)
        finally:
            channel._handler_finished()

    def _handle_admitted(self, channel: DecideReplyChannel) -> None:
        self.request.settimeout(channel._request_timeout)
        chunks: list[bytes] = []
        total = 0
        try:
            while True:
                chunk = self.request.recv(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > channel._max_request_bytes:
                    # Closes without a reply, same reasoning as the
                    # over-capacity case: an unbounded line is refused,
                    # never buffered further to find out how long it
                    # actually is.
                    return
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
        except OSError:
            return  # a read deadline or a reset connection - refused, not a crash
        line = b"".join(chunks).split(b"\n", 1)[0]
        try:
            request = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._reply_refused("malformed request")
            return
        if not isinstance(request, dict):
            self._reply_refused("malformed request")
            return
        try:
            result = channel._decide_and_log(request)
        except ChannelRefusal as exc:
            self._reply_refused(str(exc))
            return
        try:
            self.request.sendall(json.dumps({"ok": True, "result": result}).encode("utf-8") + b"\n")
        except OSError:
            pass  # the client disconnected before reading the reply - nothing more to do

    def _reply_refused(self, error: str) -> None:
        try:
            self.request.sendall(json.dumps({"ok": False, "error": error}).encode("utf-8") + b"\n")
        except OSError:
            pass  # same reasoning as the success path above


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True
    #: stdlib's default (5) is sized for a slow, occasional caller - a
    #: subject's tool wrapper can plausibly fire several requests in a
    #: tight burst, and a backlog this small turns a legitimate burst into
    #: `ECONNREFUSED`/`EAGAIN` on the caller's own `connect()`, which would
    #: read as a spurious bypass (`no-controller-witness`) rather than
    #: what it actually was: this channel refusing a connection it was
    #: never asked to accept. Found by this module's own concurrency test.
    request_queue_size = 128
    channel: DecideReplyChannel


class DecideReplyChannel:
    """Owns one Unix domain socket for one attempt, for this channel's whole
    lifetime: `start()` once, then `stop_and_finalize()` once, around the
    `ExecutionBackend.execute()` call whose container has this channel's
    socket bind-mounted in. Usage:

        channel = DecideReplyChannel(socket_path, decide=my_decide_fn)
        channel.start()
        result = backend.execute(handle, argv, limits)  # runs concurrently
        log = channel.stop_and_finalize()

    `decide` is called with exactly the parsed request dict (including
    `op`) and must return the `result` mapping to reply with, or raise
    `ChannelRefusal` to refuse the request. It is called on the server's
    own worker thread, one at a time per connection but POSSIBLY
    concurrently across connections (`socketserver.ThreadingUnixStreamServer`)
    - `decide` must be safe to call from multiple threads, or must do its
    own locking; this class's own log append is already locked (below),
    independent of whatever `decide` itself does."""

    def __init__(
        self, socket_path: Path, decide: DecideFn, attempt_id: str, *,
        socket_mode: int = 0o600, handler_drain_timeout: float = 5.0,
        max_concurrent_handlers: int = 32, max_request_bytes: int = 64 * 1024,
        request_timeout: float = 5.0,
    ) -> None:
        self._socket_path = socket_path
        self._decide = decide
        #: Carried into `TrustedLog.witnessed()` by this channel's own
        #: `trusted_log()` below, never re-supplied by a caller - this
        #: channel is constructed per attempt (module docstring, "ONE
        #: SOCKET, ONE DECISION FUNCTION, ONE ATTEMPT"), so it already
        #: knows the one value a caller-side wrapper would otherwise have
        #: to assert separately and could get wrong.
        self.attempt_id = attempt_id
        self._socket_mode = socket_mode
        self._handler_drain_timeout = handler_drain_timeout
        #: Cross-model review finding: the subject's
        #: own resource limits (`--pids-limit`, `--memory`, ...) bound ITS
        #: side of this socket, never the CONTROLLER's. These three bound
        #: what a connecting subject can cost THIS process - concurrent
        #: handler threads, buffered bytes per connection before a
        #: newline, and how long one connection may sit idle before this
        #: channel gives up on it - independent of anything Docker already
        #: enforces on the container.
        self._max_concurrent_handlers = max_concurrent_handlers
        self._max_request_bytes = max_request_bytes
        self._request_timeout = request_timeout
        self._lock = threading.Lock()
        self._log: list[LoggedDecision] = []
        self._next_seq = 1
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._finalized = False
        #: Counts handler threads currently inside `_Handler.handle()` -
        #: `stop_and_finalize()` drains this to zero (bounded by
        #: `handler_drain_timeout`) before snapshotting the log, because
        #: `ThreadingUnixStreamServer.server_close()` does not wait for
        #: in-flight handlers on its own: this class sets `daemon_threads =
        #: True` on `_Server` (so a stuck handler cannot hang interpreter
        #: exit), and `socketserver`'s own join-on-close explicitly skips
        #: daemon threads (`_Threads.append`, stdlib). Without this, a
        #: handler still inside `decide()` when `stop_and_finalize()` is
        #: called could append a decision AFTER the "finalized" log was
        #: already returned once - found by cross-model review, not reasoned out in advance.
        self._active_handlers = 0
        self._handlers_idle = threading.Condition(self._lock)

    def start(self) -> None:
        """Binds and starts listening. Raises `OSError` if the socket path's
        parent directory does not exist or the bind itself fails - this
        channel never silently falls back to not listening at all, which
        would turn every request into an unexplained bypass.

        Checks the path length FIRST, against a safety margin below the
        kernel's own `sizeof(sun_path)` bind (108 bytes on Linux, including
        the terminator) - found running this module's own caller
        (`docker_backend.py`'s trigger-socket integration test): a
        `base_dir`-derived path routinely overflows this on its own, before
        any attempt-specific suffix, and the kernel's own `OSError: AF_UNIX
        path too long` names neither the limit nor the path, which reads as
        a mysterious bind failure rather than what it actually is. Raising
        early, by name, here - once, for every caller of this class -
        beats every caller discovering the same kernel limit on its own."""
        if self._started:
            raise RuntimeError("this channel has already been started")
        encoded_len = len(os.fsencode(str(self._socket_path)))
        if encoded_len > 100:
            raise OSError(
                f"socket path {len(str(self._socket_path))} chars "
                f"({encoded_len} bytes encoded) exceeds this channel's 100-byte safety margin "
                f"below AF_UNIX's sun_path limit (108 bytes on Linux, including the "
                f"terminator): {self._socket_path}"
            )
        lock_path = self._socket_path.with_name(self._socket_path.name + ".lock")
        lock_file = open(lock_path, "wb")  # noqa: SIM115 - held deliberately past this block, see below
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            raise OSError(
                f"refusing to bind {self._socket_path}: another channel is already working on "
                f"this exact path (two attempts hashed to the same path, racing to start)"
            ) from None
        try:
            # EVERYTHING that decides whether this path is safe to bind,
            # AND the bind-and-listen itself, happens while this lock is
            # held (cross-model review finding): a
            # probe-then-unlink-then-bind sequence with no lock has a real
            # window between another channel's `bind()` and its `listen()`
            # during which a socket exists but nothing is accepting yet -
            # `connect()` fails with the SAME `ConnectionRefusedError` a
            # genuine dead orphan produces, so a probe racing that window
            # would misread a channel that is MID-START as stale and
            # unlink the path out from under it. Serializing the whole
            # decide-then-act sequence per path removes the window rather
            # than trying to narrow it.
            self._clear_stale_path()
            server = _Server(str(self._socket_path), _Handler)  # binds AND listens; self-cleans on failure
            server.channel = self
            try:
                os.chmod(self._socket_path, self._socket_mode)
            except OSError:
                # `_Server.__init__` already self-closes on a bind/listen
                # failure (stdlib `TCPServer.__init__`'s own try/except),
                # but a chmod failure happens AFTER that succeeds, with
                # nothing else closing the now-live listener - found by
                # cross-model review.
                server.server_close()
                raise
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
        self._started = True
        self._server = server
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05),
                                   daemon=True, name="decide-reply-channel")
        thread.start()
        self._thread = thread

    def _clear_stale_path(self) -> None:
        """Decides whether whatever already sits at `self._socket_path` is
        safe to replace - design doc §2f, decision 4 (two attempts racing
        for the same path: REFUSED, never silently shared).

        Nothing there: nothing to do. A SOCKET with nothing answering on it
        is a stale orphan (a prior attempt's listener that exited without
        unlinking - `stop_and_finalize()` unlinks on a clean exit, but a
        killed process cannot) and is safely removed before this call binds
        its own listener over the same path. A SOCKET with something
        actively accepting the connection means another live channel
        already owns this path - refused outright, never adopted and never
        silently shared; the two channels would otherwise interleave
        requests on one log with no way to attribute either to its own
        attempt. Anything OTHER than a socket (a regular file, a directory)
        at this exact path is refused too - this channel creates nothing
        but sockets here, so anything else is either a different caller's
        mistake or an adversarial pre-creation, and guessing which is not
        this method's job."""
        if not self._socket_path.exists():
            return
        if not stat.S_ISSOCK(self._socket_path.stat().st_mode):
            raise OSError(f"refusing to replace a non-socket at {self._socket_path}")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect(str(self._socket_path))
        except ConnectionRefusedError:
            self._socket_path.unlink()  # stale orphan - nothing was listening
        else:
            raise OSError(
                f"refusing to bind {self._socket_path}: another channel is already "
                f"listening on it (two attempts hashed to the same path)"
            )
        finally:
            probe.close()

    def _handler_started(self) -> bool:
        """Admits a new handler unless `max_concurrent_handlers` is already
        reached - cross-model review finding: an
        unbounded thread-per-connection accept had no cap at all, so a
        subject opening many connections (or just many slow ones) could
        exhaust controller-side threads regardless of the CONTAINER's own
        resource limits, which bound the subject's side, never this
        process's. Returns `False` without incrementing anything - a
        caller that is refused admission must not later call
        `_handler_finished()` for it, or the count would go negative."""
        with self._lock:
            if self._active_handlers >= self._max_concurrent_handlers:
                return False
            self._active_handlers += 1
            return True

    def _handler_finished(self) -> None:
        with self._handlers_idle:
            self._active_handlers -= 1
            if self._active_handlers == 0:
                self._handlers_idle.notify_all()

    def _decide_and_log(self, request: Mapping[str, object]) -> Mapping[str, object]:
        result = self._decide(request)  # may raise ChannelRefusal - never logged, see docstring
        with self._lock:
            seq = self._next_seq
            self._next_seq += 1
            # Deep-copied, not stored by reference (cross-model review
            # finding): `LoggedDecision` is frozen only at
            # the dataclass's own attribute level - a caller-supplied
            # `decide` that returns the SAME mutable dict across calls (or
            # a consumer mutating a dict retrieved from the log) would
            # otherwise rewrite an entry already presented as finalized.
            # `request` is freshly parsed per call in THIS module's own
            # handler and never reused, but copying it too costs nothing
            # and does not depend on staying true forever.
            self._log.append(LoggedDecision(
                seq=seq, request=copy.deepcopy(request), result=copy.deepcopy(result), logged_at=time.time(),
            ))
        return result

    def stop_and_finalize(self) -> list[LoggedDecision]:
        """Stops listening and returns the finalized, ordered log. Safe to
        call only once `execute()`/`confirm_stopped()` has returned for the
        attempt this channel's socket was mounted into - matching
        `DisruptionTrigger.stop_and_finalize()`'s own single-call
        discipline. An empty list is a real, meaningful result: the subject
        never connected at all (see `TrustedLog.read_as`'s
        `no-controller-witness` case) - never treated as an error here.

        Waits (bounded by `handler_drain_timeout`) for every handler thread
        already inside `handle()` to finish BEFORE snapshotting the log -
        `shutdown()` only stops ACCEPTING new connections, it says nothing
        about ones already in flight, and this class's own `daemon_threads
        = True` means `server_close()` will not wait for them either (see
        `_active_handlers`'s own comment). Raises `RuntimeError` rather than
        returning a log that might still grow if the drain times out - a
        silently short snapshot would read as complete when it is not."""
        if not self._started:
            raise RuntimeError("stop_and_finalize() called before start()")
        if self._finalized:
            raise RuntimeError("this channel has already been finalized")
        self._finalized = True
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join()
        with self._handlers_idle:
            drained = self._handlers_idle.wait_for(
                lambda: self._active_handlers == 0, timeout=self._handler_drain_timeout,
            )
        if not drained:
            raise RuntimeError(
                f"stop_and_finalize(): {self._active_handlers} handler(s) still running past "
                f"handler_drain_timeout={self._handler_drain_timeout}s - the log cannot be "
                f"trusted as finalized while a decision may still be appended to it"
            )
        try:
            self._socket_path.unlink()
        except OSError:
            pass
        with self._lock:
            return list(self._log)

    def log_or_finalize(self) -> list[LoggedDecision]:
        """Idempotent variant of `stop_and_finalize()`, for a caller that
        may need the log from more than one path - the documented
        confirm-then-finalize call, and a defensive teardown (e.g.
        `DockerBackend.destroy()`) that must not crash if the first already
        ran. Returns the same finalized log on every call after the first,
        rather than raising. Still raises if called before `start()` - that
        remains a real misuse, not a case this method papers over."""
        if self._finalized:
            with self._lock:
                return list(self._log)
        return self.stop_and_finalize()

    def trusted_log(self) -> TrustedLog:
        """`log_or_finalize()`'s result, already wrapped as this channel's
        own `TrustedLog` - the convenience a caller should prefer over
        calling `TrustedLog.witnessed()` itself, since this channel is the
        one thing that actually knows its own `attempt_id` (see
        `__init__`'s own comment); a caller-side wrapper asserting that
        value separately is exactly the forgeable extra claim #183's
        provenance review rejected. `channel-unavailable` (this backend
        never configured a channel at all) is a DIFFERENT caller's fact -
        `DockerBackend.trigger_log()` returning `None` - and is reported by
        that caller, not by this method, which only runs once a channel
        genuinely exists."""
        return TrustedLog.witnessed(self.log_or_finalize(), self.attempt_id)

    def close(self) -> None:
        """Best-effort, idempotent teardown - safe before `start()` (no-op)
        and safe after `stop_and_finalize()` (no-op). For a caller that
        needs to guarantee the listening thread is gone without caring
        about the log itself (`DockerBackend.prepare()`'s own failure
        path, `destroy()`'s best-effort contract)."""
        if not self._started or self._finalized:
            return
        self.stop_and_finalize()


@dataclass(frozen=True)
class TrustedLog:
    """The three-way read of one channel's finalized log (design doc §2d,
    generalized in §2e for #269's own reuse) - never a caller-supplied
    `bool`, for the same reason `backend.Confirmation` is a three-valued
    enum and not one: a bypass must never collapse into a guessed
    `NOT_CONFIRMED` (matching #268's own framing - a bypass does not
    positively establish non-execution, it only establishes that nothing
    was reported)."""

    status: str  # "witnessed" | "no-controller-witness" | "channel-unavailable"
    #: Which attempt this log belongs to - REQUIRED, never optional,
    #: because a caller that must bind a trusted observation to the
    #: specific attempt it is grading (#183's provenance review,
    #: evals/level5's own `grade_recovery.py`) needs this value from the
    #: channel itself, not from a second, separately-asserted claim it
    #: could get wrong or that a forger could fabricate to match.
    attempt_id: str
    decisions: tuple[LoggedDecision, ...] = ()

    #: Read as a class attribute so callers (and this module's own tests)
    #: can cite the exact rule without re-deriving it from prose.
    read_as: str = field(default=READ_AS_NOTE, repr=False, compare=False)

    @classmethod
    def witnessed(cls, decisions: list[LoggedDecision], attempt_id: str) -> TrustedLog:
        if not decisions:
            return cls(status="no-controller-witness", attempt_id=attempt_id)
        return cls(status="witnessed", attempt_id=attempt_id, decisions=tuple(decisions))

    @classmethod
    def unavailable(cls, attempt_id: str) -> TrustedLog:
        return cls(status="channel-unavailable", attempt_id=attempt_id)

    def to_json_bytes(self) -> bytes:
        """A retainable, exportable form - the `raw` data a caller may cite
        by `{ref, digest}` per `docs/specs/evaluation-facility/records.md`'s
        existing convention for backend raw data (design doc §2e). Shape is
        deliberately generic (status plus a decisions list), not Level 5's
        specific `trusted-disruption-log.json` schema - adapting this into
        that shape is a caller's job (#183's own PR C), not this module's.
        `decisions` is written in `seq` order explicitly (never merely "the
        order this tuple happens to hold," even though construction already
        preserves it) so a reader never has to trust that ordering came
        from this method rather than from whatever handed it the tuple -
        the bytes are self-consistent on their own."""
        return json.dumps({
            "status": self.status,
            "attempt_id": self.attempt_id,
            "read_as": self.read_as,
            "decisions": [
                {"seq": d.seq, "request": d.request, "result": d.result, "logged_at": d.logged_at}
                for d in sorted(self.decisions, key=lambda d: d.seq)
            ],
        }).encode("utf-8")
