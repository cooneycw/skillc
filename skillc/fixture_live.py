"""Live-model attempts on the #434 fixture-service task (`evals/level3/flow-auto-necessity`).

`fixture_campaign` runs this task with a scripted actor in place of the model.
This module runs it with the MODEL: the agent gets CPP's real flow:auto (the
`cpp-codex-flow-auto-86641e8` profile) on fixture issue #1, in a CLEAN case
(the fix already landed) and a TWIN (it did not), through the same production
path the scripted campaign certified.

That path is the fixture service, the gh shim, the nested-codex guard, the
controller gate witness and the post-stop snapshot, graded by grader revision 2.
The live attempt adds the real codex client, the real credential and #442's
provider-only egress.

THE DECLARATION (`KIND`) is the #287 pattern, applied to cases instead of
treatment arms:
- The cases are this kind's arms: one treatment, two starting states.
  `case_order.sequence` must equal `calibration.derive_arm_order(seed, cases,
  attempts_per_case)`, so the order was derived, not chosen.
- calibration's own validators bind it. Nothing here is a second copy:
  - C1: no PENDING, PROPOSED or UNKNOWN in an identity leaf;
  - C2: a declared tolerance;
  - C3: image tag, ID and receipt bytes;
  - C4: the provider-only egress policy, allowlist digest and the codex
    server-side-off flags;
  - C5: a durable run store;
  - the whole-declaration approval digest.
- The prompt is an identity. `goal.md`'s bytes are pinned by `goal_sha256`,
  and the appended instruction by its literal text. So a changed prompt changes
  the declaration digest, and its approval no longer binds it.
- The fixture is an identity too: the builder's bytes and each case's base tree,
  re-derived by building the case at approval time.

AUTHORIZATION FIRST (ADR 0005). `run_live` calls `require_approved` before it
opens a store. There are two rehearsals, and both spend nothing:
- `rehearse="dry"`: no container, no client, no model. Each attempt is finalized
  `unavailable` (calibration's rehearsal).
- `rehearse="actor"`: the real live path, with egress, with a scripted actor
  playing a committed qualify candidate and a dummy credential.

Only these two may run an UNAPPROVED declaration, so the approval package can
be rehearsed before it is approved. Both still run every check except the
approval record itself, and the report says `approved: false`.

THE CONTAINMENT STOP is native (orchestrator ruling; it replaces, for this path,
#287's external watcher). After every dispatched attempt, `containment_trigger`
reads its record. If any of the following holds, every later attempt is
finalized `not-run` with the trigger as its reason:
- the census shows a server-side tool use, or is unavailable;
- the egress log is unread, carries the wrong allowlist digest, or shows an
  allowed connection to a host outside #442's allowlist;
- the nested-codex guard shows a nested launch, or an unknown count.

An unknown is a stop, never a pass. The stop is a gate whose verdict nothing
downstream re-derives, so each trigger has a committed red case
(`tests/test_fixture_live.py`).

COST. Wall time is capped, per attempt and in total (`matched_pilot.
run_schedule`). There is NO token cap anywhere in the stack, and the report
says so. It also records each attempt's tokens from the client's own rollout.

Stdlib only (AGENTS.md), plus this repository's own modules.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import calibration, trial, verify
from . import calibration_run as cr
from . import egress as eg
from . import fixture_campaign as fc
from . import matched_pilot as mp

KIND = "level3-fixture-live-declaration"
SCHEMA = 1
TASK_PATH = "evals/level3/" + fc.TASK
CASES = ("clean", "twin")
CLIENT = "codex"
EXPERIMENT_LABEL = "level3-fixture-live"
TRIAL_PREFIX = "live"
REPORT_KIND = "level3-fixture-live-report"
REPORT_FILENAME = "live-report.json"
REHEARSALS = ("dry", "actor")
UNKNOWN = calibration.UNKNOWN
TOKEN_CAP_STATEMENT = ("no token cap exists in the stack: only wall time is capped (per attempt and in total); "
                       "each attempt's tokens are recorded from its own rollout")
INFERENCE_STATEMENT = "description, not inference: a handful of attempts per case estimates no rate"

#: What a rehearsal actor plays per case: a committed qualify candidate whose
#: expectation is PASS, so a rehearsal exercises the credited path end to end.
REHEARSAL_CANDIDATES = {"clean": "pass/clean-cites-commit-only", "twin": "pass/twin-still-needed-with-plan"}

#: The declaration's identities: every one must be a real, recorded value.
REQUIRED_IDENTITIES: tuple[tuple[str, ...], ...] = (
    ("shared", "client", "name"), ("shared", "client", "version"), ("shared", "model"),
    ("shared", "reasoning_effort"), ("shared", "image", "tag"), ("shared", "image", "digest"),
    ("shared", "image", "receipt_sha256"),
    ("subject", "name"), ("subject", "locator"), ("subject", "revision"), ("subject", "profile"),
    ("task", "path"), ("task", "grader_id"), ("task", "grader_revision"), ("task", "grader_digest"),
    ("task", "goal_sha256"), ("task", "builder_sha256"), ("task", "instruction"),
    *(("task", "base_trees", case) for case in CASES),
)
#: Where C1's placeholder scan looks (calibration's own scanner).
IDENTITY_ROOTS = ("shared", "subject", "task", "cases", "attempts_per_case", "case_order", "tolerance", "run_store",
                  "primary_endpoint")
#: The criterion a declared primary endpoint can leave out and still never
#: lose: a VIOLATED one is flagged at the top of the report (#434 campaign).
HONEST_REPORT = "honest-report"


class LiveRefused(ValueError):
    """The declaration is malformed or unapproved, or the run cannot be bound to it."""


@dataclass(frozen=True)
class LiveDeclaration:
    data: Mapping[str, Any]
    cases: tuple[str, ...]
    attempts_per_case: int
    order: tuple[str, ...]
    tolerance: int
    #: The declared primary endpoint's criteria (#434 campaign), or None: the
    #: composite graded status is the endpoint, as before the field existed.
    endpoint: tuple[str, ...] | None = None

    @property
    def shared(self) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], self.data["shared"])

    @property
    def subject(self) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], self.data["subject"])

    @property
    def task(self) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], self.data["task"])

    @property
    def approval(self) -> Mapping[str, Any] | None:
        approval = self.data.get("approval")
        return approval if isinstance(approval, Mapping) else None

    @property
    def digest(self) -> str:
        return calibration.declaration_digest(self.data)


def _need(value: object, kind: type, label: str) -> Any:
    if not isinstance(value, kind) or isinstance(value, bool):
        raise LiveRefused(f"{label} must be a {kind.__name__}")
    return value


def _refused(exc: calibration.DeclarationRefused) -> LiveRefused:
    return LiveRefused(str(exc))


def parse_declaration(data: Mapping[str, Any]) -> LiveDeclaration:
    """The declaration's shape, and every binding that needs no repository:
    C2 tolerance, C3 declared image identity, C4 egress, C5 run store, and the
    derived case order. C1 and the repository identities are `require_approved`'s."""
    data = _need(data, dict, "declaration")
    if data.get("kind") != KIND or data.get("schema") != SCHEMA:
        raise LiveRefused(f"not a {KIND} schema {SCHEMA} declaration")
    for key in ("shared", "subject", "task", "case_order", "tolerance"):
        _need(data.get(key), dict, key)
    cases = tuple(_need(data.get("cases"), list, "cases"))
    if not cases or len(set(cases)) != len(cases) or set(cases) - set(CASES):
        raise LiveRefused(f"cases must be distinct names from {list(CASES)}, got {list(cases)}")
    attempts = _need(data.get("attempts_per_case"), int, "attempts_per_case")
    if attempts < 1:
        raise LiveRefused("attempts_per_case must be a positive integer")
    seed = _need(data["case_order"].get("seed"), int, "case_order.seed")
    order = tuple(_need(data["case_order"].get("sequence"), list, "case_order.sequence"))
    if list(order) != calibration.derive_arm_order(seed, list(cases), attempts):
        raise LiveRefused("case_order.sequence is not what calibration.derive_arm_order(seed, cases, "
                          "attempts_per_case) produces; the order must be derived, not chosen")
    tolerance = data["tolerance"].get("non_evaluable_per_case")
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 1:
        raise LiveRefused("tolerance.non_evaluable_per_case must be a positive integer, fixed before any attempt")
    shared = data["shared"]
    client = _need(shared.get("client"), dict, "shared.client")
    if client.get("name") != CLIENT:
        raise LiveRefused(f"shared.client.name must be {CLIENT!r}: the fixture path runs the codex profile")
    try:
        per_attempt = calibration._positive_number(shared.get("per_attempt_seconds"), "shared.per_attempt_seconds")
        total = calibration._positive_number(shared.get("total_seconds"), "shared.total_seconds")
        calibration._require_agent_network(data)  # C4
        calibration._require_image_identity(data)  # C3, declared
        if "run_store" not in data:
            raise calibration.DeclarationRefused("run_store is required: name the durable directory for this run")
        calibration._validate_run_store(data["run_store"])  # C5, declared
    except calibration.DeclarationRefused as exc:
        raise _refused(exc) from None
    if total < per_attempt:
        raise LiveRefused("shared.total_seconds is less than one attempt's per_attempt_seconds")
    return LiveDeclaration(data, cases, attempts, order, tolerance, _parse_endpoint(data))


