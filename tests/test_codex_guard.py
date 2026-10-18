"""The nested-codex guard (#434 PR 2b, D3): its controller record
(`skillc.codex_guard`), the in-container guard script
(`docker/fixture-service/skillc-codex-guard.py`) and its overlay
(`skillc.fixture_overlay`), without a container.

The guard's ancestry walk is driven over a SYNTHETIC `/proc` here, so each
ancestor shape is exact. On a host the real walk reaches PID 1, whose exe a
non-root user cannot read, and every call would be ancestry-unknown. The real
`/proc` walk in a real container, under the real launch, is
`tests/test_codex_guard_live.py`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from skillc import codex_guard as cg
from skillc import fixture_overlay as fo
from skillc.backend import ExecuteResult, Limits
from skillc.decide_reply_channel import ChannelRefusal

GUARD_SOURCE = fo.CODEX_GUARD_SOURCE
DIGEST = "sha256:" + "a" * 64


def _load_guard() -> Any:
    spec = importlib.util.spec_from_file_location("skillc_codex_guard_script", GUARD_SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


# --- the controller's record ------------------------------------------------------

def _session(*decisions: str) -> cg.CodexGuardSession:
    session = cg.CodexGuardSession("a-1")
    for decision in decisions:
        session.decide({"op": "codex_guard", "decision": decision, "argv_digest": DIGEST})
    return session


def test_one_top_level_launch_and_nothing_else_is_zero() -> None:
    nested = _session("passed-top-level").finalize()["nested"]
    assert nested == {"status": "zero", "top_level": 1, "confirmed": 0, "suspected": 0, "ancestry_unknown": 0}
    assert cg.credit_block(_session("passed-top-level").finalize()) is None


def test_a_nested_refusal_is_observed_and_blocks_credit() -> None:
    record = _session("passed-top-level", "refused-nested").finalize()
    assert record["nested"]["status"] == "observed" and record["nested"]["confirmed"] == 1
    assert record["decisions"][1] == {"seq": 2, "decision": "refused-nested", "argv_digest": DIGEST}
    block = cg.credit_block(record)
    assert block is not None and block.startswith("not credited: nested codex observed")


def test_a_second_top_level_launch_is_nested_suspected() -> None:
    """Ruling B: the harness launches once; a second top-level launch is what
    a double-fork reparent to PID 1 looks like."""
    nested = _session("passed-top-level", "passed-top-level").finalize()["nested"]
    assert nested["status"] == "observed" and nested["suspected"] == 1 and nested["confirmed"] == 0
    block = cg.credit_block(_session("passed-top-level", "passed-top-level").finalize())
    assert block is not None and "suspected=1" in block


def test_ancestry_unknown_is_observed_never_zero() -> None:
    nested = _session("passed-top-level", "refused-ancestry-unknown").finalize()["nested"]
    assert nested["status"] == "observed" and nested["ancestry_unknown"] == 1


@pytest.mark.parametrize("decisions,unhealthy", [((), False), (("passed-top-level",), True)])
def test_no_top_level_launch_or_an_unhealthy_channel_is_unknown(decisions: tuple[str, ...],
                                                                 unhealthy: bool) -> None:
    """With the channel down the guard still exits 3, but the controller sees
    fewer decisions than happened: the count is UNKNOWN, never 0."""
    session = _session(*decisions)
    session.channel_unavailable = unhealthy
    record = session.finalize()
    assert record["nested"]["status"] == "unknown"
    assert cg.credit_block(record) == "not credited: nested-codex count unknown"


def test_a_missing_record_is_unknown_never_zero() -> None:
    assert cg.credit_block(None) == "not credited: nested-codex count unknown (no guard record)"
    assert cg.credit_block({"nested": {"status": "fine"}}) is not None


@pytest.mark.parametrize("request_", [
    {"op": "codex_guard", "decision": "passed-top-level"},
    {"op": "codex_guard", "decision": "passed-top-level", "argv_digest": DIGEST, "note": "x"},
    {"op": "codex_guard", "decision": "passed", "argv_digest": DIGEST},
    {"op": "codex_guard", "decision": "refused-nested", "argv_digest": "sha256:xyz"},
    {"op": "gh", "decision": "refused-nested", "argv_digest": DIGEST},
])
def test_a_forged_or_malformed_request_is_refused_and_marks_the_channel(request_: Mapping[str, object]) -> None:
    session = _session("passed-top-level")
    with pytest.raises(ChannelRefusal):
        session.decide(request_)
    record = session.finalize()
    assert record["channel_unavailable"] and record["nested"]["status"] == "unknown"
    assert len(record["decisions"]) == 1


def test_a_request_after_finalization_or_past_the_cap_is_refused() -> None:
    session = _session("passed-top-level")
    session.finalize()
    with pytest.raises(ChannelRefusal, match="finalized"):
        session.decide({"op": "codex_guard", "decision": "refused-nested", "argv_digest": DIGEST})
    flood = cg.CodexGuardSession("a-2")
    for _ in range(cg.MAX_DECISIONS):
        flood.decide({"op": "codex_guard", "decision": "refused-nested", "argv_digest": DIGEST})
    with pytest.raises(ChannelRefusal, match="more than"):
        flood.decide({"op": "codex_guard", "decision": "refused-nested", "argv_digest": DIGEST})
    assert flood.channel_unavailable


# --- the guard's ancestry walk, over a synthetic /proc ------------------------------

NODE = "/usr/local/bin/node"
CODEX_JS = "/usr/local/lib/node_modules/@openai/codex/bin/codex.js"
NATIVE = "/usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x/bin/codex"
CONFIG = {"real": "/usr/local/bin/codex", "node": NODE, "codex_js": CODEX_JS, "native": [NATIVE]}


@pytest.fixture
def proc(monkeypatch: pytest.MonkeyPatch) -> dict[int, dict[str, Any]]:
    """A synthetic process table: pid -> exe, argv, cwd, ppid. A missing
    field raises the OSError a real unreadable /proc entry would."""
    table: dict[int, dict[str, Any]] = {}

    def entry(path: str) -> tuple[dict[str, Any], str]:
        parts = path.split("/")  # "", "proc", pid, field
        if len(parts) != 4 or parts[1] != "proc" or int(parts[2]) not in table:
            raise FileNotFoundError(path)
        return table[int(parts[2])], parts[3]

    def read(path: str) -> bytes:
        row, name = entry(path)
        if name == "stat":
            if "ppid" not in row:
                raise PermissionError(path)
            return f"{path.split('/')[2]} (a) b) S {row['ppid']} 1 1".encode()
        if name == "cmdline":
            return b"\0".join(os.fsencode(a) for a in row.get("argv", [])) + b"\0"
        raise FileNotFoundError(path)

    def readlink(path: str) -> str:
        row, name = entry(path)
        if name not in row:
            raise PermissionError(path)
        return str(row[name])

    monkeypatch.setattr(guard, "_read", read)
    monkeypatch.setattr(guard.os, "readlink", readlink)
    monkeypatch.setattr(guard.os.path, "realpath", lambda p: p.replace("/usr/local/bin/codex", CODEX_JS))
    return table


def test_the_harness_launch_passes(proc: dict[int, dict[str, Any]]) -> None:
    """The agent's own launch: its parent is outside the pid namespace."""
    assert guard.decide(CONFIG, 0) == "passed-top-level"


