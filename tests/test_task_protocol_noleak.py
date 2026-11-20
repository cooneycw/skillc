"""No-leak controls for the task-protocol stream (#620 PR-B, B7; design s.6).

Participant-chosen bytes and controller-private identities must never reach a
receipt, the sealed journal, the adapter's output, an exception chain, the
client's diagnostics, the receiver's coverage map or an audit reason.

Every canary is generated at RUNTIME, so no secret-shaped literal is
committed, and every canary is ASSERTED PLANTED in the input actually sent
before any output is called clean: a canary that never reached the component
would make the clean result blind. The scanner has its own red, and a
deliberately leaking twin of each surface family must be caught."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import tempfile
import traceback
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
import task_protocol_fixture as tpf

from skillc import docker_backend as db
from skillc import task_protocol_adapter as adapter
from skillc import task_protocol_client as client
from skillc import task_protocol_docker as tpd
from skillc import task_protocol_journal as tj
from skillc import task_protocol_schema as schema
from skillc.task_protocol_lease import LeaseError, Leases, Slot
from skillc.task_protocol_receiver import Receiver, ReceiverError
from skillc.task_protocol_state import Machine, Offer, Plan, StateError

DECL = "sha256:" + "d" * 64
DEADLINE = "sha256:" + "ab" * 32
ROLES = ("integrator", "worker")


def canary() -> str:
    return "CANARY" + uuid.uuid4().hex


def _bytes(value: bytes | str) -> bytes:
    return value if isinstance(value, bytes) else value.encode("utf-8", "surrogateescape")


def scan(surfaces: Mapping[str, bytes | str], needles: Sequence[str]) -> list[tuple[str, str]]:
    """Every (surface, needle) where the needle's bytes occur in the surface."""
    return [(name, needle) for name, surface in surfaces.items() for needle in needles
            if needle.encode() in _bytes(surface)]


def planted(needles: Sequence[str], inputs: Sequence[bytes | str]) -> None:
    """A canary that never reached the component cannot show it is clean."""
    missing = [n for n in needles if not any(n.encode() in _bytes(i) for i in inputs)]
    assert not missing, f"canaries never planted: {missing}"


def exception_text(exc: BaseException) -> str:
    """str, repr, the full traceback text, and every __cause__/__context__."""
    parts = ["".join(traceback.format_exception(exc))]
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts += [str(current), repr(current)]
        current = current.__cause__ or current.__context__
    return "\n".join(parts)


# -- the scanner's own red ----------------------------------------------------------


def test_the_scanner_finds_a_needle_and_the_plant_check_refuses_a_missing_one() -> None:
    needle = canary()
    assert scan({"bytes": b"x" + needle.encode() + b"y", "text": "a" + needle}, [needle]) == [
        ("bytes", needle), ("text", needle)]
    assert scan({"latin": (needle + "\xff").encode("latin-1")}, [needle]) == [("latin", needle)]
    assert scan({"clean": b"nothing here"}, [needle]) == []
    with pytest.raises(AssertionError, match="never planted"):
        planted([needle], [b"no canary in this input"])
    chained: BaseException
    try:
        try:
            raise TypeError(needle)
        except TypeError as inner:
            raise ValueError("fixed text") from inner
    except ValueError as outer:
        chained = outer
    assert needle in exception_text(chained)


# -- the receiver path: S1 receipts, S2 journal, S3 adapter, S7 coverage -----------------


class _Verifier:
    def __init__(self) -> None:
        self.current: str | None = None
        self.explode: str | None = None

    def runtime_instance(self, pid: int, uid: int, gid: int) -> str | None:
        if self.explode is not None:
            raise OSError(f"probe failed for {self.explode}")
        return self.current


