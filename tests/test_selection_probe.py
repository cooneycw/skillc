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
        allow_host_grading=True,  # committed fixture candidates only - never an agent's output
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
            base=tmp_path / "grading", grader=GRADER, allow_host_grading=True,
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



# --------------------------------------------------- refusals before any run


def _counting_runner() -> tuple[sp.AttemptRunner, list[str]]:
    calls: list[str] = []

    def runner(trial_dict: dict[str, object], attempt: dict[str, object]) -> sp.AttemptTranscript | None:
        calls.append(str(attempt["attempt_id"]))
        return _transcript()
    return runner, calls


def test_no_grading_backend_is_refused_before_any_attempt_runs(tmp_path: Path) -> None:
    """With no grading backend, `verify.grade_files` executes the candidate
    on the HOST - so a run that has not opted in is refused before the
    runner is called even once. Confirmed red when the check is removed: all
    six attempts run and their output is probed on the host."""
    runner, calls = _counting_runner()
    with pytest.raises(sp.SelectionProbeRefused, match="grading_backend"):
        sp.run_selection_probe(
            CASES, MANIFEST, runner,
            treatment_subject_digest=_TREATMENT_SUBJECT_DIGEST, baseline_subject_digest=_BASELINE_SUBJECT_DIGEST,
            image_digest=_PLACEHOLDER_IMAGE_DIGEST, store=t.open_store(tmp_path / "store", forbidden=[]),
            base=tmp_path / "grading", grader=GRADER,
        )
    assert calls == []


def test_a_repeated_attempt_is_refused_before_any_attempt_runs(tmp_path: Path) -> None:
    """The report carries one result per arm, so a second attempt would pass
    attendance and then vanish - a contaminated second baseline would read
    as clean. Refused up front instead. Confirmed red when the check is
    removed: the run completes and reports the first attempt only."""
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["repeat_schedule"]["attempts_per_trial"] = 2
    runner, calls = _counting_runner()
    with pytest.raises(sp.SelectionProbeRefused, match="more than one attempt"):
        sp.run_selection_probe(
            CASES, manifest, runner,
            treatment_subject_digest=_TREATMENT_SUBJECT_DIGEST, baseline_subject_digest=_BASELINE_SUBJECT_DIGEST,
            image_digest=_PLACEHOLDER_IMAGE_DIGEST, store=t.open_store(tmp_path / "store", forbidden=[]),
            base=tmp_path / "grading", grader=GRADER, allow_host_grading=True,
        )
    assert calls == []


def test_selection_is_judged_against_the_frozen_plan_not_the_supplied_cases(tmp_path: Path) -> None:
    """Editing a case's `applicable_skills` after planning (same revision)
    cannot change a verdict: the planned, content-addressed configuration
    decides. Confirmed red when report assembly reads `cases` instead: the
    recorded qa-test invocation flips from "selected" to "not-selected"."""
    experiment = _plan(tmp_path)
    edited = json.loads(json.dumps(CASES))
    for case in edited["cases"]:
        if case["id"] == INTENDED_USE:
            case["applicable_skills"] = ["something-else"]
    report = sp.run_planned_selection_probe(
        experiment, edited, _fake_runner({(INTENDED_USE, "treatment"): _transcript(skills=("qa-test",))}),
        base=tmp_path / "grading", grader=GRADER, allow_host_grading=True,
    )
    intended = _case(report, INTENDED_USE)
    assert intended.treatment.selection == "selected"
    assert intended.applicable_skills == ("qa-test",)


def test_a_case_revision_that_differs_from_the_plan_is_refused(tmp_path: Path) -> None:
    experiment = _plan(tmp_path)
    edited = json.loads(json.dumps(CASES))
    edited["cases"][0]["revision"] = "c-edited"
    runner, calls = _counting_runner()
    with pytest.raises(sp.SelectionProbeRefused, match="revision"):
        sp.run_planned_selection_probe(
            experiment, edited, runner, base=tmp_path / "grading", grader=GRADER, allow_host_grading=True,
        )
    assert calls == []


