"""The live-Docker conformance test for #269's gate-execution witness -
`exec_in_attempt()`'s own docstring names this gap explicitly: "A REAL
daemon's `docker exec` behavior for this three-exec sequence ... is
exercised here only against the fake CLI ... named as owed."

Four properties, proven against a REAL daemon rather than the fake CLI's
host-process simulation (plan reviewed and approved on issue #269,
comment 6023059101, with the three changes recorded in the review
comment that follows it):

1. CONCURRENT EXEC INTO ONE LIVE CONTAINER. A gate can `exec_in_attempt()`
   into the SAME running container the primary subject's own `execute()`
   call is concurrently still inside - proven by the gate reading a
   marker file only the primary (running the whole time) can have
   written, in the SAME container.
2. SELECTIVE, CONFIRMED KILL. A timed-out gate's in-container PID is
   killed and the kill independently confirmed via a real `kill -0` -
   never the primary's own PID, never the whole container - proven by
   the primary's own progress counter continuing to advance across the
   gate's kill window.
3. THE PID-MARKER ROUND TRIP persists across two separate real `docker
   exec` invocations into the same container - exercised by every intact
   case below (both read back a marker a PRIOR exec wrote). No dedicated
   break mode for this property: every attempt to construct one collapses
   into either property 1's or property 2's own break mode, so none is
   added here rather than inventing a redundant one (orchestrator review:
   "optional; say so in the docstring rather than inventing one").
4. NO STANDALONE `kill` BINARY NEEDED on a real minimal image's real
   shell - the intact run uses `python:3.12-slim` (the CI gate step's own
   image) precisely because it does not ship `procps`.

ONE TEST FUNCTION, SKILLC_GATE_WITNESS_LIVE_BREAK SELECTS THE MODE - same
shape as `test_decide_reply_channel_live.py`'s `SKILLC_LIVE_TEST_BREAK`.
`xfail(strict=True)` on every non-`none` mode: a break that fails to
actually break anything surfaces as XPASS, not a silent pass.

    none               (default) BOTH intact cases pass:
                        (a) a concurrent gate that exits on its own;
                        (b) a TERM-ignoring gate past its timeout, killed
                            and confirmed, primary unaffected.
    stale-confirm-lie   the kill-confirmation step is monkeypatched to
                        unconditionally report True without checking -
                        the test's OWN independent `kill -0` must still
                        find the gate's pid alive, catching the lie.
    kill-wrong-pid      the in-container pid the kill sequence targets is
                        monkeypatched to the PRIMARY's own pid instead of
                        the gate's real one - the primary's counter must
                        stop advancing (or `execute()` must report it was
                        killed), never the gate's own kill succeeding
                        quietly on the wrong target.
    gate-in-fresh-container
                        `exec_in_attempt()` is monkeypatched to run the
                        gate's argv in a brand-new, separate container
                        instead of the live one - the gate must NOT see
                        the primary's marker, proving property 1 is what
                        actually held in the intact run.

Per orchestrator review C3: no exact-count timing assertions (flakes on a
loaded VM). Assert MONOTONIC counter progress across the gate's own
window instead, plus the primary's own exit code.

Every container this file starts is removed in a `finally` - never left
to the runner's own prune.

LEAK SAFETY: no host `base_dir` path or raw container name is ever
printed into an assertion message or any captured value this file
returns - every assertion compares in-memory integers/booleans/exit
codes; where a subprocess's stderr is inspected, only for the same
known-static substrings `_confirm_and_kill_in_container`'s own code
already matches on ("no such process"), never logged wholesale.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc.backend import ExecuteResult, Limits
from skillc.gate_witness import GateWitness

LIVE_TEST_IMAGE = os.environ.get("SKILLC_LIVE_TEST_IMAGE", "python:3.12-slim")
BREAK_MODE = os.environ.get("SKILLC_GATE_WITNESS_LIVE_BREAK", "none")
_VALID_BREAK_MODES = ("none", "stale-confirm-lie", "kill-wrong-pid", "gate-in-fresh-container")

PRIMARY_MARKER = f"{d.CONTAINER_WORKSPACE}/primary-marker"
PRIMARY_COUNTER = f"{d.CONTAINER_WORKSPACE}/primary-counter"
#: Written by the kill-timeout gate's OWN script, at a path the test
#: knows in advance - `exec_in_attempt()`'s own internal marker path is a
#: fresh uuid per call and not something a caller should need to predict,
#: but the test needs the gate's real in-container pid independently of
#: anything the witness itself reports, to check `stale-confirm-lie`'s
#: claim against the real daemon rather than against the witness's own
#: (possibly lying) record of itself.
GATE_PID_MARKER = f"{d.CONTAINER_WORKSPACE}/gate-pid"
GATE_TIMEOUT = 2.0
GATE_GRACE = 2.0
#: Long enough to span: marker write, several counter ticks, the
#: concurrent gate's own exec, the kill-timeout gate's full escalation
#: window (timeout + grace), and a final counter read - generous on a
#: loaded CI VM rather than tuned tight (orchestrator review C3's own
#: reasoning extended to the primary's total runtime, not only to the
#: counter assertion).
PRIMARY_DURATION_SECONDS = 12

if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_GATE_WITNESS_LIVE_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")

_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - this test needs a real daemon for exec_in_attempt()'s own owed evidence; "
                 "real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]


def _image_available(image: str) -> bool:
    """Bounded, best-effort, matching `test_decide_reply_channel_live.py`'s
    own helper exactly - never pulls implicitly, one bounded explicit pull
    if the image isn't already present."""
    inspect = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, timeout=10, check=False,
    )
    if inspect.returncode == 0:
        return True
    pull = subprocess.run(["docker", "pull", image], capture_output=True, timeout=120, check=False)
    return pull.returncode == 0


