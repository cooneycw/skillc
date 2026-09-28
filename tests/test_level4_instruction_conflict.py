"""Tests for the Level 4 instruction-conflict-config-secret task and its
grader (#14).

Mirrors `tests/test_level1_slug.py`'s own wiring: `qualify.py` is loaded and
driven directly so the grader cannot go blind unnoticed, and each broken
grader control is proven refused for the reason its name gives. A gate that
runs only as a standalone script, invoked by nothing, is an instrument no CI
gate actually exercises - this file is what makes it one, including for
`check_known_gap`'s own drift/refusal behavior, negative-controlled here
against a synthetic gap built from `reference/` rather than against this
task's own known gaps, which issue #14's runtime PR closed (`known-gaps/
forged-log` moved to `wrong/forged-log` once `envelope["trusted"]` gave the
judge a real out-of-band channel) - so these controls do not depend on the
task always carrying an open one.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

TASK = (
    Path(__file__).resolve().parent.parent
    / "evals" / "level4" / "instruction-conflict-config-secret"
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level4_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("qualify")
grade_workflow = _load("grade_workflow")


def test_the_grader_is_certified() -> None:
    certified, rows = qualify.certify(TASK / "grade_workflow.py")
    assert certified, [r for r in rows if not r.ok]
    by_name = {r.candidate: r.status for r in rows}
    assert by_name["reference"] == "PASS"
    assert len(rows) >= 1 + 6  # reference + 6 wrong/*


@pytest.mark.parametrize("control", sorted(qualify.CONTROLS))
def test_every_broken_grader_is_refused_for_the_reason_its_name_gives(control: str) -> None:
    held, reason, _ = qualify.control_verdict(control)
    assert held, reason


def test_qualify_main_reports_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualify.main() == 0
    out = capsys.readouterr().out
    assert "QUALIFY: ok" in out
    assert "known gap(s) reproduce as documented" in out


def test_known_gaps_reproduce_as_documented() -> None:
    # If this task documents any known gaps, each must stay a checked fact
    # rather than a claim: the recorded miss must still reproduce exactly.
    # Issue #14's runtime PR closed this task's only gap (forged-log moved to
    # wrong/forged-log), so an empty known-gaps/ here is the correct state,
    # not an oversight.
    for path in qualify.known_gaps():
        ok, detail = qualify.check_known_gap(TASK / "grade_workflow.py", path)
        assert ok, detail


def _copy_task(tmp_path: Path) -> Path:
    root = tmp_path / "task"
    shutil.copytree(TASK, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _make_synthetic_known_gap(root: Path) -> Path:
    """A known-gaps/ fixture for negative-controlling `check_known_gap`
    itself, independent of whether this task currently has an open gap of
    its own. Built from `reference/` (graded PASS, no violations) with a
    declared `true_status` of FAIL - the documented-miss shape `check_known_gap`
    exists to verify, without tying the test to any specific narrative."""
    gap = root / "known-gaps" / "synthetic-gap"
    shutil.copytree(root / "reference", gap, ignore=shutil.ignore_patterns("__pycache__"))
    (gap / "expected.json").write_text(json.dumps({
        "graded_status_today": "PASS", "graded_violated_today": [],
        "true_status": "FAIL", "true_violated": ["stayed-in-bounds"],
    }), encoding="utf-8")
    return gap


def test_a_drifted_known_gap_turns_the_check_red(tmp_path: Path) -> None:
    # Negative control for check_known_gap itself: a known gap that stopped
    # reproducing as documented must be caught, not silently accepted.
    root = _copy_task(tmp_path)
    gap = _make_synthetic_known_gap(root)
    expected_path = gap / "expected.json"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    assert data["graded_violated_today"] == []  # the real grader reports no violations
    data["graded_violated_today"] = ["stayed-in-bounds"]
    expected_path.write_text(json.dumps(data), encoding="utf-8")
    ok, detail = qualify.check_known_gap(root / "grade_workflow.py", gap, root)
    assert not ok
    assert "no longer reproduces" in detail


def test_a_known_gap_whose_graded_status_matches_its_true_status_is_refused(tmp_path: Path) -> None:
    # A "known gap" that the grader already catches is not a gap - it belongs
    # in wrong/, not known-gaps/. check_known_gap must refuse that shape too.
    root = _copy_task(tmp_path)
    gap = _make_synthetic_known_gap(root)
    expected_path = gap / "expected.json"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    data["true_status"] = data["graded_status_today"]
    expected_path.write_text(json.dumps(data), encoding="utf-8")
    ok, detail = qualify.check_known_gap(root / "grade_workflow.py", gap, root)
    assert not ok
    assert "not a documented miss" in detail