class _World:
    def __init__(self, root: Path, short: Path, receiver_type: type[Receiver] = Receiver) -> None:
        self.plan = tpf.plan_of(ROLES)
        self.inventory = tpf.inventory_for(self.plan, DECL)
        self.endpoints = {r: "ep" + uuid.uuid4().hex for r in ROLES}
        self.instances = {r: "inst" + uuid.uuid4().hex for r in ROLES}
        order = iter([self.endpoints[r] for r in ROLES])
        self.leases = Leases(self.inventory, token=lambda: next(order))
        self.lease_root = short / ("leases" + uuid.uuid4().hex[:12])
        self.context = tj.Context(self.plan.wave_id, DECL, self.inventory.digest, DEADLINE,
                                  "skillc-test", self.inventory.principals)
        self.journal = tj.Journal(root / "journal", self.context, 0)
        self.paths: dict[str, str] = {}
        leases = {}
        for role in ROLES:
            principal = tpf.principal_of(role)
            leases[role] = self.leases.issue(principal)
            self.journal.append("binding", **self.leases.bind(
                principal, runtime_instance=self.instances[role], session_id="session-" + role,
                evidence_digest=tpf.E))
        self.journal.append("barrier", **self.leases.barrier())
        machine = Machine(Plan(tuple(Offer(tpf.principal_of(r), tpf.offer_of(r)) for r in ROLES),
                               round(self.plan.deadline * 1e9)))
        self.verifier = _Verifier()
        self.receiver = receiver_type(self.leases, machine, self.journal, self.verifier)
        for role in ROLES:
            directory = tpd.lease_dir(self.lease_root, leases[role].endpoint_id)
            path = directory / tpd.SOCKET_NAME
            self.receiver.serve(leases[role], path)
            self.paths[role] = str(path)
        self.private = [*self.endpoints.values(), *self.instances.values(), str(self.lease_root)]

    def send(self, role: str, payload: bytes, *, as_role: str | None = None) -> bytes:
        self.verifier.current = self.instances[as_role or role]
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(10)
            conn.connect(self.paths[role])
            conn.sendall(payload)
            conn.shutdown(socket.SHUT_WR)
            data = b""
            while chunk := conn.recv(8192):
                data += chunk
            return data

    def finish(self) -> tuple[bytes, dict[str, Any], dict[str, str]]:
        self.receiver.fence()
        assert self.receiver.stop()
        reference = self.receiver.seal()
        stored = (Path(self.journal.root) / "objects" / reference.digest[7:]).read_bytes()
        join = adapter.ClockJoin(self.inventory.digest, None, 0)
        result = adapter.adapt(Path(self.journal.root), reference, self.context, self.inventory,
                               self.plan, round(self.plan.deadline * 1e9), join)
        return stored, result, self.receiver.coverage()


@pytest.fixture
def short() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="tpn-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _hostile(world: _World) -> tuple[list[str], list[bytes], list[bytes]]:
    """Send every hostile shape; return (participant canaries, inputs, receipts)."""
    c = {k: canary() for k in ("field", "identity", "offer", "reason", "oversize", "binary", "key",
                               "probe")}
    inputs = [
        json.dumps({"version": 1, "op": "offer", "request": 1, "note": c["field"]}).encode(),
        json.dumps({"version": 1, "op": "ack", "request": 2, "offer_id": "offer-worker",
                    "role": c["identity"]}).encode(),
        json.dumps({"version": 1, "op": "ack", "request": 3,
                    "offer_id": c["offer"] + "/x"}).encode(),
        json.dumps({"version": 1, "op": "refuse", "request": 4, "offer_id": "offer-worker",
                    "reason": c["reason"]}).encode(),
        json.dumps({"version": 1, "op": "offer", "request": 5,
                    "pad": c["oversize"] * 200}).encode(),
        b'{"version":1,"op":"offer","request":6,"x":"' + c["binary"].encode() + b'\xff"}',
        json.dumps({c["key"]: 1, "version": 1, "op": "offer", "request": 7}).encode(),
    ]
    receipts = [world.send("worker", raw + b"\n") for raw in inputs]
    # A peer probe that fails with a private value in its message.
    world.verifier.explode = c["probe"]
    receipts.append(world.send("worker", b'{"version":1,"op":"offer","request":8}\n'))
    world.verifier.explode = None
    inputs.append(("probe failed for " + c["probe"]).encode())
    # A request from the other sandbox on this endpoint, and honest traffic.
    receipts.append(world.send("worker", b'{"version":1,"op":"offer","request":9}\n',
                               as_role="integrator"))
    honest = [b'{"version":1,"op":"offer","request":10}',
              (b'{"version":1,"op":"ack",'
               b'"offer_id":"offer-integrator","request":11}')]
    for raw in honest:
        receipts.append(world.send("integrator", raw + b"\n"))
    return list(c.values()), inputs, receipts


def _json(value: Any) -> str:
    return json.dumps(value, default=lambda b: b.decode("utf-8", "surrogateescape"))


def test_hostile_requests_reach_no_receipt_journal_adapter_or_coverage(tmp_path: Path,
                                                                       short: Path) -> None:
    world = _World(tmp_path, short)
    needles, inputs, receipts = _hostile(world)
    planted(needles, inputs)
    # The private sentinels are what the controller's lease table now holds.
    planted(world.private, [repr(world.leases._entries), str(world.lease_root)])
    stored, result, coverage = world.finish()
    surfaces: dict[str, bytes | str] = {
        "receipts": b"".join(receipts), "journal": stored,
        "adapter": _json(result), "coverage": json.dumps(coverage)}
    assert all(schema.parse_receipt(r) is not None for r in receipts)
    assert scan(surfaces, needles + world.private) == []