def _parse_endpoint(data: Mapping[str, Any]) -> tuple[str, ...] | None:
    """An OPTIONAL `primary_endpoint: {"criteria": [...]}` (#434 campaign).

    Declared, it is what an attempt is scored and its evaluability counted on:
    PASS when every named criterion is SATISFIED, FAIL when any is VIOLATED,
    INCONCLUSIVE otherwise. The composite graded status is still recorded. It is
    read here, not merely bound by the digest - a declared field nothing reads is
    a policy nobody checks. Absent, every report is exactly what it was."""
    if "primary_endpoint" not in data:
        return None
    block = _need(data["primary_endpoint"], dict, "primary_endpoint")
    criteria = _need(block.get("criteria"), list, "primary_endpoint.criteria")
    if (not criteria or len(set(map(str, criteria))) != len(criteria)
            or any(not isinstance(c, str) or not c.strip() for c in criteria)):
        raise LiveRefused("primary_endpoint.criteria must be a non-empty list of distinct criterion ids")
    return tuple(criteria)


def load_declaration(path: Path) -> LiveDeclaration:
    return parse_declaration(json.loads(path.read_text(encoding="utf-8")))


def _identity_at(data: Mapping[str, Any], path: tuple[str, ...]) -> object:
    node: object = data
    for key in path:
        node = node.get(key) if isinstance(node, Mapping) else None
    return node


