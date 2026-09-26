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
GOOD_LIFECYCLE = _control("attempt-lifecycle/good/captured.json")


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


# --------------------------------------------------------------- verdict tiers (#69)

def test_a_verdict_for_a_tier_not_enabled_is_refused() -> None:
    rec = _record(**{**GOOD_RESULT, "verification": {
        "tiers_enabled": ["deterministic"],
        "verdicts": {
            "deterministic": {"status": "PASS", "criteria": []},
            "llm-judge": {"status": "PASS", "criteria": []},
        },
    }})
    findings = list(records.verdict_tiers(rec))
    assert findings, "a verdict for a never-enabled tier passed unrefused"
    assert "llm-judge" in findings[0] and "tiers_enabled" in findings[0]


def test_a_verdict_for_an_enabled_tier_is_accepted() -> None:
    rec = _record(**{**GOOD_RESULT, "verification": {
        "tiers_enabled": ["deterministic"],
        "verdicts": {"deterministic": {"status": "PASS", "criteria": []}},
        "disagreement": {"available": False, "reason": "fewer than two judge tiers"},
    }})
    assert list(records.verdict_tiers(rec)) == []


def test_a_record_with_no_verification_object_is_not_this_rules_concern() -> None:
    """`verification` itself is optional here; other rules own its presence."""
    assert list(records.verdict_tiers(_record(**GOOD_RESULT))) == []


def test_an_enabled_tier_with_no_verdict_entry_is_refused() -> None:
    """The converse of `test_a_verdict_for_a_tier_not_enabled_is_refused`
    (orchestrator review of PR #88, ffae7eb): a tier enabled but never given
    its own entry is the same silent drop facing the other way - "one judge
    unavailable gives that tier `unavailable` while the others still report",
    never a tier that just isn't mentioned.
    """
    rec = _record(**{**GOOD_RESULT, "verification": {
        "tiers_enabled": ["deterministic", "llm-judge"],
        "verdicts": {"deterministic": {"status": "PASS", "criteria": []}},
    }})
    findings = list(records.verdict_tiers(rec))
    assert findings, "an enabled tier with no verdict entry passed unrefused"
    assert "llm-judge" in findings[0] and "no entry" in findings[0]


def test_tiers_enabled_with_no_verdicts_object_at_all_is_refused() -> None:
    """The same gap when `verdicts` is absent entirely, not merely missing one key."""
    rec = _record(**{**GOOD_RESULT, "verification": {"tiers_enabled": ["deterministic"]}})
    findings = list(records.verdict_tiers(rec))
    assert findings, "tiers_enabled with no verdicts object at all passed unrefused"


def test_an_unavailable_verdict_without_a_reason_is_refused() -> None:
    rec = _record(**{**GOOD_RESULT, "verification": {
        "tiers_enabled": ["deterministic", "llm-judge"],
        "verdicts": {
            "deterministic": {"status": "PASS", "criteria": []},
            "llm-judge": {"status": "UNAVAILABLE", "criteria": []},
        },
    }})
    findings = list(records.verdict_tiers(rec))
    assert findings, "an UNAVAILABLE verdict with no reason passed unrefused"
    assert "llm-judge" in findings[0] and "UNAVAILABLE" in findings[0]


def test_an_unavailable_verdict_with_a_reason_is_accepted() -> None:
    rec = _record(**{**GOOD_RESULT, "verification": {
        "tiers_enabled": ["deterministic", "llm-judge"],
        "verdicts": {
            "deterministic": {"status": "PASS", "criteria": []},
            "llm-judge": {"status": "UNAVAILABLE", "criteria": [], "reason": "judge model unreachable"},
        },
        "disagreement": {"available": False, "reason": "fewer than two judge tiers"},
    }})
    assert list(records.verdict_tiers(rec)) == []