def test_a_native_codex_ancestor_is_nested(proc: dict[int, dict[str, Any]]) -> None:
    proc[20] = {"exe": NATIVE, "ppid": 12}
    proc[12] = {"exe": NODE, "argv": ["node", "/usr/local/bin/codex", "exec"], "ppid": 0}
    proc[30] = {"exe": "/usr/bin/bash", "argv": ["bash", "-c", "codex exec review"], "ppid": 20}
    assert guard.decide(CONFIG, 30) == "refused-nested"


def test_a_node_codex_ancestor_is_nested_by_its_script_not_its_name(proc: dict[int, dict[str, Any]]) -> None:
    """node with argv[1] resolving to codex.js, a relative one resolved
    against that process's own cwd."""
    proc[12] = {"exe": NODE, "argv": ["node", "codex.js"], "cwd": "/usr/local/lib/node_modules/@openai/codex/bin",
                "ppid": 0}
    assert guard.decide(CONFIG, 12) == "refused-nested"
    proc[12] = {"exe": NODE, "argv": ["node", "/opt/other.js"], "ppid": 0}
    assert guard.decide(CONFIG, 12) == "passed-top-level"


@pytest.mark.parametrize("ancestor", [
    {"exe": "/usr/bin/dash", "argv": ["sh", "-c", "grep codex notes.txt | codex-lint"]},
    {"exe": "/tmp/codex-something", "argv": ["/tmp/codex-something"]},
    {"exe": "/usr/bin/codex-wrapper", "argv": ["codex"]},
    {"exe": NODE, "argv": ["node"]},
])
def test_names_and_command_lines_never_count(proc: dict[int, dict[str, Any]], ancestor: dict[str, Any]) -> None:
    """Ruling condition 1: EXACT exe/script identity only. An ancestor that
    merely mentions codex, or is named like it, is not codex."""
    proc[40] = {**ancestor, "ppid": 0}
    assert guard.decide(CONFIG, 40) == "passed-top-level"


