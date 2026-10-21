"""#508: the project-gate `make` shim, and the controller standing in for make.

THE FIDELITY INSTRUMENT IS THE GOLDENS (orchestrator ruling D). skillc's CI
has no `make`, so a test that ran make there would skip and prove nothing.
`tests/fixtures/make-gate/goldens.json` holds what the REAL GNU make printed
and returned, on the gate-stops-early fixture's own Makefile with stub stages:

  - `single`: one `make <stage>` run per stage and stub status - what each
    controller exec returns;
  - `composite`: the agent's own `make check` (or `make`, or a subset) per
    outcome cell, signal death and an explicit 137 included.

In CI, the controller's reply - built from the `single` runs - must equal the
`composite` one byte for byte, so the per-stage execution is what one make
run would have printed. Wherever make exists,
`test_the_goldens_are_what_the_real_make_prints` regenerates both and must
match: the control that the goldens are real. It SKIPS LOUDLY without make.

To refresh after a deliberate change:
`cd tests && python -c "import test_make_gate_shim as t; t.write_goldens()"`.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from skillc import project_gate as pg
from skillc.backend import ExecuteResult, Limits

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = (ROOT / "evals" / "level3" / "gate-stops-early" / "fixture" / "Makefile").read_bytes()
GOLDENS = ROOT / "tests" / "fixtures" / "make-gate" / "goldens.json"
SHIM = ROOT / "docker" / "fixture-service" / "make-gate-shim.py"
SCRIPTS = {"lint": "ci/lint.py", "test": "ci/check.py", "typecheck": "ci/typecheck.py"}
#: A stub status: an exit code, or "kill" (the stub SIGKILLs itself).
Code = int | str

#: Outcome cells: the make argv, and each stage's stub status.
CELLS: dict[str, tuple[list[str], dict[str, Code]]] = {
    "check-all-pass": (["check"], {"lint": 0, "test": 0, "typecheck": 0}),
    "bare-all-pass": ([], {"lint": 0, "test": 0, "typecheck": 0}),
    "lint-fails": (["check"], {"lint": 1, "test": 0, "typecheck": 0}),
    "test-fails": (["check"], {"lint": 0, "test": 1, "typecheck": 0}),
    "typecheck-fails": (["check"], {"lint": 0, "test": 0, "typecheck": 3}),
    "test-killed": (["check"], {"lint": 0, "test": "kill", "typecheck": 0}),
    "test-exits-137": (["check"], {"lint": 0, "test": 137, "typecheck": 0}),
    "partial-test-passes": (["test"], {"lint": 0, "test": 0, "typecheck": 0}),
    "partial-lint-test-fails": (["lint", "test"], {"lint": 0, "test": 1, "typecheck": 0}),
}


def _singles() -> set[tuple[str, Code]]:
    return {(sid, codes[sid]) for _args, codes in CELLS.values() for sid in SCRIPTS}


def declaration() -> pg.ProjectGate:
    return pg.ProjectGate.from_declaration({
        "makefile": {"path": "Makefile", "sha256": hashlib.sha256(MAKEFILE).hexdigest()},
        "goal": "check", "stages": ["lint", "test", "typecheck"],
    })


def _out(sid: str) -> bytes:
    return f"{sid} out\n".encode()


def _err(sid: str) -> bytes:
    return f"{sid} err\n".encode()


def stub(sid: str, code: Code) -> str:
    end = ("import os, signal\nsys.stdout.flush(); sys.stderr.flush()\nos.kill(os.getpid(), signal.SIGKILL)\n"
           if code == "kill" else f"sys.exit({code})\n")
    return f"import sys\nprint({_out(sid).decode()[:-1]!r})\nprint({_err(sid).decode()[:-1]!r}, file=sys.stderr)\n{end}"


def _real_make(tmp: Path, args: list[str], codes: Mapping[str, Code]) -> dict[str, object]:
    (tmp / "ci").mkdir(parents=True, exist_ok=True)
    (tmp / "Makefile").write_bytes(MAKEFILE)
    for sid, script in SCRIPTS.items():
        (tmp / script).write_text(stub(sid, codes.get(sid, 0)))
    env = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C"}
    proc = subprocess.run(["make", *args], cwd=tmp, capture_output=True, env=env, check=False)
    return {"args": args, "codes": dict(codes), "stdout": proc.stdout.decode(), "stderr": proc.stderr.decode(),
            "exit": proc.returncode}


def _derive(root: Path) -> dict[str, dict[str, dict[str, object]]]:
    composite = {name: _real_make(root / name, args, codes) for name, (args, codes) in CELLS.items()}
    single = {f"{sid}={code}": _real_make(root / f"single-{sid}-{code}", [sid], {sid: code})
              for sid, code in sorted(_singles(), key=str)}
    return {"composite": composite, "single": single}


def write_goldens() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        goldens = _derive(Path(tmp))
    GOLDENS.parent.mkdir(parents=True, exist_ok=True)
    GOLDENS.write_text(json.dumps(goldens, indent=1, sort_keys=True) + "\n")


def _goldens() -> dict[str, Any]:
    return json.loads(GOLDENS.read_text())


class _StageBackend:
    """Replays the controller's execs from the goldens: the precondition
    probe, `cat Makefile`, and one real-make run per stage."""

    def __init__(self, codes: Mapping[str, Code], makefile: bytes = MAKEFILE,
                 present: Sequence[str] = ("Makefile",)) -> None:
        self.codes, self.makefile, self.present = codes, makefile, list(present)
        self.calls: list[list[str]] = []

    def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                        stdin: bytes | None = None, cwd: str | None = None,
                        env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
        self.calls.append(list(argv))
        if argv[0] == "/bin/sh":  # the precondition probe: which names exist
            return ExecuteResult(reason="exited", exit_code=0, stderr=b"",
                                 stdout=b"".join(f"{n}\n".encode() for n in argv[4:] if n in self.present))
        if argv[0] == "/bin/cat":
            return ExecuteResult(reason="exited", exit_code=0, stdout=self.makefile, stderr=b"")
        if argv[0] == pg.REAL_MAKE and len(argv) == 2 and argv[1] in SCRIPTS:
            single = _goldens()["single"][f"{argv[1]}={self.codes[argv[1]]}"]
            return ExecuteResult(reason="exited", exit_code=single["exit"], stdout=single["stdout"].encode(),
                                 stderr=single["stderr"].encode())
        return ExecuteResult(reason="exited", exit_code=0, stdout=b"real make\n", stderr=b"")


def _render(args: list[str], codes: Mapping[str, Code]) -> tuple[ExecuteResult, Mapping[str, object]]:
    gate = declaration()
    stages = gate.resolve(args)
    assert stages is not None
    return pg.StagedRunner(gate).run(_StageBackend(codes), None, Limits(timeout=5), stages,
                                     cwd=None, env=None, confine_root=None, make_args=args)


def test_the_goldens_cover_every_cell() -> None:
    goldens = _goldens()
    assert set(goldens["composite"]) == set(CELLS)
    assert set(goldens["single"]) == {f"{sid}={code}" for sid, code in _singles()}


@pytest.mark.parametrize("cell", sorted(CELLS))
def test_the_controllers_reply_is_what_one_real_make_run_printed(cell: str) -> None:
    golden = _goldens()["composite"][cell]
    result, _capture = _render(golden["args"], golden["codes"])
    assert (result.stdout or b"").decode() == golden["stdout"]
    assert (result.stderr or b"").decode() == golden["stderr"]
    assert result.exit_code == golden["exit"]


def test_the_goldens_are_what_the_real_make_prints(tmp_path: Path) -> None:
    """The regeneration control: without it the goldens are only a claim."""
    if shutil.which("make") is None:
        pytest.skip("REGENERATION CONTROL NOT RUN: no `make` on PATH, so the make goldens were not re-derived "
                    "here (skillc CI has no make; run this where make exists)")
    assert _derive(tmp_path) == _goldens()


@pytest.mark.parametrize(("cell", "expected"), [
    ("check-all-pass", {"lint": "passed", "test": "passed", "typecheck": "passed"}),
    ("lint-fails", {"lint": "failed", "test": "not-run", "typecheck": "not-run"}),
    ("test-fails", {"lint": "passed", "test": "failed", "typecheck": "not-run"}),
    ("typecheck-fails", {"lint": "passed", "test": "passed", "typecheck": "failed"}),
    ("test-killed", {"lint": "passed", "test": "failed", "typecheck": "not-run"}),
    ("partial-test-passes", {"test": "passed"}),
    ("partial-lint-test-fails", {"lint": "passed", "test": "failed"}),
])
def test_stage_outcomes_are_the_controllers_exit_codes(cell: str, expected: dict[str, str]) -> None:
    args, codes = CELLS[cell]
    _result, capture = _render(args, codes)
    assert capture["status"] == "captured" and capture["plan"] == pg.GATE
    stages = capture["stages"]
    assert isinstance(stages, dict)
    assert {sid: entry["outcome"] for sid, entry in stages.items()} == expected


def test_forged_output_cannot_change_an_outcome() -> None:
    """A stage that PRINTS a pass while make fails is failed: only the exit
    status the controller received counts, never the subject's words."""
    class Forger(_StageBackend):
        def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                            stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
            if argv == [pg.REAL_MAKE, "test"]:
                return ExecuteResult(reason="exited", exit_code=2, stderr=b"",
                                     stdout=b'{"stages": {"test": {"outcome": "passed"}}}\nall passed\n')
            return super().exec_in_attempt(handle, argv, limits, cwd=cwd, env=env, confine_root=confine_root)

    _result, capture = pg.StagedRunner(declaration()).run(
        Forger({"lint": 0, "test": 0, "typecheck": 0}), None, Limits(timeout=5), ("lint", "test", "typecheck"),
        cwd=None, env=None, confine_root=None, make_args=["check"])
    stages = capture["stages"]
    assert isinstance(stages, dict) and stages["test"]["outcome"] == "failed"