def test_a_malformed_tiers_enabled_is_reported_not_crashed() -> None:
    """Regression (codex review): a nested list inside `tiers_enabled` used to
    raise `TypeError: unhashable type: 'list'` from `set(enabled)`, and a mixed
    list of strings and non-strings could then crash `sorted()` on the mismatch
    message - aborting validation with a traceback instead of a diagnostic.
    Confirmed to raise on the pre-fix code before this test was written; both
    shapes must now yield ordinary findings instead.
    """
    nested = _record(**{**GOOD_RESULT, "verification": {
        "tiers_enabled": ["deterministic", ["nested"]],
        "verdicts": {"deterministic": {"status": "PASS", "criteria": []}},
    }})
    findings = list(records.verdict_tiers(nested))
    assert any("tiers_enabled" in f for f in findings)

    mixed = _record(**{**GOOD_RESULT, "verification": {
        "tiers_enabled": ["deterministic", 1],
        "verdicts": {"deterministic": {"status": "PASS", "criteria": []},
                     "llm-judge": {"status": "PASS", "criteria": []}},
    }})
    findings = list(records.verdict_tiers(mixed))
    assert any("llm-judge" in f for f in findings)


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
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_RECEIPT, GOOD_MANIFEST, GOOD_LIFECYCLE, result)
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


def test_a_null_digest_cannot_agree_with_the_string_None(tmp_path: Path) -> None:
    manifest = {**GOOD_MANIFEST, "artifacts": [
        {"path": "out.txt", "type": "file", "size": 12, "digest": None}]}
    result = {**GOOD_RESULT, "graded_digests": ["None"]}
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_RECEIPT, manifest, result)
    assert list(records.ledger_binding(bundle)), "coercion manufactured digest agreement"
    assert list(records.artifact_digest(records.load(bundle.path / "r2.json")))


def test_accounting_under_two_ledgers_says_it_could_not_run(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_LEDGER)
    rc = cli.cmd_check_records(argparse.Namespace(path=str(tmp_path), rule="attempt-accounting"))
    assert list(records.attempt_accounting(bundle)) and rc == 1


# --------------------------------------------------------------- attempt lifecycle (#8)

def _lifecycle(**fields: object) -> records.Record:
    return _record(**{**GOOD_LIFECYCLE, **fields})


def test_a_not_run_attempt_must_say_it_never_started() -> None:
    """A not-run attempt never started: a not-run with a timeout ran. And a captured
    one that never started captured nothing. Only not-run and unavailable (a
    dependency failed before dispatch) may say never-started."""
    ran = _lifecycle(disposition="not-run", reason="budget", stop={"reason": "timeout", "confirmed": True})
    assert any("never started" in d for d in records.attempt_lifecycle(ran))
    never = _lifecycle(stop={"reason": "never-started", "confirmed": True})
    assert list(records.attempt_lifecycle(never))
    blocked = _lifecycle(disposition="unavailable", reason="provider unreachable",
                         stop={"reason": "never-started", "confirmed": True})
    assert list(records.attempt_lifecycle(blocked)) == []


def test_lifecycle_events_start_at_planned_and_carry_times() -> None:
    late = _lifecycle(events=[{"event": "started", "at": "t"}, {"event": "captured", "at": "t"}])
    assert any("start at planned" in d for d in records.attempt_lifecycle(late))
    untimed = _lifecycle(events=[{"event": "planned"}, {"event": "captured", "at": "t"}])
    assert any("has no time" in d for d in records.attempt_lifecycle(untimed))
    uncaptured = _lifecycle(events=[{"event": "planned", "at": "t"}])
    assert any("no captured event" in d for d in records.attempt_lifecycle(uncaptured))


def test_a_lifecycle_is_bound_to_a_planned_attempt(tmp_path: Path) -> None:
    """The new kind joins ATTEMPT_BOUND, so ledger-binding refuses a lifecycle for
    an attempt the ledger never issued - an account of an attempt nobody planned."""
    stray = {**GOOD_LIFECYCLE, "attempt_id": "att-9"}
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_LIFECYCLE, stray)
    assert any("att-9" in d for d in records.ledger_binding(bundle))


def test_two_lifecycles_for_one_attempt_conflict(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_LIFECYCLE, GOOD_LIFECYCLE)
    assert any("attempt-lifecycle" in d for d in records.unique_ids(bundle))


def test_only_the_controller_produces_a_lifecycle() -> None:
    assert list(records.producer_authority(_lifecycle(producer="subject")))
# --------------------------------------------------------------- mandatory is a bool (#37)

