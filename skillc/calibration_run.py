"""Run an approved calibration declaration (issue #207, for #204; three arms, #231).

`skillc.calibration` validates a `calibration-declaration` and refuses to
authorize an unapproved one; this module is what then EXECUTES it. Before
#207 nothing could: `collection-run` runs one attempt, has no baseline arm
and does not pin the model, and `pilot-run` reads only the Level 1 matched
pilot's own declaration. Hand-running the schedule would take the arm order,
the caps and the model pin from a person instead of from the declaration -
the drift #141 fixed for the pilot.

AUTHORIZATION FIRST. `run_calibration` calls `calibration.require_approved`
before it opens a store, plans a trial or builds a backend: an unapproved
declaration leaves nothing behind that could read as a started run (ADR 0005).

THE DECLARED ORDER, THROUGH THE REAL CONTROLLER. One trial per attempt,
planned by `trial.plan` in exactly `arm_order.sequence` - the seeded order
`calibration.parse_declaration` already proved was derived, not chosen. Each
trial is labelled `calibration_<arm>_<k>` (the arm's k-th attempt), so the
schedule is recoverable from the ledger alone (`schedule_from_ledger`).

ONE ATTEMPT PATH FOR EVERY ARM. Every attempt goes through
`collection_conformance.run_level1_agent_attempt` with the declared task as
`task_root` - the same client, prompt (`goal.md`), starting state and grader.
The arms differ ONLY in what is installed: a treated arm gets the subject's
selected skill files and the #150-D `InstallationReceiptContext`, the
baseline gets `{}` and none. A provided-skill arm (#231, P in #203's B/N/P)
installs the same subject as the natural arm and differs from it by one
thing: its declared `instruction` is appended to `goal.md`. The starting state is `task_surface` (the whole
fixture but its answer key), because a Level 3 fixture has no `src/`.

THE MODEL IS PINNED AT LAUNCH AND CHECKED AFTER, through
`matched_pilot.pin_model_argv` - the pilot's own refusal of a caller argv that
chooses the model, never a second copy. An attempt whose rollout reports
another model, or none, is `model_eligible: False` (`matched_pilot.
model_eligibility`), and the CLI fails the run on it.

CAPS AND RECONCILIATION are `matched_pilot.run_schedule` and
`matched_pilot.reconcile`: an attempt with no total cap left is finalized
`not-run`, a crashed one `inconclusive`, and every planned attempt yields
exactly one outcome.

THE ENDPOINT IS SYMMETRIC. Each attempt reports `calibration.
primary_endpoint` (the task grader's criteria, never `installation-ready`)
and, beside it, `calibration.readiness_beside` read from the attempt's stored
`verified-result`. The verified status is never the endpoint.

RETENTION. Everything stays in a private run directory outside any work tree
(`trial.open_store` refuses one inside a work tree): the store with each
attempt's leak-checked transcript (#202, retained by `agent_trial.
run_one_attempt` itself), `outcomes.json` and the report. Nothing is exported
for committing here; publishing the run's evidence belongs to the calibration
report (#204), which needs its own record kind.

Nothing here names or branches on a particular subject: the subject, task,
client and model all come from the declaration.

Stdlib only (AGENTS.md), plus this repository's own modules.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import agent_trial, calibration, demo, profile, trial, verify
from . import collection_conformance as cc
from . import matched_pilot as mp
from . import materialize as m

ROOT = mp.ROOT
EXPERIMENT_LABEL = "calibration"
TRIAL_PREFIX = "calibration"
OUTCOMES_FILENAME = mp.OUTCOMES_FILENAME
REPORT_FILENAME = "calibration-report.json"
REPORT_KIND = "calibration-run-report"
UNKNOWN = calibration.UNKNOWN

#: Private by default: outside any work tree, never exported.
DEFAULT_PRIVATE_ROOT = Path.home() / ".local" / "share" / "skillc" / "calibration-runs"

_TRIAL_ID_RE = re.compile(rf"^t\d+-{TRIAL_PREFIX}_(?P<arm>.+)_(?P<k>\d+)$")
_RESULT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class CalibrationRefused(ValueError):
    """The declaration cannot be run as written, or a run's own record
    disagrees with it."""


@dataclass(frozen=True)
class Treatment:
    """What the non-baseline arm installs, acquired once for the whole run:
    the subject's selected skill files, their content digest (the plan's
    `subject.digest`), and the #150-D receipt context - one discovery cache
    shared by every treatment attempt.

    `verify_home_files`/`preflight_tools` (#334) are empty unless a
    profile was opted in: the closure files' expected digests, re-checked
    IN the live container after delivery (never trusting delivery alone),
    and the profile's own `tool`-kind dependencies, checked present in
    that same container at their declared constraint. `gate_entrypoint`
    (mailbox 6047) is `None` unless the opted-in profile declares one -
    the SUBJECT's own fact about which installed path is its gate
    command, never inferred from `verify_home_files`' own membership."""

    home_files: Mapping[str, bytes]
    digest: str
    receipt_context: agent_trial.InstallationReceiptContext | None
    verify_home_files: Mapping[str, str] = field(default_factory=dict)
    preflight_tools: tuple[dict[str, object], ...] = ()
    gate_entrypoint: str | None = None


@dataclass(frozen=True)
class _ClosureResult:
    home_files: dict[str, bytes]
    #: The inventory's own `kind == "tool"` dependency records - #334's
    #: in-container preflight reads these directly (each already carries
    #: its own `probes`, serialized by `profile._dep_record`).
    tools: tuple[dict[str, object], ...]
    #: The profile's own declared `gate_entrypoint` (mailbox 6047), or
    #: `None` if it declares none - carried straight through, never
    #: re-derived from `home_files`' own keys.
    gate_entrypoint: str | None


def _closure_home_files(acquired: cc.AcquiredCollection, subject_profile: str, root: Path) -> _ClosureResult:
    """skillc#334: the validated profile's dependency closure, built from
    the SAME checkout the skills came from (`acquired.repo`), not a
    second acquisition - see `AcquiredCollection.repo`'s own docstring.

    Three refusals, all before any container exists:
    1. `verify_repo_matches_skills` (required mode - a live attempt must
       always be able to prove its checkout's identity).
    2. The LIVE inventory (re-`validate()`d against `acquired.repo` at
       the subject's own declared pin) must digest-match the COMMITTED
       `evidence/inventory.json` at `subject_profile` - the profile is
       stale against the current subject source otherwise, and `#334`'s
       whole point is to install the closure that was actually validated,
       never one assumed still accurate.
    3. The closure's own destinations must not collide with the skill
       surface's - the two delivery paths share one container home.
    """
    cc.verify_repo_matches_skills(acquired, revision_check="required")
    if acquired.repo is None:
        raise CalibrationRefused("subject.profile is named but no full checkout was acquired")
    prof = profile.Profile.load(root / subject_profile / "profile.json")
    tree = profile.GitTree(acquired.repo, acquired.subject.revision)
    inventory = profile.validate(prof, tree)
    inventory_path = root / subject_profile / "evidence" / "inventory.json"
    try:
        committed = json.loads(inventory_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CalibrationRefused(f"subject.profile {subject_profile!r} names no readable "
                                 f"evidence/inventory.json: {exc}") from exc
    live_digest, committed_digest = profile.inventory_digest(inventory), profile.inventory_digest(committed)
    if live_digest != committed_digest:
        raise CalibrationRefused(
            f"profile {subject_profile!r}'s live inventory (validated against the acquired checkout at "
            f"{acquired.subject.revision}) digests to {live_digest!r}, not the committed "
            f"{committed_digest!r} at {inventory_path} - the profile is stale against the current "
            f"subject source and must be re-declared before this closure can be installed"
        )
    home_files = profile.installed_home_files(inventory, tree)
    tools = tuple(dep for dep in inventory["dependencies"] if dep["kind"] == "tool")
    gate_entrypoint = inventory.get("gate_entrypoint")
    assert gate_entrypoint is None or isinstance(gate_entrypoint, str)
    # The earliest possible refusal point, before any container exists
    # (mailbox 6047): `profile.validate()` already proved the entrypoint
    # is installed by SOME closure at declaration time, but THIS run's
    # own installed_home_files() - built from the live, re-validated
    # inventory above - is the actual population this attempt would
    # deliver. The two can only disagree if something between validation
    # and here dropped the file, which must never pass silently.
    if gate_entrypoint is not None and gate_entrypoint not in home_files:
        raise CalibrationRefused(
            f"profile {subject_profile!r} declares gate_entrypoint {gate_entrypoint!r}, but this "
            f"closure's own installed_home_files does not carry it - witnessing is required "
            f"whenever a gate_entrypoint is declared, and cannot be honoured for a file that was "
            f"never actually produced"
        )
    return _ClosureResult(home_files=home_files, tools=tools, gate_entrypoint=gate_entrypoint)


def build_treatment(
    acquired: cc.AcquiredCollection, *, listing_client_argv: Sequence[str] | None = None,
    subject_profile: str | None = None, root: Path | None = None,
) -> Treatment:
    """The treatment arm from an acquisition, built exactly as
    `run_collection_agent_attempt` builds its own - the same home files, the
    same receipt context - so the calibration treatment IS a collection-run
    install. A subject whose selection is empty installs nothing: refused,
    since the arms would then not differ at all.

    `subject_profile` (#334) names a validated profile (repo-relative path
    to its `profile.json`, as `calibration.py`'s `subject.profile` opt-in
    field declares it) whose dependency closure joins the skill surface in
    ONE merged home-files mapping - never a second delivery mechanism.
    `root` is the skillc checkout root the profile path resolves against;
    required together with `subject_profile`, meaningless alone."""
    if not acquired.files:
        raise CalibrationRefused(
            f"subject {acquired.subject.locator!r} selects no skill; a treatment arm that installs "
            "nothing is a second baseline"
        )
    if (subject_profile is None) != (root is None):
        raise CalibrationRefused("subject_profile and root must be given together, or not at all")
    home_files: dict[str, bytes] = dict(cc._collection_home_files(acquired.source, acquired.files))
    verify_home_files: dict[str, str] = {}
    preflight_tools: tuple[dict[str, object], ...] = ()
    gate_entrypoint: str | None = None
    if subject_profile is not None:
        assert root is not None
        closure = _closure_home_files(acquired, subject_profile, root)
        closure_files = closure.home_files
        # A validated profile's own closure covers the selected skill's
        # bundled files too (profile.py installs skills AND dependencies
        # together) - so an overlap with the skill surface is EXPECTED,
        # not an error, as long as the two paths agree byte-for-byte
        # (which `verify_repo_matches_skills`, already run inside
        # `_closure_home_files`, is what makes that a safe assumption
        # rather than a hope). Only a genuine DISAGREEMENT - the two
        # paths naming different bytes for the same destination - is
        # refused: that would mean the acquisition and the profile
        # validation drifted apart despite the consistency check.
        disagreeing = sorted(k for k in set(closure_files) & set(home_files) if closure_files[k] != home_files[k])
        if disagreeing:
            raise CalibrationRefused(
                f"profile {subject_profile!r}'s closure disagrees with the skill surface at: {disagreeing}"
            )
        home_files.update(closure_files)
        # Every closure file, not a curated subset (orchestrator ruling,
        # mailbox 5872 step 2: "read back the digest of every closure
        # file") - host-side bytes were already digest-verified against
        # the inventory inside `installed_home_files`, so this is simply
        # that same digest, carried forward for the in-container re-check.
        verify_home_files = {relpath: m.sha256_bytes(data) for relpath, data in closure_files.items()}
        preflight_tools = closure.tools
        gate_entrypoint = closure.gate_entrypoint
    return Treatment(
        home_files=home_files,
        digest=acquired.source.digest,
        gate_entrypoint=gate_entrypoint,
        receipt_context=agent_trial.InstallationReceiptContext(
            declared=frozenset(f.skill for f in acquired.files),
            tree_digest=acquired.source.digest,
            listing_client_argv=listing_client_argv,
            subject_locator=acquired.subject.locator,
            subject_revision=acquired.source.revision,
            surface_name=acquired.subject.surface,
            cache={},
        ),
        verify_home_files=verify_home_files,
        preflight_tools=preflight_tools,
    )


def _shared_str(declaration: calibration.CalibrationDeclaration, *path: str) -> str:
    node: object = declaration.shared
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, str) or not node:
        raise CalibrationRefused(f"shared.{'.'.join(path)} is not declared")
    return node


def declared_model(declaration: calibration.CalibrationDeclaration) -> tuple[str, str]:
    return _shared_str(declaration, "model"), _shared_str(declaration, "reasoning_effort")


def declared_client(declaration: calibration.CalibrationDeclaration) -> tuple[str, str]:
    return _shared_str(declaration, "client", "name"), _shared_str(declaration, "client", "version")


def treatment_subject(declaration: calibration.CalibrationDeclaration) -> Mapping[str, object]:
    """The non-baseline arm's declared subject (`parse_declaration` already
    proved there is exactly one, and that it is an object)."""
    arms = declaration.data.get("arms")
    arm = next(a for a in arms if isinstance(a, dict) and a.get("name") != calibration.BASELINE_ARM) \
        if isinstance(arms, list) else None
    subject = arm.get("subject") if isinstance(arm, dict) else None
    if not isinstance(subject, dict):
        raise CalibrationRefused("the treatment arm declares no subject")
    return subject


def plan_calibration(
    declaration: calibration.CalibrationDeclaration, store: Path, *,
    root: Path, treatment_digest: str, image_digest: str | None,
) -> tuple[trial.Experiment, list[mp.ScheduledAttempt]]:
    """Plan one trial per attempt through the real controller, in
    `arm_order.sequence`. `repeat` is the arm's own 1-based attempt count."""
    client_name, client_version = declared_client(declaration)
    grader = verify.GraderDef.load(root / declaration.task_path)
    trials: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for position, arm in enumerate(declaration.arm_order, start=1):
        counts[arm] = counts.get(arm, 0) + 1
        trials.append({
            "label": f"{TRIAL_PREFIX}_{arm}_{counts[arm]}",
            "case": {"id": declaration.grader_id, "revision": declaration.grader_revision},
            # The full identity, digest included (#139): the verifier stores no
            # result against a ledger that pins no grader digest.
            "grader": grader.identity(),
            "subject": {"digest": mp.BASELINE_SUBJECT_DIGEST if arm == calibration.BASELINE_ARM else treatment_digest},
            "client": {"name": client_name, "version": client_version},
            "image": {"digest": image_digest or UNKNOWN},
            "config": {"arm": arm, "repeat": counts[arm], "position": position},
            "attempts": 1,
        })
    try:
        experiment = trial.plan({"experiment": EXPERIMENT_LABEL, "trials": trials}, store)
    except trial.Refused as exc:
        raise CalibrationRefused(f"the controller refused the schedule: {exc}") from exc
    pairs = list(experiment.attempts())
    if len(pairs) != len(trials):
        raise CalibrationRefused(f"planned {len(pairs)} attempts for {len(trials)} trials")
    schedule = []
    for (planned_trial, attempt), spec in zip(pairs, trials, strict=True):
        config = spec["config"]
        assert isinstance(config, dict)
        schedule.append(mp.ScheduledAttempt(
            attempt_id=str(attempt["attempt_id"]), trial_id=str(planned_trial["trial_id"]),
            arm=str(config["arm"]), repeat=int(config["repeat"]),
        ))
    return experiment, schedule


def schedule_from_ledger(experiment: trial.Experiment) -> list[mp.ScheduledAttempt]:
    """The planned schedule, recovered from the ledger alone - what
    `matched_pilot.reconcile` checks the outcomes against."""
    schedule = []
    for planned_trial, attempt in experiment.attempts():
        trial_id = str(planned_trial["trial_id"])
        match = _TRIAL_ID_RE.match(trial_id)
        if match is None:
            raise CalibrationRefused(f"ledger trial {trial_id!r} is not a calibration trial")
        schedule.append(mp.ScheduledAttempt(str(attempt["attempt_id"]), trial_id, match["arm"], int(match["k"])))
    return schedule


def reconcile(experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome]) -> list[mp.AttemptOutcome]:
    """One outcome per planned attempt, in ledger (= declared) order; none dropped."""
    return mp.reconcile(experiment, outcomes, schedule_from_ledger(experiment))


