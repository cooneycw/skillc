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
agent path is `agent_trial.py` (issue #106, its driver-loop half, not yet
merged as this module lands) - `AttemptRunner` is the seam this module
depends on rather than that module directly, so everything below it can be
built, tested and reviewed before that seam has a real implementation on the
other side, and the real implementation is a one-function adapter once it
does.

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import records, trial, verify

PROBE_ROOT = Path(__file__).resolve().parent.parent / "evals" / "selection-probe"
GRADER_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix"

ARMS: tuple[str, ...] = ("treatment", "baseline")

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
    spec: dict[str, object] = {"experiment": "selection-probe", "trials": trials}
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


def _grade(grader: verify.GraderDef, transcript: AttemptTranscript, base: Path) -> bool | None:
    """The task's own public outcome, graded independently of selection -
    `None` when the attempt's own disposition means nothing was ever
    captured to grade (never a guessed PASS or FAIL for a run that did not
    happen)."""
    if transcript.disposition != "captured":
        return None
    graded = verify.grade_files(grader, list(transcript.candidate_files), base)
    return graded.status == "PASS"


@dataclass(frozen=True)
class ArmResult:
    disposition: str
    selection: str  # SELECTION_STATUSES
    task_success: bool | None
    observed: frozenset[str] = field(default_factory=frozenset)
    codex_best_effort: bool = False
    detail: str = ""


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
) -> SelectionProbeReport:
    """Plans, runs every attempt through `runner`, grades, and assembles the
    report - refusing (`SelectionProbeRefused`) if any planned attempt is
    missing from the results (the attendance rule)."""
    experiment = plan_selection_probe(
        cases, manifest, treatment_subject_digest=treatment_subject_digest,
        baseline_subject_digest=baseline_subject_digest, image_digest=image_digest, store=store,
    )
    grader = grader if grader is not None else verify.GraderDef.load(GRADER_ROOT)

    planned = [(_resolved_trial(experiment, trial_dict), attempt) for trial_dict, attempt in experiment.attempts()]
    planned_ids = {str(attempt["attempt_id"]) for _trial, attempt in planned}

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

    all_cases = cases["cases"]
    assert isinstance(all_cases, list)
    case_by_id: dict[str, dict[str, object]] = {c["id"]: c for c in all_cases}
    results = []
    for case_id, arms in by_case.items():
        case = case_by_id[case_id]
        case_applicable = case["applicable_skills"]
        assert isinstance(case_applicable, list)
        applicable: tuple[str, ...] = tuple(case_applicable)
        arm_results: dict[str, ArmResult] = {}
        for arm in ARMS:
            trial_dict, transcript = arms[arm][0]  # first attempt of possibly-repeated trials
            arm_applicable = applicable if arm == "treatment" else ()
            arm_results[arm] = ArmResult(
                disposition=transcript.disposition,
                selection=selection_status(transcript, arm_applicable),
                task_success=_grade(grader, transcript, base),
                observed=observed_skills(transcript),
                codex_best_effort=transcript.codex_best_effort,
                detail=transcript.detail,
            )
        results.append(CaseResult(
            case_id=case_id, kind=str(case["kind"]), applicable_skills=applicable,
            treatment=arm_results["treatment"], baseline=arm_results["baseline"],
        ))
    return SelectionProbeReport(cases=tuple(results))