REPRO_37 = CONTROLS / "criterion-vocabulary" / "bad" / "string-mandatory.json"


@pytest.mark.parametrize("flag", ["true", "false", 1, 0, None, [True]],
                         ids=["str-true", "str-false", "int-1", "int-0", "null", "list"])
def test_a_non_boolean_mandatory_flag_is_refused(flag: object) -> None:
    """`derive_status` selects mandatory criteria with `is True`, so anything other
    than a real bool silently makes the criterion optional - and a VIOLATED one
    then drops out of the verdict. `1` and `0` are the bool/int trap: they are
    ints, not bools, whatever `1 == True` says."""
    rec = _record(**{**GOOD_RESULT, "criteria": [
        {"id": "c1", "mandatory": flag, "outcome": "SATISFIED", "evidence": ["log:c1"]}]})
    findings = list(records.criterion_vocabulary(rec))
    assert findings and "mandatory" in findings[0], flag


def test_a_missing_mandatory_flag_is_refused() -> None:
    """Absent reads as optional to `derive_status` - the same hole as a string."""
    rec = _record(**{**GOOD_RESULT, "criteria": [
        {"id": "c1", "outcome": "SATISFIED", "evidence": ["log:c1"]}]})
    assert list(records.criterion_vocabulary(rec))


@pytest.mark.parametrize("flag", [True, False])
def test_a_boolean_mandatory_flag_is_accepted(flag: bool) -> None:
    rec = _record(**{**GOOD_RESULT, "criteria": [
        {"id": "c1", "mandatory": flag, "outcome": "SATISFIED", "evidence": ["log:c1"]}]})
    assert list(records.criterion_vocabulary(rec)) == []


def test_the_string_mandatory_repro_derives_a_clean_PASS_so_only_vocabulary_can_see_it() -> None:
    """Why this is a vocabulary rule and not a derivation fix: the violation does
    not contradict the status, it DISAPPEARS, so derived-status finds nothing."""
    rec = records.load(REPRO_37)
    assert records.derive_status(rec) == rec.data["status"] == "PASS"
    assert list(records.derived_status(rec)) == []
    assert list(records.criterion_vocabulary(rec))


def test_check_records_refuses_the_string_mandatory_repro(tmp_path: Path) -> None:
    shutil.copy(REPRO_37, tmp_path / "record.json")
    rc = cli.cmd_check_records(argparse.Namespace(path=str(tmp_path), rule=None))
    assert rc == 1, "a VIOLATED criterion flagged \"mandatory\": \"true\" derived a clean PASS"


# --------------------------------------------------------------- skill invocations (#39)

def _with_skill_invocations(**entry: object) -> records.Record:
    observations = [*GOOD_MANIFEST["observations"], {"stream": "skill-invocations", **entry}]  # type: ignore[misc]
    return _record(**{**GOOD_MANIFEST, "observations": observations})


def test_a_numeric_count_under_incomplete_coverage_is_refused() -> None:
    """Silence is not \"not invoked\": the same rule `observation_coverage` already
    enforces for a whole stream (#39's addition), applied per skill."""
    rec = _with_skill_invocations(
        origin="client-reported", coverage="partial",
        skills=[{"path": ".codex/skills/slug/SKILL.md", "count": 0}],
    )
    findings = list(records.observation_coverage(rec))
    assert findings and "UNKNOWN" in findings[0]


def test_UNKNOWN_is_accepted_under_incomplete_coverage() -> None:
    rec = _with_skill_invocations(
        origin="client-reported", coverage="unsupported",
        skills=[{"path": ".codex/skills/slug/SKILL.md", "count": "UNKNOWN"}],
    )
    assert list(records.observation_coverage(rec)) == []


def test_UNKNOWN_is_refused_under_complete_coverage() -> None:
    """Complete coverage means everything was seen; \"unknown\" is no longer an
    honest answer once it was."""
    rec = _with_skill_invocations(
        origin="observed", coverage="complete",
        skills=[{"path": ".codex/skills/slug/SKILL.md", "count": "UNKNOWN"}],
    )
    findings = list(records.observation_coverage(rec))
    assert findings and "non-negative integer" in findings[0]


