"""`skillc charter create` (#778 PR B): the owner's answers become a CHARTER.md
with a trap-task stub per clause, checked by the real contracts rules."""

from __future__ import annotations

import copy
import datetime as _dt
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from skillc import charter_create, cli, contracts
from skillc.charter_create import CreateRefused, create
from skillc.charter_evidence import gather
from skillc.verify import GraderDef, Refused

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "evals" / "subjects" / "charter-create"
TODAY = _dt.date(2026, 11, 15)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURE / "collection", tmp_path / "c")
    shutil.copy(FIXTURE / "evidence.json", tmp_path / "evidence.json")
    return tmp_path


def _answers(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURE / "answers.json").read_text(encoding="utf-8"))
    data.update(copy.deepcopy(changes))
    return data


def _run(work: Path, answers: dict[str, Any], **kw: Any) -> charter_create.Created:
    path = work / "answers.json"
    path.write_text(json.dumps(answers), encoding="utf-8")
    return create(work / "c", "skills/demo", work / "evidence.json", path, today=TODAY, **kw)


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _rules(root: Path) -> dict[str, list[str]]:
    collection = contracts.load_collection(root)
    return {name: [m for _, m in rule(collection)] for name, rule in (
        ("contract-shape", contracts.contract_shape), ("clause-backed", contracts.clause_backed),
        ("negative-backed", contracts.negative_backed), ("approval-present", contracts.approval_present))}


# ---------------------------------------------------------------- the committed fixture is current


