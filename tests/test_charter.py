"""`skillc charter draft` (#726, round 1, PR A): a draft charter from evidence."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from skillc import charter, checks, cli, contracts, cost_estimate
from skillc.spec import parse_contract_block

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "evals/subjects/charter-draft"
SKILL = FIXTURE / "skills/demo"
LOGS = FIXTURE / "logs"

LANE_DUTY = "ALWAYS report every lane the project lists."


def _columns(drafted: charter.Draft) -> dict[str, str]:
    return {p.text: p.column for p in drafted.placed}


def _draft(case: str | None) -> charter.Draft:
    return charter.draft(SKILL, [LOGS / case] if case else [])


# ---------------------------------------------------------------- the three columns


def test_a_complete_log_sorts_every_column() -> None:
    """Acceptance 2: stated and observed; stated and never observed; observed
    and never stated."""
    cols = _columns(_draft("complete"))
    assert cols["You MUST stop at the approval gate before editing anything."] == charter.OBSERVED_AND_STATED
    assert cols[LANE_DUTY] == charter.STATED_NOT_OBSERVED
    assert cols["observed, never stated: runs end with stop_reason retry-loop"] == charter.OBSERVED_NOT_STATED


@pytest.mark.parametrize("case", [None, "empty", "unreadable", "partial", "unsupported"])
def test_each_unknown_trigger_puts_the_unseen_duty_at_unknown(case: str | None) -> None:
    """Orchestrator gate on #726: one control per trigger (no log, an empty
    log, an unreadable log, only partial or only unsupported coverage). None of
    them could have shown the duty, so none may call it 'never observed'."""
    drafted = _draft(case)
    assert _columns(drafted)[LANE_DUTY] == charter.UNKNOWN_COLUMN
    assert charter.STATED_NOT_OBSERVED not in _columns(drafted).values()


def test_one_complete_record_without_the_token_flips_it_to_never_observed() -> None:
    """The flip case: the same duty, once a complete-coverage record exists."""
    assert _columns(_draft("flip"))[LANE_DUTY] == charter.STATED_NOT_OBSERVED


def test_a_partial_observation_still_counts_as_seen() -> None:
    """Coverage limits what an ABSENCE means, never what a presence means."""
    cols = _columns(_draft("partial"))
    assert cols["You MUST stop at the approval gate before editing anything."] == charter.OBSERVED_AND_STATED
    assert cols[LANE_DUTY] == charter.UNKNOWN_COLUMN


def test_a_record_for_another_skill_is_not_evidence(tmp_path: Path) -> None:
    log = tmp_path / "usage.jsonl"
    log.write_text((LOGS / "flip/usage.jsonl").read_text(encoding="utf-8").replace('"demo"', '"other"'), encoding="utf-8")
    assert _columns(charter.draft(SKILL, [log]))[LANE_DUTY] == charter.UNKNOWN_COLUMN


def test_the_token_matcher_needs_every_token_word() -> None:
    line = charter.Candidate("always", "Stop at the approval gate.", "x:1", False)
    assert charter.TokenMatcher().matches(line, charter.Observation("approval-gate", 1))
    assert not charter.TokenMatcher().matches(line, charter.Observation("approval-ledger", 1))


# ---------------------------------------------------------------- nothing to draft from


def test_no_source_at_all_is_nothing_to_draft_from(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare/SKILL.md").write_text("---\nname: bare\n---\n\n# Bare\n", encoding="utf-8")
    with pytest.raises(charter.NothingToDraft, match="nothing to draft from"):
        charter.draft(tmp_path / "bare")
    assert cli.main(["charter", "draft", str(tmp_path / "bare")]) == cli.CHARTER_EXIT_NOTHING == 3
    captured = capsys.readouterr()
    assert captured.out == ""  # never an empty charter
    assert "nothing to draft from" in captured.err


def test_a_missing_skill_is_a_usage_error(tmp_path: Path) -> None:
    assert cli.main(["charter", "draft", str(tmp_path / "absent")]) == cli.CHARTER_EXIT_USAGE


def test_draft_never_overwrites(tmp_path: Path) -> None:
    out = tmp_path / "CHARTER.md"
    out.write_text("the owner's charter\n", encoding="utf-8")
    assert cli.main(["charter", "draft", str(SKILL), "--out", str(out)]) == cli.CHARTER_EXIT_USAGE
    assert out.read_text(encoding="utf-8") == "the owner's charter\n"


# ---------------------------------------------------------------- the draft is #720's format


def _as_collection(tmp_path: Path, drafted: charter.Draft) -> contracts.Collection:
    shutil.copytree(SKILL, tmp_path / "skills/demo")
    (tmp_path / "skills/demo/CHARTER.md").write_text(drafted.render(), encoding="utf-8")
    return contracts.load_collection(tmp_path)


def test_a_draft_passes_contract_shape_warns_approval_and_fails_clause_backed(tmp_path: Path) -> None:
    """Acceptance 4, and the orchestrator's: a draft fails clause-backed by
    design (no clause has a test until round 3). Asserted, so it is never
    mistaken for a regression."""
    found = checks.run_contracts(_as_collection(tmp_path, _draft("complete")))
    rules = {f.rule for f in found}
    assert "contract-shape" not in rules
    assert {f.rule for f in found if f.severity == checks.WARN} == {"approval-present"}
    assert any(f.rule == "clause-backed" and f.severity == checks.ERROR for f in found)


def test_no_draft_clause_carries_an_approved_date() -> None:
    data, _body = parse_contract_block(_draft("complete").render())
    intent = data["intent"]
    assert isinstance(intent, dict) and "approved" not in intent and intent["draft"] is True
    invariants = data["invariants"]
    assert isinstance(invariants, dict)
    for clauses in invariants.values():
        for clause in clauses:
            assert "approved" not in clause and clause["draft"] is True


def test_the_draft_says_it_awaits_the_owner() -> None:
    assert "**Draft ready for owner confirmation.**" in _draft("complete").render()


def test_a_command_draft_carries_its_subject_and_passes_shape(tmp_path: Path) -> None:
    """Owner decision 2026-11-15: a slash command's charter lives under
    charters/ and names its command file."""
    shutil.copytree(ROOT / "controls/contract-shape/good/subject-command", tmp_path / "c")
    command = tmp_path / "c/.claude/commands/flow/auto.md"
    command.write_text(command.read_text(encoding="utf-8") + "\nYou MUST open one PR per issue.\n", encoding="utf-8")
    drafted = charter.draft(command, subject=".claude/commands/flow/auto.md")
    assert drafted.name == "flow-auto"
    shutil.rmtree(tmp_path / "c/charters")
    target = tmp_path / "c/charters/flow/auto/CHARTER.md"
    target.parent.mkdir(parents=True)
    target.write_text(drafted.render(), encoding="utf-8")
    found = checks.run_contracts(contracts.load_collection(tmp_path / "c"))
    assert "contract-shape" not in {f.rule for f in found}


def test_a_command_is_matched_by_its_invocation_name() -> None:
    names = charter.skill_names(Path("x/.claude/commands/flow/eli5.md"), {}, [])
    assert names == {"flow-eli5", "flow:eli5"}


# ---------------------------------------------------------------- the emitter


@pytest.mark.parametrize("value", [
    'say "hi" # not a comment',
    "a: b [c, d] {e} & * ! % @ `f`",
    "back\\slash",
    "café — dash",
])
def test_the_emitter_round_trips_through_the_contract_parser(value: str) -> None:
    data = {"contract": "x", "k": value, "l": [value, 3], "m": [{"id": "a", "what": value, "flag": True}]}
    assert parse_contract_block("---\n" + charter.dump(data) + "---\n")[0] == data


def test_the_emitter_refuses_what_it_cannot_emit() -> None:
    with pytest.raises(TypeError):
        charter.dump({"k": 1.5})


def test_quotes_stay_short() -> None:
    long = " ".join(["word"] * 90) + " MUST hold."
    (candidate,) = charter.stated_duties(long, "x.md")
    assert len(candidate.text.split()) <= charter.MAX_QUOTE_WORDS + 1  # + the "..." marker


def test_fenced_code_and_html_comments_state_no_duty() -> None:
    text = "```\nYou MUST run this.\n```\n<!-- NEVER\nread this -->\nPlain text.\n"
    assert charter.stated_duties(text, "x.md") == []


# ---------------------------------------------------------------- sizing


def test_round_one_model_runs_are_sized_not_run() -> None:
    sizing = cost_estimate.size_round1(34)
    assert sizing.label == "sized, not run"
    assert sizing.calls == 6 + 102 + 6
    with pytest.raises(ValueError):
        cost_estimate.size_round1(0)


# ---------------------------------------------------------------- counter-model review, pass 1


def test_an_observation_of_an_undrafted_duty_is_not_called_unstated(tmp_path: Path) -> None:
    """Five ALWAYS duties, the cap is four, and the record matches the fifth:
    it is stated, so it must not appear as observed-not-stated."""
    skill = tmp_path / "five"
    skill.mkdir()
    duties = "\n".join(f"ALWAYS do duty {w}." for w in ("alpha", "beta", "gamma", "delta", "retry loop"))
    (skill / "SKILL.md").write_text(f"---\nname: demo\ndescription: d\n---\n\n{duties}\n", encoding="utf-8")
    drafted = charter.draft(skill, [LOGS / "complete"])
    assert "observed, never stated: runs end with stop_reason retry-loop" not in _columns(drafted)
    assert "(observed: stop_reason retry-loop)" in drafted.render()


def test_a_match_beyond_the_quote_cut_still_counts(tmp_path: Path) -> None:
    skill = tmp_path / "long"
    skill.mkdir()
    sentence = "You MUST " + " ".join(["wait"] * 45) + " at the approval gate."
    (skill / "SKILL.md").write_text(f"---\nname: demo\ndescription: d\n---\n\n{sentence}\n", encoding="utf-8")
    cols = charter.draft(skill, [LOGS / "complete"]).placed
    assert [p.column for p in cols if p.kind == "always" and "wait" in p.text] == [charter.OBSERVED_AND_STATED]


def test_a_record_the_usage_rules_refuse_grants_no_coverage(tmp_path: Path) -> None:
    log = tmp_path / "usage.jsonl"
    log.write_text('{"kind": "skill-usage", "version": true, "skill": "demo", "coverage": "complete"}\n', encoding="utf-8")
    drafted = charter.draft(SKILL, [log])
    assert _columns(drafted)[LANE_DUTY] == charter.UNKNOWN_COLUMN
    assert drafted.evidence.rejected == 1 and drafted.evidence.records == 0
    assert any("fail #719's usage rules" in w for w in drafted.warnings)


def test_a_quote_never_trips_the_copied_passage_detector(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The gate: quotes under 40 words. Run the REAL detector over a long
    source sentence and the draft that quotes it."""
    import json

    words = " ".join(f"w{i}" for i in range(80))
    (tmp_path / "skills/src").mkdir(parents=True)
    (tmp_path / "skills/src/SKILL.md").write_text(f"---\nname: src\ndescription: d\n---\n\nYou MUST {words}.\n", encoding="utf-8")
    drafted = charter.draft(tmp_path / "skills/src")
    (tmp_path / "skills/draft").mkdir()
    (tmp_path / "skills/draft/SKILL.md").write_text(drafted.render(), encoding="utf-8")
    capsys.readouterr()
    cli.main(["inspect", str(tmp_path), "--offline", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert '"rule": "copied-passage"' not in json.dumps(report.get("findings", report))
    longest = max(len(p.text.replace(" ...", "").split()) for p in drafted.placed)
    assert longest <= charter.MAX_QUOTE_WORDS < 40