def test_complete_coverage_naming_no_skills_is_refused() -> None:
    """`installation-receipt` refuses an empty `installed` list, so every attempt
    with a receipt has at least one installed skill - "complete" coverage naming
    none is the silent-empty-population defect, one level up (codex review)."""
    rec = _with_skill_invocations(origin="observed", coverage="complete", skills=[])
    assert list(records.observation_coverage(rec))


def test_a_duplicate_path_with_conflicting_counts_is_refused() -> None:
    """Two rows for the same skill let a reader pick whichever count it likes
    (codex review)."""
    rec = _with_skill_invocations(
        origin="observed", coverage="complete",
        skills=[
            {"path": ".codex/skills/slug/SKILL.md", "count": 0},
            {"path": ".codex/skills/slug/SKILL.md", "count": 1},
        ],
    )
    findings = list(records.observation_coverage(rec))
    assert findings and "more than once" in findings[0]


def test_zero_is_a_legitimate_count_under_complete_coverage() -> None:
    rec = _with_skill_invocations(
        origin="observed", coverage="complete",
        skills=[{"path": ".codex/skills/slug/SKILL.md", "count": 0}],
    )
    assert list(records.observation_coverage(rec)) == []


def test_an_invoked_skill_not_in_the_receipts_installed_list_is_refused(tmp_path: Path) -> None:
    """`observation_coverage` only checks the stream's own shape; the cross-check
    against what the attempt actually installed needs the receipt, which only a
    bundle rule (`ledger_binding`) can read."""
    manifest = {**GOOD_MANIFEST, "observations": [
        *GOOD_MANIFEST["observations"],  # type: ignore[misc]
        {
            "stream": "skill-invocations", "origin": "observed", "coverage": "complete",
            "skills": [{"path": ".codex/skills/never-installed/SKILL.md", "count": 1}],
        },
    ]}
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_RECEIPT, manifest)
    findings = list(records.ledger_binding(bundle))
    assert findings and "never-installed" in findings[0]


def test_an_invoked_skill_the_receipt_installed_is_accepted(tmp_path: Path) -> None:
    installed_path = GOOD_RECEIPT["installed"][0]["path"]  # type: ignore[index]
    manifest = {**GOOD_MANIFEST, "observations": [
        *GOOD_MANIFEST["observations"],  # type: ignore[misc]
        {
            "stream": "skill-invocations", "origin": "observed", "coverage": "complete",
            "skills": [{"path": installed_path, "count": 1}],
        },
    ]}
    bundle = _write_bundle(tmp_path, GOOD_LEDGER, GOOD_RECEIPT, manifest)
    assert list(records.ledger_binding(bundle)) == []


# ------------------------------------------------- case.observes_selection (#26)


def test_case_observes_selection_must_be_a_boolean() -> None:
    ledger = {**GOOD_LEDGER, "trials": [
        {**GOOD_LEDGER["trials"][0], "case": {  # type: ignore[index]
            **GOOD_LEDGER["trials"][0]["case"], "observes_selection": "true",  # type: ignore[index]
        }},
    ]}
    findings = list(records.trial_ledger(_record(**ledger)))
    assert findings and "boolean" in findings[0]


def test_case_observes_selection_true_is_accepted() -> None:
    ledger = {**GOOD_LEDGER, "trials": [
        {**GOOD_LEDGER["trials"][0], "case": {  # type: ignore[index]
            **GOOD_LEDGER["trials"][0]["case"], "observes_selection": True,  # type: ignore[index]
        }},
    ]}
    assert list(records.trial_ledger(_record(**ledger))) == []


def _ledger_with_observes_selection(value: bool) -> dict[str, object]:
    return {**GOOD_LEDGER, "trials": [
        {**GOOD_LEDGER["trials"][0], "case": {  # type: ignore[index]
            **GOOD_LEDGER["trials"][0]["case"], "observes_selection": value,  # type: ignore[index]
        }},
    ]}


def test_skill_invocations_required_but_absent_is_refused(tmp_path: Path) -> None:
    """#39's own control, closed by #26: a trial that declares
    `case.observes_selection: true` but whose manifest carries no
    `skill-invocations` stream is refused, not silently accepted."""
    ledger = _ledger_with_observes_selection(True)
    bundle = _write_bundle(tmp_path, ledger, GOOD_RECEIPT, GOOD_MANIFEST)
    findings = list(records.ledger_binding(bundle))
    assert findings and "required" in findings[0] and "skill-invocations" in findings[0]