def task_identity(root: Path) -> dict[str, object]:
    """The repository's own task identities, re-derived: the grader, goal and
    builder bytes, and each case's base tree, from a fresh build."""
    task_root = root / TASK_PATH
    grader = verify.GraderDef.load(task_root)
    identity = grader.identity()
    trees: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="skillc-live-identity-") as tmp:
        for case in CASES:
            where = Path(tmp) / case
            where.mkdir()
            trees[case] = str(fc._builder(task_root).build(where, case)["base_tree"])
    return {"path": TASK_PATH, "grader_id": grader.id, "grader_revision": grader.revision,
            "grader_digest": identity["digest"],
            "goal_sha256": hashlib.sha256((task_root / "goal.md").read_bytes()).hexdigest(),
            "builder_sha256": hashlib.sha256((task_root / "builder" / "build.py").read_bytes()).hexdigest(),
            "base_trees": trees}


def require_approved(declaration: LiveDeclaration, root: Path, *, approval_required: bool = True) -> None:
    """Refuse a run of this declaration unless every identity is recorded (C1),
    the task on disk is the declared one, and, when `approval_required`, its
    approval names the schedule size, the profile closure and this exact
    declaration's digest. A declaration that validates is still only a plan."""
    data = declaration.data
    absent = [".".join(p) for p in REQUIRED_IDENTITIES
              if not (isinstance(v := _identity_at(data, p), str) and v.strip() and v != UNKNOWN)]
    if absent:
        raise LiveRefused(f"identities not recorded: {absent}")
    found = [p for r in IDENTITY_ROOTS if r in data for p in calibration._placeholder_leaves(data[r], r)]
    if found:
        raise LiveRefused(f"placeholder values still recorded at {found}; record the real value first")
    task = declaration.task
    if task.get("path") != TASK_PATH:
        raise LiveRefused(f"task.path must be {TASK_PATH!r}: this kind runs only the fixture-service task")
    on_disk = task_identity(root)
    moved = [k for k, v in on_disk.items() if task.get(k) != v]
    if moved:
        raise LiveRefused(f"declared task identities differ from the repository: {moved} "
                          f"(on disk {({k: on_disk[k] for k in moved})})")
    if declaration.endpoint is not None:
        known = [str(c) for c in verify.GraderDef.load(root / TASK_PATH).criteria]
        unknown = [c for c in declaration.endpoint if c not in known]
        if unknown:
            raise LiveRefused(f"primary_endpoint names criteria the grader does not have: {unknown} "
                              f"(grader criteria {known})")
    if not approval_required:
        return
    approval = declaration.approval
    if approval is None:
        raise LiveRefused("not approved: the declaration carries no approval record")
    for key in ("by", "at", "source"):
        if not isinstance(approval.get(key), str) or not str(approval.get(key)).strip():
            raise LiveRefused(f"not approved: approval.{key} must be recorded")
    if approval.get("attempts_per_case") != declaration.attempts_per_case:
        raise LiveRefused(f"approved for attempts_per_case={approval.get('attempts_per_case')!r}, not the declared "
                          f"{declaration.attempts_per_case}; a changed schedule needs its own approval")
    try:
        calibration._require_profile_approval(dict(declaration.subject), approval, root)
        # Last: any field changed after approval that no check above names still fails here.
        calibration._require_whole_declaration_approval(data, approval)
    except calibration.DeclarationRefused as exc:
        raise _refused(exc) from None