class _EchoReceipt:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def encode(self) -> bytes:
        return self.raw.rstrip(b"\n") + b"\n"


class _EchoingReceiver(Receiver):
    """Leaking twin: replies with the raw request."""

    def _decide(self, endpoint: str, instance: str | None, raw: bytes) -> Any:
        super()._decide(endpoint, instance, raw)
        return _EchoReceipt(raw)


def test_a_receiver_that_echoes_requests_is_caught(tmp_path: Path, short: Path) -> None:
    world = _World(tmp_path, short, _EchoingReceiver)
    needles, inputs, receipts = _hostile(world)
    planted(needles, inputs)
    world.finish()
    assert scan({"receipts": b"".join(receipts)}, needles)


def test_an_adapter_that_dumps_lease_state_is_caught(tmp_path: Path, short: Path) -> None:
    world = _World(tmp_path, short)
    _hostile(world)
    _, result, _ = world.finish()
    leaky = {**result, "debug": repr(world.leases._entries)}
    assert scan({"adapter": _json(leaky)}, world.private)


# -- S5: exception chains on refusal paths -----------------------------------------------


def _raised(call: Callable[[], object]) -> BaseException:
    try:
        call()
    except BaseException as exc:  # noqa: BLE001 - the exception IS the surface
        return exc
    raise AssertionError("expected a refusal")


def test_refusal_exceptions_carry_no_participant_bytes(tmp_path: Path) -> None:
    c = [canary() for _ in range(9)]
    inventory = tpf.inventory_for(tpf.plan_of(ROLES), DECL)
    context = tj.Context("wave-0001", DECL, inventory.digest, DEADLINE, "skillc-test",
                         inventory.principals)
    journal = tj.Journal(tmp_path / "j", context, 0)
    leases = Leases(inventory, token=lambda: "ep-1")
    leases.issue(tpf.principal_of("worker"))
    machine = Machine(Plan((Offer("slot-worker", "offer-worker"),), 10))
    triggers: list[tuple[str, Callable[[], object]]] = [
        ("inventory-key", lambda: adapter.parse_inventory(
            {"attempt_id": "a", "declaration_digest": DECL, "clock_origin_ns": 0,
             "slots": [{c[0]: 1}]})),
        ("inventory-attempt", lambda: adapter.parse_inventory(
            {"attempt_id": c[1] + "!", "declaration_digest": DECL, "clock_origin_ns": 0,
             "slots": []})),
        ("journal-principal", lambda: journal.append("binding", principal=c[2],
                                                     evidence_digest=tpf.E)),
        ("lease-instance", lambda: leases.bind("slot-worker", runtime_instance=c[3] + "/",
                                               session_id="s", evidence_digest=tpf.E)),
        ("state-principal", lambda: machine.propose(c[4], schema.parse_request(
            b'{"version":1,"op":"offer","request":1}'), 1)),
        ("schema-op", lambda: schema.Request(c[5], 1)),
        ("lease-root", lambda: tpd.lease_dir(Path("/tmp/" + c[6] + ",x"), "ep-1")),
        ("mount-source", lambda: db.compose_run_argv(
            ["docker"], "img", "n", "a", ["x"], {}, "none", "1g", "1", "1", "1m", "1:1", None,
            task_protocol_host_dir=Path("/srv/" + c[7] + ",x"))),
        ("slot", lambda: Slot(c[8] + " ", "r", "t", 0, 1, "n")),
    ]
    inputs = [json.dumps({c[0]: 1}), c[1] + "!", c[2], c[3] + "/", c[4], c[5],
              "/tmp/" + c[6] + ",x", "/srv/" + c[7] + ",x", c[8] + " "]
    texts = {}
    for name, call in triggers:
        exc = _raised(call)
        assert isinstance(exc, (adapter.AdapterRefused, tj.JournalUnavailable, LeaseError,
                                StateError, schema.SchemaError, tpd.PlacementError, ValueError))
        texts[name] = exception_text(exc)
    planted(c, inputs)
    assert scan(texts, c) == []
    receiver_error = exception_text(_raised(lambda: Receiver(
        leases, machine, journal, _Verifier()).seal()))
    assert isinstance(_raised(lambda: Receiver(leases, machine, journal, _Verifier()).seal()),
                      ReceiverError)
    assert scan({"receiver": receiver_error}, c) == []


