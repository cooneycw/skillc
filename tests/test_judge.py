"""Tests for the judge seam (#69).

Every acceptance item names its own case:

  malformed output ........... test_parse_judge_verdict_refuses_*
  no partial application ...... test_run_tier_marks_only_the_malformed_criterion_unknown
  per-tier availability ....... test_run_tier_reports_unavailable_with_a_reason,
                                 test_one_unavailable_tier_does_not_affect_the_other (in test_verify_judge.py)
  disagreement ................ test_compute_disagreement_*
  leak-check ................... test_check_judge_input_refuses_*
  no real model call ........... every judge here is FakeJudge; test_no_mcp_import_in_this_module
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from fixtures.leak_seeds.judge_seeds import HOME_PATH_LEAK, PRIVATE_IP_LEAK, PRIVATE_IP_LEAK_2

from skillc import judge


def _criteria(result: dict[str, object]) -> list[dict[str, object]]:
    value = result["criteria"]
    assert isinstance(value, list)
    return value


def _str(result: dict[str, object], key: str) -> str:
    value = result[key]
    assert isinstance(value, str)
    return value


def test_fake_judge_answers_every_criterion() -> None:
    j = judge.FakeJudge(outcome="SATISFIED")
    answers = j.evaluate(["R1", "R2"], "goal", [("out.txt", b"ok")])
    assert {a["id"] for a in answers} == {"R1", "R2"}
    assert all(a["outcome"] == "SATISFIED" for a in answers)


# --------------------------------------------------------------- parse_judge_verdict


def test_parse_judge_verdict_accepts_a_well_formed_satisfied() -> None:
    verdict = judge.parse_judge_verdict({"id": "R1", "outcome": "SATISFIED", "evidence": ["e1"]}, "R1")
    assert verdict == judge.JudgeCriterionVerdict(id="R1", outcome="SATISFIED", evidence=("e1",))


def test_parse_judge_verdict_accepts_a_well_formed_unknown() -> None:
    verdict = judge.parse_judge_verdict({"id": "R1", "outcome": "UNKNOWN", "missing": "no basis"}, "R1")
    assert verdict.outcome == "UNKNOWN"
    assert verdict.missing == "no basis"


def test_parse_judge_verdict_refuses_a_non_object() -> None:
    with pytest.raises(judge.MalformedJudgeOutput, match="not an object"):
        judge.parse_judge_verdict("SATISFIED", "R1")


def test_parse_judge_verdict_refuses_a_mismatched_id() -> None:
    with pytest.raises(judge.MalformedJudgeOutput, match="names"):
        judge.parse_judge_verdict({"id": "R2", "outcome": "SATISFIED", "evidence": ["e"]}, "R1")


def test_parse_judge_verdict_refuses_an_outcome_outside_the_vocabulary() -> None:
    with pytest.raises(judge.MalformedJudgeOutput, match="not one of"):
        judge.parse_judge_verdict({"id": "R1", "outcome": "MAYBE"}, "R1")


def test_parse_judge_verdict_refuses_satisfied_with_no_evidence() -> None:
    """No partial application: an otherwise-valid SATISFIED with no evidence
    is refused whole, never accepted with evidence silently defaulted."""
    with pytest.raises(judge.MalformedJudgeOutput, match="no evidence"):
        judge.parse_judge_verdict({"id": "R1", "outcome": "SATISFIED", "evidence": []}, "R1")


def test_parse_judge_verdict_refuses_unknown_with_no_missing_reason() -> None:
    with pytest.raises(judge.MalformedJudgeOutput, match="no 'missing' reason"):
        judge.parse_judge_verdict({"id": "R1", "outcome": "UNKNOWN"}, "R1")


def test_parse_judge_verdict_refuses_non_string_evidence() -> None:
    with pytest.raises(judge.MalformedJudgeOutput, match="evidence"):
        judge.parse_judge_verdict({"id": "R1", "outcome": "SATISFIED", "evidence": [1, 2]}, "R1")


def test_parse_judge_verdict_refuses_a_malformed_missing_field_on_satisfied() -> None:
    """Red case from cross-model review: an earlier version validated
    'missing' only on the UNKNOWN path, so a garbage value riding along on a
    SATISFIED entry was silently discarded instead of refusing the whole
    response - 'every field is validated' means every field PRESENT, not
    only the ones the outcome happens to require."""
    with pytest.raises(judge.MalformedJudgeOutput, match="'missing' is present but not"):
        judge.parse_judge_verdict({"id": "R1", "outcome": "SATISFIED", "evidence": ["e"], "missing": 123}, "R1")


def test_parse_judge_verdict_refuses_an_unknown_field() -> None:
    with pytest.raises(judge.MalformedJudgeOutput, match="unknown field"):
        judge.parse_judge_verdict({"id": "R1", "outcome": "SATISFIED", "evidence": ["e"], "extra": True}, "R1")


# --------------------------------------------------------------- run_tier


def test_run_tier_accepts_a_well_formed_pass() -> None:
    result = judge.run_tier(judge.SAME_MODEL_TIER, judge.FakeJudge(outcome="SATISFIED"),
                             ["R1", "R2"], "goal text", [("out.txt", b"ok")])
    assert result["status"] == "PASS"
    assert {c["id"] for c in _criteria(result)} == {"R1", "R2"}
    judge_info = result["judge"]
    assert isinstance(judge_info, dict)
    assert judge_info["name"] == "fake-judge"


def test_a_plain_answer_keeps_the_described_model_and_names_no_server() -> None:
    result = judge.run_tier(judge.SAME_MODEL_TIER, judge.FakeJudge(), ["R1"], "goal", [("out.txt", b"ok")])
    assert result["judge"] == {"name": "fake-judge", "model": "fake-model-1", "version": "1"}


class _RelayJudge:
    """A judge behind a server: describe() knows only the server, and each
    answer names the model that produced it (#12)."""

    def describe(self) -> judge.JudgeDescription:
        return judge.JudgeDescription(name="relay", model=None, version=None,
                                      server_name="relay-server", server_version="2")

    def evaluate(self, criteria: Sequence[str], goal_text: str,
                 candidate_files: Sequence[tuple[str, bytes]]) -> judge.JudgeAnswer:
        return judge.JudgeAnswer(
            verdicts=[{"id": c, "outcome": "SATISFIED", "evidence": ["relay"]} for c in criteria],
            model="answering-llm",
        )


def test_the_answering_model_is_recorded_apart_from_the_server() -> None:
    result = judge.run_tier(judge.INDEPENDENT_TIER, _RelayJudge(), ["R1"], "goal", [("out.txt", b"ok")])
    assert result["status"] == "PASS"
    assert result["judge"] == {
        "name": "relay", "model": "answering-llm", "version": None,
        "server": {"name": "relay-server", "version": "2"},
    }


def test_run_tier_reports_fail_on_a_violation() -> None:
    result = judge.run_tier(judge.INDEPENDENT_TIER, judge.FakeJudge(outcome="VIOLATED"),
                             ["R1"], "goal text", [("out.txt", b"ok")])
    assert result["status"] == "FAIL"


def test_run_tier_reports_unavailable_with_a_reason() -> None:
    """Per-tier availability control: an unreachable judge yields UNAVAILABLE
    with a stated reason, never a silent drop."""
    result = judge.run_tier(judge.INDEPENDENT_TIER, judge.FakeJudge(unavailable="no network"),
                             ["R1"], "goal text", [("out.txt", b"ok")])
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "no network"
    assert result["criteria"] == []


def test_run_tier_marks_a_missing_criterion_unknown() -> None:
    class PartialJudge:
        def describe(self) -> judge.JudgeDescription:
            return judge.JudgeDescription(name="partial", model=None, version=None)

        def evaluate(self, criteria, goal_text, candidate_files):
            return [{"id": "R1", "outcome": "SATISFIED", "evidence": ["e"]}]  # R2 never answered

    result = judge.run_tier(judge.SAME_MODEL_TIER, PartialJudge(), ["R1", "R2"], "goal", [("out.txt", b"ok")])
    outcomes = {c["id"]: c["outcome"] for c in _criteria(result)}
    assert outcomes == {"R1": "SATISFIED", "R2": "UNKNOWN"}
    assert result["status"] == "INCONCLUSIVE"


def test_run_tier_marks_only_the_malformed_criterion_unknown() -> None:
    """No partial application, at the granularity of ONE criterion: a
    malformed entry for R2 does not affect R1's own valid verdict."""
    class MixedJudge:
        def describe(self) -> judge.JudgeDescription:
            return judge.JudgeDescription(name="mixed", model=None, version=None)

        def evaluate(self, criteria, goal_text, candidate_files):
            return [
                {"id": "R1", "outcome": "SATISFIED", "evidence": ["e"]},
                {"id": "R2", "outcome": "MAYBE"},  # malformed
            ]

    result = judge.run_tier(judge.SAME_MODEL_TIER, MixedJudge(), ["R1", "R2"], "goal", [("out.txt", b"ok")])
    criteria = _criteria(result)
    outcomes = {c["id"]: c["outcome"] for c in criteria}
    assert outcomes["R1"] == "SATISFIED"
    assert outcomes["R2"] == "UNKNOWN"
    r2 = next(c for c in criteria if c["id"] == "R2")
    assert "malformed judge response" in _str(r2, "missing")


def test_run_tier_marks_a_duplicate_response_unknown_regardless_of_order() -> None:
    """Red case from cross-model review: two responses for the same
    criterion let response ORDER decide the grade (VIOLATED then SATISFIED
    passes; reversed, it fails) - both orders must instead produce UNKNOWN,
    not a last-wins result."""
    class DuplicatingJudge:
        def __init__(self, order: tuple[str, str]) -> None:
            self.order = order

        def describe(self) -> judge.JudgeDescription:
            return judge.JudgeDescription(name="dup", model=None, version=None)

        def evaluate(self, criteria, goal_text, candidate_files):
            return [{"id": "R1", "outcome": o, "evidence": ["e"]} for o in self.order]

    for order in (("VIOLATED", "SATISFIED"), ("SATISFIED", "VIOLATED")):
        result = judge.run_tier(judge.SAME_MODEL_TIER, DuplicatingJudge(order), ["R1"], "goal", [])
        r1 = _criteria(result)[0]
        assert r1["outcome"] == "UNKNOWN"
        assert "more than one response" in _str(r1, "missing")
        assert result["status"] == "INCONCLUSIVE"


def test_run_tier_refuses_leaked_goal_text_before_calling_the_judge() -> None:
    calls: list[str] = []

    class RecordingJudge:
        def describe(self) -> judge.JudgeDescription:
            calls.append("describe")
            return judge.JudgeDescription(name="x", model=None, version=None)

        def evaluate(self, criteria, goal_text, candidate_files):
            calls.append("evaluate")
            return []

    with pytest.raises(judge.JudgeInputLeaked):
        judge.run_tier(judge.SAME_MODEL_TIER, RecordingJudge(), ["R1"],
                        f"please read {HOME_PATH_LEAK}/notes.txt", [("out.txt", b"ok")])
    assert calls == []  # the judge was never called at all


def test_run_tier_refuses_leaked_candidate_content() -> None:
    with pytest.raises(judge.JudgeInputLeaked):
        judge.run_tier(judge.SAME_MODEL_TIER, judge.FakeJudge(), ["R1"], "goal",
                        [("out.txt", f"server at {PRIVATE_IP_LEAK} leaked".encode())])


# --------------------------------------------------------------- check_judge_input


def test_check_judge_input_accepts_clean_input() -> None:
    judge.check_judge_input("a clean goal", [("out.txt", b"clean content")])  # must not raise


def test_check_judge_input_refuses_a_home_path_in_the_goal() -> None:
    with pytest.raises(judge.JudgeInputLeaked, match="<goal>"):
        judge.check_judge_input(f"see {HOME_PATH_LEAK}/secret", [])


def test_check_judge_input_refuses_a_private_ip_in_candidate_content() -> None:
    with pytest.raises(judge.JudgeInputLeaked, match="out.txt"):
        judge.check_judge_input("goal", [("out.txt", f"connect to {PRIVATE_IP_LEAK_2}".encode())])


def test_check_judge_input_decodes_undecodable_bytes_permissively() -> None:
    """A candidate file skillc's own scanner cannot cleanly decode is not
    thereby exempt from being scanned - it must not raise UnicodeDecodeError."""
    judge.check_judge_input("goal", [("binary.dat", b"\xff\xfe\x00\x01clean")])  # must not raise


def test_check_judge_input_refuses_a_leak_in_a_filename_with_clean_content() -> None:
    """Red case from cross-model review: an earlier version scanned only file
    CONTENT, so a private IP or home path spelled into the FILENAME reached
    the judge unchecked."""
    with pytest.raises(judge.JudgeInputLeaked, match="filename"):
        judge.check_judge_input("goal", [(f"{PRIVATE_IP_LEAK_2}.txt", b"perfectly clean content")])


def test_check_judge_input_refuses_a_leak_in_a_criterion_id() -> None:
    with pytest.raises(judge.JudgeInputLeaked, match="criterion id"):
        judge.check_judge_input("goal", [], criteria=[f"{HOME_PATH_LEAK}/R1"])


# --------------------------------------------------------------- compute_disagreement


def test_compute_disagreement_unavailable_with_fewer_than_two_tiers() -> None:
    same = judge.run_tier(judge.SAME_MODEL_TIER, judge.FakeJudge(outcome="SATISFIED"), ["R1"], "g", [])
    result = judge.compute_disagreement({judge.SAME_MODEL_TIER: same})
    assert result == {"available": False, "reason": judge.DISAGREEMENT_UNAVAILABLE_REASON}


def test_compute_disagreement_unavailable_when_one_tier_is_unavailable() -> None:
    same = judge.run_tier(judge.SAME_MODEL_TIER, judge.FakeJudge(outcome="SATISFIED"), ["R1"], "g", [])
    independent = judge.run_tier(judge.INDEPENDENT_TIER, judge.FakeJudge(unavailable="down"), ["R1"], "g", [])
    result = judge.compute_disagreement({judge.SAME_MODEL_TIER: same, judge.INDEPENDENT_TIER: independent})
    assert result["available"] is False


def test_compute_disagreement_opposite_verdicts_are_recorded_and_neither_overrides() -> None:
    """Control: a same-model judge that always passes and an independent
    judge that always fails give two opposite verdicts and a non-empty
    disagreement record. Neither overrides the other."""
    same = judge.run_tier(judge.SAME_MODEL_TIER, judge.FakeJudge(outcome="SATISFIED"), ["R1", "R2"], "g", [])
    independent = judge.run_tier(judge.INDEPENDENT_TIER, judge.FakeJudge(outcome="VIOLATED"), ["R1", "R2"], "g", [])
    assert same["status"] == "PASS"
    assert independent["status"] == "FAIL"  # neither tier's status changed the other's
    result = judge.compute_disagreement({judge.SAME_MODEL_TIER: same, judge.INDEPENDENT_TIER: independent})
    assert result["available"] is True
    assert result["disagreement_count"] == 2
    assert result["agreement_count"] == 0
    per_criterion = result["per_criterion"]
    assert isinstance(per_criterion, list)
    assert all(not p["agree"] for p in per_criterion)


def test_compute_disagreement_agreeing_verdicts_show_zero_disagreement() -> None:
    same = judge.run_tier(judge.SAME_MODEL_TIER, judge.FakeJudge(outcome="SATISFIED"), ["R1"], "g", [])
    independent = judge.run_tier(judge.INDEPENDENT_TIER, judge.FakeJudge(outcome="SATISFIED"), ["R1"], "g", [])
    result = judge.compute_disagreement({judge.SAME_MODEL_TIER: same, judge.INDEPENDENT_TIER: independent})
    assert result["disagreement_count"] == 0
    assert result["agreement_count"] == 1
