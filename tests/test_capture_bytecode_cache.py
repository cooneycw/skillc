"""Bytecode caches are build products, never captured (#408).

#400 ran witnessed gates with PYTHONDONTWRITEBYTECODE=1, but a gate whose
child interpreter runs in isolated mode (`python -I`) ignores every PYTHON*
variable and writes `__pycache__/*.pyc` anyway. The final capture froze them,
and the honest run's `tree_digest_at_start` read stale against the graded
tree: 2 of #375's 42 rows (`incomplete.isolated-child-gate`).

CPython reads a `__pycache__/*.pyc` only as a cache for its matching source
and never imports one without it, so capture now excludes it. It is neither
digested nor delivered to grading, so a cache planted after a gate can neither
move a freshness digest nor load in place of its source (an unchecked-hash
.pyc, PEP 552). A sourceless `mod.pyc` beside the code IS importable code and
stays captured.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from skillc import agent_trial, trial, witness_capture
from skillc import level3_campaign as lc

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "evals" / "level3" / "campaign-375" / "manifest.json"
STAGES = ("ci/lint.py", "ci/check.py", "ci/typecheck.py")


def _tree(root: Path) -> Path:
    (root / "src" / "__pycache__").mkdir(parents=True)
    (root / "src" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    return root


def _capture(root: Path, store: Path) -> trial._Capture:
    store.mkdir()
    (store / trial.OBJECTS).mkdir(mode=0o700)
    return trial._export(trial.Experiment(root=store, ledger={}), root, ("*",), trial.Limits())


def test_a_cache_pyc_is_excluded_and_says_why(tmp_path: Path) -> None:
    root = _tree(tmp_path / "work")
    (root / "src" / "__pycache__" / "mod.cpython-311.pyc").write_bytes(b"cached bytecode")
    got = _capture(root, tmp_path / "store")
    assert [a["path"] for a in got.artifacts] == ["src/mod.py"]
    assert got.exclusions == [{"path": "src/__pycache__/mod.cpython-311.pyc",
                               "reason": "a bytecode cache under __pycache__/; a build product, never exported"}]


def test_a_sourceless_pyc_and_other_cache_dir_files_are_still_captured(tmp_path: Path) -> None:
    """The red side of the boundary: `legacy.pyc` beside the code is importable
    without a source, and a non-.pyc file under __pycache__ is not bytecode."""
    root = _tree(tmp_path / "work")
    (root / "src" / "legacy.pyc").write_bytes(b"sourceless bytecode")
    (root / "src" / "__pycache__" / "notes.txt").write_text("not bytecode\n", encoding="utf-8")
    (root / "__pycache__.pyc").write_bytes(b"a file, not a cache directory")
    got = _capture(root, tmp_path / "store")
    assert sorted(str(a["path"]) for a in got.artifacts) == [
        "__pycache__.pyc", "src/__pycache__/notes.txt", "src/legacy.pyc", "src/mod.py"]
    assert got.exclusions == []


def test_the_freshness_digest_ignores_a_cache_but_not_code(tmp_path: Path) -> None:
    root = _tree(tmp_path / "work")
    before = witness_capture.capture_digest(root)
    (root / "src" / "__pycache__" / "mod.cpython-311.pyc").write_bytes(b"planted after the gate")
    assert witness_capture.capture_digest(root) == before, "a cache moved the freshness digest"
    (root / "src" / "legacy.pyc").write_bytes(b"sourceless bytecode")
    assert witness_capture.capture_digest(root) != before, "a sourceless .pyc is code and must read stale"
    (root / "src" / "legacy.pyc").unlink()
    (root / "src" / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert witness_capture.capture_digest(root) != before, "a source edit must read stale"


@pytest.mark.parametrize("task", ["gate-stops-early", "verify-stops-early"])
def test_an_isolated_child_gate_stays_fresh(tmp_path: Path, task: str) -> None:
    """The #375 rows themselves: the `incomplete/isolated-child-gate` candidate's
    real gate, under the env production declares to the witness. Its `python -I`
    child DOES write bytecode (asserted, so this cannot pass on a gate that
    imports nothing), and the capture digest still does not move."""
    work = tmp_path / "work"
    row = next(r for r in lc.load_manifest(MANIFEST).rows
               if r.task == task and r.candidate == "incomplete/isolated-child-gate")
    for relpath, data, executable in lc.candidate_files(ROOT / "evals" / "level3" / task, row):
        target = work / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if executable else 0o644)
    session = agent_trial._WitnessSession("a-isolated", agent_trial.Limits(timeout=1))
    session.environment = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(tmp_path), "LANG": "C.UTF-8"}
    env = dict(session.gate_environment())
    at_start = witness_capture.capture_digest(work)
    for stage in STAGES:
        done = subprocess.run([sys.executable, stage], cwd=work, env=env, check=False,
                              capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, f"{stage} exited {done.returncode}: {done.stdout}{done.stderr}"
    assert list(work.rglob("__pycache__/*.pyc")), "the -I child wrote no bytecode; this case is blind"
    assert witness_capture.capture_digest(work) == at_start, \
        "the plan run's tree_digest_at_start would read stale against the graded tree"
