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
`xfail(strict=True)` on every non-`none` mode, `raises=` looked up per
mode: a break that fails to actually break anything surfaces as XPASS,
not a silent pass.

`raises=` a PER-PROPERTY `_PropertyHeld` subtype, not one shared type
(issue #341, counter-model review on #336's own fix): `raises=
AssertionError` was passed here originally (too WIDE - every
assertion, setup and property alike, raised that same base type); #336
narrowed it to one shared `_PropertyHeld`, which closed that gap but
opened a different one - a NEIGHBORING property's own failure, within
the SAME break-mode run, could also satisfy the marker, since every
property shared one type. Fixed by giving each its own subtype -
`_ConcurrentAccessPropertyHeld` (property 1: `concurrent_reply
["exit_code"] == 0`) and, for property 2, `_KillConfirmationPropertyHeld`
(`gate_pid_alive is False`, `kill_run.stop_confirmed is True` - targeted
by BOTH `stale-confirm-lie` and `kill-wrong-pid`) plus
`_PrimaryUnaffectedPropertyHeld` (the primary-unaffected checks
`primary_result[0].reason`/`exit_code`/`counter_after > counter_before` -
`kill-wrong-pid`'s own additional observable). `kill-wrong-pid`'s marker accepts only confirmed survival of the actual
gate. A primary-only failure stays an unrelated hard failure. Each
check is still asserted UNCONDITIONALLY and IDENTICALLY across every
mode where it applies, never branched to check "the break occurred"
instead of "the real property held" (audited: this file was already
unbranched this way, so no XPASS-by-construction fix was ever needed,
only the exception granularity). Every other check (handle/channel
preconditions, `concurrent_reply`/`kill_reply`'s own `reason` sanity
checks, the thread having joined) stays a plain `assert`.

KNOWN LIMITATION, unverified against a real daemon: this classification
assumes each break's real symptom surfaces through the property checks
named above, never through one of the plain-assert infra checks. If a
real run ever shows otherwise, that break would report a hard FAILED
rather than the expected XFAILED - the loud direction, never a silent
pass, but worth knowing before reading such a result as "the mechanism
broke."

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
import uuid
from collections.abc import Callable, Mapping, Sequence
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
#: Written by the primary's OWN script - never discovered via `ps` (see
#: `_primary_script()`'s own docstring for why `procps` is deliberately
#: unavailable to depend on here).
PRIMARY_PID_MARKER = f"{d.CONTAINER_WORKSPACE}/primary-pid"
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


class _PropertyHeld(Exception):
    """Shared base for every property-specific exception below (issue
    #341: one subtype per independently-targeted property, so a
    NEIGHBORING property's own failure cannot satisfy a break mode's own
    `xfail(raises=...)` - counter-model review on #336's own fix, which
    gave every property in this file the same single type). Never
    raised directly."""


class _ConcurrentAccessPropertyHeld(_PropertyHeld):
    """Property 1's own targeted property: a gate reaches the SAME live
    container the primary subject is running in. `gate-in-fresh-
    container`'s own target."""


class _KillConfirmationPropertyHeld(_PropertyHeld):
    """Property 2's own targeted property: a timed-out gate's real
    in-container process is genuinely killed and independently
    confirmed. Targeted by BOTH `stale-confirm-lie` (the confirmation
    step lies) and `kill-wrong-pid` (the kill lands on the wrong
    process, so the gate's own pid survives) - the file's own prior
    comments already establish both as violations of this ONE property,
    not two different ones."""


class _PrimaryUnaffectedPropertyHeld(_PropertyHeld):
    """The primary did not remain healthy while the gate was stopped."""


_EXPECTED_PROPERTY_EXCEPTION: dict[str, type[_PropertyHeld]] = {
    "gate-in-fresh-container": _ConcurrentAccessPropertyHeld,
    "stale-confirm-lie": _KillConfirmationPropertyHeld,
    "kill-wrong-pid": _KillConfirmationPropertyHeld,
}


def _require(condition: bool, message: str, exc_type: type[_PropertyHeld]) -> None:
    if not condition:
        raise exc_type(message)


def _check_concurrent_reply(reply: Mapping[str, object], *, missing_marker_confirmed: bool) -> None:
    assert reply["reason"] == "exited", "concurrent gate did not launch and exit normally"
    assert reply["exit_code"] in (0, 1), "unexpected concurrent gate exit"
    if reply["exit_code"] != 0:
        assert missing_marker_confirmed, "no independent missing-primary-marker observation"
    _require(reply["exit_code"] == 0, "gate did not reach the primary container", _ConcurrentAccessPropertyHeld)


def _check_kill_observation(alive: bool | None, confirmed: bool | None) -> None:
    assert type(alive) is bool, "gate liveness is unknown"
    _require(not alive, "the actual gate process survived the kill", _KillConfirmationPropertyHeld)
    assert confirmed is True, "dead gate and witness kill confirmation disagree"


def _check_primary(results: list[ExecuteResult], before: int, after: int) -> None:
    _require(
        bool(results) and results[0].reason == "exited" and results[0].exit_code == 0 and after > before,
        "the primary did not remain healthy across the gate", _PrimaryUnaffectedPropertyHeld,
    )


def _make_fresh_exec(real_exec: Callable[..., ExecuteResult], observations: list[tuple[int | None, str | None]]):
    """Substitute only gate transport; preserve all current exec arguments.

    #338's prospective confine_root argument must be integrated only after
    that production dependency merges. This helper targets the current API.
    """
    def fresh_container_exec(
        self: d.DockerBackend, _handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
        cwd: str | None = None, env: Mapping[str, str] | None = None,
    ) -> ExecuteResult:
        fresh_handle = self.prepare(f"a-gw-live-fresh-container-{uuid.uuid4().hex[:12]}")
        try:
            assert isinstance(fresh_handle, d._Handle)
            _prepare_candidate_workspace(self, fresh_handle)
            self.install(fresh_handle, {})
            result = real_exec(self, fresh_handle, argv, limits, cancel, stdin, cwd=cwd, env=env)
            assert result.reason == "exited" and result.error is None, "fresh gate transport failed"
            output = _read_file_via_exec(self, fresh_handle, f"{d.CONTAINER_WORKSPACE}/observations")
            assert output is not None, "fresh gate output unavailable"
            observations.append((result.exit_code, output))
            return result
        finally:
            self.destroy(fresh_handle)
    return fresh_container_exec


def _run_primary(
    real_exec: Callable[..., ExecuteResult], backend: d.DockerBackend, handle: object,
    results: list[ExecuteResult], errors: list[Exception],
) -> None:
    try:
        results.append(real_exec(
            backend, handle, ["python3", "-c", _primary_script()], Limits(timeout=PRIMARY_DURATION_SECONDS + 10),
        ))
    except Exception as exc:  # noqa: BLE001 - re-raised by the owning test thread
        errors.append(exc)


def _destroy_and_join(backend: d.DockerBackend, handle: object, primary: threading.Thread | None) -> None:
    try:
        backend.destroy(handle)
    finally:
        if primary is not None:
            primary.join(timeout=backend.daemon_timeout + GATE_GRACE)
            assert not primary.is_alive(), "primary worker did not stop after container cleanup"


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
    """Writes its OWN pid to `PRIMARY_PID_MARKER` and `PRIMARY_MARKER`
    (property 1's own oracle - only a gate reaching this SAME container
    can read it) once at startup, then increments `PRIMARY_COUNTER` once
    per second for the test's whole duration, then exits 0 - the intact-
    run assertion a broken kill (`kill-wrong-pid`) must interrupt.

    `PRIMARY_PID_MARKER` is written by the primary ITSELF, never
    discovered via `ps`/`procps` (codex:code_review finding: `python:
    3.12-slim` is chosen specifically because it LACKS `procps` - a
    `kill-wrong-pid` setup that depended on `ps` would fail before either
    gate even ran, satisfying `xfail(strict=True)` on a missing tool, not
    on the intended mistargeted-kill behavior)."""
    # The counter is published via a temp-file-then-os.replace() swap, not a
    # direct truncating open("w") - codex:code_review finding: a `docker exec
    # cat` landing between this script's own truncate and write would read
    # an empty file, and `_read_counter()` turns that into a spurious zero
    # indistinguishable from "never ticked". `os.replace()` on the same
    # filesystem is atomic, so a concurrent reader sees either the whole
    # prior value or the whole new one, never a truncated in-between.
    return (
        "import os, time\n"
        f"with open({PRIMARY_PID_MARKER!r}, 'w') as f:\n"
        "    f.write(str(os.getpid()))\n"
        f"with open({PRIMARY_MARKER!r}, 'w') as f:\n"
        "    f.write('primary-is-here')\n"
        f"for i in range(1, {PRIMARY_DURATION_SECONDS} + 1):\n"
        f"    tmp = {PRIMARY_COUNTER!r} + '.tmp'\n"
        "    with open(tmp, 'w') as f:\n"
        "        f.write(str(i))\n"
        f"    os.replace(tmp, {PRIMARY_COUNTER!r})\n"
        "    time.sleep(1)\n"
    )


def _concurrent_gate_argv() -> list[str]:
    """Case (a): exits on its own, reporting whether it can see the
    primary's marker - exit 0 only if the marker is readable, exit 1
    otherwise. The fresh-container control also requires the exact fixed
    missing-marker observation before crediting the targeted failure.
    Raw container output is never published in the test report."""
    script = (
        f"import sys, os; present = os.path.isfile({PRIMARY_MARKER!r}); "
        "print('PRIMARY_MARKER: present' if present else 'PRIMARY_MARKER: absent'); "
        "sys.exit(0 if present else 1)"
    )
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


def _read_file_via_exec(backend: d.DockerBackend, handle: d._Handle, path: str) -> str | None:
    """A cheap, pollable read - `docker exec cat <path>`, never the
    heavier `export()`+tar-extract round trip `_read_counter`'s own
    first draft used for every single poll attempt (codex:code_review
    finding: a fixed `time.sleep` before checking readiness is fragile
    on a loaded VM; polling needs each check to be cheap). `None` when
    the file does not exist yet or the exec itself could not be reached -
    both read the same as "not ready", never as a hard failure, since
    "not yet written" is the expected state before the primary starts."""
    try:
        proc = subprocess.run(
            [*backend.docker_bin, "exec", "--", handle.name, "cat", path],
            capture_output=True, text=True, timeout=backend.daemon_timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _wait_for_file_via_exec(backend: d.DockerBackend, handle: d._Handle, path: str, deadline_seconds: float) -> str:
    """Polls `_read_file_via_exec` until it returns content or the
    deadline elapses - replaces a fixed `time.sleep` before assuming the
    primary has started (codex:code_review finding: too short flakes on
    a loaded VM, and a long fixed sleep eats into the primary's own
    bounded lifetime either way)."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        content = _read_file_via_exec(backend, handle, path)
        if content is not None:
            return content
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for a file to appear in the container (after {deadline_seconds}s)")


def _read_int_file_via_exec(backend: d.DockerBackend, handle: d._Handle, path: str) -> int:
    content = _read_file_via_exec(backend, handle, path)
    assert content is not None, "expected file was not found in the container"
    text = content.strip()
    assert text.isdigit(), f"expected file did not contain a plain integer (len={len(text)})"
    return int(text)


def _read_counter(backend: d.DockerBackend, handle: d._Handle) -> int:
    content = _read_file_via_exec(backend, handle, PRIMARY_COUNTER)
    if content is None:
        return 0
    text = content.strip()
    return int(text) if text.isdigit() else 0


def _read_gate_pid(backend: d.DockerBackend, handle: d._Handle) -> int:
    return _read_int_file_via_exec(backend, handle, GATE_PID_MARKER)


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


def _prepare_candidate_workspace(backend: d.DockerBackend, handle: d._Handle) -> None:
    """Hands `CONTAINER_WORKSPACE` to the candidate, as the real trial image
    (`docker/trial/Dockerfile`, `WORKDIR /work` under `USER candidate`)
    already does. On a bare `python:3.12-slim` Docker creates the `-w`
    workdir root-owned, so the primary's marker writes failed with
    `Permission denied` and this test timed out waiting for them (#355).
    Runs AS ROOT (`exec -u 0`), before the primary starts; a no-op on the
    trial image."""
    owner = f"{d.CANDIDATE_UID}:{d.CANDIDATE_GID}"
    setup = subprocess.run(
        [*backend.docker_bin, "exec", "-u", "0", "--", handle.name,
         "sh", "-c", 'mkdir -p "$1" && chown "$2" "$1"', "sh", d.CONTAINER_WORKSPACE, owner],
        capture_output=True, timeout=backend.daemon_timeout, check=False,
    )
    assert setup.returncode == 0, f"could not prepare the candidate's workspace: {setup.stderr!r}"


@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True,
    raises=_EXPECTED_PROPERTY_EXCEPTION.get(BREAK_MODE, _PropertyHeld),
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
    # Per-run suffix and everything after `prepare()` inside the `try`
    # (#355): a fixed name plus a setup step outside the `try` leaked the
    # container, and the leak failed every later run on a name `Conflict`.
    handle = backend.prepare(f"a-gw-live-conformance-{uuid.uuid4().hex[:12]}")
    primary_thread: threading.Thread | None = None
    real_exec = d.DockerBackend.exec_in_attempt
    fresh_observations: list[tuple[int | None, str | None]] = []
    try:
        assert isinstance(handle, d._Handle)
        assert handle.trigger_channel is not None
        _prepare_candidate_workspace(backend, handle)
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
            monkeypatch.setattr(d.DockerBackend, "exec_in_attempt", _make_fresh_exec(real_exec, fresh_observations))

        primary_pid_holder: list[int] = []
        injected_targets: list[tuple[int, int]] = []
        if BREAK_MODE == "kill-wrong-pid":
            # Property 2's own break: the kill-confirmation sequence targets
            # the PRIMARY's own in-container pid instead of the gate's real
            # one - read back via the SAME marker-file mechanism
            # `exec_in_attempt()` itself uses, applied to the primary's own
            # process this time (`PRIMARY_PID_MARKER`, written by the primary
            # script itself - never discovered via `ps`/`procps`, which
            # `python:3.12-slim` deliberately lacks; see `_primary_script()`'s
            # own docstring for the codex:code_review finding this fixes).
            real_read_pid = d.DockerBackend._read_in_container_pid

            def targeting_the_primary(self: d.DockerBackend, handle_: d._Handle, marker_path: str, timeout: float = 2.0) -> int | None:
                actual = real_read_pid(self, handle_, marker_path, timeout)
                if primary_pid_holder:
                    assert actual is not None, "actual exec PID was not observed"
                    injected_targets.append((actual, primary_pid_holder[0]))
                    return primary_pid_holder[0]
                return actual

            monkeypatch.setattr(d.DockerBackend, "_read_in_container_pid", targeting_the_primary)

        primary_result: list[ExecuteResult] = []
        primary_errors: list[Exception] = []
        primary_thread = threading.Thread(
            target=_run_primary, args=(real_exec, backend, handle, primary_result, primary_errors), daemon=True,
        )
        primary_thread.start()
        # Bounded poll for primary readiness, never a blind sleep (codex:
        # code_review finding: a fixed delay is both too short on a
        # loaded VM and eats into the primary's own bounded lifetime
        # either way).
        _wait_for_file_via_exec(backend, handle, PRIMARY_MARKER, deadline_seconds=10.0)

        primary_pid = _read_int_file_via_exec(backend, handle, PRIMARY_PID_MARKER)
        assert primary_pid > 0, "invalid primary PID"
        if BREAK_MODE == "kill-wrong-pid":
            primary_pid_holder.append(primary_pid)

        # Case (a): a concurrent gate that exits on its own, proving
        # property 1 (or its negation, under gate-in-fresh-container).
        concurrent_reply = _run_gate_over_socket(socket_path, "concurrent-gate")
        _check_concurrent_reply(
            concurrent_reply, missing_marker_confirmed=fresh_observations == [(1, "PRIMARY_MARKER: absent\n")],
        )

        # Case (b): a TERM-ignoring gate past its timeout, forcing the
        # kill-confirmation path. `counter_before`/`counter_after` bracket
        # ONLY this call (codex:code_review finding 3) - not case (a), and
        # not the independent-oracle reads below - so the final monotonic-
        # progress assertion proves progress across THIS window, not
        # merely across the whole test.
        counter_before = _read_counter(backend, handle)
        kill_reply = _run_gate_over_socket(socket_path, "kill-timeout-gate")
        counter_after = _read_counter(backend, handle)
        assert kill_reply["reason"] in ("timeout", "operator-cancelled")

        # Independent identities come from the processes' own marker files,
        # not the monkeypatched backend PID reader.
        gate_pid = _read_gate_pid(backend, handle)
        assert gate_pid > 0 and gate_pid != primary_pid, "ambiguous primary/gate identities"
        if BREAK_MODE == "kill-wrong-pid":
            assert (gate_pid, primary_pid) in injected_targets, "wrong-target injection did not reach the timed-out gate"
        gate_pid_alive = _real_daemon_pid_is_alive(backend, handle, gate_pid)

        primary_thread.join(timeout=PRIMARY_DURATION_SECONDS + 15)
        assert not primary_thread.is_alive(), "the primary subject never finished"
        if primary_errors:
            raise primary_errors[0]
    finally:
        _destroy_and_join(backend, handle, primary_thread)

    record = witness.finalize(handle.attempt_id)
    kill_run = record.gates["kill-timeout-gate"].runs[-1]

    _check_kill_observation(gate_pid_alive, kill_run.stop_confirmed)
    _check_primary(primary_result, counter_before, counter_after)
