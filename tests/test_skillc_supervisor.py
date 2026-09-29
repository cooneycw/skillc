"""Process-level tests for `docker/trial/skillc-supervisor.py` and
`docker/trial/skillc-wrap.py` (issue #158) - real subprocesses, real Unix
sockets, real signals, run OUTSIDE any container (no root/namespace
privileges are available in this environment; `tests/test_docker_backend.py`
covers the capability-gated argv/ExecuteResult behavior against the fake
docker CLI instead).

`tests/fixtures/signal-forwarding/mini_init.py` stands in for `tini`: it
execs its argv as a child, forwards a received SIGTERM to it, and - the
property these tests key on - exits as soon as its child does, exactly as a
real container's PID 1 dying stops the container. `run_mutant_supervisor.py`
monkeypatches the REAL supervisor module's `_on_term` to relay and then
exit - the bug `signal-forwarding.md` section 2a item 6 forbids - so the
production script itself never carries a switch for its own safety rule.
"""

from __future__ import annotations

import importlib.util
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "signal-forwarding"
MINI_INIT = FIXTURES / "mini_init.py"
MUTANT_SUPERVISOR = FIXTURES / "run_mutant_supervisor.py"
REAL_SUPERVISOR = Path(__file__).resolve().parent.parent / "docker" / "trial" / "skillc-supervisor.py"
WRAP = Path(__file__).resolve().parent.parent / "docker" / "trial" / "skillc-wrap.py"

_POLL_INTERVAL = 0.02


