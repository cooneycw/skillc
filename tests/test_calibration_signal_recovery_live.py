"""PID-only calibration interruption on real Docker; scripted, network none.

These are reproduction probes, not evidence that either historical symptom was
fixed. The inherited-ignore and never-dispatched cases are committed opposites.
Only an executed real-daemon population establishes the observed behavior.
"""
from __future__ import annotations

import ctypes
import dataclasses
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT, stamp_approval
from test_calibration_run import _TEST_PINS, _declaration_data
from test_calibration_signal_recovery import ROOT, _pause, _recover, _wait_ready
from test_codex_guard_live import _trial_image

from skillc import calibration, lifecycle, reap, trial
from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import docker_backend as d
from skillc import matched_pilot as mp
from skillc.backend import Confirmation, ExecuteResult, Limits

WAIT = 120
CONTROL = os.environ.get("SKILLC_SIGNAL_REPRO_CONTROL")
if CONTROL not in (None, "suppress-sigint", "forget-dispatch"):
    raise ValueError("unknown signal reproduction control")
pytestmark = [pytest.mark.real_docker, pytest.mark.timeout(1800),
              pytest.mark.skipif(shutil.which("docker") is None or d.probe_daemon(["docker"]) is None,
                                 reason="UNAVAILABLE: real-Docker signal/recovery reproduction not run")]
SCRIPT = b'''import json,os,time
from pathlib import Path
home=Path.home()
Path('/work/out.txt').write_text('controlled execution')
Path('/work/.skillc-canary-result').write_text('touched:'+Path('/work/.skillc-canary').read_text())
(home/'.signal-ready').write_text(json.dumps({'subject_pid':os.getpid(),'output':'controlled execution'}))
if (home/'.signal-wait').exists():
 end=time.monotonic()+120
 while not (home/'.signal-release').exists():
  if time.monotonic()>=end: raise RuntimeError('container release expired')
  time.sleep(.02)
'''


def _write(path: Path, value: object) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value))
    tmp.replace(path)