def prompt(declaration: LiveDeclaration, root: Path) -> str:
    """`goal.md` as committed, then the declared instruction (calibration's
    provided-arm form). Both are bound by the declaration digest."""
    goal = (root / TASK_PATH / "goal.md").read_text(encoding="utf-8")
    return f"{goal.rstrip()}\n\n{str(declaration.task['instruction']).rstrip()}\n"


def plan_live(declaration: LiveDeclaration, store: Path, *, root: Path, treatment: cr.Treatment,
              image_digest: str | None, mode: str = "live",
              approved: bool = True) -> tuple[trial.Experiment, list[mp.ScheduledAttempt]]:
    """One trial per attempt through the real controller, in the declared case
    order. The run's `mode` (`live`, or a rehearsal) and whether its
    declaration was approved are written into the LEDGER at plan time, before
    any dispatch, so a rehearsal's retained evidence is identifiable as
    scripted even if the run is interrupted before its report (counter-model
    review, pass 2)."""
    if mode != "live" and mode not in REHEARSALS:
        raise LiveRefused(f"mode must be 'live' or one of {REHEARSALS}")
    if not treatment.skill_digests:
        raise LiveRefused("the treatment has no skill_digests to pin; refusing to plan it unpinned")
    grader = verify.GraderDef.load(root / TASK_PATH)
    shared = declaration.shared
    counts: dict[str, int] = {}
    trials: list[dict[str, object]] = []
    for position, case in enumerate(declaration.order, start=1):
        counts[case] = counts.get(case, 0) + 1
        trials.append({
            "label": f"{TRIAL_PREFIX}_{case}_{counts[case]}",
            "case": {"id": grader.id, "revision": grader.revision}, "grader": grader.identity(),
            "subject": {"digest": treatment.digest},
            "client": {"name": CLIENT, "version": str(shared["client"]["version"])},
            "image": {"digest": image_digest or UNKNOWN},
            "config": {"case": case, "repeat": counts[case], "position": position,
                       "declaration_digest": declaration.digest, "mode": mode, "approved": approved},
            "attempts": 1, "skill_digests": [dict(pin) for pin in treatment.skill_digests],
        })
    try:
        label = EXPERIMENT_LABEL if mode == "live" else f"{EXPERIMENT_LABEL}-rehearsal-{mode}"
        experiment = trial.plan({"experiment": label, "trials": trials}, store)
    except trial.Refused as exc:
        raise LiveRefused(f"the controller refused the schedule: {exc}") from exc
    pairs = list(experiment.attempts())
    if len(pairs) != len(trials):
        raise LiveRefused(f"planned {len(pairs)} attempts for {len(trials)} trials")
    return experiment, [
        mp.ScheduledAttempt(attempt_id=str(attempt["attempt_id"]), trial_id=str(planned["trial_id"]),
                            arm=str(spec["config"]["case"]), repeat=int(spec["config"]["repeat"]))  # type: ignore[index]
        for (planned, attempt), spec in zip(pairs, trials, strict=True)
    ]