def test_the_committed_evidence_is_what_charter_evidence_writes_today(work: Path) -> None:
    fresh = gather(work / "c", "skills/demo", reader=None).to_data()
    assert fresh == json.loads((FIXTURE / "evidence.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the good case


def test_planted_answers_give_a_charter_that_passes_shape_backed_and_negative_backed(work: Path) -> None:
    made = _run(work, _answers())
    assert made.charter == work / "c/skills/demo/CHARTER.md"
    assert made.warnings == []
    assert _rules(work / "c") == {"contract-shape": [], "clause-backed": [], "negative-backed": [],
                                  "approval-present": []}
    assert cli.main(["contracts", str(work / "c")]) == 0


def test_every_safety_clause_gets_a_bad_and_a_good_stub_and_the_charter_points_at_them(work: Path) -> None:
    _run(work, _answers())
    trap = work / "c/evals/trap-tasks/demo"
    assert sorted(p.name for p in trap.iterdir()) == ["cite-every-claim", "never-approve", "owner-merges"]
    for case in ("bad", "good"):
        stub = trap / "never-approve" / case
        assert sorted(_files(stub)) == ["STUB.md", "fixture", "fixture/README.md", "goal.md"]
    bad = (trap / "never-approve/bad/STUB.md").read_text(encoding="utf-8")
    assert "approves the PR to save the reviewer a step" in bad and "WRONG move" in bad
    text = (work / "c/skills/demo/CHARTER.md").read_text(encoding="utf-8")
    assert 'test: "evals/trap-tasks/demo/never-approve/{bad,good}"' in text


def test_a_stub_is_refused_by_the_grader_loader(work: Path) -> None:
    """The stub can never pass as a graded task: round 3 refuses it."""
    _run(work, _answers())
    for case in ("bad", "good"):
        with pytest.raises((Refused, OSError)):
            GraderDef.load(work / "c/evals/trap-tasks/demo/never-approve" / case)


def test_approved_lands_only_on_intent_and_authority(work: Path) -> None:
    _run(work, _answers())
    data, _ = charter_create.parse_contract_block((work / "c/skills/demo/CHARTER.md").read_text(encoding="utf-8"))
    assert data["intent"]["approved"] == "2026-11-15"
    assert data["authority"][0]["approved"] == "2026-11-15"
    invariants = data["invariants"]
    assert all("approved" not in c for c in invariants["always"] + invariants["never"])


def test_the_skill_under_review_is_unchanged(work: Path) -> None:
    skill = work / "c/skills/demo/SKILL.md"
    before = charter_create.skill_tree_digest(skill, command=False)
    raw = skill.read_bytes()
    _run(work, _answers())
    assert charter_create.skill_tree_digest(skill, command=False) == before
    assert skill.read_bytes() == raw


def test_the_digest_sees_a_change_to_the_skill() -> None:
    """The control for the digest itself: an edit to SKILL.md changes it, and
    CHARTER.md does not."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        skill = Path(d) / "SKILL.md"
        skill.write_text("a\n", encoding="utf-8")
        before = charter_create.skill_tree_digest(skill, command=False)
        (Path(d) / "CHARTER.md").write_text("x\n", encoding="utf-8")
        assert charter_create.skill_tree_digest(skill, command=False) == before
        skill.write_text("b\n", encoding="utf-8")
        assert charter_create.skill_tree_digest(skill, command=False) != before


def test_an_owner_who_withholds_approval_gets_warnings_only_for_what_they_withheld(work: Path) -> None:
    answers = _answers(approved_on=None)
    answers["intent"]["approve"] = False
    answers["clauses"][2]["approve"] = False
    made = _run(work, answers)
    assert len(made.warnings) == 2 and all("approval-present" in w for w in made.warnings)
    assert _rules(work / "c")["clause-backed"] == [] and _rules(work / "c")["negative-backed"] == []


def test_a_clause_naming_an_existing_test_uses_it_and_a_safety_clause_still_gets_its_stub(work: Path) -> None:
    (work / "c/tests").mkdir()
    (work / "c/tests/test_demo.py").write_text("def test_x(): pass\n", encoding="utf-8")
    answers = _answers()
    answers["clauses"][0]["test"] = "tests/test_demo.py"
    answers["clauses"][1]["test"] = "tests/test_demo.py"
    made = _run(work, answers)
    data, _ = charter_create.parse_contract_block(made.charter.read_text(encoding="utf-8"))
    assert data["invariants"]["always"][0]["test"] == "tests/test_demo.py"
    assert data["invariants"]["never"][0]["test"] == ["tests/test_demo.py", "evals/trap-tasks/demo/never-approve/{bad,good}"]
    assert not (work / "c/evals/trap-tasks/demo/cite-every-claim").exists()


# ---------------------------------------------------------------- refusals: nothing written


def _refused(work: Path, answers: dict[str, Any], match: str, **kw: Any) -> None:
    before = _files(work / "c")
    with pytest.raises(CreateRefused, match=match):
        _run(work, answers, **kw)
    assert _files(work / "c") == before


def test_an_unanswered_suggestion_is_refused(work: Path) -> None:
    answers = _answers()
    del answers["answers"]["e3"]
    _refused(work, answers, "unanswered suggestion")


def test_an_accepted_suggestion_no_clause_uses_is_refused(work: Path) -> None:
    answers = _answers()
    answers["clauses"][0]["from"] = []
    _refused(work, answers, "no clause uses: e2")


def test_a_dropped_suggestion_a_clause_uses_is_refused(work: Path) -> None:
    answers = _answers()
    answers["answers"]["e2"] = "drop"
    _refused(work, answers, "e2 was dropped")


def test_a_must_never_without_a_shortcut_is_refused(work: Path) -> None:
    answers = _answers()
    del answers["clauses"][1]["shortcut"]
    _refused(work, answers, "never 'never-approve'.*names no shortcut")


def test_an_authority_clause_without_a_shortcut_is_refused(work: Path) -> None:
    answers = _answers()
    answers["clauses"][2]["shortcut"] = "  "
    _refused(work, answers, "authority 'owner-merges'.*names no shortcut")


def test_no_approval_without_an_approve_answer_and_a_date(work: Path) -> None:
    _refused(work, _answers(approved_on=None), "approval needs approved_on")
    answers = _answers()
    answers["clauses"][0]["approve"] = True
    _refused(work, answers, "only intent and authority")
    _refused(work, _answers(approved_on="2026-02-30"), "not a real date")
    _refused(work, _answers(approved_on="2026-11-16"), "in the future")


def test_a_clause_without_text_or_with_a_repeated_id_is_refused(work: Path) -> None:
    answers = _answers()
    answers["clauses"][0]["what"] = ""
    _refused(work, answers, "clause 1: needs the owner's text")
    answers = _answers()
    answers["clauses"][1]["id"] = "cite-every-claim"
    _refused(work, answers, "used twice")


def test_evidence_for_another_skill_is_refused(work: Path) -> None:
    data = json.loads((work / "evidence.json").read_text(encoding="utf-8"))
    data["skill"] = "skills/other"
    (work / "evidence.json").write_text(json.dumps(data), encoding="utf-8")
    _refused(work, _answers(), "the evidence is for 'skills/other'")


def test_nothing_is_overwritten(work: Path) -> None:
    _run(work, _answers())
    _refused(work, _answers(), "never overwrites a charter")
    (work / "c/skills/demo/CHARTER.md").unlink()
    _refused(work, _answers(), "never overwrites a trap task")


def test_a_draft_charter_is_replaced_only_with_replace_draft(work: Path) -> None:
    draft = work / "c/skills/demo/CHARTER.md"
    draft.write_text('---\ncontract: "demo"\nversion: 1\nintent:\n  id: "demo.intent"\n  draft: true\n  what: "x"\n'
                     'purpose: "p"\nowner: "owner"\n---\n', encoding="utf-8")
    _refused(work, _answers(), "never overwrites a charter")
    _run(work, _answers(), replace_draft=True)
    assert "draft: true" not in draft.read_text(encoding="utf-8")


def test_a_failing_final_check_rolls_everything_back(work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The final contracts check is the gate that lets the charter through: an
    error from it must keep nothing."""
    real = charter_create._findings

    def failing(root: Path, path: Path):  # type: ignore[no-untyped-def]
        yield from real(root, path)
        yield "clause-backed", "planted failure"

    monkeypatch.setattr(charter_create, "_findings", failing)
    _refused(work, _answers(), "not clean.*planted failure")
    assert not (work / "c/evals").exists()


def test_an_approval_warning_on_a_clause_the_owner_approved_rolls_back(work: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    def warn(root: Path, path: Path):  # type: ignore[no-untyped-def]
        yield "approval-present", "authority clause 'demo.owner-merges' has no owner 'approved' date; it is a draft"

    monkeypatch.setattr(charter_create, "_findings", warn)
    _refused(work, _answers(), "approval-present")


# ---------------------------------------------------------------- the CLI


def test_the_cli_reports_the_charter_the_stubs_and_that_nothing_was_committed(
        work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (work / "answers.json").write_text(json.dumps(_answers(approved_on=TODAY.isoformat())), encoding="utf-8")
    code = cli.main(["charter", "create", str(work / "c"), "skills/demo", "--evidence", str(work / "evidence.json"),
                     "--answers", str(work / "answers.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "nothing was committed" in out and out.count("trap-task stub") == 3


def test_the_cli_refusal_exits_1_and_writes_nothing(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    answers = _answers()
    del answers["answers"]["e1"]
    (work / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    before = _files(work / "c")
    code = cli.main(["charter", "create", str(work / "c"), "skills/demo", "--evidence", str(work / "evidence.json"),
                     "--answers", str(work / "answers.json")])
    assert code == 1 and "unanswered suggestion" in capsys.readouterr().err
    assert _files(work / "c") == before
