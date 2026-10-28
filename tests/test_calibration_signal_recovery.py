"""Real PID signals at controlled lifecycle seams; no Docker or model claims."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from test_calibration_run import _IMAGE_DIGEST, _TEST_PINS, _declaration
from test_lifecycle import FAKE_CLIENT, FakeBackend

from skillc import calibration_run as cr
from skillc import cli, lifecycle, trial
from skillc import collection_conformance as cc
from skillc import matched_pilot as mp
from skillc.backend import ExecuteResult, Limits

ROOT = Path(__file__).resolve().parent.parent
WAIT_SECONDS = 90


def _pause(base: Path, stage: str, experiment: trial.Experiment, attempt_id: str) -> None:
    """Publish readiness only after inspecting the actual durable artifacts."""
    data = {"pid": os.getpid(), "stage": stage, "attempt_id": attempt_id,
            "ignored": signal.getsignal(signal.SIGINT) == signal.SIG_IGN,
            "dispatched": any(e["event"] == "dispatched" for e in experiment.events(attempt_id)),
            "lifecycle_exists": (experiment.root / f"lifecycle-{attempt_id}.json").exists()}
    (base / "ready.tmp").write_text(json.dumps(data))
    (base / "ready.tmp").replace(base / "ready.json")
    deadline = time.monotonic() + WAIT_SECONDS
    while not (base / "release").exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"controller handshake expired: {data}")
        time.sleep(0.02)


def _controller(base: Path, stage: str) -> int:
    declaration = _declaration(attempts=2)
    (base / "declaration.json").write_text(json.dumps(declaration.data))
    run_dir = base / "run"
    run_dir.mkdir()
    calls: list[str] = []

    def attempt(**kwargs: Any) -> dict[str, object]:
        experiment, attempt_id = kwargs["experiment"], kwargs["attempt_id"]
        calls.append(attempt_id)
        (base / "calls.json").write_text(json.dumps(calls))
        active = len(calls) == 2
        if active and stage == "before-dispatch":
            _pause(base, stage, experiment, attempt_id)

        class ControlledBackend(FakeBackend):
            def execute(self, handle: object, argv: Any, limits: Limits,
                        cancel: Any = None, stdin: bytes | None = None) -> ExecuteResult:
                if active and stage == "after-dispatch":
                    _pause(base, stage, experiment, attempt_id)
                if active and stage == "during-execution":
                    source = base / "subject.py"
                    data = {"pid": os.getpid(), "stage": stage, "attempt_id": attempt_id,
                            "ignored": signal.getsignal(signal.SIGINT) == signal.SIG_IGN,
                            "dispatched": any(e["event"] == "dispatched" for e in experiment.events(attempt_id)),
                            "lifecycle_exists": (experiment.root / f"lifecycle-{attempt_id}.json").exists()}
                    source.write_text(
                        "import json,os,time\nfrom pathlib import Path\n"
                        + f"base=Path({str(base)!r})\ndata={data!r}\n"
                        + "data['subject_pid']=os.getpid()\n"
                        + "Path('out.txt').write_text('controlled execution')\n"
                        + "(base/'ready.tmp').write_text(json.dumps(data))\n"
                        + "(base/'ready.tmp').replace(base/'ready.json')\n"
                        + "deadline=time.monotonic()+90\n"
                        + "while not (base/'release').exists():\n"
                        + " if time.monotonic()>=deadline: raise RuntimeError('subject release expired')\n"
                        + " time.sleep(.02)\n")
                    argv = [sys.executable, str(source)]
                result = super().execute(handle, argv, limits, cancel, stdin)
                if active and stage == "after-execution":
                    assert result.reason == "exited" and result.exit_code == 0
                    # The real fixture subprocess has exited and been reaped.
                    # No subject can become an orphan when the controller dies.
                    _pause(base, stage, experiment, attempt_id)
                return result

            def destroy(self, handle: object) -> None:
                # The general lifecycle fake removes its files only. This
                # signal fixture additionally owns and reaps its live subject.
                proc = getattr(handle, "proc", None)
                if proc is not None and proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=30)
                super().destroy(handle)

        record = lifecycle.run_through_backend(
            ControlledBackend(base / "backend"), experiment, attempt_id,
            [sys.executable, str(FAKE_CLIENT), "work"], surface={}, limits=Limits(timeout=60), base=base,
            completion_deadline=kwargs["completion_deadline"],
        )
        # Controlled metadata, not a model execution or a spending measurement.
        record["observation"] = {"run_metadata": {"model": "gpt-6-astra", "reasoning_effort": "high"}}
        record["codex_guard"] = {"stop": None}
        return record

    cc.run_level1_agent_attempt = attempt
    try:
        cr.run_calibration(
            declaration, run_dir=run_dir, root=ROOT,
            treatment=cr.Treatment({"skill": b"body"}, "sha256:" + "ab" * 32, None, skill_digests=_TEST_PINS),
            image_digest=_IMAGE_DIGEST, backends=lambda: (object(), object()), argv_for=lambda _: ["codex"],
        )
    except KeyboardInterrupt:
        return 130
    return 0


def _wait_ready(base: Path, proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_SECONDS
    while not (base / "ready.json").exists():
        if proc.poll() is not None or time.monotonic() >= deadline:
            pytest.fail(f"no ready handshake; exit={proc.poll()}; log={(base / 'controller.log').read_text()}")
        time.sleep(0.02)
    return json.loads((base / "ready.json").read_text())  # type: ignore[no-any-return]


def _spawn(base: Path, stage: str, ignored: bool = False) -> subprocess.Popen[bytes]:
    # exec preserves ignored signals. The opposite really inherits SIG_IGN,
    # instead of setting it after Python's startup policy has already run.
    launcher = ("import os,signal,sys; "
                "signal.signal(signal.SIGINT, signal.SIG_IGN if sys.argv[1]=='ignored' else signal.SIG_DFL); "
                "os.execv(sys.executable,[sys.executable,*sys.argv[2:]])")
    with (base / "controller.log").open("wb") as log:
        return subprocess.Popen(
            [sys.executable, "-c", launcher, "ignored" if ignored else "default", __file__, str(base), stage],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )


def _cleanup(base: Path, proc: subprocess.Popen[bytes]) -> None:
    (base / "release").touch()
    if proc.poll() is None:
        try:
            proc.wait(timeout=WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=WAIT_SECONDS)


def _recover(base: Path) -> dict[str, Any]:
    code = cli.main(["calibration-report", str(base / "run"), "--declaration", str(base / "declaration.json")])
    assert code in (0, 1), (base / "controller.log").read_text()
    return json.loads((base / "run" / cr.REPORT_FILENAME).read_text())  # type: ignore[no-any-return]


@pytest.mark.timeout(300)
@pytest.mark.parametrize("stage", ["after-dispatch", "during-execution", "after-execution"])
@pytest.mark.parametrize("ignored", [False, True], ids=["default", "inherited-ignore"])
def test_pid_sigint_stops_the_controller_unless_startup_ignored_it(
    tmp_path: Path, stage: str, ignored: bool,
) -> None:
    proc = _spawn(tmp_path, stage, ignored)
    try:
        ready = _wait_ready(tmp_path, proc)
        assert ready["pid"] == proc.pid and ready["ignored"] is ignored
        assert ready["dispatched"] and not ready["lifecycle_exists"]
        _, prefix = mp.read_outcomes(tmp_path / "run")
        assert len(prefix) == 1  # One complete checkpoint before the active second slot.
        os.kill(proc.pid, signal.SIGINT)
        if ignored:
            (tmp_path / "release").touch()
        code = proc.wait(timeout=WAIT_SECONDS)
        calls = json.loads((tmp_path / "calls.json").read_text())
        if "subject_pid" in ready:
            assert ready["subject_pid"] != proc.pid
            with pytest.raises(ProcessLookupError):
                os.kill(ready["subject_pid"], 0)
        assert code == (0 if ignored else 130), (tmp_path / "controller.log").read_text()
        assert len(calls) == (4 if ignored else 2)
        _, checkpoint = mp.read_outcomes(tmp_path / "run")
        assert len(checkpoint) == 4
        report = _recover(tmp_path)
        dispositions = [row["disposition"] for row in report["attempts"]]
        assert dispositions == (["captured"] * 4 if ignored else ["captured", "inconclusive", "not-run", "not-run"])
    finally:
        _cleanup(tmp_path, proc)


@pytest.mark.timeout(300)
@pytest.mark.parametrize("stage", ["before-dispatch", "after-dispatch", "after-execution"])
def test_sigkill_recovery_distinguishes_dispatched_from_never_started(tmp_path: Path, stage: str) -> None:
    proc = _spawn(tmp_path, stage)
    try:
        ready = _wait_ready(tmp_path, proc)
        dispatched = stage != "before-dispatch"
        assert ready["dispatched"] is dispatched and not ready["lifecycle_exists"]
        checkpoint = (tmp_path / "run" / cr.OUTCOMES_FILENAME).read_bytes()
        _, prefix = mp.read_outcomes(tmp_path / "run")
        assert len(prefix) == 1
        os.kill(proc.pid, signal.SIGKILL)
        assert proc.wait(timeout=WAIT_SECONDS) == -signal.SIGKILL
        assert len(json.loads((tmp_path / "calls.json").read_text())) == 2
        assert (tmp_path / "run" / cr.OUTCOMES_FILENAME).read_bytes() == checkpoint
        report = _recover(tmp_path)
        rows = report["attempts"]
        assert len(rows) == 4 and rows[1]["attempt_id"] == ready["attempt_id"]
        assert [r["disposition"] for r in rows] == [
            "captured", "inconclusive" if dispatched else "not-run", "not-run", "not-run"]
    finally:
        _cleanup(tmp_path, proc)


if __name__ == "__main__":
    raise SystemExit(_controller(Path(sys.argv[1]), sys.argv[2]))