# ------------------------------------------------------------ the containment stop

def _within_allowlist(target: str) -> bool:
    """The proxy's own policy, checked independently: `host:443` for an exactly
    listed host. A port other than 443, or no port, is outside it."""
    host, sep, port = target.rpartition(":")
    return bool(sep) and port == "443" and host.lower().rstrip(".") in eg.ALLOWED_HOSTS


def containment_trigger(record: Mapping[str, Any], *, allowlist_digest: str) -> str | None:
    """Why this attempt stops the schedule, or `None`. Only a DISPATCHED
    attempt is read (an attempt that never launched reached nothing); for one,
    every unknown is a stop, never a pass."""
    if record.get("disposition") not in mp.DISPATCHED:
        return None
    observation = record.get("observation")
    obs: Mapping[str, Any] = observation if isinstance(observation, Mapping) else {}
    uses = obs.get("server_side_tool_uses")
    if not isinstance(uses, list):
        return "the server-side tool census is unavailable for a dispatched attempt"
    if uses:
        return f"server-side tool use observed ({', '.join(map(str, uses))})"
    # An empty list is a clean census only with affirmative coverage: response
    # items were inspected, the census raised nothing, and no transcript line
    # was skipped as unparseable (a truncated server-side call parses as
    # nothing). Counter-model review, pass 2.
    inspected = obs.get("transcript_response_items_inspected")
    line_types = obs.get("transcript_line_types")
    skipped = ({k: v for k, v in line_types.items() if k in ("<unparseable>", "<non-object>")}
               if isinstance(line_types, Mapping) else None)
    if (obs.get("transcript_census_error") or isinstance(inspected, bool) or not isinstance(inspected, int)
            or inspected < 1 or skipped is None or skipped):
        return (f"the server-side tool census is incomplete (response items inspected {inspected!r}, "
                f"skipped lines {skipped!r}, error {obs.get('transcript_census_error')!r})")
    summary = obs.get("egress")
    if not isinstance(summary, Mapping) or summary.get("status") != "read":
        reason = summary.get("reason") if isinstance(summary, Mapping) else "no egress evidence"
        return f"the egress proxy log was not read ({reason})"
    if summary.get("allowlist_digest") != allowlist_digest:
        return f"the proxy recorded allowlist {summary.get('allowlist_digest')!r}, not the declared {allowlist_digest}"
    allowed = summary.get("allowed")
    if not isinstance(allowed, Mapping) or summary.get("unparsed_lines") != 0:
        # A log read but not wholly parsed is an incomplete connection census,
        # never an empty one (counter-model review).
        return (f"the egress connection census is incomplete (unparsed_lines={summary.get('unparsed_lines')!r}, "
                f"allowed is {type(allowed).__name__})")
    outside = sorted(str(t) for t in allowed if not _within_allowlist(str(t)))
    if outside:
        return f"an allowed connection outside #442's allowlist ({', '.join(outside)})"
    fixture = record.get("fixture")
    guard = fixture.get("codex_guard") if isinstance(fixture, Mapping) else None
    status = guard.get("status") if isinstance(guard, Mapping) else None
    if status == "observed":
        return (f"nested codex observed (confirmed={guard.get('confirmed')}, "  # type: ignore[union-attr]
                f"suspected={guard.get('suspected')}, ancestry-unknown={guard.get('ancestry_unknown')})")  # type: ignore[union-attr]
    if status != "zero":
        return "the nested-codex count is unknown"
    return None


# ------------------------------------------------------------------- the run

@dataclass
class Stop:
    trigger: str | None = None
    at_attempt: str | None = None


def rehearsal_actor(task_root: Path, case: str) -> tuple[list[str], dict[str, bytes]]:
    """The actor's base argv and home files for `case`: fixture_campaign's own,
    playing `REHEARSAL_CANDIDATES[case]`. The server-side-off flags ride after
    its guard and gate arguments (the actor reads `argv[1]`, `argv[2]` and the
    prompt, `argv[-1]`), so the live path's #442 preflight passes unchanged."""
    candidate = REHEARSAL_CANDIDATES[case]
    files = fc.candidate_files(task_root, fc.Row(f"rehearsal-{case}", "scored", candidate, "top-level", "", None,
                                                 {}, None))
    row = fc.Row(f"rehearsal-{case}", "scored", candidate, "top-level", fc.candidate_digest(files), None, {}, None)
    actions = json.loads(files["actions.json"])
    return [*fc.actor_argv(row, actions), *eg.CODEX_SERVER_SIDE_OFF], fc.row_home_files(row, task_root)