@pytest.mark.parametrize("broken", [
    {41: {"argv": ["sh"], "ppid": 0}},                       # exe unreadable
    {41: {"exe": "/usr/bin/dash", "argv": ["sh"]}},           # stat unreadable
    {41: {"exe": "/usr/bin/dash", "argv": ["sh"], "ppid": 99}},  # parent vanished mid-walk
    {41: {"exe": "/usr/bin/dash", "argv": ["sh"], "ppid": 41}},  # a loop
])
def test_unreadable_ancestry_fails_closed(proc: dict[int, dict[str, Any]], broken: dict[int, Any]) -> None:
    proc.update(broken)
    assert guard.decide(CONFIG, 41) == "refused-ancestry-unknown"


def test_a_walk_deeper_than_the_cap_fails_closed(proc: dict[int, dict[str, Any]]) -> None:
    for pid in range(2, guard._MAX_DEPTH + 3):
        proc[pid] = {"exe": "/usr/bin/dash", "argv": ["sh"], "ppid": pid + 1}
    proc[guard._MAX_DEPTH + 3] = {"exe": "/usr/bin/dash", "argv": ["sh"], "ppid": 0}
    assert guard.decide(CONFIG, 2) == "refused-ancestry-unknown"


# --- the guard as a process: pass-through, refusal, the channel ---------------------

class _Recorder:
    """A unix socket that records every line the guard sends."""

    def __init__(self, path: Path) -> None:
        self.lines: list[dict[str, Any]] = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(4)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = b""
                while chunk := conn.recv(65536):
                    data += chunk
                self.lines.append(json.loads(data))
                conn.sendall(b'{"ok": true, "result": {"recorded": 1}}\n')

    def close(self) -> None:
        self.server.close()


def _guard_copy(tmp_path: Path, *, decision: str | None, real: Path, sock: Path,
                self_bound: int | None = None) -> Path:
    """The guard with only its two constants, its interpreter and (on a host,
    where the real walk reaches an unreadable PID 1) its decision replaced.
    Each replacement must match exactly once."""
    text = GUARD_SOURCE.read_text()
    config = tmp_path / "codex-guard.json"
    config.write_text(json.dumps({"real": str(real), "node": NODE, "codex_js": CODEX_JS, "native": [NATIVE]}))
    for old, new in [("#!/usr/bin/python3 -IS", f"#!{sys.executable} -IS"),
                     ('CONFIG = "/opt/skillc-harness/codex-guard.json"', f"CONFIG = {str(config)!r}"),
                     ('TRIGGER_SOCKET_PATH = "/run/skillc/trigger.sock"', f"TRIGGER_SOCKET_PATH = {str(sock)!r}"),
                     *([("decide(config, os.getppid())", repr(decision))] if decision else []),
                     *([("_MAX_SELF_BYTES = 64 << 20", f"_MAX_SELF_BYTES = {self_bound}")] if self_bound else [])]:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    path = tmp_path / "codex"
    path.write_text(text)
    path.chmod(0o755)
    return path


@pytest.fixture
def recorder(tmp_path: Path) -> Iterator[tuple[_Recorder, Path]]:
    sock = tmp_path / "trigger.sock"
    rec = _Recorder(sock)
    yield rec, sock
    rec.close()


def _real_recorder(tmp_path: Path) -> tuple[Path, Path]:
    out = tmp_path / "received.json"
    real = tmp_path / "real-codex"
    real.write_text(f"#!{sys.executable}\n"
                    "import json, sys\n"
                    "env = open('/proc/self/environ', 'rb').read()\n"
                    f"json.dump({{'argv': [a.encode('utf-8', 'surrogateescape').hex() for a in sys.argv[1:]], "
                    f"'environ': env.hex()}}, open({str(out)!r}, 'w'))\n")
    real.chmod(0o755)
    return real, out