def write_outcomes(
    run_dir: Path, experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome],
    declaration: calibration.CalibrationDeclaration,
) -> Path:
    """The private, resumable per-run record (`matched_pilot.read_outcomes`
    reads it back). Rewritten after every attempt, and before the first, so
    an interruption still leaves a store to reconcile. Carries the model and
    effort the run DECLARED, so a rebuilt report is scored against the pin it
    launched with."""
    model, effort = declared_model(declaration)
    path = run_dir / OUTCOMES_FILENAME
    tmp = path.with_suffix(".tmp")
    data = {
        "experiment_root": str(experiment.root),
        "declared": {"model": model, "reasoning_effort": effort, "arm_order": list(declaration.arm_order)},
        "outcomes": [o.to_json() for o in outcomes],
    }
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def run_calibration(
    declaration: calibration.CalibrationDeclaration,
    *,
    run_dir: Path,
    treatment: Treatment,
    image_digest: str | None,
    backends: Callable[[], tuple[object, object]],
    argv_for: Callable[[mp.ScheduledAttempt], Sequence[str]],
    root: Path = ROOT,
    credential_explicit_path: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    total_seconds: float | None = None,
) -> tuple[trial.Experiment, list[mp.AttemptOutcome]]:
    """Authorize, plan and run the whole declared schedule. `backends()`
    returns a fresh `(agent backend, grading backend)` pair per attempt;
    `argv_for` gives the BASE client invocation (a real run passes the same
    one every time; a test's scripted client needs the attempt id), to which
    the declared model and effort are added. `total_seconds` overrides the
    declared total cap - for tests only; the CLI never sets it."""
    # ADR 0005: nothing - no store, no plan, no container - before this.
    calibration.require_approved(declaration, root)
    model, effort = declared_model(declaration)
    client_name, client_version = declared_client(declaration)
    mp.pin_model_argv(model, effort, [])
    task_root = root / declaration.task_path
    try:
        surface = cc.surface_mapping(cc.task_surface(task_root / "fixture"))
    except demo.SubjectRefused as exc:
        raise CalibrationRefused(str(exc)) from exc
    per_attempt = float(str(declaration.shared["per_attempt_seconds"]))
    total = float(str(declaration.shared["total_seconds"])) if total_seconds is None else total_seconds

    goal = (task_root / "goal.md").read_text(encoding="utf-8")
    installed = treatment.receipt_context.declared if treatment.receipt_context is not None else frozenset()
    for arm, skills in named_skills_by_arm(declaration).items():
        absent = sorted(set(skills) - installed)
        if absent:
            # A P arm told to read a skill the install does not hold would
            # make its zero uptake a configuration error (counter-model review).
            raise CalibrationRefused(f"arm {arm!r} names {absent}, which the treatment does not install")

    store = trial.open_store(run_dir / "store", forbidden=[])
    experiment, schedule = plan_calibration(
        declaration, store, root=root, treatment_digest=treatment.digest, image_digest=image_digest,
    )
    outcomes: list[mp.AttemptOutcome] = []
    write_outcomes(run_dir, experiment, outcomes, declaration)

    def run_attempt(scheduled: mp.ScheduledAttempt, budget: float) -> dict[str, object]:
        treated = scheduled.arm != calibration.BASELINE_ARM
        instruction = calibration.arm_spec(declaration, scheduled.arm).get("instruction")
        prompt = f"{goal.rstrip()}\n\n{instruction}\n" if isinstance(instruction, str) else goal
        agent_backend, grading_backend = backends()
        return cc.run_level1_agent_attempt(
            experiment=experiment, attempt_id=scheduled.attempt_id,
            backend=agent_backend, grading_backend=grading_backend,  # type: ignore[arg-type]
            base=run_dir, base_argv=mp.pin_model_argv(model, effort, argv_for(scheduled)),
            extra_home_files=treatment.home_files if treated else {},
            client=client_name, cli_version=client_version, task_root=task_root, surface=surface, prompt=prompt,
            timeout=budget, credential_explicit_path=credential_explicit_path,
            receipt_context=treatment.receipt_context if treated else None,
        )

    def on_outcome(outcome: mp.AttemptOutcome) -> None:
        outcomes.append(outcome)
        write_outcomes(run_dir, experiment, outcomes, declaration)

    try:
        mp.run_schedule(
            experiment, schedule, run_attempt, total_seconds=total, per_attempt_seconds=per_attempt,
            clock=clock, on_outcome=on_outcome,
        )
    except KeyboardInterrupt:
        # An operator's interrupt still accounts for every planned attempt
        # (counter-model review): the ones that never ran are finalized from
        # the ledger and the private record is rewritten whole, so the report
        # the CLI then writes covers the declared schedule, not a prefix of it.
        # A kill that cannot be caught leaves `outcomes.json` as the last
        # checkpoint; `reconcile` over it gives the same accounting.
        write_outcomes(run_dir, experiment, reconcile(experiment, outcomes), declaration)
        raise
    return experiment, outcomes