def _primary_script() -> str:
    """Writes `PRIMARY_MARKER` once (property 1's own oracle - only a
    gate reaching this SAME container can read it), then increments
    `PRIMARY_COUNTER` once per second for the test's whole duration, then
    exits 0 - the intact-run assertion a broken kill (`kill-wrong-pid`)
    must interrupt."""
    return (
        "import time\n"
        f"with open({PRIMARY_MARKER!r}, 'w') as f:\n"
        "    f.write('primary-is-here')\n"
        f"for i in range(1, {PRIMARY_DURATION_SECONDS} + 1):\n"
        f"    with open({PRIMARY_COUNTER!r}, 'w') as f:\n"
        "        f.write(str(i))\n"
        "    time.sleep(1)\n"
    )


def _concurrent_gate_argv() -> list[str]:
    """Case (a): exits on its own, reporting whether it can see the
    primary's marker - exit 0 only if the marker is readable, exit 1
    otherwise. Never trusted via stdout text; the exit code alone is the
    oracle, matching this whole module's "no raw output" leak discipline."""
    script = f"import sys, os; sys.exit(0 if os.path.isfile({PRIMARY_MARKER!r}) else 1)"
    return ["python3", "-c", script]


def _kill_timeout_gate_argv() -> list[str]:
    """Case (b): writes its OWN pid to `GATE_PID_MARKER` (the test's
    independent oracle for `stale-confirm-lie` - see that mode's own
    comment below), then ignores TERM and sleeps far past `GATE_TIMEOUT`,
    forcing the full kill-confirmation escalation (`_confirm_and_kill_in_
    container()`'s TERM-then-KILL sequence). `exec_in_attempt()` wraps
    this argv as `sh -c 'echo $$ > MARKER; exec "$@"' sh <argv...>` - the
    `exec` replaces the shell with THIS script in place, keeping the same
    pid, so `os.getpid()` here is exactly the pid the witness's own kill
    sequence targets."""
    script = (
        "import os, signal, time\n"
        f"with open({GATE_PID_MARKER!r}, 'w') as f:\n"
        "    f.write(str(os.getpid()))\n"
        "signal.signal(signal.SIGTERM, lambda *_: None)\n"
        "time.sleep(3600)\n"
    )
    return ["python3", "-c", script]


