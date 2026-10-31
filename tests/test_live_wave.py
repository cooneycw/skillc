"""Model-free controller capture controls for the live wave primary unit."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from skillc import live_wave as lw

CONTROLS = Path(__file__).resolve().parents[1] / "controls/live-wave"
CASES = json.loads((CONTROLS / "cases.json").read_text())


def blob(value: Any) -> lw.Blob | None:
    if value is None:
        return None
    data = b"".join(json.dumps(row).encode() + b"\n" for row in value)
    return lw.Blob(data, hashlib.sha256(data).hexdigest())


def fixture(patches: list[dict[str, Any]] | None = None) -> tuple[lw.WavePlan, lw.WaveEvidence]:
    raw = json.loads((CONTROLS / "healthy.json").read_text())
    plan = raw["plan"]
    plan["roles"] = tuple(lw.RoleBinding(**{**r, "required_artifacts": tuple(r["required_artifacts"])})
                          for r in plan["roles"])
    evidence = raw["evidence"]
    for patch in patches or []:
        target = evidence
        for key in patch["path"][:-1]:
            target = target[key]
        target[patch["path"][-1]] = copy.deepcopy(patch["value"])
    captures = []
    for r in evidence["roles"]:
        r["transcript"] = blob(r["transcript"])
        r["protocol"] = blob(r["protocol"])
        r["pokes"] = lw.PokeCount(**r["pokes"]) if r.get("pokes") else None
        if r["artifacts"] is not None:
            r["artifacts"] = {p: lw.Blob(data.encode(), hashlib.sha256(data.encode()).hexdigest())
                              for p, data in r["artifacts"].items()}
        captures.append(lw.RoleEvidence(**r))
    evidence["roles"] = tuple(captures)
    return lw.WavePlan(**plan), lw.WaveEvidence(**evidence)


def grade(plan: lw.WavePlan, artifacts: Any) -> lw.DeliveryGrade:
    # Actual captured integrated bytes must contain BOTH independent outputs.
    expected = {r: json.loads(artifacts[r]["output.json"]) for r in ("worker-a", "worker-b")}
    actual = json.loads(artifacts[plan.integrator]["output.json"])
    return lw.DeliveryGrade("PASS" if actual == expected else "FAIL", 5)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_committed_controls(case: dict[str, Any]) -> None:
    plan, evidence = fixture(case["patches"])
    report = lw.verdict(plan, evidence, grade)
    assert report["status"] == case["expected"], report
    assert report["primary"]["planned"] == 1
    assert report["primary"]["completed"] == int(case["expected"] == "PASS")
    if case["reason"]:
        assert case["reason"] in report["failures"] + report["unknown"]


def test_denominator_includes_unobserved_nonstarts_timeouts_and_incomplete() -> None:
    cases = [CASES[0], *[c for c in CASES if c["name"] in
             {"launch-failure", "missed-deadline", "unfinished-integration"}]]
    plans = []
    evidence = {}
    for index, case in enumerate(cases):
        plan, observed = fixture(case["patches"])
        wave_id = f"wave-{index}"
        # Update the retained protocol bindings as well as the inventory key.
        roles = []
        for r in observed.roles:
            assert r.protocol is not None
            rows = [json.loads(line) for line in r.protocol.data.splitlines()]
            for row in rows:
                row["wave_id"] = wave_id
            roles.append(replace(r, protocol=blob(rows)))
        plans.append(replace(plan, wave_id=wave_id))
        evidence[wave_id] = replace(observed, wave_id=wave_id, roles=tuple(roles))
    plans.append(replace(plans[0], wave_id="never-started"))
    result = lw.report(plans, evidence, grade)
    assert result["primary"] == {"unit": "wave", "planned": 5, "completed": 1,
                                 "pass": 1, "fail": 2, "unknown": 2}
    assert len(result["waves"]) == 5
    assert len(result["waves"][-1]["roles"]) == 3


@pytest.mark.parametrize("field,value", [("session_id", "another-session"), ("attempt_id", "stale-attempt")])
def test_capture_join_loss_is_unknown(field: str, value: str) -> None:
    plan, evidence = fixture([{"path": ["roles", 1, field], "value": value}])
    result = lw.verdict(plan, evidence, grade)
    assert result["status"] == "UNKNOWN"
    assert "worker-a:session-capture-binding" in result["unknown"]


@pytest.mark.parametrize("field,value", [("session_id", "stale-session"), ("attempt_id", "stale-attempt"),
    ("nonce", "stale-nonce"), ("generation", 1), ("generation", False), ("revision", True),
    ("task", "wrong-task"), ("wave_id", "another-wave")])
def test_positive_protocol_join_violation_is_fail(field: str, value: Any) -> None:
    plan, evidence = fixture([{"path": ["roles", 1, "protocol", 0, field], "value": value}])
    result = lw.verdict(plan, evidence, grade)
    assert result["status"] == "FAIL"
    assert "worker-a:wrong-assignment-identity" in result["failures"]


@pytest.mark.parametrize("stream", ["protocol", "transcript"])
@pytest.mark.parametrize("fault", ["digest", "truncated", "duplicate-key", "bad-json", "empty", "nonobject"])
def test_capture_corruption_is_unknown(stream: str, fault: str) -> None:
    plan, evidence = fixture()
    r = evidence.roles[1]
    original = getattr(r, stream)
    data = {"truncated": original.data[:-1], "duplicate-key": b'{"x":1,"x":2}\n',
            "bad-json": b'{oops\n', "empty": b'', "nonobject": b'[]\n'}.get(fault, original.data)
    altered = lw.Blob(data, "0" * 64 if fault == "digest" else hashlib.sha256(data).hexdigest())
    roles = list(evidence.roles)
    roles[1] = replace(r, protocol=altered) if stream == "protocol" else replace(r, transcript=altered)
    result = lw.verdict(plan, replace(evidence, roles=tuple(roles)), grade)
    assert result["status"] == "UNKNOWN", result


def test_artifact_corruption_does_not_become_task_failure() -> None:
    plan, evidence = fixture()
    roles = list(evidence.roles)
    roles[0] = replace(roles[0], artifacts={"output.json": lw.Blob(b"{}", "0" * 64)})
    result = lw.verdict(plan, replace(evidence, roles=tuple(roles)), grade)
    assert result["status"] == "UNKNOWN"
    assert "incorrect-integrated-delivery" not in result["failures"]


@pytest.mark.parametrize("elapsed,expected", [(10, "PASS"), (10.01, "FAIL"), (None, "UNKNOWN")])
def test_grading_and_capture_share_the_common_deadline(elapsed: float | None, expected: str) -> None:
    plan, evidence = fixture()
    result = lw.verdict(plan, evidence, lambda p, a: replace(grade(p, a), completed_elapsed=elapsed))
    assert result["status"] == expected


def test_wrong_transcript_session_and_poke_binding_are_not_guessed() -> None:
    plan, evidence = fixture([
        {"path": ["roles", 1, "transcript", 0, "payload", "id"], "value": "stale"},
        {"path": ["roles", 1, "pokes", "session_id"], "value": "stale"}])
    result = lw.verdict(plan, evidence, grade)
    assert result["status"] == "UNKNOWN"
    assert result["roles"]["worker-a"]["pokes"] is None
    assert "worker-a:transcript-unavailable" in result["unknown"]


def test_metrics_are_separate_and_optional_observations_stay_null() -> None:
    plan, evidence = fixture()
    result = lw.verdict(plan, evidence, grade)
    assert result["metrics"] == {"timeout": False, "abandonment": False,
        "handoff_timings": None, "clutter_count": None, "tokens": 303, "wall_seconds": 5}
    assert result["roles"]["worker-a"]["tokens"] == 101
    assert result["roles"]["worker-a"]["wall_seconds"] == 4.5
    assert result["roles"]["worker-a"]["pokes"] == 1
    assert result["roles"]["worker-a"]["transcript_sha256"]
    assert result["roles"]["worker-a"]["protocol_sha256"]
    enriched = lw.verdict(plan, replace(evidence, handoff_timings={"worker-a": 2}, clutter_count=3), grade)
    assert enriched["status"] == "PASS"
    assert enriched["metrics"]["clutter_count"] == 3


@pytest.mark.parametrize("bad", [True, -1, None])
def test_pokes_do_not_infer_zero(bad: Any) -> None:
    plan, evidence = fixture([{"path": ["roles", 1, "pokes", "pokes"], "value": bad}])
    result = lw.verdict(plan, evidence, grade)
    assert result["status"] == "UNKNOWN"
    assert result["roles"]["worker-a"]["pokes"] is None


def test_population_refuses_empty_duplicate_or_unplanned_waves() -> None:
    plan, evidence = fixture()
    for plans, captures in [([], {}), ([plan, plan], {}), ([plan], {"unplanned": evidence})]:
        with pytest.raises(ValueError, match="population"):
            lw.report(plans, captures, grade)


def test_wrong_wave_envelope_cannot_supply_positive_task_evidence() -> None:
    plan, evidence = fixture([{"path": ["roles", 1, "protocol", 0, "role"], "value": "wrong"}])
    result = lw.verdict(plan, replace(evidence, wave_id="stale-wave"), grade)
    assert result["status"] == "UNKNOWN"
    assert not result["failures"]


@pytest.mark.parametrize("infrastructure_time", [None, 3])
def test_infrastructure_cancellation_does_not_grade_partial_artifact_as_task_failure(
    infrastructure_time: float | None,
) -> None:
    plan, evidence = fixture([{"path": ["roles", 0, "artifacts", "output.json"], "value": "{}"}])
    roles = tuple(replace(r, stop_reason="infrastructure-cancelled") for r in evidence.roles)
    result = lw.verdict(plan, replace(evidence, roles=roles, infrastructure_failed_at=infrastructure_time), grade)
    assert result["status"] == "UNKNOWN", result
    assert not result["failures"]


@pytest.mark.parametrize("at,expected", [(2, "FAIL"), (4, "UNKNOWN"), (None, "UNKNOWN")])
def test_natural_exit_failure_requires_observation_before_infrastructure(
    at: float | None, expected: str,
) -> None:
    plan, evidence = fixture()
    roles = list(evidence.roles)
    roles[1] = replace(roles[1], exit_code=7, stop_elapsed=at)
    result = lw.verdict(plan, replace(evidence, roles=tuple(roles), infrastructure_failed_at=3), grade)
    assert result["status"] == expected


def test_later_transcript_session_rebinding_is_unknown() -> None:
    raw = json.loads((CONTROLS / "healthy.json").read_text())["evidence"]["roles"][1]["transcript"]
    raw.append({"type": "session_meta", "payload": {"id": "another-session"}})
    plan, evidence = fixture([{"path": ["roles", 1, "transcript"], "value": raw}])
    assert lw.verdict(plan, evidence, grade)["status"] == "UNKNOWN"


@pytest.mark.parametrize("field,value", [("completion_elapsed", float("nan")),
    ("infrastructure_failed_at", -1), ("deadline_witnessed_at", 2),
    ("handoff_timings", {"worker-a": -1}), ("clutter_count", True)])
def test_invalid_observed_times_and_metrics_are_unknown(field: str, value: Any) -> None:
    plan, evidence = fixture()
    changes: dict[str, Any] = {field: value}
    result = lw.verdict(plan, replace(evidence, **changes), grade)
    assert result["status"] == "UNKNOWN", result


def test_ambiguous_duplicate_role_capture_is_unknown() -> None:
    plan, evidence = fixture()
    result = lw.verdict(plan, replace(evidence, roles=(*evidence.roles, evidence.roles[1])), grade)
    assert result["status"] == "UNKNOWN"
    assert "duplicate-role-capture" in result["unknown"]


@pytest.mark.parametrize("field", ["completion_elapsed", "grading"])
def test_inconsistent_observation_clock_is_unknown(field: str) -> None:
    plan, evidence = fixture()
    if field == "grading":
        result = lw.verdict(plan, evidence, lambda p, a: replace(grade(p, a), completed_elapsed=1))
    else:
        result = lw.verdict(plan, replace(evidence, completion_elapsed=1), grade)
    assert result["status"] == "UNKNOWN"


@pytest.mark.parametrize("status", ["UNKNOWN", "unrecognized"])
def test_grader_cannot_supply_a_pass_without_valid_verdict(status: Any) -> None:
    plan, evidence = fixture()
    result = lw.verdict(plan, evidence, lambda p, a: lw.DeliveryGrade(status, 5))
    assert result["status"] == "UNKNOWN"


def test_grader_unavailability_retains_planned_wave() -> None:
    plan, evidence = fixture()

    def unavailable(p: lw.WavePlan, a: Any) -> lw.DeliveryGrade:
        raise OSError("scripted grader unavailable")

    result = lw.report([plan], {plan.wave_id: evidence}, unavailable)
    assert result["primary"]["unknown"] == result["primary"]["planned"] == 1
