"""Public declaration budget boundaries and exact historical exceptions (#546)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from skillc import calibration, uptake_study

ROOT = Path(__file__).resolve().parent.parent
HISTORICAL = (
    "evals/calibration-203/run-manifest.json",
    "evals/calibration-203-c3/run-manifest.json",
    "evals/calibration-203-low/run-manifest.json",
    "evals/calibration-287/auto6-pilot-declaration.json",
    "evals/calibration-287/auto6-precheck-declaration.json",
    "evals/calibration-287/pilot-discrimination-declaration.json",
    "evals/calibration-287/pilot-improvement-declaration.json",
    "evals/calibration-557-repeat/run-manifest.json",
    "evals/description-probe/agreement-broad/run-manifest.json",
    "evals/description-probe/agreement-selective/run-manifest.json",
    "evals/uptake-study/run-manifest.json",
    "evals/uptake-study/selective/run-manifest.json",
)
SAMPLES = {
    "calibration": "evals/calibration-204/run-manifest.json",
    "discrimination": "evals/calibration-287/auto6-precheck-declaration.json",
    "uptake": "evals/description-probe/agreement-broad/run-manifest.json",
}


def _load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text())


def _parse(data: dict[str, Any]) -> object:
    if data["kind"] == uptake_study.KIND:
        return uptake_study.parse_declaration(data)
    if data["kind"] == "discrimination-declaration":
        return calibration.parse_discrimination_declaration(data)
    return calibration.parse_declaration(data)


def _attempts(data: dict[str, Any]) -> int:
    repeats = (sum(c["attempts_per_arm"] for c in data["cases"]) if "cases" in data
               else data["attempts_per_arm"])
    return repeats * len(data["arms"])


def _new(kind: str) -> dict[str, Any]:
    data = _load(SAMPLES[kind])
    data["_comment"] += " New prospective declaration."
    return data


@pytest.mark.parametrize("kind", SAMPLES)
@pytest.mark.parametrize("shortfall", ["no-overhead", "one-second"])
def test_new_schedule_rejects_cap_without_measured_overhead(kind: str, shortfall: str) -> None:
    data = _new(kind)
    count, per = _attempts(data), data["shared"]["per_attempt_seconds"]
    data["shared"]["total_seconds"] = count * (per + 16) - (count * 16 if shortfall == "no-overhead" else 1)
    with pytest.raises((calibration.DeclarationRefused, uptake_study.StudyRefused), match="overhead"):
        _parse(data)
    # The edited declaration is valid once it budgets overhead; it is the
    # insufficient cap, rather than the act of editing, that must refuse.
    data["shared"]["total_seconds"] = _attempts(data) * (data["shared"]["per_attempt_seconds"] + 16)
    _parse(data)


@pytest.mark.parametrize("kind", SAMPLES)
def test_new_schedule_accepts_exact_measured_boundary(kind: str) -> None:
    data = _new(kind)
    data["shared"]["total_seconds"] = _attempts(data) * (data["shared"]["per_attempt_seconds"] + 16)
    _parse(data)


@pytest.mark.parametrize("path", (*HISTORICAL, SAMPLES["calibration"]))
def test_frozen_historical_declarations_still_parse(path: str) -> None:
    _parse(_load(path))


@pytest.mark.parametrize("path", HISTORICAL)
def test_single_byte_mutation_loses_historical_budget_exception(path: str) -> None:
    data = _load(path)
    original = json.dumps(data, sort_keys=True)
    data["_comment"] += "x"
    assert len(json.dumps(data, sort_keys=True).encode()) == len(original.encode()) + 1
    with pytest.raises((calibration.DeclarationRefused, uptake_study.StudyRefused), match="overhead"):
        _parse(data)
    data["shared"]["total_seconds"] = _attempts(data) * (data["shared"]["per_attempt_seconds"] + 16)
    _parse(data)


def test_overhead_constant_is_the_rounded_committed_live_maximum() -> None:
    from skillc import schedule_budget

    reports = [
        ROOT / "evals/matched-pilot/evidence/records/report.json",
        ROOT / "evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/records/report.json",
    ]
    overheads = []
    for path in reports:
        for row in json.loads(path.read_text())["attempts"]:
            timing = row["time_seconds"]
            overhead = timing["total"] - timing["agent"]
            assert overhead == pytest.approx(timing["setup"] + timing["grading"], abs=0.002)
            overheads.append(overhead)
    assert len(overheads) == 12
    assert max(overheads) == pytest.approx(15.622)
    assert schedule_budget.MIN_ATTEMPT_OVERHEAD_SECONDS == math.ceil(max(overheads)) == 16