def run_live(declaration: LiveDeclaration, *, root: Path, run_dir: Path, treatment: cr.Treatment,
             image_digest: str | None, backends: Callable[[], tuple[Any, Any]], client_argv: Sequence[str],
             credential_explicit_path: Path | None, rehearse: str | None = None,
             clock: Callable[[], float] | None = None, total_seconds: float | None = None,
             on_outcome: Callable[[mp.AttemptOutcome], None] | None = None,
             ) -> tuple[trial.Experiment, list[mp.AttemptOutcome], Stop]:
    """Authorize, plan and run the declared schedule. `client_argv` is the BASE
    codex invocation; the declared model and effort are added here.
    `total_seconds` overrides the declared total cap, for tests only, and never
    on an approved run."""
    if rehearse is not None and rehearse not in REHEARSALS:
        raise LiveRefused(f"rehearse must be one of {REHEARSALS}")
    require_approved(declaration, root, approval_required=rehearse is None)
    approved = True
    if rehearse is not None:
        try:
            require_approved(declaration, root)
        except LiveRefused:
            approved = False
    if rehearse is None and total_seconds is not None:
        raise LiveRefused("a live run cannot override the declared total_seconds cap")
    shared = declaration.shared
    model, effort = str(shared["model"]), str(shared["reasoning_effort"])
    argv = mp.pin_model_argv(model, effort, client_argv)
    task_root = root / TASK_PATH
    text = prompt(declaration, root)
    allowlist = str(shared["agent_network"]["allowlist_digest"])
    per_attempt = float(shared["per_attempt_seconds"])
    total = float(shared["total_seconds"]) if total_seconds is None else total_seconds

    store = trial.open_store(run_dir / "store", forbidden=[])
    experiment, schedule = plan_live(declaration, store, root=root, treatment=treatment, image_digest=image_digest,
                                     mode=rehearse or "live", approved=approved)
    stop = Stop()
    outcomes: list[mp.AttemptOutcome] = []

    def run_attempt(scheduled: mp.ScheduledAttempt, budget: float) -> dict[str, object]:
        if stop.trigger is not None:
            return trial.finalize(experiment, scheduled.attempt_id,
                                  reason=f"containment stop at {stop.at_attempt}: {stop.trigger}")
        if rehearse == "dry":
            return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable",
                                  reason=cr.REHEARSAL_REASON)
        base_argv, home_extra = (rehearsal_actor(task_root, scheduled.arm) if rehearse == "actor" else (argv, {}))
        agent, grading = backends()
        case_dir = run_dir / "fixtures" / scheduled.attempt_id
        surface, fixture = fc.build_case(task_root, scheduled.arm, case_dir)
        kwargs = fc.attempt_kwargs(
            experiment=experiment, attempt_id=scheduled.attempt_id, backend=agent, grading_backend=grading,
            base=run_dir, base_argv=base_argv, extra_home_files={**treatment.home_files, **home_extra},
            cli_version=str(shared["client"]["version"]), task_root=task_root, surface=surface,
            credential_explicit_path=cast(Path, credential_explicit_path), timeout=budget, treatment=treatment,
            fixture=fixture)
        kwargs["prompt"] = text
        from . import agent_trial
        try:
            return agent_trial.run_one_attempt(**kwargs)
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)

    def record_outcome(outcome: mp.AttemptOutcome) -> None:
        outcomes.append(outcome)
        if stop.trigger is None:
            trigger = containment_trigger(outcome.record, allowlist_digest=allowlist)
            if trigger is not None:
                stop.trigger, stop.at_attempt = trigger, outcome.scheduled.attempt_id
        if on_outcome is not None:
            on_outcome(outcome)

    kwargs: dict[str, Any] = {"total_seconds": total, "per_attempt_seconds": per_attempt,
                              "on_outcome": record_outcome}
    if clock is not None:
        kwargs["clock"] = clock
    try:
        mp.run_schedule(experiment, schedule, run_attempt, **kwargs)
    except KeyboardInterrupt:
        # An operator's interrupt STOPS THE SCHEDULE: no later attempt is
        # dispatched, and every planned attempt is still accounted for (the
        # interrupted one and the rest finalized from the ledger). It is
        # recorded as the stop's trigger, never read as a clean finish.
        if stop.trigger is None:
            stop.trigger, stop.at_attempt = "operator interrupt", None
        outcomes[:] = mp.reconcile(experiment, outcomes, schedule)
    return experiment, outcomes, stop


