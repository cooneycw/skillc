"""`skillc charter confirm` (#726, round 1, PR A): only the owner's answers
become a charter, and the tool never approves by itself."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from skillc import charter, charter_confirm, cli
from skillc.charter_confirm import ConfirmRefused
from skillc.spec import parse_contract_block

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "evals/subjects/charter-draft"
DAY = dt.date(2026, 11, 15)


def _draft() -> str:
    return charter.draft(FIXTURE / "skills/demo", [FIXTURE / "logs/complete"]).render()


def _ids(text: str) -> list[str]:
    return [str(c.get("id")) for _s, c in charter_confirm._draft_clauses(parse_contract_block(text)[0])]


def _accept_all(text: str) -> str:
    return "\n".join(f"{i}: accept" for i in _ids(text)) + "\n"


def _every_clause(text: str) -> list[tuple[str, dict[str, object]]]:
    return charter_confirm._draft_clauses(parse_contract_block(text)[0])


# ---------------------------------------------------------------- never self-approves


def test_no_answers_file_is_refused(tmp_path: Path) -> None:
    """The committed negative case (orchestrator gate on #726)."""
    with pytest.raises(ConfirmRefused, match="never approves by itself"):
        charter_confirm.confirm(_draft(), None, DAY)
    draft = tmp_path / "draft.md"
    draft.write_text(_draft(), encoding="utf-8")
    out = tmp_path / "CHARTER.md"
    assert cli.main(["charter", "confirm", str(draft), "--out", str(out)]) == cli.CHARTER_EXIT_REFUSED
    assert not out.exists()


def test_accepting_every_clause_stamps_only_intent_and_authority() -> None:
    """The positive half: even an answers file that accepts EVERYTHING puts
    `approved` only on intent and authority clauses, never on any other."""
    confirmed = charter_confirm.confirm(_draft(), _accept_all(_draft()), DAY)
    for section, clause in _every_clause(confirmed):
        if section in charter_confirm.APPROVAL_SECTIONS:
            assert clause.get("approved") == "2026-11-15", section
        else:
            assert "approved" not in clause, (section, clause.get("id"))
        assert "draft" not in clause
    assert any(s == "invariants.always" for s, _c in _every_clause(confirmed))


def test_an_unanswered_clause_is_refused_never_defaulted() -> None:
    answers = "\n".join(f"{i}: accept" for i in _ids(_draft())[:-1])
    with pytest.raises(ConfirmRefused, match="unanswered clause"):
        charter_confirm.confirm(_draft(), answers, DAY)


def test_an_answer_for_a_clause_the_draft_lacks_is_refused() -> None:
    with pytest.raises(ConfirmRefused, match="does not hold: demo.always-99"):
        charter_confirm.confirm(_draft(), _accept_all(_draft()) + "demo.always-99: accept\n", DAY)


@pytest.mark.parametrize(("answers", "reason"), [
    ("demo.intent accept\n", "not '<clause-id>"),
    ("demo.intent: approve\n", "not '<clause-id>"),
    ("demo.intent: edit:\n", "needs the owner's wording"),
    ("demo.intent: drop: why\n", "only 'edit' takes text"),
    ("demo.intent: accept\ndemo.intent: drop\n", "answered twice"),
    ("approved-on: 2026-11-15\napproved-on: 2026-11-16\n", "approved-on given twice"),
])
def test_an_answers_file_it_cannot_read_is_refused(answers: str, reason: str) -> None:
    with pytest.raises(ConfirmRefused, match=reason):
        charter_confirm.parse_answers(answers)


def test_the_intent_cannot_be_dropped_or_forbidden() -> None:
    for action in ("drop", "forbid"):
        answers = _accept_all(_draft()).replace("demo.intent: accept", f"demo.intent: {action}")
        with pytest.raises(ConfirmRefused, match="intent cannot be"):
            charter_confirm.confirm(_draft(), answers, DAY)


# ---------------------------------------------------------------- the owner's answers


def test_edit_drop_and_forbid_do_what_the_owner_said() -> None:
    draft = _draft()
    answers = _accept_all(draft)
    answers = answers.replace("demo.always-1: accept", "demo.always-1: edit: Stop at the gate # and wait")
    answers = answers.replace("demo.always-2: accept", "demo.always-2: drop")
    answers = answers.replace("demo.observed-retry-loop: accept", "demo.observed-retry-loop: forbid")
    confirmed = charter_confirm.confirm(draft, "approved-on: 2026-11-20\n" + answers, DAY)
    clauses = {str(c["id"]): (s, c) for s, c in _every_clause(confirmed)}
    assert clauses["demo.always-1"][1]["what"] == "Stop at the gate # and wait"
    assert "demo.always-2" not in clauses
    section, forbidden = clauses["demo.observed-retry-loop"]
    assert section == "invariants.never" and str(forbidden["what"]).startswith("Never: ")
    assert clauses["demo.intent"][1]["approved"] == "2026-11-20"


def test_a_comment_ends_an_accept_line() -> None:
    answers, _date = charter_confirm.parse_answers("demo.intent: accept  # fine as drafted\n")
    assert answers["demo.intent"].action == "accept"


def test_confirm_never_overwrites(tmp_path: Path) -> None:
    draft, answers, out = tmp_path / "draft.md", tmp_path / "answers.txt", tmp_path / "CHARTER.md"
    draft.write_text(_draft(), encoding="utf-8")
    answers.write_text(_accept_all(_draft()), encoding="utf-8")
    out.write_text("the owner's charter\n", encoding="utf-8")
    assert cli.main(["charter", "confirm", str(draft), "--answers", str(answers), "--out", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "the owner's charter\n"


def test_the_confirmed_charter_says_who_confirmed_it(tmp_path: Path) -> None:
    draft, answers, out = tmp_path / "draft.md", tmp_path / "answers.txt", tmp_path / "CHARTER.md"
    draft.write_text(_draft(), encoding="utf-8")
    answers.write_text(_accept_all(_draft()), encoding="utf-8")
    assert cli.main(["charter", "confirm", str(draft), "--answers", str(answers), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "Confirmed by the owner on" in text and "Draft ready for owner confirmation" not in text


# ---------------------------------------------------------------- counter-model review, pass 1

RICH = """---
contract: rich
version: 1
intent:
  id: rich.intent
  draft: true
  what: Why rich exists.
purpose: Rich delivers.
owner: owner
provides:
  - id: rich.out
    draft: true
    what: the output
    readers: [owner]
authority:
  - id: rich.no-self-approval
    draft: true
    what: never approves itself
  - id: rich.auth-drop
    draft: true
    what: to drop
requires:
  - id: rich.input
    draft: true
    what: the input
invariants:
  always: []
  never: []
---

**Draft ready for owner confirmation.**
"""


def test_every_clause_section_takes_the_owners_answers() -> None:
    """Pass 1 HIGH: only intent and invariants were written back, so an
    authority clause was never approved and drop/forbid on provides did nothing."""
    answers = ("rich.intent: accept\nrich.out: forbid\nrich.no-self-approval: edit: Never approves its own plan.\n"
               "rich.auth-drop: drop\nrich.input: accept\n")
    clauses = {str(c["id"]): (s, c) for s, c in _every_clause(charter_confirm.confirm(RICH, answers, DAY))}
    section, auth = clauses["rich.no-self-approval"]
    assert section == "authority" and auth["approved"] == "2026-11-15" and "draft" not in auth
    assert auth["what"] == "Never approves its own plan."
    assert "rich.auth-drop" not in clauses
    assert clauses["rich.out"][0] == "invariants.never"  # moved, not duplicated
    assert [s for s, c in _every_clause(charter_confirm.confirm(RICH, answers, DAY)) if c["id"] == "rich.out"] == ["invariants.never"]
    section, needed = clauses["rich.input"]
    assert section == "requires" and "approved" not in needed and "draft" not in needed


@pytest.mark.parametrize("date", ["2026-02-30", "2026-99-99"])
def test_an_impossible_approval_date_is_refused(date: str) -> None:
    with pytest.raises(ConfirmRefused, match="not a real date"):
        charter_confirm.parse_answers(f"approved-on: {date}\n")


# ---------------------------------------------------------------- counter-model review, pass 2


def test_a_draft_with_no_addressable_intent_is_refused() -> None:
    """An empty answers file must never confirm a charter with nothing to answer."""
    bare = "---\ncontract: bare\nversion: 1\nintent: A job.\npurpose: p\nowner: owner\n---\n"
    with pytest.raises(ConfirmRefused, match="no intent clause"):
        charter_confirm.confirm(bare, "", DAY)


def test_a_draft_with_duplicate_clause_ids_is_refused() -> None:
    dup = RICH.replace("id: rich.auth-drop", "id: rich.no-self-approval")
    answers = "rich.intent: accept\nrich.out: accept\nrich.no-self-approval: accept\nrich.input: accept\n"
    with pytest.raises(ConfirmRefused, match="fails contract-shape"):
        charter_confirm.confirm(dup, answers, DAY)


def test_an_edit_that_cannot_be_written_exactly_is_refused() -> None:
    answers = _accept_all(_draft()).replace("demo.always-1: accept", "demo.always-1: edit: tab\there")
    with pytest.raises(ConfirmRefused, match="cannot be written exactly"):
        charter_confirm.confirm(_draft(), answers, DAY)


def test_a_confirmed_charter_no_longer_says_nothing_is_approved() -> None:
    text = charter_confirm.confirm(_draft(), _accept_all(_draft()), DAY)
    assert "Nothing here is approved" not in text


def test_the_output_is_created_exclusively(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A charter that appears between the existence check and the write is never truncated."""
    out = tmp_path / "CHARTER.md"
    real_confirm = charter_confirm.confirm

    def racing(*args: object, **kwargs: object) -> str:
        out.write_text("the owner's charter\n", encoding="utf-8")  # appears mid-confirm
        return real_confirm(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(charter_confirm, "confirm", racing)
    draft, answers = tmp_path / "draft.md", tmp_path / "answers.txt"
    draft.write_text(_draft(), encoding="utf-8")
    answers.write_text(_accept_all(_draft()), encoding="utf-8")
    with pytest.raises(ConfirmRefused, match="appeared"):
        charter_confirm.confirm_file(draft, answers, out, DAY)
    assert out.read_text(encoding="utf-8") == "the owner's charter\n"
