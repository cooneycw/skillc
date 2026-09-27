"""The first bounded matched pilot (issue #12): plan the predeclared schedule,
run it, and assemble the evidence report.

`evals/matched-pilot/run-manifest.json` is the predeclaration - written and
merged (#89) before any attempt ran. This module READS it and never widens
it: the arms, repeats, arm order, subject, task and time caps all come from
that file, so a run cannot quietly drift from what was declared.

ONE ATTEMPT PATH FOR BOTH ARMS. Every attempt goes through
`collection_conformance.run_level1_agent_attempt` - the same client, prompt,
fixture, skill-free canary and grader #11's live run used. The arms differ
ONLY in `extra_home_files`: the treatment gets the subject's selected skill
files, the baseline gets `{}`. A second copy of the wiring could differ from
the first in a way that would read as a treatment effect.

TIME CAPS ARE ENFORCED HERE, not only stated. Each attempt's agent limit
(`Limits.timeout`) is the SMALLER of the per-attempt cap and what remains of
the total cap, so agent execution can never run past the total. An attempt
that would start with nothing left is finalized `not-run` with that reason -
reported, never dropped (`ledger_binding` refuses a report that omits a
scheduled attempt). Setup, grading and teardown are not killed mid-way, so
the wall-clock can pass the total by those alone, for the last attempt.

MISSING IS EXPLICIT. Anything the run cannot measure is the literal
`"UNKNOWN"` (the `pilot-report` rule's own convention), never a zero:
  - agent dollar cost: the attempts run on the operator's subscription login
    (ADR 0005 rule 6), which has no per-attempt price. Observed token counts
    are reported beside it instead;
  - claim accuracy: whether the agent's closing message claimed success is a
    REVIEWED judgement, supplied as a separate claims file after a person has
    read the private final messages. Without one, every claim is `UNKNOWN`.

RETENTION. Raw evidence - the trial store, the transcripts' final messages,
the per-attempt outcomes - stays in a private run directory outside any git
work tree (`trial.open_store` already refuses one inside a work tree). Only
the ledger, the lifecycle records and the assembled report are exported for
committing, and the CLI leak-checks them first.

Stdlib only (AGENTS.md), plus this repository's own modules.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import demo, records, trial
from .lifecycle import RealAgentBlocked

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "evals" / "matched-pilot"
MANIFEST_PATH = PILOT_DIR / "run-manifest.json"

TREATMENT = "treatment"
BASELINE = "baseline"

#: The baseline arm installs nothing, so its "subject" is the empty surface:
#: this is the sha256 of zero bytes, stated as exactly that - not a
#: placeholder shaped like a real subject digest (issue #10 lesson D13).
BASELINE_SUBJECT_DIGEST = "sha256:" + hashlib.sha256(b"").hexdigest()

#: Allowed values in a claims file (`build_report`'s `claims`).
#: `asked-clarification`: the agent ended by asking a question instead of
#: finishing. The manifest's declared behaviour counts that as an
#: intervention and names it under uncertainty (it is never auto-answered).
CLAIM_VALUES = ("claimed-success", "claimed-failure", "no-claim", "asked-clarification")

UNKNOWN = "UNKNOWN"


class ManifestRefused(ValueError):
    """The run manifest does not declare a schedule this module can run as written."""


@dataclass(frozen=True)
class PilotDeclaration:
    """The parts of the run manifest a run needs, validated once."""

    arms: tuple[str, ...]
    repeats_per_arm: int
    attempts_per_trial: int
    per_attempt_seconds: float
    total_seconds: float
    task_id: str
    task_revision: str
    grader_path: Path
    client_name: str
    client_version: str
    subject_name: str
    subject_revision: str
    #: The declared image digest; `pilot-run` refuses to run any other.
    image_digest: str
    #: The declared model. NOT enforced at launch (the client picks its own
    #: default); every report entry compares it with the observed model.
    model: str


def _positive_finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ManifestRefused(f"time_caps.{name} is {value!r}, not a positive finite number of seconds")
    return float(value)


def load_declaration(manifest_path: Path = MANIFEST_PATH) -> PilotDeclaration:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = manifest.get("predeclared_experiment_record")
    if not isinstance(record, dict):
        raise ManifestRefused("run manifest has no predeclared_experiment_record")
    order = record.get("arm_order")
    if not isinstance(order, str) or not order.startswith("treatment then baseline, per repeat"):
        raise ManifestRefused(f"arm_order {order!r} is not the order this runner implements")
    schedule = record.get("repeat_schedule")
    caps = record.get("time_caps")
    task = (record.get("goal_population") or {}).get("task")
    if not isinstance(schedule, dict) or not isinstance(caps, dict) or not isinstance(task, dict):
        raise ManifestRefused("run manifest is missing repeat_schedule, time_caps or goal_population.task")
    if schedule.get("arms") != 2:
        raise ManifestRefused(f"declares {schedule.get('arms')!r} arms; this runner implements exactly two")
    repeats = schedule.get("repeats_per_arm")
    per_trial = schedule.get("attempts_per_trial")
    if not isinstance(repeats, int) or repeats < 1 or per_trial != 1:
        raise ManifestRefused("repeats_per_arm must be a positive integer and attempts_per_trial exactly 1")
    if schedule.get("total_attempts") != repeats * 2:
        raise ManifestRefused("total_attempts does not equal 2 x repeats_per_arm")
    subject = record.get("subject")
    client = record.get("client")
    if not isinstance(subject, dict) or not isinstance(client, dict):
        raise ManifestRefused("run manifest is missing subject or client")
    subject_name = subject.get("name")
    if not isinstance(subject_name, str):
        raise ManifestRefused("subject.name is not a string")
    # The runner executes exactly one task: the Level 1 fixture
    # `collection_conformance.run_level1_agent_attempt` loads. A manifest
    # naming any other task or grader would be recorded in the ledger but
    # not run, so it is refused rather than planned.
    grader_path = (ROOT / str(task.get("grader"))).resolve()
    if grader_path != (demo.GRADER_ROOT / "grader.json").resolve():
        raise ManifestRefused(
            f"goal_population.task.grader {task.get('grader')!r} is not the task this runner executes "
            f"({demo.GRADER_ROOT.relative_to(ROOT)}/grader.json)"
        )
    grader = json.loads(grader_path.read_text(encoding="utf-8"))
    if (str(task.get("id")), str(task.get("revision"))) != (grader["id"], grader["revision"]):
        raise ManifestRefused("goal_population.task id/revision does not match the grader it names")
    image_digest = record.get("image_digest")
    if not isinstance(image_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise ManifestRefused(f"image_digest {image_digest!r} is not a declared sha256 digest")
    model = (record.get("model") or {}).get("name")
    if not isinstance(model, str) or not model:
        raise ManifestRefused("model.name is not declared")
    return PilotDeclaration(
        arms=(TREATMENT, BASELINE), repeats_per_arm=repeats, attempts_per_trial=per_trial,
        per_attempt_seconds=_positive_finite(caps.get("per_attempt_seconds"), "per_attempt_seconds"),
        total_seconds=_positive_finite(caps.get("total_seconds"), "total_seconds"),
        task_id=str(task["id"]), task_revision=str(task["revision"]),
        grader_path=grader_path,
        client_name=str(client["name"]), client_version=str(client["version"]),
        subject_name=subject_name, subject_revision=str(subject.get("revision")),
        image_digest=image_digest, model=model,
    )


@dataclass(frozen=True)
class ScheduledAttempt:
    attempt_id: str
    trial_id: str
    arm: str
    repeat: int


def plan_pilot(
    declaration: PilotDeclaration, store: Path, *, treatment_digest: str, image_digest: str | None,
) -> tuple[trial.Experiment, list[ScheduledAttempt]]:
    """Plan every trial through the real controller, in the predeclared order:
    repeat-outer, arm-inner, so the schedule interleaves T,B,T,B,... rather
    than running each arm as one block (which would confound the arm with
    time of day, login state and provider load)."""
    grader = json.loads(declaration.grader_path.read_text(encoding="utf-8"))
    trials: list[dict[str, object]] = []
    for repeat in range(1, declaration.repeats_per_arm + 1):
        for arm in declaration.arms:
            trials.append({
                "label": f"matched_pilot_{arm}_{repeat}",
                "case": {"id": declaration.task_id, "revision": declaration.task_revision},
                "grader": {"id": grader["id"], "revision": grader["revision"]},
                "subject": {"digest": treatment_digest if arm == TREATMENT else BASELINE_SUBJECT_DIGEST},
                "client": {"name": declaration.client_name, "version": declaration.client_version},
                "image": {"digest": image_digest or UNKNOWN},
                "config": {"arm": arm, "repeat": repeat},
                "attempts": declaration.attempts_per_trial,
            })
    experiment = trial.plan({"experiment": "matched-pilot", "trials": trials}, store)
    pairs = list(experiment.attempts())
    if len(pairs) != len(trials):
        raise ManifestRefused(f"planned {len(pairs)} attempts for {len(trials)} trials")
    schedule = []
    for (planned_trial, attempt), spec in zip(pairs, trials, strict=True):
        config = spec["config"]
        assert isinstance(config, dict)
        schedule.append(ScheduledAttempt(
            attempt_id=str(attempt["attempt_id"]), trial_id=str(planned_trial["trial_id"]),
            arm=str(config["arm"]), repeat=int(config["repeat"]),
        ))
    return experiment, schedule


@dataclass
class AttemptOutcome:
    """One scheduled attempt as it actually went. `record` is what
    `run_level1_agent_attempt` returned, or the lifecycle record this runner
    finalized itself (a cap-cut or a crashed attempt)."""

    scheduled: ScheduledAttempt
    record: dict[str, object]
    wall_seconds: float
    runner_note: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "attempt_id": self.scheduled.attempt_id, "trial_id": self.scheduled.trial_id,
            "arm": self.scheduled.arm, "repeat": self.scheduled.repeat,
            "wall_seconds": self.wall_seconds, "runner_note": self.runner_note, "record": self.record,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> AttemptOutcome:
        record = data["record"]
        assert isinstance(record, dict)
        return cls(
            scheduled=ScheduledAttempt(
                attempt_id=str(data["attempt_id"]), trial_id=str(data["trial_id"]),
                arm=str(data["arm"]), repeat=int(str(data["repeat"])),
            ),
            record=record, wall_seconds=float(str(data["wall_seconds"])),
            runner_note=data.get("runner_note") if isinstance(data.get("runner_note"), str) else None,  # type: ignore[arg-type]
        )


def run_schedule(
    experiment: trial.Experiment,
    schedule: Sequence[ScheduledAttempt],
    run_attempt: Callable[[ScheduledAttempt, float], dict[str, object]],
    *,
    total_seconds: float,
    per_attempt_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    on_outcome: Callable[[AttemptOutcome], None] | None = None,
) -> list[AttemptOutcome]:
    """Run every scheduled attempt in order, enforcing the total cap as a
    start gate and as each attempt's agent limit: `run_attempt` receives the
    seconds its agent may run, `min(per_attempt_seconds, remaining)`. Every
    scheduled attempt yields exactly one outcome.

    An exception out of `run_attempt` (a bug, not a failed attempt - a failed
    attempt is a disposition) does not abandon the rest of the schedule: the
    attempt is finalized `inconclusive` (or `unavailable`, if it never
    started) with the error as its reason - unless it was finalized already,
    whose record then stands - and the run moves on. The one exception is
    `RealAgentBlocked` - no opt-in - which aborts the run outright."""
    started = clock()
    outcomes: list[AttemptOutcome] = []
    for scheduled in schedule:
        elapsed = clock() - started
        if elapsed >= total_seconds:
            reason = (
                f"total time cap reached before this attempt could start "
                f"({elapsed:.0f}s elapsed of {total_seconds:.0f}s declared)"
            )
            record = trial.finalize(experiment, scheduled.attempt_id, reason=reason)
            outcome = AttemptOutcome(scheduled, record, 0.0, runner_note=reason)
        else:
            attempt_started = clock()
            budget = min(per_attempt_seconds, total_seconds - elapsed)
            try:
                record = run_attempt(scheduled, budget)
                note = None if budget >= per_attempt_seconds else (
                    f"agent limit cut to {budget:.0f}s by the total time cap"
                )
            except RealAgentBlocked:
                # A missing opt-in is the caller's error, not an attempt's
                # outcome: recording six "inconclusive" attempts for a run
                # that was never allowed to start would read as a pilot.
                raise
            except Exception as exc:  # noqa: BLE001 - one attempt's crash must not drop the rest of the schedule
                note = f"runner error: {type(exc).__name__}: {exc}"
                record = _finalize_after_error(experiment, scheduled.attempt_id, note)
            outcome = AttemptOutcome(scheduled, record, clock() - attempt_started, runner_note=note)
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)
    return outcomes


def _finalize_after_error(experiment: trial.Experiment, attempt_id: str, note: str) -> dict[str, object]:
    """The attempt's lifecycle record after `run_attempt` raised. If the
    attempt was already finalized (the error came later - in grading, say),
    that record stands: a capture is never rewritten as `inconclusive`, and
    the error is carried as the runner note instead."""
    existing = experiment.root / f"lifecycle-{attempt_id}.json"
    if existing.is_file():
        record: dict[str, object] = json.loads(existing.read_text(encoding="utf-8"))
        return record
    try:
        return trial.finalize(experiment, attempt_id, disposition="inconclusive", reason=note)
    except trial.Refused:
        # Never dispatched: the record contract allows only `not-run` or
        # `unavailable` for an attempt that never started, and a runner error
        # that prevented it is the latter.
        return trial.finalize(experiment, attempt_id, disposition="unavailable", reason=note)


def _parse_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def agent_seconds(experiment: trial.Experiment, attempt_id: str) -> float | None:
    """`started` to `stopped` in the attempt's own journal - the time the
    agent process actually ran. `None` when either event is absent."""
    started = stopped = None
    for event in experiment.events(attempt_id):
        if event.get("event") == "started" and started is None:
            started = _parse_at(event.get("at"))
        elif event.get("event") == "stopped":
            stopped = _parse_at(event.get("at"))
    if started is None or stopped is None:
        return None
    return max(0.0, (stopped - started).total_seconds())


def _round(value: float) -> float:
    return round(value, 3)


def _time_split(outcome: AttemptOutcome, agent: float | None) -> dict[str, object]:
    record = outcome.record
    grading = record.get("grading_seconds")
    grading_value = float(grading) if isinstance(grading, (int, float)) and not isinstance(grading, bool) else 0.0
    if record.get("disposition") == "not-run":
        return {"setup": 0, "agent": 0, "grading": 0, "total": 0}
    if agent is None:
        # Dispatched never happened (unavailable) - the agent ran for no time,
        # and nothing was graded; everything spent was setup and teardown.
        if not any(e in ("started",) for e in _event_names(record)):
            total = _round(outcome.wall_seconds)
            return {"setup": total, "agent": 0, "grading": 0, "total": total}
        return {"setup": UNKNOWN, "agent": UNKNOWN, "grading": _round(grading_value), "total": _round(outcome.wall_seconds)}
    agent_r = _round(agent)
    grading_r = _round(grading_value)
    setup_r = _round(max(0.0, outcome.wall_seconds - agent - grading_value))
    return {"setup": setup_r, "agent": agent_r, "grading": grading_r, "total": _round(setup_r + agent_r + grading_r)}


def _event_names(record: Mapping[str, object]) -> list[str]:
    events = record.get("events")
    if not isinstance(events, list):
        return []
    return [str(e.get("event")) for e in events if isinstance(e, dict)]


def _uncertainty(outcome: AttemptOutcome) -> str:
    record = outcome.record
    notes: list[str] = []
    if outcome.runner_note:
        notes.append(outcome.runner_note)
    elif record.get("disposition") != "captured" and record.get("reason"):
        notes.append(f"disposition reason: {record.get('reason')}")
    if record.get("grading_blocked_reason"):
        notes.append(f"not graded: {record.get('grading_blocked_reason')}")
    observation = record.get("observation")
    if isinstance(observation, dict):
        if observation.get("status") == "unknown":
            notes.append(f"transcript unobserved: {observation.get('reason')}")
        if observation.get("skill_invocation_detection") == "heuristic":
            notes.append("skill_invocations is a heuristic for codex (a SKILL.md read in an exec call)")
        if observation.get("run_metadata") is None and observation.get("status") != "unknown":
            notes.append("run metadata (model, tokens) not observed")
    if record.get("backend_teardown") not in (None, "confirmed"):
        notes.append(f"backend teardown {record.get('backend_teardown')}")
    return "; ".join(notes) if notes else "none"


def _criteria(record: Mapping[str, object]) -> list[dict[str, object]]:
    graded = record.get("graded")
    if not isinstance(graded, dict):
        return []
    criteria = graded.get("criteria")
    if not isinstance(criteria, list):
        return []
    out = []
    for c in criteria:
        if isinstance(c, dict) and isinstance(c.get("id"), str):
            outcome = c.get("outcome")
            out.append({"id": c["id"], "outcome": outcome if outcome in records.CRITERION_OUTCOMES else UNKNOWN})
    return out


def _run_metadata(record: Mapping[str, object]) -> dict[str, object]:
    observation = record.get("observation")
    meta = observation.get("run_metadata") if isinstance(observation, dict) else None
    return meta if isinstance(meta, dict) else {}


def graded_status(record: Mapping[str, object]) -> str | None:
    graded = record.get("graded")
    status = graded.get("status") if isinstance(graded, dict) else None
    return status if isinstance(status, str) else None


def claim_accuracy(claim: str, status: str | None) -> object:
    """`True`/`False` when a success-or-failure claim can be checked against a
    PASS or FAIL grade; `"n/a"` when the agent made no claim or asked a
    question instead; `UNKNOWN` otherwise (no reviewed claim, or a grade that
    is neither PASS nor FAIL)."""
    if claim in ("no-claim", "asked-clarification"):
        return "n/a"
    if claim not in ("claimed-success", "claimed-failure") or status not in ("PASS", "FAIL"):
        # INCONCLUSIVE, UNAVAILABLE, NOT_RUN or no grade: the grader
        # established neither outcome, so no claim can be checked against it.
        return UNKNOWN
    return (claim == "claimed-success") == (status == "PASS")


def load_claims(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(claims, dict):
        raise ValueError(f"{path}: expected an object with a 'claims' mapping")  # noqa: TRY004 - a malformed file, reported with the others
    for attempt_id, value in claims.items():
        if value not in CLAIM_VALUES:
            raise ValueError(f"{path}: claim for {attempt_id!r} is {value!r}, not one of {list(CLAIM_VALUES)}")
    return {str(k): str(v) for k, v in claims.items()}


def schedule_from_ledger(experiment: trial.Experiment) -> list[ScheduledAttempt]:
    """The planned schedule, recovered from the ledger alone (each trial's
    label is `matched_pilot_<arm>_<repeat>`, carried in its trial id)."""
    schedule = []
    for planned_trial, attempt in experiment.attempts():
        trial_id = str(planned_trial["trial_id"])
        match = re.search(r"matched_pilot_(treatment|baseline)_(\d+)$", trial_id)
        if match is None:
            raise ManifestRefused(f"ledger trial {trial_id!r} is not a matched-pilot trial")
        schedule.append(ScheduledAttempt(str(attempt["attempt_id"]), trial_id, match.group(1), int(match.group(2))))
    return schedule


def reconcile(experiment: trial.Experiment, outcomes: Sequence[AttemptOutcome]) -> list[AttemptOutcome]:
    """One outcome per attempt the LEDGER planned, in ledger order. A planned
    attempt with no recorded outcome (the run was interrupted) takes its
    lifecycle record if one was written, else is finalized now - never left
    out, since a report that omits a scheduled attempt is not a report of the
    pilot. An outcome for an attempt the ledger never planned is refused."""
    by_id = {o.scheduled.attempt_id: o for o in outcomes}
    schedule = schedule_from_ledger(experiment)
    stray = set(by_id) - {s.attempt_id for s in schedule}
    if stray:
        raise ManifestRefused(f"outcomes name attempt(s) the ledger never planned: {sorted(stray)}")
    reconciled = []
    for scheduled in schedule:
        outcome = by_id.get(scheduled.attempt_id)
        if outcome is None:
            note = "no outcome was recorded for this attempt (the run was interrupted)"
            lifecycle = experiment.root / f"lifecycle-{scheduled.attempt_id}.json"
            record = (
                json.loads(lifecycle.read_text(encoding="utf-8")) if lifecycle.is_file()
                # DERIVED, not declared: never dispatched is `not-run`, a
                # dispatched attempt with no capture is `inconclusive`.
                else trial.finalize(experiment, scheduled.attempt_id, reason=note)
            )
            outcome = AttemptOutcome(scheduled, record, 0.0, runner_note=note)
        reconciled.append(outcome)
    return reconciled


def build_report(
    experiment: trial.Experiment, outcomes: Sequence[AttemptOutcome], claims: Mapping[str, str] | None = None,
    *, declared_model: str | None = None,
) -> dict[str, object]:
    """The `pilot-report` record: one entry per scheduled attempt, in schedule
    order. The keys the `pilot-report` rule checks are exactly its contract;
    the extra keys (`arm`, `graded_status`, `tokens`, `claim`, ...) are this
    pilot's own reporting and are not read by that rule."""
    entries: list[dict[str, object]] = []
    for outcome in outcomes:
        record = outcome.record
        attempt_id = outcome.scheduled.attempt_id
        agent = agent_seconds(experiment, attempt_id) if record.get("disposition") != "not-run" else None
        meta = _run_metadata(record)
        status = graded_status(record)
        claim = (claims or {}).get(attempt_id, UNKNOWN)
        observation = record.get("observation")
        obs = observation if isinstance(observation, dict) else {}
        disposition = record.get("disposition")
        uncertainty = _uncertainty(outcome)
        interventions = 0
        if claim == "asked-clarification":
            # The declared behaviour: never auto-answered, counted, named.
            interventions = 1
            clarification = "the agent ended by asking a clarifying question (reviewed), which nobody answered"
            uncertainty = clarification if uncertainty == "none" else f"{uncertainty}; {clarification}"
        observed_model = meta.get("model") or UNKNOWN
        entries.append({
            "attempt_id": attempt_id,
            "trial_id": outcome.scheduled.trial_id,
            "arm": outcome.scheduled.arm,
            "repeat": outcome.scheduled.repeat,
            "disposition": disposition,
            "graded_status": status if status is not None else UNKNOWN,
            "criteria": _criteria(record),
            "uncertainty": uncertainty,
            # Non-interactive by declaration: nobody answers, redirects or
            # restarts an attempt once it starts. A reviewed clarification
            # request is the one thing that counts (see above).
            "interventions": interventions,
            "cost_usd": (
                {"setup": 0, "agent": 0, "grading": 0, "total": 0} if disposition == "not-run"
                else {"setup": 0, "agent": UNKNOWN, "grading": 0, "total": UNKNOWN}
            ),
            "cost_note": "agent runs on the operator's subscription login (ADR 0005 rule 6) - no per-attempt "
                         "dollar price exists; tokens are the observed usage. Setup and grading are local "
                         "containers with no metered call.",
            "tokens": meta.get("token_usage") if meta.get("token_usage") is not None else UNKNOWN,
            "time_seconds": _time_split(outcome, agent),
            "model_observed": observed_model,
            "model_declared": declared_model or UNKNOWN,
            "model_matches_declaration": (
                UNKNOWN if declared_model is None or observed_model == UNKNOWN
                else observed_model == declared_model
            ),
            "reasoning_effort_observed": meta.get("reasoning_effort") or UNKNOWN,
            "cli_version_observed": meta.get("cli_version") or UNKNOWN,
            "prompt_delivered": obs.get("prompt_delivered", UNKNOWN),
            "canary_satisfied": obs.get("canary_satisfied", UNKNOWN),
            "skill_invocations": obs.get("skill_invocations", UNKNOWN),
            "claim": claim,
            "claim_accurate": claim_accuracy(claim, status),
        })
    return {
        "version": 2,
        "kind": records.PILOT_REPORT,
        "producer": "assembler",
        "experiment_id": experiment.id,
        "claims_reviewed": claims is not None,
        "attempts": entries,
    }