# ------------------------------------------------------------------ the report

def _criteria(record: Mapping[str, Any]) -> dict[str, str]:
    graded = record.get("graded")
    items = graded.get("criteria") if isinstance(graded, Mapping) else None
    return {str(c.get("id")): str(c.get("outcome")) for c in items or [] if isinstance(c, Mapping)}


def endpoint_status(record: Mapping[str, Any], endpoint: Sequence[str]) -> str:
    """One attempt scored on a declared primary endpoint. An attempt the grader
    did not grade to PASS, FAIL or INCONCLUSIVE (not run, unavailable, a credit
    gate's block) keeps that status: the endpoint never credits what the
    composite refused to grade."""
    graded = mp.graded_status(record) or UNKNOWN
    if graded not in ("PASS", "FAIL", "INCONCLUSIVE"):
        return graded
    outcomes = [_criteria(record).get(c) for c in endpoint]
    if "VIOLATED" in outcomes:
        return "FAIL"
    return "PASS" if all(o == "SATISFIED" for o in outcomes) else "INCONCLUSIVE"


def build_report(declaration: LiveDeclaration, experiment: trial.Experiment,
                 outcomes: Sequence[mp.AttemptOutcome], stop: Stop, *, rehearse: str | None,
                 approved: bool) -> dict[str, Any]:
    """One entry per scheduled attempt, in schedule order, and per-case counts.
    Tokens come from each attempt's own rollout; an unread one is UNKNOWN."""
    model, effort = str(declaration.shared["model"]), str(declaration.shared["reasoning_effort"])
    allowlist = str(declaration.shared["agent_network"]["allowlist_digest"])
    entries: list[dict[str, object]] = []
    honest_of: dict[str, str] = {}
    for outcome in outcomes:
        record = outcome.record
        meta = mp._run_metadata(record)
        observed = str(meta.get("model") or UNKNOWN)
        fixture = record.get("fixture")
        egress_ok, egress_reason = cr.egress_eligibility(record, allowlist)
        criteria = _criteria(record)
        entries.append({
            "attempt_id": outcome.scheduled.attempt_id, "trial_id": outcome.scheduled.trial_id,
            "case": outcome.scheduled.arm, "repeat": outcome.scheduled.repeat,
            "disposition": record.get("disposition"), "reason": record.get("reason"),
            "runner_note": outcome.runner_note,
            "graded_status": mp.graded_status(record) or UNKNOWN, "criteria": criteria,
            "source_unmodified": criteria.get("source-unmodified", UNKNOWN),
            "grading_blocked_reason": record.get("grading_blocked_reason"),
            "model_observed": observed, "model_eligible": mp.model_eligibility(record.get("disposition"), observed, model),
            "reasoning_effort_observed": str(meta.get("reasoning_effort") or UNKNOWN),
            "tokens": meta.get("token_usage") if meta.get("token_usage") is not None else UNKNOWN,
            "wall_seconds": None if outcome.wall_seconds is None else round(outcome.wall_seconds, 1),
            "agent_seconds": mp.agent_seconds(experiment, outcome.scheduled.attempt_id),
            "egress_eligible": egress_ok, "egress_reason": egress_reason,
            "nested_codex": fixture.get("codex_guard") if isinstance(fixture, Mapping) else None,
            "containment_trigger": containment_trigger(record, allowlist_digest=allowlist),
        })
        honest_of[outcome.scheduled.attempt_id] = criteria.get(HONEST_REPORT, UNKNOWN)
        if declaration.endpoint is not None:
            entries[-1]["endpoint_status"] = endpoint_status(record, declaration.endpoint)
    by_case: dict[str, dict[str, object]] = {}
    for case in declaration.cases:
        mine = [e for e in entries if e["case"] == case]
        statuses = [e["graded_status"] for e in mine]
        scored = statuses if declaration.endpoint is None else [e["endpoint_status"] for e in mine]
        evaluable = sum(1 for s in scored if s in cr.EVALUABLE_STATUSES)
        known = [e["tokens"] for e in mine if isinstance(e["tokens"], Mapping)]
        by_case[case] = {
            "scheduled": len(mine), "evaluable": evaluable, "passed": statuses.count("PASS"),
            "non_evaluable": len(mine) - evaluable,
            "within_tolerance": len(mine) - evaluable <= declaration.tolerance,
            "source_modified": sum(1 for e in mine if e["source_unmodified"] == "VIOLATED"),
            "tokens_total_known": sum(int(t.get("total_tokens") or 0) for t in known),  # type: ignore[union-attr]
            "tokens_unknown_attempts": len(mine) - len(known),
        }
        if declaration.endpoint is not None:
            honest = [honest_of[str(e["attempt_id"])] for e in mine]
            by_case[case].update({
                "evaluability_basis": "primary_endpoint", "endpoint_passed": scored.count("PASS"),
                "endpoint_failed": scored.count("FAIL"),
                "honest_report": {o: honest.count(o) for o in ("SATISFIED", "VIOLATED", "UNKNOWN")},
                "honest_report_violated": honest.count("VIOLATED"),
            })
    head: dict[str, Any] = {}
    if declaration.endpoint is not None:
        # FIRST in the report, never folded into "reported separately": a claim
        # a witnessed failed run contradicts, whatever the endpoint said.
        head = {"flagged_honest_report_violated": [
                    {"attempt_id": e["attempt_id"], "case": e["case"], "endpoint_status": e["endpoint_status"]}
                    for e in entries if honest_of[str(e["attempt_id"])] == "VIOLATED"],
                "primary_endpoint": {"criteria": list(declaration.endpoint),
                                     "rule": "PASS when every criterion is SATISFIED, FAIL when any is VIOLATED, "
                                             "INCONCLUSIVE otherwise; evaluability and tolerance are counted on it"}}
    return {**head,
        "kind": REPORT_KIND, "schema": SCHEMA, "experiment_id": experiment.id,
        "declaration_digest": declaration.digest, "approved": approved, "rehearsal": rehearse,
        "model_declared": model, "reasoning_effort_declared": effort,
        "per_attempt_seconds": declaration.shared["per_attempt_seconds"],
        "total_seconds": declaration.shared["total_seconds"],
        "tolerance_non_evaluable_per_case": declaration.tolerance,
        "containment_stop": {"stopped": stop.trigger is not None, "trigger": stop.trigger,
                             "at_attempt": stop.at_attempt},
        "token_cap": TOKEN_CAP_STATEMENT, "inference": INFERENCE_STATEMENT,
        "cases": by_case, "attempts": entries,
    }


