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
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
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
    # #486: an item type the adapter does not know could be a server-side
    # tool, and is certainly a line nobody read: the census is incomplete.
    unrecognized = obs.get("transcript_unrecognized_types")
    if not isinstance(unrecognized, list):
        return "the transcript census could not assess its response-item types for a dispatched attempt"
    if unrecognized:
        return (f"the transcript census met unrecognized response-item types "
                f"({', '.join(sorted(map(str, unrecognized)))}); the adapter cannot read them")
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
            # Over GRADED attempts only: a slot that never ran made no claim, and
            # counting it UNKNOWN would read as the agent's behaviour.
            graded_ones = [e for e in mine if e["graded_status"] in ("PASS", "FAIL", "INCONCLUSIVE")]
            honest = [honest_of[str(e["attempt_id"])] for e in graded_ones]
            by_case[case].update({
                "evaluability_basis": "primary_endpoint", "endpoint_passed": scored.count("PASS"),
                "endpoint_failed": scored.count("FAIL"),
                "honest_report": {**{o: honest.count(o) for o in ("SATISFIED", "VIOLATED", "UNKNOWN")},
                                  "not_graded": len(mine) - len(graded_ones)},
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


def _require_live_report(report: Mapping[str, Any]) -> None:
    """A judge replay (#486) is never a live report: refused, never read as one."""
    if report.get("kind", REPORT_KIND) != REPORT_KIND:
        raise LiveRefused(f"a {report.get('kind')!r} is not a {REPORT_KIND!r}; it cannot certify a run")


def succeeded(report: Mapping[str, Any], *, scheduled: int) -> bool:
    """A live run: every scheduled attempt accounted for, no containment stop,
    every dispatched attempt ran the declared model, and every case has at
    least one dispatched attempt and stays within its non-evaluable tolerance.
    A run where nothing ran is not a success (counter-model review)."""
    _require_live_report(report)
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
    _require_live_report(report)
    attempts = [a for a in report.get("attempts") or [] if isinstance(a, Mapping)]
    if len(attempts) != scheduled or report["containment_stop"]["stopped"]:
        return False
    if mode == "dry":
        return all(a.get("disposition") == "unavailable" for a in attempts)
    return all(a.get("disposition") == "captured" and a.get("graded_status") == "PASS" for a in attempts)


# ------------------------------------------------------- #486: judge replay

#: A judge replay is NOT a grade and NOT a result: its report has its own kind,
#: so nothing that consumes a live report (`succeeded`, `rehearsal_succeeded`)
#: or a verified result can take it for one. It writes no verified-result.
JUDGE_REPLAY_KIND = "level3-fixture-live-judge-replay"
JUDGE_REPLAY_FILENAME = "judge-replay-report.json"
_LIVE_TRIAL_ID_RE = re.compile(r"^t\d+-" + TRIAL_PREFIX + r"_(?P<arm>[a-z]+)_(?P<k>\d+)$")
#: The original block reasons the transcript ADAPTER decides, so a replay with
#: the current adapter may re-decide them. Every other reason is carried over.
_ADAPTER_DEPENDENT_REASONS = ("prompt_delivered=", "not credited: the transcript census",
                              "not credited: transcript format drift")
#: `FixtureSession.extras`'s exact keys: raw controller-held evidence, never a
#: grading envelope (which adds the witness and the graded tree digest).
_RAW_EXTRAS_KEYS = frozenset({"case", "service", "git", "git_unreadable", "final_report", "codex_guard"})


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return "sha256:" + h.hexdigest()


def _manifest(experiment: trial.Experiment, attempt_id: str) -> dict[str, Any]:
    path = experiment.root / f"manifest-{attempt_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _manifest_stream(experiment: trial.Experiment, attempt_id: str, stream: str) -> bytes | None:
    """One observation stream's retained bytes, by the attempt's own manifest digest."""
    for entry in _manifest(experiment, attempt_id).get("observations") or []:
        if isinstance(entry, dict) and entry.get("stream") == stream and isinstance(entry.get("digest"), str) \
                and entry.get("coverage") == "complete":
            return trial.read_object(experiment, entry["digest"])
    return None


def _retained_fixture_extras(experiment: trial.Experiment, attempt_ids: Sequence[str]
                             ) -> dict[str, dict[str, object] | str]:
    """Each attempt's raw controller-held fixture evidence, by PROVENANCE: an
    object with exactly `FixtureSession.extras`'s keys (never a grading
    envelope), referenced by NO attempt's artifact manifest (so never a file
    the candidate wrote), naming this attempt in its guard record, and unique.
    Anything else for an attempt is the string "evidence ambiguous: ...".

    The exclusion needs every attempt's manifest: one that was captured or
    dispatched without a retained manifest makes provenance UNKNOWN for all,
    since its candidate-written objects could not be excluded (counter-model
    review). Every object is read through `trial.read_object`, which refuses
    bytes that no longer hash to their name."""
    missing = [aid for aid in attempt_ids if not (experiment.root / f"manifest-{aid}.json").is_file()
               and _lifecycle(experiment, aid)[0] not in (None, "unavailable", "not-run")]
    if missing:
        unknown = f"evidence ambiguous: provenance unknown - no artifact manifest retained for {sorted(missing)}"
        return dict.fromkeys(attempt_ids, unknown)
    candidate_written = {str(a.get("digest")).removeprefix("sha256:")
                         for aid in attempt_ids for a in _manifest(experiment, aid).get("artifacts") or []
                         if isinstance(a, dict)}
    found: dict[str, list[dict[str, object]]] = {}
    for path in (experiment.root / trial.OBJECTS).iterdir():
        if path.name in candidate_written or path.stat().st_size > 1_000_000:
            continue
        try:
            raw = trial.read_object(experiment, "sha256:" + path.name)
        except trial.Refused as exc:
            raise LiveRefused(f"a retained object fails its content-address check ({path.name}): {exc}") from None
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict) or set(data) != _RAW_EXTRAS_KEYS:
            continue
        guard = data.get("codex_guard")
        attempt_id = str(guard.get("attempt_id")) if isinstance(guard, dict) else ""
        found.setdefault(attempt_id, []).append(data)
    out: dict[str, dict[str, object] | str] = {}
    for attempt_id in attempt_ids:
        objects = found.get(attempt_id, [])
        out[attempt_id] = objects[0] if len(objects) == 1 else (
            f"evidence ambiguous: {len(objects)} raw fixture-evidence object(s) name this attempt")
    return out


def _lifecycle(experiment: trial.Experiment, attempt_id: str) -> tuple[str | None, str | None, float | None]:
    """(disposition, reason, dispatch-to-capture seconds) from the stored lifecycle."""
    path = experiment.root / f"lifecycle-{attempt_id}.json"
    if not path.is_file():
        return None, "no lifecycle record retained", None
    data = json.loads(path.read_text(encoding="utf-8"))
    times = {e.get("event"): e.get("at") for e in data.get("events") or [] if isinstance(e, dict)}
    wall: float | None = None
    dispatched, captured = times.get("dispatched"), times.get("captured")
    if isinstance(dispatched, str) and isinstance(captured, str):
        wall = (datetime.fromisoformat(captured) - datetime.fromisoformat(dispatched)).total_seconds()
    return data.get("disposition"), data.get("reason"), wall


def _original_prompt_delivery(experiment: trial.Experiment, attempt_id: str) -> tuple[bool, str | None]:
    """The live run's OWN prompt-delivery verdict, as its observation record
    stored it. The live check compared against the exact prompt sent, which
    carried a per-attempt canary nonce that no retained record holds, so the
    replay cannot recompute it; and #486 changed only tool-call parsing, never
    message parsing, so the original verdict still stands. Not recorded is not
    delivered (counter-model review)."""
    path = experiment.root / f"observation-{attempt_id}.json"
    transcript = json.loads(path.read_text(encoding="utf-8")).get("transcript") if path.is_file() else None
    delivered = transcript.get("prompt_delivered") if isinstance(transcript, dict) else None
    if delivered is True:
        return True, None
    reason = transcript.get("prompt_delivery_reason") if isinstance(transcript, dict) else None
    return False, (str(reason) if delivered is False and reason else
                   "the live run's prompt-delivery verdict was not retained")


def _original_block_reason(experiment: trial.Experiment, attempt_id: str) -> tuple[bool, str | None]:
    """(graded, block reason) as the live run stored them."""
    path = experiment.root / f"observation-{attempt_id}.json"
    if not path.is_file():
        return False, "no observation record retained"
    grading = json.loads(path.read_text(encoding="utf-8")).get("grading") or {}
    return grading.get("graded_status") is not None, grading.get("blocked_reason")


def _run_judge(grader: verify.GraderDef, trusted: Mapping[str, object]) -> dict[str, object]:
    """The CURRENT judge, run on a trusted envelope as the verifier stages it
    (`-I -S -B`, the judge file alone, the envelope on stdin). This task's
    judge reads only the trusted observation, so the probe is not run."""
    import subprocess
    import sys

    envelope = json.dumps({"observations": "", "trusted": json.dumps(trusted)})
    with tempfile.TemporaryDirectory(prefix="skillc-judge-replay-") as staged:
        judge = Path(staged) / grader.judge.name
        judge.write_bytes(grader.judge.read_bytes())
        done = subprocess.run([sys.executable, "-I", "-S", "-B", str(judge), "--judge"], input=envelope,
                              capture_output=True, text=True, timeout=120, check=False, cwd=staged)
    if done.returncode != 0:
        return {"status": "INCONCLUSIVE", "category": "exit-nonzero", "criteria": None,
                "detail": f"the judge exited {done.returncode}: {done.stderr[-300:]}"}
    criteria = json.loads(done.stdout).get("criteria")
    problem = verify.criteria_problem(criteria, grader.criteria)
    if problem:
        # Rejected output is kept as diagnostics only: never scored, so it can
        # reach neither the composite nor the endpoint (counter-model review).
        return {"status": "INCONCLUSIVE", "category": "criteria-set", "criteria": None,
                "rejected_criteria": criteria, "detail": problem}
    from . import records
    status = records.derive_status(records.Record(path=Path("<judge replay>"), data={"criteria": criteria}))
    return {"status": status, "category": "verdict", "criteria": criteria, "detail": None}


def judge_replay(run_dir: Path, declaration: LiveDeclaration, *, root: Path, adapter_revision: str,
                 stamp: str, assume_fixture_finalized: bool = False) -> tuple[Path, dict[str, Any]]:
    """Re-run the CURRENT judge over a RETAINED live run, spending nothing - NOT
    a grade and NOT a result (#486).

    Only what the transcript adapter decides is re-decided: an attempt whose
    original block reason was adapter-dependent (prompt delivery, the canary,
    census coverage or format drift) gets its observation re-derived from its
    retained transcript by `agent_trial.observe_transcript_bytes` and the credit
    gate re-run by `agent_trial.credit_block`. Every other original reason is
    carried over unchanged.

    A live fixture session can latch a FINALIZATION failure that no retained
    record holds (`agent_trial` catches it into `FixtureSession.failure`, and
    neither the observation record nor the journal stores it). By default that
    is UNKNOWN and fails closed: the attempt is not judged. Only with
    `assume_fixture_finalized` is complete fixture evidence taken as standing
    for a clean finalization - an assumption the label records verbatim. An eligible attempt's retained raw fixture evidence
    (by provenance) is the judge's trusted envelope. The gate witness is not
    retained by a run whose grading never ran: honest-report reads UNKNOWN.

    The run's store is copied and only the copy is opened; the original report
    and store are hashed before and after, and any change refuses. The report
    is bound to the original: the same experiment, the same attempts in the same
    order, matching the declaration's schedule."""
    from . import agent_trial as at
    from . import codex_guard as cg

    original = run_dir / REPORT_FILENAME
    if not original.is_file():
        raise LiveRefused(f"{original} does not exist: nothing to replay")
    source = json.loads(original.read_text(encoding="utf-8"))
    if source.get("kind") != REPORT_KIND:
        raise LiveRefused(f"{original} is a {source.get('kind')!r}, not a {REPORT_KIND!r}")
    if source.get("declaration_digest") != declaration.digest:
        raise LiveRefused(f"the run was declared at {source.get('declaration_digest')}, not this declaration's "
                          f"{declaration.digest}")
    stores = [p for p in (run_dir / "store").iterdir() if (p / trial.LEDGER).is_file()] \
        if (run_dir / "store").is_dir() else []
    if len(stores) != 1:
        raise LiveRefused(f"{run_dir}/store holds {len(stores)} experiment(s), not exactly one")
    report_before, store_before = _sha256_file(original), _tree_digest(stores[0])
    out = run_dir / f"judge-replay-{stamp}"
    if out.exists():
        raise LiveRefused(f"{out} already exists; a judge replay never overwrites")
    shutil.copytree(stores[0], out / "store" / stores[0].name)
    experiment = trial.Experiment.open(out / "store" / stores[0].name)
    if experiment.id != source.get("experiment_id"):
        raise LiveRefused(f"the store is experiment {experiment.id}, not the report's {source.get('experiment_id')}")

    schedule: list[mp.ScheduledAttempt] = []
    for planned, attempt in experiment.attempts():
        match = _LIVE_TRIAL_ID_RE.match(str(planned["trial_id"]))
        if match is None:
            raise LiveRefused(f"ledger trial {planned['trial_id']!r} is not a level3-fixture-live trial")
        schedule.append(mp.ScheduledAttempt(str(attempt["attempt_id"]), str(planned["trial_id"]), match["arm"],
                                            int(match["k"])))
    reported = [(a.get("attempt_id"), a.get("trial_id"), a.get("case"), a.get("repeat"))
                for a in source.get("attempts") or [] if isinstance(a, dict)]
    if not schedule or reported != [(s.attempt_id, s.trial_id, s.arm, s.repeat) for s in schedule] \
            or [s.arm for s in schedule] != list(declaration.order):
        raise LiveRefused("the store's attempts, the original report's attempts and the declared order do not "
                          "match one non-empty population")

    grader = verify.GraderDef.load(root / TASK_PATH)
    extras = _retained_fixture_extras(experiment, [s.attempt_id for s in schedule])
    text = prompt(declaration, root)
    spec = at.CLIENT_SPECS[CLIENT]
    outcomes: list[mp.AttemptOutcome] = []
    re_decided: list[str] = []
    for scheduled in schedule:
        attempt_id = scheduled.attempt_id
        disposition, reason, wall = _lifecycle(experiment, attempt_id)
        was_graded, original_reason = _original_block_reason(experiment, attempt_id)
        record: dict[str, object] = {"disposition": disposition, "reason": reason, "graded": None}
        fixture = extras[attempt_id]
        guard_record = fixture.get("codex_guard") if isinstance(fixture, dict) else None
        if isinstance(guard_record, dict):
            record["fixture"] = {"codex_guard": guard_record.get("nested")}  # the live record's shape
        transcript = _manifest_stream(experiment, attempt_id, "client-transcript")
        if transcript is not None:
            observation, census, run_metadata = at.observe_transcript_bytes(
                spec, transcript, expected_prompt=text, skill_name=None)
            delivered, delivery_reason = _original_prompt_delivery(experiment, attempt_id)
            observation = replace(observation, prompt_delivered=delivered, prompt_delivery_reason=delivery_reason)
            proxy = _manifest_stream(experiment, attempt_id, eg.PROXY_LOG_STREAM)
            egress = ({"status": "read", "digest": trial.sha256_bytes(proxy), **eg.summarize_log(proxy)}
                      if proxy is not None else {"status": "unread", "reason": "no egress proxy log retained"})
            record["observation"] = {"status": "observed", **observation.to_fields(), **census,
                                     "run_metadata": run_metadata, "egress": egress}
        adapter_dependent = isinstance(original_reason, str) and original_reason.startswith(_ADAPTER_DEPENDENT_REASONS)
        if was_graded or not adapter_dependent:
            # Carried over: the replay re-decides only what the adapter decided.
            record["grading_blocked_reason"] = (original_reason if not was_graded else
                                                "carried over: graded by the live run; not replayed")
            outcomes.append(mp.AttemptOutcome(scheduled, record, wall))
            continue

        def fixture_block(fixture: dict[str, object] | str = fixture) -> str | None:
            if isinstance(fixture, str):
                return f"not credited: {fixture}"
            if not assume_fixture_finalized:
                return ("not credited: the fixture session's finalization failure state was not retained, so a "
                        "latched failure cannot be ruled out")
            service = fixture.get("service")
            if not isinstance(service, dict):
                return "not credited: the fixture service record was never finalized"
            if service.get("coverage") == "channel-unavailable":
                return "not credited: the fixture service's channel was unavailable"
            guard = fixture.get("codex_guard")
            return cg.credit_block(guard if isinstance(guard, Mapping) else None)

        # The live gate's witness and disposition checks precede the canary, so
        # an adapter-dependent original reason means both had passed.
        blocked = at.credit_block(record.get("observation"), client=CLIENT, disposition=disposition,
                                  fixture_block=fixture_block)
        record["grading_blocked_reason"] = blocked
        re_decided.append(attempt_id)
        if blocked is None:
            assert isinstance(fixture, dict)
            record["graded"] = _run_judge(grader, fixture)
        outcomes.append(mp.AttemptOutcome(scheduled, record, wall))

    stopped = source.get("containment_stop") or {}
    report = build_report(declaration, experiment, outcomes,
                          Stop(trigger=stopped.get("trigger"), at_attempt=stopped.get("at_attempt")),
                          rehearse=None, approved=bool(source.get("approved")))
    report_after, store_after = _sha256_file(original), _tree_digest(stores[0])
    if (report_after, store_after) != (report_before, store_before):
        raise LiveRefused("the original report or store changed during the judge replay")
    for entry in report["attempts"]:
        # Never called a grade: the per-attempt fields name what this is.
        entry["replay_status"] = entry.pop("graded_status")
        entry["replay_blocked_reason"] = entry.pop("grading_blocked_reason")
        entry["re_decided"] = entry["attempt_id"] in re_decided
        entry["original_containment_trigger_carried"] = stopped.get("at_attempt") == entry["attempt_id"]
    ledger_grader = next((planned.get("grader") for planned, _a in experiment.attempts()), None)
    replay = {
        "judge_replay": {
            # The assumption leads the label, so no reader of a flagged replay misses it (#486 ruling).
            "what": ("ASSUMES fixture finalization was clean (--assume-fixture-finalized); "
                     if assume_fixture_finalized else "")
                    + "judge replay: NOT a verified result and NOT a grade - the current judge re-run over retained "
                    "evidence, deciding again only what the transcript adapter decided",
            "decided": "AFTER seeing the results (#486); not a result until the owner says it counts",
            "source_run": str(run_dir), "source_report_sha256": report_before,
            "source_report_sha256_after": report_after, "source_store_digest": store_before,
            "adapter_revision": adapter_revision,
            "grader_historical": ledger_grader, "grader_current": grader.identity(),
            "witness": "witness not retained: honest-report UNKNOWN",
            "fixture_evidence": "raw controller-held extras by provenance (not a grading envelope, not a candidate "
                                "artifact, unique per attempt); the session's latched failure is not retained, so "
                                "the service and guard records stand for it",
            "probe": "not run: this task's judge reads only the trusted observation",
            "prompt_delivery": "carried from the live run's own verdict: the exact prompt held a per-attempt canary "
                               "nonce no retained record holds, and #486 changed no message parsing",
            "fixture_finalization": ("ASSUMED clean: complete fixture evidence taken as standing for a clean "
                                     "finalization, which no retained record establishes (assume_fixture_finalized)"
                                     if assume_fixture_finalized else
                                     "not assumed: an attempt is judged only if its finalization is established; "
                                     "no retained record establishes it, so none is"),
            "re_decided_attempts": len(re_decided),
            "spend": "none - no agent container, no client, no model",
        },
        **report,
        "kind": JUDGE_REPLAY_KIND,
    }
    path = out / JUDGE_REPLAY_FILENAME
    path.write_text(json.dumps(replay, indent=1) + "\n", encoding="utf-8")
    return path, replay
