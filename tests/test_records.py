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
import shutil
from pathlib import Path

import pytest

from skillc import checks, cli, records
from skillc.spec import DEFAULT_TARGET, discover

CONTROLS = Path(__file__).resolve().parent.parent / "controls"


def _record(**fields: object) -> records.Record:
    return records.Record(path=Path("in-memory.json"), data=dict(fields))


def _control(path: str) -> dict[str, object]:
    data = json.loads((CONTROLS / path).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


#: The committed known-good records, so a test starts from what the controls prove.
GOOD_RESULT = _control("result-evidence/good/record.json")
GOOD_RECEIPT = _control("installation-receipt/good/receipt.json")
GOOD_LEDGER = _control("trial-ledger/good/ledger.json")
GOOD_MANIFEST = _control("artifact-digest/good/record.json")


# --------------------------------------------------------------- the pairing

def _findings(rule: checks.RecordRule | checks.BundleRule, where: Path) -> list[checks.Finding]:
    if isinstance(rule, checks.BundleRule):
        return [f for b in records.discover_bundles(where) for f in checks.run_bundle(b, only=rule.id)]
    return [f for r in records.discover(where) for f in checks.run_record(r, only=rule.id)]


@pytest.mark.parametrize("rule", checks.RECORD_RULES + checks.BUNDLE_RULES, ids=lambda r: r.id)
def test_every_record_rule_discriminates(rule: checks.RecordRule | checks.BundleRule) -> None:
    bad_dir, good_dir = CONTROLS / rule.id / "bad", CONTROLS / rule.id / "good"
    assert bad_dir.is_dir() and good_dir.is_dir(), f"{rule.id} ships no committed control"
    bad, good = _findings(rule, bad_dir), _findings(rule, good_dir)
    assert bad, f"{rule.id} is silent on its known-bad input"
    assert not good, f"{rule.id} fired on its known-good input: {good[0].detail}"


@pytest.mark.parametrize("rule", checks.BUNDLE_RULES, ids=lambda r: r.id)
def test_EVERY_bundle_bad_case_fires_its_rule(rule: checks.BundleRule) -> None:
    """Per case, not in aggregate: one red bundle must not carry a silent sibling.

    Selftest already refuses a silent case (BLIND counts per subject); this pins
    that every bad directory under a bundle rule really is a bundle, so a case
    whose ledger was deleted cannot drop out of the population unnoticed.
    """
    cases = sorted(p for p in (CONTROLS / rule.id / "bad").iterdir() if p.is_dir())
    bundles = records.discover_bundles(CONTROLS / rule.id / "bad")
    assert len(bundles) == len(cases), "a bad case is not a bundle, so it tests nothing"
    for bundle in bundles:
        assert checks.run_bundle(bundle, only=rule.id), f"{rule.id} silent on {bundle.path.name}"


@pytest.mark.parametrize("rule", checks.ALL_RULES, ids=lambda r: r.id)
def test_each_bad_case_fires_ITS_OWN_rule_and_NOTHING_ELSE(
    rule: checks.Rule | checks.RecordRule | checks.BundleRule,
) -> None:
    """Every rule in the repository, not only the record family.

    WHAT SELFTEST ALREADY DOES, stated precisely because it is easy to overstate:
    it passes `only=rule.id`, so a neighbour's findings are FILTERED OUT and a
    neighbour firing cannot satisfy the pairing. Attribution is already enforced.

    WHAT IT DOES NOT DO, and what this adds: it never asks whether the bad case
    ALSO trips other rules. A bad case that trips three rules still proves its own,
    but it is not minimal, and a later edit that fixes the incidental defect can
    silently change what the case is testing.

    THE ONE PLACE ATTRIBUTION COULD FAIL is `checks.run`, which answers a SKILL.md
    that does not parse with the `frontmatter` finding alone, whichever rule was
    selected. Before #2, selftest counted any finding, so an unparseable bad case
    made ANY rule red on its own input: with `name-spec` blinded and its bad case
    replaced by a file carrying no frontmatter, selftest printed `ok name-spec` and
    `11/11 rule(s) discriminate` - a green over a rule that contributed nothing.
    Selftest now refuses that itself (UNPARSED) and credits only findings whose
    `rule` is the rule under test; this case keeps the SHIPPED controls minimal.

    WHY THIS GUARDS THE PAIRING INSTEAD OF REORDERING `run`, because someone will
    otherwise "simplify" it by moving the filter above the early return: that early
    `frontmatter` finding is CORRECT for `run`'s other caller. `skillc check`
    genuinely wants to hear that a file will not parse, and wants to hear it before
    any rule opinion. Narrowing `run`'s contract to fix one caller's misuse would
    change behaviour for a caller that wants exactly what it currently gets.
    Guarding the misuse keeps the blast radius at this one call site.

    No semantic rule's bad case is unparseable, and this case keeps that true. The
    parser rules (`frontmatter`, `record-envelope`) are exempt by declaration.
    """
    bad_dir = CONTROLS / rule.id / "bad"
    assert bad_dir.is_dir(), f"{rule.id} ships no bad case"

    if isinstance(rule, checks.BundleRule):
        # A bundle case must be clean under every RECORD rule too: a bad bundle
        # whose receipt is also malformed tests two things at once.
        bundles = records.discover_bundles(bad_dir)
        own = [f for b in bundles for f in checks.run_bundle(b, only=rule.id)]
        every = [f for b in bundles for f in checks.run_bundle(b)]
        every += [f for r in records.discover(bad_dir) for f in checks.run_record(r)]
    elif isinstance(rule, checks.RecordRule):
        recs = records.discover(bad_dir)
        own = [f for r in recs for f in checks.run_record(r, only=rule.id)]
        every = [f for r in recs for f in checks.run_record(r)]
    else:
        skills = discover(bad_dir)
        own = [f for sk in skills for f in checks.run(sk, only=rule.id)]
        # Under the rule's OWN target: a field rule for one client is minimal when
        # it is the only thing that fires for that client, not for every client.
        target = rule.target or DEFAULT_TARGET
        every = [f for sk in skills for f in checks.run(sk, target=target)]

    assert own, f"{rule.id} is silent on its own known-bad input"
    # A parser rule is proven BY input that does not parse; that is its explicit
    # expectation, and selftest checks it (UNPARSED). Every other rule must not be.
    assert rule.parser or not any(f.rule == "frontmatter" for f in own), (
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
    forged = _record(**{**GOOD_RESULT, "status": "PASS", "criteria": [
        {"id": "a", "mandatory": True, "outcome": "VIOLATED", "evidence": ["log:a"]}]})
    for structural in (records.record_envelope, records.producer_authority,
                       records.attempt_binding, records.criterion_vocabulary,
                       records.result_evidence):
        assert list(structural(forged)) == [], structural.__name__
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


# --------------------------------------------------------------- bundle machinery

def test_an_uncontrolled_bundle_rule_is_UNPROVEN(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bundle arm is covered by the same coverage guarantee, not beside it."""
    uncontrolled = checks.BundleRule(
        "temp-uncontrolled-bundle", checks.ERROR, "no control pair", records.lineage
    )
    monkeypatch.setattr(checks, "BUNDLE_RULES", checks.BUNDLE_RULES + (uncontrolled,))
    monkeypatch.setattr(
        checks, "ALL_RULES", checks.RULES + checks.RECORD_RULES + checks.BUNDLE_RULES
    )

    rc = cli.cmd_selftest(argparse.Namespace(controls=str(CONTROLS)))

    assert rc == 1, "a bundle rule with no committed control did not fail the run"


def test_selftest_reports_a_blinded_bundle_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    blinded = checks.BundleRule("lineage", checks.ERROR, "blinded", lambda _b: iter(()))
    monkeypatch.setattr(
        checks,
        "BUNDLE_RULES",
        tuple(blinded if r.id == "lineage" else r for r in checks.BUNDLE_RULES),
    )

    rc = cli.cmd_selftest(argparse.Namespace(controls=str(CONTROLS)))

    assert rc == 1, "selftest passed a bundle rule that reports nothing on its known-bad input"


def _write_bundle(where: Path, *docs: dict[str, object]) -> records.Bundle:
    where.mkdir(parents=True, exist_ok=True)
    for index, doc in enumerate(docs):
        (where / f"r{index}.json").write_text(json.dumps(doc), encoding="utf-8")
    [bundle] = records.discover_bundles(where)
    return bundle


def test_a_bundle_with_two_ledgers_is_refused(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_LEDGER, GOOD_RECEIPT)
    assert any("2 trial ledgers" in d for d in records.ledger_binding(bundle))


def test_a_retry_may_not_link_to_another_trials_attempt(tmp_path: Path) -> None:
    trial = dict(GOOD_LEDGER["trials"][0])  # type: ignore[index]
    other = {**trial, "trial_id": "t-2", "attempts": [{"attempt_id": "att-2", "retry_of": "att-1"}]}
    ledger = {**GOOD_LEDGER, "trials": [trial, other]}
    bundle = _write_bundle(tmp_path, ledger)
    assert any("does not plan" in d for d in records.lineage(bundle))


def test_a_regrade_of_another_attempts_result_is_refused(tmp_path: Path) -> None:
    regrade = {**GOOD_RESULT, "result_id": "res-2", "regrade_of": "res-1", "attempt_id": "att-2"}
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_RESULT, regrade)
    assert any("its original graded" in d for d in records.lineage(bundle))


def test_a_regrade_may_carry_a_new_grader_revision_but_not_a_new_grader(tmp_path: Path) -> None:
    """protocol.md: regrading uses a "new grader revision"; a different grader is
    not a regrade of this trial at all."""
    revised = {**GOOD_RESULT, "result_id": "res-2", "regrade_of": "res-1",
               "grader": {"id": "slug-grader", "revision": "g9"}}
    ok = _write_bundle(tmp_path / "ok", GOOD_LEDGER, GOOD_RECEIPT, GOOD_MANIFEST, GOOD_RESULT, revised)
    assert list(records.ledger_binding(ok)) == []
    swapped = {**revised, "grader": {"id": "other", "revision": "g9"}}
    bad = _write_bundle(tmp_path / "bad", GOOD_LEDGER, GOOD_RECEIPT, GOOD_MANIFEST, GOOD_RESULT, swapped)
    assert list(records.ledger_binding(bad))


def test_a_directory_without_a_ledger_is_not_a_bundle(tmp_path: Path) -> None:
    (tmp_path / "r.json").write_text(json.dumps(GOOD_RESULT), encoding="utf-8")
    assert records.discover_bundles(tmp_path) == []


# --------------------------------------------------------------- version handling

@pytest.mark.parametrize("version", [True, 0, -1, 1, 3, "2", 2.0])
def test_only_a_supported_integer_version_is_read(version: object) -> None:
    """An exact set, not a ceiling. `true` is an int to Python and read as 1 before
    this; 0 and negatives were accepted because only NEWER versions were refused."""
    assert list(records.record_envelope(_record(**{**GOOD_RESULT, "version": version})))


def test_the_supported_version_is_read() -> None:
    assert list(records.record_envelope(_record(**GOOD_RESULT))) == []


def test_a_v1_record_is_refused_with_its_reason() -> None:
    [finding] = list(records.record_envelope(_record(**{**GOOD_RESULT, "version": 1})))
    assert "predates producer authority" in finding


# --------------------------------------------------------------- identifiers

@pytest.mark.parametrize(
    "attempt_id", ["", " ", "att 1", "../att-1", "att/1", "-att", "a" * 129, 7, "att-1\n"]
)
def test_a_malformed_attempt_id_is_refused(attempt_id: object) -> None:
    rec = _record(**{**GOOD_RESULT, "attempt_id": attempt_id})
    assert list(records.attempt_binding(rec)), f"accepted attempt_id {attempt_id!r}"


def test_the_ledger_is_not_itself_bound_to_an_attempt() -> None:
    """It ISSUES attempt IDs; demanding one of it would be a category error."""
    assert list(records.attempt_binding(_record(**GOOD_LEDGER))) == []


# --------------------------------------------------------------- established failures

def test_an_established_violation_stays_FAIL_in_a_bundle_with_unknowns(tmp_path: Path) -> None:
    """The mandatory-failure precedence survives the new evidence rules: a result
    with a VIOLATED and an UNKNOWN criterion is a consistent FAIL, not refused."""
    result = {**GOOD_RESULT, "status": "FAIL", "criteria": [
        {"id": "a", "mandatory": True, "outcome": "VIOLATED", "evidence": ["log:a"]},
        {"id": "b", "mandatory": True, "outcome": "UNKNOWN", "missing": "trace lost"},
    ]}
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_RECEIPT, GOOD_MANIFEST, result)
    assert checks.run_bundle(bundle) == []
    assert [f for r in bundle.records for f in checks.run_record(r)] == []


# --------------------------------------------------------------- the command, bundles

def test_check_records_refuses_a_bundle_rule_with_no_bundle_to_read(tmp_path: Path) -> None:
    (tmp_path / "r.json").write_text(json.dumps(GOOD_RESULT), encoding="utf-8")
    rc = cli.cmd_check_records(argparse.Namespace(path=str(tmp_path), rule="lineage"))
    assert rc == 2, "a bundle rule with nothing to read reported success"


def test_check_records_runs_a_selected_bundle_rule_on_a_bundle() -> None:
    """Negative control for the refusal above: with a bundle present it runs."""
    bad = CONTROLS / "lineage" / "bad"
    assert cli.cmd_check_records(argparse.Namespace(path=str(bad), rule="lineage")) == 1


def test_check_records_says_when_records_were_bound_to_no_ledger(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.cmd_check_records(
        argparse.Namespace(path=str(CONTROLS / "derived-status" / "good"), rule=None)
    )
    assert "NOT against any ledger" in capsys.readouterr().out


def test_check_records_does_not_claim_loose_records_in_a_bundled_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.cmd_check_records(
        argparse.Namespace(path=str(CONTROLS / "lineage" / "good"), rule=None)
    )
    out = capsys.readouterr().out
    assert "in 2 bundle(s)" in out and "NOT against any ledger" not in out


def test_check_records_refuses_an_unknown_rule() -> None:
    rc = cli.cmd_check_records(
        argparse.Namespace(path=str(CONTROLS / "lineage" / "good"), rule="no-such-rule")
    )
    assert rc == 2


# --------------------------------------------------------------- counter-model findings (#4)

def test_selftest_refuses_a_bundle_case_whose_ledger_became_unreadable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Discovery skips a directory with no readable ledger. Selftest must not: a
    case that silently left the population would leave `22/22` behind."""
    copy = tmp_path / "controls"
    shutil.copytree(CONTROLS, copy)
    (copy / "lineage" / "bad" / "regrade-erased-original" / "ledger.json").write_text(
        "{not json", encoding="utf-8"
    )
    rc = cli.cmd_selftest(argparse.Namespace(controls=str(copy)))
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "UNPARSED" in out and "lineage" in out, out


def test_a_bundle_with_non_string_ids_is_reported_not_crashed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trial = {**GOOD_LEDGER["trials"][0], "trial_id": []}  # type: ignore[index]
    attempts = [{"attempt_id": []}, {"attempt_id": "att-2", "retry_of": {}}]
    ledger = {**GOOD_LEDGER, "trials": [{**trial, "attempts": attempts}]}
    (tmp_path / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    rc = cli.cmd_check_records(argparse.Namespace(path=str(tmp_path), rule=None))
    assert rc == 1
    assert "trial-ledger" in capsys.readouterr().out


def test_an_empty_plan_is_not_a_fully_accounted_one(tmp_path: Path) -> None:
    """`--rule attempt-accounting` filters trial-ledger out, so accounting itself
    must not read zero planned attempts as zero missing ones."""
    bundle = _write_bundle(tmp_path, {**GOOD_LEDGER, "trials": []})
    assert list(records.attempt_accounting(bundle))
    rc = cli.cmd_check_records(argparse.Namespace(path=str(tmp_path), rule="attempt-accounting"))
    assert rc == 1


def test_a_blank_evidence_reference_is_no_evidence() -> None:
    rec = _record(**{**GOOD_RESULT, "criteria": [
        {"id": "c1", "mandatory": True, "outcome": "SATISFIED", "evidence": [""]}]})
    assert list(records.result_evidence(rec))
    assert list(records.result_evidence(_record(**{**GOOD_RESULT, "graded_digests": [" "]})))
