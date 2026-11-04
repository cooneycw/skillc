"""Compose the existing Docker seam/turn driver with a trusted helper tap.

No Docker fallback, model calls, new service engine or participant log importer.
Callers must still grade retained remote delivery and independently check clutter.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from skillc.backend import BackendUnavailable, ExecuteResult
from skillc.docker_wave import DockerWave, Role
from skillc.wave_tap import Binding, Endpoint, HelperTap
from skillc.wave_tap_docker import DockerHelperExecutor

ROLES = ("orchestrator", "worker-a", "worker-b")


def helper_sources(directory: Path) -> dict[str, bytes]:
    pins = json.loads((Path(__file__).resolve().parent / "helper-pins.json").read_text())
    if pins["source_commit"] != "87ecb0970f70aace9e0323feee00c9ca57dda133":
        raise ValueError("unapproved helper source pin")
    files = {path.name: path.read_bytes() for path in directory.iterdir()
             if path.suffix in {".sh", ".py"}}
    if {name: hashlib.sha256(data).hexdigest() for name, data in files.items()} != pins["files"]:
        raise ValueError("helper source population or bytes differ from approved pin")
    return files


class TappedWave(DockerWave):
    def __init__(self, *, helpers: Path, mode: str, **kwargs: Any) -> None:
        source = Path(__file__).resolve().parent
        self.executor = DockerHelperExecutor(None, helper_sources(helpers),
            (source / "role_actor.py").read_bytes(), (source / "task.json").read_bytes())
        self.specs = {role: {"attempt_id": kwargs["attempt_id"] + "-" + role,
            "task": "quote-" + role, "generation": 0, "revision": 1,
            "nonce": secrets.token_hex(16)} for role in ROLES}
        prompt = json.dumps({"wave_id": kwargs["attempt_id"], "bindings": self.specs, "tap": True})
        kwargs["roles"] = [Role(role, ("python3", "-I", "-S", self.executor.path + "/role_actor.py", role, mode),
                               prompt, min(30, kwargs["seconds"])) for role in ROLES]
        self.tap: HelperTap | None = None
        self.endpoints: dict[str, Endpoint] = {}
        self.setup_lock = threading.RLock()
        self.tap_finalized = False
        super().__init__(**kwargs)
        self.executor.wave = self

    def _backend(self, name: str, **kwargs: Any) -> Any:
        if name in ROLES:
            guard = kwargs["trigger_decide"]

            def route(request: Any) -> Any:
                if request.get("kind") != "wave-helper":
                    return guard(request)
                with self.setup_lock:
                    tap, endpoint = self.tap, self.endpoints.get(name)
                if tap is None or endpoint is None:
                    self.unknown.append(name + ":unobserved-tap-endpoint")
                    return {"accepted": False, "reason": "unobserved-tap-endpoint"}
                return tap.request(endpoint, {key: value for key, value in request.items() if key != "kind"})

            kwargs["trigger_decide"] = route
        return super()._backend(name, **kwargs)

    def prepare(self) -> None:
        super().prepare()
        for role in ROLES:
            channel = getattr(self.states[role].handle, "trigger_channel", None)
            if channel is None:
                raise BackendUnavailable("role channel absent before actor bootstrap")
            channel.set_peer_authorizer(lambda pid, uid, gid, role=role:
                                        self.executor.peer_allowed(role, pid, uid, gid))
            if not self.executor.install(role):
                raise BackendUnavailable("protected rehearsal helper installation unavailable")
            self._write(role + "/tap-install.json", {"actor_helper_pins": self.executor.source_pins})

    def _bind_after_bootstrap(self) -> None:
        if self.tap is not None or len(self.states) != len(ROLES):
            return
        for state in self.states.values():
            if (state.session_id is None or not state.executions
                    or state.executions[0].reason != "exited" or state.executions[0].exit_code != 0):
                return
        observed_bindings = []
        for role in ROLES:
            session = self.states[role].session_id
            assert session is not None
            observed_bindings.append(Binding(wave_id=self.attempt_id, role=role,
                session_id=session, **self.specs[role]))
        bindings = tuple(observed_bindings)
        self.tap = HelperTap(bindings, self.executor.pins, self.executor,
                             self.root / "tap-controller", origin=self.deadline.start)
        for binding in bindings:
            state = self.states[binding.role]
            channel = getattr(state.handle, "trigger_channel", None)
            if channel is None:
                raise BackendUnavailable("actual role channel unavailable")
            self.tap.bind_channel(binding.role, channel)
            endpoint = self.tap.open_turn(binding.role, state.executions[0].stderr or b"")
            try:
                if not self.tap.assign(binding.role):
                    raise BackendUnavailable("controller assignment not observed")
            finally:
                self.tap.end_turn(endpoint)

    def turn(self, role: str, text: str | None = None, cancel: Any = None,
             *, expected_session: str | None = None) -> ExecuteResult:
        endpoint = None
        with self.setup_lock:
            if self.tap is not None and self.states[role].executions:
                endpoint = self.tap.open_turn(role, self.states[role].executions[0].stderr or b"")
                self.endpoints[role] = endpoint
                if not self.executor.deliver_turn_nonce(role, endpoint.turn_nonce):
                    self.tap.end_turn(endpoint)
                    del self.endpoints[role]
                    raise BackendUnavailable("protected turn fence delivery unavailable")
        try:
            return super().turn(role, text, cancel, expected_session=expected_session)
        finally:
            with self.setup_lock:
                if endpoint is not None and self.tap is not None:
                    self.tap.end_turn(endpoint)
                    self.endpoints.pop(role, None)
                self._bind_after_bootstrap()

    def close(self) -> dict[str, Any]:
        report = super().close()
        if not self.tap_finalized:
            self.tap_finalized = True
            collected: dict[str, Any] = self.tap.finalize() if self.tap is not None else {
                "status": "UNKNOWN", "unknown": ["bootstrap-population-incomplete"],
                "events": [], "refusals": [], "task_success": "UNASSESSED"}
            collected["collection_elapsed"] = time.monotonic() - self.deadline.start
            collected["plan"] = [asdict(b) for b in self.tap.bindings.values()] if self.tap else []
            self._write("tap-report.json", collected)
        return report
