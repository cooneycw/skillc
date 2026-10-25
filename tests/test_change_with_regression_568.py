"""Artifact qualification and its own blinding/resource controls; no live client."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

TASK = Path(__file__).resolve().parents[1] / "evals/level3/change-with-regression-568"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("python3") is None or not hasattr(os, "WNOWAIT"),
    reason="requires git, python3 and POSIX WNOWAIT",
)


def load() -> Any:
    spec = importlib.util.spec_from_file_location("inventory568_qualify", TASK / "qualify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def q() -> Any:
    return load()


@pytest.fixture(scope="module")
def certified(q: Any) -> dict[str, Any]:
    return dict(q.qualify())


def test_fixed_population_discriminates_artifacts(certified: dict[str, Any]) -> None:
    assert certified["case_count"] == 24
    assert certified["valid_vector_count"] == 48
    cases = certified["cases"]
    assert cases["reference-valid-pack"] == cases["alternative-valid-pack"] == "PASS"
    assert cases["initial-missing-batch"] == cases["shared-replace-regression"] == "FAIL"
    assert cases["remote-correct-local-wrong"] == "PASS"
    assert cases["remote-wrong-local-correct"] == "FAIL"
    assert cases["unreadable-remote-object"] == cases["unsupported-packed-remote"] == "UNKNOWN"
    assert certified["executed_semantic_vectors"] == 11 * 24
    remote = certified["remote_cases"]["remote-correct-local-wrong"]
    assert remote["files"]["inventory.py"]["mode"] == "100644"
    assert len(remote["files"]["inventory.py"]["sha256"]) == 64
    assert remote["remote_vector"]["feature"] and not remote["local_vector"]["feature"]
    initial = certified["semantic"]["initial-missing-batch"]
    assert initial["legacy"] and not initial["feature"]


def test_actual_feature_and_regression_test_reds(certified: dict[str, Any]) -> None:
    rows = {r["program"]: r for r in certified["protection"]}
    assert set(rows) == {"reference", "alternative", "csv-only", "jsonl-only", "partial", "replace"}
    assert rows["reference"]["ok"] and rows["alternative"]["ok"]
    assert not any(rows[k]["ok"] for k in ("csv-only", "jsonl-only", "partial", "replace"))
    assert "test_public_api_preserves_history" in rows["replace"]["stderr"]
    assert all(r["count"] == 5 and r["skipped"] == 0 for r in rows.values())


@pytest.mark.parametrize("field", ["cases", "vectors", "protection", "resource_probes"])
def test_missing_and_duplicate_population_is_refused(q: Any, field: str) -> None:
    sources = q.o.load_sources()
    for replacement in ([], [1, 1]):
        m = q.manifest(sources)
        m[field] = replacement
        changed = {**sources, "controls.json": json.dumps(m).encode()}
        with pytest.raises(q.Refused):
            q.manifest(changed)


def test_blind_semantic_engine_cannot_certify(q: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = q.o.load_sources()
    assert b"batch import is not implemented" in sources["fixture/inventory.py"]
    monkeypatch.setattr(q.o, "semantic", lambda *a: {
        "feature": True, "legacy": True, "vectors": [{"id": name} for name in q.VECTORS],
    })
    with pytest.raises(q.Refused, match="initial-missing-batch"):
        q.qualify()


def test_always_pass_and_false_red_reconciliation(q: Any) -> None:
    q.reconcile({"good": "PASS", "bad": "FAIL", "missing": "UNKNOWN"})
    for status in ("PASS", "FAIL"):
        with pytest.raises(q.Refused):
            q.reconcile(dict.fromkeys(("good", "bad", "missing"), status))


def test_mutation_must_really_apply(q: Any) -> None:
    sources = q.o.load_sources()
    m = q.manifest(sources)
    m["mutations"]["replace"]["old"] = "not present in reference"
    with pytest.raises(q.o.Unavailable, match="precondition"):
        q.o.program("replace", m, sources)
    with pytest.raises(q.o.Unavailable, match="unknown trusted"):
        q.o.program("../arbitrary", m, sources)


def test_resources_have_real_refusal_and_positive_twins(certified: dict[str, Any]) -> None:
    probes = certified["resource_probes"]
    assert set(probes) == {"stdout-overflow", "stderr-overflow", "staging-overflow", "owned-child-timeout"}
    assert probes["owned-child-timeout"]["below"]["status"] == "PASS"
    assert probes["owned-child-timeout"]["over"]["status"] == "UNKNOWN"


def test_neutered_cleanup_is_not_a_green(q: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    owned: list[Any] = []
    real = q.o.stop_group
    monkeypatch.setattr(q.o, "stop_group", owned.append)
    try:
        with pytest.raises(q.Refused, match="still executing"):
            q.child_probe(q.o.Budget())
    finally:
        for process in owned:
            real(process)


def test_deadline_refuses_before_launch(q: Any, tmp_path: Path) -> None:
    budget = q.o.Budget(seconds=-1)
    with pytest.raises(q.o.Unavailable, match="deadline"):
        q.o.bounded([sys.executable, "-c", "pass"], tmp_path, budget)
    assert budget.processes == 0


def test_staging_limit_is_checked_before_write(q: Any, tmp_path: Path) -> None:
    budget = q.o.Budget(capacity=1)
    budget.write(tmp_path / "ok", b"x")
    with pytest.raises(q.o.Unavailable):
        budget.write(tmp_path / "overflow", b"y")
    assert not (tmp_path / "overflow").exists()


def test_no_arbitrary_candidate_cli(q: Any, tmp_path: Path) -> None:
    sentinel = tmp_path / "would-execute.py"
    sentinel.write_text("raise RuntimeError('must not execute')\n")
    proc = subprocess.run([sys.executable, str(TASK / "qualify.py"), "--candidate", str(sentinel)],
                          capture_output=True, text=True, timeout=5, check=False)
    assert proc.returncode == 64
    assert "committed fixture cases only" in proc.stderr


def test_capture_limit_cannot_be_called_a_valid_remote(q: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = q.o.load_sources()
    m = q.manifest(sources)
    real = q.o.remote_files
    monkeypatch.setattr(q.o, "remote_files", lambda export: real(export, max_bytes=1))
    with pytest.raises(q.o.Unavailable, match="capture budget"):
        q.remote_case("remote-correct-local-wrong", m, sources, q.o.Budget())


def test_uncommitted_source_is_not_host_executable(q: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    assert (TASK / "candidates/reference.py").read_bytes()
    monkeypatch.setattr(q.o.subprocess, "check_output", lambda *a, **kw: b"not the committed source")
    with pytest.raises(q.o.Unavailable, match="differs from HEAD"):
        q.o.load_sources()