def _controller(base: Path, stage: str, image: str, digest: str) -> int:
    data = _declaration_data(attempts=2)
    shared = data["shared"]
    assert isinstance(shared, dict)
    shared["image"] = {"tag": image, "digest": digest}
    declaration = calibration.parse_declaration(stamp_approval(data))
    _write(base / "declaration.json", declaration.data)
    run_dir = base / "run"
    run_dir.mkdir()
    calls: list[str] = []

    def attempt(**kwargs: Any) -> dict[str, object]:
        experiment, attempt_id = kwargs["experiment"], kwargs["attempt_id"]
        calls.append(attempt_id)
        _write(base / "calls.json", calls)
        active = len(calls) == 2
        if active:
            # Parent retains this label-selected, independently inspected
            # immutable inventory BEFORE signalling. Never use a global sweep.
            _write(base / "active.json", {"attempt_id": attempt_id,
                                         "store": str(experiment.root)})
        if active and stage == "before-dispatch":
            _pause(base, stage, experiment, attempt_id)

        class ControlledBackend(d.DockerBackend):
            def execute(self, handle: object, argv: Any, limits: Limits,
                        cancel: Any = None, stdin: bytes | None = None, keep_running: bool = False) -> ExecuteResult:
                if active and stage == "after-dispatch":
                    _pause(base, stage, experiment, attempt_id)
                stopped = threading.Event()
                failures: list[str] = []

                def bridge() -> None:
                    try:
                        end = time.monotonic() + WAIT
                        while not stopped.is_set():
                            try:
                                receipt = json.loads(self.read_home_file(handle, ".signal-ready"))
                                break
                            except (d.BackendUnavailable, FileNotFoundError, json.JSONDecodeError):
                                if time.monotonic() >= end:
                                    raise AssertionError("container readiness timeout")
                                stopped.wait(.05)
                        else:
                            return
                        assert receipt["output"] == "controlled execution"
                        assert type(receipt["subject_pid"]) is int and receipt["subject_pid"] > 0
                        _write(base / "container-ready.json", receipt)
                        _write(base / "ready.json", {
                            "pid": os.getpid(), "stage": stage, "attempt_id": attempt_id,
                            "ignored": signal.getsignal(signal.SIGINT) == signal.SIG_IGN,
                            "dispatched": any(e["event"] == "dispatched" for e in experiment.events(attempt_id)),
                            "lifecycle_exists": (experiment.root / f"lifecycle-{attempt_id}.json").exists(),
                            "container_receipt": receipt})
                        while not stopped.is_set() and not (base / "release").exists():
                            if time.monotonic() >= end:
                                raise AssertionError("controller release timeout")
                            stopped.wait(.05)
                        if not stopped.is_set():
                            self.deliver_home_file(handle, ".signal-release", b"release")
                    except Exception as exc:  # noqa: BLE001 - publish thread failures to controller
                        failures.append(repr(exc))
                        _write(base / "bridge-error.json", failures)

                watcher = None
                if active and stage == "during-execution":
                    watcher = threading.Thread(target=bridge, daemon=True)
                    watcher.start()
                try:
                    result = super().execute(handle, argv, limits, cancel, stdin, keep_running)
                finally:
                    stopped.set()
                    if watcher is not None:
                        watcher.join(timeout=LIVE_DOCKER_DAEMON_TIMEOUT + 2)
                        assert not watcher.is_alive(), "container handshake thread not reaped"
                assert not failures, failures
                if active and stage == "after-execution":
                    assert result.reason == "exited" and result.exit_code == 0, result
                    assert self.confirm_stopped(handle) is Confirmation.CONFIRMED
                    _write(base / "execution.json", {"reason": result.reason, "exit_code": result.exit_code,
                        "stdout_bytes": result.stdout_bytes, "stop_confirmed": result.stop_confirmed})
                    _pause(base, stage, experiment, attempt_id)
                return result

        backend = ControlledBackend(image=digest, base_dir=base / "backend", network="none",
                                    daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)

        def deliver(backend: Any, handle: object) -> None:
            backend.deliver_home_file(handle, ".signal-probe.py", SCRIPT)
            if active and stage == "during-execution":
                backend.deliver_home_file(handle, ".signal-wait", b"wait")

        record = lifecycle.run_through_backend(
            backend, experiment, attempt_id, ["python3", "/home/candidate/.signal-probe.py"],
            surface={}, limits=Limits(timeout=180), base=base, before_execute=deliver,
            completion_deadline=kwargs["completion_deadline"])
        # Synthetic metadata needed by the calibration contract. No model ran,
        # no token spend is measured or claimed by this fixture.
        record["observation"] = {"run_metadata": {"model": "gpt-6-astra", "reasoning_effort": "high"}}
        record["codex_guard"] = {"stop": None}
        return record

    cc.run_level1_agent_attempt = attempt
    try:
        cr.run_calibration(declaration, run_dir=run_dir, root=ROOT,
            treatment=cr.Treatment({"skill": b"body"}, "sha256:" + "ab" * 32, None, skill_digests=_TEST_PINS),
            image_digest=digest, backends=lambda: (object(), object()), argv_for=lambda _: ["codex"])
    except KeyboardInterrupt:
        return 130
    return 0


@pytest.fixture(scope="module")
def signal_image() -> Iterator[tuple[str, str]]:
    image, built = _trial_image()
    try:
        found = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                               capture_output=True, text=True, timeout=LIVE_DOCKER_DAEMON_TIMEOUT, check=True)
        digest = found.stdout.strip()
        assert digest.startswith("sha256:") and len(digest) == 71
        yield image, digest
    finally:
        if built:
            subprocess.run(["docker", "image", "rm", image], capture_output=True,
                           timeout=LIVE_DOCKER_DAEMON_TIMEOUT, check=True)


