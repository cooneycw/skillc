"""#508: the project gate witnessed by the attempt's ONE GateWitness.

Each red here is a condition of the #508 gate: the staged gate records the
controller's own stage outcomes; a non-gate invocation creates no run; the
pass-through log never reaches what grading reads; one witness owns every
gate exec; controller execs never carry the shim directory, and the agent's
exec always does; and the shim's PATH position can never shadow the
nested-codex guard.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from test_make_gate_shim import SCRIPTS, SHIM, _StageBackend, declaration

from skillc import agent_trial, trial
from skillc import fixture_overlay as fo
from skillc import project_gate as pg
from skillc.backend import ExecuteResult, Limits
from skillc.decide_reply_channel import ChannelRefusal
from skillc.gate_witness import GateWitness

ROOT = Path(__file__).resolve().parent.parent


class _WitnessBackend(_StageBackend):
    def resolve_realpath_in_attempt(self, handle: object, path: str) -> str:
        return path


def _witness(codes: Mapping[str, int], **kwargs: Any) -> tuple[GateWitness, _WitnessBackend]:
    backend = _WitnessBackend(codes)
    witness = GateWitness(
        declared_gates={pg.GATE: [pg.REAL_MAKE, "check"], "flow-auto-finish": ["bash", "gate.sh"]},
        tree_digest_fn=lambda: "sha256:" + "0" * 64, backend=backend, handle=None,  # type: ignore[arg-type]
        limits=Limits(timeout=5), gate_exclusivity=False, exclusivity_basis="bypass is not excluded",
        workspace_root="/work", staged={pg.GATE: pg.StagedRunner(declaration())}, **kwargs)
    return witness, backend


def test_a_witnessed_make_check_records_the_controllers_stage_outcomes() -> None:
    witness, backend = _witness({"lint": 0, "test": 1, "typecheck": 0})
    reply = witness.decide({"op": "run_gate", "gate": pg.GATE, "cwd": "/work", "make_args": ["check"]})
    assert reply["accepted"] is True and reply["exit_code"] == pg.MAKE_FAILURE_EXIT
    assert "make: *** [Makefile:7: test] Error 1" in str(reply["stderr"])
    [run] = json.loads(witness.finalize("a-1").to_json_bytes())["gates"][pg.GATE]["runs"]
    assert run["exit_code"] == 2 and run["reason"] == "exited"
    assert run["stages"]["status"] == "captured" and run["stages"]["cwd"] == "/work"
    assert {k: v["outcome"] for k, v in run["stages"]["stages"].items()} == {
        "lint": "passed", "test": "failed", "typecheck": "not-run"}
    assert ["python3", SCRIPTS["typecheck"]] not in backend.calls  # stopped at the first failure


def test_a_non_gate_invocation_creates_no_run_and_is_never_refused() -> None:
    witness, backend = _witness({"lint": 0, "test": 0, "typecheck": 0})
    reply = witness.decide({"op": "run_gate", "gate": pg.GATE, "cwd": "/work", "make_args": ["-k", "clean"]})
    assert reply == {"accepted": False, "passthrough": True, "reason": "not a gate invocation"}
    assert backend.calls == []
    record = witness.finalize("a-1")
    assert record.gates[pg.GATE].runs == () and record.gates[pg.GATE].coverage == "not-observed"


def test_make_args_are_refused_on_a_gate_that_is_not_staged() -> None:
    witness, _backend = _witness({"lint": 0, "test": 0, "typecheck": 0})
    with pytest.raises(ChannelRefusal, match="takes no make_args or make_env"):
        witness.decide({"op": "run_gate", "gate": "flow-auto-finish", "make_args": ["check"]})


@pytest.mark.parametrize("kwargs", [
    {"staged": {"undeclared": pg.StagedRunner(declaration())}},
    {"stage_capture": {pg.GATE: lambda out, code: {}}},
])
def test_a_staged_gate_must_be_declared_and_cannot_also_read_stdout(kwargs: dict[str, Any]) -> None:
    staged = kwargs.pop("staged", {pg.GATE: pg.StagedRunner(declaration())})
    with pytest.raises(ValueError):
        GateWitness(declared_gates={pg.GATE: [pg.REAL_MAKE]}, tree_digest_fn=lambda: "d",
                    backend=_WitnessBackend({}), handle=None, limits=Limits(timeout=5),  # type: ignore[arg-type]
                    gate_exclusivity=False, exclusivity_basis="b", staged=staged, **kwargs)


# ------------------------------------------- the pass-through log is never evidence

MARKER = "passthrough-marker-6f1c"


def _session() -> agent_trial._WitnessSession:
    session = agent_trial._WitnessSession("a-1", Limits(timeout=5), gate_args={}, project_gate=declaration())
    session.witness, _backend = _witness({"lint": 0, "test": 0, "typecheck": 0})
    session.ready = True
    return session


def test_the_pass_through_log_never_reaches_what_grading_reads() -> None:
    """The red the gate asked for: what grading receives is the gate-witness
    record (verify builds its trusted envelope from it alone); the shim's
    subject-reported log must not be in it."""
    session = _session()
    assert session.decide({"op": pg.PASSTHROUGH_OP, "argv": [MARKER], "cwd": "/work", "exit_code": 0,
                           "why": "not-a-gate-invocation"}) == {"logged": True}
    assert session.passthrough_log[0]["argv"] == [MARKER] and session.passthrough_log[0]["subject_reported"]
    assert session.witness is not None
    record = session.witness.finalize("a-1")
    envelope = trial.canonical({"witness": json.loads(record.to_json_bytes()), "graded_tree_digest": "x"})
    assert MARKER.encode() not in record.to_json_bytes()
    assert MARKER.encode() not in envelope
    # The scan can find it: the same canonical form, with the log in it.
    assert MARKER.encode() in trial.canonical({"log": session.passthrough_log})


def test_the_envelope_is_built_from_the_witness_record_alone() -> None:
    """Guards the premise above: if verify ever widened the envelope beyond
    the witness record and the extras, this would need a new red."""
    source = (ROOT / "skillc" / "verify.py").read_text()
    assert '"witness": json.loads(gate_witness.to_json_bytes()),' in source
    assert "passthrough" not in source


@pytest.mark.parametrize("request_", [
    {"op": pg.PASSTHROUGH_OP, "argv": "make", "cwd": "/w", "exit_code": 0, "why": "x"},
    {"op": pg.PASSTHROUGH_OP, "argv": ["x"] * 65, "cwd": "/w", "exit_code": 0, "why": "x"},
    {"op": pg.PASSTHROUGH_OP, "argv": [], "cwd": "/w", "exit_code": True, "why": "x"},
    {"op": pg.PASSTHROUGH_OP, "argv": [], "cwd": "/w", "exit_code": 0, "why": "x" * 129},
])
def test_a_malformed_pass_through_log_is_refused(request_: dict[str, object]) -> None:
    with pytest.raises(ChannelRefusal):
        _session().decide(request_)


def test_the_pass_through_log_is_bounded() -> None:
    session = _session()
    entry = {"op": pg.PASSTHROUGH_OP, "argv": [], "cwd": "/w", "exit_code": 0, "why": "x"}
    for _ in range(pg.MAX_PASSTHROUGH_LOG):
        session.decide(entry)
    assert session.decide(entry) == {"logged": False, "reason": "the pass-through log is full"}
    assert len(session.passthrough_log) == pg.MAX_PASSTHROUGH_LOG


def test_an_attempt_without_a_project_gate_takes_no_pass_through_log() -> None:
    session = _session()
    session.project_gate = None
    with pytest.raises(ChannelRefusal):
        session.decide({"op": pg.PASSTHROUGH_OP, "argv": [], "cwd": "/w", "exit_code": 0, "why": "x"})


# ------------------------------------------------ one witness owns every gate exec

def test_a_second_witness_is_refused() -> None:
    """The cross-gate order is ONE witness's `_exec_lock` (#508 condition 4)."""
    session = _session()
    with pytest.raises(agent_trial.HomeFileVerificationRefused, match="bound once"):
        session.bind_and_check(object(), object())  # type: ignore[arg-type]


