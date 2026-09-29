"""Tests for `skillc/outcome_report.py` (issue #13): separate functional/
constraint/integration outcome reporting, built ONLY from a criteria list
and a declared dimension mapping - synthetic fixture criteria throughout,
never a real graded run (only the code path is in scope here; real runs
are operator-owed)."""

from __future__ import annotations

from skillc import outcome_report as orpt


def _c(cid: str, outcome: str, mandatory: bool = True) -> dict[str, object]:
    return {"id": cid, "mandatory": mandatory, "outcome": outcome}


def test_every_criterion_lands_in_exactly_one_bucket() -> None:
    criteria = [
        _c("functional-a", "SATISFIED"),
        _c("constraint-b", "SATISFIED"),
        _c("integration-c", "SATISFIED"),
        _c("mystery-d", "SATISFIED"),
    ]
    dimensions = {"functional-a": "functional", "constraint-b": "constraint", "integration-c": "integration"}
    report = orpt.build(criteria, dimensions)
    assert [c["id"] for c in report["functional"].criteria] == ["functional-a"]
    assert [c["id"] for c in report["constraint"].criteria] == ["constraint-b"]
    assert [c["id"] for c in report["integration"].criteria] == ["integration-c"]
    assert [c["id"] for c in report["unclassified"].criteria] == ["mystery-d"]
    total = sum(len(report[b].criteria) for b in orpt.BUCKETS)
    assert total == len(criteria)


def test_an_undeclared_criterion_is_unclassified_never_guessed() -> None:
    """Review ruling: declared, never inferred. A criterion id that LOOKS
    like it should be "functional" by naming convention alone must not be
    bucketed there without an explicit declaration."""
    criteria = [_c("functional-looking-id", "SATISFIED")]
    report = orpt.build(criteria, dimensions={})
    assert [c["id"] for c in report["unclassified"].criteria] == ["functional-looking-id"]
    assert report["functional"].criteria == ()


def test_an_empty_bucket_reports_not_applicable_not_inconclusive() -> None:
    """A dimension with zero criteria (e.g. a Level 1 task has no
    constraint-*/integration-* criteria at all) is a different fact from
    "we could not determine this dimension's outcome" - conflating the two
    would make a task family that never uses a dimension look exactly like
    one that tried to check it and failed to get an answer."""
    report = orpt.build([_c("functional-a", "SATISFIED")], {"functional-a": "functional"})
    assert report["functional"].verdict == orpt.PASS
    assert report["constraint"].verdict == orpt.NOT_APPLICABLE
    assert report["integration"].verdict == orpt.NOT_APPLICABLE


def test_bucket_verdict_mirrors_derive_status_violated_first() -> None:
    criteria = [_c("constraint-a", "VIOLATED"), _c("constraint-b", "UNKNOWN")]
    report = orpt.build(criteria, {"constraint-a": "constraint", "constraint-b": "constraint"})
    assert report["constraint"].verdict == orpt.FAIL


def test_bucket_verdict_unknown_mandatory_is_inconclusive_not_pass() -> None:
    criteria = [_c("constraint-a", "SATISFIED"), _c("constraint-b", "UNKNOWN")]
    report = orpt.build(criteria, {"constraint-a": "constraint", "constraint-b": "constraint"})
    assert report["constraint"].verdict == orpt.INCONCLUSIVE


def test_bucket_verdict_all_satisfied_is_pass() -> None:
    criteria = [_c("constraint-a", "SATISFIED"), _c("constraint-b", "SATISFIED")]
    report = orpt.build(criteria, {"constraint-a": "constraint", "constraint-b": "constraint"})
    assert report["constraint"].verdict == orpt.PASS


def test_optional_criteria_never_enter_the_bucket_verdict() -> None:
    """Mirrors records.derive_status: optional quality scores cannot
    average away a mandatory failure, nor manufacture a PASS on their own."""
    criteria = [_c("constraint-a", "VIOLATED", mandatory=False)]
    report = orpt.build(criteria, {"constraint-a": "constraint"})
    # Non-empty bucket, but no MANDATORY outcomes to derive a verdict from.
    assert report["constraint"].criteria != ()
    assert report["constraint"].verdict == orpt.INCONCLUSIVE


def test_a_passing_functional_bucket_does_not_imply_a_passing_integration_bucket() -> None:
    """#13's own acceptance line, directly: a passing unit test must not
    imply installed-path success."""
    criteria = [
        _c("functional-a", "SATISFIED"),
        _c("integration-a", "VIOLATED"),
    ]
    report = orpt.build(criteria, {"functional-a": "functional", "integration-a": "integration"})
    assert report["functional"].verdict == orpt.PASS
    assert report["integration"].verdict == orpt.FAIL


def test_as_dict_is_json_safe_and_covers_every_bucket() -> None:
    report = orpt.build([_c("functional-a", "SATISFIED")], {"functional-a": "functional"})
    as_dict = report.as_dict()
    assert set(as_dict) == set(orpt.BUCKETS)
    functional = as_dict["functional"]
    constraint = as_dict["constraint"]
    assert isinstance(functional, dict) and functional["verdict"] == orpt.PASS
    assert isinstance(constraint, dict) and constraint["verdict"] == orpt.NOT_APPLICABLE


def test_unavailable_is_distinct_from_unclassified() -> None:
    """Review ruling: "this grader declares no dimensions" (UNCLASSIFIED, a
    true statement about the grader) and "the dimensions lookup itself
    failed" (UNAVAILABLE, a statement about this call) must never collapse
    into the same reported value - a reader must not mistake a failed
    lookup for a grader that genuinely declares nothing."""
    criteria = [_c("functional-a", "SATISFIED")]

    unclassified = orpt.build(criteria, dimensions={})
    assert unclassified["unclassified"].verdict != orpt.UNAVAILABLE
    assert [c["id"] for c in unclassified["unclassified"].criteria] == ["functional-a"]

    unavailable = orpt.build(criteria, dimensions={}, unavailable_reason="grader load failed (Refused)")
    for bucket in orpt.BUCKETS:
        assert unavailable[bucket].verdict == orpt.UNAVAILABLE
    assert unavailable.unavailable_reason == "grader load failed (Refused)"


def test_unavailable_ignores_a_populated_dimensions_argument() -> None:
    """`unavailable_reason` short-circuits entirely - a caller that (by
    mistake, or because it has stale data) passes both a real `dimensions`
    mapping AND a reason must still get `UNAVAILABLE` throughout, never a
    real verdict computed from data the reason says was not trustworthy."""
    criteria = [_c("functional-a", "VIOLATED")]
    report = orpt.build(criteria, {"functional-a": "functional"}, unavailable_reason="stale")
    assert report["functional"].verdict == orpt.UNAVAILABLE
    assert report["functional"].criteria == ()


def test_unavailable_as_dict_includes_the_reason() -> None:
    report = orpt.build([], {}, unavailable_reason="grader load failed (OSError)")
    as_dict = report.as_dict()
    assert as_dict["unavailable_reason"] == "grader load failed (OSError)"


def test_available_as_dict_omits_the_reason_key_entirely() -> None:
    """Not merely `None` - the key itself is absent, so a caller cannot
    mistake a present-but-null reason for "no reason was ever computed"."""
    report = orpt.build([_c("functional-a", "SATISFIED")], {"functional-a": "functional"})
    assert "unavailable_reason" not in report.as_dict()
