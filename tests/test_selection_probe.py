"""The selection probe's no-run deliverables (#26): the three predeclared
cases plan through the real controller, and the committed run manifest's
numbers are exactly what that plan and the cost estimator compute - never a
hand-typed number that could drift from the code that is supposed to produce
it.

No paid model call happens anywhere in this file (ADR 0005 rule 5, the cost
stop): `trial.plan()` only ever writes a ledger to a throwaway store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillc import cost_estimate as ce
from skillc import selection_probe as sp
from skillc import trial as t
from skillc import verify

ROOT = Path(__file__).resolve().parent.parent
PROBE_DIR = ROOT / "evals" / "selection-probe"
CASES = json.loads((PROBE_DIR / "cases.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((PROBE_DIR / "run-manifest.json").read_text(encoding="utf-8"))

_TREATMENT_SUBJECT_DIGEST = json.loads(
    (ROOT / "evals" / "subjects" / "cpp-codex" / "evidence" / "records" / "receipt.json").read_text(encoding="utf-8")
)["subject"]["digest"]

#: No baseline materialization has ever run for this probe (an empty home
#: installs nothing, so there is no receipt to read a real digest from) and
#: no image has been built (#77's Docker backend implementation is a
#: follow-up PR). Both are named placeholders rather than silently
#: plausible-looking values (issue #10 lesson D13: pin the digest of what
#: actually ran, never one that merely looks real).
_BASELINE_SUBJECT_DIGEST = "sha256:0000000000000000000000000000000000000000000000000000000000baseline"
_PLACEHOLDER_IMAGE_DIGEST = "sha256:0000000000000000000000000000000000000000000000000000000000pending"

_PRICE = ce.ModelPrice(
    name=MANIFEST["cost_estimate"]["price"]["name"],
    input_usd_per_million=MANIFEST["cost_estimate"]["price"]["input_usd_per_million"],
    output_usd_per_million=MANIFEST["cost_estimate"]["price"]["output_usd_per_million"],
    source=MANIFEST["cost_estimate"]["price"]["source"],
)
_ASSUMED_INPUT_TOKENS_PER_ATTEMPT = MANIFEST["cost_estimate"]["assumptions"]["estimated_input_tokens_per_attempt"]
_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT = MANIFEST["cost_estimate"]["assumptions"]["estimated_output_tokens_per_attempt"]

_ARMS = ("treatment", "baseline")


def _plan(tmp_path: Path) -> t.Experiment:
    """Each case plans BOTH arms as its own trial - a Codex code-review
    finding on #26 caught an earlier version that planned only one arm per
    case while the manifest's own `treatment_vs_baseline` section (and #26's
    own text: "matched minimal baseline") requires both, and both arms need a
    real paid attempt (the baseline arm must show no skill invoked, which
    needs the same live call the treatment arm does). Delegates to
    `selection_probe.plan_selection_probe` - the ONE place this shape is
    built (#26's run driver reuses it too), rather than a second copy here
    that could drift from it."""
    store = t.open_store(tmp_path / "store", forbidden=[])
    return sp.plan_selection_probe(
        CASES, MANIFEST, treatment_subject_digest=_TREATMENT_SUBJECT_DIGEST,
        baseline_subject_digest=_BASELINE_SUBJECT_DIGEST, image_digest=_PLACEHOLDER_IMAGE_DIGEST, store=store,
    )


def test_the_three_cases_plan_through_the_real_controller(tmp_path: Path) -> None:
    """No paid call, no live agent - just the ledger the controller would
    issue before anything runs. Proves the case format (#26's
    `observes_selection` field) round-trips through `trial.plan()` for real,
    not merely through a hand-written fixture, for BOTH arms of all three
    cases."""
    experiment = _plan(tmp_path)
    trials = experiment.ledger["trials"]
    assert isinstance(trials, list)
    assert len(trials) == len(CASES["cases"]) * len(_ARMS) == MANIFEST["cost_estimate"]["trials"] * MANIFEST["cost_estimate"]["arms_per_case"]
    for trial in trials:
        assert isinstance(trial, dict)
        assert trial["case"]["observes_selection"] is True
        assert len(trial["attempts"]) == MANIFEST["repeat_schedule"]["attempts_per_trial"]
    case_ids = {trial["case"]["id"] for trial in trials}  # type: ignore[index]
    assert case_ids == {case["id"] for case in CASES["cases"]}


def test_the_committed_cost_estimate_matches_what_the_code_computes() -> None:
    """The run manifest's numbers are not hand-typed: recompute them here and
    assert EVERY published field - population, price rates and token
    assumptions, not merely the final dollar figure - equals the committed
    file. A Codex code-review finding on #26 caught an earlier version that
    checked only `total_attempts`/`estimated_usd`/price name, which a
    manifest with a wrong stated price or token assumption could still pass
    if the final number happened to agree by coincidence."""
    trials = len(CASES["cases"])
    arms_per_case = len(_ARMS)
    attempts_per_trial = MANIFEST["repeat_schedule"]["attempts_per_trial"]
    cost = ce.estimate(
        trials=trials * arms_per_case,
        attempts_per_trial=attempts_per_trial,
        estimated_input_tokens_per_attempt=_ASSUMED_INPUT_TOKENS_PER_ATTEMPT,
        estimated_output_tokens_per_attempt=_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        price=_PRICE,
    )
    manifest_cost = MANIFEST["cost_estimate"]
    assert manifest_cost["trials"] == trials
    assert manifest_cost["arms_per_case"] == arms_per_case
    assert manifest_cost["attempts_per_trial"] == attempts_per_trial
    assert cost.total_attempts == manifest_cost["total_attempts"]
    assert manifest_cost["price"]["input_usd_per_million"] == _PRICE.input_usd_per_million
    assert manifest_cost["price"]["output_usd_per_million"] == _PRICE.output_usd_per_million
    assert manifest_cost["assumptions"]["estimated_input_tokens_per_attempt"] == _ASSUMED_INPUT_TOKENS_PER_ATTEMPT
    assert manifest_cost["assumptions"]["estimated_output_tokens_per_attempt"] == _ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT
    # ADR 0005 rule 6: relabelled as a quota/usage figure, not a dollar charge
    # (this probe's agent attempts run under the operator's normal Codex
    # subscription login) - still the exact number `estimate()` computes.
    assert cost.estimated_usd == manifest_cost["estimated_agent_quota_usd_equivalent"]
    assert manifest_cost["judge_estimated_quota_usd_equivalent"] == 0.0
    assert cost.judge_estimated_usd == 0.0


def _committed_estimate() -> ce.RunCostEstimate:
    trials = len(CASES["cases"]) * len(_ARMS)
    return ce.estimate(
        trials=trials,
        attempts_per_trial=MANIFEST["repeat_schedule"]["attempts_per_trial"],
        estimated_input_tokens_per_attempt=_ASSUMED_INPUT_TOKENS_PER_ATTEMPT,
        estimated_output_tokens_per_attempt=_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        price=_PRICE,
    )


def test_the_judge_spend_is_within_the_operator_ceiling() -> None:
    """Operator ruling (ADR 0005 rule 6): dollar-metered JUDGE spend must
    stay under $5 - this probe's agent-attempt quota is not dollar-metered
    (subscription login) and is never checked against this ceiling (Codex
    code-review finding: an earlier version of this test checked the
    combined total, which would have wrongly rejected a future manifest
    whose agent quota grew large with $0 judge spend). If judge spend ever
    exceeds the ceiling, the estimate must be reported to the orchestrator
    and the run must NOT proceed - never silently accepted."""
    assert _committed_estimate().judge_estimated_usd <= ce.CEILING_USD


def test_a_large_agent_quota_alone_does_not_breach_the_ceiling() -> None:
    """Red case for the fix above: an agent-only figure well over $5 (this
    probe's own token-assumption-sensitivity note names 1,000,000
    input-tokens/attempt as producing an over-$5 COMBINED total) must still
    authorize in subscription mode, because the ceiling gates judge spend
    alone. The pre-fix combined-total check would have rejected this."""
    huge_agent_only = ce.estimate(
        trials=len(CASES["cases"]) * len(_ARMS),
        attempts_per_trial=MANIFEST["repeat_schedule"]["attempts_per_trial"],
        estimated_input_tokens_per_attempt=1_000_000,
        estimated_output_tokens_per_attempt=_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        price=_PRICE,
    )
    assert huge_agent_only.estimated_usd > ce.CEILING_USD, "the agent-only figure must exceed the ceiling for this control to mean anything"
    assert huge_agent_only.judge_estimated_usd == 0.0
    ce.authorize(
        huge_agent_only, approved_budget_usd=None, agent_uses_subscription_login=True,
    )  # must not raise - no judge spend to gate, however large the agent quota


def test_authorize_agrees_with_the_manifests_own_execution_state() -> None:
    """The manifest is a subscription-login run (ADR 0005 rule 6) with no
    judge tier enabled, so `authorize()` in that mode succeeds
    unconditionally - $0 of dollar-metered spend needs no budget approval.
    The manifest's own `execution` field stays "incomplete" for a DIFFERENT,
    still-real reason (issue #98's in-container credential path,
    skillc/trial.py's execution loop), so the two facts are checked
    independently rather than via the old one-to-one implication a plain
    dollar gate used to support (Codex code-review finding on #26, the
    original version of this test)."""
    cost = _committed_estimate()
    ce.authorize(
        cost, approved_budget_usd=MANIFEST["approved_budget_usd"], agent_uses_subscription_login=True,
    )  # must not raise: no judge tier enabled, so judge spend is $0
    assert MANIFEST["execution"].startswith("incomplete"), (
        "execution should still name #98/trial.py as the real blocker, not a dollar gate"
    )


def test_authorize_refuses_an_estimate_over_the_ceiling() -> None:
    """Red case: the operator's $5 ceiling (ADR 0005 rule 6) is refused
    regardless of any approved budget, however large."""
    over_ceiling = ce.estimate(
        trials=1000, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=_ASSUMED_INPUT_TOKENS_PER_ATTEMPT,
        estimated_output_tokens_per_attempt=_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        price=_PRICE,
    )
    assert over_ceiling.estimated_usd > ce.CEILING_USD
    try:
        ce.authorize(over_ceiling, approved_budget_usd=1_000_000.0)
    except ce.SpendNotAuthorized:
        pass
    else:
        raise AssertionError("authorize() must refuse an over-ceiling estimate even with an enormous approved budget")


def test_every_case_publishes_at_least_one_allowed_choice() -> None:
    """#26's own requirement: publish allowed choices before observing
    results."""
    for case in CASES["cases"]:
        assert case["allowed_choices"], f"{case['id']} publishes no allowed choice"


def test_the_near_miss_case_allows_no_skill_and_names_no_applicable_skill() -> None:
    near_miss = next(c for c in CASES["cases"] if c["kind"] == "near-miss")
    assert near_miss["applicable_skills"] == []


def test_the_overlapping_choice_case_names_two_applicable_skills() -> None:
    overlap = next(c for c in CASES["cases"] if c["kind"] == "overlapping-choice")
    assert len(overlap["applicable_skills"]) == 2


# --------------------------------------------------------------------------
# The run driver (#26's own live-run half): a FAKE AttemptRunner throughout -
# lifecycle.py's own guard already refuses to launch claude/codex without
# SKILLC_ALLOW_REAL_AGENT=1, and none of these fakes ever call execute() at
# all, so nothing here could accidentally spend against a real subscription.
# --------------------------------------------------------------------------


import os
import stat

GOOD_CANDIDATE = ROOT / "evals" / "level1" / "slug-small-fix" / "reference"
BAD_CANDIDATE = ROOT / "evals" / "level1" / "slug-small-fix" / "wrong" / "no-lowercase"
GRADER = verify.GraderDef.load(ROOT / "evals" / "level1" / "slug-small-fix")

INTENDED_USE = "selection-probe-intended-use"
NEAR_MISS = "selection-probe-near-miss"
OVERLAPPING = "selection-probe-overlapping-choice"


def _candidate_files(candidate_dir: Path) -> tuple[tuple[str, bytes, bool], ...]:
    """The same walk `skillc.demo`'s own grading demo uses - reused here
    rather than reinvented, since #81 already established it against this
    exact fixture shape."""
    files: list[tuple[str, bytes, bool]] = []
    for dirpath, dirnames, filenames in os.walk(candidate_dir, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            path = Path(dirpath) / name
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                rel = path.relative_to(candidate_dir).as_posix()
                files.append((rel, path.read_bytes(), bool(info.st_mode & stat.S_IXUSR)))
    return tuple(files)


def _transcript(
    disposition: str = "captured", skills: tuple[str, ...] = (), good: bool = True,
) -> sp.AttemptTranscript:
    events: tuple[dict[str, object], ...] = tuple({"type": "skill_invocation", "skill": s} for s in skills)
    candidate = _candidate_files(GOOD_CANDIDATE if good else BAD_CANDIDATE)
    return sp.AttemptTranscript(disposition=disposition, events=events, candidate_files=candidate)


def _fake_runner(overrides: dict[tuple[str, str], sp.AttemptTranscript]) -> sp.AttemptRunner:
    """Keyed by (case_id, arm) - every combination not named in `overrides`
    gets the default: captured, nothing invoked, the good candidate."""
    def runner(trial_dict: dict[str, object], attempt: dict[str, object]) -> sp.AttemptTranscript | None:
        case = trial_dict["case"]
        config = trial_dict["config"]
        assert isinstance(case, dict) and isinstance(config, dict)
        key = (str(case["id"]), str(config["arm"]))
        return overrides.get(key, _transcript())
    return runner


def _run(overrides: dict[tuple[str, str], sp.AttemptTranscript], tmp_path: Path) -> sp.SelectionProbeReport:
    store = t.open_store(tmp_path / "store", forbidden=[])
    return sp.run_selection_probe(
        CASES, MANIFEST, _fake_runner(overrides),
        treatment_subject_digest=_TREATMENT_SUBJECT_DIGEST, baseline_subject_digest=_BASELINE_SUBJECT_DIGEST,
        image_digest=_PLACEHOLDER_IMAGE_DIGEST, store=store, base=tmp_path / "grading", grader=GRADER,
    )


def _case(report: sp.SelectionProbeReport, case_id: str) -> sp.CaseResult:
    return next(c for c in report.cases if c.case_id == case_id)


def test_run_selection_probe_happy_path(tmp_path: Path) -> None:
    """Each treatment arm invokes exactly its own applicable skill(s) with a
    good candidate; every baseline arm invokes nothing. Selection and task
    success are reported correctly, and no baseline is contaminated."""
    overrides = {
        (INTENDED_USE, "treatment"): _transcript(skills=("qa-test",)),
        (OVERLAPPING, "treatment"): _transcript(skills=("security-scan",)),
        # near-miss's own treatment arm invokes nothing - the default.
    }
    report = _run(overrides, tmp_path)
    assert len(report.cases) == 3

    intended = _case(report, INTENDED_USE)
    assert intended.treatment.selection == "selected"
    assert intended.treatment.task_success is True
    assert intended.baseline.selection == "not-selected"
    assert intended.baseline_contaminated is False

    near_miss = _case(report, NEAR_MISS)
    assert near_miss.treatment.selection == "not-selected"
    assert near_miss.baseline.selection == "not-selected"

    overlap = _case(report, OVERLAPPING)
    assert overlap.treatment.selection == "selected"


def test_run_selection_probe_reports_task_failure_independently_of_selection(tmp_path: Path) -> None:
    """A correct result without invoking the applicable skill is still a
    SUCCESS (#26's own text) - and an invocation with a WRONG fix is still a
    FAILURE. Selection and task success are reported side by side, neither
    one inferred from the other."""
    overrides = {
        # Invoked qa-test but the candidate is still wrong: selected, failed.
        (INTENDED_USE, "treatment"): _transcript(skills=("qa-test",), good=False),
        # Invoked nothing but got the fix right anyway: not-selected, succeeded.
        (OVERLAPPING, "treatment"): _transcript(skills=(), good=True),
    }
    report = _run(overrides, tmp_path)
    intended = _case(report, INTENDED_USE)
    assert intended.treatment.selection == "selected"
    assert intended.treatment.task_success is False

    overlap = _case(report, OVERLAPPING)
    assert overlap.treatment.selection == "not-selected"
    assert overlap.treatment.task_success is True


def test_a_baseline_invocation_is_flagged_as_contamination(tmp_path: Path) -> None:
    """Red case (#26, orchestrator's own named check): a baseline arm that
    shows a skill invocation must be flagged, however the task itself
    turned out."""
    overrides = {
        (NEAR_MISS, "baseline"): _transcript(skills=("qa-test",)),
    }
    report = _run(overrides, tmp_path)
    near_miss = _case(report, NEAR_MISS)
    assert near_miss.baseline.selection == "selected"
    assert near_miss.baseline_contaminated is True
    # Every OTHER case's baseline is untouched and must read clean.
    assert _case(report, INTENDED_USE).baseline_contaminated is False
    assert _case(report, OVERLAPPING).baseline_contaminated is False


def test_a_blocked_treatment_attempt_is_unknown_never_not_selected(tmp_path: Path) -> None:
    """Red case (#26, orchestrator's own named check): a treatment attempt
    that is BLOCKED (`disposition="unavailable"`) or UNKNOWN
    (`disposition="inconclusive"`) must never be counted as "not-selected" -
    that would silently manufacture a negative selection conclusion from an
    attempt that never ran cleanly. Task success is also None, never a
    guessed PASS/FAIL, for the same reason."""
    overrides = {
        (INTENDED_USE, "treatment"): sp.AttemptTranscript(disposition="unavailable"),
        (OVERLAPPING, "treatment"): sp.AttemptTranscript(disposition="inconclusive"),
    }
    report = _run(overrides, tmp_path)
    intended = _case(report, INTENDED_USE)
    assert intended.treatment.selection == "unknown"
    assert intended.treatment.selection != "not-selected"
    assert intended.treatment.task_success is None

    overlap = _case(report, OVERLAPPING)
    assert overlap.treatment.selection == "unknown"
    assert overlap.treatment.task_success is None


def test_report_refuses_when_an_attempt_is_missing(tmp_path: Path) -> None:
    """Red case (#26, orchestrator's own named check, and CLAUDE.md's own
    Negative Control directive: an instrument that cannot fail is not
    evidence): a runner that returns `None` for one planned attempt - never
    launched at all, never a captured-but-unavailable result - must refuse
    the whole report rather than silently producing one short an attempt."""
    def flaky_runner(trial_dict: dict[str, object], attempt: dict[str, object]) -> sp.AttemptTranscript | None:
        case = trial_dict["case"]
        assert isinstance(case, dict)
        if case["id"] == INTENDED_USE:
            return None  # never even attempted
        return _transcript()

    store = t.open_store(tmp_path / "store", forbidden=[])
    with pytest.raises(sp.SelectionProbeRefused):
        sp.run_selection_probe(
            CASES, MANIFEST, flaky_runner,
            treatment_subject_digest=_TREATMENT_SUBJECT_DIGEST, baseline_subject_digest=_BASELINE_SUBJECT_DIGEST,
            image_digest=_PLACEHOLDER_IMAGE_DIGEST, store=store,
            base=tmp_path / "grading", grader=GRADER,
        )


def test_selection_status_a_non_captured_disposition_is_always_unknown() -> None:
    """Direct unit coverage of the rule the two red cases above exercise
    end to end: EVERY non-"captured" disposition in `records.DISPOSITIONS`
    reports "unknown", regardless of what `events` claims to show."""
    for disposition in ("not-run", "unavailable", "inconclusive"):
        transcript = sp.AttemptTranscript(
            disposition=disposition, events=({"type": "skill_invocation", "skill": "qa-test"},),
        )
        assert sp.selection_status(transcript, ["qa-test"]) == "unknown"


def test_selection_status_captured_with_no_applicable_skill_reports_selected_on_any_invocation() -> None:
    """The near-miss/baseline shape directly: zero applicable skills, one
    invoked anyway - "selected" is this function's own contamination/false-
    positive signal, not a bug."""
    transcript = sp.AttemptTranscript(
        disposition="captured", events=({"type": "skill_invocation", "skill": "anything"},),
    )
    assert sp.selection_status(transcript, []) == "selected"
    clean = sp.AttemptTranscript(disposition="captured", events=())
    assert sp.selection_status(clean, []) == "not-selected"
