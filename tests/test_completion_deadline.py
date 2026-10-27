"""Shared completion controls use injected policy time, never native latency."""
from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest

from skillc import coordination_wave as cw
from skillc import docker_backend as docker
from skillc import matched_pilot as mp
from skillc import trial


@pytest.mark.parametrize("controller", ["pilot", "calibration"])
def test_existing_public_controller_does_not_launch_after_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, controller: str,
) -> None:
    import test_calibration_run as calibration_helpers
    import test_matched_pilot_run as pilot_helpers

    ticks = [0.0]
    launches: list[str] = []
    original_prepare = docker.DockerBackend.prepare
    original_execute = docker.DockerBackend.execute

    def prepare(self: Any, aid: str) -> object:
        handle = original_prepare(self, aid)
        ticks[0] = 11.0
        return handle

    def execute(self: Any, handle: Any, *args: Any, **kwargs: Any) -> Any:
        launches.append(handle.attempt_id)
        return original_execute(self, handle, *args, **kwargs)

    monkeypatch.setattr(docker.DockerBackend, "prepare", prepare)
    monkeypatch.setattr(docker.DockerBackend, "execute", execute)
    if controller == "pilot":
        original_pilot = mp.run_pilot

        def pilot(*args: Any, **kwargs: Any) -> Any:
            kwargs["clock"] = lambda: ticks[0]
            return original_pilot(*args, **kwargs)

        monkeypatch.setattr(mp, "run_pilot", pilot)
        experiment, outcomes, _ = pilot_helpers._run_fake_pilot(tmp_path, total_seconds=10)
    else:
        # _run's existing clock advances in its real backend factory.
        experiment, outcomes, _, _ = calibration_helpers._run(
            tmp_path, monkeypatch, total_seconds=10, tick=11,
        )
    assert len(outcomes) == len(list(experiment.attempts()))
    assert launches == [], f"actual execute after setup exhausted the original allowance: {launches}"


@pytest.mark.parametrize("controller", ["pilot", "calibration"])
def test_existing_pilot_does_not_credit_late_result_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, controller: str,
) -> None:
    import test_calibration_run as calibration_helpers
    import test_matched_pilot_run as helpers

    from skillc import calibration, calibration_run

    ticks = [0.0]
    original_pilot = mp.run_pilot if controller == "pilot" else calibration_run.run_calibration
    original_add = trial.add_result

    def pilot(*args: Any, **kwargs: Any) -> Any:
        kwargs["clock"] = lambda: ticks[0]
        return original_pilot(*args, **kwargs)

    def add(*args: Any, **kwargs: Any) -> Any:
        value = original_add(*args, **kwargs)
        ticks[0] = 101.0
        return value

    monkeypatch.setattr(mp if controller == "pilot" else calibration_run,
                        "run_pilot" if controller == "pilot" else "run_calibration", pilot)
    monkeypatch.setattr(trial, "add_result", add)
    if controller == "pilot":
        experiment, outcomes, _ = helpers._run_fake_pilot(tmp_path, total_seconds=100)
    else:
        experiment, outcomes, _, _ = calibration_helpers._run(tmp_path, monkeypatch, total_seconds=100)
    first = outcomes[0].record
    assert isinstance(first["graded"], dict) and first["graded"]["status"] == "PASS"
    stored = list(experiment.root.glob("result-*.json"))
    assert stored, "real task result storage was not reached"
    assert mp.graded_status(first) != "PASS", "raw task PASS was credited after actual storage expired"
    if controller == "calibration":
        assert calibration.primary_endpoint(first)["status"] == "UNKNOWN"


def test_existing_wave_does_not_launch_after_spool_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_coordination_wave import ACTOR, assert_resources_absent

    ticks = [0.0]
    launches: list[object] = []
    original_popen = trial.subprocess.Popen

    def open_spool(file: Any, *args: Any, **kwargs: Any) -> Any:
        result = builtins.open(file, *args, **kwargs)  # noqa: SIM115 - returned to the real caller's context manager
        if str(file).endswith(".stderr"):
            ticks[0] = 11.0
        return result

    def popen(*args: Any, **kwargs: Any) -> Any:
        launches.append(args[0])
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(trial, "open", open_spool, raising=False)
    monkeypatch.setattr(trial.subprocess, "Popen", popen)
    work = tmp_path / "work"
    work.mkdir()
    result = cw.run_wave(cw.WavePlan(actor_digest=trial.sha256_bytes(ACTOR.read_bytes())),
                         ACTOR, tmp_path / "store", work, clock=lambda: ticks[0])
    assert_resources_absent(result)
    assert launches == [], f"actual Popen after spool consumed the original allowance: {launches}"


@pytest.mark.parametrize("bad", [True, False, 0, -1, float("inf"), float("nan"), "1"])
def test_invalid_allowance_never_authorizes_a_deadline(bad: Any) -> None:
    from skillc.completion import CompletionDeadline, CompletionUnavailable
    with pytest.raises(CompletionUnavailable):
        CompletionDeadline.after(bad)