def verified_result(experiment: trial.Experiment, record: Mapping[str, object]) -> dict[str, object] | None:
    """The attempt's stored `verified-result`, named by its own graded
    record, or `None` when it has none (never graded, or never stored)."""
    graded = record.get("graded")
    result_id = graded.get("result_id") if isinstance(graded, dict) else None
    if not isinstance(result_id, str) or not _RESULT_ID_RE.fullmatch(result_id):
        return None
    path = experiment.root / f"result-{result_id}.json"
    if path.is_symlink() or not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def named_skills_by_arm(declaration: calibration.CalibrationDeclaration) -> dict[str, tuple[str, ...]]:
    """Each provided-skill arm's declared `named_skills` (#231)."""
    named: dict[str, tuple[str, ...]] = {}
    for arm in declaration.arms:
        skills = calibration.arm_spec(declaration, arm).get("named_skills")
        if isinstance(skills, list):
            named[arm] = tuple(str(k) for k in skills)
    return named


def observation_confirmed(obs: Mapping[str, object]) -> bool:
    """The attempt's own transcript was found and read: not an unknown
    observation, exactly one transcript file, and that file's first user
    message is this attempt's prompt. The same confirmation
    `selection_probe` requires (counter-model review on #231): the reader
    records `skill_invocations=[]` when it found no transcript or several,
    and that empty list is not evidence that nothing was opened."""
    return (
        bool(obs) and obs.get("status") != "unknown" and obs.get("transcript_files_found") == 1
        and obs.get("prompt_delivered") is True
    )