ARGS = ["exec", "--sandbox", "danger-full-access", "a b\tc", "ü", "-", ""]
ENV = {"PATH": "/usr/bin:/bin", "HOME": "/home/candidate", "LANG": "C", "EMPTY": "", "SPACED": "x y"}


def test_pass_through_reaches_the_real_codex_with_argv_and_env_byte_for_byte(
        tmp_path: Path, recorder: tuple[_Recorder, Path]) -> None:
    """Ruling condition 5. LANG=C invites Python's locale coercion to ADD
    LC_CTYPE to os.environ; the real codex must not see it."""
    rec, sock = recorder
    real, out = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision="passed-top-level", real=real, sock=sock)
    proc = subprocess.run([str(copy), *ARGS], env=ENV, capture_output=True, timeout=30, check=False)
    assert proc.returncode == 0, proc.stderr
    received = json.loads(out.read_text())
    assert [bytes.fromhex(a) for a in received["argv"]] == [a.encode() for a in ARGS]
    sent = b"".join(f"{k}={v}".encode() + b"\0" for k, v in ENV.items())
    assert bytes.fromhex(received["environ"]) == sent
    digest = "sha256:" + hashlib.sha256(b"\0".join([os.fsencode(str(copy)), *[a.encode() for a in ARGS]])).hexdigest()
    assert rec.lines == [{"op": "codex_guard", "decision": "passed-top-level", "argv_digest": digest}]


def test_pass_through_control_a_guard_that_drops_a_variable_is_caught(
        tmp_path: Path, recorder: tuple[_Recorder, Path]) -> None:
    """The byte-for-byte check's committed control: one dropped variable."""
    _, sock = recorder
    real, out = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision="passed-top-level", real=real, sock=sock)
    text = copy.read_text()
    assert text.count("        env[key] = value\n") == 1
    copy.write_text(text.replace("        env[key] = value\n", "        env[key] = value\n    env.pop(b'EMPTY')\n"))
    subprocess.run([str(copy), *ARGS], env=ENV, capture_output=True, timeout=30, check=True)
    sent = b"".join(f"{k}={v}".encode() + b"\0" for k, v in ENV.items())
    assert bytes.fromhex(json.loads(out.read_text())["environ"]) != sent


@pytest.mark.parametrize("decision", ["refused-nested", "refused-ancestry-unknown"])
def test_a_refusal_exits_3_with_the_unavailable_line_and_is_sent(
        tmp_path: Path, recorder: tuple[_Recorder, Path], decision: str) -> None:
    rec, sock = recorder
    real, out = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision=decision, real=real, sock=sock)
    proc = subprocess.run([str(copy), "exec", "review"], env=ENV, capture_output=True, timeout=30, check=False)
    assert proc.returncode == 3 and proc.stdout == b""
    assert proc.stderr.startswith(b"CODEX_REVIEW: unavailable")
    assert not out.exists()  # the real codex never ran
    assert [line["decision"] for line in rec.lines] == [decision]


def test_with_the_channel_down_a_refusal_still_exits_3(tmp_path: Path) -> None:
    real, out = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision="refused-nested", real=real, sock=tmp_path / "no-such.sock")
    proc = subprocess.run([str(copy), "exec"], env=ENV, capture_output=True, timeout=30, check=False)
    assert proc.returncode == 3 and not out.exists()


def test_an_environment_that_cannot_be_carried_exactly_is_refused(
        tmp_path: Path, recorder: tuple[_Recorder, Path]) -> None:
    """A duplicate name cannot pass through `os.execve` unchanged."""
    rec, sock = recorder
    real, out = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision=None, real=real, sock=sock)
    # A raw execve: GNU env and every Python mapping would collapse the pair.
    raw = ("import ctypes\n"
           "libc = ctypes.CDLL(None, use_errno=True)\n"
           f"argv = (ctypes.c_char_p * 3)({os.fsencode(str(copy))!r}, b'exec', None)\n"
           "envp = (ctypes.c_char_p * 4)(b'PATH=/usr/bin:/bin', b'A=1', b'A=2', None)\n"
           "libc.execve(argv[0], argv, envp)\n"
           "raise SystemExit(f'execve failed: {ctypes.get_errno()}')\n")
    proc = subprocess.run([sys.executable, "-c", raw], capture_output=True, timeout=30, check=False)
    assert proc.returncode == 3 and not out.exists()
    assert [line["decision"] for line in rec.lines] == ["refused-ancestry-unknown"]


