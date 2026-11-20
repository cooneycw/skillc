"""The controller-side task-protocol receiver (#620 PR-B, B5a).

See `docs/specs/evaluation-facility/task-protocol-stream.md`, sections 1 to 3.
This joins the slices: one Unix socket listener per endpoint lease (B4), the
kernel peer check, the closed schema (B1), the decision state machine (B3) and
the journal (B2), in one fixed order per request.

1. The kernel's `SO_PEERCRED` pid, uid and gid are read before any byte. A
   `PeerVerifier` maps them to the runtime instance the peer actually lives in.
   B5b supplies the Docker implementation, using the PID namespace or cgroup
   membership. A failing or unknown probe is no instance.
2. The principal is the one whose ACTIVE, bound lease is THIS endpoint AND whose
   recorded runtime instance is the observed one (`Leases.principal_for`).
   Nothing in the request can name a principal. Without one, the request is
   journaled as `unauthenticated-peer` against nobody, so it can never make the
   endpoint's owner, or any other role, fail. The endpoint's coverage becomes
   UNKNOWN.
3. Under ONE receiver lock: parse, propose, record, commit. `Journal.transact`
   records the decision at the same elapsed reading the state machine
   used, fsynced before it returns. `Machine.commit` runs only after that.
4. Only then is the receipt sent. If the journal fails, nothing is sent: a lost
   reply is UNKNOWN, never an invented decision. If the journal is full, the
   receiver records the capacity event from the closure reserve and replies
   `capacity`. Either way, coverage becomes UNKNOWN.

Finishing is the controller's job, in this order:

1. `fence()` stops admitting decisions;
2. `stop()` closes every listener and drains in-flight handlers;
3. `seal()` writes the journal's seal with the coverage this receiver observed.

A handler that cannot be drained leaves every principal UNKNOWN.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import hashlib
import os
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .decide_reply_channel import peer_credentials
from .task_protocol_journal import CapacityExceeded, Journal, JournalUnavailable, Reference
from .task_protocol_lease import Lease, Leases
from .task_protocol_schema import MAX_REQUEST_BYTES, Receipt, Rejected, Request, parse_request
from .task_protocol_state import Machine

#: After replying, the receiver reads the rest of an over-long request before
#: closing, so the kernel delivers the reply instead of resetting the
#: connection. Bounded in bytes (here) and time (`request_timeout`); a sender
#: that exceeds either is an I/O-limit outcome: coverage UNKNOWN, never a hang.
DRAIN_LIMIT = 64 * 1024


class PeerVerifier(Protocol):
    """Maps a connected peer's kernel credentials to its runtime instance, or
    None when that cannot be established. Never reads the request."""

    def runtime_instance(self, pid: int, uid: int, gid: int) -> str | None: ...


class ReceiverError(RuntimeError):
    """A controller lifecycle error (serve after stop, seal before fence)."""


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw[:MAX_REQUEST_BYTES]).hexdigest()


class Receiver:
    def __init__(self, leases: Leases, machine: Machine, journal: Journal,
                 verifier: PeerVerifier, *, request_timeout: float = 5.0,
                 max_handlers: int = 64, drain_timeout: float = 10.0) -> None:
        self.leases, self.machine, self.journal, self.verifier = leases, machine, journal, verifier
        self.request_timeout, self.max_handlers = request_timeout, max_handlers
        self.drain_timeout = drain_timeout
        self.lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._owners: dict[str, str] = {}
        self._listeners: list[socket.socket] = []
        self._threads: list[threading.Thread] = []
        self._handlers: set[threading.Thread] = set()
        self._unknown: set[str] = set()
        self._stopping = threading.Event()
        self._stopped = False

    # -- lifecycle -------------------------------------------------------------

    def serve(self, lease: Lease, path: Path, mode: int = 0o666) -> None:
        """Listen for one lease's endpoint at `path`. The caller owns the
        directory, which is mounted read-only into that lease's sandbox only."""
        if self._stopping.is_set():
            raise ReceiverError("receiver stopped")
        if lease.endpoint_id in self._owners:
            raise ReceiverError("endpoint already served")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(path))
            os.chmod(path, mode)
            listener.listen(128)
            listener.settimeout(0.2)
        except BaseException:
            listener.close()
            raise
        self._owners[lease.endpoint_id] = lease.principal
        self._listeners.append(listener)
        thread = threading.Thread(target=self._accept, args=(listener, lease.endpoint_id),
                                  daemon=True)
        self._threads.append(thread)
        thread.start()

    def fence(self, reason: str = "closure") -> None:
        with self.lock:
            if not self.journal.fenced:
                self.journal.append("fence", reason=reason)

    def stop(self) -> bool:
        """Close every listener and drain handlers. False (and every principal
        UNKNOWN) when a handler could not be drained in time."""
        self._stopping.set()
        for listener in self._listeners:
            listener.close()
        for thread in self._threads:
            thread.join(self.drain_timeout)
        with self._state_lock:
            handlers = list(self._handlers)
        for handler in handlers:
            handler.join(self.drain_timeout)
        drained = not any(t.is_alive() for t in self._threads + handlers)
        if not drained:
            with self._state_lock:
                self._unknown.update(self.leases.inventory.principals)
        self._stopped = True
        return drained

    def coverage(self) -> dict[str, str]:
        with self._state_lock:
            return {p: ("unknown" if p in self._unknown else "complete")
                    for p in self.leases.inventory.principals}

    def seal(self) -> Reference:
        if not self._stopped or not self.journal.fenced:
            raise ReceiverError("seal requires fence then stop")
        return self.journal.seal(self.coverage())

    # -- ingress -----------------------------------------------------------------

    def _mark_unknown(self, principal: str | None) -> None:
        with self._state_lock:
            if principal is None:
                self._unknown.update(self.leases.inventory.principals)
            else:
                self._unknown.add(principal)

    def _accept(self, listener: socket.socket, endpoint: str) -> None:
        while not self._stopping.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with self._state_lock:
                full = len(self._handlers) >= self.max_handlers
            if full:
                conn.close()
                self._mark_unknown(self._owners[endpoint])
                continue
            handler = threading.Thread(target=self._handle, args=(conn, endpoint), daemon=True)
            with self._state_lock:
                self._handlers.add(handler)
            handler.start()

    def _peer(self, conn: socket.socket, endpoint: str) -> str | None:
        """The observed runtime instance of the connected peer. `endpoint`
        is unused here on purpose: the kernel, not the socket it reached,
        says who the peer is."""
        try:
            pid, uid, gid = peer_credentials(conn)
            instance = self.verifier.runtime_instance(pid, uid, gid)
        except Exception:  # noqa: BLE001 - an unavailable peer probe is no identity
            return None
        return instance if isinstance(instance, str) and instance else None

    def _read(self, conn: socket.socket) -> bytes | None:
        chunks: list[bytes] = []
        total = 0
        try:
            while total <= MAX_REQUEST_BYTES:
                chunk = conn.recv(MAX_REQUEST_BYTES + 1)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if b"\n" in chunk:
                    break
        except OSError:
            return None
        return b"".join(chunks)

    def _handle(self, conn: socket.socket, endpoint: str) -> None:
        try:
            with conn:
                conn.settimeout(self.request_timeout)
                instance = self._peer(conn, endpoint)
                raw = self._read(conn)
                if raw is None:
                    self._mark_unknown(self._owners[endpoint])
                    return
                receipt = self._decide(endpoint, instance, raw)
                if receipt is None:
                    return
                try:
                    conn.sendall(receipt.encode())
                except OSError:
                    self._mark_unknown(self._owners[endpoint])
                    return
                if not self._drain(conn):
                    self._mark_unknown(self._owners[endpoint])
        finally:
            with self._state_lock:
                self._handlers.discard(threading.current_thread())

    @staticmethod
    def _drain(conn: socket.socket) -> bool:
        """Half-close, then read to EOF within DRAIN_LIMIT and the socket's
        timeout. Closing with unread bytes would make the kernel reset the
        connection and discard the reply just sent. False when the bound is
        hit or the read fails."""
        try:
            conn.shutdown(socket.SHUT_WR)
            drained = 0
            while drained <= DRAIN_LIMIT:
                chunk = conn.recv(65536)
                if not chunk:
                    return True
                drained += len(chunk)
        except OSError:
            return False
        return False

    def _decide(self, endpoint: str, instance: str | None, raw: bytes) -> Receipt | None:
        with self.lock:
            principal = (self.leases.principal_for(endpoint, instance)
                         if instance is not None else None)
            if principal is None:
                return self._unauthenticated(endpoint, raw)
            parsed = parse_request(raw)
            number = parsed.request if isinstance(parsed, Request) else None
            try:
                seq, _, proposal = self.journal.transact(self._proposer(principal, parsed))
            except CapacityExceeded as exc:
                self.machine.discard()
                self._mark_unknown(principal)
                return self._capacity(principal, str(exc), number)
            except Exception:  # noqa: BLE001 - no durable decision means no receipt
                self.machine.discard()
                self._mark_unknown(None)
                return None
            self.machine.commit(proposal, seq)
            receipt: Receipt = proposal.receipt
            return receipt

    def _proposer(self, principal: str, parsed: Request | Rejected
                  ) -> Callable[[int, bool], tuple[str, dict[str, Any], Any]]:
        def decide(elapsed: int, fenced: bool) -> tuple[str, dict[str, Any], Any]:
            proposal = self.machine.propose(principal, parsed, elapsed, fenced=fenced)
            return proposal.kind, proposal.fields, proposal
        return decide

    def _unauthenticated(self, endpoint: str, raw: bytes) -> Receipt | None:
        self._mark_unknown(self._owners[endpoint])
        try:
            self.journal.append("rejection", principal=None, reason="unauthenticated-peer",
                                length=len(raw), content_digest=_digest(raw))
        except CapacityExceeded as exc:
            return self._capacity(None, str(exc), None)
        except Exception:  # noqa: BLE001 - nothing durable, so nothing is said
            self._mark_unknown(None)
            return None
        return Receipt(None, "rejected", None, "unauthenticated-peer")

    def _capacity(self, principal: str | None, scope: str, number: int | None) -> Receipt | None:
        try:
            self.journal.append("capacity", principal=principal, scope=scope)
        except (JournalUnavailable, OSError):
            self._mark_unknown(None)
            return None
        return Receipt(number, "rejected", None, "capacity")