def test_an_inconclusive_grade_is_unknown_never_a_task_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A grade that reached no verdict is a fact about the grading, not the
    candidate - `task_success` is `None` and the grader's reason is kept.
    Confirmed red on the old `status == "PASS"` mapping: it reports `False`."""
    def inconclusive(*_args: object, **_kwargs: object) -> verify.Graded:
        return verify.Graded(
            status="INCONCLUSIVE", category="containment", detail="the probe was not contained: test",
            criteria=[], containment={},
        )
    monkeypatch.setattr(sp.verify, "grade_files", inconclusive)
    report = _run({}, tmp_path)
    treatment = _case(report, INTENDED_USE).treatment
    assert treatment.task_success is None
    assert "INCONCLUSIVE" in treatment.detail and "not contained" in treatment.detail


# --------------------------------------------------------------------------
# The REAL AttemptRunner (`agent_trial_runner`), end to end on the fake
# `docker` CLI and the scripted fake client `tests/test_agent_trial.py`
# already uses - `run_one_attempt` for real, every planned attempt, no real
# daemon and no real agent binary.
# --------------------------------------------------------------------------

import dataclasses
import sys
import time
from base64 import urlsafe_b64encode
from collections.abc import Callable

from skillc import docker_backend as d

FAKE_DOCKER = ROOT / "tests" / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = ROOT / "tests" / "fixtures" / "agent-trial" / "fake_agent_client.py"

#: The collection the treatment arm receives, in the codex skills layout -
#: the three skills the cases name, plus one no case names.
_COLLECTION = {
    f".codex/skills/{name}/SKILL.md": f"---\nname: {name}\ndescription: A test skill.\n---\nBody.\n".encode()
    for name in ("qa-test", "security-scan", "security-deep", "unrelated-skill")
}


class _HomeRecordingBackend(d.DockerBackend):
    """Records every `deliver_home_file` path per attempt - the container is
    destroyed before `run_one_attempt` returns, so this is the only place to
    see what each arm's home actually received."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.delivered: dict[str, list[str]] = {}

    def deliver_home_file(self, handle: object, container_relpath: str, data: bytes, *, mode: int = 0o600) -> None:
        super().deliver_home_file(handle, container_relpath, data, mode=mode)
        self.delivered.setdefault(str(handle.attempt_id), []).append(container_relpath)  # type: ignore[attr-defined]


def _codex_credential(tmp_path: Path) -> Path:
    def seg(data: bytes) -> str:
        return urlsafe_b64encode(data).rstrip(b"=").decode()
    token = f"{seg(json.dumps({'alg': 'none'}).encode())}.{seg(json.dumps({'exp': int(time.time() + 3600)}).encode())}.sig"
    path = tmp_path / "codex-credential.json"
    path.write_text(json.dumps({"tokens": {"access_token": token}}))
    return path


def _script(
    *, plant: tuple[str, ...] = (), candidate: Path | None = GOOD_CANDIDATE, fail_canary: bool = False,
) -> dict[str, object]:
    return {"plant": plant, "candidate": candidate, "fail_canary": fail_canary}


def _argv_for(
    experiment: t.Experiment, docker_state: Path, scripts: dict[tuple[str, str], dict[str, object]],
) -> Callable[[str], list[str]]:
    """`argv_for(attempt_id)`: the fake client's argv for whichever (case,
    arm) that attempt belongs to - the fake docker maps CONTAINER_HOME to a
    host path named after the attempt, which is why the real runner takes a
    per-attempt argv function at all."""
    def argv_for(attempt_id: str) -> list[str]:
        trial_dict = sp._resolved_trial(experiment, experiment.trial_of(attempt_id))
        key = (str(trial_dict["case"]["id"]), str(trial_dict["config"]["arm"]))  # type: ignore[index]
        script = scripts.get(key, _script())
        home = docker_state / f"{d._container_name(attempt_id)}.fsroot" / "home" / "candidate"
        argv = [
            sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
            "--transcript-relpath", f".codex/sessions/2026/01/01/rollout-{attempt_id}.jsonl",
        ]
        if script["candidate"] is not None:
            argv.extend(["--copy-solution", str(script["candidate"])])
        if script["fail_canary"]:
            argv.append("--fail-canary")
        for skill in script["plant"]:  # type: ignore[attr-defined]
            argv.extend(["--plant-skill", str(skill)])
        return argv
    return argv_for


