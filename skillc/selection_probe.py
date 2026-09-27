"""The selection probe's live run driver (#26): plans both arms of each
predeclared case (`evals/selection-probe/cases.json`) through the real
controller, runs every planned attempt through a real agent, observes native
skill selection from its transcript, grades the same public task outcome
independently of what it observed, and reports both - never conflating them
(#26's own requirement: "Grade the public task outcome independently of
observed selection").

NOTHING RUNS FOR REAL BY DEFAULT. `lifecycle.py`'s own guard
(`_refuse_real_agent`, `ALLOW_REAL_AGENT_ENV`) already refuses to launch
`claude`/`codex` anywhere in an `execute()` argv unless
`SKILLC_ALLOW_REAL_AGENT=1` is set - this module adds no second gate on top
of it, and every test here uses a FAKE `AttemptRunner` that never calls
`execute()` at all, so the guard is never even exercised by this file's own
suite (`tests/test_lifecycle.py` already covers the guard itself). The real
agent path is `agent_trial.py` (#106): `AttemptRunner` is the seam the
driver depends on, and `agent_trial_runner` at the bottom of this module is
its real implementation - skill-free canary mode, the collection installed
into the treatment arm's home only, the record translated by
`transcript_from_record`.

SELECTION VOCABULARY, never a fourth ad-hoc word: `"selected"` (an
applicable skill was invoked, captured disposition), `"not-selected"`
(disposition captured, no applicable skill invoked), `"unknown"` (the
attempt's own disposition is not `"captured"` - `"unavailable"`,
`"not-run"` or `"inconclusive"` - so invocation could not be reliably
observed at all). **A non-captured disposition is ALWAYS `"unknown"`, never
`"not-selected"`** (#26's own decision-traceability requirement: "Unavailable
native selection observations limit the selection conclusion; do not
substitute prompted invocation" - reporting "not-selected" for an attempt
that never ran cleanly would silently manufacture the very substitution that
sentence forbids). The baseline arm's own `applicable_skills` is always
empty (nothing is installed for it to select FROM), so `selection_status`
returning `"selected"` there is exactly this probe's own contamination
signal - one mechanism, not two: `baseline_contaminated` is a named alias of
that same result for the arm where it is never desired.

TASK SUCCESS IS GRADED, NEVER INFERRED FROM SELECTION. `verify.grade_files`
(#76) grades the SAME `slug-small-fix` task's public outcome for every
arm and every case - a correct fix without invoking any skill is a valid,
successful result (#26's own text), and an invoked-but-wrong-fix attempt is
still a failure. The two facts are reported side by side, never folded into
one verdict.

THE ATTENDANCE RULE: `run_selection_probe` refuses (`SelectionProbeRefused`)
if any attempt the plan issued is missing from the collected results -
records.py's own ledger-binding "ATTENDANCE" convention, one level up: a
report that silently drops a planned attempt is worse than one that never
ran it, because it reads as complete. This is why `AttemptRunner` may return
`None`: an `AttemptTranscript` with a non-`"captured"` disposition is still
a real result (reported as `"unknown"`), but `None` means the attempt could
not even be attempted at all, and that is the one shape the attendance check
exists to catch - a runner that always returns SOME `AttemptTranscript` for
every attempt it is called with would make this check unreachable, which is
exactly the "instrument that cannot fail" the committed red case below
exists to rule out.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import agent_trial, collection_conformance, credential, records, trial, verify
from .backend import ExecutionBackend, Limits
from .docker_backend import DockerBackend

PROBE_ROOT = Path(__file__).resolve().parent.parent / "evals" / "selection-probe"
GRADER_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix"

ARMS: tuple[str, ...] = ("treatment", "baseline")

#: The baseline arm installs nothing, so there is no receipt to read a real
#: digest from - a named placeholder rather than a plausible-looking value
#: (issue #10 lesson D13).
BASELINE_SUBJECT_DIGEST = "sha256:0000000000000000000000000000000000000000000000000000000000baseline"

SELECTION_STATUSES = ("selected", "not-selected", "unknown")


class SelectionProbeRefused(Exception):
    """The plan, a runner's output, or the assembled report violated one of
    this module's own structural guarantees - never silently patched over."""