def _wait_for(predicate: object, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(_POLL_INTERVAL)
    return predicate()  # type: ignore[operator]


def _subject_script(started: Path, sentinel: Path, handler_delay: float) -> str:
    """A subject that reports it has started, then - only if it receives a
    real SIGTERM - waits `handler_delay` (simulating a graceful shutdown
    that takes a moment: flushing output, releasing a lock) before writing
    `sentinel` and exiting. A subject killed by SIGKILL never runs this
    handler at all, so `sentinel` existing is proof of a COMPLETED graceful
    handler, not merely a delivered signal."""
    return (
        "import signal, sys, time\n"
        "def handler(signum, frame):\n"
        f"    time.sleep({handler_delay})\n"
        f"    open({str(sentinel)!r}, 'w').write('done')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, handler)\n"
        f"open({str(started)!r}, 'w').write('up')\n"
        "time.sleep(20)\n"
    )


def _spawn_init_and_supervisor(supervisor_argv: list[str], sock_path: Path) -> subprocess.Popen[bytes]:
    env = {**os.environ, "SKILLC_CONTROL_SOCKET": str(sock_path)}
    return subprocess.Popen(
        [sys.executable, str(MINI_INIT), *supervisor_argv],
        env=env, start_new_session=True,
    )


def _spawn_wrapped_subject(subject_argv: list[str], sock_path: Path) -> subprocess.Popen[bytes]:
    """No `start_new_session=True` here - matching real `docker exec`, which
    does not do this for the caller either; `skillc-wrap.py` itself calls
    `os.setsid()` as its very first action (see its own docstring), which
    would raise `PermissionError` if the process were already a group
    leader by the time it runs."""
    env = {**os.environ, "SKILLC_CONTROL_SOCKET": str(sock_path)}
    return subprocess.Popen([sys.executable, str(WRAP), *subject_argv], env=env)


def _cleanup(*procs: subprocess.Popen[bytes]) -> None:
    for proc in procs:
        if proc.poll() is None:
            try:
                # The subject's own group only exists once skillc-wrap's
                # os.setsid() has run; os.getpgid(pid) always resolves the
                # CURRENT group for this still-live pid, exec() having
                # preserved it throughout.
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        proc.wait(timeout=5)


def test_a_real_supervisor_relays_term_and_survives_letting_the_subject_finish(
    tmp_path: Path,
) -> None:
    """Green case: the REAL, unmodified skillc-supervisor.py relays a
    container-level TERM to the registered subject and does NOT exit - so
    mini_init (standing in for tini) never sees its child exit, and the
    subject's own graceful handler runs to completion."""
    sock_path = tmp_path / "control.sock"
    started = tmp_path / "started"
    sentinel = tmp_path / "term-received"

    init_proc = _spawn_init_and_supervisor([sys.executable, str(REAL_SUPERVISOR)], sock_path)
    subject_proc = None
    try:
        assert _wait_for(sock_path.exists, timeout=5), "supervisor never created its control socket"

        subject_proc = _spawn_wrapped_subject(
            [sys.executable, "-c", _subject_script(started, sentinel, handler_delay=0.3)], sock_path,
        )
        assert _wait_for(started.exists, timeout=5), "the wrapped subject never started"
        # Registration is a local socket write; give it a brief, generous
        # window to land before the container-level TERM is sent - the same
        # ordering _stop() itself relies on in the real backend.
        time.sleep(0.2)

        os.killpg(init_proc.pid, signal.SIGTERM)  # simulates `docker kill --signal TERM` reaching PID 1

        assert _wait_for(sentinel.exists, timeout=5), (
            "the subject's graceful handler never completed - the real supervisor "
            "should have relayed TERM and stayed alive long enough for it to run"
        )
        assert init_proc.poll() is None, (
            "mini_init exited - the real supervisor must not exit after relaying (section 2a item 6)"
        )
    finally:
        _cleanup(*(p for p in (init_proc, subject_proc) if p is not None))


def test_a_supervisor_that_exits_after_relaying_kills_the_subject_before_its_handler_completes(
    tmp_path: Path,
) -> None:
    """Red case for the must-not-exit rule (section 2a item 6): the MUTANT
    supervisor (tests/fixtures only - see run_mutant_supervisor.py) relays
    TERM and then exits. Because it is tini's only child, mini_init exits
    right behind it - the real-world trigger for the kernel's PID-namespace
    teardown this test cannot itself reproduce without root. What IS
    directly observable here: mini_init exits almost immediately, well
    before the subject's own (deliberately slower) graceful handler could
    have completed - proof the subject's shutdown window was cut short by
    its supervisor's own premature exit, exactly what the rule exists to
    prevent."""
    sock_path = tmp_path / "control.sock"
    started = tmp_path / "started"
    sentinel = tmp_path / "term-received"

    init_proc = _spawn_init_and_supervisor([sys.executable, str(MUTANT_SUPERVISOR)], sock_path)
    subject_proc = None
    try:
        assert _wait_for(sock_path.exists, timeout=5), "mutant supervisor never created its control socket"

        subject_proc = _spawn_wrapped_subject(
            [sys.executable, "-c", _subject_script(started, sentinel, handler_delay=0.5)], sock_path,
        )
        assert _wait_for(started.exists, timeout=5), "the wrapped subject never started"
        time.sleep(0.2)

        os.killpg(init_proc.pid, signal.SIGTERM)

        assert _wait_for(lambda: init_proc.poll() is not None, timeout=5), (
            "mini_init never exited - the mutant should have taken it down by exiting right after relaying"
        )
        assert not sentinel.exists(), (
            "the subject's graceful handler completed anyway - the mutant's premature exit "
            "should have raced ahead of its 0.5s handler delay, showing the shutdown window was cut short"
        )
    finally:
        _cleanup(*(p for p in (init_proc, subject_proc) if p is not None))


def _load_supervisor_module() -> ModuleType:
    """A fresh import per test (never the cached `sys.modules` entry) so
    each test gets its own `_registered_pgid` global, isolated from every
    other test - this test binds its own socket directly rather than
    calling the module's blocking `main()`, so `CONTROL_SOCKET_PATH`
    itself is never read here."""
    spec = importlib.util.spec_from_file_location("skillc_supervisor_under_test", REAL_SUPERVISOR)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_supervisor_refuses_pgid_at_or_below_1_and_its_own_process_group(tmp_path: Path) -> None:
    """Must-fix (review, PR #182): accepting a registered `pgid <= 1` or the
    supervisor's OWN process group would make `_on_term`'s later
    `os.killpg(pgid, SIGTERM)` signal itself - a TERM storm (the handler
    re-entering itself via the very signal it just sent), not merely a
    wrong relay target. Exercises the real wire protocol (a real socket,
    real `REGISTER` lines) against `_accept_loop` directly - never calls
    the blocking `main()` - so a bad registration must leave
    `_registered_pgid` exactly as it was, and a subsequent GOOD one must
    still be accepted afterward (a bad message must not wedge the
    listener)."""
    sock_path = tmp_path / "control.sock"
    mod = _load_supervisor_module()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(8)
    threading.Thread(target=mod._accept_loop, args=(server,), daemon=True).start()

    def _register(pgid: int) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2.0)
            client.connect(str(sock_path))
            client.sendall(f"REGISTER {pgid}\n".encode())
            try:
                client.recv(64)
            except OSError:
                pass

    subject = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True)
    try:
        _register(1)
        assert mod._registered_pgid is None, "pgid 1 must be refused"

        _register(os.getpgrp())  # this test process's OWN group - accept_loop runs in this same process
        assert mod._registered_pgid is None, "the supervisor's own process group must be refused"

        _register(subject.pid)  # a real, independent, freshly-sessioned process group
        assert mod._registered_pgid == subject.pid, "a legitimate registration after bad ones must still land"
    finally:
        server.close()
        if subject.poll() is None:
            os.killpg(subject.pid, signal.SIGKILL)
        subject.wait(timeout=5)


def test_a_bind_failure_falls_through_to_the_pause_loop_rather_than_crashing(tmp_path: Path) -> None:
    """Should-fix (review, PR #182): a bind failure must not exit this
    process - it is `tini`'s only child, and exiting would take the
    container down at `prepare()` time exactly like relaying-then-exiting
    would. Forces a bind failure by pointing the control socket's parent
    directory at a path that already exists as a plain FILE (`os.makedirs`
    still raises there even with `exist_ok=True`, since the existing entry
    is not a directory), then asserts the real subprocess is still running
    well after it would have exited if the exception had propagated."""
    broken_dir = tmp_path / "not-a-dir"
    broken_dir.touch()
    sock_path = broken_dir / "control.sock"
    env = {**os.environ, "SKILLC_CONTROL_SOCKET": str(sock_path)}
    proc = subprocess.Popen(
        [sys.executable, str(REAL_SUPERVISOR)], env=env, start_new_session=True, stderr=subprocess.PIPE,
    )
    try:
        time.sleep(0.3)
        assert proc.poll() is None, "the supervisor exited after a bind failure - it must fall through instead"
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
    stderr = proc.stderr.read().decode() if proc.stderr else ""
    assert "could not bind" in stderr