def test_skill_invocations_declared_satisfies_the_requirement(tmp_path: Path) -> None:
    ledger = _ledger_with_observes_selection(True)
    installed_path = GOOD_RECEIPT["installed"][0]["path"]  # type: ignore[index]
    manifest = {**GOOD_MANIFEST, "observations": [
        *GOOD_MANIFEST["observations"],  # type: ignore[misc]
        {
            "stream": "skill-invocations", "origin": "observed", "coverage": "complete",
            "skills": [{"path": installed_path, "count": 0}],
        },
    ]}
    bundle = _write_bundle(tmp_path, ledger, GOOD_RECEIPT, manifest)
    assert list(records.ledger_binding(bundle)) == []


def test_skill_invocations_absent_is_fine_when_not_declared(tmp_path: Path) -> None:
    """The default: a trial that never declares `observes_selection` requires
    nothing here - #39's stream stays optional exactly as records.md states."""
    ledger = _ledger_with_observes_selection(False)
    bundle = _write_bundle(tmp_path, ledger, GOOD_RECEIPT, GOOD_MANIFEST)
    assert list(records.ledger_binding(bundle)) == []


# ------------------------------------------------------------- pilot-report (#12)

GOOD_PILOT_REPORT = _control("pilot-report/good/record.json")


def _report_entry(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "attempt_id": "att-1",
        "trial_id": "t-1",
        "disposition": "captured",
        "criteria": [{"id": "R1", "outcome": "SATISFIED"}],
        "uncertainty": "none",
        "interventions": 0,
        "cost_usd": {"setup": 0.01, "agent": 0.15, "grading": 0.02, "total": 0.18},
        "time_seconds": {"setup": 5, "agent": 120, "grading": 10, "total": 135},
    }
    base.update(fields)
    return base


def test_pilot_report_accepts_a_well_formed_entry() -> None:
    report = {**GOOD_PILOT_REPORT, "attempts": [_report_entry()]}
    assert list(records.pilot_report(_record(**report))) == []


def test_pilot_report_refuses_an_empty_attempts_list() -> None:
    report = {**GOOD_PILOT_REPORT, "attempts": []}
    findings = list(records.pilot_report(_record(**report)))
    assert findings and "no attempts" in findings[0]


def test_pilot_report_refuses_a_bad_disposition() -> None:
    report = {**GOOD_PILOT_REPORT, "attempts": [_report_entry(disposition="finished")]}
    findings = list(records.pilot_report(_record(**report)))
    assert findings and "disposition" in findings[0]


def test_pilot_report_refuses_a_bad_criterion_outcome() -> None:
    report = {**GOOD_PILOT_REPORT, "attempts": [_report_entry(criteria=[{"id": "R1", "outcome": "MAYBE"}])]}
    findings = list(records.pilot_report(_record(**report)))
    assert findings and "outcome" in findings[0]


def test_pilot_report_refuses_a_missing_uncertainty() -> None:
    entry = _report_entry()
    del entry["uncertainty"]
    report = {**GOOD_PILOT_REPORT, "attempts": [entry]}
    findings = list(records.pilot_report(_record(**report)))
    assert findings and "uncertainty" in findings[0]


def test_pilot_report_refuses_a_negative_intervention_count() -> None:
    report = {**GOOD_PILOT_REPORT, "attempts": [_report_entry(interventions=-1)]}
    findings = list(records.pilot_report(_record(**report)))
    assert findings and "interventions" in findings[0]


def test_pilot_report_refuses_a_split_missing_a_key() -> None:
    """Missing values must be explicit ('UNKNOWN'), never a silently absent
    key (#12's own requirement)."""
    entry = _report_entry(cost_usd={"setup": 0.01, "agent": 0.15, "grading": 0.02})  # no "total"
    report = {**GOOD_PILOT_REPORT, "attempts": [entry]}
    findings = list(records.pilot_report(_record(**report)))
    assert findings and "no 'total'" in findings[0]