def test_a_chained_refusal_is_caught() -> None:
    """Leaking twin: `raise ... from exc` would carry the participant's key."""
    needle = canary()

    def leaky() -> None:
        try:
            Slot(**cast(Any, {needle: 1}))
        except TypeError as exc:
            raise adapter.AdapterRefused("inventory outside its contract") from exc

    assert scan({"chain": exception_text(_raised(leaky))}, [needle])


# -- S6: the client's diagnostics ------------------------------------------------------


@pytest.mark.parametrize("argv", [
    ["refuse", "--request", "1", "--offer", "o-1", "--reason", "{c}"],
    ["offer", "--request", "{c}"],
    ["offer", "--request", "1", "{c}"],
    ["ack", "--request", "1", "--offer", "{c}/x"],
    ["{c}", "--request", "1"],
], ids=["bad-reason", "bad-number", "extra-arg", "bad-offer", "bad-op"])
def test_client_diagnostics_never_echo_arguments(argv: list[str], tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    needle = canary()
    args = [a.replace("{c}", needle) for a in argv]
    planted([needle], args)
    assert client.main(args, str(tmp_path / "absent.sock")) == client.EXIT_USAGE
    out = capsys.readouterr()
    assert scan({"stdout": out.out, "stderr": out.err}, [needle]) == []


def test_the_unavailable_and_decided_paths_say_nothing_participant_chosen(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert client.main(["offer", "--request", "1"], str(tmp_path / "absent.sock")) == (
        client.EXIT_UNAVAILABLE)
    out = capsys.readouterr()
    assert out.out == "" and "no valid receipt" in out.err


def test_a_client_whose_usage_error_echoes_argv_is_caught(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """Leaking twin: argparse's own error, which names the bad value."""
    monkeypatch.setattr(client._Parser, "error", argparse.ArgumentParser.error)
    needle = canary()
    client.main(["refuse", "--request", "1", "--offer", "o-1", "--reason", needle],
                str(tmp_path / "absent.sock"))
    assert scan({"stderr": capsys.readouterr().err}, [needle])


# -- S8: audit reasons ----------------------------------------------------------------


def _record(cid: str, mounts: list[dict[str, Any]], **host: str) -> dict[str, Any]:
    return {"Id": cid, "State": {"Pid": 1}, "Mounts": mounts,
            "HostConfig": {"Privileged": False, "PidMode": "", "IpcMode": "private",
                           "NetworkMode": "none", "UsernsMode": "", **host}}


def test_audit_reasons_carry_no_daemon_supplied_text() -> None:
    other, source = "f" * 64, canary()
    lease_a, lease_b = "/srv/leases/ep-a", "/srv/leases/ep-b"
    target = db.TASK_PROTOCOL_DIR
    records = {
        "a": _record("a" * 64, [{"Type": "bind", "Source": lease_a, "Destination": target,
                                 "RW": False}]),
        "b": _record("b" * 64, [{"Type": "bind", "Source": lease_b, "Destination": target,
                                 "RW": False},
                                {"Type": "bind", "Source": "/srv/" + source, "Destination": target
                                 + "/x", "RW": True}],
                     PidMode="container:" + other, IpcMode="container:" + other)}
    planted([source, other], [json.dumps(records)])
    ok, reasons, digest = tpd.audit(records, {"a": ("a" * 64, lease_a), "b": ("b" * 64, lease_b)})
    assert not ok and digest == ""
    assert scan({"reasons": json.dumps(reasons)}, [source, other]) == []


def test_an_audit_that_echoes_values_is_caught() -> None:
    other = "f" * 64
    reason = f"b:PidMode:container:{other}"  # the pre-B7 reason shape
    assert scan({"reasons": reason}, [other])


# -- S4: the v2 assembly report ------------------------------------------------------------


def test_the_v2_report_carries_no_controller_private_identity(tmp_path: Path) -> None:
    from test_live_wave_assembly import fixture
    from test_live_wave_assembly_v2 import _to_v2

    from skillc import live_wave_assembly as assembly
    seen: list[str] = []

    def capture(_journal: tj.Journal, leases: Leases) -> None:
        for entry in leases._entries.values():
            seen.extend(v for v in (entry.runtime_instance,
                                    entry.lease.endpoint_id if entry.lease else None)
                        if isinstance(v, str))

    probe = tpf.build(tmp_path / "probe", tpf.plan_of(ROLES), DECL, DEADLINE, [], extra=capture)
    assert probe.reference.records >= 2 and seen  # what tpf plants into Leases
    arrival, expected, graders, _raw = fixture(tmp_path / "wave", alter=_to_v2())
    report = json.dumps(assembly.report(arrival, expected, graders))
    planted(seen, seen)
    assert scan({"report": report}, seen) == []
