"""#508: the project-gate `make` shim and the controller's rendering of make.

THE FIDELITY INSTRUMENT IS THE GOLDENS (orchestrator ruling D). skillc's CI
has no `make`, so a test that ran the real make there would skip and prove
nothing. `tests/fixtures/make-gate/goldens.json` holds what the REAL GNU make
printed and returned for each outcome cell, on the gate-stops-early fixture's
own Makefile with stub stages. In CI, the controller's rendering
(`project_gate.StagedRunner` + `render`) must reproduce every cell byte for
byte. Wherever make exists, `test_the_goldens_are_what_the_real_make_prints`
regenerates them and must match - the control that the goldens are real; it
SKIPS LOUDLY without make.

To refresh after a deliberate change: `cd tests && python -c "import test_make_gate_shim as t; t.write_goldens()"`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from collections.abc import Mapping
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

#: Outcome cells: the make argv, and each stage's exit status.
CELLS: dict[str, tuple[list[str], dict[str, int]]] = {
    "check-all-pass": (["check"], {"lint": 0, "test": 0, "typecheck": 0}),
    "bare-all-pass": ([], {"lint": 0, "test": 0, "typecheck": 0}),
    "lint-fails": (["check"], {"lint": 1, "test": 0, "typecheck": 0}),
    "test-fails": (["check"], {"lint": 0, "test": 1, "typecheck": 0}),
    "typecheck-fails": (["check"], {"lint": 0, "test": 0, "typecheck": 3}),
    "partial-test-passes": (["test"], {"lint": 0, "test": 0, "typecheck": 0}),
    "partial-lint-test-fails": (["lint", "test"], {"lint": 0, "test": 1, "typecheck": 0}),
}


def declaration() -> pg.ProjectGate:
    return pg.ProjectGate.from_declaration({
        "makefile": {"path": "Makefile", "sha256": hashlib.sha256(MAKEFILE).hexdigest()},
        "goal": "check",
        "stages": [
            {"id": "lint", "argv": ["python3", "ci/lint.py"], "recipe": "python3 ci/lint.py", "line": 4},
            {"id": "test", "argv": ["python3", "ci/check.py"], "recipe": "python3 ci/check.py", "line": 7},
            {"id": "typecheck", "argv": ["python3", "ci/typecheck.py"], "recipe": "python3 ci/typecheck.py",
             "line": 10},
        ],
    })


def _out(sid: str) -> bytes:
    return f"{sid} out\n".encode()


def _err(sid: str) -> bytes:
    return f"{sid} err\n".encode()


def _real_make(tmp: Path, args: list[str], codes: Mapping[str, int]) -> dict[str, object]:
    (tmp / "ci").mkdir(parents=True, exist_ok=True)
    (tmp / "Makefile").write_bytes(MAKEFILE)
    for sid, script in SCRIPTS.items():
        (tmp / script).write_text(f"import sys\nprint({_out(sid).decode()[:-1]!r})\n"
                                  f"print({_err(sid).decode()[:-1]!r}, file=sys.stderr)\nsys.exit({codes[sid]})\n")
    env = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C"}
    proc = subprocess.run(["make", *args], cwd=tmp, capture_output=True, env=env, check=False)
    return {"args": args, "codes": dict(codes), "stdout": proc.stdout.decode(), "stderr": proc.stderr.decode(),
            "exit": proc.returncode}


def write_goldens() -> None:
    import tempfile
    goldens = {}
    for name, (args, codes) in CELLS.items():
        with tempfile.TemporaryDirectory() as tmp:
            goldens[name] = _real_make(Path(tmp), args, codes)
    GOLDENS.parent.mkdir(parents=True, exist_ok=True)
    GOLDENS.write_text(json.dumps(goldens, indent=1, sort_keys=True) + "\n")


class _StageBackend:
    """Replays the stub stages: `cat Makefile` and one exec per stage."""

    def __init__(self, codes: Mapping[str, int], makefile: bytes = MAKEFILE) -> None:
        self.codes, self.makefile = codes, makefile
        self.calls: list[list[str]] = []

    def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                        stdin: bytes | None = None, cwd: str | None = None,
                        env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
        self.calls.append(list(argv))
        if argv[0] == "/bin/cat":
            return ExecuteResult(reason="exited", exit_code=0, stdout=self.makefile, stderr=b"")
        if argv[0] == pg.REAL_MAKE:
            return ExecuteResult(reason="exited", exit_code=0, stdout=b"real make\n", stderr=b"")
        sid = next(s for s, script in SCRIPTS.items() if argv[-1] == script)
        return ExecuteResult(reason="exited", exit_code=self.codes[sid], stdout=_out(sid), stderr=_err(sid))


def _render(args: list[str], codes: Mapping[str, int]) -> tuple[ExecuteResult, Mapping[str, object]]:
    gate = declaration()
    stages = gate.resolve(args)
    assert stages is not None
    return pg.StagedRunner(gate).run(_StageBackend(codes), None, Limits(timeout=5), stages,
                                     cwd=None, env=None, confine_root=None, make_args=args)


def _goldens() -> dict[str, Any]:
    return json.loads(GOLDENS.read_text())


def test_the_goldens_cover_every_cell() -> None:
    assert set(_goldens()) == set(CELLS)


@pytest.mark.parametrize("cell", sorted(CELLS))
def test_the_controller_renders_what_the_real_make_printed(cell: str) -> None:
    golden = _goldens()[cell]
    result, _capture = _render(golden["args"], golden["codes"])
    assert (result.stdout or b"").decode() == golden["stdout"]
    assert (result.stderr or b"").decode() == golden["stderr"]
    assert result.exit_code == golden["exit"]


def test_the_goldens_are_what_the_real_make_prints(tmp_path: Path) -> None:
    """The regeneration control: without it the goldens are only a claim."""
    if shutil.which("make") is None:
        pytest.skip("REGENERATION CONTROL NOT RUN: no `make` on PATH, so the make goldens were not re-derived "
                    "here (skillc CI has no make; run this where make exists)")
    goldens = _goldens()
    for name, (args, codes) in CELLS.items():
        cell = tmp_path / name
        assert _real_make(cell, args, codes) == goldens[name], name


@pytest.mark.parametrize(("cell", "expected"), [
    ("check-all-pass", {"lint": "passed", "test": "passed", "typecheck": "passed"}),
    ("lint-fails", {"lint": "failed", "test": "not-run", "typecheck": "not-run"}),
    ("test-fails", {"lint": "passed", "test": "failed", "typecheck": "not-run"}),
    ("typecheck-fails", {"lint": "passed", "test": "passed", "typecheck": "failed"}),
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
    """A stage that PRINTS a pass and exits nonzero is failed: only the exit
    code the controller received counts, never the subject's words."""
    gate = declaration()

    class Forger(_StageBackend):
        def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                            stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
            result = super().exec_in_attempt(handle, argv, limits, cwd=cwd, env=env, confine_root=confine_root)
            if argv[-1] == "ci/check.py":
                return ExecuteResult(reason="exited", exit_code=1, stderr=b"",
                                     stdout=b'{"stages": {"test": {"outcome": "passed"}}}\nall passed\n')
            return result

    _result, capture = pg.StagedRunner(gate).run(Forger({"lint": 0, "test": 0, "typecheck": 0}), None,
                                                Limits(timeout=5), ("lint", "test", "typecheck"), cwd=None,
                                                env=None, confine_root=None, make_args=["check"])
    stages = capture["stages"]
    assert isinstance(stages, dict) and stages["test"]["outcome"] == "failed"