def load_cases(path: Path = PROBE_ROOT / "cases.json") -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest(path: Path = PROBE_ROOT / "run-manifest.json") -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def plan_selection_probe(
    cases: dict[str, object], manifest: dict[str, object], *,
    treatment_subject_digest: str, baseline_subject_digest: str, image_digest: str, store: Path,
    experiment_name: str = "selection-probe",
) -> trial.Experiment:
    """Plans BOTH arms of every case as its own trial through the real
    controller - the exact shape `tests/test_selection_probe.py`'s own
    no-run deliverable already proved round-trips through `trial.plan()`
    (issue #26), now the ONE place that shape is built, shared by that test
    and by `run_selection_probe` below, rather than two copies that could
    drift apart."""
    case_list = cases["cases"]
    assert isinstance(case_list, list)
    client = cases["client"]
    assert isinstance(client, dict)
    repo_root = PROBE_ROOT.parent.parent
    grader_path = repo_root / str(cases["base_task"]["grader"])  # type: ignore[index]
    base_grader = json.loads(grader_path.read_text(encoding="utf-8"))
    manifest_repeat = manifest["repeat_schedule"]  # type: ignore[index]
    assert isinstance(manifest_repeat, dict)
    attempts_per_trial = manifest_repeat["attempts_per_trial"]

    trials = []
    for case in case_list:
        assert isinstance(case, dict)
        for arm in ARMS:
            trials.append({
                "label": f"{str(case['kind']).replace('-', '_')}_{arm}",
                "case": {"id": case["id"], "revision": case["revision"], "observes_selection": case["observes_selection"]},
                "grader": {"id": base_grader["id"], "revision": base_grader["revision"]},
                "subject": {"digest": treatment_subject_digest if arm == "treatment" else baseline_subject_digest},
                "client": {"name": client["name"], "version": client["version"]},
                "image": {"digest": image_digest},
                "config": {
                    "arm": arm,
                    "prompt_addendum": case["prompt_addendum"],
                    "applicable_skills": case["applicable_skills"] if arm == "treatment" else [],
                },
                "attempts": attempts_per_trial,
            })
    spec: dict[str, object] = {"experiment": experiment_name, "trials": trials}
    return trial.plan(spec, store)


@dataclass(frozen=True)
class AttemptTranscript:
    """What running one planned attempt through a real agent hands back,
    normalized regardless of which client ran it (`transcript_adapter.py`'s
    own event shape) - `AttemptRunner`'s return type, and the seam
    `agent_trial.py` (#106) implements on the other side."""

    disposition: str  # one of records.DISPOSITIONS
    events: tuple[dict[str, object], ...] = ()  # NormalizedEvent-shaped, e.g. {"type": "skill_invocation", "skill": "qa-test"}
    candidate_files: tuple[tuple[str, bytes, bool], ...] = ()  # verify.grade_files' own (relpath, bytes, executable) convention
    codex_best_effort: bool = False  # transcript_adapter.py: Codex's own skill-invocation detection is best-effort, never a structural guarantee
    detail: str = ""
    #: The transcript was found and read (exactly one file, no hook failure),
    #: so `events` is an OBSERVATION - an empty tuple then means "looked and
    #: saw none", not "had nothing to look at". Independent of `disposition`:
    #: an attempt whose named canary failed is inconclusive, yet its
    #: transcript was still read.
    observation_confirmed: bool = False

    def __post_init__(self) -> None:
        if self.disposition not in records.DISPOSITIONS:
            raise SelectionProbeRefused(
                f"AttemptTranscript.disposition {self.disposition!r} is not one of {records.DISPOSITIONS}"
            )


#: (trial dict, attempt dict) -> AttemptTranscript, or `None` when the
#: attempt could not even be ATTEMPTED (never launched, a runner-level crash
#: swallowed rather than raised, or similar) - distinct from an
#: `AttemptTranscript(disposition="unavailable"/"inconclusive", ...)`, which
#: means the attempt WAS attempted and has a result to report as `"unknown"`.
#: Only `None` triggers the attendance rule below; a real, non-captured
#: disposition is reported, never dropped. The seam this module depends on
#: instead of `agent_trial.py` directly - see the module docstring for why.
AttemptRunner = Callable[[dict[str, object], dict[str, object]], "AttemptTranscript | None"]


