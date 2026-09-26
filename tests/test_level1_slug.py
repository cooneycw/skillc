"""Tests for the Level 1 slug small-fix task and its grader (#5).

`test_the_grader_is_certified` and `test_every_broken_grader_is_refused` are the
two halves of `qualify.py`, wired into the suite so the grader cannot go blind
unnoticed. `test_a_mutated_reference_turns_the_gate_red` is the negative control
for the gate itself: the same gate, one planted defect, and it must refuse.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

TASK = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix"

#: The CPP blob recorded in PROVENANCE.md.
PINNED_FIXTURE_BLOB = "8229b1b71d1d6d23cc10e4d68b646e89572c4f3e"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level1_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # A dataclass resolves its module through sys.modules while it is being built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("qualify")
grade_slug = _load("grade_slug")


def _outcomes(candidate: Path) -> dict[str, str]:
    result = grade_slug.grade(candidate)
    return {c["id"]: c["outcome"] for c in result["criteria"]}


def test_the_fixture_is_the_pinned_cpp_blob() -> None:
    blob = subprocess.run(
        ["git", "hash-object", str(TASK / "fixture" / "src" / "slugify.py")],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert blob == PINNED_FIXTURE_BLOB
    assert PINNED_FIXTURE_BLOB in (TASK / "PROVENANCE.md").read_text(encoding="utf-8")


def test_the_grader_is_certified() -> None:
    certified, rows = qualify.certify(TASK / "grade_slug.py")
    assert certified, [r for r in rows if not r.ok]
    by_name = {r.candidate: r.status for r in rows}
    assert by_name["fixture"] == "FAIL"
    assert by_name["reference"] == "PASS"
    assert len(rows) >= 2 + 2 + 5


@pytest.mark.parametrize("control", qualify.CONTROLS)
def test_every_broken_grader_is_refused(control: str) -> None:
    certified, _ = qualify.certify(TASK / "grader-controls" / f"{control}.py")
    assert not certified


@pytest.mark.parametrize("control", ["crash", "no_output"])
def test_a_grader_that_gave_no_verdict_is_INCONCLUSIVE_not_FAIL(control: str) -> None:
    # Refusal alone would also hold if a crash were read as FAIL (the reference
    # would still mismatch). The property is the classification: a crash must not
    # count as having detected the wrong outputs.
    _, rows = qualify.certify(TASK / "grader-controls" / f"{control}.py")
    assert {r.status for r in rows} == {"INCONCLUSIVE"}


def test_reported_example_only_fixes_pass_the_example_and_fail_held_out() -> None:
    for name in ("example-only", "trailing-only"):
        outcomes = _outcomes(TASK / "wrong" / name)
        assert outcomes["reported-example"] == "SATISFIED", name
        assert outcomes["R3"] == "VIOLATED", name


def test_a_missing_function_is_a_candidate_violation_not_unknown() -> None:
    outcomes = _outcomes(TASK / "wrong" / "renamed")
    assert outcomes["R4-interface"] == "VIOLATED"
    certified_status, _ = qualify.status_of(TASK / "grade_slug.py", TASK / "wrong" / "renamed")
    assert certified_status == "FAIL"


def test_a_raising_or_hanging_candidate_is_a_violation(tmp_path: Path) -> None:
    for name, body in {
        "raises": "def slugify(title):\n    raise ValueError('no')\n",
        "hangs": "def slugify(title):\n    while True:\n        pass\n",
        "not-str": "def slugify(title):\n    return None\n",
    }.items():
        src = tmp_path / name / "src"
        src.mkdir(parents=True)
        (src / "slugify.py").write_text(body, encoding="utf-8")
        if name == "hangs":
            grade_slug.TIMEOUT_SECONDS = 2
        try:
            outcomes = _outcomes(tmp_path / name)
        finally:
            grade_slug.TIMEOUT_SECONDS = 10
        assert outcomes["R4-interface"] == "VIOLATED", name


def test_a_mutated_reference_turns_the_gate_red(tmp_path: Path) -> None:
    root = tmp_path / "task"
    shutil.copytree(TASK, root, ignore=shutil.ignore_patterns("__pycache__"))
    reference = root / "reference" / "src" / "slugify.py"
    text = reference.read_text(encoding="utf-8")
    assert text.count('.strip("-")') == 1
    reference.write_text(text.replace('.strip("-")', ".strip()"), encoding="utf-8")
    certified, rows = qualify.certify(root / "grade_slug.py", root)
    assert not certified
    assert {r.candidate: r.status for r in rows}["reference"] == "FAIL"


def test_an_empty_candidate_population_refuses(tmp_path: Path) -> None:
    root = tmp_path / "task"
    shutil.copytree(TASK, root, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.rmtree(root / "wrong")
    (root / "wrong").mkdir()
    with pytest.raises(SystemExit):
        qualify.certify(root / "grade_slug.py", root)


def test_held_out_inputs_are_not_published_in_the_goal() -> None:
    goal = (TASK / "goal.md").read_text(encoding="utf-8")
    assert grade_slug.REPORTED_EXAMPLE[0] in goal
    leaked = [text for _, text, _ in grade_slug.HELD_OUT if text and text in goal]
    assert leaked == []


def test_every_held_out_case_varies_a_published_requirement() -> None:
    goal = (TASK / "goal.md").read_text(encoding="utf-8")
    published = set(re.findall(r"\*\*(R\d)\*\*", goal))
    tags = {rule for rule, _, _ in grade_slug.HELD_OUT}
    assert tags == set(grade_slug.RULES)
    assert tags <= published
    assert all(any(r == rule for r, _, _ in grade_slug.HELD_OUT) for rule in grade_slug.RULES)


def test_qualify_main_reports_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualify.main() == 0
    assert "QUALIFY: ok" in capsys.readouterr().out