def test_skillc_constructs_a_gate_witness_at_exactly_one_site() -> None:
    sites = []
    for path in sorted((ROOT / "skillc").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "GateWitness":
                sites.append(f"{path.name}:{node.lineno}")
    assert len(sites) == 1 and sites[0].startswith("agent_trial.py:"), sites


# ------------------------------------- PATH: the agent's exec only, never a controller's

def test_controller_gate_execs_never_carry_the_shim_directory() -> None:
    session = _session()
    session.environment = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"}
    assert pg.SHIM_DIR not in session.gate_environment()["PATH"]
    assert pg.agent_path(session.environment).split(":")[0] == pg.SHIM_DIR


def test_only_execute_passes_the_agent_exec_env() -> None:
    """`exec_env` reaches `_launch_and_wait` from `execute()` alone; every
    controller exec (`exec_in_attempt`, `controller_output`) goes without it."""
    tree = ast.parse((ROOT / "skillc" / "docker_backend.py").read_text())
    callers = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "_launch_and_wait"
                        and any(k.arg == "exec_env" for k in node.keywords)):
                    callers.append(fn.name)
    assert callers == ["execute"]


def test_the_agent_exec_env_becomes_explicit_docker_exec_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from skillc import docker_backend as db

    seen: list[list[str]] = []

    def popen(argv: list[str], **kwargs: Any) -> Any:
        seen.append(list(argv))
        raise OSError("not launched in a unit test")

    monkeypatch.setattr(db.subprocess, "Popen", popen)
    backend = db.DockerBackend(image="img", base_dir=tmp_path)
    handle = db._Handle.__new__(db._Handle)
    object.__setattr__(handle, "name", "c-1")
    object.__setattr__(handle, "env", {})
    for env in ({"PATH": f"{pg.SHIM_DIR}:/usr/bin"}, None):
        backend._launch_and_wait(handle, ["true"], Limits(timeout=5), None, None, prefix_wrap=False, exec_env=env)
    with_env, without = seen
    assert with_env[with_env.index("--") - 2:with_env.index("--")] == ["-e", f"PATH={pg.SHIM_DIR}:/usr/bin"]
    assert "-e" not in without[:without.index("--")]