@pytest.mark.parametrize("bad", [True, float("inf"), float("nan"), -1, "1"])
def test_bad_clock_poison_is_shared_with_children(bad: Any) -> None:
    from skillc.completion import CompletionDeadline, CompletionUnavailable
    ticks = [0.0]
    parent = CompletionDeadline.after(10, lambda: ticks[0])
    child = parent.child(5)
    ticks[0] = bad
    with pytest.raises(CompletionUnavailable):
        child.remaining(10)
    ticks[0] = 1.0
    with pytest.raises(CompletionUnavailable):
        parent.remaining(10)
    assert parent.qualify(parent.marker("a"), True)["on_time"] is False


def test_children_only_shorten_same_clock_and_equal_ticks_are_valid() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from skillc.completion import CompletionDeadline
    ticks = [0.0]
    parent = CompletionDeadline.after(10, lambda: ticks[0])
    child = parent.child(4)
    assert child.remaining(9) == 4
    ticks[0] = 3.0
    assert child.remaining(9) == 1 and parent.remaining(9) == 7
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: child.remaining(9), range(12))) == [1] * 12


@pytest.mark.parametrize("delayed", ["scratch-cleanup", "excluded-publication"])
def test_task_fact_and_completion_publication_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delayed: str,
) -> None:
    import test_matched_pilot_run as helpers

    from skillc import agent_trial, verify
    ticks = [0.0]
    original_pilot = mp.run_pilot
    original = verify.remove_owned if delayed == "scratch-cleanup" else agent_trial.write_observation_record

    def pilot(*args: Any, **kwargs: Any) -> Any:
        kwargs["clock"] = lambda: ticks[0]
        return original_pilot(*args, **kwargs)

    def delay(*args: Any, **kwargs: Any) -> Any:
        value = original(*args, **kwargs)
        ticks[0] = 101.0
        return value

    monkeypatch.setattr(mp, "run_pilot", pilot)
    if delayed == "scratch-cleanup":
        monkeypatch.setattr(verify, "remove_owned", delay)
    else:
        monkeypatch.setattr(agent_trial, "write_observation_record", delay)
    experiment, outcomes, _ = helpers._run_fake_pilot(tmp_path, total_seconds=100)
    first = outcomes[0].record
    grade = first["graded"]
    assert isinstance(grade, dict) and grade["status"] == "PASS"
    assert mp.graded_status(first) == ("PASS" if delayed == "excluded-publication" else "UNKNOWN")
    qualification = first["completion"]
    assert isinstance(qualification, dict)
    assert qualification["on_time"] is (delayed == "excluded-publication")
    assert list(experiment.root.glob("result-*.json"))


def test_bound_collector_is_same_before_failed_probe_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import test_matched_pilot_run as helpers

    from skillc import agent_trial, collection_conformance
    from skillc.backend import BackendUnavailable
    ticks = [0.0]
    original_pilot, original_agent = mp.run_pilot, agent_trial.run_one_attempt
    original_wrapper = collection_conformance.run_level1_agent_attempt
    original_prepare = docker.DockerBackend.prepare
    holders: list[trial.OwnedAttemptIds] = []
    witnessed: list[str] = []
    supplied: list[tuple[object, object]] = []

    def pilot(*args: Any, **kwargs: Any) -> Any:
        kwargs["clock"] = lambda: ticks[0]
        return original_pilot(*args, **kwargs)

    def wrapper(**kwargs: Any) -> Any:
        supplied.append((kwargs["completion_deadline"], kwargs["recorded_attempt_ids"]))
        return original_wrapper(**kwargs)

    def agent(**kwargs: Any) -> Any:
        ids = kwargs["recorded_attempt_ids"]
        assert kwargs["completion_deadline"] is supplied[-1][0]
        assert ids is supplied[-1][1]
        assert isinstance(ids, trial.OwnedAttemptIds)
        holders.append(ids)
        record = original_agent(**kwargs)
        ticks[0] = 101.0
        return record

    def prepare(self: Any, aid: str) -> Any:
        if aid.startswith("probe-"):
            ids = holders[-1]
            assert ids == [aid]
            assert any(e.get("owned_id") == aid for e in ids.experiment.events(ids.parent_attempt))
            witnessed.append(aid)
            raise BackendUnavailable("controlled prepare failed without a handle")
        return original_prepare(self, aid)

    monkeypatch.setattr(mp, "run_pilot", pilot)
    monkeypatch.setattr(collection_conformance, "run_level1_agent_attempt", wrapper)
    monkeypatch.setattr(agent_trial, "run_one_attempt", agent)
    monkeypatch.setattr(docker.DockerBackend, "prepare", prepare)
    _, outcomes, _ = helpers._run_fake_pilot(tmp_path, total_seconds=100)
    assert witnessed and holders[0] == witnessed
    assert holders[0].all_absent() is False
    qualification = outcomes[0].record["completion"]
    assert isinstance(qualification, dict) and qualification["cleanup_confirmed"] is False
    assert mp.graded_status(outcomes[0].record) != "PASS"


