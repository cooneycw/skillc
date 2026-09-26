"""Tests for the Level 1 slug small-fix task and its grader (#5).

`test_the_grader_is_certified` and `test_every_broken_grader_is_refused` are the
two halves of `qualify.py`, wired into the suite so the grader cannot go blind
unnoticed. `test_a_mutated_reference_turns_the_gate_red` is the negative control
for the gate itself: the same gate, one planted defect, and it must refuse.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import shutil
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


def _outcomes(candidate: Path, timeout: float = 10) -> dict[str, str]:
    result = grade_slug.grade(candidate, timeout)
    return {c["id"]: c["outcome"] for c in result["criteria"]}


def _git_blob_id(data: bytes) -> str:
    """The id `git hash-object` gives these bytes, computed without git.

    CI runs in a slim image with no git binary, so shelling out to it failed
    there while passing everywhere git happens to be installed.
    """
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def test_the_blob_id_matches_git() -> None:
    # Known value: `printf 'hello\n' | git hash-object --stdin`.
    assert _git_blob_id(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_the_fixture_is_the_pinned_cpp_blob() -> None:
    data = (TASK / "fixture" / "src" / "slugify.py").read_bytes()
    assert _git_blob_id(data) == PINNED_FIXTURE_BLOB
    assert PINNED_FIXTURE_BLOB in (TASK / "PROVENANCE.md").read_text(encoding="utf-8")


def test_the_grader_is_certified() -> None:
    certified, rows = qualify.certify(TASK / "grade_slug.py")
    assert certified, [r for r in rows if not r.ok]
    by_name = {r.candidate: r.status for r in rows}
    assert by_name["fixture"] == "FAIL"
    assert by_name["reference"] == "PASS"
    assert len(rows) >= 2 + 2 + 6


@pytest.mark.parametrize("control", sorted(qualify.CONTROLS))
def test_every_broken_grader_is_refused_for_the_reason_its_name_gives(control: str) -> None:
    held, reason, _ = qualify.control_verdict(control)
    assert held, reason


def _copy_task(tmp_path: Path) -> Path:
    root = tmp_path / "task"
    shutil.copytree(TASK, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def test_a_missing_control_does_not_count_as_refused(tmp_path: Path) -> None:
    root = _copy_task(tmp_path)
    (root / "grader-controls" / "always_pass.py").unlink()
    held, reason, _ = qualify.control_verdict("always_pass", root)
    assert not held and "does not exist" in reason


def test_a_control_that_misbehaves_does_not_count_as_refused(tmp_path: Path) -> None:
    # A "no output" control that actually crashes is still refused by certify(),
    # so refusal alone cannot tell it from a working control.
    root = _copy_task(tmp_path)
    shutil.copy2(root / "grader-controls" / "always_fail.py",
                 root / "grader-controls" / "no_output.py")
    held, reason, _ = qualify.control_verdict("no_output", root)
    assert not held and "not ('INCONCLUSIVE', 'no-output') throughout" in reason


def test_controls_sharing_a_status_cannot_stand_in_for_each_other(tmp_path: Path) -> None:
    # crash and no_output both yield INCONCLUSIVE; only the category separates them.
    root = _copy_task(tmp_path)
    shutil.copy2(root / "grader-controls" / "crash.py",
                 root / "grader-controls" / "no_output.py")
    held, _, _ = qualify.control_verdict("no_output", root)
    assert not held


def test_a_malformed_criterion_id_is_inconclusive_not_a_crash(tmp_path: Path) -> None:
    grader = tmp_path / "bad_ids.py"
    grader.write_text(
        "import json\nprint(json.dumps({'grader': {'id': 'g', 'revision': '1'},"
        " 'criteria': [{'id': [], 'mandatory': True, 'outcome': 'SATISFIED',"
        " 'evidence': ['x']}]}))\n", encoding="utf-8")
    status, _, _, category = qualify.status_of(grader, TASK / "reference")
    assert (status, category) == ("INCONCLUSIVE", "criteria-set")


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
    certified_status, _, _, _ = qualify.status_of(
        TASK / "grade_slug.py", TASK / "wrong" / "renamed")
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
        outcomes = _outcomes(tmp_path / name, timeout=2)
        assert outcomes["R4-interface"] == "VIOLATED", name


def test_a_mutated_reference_turns_the_gate_red(tmp_path: Path) -> None:
    root = _copy_task(tmp_path)
    reference = root / "reference" / "src" / "slugify.py"
    text = reference.read_text(encoding="utf-8")
    assert text.count('.strip("-")') == 1
    reference.write_text(text.replace('.strip("-")', ".strip()"), encoding="utf-8")
    certified, rows = qualify.certify(root / "grade_slug.py", root)
    assert not certified
    assert {r.candidate: r.status for r in rows}["reference"] == "FAIL"


def test_an_empty_candidate_population_refuses(tmp_path: Path) -> None:
    root = _copy_task(tmp_path)
    shutil.rmtree(root / "wrong")
    (root / "wrong").mkdir()
    with pytest.raises(SystemExit):
        qualify.certify(root / "grade_slug.py", root)


def test_a_deleted_wrong_source_is_not_read_as_discrimination(tmp_path: Path) -> None:
    # Without the source it would FAIL on R4-interface, which looks like a catch.
    root = _copy_task(tmp_path)
    (root / "wrong" / "no-collapse" / "src" / "slugify.py").unlink()
    with pytest.raises(SystemExit, match="no src/slugify.py"):
        qualify.certify(root / "grade_slug.py", root)


def test_a_fail_for_the_wrong_reason_does_not_certify(tmp_path: Path) -> None:
    root = _copy_task(tmp_path)
    (root / "wrong" / "no-collapse" / "expected.json").write_text(
        '{"status": "FAIL", "violated": ["R4-interface"]}', encoding="utf-8")
    certified, rows = qualify.certify(root / "grade_slug.py", root)
    assert not certified
    bad = [r for r in rows if not r.ok]
    assert [(r.candidate, r.status) for r in bad] == [("wrong/no-collapse", "FAIL")]


def test_a_single_defect_violates_only_its_own_rule() -> None:
    for name, rule in [("no-lowercase", "R1"), ("no-collapse", "R2"), ("keeps-spaces", "R2"),
                       ("trailing-only", "R3"), ("example-only", "R3")]:
        outcomes = _outcomes(TASK / "wrong" / name)
        held_out_violations = {r for r in grade_slug.RULES if outcomes[r] == "VIOLATED"}
        assert held_out_violations == {rule}, name


def test_a_third_party_import_violates_the_stdlib_constraint() -> None:
    import pytest as installed  # the dependency is present in this environment
    assert installed
    assert _outcomes(TASK / "wrong" / "third-party")["R4-interface"] == "VIOLATED"


def test_a_rule_with_no_held_out_cases_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    kept = tuple(c for c in grade_slug.HELD_OUT if c[0] != "R1")
    monkeypatch.setattr(grade_slug, "HELD_OUT", kept)
    outcomes = _outcomes(TASK / "reference")
    assert outcomes["R1"] == "UNKNOWN"
    status, _, _, _ = qualify.status_of(TASK / "grade_slug.py", TASK / "reference")
    assert status == "PASS"  # the subprocess grader is unaffected by the patch


def test_a_report_missing_a_required_criterion_is_inconclusive() -> None:
    status, detail, _, _ = qualify.status_of(
        TASK / "grader-controls" / "omits_criterion.py", TASK / "reference")
    assert status == "INCONCLUSIVE" and "missing ['R1', 'R2']" in detail


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
