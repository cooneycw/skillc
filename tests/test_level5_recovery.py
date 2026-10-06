"""Tests for the Level 5 recovery-partial-processing task and its grader
(#14).

Mirrors `tests/test_level1_slug.py`'s own wiring: `qualify.py` is loaded and
driven directly so the grader cannot go blind unnoticed, and each broken
grader control is proven refused for the reason its name gives. A gate that
runs only as a standalone script, invoked by nothing, is an instrument no CI
gate actually exercises - this file is what makes it one, including for
`check_known_gap`'s own drift/refusal behavior, negative-controlled here
against a synthetic gap built from `reference/` rather than against this
task's own known gaps, which issue #14's runtime PR closed (`known-gaps/
forged-log` moved to `wrong/forged-log` once `envelope["trusted"]` gave the
judge a real out-of-band channel) - so these controls do not depend on the
task always carrying an open one.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from skillc.decide_reply_channel import LoggedDecision, TrustedLog

TASK = (
    Path(__file__).resolve().parent.parent
    / "evals" / "level5" / "recovery-partial-processing"
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level5_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("qualify")
grade_recovery = _load("grade_recovery")


def test_the_grader_is_certified() -> None:
    certified, rows = qualify.certify(TASK / "grade_recovery.py")
    assert certified, [r for r in rows if not r.ok]
    by_name = {r.candidate: r.status for r in rows}
    assert by_name["reference"] == "PASS"
    assert len(rows) >= 1 + 5  # reference + 5 wrong/*


@pytest.mark.parametrize("control", sorted(qualify.CONTROLS))
def test_every_broken_grader_is_refused_for_the_reason_its_name_gives(control: str) -> None:
    held, reason, _ = qualify.control_verdict(control)
    assert held, reason


def test_qualify_main_reports_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualify.main() == 0
    out = capsys.readouterr().out
    assert "QUALIFY: ok" in out
    assert "known gap(s) reproduce as documented" in out


def test_known_gaps_reproduce_as_documented() -> None:
    # If this task documents any known gaps, each must stay a checked fact
    # rather than a claim: the recorded miss must still reproduce exactly.
    # Issue #14's runtime PR closed this task's only gap (forged-log moved to
    # wrong/forged-log), so an empty known-gaps/ here is the correct state,
    # not an oversight.
    for path in qualify.known_gaps():
        ok, detail = qualify.check_known_gap(TASK / "grade_recovery.py", path)
        assert ok, detail


def _copy_task(tmp_path: Path) -> Path:
    root = tmp_path / "task"
    shutil.copytree(TASK, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _make_synthetic_known_gap(root: Path) -> Path:
    """A known-gaps/ fixture for negative-controlling `check_known_gap`
    itself, independent of whether this task currently has an open gap of
    its own. Built from `reference/` (graded PASS, no violations) with a
    declared `true_status` of FAIL - the documented-miss shape `check_known_gap`
    exists to verify, without tying the test to any specific narrative."""
    gap = root / "known-gaps" / "synthetic-gap"
    shutil.copytree(root / "reference", gap, ignore=shutil.ignore_patterns("__pycache__"))
    (gap / "expected.json").write_text(json.dumps({
        "graded_status_today": "PASS", "graded_violated_today": [],
        "true_status": "FAIL", "true_violated": ["work-preserved"],
    }), encoding="utf-8")
    return gap


def test_a_drifted_known_gap_turns_the_check_red(tmp_path: Path) -> None:
    # Negative control for check_known_gap itself: a known gap that stopped
    # reproducing as documented must be caught, not silently accepted.
    root = _copy_task(tmp_path)
    gap = _make_synthetic_known_gap(root)
    expected_path = gap / "expected.json"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    assert data["graded_violated_today"] == []  # the real grader reports no violations
    data["graded_violated_today"] = ["work-preserved"]
    expected_path.write_text(json.dumps(data), encoding="utf-8")
    ok, detail = qualify.check_known_gap(root / "grade_recovery.py", gap, root)
    assert not ok
    assert "no longer reproduces" in detail


def test_a_known_gap_whose_graded_status_matches_its_true_status_is_refused(tmp_path: Path) -> None:
    # A "known gap" that the grader already catches is not a gap - it belongs
    # in wrong/, not known-gaps/. check_known_gap must refuse that shape too.
    root = _copy_task(tmp_path)
    gap = _make_synthetic_known_gap(root)
    expected_path = gap / "expected.json"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    data["true_status"] = data["graded_status_today"]
    expected_path.write_text(json.dumps(data), encoding="utf-8")
    ok, detail = qualify.check_known_gap(root / "grade_recovery.py", gap, root)
    assert not ok
    assert "not a documented miss" in detail


# ------------------------------------------------- _trusted_log (#183)


def _trusted_log_bytes(*allows: bool, attempt_id: str = "a1", out_of_order: bool = False) -> str:
    """A REAL `TrustedLog.to_json_bytes()` output, not a hand-typed guess at
    its shape - proves `grade_recovery._trusted_log` parses what the real
    producer actually emits, not a mirror of it that could drift
    independently. `out_of_order` permutes the tuple's own order while
    keeping `seq` correct and ascending, exercising `to_json_bytes()`'s own
    seq-sort rather than this helper's."""
    decisions = [
        LoggedDecision(seq=i + 1, request={}, result={"allow": allow}, logged_at=float(i))
        for i, allow in enumerate(allows)
    ]
    if out_of_order:
        decisions = [decisions[-1], *decisions[:-1]] if len(decisions) > 1 else decisions
    trusted = TrustedLog(status="witnessed", attempt_id=attempt_id, decisions=tuple(decisions))
    return trusted.to_json_bytes().decode("utf-8")