@pytest.mark.parametrize("tamper", ["clean", "suffix", "prefix", "other-store"])
def test_ownership_journal_appends_do_not_hide_store_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str,
) -> None:
    import test_matched_pilot_run as helpers
    original_pilot, original_execute = mp.run_pilot, docker.DockerBackend.execute
    ticks = [0.0]
    own: list[trial.OwnedAttemptIds] = []
    original_ids = trial.OwnedAttemptIds

    # Observe existing constructors without replacing the type used by isinstance.
    original_append = original_ids.append

    def append(self: Any, aid: str) -> None:
        own.append(self)
        original_append(self, aid)

    def pilot(*args: Any, **kwargs: Any) -> Any:
        kwargs["clock"] = lambda: ticks[0]
        return original_pilot(*args, **kwargs)

    def execute(self: Any, handle: Any, *args: Any, **kwargs: Any) -> Any:
        value = original_execute(self, handle, *args, **kwargs)
        if handle.attempt_id.startswith("probe-") and tamper != "clean":
            path = own[-1].experiment.journal(own[-1].parent_attempt)
            if tamper == "suffix":
                with path.open("ab") as stream:
                    stream.write(b'{"event":"owned-attempt","owned_id":"forged"}\n')
            elif tamper == "prefix":
                original = path.read_bytes()
                altered = original.replace(b'"event": "planned"', b'"event": "forged"', 1)
                assert altered != original
                path.write_bytes(altered)
            else:
                (own[-1].experiment.root / "unauthorized-object").write_text("forged")
        return value

    monkeypatch.setattr(mp, "run_pilot", pilot)
    monkeypatch.setattr(original_ids, "append", append)
    monkeypatch.setattr(docker.DockerBackend, "execute", execute)
    # Stop subsequent attempts after the first observation, keeping one actual probe.
    from skillc import agent_trial
    original_observe = agent_trial.write_observation_record

    def observe(*args: Any, **kwargs: Any) -> Any:
        result = original_observe(*args, **kwargs)
        ticks[0] = 101.0
        return result

    monkeypatch.setattr(agent_trial, "write_observation_record", observe)
    _, outcomes, _ = helpers._run_fake_pilot(tmp_path, total_seconds=100)
    first = outcomes[0]
    assert own and len(own[0]) == 1
    if tamper != "clean":
        assert ("journal changed outside" if tamper != "other-store" else "evidence store changed") in str(first.runner_note)
        assert mp.graded_status(first.record) != "PASS"
    else:
        assert "runner error" not in str(first.runner_note) and mp.graded_status(first.record) == "PASS"


@pytest.mark.parametrize("phase", ["backend-install", "host-stage", "judge-stage", "healthy"])
def test_probe_and_judge_resample_after_actual_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str,
) -> None:
    from test_verify_backend import GRADER, REFERENCE, FakeProbeBackend

    from skillc import verify
    from skillc.completion import CompletionDeadline
    ticks = [0.0]
    deadline = CompletionDeadline.after(10, lambda: ticks[0])
    calls: list[str] = []
    original_write, original_popen = verify._write_tree, verify.subprocess.Popen
    backend = FakeProbeBackend(tmp_path / "backend") if phase == "backend-install" else None
    original_install = FakeProbeBackend.install

    def install(self: Any, *args: Any, **kwargs: Any) -> Any:
        value = original_install(self, *args, **kwargs)
        ticks[0] = 11.0
        return value

    def write(root: Path, *args: Any, **kwargs: Any) -> Any:
        value = original_write(root, *args, **kwargs)
        if (phase == "host-stage" and root.name == "harness") or (phase == "judge-stage" and root.name == "judge"):
            ticks[0] = 11.0
        return value

    def popen(argv: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append("judge" if "--judge" in argv else "probe")
        return original_popen(argv, *args, **kwargs)

    monkeypatch.setattr(FakeProbeBackend, "install", install)
    monkeypatch.setattr(verify, "_write_tree", write)
    monkeypatch.setattr(verify.subprocess, "Popen", popen)
    graded = verify.grade_files(GRADER, [("src/slugify.py", REFERENCE.read_bytes(), False)],
                                tmp_path / "grading", backend=backend, completion_deadline=deadline)
    assert graded.containment["cleanup"] == "removed"
    if phase == "healthy":
        assert graded.status == "PASS" and calls == ["probe", "judge"]
    else:
        assert graded.status == "INCONCLUSIVE"
        assert all(c["outcome"] == "UNKNOWN" for c in graded.criteria)
        assert calls == (["probe"] if phase == "judge-stage" else [])
    if backend is not None:
        assert backend.prepared and all(h.destroyed for h in backend.prepared)


@pytest.mark.parametrize("advance", [3.0, 11.0, float("nan")])
def test_actual_turn_primitive_shares_endpoint_and_always_ends(
    tmp_path: Path, advance: float,
) -> None:
    from test_agent_trial import _planned
    from test_lifecycle import FakeBackend

    from skillc import lifecycle
    from skillc.backend import ExecuteResult
    from skillc.completion import CompletionDeadline

    ticks = [0.0]
    deadline = CompletionDeadline.after(10, lambda: ticks[0])
    experiment, aid = _planned(trial.open_store(tmp_path / "store", []))
    caps: list[float] = []
    ended: list[bool] = []

    class Turns(FakeBackend):
        def execute_turn(self, handle: Any, argv: Any, limits: Any, cancel: Any = None) -> Any:
            assert limits.completion_deadline is deadline
            caps.append(limits.timeout)
            return ExecuteResult("exited", 0)

        def end_attempt(self, handle: Any) -> None:
            ended.append(True)

    def next_turn(*args: Any) -> Any:
        if len(caps) == 1:
            ticks[0] = advance
            return ["next"]
        return None

    result = lifecycle._run_turns(Turns(tmp_path / "backend"), object(), experiment, aid, ["first"],
                                  lifecycle.Limits(timeout=20), None, next_turn, completion_deadline=deadline)
    assert ended == [True]
    assert caps == ([10, 7] if advance == 3 else [10])
    assert result.reason == ("exited" if advance == 3 else "timeout")


@pytest.mark.parametrize("poison", [False, True])
def test_wave_inherits_clock_domain_and_preserves_cleanup_on_invalid_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, poison: bool,
) -> None:
    from test_coordination_wave import ACTOR, assert_resources_absent

    from skillc.completion import CompletionDeadline, CompletionUnavailable
    ticks = [0.0]
    inherited = CompletionDeadline.after(5, lambda: ticks[0])
    work = tmp_path / "work"
    work.mkdir()
    if poison:
        def open_spool(file: Any, *args: Any, **kwargs: Any) -> Any:
            opened = builtins.open(file, *args, **kwargs)  # noqa: SIM115 - real caller owns context
            if str(file).endswith(".stderr"):
                ticks[0] = float("nan")
            return opened
        monkeypatch.setattr(trial, "open", open_spool, raising=False)
        with pytest.raises(CompletionUnavailable):
            cw.run_wave(cw.WavePlan(actor_digest=trial.sha256_bytes(ACTOR.read_bytes())), ACTOR,
                        tmp_path / "store", work, completion_deadline=inherited)
        [root] = (tmp_path / "store").glob("scripted-wave-*")
        experiment = trial.Experiment.open(root)
        for _, attempt in experiment.attempts():
            for event in experiment.events(str(attempt["attempt_id"])):
                if event["event"] == "workspace":
                    assert not Path(str(event["path"])).exists()
                assert event["event"] != "started"
    else:
        # This deliberately incompatible extra clock must never be consulted.
        result = cw.run_wave(cw.WavePlan(actor_digest=trial.sha256_bytes(ACTOR.read_bytes())), ACTOR,
                             tmp_path / "store", work, clock=lambda: -999, completion_deadline=inherited)
        assert_resources_absent(result)
        assert result.report["status"] == "PASS" and result.report["deadline"] == 5
        assert result.report["declared_deadline"] == 10 and result.report["clock"] == "injected-policy-only"


