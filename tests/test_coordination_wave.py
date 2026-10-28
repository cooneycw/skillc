"""Known-bad waves and healthy twins through owned processes and real sockets."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from skillc import coordination_wave as cw
from skillc import trial

FIXTURE = Path(__file__).parent / "fixtures" / "coordination-wave"
ACTOR = FIXTURE / "role_actor.py"
CASES = json.loads((FIXTURE / "cases.json").read_text())


def run(tmp_path: Path, **changes: Any) -> cw.WaveResult:
    base = tmp_path / "work"
    base.mkdir(exist_ok=True)
    plan = cw.WavePlan(actor_digest=trial.sha256_bytes(ACTOR.read_bytes()), **changes)
    return cw.run_wave(plan, ACTOR, tmp_path / "store", base)


def assert_resources_absent(result: cw.WaveResult) -> None:
    assert len(result.report["roles"]) == 3
    for diagnostic in result.report["roles"].values():
        aid = diagnostic["attempt_id"]
        events = result.experiment.events(aid)
        for event in events:
            if event["event"] == "started":
                with pytest.raises(ProcessLookupError):
                    os.killpg(int(str(event["pid"])), 0)
            if event["event"] == "workspace":
                assert not Path(str(event["path"])).exists()
        assert diagnostic["cleanup"] in {"removed", "not-needed"}
        assert (result.experiment.root / f"lifecycle-{aid}.json").is_file()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_committed_cases_own_real_processes_and_capture(tmp_path: Path, case: dict[str, Any]) -> None:
    fields: dict[str, Any] = {k: case[k] for k in ("mode", "deadline", "offer_delay") if k in case}
    if "order" in case:
        fields["order"] = tuple(case["order"])
    result = run(tmp_path, case_id=case["id"], **fields)
    assert_resources_absent(result)
    assert result.report["status"] == case["expected"], result.report
    assert result.report["primary"] == {"unit": "wave", "planned": 1,
                                         "completed": int(case["expected"] == "PASS")}
    assert result.report["native_wake"] == "UNOBSERVED"
    if case["mode"] == "request-flood":
        assert {"request-limit", "event-limit"} & set(result.report["unknown"])
    root = result.experiment.root
    assert trial.sha256_bytes((root / "wave-events.json").read_bytes()) == result.report["events_digest"]
    assert trial.sha256_bytes((root / "wave-plan.json").read_bytes()) == result.report["plan_digest"]
    events = json.loads((root / "wave-events.json").read_bytes())
    assert len(events) <= cw.MAX_EVENTS
    if case["expected"] == "PASS":
        offers = [e["role"] for e in events if e["event"] == "offer-decision"]
        assert offers == [*fields.get("order", cw.ROLES[1:]), "orchestrator"]
        integration = json.loads(trial.read_object(result.experiment, result.report["outputs"]["orchestrator"]))
        assert integration == {r: result.report["outputs"][r] for r in cw.ROLES[1:]}
        captured = [e["seq"] for e in events if e["event"] == "artifact-captured" and e["role"] != "orchestrator"]
        integration_offer = next(e["seq"] for e in events if e["event"] == "offer-decision" and e["role"] == "orchestrator")
        assert max(captured) < integration_offer
        for role, diagnostic in result.report["roles"].items():
            assert trial.sha256_bytes((root / f"channel-{role}.json").read_bytes()) == result.report["channel_digests"][role]
            manifest = json.loads((root / diagnostic["manifest"]).read_bytes())
            observed = next(o for o in manifest["observations"] if o["stream"] == "coordination-events")
            assert observed["origin"] == "observed" and observed["coverage"] == "complete"
            payload = json.loads(trial.read_object(result.experiment, observed["digest"]))
            assert payload["attempt_id"] == diagnostic["attempt_id"]
            assert all(e["role"] == role and e["attempt_id"] == payload["attempt_id"] for e in payload["events"])


def test_source_mismatch_refuses_before_planning(tmp_path: Path) -> None:
    base = tmp_path / "work"
    base.mkdir()
    plan = cw.WavePlan(actor_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="source identity"):
        cw.run_wave(plan, ACTOR, tmp_path / "store", base)
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("change", [{"deadline": True}, {"deadline": float("nan")},
                                    {"deadline": 31}, {"mode": "live-agent"},
                                    {"order": ("worker-a", "worker-a")}])
def test_closed_scripted_profile_refuses_invalid_inputs(tmp_path: Path, change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        run(tmp_path, **change)
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("fault", ["missing", "corrupt"])
def test_capture_loss_cannot_be_clean_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    capture = trial.capture

    def injected(experiment: trial.Experiment, aid: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            if fault == "missing":
                raise OSError("injected collector loss")
            manifest: dict[str, Any] = capture(experiment, aid, *args, **kwargs)
            artifact = next(a for a in manifest["artifacts"] if a["path"] == "output.json")
            path = experiment.object_path(artifact["digest"])
            before = path.read_bytes()
            path.chmod(0o600)
            path.write_bytes(b"corrupt captured object")
            assert path.read_bytes() != before
            return manifest
        return capture(experiment, aid, *args, **kwargs)

    monkeypatch.setattr(trial, "capture", injected)
    result = run(tmp_path, case_id="capture-" + fault)
    assert_resources_absent(result)
    assert result.report["status"] == "UNKNOWN", result.report
    assert "capture-or-controller-unavailable" in result.report["unknown"]
    assert result.report["primary"]["completed"] == 0


def test_cleanup_uncertainty_is_visible_after_real_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cleanup = trial.cleanup_workspace

    def uncertain(experiment: trial.Experiment, aid: str) -> dict[str, Any]:
        outcome = cleanup(experiment, aid)
        assert outcome["status"] == "removed"
        return {"status": "unknown", "errors": ["injected confirmation loss"]}

    monkeypatch.setattr(trial, "cleanup_workspace", uncertain)
    result = run(tmp_path, case_id="cleanup-unknown")
    assert result.report["status"] == "UNKNOWN", result.report
    assert "cleanup-unconfirmed" in result.report["unknown"]
    for role in result.report["roles"].values():
        assert role["cleanup"] == "unknown"
        assert all(not Path(str(e["path"])).exists() for e in result.experiment.events(role["attempt_id"])
                   if e["event"] == "workspace")


def test_logical_clock_expiry_is_not_native_latency(tmp_path: Path) -> None:
    ticks = iter([0.0, *([31.0] * 500)])
    base = tmp_path / "work"
    base.mkdir()
    plan = cw.WavePlan(actor_digest=trial.sha256_bytes(ACTOR.read_bytes()))
    result = cw.run_wave(plan, ACTOR, tmp_path / "store", base, clock=lambda: next(ticks))
    assert_resources_absent(result)
    assert result.report["status"] == "FAIL" and "deadline" in result.report["failures"]
    assert result.report["native_wake"] == "UNOBSERVED"


def test_launch_unavailable_is_not_a_task_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    popen = trial.subprocess.Popen

    def unavailable(argv: list[str], *args: Any, **kwargs: Any) -> Any:
        if json.loads(argv[-1])["role"] == "worker-a":
            raise FileNotFoundError("injected executable unavailable")
        return popen(argv, *args, **kwargs)

    monkeypatch.setattr(trial.subprocess, "Popen", unavailable)
    result = run(tmp_path)
    assert_resources_absent(result)
    assert result.report["status"] == "UNKNOWN", result.report


@pytest.mark.parametrize("after_start", [False, True])
def test_partial_setup_preserves_accounting_and_closes_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_start: bool,
) -> None:
    start = cw.DecideReplyChannel.start
    channels: list[cw.DecideReplyChannel] = []

    def failing(channel: cw.DecideReplyChannel) -> None:
        channels.append(channel)
        if len(channels) == 2:
            if after_start:
                start(channel)
            raise OSError("injected channel setup failure")
        start(channel)

    monkeypatch.setattr(cw.DecideReplyChannel, "start", failing)
    try:
        with pytest.raises(OSError, match="injected channel setup"):
            run(tmp_path)
        reports = list((tmp_path / "store").rglob("wave-report.json"))
        assert len(reports) == 1
        report = json.loads(reports[0].read_bytes())
        assert report["status"] == "UNKNOWN" and len(report["roles"]) == 3
        assert len(list(reports[0].parent.glob("lifecycle-*.json"))) == 3
        assert all(channel._shutdown_attempted for channel in channels if channel._started)
    finally:
        for channel in channels:
            channel.close()


def test_corruption_after_dependency_capture_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture = trial.capture
    mutated: list[Path] = []

    def injected(experiment: trial.Experiment, aid: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        manifest = capture(experiment, aid, *args, **kwargs)
        if str(experiment.trial_of(aid)["trial_id"]).endswith("orchestrator"):
            worker = next(a for t, a in experiment.attempts() if str(t["trial_id"]).endswith("worker-a"))
            worker_manifest = json.loads((experiment.root / f"manifest-{worker['attempt_id']}.json").read_bytes())
            digest = next(a["digest"] for a in worker_manifest["artifacts"] if a["path"] == "output.json")
            path = experiment.object_path(digest)
            path.chmod(0o600)
            path.write_bytes(b"corrupted after relay")
            assert trial.sha256_bytes(path.read_bytes()) != digest
            mutated.append(path)
        return manifest

    monkeypatch.setattr(trial, "capture", injected)
    result = run(tmp_path)
    assert mutated
    assert_resources_absent(result)
    assert result.report["status"] == "UNKNOWN", result.report


def test_inflight_decision_cannot_escape_captured_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decide, capture = cw._Controller.decide, trial.capture
    blocked, release = threading.Event(), threading.Event()

    def late(controller: Any, role: str, request: Any) -> Any:
        if role == "worker-a" and request.get("op") == "poll" and role in controller.claimed:
            blocked.set()
            assert release.wait(3), "test callback was not released"
        return decide(controller, role, request)

    def collected(experiment: trial.Experiment, aid: str, *args: Any, **kwargs: Any) -> Any:
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            assert blocked.is_set()
            release.set()
        return capture(experiment, aid, *args, **kwargs)

    monkeypatch.setattr(cw._Controller, "decide", late)
    monkeypatch.setattr(trial, "capture", collected)
    try:
        result = run(tmp_path, mode="late-decision")
        assert_resources_absent(result)
        assert blocked.is_set()
        assert result.report["status"] == "UNKNOWN", result.report
        assert "channel-coverage-unavailable" in result.report["unknown"]
        record = result.report["roles"]["worker-a"]
        payload = json.loads((result.experiment.root / f"events-{record['attempt_id']}.json").read_bytes())
        assert payload["channel_finalized"] is False
    finally:
        release.set()


@pytest.mark.parametrize("task_failure", [False, True])
def test_infrastructure_delay_does_not_create_secondary_task_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task_failure: bool,
) -> None:
    capture = trial.capture

    def delayed(experiment: trial.Experiment, aid: str, *args: Any, **kwargs: Any) -> Any:
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            time.sleep(0.6)
            raise OSError("injected stalled collector")
        return capture(experiment, aid, *args, **kwargs)

    monkeypatch.setattr(trial, "capture", delayed)
    result = run(tmp_path, deadline=0.5, mode="wrong-role" if task_failure else "healthy")
    assert_resources_absent(result)
    assert result.report["status"] == ("FAIL" if task_failure else "UNKNOWN"), result.report
    assert "capture-or-controller-unavailable" in result.report["unknown"]
    if task_failure:
        assert "wrong-assignment-identity" in result.report["failures"]


def test_thread_setup_failure_accounts_for_unstarted_roles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = threading.Thread.start

    def failing(thread: Any) -> None:
        if getattr(thread._target, "__name__", "") == "participant" and thread._args[0] == "worker-a":
            raise RuntimeError("injected thread setup failure")
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", failing)
    with pytest.raises(RuntimeError, match="injected thread setup"):
        run(tmp_path)
    path = next((tmp_path / "store").rglob("wave-report.json"))
    report = json.loads(path.read_bytes())
    assert report["status"] == "UNKNOWN" and len(report["roles"]) == 3
    assert report["roles"]["worker-a"]["lifecycle"] == "not-run"
    assert_resources_absent(cw.WaveResult(trial.Experiment.open(path.parent), report))


def test_report_write_crossing_deadline_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write = cw._write

    def delayed(path: Path, value: object) -> str:
        if path.name == "wave-report.json":
            time.sleep(0.7)
        return write(path, value)

    monkeypatch.setattr(cw, "_write", delayed)
    result = run(tmp_path, deadline=0.6)
    assert_resources_absent(result)
    assert result.report["status"] == "FAIL", result.report
    assert "deadline" in result.report["failures"]
    assert json.loads((result.experiment.root / "wave-report.json").read_bytes()) == result.report


def test_actor_staging_failure_preserves_planned_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write = Path.write_bytes

    def unavailable(path: Path, data: Any) -> int:
        if path.name == "actor.py" and path.parent.name.startswith("sw-"):
            raise OSError("injected actor staging loss")
        return write(path, data)

    monkeypatch.setattr(Path, "write_bytes", unavailable)
    with pytest.raises(OSError, match="injected actor staging"):
        run(tmp_path)
    reports = list((tmp_path / "store").rglob("wave-report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_bytes())
    assert report["status"] == "UNKNOWN"
    assert_resources_absent(cw.WaveResult(trial.Experiment.open(reports[0].parent), report))


def test_teardown_write_failure_preserves_first_error_and_closes_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, write = cw.DecideReplyChannel.start, cw._write
    channels: list[cw.DecideReplyChannel] = []

    def setup(channel: cw.DecideReplyChannel) -> None:
        channels.append(channel)
        start(channel)
        if len(channels) == 2:
            raise ValueError("injected original setup error")

    def lost(path: Path, value: object) -> str:
        if path.name.startswith("channel-"):
            raise OSError("injected teardown publication loss")
        return write(path, value)

    monkeypatch.setattr(cw.DecideReplyChannel, "start", setup)
    monkeypatch.setattr(cw, "_write", lost)
    try:
        with pytest.raises(ValueError, match="injected original setup"):
            run(tmp_path)
        assert all(c._shutdown_attempted for c in channels)
        path = next((tmp_path / "store").rglob("wave-report.json"))
        report = json.loads(path.read_bytes())
        assert report["status"] == "UNKNOWN" and len(report["roles"]) == 3
        assert "channel-publication-unavailable" in report["unknown"]
    finally:
        for channel in channels:
            channel.close()


def test_partial_workspace_allocation_removes_journaled_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mkdir = Path.mkdir
    failed: list[Path] = []

    def partial(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name == "work" and path.parent.parent == tmp_path / "work" and not failed:
            failed.append(path.parent)
            raise OSError("injected work subdirectory loss")
        mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", partial)
    result = run(tmp_path)
    try:
        assert failed and not failed[0].exists()
        assert_resources_absent(result)
        assert result.report["status"] == "UNKNOWN"
    finally:
        for role in result.report["roles"].values():
            if any(e["event"] == "workspace" and Path(str(e["path"])).exists()
                   for e in result.experiment.events(role["attempt_id"])):
                trial.cleanup_workspace(result.experiment, role["attempt_id"])


def test_natural_failure_survives_concurrent_infrastructure_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt, cleanup, fail = trial.run_attempt, trial.cleanup_workspace, cw._Controller.fail
    exited, cancelled = threading.Event(), threading.Event()

    def synchronized(experiment: Any, aid: str, *args: Any, **kwargs: Any) -> Any:
        result = attempt(experiment, aid, *args, **kwargs)
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            assert result["reason"] == "exited" and result["exit_code"] == 7
            exited.set()
            assert cancelled.wait(3)
        return result

    def uncertain(experiment: Any, aid: str) -> Any:
        result = cleanup(experiment, aid)
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-b"):
            assert exited.wait(3)
            return {"status": "unknown", "errors": ["injected cleanup confirmation loss"]}
        return result

    def observed(controller: Any, reason: str, **kwargs: Any) -> None:
        fail(controller, reason, **kwargs)
        if reason == "cleanup-unconfirmed":
            cancelled.set()

    monkeypatch.setattr(trial, "run_attempt", synchronized)
    monkeypatch.setattr(trial, "cleanup_workspace", uncertain)
    monkeypatch.setattr(cw._Controller, "fail", observed)
    result = run(tmp_path, mode="disappear")
    assert result.report["status"] == "FAIL", result.report
    assert "participant-exit" in result.report["failures"]
    assert "cleanup-unconfirmed" in result.report["unknown"]


@pytest.mark.parametrize("fault", ["delete", "replace"])
def test_retained_channel_evidence_is_checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    write = cw._write
    mutated: list[Path] = []

    def tampered(path: Path, value: object) -> str:
        digest = write(path, value)
        if path.name == "channel-worker-a.json":
            path.unlink()
            if fault == "replace":
                path.write_text(json.dumps({"attempt_id": "forged", "decisions": []}))
            mutated.append(path)
        return digest

    monkeypatch.setattr(cw, "_write", tampered)
    result = run(tmp_path)
    assert mutated
    assert_resources_absent(result)
    assert result.report["status"] == "UNKNOWN", result.report


def test_request_and_event_caps_refuse_the_next_input(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.report["status"] == "PASS"
    plan = cw.WavePlan(actor_digest=trial.sha256_bytes(ACTOR.read_bytes()))
    controller = cw._Controller(plan, result.experiment, time.monotonic(), time.monotonic)
    bound = controller.roles["worker-a"]
    base = {k: bound[k] for k in ("role", "session", "generation", "attempt_id")}
    base["wave"] = result.experiment.root.name
    controller.decide("worker-a", {**base, "op": "register"})
    for _ in range(cw.MAX_EVENTS - 1):
        controller.decide("worker-a", {**base, "op": "poll"})
    with pytest.raises(cw.ChannelRefusal, match="request-limit"):
        controller.decide("worker-a", {**base, "op": "poll"})
    assert controller.unknown == {"event-limit", "request-limit"}
    assert controller.cancel.is_set() and len(controller.events) == cw.MAX_EVENTS


@pytest.mark.parametrize("fault", ["write", "replace"])
def test_failed_late_publication_cannot_retain_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    write, replace = cw._write, Path.replace

    def late(path: Path, value: object) -> str:
        if path.name == "wave-report.json":
            time.sleep(0.7)
        if path.name == "wave-report-late.json" and fault == "write":
            raise OSError("injected final publication failure")
        return write(path, value)

    def unavailable(path: Path, target: Any) -> Path:
        if path.name == "wave-report-late.json" and fault == "replace":
            raise OSError("injected final publication failure")
        return replace(path, target)

    monkeypatch.setattr(cw, "_write", late)
    monkeypatch.setattr(Path, "replace", unavailable)
    with pytest.raises(OSError, match="injected final publication"):
        run(tmp_path, deadline=0.6)
    path = next((tmp_path / "store").rglob("wave-report.json"))
    assert json.loads(path.read_bytes())["status"] != "PASS"


def test_witnessed_timeout_survives_later_cleanup_loss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempt, cleanup = trial.run_attempt, trial.cleanup_workspace
    witnessed: list[Any] = []

    def observed(experiment: Any, aid: str, *args: Any, **kwargs: Any) -> Any:
        worker = str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a")
        if worker:
            kwargs["cancel"] = lambda: False
        result = attempt(experiment, aid, *args, **kwargs)
        if worker:
            assert result["reason"] == "timeout"
            witnessed.append(result)
        return result

    def lost(experiment: Any, aid: str) -> Any:
        result = cleanup(experiment, aid)
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            return {"status": "unknown", "errors": ["injected later cleanup loss"]}
        return result

    monkeypatch.setattr(trial, "run_attempt", observed)
    monkeypatch.setattr(trial, "cleanup_workspace", lost)
    result = run(tmp_path, mode="hang", deadline=0.6)
    assert witnessed and result.report["status"] == "FAIL", result.report
    assert "deadline" in result.report["failures"] and "cleanup-unconfirmed" in result.report["unknown"]


def test_natural_exit_survives_same_role_channel_loss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    finalized = cw.DecideReplyChannel.log_or_finalize

    def lost(channel: Any) -> Any:
        result = finalized(channel)
        if channel._socket_path.name == "worker-a.sock":
            raise RuntimeError("injected finalized channel observation loss")
        return result

    monkeypatch.setattr(cw.DecideReplyChannel, "log_or_finalize", lost)
    result = run(tmp_path, mode="disappear")
    assert_resources_absent(result)
    assert result.report["status"] == "FAIL", result.report
    assert "participant-exit" in result.report["failures"]
    assert "channel-coverage-unavailable" in result.report["unknown"]


@pytest.mark.parametrize("expiry_write", ["wave-report.json", "wave-report-late.json"])
def test_final_decision_emission_is_outside_completion_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expiry_write: str,
) -> None:
    write = cw._write
    ticks = [0.0]
    observed: list[str] = []

    def delayed(path: Path, value: object) -> str:
        digest = write(path, value)
        if path.name == expiry_write:
            observed.append(path.name)
            ticks[0] = 11.0  # Policy time crosses the default ten-second endpoint after this write.
        return digest

    monkeypatch.setattr(cw, "_write", delayed)
    base = tmp_path / "work"
    base.mkdir()
    plan = cw.WavePlan(actor_digest=trial.sha256_bytes(ACTOR.read_bytes()))
    result = cw.run_wave(plan, ACTOR, tmp_path / "store", base, clock=lambda: ticks[0])
    late_provisional = expiry_write == "wave-report.json"
    assert observed == [expiry_write] and len(result.report["outputs"]) == 3
    assert_resources_absent(result)
    assert not result.report["unknown"] and "incomplete-wave" not in result.report["failures"]
    assert result.report["status"] == ("FAIL" if late_provisional else "PASS"), result.report
    assert result.report["failures"] == (["deadline"] if late_provisional else [])
    assert result.report["primary"]["completed"] == int(not late_provisional)
    assert (result.report["completion_elapsed"] > plan.deadline) is late_provisional
    assert ticks[0] > plan.deadline and result.report["clock"] == "injected-policy-only"
    assert result.report["final_decision_emission"] == "outside-completion-deadline"
    assert json.loads((result.experiment.root / "wave-report.json").read_bytes()) == result.report


@pytest.mark.parametrize("deadline_entry", ["main-loop", "allocation"])
@pytest.mark.parametrize("infrastructure_first", [False, True])
def test_common_deadline_cancellation_survives_later_cleanup_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, infrastructure_first: bool, deadline_entry: str,
) -> None:
    decide, attempt, cleanup = cw._Controller.decide, trial.run_attempt, trial.cleanup_workspace
    allocate = trial.allocate_workspace
    expired, acknowledged_task = threading.Event(), threading.Event()
    controllers: list[Any] = []
    allocation_lock: list[Any] = []
    witnessed: list[Any] = []

    def policy_clock() -> float:
        return time.monotonic() + (10 if expired.is_set() else 0)

    def acknowledged(controller: Any, role: str, request: Any) -> Any:
        reply = decide(controller, role, request)
        if role == "worker-a" and request["op"] == "ack":
            assert role in controller.received and role not in controller.claimed
            controllers.append(controller)
            if deadline_entry == "main-loop":
                if infrastructure_first:
                    controller.fail("injected-infrastructure-first", unknown=True)
                    assert controller.cancel.is_set() and controller.unknown
                expired.set()  # Policy deadline wins before the runner's real five-second timeout.
            acknowledged_task.set()
        return reply

    def allocated(experiment: Any, aid: str, *args: Any, **kwargs: Any) -> Any:
        workspace = allocate(experiment, aid, *args, **kwargs)
        if deadline_entry == "allocation" and str(experiment.trial_of(aid)["trial_id"]).endswith("worker-b"):
            assert acknowledged_task.wait(3)
            controller = controllers[0]
            controller.lock.acquire()  # Allocation-side expiry must beat the main-loop lock.
            allocation_lock.append(controller.lock)
            if infrastructure_first:
                controller.fail("injected-infrastructure-first", unknown=True)
            expired.set()
        return workspace

    def observed(experiment: Any, aid: str, *args: Any, **kwargs: Any) -> Any:
        assert callable(kwargs["cancel"])  # Exercise the real cancellation callback, unchanged.
        result = attempt(experiment, aid, *args, **kwargs)
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            assert result["reason"] == "operator-cancelled"
            witnessed.append(result)
        return result

    def lost(experiment: Any, aid: str) -> Any:
        if allocation_lock and str(experiment.trial_of(aid)["trial_id"]).endswith("worker-b"):
            allocation_lock.pop().release()  # Participant has already made its cancellation decision.
        result = cleanup(experiment, aid)
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            assert result["status"] == "removed"
            return {"status": "unknown", "errors": ["injected later cleanup loss"]}
        return result

    monkeypatch.setattr(cw._Controller, "decide", acknowledged)
    monkeypatch.setattr(trial, "allocate_workspace", allocated)
    monkeypatch.setattr(trial, "run_attempt", observed)
    monkeypatch.setattr(trial, "cleanup_workspace", lost)
    base = tmp_path / "work"
    base.mkdir()
    plan = cw.WavePlan(actor_digest=trial.sha256_bytes(ACTOR.read_bytes()), mode="hang", deadline=5)
    result = cw.run_wave(plan, ACTOR, tmp_path / "store", base, clock=policy_clock)
    assert expired.is_set() and witnessed
    assert result.report["clock"] == "injected-policy-only"
    assert result.report["status"] == ("UNKNOWN" if infrastructure_first else "FAIL"), result.report
    assert ("deadline" in result.report["failures"]) is not infrastructure_first
    assert "cleanup-unconfirmed" in result.report["unknown"]
