"""The matched pilot's no-run deliverables (#12): the predeclared experiment
plans through the real controller, and the committed run manifest's numbers
are exactly what the SAME estimator #26 uses computes - never a hand-typed
number, and never a second estimator forked for this issue (orchestrator
instruction, msg 1410).

No paid model call happens anywhere in this file (ADR 0005 rule 5, the cost
stop): `trial.plan()` only ever writes a ledger to a throwaway store.
"""

from __future__ import annotations

import json
from pathlib import Path

from skillc import cost_estimate as ce
from skillc import trial as t

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "evals" / "matched-pilot"
MANIFEST = json.loads((PILOT_DIR / "run-manifest.json").read_text(encoding="utf-8"))
RECORD = MANIFEST["predeclared_experiment_record"]

_BASE_GRADER = json.loads((ROOT / RECORD["goal_population"]["task"]["grader"]).read_text(encoding="utf-8"))

_TREATMENT_SUBJECT_DIGEST = json.loads(
    (ROOT / "evals" / "subjects" / "cpp-codex" / "evidence" / "records" / "receipt.json").read_text(encoding="utf-8")
)["subject"]["digest"]

#: No baseline materialization has ever run for this pilot (an empty home
#: installs nothing, so there is no receipt to read a real digest from), and
#: the image digest is explicitly owed to the live build - see
#: `predeclared_experiment_record.image_digest_note`. Both are named
#: placeholders, never a value shaped like a real one (issue #10 lesson D13).
_BASELINE_SUBJECT_DIGEST = "sha256:0000000000000000000000000000000000000000000000000000000000baseline"

_PRICE = ce.ModelPrice(
    name=MANIFEST["cost_estimate"]["price"]["name"],
    input_usd_per_million=MANIFEST["cost_estimate"]["price"]["input_usd_per_million"],
    output_usd_per_million=MANIFEST["cost_estimate"]["price"]["output_usd_per_million"],
    source=MANIFEST["cost_estimate"]["price"]["source"],
)
_ASSUMED_INPUT_TOKENS_PER_ATTEMPT = MANIFEST["cost_estimate"]["assumptions"]["estimated_input_tokens_per_attempt"]
_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT = MANIFEST["cost_estimate"]["assumptions"]["estimated_output_tokens_per_attempt"]

_ARMS = ("treatment", "baseline")
_REPEATS_PER_ARM = MANIFEST["cost_estimate"]["repeats_per_arm"]


def _plan_spec() -> dict[str, object]:
    """Iterates repeat-then-arm, not arm-then-repeat: the predeclared
    `arm_order` states "treatment then baseline, PER REPEAT" (interleaved),
    which an arm-outer loop would instead plan as two separate temporal
    blocks (all treatment, then all baseline) - a mismatch between the
    predeclared schedule and the actual plan found by cross-model review."""
    trials = []
    for repeat in range(1, _REPEATS_PER_ARM + 1):
        for arm in _ARMS:
            trials.append({
                "label": f"matched_pilot_{arm}_{repeat}",
                "case": {"id": "matched-pilot", "revision": "c1"},
                "grader": {"id": _BASE_GRADER["id"], "revision": _BASE_GRADER["revision"]},
                "subject": {"digest": _TREATMENT_SUBJECT_DIGEST if arm == "treatment" else _BASELINE_SUBJECT_DIGEST},
                "client": {"name": RECORD["client"]["name"], "version": RECORD["client"]["version"]},
                "image": {"digest": RECORD["image_digest"]},
                "config": {"arm": arm, "repeat": repeat},
                "attempts": MANIFEST["cost_estimate"]["attempts_per_trial"],
            })
    return {"experiment": "matched-pilot", "trials": trials}


def test_the_matched_pilot_plans_through_the_real_controller(tmp_path: Path) -> None:
    """No paid call, no live agent - just the ledger the controller would
    issue before anything runs, for both arms across every repeat."""
    store = t.open_store(tmp_path / "store", forbidden=[])
    experiment = t.plan(_plan_spec(), store)
    trials = experiment.ledger["trials"]
    assert isinstance(trials, list)
    assert len(trials) == len(_ARMS) * _REPEATS_PER_ARM == MANIFEST["cost_estimate"]["total_attempts"]
    treatment_count = 0
    baseline_count = 0
    for trial in trials:
        assert isinstance(trial, dict)
        assert len(trial["attempts"]) == MANIFEST["cost_estimate"]["attempts_per_trial"]
        digest = trial["subject"]["digest"]
        if digest == _TREATMENT_SUBJECT_DIGEST:
            treatment_count += 1
        elif digest == _BASELINE_SUBJECT_DIGEST:
            baseline_count += 1
    assert treatment_count == _REPEATS_PER_ARM
    assert baseline_count == _REPEATS_PER_ARM


