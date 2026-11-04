"""Controller adapter wiring controls; modeled root identity is not Docker proof."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skillc.completion import CompletionDeadline
from skillc.wave_tap import Binding
from skillc.wave_tap_docker import DockerHelperExecutor

CASES = json.loads((Path(__file__).resolve().parents[1] / "controls/wave-tap/install.json").read_text())
SID = "00000000-0000-0000-0000-000000000001"
HEADER = ("OpenAI Codex v0.157.1\n--------\nsession id: " + SID + "\n--------\n").encode()


class ModelBackend:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.writable: bool | None = False
        self.status: str | None = "running"
        self.modes: list[int] = []

    def write_root_owned_file_in_attempt(self, handle: Any, path: str, data: bytes,
                                        *, mode: int, timeout: float) -> bool:
        self.files[path] = data
        self.modes.append(mode)
        return True

    def candidate_can_write_in_attempt(self, handle: Any, path: str) -> bool | None:
        return self.writable

    def root_output_in_attempt(self, handle: Any, argv: list[str], **kwargs: Any) -> bytes:
        root, names = json.loads(argv[-1])
        return json.dumps({name: hashlib.sha256(self.files[root + "/" + name]).hexdigest()
                           for name in names}).encode()

    def _inspect(self, handle: Any) -> tuple[bool, bool, str | None]:
        return self.status is not None, False, self.status


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_committed_identity_and_install_controls(case: dict[str, Any]) -> None:
    b = Binding("tap-wave", "worker-a", "attempt-a", SID, "quote-a", 0, 1, "task-nonce")
    backend = ModelBackend()
    state = SimpleNamespace(backend=backend, handle=object(), guard=SimpleNamespace(attempt_id=b.attempt_id),
        session_id=SID, unknown=[], executions=[SimpleNamespace(reason="exited", exit_code=0, stderr=HEADER)])
    config = {"wave_id": b.wave_id, "tap": True, "bindings": {b.role: {
        "attempt_id": b.attempt_id, "task": b.task, "generation": b.generation,
        "revision": b.revision, "nonce": b.nonce}}}
    wave = SimpleNamespace(states={b.role: state}, closed=False, deadline=CompletionDeadline.after(30))
    executor = DockerHelperExecutor(wave, {"flow-wave-mailbox.sh": b"fixed helper"}, b"fixed actor", b"{}")
    state.role = SimpleNamespace(argv=("python3", "-I", "-S", executor.path + "/role_actor.py", b.role, "healthy"),
                                 prompt=json.dumps(config))
    if case["fault"] in {"writable", "unknown-write"}:
        backend.writable = True if case["fault"] == "writable" else None
    installed = executor.install(b.role)
    if case["fault"] == "source":
        backend.files[executor.path + "/flow-wave-mailbox.sh"] = b"replaced"
    elif case["fault"] == "attempt":
        state.guard.attempt_id = "other-attempt"
    elif case["fault"] == "session":
        state.session_id = "other-session"
    elif case["fault"] == "header":
        state.executions[0].stderr = b"unobserved actor claim"
    elif case["fault"] == "bootstrap":
        state.executions = []
    elif case["fault"] == "liveness":
        backend.status = None
    elif case["fault"] == "launch":
        state.role.argv = ("python3", "actor.py")
    elif case["fault"] == "role":
        state.role.argv = (*state.role.argv[:4], "worker-b", "healthy")
    elif case["fault"] == "config":
        config["tap"] = False
    elif case["fault"] == "wave":
        config["wave_id"] = "other-wave"
    elif case["fault"] == "deadline":
        wave.deadline = CompletionDeadline.after(1, lambda: 0)
        wave.deadline._clock.read = lambda: 2
    state.role.prompt = json.dumps(config)
    assert (installed and executor.admitted(b)) is case["admitted"]
    assert all(mode == 0o555 for mode in backend.modes)


@pytest.fixture
def peer_model(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Model daemon/proc observations; execute the production authorizer itself."""
    from skillc.backend import BackendUnavailable

    model = SimpleNamespace(fault="good", calls=[], reads=0, peer_pid=123)
    original_read, original_stat = Path.read_text, Path.stat

    def inspect(argv: list[str]) -> str:
        model.calls.append(argv)
        if model.fault == "daemon":
            raise BackendUnavailable("modeled unavailable daemon")
        return "0" if model.fault == "stopped" else "not-a-pid" if model.fault == "malformed" else "90001"

    def read(path: Path, *args: Any, **kwargs: Any) -> str:
        if str(path) == f"/proc/{model.peer_pid}/stat":
            model.reads += 1
            if model.fault == "missing":
                raise FileNotFoundError(path)
            if model.fault == "unreadable":
                raise PermissionError(path)
            if model.fault == "bad-stat":
                return "truncated"
            start = "101" if model.fault == "reused" and model.reads % 2 == 0 else "100"
            return "123 (process ) with spaces) S " + "0 " * 18 + start
        return original_read(path, *args, **kwargs)

    def stat(path: Path, *args: Any, **kwargs: Any) -> Any:
        if str(path) in {f"/proc/{model.peer_pid}/ns/pid", "/proc/90001/ns/pid"}:
            if model.fault == "namespace-unreadable":
                raise PermissionError(path)
            owned = str(path) == "/proc/90001/ns/pid"
            return SimpleNamespace(st_ino=42 if owned or model.fault not in {"host", "sibling"} else 43)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(Path, "stat", stat)
    wave = SimpleNamespace(states={"worker-a": SimpleNamespace(handle="owned-role")},
                           _call=inspect, _name=lambda handle: "owned-container")
    model.executor = DockerHelperExecutor(wave, {"flow-wave-mailbox.sh": b"helper"}, b"actor", b"{}")
    return model