def observed_skills(transcript: AttemptTranscript) -> frozenset[str]:
    return frozenset(
        str(event["skill"]) for event in transcript.events
        if event.get("type") == "skill_invocation" and "skill" in event
    )


def selection_status(transcript: AttemptTranscript, applicable_skills: Sequence[str]) -> str:
    """One of `SELECTION_STATUSES`. A non-`"captured"` disposition is ALWAYS
    `"unknown"` - see the module docstring's decision-traceability rule; this
    is the one place that rule is enforced, so every caller (including the
    baseline-arm contamination check below) gets it for free."""
    if transcript.disposition != "captured":
        return "unknown"
    observed = observed_skills(transcript)
    if applicable_skills:
        return "selected" if observed & set(applicable_skills) else "not-selected"
    # No applicable skill exists for this arm at all (the near-miss case's
    # treatment arm, or ANY case's baseline arm) - ANY invocation at all is
    # exactly the false positive / contamination signal this shape exists to
    # catch, so it is reported as "selected" with zero applicable options.
    return "selected" if observed else "not-selected"


def _grade(
    grader: verify.GraderDef, transcript: AttemptTranscript, base: Path,
    backend: ExecutionBackend | None = None,
) -> tuple[bool | None, str]:
    """The task's own public outcome, graded independently of selection -
    `None` when the attempt's own disposition means nothing was ever
    captured to grade (never a guessed PASS or FAIL for a run that did not
    happen), and `None` too for a grade that reached no verdict, with the
    grader's own reason as the second element. `backend`, when given, is where the grader's probe executes
    the candidate (`verify.grade_files`' own parameter) - a real agent's
    output is untrusted code, so the real-agent path passes a SEPARATE
    grading backend (interfaces.md step 8) rather than probing it on the
    host."""
    if transcript.disposition != "captured":
        return None, ""
    graded = verify.grade_files(grader, list(transcript.candidate_files), base, backend=backend)
    # Only PASS and FAIL are verdicts about the candidate. Anything else (an
    # INCONCLUSIVE grade: an unconfirmed containment, a judge that did not
    # return a verdict) is a fact about the GRADING, and reporting it as
    # task failure would blame the candidate for the grader's own gap.
    success = {"PASS": True, "FAIL": False}.get(graded.status)
    return success, "" if success is not None else f"grading {graded.status}: {graded.detail}"


@dataclass(frozen=True)
class ArmResult:
    disposition: str
    selection: str  # SELECTION_STATUSES
    task_success: bool | None
    observed: frozenset[str] = field(default_factory=frozenset)
    codex_best_effort: bool = False
    detail: str = ""
    observation_confirmed: bool = False


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    kind: str
    applicable_skills: tuple[str, ...]
    treatment: ArmResult
    baseline: ArmResult

    @property
    def baseline_contaminated(self) -> bool:
        """A named alias of `baseline.selection == "selected"` - the
        baseline arm's own `applicable_skills` is always empty by
        construction (`plan_selection_probe`), so `"selected"` there can
        only mean an invocation happened where nothing should have been
        installed to invoke. `"unknown"` (a blocked/inconclusive baseline
        attempt) is deliberately NOT contamination - see the module
        docstring: unknown never becomes an affirmative claim in either
        direction."""
        return self.baseline.selection == "selected"


@dataclass(frozen=True)
class SelectionProbeReport:
    cases: tuple[CaseResult, ...]