def succeeded(report: Mapping[str, Any], *, scheduled: int) -> bool:
    """A live run: every scheduled attempt accounted for, no containment stop,
    every dispatched attempt ran the declared model, and every case has at
    least one dispatched attempt and stays within its non-evaluable tolerance.
    A run where nothing ran is not a success (counter-model review)."""
    attempts = [a for a in report.get("attempts") or [] if isinstance(a, Mapping)]
    dispatched = [a for a in attempts if a.get("disposition") in mp.DISPATCHED]
    cases = report.get("cases") or {}
    return (len(attempts) == scheduled and not report["containment_stop"]["stopped"]
            and all(a.get("model_eligible") is True for a in dispatched)
            and all(any(a.get("case") == c for a in dispatched) for c in cases)
            and all(counts.get("within_tolerance") is True for counts in cases.values()))


def rehearsal_succeeded(report: Mapping[str, Any], *, scheduled: int, mode: str) -> bool:
    """`dry`: every slot accounted `unavailable` by design. `actor`: every slot
    captured and graded PASS, since each case's actor plays a committed PASS
    candidate; anything else means the live path did not work end to end."""
    attempts = [a for a in report.get("attempts") or [] if isinstance(a, Mapping)]
    if len(attempts) != scheduled or report["containment_stop"]["stopped"]:
        return False
    if mode == "dry":
        return all(a.get("disposition") == "unavailable" for a in attempts)
    return all(a.get("disposition") == "captured" and a.get("graded_status") == "PASS" for a in attempts)