def _real_daemon_pid_is_alive(backend: d.DockerBackend, handle: d._Handle, pid: int) -> bool | None:
    """The test's OWN independent `kill -0` against the real daemon -
    never the witness's self-report. Mirrors `_confirm_and_kill_in_
    container()`'s own `_alive()` discipline exactly (trust only an
    explicit exit-0 or a literal "no such process" in stderr; anything
    else is UNKNOWN, `None`) so this oracle cannot itself be fooled by an
    unreachable exec reading as a confident answer either way."""
    try:
        proc = subprocess.run(
            [*backend.docker_bin, "exec", "--", handle.name, "sh", "-c", f"kill -0 {pid}"],
            capture_output=True, timeout=backend.daemon_timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0:
        return True
    if "no such process" in proc.stderr.decode("utf-8", errors="replace").lower():
        return False
    return None


def _read_gate_pid(backend: d.DockerBackend, handle: d._Handle) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        backend.export(handle, dest)
        marker = dest / "gate-pid"
        assert marker.is_file(), "the kill-timeout gate never wrote its own pid marker"
        text = marker.read_text(encoding="utf-8").strip()
        assert text.isdigit(), f"gate pid marker did not contain a plain integer (len={len(text)})"
        return int(text)


def _read_counter(backend: d.DockerBackend, handle: object) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        backend.export(handle, dest)
        counter_path = dest / "primary-counter"
        if not counter_path.is_file():
            return 0
        text = counter_path.read_text(encoding="utf-8").strip()
        return int(text) if text.isdigit() else 0


def _run_gate_over_socket(socket_path: Path, gate: str) -> Mapping[str, object]:
    """One-shot framing matching `decide_reply_channel.py`'s own module
    docstring - the test plays the role of whatever external caller would
    request a gate run in production; `GateWitness.decide` does not care
    who asks, only that the request is well-formed."""
    import socket as socket_module

    with socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM) as sock:
        sock.settimeout(GATE_TIMEOUT + GATE_GRACE + 10.0)
        sock.connect(str(socket_path))
        sock.sendall((json.dumps({"op": "run_gate", "gate": gate}) + "\n").encode("utf-8"))
        sock.shutdown(socket_module.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    reply = json.loads(b"".join(chunks).decode("utf-8").splitlines()[0])
    assert reply.get("ok") is True, reply
    return reply["result"]


@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True,
    reason=f"SKILLC_GATE_WITNESS_LIVE_BREAK={BREAK_MODE} deliberately breaks one property",
)
def test_the_gate_witness_round_trips_correctly_against_a_real_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _image_available(LIVE_TEST_IMAGE):
        pytest.skip(f"image {LIVE_TEST_IMAGE!r} is not available locally and could not be pulled")

    base = Path(tempfile.mkdtemp(prefix="sk-gw-live-base-"))
    trigger_dir = Path(tempfile.mkdtemp(prefix="sk-gw-live-trig-"))
    witness_holder: list[GateWitness] = []

    def tree_digest_fn() -> str:
        return "live-test-digest"

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        return witness_holder[0].decide(request)

    backend = d.DockerBackend(
        image=LIVE_TEST_IMAGE, base_dir=base, network="none",
        trigger_decide=decide, trigger_socket_dir=trigger_dir,
    )
    handle = backend.prepare("a-gw-live-conformance-000000001")
    assert isinstance(handle, d._Handle)
    assert handle.trigger_channel is not None
    socket_path = d.trigger_socket_host_path_for(trigger_dir, handle.name)

    witness = GateWitness(
        declared_gates={
            "concurrent-gate": tuple(_concurrent_gate_argv()),
            "kill-timeout-gate": tuple(_kill_timeout_gate_argv()),
        },
        tree_digest_fn=tree_digest_fn,
        backend=backend,
        handle=handle,
        limits=Limits(timeout=GATE_TIMEOUT, grace=GATE_GRACE),
        gate_exclusivity=False,
        exclusivity_basis="live conformance test - no exclusivity claim exercised here",
    )
    witness_holder.append(witness)

    if BREAK_MODE == "stale-confirm-lie":
        # Property 2's confirmation lies: reports a kill confirmed without
        # ever independently checking. The test's own, separate `kill -0`
        # below is the only thing that can catch this.
        monkeypatch.setattr(d.DockerBackend, "_confirm_and_kill_in_container", lambda *a, **k: True)
    elif BREAK_MODE == "gate-in-fresh-container":
        # Property 1's own break: the gate runs in a DIFFERENT, freshly
        # prepared container instead of the live one, so it cannot see
        # the primary's marker - the concurrent-gate case must now report
        # exit 1 (marker not found), not 0.
        real_execute = d.DockerBackend.execute

        def fresh_container_exec(self: d.DockerBackend, _handle: object, argv, limits, cancel=None, stdin=None):
            fresh_handle = self.prepare("a-gw-live-fresh-container-000000002")
            try:
                self.install(fresh_handle, {})
                return real_execute(self, fresh_handle, argv, limits, cancel, stdin)
            finally:
                self.destroy(fresh_handle)

        monkeypatch.setattr(d.DockerBackend, "exec_in_attempt", fresh_container_exec)

    primary_pid_holder: list[int] = []
    if BREAK_MODE == "kill-wrong-pid":
        # Property 2's own break: the kill-confirmation sequence targets
        # the PRIMARY's own in-container pid instead of the gate's real
        # one - read back via the SAME marker-file mechanism
        # `exec_in_attempt()` itself uses, applied to the primary's own
        # process this time (a second, test-side marker the primary
        # script does not write - the test reads /proc directly inside
        # the container instead, never trusting a self-reported pid for
        # the thing this break mode is deliberately attacking).
        real_read_pid = d.DockerBackend._read_in_container_pid

        def targeting_the_primary(self: d.DockerBackend, handle_: d._Handle, marker_path: str, timeout: float = 2.0) -> int | None:
            if primary_pid_holder:
                return primary_pid_holder[0]
            return real_read_pid(self, handle_, marker_path, timeout)

        monkeypatch.setattr(d.DockerBackend, "_read_in_container_pid", targeting_the_primary)

    primary_result: list[ExecuteResult] = []

    def run_primary() -> None:
        primary_result.append(
            backend.execute(handle, ["python3", "-c", _primary_script()], Limits(timeout=PRIMARY_DURATION_SECONDS + 10)),
        )

    primary_thread = threading.Thread(target=run_primary)
    try:
        primary_thread.start()
        time.sleep(2.0)  # let the primary write its marker and start counting

        if BREAK_MODE == "kill-wrong-pid":
            # The primary's own in-container pid, read directly via `ps`
            # inside the SAME container the primary is running in - never
            # assumed, never self-reported by the primary script itself.
            ps_result = subprocess.run(
                [*backend.docker_bin, "exec", "--", handle.name, "sh", "-c",
                 "ps -eo pid,comm | grep python3 | head -1 | awk '{print $1}'"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            pid_text = ps_result.stdout.strip()
            assert pid_text.isdigit(), f"could not read the primary's own pid: {ps_result.stderr!r}"
            primary_pid_holder.append(int(pid_text))

        counter_before = _read_counter(backend, handle)

        # Case (a): a concurrent gate that exits on its own, proving
        # property 1 (or its negation, under gate-in-fresh-container).
        concurrent_reply = _run_gate_over_socket(socket_path, "concurrent-gate")
        assert concurrent_reply["reason"] == "exited"
        if BREAK_MODE == "gate-in-fresh-container":
            assert concurrent_reply["exit_code"] == 1  # marker NOT visible from a fresh container
        else:
            assert concurrent_reply["exit_code"] == 0  # marker IS visible from the live one

        # Case (b): a TERM-ignoring gate past its timeout, forcing the
        # kill-confirmation path - proving (or, under the two kill-
        # targeted break modes, disproving) property 2.
        kill_reply = _run_gate_over_socket(socket_path, "kill-timeout-gate")
        assert kill_reply["reason"] in ("timeout", "operator-cancelled")

        # THE INDEPENDENT ORACLE for stale-confirm-lie: read the gate's
        # own pid back from its OWN marker (never the witness's internal
        # state) and ask the real daemon directly whether it is still
        # alive - skipped for gate-in-fresh-container, whose fresh
        # container is already destroyed by the time control returns
        # here, and for which this property is not the one under test.
        gate_pid_alive: bool | None = None
        if BREAK_MODE != "gate-in-fresh-container":
            gate_pid = _read_gate_pid(backend, handle)
            gate_pid_alive = _real_daemon_pid_is_alive(backend, handle, gate_pid)

        counter_after = _read_counter(backend, handle)

        primary_thread.join(timeout=PRIMARY_DURATION_SECONDS + 15)
        assert not primary_thread.is_alive(), "the primary subject never finished"
    finally:
        backend.destroy(handle)

    record = witness.finalize(handle.attempt_id)

    if BREAK_MODE != "gate-in-fresh-container":
        # Only `none` genuinely kills the GATE's own real pid. Both other
        # modes leave it untouched, for different reasons: stale-confirm-
        # lie never sends a real kill at all; kill-wrong-pid sends a real
        # kill, but at the PRIMARY's pid, which has no bearing on whether
        # the gate's OWN sleep(3600) is still running. This oracle is the
        # one that catches stale-confirm-lie; it also happens to be true
        # (not the catching assertion, but not wrong either) for
        # kill-wrong-pid, whose own catch is the primary's fate below.
        if BREAK_MODE in ("stale-confirm-lie", "kill-wrong-pid"):
            assert gate_pid_alive is True, "the gate's own real process should have been left untouched"
        else:
            assert gate_pid_alive is False, "the gate's own pid should have been genuinely killed and confirmed"

    kill_run = record.gates["kill-timeout-gate"].runs[-1]
    if BREAK_MODE == "stale-confirm-lie":
        # The witness's OWN record agrees with its lie (expected - the
        # lie IS the witness's own report; the independent oracle above
        # is what actually catches it, not this).
        assert kill_run.stop_confirmed is True

    # Per orchestrator review C3: monotonic progress, never an exact
    # count (flakes on a loaded VM) - except kill-wrong-pid, where this
    # IS the assertion that must go red: a kill that hit the primary
    # instead of the gate stops its counter from advancing at all.
    assert primary_result and primary_result[0].reason == "exited"
    assert primary_result[0].exit_code == 0
    assert counter_after > counter_before