def _resolve_config(experiment: trial.Experiment, trial_dict: dict[str, object]) -> dict[str, object]:
    """`trial.plan()` stores each trial's `config` as a content-addressed
    digest reference, not the literal object (`trial.py`'s own "the resolved
    configuration is stored as an object and the ledger binds its digest") -
    `experiment.attempts()` hands back the ledger's own trial entries
    verbatim, so `trial_dict["config"]` is `{"digest": "sha256:..."}` there,
    never the `arm`/`prompt_addendum`/`applicable_skills` dict this module
    (and any real `AttemptRunner`) needs. Read it back the same way
    `verify.py`'s own `_read_frozen` reads any other stored object."""
    config_ref = trial_dict["config"]
    assert isinstance(config_ref, dict)
    digest = config_ref["digest"]
    assert isinstance(digest, str)
    data = experiment.object_path(digest).read_bytes()
    if trial.sha256_bytes(data) != digest:
        raise SelectionProbeRefused(f"config object {digest} was modified after it was stored")
    resolved = json.loads(data)
    assert isinstance(resolved, dict)
    return resolved


def _resolved_trial(experiment: trial.Experiment, trial_dict: dict[str, object]) -> dict[str, object]:
    """`trial_dict` with `config` replaced by its resolved content - what
    `AttemptRunner` actually receives, since a digest reference is useless to
    a real runner that needs `arm`/`prompt_addendum`/`applicable_skills` to
    build its own launch argv."""
    return {**trial_dict, "config": _resolve_config(experiment, trial_dict)}


def run_selection_probe(
    cases: dict[str, object], manifest: dict[str, object], runner: AttemptRunner, *,
    treatment_subject_digest: str, baseline_subject_digest: str, image_digest: str,
    store: Path, base: Path, grader: verify.GraderDef | None = None,
    grading_backend: ExecutionBackend | None = None, allow_host_grading: bool = False,
) -> SelectionProbeReport:
    """Plans, runs every attempt through `runner`, grades, and assembles the
    report - refusing (`SelectionProbeRefused`) if any planned attempt is
    missing from the results (the attendance rule).

    A runner that needs the planned experiment itself (the real
    `agent_trial_runner` does - `agent_trial.run_one_attempt` takes it)
    plans with `plan_selection_probe` first and calls
    `run_planned_selection_probe` directly; this is exactly that, in one
    call, for a runner that does not."""
    experiment = plan_selection_probe(
        cases, manifest, treatment_subject_digest=treatment_subject_digest,
        baseline_subject_digest=baseline_subject_digest, image_digest=image_digest, store=store,
    )
    return run_planned_selection_probe(
        experiment, cases, runner, base=base, grader=grader, grading_backend=grading_backend,
        allow_host_grading=allow_host_grading,
    )


