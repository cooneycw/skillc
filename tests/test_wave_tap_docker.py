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
