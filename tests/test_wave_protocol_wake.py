"""#626 P2: ProtocolWave with `measured="wake"`, model-free (the model backend
of tests/test_docker_wave.py, the REAL client and receiver over Unix sockets).

The wake driver owns the turns; the protocol order is unchanged, the wake
capture's own origin joins the journal, and the report carries the wake
binding. Parent-compatible: it checks ProtocolWave's signature by assertion,
so on the parent the wake cases fail by assertion, not ImportError.

The blind twin is the parent's binding: `wake_context_digest` left None. With
the wake capture's context the adapter then refuses the join, so the twin
DISAGREES with the real report."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, ClassVar

import pytest
from test_wave_protocol_run import (
    HEALTHY_EVENTS,
    ROLES,
    Census,
    PeerFromEndpoint,
    ProtocolModel,
    World,
    _plan,
    short,  # noqa: F401 - a fixture
)

from skillc import docker_wave as wave
from skillc import task_protocol_adapter as adapter
from skillc import task_protocol_client as client
from skillc import task_protocol_journal as tj
from skillc import wave_protocol_run as wpr
from skillc import wave_wake, wave_wake_capture
from skillc.backend import Confirmation, ExecuteResult
from skillc.task_protocol_lease import Slot

DECL = "sha256:" + "d" * 64
DEADLINE = "sha256:" + "ab" * 32
LITERAL = "Read the shared work and continue."
POLICY = wave_wake.WakePolicy(
    literal=LITERAL,
    poll_seconds=.001,  # timing: cadence - the driver's sample period; each wave waits on poke COUNTS (max_pokes=1, STOPPED), bounded by its 60 s deadline
    min_spacing_seconds=0., max_pokes=1)


class WakeModel(ProtocolModel):
    """A poked turn speaks the whole protocol through the installed client's
    code; an attempt reads as running until it is ended."""

    poked: ClassVar[list[str]] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ended = False

    def execute_turn(self, handle: object, argv: Any, limits: Any,
                     cancel: Any = None) -> ExecuteResult:
        lease = self.config.get("task_protocol_host_dir")
        if argv[-1] == LITERAL and lease is not None:
            role = self.name.split("-")[-1]
            for op in ("offer", "ack", "complete"):
                offer = None if op == "offer" else "offer-" + role
                client.call(client.request_fields(op, next(self.requests), offer),
                            str(Path(lease) / "channel.sock"), timeout=10)
            self.poked.append(role)
        return super(ProtocolModel, self).execute_turn(handle, argv, limits, cancel)

    def end_attempt(self, handle: object) -> None:
        self.ended = True
        super().end_attempt(handle)

    def confirm_stopped(self, handle: object) -> Confirmation:
        super().confirm_stopped(handle)
        return Confirmation.CONFIRMED if self.ended else Confirmation.NOT_CONFIRMED


def _shared_state(events: list[str]) -> Any:
    """The controller-observed shared state. It changes once when the
    protocol starts serving (the assignment), then once per completed poked
    turn. A revision must hold still between the offer and the dispatch
    re-sample, or the driver refuses the poke as stale."""

    def read() -> wave_wake.Revision:
        state = f"{'serving' in events}:{len(WakeModel.poked)}"
        digest = hashlib.sha256(state.encode()).hexdigest()
        return wave_wake.Revision("sha256:" + digest, "sha256:" + "0" * 64)
    return read


def _wake_world(root: Path, short_dir: Path, monkeypatch: pytest.MonkeyPatch,
                census: Any = None) -> tuple[World, Any]:
    world = World(root, short_dir, monkeypatch)
    monkeypatch.setattr(wave, "DockerBackend", WakeModel)
    roles = [replace(r, resume_texts=()) for r in world.wave.roles]
    world.wave = wave.DockerWave(attempt_id="proto-wave", image="scripted", root=root / "ev-wake",
                                 fixture=root / "fixture", roles=roles, seconds=60)
    declaration = json.dumps({"roles": list(ROLES), "controller_wake": {"version": 1,
                              **asdict(POLICY)}}, sort_keys=True, separators=(",", ":")).encode()
    WakeModel.poked = []
    # The caller-held approval wave_wake.drive reads; bind_declaration
    # verifies it against the independently held digest.
    approved = wave_wake.bind_declaration(json.loads(declaration),
                                          "sha256:" + hashlib.sha256(declaration).hexdigest())
    vars(world.wave)["approved_wake"] = approved  # DockerWave declares no such field
    assert "measured" in inspect.signature(wpr.ProtocolWave).parameters, \
        "ProtocolWave has no wake mode"
    slots = [Slot("slot-" + r, r, "task-" + r, 0, 1, "nonce-" + r) for r in ROLES]
    budget = world.wave.deadline.marker(world.wave.attempt_id)["budget_id"]
    events: list[str] = []
    run = wpr.ProtocolWave(world.wave, slots=slots,
                           declaration_digest=approved.approved_digest,
                           deadline_digest="sha256:" + str(budget), deadline_seconds=60,
                           lease_root=short_dir / "wake-leases", journal_root=root / "wake-journal",
                           census=census, inspect=world.inspect, freeze=world.freeze,
                           receiver_factory=PeerFromEndpoint, measured="wake",
                           wake_policy=POLICY,
                           wake_options={"read_revision": _shared_state(events)})
    run.events = events  # the observer reads the run's own event list
    world.run = run
    return world, run


def _adapt(report: dict[str, Any], *, digest_from_report: bool = True) -> dict[str, Any]:
    bound = report["protocol_v2"]
    plan = _plan(report)
    wake = wave_wake_capture.parse_context(report["wake"]["context"])
    join = adapter.parse_clock_join(bound["clock_join"])
    if not digest_from_report:  # the parent's binding: no wake digest
        join = adapter.ClockJoin(join.inventory_digest, None, join.origin_ns)
    result: dict[str, Any] = adapter.adapt(
        Path(bound["root"]), tj.parse_reference(bound["reference"]),
        tj.parse_context(bound["context"]), adapter.parse_inventory(bound["inventory"]),
        plan, round(plan.deadline * 1e9), join, wake)
    return result


def _ran(tmp_path: Path, short_dir: Path,
         monkeypatch: pytest.MonkeyPatch) -> tuple[World, dict[str, Any], Census]:
    """Called inside each test (not a fixture), so the parent's missing wake
    mode is a test FAILURE by assertion rather than a setup error."""
    census = Census()
    world, run = _wake_world(tmp_path, short_dir, monkeypatch, census)
    return world, run.run(), census


def test_wake_mode_keeps_the_protocol_order(tmp_path: Path, short: Path,  # noqa: F811
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    world, report, census = _ran(tmp_path, short, monkeypatch)
    assert report["events"] == HEALTHY_EVENTS, report["unknown"]
    assert report["unknown"] == [] and report["wake_outcome"] == "STOPPED"
    # The freeze saw the barrier's sessions before serving, so before any poke.
    assert world.frozen and "serving" not in world.frozen[0]["events"]
    # The live census: every completion, then capture_after, then finalize
    # with the CONFIRMED stops that only close produced.
    names = [c if isinstance(c, str) else c[0] for c in census.calls]
    after = names.index("capture_after")
    assert names[:after] == ["setup"] + ["completion"] * len(ROLES)
    assert census.calls[after + 1][0] == "finalize"
    assert set(census.calls[after + 1][1].values()) == {"confirmed"}


def test_the_wake_capture_origin_joins_the_journal(tmp_path: Path, short: Path,  # noqa: F811
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    report = _ran(tmp_path, short, monkeypatch)[1]
    context = wave_wake_capture.parse_context(report["wake"]["context"])
    assert context.clock_origin_ns == report["protocol_v2"]["inventory"]["clock_origin_ns"]
    assert report["protocol_v2"]["clock_join"]["wake_context_digest"] == context.digest
    result = _adapt(report)
    assert result["status"] == "CAPTURED"
    for role in ROLES:
        rows = [json.loads(x) for x in (result["projections"][role] or b"").splitlines()]
        assert [r["op"] for r in rows] == ["ack", "complete"], role


def test_a_binding_without_the_wake_digest_disagrees(tmp_path: Path, short: Path,  # noqa: F811
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """BLIND TWIN: the parent's clock join (no wake digest) refuses the join
    against this wake capture; the real binding captures."""
    report = _ran(tmp_path, short, monkeypatch)[1]
    real, blind = _adapt(report), _adapt(report, digest_from_report=False)
    assert real["status"] == "CAPTURED"
    assert blind["status"] == "UNKNOWN" and blind["reasons"] == ["clock-join-unavailable"]


@pytest.mark.parametrize("measured,policy", [("wake", None), ("scripted", POLICY),
                                             ("other", POLICY)])
def test_a_wake_mode_needs_exactly_an_approved_policy(tmp_path: Path, short: Path,  # noqa: F811
                                                       monkeypatch: pytest.MonkeyPatch,
                                                       measured: str, policy: Any) -> None:
    world = World(tmp_path, short, monkeypatch)
    assert "measured" in inspect.signature(wpr.ProtocolWave).parameters
    # This wave has no approved wake binding, so even a policy is refused.
    slots = [Slot("slot-" + r, r, "task-" + r, 0, 1, "nonce-" + r) for r in ROLES]
    with pytest.raises(ValueError):
        wpr.ProtocolWave(world.wave, slots=slots, declaration_digest=DECL,
                         deadline_digest=DEADLINE, deadline_seconds=60,
                         lease_root=short / "x", journal_root=tmp_path / "x",
                         measured=measured, wake_policy=policy)


@pytest.mark.parametrize("field", ["declaration_digest", "deadline_digest"])
def test_wake_mode_refuses_a_journal_the_wake_capture_cannot_join(
        tmp_path: Path, short: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
        field: str) -> None:
    """A declaration or deadline that differs from the wake capture's is refused
    at construction, not left to fail late as clock-join-unavailable."""
    world, run = _wake_world(tmp_path, short, monkeypatch)
    slots = [Slot("slot-" + r, r, "task-" + r, 0, 1, "nonce-" + r) for r in ROLES]
    good = {"declaration_digest": run.context.declaration_digest,
            "deadline_digest": run.context.deadline_digest}
    with pytest.raises(ValueError, match="wake mode"):
        wpr.ProtocolWave(world.wave, slots=slots, **{**good, field: "sha256:" + "e" * 64},
                         deadline_seconds=60, lease_root=short / "y",
                         journal_root=tmp_path / "y", measured="wake", wake_policy=POLICY)
