"""Population and qualification-data controls for the revision-6 successor."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

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
