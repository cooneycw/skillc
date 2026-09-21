"""Tests for the evaluation-record rules.

`test_every_record_rule_discriminates` is the same pairing `skillc selftest`
runs, wired into the suite so a record rule cannot go blind unnoticed - the
counterpart of `test_every_rule_discriminates` for the new family.

The two that matter most are the machinery ones. Record rules were added to the
SAME registry and the SAME selftest loop as the SKILL.md rules, because splitting
"a check with no control is UNPROVEN" across two arms is how one arm later stops
being enforced. `test_an_uncontrolled_record_rule_is_UNPROVEN` and
`test_selftest_reports_a_blinded_record_rule` are what establish that the new arm
is genuinely covered by that guarantee rather than merely adjacent to it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from skillc import checks, cli, records
from skillc.spec import discover

CONTROLS = Path(__file__).resolve().parent.parent / "controls"


def _record(**fields: object) -> records.Record:
    return records.Record(path=Path("in-memory.json"), data=dict(fields))


# --------------------------------------------------------------- the pairing

@pytest.mark.parametrize("rule", checks.RECORD_RULES, ids=lambda r: r.id)
def test_every_record_rule_discriminates(rule: checks.RecordRule) -> None:
    bad_dir, good_dir = CONTROLS / rule.id / "bad", CONTROLS / rule.id / "good"
    assert bad_dir.is_dir() and good_dir.is_dir(), f"{rule.id} ships no committed control"
    bad = [f for r in records.discover(bad_dir) for f in checks.run_record(r, only=rule.id)]
    good = [f for r in records.discover(good_dir) for f in checks.run_record(r, only=rule.id)]
    assert bad, f"{rule.id} is silent on its known-bad input"
    assert not good, f"{rule.id} fired on its known-good input: {good[0].detail}"


@pytest.mark.parametrize("rule", checks.ALL_RULES, ids=lambda r: r.id)
def test_each_bad_case_fires_ITS_OWN_rule_and_NOTHING_ELSE(rule: object) -> None:
    """Every rule in the repository, not only the record family.

    WHAT SELFTEST ALREADY DOES, stated precisely because it is easy to overstate:
    it passes `only=rule.id`, so a neighbour's findings are FILTERED OUT and a
    neighbour firing cannot satisfy the pairing. Attribution is already enforced.

    WHAT IT DOES NOT DO, and what this adds: it never asks whether the bad case
    ALSO trips other rules. A bad case that trips three rules still proves its own,
    but it is not minimal, and a later edit that fixes the incidental defect can
    silently change what the case is testing.

    THE ONE PLACE ATTRIBUTION COULD ACTUALLY FAIL is `checks.run`, which returns a
    `frontmatter` Finding and RETURNS EARLY, before the `only` filter, when a
    SKILL.md does not parse. So a bad case that is merely unparseable would make
    ANY rule report red on its own input without that rule having anything to say.
    No current bad case is unparseable - measured - and this case pins that.
    """
    bad_dir = CONTROLS / rule.id / "bad"
    assert bad_dir.is_dir(), f"{rule.id} ships no bad case"

    if isinstance(rule, checks.RecordRule):
        found = records.discover(bad_dir)
        own = [f for r in found for f in checks.run_record(r, only=rule.id)]
        every = [f for r in found for f in checks.run_record(r)]
    else:
        found = discover(bad_dir)
        own = [f for sk in found for f in checks.run(sk, only=rule.id)]
        every = [f for sk in found for f in checks.run(sk)]

    assert own, f"{rule.id} is silent on its own known-bad input"
    assert not any(f.rule == "frontmatter" for f in own), (
        f"{rule.id}'s bad case does not parse, so the frontmatter early return - not "
        f"the rule - is what makes selftest see red. The rule is unproven."
    )
    fired = sorted({f.rule for f in every})
    assert fired == [rule.id], (
        f"{rule.id}'s bad case also trips {sorted(set(fired) - {rule.id})}; it is not "
        f"minimal, so a later fix to the incidental defect would change what it tests"
    )


# --------------------------------------------------------------- the machinery

def test_an_uncontrolled_record_rule_is_UNPROVEN(monkeypatch: pytest.MonkeyPatch) -> None:
    """The new arm is covered by the coverage guarantee, not merely beside it.

    Record rules were added to the existing registry rather than given their own
    loop. This is what proves that decision held: a record rule with no committed
    control must report UNPROVEN and fail the run, exactly as a SKILL.md rule does.
    """
    uncontrolled = checks.RecordRule(
        "temp-uncontrolled", checks.ERROR, "no control pair", records.derived_status
    )
    monkeypatch.setattr(checks, "RECORD_RULES", checks.RECORD_RULES + (uncontrolled,))
    monkeypatch.setattr(checks, "ALL_RULES", checks.RULES + checks.RECORD_RULES)

    rc = cli.cmd_selftest(argparse.Namespace(controls=str(CONTROLS)))

    assert rc == 1, "a record rule with no committed control did not fail the run"


def test_selftest_reports_a_blinded_record_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """The negative control on the new arm's BLIND detection.

    Note the patch target: `run_record` resolves the checker from `RECORD_RULES`,
    so blinding must patch that rather than `ALL_RULES`, which holds the rule
    OBJECTS the loop iterates.
    """
    blinded = checks.RecordRule(
        "derived-status", checks.ERROR, "blinded", lambda _r: iter(())
    )
    monkeypatch.setattr(
        checks,
        "RECORD_RULES",
        tuple(blinded if r.id == "derived-status" else r for r in checks.RECORD_RULES),
    )

    rc = cli.cmd_selftest(argparse.Namespace(controls=str(CONTROLS)))

    assert rc == 1, "selftest passed a record rule that reports nothing on its known-bad input"


# --------------------------------------------------------------- derivation precedence

def test_a_violation_stays_FAIL_even_when_another_criterion_is_unknown() -> None:
    """interfaces.md: "An established mandatory violation remains FAIL when another
    criterion is unknown." So VIOLATED is tested before UNKNOWN, not after."""
    rec = _record(criteria=[
        {"id": "a", "mandatory": True, "outcome": "VIOLATED"},
        {"id": "b", "mandatory": True, "outcome": "UNKNOWN"},
    ])
    assert records.derive_status(rec) == "FAIL"


