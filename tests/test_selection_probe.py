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


# --------------------------------------------------------------------------
# The REAL AttemptRunner (`agent_trial_runner`), end to end on the fake
# `docker` CLI and the scripted fake client `tests/test_agent_trial.py`
# already uses - `run_one_attempt` for real, every planned attempt, no real
# daemon and no real agent binary.
# --------------------------------------------------------------------------

import sys
import time
from base64 import urlsafe_b64encode

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
):  # type: ignore[no-untyped-def]
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


@pytest.mark.skipif(
    os.environ.get("SKILLC_ALLOW_REAL_AGENT") != "1",
    reason="launches a real codex agent for every planned attempt - operator-run only (ADR 0005 rule 5)",
)
def test_real_agent_selection_probe(tmp_path: Path) -> None:  # pragma: no cover - operator-run only
    """The live probe, as a runnable harness: the pinned cpp-codex collection,
    the trial image, the real `codex` client under the operator's subscription
    login, all six planned attempts. Asserts only what must hold whatever the
    agent does - every planned attempt reported in both arms, each in the
    driver's own vocabulary; the findings themselves are the report, printed
    for the operator to record."""
    from skillc import collection_conformance as cc
    from skillc import demo

    base = tmp_path / "run"
    base.mkdir()
    acquired = cc.acquire_collection(str(CASES["subject"]), base)
    docker_bin = ["docker"]
    image = os.environ.get("SKILLC_TRIAL_IMAGE", demo.DEFAULT_IMAGE)
    image_digest = demo.resolve_image_digest(docker_bin, image, None, 120) or "UNKNOWN"
    backend, grading_backend = cc.agent_backends(image=image, base=base, docker_bin=docker_bin, daemon_timeout=120)
    experiment = sp.plan_selection_probe(
        CASES, MANIFEST, treatment_subject_digest=acquired.source.digest,
        baseline_subject_digest=_BASELINE_SUBJECT_DIGEST, image_digest=image_digest,
        store=t.open_store(tmp_path / "store", forbidden=[]),
    )
    runner = sp.agent_trial_runner(
        experiment=experiment, backend=backend, base=base, client="codex",
        argv_for=lambda _attempt_id: list(cc.DEFAULT_CLIENT_ARGV),
        treatment_home_files=cc._collection_home_files(acquired.source, acquired.files),
        timeout=cc.DEFAULT_AGENT_TIMEOUT, cli_version=acquired.subject.client_version,
    )
    report = sp.run_planned_selection_probe(
        experiment, CASES, runner, base=base, grader=GRADER, grading_backend=grading_backend,
    )
    assert len(report.cases) == 3
    for case in report.cases:
        for arm in (case.treatment, case.baseline):
            assert arm.selection in sp.SELECTION_STATUSES
        print(case)