def _serve(path: Path, requests: list[dict[str, object]]) -> None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.listen()

    def loop() -> None:
        while True:
            conn, _ = sock.accept()
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                requests.append(json.loads(data))
                reply = {"accepted": False, "passthrough": True} if requests[-1]["op"] == "run_gate" else {}
                conn.sendall((json.dumps({"ok": True, "result": reply}) + "\n").encode())

    threading.Thread(target=loop, daemon=True).start()


def test_a_nested_make_reenters_the_channel_only_with_the_shim_directory_on_path(tmp_path: Path) -> None:
    """The property behind controller-only PATH, and its red: a gate plan that
    calls `make lint` makes ZERO channel requests under the controller's env,
    and a nested `run_gate` once the shim directory is first on PATH."""
    shim_dir = tmp_path / "make-shim"
    shim_dir.mkdir()
    (shim_dir / "make").write_text(f'#!/bin/sh\nexec {sys.executable} -I {SHIM} "$@"\n')
    (shim_dir / "make").chmod(0o755)
    requests: list[dict[str, object]] = []
    _serve(tmp_path / "s", requests)
    base = os.environ.get("PATH", os.defpath)
    plan = ["sh", "-c", "make lint >/dev/null 2>&1; true"]
    env = {"PATH": base, "SKILLC_TRIGGER_SOCKET": str(tmp_path / "s")}
    subprocess.run(plan, env=env, cwd=tmp_path, check=True, timeout=60)
    assert [r for r in requests if r["op"] == "run_gate"] == []
    subprocess.run(plan, env={**env, "PATH": f"{shim_dir}:{base}"}, cwd=tmp_path, check=True, timeout=60)
    assert [r["make_args"] for r in requests if r["op"] == "run_gate"] == [["lint"]]


# ------------------------------------------------ the overlay, and the codex guard

class _FakeAttempt:
    """A file table, a candidate-writable set and the overlay's exact probes."""

    def __init__(self) -> None:
        self.witness_io = True
        self.files: dict[str, bytes] = {fo.CODEX_GUARD_PATH: b"guard", "/usr/local/bin/codex": b"real"}
        self.writable: set[str] = set()

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits, cancel: object = None,
                        stdin: bytes | None = None, cwd: str | None = None,
                        env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
        def ok(out: bytes, code: int = 0) -> ExecuteResult:
            return ExecuteResult(reason="exited", exit_code=code, stdout=out, stderr=b"")

        if argv[0] == "cat":
            return ok(self.files[argv[-1]])
        if argv[0] == "ls":
            prefix = argv[-1] + "/"
            return ok(b"".join(f"{p[len(prefix):]}\n".encode() for p in sorted(self.files) if p.startswith(prefix)))
        if argv[0] == "sh" and "command -v" in argv[2]:
            for directory in (env or {})["PATH"].split(":"):
                if f"{directory}/{argv[-1]}" in self.files:
                    return ok(f"{directory}/{argv[-1]}\n".encode())
            return ok(b"", 1)
        if argv[0] == "sh":
            return ok(b"present\n" if argv[-1] in self.files else b"absent\n")
        raise AssertionError(f"unexpected probe {argv!r}")

    def write_root_owned_file_in_attempt(self, handle: object, path: str, content: bytes, mode: int = 0o755) -> bool:
        self.files[path] = content
        return True

    def candidate_can_write_in_attempt(self, handle: object, path: str) -> bool | None:
        return path in self.writable


ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"}


