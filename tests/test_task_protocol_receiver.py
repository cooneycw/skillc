"""The #620 PR-B receiver (skillc/task_protocol_receiver.py, B5a), end to end
over real Unix sockets with a fake peer verifier. Physical peer and mount
facts are B0's and B5b's; here the verifier is the seam."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import shutil
import socket
import tempfile
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from skillc import task_protocol_client as client
from skillc import task_protocol_journal as tj
from skillc.task_protocol_lease import Inventory, Leases, Slot
from skillc.task_protocol_receiver import Receiver, ReceiverError
from skillc.task_protocol_state import Machine, Offer, Plan

E = "sha256:" + "e" * 64


class FakeVerifier:
    """Answers with whichever runtime instance the test says the peer is in."""

    def __init__(self) -> None:
        self.current: str | None = "inst-a"
        self.fail = False

    def runtime_instance(self, pid: int, uid: int, gid: int) -> str | None:
        assert pid == os.getpid()
        if self.fail:
            raise OSError("modeled unavailable probe")
        return self.current


@dataclass
class World:
    root: Path
    sockets: Path
    receiver: Receiver
    journal: tj.Journal
    context: tj.Context
    leases: Leases
    verifier: FakeVerifier
    paths: dict[str, str] = field(default_factory=dict)

    def call(self, principal: str, op: str, request: int, offer: str | None = None,
             reason: str | None = None) -> dict[str, Any] | None:
        self.verifier.current = "inst-a" if principal == "p-a" else "inst-b"
        return client.call(client.request_fields(op, request, offer, reason),
                           self.paths[principal], timeout=10)

    def raw(self, endpoint: str, payload: bytes) -> bytes:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(10)
            conn.connect(self.paths[endpoint])
            conn.sendall(payload)
            conn.shutdown(socket.SHUT_WR)
            data = b""
            while chunk := conn.recv(8192):
                data += chunk
            return data

    def finish(self) -> dict[str, Any]:
        self.receiver.fence()
        assert self.receiver.stop()
        reference = self.receiver.seal()
        return tj.verify(self.root / "journal", reference, self.context)


def _counter() -> Callable[[], str]:
    count = itertools.count(1)
    return lambda: f"ep-{next(count)}"


def _ticks(step: int = 10) -> Callable[[], int]:
    values: Iterator[int] = itertools.count(0, step)
    return lambda: next(values)


@pytest.fixture
def make_world(tmp_path: Path) -> Iterator[Callable[..., World]]:
    worlds: list[World] = []
    short = Path(tempfile.mkdtemp(prefix="tp-", dir="/tmp"))

    def build(*, deadline: int = 1 << 62, limits: dict[str, int] | None = None,
              fs: Any = None, barrier: bool = True,
              receiver_type: type[Receiver] = Receiver, **receiver_kwargs: Any) -> World:
        index = len(worlds)
        inventory = Inventory("attempt-1", "sha256:" + "a" * 64,
                              (Slot("p-a", "worker-a", "task-a", 0, 1, "n-a"),
                               Slot("p-b", "worker-b", "task-b", 0, 1, "n-b")), 0)
        leases = Leases(inventory, token=_counter())
        lease_a, lease_b = leases.issue("p-a"), leases.issue("p-b")
        records = [leases.bind("p-a", runtime_instance="inst-a", session_id="sess-a",
                               evidence_digest=E),
                   leases.bind("p-b", runtime_instance="inst-b", session_id="sess-b",
                               evidence_digest=E)]
        context = tj.Context("attempt-1", "sha256:" + "a" * 64, inventory.digest,
                             "sha256:" + "c" * 64, "skillc-test", inventory.principals,
                             limits=limits or dict(tj.DEFAULT_LIMITS))
        root = tmp_path / f"world-{index}"
        root.mkdir()
        journal = tj.Journal(root / "journal", context, 0, clock_ns=_ticks(), fs=fs)
        for record in records:
            journal.append("binding", **record)
        if barrier:
            journal.append("barrier", **leases.barrier())
        machine = Machine(Plan((Offer("p-a", "o-a"), Offer("p-b", "o-b")), deadline))
        verifier = FakeVerifier()
        receiver = receiver_type(leases, machine, journal, verifier, **receiver_kwargs)
        sockets = short / f"w{index}"
        sockets.mkdir()
        world = World(root, sockets, receiver, journal, context, leases, verifier)
        for name, lease in (("p-a", lease_a), ("p-b", lease_b)):
            path = sockets / f"{name}.sock"
            receiver.serve(lease, path)
            world.paths[name] = str(path)
        worlds.append(world)
        return world

    yield build
    for world in worlds:
        world.receiver.stop()
    shutil.rmtree(short, ignore_errors=True)


def _decision(receipt: dict[str, Any] | None) -> tuple[str, str | None] | None:
    return None if receipt is None else (receipt["decision"], receipt.get("reason"))


def _rows(result: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [r for r in result["records"] if r["kind"] == kind]


def test_a_healthy_wave_is_recorded_and_sealed_closed(make_world: Callable[..., World]) -> None:
    world = make_world()
    for principal, offer in (("p-a", "o-a"), ("p-b", "o-b")):
        assert _decision(world.call(principal, "offer", 1)) == ("offered", None)
        assert world.call(principal, "offer", 1) == world.call(principal, "offer", 1)
        assert _decision(world.call(principal, "ack", 2, offer)) == ("acknowledged", None)
        assert _decision(world.call(principal, "complete", 3, offer)) == (
            "completion-claimed", None)
    result = world.finish()
    assert result["status"] == "CAPTURED" and result["outcome"] == "CLOSED"
    decisions = _rows(result, "decision")
    assert [(d["principal"], d["decision"]) for d in decisions] == [
        ("p-a", "offered"), ("p-a", "acknowledged"), ("p-a", "completion-claimed"),
        ("p-b", "offered"), ("p-b", "acknowledged"), ("p-b", "completion-claimed")]
    assert len(_rows(result, "retry")) == 4


def test_a_request_from_another_sandbox_is_unauthenticated_and_blames_nobody(
        make_world: Callable[..., World]) -> None:
    world = make_world()
    world.verifier.current = "inst-b"
    receipt = client.call(client.request_fields("offer", 1), world.paths["p-a"])
    assert _decision(receipt) == ("rejected", "unauthenticated-peer")
    result = world.finish()
    rejection = _rows(result, "rejection")
    assert [(r["principal"], r["reason"]) for r in rejection] == [
        (None, "unauthenticated-peer")]
    assert not _rows(result, "decision")
    assert result["coverage"] == {"p-a": "unknown", "p-b": "complete"}
    assert result["outcome"] == "UNKNOWN"


@pytest.mark.parametrize("setup", ["probe-fails", "probe-unknown", "revoked", "no-barrier"])
def test_unestablished_identity_is_unauthenticated(make_world: Callable[..., World],
                                                   setup: str) -> None:
    world = make_world(barrier=setup != "no-barrier")
    if setup == "probe-fails":
        world.verifier.fail = True
    if setup == "revoked":
        world.journal.append("revocation", **world.leases.revoke("p-a", "closed"))
    if setup == "probe-unknown":
        world.verifier.current = None
        receipt = client.call(client.request_fields("offer", 1), world.paths["p-a"])
    else:
        receipt = world.call("p-a", "offer", 1)
    assert _decision(receipt) == ("rejected", "unauthenticated-peer")


def test_identity_in_the_payload_is_rejected_and_never_echoed(
        make_world: Callable[..., World]) -> None:
    world = make_world()
    world.verifier.current = "inst-a"
    canary = "CANARY-role-b-claim"
    reply = world.raw("p-a", json.dumps({"version": 1, "op": "ack", "request": 1,
                                         "offer_id": "o-a", "role": canary}).encode() + b"\n")
    assert canary.encode() not in reply
    assert _decision(client.parse_receipt(reply)) == ("rejected", "identity-field-supplied")
    world.receiver.fence()
    world.receiver.stop()
    reference = world.receiver.seal()
    stored = (world.root / "journal" / "objects" / reference.digest[7:]).read_bytes()
    assert canary.encode() not in stored


def test_an_oversize_request_is_rejected_by_size(make_world: Callable[..., World]) -> None:
    world = make_world()
    world.verifier.current = "inst-a"
    reply = world.raw("p-a", b'{"version":1,"op":"offer","request":1,"x":"' + b"y" * 5000 + b'"}\n')
    assert _decision(client.parse_receipt(reply)) == ("rejected", "oversize")


def test_lateness_uses_the_recorded_elapsed_time(make_world: Callable[..., World]) -> None:
    world = make_world(deadline=0)
    assert _decision(world.call("p-a", "offer", 1)) == ("rejected", "late")
    result = world.finish()
    late = _rows(result, "decision")[0]
    assert late["reason"] == "late" and late["elapsed_ns"] > 0


def test_after_the_fence_every_request_is_fenced(make_world: Callable[..., World]) -> None:
    world = make_world()
    assert _decision(world.call("p-a", "offer", 1)) == ("offered", None)
    world.receiver.fence()
    assert _decision(world.call("p-a", "offer", 1)) == ("rejected", "fenced")
    assert _decision(world.call("p-a", "ack", 2, "o-a")) == ("rejected", "fenced")


def test_a_full_journal_replies_capacity_and_seals_unknown(
        make_world: Callable[..., World]) -> None:
    world = make_world(limits={**tj.DEFAULT_LIMITS, "decisions_per_principal": 2})
    assert _decision(world.call("p-a", "offer", 1)) == ("offered", None)
    assert _decision(world.call("p-a", "ack", 2, "o-a")) == ("acknowledged", None)
    assert _decision(world.call("p-a", "complete", 3, "o-a")) == ("rejected", "capacity")
    assert _decision(world.call("p-b", "offer", 1)) == ("offered", None)
    result = world.finish()
    assert [r["scope"] for r in _rows(result, "capacity")] == ["principal"]
    assert result["coverage"]["p-a"] == "unknown" and result["outcome"] == "UNKNOWN"


class _FailFsyncAfter:
    def __init__(self, ok: int) -> None:
        self.ok, self.count = ok, 0

    def write(self, fd: int, data: bytes) -> int:
        return os.write(fd, data)

    def fsync(self, fd: int) -> None:
        self.count += 1
        if self.count > self.ok:
            raise OSError("injected fsync failure")
        os.fsync(fd)


def test_no_receipt_is_sent_for_a_decision_that_is_not_durable(
        make_world: Callable[..., World]) -> None:
    # Start (2 fsyncs), two bindings and the barrier succeed; the first
    # decision's fsync fails.
    world = make_world(fs=_FailFsyncAfter(5))
    assert world.call("p-a", "offer", 1) is None
    assert client.main(["offer", "--request", "2"], world.paths["p-a"]) == client.EXIT_UNAVAILABLE
    assert world.receiver.coverage() == {"p-a": "unknown", "p-b": "unknown"}


def test_a_silent_connection_is_dropped_and_leaves_coverage_unknown(
        make_world: Callable[..., World]) -> None:
    # The silent peer never sends, so load can only delay the drop, never beat it.
    world = make_world(request_timeout=0.5)  # timing: must-fire - the read timeout under test
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(world.paths["p-b"])
        conn.settimeout(5)
        assert conn.recv(10) == b""
    world.receiver.fence()
    assert world.receiver.stop()
    assert world.receiver.coverage() == {"p-a": "complete", "p-b": "unknown"}


class _PeerFromEndpoint(Receiver):
    """One test process plays both sandboxes, so the peer is named from the
    endpoint it reached. Only this test may do that."""

    def _peer(self, conn: socket.socket, endpoint: str) -> str | None:
        return {"p-a": "inst-a", "p-b": "inst-b"}[self._owners[endpoint]]


def test_concurrent_requests_stay_ordered_and_sealed(make_world: Callable[..., World]) -> None:
    world = make_world(receiver_type=_PeerFromEndpoint)
    results: dict[str, list[dict[str, Any] | None]] = {}

    def run(principal: str) -> None:
        results[principal] = [client.call(client.request_fields("offer", number),
                                          world.paths[principal]) for number in range(1, 11)]

    threads = [threading.Thread(target=run, args=(p,)) for p in ("p-a", "p-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert sorted(results) == ["p-a", "p-b"]
    assert all(_decision(r) == ("offered", None) for rs in results.values() for r in rs)
    result = world.finish()
    assert result["status"] == "CAPTURED" and len(_rows(result, "decision")) == 20
    assert [r["seq"] for r in result["records"]] == list(range(2, 2 + len(result["records"])))


def test_lifecycle_errors(make_world: Callable[..., World]) -> None:
    world = make_world()
    with pytest.raises(ReceiverError):
        world.receiver.seal()
    lease = world.leases._entries["p-a"].lease
    assert lease is not None
    with pytest.raises(ReceiverError):
        world.receiver.serve(lease, world.sockets / "again.sock")
    world.receiver.fence()
    world.receiver.stop()
    with pytest.raises(ReceiverError):
        world.receiver.serve(lease, world.sockets / "late.sock")


# Blind receivers: each must disagree with the behavior above.


class _SkipsPeerCheck(Receiver):
    def _peer(self, conn: socket.socket, endpoint: str) -> str | None:
        return "inst-a"


class _RepliesWithoutCustody(Receiver):
    def _decide(self, endpoint: str, instance: str | None, raw: bytes) -> Any:
        receipt = super()._decide(endpoint, instance, raw)
        if receipt is None:
            return client_receipt_offered()
        return receipt


class _BlamesTheOwner(Receiver):
    def _unauthenticated(self, endpoint: str, raw: bytes) -> Any:
        self.journal.append("rejection", principal=self._owners[endpoint],
                            reason="unauthenticated-peer", length=len(raw),
                            content_digest="sha256:" + hashlib.sha256(raw).hexdigest())
        return super()._unauthenticated(endpoint, raw)


def client_receipt_offered() -> Any:
    from skillc.task_protocol_schema import Receipt
    return Receipt(1, "offered", "o-a")


def test_a_receiver_that_skips_the_peer_check_is_caught(
        make_world: Callable[..., World]) -> None:
    world = make_world(receiver_type=_SkipsPeerCheck)
    world.verifier.current = "inst-b"
    receipt = client.call(client.request_fields("offer", 1), world.paths["p-a"])
    assert _decision(receipt) != ("rejected", "unauthenticated-peer")


def test_a_receiver_that_replies_without_custody_is_caught(
        make_world: Callable[..., World]) -> None:
    world = make_world(fs=_FailFsyncAfter(5), receiver_type=_RepliesWithoutCustody)
    assert world.call("p-a", "offer", 1) is not None


def test_a_receiver_that_blames_the_owner_is_caught(make_world: Callable[..., World]) -> None:
    world = make_world(receiver_type=_BlamesTheOwner)
    world.verifier.current = "inst-b"
    client.call(client.request_fields("offer", 1), world.paths["p-a"])
    result = world.finish()
    assert any(r["principal"] == "p-a" for r in _rows(result, "rejection"))


def test_peer_authority_has_one_implementation() -> None:
    """The receiver must take kernel credentials from the same helper the
    decide/reply channel gate uses, never a second SO_PEERCRED reader."""
    from skillc import decide_reply_channel, task_protocol_receiver
    receiver_source = Path(task_protocol_receiver.__file__).read_text()
    channel_source = Path(decide_reply_channel.__file__).read_text()
    assert "SO_PEERCRED" not in receiver_source.replace("`SO_PEERCRED`", "")
    assert "peer_credentials(conn)" in receiver_source
    assert channel_source.count("socket.SO_PEERCRED") == 1
    assert "peer_credentials(self.request)" in channel_source


def test_a_far_oversize_sender_gets_a_bounded_outcome(make_world: Callable[..., World]) -> None:
    """Regression (B5a early VM run): the receiver used to close with unread
    request bytes, so the kernel reset the connection and the oversize reply
    was lost. A 1 MiB sender must now end within the I/O bounds, be recorded
    as oversize, and leave that endpoint's coverage UNKNOWN."""
    world = make_world(request_timeout=2.0)
    world.verifier.current = "inst-a"
    outcome: dict[str, Any] = {}

    def send() -> None:
        try:
            outcome["reply"] = world.raw("p-a", b"x" * (1 << 20))
        except OSError as exc:
            outcome["error"] = type(exc).__name__

    sender = threading.Thread(target=send)
    sender.start()
    sender.join(30)
    assert not sender.is_alive()
    result = world.finish()
    assert [(r["principal"], r["reason"]) for r in _rows(result, "rejection")] == [
        ("p-a", "oversize")]
    assert result["coverage"]["p-a"] == "unknown" and result["outcome"] == "UNKNOWN"
    if "reply" in outcome:
        assert _decision(client.parse_receipt(outcome["reply"])) == ("rejected", "oversize")


def test_a_just_oversize_request_still_receives_its_reply_and_drains_clean(
        make_world: Callable[..., World]) -> None:
    world = make_world()
    world.verifier.current = "inst-a"
    reply = world.raw("p-a", b'{"version":1,"op":"offer","request":1,"x":"' + b"y" * 5000 + b'"}\n')
    assert _decision(client.parse_receipt(reply)) == ("rejected", "oversize")
    world.receiver.fence()
    world.receiver.stop()
    assert world.receiver.coverage()["p-a"] == "complete"