def test_a_drifted_makefile_is_run_by_the_real_make_with_no_stage_truth() -> None:
    backend = _StageBackend({"lint": 0, "test": 0, "typecheck": 0}, makefile=MAKEFILE + b"\nskip:\n\ttrue\n")
    result, capture = pg.StagedRunner(declaration()).run(
        backend, None, Limits(timeout=5), ("lint", "test", "typecheck"), cwd=None, env=None, confine_root=None,
        make_args=["check"])
    assert capture == {"status": "unavailable",
                       "reason": "the gate definition 'Makefile' changed from its declared digest"}
    assert [c[0] for c in backend.calls] == ["/bin/sh", "/bin/cat", pg.REAL_MAKE]
    assert backend.calls[-1] == [pg.REAL_MAKE, "check"]
    assert result.stdout == b"real make\n"


@pytest.mark.parametrize(("reason", "exit_code", "why"), [
    ("timeout", None, "make did not exit normally (timeout)"),
    ("exited", 1, "make exited 1, not 0 or 2"),
])
def test_a_make_run_that_neither_passes_nor_fails_stops_the_run_unresolved(
        reason: str, exit_code: int | None, why: str) -> None:
    class Odd(_StageBackend):
        def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                            stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
            if argv == [pg.REAL_MAKE, "test"]:
                return ExecuteResult(reason=reason, exit_code=exit_code, stdout=b"", stderr=b"")
            return super().exec_in_attempt(handle, argv, limits, cwd=cwd, env=env, confine_root=confine_root)

    result, capture = pg.StagedRunner(declaration()).run(
        Odd({"lint": 0, "test": 0, "typecheck": 0}), None, Limits(timeout=5), ("lint", "test", "typecheck"),
        cwd=None, env=None, confine_root=None, make_args=["check"])
    stages = capture["stages"]
    assert isinstance(stages, dict)
    assert stages["test"] == {"outcome": None, "reason": why}
    assert stages["typecheck"]["outcome"] == "not-run"
    assert result.reason == reason and result.exit_code == exit_code