@pytest.mark.parametrize("field,value", [
    ("elapsed", float("nan")), ("elapsed", True), ("elapsed", 11),
    ("on_time", False), ("cleanup_confirmed", False), ("publication_confirmed", False), ("marker", {}),
])
def test_completion_evidence_requires_valid_finite_matching_healthy_data(field: str, value: Any) -> None:
    from skillc.completion import CompletionDeadline, combine, normalize
    deadline = CompletionDeadline.after(10, lambda: 0.0)
    marker = deadline.marker("attempt")
    final = {**deadline.qualify(marker, True), "publication_confirmed": True}
    record = {"attempt_id": "attempt", "completion_required": True,
              "completion_marker": marker, "completion": final}
    assert combine("PASS", record) == "PASS"
    assert combine("PASS", {**record, "completion": {**final, field: value}}) == "UNKNOWN"
    assert combine("FAIL", {**record, "completion": None}) == "FAIL"
    assert combine("PASS", normalize(record, [])) == "UNKNOWN"  # Copied private data has no durable marker.


@pytest.mark.parametrize("clock_value", [[], {}])
def test_malformed_marker_clock_is_unknown(clock_value: Any) -> None:
    from skillc.completion import CompletionDeadline, combine
    deadline = CompletionDeadline.after(10, lambda: 0.0)
    marker = deadline.marker("attempt")
    record = {"attempt_id": "attempt", "completion_required": True,
              "completion_marker": marker, "completion": {**deadline.qualify(marker, True), "publication_confirmed": True}}
    assert combine("PASS", record) == "PASS"
    marker["clock"] = clock_value
    record["completion"] = {**deadline.qualify(marker, True), "publication_confirmed": True}
    assert combine("PASS", record) == "UNKNOWN"
    assert combine("FAIL", record) == "FAIL"


@pytest.mark.parametrize("cancelled", [True, False])
def test_host_shared_expiry_preserves_already_requested_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancelled: bool,
) -> None:
    import sys

    from test_agent_trial import _planned

    from skillc.completion import CompletionDeadline

    experiment, aid = _planned(trial.open_store(tmp_path / "store", []))
    workspace_base = tmp_path / "work"
    workspace_base.mkdir()
    workspace = trial.allocate_workspace(experiment, aid, workspace_base, [])
    ticks = [0.0]
    endpoint = CompletionDeadline.after(5, lambda: ticks[0])
    original = trial.Experiment.record

    def record(self: trial.Experiment, attempt: str, event: str, **detail: Any) -> None:
        original(self, attempt, event, **detail)
        if event == "started":
            ticks[0] = 6.0

    monkeypatch.setattr(trial.Experiment, "record", record)
    result = trial.run_attempt(experiment, aid, [sys.executable, "-c", "import time; time.sleep(30)"],
                               workspace, 5, cancel=lambda: cancelled, completion_deadline=endpoint)
    assert result["confirmed"] is True
    assert result["reason"] == ("operator-cancelled" if cancelled else "timeout")
    assert trial.cleanup_workspace(experiment, aid)["status"] == "removed"