def run_planned_selection_probe(
    experiment: trial.Experiment, cases: dict[str, object], runner: AttemptRunner, *,
    base: Path, grader: verify.GraderDef | None = None,
    grading_backend: ExecutionBackend | None = None, allow_host_grading: bool = False,
    detection_control: bool = False,
) -> SelectionProbeReport:
    """`run_selection_probe` over an ALREADY-planned experiment - the same
    attendance rule, grading and report assembly, split out so a runner can
    be built against the experiment before it runs.

    Refused before ANY attempt runs:
      - a runner whose canary NAMES a skill, unless `detection_control=True` -
        a prompt that names the skill supplies the selection it would report -
        and a control whose runner names none.
      - a `grading_backend` that IS the runner's own agent backend
        (`AgentTrialRunner.backend`), or that has network egress.
      - a plan that does not cover every (case, arm) the supplied cases
        declare, including an empty one.
      - no `grading_backend` without `allow_host_grading=True`. With no
        backend, `verify.grade_files` executes the candidate as a HOST
        subprocess - acceptable only for committed, trusted fixture
        candidates (this module's own fake-runner tests), never for what a
        real agent wrote. The default is the safe one.
      - more than one attempt for any (case, arm). The report carries one
        `ArmResult` per arm, so a second attempt would pass attendance and
        then vanish from the report - a contaminated second baseline would
        read as clean. The bounded pilot plans one attempt per arm
        (`run-manifest.json`'s `attempts_per_trial`); repeats need a report
        that carries every attempt, not a silent first-wins.
      - a `cases` entry whose revision differs from the one planned. Selection
        itself is judged against the FROZEN planned configuration's
        `applicable_skills`, never against `cases`, so editing the case file
        after planning cannot change a verdict; `cases` supplies only the
        case's kind for the report."""
    named = getattr(runner, "skill_name", None)
    if named is not None and not detection_control:
        raise SelectionProbeRefused(
            f"the runner's canary names the skill {named!r} - a prompted invocation is a detection "
            "control, never a selection result (#26: do not substitute prompted invocation)"
        )
    if detection_control and named is None:
        raise SelectionProbeRefused(
            "a detection control needs a runner whose canary names the skill it must detect"
        )
    if grading_backend is None and not allow_host_grading:
        raise SelectionProbeRefused(
            "no grading_backend: the candidate would be executed on the host - pass a separate "
            "grading backend, or allow_host_grading=True for trusted fixture candidates only"
        )
    if grading_backend is not None and grading_backend is getattr(runner, "backend", None):
        # interfaces.md step 8: the grader runs in a SEPARATE instance, never
        # the one the agent's own attempt used - `run_one_attempt`'s own
        # identity guard only fires when IT grades, which this driver does not.
        raise SelectionProbeRefused(
            "grading_backend is the runner's own agent backend - grading needs a separate instance"
        )
    grading_network = getattr(grading_backend, "network", "none")
    if grading_network != "none":
        raise SelectionProbeRefused(
            f"grading_backend has network={grading_network!r} - candidate grading "
            "never gets egress (collection_conformance.agent_backends' own split)"
        )
    grader = grader if grader is not None else verify.GraderDef.load(GRADER_ROOT)

    planned = [(_resolved_trial(experiment, trial_dict), attempt) for trial_dict, attempt in experiment.attempts()]
    planned_ids = {str(attempt["attempt_id"]) for _trial, attempt in planned}

    all_cases = cases["cases"]
    assert isinstance(all_cases, list)
    case_by_id: dict[str, dict[str, object]] = {c["id"]: c for c in all_cases}
    expected_pairs = {(str(case_id), arm) for case_id in case_by_id for arm in ARMS}
    per_arm: dict[tuple[str, str], int] = {}
    for trial_dict, _attempt in planned:
        case_ref = trial_dict["case"]
        assert isinstance(case_ref, dict)
        case_id, revision = str(case_ref["id"]), str(case_ref["revision"])
        if case_id not in case_by_id or str(case_by_id[case_id]["revision"]) != revision:
            raise SelectionProbeRefused(
                f"planned case {case_id!r} revision {revision!r} is not in the supplied cases"
            )
        key = (case_id, str(trial_dict["config"]["arm"]))  # type: ignore[index]
        per_arm[key] = per_arm.get(key, 0) + 1
    repeated = sorted(key for key, count in per_arm.items() if count != 1)
    if repeated:
        raise SelectionProbeRefused(
            f"(case, arm) pairs planned with more than one attempt: {repeated} - the report "
            "carries one result per arm, so a repeat would be run and then dropped"
        )
    # Attendance (below) checks results against the attempts the plan ISSUED;
    # this checks the plan against what the cases DECLARE - an experiment
    # missing a case or a baseline would otherwise yield a report that looks
    # complete over a smaller population, and an empty one a report of nothing.
    absent = sorted(expected_pairs - per_arm.keys())
    if not expected_pairs or absent:
        raise SelectionProbeRefused(
            f"the plan does not cover every declared (case, arm) pair: missing {absent or 'all'} - "
            "a report over a partial population would read as complete"
        )

    transcripts: dict[str, AttemptTranscript] = {}
    for trial_dict, attempt in planned:
        attempt_id = str(attempt["attempt_id"])
        result = runner(trial_dict, attempt)
        if result is not None:
            transcripts[attempt_id] = result

    missing = planned_ids - transcripts.keys()
    if missing:
        raise SelectionProbeRefused(
            f"the report is missing {len(missing)} planned attempt(s): {sorted(missing)} - "
            "every planned attempt must appear in the report, or none of it can be trusted"
        )

    by_case: dict[str, dict[str, list[tuple[dict[str, object], AttemptTranscript]]]] = {}
    for trial_dict, attempt in planned:
        case_id = str(trial_dict["case"]["id"])  # type: ignore[index]
        arm = str(trial_dict["config"]["arm"])  # type: ignore[index]
        by_case.setdefault(case_id, {}).setdefault(arm, []).append(
            (trial_dict, transcripts[str(attempt["attempt_id"])])
        )

    results = []
    for case_id, arms in by_case.items():
        case = case_by_id[case_id]
        arm_results: dict[str, ArmResult] = {}
        applicable: tuple[str, ...] = ()
        for arm in ARMS:
            [(trial_dict, transcript)] = arms[arm]  # exactly one - refused above otherwise
            frozen_applicable = trial_dict["config"]["applicable_skills"]  # type: ignore[index]
            assert isinstance(frozen_applicable, list)
            arm_applicable = tuple(str(name) for name in frozen_applicable)
            if arm == "treatment":
                applicable = arm_applicable
            success, grading_detail = _grade(grader, transcript, base, grading_backend)
            arm_results[arm] = ArmResult(
                disposition=transcript.disposition,
                selection=selection_status(transcript, arm_applicable),
                task_success=success,
                observed=observed_skills(transcript),
                codex_best_effort=transcript.codex_best_effort,
                detail="; ".join(part for part in (transcript.detail, grading_detail) if part),
                observation_confirmed=transcript.observation_confirmed,
            )
        results.append(CaseResult(
            case_id=case_id, kind=str(case["kind"]), applicable_skills=applicable,
            treatment=arm_results["treatment"], baseline=arm_results["baseline"],
        ))
    return SelectionProbeReport(cases=tuple(results))