@pytest.mark.parametrize("fault,expected", [
    ("good", True), ("host", False), ("sibling", False), ("uid", False), ("gid", False),
    ("pid", None), ("role", None), ("missing", None), ("unreadable", None),
    ("namespace-unreadable", None), ("reused", None), ("stopped", None),
    ("malformed", None), ("bad-stat", None), ("daemon", None),
])
def test_production_peer_authorizer_observation_controls(peer_model: Any, fault: str,
                                                        expected: bool | None) -> None:
    from skillc.docker_backend import CANDIDATE_GID, CANDIDATE_UID

    peer_model.fault = fault
    result = peer_model.executor.peer_allowed("absent" if fault == "role" else "worker-a",
        0 if fault == "pid" else 123, CANDIDATE_UID + int(fault == "uid"),
        CANDIDATE_GID + int(fault == "gid"))
    assert result is expected
    if fault not in {"uid", "gid", "pid", "role"}:
        assert peer_model.calls == [["inspect", "--format", "{{.State.Pid}}", "owned-container"]]


@pytest.mark.parametrize("fault", ["good", "host", "sibling", "reused", "unreadable"])
def test_production_peer_gate_socket_drops_prevent_helper_and_completion(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, peer_model: Any, fault: str) -> None:
    import os
    import socket
    import tempfile
    from dataclasses import asdict

    from test_wave_tap import LocalHelperExecutor

    from skillc import wave_tap_docker
    from skillc.decide_reply_channel import DecideReplyChannel
    from skillc.wave_tap import HelperTap

    # Socket credentials remain actual kernel facts. Model the candidate mapping
    # to this unit process; fixed production UID/GID refusals are checked above.
    monkeypatch.setattr(wave_tap_docker, "CANDIDATE_UID", os.getuid())
    monkeypatch.setattr(wave_tap_docker, "CANDIDATE_GID", os.getgid())
    peer_model.fault = fault
    peer_model.peer_pid = os.getpid()
    b = Binding("tap-wave", "worker-a", "attempt-a", SID, "quote-a", 0, 1, "task-nonce")
    executor = LocalHelperExecutor(tmp_path)
    tap = HelperTap((b,), executor.pins, executor, tmp_path / "controller")
    endpoint = tap.open_turn(b.role, HEADER)
    with tempfile.TemporaryDirectory(prefix="peer-gate-") as short:
        path = Path(short) / "role.sock"
        channel = DecideReplyChannel(path, lambda req: tap.request(endpoint, req), b.attempt_id)
        channel.set_peer_authorizer(lambda pid, uid, gid: peer_model.executor.peer_allowed(b.role, pid, uid, gid))
        tap.bind_channel(b.role, channel)
        assert tap.assign(b.role)
        before = len(executor.calls)
        channel.start()
        try:
            for op in ("ack", "complete"):
                payload = {"op": op, "binding": asdict(b), "turn_nonce": endpoint.turn_nonce}
                if op == "complete":
                    payload["commit"] = "1" * 40
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(5)
                    client.connect(str(path))
                    try:
                        client.sendall(json.dumps(payload).encode() + b"\n")
                        response = client.recv(16384)
                    except ConnectionResetError:
                        response = b""
                if fault == "good":
                    assert json.loads(response)["result"]["accepted"] is True
                else:
                    assert response == b"", "unauthorized peer reached the helper tap"
        finally:
            channel.stop_and_finalize()
        assert peer_model.calls, "production peer gate was never invoked"
        tap.end_turn(endpoint)
        executor.stopped = True
        report = tap.finalize()
        if fault == "good":
            assert len(executor.calls) == before + 2
            assert channel.dropped_connections() == 0
            assert report["status"] == "COMPLETE", report
        else:
            assert len(executor.calls) == before
            assert channel.dropped_connections() == 2
            assert report["status"] == "UNKNOWN"
            assert b.role + ":channel-finalization-unavailable" in report["unknown"]