@pytest.mark.parametrize("infrastructure_first", [True, False])
def test_wave_first_cause_survives_shared_expiry_and_cleanup_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, infrastructure_first: bool,
) -> None:
    import os
    import threading
    import time

    from test_coordination_wave import ACTOR

    expired = threading.Event()
    original_decide = cw._Controller.decide
    original_attempt = trial.run_attempt
    original_cleanup = trial.cleanup_workspace
    stops: list[str] = []

    def decide(controller: Any, role: str, request: Any) -> Any:
        reply = original_decide(controller, role, request)
        if role == "worker-a" and request["op"] == "ack":
            if infrastructure_first:
                controller.fail("controlled-infrastructure-first", unknown=True)
            expired.set()
        return reply

    def attempt(experiment: Any, aid: str, *args: Any, **kwargs: Any) -> Any:
        result = original_attempt(experiment, aid, *args, **kwargs)
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            stops.append(str(result["reason"]))
        return result

    def cleanup(experiment: Any, aid: str) -> Any:
        result = original_cleanup(experiment, aid)
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            assert result["status"] == "removed"
            return {"status": "unknown", "errors": ["controlled later cleanup loss"]}
        return result

    monkeypatch.setattr(cw._Controller, "decide", decide)
    monkeypatch.setattr(trial, "run_attempt", attempt)
    monkeypatch.setattr(trial, "cleanup_workspace", cleanup)
    work = tmp_path / "work"
    work.mkdir()
    result = cw.run_wave(cw.WavePlan(actor_digest=trial.sha256_bytes(ACTOR.read_bytes()),
                                     mode="hang", deadline=5), ACTOR, tmp_path / "store", work,
                         clock=lambda: time.monotonic() + (10 if expired.is_set() else 0))
    assert stops == ["operator-cancelled"]
    assert ("deadline" in result.report["failures"]) is not infrastructure_first
    assert result.report["status"] == ("UNKNOWN" if infrastructure_first else "FAIL")
    assert "cleanup-unconfirmed" in result.report["unknown"]
    for _, attempt_record in result.experiment.attempts():
        aid = str(attempt_record["attempt_id"])
        assert (result.experiment.root / f"lifecycle-{aid}.json").is_file()
        for event in result.experiment.events(aid):
            if event["event"] == "started":
                with pytest.raises(ProcessLookupError):
                    os.killpg(int(str(event["pid"])), 0)
            if event["event"] == "workspace":
                assert not Path(str(event["path"])).exists()


@pytest.mark.parametrize("fault", ["healthy", "scratch", "observation", "qualification-fail"])
def test_completion_requires_cleanup_and_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import test_matched_pilot_run as helpers

    from skillc import agent_trial, verify

    ticks = [0.0]
    run, observe, remove, record = (
        mp.run_pilot,
        agent_trial.write_observation_record,
        verify.remove_owned,
        trial.Experiment.record,
    )

    def pilot(*args: Any, **kwargs: Any) -> Any:
        kwargs["clock"] = lambda: ticks[0]
        return run(*args, **kwargs)

    def publication(*args: Any, **kwargs: Any) -> str:
        ticks[0] = 101.0
        return "write-failed" if fault == "observation" else observe(*args, **kwargs)

    def cleanup(*args: Any, **kwargs: Any) -> Any:
        value = remove(*args, **kwargs)
        return {**value, "status": "partial"} if fault == "scratch" else value

    def journal(self: Any, aid: str, event: str, **detail: Any) -> None:
        if event == "completion-qualified" and fault == "qualification-fail":
            ticks[0] = 101.0
            raise OSError("controlled qualification publication failure")
        record(self, aid, event, **detail)

    monkeypatch.setattr(mp, "run_pilot", pilot)
    monkeypatch.setattr(agent_trial, "write_observation_record", publication)
    monkeypatch.setattr(verify, "remove_owned", cleanup)
    monkeypatch.setattr(trial.Experiment, "record", journal)
    experiment, outcomes, run_dir = helpers._run_fake_pilot(
        tmp_path,
        total_seconds=100,
        solve_arms=() if fault == "qualification-fail" else (mp.TREATMENT,),
    )
    first = outcomes[0].record
    expected = (
        "FAIL" if fault == "qualification-fail" else "PASS" if fault == "healthy" else "UNKNOWN"
    )
    if fault == "qualification-fail":
        import json

        stored = [json.loads(f.read_text()) for f in experiment.root.glob("result-*.json")]
        assert any(r["attempt_id"] == outcomes[0].scheduled.attempt_id and r["status"] == "FAIL" for r in stored)
    assert mp.graded_status(first) == expected
    recovered = mp.reconcile(experiment, outcomes)[0].record
    assert mp.graded_status(recovered) == expected
    _, disk = mp.read_outcomes(run_dir)
    assert mp.graded_status(disk[0].record) == expected
    assert len(outcomes) == len(list(experiment.attempts()))
    if fault != "qualification-fail":
        grade = first["graded"]
        assert isinstance(grade, dict) and grade["status"] == "PASS"


