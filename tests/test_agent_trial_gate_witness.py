"""Production runner/witness composition through real fake-CLI processes.

The fake Docker has no mounts, container interpreter or per-uid protection. This transport
adapter virtualizes only those absent facilities; it never constructs a witness,
answers a readiness nonce, or supplies a grading envelope. Real Docker proof is
separate. The scripted client and receipt fixture are deterministic stand-ins.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from conftest import FAKE_DOCKER_DAEMON_TIMEOUT
from test_agent_trial import (
    GRADER_ROOT,
    _docker_bin,
    _fake_argv,
    _fresh_credential,
    _mapped_home,
    _planned,
)
from test_verify import RECEIPT as INSTALL_RECEIPT
from test_verify import _receipt

from skillc import agent_trial as at
from skillc import docker_backend as d
from skillc import trial, verify, witness_capture
from skillc.backend import Confirmation, ExecuteResult, Limits
from skillc.collection_conformance import TrackingDockerBackend

_HOST_INTERPRETER = sys.executable


def failure_reason(result: Mapping[str, Any]) -> str:
    return f"lifecycle: {result.get('reason')}; grading: {result.get('grading_blocked_reason')}"


@dataclass(frozen=True)
class VirtualMountBackend(TrackingDockerBackend):
    fault: str | None = None
    executed: list[object] = field(default_factory=list, compare=False)
    drained: list[object] = field(default_factory=list, compare=False)

    def _home(self, handle: object) -> Path:
        assert isinstance(handle, d._Handle)
        return Path(self.docker_bin[-1]) / f"{handle.name}.fsroot/home/candidate"

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits,
                        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
                        cwd: str | None = None, env: Mapping[str, str] | None = None,
                        confine_root: str | None = None) -> ExecuteResult:
        assert isinstance(handle, d._Handle)
        args = list(argv)
        if at.TRIGGER_SOCKET_PATH in args:
            index = args.index(at.TRIGGER_SOCKET_PATH)
            assert (len(args) == 6 and index == 3 and args[:2] == ["/usr/bin/python3", "-c"]
                    and "witness_ready" in args[2]), "unexpected readiness invocation"
            # The real image has this pinned interpreter; fake Docker executes
            # host processes, whose Python can live elsewhere (python:slim CI).
            args[0] = _HOST_INTERPRETER
            args[index] = str(d.trigger_socket_host_path_for(self.trigger_socket_dir, handle.name))
            if self.fault == "nonce":
                args[index + 1] = "wrong-controller-nonce"
            elif self.fault == "channel":
                args[index] += ".missing"
        result = super().exec_in_attempt(handle, args, limits, cancel, stdin, cwd, env, confine_root)
        if result.stdout is not None:
            result = replace(result, stdout=result.stdout.replace(str(self._home(handle)).encode(),
                                                                  d.CONTAINER_HOME.encode()))
        return result

    def export(self, handle: object, dest: Path, root: str | None = None) -> None:
        super().export(handle, dest, root)
        # sha256sum inside fake Docker prints host-mapped paths. Virtualize the
        # same path namespace in legacy write-back, for red-before runs too.
        observations = dest / "observations"
        if observations.is_file() and at._TOOLS_MARKER.encode() in observations.read_bytes():
            observations.write_bytes(observations.read_bytes().replace(str(self._home(handle)).encode(),
                                                                       d.CONTAINER_HOME.encode()))

    def resolve_realpath_in_attempt(self, handle: object, path: str, timeout: float = 2.0) -> str | None:
        found = super().resolve_realpath_in_attempt(handle, path, timeout)
        assert isinstance(handle, d._Handle)
        workspace = str(Path(self.docker_bin[-1]) / f"{handle.name}.fsroot/work")
        return found.replace(workspace, d.CONTAINER_WORKSPACE, 1) if found else None

    def candidate_can_write_in_attempt(self, handle: object, path: str, timeout: float | None = None) -> bool | None:
        if path.startswith(at._FLOW_CHECK_GATE_HARNESS_ROOT):
            return False  # fake transport has no distinct root/candidate identities
        return super().candidate_can_write_in_attempt(handle, path, timeout)

    def execute(self, handle: object, argv: Sequence[str], limits: Limits,
                cancel: Callable[[], bool] | None = None, stdin: bytes | None = None) -> ExecuteResult:
        self.executed.append(handle)
        return super().execute(handle, argv, limits, cancel, stdin)

    def trigger_log(self, handle: object) -> list | None:
        self.drained.append(handle)
        if self.fault == "drain" and len(self.drained) == 1:
            raise RuntimeError("first drain failed; retry would falsely succeed (#367)")
        return super().trigger_log(handle)

    def confirm_stopped(self, handle: object) -> Confirmation:
        actual = super().confirm_stopped(handle)
        return Confirmation.UNKNOWN if self.fault == "stop" else actual


def run_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str = "fresh",
             fault: str | None = None, receipt: bool = False, gate: bool = True) -> tuple[dict, list, VirtualMountBackend]:
    base = tmp_path / "work"
    base.mkdir()
    experiment, attempt = _planned(trial.open_store(tmp_path / "store", forbidden=[]))
    state = tmp_path / "docker-state"
    monkeypatch.setattr(at, "_FLOW_CHECK_GATE_HARNESS_ROOT", "/home/candidate/.protected-harness")
    with tempfile.TemporaryDirectory(prefix="sk-witness-") as channel_dir:
        backend = VirtualMountBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(state),
                                      trigger_socket_dir=Path(channel_dir), fault=fault)
        grading = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(state), daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
        home = _mapped_home(state, attempt)
        fake = _fake_argv(fmt="codex-fake", home=home,
                         transcript_relpath=".codex/sessions/2026/01/01/rollout-witness.jsonl",
                         copy_solution=GRADER_ROOT / "reference")
        socket_path = str(d.trigger_socket_host_path_for(Path(channel_dir), d._container_name(attempt)))
        actor = tmp_path / "actor.py"
        actor.write_text(
            "import json,pathlib,runpy,socket,sys\n"
            "sys.argv=sys.argv[1:]\n"
            "try: runpy.run_path(sys.argv[0],run_name='__main__')\n"
            "except SystemExit as exc:\n"
            " if exc.code not in (None,0): raise\n"
            "pathlib.Path('gate-witness.json').write_text('{\"forged\":true}')\n"
            "def ask(gate):\n"
            " with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:\n"
            "  sock.settimeout(5)\n"
            f"  sock.connect({socket_path!r})\n"
            "  sock.sendall((json.dumps(dict(op='run_gate',gate=gate,cwd='/work'))+'\\n').encode())\n"
            "  sock.shutdown(socket.SHUT_WR)\n"
            "  reply=json.loads(sock.makefile('rb').readline())\n"
            "  assert reply['ok'] and reply['result']['reason']=='exited',reply\n"
            + ("ask('flow-check-plan')\n" if gate else "")
            + ("ask('flow-check-summary')\n" if gate and mode != "omit" else "")
            + ("pathlib.Path('later.txt').write_text('changed')\n" if mode in ("stale", "rerun") else "")
            + ("ask('flow-check-summary')\n" if gate and mode == "rerun" else "")
        )
        trusted: list[dict[str, Any]] = []
        real_grade = verify.grade_files

        def observe_grade(*args: Any, **kwargs: Any) -> Any:
            raw = kwargs.get("trusted_observation")
            if raw is not None:
                trusted.append(json.loads(raw))
                assert trusted[-1]["graded_tree_digest"] == witness_capture.files_digest(args[1])
            return real_grade(*args, **kwargs)

        monkeypatch.setattr(verify, "grade_files", observe_grade)
        context = None
        if receipt:
            context = at.InstallationReceiptContext(frozenset({"flow-check"}), "sha256:00", "fixture", "pin",
                                                     "codex-skills", {})
            monkeypatch.setattr(at, "_build_discovery_receipt", lambda **kw: _receipt(
                experiment, attempt, subject={**INSTALL_RECEIPT["subject"], "digest": "sha256:00"}, image={"digest": "sha256:01"}))
        script = b"#!/bin/bash\nprintf 'controller gate output\\n'\n"
        entry = ".claude/scripts/flow-finish-gate.sh"
        result = at.run_one_attempt(
            backend=backend, experiment=experiment, attempt_id=attempt, client="codex",
            base_argv=[sys.executable, str(actor), *fake[1:]], prompt="Fix the slug helper.", skill_name=None,
            surface={}, limits=Limits(timeout=15), base=base, credential_explicit_path=_fresh_credential(tmp_path, "codex"),
            extra_home_files={entry: script} if gate else {},
            verify_home_files={entry: "sha256:" + hashlib.sha256(script).hexdigest()} if gate else {},
            gate_entrypoint=entry if gate else None, receipt_context=context,
            grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=grading,
        )
        assert len(backend.prepared_ids) == 1
        return result, trusted, backend


@pytest.mark.parametrize("receipt", [False, True])
def test_actual_runner_constructs_and_delivers_controller_witness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                receipt: bool) -> None:
    result, trusted, backend = run_case(tmp_path, monkeypatch, receipt=receipt)
    assert result["disposition"] == "captured", failure_reason(result)
    assert len(backend.executed) == 1, failure_reason(result)
    assert len(trusted) == 1
    witness = trusted[0]["witness"]
    assert witness["attempt_id"] == result["attempt_id"]
    assert witness["declared_gates"] == ["flow-check-plan", "flow-check-summary"]
    for gate in witness["gates"].values():
        assert gate["coverage"] == "complete"
        assert len(gate["runs"]) == 1
        assert gate["runs"][0]["tree_digest_at_start"] == trusted[0]["graded_tree_digest"]


def test_actual_runner_without_gate_preserves_ordinary_grading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result, trusted, backend = run_case(tmp_path, monkeypatch, gate=False)
    assert result["disposition"] == "captured"
    assert result["graded"] is not None, result
    assert trusted == []
    assert len(backend.executed) == 1
    assert backend.trigger_decide is None and not backend.witness_io


@pytest.mark.parametrize("fault", ["nonce", "channel"])
def test_actual_readiness_failure_prevents_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    result, trusted, backend = run_case(tmp_path, monkeypatch, fault=fault)
    assert result["disposition"] == "unavailable", result
    assert backend.executed == []
    assert trusted == []
    assert result["graded"] is None
    assert result["grading_blocked_reason"]


@pytest.mark.parametrize("fault", ["drain", "stop"])
def test_actual_finalization_failure_never_delivers_trusted_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    sessions: list[at._WitnessSession] = []
    real_finish = at._WitnessSession.finish

    def twice(session: at._WitnessSession, backend: d.DockerBackend, handle: object,
              experiment: trial.Experiment) -> None:
        sessions.append(session)
        for _ in range(2):
            with pytest.raises((RuntimeError, at.HomeFileVerificationRefused)):
                real_finish(session, backend, handle, experiment)
        assert session.record is None

    monkeypatch.setattr(at._WitnessSession, "finish", twice)
    result, trusted, backend = run_case(tmp_path, monkeypatch, fault=fault)
    assert len(backend.executed) == 1, failure_reason(result)
    assert sessions and sessions[0].failure
    assert len(backend.drained) == (1 if fault == "drain" else 0)
    assert trusted == []
    assert result["graded"] is None
    assert result["grading_blocked_reason"]


@pytest.mark.parametrize("mode", ["omit", "stale", "rerun"])
def test_actual_gate_history_binds_each_call_to_its_own_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    result, trusted, backend = run_case(tmp_path, monkeypatch, mode=mode)
    assert result["disposition"] == "captured", failure_reason(result)
    assert len(backend.executed) == 1 and len(trusted) == 1
    record = trusted[0]
    summary = record["witness"]["gates"]["flow-check-summary"]
    if mode == "omit":
        assert summary["coverage"] == "not-observed" and summary["runs"] == []
    else:
        assert summary["coverage"] == "complete"
        assert summary["runs"][0]["tree_digest_at_start"] != record["graded_tree_digest"]
        assert len(summary["runs"]) == (2 if mode == "rerun" else 1)
        if mode == "rerun":
            assert summary["runs"][-1]["tree_digest_at_start"] == record["graded_tree_digest"]


@pytest.mark.parametrize("fault", [None, "nonce", "channel"])
def test_readiness_runs_without_a_host_container_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None,
) -> None:
    host_interpreter = tmp_path / "host-python"
    host_interpreter.symlink_to(sys.executable)
    monkeypatch.setattr(sys.modules[__name__], "_HOST_INTERPRETER", str(host_interpreter))
    real_exec = d.DockerBackend.exec_in_attempt
    interpreters: list[str] = []
    measurements: list[ExecuteResult] = []

    def host_without_container_python(self: d.DockerBackend, handle: object, argv: Sequence[str],
                                      *args: Any, **kwargs: Any) -> ExecuteResult:
        command = list(argv)
        readiness = len(command) >= 3 and "witness_ready" in command[2]
        if readiness:
            interpreters.append(command[0])
            if command[0] == "/usr/bin/python3":
                # Make the real fake-CLI subprocess encounter the missing host
                # executable, even on developer machines that happen to have it.
                command[0] = str(tmp_path / "missing-host-container-python")
        result = real_exec(self, handle, command, *args, **kwargs)
        if readiness:
            measurements.append(result)
        return result

    monkeypatch.setattr(d.DockerBackend, "exec_in_attempt", host_without_container_python)
    result, trusted, backend = run_case(tmp_path, monkeypatch, fault=fault)
    if fault is None:
        assert result["disposition"] == "captured", failure_reason(result)
        assert len(backend.executed) == len(trusted) == 1
        assert measurements[0].exit_code == 0
        reply = json.loads(measurements[0].stdout or b"")
        assert reply["ok"] is True and len(reply["result"]["nonce"]) == 64
    else:
        assert result["disposition"] == "unavailable", failure_reason(result)
        assert backend.executed == [] and trusted == []
    assert interpreters == [str(host_interpreter)], failure_reason(result)


@pytest.mark.parametrize("fault", ["interpreter", "mode", "script", "arity"])
def test_readiness_translation_refuses_unexpected_invocations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    backend = VirtualMountBackend(image="fake", base_dir=tmp_path)
    handle = d._Handle("attempt", "container", {})
    argv = ["/usr/bin/python3", "-c", "witness_ready", at.TRIGGER_SOCKET_PATH, "nonce", "5"]
    if fault == "arity":
        argv.pop()
    else:
        argv[{"interpreter": 0, "mode": 1, "script": 2}[fault]] = "unexpected"

    def must_not_execute(*args: object, **kwargs: object) -> ExecuteResult:
        pytest.fail("unexpected readiness argv reached external execution")

    monkeypatch.setattr(d.DockerBackend, "exec_in_attempt", must_not_execute)
    with pytest.raises(AssertionError, match="unexpected readiness invocation"):
        backend.exec_in_attempt(handle, argv, Limits(timeout=1))