def test_the_planned_order_matches_the_predeclared_arm_order(tmp_path: Path) -> None:
    """Red case from cross-model review: the predeclared 'treatment then
    baseline, per repeat' order must be the ACTUAL planned sequence -
    interleaved (T,B,T,B,...), never two separate blocks (all treatment then
    all baseline)."""
    assert RECORD["arm_order"].startswith("treatment then baseline, per repeat")
    store = t.open_store(tmp_path / "store", forbidden=[])
    experiment = t.plan(_plan_spec(), store)
    trials = experiment.ledger["trials"]
    assert isinstance(trials, list)
    actual_order = [
        "treatment" if trial["subject"]["digest"] == _TREATMENT_SUBJECT_DIGEST else "baseline"
        for trial in trials
    ]
    expected_order = list(_ARMS) * _REPEATS_PER_ARM
    assert actual_order == expected_order


def test_the_committed_cost_estimate_matches_what_the_code_computes() -> None:
    """The run manifest's numbers are not hand-typed, and are produced by
    the SAME `skillc.cost_estimate` module #26 uses - no second estimator."""
    total_attempts = MANIFEST["cost_estimate"]["total_attempts"]
    cost = ce.estimate(
        trials=total_attempts,
        attempts_per_trial=1,
        estimated_input_tokens_per_attempt=_ASSUMED_INPUT_TOKENS_PER_ATTEMPT,
        estimated_output_tokens_per_attempt=_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        price=_PRICE,
    )
    manifest_cost = MANIFEST["cost_estimate"]
    assert cost.total_attempts == manifest_cost["total_attempts"]
    assert manifest_cost["price"]["input_usd_per_million"] == _PRICE.input_usd_per_million
    assert manifest_cost["price"]["output_usd_per_million"] == _PRICE.output_usd_per_million
    assert manifest_cost["assumptions"]["estimated_input_tokens_per_attempt"] == _ASSUMED_INPUT_TOKENS_PER_ATTEMPT
    assert manifest_cost["assumptions"]["estimated_output_tokens_per_attempt"] == _ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT
    assert cost.estimated_usd == manifest_cost["estimated_usd"]


def _committed_estimate() -> ce.RunCostEstimate:
    return ce.estimate(
        trials=MANIFEST["cost_estimate"]["total_attempts"],
        attempts_per_trial=1,
        estimated_input_tokens_per_attempt=_ASSUMED_INPUT_TOKENS_PER_ATTEMPT,
        estimated_output_tokens_per_attempt=_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        price=_PRICE,
    )


def test_the_estimate_is_within_the_operator_ceiling() -> None:
    """Operator ruling (msg 1401/1402, carried into #12 by msg 1410): the
    whole run must stay under $5. If this ever fails, report to the
    orchestrator and do not shrink the population to fit - never silently
    accept it."""
    assert _committed_estimate().estimated_usd <= ce.CEILING_USD
    assert MANIFEST["predeclared_experiment_record"]["monetary_ceiling_usd"] == ce.CEILING_USD


def test_authorize_agrees_with_the_manifests_own_execution_state() -> None:
    cost = _committed_estimate()
    try:
        ce.authorize(cost, approved_budget_usd=MANIFEST["approved_budget_usd"])
    except ce.SpendNotAuthorized:
        authorized = False
    else:
        authorized = True
    if MANIFEST["execution"].startswith("incomplete"):
        assert not authorized, "the manifest claims execution is incomplete, but authorize() would allow it"
    else:
        assert authorized, "the manifest claims execution may proceed, but authorize() refuses it"


def test_the_image_digest_is_named_as_owed_not_invented() -> None:
    """Orchestrator instruction (msg 1410): the image digest is owed to the
    live build - say so rather than invent a value that looks like a real
    one. A hash-shaped placeholder (e.g. 'sha256:000...') would read as data;
    this must not be that shape."""
    digest = RECORD["image_digest"]
    assert not digest.startswith("sha256:")
    assert "owed" in digest


def test_goal_population_reuses_the_already_qualified_grader_not_a_new_one() -> None:
    task = RECORD["goal_population"]["task"]
    assert task["id"] == "slug-small-fix"
    assert task["id"] == _BASE_GRADER["id"]
    assert task["revision"] == _BASE_GRADER["revision"]


def test_clarification_and_approval_behavior_are_both_stated() -> None:
    behavior = RECORD["clarification_and_approval_behavior"]
    assert behavior["clarification"]
    assert behavior["approval"]
