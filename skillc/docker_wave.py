"""Several owned Docker role sessions under one completion deadline (#621).

This is a runtime seam, not a study declaration or a wake scheduler (#622).
The runner is intended for scripted actors. Real clients require their own
approved caller; constructing this seam grants no model or credential authority.
All subjects run in Docker. An unavailable daemon never falls back to the host.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import subprocess
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import controller_turns as turns
from . import egress, fixture_overlay, leak
from .backend import BackendUnavailable, Confirmation, ExecuteResult, Limits
from .codex_guard import CodexGuardSession
from .completion import CompletionDeadline, CompletionUnavailable
from .docker_backend import (
    ATTEMPT_LABEL_KEY,
    CANDIDATE_GID,
    CANDIDATE_UID,
    OWNER_LABEL_KEY,
    OWNER_LABEL_VALUE,
    DockerBackend,
    HomeTreeTooLarge,
    _docker_env,
)
from .wave_attachment import WAVE_ROOT, WaveAttachment

ROLE_NAME = re.compile(r"[a-z][a-z0-9-]{0,39}\Z")


@dataclass(frozen=True)
class Role:
    name: str
    argv: tuple[str, ...]
    prompt: str
    timeout: float
    resume_texts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not ROLE_NAME.fullmatch(self.name) or not self.argv or not self.prompt.strip():
            raise ValueError("role requires a logical name, argv and literal prompt")
        # Reuse the closed literal-turn grammar. No agent output is interpreted.
        turns.parse_turns({"version": 1, "by_case": {self.name: [
            {"text": t} for t in self.resume_texts]}}, [self.name])
        if isinstance(self.timeout, bool) or self.timeout <= 0 or not self.timeout < float("inf"):
            raise ValueError("role timeout must be positive and finite")


@dataclass
class RoleState:
    role: Role
    backend: DockerBackend
    handle: object
    guard: CodexGuardSession
    session_id: str | None = None
    executions: list[ExecuteResult] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    stopped: Confirmation = Confirmation.UNKNOWN
    absent: Confirmation = Confirmation.UNKNOWN
    busy: threading.Lock = field(default_factory=threading.Lock, repr=False)


def isolation_verdict(observed: Mapping[str, str | None]) -> str:
    """Only affirmative evidence of a listening peer AND a refused path counts.

    A listener missing before or after the attempted connection is UNKNOWN,
    not evidence of network isolation. Committed controls cover all outcomes.
    """
    if observed.get("connect") == "connected":
        return "FAIL"
    required = {"listener_before": "ready", "listener_after": "ready", "connect": "refused"}
    return "PASS" if all(observed.get(k) == v for k, v in required.items()) else "UNKNOWN"


class DockerWave:
    """Own wave resources, per-role backends and capture through confirmed cleanup.

    The common internal bridge disables inter-container communication. Each role
    also keeps its own existing provider-egress network/proxy. Only the fixture
    git daemon joins those private role networks; roles never join each other's.
    The shared volume is the sole shared filesystem. Projects/homes remain local.
    """

    def __init__(self, *, attempt_id: str, image: str, root: Path, fixture: Path,
                 roles: Sequence[Role], seconds: float, docker_bin: Sequence[str] = ("docker",)) -> None:
        if not ROLE_NAME.fullmatch(attempt_id):
            raise ValueError("attempt_id must be a logical name")
        if len(roles) < 2 or len({r.name for r in roles}) != len(roles):
            raise ValueError("a wave requires at least two uniquely named roles")
        if not fixture.is_dir():
            raise ValueError("fixture must be a controller-owned git checkout")
        root.mkdir(parents=True, exist_ok=False)
        self.attempt_id, self.image, self.root, self.fixture = attempt_id, image, root, fixture
        self.roles = tuple(roles)
        self.deadline = CompletionDeadline.after(seconds)
        self.docker_bin, self.env = tuple(docker_bin), _docker_env()
        self.token = uuid.uuid4().hex
        self.network = f"skillc-wave-{self.token}"
        self.attachment = WaveAttachment(self.network + "-state")
        self.states: dict[str, RoleState] = {}
        self.remote_backend: DockerBackend | None = None
        self.remote: object | None = None
        self.created: list[tuple[str, str]] = []
        self.unknown: list[str] = []
        self.closed = False
        self._prepared = False
        self._write("declaration.json", {"attempt_id": attempt_id, "roles": [asdict(r) for r in roles],
            "deadline": self.deadline.marker(attempt_id), "pid_namespaces": "separate",
            "shared_surfaces": ["wave-state-volume", "fixture-git-remote"],
            "sibling_failure_policy": "continue", "wake": "caller-owned-see-622"})

    def _write(self, name: str, value: object) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")

    def _call(self, argv: Sequence[str], *, cleanup: bool = False) -> bytes:
        timeout = 5.0 if cleanup else self.deadline.remaining(5.0)
        try:
            done = subprocess.run([*self.docker_bin, *argv], env=self.env,
                                  capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendUnavailable("wave daemon operation unavailable") from exc
        if done.returncode:
            # Retain diagnostics privately; never embed a host identity in a public error.
            raise BackendUnavailable("wave daemon operation refused")
        return done.stdout

    def _backend(self, name: str, **kwargs: Any) -> DockerBackend:
        return DockerBackend(image=self.image, base_dir=self.root / name,
                             docker_bin=self.docker_bin, witness_io=True,
                             daemon_timeout=self.deadline.remaining(5.0), **kwargs)

    def _limits(self, cap: float) -> Limits:
        return Limits(timeout=self.deadline.remaining(cap), completion_deadline=self.deadline)

    def _exec(self, backend: DockerBackend, handle: object, argv: Sequence[str]) -> bytes:
        result = backend.exec_in_attempt(handle, argv, self._limits(20))
        if (result.reason != "exited" or result.exit_code != 0 or result.stdout is None
                or result.stdout_truncated or result.stdout_incomplete):
            raise BackendUnavailable("wave setup shell did not complete")
        return result.stdout

    def prepare(self) -> None:
        """Create resources in order; caller MUST close even after this raises."""
        if self.closed or self._prepared or self.created:
            raise ValueError("wave preparation is single-use")
        labels = ["--label", f"{OWNER_LABEL_KEY}={OWNER_LABEL_VALUE}",
                  "--label", f"{ATTEMPT_LABEL_KEY}={self.attempt_id}"]
        # Track before dispatch: a timed-out create may still have allocated it.
        self.created.append(("network", self.network))
        self._call(["network", "create", "--internal", "--opt",
                    "com.docker.network.bridge.enable_icc=false", *labels, self.network])
        self.created.append(("volume", self.attachment.volume))
        self._call(["volume", "create", *labels, self.attachment.volume])
        remote_backend = self._backend("remote", wave_attachment=self.attachment)
        self.remote_backend = remote_backend
        self.remote = remote_backend.prepare(self.attempt_id + "-fixture")
        # No host bind mount; fixture bytes enter this controller-owned container by cp.
        self._call(["exec", "-u", "0", "--", self._name(self.remote), "mkdir", "-p", "/fixture/seed"])
        self._call(["cp", str(self.fixture) + "/.", self._name(self.remote) + ":/fixture/seed"])
        self._call(["exec", "-u", "0", "--", self._name(self.remote), "sh", "-c",
                    ('git clone --bare /fixture/seed /fixture/repo.git && '
                    'git --git-dir=/fixture/repo.git config daemon.receivepack true && '
                    'chown -R "$1:$2" /fixture "$3"'), "sh",
                    str(CANDIDATE_UID), str(CANDIDATE_GID), WAVE_ROOT])
        # git daemon is the only service exposed by the fixture container.
        self._call(["exec", "-d", "--", self._name(self.remote), "git", "daemon", "--reuseaddr",
                    "--export-all", "--enable=receive-pack", "--base-path=/fixture", "/fixture"])
        for role in self.roles:
            guard = CodexGuardSession(self.attempt_id + "-" + role.name)
            backend = self._backend(role.name, egress=True, wave_attachment=self.attachment,
                                    trigger_decide=guard.decide)
            handle = backend.prepare(guard.attempt_id)
            state = RoleState(role, backend, handle, guard)
            self.states[role.name] = state
            self._call(["network", "connect", self.network, self._name(handle)])
            role_network = getattr(handle, "egress_network", None)
            if not isinstance(role_network, str):
                raise BackendUnavailable("role provider-egress network missing")
            self._call(["network", "connect", role_network, self._name(self.remote)])
            address = self._call(egress.proxy_address_argv((), role_network, self._name(self.remote))).decode().strip()
            ipaddress.ip_address(address)
            remote_url = f"git://{address}/repo.git"
            self._exec(backend, handle, ["git", "clone", remote_url, "."])
            fixture_overlay.install_codex_guard(backend, handle, {})
            self._write(role.name + "/setup.json", {"guard_installed": True,
                "credential": "not-delivered-model-free", "project": "independent-clone",
                "wave_root": WAVE_ROOT, "pid_namespace": "private"})
        self._prepared = True

    @staticmethod
    def _name(handle: object) -> str:
        name = getattr(handle, "name", None)
        if not isinstance(name, str):
            raise BackendUnavailable("Docker handle has no owned container identity")
        return name

    def turn(self, role: str, text: str | None = None,
             cancel: Callable[[], bool] | None = None) -> ExecuteResult:
        """One caller-scheduled turn. Failure stops this role alone, never siblings."""
        state = self.states[role]
        if not state.busy.acquire(blocking=False):
            raise ValueError("role already executing")
        try:
            if self.closed or not self._prepared:
                raise ValueError("wave closed or not fully prepared")
            if not state.executions:
                if text is not None:
                    raise ValueError("first turn uses the declared prompt")
                argv = (*state.role.argv, state.role.prompt)
            else:
                if (state.session_id is None or state.executions[-1].reason != "exited"
                        or state.executions[-1].exit_code != 0 or text is None):
                    raise ValueError("role cannot be resumed without a clean turn and its own header")
                # The seam delivers literals authorized by its caller. A dynamic
                # wake caller (#622) must bind its literals in its own declaration.
                turns.parse_turns({"version": 1, "by_case": {role: [{"text": text}]}}, [role])
                argv = turns.resume_argv("codex", state.role.argv, state.session_id, text)
            result = state.backend.execute_turn(state.handle, argv, self._limits(state.role.timeout), cancel)
            index = len(state.executions)
            state.executions.append(result)
            # Never consult the agent's files for session identity.
            if index == 0 and not result.stderr_truncated and not result.stderr_incomplete:
                state.session_id = turns.session_id_from_header(result.stderr)
            elif index and turns.session_id_from_header(result.stderr) != state.session_id:
                state.unknown.append("resume-header-disagrees")
            self._write(f"{role}/turn-{index}.json", {k: v for k, v in asdict(result).items()
                                                    if k not in ("stdout", "stderr")})
            for stream in ("stdout", "stderr"):
                payload = getattr(result, stream)
                if payload is not None:
                    (self.root / role / f"turn-{index}.{stream}").write_bytes(payload)
            return result
        finally:
            state.busy.release()

    def run_scripted(self) -> dict[str, Any]:
        """Concurrent declared actors and literal resumes; no mailbox interpretation."""
        errors: list[BaseException] = []

        def actor(role: Role) -> None:
            try:
                result = self.turn(role.name)
                for text in role.resume_texts:
                    if result.reason != "exited" or result.exit_code != 0:
                        break
                    result = self.turn(role.name, text)
            except BaseException as exc:  # noqa: BLE001 - propagate after all owned threads finish
                self.states[role.name].unknown.append("role-execution-unavailable")
                errors.append(exc)

        threads: list[threading.Thread] = []
        try:
            self.prepare()
            for role in self.roles:
                thread = threading.Thread(target=actor, args=(role,))
                threads.append(thread)
                thread.start()
        except BaseException as exc:  # noqa: BLE001 - preserve after cleanup
            errors.append(exc)
        finally:
            for thread in threads:
                if thread.ident is not None:
                    thread.join()  # execute_turn enforces the common deadline.
            try:
                report = self.close()
            except BaseException as exc:  # noqa: BLE001 - do not mask original failure
                errors.append(exc)
        if errors:
            raise errors[0]
        return report

    def close(self) -> dict[str, Any]:
        """Stop ALL roles before capture, then retire remote and shared resources.

        Cleanup continues after deadline exhaustion but can never certify timely
        completion then. Unreachable observations are UNKNOWN, never absence.
        """
        if self.closed:
            return json.loads((self.root / "report.json").read_text())
        self.closed = True
        for state in self.states.values():
            state.backend.end_attempt(state.handle)
        # An in-flight turn can still be draining its exec stream after Docker
        # stopped. Wait for its controller writes before capturing or reporting.
        for state in self.states.values():
            with state.busy:
                pass
            state.stopped = state.backend.confirm_stopped(state.handle)
        for name, state in self.states.items():
            if state.stopped is not Confirmation.CONFIRMED:
                state.unknown.append("stop-unconfirmed")
            else:
                try:
                    state.backend.export(state.handle, self.root / name / "artifacts")
                    transcripts = state.backend.read_home_tree(state.handle, ".codex/sessions")
                    for payload in transcripts.values():
                        # Backend paths are untrusted input; use a content-addressed filename.
                        digest = hashlib.sha256(payload).hexdigest()
                        (self.root / name / ("transcript-" + digest + ".jsonl")).write_bytes(payload)
                    self._write(name + "/transcripts.json", {rel: hashlib.sha256(data).hexdigest()
                                                              for rel, data in transcripts.items()})
                except (OSError, BackendUnavailable, HomeTreeTooLarge):
                    state.unknown.append("capture-unavailable")
        if self.remote_backend is not None and self.remote is not None:
            try:
                # Controller helper is the sole volume reader after every role stopped.
                self.remote_backend.export(self.remote, self.root / "shared-state", root=WAVE_ROOT)
                self.remote_backend.export(self.remote, self.root / "fixture-remote", root="/fixture/repo.git")
            except (OSError, BackendUnavailable):
                self.unknown.append("shared-capture-unavailable")
            self.remote_backend.end_attempt(self.remote)
            if self.remote_backend.confirm_stopped(self.remote) is not Confirmation.CONFIRMED:
                self.unknown.append("fixture-stop-unconfirmed")
            self.remote_backend.destroy(self.remote)
            if self.remote_backend.confirm_absent(self.remote) is not Confirmation.CONFIRMED:
                self.unknown.append("fixture-removal-unconfirmed")
        # The remote held an endpoint on EVERY role network. Remove it before
        # asking backends to retire those networks, or their removal must fail.
        for name, state in self.states.items():
            try:
                state.backend.destroy(state.handle)
            except (OSError, BackendUnavailable):
                state.unknown.append("destroy-unavailable")
            state.absent = state.backend.confirm_absent(state.handle)
            guard_record = state.guard.finalize()
            try:
                self._write(name + "/guard.json", guard_record)
            except OSError:
                state.unknown.append("guard-publication-unavailable")
        cleanup: dict[str, str] = {}
        for kind, name in reversed(self.created):
            try:
                self._call([kind, "rm", name], cleanup=True)
            except BackendUnavailable:
                pass  # The independent listing below determines absence, not rm's exit.
            try:
                observed = self._call([kind, "ls", "--format", "{{.Name}}"], cleanup=True)
                cleanup[kind] = ("confirmed" if name not in observed.decode().splitlines() else "not-confirmed")
            except (BackendUnavailable, UnicodeError):
                cleanup[kind] = "unknown"
        if len(self.states) != len(self.roles):
            self.unknown.append("planned-role-not-started")
        report: dict[str, Any] = {"attempt_id": self.attempt_id, "status": "UNKNOWN",
            "roles": {name: {"session_id": s.session_id, "stop": s.stopped.value,
                "absent": s.absent.value, "unknown": s.unknown,
                "turns": len(s.executions), "exit_codes": [e.exit_code for e in s.executions],
                "reasons": [e.reason for e in s.executions]} for name, s in self.states.items()},
            "resources": cleanup, "unknown": self.unknown,
            "completion": self.deadline.qualify(self.deadline.marker(self.attempt_id),
                all(s.absent is Confirmation.CONFIRMED and s.stopped is Confirmation.CONFIRMED
                    for s in self.states.values())
                and set(cleanup) == {"network", "volume"}
                and all(v == "confirmed" for v in cleanup.values()) and not self.unknown)}
        # Lifecycle evidence only: task success, isolation, guard/egress controls,
        # transcript coverage and CPP peer liveness are separate observations.
        report["scope"] = "runtime-lifecycle-only"
        try:
            self.deadline.remaining(1)
        except CompletionUnavailable:
            self.unknown.append("completion-deadline-exhausted")
        self._write("report.json", report)
        scan = leak.scan_path(self.root, leak.load_denylist(), host_paths=leak.default_host_paths())
        report["leak_check"] = {"findings": len(scan.findings), "skipped": scan.skipped}
        report["completion"] = self.deadline.qualify(self.deadline.marker(self.attempt_id),
            report["completion"]["cleanup_confirmed"])
        if not report["completion"]["on_time"] and "completion-deadline-exhausted" not in self.unknown:
            self.unknown.append("completion-deadline-exhausted")
        report["completion_scope"] = "through-provisional-report-and-leak-scan"
        report["final_decision_emission"] = "outside-completion-deadline"
        self._write("report.json", report)
        return report
