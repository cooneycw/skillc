"""`skillc inspect` (issue #725): the round-2 sorter's own negative and purpose
controls, held to the charter in docs/specs/inspect.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from skillc import cli, decay, inspect

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "inspect"
REPO_CONTROLS = Path(__file__).resolve().parent.parent / "controls"


def _cli(case: Path, *extra: str) -> list[str]:
    return [
        "inspect", str(case), "--repo", "example/collection",
        "--issue-states", str(case / "issue-states.json"), *extra,
    ]


def _skill(root: Path, name: str, body: str) -> None:
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: Use when testing.\n---\n{body}", encoding="utf-8")


# ------------------------------------------------- charter: must never

def test_zero_subjects_is_nothing_inspected_never_zero_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance: a collection with zero skills exits non-zero with 'nothing
    inspected', never '0 findings'."""
    (tmp_path / "README.md").write_text("not a skill\n", encoding="utf-8")
    assert cli.main(["inspect", str(tmp_path), "--offline"]) == 2
    captured = capsys.readouterr()
    assert "nothing inspected" in captured.out + captured.err
    assert "0 finding" not in captured.out


def test_planted_collection_stops_on_the_helper_and_sorts_the_marker_into_D(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Acceptance (negative control for inspect): one deleted helper reference
    and one closed `until #N` - inspect STOPS on the first and sorts the second
    into D."""
    assert cli.main(_cli(FIXTURES / "planted", "--json")) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == inspect.STOPPED
    assert [(e["rule"], e["path"]) for e in report["errors"]] == [
        ("dangling-reference", "skills/tidy/SKILL.md"),
    ]
    d = [f for f in report["findings"] if f["bucket"] == inspect.D]
    assert [(f["rule"], f["issue"]) for f in d] == [("expired-marker", "example/collection#7")]


def test_the_same_collection_repaired_inspects_clean(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(_cli(FIXTURES / "repaired", "--json")) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == inspect.CLEAN, report["summary"]
    assert report["errors"] == [] and report["findings"] == [] and report["unknown"] == []


def test_planted_and_repaired_differ_only_in_the_two_planted_defects() -> None:
    """The control is only a control if nothing ELSE differs between its sides."""
    def files(root: Path) -> dict[str, str]:
        return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
                for p in root.rglob("*") if p.is_file()}

    planted, repaired = files(FIXTURES / "planted"), files(FIXTURES / "repaired")
    assert set(repaired) - set(planted) == {"skills/tidy/scripts/cleanup.sh"}
    changed = {k for k in planted if planted[k] != repaired.get(k)}
    assert changed == {"skills/release/SKILL.md"}


def test_inspect_never_writes_into_the_collection(tmp_path: Path) -> None:
    import shutil

    case = tmp_path / "planted"
    shutil.copytree(FIXTURES / "planted", case)
    before = {p: p.read_bytes() for p in case.rglob("*") if p.is_file()}
    cli.main(_cli(case, "--out", str(tmp_path / "out")))
    after = {p: p.read_bytes() for p in case.rglob("*") if p.is_file()}
    assert before == after


def test_C_is_never_assigned_and_the_report_says_why(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(_cli(FIXTURES / "planted", "--json"))
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["by_bucket"][inspect.C] == 0
    assert "owner" in report["bucket_policy"][inspect.C]


def test_a_refused_exposure_report_refuses_the_run(tmp_path: Path) -> None:
    bad = tmp_path / "report.json"
    bad.write_text(json.dumps({"kind": "exposure-report", "status": "refused", "reason": "x"}), encoding="utf-8")
    assert cli.main(_cli(FIXTURES / "repaired", "--exposure", str(bad))) == 2
    bad.write_text("not json", encoding="utf-8")
    assert cli.main(_cli(FIXTURES / "repaired", "--exposure", str(bad))) == 2


# ------------------------------------------------- charter: must always

def test_exposure_not_supplied_is_said(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(_cli(FIXTURES / "repaired"))
    assert "exposure: not supplied - what reaches the model was not measured" in capsys.readouterr().out


def test_a_supplied_exposure_report_folds_in_what_did_not_reach_the_model(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({
        "kind": "exposure-report", "status": "ok", "client": "claude-code",
        "markers": [{"layer": "always_loaded", "verdict": "TRUNCATED", "note": "at 25 KB"}],
        "skills": [{"skill": "tidy", "verdict": "EXPOSED"}, {"skill": "release", "verdict": "HIDDEN", "cause": "policy"}],
    }), encoding="utf-8")
    coll = decay.load_case(FIXTURES / "repaired")
    report = inspect.run(coll, exposure=inspect.load_exposure(report_path))
    exposure_items = [f for f in report.data["findings"] if f["rule"] == "exposure"]
    assert {f["path"] for f in exposure_items} == {"release", "always_loaded"}
    assert all(f["bucket"] == inspect.UNSORTED for f in exposure_items)


def test_every_finding_has_a_bucket_or_UNSORTED_with_a_reason(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(_cli(FIXTURES / "planted", "--json"))
    report = json.loads(capsys.readouterr().out)
    for item in report["findings"] + report["rule_lines"]:
        assert item["bucket"] in inspect.BUCKETS and item["reason"]


def test_the_markdown_and_json_carry_the_same_verdict(tmp_path: Path) -> None:
    out = tmp_path / "out"
    cli.main(_cli(FIXTURES / "planted", "--out", str(out)))
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    md = (out / "report.md").read_text(encoding="utf-8")
    assert f"**Verdict: {data['verdict']}**" in md
    assert "a zero there means NOT ASSIGNED" in md
    assert str(tmp_path) not in json.dumps(data), "the report must not carry a host path"


# ------------------------------------------------- A needs a red case (R1/R2)

def _enforced(tmp_path: Path, rule_line: str) -> list[dict[str, Any]]:
    _skill(tmp_path, "a", f"{rule_line}\n")
    _skill(tmp_path, "b", "unrelated text\n")
    coll = decay.load(tmp_path, offline=True, maps=[("~/.claude/scripts/", "scripts/")])
    rows: list[dict[str, Any]] = inspect.run(coll).data["rule_lines"]
    return rows


def test_A_when_the_named_control_has_a_bad_case(tmp_path: Path) -> None:
    (tmp_path / "controls" / "lanes" / "bad").mkdir(parents=True)
    (tmp_path / "controls" / "lanes" / "bad" / "no-lane-rows.md").write_text("x", encoding="utf-8")
    (tmp_path / "controls" / "lanes" / "check.sh").write_text("x", encoding="utf-8")
    [line] = _enforced(tmp_path, "You MUST answer every lane; `controls/lanes/check.sh` refuses one left out.")
    assert line["bucket"] == inspect.A and line["red_case"] == "controls/lanes/bad"


def test_A_when_the_named_helper_declares_an_existing_negative_control(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "controls" / "guard-bad").mkdir(parents=True)
    (tmp_path / "controls" / "guard-bad" / "case.txt").write_text("x", encoding="utf-8")
    (tmp_path / "scripts" / "guard.sh").write_text("#: NEGATIVE-CONTROL: controls/guard-bad\n", encoding="utf-8")
    [line] = _enforced(tmp_path, "NEVER skip it.\n`~/.claude/scripts/guard.sh` refuses the skip.")
    assert line["bucket"] == inspect.A and line["enforcer"] == "scripts/guard.sh"


def test_an_enforcer_with_no_red_case_is_UNSORTED_not_A(tmp_path: Path) -> None:
    """'A check exists' is not 'a check goes red' (#1830 Part 3)."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_lanes.py").write_text("def test_x(): pass\n", encoding="utf-8")
    [line] = _enforced(tmp_path, "You MUST answer every lane (`tests/test_lanes.py`).")
    assert line["bucket"] == inspect.UNSORTED and "no known-bad case" in line["reason"]


def test_a_helper_whose_declared_negative_control_is_gone_is_not_A(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "guard.sh").write_text("#: NEGATIVE-CONTROL: controls/deleted\n", encoding="utf-8")
    [line] = _enforced(tmp_path, "NEVER skip it - `~/.claude/scripts/guard.sh` refuses the skip.")
    assert line["bucket"] == inspect.UNSORTED


def test_B_only_for_a_named_check_that_does_not_exist(tmp_path: Path) -> None:
    [line] = _enforced(tmp_path, "You MUST answer every lane (`tests/test_missing.py` will catch it).")
    assert line["bucket"] == inspect.B
    [line] = _enforced(tmp_path / "other", "You MUST answer every lane.")
    assert line["bucket"] == inspect.UNSORTED and "recurrence" in line["reason"]


def test_a_rule_line_sorts_on_its_paragraph_not_its_line(tmp_path: Path) -> None:
    (tmp_path / "controls" / "x" / "bad").mkdir(parents=True)
    (tmp_path / "controls" / "x" / "bad" / "case.txt").write_text("x", encoding="utf-8")
    [line] = _enforced(tmp_path, "NEVER skip the gate.\nThe gate is `controls/x/`.\n\n`controls/x/` again, next paragraph.")
    assert line["bucket"] == inspect.A


def test_a_rule_line_does_not_borrow_an_enforcer_from_the_next_paragraph(tmp_path: Path) -> None:
    (tmp_path / "controls" / "x" / "bad").mkdir(parents=True)
    (tmp_path / "controls" / "x" / "bad" / "case.txt").write_text("x", encoding="utf-8")
    [line] = _enforced(tmp_path, "NEVER skip the gate.\n\nThe gate is `controls/x/`.")
    assert line["bucket"] == inspect.UNSORTED


# ------------------------------------------------- pinned-by (R4)

def test_a_D_item_names_the_tests_that_pin_its_document(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "Do it by hand until #3 lands.\n")
    _skill(tmp_path, "b", "other\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_doc.py").write_text('TEXT = open("a/SKILL.md").read()\n', encoding="utf-8")
    (tmp_path / "tests" / "test_other.py").write_text('x = "SKILL.md"\n', encoding="utf-8")
    coll = decay.load(tmp_path, repo="o/r", issue_states={"o/r#3": "CLOSED"})
    [d] = [f for f in inspect.run(coll).data["findings"] if f["bucket"] == inspect.D]
    assert d["pinned_by"] == ["tests/test_doc.py"], "a bare basename must not count as pinning"


# ------------------------------------------------- verdicts and exit codes

def test_findings_without_errors_exit_zero_and_strict_makes_them_fail(tmp_path: Path) -> None:
    words = " ".join(f"w{i}" for i in range(50))
    _skill(tmp_path, "a", words + "\n")
    _skill(tmp_path, "b", words + "\n")
    assert cli.main(["inspect", str(tmp_path), "--offline"]) == 0
    assert cli.main(["inspect", str(tmp_path), "--offline", "--strict"]) == 1


def test_a_single_subject_collection_is_incomplete_not_clean(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "plain\n")
    report = inspect.run(decay.load(tmp_path, offline=True))
    assert report.verdict == inspect.INCOMPLETE and "copied-passage" in report.data["summary"]


# ------------------------------------------------- counter-model review, pass 1

def test_an_empty_bad_directory_is_not_a_red_case(tmp_path: Path) -> None:
    """Review finding 3: a `bad/` with nothing in it has no input to run."""
    (tmp_path / "controls" / "x" / "bad").mkdir(parents=True)
    [line] = _enforced(tmp_path, "NEVER skip it - `controls/x/` refuses the skip.")
    assert line["bucket"] == inspect.UNSORTED


def test_a_B_only_rule_line_is_a_finding_and_fails_strict(tmp_path: Path) -> None:
    """Review finding 5."""
    _skill(tmp_path, "a", "You MUST run `tests/test_missing.py` first.\n")
    _skill(tmp_path, "b", "other\n")
    report = inspect.run(decay.load(tmp_path, offline=True), strict=True)
    assert report.verdict == inspect.FINDINGS and report.exit_code == 1


def test_markdown_shows_unsorted_rule_statements_with_reasons(tmp_path: Path) -> None:
    """Review finding 6."""
    _skill(tmp_path, "a", "You MUST keep the branch current.\n")
    _skill(tmp_path, "b", "other\n")
    md = inspect.render_markdown(inspect.run(decay.load(tmp_path, offline=True)))
    assert "You MUST keep the branch current." in md and "no enforcer named" in md


def test_pinning_does_not_match_a_neighbouring_document() -> None:
    """Review finding 7."""
    tests = {"tests/test_x.py": 'open(".claude/commands/workflow/auto.md")'}
    assert inspect.pinned_by(".claude/commands/flow/auto.md", tests) == []
    tests = {"tests/test_y.py": 'open(".claude/commands/flow/auto.md")'}
    assert inspect.pinned_by(".claude/commands/flow/auto.md", tests) == ["tests/test_y.py"]


# ------------------------------------------------- counter-model review, pass 2

def test_out_inside_the_collection_is_refused(tmp_path: Path) -> None:
    """Pass 2 finding 1: the report must never land on an inspected file."""
    import shutil

    case = tmp_path / "repaired"
    shutil.copytree(FIXTURES / "repaired", case)
    before = {p: p.read_bytes() for p in case.rglob("*") if p.is_file()}
    assert cli.main(_cli(case, "--out", str(case / "skills" / "tidy"))) == 2
    out = tmp_path / "out"
    out.mkdir()
    (out / "report.md").symlink_to(case / "skills" / "tidy" / "SKILL.md")
    assert cli.main(_cli(case, "--out", str(out))) == 2
    assert {p: p.read_bytes() for p in case.rglob("*") if p.is_file()} == before


def test_an_existing_report_is_not_overwritten(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert cli.main(_cli(FIXTURES / "repaired", "--out", str(out))) == 0
    assert cli.main(_cli(FIXTURES / "repaired", "--out", str(out))) == 2


def test_an_exposure_report_with_nothing_measured_is_refused(tmp_path: Path) -> None:
    """Pass 2 finding 4: an empty exposure population is not evidence."""
    empty = tmp_path / "report.json"
    empty.write_text(json.dumps({"kind": "exposure-report", "status": "ok",
                                 "markers": [], "skills": []}), encoding="utf-8")
    assert cli.main(_cli(FIXTURES / "repaired", "--exposure", str(empty))) == 2
    nostatus = tmp_path / "nostatus.json"
    nostatus.write_text(json.dumps({"kind": "exposure-report", "markers": [],
                                    "skills": [{"skill": "x", "verdict": "EXPOSED"}]}), encoding="utf-8")
    assert cli.main(_cli(FIXTURES / "repaired", "--exposure", str(nostatus))) == 2


# ------------------------------------------------- #731 (counter-model pass 3, deferred)

def test_731_a_known_bad_input_is_never_the_enforcer(tmp_path: Path) -> None:
    """#731 item 1, the issue's exact line: a file INSIDE a control's bad/ is an
    input to the check, not the check."""
    import shutil

    shutil.copytree(REPO_CONTROLS / "dangling-reference", tmp_path / "controls" / "dangling-reference")
    [line] = _enforced(tmp_path, "You MUST reject `controls/dangling-reference/bad/dead-link/skills/demo/SKILL.md`")
    assert line["bucket"] == inspect.UNSORTED


def test_731_the_control_root_is_still_an_enforcer(tmp_path: Path) -> None:
    import shutil

    shutil.copytree(REPO_CONTROLS / "dangling-reference", tmp_path / "controls" / "dangling-reference")
    [line] = _enforced(tmp_path, "You MUST resolve every path - `controls/dangling-reference/` refuses one that is gone.")
    assert line["bucket"] == inspect.A and line["red_case"] == "controls/dangling-reference/bad"


def test_731_the_report_summary_says_when_a_copy_count_is_an_estimate(tmp_path: Path) -> None:
    same = " ".join(["same"] * 200)
    _skill(tmp_path, "a", same + "\n")
    _skill(tmp_path, "b", same + "\n")
    report = inspect.run(decay.load(tmp_path, offline=True))
    assert "bounded estimate" in report.data["summary"]
    assert report.data["rules"]["copied-passage"]["population"]["estimated_pairs"] == 1
    assert "bounded estimate" in inspect.render_markdown(report)