@pytest.mark.parametrize("fault", ["journal", "local"])
def test_turn_dispatch_resamples_and_consumes_local_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from types import SimpleNamespace

    from test_agent_trial import _planned
    from test_lifecycle import FakeBackend

    from skillc import completion, lifecycle
    from skillc.backend import ExecuteResult, Limits

    ticks = [0.0]
    experiment, aid = _planned(trial.open_store(tmp_path / "store", []))
    caps: list[float] = []
    ended: list[bool] = []

    class Turns(FakeBackend):
        def execute_turn(self, handle: Any, argv: Any, limits: Any, cancel: Any = None) -> Any:
            caps.append(limits.timeout)
            if fault == "local":
                ticks[0] = 4.0
            return ExecuteResult("exited", 0)

        def end_attempt(self, handle: Any) -> None:
            ended.append(True)

    def next_turn(*args: Any) -> Any:
        if len(caps) == 1:
            if fault == "journal":
                ticks[0] = 9.0
            return ["second"]
        return None

    original_record = trial.Experiment.record

    def record(self: Any, attempt: str, event: str, **detail: Any) -> None:
        original_record(self, attempt, event, **detail)
        if fault == "journal" and event == "controller-turn" and detail.get("dispatched"):
            ticks[0] = 11.0

    monkeypatch.setattr(trial.Experiment, "record", record)
    monkeypatch.setattr(lifecycle, "time", SimpleNamespace(monotonic=lambda: ticks[0]))
    endpoint = completion.CompletionDeadline.after(
        10 if fault == "journal" else 60, lambda: ticks[0]
    )
    result = lifecycle._run_turns(
        Turns(tmp_path / "backend"),
        object(),
        experiment,
        aid,
        ["first"],
        Limits(timeout=20 if fault == "journal" else 5),
        None,
        next_turn,
        completion_deadline=endpoint,
    )
    assert ended == [True]
    assert caps == ([10] if fault == "journal" else [5, 1])
    if fault == "journal":
        assert result.reason == "timeout"


