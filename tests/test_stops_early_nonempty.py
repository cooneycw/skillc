"""Population and qualification-data controls for the revision-6 successor."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from test_stops_early_public_gate import LEGACY, ROOT, TASK

SUCCESSOR = ROOT / "evals/level3/gate-stops-early-public-gate"


def qualifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("public_gate_qualifier", SUCCESSOR / "qualify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seeded_reference(tmp_path: Path) -> Path:
    work = tmp_path / "candidate"
    shutil.copytree(LEGACY / "reference", work, ignore=shutil.ignore_patterns("__pycache__"))
    for script in (TASK / "fixture/ci").glob("*.py"):
        shutil.copy2(script, work / "ci" / script.name)
    return work


@pytest.mark.parametrize("stage", ["check", "lint", "typecheck"])
def test_seed_checkers_refuse_an_empty_population(tmp_path: Path, stage: str) -> None:
    work = seeded_reference(tmp_path)
    if stage == "check":
        shutil.rmtree(work / "tests")
        (work / "tests").mkdir()
    else:
        shutil.rmtree(work / "rangekit")
    result = subprocess.run([sys.executable, "-B", f"ci/{stage}.py"], cwd=work,
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 1 and "EMPTY:" in result.stdout, result


def test_seed_nonempty_healthy_twin_prints_real_population(tmp_path: Path) -> None:
    work = seeded_reference(tmp_path)
    result = subprocess.run(["make", "check"], cwd=work, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert "SOURCE: 2 module(s)" in result.stdout
    assert "Ran 2 tests" in result.stdout


def test_pinned_data_and_exact_population_have_a_healthy_twin() -> None:
    q = qualifier()
    sources = q.load_sources(ROOT)
    rows = q.load_rows(ROOT)
    assert len(sources) == 363 and len(rows) == 29
    assert {r["name"] for r in rows} == q.source_candidates(ROOT) | {"fixture", "discrimination/fixture"}


INTEGRITY = json.loads((SUCCESSOR / "public-gate-controls.json").read_text())["integrity_cases"]


@pytest.mark.parametrize("cell", INTEGRITY, ids=lambda cell: cell["name"])
def test_committed_source_integrity_case_is_refused(cell: dict) -> None:
    assert qualifier().integrity_case(ROOT, cell), cell


def test_missing_or_symlink_source_root_cannot_certify(tmp_path: Path) -> None:
    q = qualifier()
    with pytest.raises(ValueError, match="source root"):
        q.load_sources(tmp_path / "missing")
    (tmp_path / "link").symlink_to(ROOT, target_is_directory=True)
    with pytest.raises(ValueError, match="source root"):
        q.load_sources(tmp_path / "link")


def test_added_unindexed_fifo_is_not_an_exact_data_population(tmp_path: Path) -> None:
    q = qualifier()
    scratch = tmp_path / "sources"
    scratch.mkdir()
    q.write_surface(scratch, q.load_sources(ROOT))
    assert len(q.load_sources(scratch)) == 363  # Nonempty, byte-identical healthy twin.
    os.mkfifo(scratch / q.PREFIX / "reference/unlisted.py")
    with pytest.raises(ValueError, match="nonregular|source population"):
        q.load_sources(scratch)


def test_broken_judge_control_cannot_pass_a_blind_normal_predicate(monkeypatch: pytest.MonkeyPatch) -> None:
    q = qualifier()

    def always_pass(row: dict, files: dict, sources: dict, control: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(status="PASS", category="verdict", expected=row["expected"],
                               criteria=[{"id": c, "outcome": "SATISFIED"} for c in q.CRITERIA])

    monkeypatch.setattr(q, "grade", always_pass)
    assert q.certify(ROOT, "always_pass")  # Its actual output opposes the committed fixture expectation.
    monkeypatch.setattr(q, "outcomes", lambda result: result.expected)
    assert not q.certify(ROOT, "always_pass")  # A blind normal predicate cannot certify its own control.


BUDGET = json.loads((SUCCESSOR / "public-gate-controls.json").read_text())["budget_cases"]


@pytest.mark.parametrize("cell", BUDGET, ids=lambda cell: cell["name"])
def test_shared_launch_budget_has_both_verdicts(
        cell: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location("public_gate_budget", SUCCESSOR / "probe.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    elapsed, seen = 0, []
    durations = iter(cell["durations"])

    def run(argv: list, **kwargs: object) -> SimpleNamespace:
        nonlocal elapsed
        seen.append(kwargs["timeout"])
        elapsed += next(durations)
        text = "" if kwargs.get("text") else b""
        return SimpleNamespace(returncode=0, stdout=text, stderr=text)

    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: elapsed))
    monkeypatch.setattr(module, 'subprocess', SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(module, 'DEADLINE', 85)
    work = seeded_reference(tmp_path)
    launch = {"public": module.run_public_gate, "gate": module.run_gate, "traced": module.run_traced_gate}
    for name in cell["launchers"]:
        launch[name](str(work))
    assert seen == cell["expected_timeouts"]
    if cell["exhausted"]:
        assert module.run_public_gate(str(work))["timed_out"] is True
        assert len(seen) == len(cell["launchers"])  # The seventh subprocess was never launched.
    else:
        assert module.command_timeout() == 15