def test_the_shim_is_placed_verified_and_leaves_the_guard_first() -> None:
    attempt = _FakeAttempt()
    placed = pg.install_make_shim(attempt, object(), ENV)
    assert placed.path == pg.SHIM_PATH
    assert placed.digest == hashlib.sha256(SHIM.read_bytes()).hexdigest()
    pg.verify_agent_path(attempt, object(), ENV, codex_guard=fo.CODEX_GUARD_PATH)


@pytest.mark.parametrize("break_", ["pre-planted", "writable-dir", "writable-harness-root", "extra-file",
                                    "codex-in-shim-dir", "guard-shadowed"])
def test_every_unsafe_shim_placement_is_refused(break_: str) -> None:
    attempt = _FakeAttempt()
    if break_ == "pre-planted":
        attempt.files[pg.SHIM_PATH] = b"subject's own"
    elif break_ == "writable-dir":
        attempt.writable.add(pg.SHIM_DIR)
    elif break_ == "writable-harness-root":
        attempt.writable.add(os.path.dirname(pg.SHIM_DIR))
    elif break_ == "extra-file":
        attempt.files[f"{pg.SHIM_DIR}/gcc"] = b"x"
    if break_ in ("codex-in-shim-dir", "guard-shadowed"):
        pg.install_make_shim(attempt, object(), ENV)
        if break_ == "codex-in-shim-dir":
            attempt.files[f"{pg.SHIM_DIR}/codex"] = b"x"
        else:
            del attempt.files[fo.CODEX_GUARD_PATH]  # codex now resolves to the real one
        with pytest.raises(fo.OverlayRefused):
            pg.verify_agent_path(attempt, object(), ENV, codex_guard=fo.CODEX_GUARD_PATH)
        return
    with pytest.raises(fo.OverlayRefused):
        pg.install_make_shim(attempt, object(), ENV)


def test_a_staged_reply_carries_make_s_bytes_exactly() -> None:
    class Binary(_WitnessBackend):
        def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                            stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
            if argv[-1] == SCRIPTS["lint"]:
                return ExecuteResult(reason="exited", exit_code=0, stdout=b"\xff\xfe raw\n", stderr=b"")
            return super().exec_in_attempt(handle, argv, limits, cwd=cwd, env=env, confine_root=confine_root)

    witness, _backend = _witness({"lint": 0, "test": 0, "typecheck": 0})
    witness._backend = Binary({"lint": 0, "test": 0, "typecheck": 0})  # type: ignore[assignment]
    reply = witness.decide({"op": "run_gate", "gate": pg.GATE, "cwd": "/work", "make_args": ["lint"]})
    assert base64.b64decode(str(reply["stdout_b64"])) == b"python3 ci/lint.py\n\xff\xfe raw\n"


def test_an_oversized_aggregate_is_refused_by_the_witness_never_sliced() -> None:
    class Chatty(_WitnessBackend):
        def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                            stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
            if argv[-1] in SCRIPTS.values():
                return ExecuteResult(reason="exited", exit_code=0, stdout=b"x" * 200, stderr=b"")
            return super().exec_in_attempt(handle, argv, limits, cwd=cwd, env=env, confine_root=confine_root)

    witness, _backend = _witness({})
    witness._backend = Chatty({})  # type: ignore[assignment]
    witness._limits = Limits(timeout=5, max_captured_stdout_bytes=256)
    with pytest.raises(ChannelRefusal, match="missing or incomplete"):
        witness.decide({"op": "run_gate", "gate": pg.GATE, "cwd": "/work", "make_args": ["check"]})
    assert witness.channel_unavailable is True
