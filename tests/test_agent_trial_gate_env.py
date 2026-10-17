"""A witnessed gate must not rewrite the tree it is judged against (#400).

`flow-check-honest` compares the last `flow-check-plan` run's
`tree_digest_at_start` with the digest of the final frozen capture. On #315's
runner every `fresh` reference row graded INCONCLUSIVE: the plan gate's test
stage imported the project and wrote `__pycache__/*.pyc` into `/work`, the
capture froze them, and the run read stale against the tree it had just
checked.

Ported from the #402 branch (a duplicate of #400) to complement #407's
synthetic importing gate in `test_agent_trial_gate_witness.py`: these run the
REAL Level-3 reference gates, and commit the control that shows those gates do
write bytecode without the fix.

These tests take the env that production hands the witness
(`_WitnessSession.bind_and_check`, intercepted at the `GateWitness`
constructor), run each Level-3 task's real gate stages on its delivered
reference surface under that env, and digest the tree with the witness's own
`witness_capture.capture_digest` before and after. No Docker is needed: the
cause is what the gate's interpreter writes under the declared env, not the
container lifecycle; #315's runner rerun covers the lifecycle.

Red case: a genuine source edit after the gate still moves the digest, so the
comparison these tests rely on can still report stale.
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial, witness_capture
from skillc import level3_campaign as lc

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "evals" / "level3" / "campaign-375" / "manifest.json"
#: The Makefile `check` target's stages, in order, for both #270 tasks.
STAGES = ("ci/lint.py", "ci/check.py", "ci/typecheck.py")


class _Captured(Exception):
    pass


def _production_gate_env(monkeypatch: pytest.MonkeyPatch, measured: Mapping[str, str]) -> dict[str, Mapping[str, str]]:
    """The per-gate env `bind_and_check` declares to the witness."""
    seen: dict[str, Any] = {}

    def record(*_: object, **kwargs: Any) -> None:
        seen.update(kwargs)
        raise _Captured

    monkeypatch.setattr(agent_trial, "GateWitness", record)
    session = agent_trial._WitnessSession("a-gate-env", agent_trial.Limits(timeout=30))
    session.environment = measured
    with pytest.raises(_Captured):
        session.bind_and_check(object(), object())  # type: ignore[arg-type]
    declared = seen["declared_env"]
    assert set(declared) == {"flow-check-plan", "flow-check-summary"}
    return dict(declared)


def _deliver(task: str, work: Path) -> None:
    row = next(r for r in lc.load_manifest(MANIFEST).rows if r.task == task and r.candidate == "reference")
    assert row.actor == "fresh", "the reference row is the honest gate-last run"
    for relpath, data, executable in lc.candidate_files(ROOT / "evals" / "level3" / task, row):
        target = work / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if executable else 0o644)


def _run_gate(work: Path, env: Mapping[str, str]) -> None:
    """Every stage must complete green: a stage that never ran imports
    nothing, and would pass the unchanged-tree test vacuously."""
    for stage in STAGES:
        done = subprocess.run([sys.executable, stage], cwd=work, env=dict(env), check=False,
                              capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, f"{stage} exited {done.returncode}: {done.stdout}{done.stderr}"


def _measured(home: Path) -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home), "LANG": "C.UTF-8"}


@pytest.mark.parametrize("task", ["gate-stops-early", "verify-stops-early"])
def test_the_witnessed_gate_leaves_the_graded_tree_unchanged(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task: str) -> None:
    work = tmp_path / "work"
    _deliver(task, work)
    env = _production_gate_env(monkeypatch, _measured(tmp_path))["flow-check-plan"]
    at_start = witness_capture.capture_digest(work)
    _run_gate(work, env)
    written = sorted(p.relative_to(work).as_posix() for p in work.rglob("*.pyc"))
    assert written == [], f"the gate wrote bytecode into the graded tree: {written}"
    assert witness_capture.capture_digest(work) == at_start, \
        "the plan run's tree_digest_at_start would read stale against the tree it just checked"


def test_red_case_a_post_gate_source_edit_still_reads_stale(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "work"
    _deliver("gate-stops-early", work)
    env = _production_gate_env(monkeypatch, _measured(tmp_path))["flow-check-plan"]
    at_start = witness_capture.capture_digest(work)
    _run_gate(work, env)
    source = work / "rangekit" / "windows.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# edited after the gate\n", encoding="utf-8")
    assert witness_capture.capture_digest(work) != at_start


def _gate_environment(measured: Mapping[str, str]) -> Mapping[str, str]:
    session = agent_trial._WitnessSession("a-gate-env", agent_trial.Limits(timeout=1))
    session.environment = measured
    return session.gate_environment()


def test_the_gate_env_overrides_an_empty_switch_and_fills_an_empty_env() -> None:
    measured = {"PATH": "/usr/bin", "HOME": "/home/candidate", "PYTHONDONTWRITEBYTECODE": ""}
    assert _gate_environment(measured) == {**measured, "PYTHONDONTWRITEBYTECODE": "1"}
    assert _gate_environment({}) == {"PYTHONDONTWRITEBYTECODE": "1"}


@pytest.mark.parametrize("task", ["gate-stops-early", "verify-stops-early"])
def test_the_reference_gate_imports_the_project_so_the_control_can_see_bytecode(tmp_path: Path, task: str) -> None:
    """Negative control for the main test: under the measured env alone (what
    production passed before #400's fix, #407) the same gate does write
    bytecode. Without this, a gate that never imported anything would make the
    main test's no-.pyc assertion pass on unfixed code.

    Since #408 capture never exports a `__pycache__/*.pyc`, so that bytecode no
    longer moves the digest: the digest is the second, independent defence,
    and `tests/test_capture_bytecode_cache.py` owns its red cases."""
    work = tmp_path / "work"
    _deliver(task, work)
    at_start = witness_capture.capture_digest(work)
    _run_gate(work, _measured(tmp_path))
    assert list(work.rglob("__pycache__/*.pyc")), "the reference gate wrote no bytecode; the control above is blind"
    assert witness_capture.capture_digest(work) == at_start, "a bytecode cache moved the digest (#408)"
