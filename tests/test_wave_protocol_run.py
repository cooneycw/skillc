"""The #620 PR-B protocol lifecycle (skillc/wave_protocol_run.py, B8b), with
the model backend of tests/test_docker_wave.py: no Docker. Resume turns call
the REAL client against the REAL receiver over Unix sockets in a short /tmp
directory. The real-daemon run is B8c."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import shutil
import socket
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, ClassVar

import pytest
from test_docker_wave import ModelBackend

from skillc import docker_wave as wave
from skillc import live_wave
from skillc import task_protocol_adapter as adapter
from skillc import task_protocol_client as client
from skillc import task_protocol_journal as tj
from skillc import wave_protocol_run as wpr
from skillc.backend import Confirmation, ExecuteResult
from skillc.docker_backend import TASK_PROTOCOL_DIR
from skillc.task_protocol_lease import Slot
from skillc.task_protocol_receiver import Receiver

DECL = "sha256:" + "d" * 64
DEADLINE = "sha256:" + "ab" * 32
ROLES = ("integrator", "worker")


class ProtocolModel(ModelBackend):
    """The lifecycle model plus the install primitives, and resume turns that
    speak the task protocol through the installed client's code."""

    installed: ClassVar[dict[str, bytes]] = {}
    fail_install: ClassVar[set[str]] = set()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.requests = itertools.count(1)

    def write_root_owned_file_in_attempt(self, handle: object, path: str, content: bytes,
                                         mode: int = 0o755, timeout: float | None = None) -> bool:
        if self.name.rsplit("-", 1)[-1] in self.fail_install:
            return False
        self.installed[self.name + ":" + path] = content
        return True

    def candidate_can_write_in_attempt(self, handle: object, path: str,
                                       timeout: float | None = None) -> bool | None:
        return False

    def root_output_in_attempt(self, handle: object, argv: Any, timeout: float | None = None,
                               max_bytes: int = 1 << 20) -> bytes | None:
        data = self.installed.get(self.name + ":" + argv[-1])
        return None if data is None else hashlib.sha256(data).hexdigest().encode() + b"\n"

    def execute_turn(self, handle: object, argv: Any, limits: Any,
                     cancel: Any = None) -> ExecuteResult:
        text = argv[-1]
        lease = self.config.get("task_protocol_host_dir")
        if text in ("offer", "ack", "complete") and lease is not None:
            role = self.name.split("-")[-1]
            offer = None if text == "offer" else "offer-" + role
            client.call(client.request_fields(text, next(self.requests), offer),
                        str(Path(lease) / "channel.sock"), timeout=10)
        return super().execute_turn(handle, argv, limits, cancel)