def _run_real(
    tmp_path: Path, scripts: dict[tuple[str, str], dict[str, object]],
) -> tuple[sp.SelectionProbeReport, t.Experiment, _HomeRecordingBackend]:
    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    docker_bin = [sys.executable, str(FAKE_DOCKER), "--state", str(docker_state)]
    backend = _HomeRecordingBackend(image="fake-image:1", base_dir=base, docker_bin=docker_bin)
    grading_backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=docker_bin)
    experiment = sp.plan_selection_probe(
        CASES, MANIFEST, treatment_subject_digest=_TREATMENT_SUBJECT_DIGEST,
        baseline_subject_digest=_BASELINE_SUBJECT_DIGEST, image_digest=_PLACEHOLDER_IMAGE_DIGEST,
        store=t.open_store(tmp_path / "store", forbidden=[]),
    )
    runner = sp.agent_trial_runner(
        experiment=experiment, backend=backend, base=base, client="codex",
        argv_for=_argv_for(experiment, docker_state, scripts), treatment_home_files=_COLLECTION,
        goal="Fix the slug helper.", timeout=5, credential_explicit_path=_codex_credential(tmp_path),
    )
    report = sp.run_planned_selection_probe(
        experiment, CASES, runner, base=base, grader=GRADER, grading_backend=grading_backend,
    )
    return report, experiment, backend


def _arm_of(experiment: t.Experiment, attempt_id: str) -> str:
    return str(sp._resolved_trial(experiment, experiment.trial_of(attempt_id))["config"]["arm"])  # type: ignore[index]


def test_agent_trial_runner_end_to_end_reports_selection_and_outcome_separately(tmp_path: Path) -> None:
    """Every planned attempt through `run_one_attempt`: intended use picks
    its skill and fixes the task; the near miss picks nothing and fixes it;
    the overlapping case picks one of its pair but ships a wrong fix - so
    selection and task success disagree there, and both are reported."""
    report, _experiment, _backend = _run_real(tmp_path, {
        (INTENDED_USE, "treatment"): _script(plant=("qa-test",)),
        (OVERLAPPING, "treatment"): _script(plant=("security-deep",), candidate=BAD_CANDIDATE),
    })

    intended, near_miss, overlapping = (_case(report, c) for c in (INTENDED_USE, NEAR_MISS, OVERLAPPING))
    assert (intended.treatment.selection, intended.treatment.task_success) == ("selected", True)
    assert (near_miss.treatment.selection, near_miss.treatment.task_success) == ("not-selected", True)
    assert (overlapping.treatment.selection, overlapping.treatment.task_success) == ("selected", False)
    assert overlapping.treatment.observed == frozenset({"security-deep"})
    for case in (intended, near_miss, overlapping):
        assert case.baseline.selection == "not-selected"
        assert case.baseline.task_success is True
        assert not case.baseline_contaminated
        # codex has no structural skill marker - never reported as structural
        assert case.treatment.codex_best_effort and case.baseline.codex_best_effort


def test_agent_trial_runner_installs_the_collection_in_the_treatment_arm_only(tmp_path: Path) -> None:
    """The baseline arm's meaning is "no skill installed" - enforced by the
    runner, not trusted to the caller, which passes ONE collection for every
    attempt. Confirmed red when the runner delivers `treatment_home_files` to
    both arms: every baseline attempt then receives the four SKILL.md files."""
    _report, experiment, backend = _run_real(tmp_path, {})
    skills = {path for path in _COLLECTION}
    assert len(backend.delivered) == 6  # every planned attempt launched
    for attempt_id, paths in backend.delivered.items():
        received = skills & set(paths)
        if _arm_of(experiment, attempt_id) == "treatment":
            assert received == skills
        else:
            assert received == set()


def test_agent_trial_runner_flags_a_baseline_invocation_as_contamination(tmp_path: Path) -> None:
    """A skill invocation in the baseline arm - nothing installed there to
    invoke - is the contamination signal, observed through the real record."""
    report, _experiment, _backend = _run_real(tmp_path, {(NEAR_MISS, "baseline"): _script(plant=("qa-test",))})
    assert _case(report, NEAR_MISS).baseline_contaminated
    assert not _case(report, INTENDED_USE).baseline_contaminated