def _agent_time(entry: Mapping[str, object]) -> float | None:
    split = entry.get("time_seconds")
    value = split.get("agent") if isinstance(split, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def summarize(report: Mapping[str, object]) -> dict[str, object]:
    """Per-arm counts, and completion time compared ONLY on repeats where
    both arms passed (matched successful pairs) - failures are listed beside
    it, never averaged into it. No significance test: at this size the
    summary is description, not inference."""
    attempts = report.get("attempts")
    entries = [e for e in attempts if isinstance(e, dict)] if isinstance(attempts, list) else []
    arms: dict[str, dict[str, object]] = {}
    for arm in (TREATMENT, BASELINE):
        mine = [e for e in entries if e.get("arm") == arm]
        arms[arm] = {
            "scheduled": len(mine),
            "captured": sum(1 for e in mine if e.get("disposition") == "captured"),
            "passed": sum(1 for e in mine if e.get("graded_status") == "PASS"),
            "not_passed": [
                {"attempt_id": e.get("attempt_id"), "disposition": e.get("disposition"),
                 "graded_status": e.get("graded_status")}
                for e in mine if e.get("graded_status") != "PASS"
            ],
        }
    pairs: list[dict[str, object]] = []
    diffs: list[float] = []
    by_repeat: dict[object, dict[object, dict[str, object]]] = {}
    for e in entries:
        by_repeat.setdefault(e.get("repeat"), {})[e.get("arm")] = e
    for repeat, pair in sorted(by_repeat.items(), key=lambda kv: str(kv[0])):
        t, b = pair.get(TREATMENT), pair.get(BASELINE)
        if not t or not b or t.get("graded_status") != "PASS" or b.get("graded_status") != "PASS":
            continue
        t_agent, b_agent = _agent_time(t), _agent_time(b)
        if t_agent is not None and b_agent is not None:
            diff = _round(t_agent - b_agent)
            diffs.append(diff)
            pairs.append({"repeat": repeat, "treatment_agent_seconds": t_agent, "baseline_agent_seconds": b_agent,
                          "difference_seconds": diff})
    return {
        "arms": arms,
        "matched_successful_pairs": pairs,
        "median_agent_seconds_difference_treatment_minus_baseline": (
            _round(statistics.median(diffs)) if diffs else UNKNOWN
        ),
        "claims_reviewed": report.get("claims_reviewed"),
        "protocol_deviations": [
            f"{e.get('attempt_id')}: ran model {e.get('model_observed')!r}, declared {e.get('model_declared')!r}"
            for e in entries if e.get("model_matches_declaration") is False
        ],
        "claim_accuracy": [
            {"attempt_id": e.get("attempt_id"), "claim": e.get("claim"), "accurate": e.get("claim_accurate")}
            for e in entries
        ],
        "scope": "a first bounded canary: no qualification or broad-benefit claim is supported by this sample",
    }


def export_bundle(experiment: trial.Experiment, report: Mapping[str, object], into: Path) -> list[Path]:
    """Copy the ledger and every per-attempt record the store holds
    (lifecycle, artifact manifest, and any receipt or result), and write the
    report, into `into` - the directory `skillc check-records` reads as one
    bundle. The content-addressed objects and the journals stay private."""
    into.mkdir(parents=True, exist_ok=True)
    written = []
    ledger = experiment.root / trial.LEDGER
    target = into / "ledger.json"
    target.write_bytes(ledger.read_bytes())
    written.append(target)
    for pattern in ("lifecycle-*.json", "manifest-*.json", "receipt-*.json", "result-*.json"):
        for source in sorted(experiment.root.glob(pattern)):
            target = into / source.name
            target.write_bytes(source.read_bytes())
            written.append(target)
    target = into / "report.json"
    target.write_text(json.dumps(report, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    written.append(target)
    return written


def private_observations(outcomes: Sequence[AttemptOutcome]) -> dict[str, object]:
    """What a claims reviewer reads: each attempt's closing message and grade.
    Transcript content - kept in the private run directory, never exported."""
    return {
        "attempts": [
            {
                "attempt_id": o.scheduled.attempt_id, "arm": o.scheduled.arm, "repeat": o.scheduled.repeat,
                "graded_status": graded_status(o.record) or UNKNOWN,
                "final_agent_message": _run_metadata(o.record).get("final_agent_message"),
            }
            for o in outcomes
        ],
    }


OUTCOMES_FILENAME = "outcomes.json"


def write_outcomes(run_dir: Path, experiment: trial.Experiment, outcomes: Sequence[AttemptOutcome]) -> Path:
    """The private, per-run record `pilot-report` rebuilds a report from.
    Rewritten after every attempt, so an interrupted run keeps what finished."""
    path = run_dir / OUTCOMES_FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "experiment_root": str(experiment.root), "outcomes": [o.to_json() for o in outcomes],
    }, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def read_outcomes(run_dir: Path) -> tuple[trial.Experiment, list[AttemptOutcome]]:
    data = json.loads((run_dir / OUTCOMES_FILENAME).read_text(encoding="utf-8"))
    root = Path(str(data["experiment_root"]))
    ledger = json.loads((root / trial.LEDGER).read_text(encoding="utf-8"))
    return trial.Experiment(root, ledger), [AttemptOutcome.from_json(o) for o in data["outcomes"]]


def run_pilot(
    declaration: PilotDeclaration,
    *,
    run_dir: Path,
    treatment_home_files: Mapping[str, bytes],
    treatment_digest: str,
    image_digest: str | None,
    backends: Callable[[], tuple[object, object]],
    argv_for: Callable[[ScheduledAttempt], Sequence[str]],
    credential_explicit_path: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    total_seconds: float | None = None,
) -> tuple[trial.Experiment, list[AttemptOutcome]]:
    """Plan and run the whole schedule. `backends()` returns a fresh
    `(agent backend, grading backend)` pair per attempt; `argv_for` gives the
    client invocation for one attempt (a real run passes the same argv every
    time; a test's scripted client needs the attempt id). `total_seconds`
    overrides the declared total cap - for tests only; the CLI never sets it."""
    from . import collection_conformance as cc

    store = trial.open_store(run_dir / "store", forbidden=[])
    experiment, schedule = plan_pilot(
        declaration, store, treatment_digest=treatment_digest, image_digest=image_digest,
    )
    outcomes: list[AttemptOutcome] = []

    def run_attempt(scheduled: ScheduledAttempt, budget: float) -> dict[str, object]:
        agent_backend, grading_backend = backends()
        return cc.run_level1_agent_attempt(
            experiment=experiment, attempt_id=scheduled.attempt_id,
            backend=agent_backend, grading_backend=grading_backend,  # type: ignore[arg-type]
            base=run_dir, base_argv=argv_for(scheduled),
            extra_home_files=treatment_home_files if scheduled.arm == TREATMENT else {},
            cli_version=declaration.client_version, timeout=budget,
            credential_explicit_path=credential_explicit_path,
        )

    def on_outcome(outcome: AttemptOutcome) -> None:
        outcomes.append(outcome)
        write_outcomes(run_dir, experiment, outcomes)

    run_schedule(
        experiment, schedule, run_attempt,
        total_seconds=declaration.total_seconds if total_seconds is None else total_seconds,
        per_attempt_seconds=declaration.per_attempt_seconds, clock=clock, on_outcome=on_outcome,
    )
    return experiment, outcomes


#: Private by default: outside any work tree, never exported.
DEFAULT_PRIVATE_ROOT = Path.home() / ".local" / "share" / "skillc" / "pilot-runs"
PRIVATE_OBSERVATIONS_FILENAME = "private-observations.json"
#: The committed bundle `skillc check-records` reads.
EVIDENCE_DIR = PILOT_DIR / "evidence" / "records"


#: The one finding a captured agent-trial attempt still carries: the #106
#: driver grades through `verify.grade_files` and stores no `verified-result`
#: record (that needs an installation receipt the agent path does not write),
#: so `attempt-accounting` correctly says the result is owed. Every OTHER
#: finding refuses publication.
KNOWN_GAP_RULE = "attempt-accounting"
KNOWN_GAP_TEXT = "is captured but has no result"


def bundle_findings(root: Path) -> tuple[list[str], int]:
    """`skillc check-records` over `root`, split into (unexpected error
    findings, count of the named known gap). An empty `root` - nothing to
    check - is itself an unexpected finding, never a clean result."""
    from . import checks

    found = records.discover(root)
    bundles = records.discover_bundles(root)
    if not found or not bundles:
        return [f"no record or no bundle under {root}; nothing was checked"], 0
    findings = [f for record in found for f in checks.run_record(record)]
    findings += [f for bundle in bundles for f in checks.run_bundle(bundle)]
    errors = [f for f in findings if f.severity == checks.ERROR]
    known = [f for f in errors if f.rule == KNOWN_GAP_RULE and KNOWN_GAP_TEXT in f.detail]
    unexpected = [f"{f.rule}: {f.detail}" for f in errors if f not in known]
    return unexpected, len(known)