def test_an_unreadable_config_fails_closed(tmp_path: Path, recorder: tuple[_Recorder, Path]) -> None:
    rec, sock = recorder
    real, out = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision=None, real=real, sock=sock)
    (tmp_path / "codex-guard.json").write_text('{"real": "relative"}')
    proc = subprocess.run([str(copy), "exec"], env=ENV, capture_output=True, timeout=30, check=False)
    assert proc.returncode == 3 and not out.exists()
    assert [line["decision"] for line in rec.lines] == ["refused-ancestry-unknown"]


# --- the overlay, against a fake backend -------------------------------------------

class _FakeAttempt:
    """Enough of an attempt for the overlay: a file table, a candidate-
    writable set, and a PATH, honoured by the overlay's exact probe argvs."""

    def __init__(self) -> None:
        self.witness_io = True
        self.files: dict[str, bytes] = {
            fo.NODE: b"node", fo.REAL_CODEX: b"->", fo.NATIVE_CANDIDATES[0]: b"native",
            "/usr/local/lib/node_modules/@openai/codex/bin/codex.js": b"js",
        }
        self.links = {fo.REAL_CODEX: "/usr/local/lib/node_modules/@openai/codex/bin/codex.js"}
        self.writable: set[str] = set()
        self.path = "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"
        self.write_ok = True
        self.tamper: bytes | None = None

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits, cancel: object = None,
                        stdin: bytes | None = None, cwd: str | None = None,
                        env: Mapping[str, str] | None = None, confine_root: str | None = None) -> ExecuteResult:
        def ok(out: bytes, code: int = 0) -> ExecuteResult:
            return ExecuteResult(reason="exited", exit_code=code, stdout=out, stderr=b"")

        if argv[0] == "realpath":
            path = self.links.get(argv[-1], argv[-1])
            return ok(f"{path}\n".encode()) if path in self.files else ok(b"", 1)
        if argv[0] == "cat":
            return ok(self.files[argv[-1]])
        if argv[0] == "sh" and "command -v" in argv[2]:
            path = (env or {}).get("PATH", self.path)
            for directory in path.split(":"):
                if f"{directory}/{argv[-1]}" in self.files:
                    return ok(f"{directory}/{argv[-1]}\n".encode())
            return ok(b"", 1)
        if argv[0] == "sh":
            return ok(b"present\n" if argv[-1] in self.files else b"absent\n")
        raise AssertionError(f"unexpected probe {argv!r}")

    def write_root_owned_file_in_attempt(self, handle: object, path: str, content: bytes, mode: int = 0o755) -> bool:
        if self.write_ok:
            self.files[path] = self.tamper if self.tamper is not None else content
        return self.write_ok

    def candidate_can_write_in_attempt(self, handle: object, path: str) -> bool | None:
        return path in self.writable


ENVIRONMENT = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"}


def test_the_guard_and_the_gh_shim_are_placed_and_verified() -> None:
    attempt = _FakeAttempt()
    placed = fo.install_codex_guard(attempt, object(), ENVIRONMENT)
    shim = fo.install_gh_shim(attempt, object(), ENVIRONMENT)
    assert attempt.files[fo.CODEX_GUARD_PATH] == fo.CODEX_GUARD_SOURCE.read_bytes()
    assert placed["resolved"] == {"real": fo.REAL_CODEX, "node": fo.NODE,
                                  "codex_js": "/usr/local/lib/node_modules/@openai/codex/bin/codex.js",
                                  "native": [fo.NATIVE_CANDIDATES[0]]}
    assert json.loads(attempt.files[fo.CODEX_GUARD_CONFIG]) == placed["resolved"]
    assert shim.digest == hashlib.sha256(fo.GH_SHIM_SOURCE.read_bytes()).hexdigest()
    assert attempt.links[fo.REAL_CODEX] in attempt.files  # the real codex link is untouched


@pytest.mark.parametrize("break_", ["pre-planted-guard", "pre-planted-gh", "path-order", "writable-sbin",
                                    "writable-codex-js", "unverifiable", "tampered", "write-failed",
                                    "no-native", "no-witness-io"])