def _id(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


class World:
    def __init__(self, root: Path, short: Path, monkeypatch: pytest.MonkeyPatch, *,
                 modes: Mapping[str, str] | None = None, privileged: bool = False,
                 census: Any = None, **kwargs: Any) -> None:
        ModelBackend.instances = []
        ModelBackend.result_modes = dict(modes or {})
        ModelBackend.stop_observation = Confirmation.CONFIRMED
        ModelBackend.absent_observation = Confirmation.CONFIRMED
        ProtocolModel.installed = {}
        root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(wave, "DockerBackend", ProtocolModel)
        monkeypatch.setattr(wave.fixture_overlay, "install_codex_guard", lambda *args: {})
        monkeypatch.setattr(wave.DockerWave, "_call", lambda self, argv, **kw: b"")
        fixture = root / "fixture"
        fixture.mkdir()
        roles = [wave.Role(n, ("python3", "actor.py"), "start", 4, ("offer", "ack", "complete"))
                 for n in ROLES]
        self.wave = wave.DockerWave(attempt_id="proto-wave", image="scripted", root=root / "ev",
                                    fixture=fixture, roles=roles, seconds=60)
        self.privileged = privileged
        self.census = census
        self.frozen: list[dict[str, Any]] = []
        slots = [Slot("slot-" + r, r, "task-" + r, 0, 1, "nonce-" + r) for r in ROLES]
        self.run = wpr.ProtocolWave(self.wave, slots=slots, declaration_digest=DECL,
                                    deadline_digest=DEADLINE, deadline_seconds=60,
                                    lease_root=short / "leases",
                                    journal_root=root / "journal", census=census,
                                    inspect=self.inspect, freeze=self.freeze,
                                    receiver_factory=PeerFromEndpoint, **kwargs)

    def inspect(self, name: str) -> dict[str, Any] | None:
        role = name.split("-")[-1]
        lease = self.wave.task_protocol_dirs.get(role)
        if lease is None:
            return None
        return {"Id": _id(name), "State": {"Pid": 1},
                "Mounts": [{"Type": "bind", "Source": os.path.realpath(lease),
                            "Destination": TASK_PROTOCOL_DIR, "RW": False}],
                "HostConfig": {"Privileged": self.privileged, "PidMode": "", "IpcMode": "private",
                               "NetworkMode": "none", "UsernsMode": ""}}

    def freeze(self, sessions: Mapping[str, str | None]) -> object:
        self.frozen.append({"sessions": dict(sessions), "events": list(self.run.events)})
        return object()


class PeerFromEndpoint(Receiver):
    """One process plays every sandbox: the peer is the container whose lease
    the request reached. Only this test may do that."""

    def _peer(self, conn: socket.socket, endpoint: str) -> str | None:
        role = self._owners[endpoint].split("-", 1)[1]
        return _id("proto-wave-" + role)


class Census:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def setup(self) -> None:
        self.calls.append("setup")

    def completion(self, role: str) -> None:
        self.calls.append(("completion", role))

    def capture_after(self) -> None:
        self.calls.append("capture_after")

    def finalize(self, *, role_stops: Mapping[str, Confirmation],
                 helper_stop: Confirmation) -> dict[str, Any]:
        self.calls.append(("finalize", {k: v.value for k, v in role_stops.items()},
                           helper_stop.value))
        return {"status": "CLEAN"}


@pytest.fixture
def short() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="tpw-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


HEALTHY_EVENTS = ["leased", "prepared", "census-setup", "audited", "bootstrapped", "barrier",
                  "frozen", "serving", "turns-done", "fenced", "census-after", "closed",
                  "sealed", "census-final"]


def _plan(report: dict[str, Any]) -> live_wave.WavePlan:
    return live_wave.WavePlan("proto-wave", tuple(
        live_wave.RoleBinding(r, "proto-wave-" + r, report["sessions"][r], "task-" + r, 0, 1,
                              "nonce-" + r, ("output.json",)) for r in ROLES),
        ROLES[0], 60.0)


def _adapt(world: World, report: dict[str, Any]) -> dict[str, Any]:
    bound = report["protocol_v2"]
    plan = _plan(report)
    reference = tj.parse_reference(bound["reference"])
    return adapter.adapt(Path(bound["root"]), reference, tj.parse_context(bound["context"]),
                         adapter.parse_inventory(bound["inventory"]), plan,
                         round(plan.deadline * 1e9), adapter.parse_clock_join(bound["clock_join"]))


def test_the_healthy_order_and_its_projection(tmp_path: Path, short: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    census = Census()
    world = World(tmp_path, short, monkeypatch, census=census)
    report = world.run.run()
    assert report["events"] == HEALTHY_EVENTS and report["unknown"] == []
    assert report["audit"]["ok"] is True and report["planned_frozen"] is True
    assert all(report["sessions"][r] is not None for r in ROLES)
    result = _adapt(world, report)
    assert result["status"] == "CAPTURED"
    for role in ROLES:
        rows = [json.loads(x) for x in (result["projections"][role] or b"").splitlines()]
        assert [r["op"] for r in rows] == ["ack", "complete"]
    assert census.calls[0] == "setup" and census.calls[-2] == "capture_after"
    assert census.calls[-1] == ("finalize", {r: "confirmed" for r in ROLES}, "confirmed")
    assert report["decision_a"].startswith("a2")


def test_the_barrier_precedes_freeze_and_freeze_precedes_offers(
        tmp_path: Path, short: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(tmp_path, short, monkeypatch)
    world.run.run()
    seen = world.frozen[0]["events"]
    assert "barrier" in seen and "serving" not in seen


def test_a_refused_audit_offers_nothing(tmp_path: Path, short: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(tmp_path, short, monkeypatch, privileged=True)
    report = world.run.run()
    assert report["audit"]["ok"] is False and "exclusivity-refused" in report["unknown"]
    records = tj.verify(Path(report["protocol_v2"]["root"]),
                        tj.parse_reference(report["protocol_v2"]["reference"]),
                        tj.parse_context(report["protocol_v2"]["context"]))["records"]
    assert not [r for r in records if r["kind"] == "decision"]
    barrier = next(r for r in records if r["kind"] == "barrier")
    assert {s["state"] for s in barrier["slots"]} == {"unavailable"}


def test_a_missing_startup_header_makes_only_that_slot_unavailable(
        tmp_path: Path, short: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(tmp_path, short, monkeypatch, modes={"proto-wave-worker": "missing-header"})
    report = world.run.run()
    assert report["sessions"]["worker"] is None and report["sessions"]["integrator"] is not None
    assert "worker:startup-binding-unavailable" in report["unknown"]


def test_an_unconfirmed_stop_reaches_the_census_as_unknown(tmp_path: Path, short: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    census = Census()
    world = World(tmp_path, short, monkeypatch, census=census)
    ModelBackend.stop_observation = Confirmation.UNKNOWN
    world.run.run()
    final = census.calls[-1]
    assert final[0] == "finalize" and set(final[1].values()) == {"unknown"}


def test_a_seal_failure_leaves_no_protocol_binding(tmp_path: Path, short: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(tmp_path, short, monkeypatch)

    def broken(self: Receiver) -> tj.Reference:
        raise OSError("injected seal failure")

    monkeypatch.setattr(Receiver, "seal", broken)
    report = world.run.run()
    assert report["protocol_v2"] is None
    assert "journal-seal-unavailable:OSError" in report["unknown"]
    assert "closed" in report["events"]


def test_cleanup_runs_when_preparation_fails(tmp_path: Path, short: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    census = Census()
    world = World(tmp_path, short, monkeypatch, census=census)

    def fail(self: Any) -> None:
        raise OSError("injected prepare failure")

    monkeypatch.setattr(wave.DockerWave, "prepare", fail)
    report = world.run.run()
    assert "protocol-step-unavailable:OSError" in report["unknown"]
    assert report["events"] == ["leased", "closed", "sealed", "census-final"]
    assert "census-settle-unavailable" in report["unknown"]
    assert report["census"]["status"] == "UNKNOWN"


# -- blind variants: each must DISAGREE with the real result ------------------------------


class _FreezesEarly(wpr.ProtocolWave):
    def _bootstrap(self, *args: Any) -> None:
        if self.freeze is not None:
            self.freeze({})
        super()._bootstrap(*args)


class _OffersWithoutAudit(wpr.ProtocolWave):
    def _audit(self, dirs: Mapping[str, Path]) -> dict[str, Any]:
        real = super()._audit(dirs)
        if not real["ok"]:
            self.unknown.remove("exclusivity-refused")
        return {**real, "ok": True, "digest": "sha256:" + "0" * 64}


class _CensusBeforeStop(wpr.ProtocolWave):
    def _close(self) -> dict[str, Any]:
        self._finalize_census({"after": "captured"})
        return super()._close()


def _with(cls: type[wpr.ProtocolWave], world: World) -> wpr.ProtocolWave:
    old = world.run
    blind = cls.__new__(cls)
    blind.__dict__.update(old.__dict__)
    world.run = blind
    return blind


def test_a_freeze_before_the_barrier_is_caught(tmp_path: Path, short: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    honest = World(tmp_path / "h", short / "h", monkeypatch)
    honest.run.run()
    blind = World(tmp_path / "b", short / "b", monkeypatch)
    _with(_FreezesEarly, blind).run()
    assert "barrier" in honest.frozen[0]["events"]
    assert "barrier" not in blind.frozen[0]["events"]


def test_offers_before_the_audit_are_caught(tmp_path: Path, short: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    honest = World(tmp_path / "h", short / "h", monkeypatch, privileged=True)
    honest_report = honest.run.run()
    blind = World(tmp_path / "b", short / "b", monkeypatch, privileged=True)
    blind_report = _with(_OffersWithoutAudit, blind).run()
    assert all(v is None for v in honest_report["sessions"].values())
    assert any(v is not None for v in blind_report["sessions"].values())


def test_a_census_before_the_confirmed_stop_is_caught(tmp_path: Path, short: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    honest_census, blind_census = Census(), Census()
    honest = World(tmp_path / "h", short / "h", monkeypatch, census=honest_census)
    honest.run.run()
    blind = World(tmp_path / "b", short / "b", monkeypatch, census=blind_census)
    _with(_CensusBeforeStop, blind).run()
    honest_final = next(c for c in honest_census.calls if c[0] == "finalize")
    blind_final = next(c for c in blind_census.calls if c[0] == "finalize")
    assert set(honest_final[1].values()) == {"confirmed"}
    assert set(blind_final[1].values()) != {"confirmed"}