def _start_ticks(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return None


def _descendants(pid: int) -> dict[int, str]:
    found: dict[int, str] = {}
    try:
        children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
    except FileNotFoundError:
        return found
    for child in children:
        identity = int(child)
        ticks = _start_ticks(identity)
        if ticks is not None:
            found[identity] = ticks
            found.update(_descendants(identity))
    return found


def _spawn(base: Path, stage: str, image: tuple[str, str], ignored: bool = False) -> subprocess.Popen[bytes]:
    _write(base / "reproduction-identity.json", {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "image": image[0], "image_id": image[1], "stage": stage,
        "startup_sigint": "inherited-ignore" if ignored else "default",
        "network": "none", "agent": "scripted-python-no-model"})
    launcher = ("import os,signal,sys; "
                "signal.signal(signal.SIGINT, signal.SIG_IGN if sys.argv[1]=='ignored' else signal.SIG_DFL); "
                "os.execv(sys.executable,[sys.executable,*sys.argv[2:]])")
    with (base / "controller.log").open("wb") as log:
        return subprocess.Popen([sys.executable, "-c", launcher, "ignored" if ignored else "default",
            __file__, str(base), stage, *image], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)


@pytest.fixture
def subreaper() -> Iterator[None]:
    # Adopt orphaned Docker CLI launchers so this parent can actually waitpid
    # them after SIGKILL. Restore prior state; never reap unrelated children.
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    try:
        yield
    finally:
        assert libc.prctl(36, previous.value, 0, 0, 0) == 0


def _retain(base: Path, proc: subprocess.Popen[bytes], ready: dict[str, Any]) -> dict[int, str]:
    active = json.loads((base / "active.json").read_text())
    assert active["attempt_id"] == ready["attempt_id"]
    # Verify the journal itself, not only the readiness claim.
    events = [json.loads(line) for line in (Path(active["store"]) / trial.JOURNAL / f"{ready['attempt_id']}.jsonl").read_text().splitlines()]
    _write(base / "journal-before.json", events)
    assert any(e["event"] == "dispatched" for e in events) is ready["dispatched"]
    assert not (Path(active["store"]) / f"lifecycle-{ready['attempt_id']}.json").exists()
    inventory, blocked, valid = reap._inventory(["docker"], [ready["attempt_id"]],
                                                d._docker_env(), LIVE_DOCKER_DAEMON_TIMEOUT)
    assert valid and not blocked, inventory
    _write(base / "owned-before.json", inventory)
    if ready["dispatched"]:
        assert inventory[ready["attempt_id"]]["container"], "dispatched seam has no owned container"
    launchers = _descendants(proc.pid)
    _write(base / "launchers-before.json", launchers)
    return launchers


def _cleanup(base: Path, proc: subprocess.Popen[bytes], launchers: dict[int, str]) -> None:
    launchers.update(_descendants(proc.pid))
    (base / "release").touch()
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=WAIT)
    calls_path = base / "calls.json"
    if calls_path.exists():
        ids = json.loads(calls_path.read_text())
        report = reap.reap(["docker"], ids, env=d._docker_env(), timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
        _write(base / "reaper.json", dataclasses.asdict(report))
        clean = report.clean
    else:
        clean = False
    for pid, ticks in launchers.items():
        if _start_ticks(pid) == ticks:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            # Subreaper adoption makes these owned orphan launchers waitable.
            try:
                end = time.monotonic() + WAIT
                while os.waitpid(pid, os.WNOHANG) == (0, 0):
                    assert time.monotonic() < end, f"launcher {pid} did not exit"
                    time.sleep(.02)
            except ChildProcessError:
                assert _start_ticks(pid) != ticks, f"owned launcher {pid} survived"
        assert _start_ticks(pid) != ticks, f"owned launcher {pid} survived cleanup"
    _write(base / "launcher-cleanup.json", {"confirmed_absent": list(launchers)})
    assert clean, "owned resource cleanup was not confirmed; see reaper.json"


@pytest.mark.parametrize("stage", ["after-dispatch", "during-execution", "after-execution"])
@pytest.mark.parametrize("ignored", [False, True], ids=["default", "inherited-ignore"])
def test_pid_sigint_stops_real_docker_schedule_unless_inherited_ignore(
    tmp_path: Path, signal_image: tuple[str, str], subreaper: None, stage: str, ignored: bool,
) -> None:
    proc = _spawn(tmp_path, stage, signal_image, ignored)
    launchers: dict[int, str] = {}
    try:
        ready = _wait_ready(tmp_path, proc)
        assert ready["pid"] == proc.pid and ready["ignored"] is ignored
        assert ready["dispatched"] and not ready["lifecycle_exists"]
        launchers = _retain(tmp_path, proc, ready)
        experiment, prefix = mp.read_outcomes(tmp_path / "run")
        planned = {str(a["attempt_id"]) for _, a in experiment.attempts()}
        assert len(prefix) == 1 and len(planned) == 4
        assert prefix[0].record["disposition"] == "captured"
        if CONTROL == "suppress-sigint" and not ignored:
            # Committed sabotage: continue the actual schedule without signal
            # delivery. The ordinary interrupt assertion must fail below.
            _write(tmp_path / "sabotage.json", {"control": CONTROL})
            (tmp_path / "release").touch()
        else:
            os.kill(proc.pid, signal.SIGINT)  # Deliberately PID-only.
        if ignored:
            (tmp_path / "release").touch()
        assert proc.wait(timeout=WAIT) == (0 if ignored else 130), (tmp_path / "controller.log").read_text()
        calls = json.loads((tmp_path / "calls.json").read_text())
        assert len(calls) == (4 if ignored else 2)
        _, checkpoint = mp.read_outcomes(tmp_path / "run")
        assert len(checkpoint) == 4
        native, blocked, valid = reap._inventory(
            ["docker"], calls, d._docker_env(), LIVE_DOCKER_DAEMON_TIMEOUT)
        _write(tmp_path / "native-cleanup.json", native)
        assert valid and not blocked and all(not any(resources.values()) for resources in native.values()), native
        report = _recover(tmp_path)
        assert {r["attempt_id"] for r in report["attempts"]} == planned
        assert [r["disposition"] for r in report["attempts"]] == (
            ["captured"] * 4 if ignored else ["captured", "inconclusive", "not-run", "not-run"])
    finally:
        _cleanup(tmp_path, proc, launchers)


@pytest.mark.parametrize("stage", ["before-dispatch", "after-dispatch", "during-execution", "after-execution"])
def test_sigkill_real_docker_recovery_preserves_durable_dispatch(
    tmp_path: Path, signal_image: tuple[str, str], subreaper: None, stage: str,
) -> None:
    proc = _spawn(tmp_path, stage, signal_image)
    launchers: dict[int, str] = {}
    try:
        ready = _wait_ready(tmp_path, proc)
        dispatched = stage != "before-dispatch"
        assert ready["dispatched"] is dispatched and not ready["lifecycle_exists"]
        launchers = _retain(tmp_path, proc, ready)
        path = tmp_path / "run" / cr.OUTCOMES_FILENAME
        checkpoint = path.read_bytes()
        _write(tmp_path / "checkpoint-before.json", json.loads(checkpoint))
        experiment, prefix = mp.read_outcomes(tmp_path / "run")
        planned = {str(a["attempt_id"]) for _, a in experiment.attempts()}
        assert len(prefix) == 1 and len(planned) == 4
        assert prefix[0].record["disposition"] == "captured"
        os.kill(proc.pid, signal.SIGKILL)
        assert proc.wait(timeout=WAIT) == -signal.SIGKILL
        assert len(json.loads((tmp_path / "calls.json").read_text())) == 2
        assert path.read_bytes() == checkpoint
        journal_path = experiment.journal(ready["attempt_id"])
        if CONTROL == "forget-dispatch" and dispatched:
            # Mutate only this private killed fixture. Its original journal is
            # already retained; the public recovery assertion must reject it.
            journal_path.write_bytes(b"".join(
                line for line in journal_path.read_bytes().splitlines(keepends=True)
                if json.loads(line)["event"] != "dispatched"))
            _write(tmp_path / "sabotage.json", {"control": CONTROL})
        journal = journal_path.read_bytes()
        (tmp_path / "journal-after-kill.jsonl").write_bytes(journal)
        report = _recover(tmp_path)
        recovered_events = experiment.events(ready["attempt_id"])
        before_events = [json.loads(line) for line in journal.splitlines()]
        assert recovered_events[:len(before_events)] == before_events
        _write(tmp_path / "journal-after-recovery.json", recovered_events)
        assert path.read_bytes() == checkpoint
        rows = report["attempts"]
        assert len(rows) == 4 and {r["attempt_id"] for r in rows} == planned
        assert rows[1]["attempt_id"] == ready["attempt_id"]
        assert [r["disposition"] for r in rows] == [
            "captured", "inconclusive" if dispatched else "not-run", "not-run", "not-run"]
    finally:
        _cleanup(tmp_path, proc, launchers)


if __name__ == "__main__":
    raise SystemExit(_controller(Path(sys.argv[1]), *sys.argv[2:]))