def test_agent_trial_runner_an_unconfirmed_transcript_is_unknown_and_ungraded(tmp_path: Path) -> None:
    """A captured attempt whose canary was not confirmed is BLOCKED (#106):
    its invocation is not reported as a selection, and its output is not
    graded - even though the transcript shows the applicable skill and the
    candidate is the correct fix. Confirmed red when `transcript_from_record`
    drops its `grading_eligible` check: the attempt reports "selected" and
    task success True."""
    report, _experiment, _backend = _run_real(tmp_path, {
        (INTENDED_USE, "treatment"): _script(plant=("qa-test",), fail_canary=True),
    })
    treatment = _case(report, INTENDED_USE).treatment
    assert treatment.disposition == "inconclusive"
    assert treatment.selection == "unknown"
    assert treatment.task_success is None


def test_transcript_from_record_never_turns_a_blocked_attempt_into_not_selected(tmp_path: Path) -> None:
    """Every non-captured disposition, and a captured one with an unknown
    observation, translates to a transcript whose selection is "unknown" -
    never "not-selected" (#26: do not substitute for an unavailable
    observation)."""
    experiment = _plan(tmp_path)
    for record in (
        {"disposition": "unavailable", "observation": None},
        {"disposition": "not-run"},
        {"disposition": "inconclusive", "observation": {"skill_invocations": ["qa-test"]}},
        {"disposition": "captured", "observation": {"status": "unknown", "reason": "hook failed"}},
        {"disposition": "captured"},
    ):
        transcript = sp.transcript_from_record(record, experiment, "unused")
        assert transcript.disposition != "captured"
        assert sp.selection_status(transcript, ["qa-test"]) == "unknown"



def _real_runner_parts(tmp_path: Path) -> tuple[t.Experiment, sp.AgentTrialRunner, list[str]]:
    base = tmp_path / "work"
    base.mkdir()
    docker_bin = [sys.executable, str(FAKE_DOCKER), "--state", str(tmp_path / "docker-state")]
    experiment = _plan(tmp_path)
    backend = _HomeRecordingBackend(image="fake-image:1", base_dir=base, docker_bin=docker_bin)
    runner = sp.agent_trial_runner(
        experiment=experiment, backend=backend, base=base, client="codex",
        argv_for=lambda _a: [], treatment_home_files=_COLLECTION, goal="x",
    )
    return experiment, runner, docker_bin


def test_grading_in_the_agents_own_backend_is_refused_before_any_attempt(tmp_path: Path) -> None:
    """interfaces.md step 8: grading runs in a SEPARATE instance. The runner
    exposes its backend, so passing the same one to grade is refused before
    anything launches. Confirmed red when the identity check is removed: the
    run launches (and here fails on the empty argv) instead of refusing."""
    experiment, runner, _docker_bin = _real_runner_parts(tmp_path)
    with pytest.raises(sp.SelectionProbeRefused, match="separate instance"):
        sp.run_planned_selection_probe(
            experiment, CASES, runner, base=tmp_path / "work", grader=GRADER, grading_backend=runner.backend,
        )
    assert runner.backend.delivered == {}  # type: ignore[attr-defined]


def test_a_grading_backend_with_egress_is_refused(tmp_path: Path) -> None:
    experiment, runner, docker_bin = _real_runner_parts(tmp_path)
    open_grader = d.DockerBackend(image="fake-image:1", base_dir=tmp_path / "work", docker_bin=docker_bin, network="bridge")
    with pytest.raises(sp.SelectionProbeRefused, match="network"):
        sp.run_planned_selection_probe(
            experiment, CASES, runner, base=tmp_path / "work", grader=GRADER, grading_backend=open_grader,
        )


def test_a_plan_missing_a_declared_case_or_arm_is_refused(tmp_path: Path) -> None:
    """Attendance checks results against the attempts the plan issued; this
    checks the plan against what the cases declare. A plan of one case, a
    plan with no baseline for a case, and a declaration of zero cases are
    all refused before the runner is called. Confirmed red when the check is
    removed: the one-case plan returns a one-case report as if complete."""
    store = t.open_store(tmp_path / "store", forbidden=[])
    one_case = {**CASES, "cases": [CASES["cases"][0]]}
    partial = sp.plan_selection_probe(
        one_case, MANIFEST, treatment_subject_digest=_TREATMENT_SUBJECT_DIGEST,
        baseline_subject_digest=_BASELINE_SUBJECT_DIGEST, image_digest=_PLACEHOLDER_IMAGE_DIGEST, store=store,
    )
    runner, calls = _counting_runner()
    # the one-case plan against three declared cases trips the population
    # check; against zero declared cases, the planned case is itself unknown
    for declared, reason in ((CASES, "does not cover"), ({**CASES, "cases": []}, "not in the supplied cases")):
        with pytest.raises(sp.SelectionProbeRefused, match=reason):
            sp.run_planned_selection_probe(
                partial, declared, runner, base=tmp_path / "grading", grader=GRADER, allow_host_grading=True,
            )
    assert calls == []