def test_every_unverified_placement_is_refused(break_: str) -> None:
    attempt = _FakeAttempt()
    env = dict(ENVIRONMENT)
    install: Callable[..., object] = fo.install_codex_guard
    if break_ == "pre-planted-guard":
        attempt.files[fo.CODEX_GUARD_PATH] = b"subject's own"
    elif break_ == "pre-planted-gh":
        attempt.files[fo.GH_PATH] = b"subject's own"
        install = fo.install_gh_shim
    elif break_ == "path-order":
        env["PATH"] = "/usr/local/bin:/usr/local/sbin:/usr/bin:/bin"
    elif break_ == "writable-sbin":
        attempt.writable.add("/usr/local/sbin")
    elif break_ == "writable-codex-js":
        attempt.writable.add("/usr/local/lib/node_modules/@openai/codex/bin/codex.js")
    elif break_ == "unverifiable":
        attempt.candidate_can_write_in_attempt = lambda handle, path: None  # type: ignore[method-assign]
    elif break_ == "tampered":
        attempt.tamper = b"something else"
    elif break_ == "write-failed":
        attempt.write_ok = False
    elif break_ == "no-native":
        del attempt.files[fo.NATIVE_CANDIDATES[0]]
    elif break_ == "no-witness-io":
        attempt.witness_io = False
    with pytest.raises(fo.OverlayRefused):
        install(attempt, object(), env)


def test_the_guard_source_is_executable_and_python_isolated() -> None:
    assert GUARD_SOURCE.read_text().splitlines()[0] == "#!/usr/bin/python3 -IS"
    assert GUARD_SOURCE.stat().st_mode & stat.S_IXUSR


@pytest.mark.parametrize("oversized", ["argv", "environ"])
def test_inputs_larger_than_the_read_bound_are_refused_never_truncated(
        tmp_path: Path, recorder: tuple[_Recorder, Path], oversized: str) -> None:
    """Counter-model review, pass 1: a bounded read that silently cut argv or
    the environment forwarded a different call. Over the bound (lowered here
    to 4 KiB; real argv cannot reach 64 MiB) is refused, exit 3, and the real
    codex never runs."""
    _, sock = recorder
    real, out = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision="passed-top-level", real=real, sock=sock, self_bound=4096)
    args = [f"arg{i:03d}-" + "x" * 90 for i in range(101)] if oversized == "argv" else ["exec"]
    env = dict(ENV, **({f"V{i:03d}": "y" * 90 for i in range(101)} if oversized == "environ" else {}))
    proc = subprocess.run([str(copy), *args], env=env, capture_output=True, timeout=30, check=False)
    assert proc.returncode == 3 and not out.exists()
    # The decision forced in this copy is passed-top-level: only the bound
    # check can have turned it into a refusal.
    assert proc.stderr.startswith(b"CODEX_REVIEW: unavailable")


def test_control_inputs_under_the_bound_still_pass_through(
        tmp_path: Path, recorder: tuple[_Recorder, Path]) -> None:
    _, sock = recorder
    real, out = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision="passed-top-level", real=real, sock=sock, self_bound=4096)
    proc = subprocess.run([str(copy), "exec"], env=ENV, capture_output=True, timeout=30, check=False)
    assert proc.returncode == 0 and out.exists()


def test_a_proc_block_that_is_not_nul_terminated_is_refused(tmp_path: Path) -> None:
    block = tmp_path / "cmdline"
    block.write_bytes(b"python3\0-IS\0truncated")
    with pytest.raises(guard._TooLarge):
        guard._read_whole(str(block))
    block.write_bytes(b"python3\0-IS\0whole\0")
    assert guard._read_whole(str(block)) == b"python3\0-IS\0whole\0"


def test_a_call_larger_than_one_mebibyte_passes_through_whole(
        tmp_path: Path, recorder: tuple[_Recorder, Path]) -> None:
    """The regression for the pass-1 finding at the REAL bound: 1.5 MiB of
    argv (the kernel allows 2 MiB) used to be cut at the old 1 MiB read and
    forwarded short. It must reach the real codex whole."""
    _, sock = recorder
    real, out = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision="passed-top-level", real=real, sock=sock)
    args = [f"a{i:02d}" + "z" * (100 * 1024) for i in range(15)]
    proc = subprocess.run([str(copy), *args], env=ENV, capture_output=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr[-300:]
    assert [bytes.fromhex(a) for a in json.loads(out.read_text())["argv"]] == [a.encode() for a in args]
