"""Controller-read per-stage outcomes for a witnessed gate run (#376).

`skillc.stage_capture.capture_stages` is exercised on REAL stdout captured
from the pinned CPP runner (`evals/level3/*/stage-samples/`), so a reader
that only understood hand-written JSON would fail here, and on mutated copies
of those bytes for every refusal it promises. The witness tests check that
the capture is taken from the run's own controller-held output, bound to that
run, and never produced for a run that did not exit normally.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from skillc import stage_capture
from skillc.backend import ExecuteResult, Limits
from skillc.gate_witness import GateWitness

ROOT = Path(__file__).resolve().parent.parent
TASKS = ("gate-stops-early", "verify-stops-early")


def _sample(task: str, shape: str) -> tuple[bytes, int]:
    directory = ROOT / "evals" / "level3" / task / "stage-samples"
    manifest = json.loads((directory / "samples.json").read_text(encoding="utf-8"))
    data = (directory / f"{shape}.stdout").read_bytes()
    assert hashlib.sha256(data).hexdigest() == manifest[shape]["sha256"]
    return data, manifest[shape]["exit_code"]


def _outcomes(capture: Mapping[str, object]) -> dict[str, object]:
    assert capture["status"] == "captured", capture
    stages = capture["stages"]
    assert isinstance(stages, dict)
    return {sid: stages[sid]["outcome"] for sid in stages}


# ------------------------------------------------------- real runner output


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("shape,expected", [
    ("all-passed", {"lint": "passed", "test": "passed", "typecheck": "passed"}),
    ("adds-typecheck", {"lint": "passed", "test": "passed", "typecheck": "passed"}),
    ("typecheck-skipped", {"lint": "passed", "test": "passed", "typecheck": "skipped"}),
    ("lint-failed", {"lint": "failed", "test": "not-run", "typecheck": "not-run"}),
    ("test-failed", {"lint": "passed", "test": "failed", "typecheck": "not-run"}),
    ("typecheck-failed", {"lint": "passed", "test": "passed", "typecheck": "failed"}),
])
def test_real_pinned_runner_output_yields_each_stage_outcome(task: str, shape: str, expected: dict) -> None:
    data, exit_code = _sample(task, shape)
    assert _outcomes(stage_capture.capture_stages(data, exit_code)) == expected


@pytest.mark.parametrize("task", TASKS)
def test_an_early_stop_names_the_failed_prerequisite(task: str) -> None:
    data, exit_code = _sample(task, "lint-failed")
    capture = stage_capture.capture_stages(data, exit_code)
    assert capture["failed_step"] == "lint" and capture["runner_success"] is False
    for later in ("test", "typecheck"):
        stage = capture["stages"][later]
        assert stage["runner_status"] == "pending"
        assert "stopped after lint failed" in stage["reason"]


# ------------------------------------------------------------ refusals


def _mutate(old: bytes, new: bytes, task: str = "gate-stops-early", shape: str = "lint-failed") -> tuple[bytes, int]:
    data, exit_code = _sample(task, shape)
    assert old in data, old
    return data.replace(old, new, 1), exit_code


@pytest.mark.parametrize("label,data_exit,why", [
    ("no stdout", (None, 1), "no stdout"),
    ("not utf-8", (b"\xff\xfe", 1), "not UTF-8"),
    ("empty", (b"", 1), "exactly one"),
    ("a second document", None, "exactly one"),
    ("no verdict", None, "verdict line"),
    ("another plan", None, "plan"),
    ("a repeated step id", None, "repeats"),
    ("exit contradicts verdict", None, "contradicts verdict"),
    ("success contradicts verdict", None, "contradicts verdict"),
    ("failed_step did not fail", None, "failed_step"),
])
def test_every_unattributable_output_is_unavailable(label: str, data_exit: tuple | None, why: str) -> None:
    if data_exit is None:
        lint_failed, exit_code = _sample("gate-stops-early", "lint-failed")
        data_exit = {
            "a second document": (b"{\n}\n" + lint_failed, exit_code),
            "no verdict": (lint_failed.replace(b"FLOW_FINISH_GATE: fail", b"done"), exit_code),
            "another plan": _mutate(b'"plan": "check"', b'"plan": "finish"'),
            "a repeated step id": _mutate(b'"id": "test"', b'"id": "lint"'),
            "exit contradicts verdict": (lint_failed, 0),
            "success contradicts verdict": _mutate(b'"success": false', b'"success": true'),
            "failed_step did not fail": _mutate(b'"failed_step": "lint"', b'"failed_step": "test"'),
        }[label]
    capture = stage_capture.capture_stages(*data_exit)
    assert capture["status"] == "unavailable", (label, capture)
    assert why in str(capture["reason"])


def test_a_successful_run_reporting_a_failed_stage_is_unavailable() -> None:
    data, exit_code = _sample("gate-stops-early", "all-passed")
    lines = data.decode().split("\n")
    index = next(i for i, line in enumerate(lines) if '"status": "success"' in line)
    lines[index] = lines[index].replace("success", "failed")
    capture = stage_capture.capture_stages("\n".join(lines).encode(), exit_code)
    assert capture["status"] == "unavailable" and "failed stage" in str(capture["reason"])


# ------------------------------------------------- per-stage unattributable


def _document(details: list[dict], *, success: bool, failed_step: str | None = None) -> tuple[bytes, int]:
    body = {"success": success, "plan": "check", "step_details": details}
    if failed_step:
        body["failed_step"] = failed_step
    verdict, code = ("ok", 0) if success else ("fail", 1)
    return (f"preamble\n{json.dumps(body, indent=2)}\nFLOW_FINISH_GATE: {verdict}\n").encode(), code


def test_runner_not_run_and_subsumed_states_map_without_context() -> None:
    data, code = _document([{"id": "lint", "status": "failed"},
                            {"id": "test", "status": "not-run", "not_run_reason": "`verify` failed"},
                            {"id": "typecheck", "status": "pending"}], success=False, failed_step="lint")
    capture = stage_capture.capture_stages(data, code)
    assert _outcomes(capture) == {"lint": "failed", "test": "not-run", "typecheck": "not-run"}
    assert capture["stages"]["test"]["reason"] == "`verify` failed"
    data, code = _document([{"id": "lint", "status": "subsumed"}], success=True)
    assert _outcomes(stage_capture.capture_stages(data, code)) == {"lint": "passed"}


@pytest.mark.parametrize("entry,why", [
    ({"id": "lint", "status": "success", "carried_from_previous_run": True}, "carried"),
    ({"id": "lint", "status": "success", "executed_in_this_run": False}, "carried"),
    ({"id": "lint", "status": "pending"}, "no earlier failed stage"),
    ({"id": "lint", "status": "running"}, "not a resolved outcome"),
])
def test_a_stage_without_this_runs_execution_is_unattributable(entry: dict, why: str) -> None:
    data, code = _document([entry, {"id": "test", "status": "success"}], success=True)
    capture = stage_capture.capture_stages(data, code)
    assert capture["status"] == "captured"
    assert capture["stages"]["lint"]["outcome"] is None and why in capture["stages"]["lint"]["reason"]
    assert capture["stages"]["test"]["outcome"] == "passed"


# ------------------------------------------------------ witness integration


@dataclass
class _Backend:
    results: dict[str, ExecuteResult]

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits, cancel: object = None,
                        stdin: object = None, cwd: object = None, env: object = None,
                        confine_root: object = None) -> ExecuteResult:
        return self.results[argv[0]]


def _witness(results: dict[str, ExecuteResult], *, digests: list[str] | None = None,
             reader: object = stage_capture.capture_stages) -> GateWitness:
    order = iter(digests or ["sha256:t"] * 8)
    return GateWitness(
        declared_gates={"flow-check-plan": ["flow-check-plan"], "flow-check-summary": ["flow-check-summary"]},
        tree_digest_fn=lambda: next(order), backend=_Backend(results), handle=None, limits=Limits(timeout=5.0),
        gate_exclusivity=False, exclusivity_basis="test", stage_capture={"flow-check-plan": reader},
    )


def _record(witness: GateWitness) -> dict:
    return json.loads(witness.finalize("a-1").to_json_bytes())


def test_the_plan_runs_stages_come_from_its_own_controller_held_stdout() -> None:
    data, code = _sample("gate-stops-early", "lint-failed")
    witness = _witness({"flow-check-plan": ExecuteResult(reason="exited", exit_code=code, stdout=data),
                        "flow-check-summary": ExecuteResult(reason="exited", exit_code=3, stdout=b"")})
    witness.decide({"op": "run_gate", "gate": "flow-check-plan"})
    witness.decide({"op": "run_gate", "gate": "flow-check-summary"})
    record = _record(witness)
    assert record["version"] == 3
    (run,) = record["gates"]["flow-check-plan"]["runs"]
    assert _outcomes(run["stages"]) == {"lint": "failed", "test": "not-run", "typecheck": "not-run"}
    # A gate with no declared reader carries no stage record at all.
    assert "stages" not in record["gates"]["flow-check-summary"]["runs"][0]


def test_a_rerun_appends_its_own_stages_and_never_rewrites_the_earlier_run() -> None:
    failed, failed_code = _sample("gate-stops-early", "lint-failed")
    passed, passed_code = _sample("gate-stops-early", "all-passed")
    backend_results = {"flow-check-plan": ExecuteResult(reason="exited", exit_code=failed_code, stdout=failed)}
    witness = _witness(backend_results, digests=["sha256:before", "sha256:after"])
    witness.decide({"op": "run_gate", "gate": "flow-check-plan"})
    backend_results["flow-check-plan"] = ExecuteResult(reason="exited", exit_code=passed_code, stdout=passed)
    witness.decide({"op": "run_gate", "gate": "flow-check-plan"})
    first, second = _record(witness)["gates"]["flow-check-plan"]["runs"]
    assert (first["tree_digest_at_start"], _outcomes(first["stages"])["lint"]) == ("sha256:before", "failed")
    assert (second["tree_digest_at_start"], _outcomes(second["stages"])["lint"]) == ("sha256:after", "passed")


@pytest.mark.parametrize("result,why", [
    (ExecuteResult(reason="timeout", exit_code=None, stop_confirmed=True), "did not exit normally"),
    (ExecuteResult(reason="launch-failed", exit_code=None), "did not exit normally"),
])
def test_a_run_that_did_not_exit_normally_has_an_unavailable_capture(result: ExecuteResult, why: str) -> None:
    witness = _witness({"flow-check-plan": result})
    witness.decide({"op": "run_gate", "gate": "flow-check-plan"})
    (run,) = _record(witness)["gates"]["flow-check-plan"]["runs"]
    assert run["stages"]["status"] == "unavailable" and why in run["stages"]["reason"]


def test_a_reader_that_raises_is_an_unavailable_capture_not_a_crash() -> None:
    def broken(stdout: object, exit_code: object) -> Mapping[str, object]:
        raise KeyError("boom")
    data, code = _sample("gate-stops-early", "all-passed")
    witness = _witness({"flow-check-plan": ExecuteResult(reason="exited", exit_code=code, stdout=data)},
                       reader=broken)
    witness.decide({"op": "run_gate", "gate": "flow-check-plan"})
    (run,) = _record(witness)["gates"]["flow-check-plan"]["runs"]
    assert run["stages"] == {"status": "unavailable", "reason": "stage reader failed (KeyError)"}


def test_a_stage_reader_for_an_undeclared_gate_is_refused() -> None:
    with pytest.raises(ValueError, match="undeclared"):
        GateWitness(declared_gates={"lint": ["lint"]}, tree_digest_fn=lambda: "t", backend=_Backend({}),
                    handle=None, limits=Limits(timeout=5.0), gate_exclusivity=False, exclusivity_basis="",
                    stage_capture={"typo": stage_capture.capture_stages})


def test_the_production_attempt_declares_the_plan_gate_as_stage_bearing() -> None:
    source = (ROOT / "skillc" / "agent_trial.py").read_text(encoding="utf-8")
    assert 'stage_capture={"flow-check-plan": stage_capture.capture_stages}' in source