# ------------------------------------------------ the real AttemptRunner (#26)


def transcript_from_record(
    record: Mapping[str, object], experiment: trial.Experiment, attempt_id: str,
) -> AttemptTranscript:
    """Translate one `agent_trial.run_one_attempt` record into the driver's
    own `AttemptTranscript`.

    Selection comes ONLY from the record's own `skill_invocations` (what the
    transcript showed), never from the canary - in skill-free mode the
    canary is a delivery/liveness check and names no skill at all.

    A captured attempt whose observation is unknown, or whose prompt
    delivery or canary was not confirmed (`grading_eligible` false), is
    reported `"inconclusive"`, never `"captured"`: #106's own rule is that
    such an attempt is BLOCKED, not graded, and the same unconfirmed
    transcript is no better evidence of selection than it is of outcome -
    so both selection and task success come out unknown for it.

    `skill_invocation_detection == "heuristic"` (Codex) sets
    `codex_best_effort`, so the report can never present a heuristic
    observation as a structural one."""
    disposition = str(record.get("disposition"))
    observation = record.get("observation")
    obs = observation if isinstance(observation, dict) else {}
    heuristic = obs.get("skill_invocation_detection") == "heuristic"
    # The invocations the transcript showed are kept whatever the canary
    # said: a failed canary makes the attempt inconclusive (no selection, no
    # grade), but an invocation it recorded is still evidence - a detection
    # control's baseline must be able to see one (#26 review).
    confirmed = bool(obs) and obs.get("status") != "unknown" and obs.get("transcript_files_found") == 1
    invocations = obs.get("skill_invocations")
    events: tuple[dict[str, object], ...] = tuple(
        {"type": "skill_invocation", "skill": str(name)}
        for name in (invocations if isinstance(invocations, list) else [])
    )

    def made(disposition: str, detail: str = "",
             candidate_files: tuple[tuple[str, bytes, bool], ...] = ()) -> AttemptTranscript:
        return AttemptTranscript(
            disposition=disposition, events=events, candidate_files=candidate_files,
            codex_best_effort=heuristic, detail=detail, observation_confirmed=confirmed,
        )

    if disposition != "captured":
        reason = record.get("reason")
        return made(disposition, f"attempt disposition is {disposition!r}" + (f": {reason}" if reason else ""))
    if not obs or obs.get("status") == "unknown":
        return made("inconclusive", f"the transcript observation is unknown: {obs.get('reason', 'no observation recorded')}")
    if not obs.get("grading_eligible"):
        return made("inconclusive", (
            f"prompt_delivered={obs.get('prompt_delivered')!r}, "
            f"canary_satisfied={obs.get('canary_satisfied')!r} - neither selection nor "
            "outcome is reported for an attempt the transcript did not confirm"
        ))
    return made("captured", candidate_files=tuple(agent_trial._frozen_candidate_files(experiment, attempt_id)))