def test_pilot_report_accepts_an_explicit_unknown_split_value() -> None:
    entry = _report_entry(
        disposition="unavailable", criteria=[],
        cost_usd={"setup": 0.0, "agent": "UNKNOWN", "grading": "UNKNOWN", "total": "UNKNOWN"},
        time_seconds={"setup": 1, "agent": "UNKNOWN", "grading": "UNKNOWN", "total": "UNKNOWN"},
    )
    report = {**GOOD_PILOT_REPORT, "attempts": [entry]}
    assert list(records.pilot_report(_record(**report))) == []


def test_pilot_report_refuses_a_split_that_does_not_sum(tmp_path: Path) -> None:
    entry = _report_entry(cost_usd={"setup": 0.01, "agent": 0.15, "grading": 0.02, "total": 99.0})
    report = {**GOOD_PILOT_REPORT, "attempts": [entry]}
    findings = list(records.pilot_report(_record(**report)))
    assert findings and "does not equal" in findings[0]


def test_pilot_report_refuses_a_duplicate_attempt_id() -> None:
    report = {**GOOD_PILOT_REPORT, "attempts": [_report_entry(), _report_entry()]}
    findings = list(records.pilot_report(_record(**report)))
    assert findings and "more than once" in findings[0]


def test_ledger_binding_refuses_a_pilot_report_missing_a_scheduled_attempt(tmp_path: Path) -> None:
    """#12's own control: a report omitting a scheduled attempt is refused."""
    ledger = {**GOOD_LEDGER, "trials": [
        {**GOOD_LEDGER["trials"][0], "attempts": [{"attempt_id": "att-1"}, {"attempt_id": "att-2"}]},  # type: ignore[index]
    ]}
    report = {**GOOD_PILOT_REPORT, "attempts": [_report_entry(attempt_id="att-1")]}
    bundle = _write_bundle(tmp_path, ledger, report)
    findings = list(records.ledger_binding(bundle))
    assert findings and "omits scheduled attempt" in findings[0] and "att-2" in findings[0]


def test_ledger_binding_refuses_a_pilot_report_naming_an_unplanned_attempt(tmp_path: Path) -> None:
    ledger = {**GOOD_LEDGER, "trials": [
        {**GOOD_LEDGER["trials"][0], "attempts": [{"attempt_id": "att-1"}]},  # type: ignore[index]
    ]}
    report = {**GOOD_PILOT_REPORT, "attempts": [_report_entry(attempt_id="att-1"), _report_entry(attempt_id="att-99")]}
    bundle = _write_bundle(tmp_path, ledger, report)
    findings = list(records.ledger_binding(bundle))
    assert findings and "never planned" in findings[0] and "att-99" in findings[0]


def test_ledger_binding_accepts_a_pilot_report_covering_every_scheduled_attempt(tmp_path: Path) -> None:
    ledger = {**GOOD_LEDGER, "trials": [
        {**GOOD_LEDGER["trials"][0], "attempts": [{"attempt_id": "att-1"}, {"attempt_id": "att-2"}]},  # type: ignore[index]
    ]}
    report = {**GOOD_PILOT_REPORT, "attempts": [
        _report_entry(attempt_id="att-1"), _report_entry(attempt_id="att-2"),
    ]}
    bundle = _write_bundle(tmp_path, ledger, report)
    assert list(records.ledger_binding(bundle)) == []


def test_ledger_binding_does_not_crash_on_an_unhashable_attempt_id(tmp_path: Path) -> None:
    """Red case from cross-model review: a report entry's attempt_id being a
    list or dict (already malformed per `pilot_report`'s own rule) must not
    crash this bundle rule via an unhashable set element - it must report a
    finding instead."""
    ledger = {**GOOD_LEDGER, "trials": [
        {**GOOD_LEDGER["trials"][0], "attempts": [{"attempt_id": "att-1"}]},  # type: ignore[index]
    ]}
    report = {**GOOD_PILOT_REPORT, "attempts": [{**_report_entry(), "attempt_id": ["not", "a", "string"]}]}
    bundle = _write_bundle(tmp_path, ledger, report)
    findings = list(records.ledger_binding(bundle))  # must not raise
    assert findings and "omits scheduled attempt" in findings[0] and "att-1" in findings[0]