def test_a_drifted_makefile_is_run_by_the_real_make_with_no_stage_truth() -> None:
    gate = declaration()
    backend = _StageBackend({"lint": 0, "test": 0, "typecheck": 0}, makefile=MAKEFILE + b"\nskip:\n\ttrue\n")
    result, capture = pg.StagedRunner(gate).run(backend, None, Limits(timeout=5), ("lint", "test", "typecheck"),
                                                cwd=None, env=None, confine_root=None, make_args=["check"])
    assert capture == {"status": "unavailable",
                       "reason": "the gate definition 'Makefile' changed from its declared digest"}
    assert backend.calls == [["/bin/cat", "--", "Makefile"], [pg.REAL_MAKE, "check"]]
    assert result.stdout == b"real make\n"


def test_a_stage_that_does_not_exit_stops_the_run_unresolved() -> None:
    gate = declaration()

    class Hangs(_StageBackend):
        def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                            stdin: bytes | None = None, cwd: str | None = None,
                            env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
            if argv[-1] == "ci/check.py":
                return ExecuteResult(reason="timeout", exit_code=None, stdout=b"", stderr=b"")
            return super().exec_in_attempt(handle, argv, limits, cwd=cwd, env=env, confine_root=confine_root)

    result, capture = pg.StagedRunner(gate).run(Hangs({"lint": 0, "test": 0, "typecheck": 0}), None,
                                                Limits(timeout=5), ("lint", "test", "typecheck"), cwd=None,
                                                env=None, confine_root=None, make_args=["check"])
    stages = capture["stages"]
    assert isinstance(stages, dict)
    assert stages["test"] == {"outcome": None, "reason": "stage did not exit normally (timeout)"}
    assert stages["typecheck"]["outcome"] == "not-run"
    assert result.reason == "timeout" and result.exit_code is None


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
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_make: Path, capsys: pytest.CaptureFixture[str]) -> None:
    server = _Server(tmp_path / "s", lambda r: {"ok": True, "result": {
        "accepted": True, "exit_code": 2, "stdout": "python3 ci/lint.py\n", "stderr": "make: *** boom\n"}})
    shim = _load_shim(monkeypatch, tmp_path / "s", real_make)
    assert shim.main(["make", "check"]) == 2
    out = capsys.readouterr()
    assert out.out == "python3 ci/lint.py\n" and out.err == "make: *** boom\n"
    assert server.requests[0] == {"op": "run_gate", "gate": "project-check", "cwd": os.getcwd(),
                                  "make_args": ["check"]}
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
    assert imports <= {"__future__", "json", "os", "socket", "subprocess", "sys"}