def agent_trial_runner(
    *,
    experiment: trial.Experiment,
    backend: DockerBackend,
    base: Path,
    client: str,
    argv_for: Callable[[str], Sequence[str]],
    treatment_home_files: Mapping[str, bytes],
    goal: str | None = None,
    surface: Mapping[str, object] | None = None,
    timeout: float = 30,
    cli_version: str | None = None,
    credential_explicit_path: str | Path | None = None,
    minimum_credential_seconds: float = credential.MINIMUM_REMAINING_SECONDS,
    skill_name: str | None = None,
) -> AgentTrialRunner:
    """The real `AttemptRunner`: each planned attempt becomes one
    `agent_trial.run_one_attempt` against `experiment`, in SKILL-FREE mode
    (`skill_name=None`) - a canary that names a skill would supply the very
    answer this probe exists to observe.

    The treatment arm receives `treatment_home_files` (the declared
    collection, keyed by container-home path - build it with
    `collection_conformance.acquire_collection` and its `_collection_home_files`,
    the one surface-reading convention). The baseline arm receives NOTHING
    extra, whatever the caller passes: its whole meaning is "no skill
    installed", and that is enforced here rather than trusted to a caller.

    The prompt is the fixed task's own `goal.md` plus the case's
    `prompt_addendum` (empty for the near-miss case). `argv_for(attempt_id)`
    returns the launch argv before the prompt, exactly as
    `run_one_attempt`'s `base_argv` - a real launch returns the same argv
    every time; the fake-docker tests need the attempt id to map the home.

    No grading happens here: `run_planned_selection_probe` grades every
    captured attempt itself, through its own `grading_backend`, so there is
    ONE grading path whichever runner produced the transcript.

    Launching a real `claude`/`codex` still requires
    `SKILLC_ALLOW_REAL_AGENT=1` - `lifecycle.py`'s own guard, unchanged.

    The returned runner exposes `.backend`, so `run_planned_selection_probe`
    can refuse to grade in the agent's own backend.

    `skill_name` switches the canary to its NAMED form ("invoke <skill>,
    then..."), which tells the agent which skill to use. That is the answer a
    selection probe exists to observe, so a named runner is ONLY for the
    predeclared detection control (`detection-control.json`): it shows the
    pipeline can see a real invocation at all. `run_planned_selection_probe`
    refuses a named runner for a selection run, and an unnamed one for a
    control."""
    return AgentTrialRunner(
        experiment=experiment, backend=backend, base=base, client=client, argv_for=argv_for,
        treatment_home_files=treatment_home_files,
        goal=goal if goal is not None else (GRADER_ROOT / "goal.md").read_text(encoding="utf-8"),
        surface=(
            surface if surface is not None
            else collection_conformance._fixture_surface(GRADER_ROOT / "fixture")
        ),
        timeout=timeout, cli_version=cli_version, credential_explicit_path=credential_explicit_path,
        minimum_credential_seconds=minimum_credential_seconds, skill_name=skill_name,
    )