def test_an_unknown_disposition_is_refused_at_construction() -> None:
    with pytest.raises(sp.SelectionProbeRefused):
        sp.AttemptTranscript(disposition="finished")
    sp.AttemptTranscript(disposition="captured")


def test_an_unrelated_invocation_is_not_a_selection_of_an_applicable_skill() -> None:
    """Deliberately narrow: `selection` answers whether an APPLICABLE skill
    was invoked. An unrelated invocation stays visible in `observed`, where
    the case's `disallowed` policy is judged."""
    transcript = sp.AttemptTranscript(
        disposition="captured", events=({"type": "skill_invocation", "skill": "unrelated-skill"},),
    )
    assert sp.selection_status(transcript, ["qa-test"]) == "not-selected"
    assert sp.observed_skills(transcript) == frozenset({"unrelated-skill"})


def test_a_tampered_config_object_is_refused(tmp_path: Path) -> None:
    experiment = _plan(tmp_path)
    trial_dict, _attempt = next(iter(experiment.attempts()))
    assert sp._resolve_config(experiment, trial_dict)["arm"] in sp.ARMS
    config_ref = trial_dict["config"]
    assert isinstance(config_ref, dict)
    path = experiment.object_path(str(config_ref["digest"]))
    path.chmod(0o644)
    path.write_bytes(path.read_bytes().replace(b"treatment", b"baseline_").replace(b"baseline\"", b"treatment\""))
    with pytest.raises(sp.SelectionProbeRefused, match="modified after it was stored"):
        sp._resolve_config(experiment, trial_dict)


def test_structural_detection_is_not_marked_best_effort(tmp_path: Path) -> None:
    experiment = _plan(tmp_path)
    for detection, expected in (("structural", False), ("heuristic", True)):
        record = {"disposition": "not-run", "observation": {"skill_invocation_detection": detection}}
        assert sp.transcript_from_record(record, experiment, "unused").codex_best_effort is expected