def _opened(invocations: object, named: Sequence[str] | None = None, *, confirmed: bool = True) -> object:
    """Whether the attempt's recorded `skill_invocations` show a skill opened
    (any, or one of `named`): True/False from a recorded list of a confirmed
    observation, `UNKNOWN` otherwise. Never False for an attempt that was not
    observed."""
    if not confirmed or not isinstance(invocations, list):
        return UNKNOWN
    names = {str(i) for i in invocations}
    return bool(names & set(named)) if named is not None else bool(names)


def build_report(
    experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome], *,
    declared_model: str, declared_effort: str, named_skills: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """One entry per attempt, in the declared order: the primary endpoint,
    readiness beside it, and the model check. `model_eligible` uses the key
    `matched_pilot.ineligible_attempts` reads, so the CLI's refusal is the
    pilot's own.

    Uptake (#231, #203 ruling 3c) is reported beside the endpoint, never
    inside it: `skill_opened` for every attempt, and for a provided-skill arm
    (`named_skills`) `named_skill_opened` - which decides whether that attempt
    counts toward the value comparison."""
    named_skills = named_skills or {}
    entries: list[dict[str, object]] = []
    for position, outcome in enumerate(outcomes, start=1):
        record = outcome.record
        observation = record.get("observation")
        obs = observation if isinstance(observation, dict) else {}
        meta = obs.get("run_metadata")
        meta = meta if isinstance(meta, dict) else {}
        disposition = record.get("disposition")
        observed_model = str(meta.get("model") or UNKNOWN)
        observed_effort = str(meta.get("reasoning_effort") or UNKNOWN)
        agent = mp.agent_seconds(experiment, outcome.scheduled.attempt_id) if disposition != "not-run" else None
        entries.append({
            "position": position,
            "attempt_id": outcome.scheduled.attempt_id,
            "trial_id": outcome.scheduled.trial_id,
            "arm": outcome.scheduled.arm,
            "repeat": outcome.scheduled.repeat,
            "disposition": disposition,
            "primary_endpoint": calibration.primary_endpoint(record),
            "readiness_beside": calibration.readiness_beside(verified_result(experiment, record)),
            "model_declared": declared_model,
            "model_observed": observed_model,
            "model_eligible": mp.model_eligibility(disposition, observed_model, declared_model),
            "reasoning_effort_declared": declared_effort,
            "reasoning_effort_observed": observed_effort,
            "time_seconds": mp._time_split(outcome, agent),
            "tokens": meta.get("token_usage") if meta.get("token_usage") is not None else UNKNOWN,
            "skill_invocations": obs.get("skill_invocations", UNKNOWN),
            "skill_opened": _opened(obs.get("skill_invocations"), confirmed=observation_confirmed(obs)),
            **({"named_skill_opened": _opened(obs.get("skill_invocations"), named_skills[outcome.scheduled.arm],
                                              confirmed=observation_confirmed(obs))}
               if outcome.scheduled.arm in named_skills else {}),
            "transcript_retention": record.get("transcript_retention", UNKNOWN),
            "runner_note": outcome.runner_note,
        })
    return {
        "version": 1,
        "kind": REPORT_KIND,
        "experiment_id": experiment.id,
        "attempts": entries,
        "arms": summarize_arms(entries),
    }


