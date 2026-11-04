"""Docker-only executor for the controller helper tap; no host fallback."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import wave_tap_operation
from .backend import BackendUnavailable, Confirmation
from .controller_turns import session_id_from_header
from .docker_backend import CANDIDATE_GID, CANDIDATE_UID
from .wave_attachment import WAVE_ROOT
from .wave_tap import Binding

_PROBE = '''import hashlib,json,os,stat,sys
root,expected=json.loads(sys.argv[1])
found={}
for name in expected:
 path=root+'/'+name
 info=os.lstat(path)
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)&0o022:
  raise SystemExit(2)
 with open(path,'rb') as stream: found[name]=hashlib.sha256(stream.read(1048577)).hexdigest()
print(json.dumps(found,sort_keys=True))
'''


class DockerHelperExecutor:
    def __init__(self, wave: Any, helpers: dict[str, bytes], actor: bytes, task: bytes) -> None:
        if "flow-wave-mailbox.sh" not in helpers or any(
                re.fullmatch(r"[a-z0-9-]+\.(sh|py)", name) is None for name in helpers):
            raise ValueError("closed helper filenames required")
        self.wave = wave
        self.helpers = dict(helpers)
        self.pins = {name: hashlib.sha256(data).hexdigest() for name, data in helpers.items()}
        self.sources = {**helpers, "role_actor.py": actor, "task.json": task}
        self.source_pins = {name: hashlib.sha256(data).hexdigest() for name, data in self.sources.items()}
        bundle = hashlib.sha256(json.dumps(self.source_pins, sort_keys=True).encode()).hexdigest()
        self.path = "/opt/skillc-wave-tap/" + bundle
        self.installed: set[str] = set()

    def install(self, role: str) -> bool:
        state = self.wave.states[role]
        for name, data in self.sources.items():
            path = self.path + "/" + name
            if not state.backend.write_root_owned_file_in_attempt(state.handle, path, data, mode=0o555,
                    timeout=self.wave.deadline.remaining(10)):
                return False
            if state.backend.candidate_can_write_in_attempt(state.handle, path) is not False:
                return False
        if state.backend.candidate_can_write_in_attempt(state.handle, self.path) is not False:
            return False
        self.installed.add(role)
        return self._pins_match(role)

    def _pins_match(self, role: str) -> bool:
        state = self.wave.states[role]
        raw = state.backend.root_output_in_attempt(state.handle, ["python3", "-I", "-S", "-c", _PROBE,
            json.dumps([self.path, self.source_pins])], max_bytes=16384,
            timeout=self.wave.deadline.remaining(10))
        try:
            return raw is not None and json.loads(raw) == self.source_pins
        except (ValueError, TypeError):
            return False

    def peer_allowed(self, role: str, pid: int, uid: int, gid: int) -> bool | None:
        """Kernel peer must inhabit the independently owned role PID namespace.

        Unknown PID visibility/user-namespace mappings are unavailable evidence.
        This probe runs only on the controller host beside its Docker daemon.
        """
        if pid <= 0:
            return None
        if uid != CANDIDATE_UID or gid != CANDIDATE_GID:
            return False
        state = self.wave.states.get(role)
        if state is None:
            return None
        try:
            raw = self.wave._call(["inspect", "--format", "{{.State.Pid}}", self.wave._name(state.handle)])
            owned_pid = int(raw.strip())
            if owned_pid <= 0:
                return None
            peer_root = Path("/proc") / str(pid)
            before = (peer_root / "stat").read_text().rsplit(")", 1)[1].split()[19]
            same_namespace = ((peer_root / "ns/pid").stat().st_ino
                              == (Path("/proc") / str(owned_pid) / "ns/pid").stat().st_ino)
            after = (peer_root / "stat").read_text().rsplit(")", 1)[1].split()[19]
            return same_namespace if before == after else None
        except (OSError, ValueError, IndexError, BackendUnavailable):
            return None

    def admitted(self, binding: Binding) -> bool:
        try:
            self.wave.deadline.remaining(1)
        except ValueError:
            return False
        state = self.wave.states.get(binding.role)
        if (state is None or binding.role not in self.installed or self.wave.closed
                or state.guard.attempt_id != binding.attempt_id or state.session_id != binding.session_id):
            return False
        if (not state.executions or state.executions[0].reason != "exited"
                or state.executions[0].exit_code != 0
                or session_id_from_header(state.executions[0].stderr) != binding.session_id
                or "resume-header-disagrees" in state.unknown):
            return False
        # The captured bootstrap must have run this exact controller-owned actor.
        if (len(state.role.argv) != 6 or state.role.argv[4] != binding.role
                or tuple(state.role.argv[:4]) != ("python3", "-I", "-S", self.path + "/role_actor.py")):
            return False
        try:
            config = json.loads(state.role.prompt)
            declared = config["bindings"][binding.role]
            if config.get("tap") is not True or config.get("wave_id") != binding.wave_id or any(declared[key] != getattr(binding, key)
                    for key in ("attempt_id", "task", "generation", "revision", "nonce")):
                return False
        except (KeyError, ValueError, TypeError):
            return False
        reachable, absent, status = state.backend._inspect(state.handle)
        return reachable is True and absent is False and status == "running" and self._pins_match(binding.role)

    def execute(self, binding: Binding, operation: str, nonce: str,
                assignment_rev: int | None, commit: str | None) -> dict[str, Any] | None:
        if not self.admitted(binding):
            return None
        state = self.wave.states[binding.role]
        config = {"scripts": self.path, "shared": WAVE_ROOT, "pins": self.pins,
                  "binding": asdict(binding), "operation": operation, "nonce": nonce,
                  "assignment_rev": assignment_rev, "commit": commit,
                  "candidate_uid": CANDIDATE_UID, "candidate_gid": CANDIDATE_GID,
                  "timeout": self.wave.deadline.remaining(10)}
        source = Path(wave_tap_operation.__file__).read_text()
        raw = state.backend.root_output_in_attempt(state.handle, ["python3", "-I", "-S", "-c", source,
            json.dumps(config)], max_bytes=96 * 1024, timeout=self.wave.deadline.remaining(10))
        try:
            receipt = json.loads(raw) if raw is not None else None
            return receipt if isinstance(receipt, dict) else None
        except (ValueError, TypeError):
            return None

    def deliver_turn_nonce(self, role: str, nonce: str) -> bool:
        state = self.wave.states[role]
        path = self.path + "/turn-" + role + ".json"
        if not state.backend.write_root_owned_file_in_attempt(state.handle, path,
                json.dumps({"turn_nonce": nonce}).encode(), mode=0o444,
                timeout=self.wave.deadline.remaining(10)):
            return False
        return state.backend.candidate_can_write_in_attempt(state.handle, path) is False

    def retired(self, binding: Binding) -> bool:
        state = self.wave.states[binding.role]
        remote = self.wave.remote
        return (state.backend.confirm_stopped(state.handle) is Confirmation.CONFIRMED
                and self.wave.remote_backend is not None and remote is not None
                and self.wave.remote_backend.confirm_stopped(remote) is Confirmation.CONFIRMED)
