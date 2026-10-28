"""Positive containment observations stop native schedules before another launch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_calibration_discrimination_run import _approved, _intact, _parse
from test_calibration_run import _IMAGE_DIGEST, _TEST_PINS, _declaration

from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import egress
from skillc import matched_pilot as mp

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, guarded: bool,
         observation: dict[str, object]) -> tuple[Any, list[mp.AttemptOutcome], list[str], list[int], Path]:
    calls: list[str] = []
    factories: list[int] = []

    def attempt(**kwargs: Any) -> dict[str, object]:
        calls.append(str(kwargs["attempt_id"]))
        return {"disposition": "inconclusive", "codex_guard": {"stop": None},
                "observation": {"run_metadata": {"model": "gpt-6-astra", "reasoning_effort": "high"},
                                **observation}}

    def backends() -> tuple[Any, Any]:
        factories.append(1)
        return object(), object()

    monkeypatch.setattr(cc, "run_level1_agent_attempt", attempt)
    if not guarded:
        monkeypatch.setattr(cr, "guard_kwargs", lambda *_: {})
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    if kind == "discrimination":
        experiment, outcomes = cr.run_discrimination(
            _parse(_approved(tmp_path)), run_dir=run_dir, intact=_intact(), image_digest="sha256:" + "d" * 64,
            backends=backends, argv_for=lambda _: ["codex"])
    else:
        experiment, outcomes = cr.run_calibration(
            _declaration(attempts=2), run_dir=run_dir, root=ROOT,
            treatment=cr.Treatment({"skill": b"body"}, "sha256:" + "ab" * 32, None, skill_digests=_TEST_PINS),
            image_digest=_IMAGE_DIGEST, backends=backends, argv_for=lambda _: ["codex"])
    return experiment, outcomes, calls, factories, run_dir


VIOLATIONS = [
    {"server_side_tool_uses": ["web_search_call"]},
    {"egress": {"status": "read", "allowlist_digest": egress.allowlist_digest(),
                "allowed": {"github.com:443": 1}}},
]


@pytest.mark.parametrize("kind", ["calibration", "discrimination"])
@pytest.mark.parametrize("guarded", [False, True])
@pytest.mark.parametrize("observation", VIOLATIONS, ids=["server-tool", "off-list-success"])
def test_native_schedule_stops_before_another_backend_and_checkpoints_the_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, guarded: bool, observation: dict[str, object],
) -> None:
    experiment, outcomes, calls, factories, run_dir = _run(tmp_path, monkeypatch, kind, guarded, observation)
    assert len(calls) == len(factories) == 1
    assert len(outcomes) == (6 if kind == "discrimination" else 4)
    assert all(o.record["disposition"] == "not-run" and "containment stop at" in str(o.record["reason"])
               for o in outcomes[1:])
    _, checkpoint = mp.read_outcomes(run_dir)
    assert checkpoint[0].record["schedule_containment_stop"] == outcomes[0].record["schedule_containment_stop"]
    report = cr.build_report(experiment, checkpoint, declared_model="gpt-6-astra", declared_effort="high")
    rows, stop = report["attempts"], report["containment_stop"]
    assert isinstance(rows, list) and isinstance(stop, dict)
    assert rows[0]["model_eligible"] is False
    assert stop["at_attempt"] == calls[0]
    assert stop["evidence"]
    assert "containment stop at " + calls[0] in cr.paste_back(report)
    assert "github.com" not in cr.paste_back(report)


@pytest.mark.parametrize("observation", [
    {"server_side_tool_uses": []},
    {"egress": {"status": "read", "allowed": {"CHATGPT.COM.:443": 1, "auth.openai.com:443": 2}}},
    {"egress": {"status": "read", "denied": {"github.com:443": 1},
                "upstream_failed": {"github.com:443": 1}, "peer_rejected": 1}},
    {"egress": {"status": "read", "allowed": {"github.com:443": 0}}},
])
def test_clean_or_refused_traffic_continues_the_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, observation: dict[str, object],
) -> None:
    _, outcomes, calls, factories, _ = _run(tmp_path, monkeypatch, "discrimination", False, observation)
    assert len(calls) == len(factories) == len(outcomes) == 6
    assert all("schedule_containment_stop" not in o.record for o in outcomes)


@pytest.mark.parametrize("observation", VIOLATIONS, ids=["server-tool", "off-list-success"])
@pytest.mark.parametrize("stopped", [False, True], ids=["historical-continue", "native-stop"])
def test_public_recovery_reports_only_a_recorded_stop(
    tmp_path: Path, observation: dict[str, object], stopped: bool,
) -> None:
    import json

    from test_calibration_report import _checkpoint, _invoke

    run, declaration, _ = _checkpoint(tmp_path, completed=2)
    path = run / cr.OUTCOMES_FILENAME
    data = json.loads(path.read_text())
    # Change controlled observation in the actual captured checkpoint, preserving
    # its verified ledger and launch pins. Historical files have no stop marker.
    record = data["outcomes"][0]["record"]
    record["observation"].update(observation)
    if stopped:
        record["schedule_containment_stop"] = cr.containment_evidence(record)
    path.write_text(json.dumps(data))
    checkpoint = path.read_bytes()
    assert _invoke(str(run), "--declaration", str(declaration)) == 1
    report = json.loads((run / cr.REPORT_FILENAME).read_text())
    assert report["attempts"][0]["model_eligible"] is False
    assert report["attempts"][0]["containment_violation"]["evidence"]
    assert bool(report.get("containment_stop")) is stopped
    assert ("containment stop at " in cr.paste_back(report)) is stopped
    assert path.read_bytes() == checkpoint


def test_recovery_refuses_a_stop_marker_without_corresponding_observation(tmp_path: Path) -> None:
    import json

    from test_calibration_report import _checkpoint, _invoke

    run, declaration, _ = _checkpoint(tmp_path, completed=2)
    path = run / cr.OUTCOMES_FILENAME
    data = json.loads(path.read_text())
    data["outcomes"][0]["record"]["schedule_containment_stop"] = {
        "trigger": "observed containment violation", "evidence": {"server_side_tool_uses": ["web_search_call"]}}
    path.write_text(json.dumps(data))
    assert _invoke(str(run), "--declaration", str(declaration)) == 2
    assert not (run / cr.REPORT_FILENAME).exists()