def summarize_arms(entries: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    """Per-arm counts of the primary endpoint - description, not inference.
    `opened` is the uptake rate's numerator and `observed` its denominator
    (k/n, #203 ruling 3c): an attempt whose invocations were not recorded is
    in neither. A provided-skill arm also counts `named_opened`, the attempts
    eligible for the value comparison."""
    arms: dict[str, dict[str, object]] = {}
    for entry in entries:
        arm = str(entry.get("arm"))
        summary = arms.setdefault(arm, {"scheduled": 0, "primary": {}, "model_ineligible": 0,
                                        "opened": 0, "observed": 0})
        summary["scheduled"] = int(str(summary["scheduled"])) + 1
        if entry.get("skill_opened") in (True, False):
            summary["observed"] = int(str(summary["observed"])) + 1
            summary["opened"] = int(str(summary["opened"])) + (entry.get("skill_opened") is True)
        if "named_skill_opened" in entry:
            summary["named_opened"] = int(str(summary.get("named_opened", 0))) + (entry["named_skill_opened"] is True)
        endpoint = entry.get("primary_endpoint")
        status = str(endpoint.get("status")) if isinstance(endpoint, dict) else calibration.NOT_GRADED
        primary = summary["primary"]
        assert isinstance(primary, dict)
        primary[status] = primary.get(status, 0) + 1
        if entry.get("model_eligible") is False:
            summary["model_ineligible"] = int(str(summary["model_ineligible"])) + 1
    return arms


def paste_back(report: Mapping[str, object]) -> str:
    """The printed summary: one line per attempt, the primary endpoint first
    and readiness beside it. Leak-checked by `demo.print_paste_back`."""
    lines = [f"calibration-run: experiment {report.get('experiment_id')}"]
    attempts = report.get("attempts")
    for entry in attempts if isinstance(attempts, list) else []:
        primary = entry.get("primary_endpoint") or {}
        ready = entry.get("readiness_beside") or {}
        lines.append(
            f"  {entry.get('position')}. {entry.get('arm')} ({entry.get('attempt_id')}): "
            f"disposition={entry.get('disposition')} primary={primary.get('status')} "
            f"| installation-ready={ready.get('installation_ready')} verified={ready.get('verified_status')} "
            f"| model={entry.get('model_observed')} eligible={entry.get('model_eligible')}"
        )
    arms = report.get("arms")
    for arm, summary in (arms.items() if isinstance(arms, dict) else []):
        named = f" named_opened={summary.get('named_opened')}" if "named_opened" in summary else ""
        lines.append(f"  [{arm}] scheduled={summary.get('scheduled')} primary={summary.get('primary')} "
                     f"opened={summary.get('opened')}/{summary.get('observed')}{named} "
                     f"model_ineligible={summary.get('model_ineligible')}")
    return "\n".join(lines)