def test_resolve_forwards_only_gate_invocations() -> None:
    gate = declaration()
    assert gate.resolve([]) == gate.resolve(["check"]) == ("lint", "test", "typecheck")
    assert gate.resolve(["test", "lint"]) == ("test", "lint")
    for args in (["lint", "lint"], ["-k"], ["check", "lint"], ["V=1"], ["clean"], ["-C", "x", "check"], "check"):
        assert gate.resolve(args) is None, args


@pytest.mark.parametrize("broken", [
    {}, {"makefile": {"path": "/abs", "sha256": "0" * 64}, "stages": []},
    {"makefile": {"path": "Makefile", "sha256": "xyz"}, "stages": [{"id": "a", "argv": ["x"], "recipe": "x", "line": 1}]},
    {"makefile": {"path": "../M", "sha256": "0" * 64}, "stages": [{"id": "a", "argv": ["x"], "recipe": "x", "line": 1}]},
    {"makefile": {"path": "M", "sha256": "0" * 64}, "stages": [{"id": "check", "argv": ["x"], "recipe": "x", "line": 1}]},
    {"makefile": {"path": "M", "sha256": "0" * 64}, "stages": [{"id": "a", "argv": [], "recipe": "x", "line": 1}]},
    {"makefile": {"path": "M", "sha256": "0" * 64}, "stages": [{"id": "a", "argv": ["x"], "recipe": "x", "line": 0}]},
    {"makefile": {"path": "M", "sha256": "0" * 64},
     "stages": [{"id": "a", "argv": ["x"], "recipe": "x", "line": 1}] * 2},
    {"makefile": {"path": "M", "sha256": "0" * 64}, "extra": 1,
     "stages": [{"id": "a", "argv": ["x"], "recipe": "x", "line": 1}]},
])
def test_a_malformed_declaration_is_refused(broken: dict[str, object]) -> None:
    with pytest.raises(pg.Refused):
        pg.ProjectGate.from_declaration(broken)