def test_an_unknown_arm_is_refused_by_the_real_runner(tmp_path: Path) -> None:
    _experiment, runner, _docker_bin = _real_runner_parts(tmp_path)
    with pytest.raises(sp.SelectionProbeRefused, match="unknown arm"):
        runner({"config": {"arm": "other", "prompt_addendum": ""}}, {"attempt_id": "a"})
    assert runner.backend.delivered == {}  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Follow-up to the first live run (#26): the record's reason, the named
# detection-control mode and its guards, the predeclared control, the exit
# rule, and the `skillc selection-probe` command. The SKILLC_ALLOW_REAL_AGENT
# pytest harness that used to sit here is gone: tests/conftest.py (rightly)
# keeps every test away from a real credential, so it could never launch,
# and it passed on six `unavailable` attempts anyway.
# --------------------------------------------------------------------------

from types import SimpleNamespace

CONTROL = json.loads((PROBE_DIR / "detection-control.json").read_text(encoding="utf-8"))


def test_a_non_captured_attempt_keeps_the_records_own_reason(tmp_path: Path) -> None:
    """Confirmed red when `transcript_from_record` drops `reason`: the
    first live run had to read the attempt journal to learn why all six
    attempts were `unavailable`."""
    transcript = sp.transcript_from_record(
        {"disposition": "unavailable", "reason": "no codex credential at /x"}, _plan(tmp_path), "unused",
    )
    assert "no codex credential at /x" in transcript.detail


def test_a_named_runner_is_refused_for_a_selection_run(tmp_path: Path) -> None:
    """A canary that names the skill supplies the answer a selection run
    measures. Confirmed red when the guard is removed: the run launches."""
    experiment, runner, _docker_bin = _real_runner_parts(tmp_path)
    named = dataclasses.replace(runner, skill_name="qa-test")
    with pytest.raises(sp.SelectionProbeRefused, match="detection control, never a selection result"):
        sp.run_planned_selection_probe(
            experiment, CASES, named, base=tmp_path / "work", grader=GRADER,
            grading_backend=d.DockerBackend(image="fake-image:1", base_dir=tmp_path / "work"),
        )
    assert named.backend.delivered == {}  # type: ignore[attr-defined]


def test_a_control_without_a_named_runner_is_refused(tmp_path: Path) -> None:
    experiment, runner, _docker_bin = _real_runner_parts(tmp_path)
    with pytest.raises(sp.SelectionProbeRefused, match="names the skill it must detect"):
        sp.run_planned_selection_probe(
            experiment, CASES, runner, base=tmp_path / "work", grader=GRADER,
            grading_backend=d.DockerBackend(image="fake-image:1", base_dir=tmp_path / "work"),
            detection_control=True,
        )


def test_the_committed_control_narrows_to_its_declared_case() -> None:
    narrowed = sp.detection_control_cases(CASES, CONTROL)
    listed = narrowed["cases"]
    assert isinstance(listed, list) and len(listed) == 1
    case: dict[str, object] = listed[0]
    assert case["id"] == CONTROL["base_case"]["id"] == INTENDED_USE
    applicable = case["applicable_skills"]
    assert isinstance(applicable, list) and CONTROL["skill_name"] in applicable


def test_a_control_declared_against_another_revision_is_refused() -> None:
    stale = {**CONTROL, "base_case": {**CONTROL["base_case"], "revision": "c0"}}
    with pytest.raises(sp.SelectionProbeRefused, match="revision"):
        sp.detection_control_cases(CASES, stale)


def _arm(disposition: str = "captured", selection: str = "not-selected") -> sp.ArmResult:
    return sp.ArmResult(disposition=disposition, selection=selection, task_success=None)


def _report(*pairs: tuple[sp.ArmResult, sp.ArmResult]) -> sp.SelectionProbeReport:
    return sp.SelectionProbeReport(cases=tuple(
        sp.CaseResult(case_id=f"c{i}", kind="k", applicable_skills=(), treatment=t_, baseline=b_)
        for i, (t_, b_) in enumerate(pairs)
    ))


def test_a_selection_run_is_ok_only_when_every_attempt_was_captured() -> None:
    """The first live attempt's shape - six `unavailable` arms, all reading
    `unknown` - must NOT be ok; that is exactly what the removed pytest
    harness called a pass. Confirmed red when the capture check is removed."""
    unavailable = _arm("unavailable", "unknown")
    ok, why = sp.probe_verdict(_report(*[(unavailable, unavailable)] * 3), detection_control=False)
    assert not ok and "c0/treatment=unavailable" in why
    ok, _ = sp.probe_verdict(_report((_arm(), _arm()), (_arm(), _arm("inconclusive", "unknown"))),
                             detection_control=False)
    assert not ok
    ok, _ = sp.probe_verdict(_report(*[(_arm(), _arm())] * 3), detection_control=False)
    assert ok
    assert sp.probe_verdict(_report(), detection_control=False)[0] is False


def test_a_control_is_ok_only_when_detected_in_treatment_and_absent_in_baseline() -> None:
    """Both halves are needed: detected-in-treatment shows the pipeline CAN
    see an invocation; absent-in-baseline shows it does not report one that
    could not have happened. Confirmed red when either check is removed."""
    detected, unknown = _arm(selection="selected"), _arm("inconclusive", "unknown")
    assert sp.probe_verdict(_report((detected, unknown)), detection_control=True)[0]
    assert sp.probe_verdict(_report((detected, _arm())), detection_control=True)[0]
    assert not sp.probe_verdict(_report((_arm(), unknown)), detection_control=True)[0]
    assert not sp.probe_verdict(_report((unknown, unknown)), detection_control=True)[0]
    assert not sp.probe_verdict(_report((detected, detected)), detection_control=True)[0]


def _run_control(tmp_path: Path, baseline: dict[str, object]) -> tuple[bool, str]:
    """The control end to end on the fake docker: treatment has the skill and
    the named canary; the baseline script says what the fake agent does
    where nothing was installed."""
    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    docker_bin = [sys.executable, str(FAKE_DOCKER), "--state", str(docker_state)]
    cases = sp.detection_control_cases(CASES, CONTROL)
    experiment = sp.plan_selection_probe(
        cases, MANIFEST, treatment_subject_digest=_TREATMENT_SUBJECT_DIGEST,
        baseline_subject_digest=sp.BASELINE_SUBJECT_DIGEST, image_digest=_PLACEHOLDER_IMAGE_DIGEST,
        store=t.open_store(tmp_path / "store", forbidden=[]), experiment_name=str(CONTROL["experiment"]),
    )
    runner = sp.agent_trial_runner(
        experiment=experiment, backend=_HomeRecordingBackend(image="fake-image:1", base_dir=base, docker_bin=docker_bin),
        base=base, client="codex",
        argv_for=_argv_for(experiment, docker_state, {(INTENDED_USE, "baseline"): baseline}),
        treatment_home_files=_COLLECTION, goal="Fix the slug helper.", timeout=5,
        credential_explicit_path=_codex_credential(tmp_path), skill_name=str(CONTROL["skill_name"]),
    )
    report = sp.run_planned_selection_probe(
        experiment, cases, runner, base=base, grader=GRADER, detection_control=True,
        grading_backend=d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=docker_bin),
    )
    return sp.probe_verdict(report, detection_control=True)