def test_trusted_log_derives_failed_after_step_from_real_channel_bytes() -> None:
    text = _trusted_log_bytes(True, True, True, False)
    failed_after, reason = grade_recovery._trusted_log({"trusted": text})
    assert (failed_after, reason) == (3, "trusted")


def test_trusted_log_handles_a_genuinely_out_of_arrival_order_but_clean_log() -> None:
    # decide_reply_channel.py's own module docstring: seq is assigned in
    # COMPLETION order, not arrival order - a clean permutation is
    # legitimate and must still derive correctly, never refused.
    text = _trusted_log_bytes(True, True, True, False, out_of_order=True)
    failed_after, reason = grade_recovery._trusted_log({"trusted": text})
    assert (failed_after, reason) == (3, "trusted")


def test_trusted_log_reports_the_full_count_when_nothing_was_ever_refused() -> None:
    text = _trusted_log_bytes(True, True, True)
    failed_after, _ = grade_recovery._trusted_log({"trusted": text})
    assert failed_after == 3


def test_trusted_log_refuses_duplicate_seq_numbers() -> None:
    """THE RED CASE for the seq-validity check: two decisions claiming the
    same seq cannot come from a real channel (`_next_seq` is a strict
    per-decision counter) - refused, not silently sorted-and-accepted."""
    raw = json.loads(_trusted_log_bytes(True, True, False))
    raw["decisions"][2]["seq"] = raw["decisions"][1]["seq"]  # duplicate, not a clean 1..N set
    failed_after, reason = grade_recovery._trusted_log({"trusted": json.dumps(raw)})
    assert failed_after is None
    assert "not a clean 1..N sequence" in reason


def test_trusted_log_refuses_a_gap_in_seq_numbers() -> None:
    raw = json.loads(_trusted_log_bytes(True, True, False))
    raw["decisions"][2]["seq"] = 10  # a gap, not a clean 1..N set
    failed_after, reason = grade_recovery._trusted_log({"trusted": json.dumps(raw)})
    assert failed_after is None
    assert "not a clean 1..N sequence" in reason


def test_trusted_log_refuses_a_malformed_trusted_observation_not_silently() -> None:
    """(b) from the orchestrator's red cases: one byte flipped so the JSON
    breaks - refused with a reason naming it, distinct from "none was
    supplied" (a different, deliberate case, never folded together)."""
    text = _trusted_log_bytes(True, True, True, False)
    corrupted = text[:-1]  # truncate the closing brace - breaks JSON parsing
    failed_after, reason = grade_recovery._trusted_log({"trusted": corrupted})
    assert failed_after is None
    assert "not JSON" in reason
    # Genuinely absent is a DIFFERENT reason text - the two cases must not
    # be folded into one message a reader could mistake for the other.
    absent_after, absent_reason = grade_recovery._trusted_log({})
    assert absent_after is None
    assert absent_reason != reason
    assert "no trusted observation was supplied" in absent_reason