def test_missing_mandatory_evidence_prevents_PASS() -> None:
    rec = _record(criteria=[
        {"id": "a", "mandatory": True, "outcome": "SATISFIED"},
        {"id": "b", "mandatory": True, "outcome": "UNKNOWN"},
    ])
    assert records.derive_status(rec) == "INCONCLUSIVE"


def test_optional_criteria_cannot_average_away_a_mandatory_failure() -> None:
    rec = _record(criteria=[
        {"id": "a", "mandatory": True, "outcome": "VIOLATED"},
        {"id": "b", "mandatory": False, "outcome": "SATISFIED"},
        {"id": "c", "mandatory": False, "outcome": "SATISFIED"},
    ])
    assert records.derive_status(rec) == "FAIL"


def test_no_mandatory_criteria_is_INCONCLUSIVE_never_PASS() -> None:
    """An empty population must not render as a clean one (AGENTS.md)."""
    assert records.derive_status(_record(criteria=[])) == "INCONCLUSIVE"
    assert records.derive_status(_record(criteria=[
        {"id": "a", "mandatory": False, "outcome": "SATISFIED"}
    ])) == "INCONCLUSIVE"


@pytest.mark.parametrize("declared", records.DECLARABLE_RUN_STATES)
def test_a_declared_run_state_is_honoured(declared: str) -> None:
    assert records.derive_status(_record(run_state=declared, criteria=[])) == declared


def test_a_derived_status_may_not_be_declared_as_a_run_state() -> None:
    """PASS is DERIVED. Letting a record declare it would reopen the forged verdict
    through the run_state field instead of the status field."""
    rec = _record(run_state="PASS", criteria=[
        {"id": "a", "mandatory": True, "outcome": "VIOLATED"}
    ])
    assert records.derive_status(rec) == "FAIL"


# --------------------------------------------------------------- the forged verdict

def test_a_structurally_perfect_record_with_a_copied_verdict_is_refused() -> None:
    """The reason a schema alone would not be enough.

    Every field is well formed and every value is in its vocabulary. The only
    defect is that the status does not follow from the record's own criteria -
    which is exactly what a subject-authored success flag looks like once it has
    been copied into an evaluator record.
    """
    forged = _record(
        version=1, kind=records.VERIFIED_RESULT, attempt_id="att-1", status="PASS",
        criteria=[{"id": "a", "mandatory": True, "outcome": "VIOLATED"}],
    )
    assert list(records.record_envelope(forged)) == []
    assert list(records.attempt_binding(forged)) == []
    assert list(records.criterion_vocabulary(forged)) == []
    findings = list(records.derived_status(forged))
    assert findings, "a copied verdict passed every structural rule and was not refused"
    assert "does not follow" in findings[0]


# --------------------------------------------------------------- the command

def test_check_records_refuses_a_forged_verdict() -> None:
    rc = cli.cmd_check_records(
        argparse.Namespace(path=str(CONTROLS / "derived-status" / "bad"), rule=None)
    )
    assert rc == 1


def test_check_records_accepts_a_consistent_record() -> None:
    rc = cli.cmd_check_records(
        argparse.Namespace(path=str(CONTROLS / "derived-status" / "good"), rule=None)
    )
    assert rc == 0


def test_check_records_on_an_empty_population_is_not_a_pass(tmp_path: Path) -> None:
    """AGENTS.md: never let an empty population render as a clean one."""
    rc = cli.cmd_check_records(argparse.Namespace(path=str(tmp_path), rule=None))
    assert rc == 2, "a directory with no records reported success"


def test_check_records_on_a_missing_path_is_not_a_pass(tmp_path: Path) -> None:
    rc = cli.cmd_check_records(
        argparse.Namespace(path=str(tmp_path / "nope"), rule=None)
    )
    assert rc == 2


def test_check_records_states_what_it_examined_on_a_PASSING_run(capsys: pytest.CaptureFixture[str]) -> None:
    """The line must appear on the green, which is the run nobody reads carefully."""
    cli.cmd_check_records(
        argparse.Namespace(path=str(CONTROLS / "derived-status" / "good"), rule=None)
    )
    out = capsys.readouterr().out
    assert records.WHAT_WAS_EXAMINED in out, (
        "a passing run did not say what it examined, so the green is quotable as "
        "verification"
    )


# --------------------------------------------------------------- honesty of the green

def test_the_module_states_what_validation_does_not_establish() -> None:
    """The #859 mitigation, pinned.

    A passing validator must not be quotable as verification. This asserts the
    sentence exists rather than trusting that it stays.
    """
    text = records.WHAT_WAS_EXAMINED
    assert "structure" in text, "the sentence does not say what WAS examined"
    assert "nothing here establishes" in text, (
        f"the sentence does not deny establishing truth, so a green could be quoted "
        f"as verification: {text!r}"
    )


def test_an_unreadable_record_is_a_finding_not_a_pass(tmp_path: Path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    rec = records.load(bad)
    assert rec.parse_error is not None
    assert list(records.record_envelope(rec)), "an unreadable record produced no finding"


def test_a_json_document_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "list.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    rec = records.load(bad)
    assert rec.parse_error is not None