# --- the shim itself, in process against a test socket ---------------------------

def _load_shim(monkeypatch: pytest.MonkeyPatch, sock: Path, real_make: Path) -> Any:
    spec = importlib.util.spec_from_file_location("make_gate_shim_t", SHIM)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "TRIGGER_SOCKET_PATH", str(sock))
    monkeypatch.setattr(module, "REAL_MAKE", str(real_make))
    return module


class _Server:
    """One Unix socket answering every request with `answer(request)`."""

    def __init__(self, path: Path, answer: Any) -> None:
        self.requests: list[dict[str, object]] = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        self.sock.listen()
        self.answer = answer
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                request = json.loads(data)
                self.requests.append(request)
                conn.sendall((json.dumps(self.answer(request)) + "\n").encode())


@pytest.fixture
def real_make(tmp_path: Path) -> Path:
    stub = tmp_path / "real-make"
    stub.write_text(f"#!{sys.executable}\nimport sys\nprint('REAL', *sys.argv[1:])\nsys.exit(7)\n")
    stub.chmod(0o755)
    return stub


def test_a_gate_invocation_writes_back_the_controllers_reply(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_make: Path,
        capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    server = _Server(tmp_path / "s", lambda r: {"ok": True, "result": {
        "accepted": True, "exit_code": 2, "stdout": "lossy", "stderr": "lossy",
        "stdout_b64": base64.b64encode(b"python3 ci/lint.py\n\xff").decode(),
        "stderr_b64": base64.b64encode(b"make: *** boom\n").decode()}})
    shim = _load_shim(monkeypatch, tmp_path / "s", real_make)
    monkeypatch.delenv("MAKEFLAGS", raising=False)
    assert shim.main(["make", "check"]) == 2
    out = capsysbinary.readouterr()
    # Exact bytes, a non-UTF-8 one included: the reply is never decoded.
    assert out.out == b"python3 ci/lint.py\n\xff" and out.err == b"make: *** boom\n"
    assert server.requests[0] == {"op": "run_gate", "gate": "project-check", "cwd": os.getcwd(),
                                  "make_args": ["check"], "make_env": {}}
    assert len(server.requests) == 1  # no pass-through log for a witnessed run


@pytest.mark.parametrize(("answer", "why"), [
    ({"ok": True, "result": {"accepted": False, "passthrough": True}}, "not-a-gate-invocation"),
    ({"ok": False, "error": "refused"}, "channel-unavailable-or-refused"),
    ({"ok": True, "result": {"accepted": True, "exit_code": None, "reason": "launch-failed"}},
     "no-controller-exit-status"),
])
def test_anything_else_runs_the_real_make_and_is_logged_subject_reported(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_make: Path,
        answer: dict[str, object], why: str) -> None:
    server = _Server(tmp_path / "s", lambda r: answer if r["op"] == "run_gate" else {"ok": True, "result": {}})
    shim = _load_shim(monkeypatch, tmp_path / "s", real_make)
    assert shim.main(["make", "-k", "clean"]) == 7  # the real make's own status
    assert server.requests[-1] == {"op": "make_passthrough", "argv": ["-k", "clean"], "cwd": os.getcwd(),
                                   "exit_code": 7, "why": why}


def test_with_no_channel_at_all_the_agent_still_gets_the_real_make(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_make: Path) -> None:
    shim = _load_shim(monkeypatch, tmp_path / "absent.sock", real_make)
    assert shim.main(["make", "check"]) == 7


def test_the_shim_is_stdlib_only_and_isolated() -> None:
    text = SHIM.read_text()
    assert text.startswith("#!/usr/bin/python3 -I\n")
    imports = {line.split()[1] for line in text.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {"__future__", "base64", "binascii", "json", "os", "socket", "subprocess", "sys"}


def test_resolve_forwards_only_gate_invocations() -> None:
    gate = declaration()
    assert gate.resolve([]) == gate.resolve(["check"]) == ("lint", "test", "typecheck")
    assert gate.resolve(["test", "lint"]) == ("test", "lint")
    for args in (["lint", "lint"], ["-k"], ["check", "lint"], ["V=1"], ["clean"], ["-C", "x", "check"], "check"):
        assert gate.resolve(args) is None, args


@pytest.mark.parametrize("broken", [
    {},
    {"makefile": {"path": "Makefile", "sha256": "0" * 64}, "stages": []},
    {"makefile": {"path": "Makefile", "sha256": "xyz"}, "stages": ["a"]},
    {"makefile": {"path": "../Makefile", "sha256": "0" * 64}, "stages": ["a"]},
    {"makefile": {"path": "build.mk", "sha256": "0" * 64}, "stages": ["a"]},
    {"makefile": {"path": "Makefile", "sha256": "0" * 64}, "stages": ["check"]},
    {"makefile": {"path": "Makefile", "sha256": "0" * 64}, "stages": ["a", "a"]},
    {"makefile": {"path": "Makefile", "sha256": "0" * 64}, "stages": ["-k"]},
    {"makefile": {"path": "Makefile", "sha256": "0" * 64}, "stages": ["a"], "extra": 1},
])
def test_a_malformed_declaration_is_refused(broken: dict[str, object]) -> None:
    with pytest.raises(pg.Refused):
        pg.ProjectGate.from_declaration(broken)


# --- counter-model review pass 1: make would not run the declared recipes ----------

@pytest.mark.parametrize(("present", "why"), [
    (("GNUmakefile", "Makefile"), "make would read another makefile"),
    (("makefile", "Makefile"), "make would read another makefile"),
    (("Makefile", "lint"), "treat a target as up to date"),
    (("Makefile", "check"), "treat a target as up to date"),
    ((), "is absent"),
])
def test_when_make_would_run_something_else_the_real_make_runs_with_no_stage_truth(
        present: tuple[str, ...], why: str) -> None:
    backend = _StageBackend({"lint": 0, "test": 0, "typecheck": 0}, present=present)
    result, capture = pg.StagedRunner(declaration()).run(
        backend, None, Limits(timeout=5), ("lint", "test", "typecheck"), cwd=None, env=None, confine_root=None,
        make_args=["check"])
    assert capture["status"] == "unavailable" and why in str(capture["reason"])
    assert backend.calls[-1] == [pg.REAL_MAKE, "check"] and result.stdout == b"real make\n"
    assert not any(c[0] == pg.REAL_MAKE and len(c) == 2 and c[1] in SCRIPTS for c in backend.calls)


def test_a_target_an_earlier_stage_created_hands_the_rest_to_the_real_make() -> None:
    """Counter-model review pass 2: lint creates a file named `test`, so make
    would call `test` up to date. The check runs before EVERY stage."""
    class Creates(_StageBackend):
        def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                            stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
            result = super().exec_in_attempt(handle, argv, limits, cwd=cwd, env=env, confine_root=confine_root)
            if argv == [pg.REAL_MAKE, "lint"]:
                self.present.append("test")
            return result

    backend = Creates({"lint": 0, "test": 0, "typecheck": 0})
    result, capture = pg.StagedRunner(declaration()).run(
        backend, None, Limits(timeout=5), ("lint", "test", "typecheck"), cwd=None, env=None, confine_root=None,
        make_args=["check"])
    assert capture["status"] == "unavailable" and "'test'" in str(capture["reason"])
    assert backend.calls[-1] == [pg.REAL_MAKE, "test", "typecheck"]  # the rest, as make itself
    assert [pg.REAL_MAKE, "test"] not in backend.calls
    assert (result.stdout or b"").endswith(b"real make\n")


@pytest.mark.parametrize("probe", ["/bin/sh", "/bin/cat"])
def test_an_unconfirmed_stop_while_checking_the_gate_reaches_the_witness(probe: str) -> None:
    class Stuck(_StageBackend):
        def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                            stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
            if argv[0] == probe:
                self.calls.append(list(argv))
                return ExecuteResult(reason="timeout", exit_code=None, stop_confirmed=False)
            return super().exec_in_attempt(handle, argv, limits, cwd=cwd, env=env, confine_root=confine_root)

    backend = Stuck({"lint": 0, "test": 0, "typecheck": 0})
    result, capture = pg.StagedRunner(declaration()).run(
        backend, None, Limits(timeout=5), ("lint",), cwd=None, env=None, confine_root=None, make_args=["lint"])
    assert result.reason == "timeout" and result.stop_confirmed is False
    assert capture["status"] == "unavailable"
    assert backend.calls[-1][0] == probe  # nothing ran after it, no fallback make


@pytest.mark.parametrize("make_env", [{"MAKEFLAGS": "n"}, {"MAKEFLAGS": "k"}, {"MAKEFILES": "x.mk"},
                                      {"MAKELEVEL": "1"}, {"OTHER": "1"}, "n"])
def test_make_s_own_environment_passes_the_invocation_through(make_env: object) -> None:
    runner = pg.StagedRunner(declaration())
    assert runner.plan({"make_args": ["check"], "make_env": make_env}) is None
    assert runner.plan({"make_args": ["check"], "make_env": {"MAKEFLAGS": ""}}) == ("lint", "test", "typecheck")


def test_an_aggregate_over_the_reply_cap_is_marked_never_sliced() -> None:
    class Chatty(_StageBackend):
        def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                            stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
            if argv[0] == pg.REAL_MAKE:
                return ExecuteResult(reason="exited", exit_code=0, stdout=b"x" * 200, stderr=b"")
            return super().exec_in_attempt(handle, argv, limits, cwd=cwd, env=env, confine_root=confine_root)

    limits = Limits(timeout=5, max_captured_stdout_bytes=256)
    result, _capture = pg.StagedRunner(declaration()).run(
        Chatty({}), None, limits, ("lint", "test", "typecheck"), cwd=None, env=None, confine_root=None,
        make_args=["check"])
    assert result.stdout_truncated is True  # each exec was complete; the whole is not