def test_the_control_end_to_end_detects_the_named_skill(tmp_path: Path) -> None:
    """With nothing installed the named canary cannot be satisfied, so the
    baseline reads unknown - the expected shape, not a failure."""
    ok, why = _run_control(tmp_path, _script(fail_canary=True))
    assert ok, why


def test_the_control_end_to_end_flags_an_invocation_in_the_empty_baseline(tmp_path: Path) -> None:
    """A baseline that somehow shows the skill being read - nothing was
    installed there - must fail the control, not pass it."""
    ok, why = _run_control(tmp_path, _script())
    assert not ok and "baseline" in why


def _cli_fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, report: sp.SelectionProbeReport) -> list[dict[str, object]]:
    """`cmd_selection_probe` with the acquisition and the run itself
    replaced - no docker, no git clone, no credential, no agent."""
    from skillc import collection_conformance as cc
    from skillc import demo

    seen: list[dict[str, object]] = []

    def fake_acquire(name: str, root: Path) -> object:
        return SimpleNamespace(
            subject=SimpleNamespace(client="codex", client_version="0.157.1", revision="v1"),
            source=SimpleNamespace(digest=_TREATMENT_SUBJECT_DIGEST), files=[],
        )

    def fake_run(experiment: object, cases: object, runner: object, **kwargs: object) -> sp.SelectionProbeReport:
        seen.append({"runner": runner, "cases": cases, **kwargs})
        return report

    monkeypatch.setattr(cc, "acquire_collection", fake_acquire)
    monkeypatch.setattr(cc, "_collection_home_files", lambda *a: {})
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *a, **k: None)
    monkeypatch.setattr(sp, "run_planned_selection_probe", fake_run)
    return seen


def test_cli_exits_1_when_attempts_were_not_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """The exact shape the removed harness passed: every arm unavailable."""
    from skillc import cli

    unavailable = _arm("unavailable", "unknown")
    seen = _cli_fakes(monkeypatch, tmp_path, _report(*[(unavailable, unavailable)] * 3))
    assert cli.main(["selection-probe", "--base", str(tmp_path)]) == 1
    [call] = seen
    assert call["detection_control"] is False
    assert call["runner"].skill_name is None  # type: ignore[attr-defined]
    assert call["grading_backend"] is not call["runner"].backend  # type: ignore[attr-defined]
    assert "verdict: NOT ok" in capsys.readouterr().out


def test_cli_exits_0_when_every_attempt_was_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from skillc import cli

    _cli_fakes(monkeypatch, tmp_path, _report(*[(_arm(), _arm())] * 3))
    assert cli.main(["selection-probe", "--base", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "verdict: ok" in out and "report_written=True" in out


def test_cli_detection_control_names_the_declared_skill_on_the_declared_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skillc import cli

    seen = _cli_fakes(monkeypatch, tmp_path, _report((_arm(selection="selected"), _arm("inconclusive", "unknown"))))
    assert cli.main(["selection-probe", "--detection-control", "--base", str(tmp_path)]) == 0
    [call] = seen
    assert call["detection_control"] is True
    assert call["runner"].skill_name == CONTROL["skill_name"]  # type: ignore[attr-defined]
    assert [c["id"] for c in call["cases"]["cases"]] == [INTENDED_USE]  # type: ignore[index]