def test_trusted_log_refuses_a_bypass_and_an_unavailable_channel_alike() -> None:
    no_witness = TrustedLog(status="no-controller-witness", attempt_id="a1").to_json_bytes().decode()
    unavailable = TrustedLog(status="channel-unavailable", attempt_id="a1").to_json_bytes().decode()
    for text in (no_witness, unavailable):
        failed_after, reason = grade_recovery._trusted_log({"trusted": text})
        assert failed_after is None
        assert "never decided anything" in reason


def test_trusted_log_checks_attempt_id_only_when_the_caller_supplies_one() -> None:
    text = _trusted_log_bytes(True, True, True, False, attempt_id="the-real-attempt")
    # No expected id -> no check, the one-shot path's own contract.
    failed_after, reason = grade_recovery._trusted_log({"trusted": text})
    assert (failed_after, reason) == (3, "trusted")
    # Matching id -> same result.
    failed_after, reason = grade_recovery._trusted_log({"trusted": text}, "the-real-attempt")
    assert (failed_after, reason) == (3, "trusted")
    # THE RED CASE (b): a log genuinely produced for a DIFFERENT attempt -
    # refused, never silently graded as if it were this attempt's own.
    failed_after, reason = grade_recovery._trusted_log({"trusted": text}, "a-different-attempt")
    assert failed_after is None
    assert "does not match the attempt being graded" in reason


# --------------------------------------------- qualify.py's own harness (#183)


def test_qualify_never_trusts_a_file_planted_inside_the_candidate_tree(tmp_path: Path) -> None:
    """THE HEADLINE RED CASE for #183 PR B. Pre-PR-B, qualify.py read
    `trusted-disruption-log.json` from inside the candidate tree and
    graded `reference` SATISFIED on its say-so. Post-PR-B, that file is
    never read at all - planting one (even a perfectly plausible one,
    naming the real calibrated value) is refused outright, not silently
    ignored as "no observation supplied" (which would at least still
    grade; this must not grade at all, so the refusal cannot be missed)."""
    root = _copy_task(tmp_path)
    planted = root / "reference" / qualify.TRUSTED_LOG_NAME
    planted.write_text(json.dumps({"failed_after_step": 3}), encoding="utf-8")
    with pytest.raises(SystemExit, match="refuses"):
        qualify.status_of(root / "grade_recovery.py", root / "reference", root)


def test_qualify_refuses_a_controller_observation_whose_attempt_id_does_not_match(tmp_path: Path) -> None:
    """THE MISMATCH RED CASE. A controller observation genuinely produced
    for a different candidate (or copy-pasted by mistake) must never be
    graded as if it belonged to the candidate it is sitting next to -
    refused, not silently graded against the wrong attempt_id."""
    root = _copy_task(tmp_path)
    wrong_log = root / "controller-observations" / "wrong-work-loss.json"
    reference_log = root / "controller-observations" / "reference.json"
    reference_log.write_bytes(wrong_log.read_bytes())  # attempt_id now says "wrong-work-loss"
    with pytest.raises(SystemExit, match="does not match"):
        qualify.status_of(root / "grade_recovery.py", root / "reference", root)


def test_controller_observations_are_reproducible_from_the_committed_generator() -> None:
    """The committed `controller-observations/*.json` files are not hand-
    maintained - re-running the generator must produce the SAME decisions
    (ignoring `logged_at`, a wall-clock timestamp that genuinely differs
    run to run) for every candidate it covers, so a committed file that
    has silently drifted from what the generator actually produces is
    caught here rather than trusted forever."""
    generate_controller_observations = _load("generate_controller_observations")
    for candidate in generate_controller_observations.CANDIDATES:
        attempt_id = generate_controller_observations.attempt_id_for(candidate)
        committed = json.loads((TASK / "controller-observations" / f"{attempt_id}.json").read_text())
        fresh = json.loads(generate_controller_observations.generate(attempt_id))
        for entry in (*committed["decisions"], *fresh["decisions"]):
            del entry["logged_at"]
        assert committed == fresh