@dataclass(frozen=True)
class AgentTrialRunner:
    """`agent_trial_runner`'s result: an `AttemptRunner` that also names the
    agent backend it launches into (see that function for the behaviour)."""

    experiment: trial.Experiment
    backend: DockerBackend
    base: Path
    client: str
    argv_for: Callable[[str], Sequence[str]]
    treatment_home_files: Mapping[str, bytes]
    goal: str
    surface: Mapping[str, object]
    timeout: float
    cli_version: str | None
    credential_explicit_path: str | Path | None
    minimum_credential_seconds: float
    skill_name: str | None = None

    def __call__(self, trial_dict: dict[str, object], attempt: dict[str, object]) -> AttemptTranscript | None:
        config = trial_dict["config"]
        assert isinstance(config, dict)
        arm = str(config["arm"])
        if arm not in ARMS:
            raise SelectionProbeRefused(f"planned trial names unknown arm {arm!r}")
        addendum = str(config.get("prompt_addendum") or "")
        prompt = f"{self.goal}\n\n{addendum}" if addendum else self.goal
        attempt_id = str(attempt["attempt_id"])
        record = agent_trial.run_one_attempt(
            backend=self.backend, experiment=self.experiment, attempt_id=attempt_id, client=self.client,
            base_argv=self.argv_for(attempt_id), prompt=prompt, skill_name=self.skill_name,
            surface=self.surface, limits=Limits(timeout=self.timeout), base=self.base,
            credential_explicit_path=self.credential_explicit_path,
            minimum_credential_seconds=self.minimum_credential_seconds, cli_version=self.cli_version,
            extra_home_files=dict(self.treatment_home_files) if arm == "treatment" else {},
        )
        return transcript_from_record(record, self.experiment, attempt_id)


# ------------------------------------------------ detection control and exit rules (#26)


def load_detection_control(path: Path = PROBE_ROOT / "detection-control.json") -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def detection_control_cases(cases: dict[str, object], control: dict[str, object]) -> dict[str, object]:
    """`cases` narrowed to the control's one base case, planned (both arms)
    under the control's own experiment name. Refused if the base case or
    its revision is not the one the control was declared against."""
    base = control["base_case"]
    assert isinstance(base, dict)
    all_cases = cases["cases"]
    assert isinstance(all_cases, list)
    matching = [c for c in all_cases if c["id"] == base["id"]]
    if not matching or matching[0]["revision"] != base["revision"]:
        raise SelectionProbeRefused(
            f"detection control is declared against {base['id']!r} revision {base['revision']!r}, "
            "which the supplied cases do not contain"
        )
    [case] = matching
    if control["skill_name"] not in case["applicable_skills"]:
        raise SelectionProbeRefused(
            f"control skill {control['skill_name']!r} is not applicable to {case['id']!r}"
        )
    return {**cases, "cases": [case]}


def probe_verdict(report: SelectionProbeReport, *, detection_control: bool) -> tuple[bool, str]:
    """`(ok, why)` for the operator command's exit status.

    A selection run is ok only when EVERY arm of every case was captured -
    a report of `unknown`s is not a measurement, however orderly it looks
    (the first live attempt at this ran six `unavailable` attempts and a
    harness that only checked the vocabulary called it a pass).

    A detection control is ok only when the treatment arm (skill installed,
    prompt names it) reads `selected` AND the baseline arm (nothing
    installed) does not. The first shows the pipeline can see a real
    invocation; the second that it does not report one that could not have
    happened. "Does not" means the baseline's transcript WAS read and showed
    no invocation of any skill - an attempt that never produced an
    observation (a failed launch, a missing transcript) proves nothing
    either way and fails the control."""
    if not report.cases:
        return False, "the report has no cases"
    if detection_control:
        [case] = report.cases
        if case.treatment.selection != "selected":
            return False, (f"control NOT detected: treatment reads {case.treatment.selection!r} "
                           f"({case.treatment.disposition}; {case.treatment.detail or 'no detail'})")
        if case.baseline.selection == "selected" or case.baseline.observed:
            return False, (f"control reported an invocation in the baseline arm, where nothing was "
                           f"installed: {sorted(case.baseline.observed) or case.baseline.selection}")
        if not case.baseline.observation_confirmed:
            return False, (f"control baseline was never observed ({case.baseline.disposition}; "
                           f"{case.baseline.detail or 'no detail'}) - absence cannot be certified from "
                           "missing evidence")
        return True, "control detected in treatment; baseline observed with no invocation"
    missing = [
        f"{case.case_id}/{arm}={result.disposition}"
        for case in report.cases
        for arm, result in (("treatment", case.treatment), ("baseline", case.baseline))
        if result.disposition != "captured"
    ]
    if missing:
        return False, "not every attempt was captured: " + ", ".join(missing)
    return True, f"all {2 * len(report.cases)} attempts captured"