@pytest.mark.parametrize("spent", [True, False])
def test_shared_endpoint_keeps_host_local_wall_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spent: bool,
) -> None:
    from types import SimpleNamespace

    from test_agent_trial import _planned

    from skillc import completion

    experiment, aid = _planned(trial.open_store(tmp_path / "store", []))
    ticks = [0.0]

    class Process:
        pid, returncode, polls = 123456, 0, 0

        def poll(self) -> int | None:
            self.polls += 1
            return None if self.polls <= 2 else 0

        def wait(self, timeout: float) -> int:
            return 0

    stopped: list[bool] = []
    original = trial.Experiment.record

    def record(self: Any, attempt: str, event: str, **detail: Any) -> None:
        original(self, attempt, event, **detail)
        if spent and event == "started":
            ticks[0] = 2.0

    monkeypatch.setattr(trial.Experiment, "record", record)
    monkeypatch.setattr(
        trial, "time", SimpleNamespace(monotonic=lambda: ticks[0], sleep=lambda _: None)
    )
    monkeypatch.setattr(trial.subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(trial, "_group_alive", lambda _: False)

    def stop(*args: Any) -> bool:
        stopped.append(True)
        return True

    monkeypatch.setattr(trial, "_stop_group", stop)
    # Finite process-state control, independent wall clock and constant policy time.
    endpoint = completion.CompletionDeadline.after(10, lambda: 0.0)
    result = trial.run_attempt(
        experiment, aid, ["controlled"], tmp_path, 1, completion_deadline=endpoint
    )
    assert result["confirmed"] is True
    assert result["reason"] == ("timeout" if spent else "exited")
    assert stopped == ([True] if spent else [])


@pytest.mark.parametrize(
    "fault",
    [
        "healthy",
        "docker-prelaunch",
        "docker-inspection",
        "docker-probe",
        "docker-poison",
        "docker-remaining",
        "docker-environment",
        "partial-qualification",
        "short-write",
        "replace-fail",
    ],
)
def test_remaining_dispatch_and_publication_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import dataclasses
    import json

    import test_matched_pilot_run as helpers

    from skillc import agent_trial, completion

    ticks = [0.0]
    late: list[Any] = []
    samples: list[float] = []
    launches: list[float] = []
    replacements: list[bool] = []
    prefixes: list[tuple[Path, bytes]] = []
    failed_publication = fault in ("partial-qualification", "short-write", "replace-fail")
    real_remaining, real_replace = completion.CompletionDeadline.remaining, trial.os.replace

    def remaining(self: Any, cap: float) -> float:
        value = real_remaining(self, cap)
        samples.append(value)
        return value

    def replace(src: Any, dst: Any) -> None:
        if fault == "replace-fail" and Path(dst).parent.name == "journal":
            replacements.append(True)
            raise OSError("controlled atomic replacement failure")
        real_replace(src, dst)

    run, observe, original_record = mp.run_pilot, agent_trial.write_observation_record, trial.Experiment.record
    original_agent = agent_trial.run_one_attempt

    def record(self: Any, aid: str, event: str, **detail: Any) -> None:
        if event == "completion-qualified":
            prefixes.append((self.journal(aid), self.journal(aid).read_bytes()))
        original_record(self, aid, event, **detail)

    def environment() -> dict[str, str]:
        ticks[0] = 101.0
        return {}

    def agent(**kwargs: Any) -> Any:
        if fault == "docker-environment":
            kwargs["backend"] = dataclasses.replace(kwargs["backend"], agent_exec_env=environment)
        return original_agent(**kwargs)
    forwarding, popen, fdopen = (
        docker.DockerBackend._forwarding_available,
        docker.subprocess.Popen,
        trial.os.fdopen,
    )
    original_inspect = docker.DockerBackend._inspect

    def inspect(*args: Any) -> Any:
        value = original_inspect(*args)
        if fault == "docker-inspection":
            for path in tmp_path.rglob(f"{args[1].attempt_id}.jsonl"):
                if any(json.loads(line).get("event") == "dispatched" for line in path.read_text().splitlines()):
                    ticks[0] = 101.0
        return value

    def pilot(*args: Any, **kwargs: Any) -> Any:
        kwargs["clock"] = lambda: ticks[0]
        return run(*args, **kwargs)

    def publish(*args: Any, **kwargs: Any) -> str:
        ticks[0] = 101.0
        return observe(*args, **kwargs)

    def forward(*args: Any, **kwargs: Any) -> Any:
        value = forwarding(*args, **kwargs)
        if fault == "docker-probe" and str(args[1].attempt_id).startswith("probe-") or fault == "docker-prelaunch":
            ticks[0] = 101.0
        elif fault == "docker-poison":
            ticks[0] = float("nan")
        elif fault == "docker-remaining":
            ticks[0] = 3.0
        return value

    def launch(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if any(str(x).startswith(docker._EXEC_TOKEN_PREFIX) for x in argv):
            launches.append(samples[-1])
            if ticks[0] == 101 or fault == "docker-poison":
                late.append(list(argv))
        return popen(argv, *args, **kwargs)

    class PartialWrite:
        def __init__(self, handle: Any):
            self.handle = handle

        def __enter__(self) -> Any:
            self.handle.__enter__()
            return self

        def __exit__(self, *args: object) -> Any:
            return self.handle.__exit__(*args)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.handle, name)

        def write(self, data: Any) -> Any:
            needle = (
                b'"event": "completion-qualified"'
                if isinstance(data, bytes)
                else '"event": "completion-qualified"'
            )
            if fault in ("partial-qualification", "short-write") and needle in data:
                stored = [json.loads(f.read_text()) for f in tmp_path.rglob("result-*.json")]
                assert any(r["status"] == "FAIL" for r in stored)
                self.handle.write(data[: len(data) // 2])
                self.handle.flush()
                if fault == "short-write":
                    return len(data) // 2
                raise OSError("controlled partial qualification write")
            return self.handle.write(data)

    monkeypatch.setattr(completion.CompletionDeadline, "remaining", remaining)
    monkeypatch.setattr(trial.os, "replace", replace)
    monkeypatch.setattr(mp, "run_pilot", pilot)
    monkeypatch.setattr(trial.Experiment, "record", record)
    monkeypatch.setattr(agent_trial, "run_one_attempt", agent)
    monkeypatch.setattr(agent_trial, "write_observation_record", publish)
    monkeypatch.setattr(docker.DockerBackend, "_forwarding_available", forward)
    monkeypatch.setattr(docker.DockerBackend, "_inspect", inspect)
    monkeypatch.setattr(docker.subprocess, "Popen", launch)
    monkeypatch.setattr(trial.os, "fdopen", lambda *a, **kw: PartialWrite(fdopen(*a, **kw)))
    try:
        experiment, outcomes, run_dir = helpers._run_fake_pilot(
            tmp_path, total_seconds=100, solve_arms=() if failed_publication else (mp.TREATMENT,)
        )
    except Exception:
        if failed_publication:
            stored = [json.loads(f.read_text()) for f in tmp_path.rglob("result-*.json")]
            assert any(r["status"] == "FAIL" for r in stored)
        raise
    assert late == []
    if fault == "replace-fail":
        assert replacements
    if fault == "docker-remaining":
        assert launches[0] == 97
    if failed_publication:
        assert mp.graded_status(outcomes[0].record) == "FAIL"
        _, disk = mp.read_outcomes(run_dir)
        assert mp.graded_status(disk[0].record) == "FAIL"
        assert prefixes and all(path.read_bytes() == data for path, data in prefixes)
        assert not list((experiment.root / trial.JOURNAL).glob(".*.tmp"))
    assert outcomes[0].record["backend_teardown"] == "confirmed"
    if fault in ("docker-prelaunch", "docker-inspection", "docker-poison", "docker-environment"):
        assert outcomes[0].record["disposition"] == "unavailable"
        assert "started" not in [e["event"] for e in experiment.events(outcomes[0].scheduled.attempt_id)]
    assert len(outcomes) == len(list(experiment.attempts()))


def test_qualification_publication_serializes_same_journal_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from test_agent_trial import _planned

    experiment, aid = _planned(trial.open_store(tmp_path / "store", []))
    journal = experiment.journal(aid)
    prefix = journal.read_bytes()
    entered, waiting, release = threading.Event(), threading.Event(), threading.Event()
    replace, flock = trial._replace, trial.fcntl.flock

    def blocked_replace(path: Path, data: bytes, **kwargs: Any) -> None:
        if path == journal:
            entered.set()
            assert release.wait(10)
        replace(path, data, **kwargs)

    def observed_flock(fd: int, operation: int) -> Any:
        if (
            threading.current_thread().name == "journal-appender"
            and operation == trial.fcntl.LOCK_EX
        ):
            waiting.set()
        return flock(fd, operation)

    def append() -> None:
        threading.current_thread().name = "journal-appender"
        experiment.record(aid, "launch-suppressed", reason="legitimate concurrent append")

    monkeypatch.setattr(trial, "_replace", blocked_replace)
    monkeypatch.setattr(trial.fcntl, "flock", observed_flock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        final = pool.submit(experiment.record, aid, "completion-qualified", qualification={})
        try:
            assert entered.wait(10)
            writer = pool.submit(append)
            assert waiting.wait(10)
        finally:
            release.set()
        final.result(timeout=10)
        writer.result(timeout=10)
    assert journal.read_bytes().startswith(prefix)
    assert [e["event"] for e in experiment.events(aid)][-2:] == [
        "completion-qualified",
        "launch-suppressed",
    ]


@pytest.mark.parametrize("mode", ["healthy", "local", "shared", "legacy"])
def test_actual_turn_preparation_keeps_local_endpoint_and_started_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    import json
    import time
    from types import SimpleNamespace

    from test_agent_trial import _backend, _planned

    from skillc import completion, lifecycle
    from skillc.backend import Limits

    wall, policy = [0.0], [0.0]
    clock = SimpleNamespace(
        monotonic=lambda: wall[0], sleep=time.sleep, time=time.time, time_ns=time.time_ns
    )
    experiment, aid = _planned(trial.open_store(tmp_path / "store", []))
    base = tmp_path / "work"
    base.mkdir()
    backend = _backend(base, tmp_path / "fake-state")
    endpoint = completion.CompletionDeadline.after(60, lambda: policy[0])
    forward, popen = docker.DockerBackend._forwarding_available, docker.subprocess.Popen
    forwarded, launches = [], []

    def forwarding(*args: Any, **kwargs: Any) -> Any:
        value = forward(*args, **kwargs)
        forwarded.append(True)
        if len(forwarded) == 2:
            if mode == "local":
                wall[0] = 6
            if mode == "shared":
                policy[0] = 61
        return value

    def launch(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if any(str(a).startswith(docker._EXEC_TOKEN_PREFIX) for a in argv):
            launches.append(True)
        return popen(argv, *args, **kwargs)

    argv = [
        "sh",
        "-c",
        "printf touched:control > .skillc-canary-result; printf done > delivered.txt",
    ]

    def next_turn(_backend: Any, _handle: Any, done: int, _result: Any) -> Any:
        wall[0] = 4
        return argv if done == 1 else None

    monkeypatch.setattr(docker.DockerBackend, "_forwarding_available", forwarding)
    monkeypatch.setattr(docker.subprocess, "Popen", launch)
    monkeypatch.setattr(docker, "time", clock)
    monkeypatch.setattr(lifecycle, "time", clock)
    record = lifecycle.run_through_backend(
        backend,
        experiment,
        aid,
        argv,
        {"seed.txt": b"initial"},
        Limits(timeout=5),
        base,
        next_turn=next_turn,
        completion_deadline=None if mode == "legacy" else endpoint,
        nonce="control",
    )
    assert record["backend_teardown"] == "confirmed"
    assert len(launches) == (2 if mode in ("healthy", "legacy") else 1)
    assert "started" in [e["event"] for e in experiment.events(aid)]
    assert record["disposition"] == "captured"
    assert json.loads((experiment.root / f"lifecycle-{aid}.json").read_text())["disposition"] == "captured"
    manifest = json.loads((experiment.root / f"manifest-{aid}.json").read_text())
    assert any(a["path"] == "delivered.txt" for a in manifest["artifacts"])


def test_finalized_sibling_confirmation_does_not_refuse_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager

    from test_verify import GRADER, REFERENCE, _freeze, _plan_two, _run

    from skillc import verify

    store = trial.open_store(tmp_path / "store", [])
    base = tmp_path / "work"
    base.mkdir()
    experiment, first, second = _plan_two(store)
    _freeze(experiment, first, _run(experiment, first, base, REFERENCE))
    _freeze(experiment, second, _run(experiment, second, base, REFERENCE))
    owned = trial.OwnedAttemptIds(experiment, second)
    owned.append("discovery-owned")
    progress = threading.Event()
    grade, record, lock = verify.grade_files, trial.Experiment.record, trial.experiment_lock

    @contextmanager
    def observed_lock(root: Any) -> Any:
        if threading.current_thread().name == "sibling-confirm":
            progress.set()
        with lock(root):
            yield

    def observed_record(self: Any, aid: str, event: str, **detail: Any) -> None:
        record(self, aid, event, **detail)
        if event == "owned-attempt-cleanup" and aid == second:
            progress.set()

    def confirm() -> None:
        threading.current_thread().name = "sibling-confirm"
        owned.confirm("discovery-owned", True)

    with ThreadPoolExecutor(max_workers=1) as pool:

        def during_grade(*args: Any, **kwargs: Any) -> Any:
            value = grade(*args, **kwargs)
            pool.submit(confirm)
            assert progress.wait(10)
            return value

        monkeypatch.setattr(verify, "grade_files", during_grade)
        monkeypatch.setattr(trial, "experiment_lock", observed_lock)
        monkeypatch.setattr(trial.Experiment, "record", observed_record)
        result = verify.grade(experiment, first, GRADER, tmp_path / "grading")
    assert result["status"] == "PASS"
    assert owned.all_absent()
