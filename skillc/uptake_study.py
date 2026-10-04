"""The two-arm skill-uptake study (issue #237, pilot of #238).

Does a rewritten skill DESCRIPTION raise the agent's natural selection of
that skill? Two arms install the same subject and differ in exactly one
thing: the target skill's `SKILL.md`, whose description the `rewritten` arm
replaces (a `degrade-subject --override-file` snapshot). Everything else -
client, model, effort, image, task, prompt - is declared once and shared.

THE DECLARATION (`kind: uptake-study`) is validated before any attempt
exists, and `require_approved` refuses one whose approval or identities are
not recorded (ADR 0005):

  - exactly two arms, `published` and `rewritten`, installing the SAME
    subject; `rewritten` names the target skill and the replacement
    description, verbatim;
  - one or more cases, each a prompt addendum on the same Level 1 task, each
    with its own attempts per arm (3-30); exactly one case is `primary`;
  - an arm order derived from a recorded seed over every (case, arm) attempt;
  - the primary test, declared in advance: a one-sided Fisher's exact test
    that the `rewritten` arm selects the target more often on the primary
    case, at a declared alpha.

SELECTION IS COUNTED ONLY FROM CONFIRMED OBSERVATIONS - one transcript,
carrying the attempt's own prompt (`calibration_run.observation_confirmed`,
PR #233). An unconfirmed attempt is reported, never counted as "not
selected". The task outcome is reported beside selection, never merged with
it: invoking a skill is not success, and success is not invocation.

THE REWRITTEN SNAPSHOT IS CHECKED, NOT TRUSTED: `check_rewritten_files`
refuses unless the two installs differ in exactly one file - the target's
`SKILL.md` - and in exactly one line of it, the frontmatter `description`,
which must equal the declared text. Any other difference would be a second
change between the arms.

Stdlib only (AGENTS.md), plus this repository's own modules.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import calibration, trial, verify
from . import calibration_run as cr
from . import collection_conformance as cc
from . import matched_pilot as mp

KIND = "uptake-study"
ARMS = ("published", "rewritten")
MIN_ATTEMPTS, MAX_ATTEMPTS = 3, 30
TRIAL_PREFIX = "uptake"
EXPERIMENT_LABEL = "uptake"
REPORT_KIND = "uptake-study-report"
REPORT_FILENAME = "uptake-report.json"
UNKNOWN = calibration.UNKNOWN
DEFAULT_PRIVATE_ROOT = Path.home() / ".local" / "share" / "skillc" / "uptake-runs"

#: What both arms share, declared once (calibration's own set).
SHARED_KEYS = calibration.SHARED_KEYS
_CASE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TRIAL_ID_RE = re.compile(rf"^t\d+-{TRIAL_PREFIX}_(?P<case>[a-z0-9-]+)__(?P<arm>published|rewritten)_(?P<k>\d+)$")
_DESCRIPTION_LINE = re.compile(r'^description:\s*(?P<value>.*)$')


class StudyRefused(ValueError):
    """The declaration or the rewritten snapshot cannot be run as written."""


def _refuse(message: str) -> StudyRefused:
    return StudyRefused(f"uptake-study declaration: {message}")


@dataclass(frozen=True)
class Case:
    id: str
    prompt_addendum: str
    attempts_per_arm: int
    primary: bool


@dataclass(frozen=True)
class StudyDeclaration:
    target_skill: str
    rewritten_description: str
    subject: Mapping[str, object]
    cases: tuple[Case, ...]
    arm_order: tuple[tuple[str, str], ...]
    seed: int
    alpha: float
    shared: Mapping[str, object]
    task_path: str
    grader_id: str
    grader_revision: str
    approval: Mapping[str, object] | None
    data: Mapping[str, object]

    @property
    def primary(self) -> Case:
        return next(c for c in self.cases if c.primary)


def derive_order(seed: int, cases: Sequence[Case]) -> list[tuple[str, str]]:
    """Every (case, arm) attempt, shuffled by `random.Random(seed)`."""
    order = [(c.id, arm) for c in cases for arm in ARMS for _ in range(c.attempts_per_arm)]
    random.Random(seed).shuffle(order)
    return order


def parse_declaration(data: Mapping[str, object]) -> StudyDeclaration:
    if data.get("kind") != KIND:
        raise _refuse(f"kind is {data.get('kind')!r}, not {KIND!r}")
    arms = data.get("arms")
    if not isinstance(arms, list) or [a.get("name") if isinstance(a, dict) else None for a in arms] != list(ARMS):
        raise _refuse(f"arms must be exactly {list(ARMS)}, in that order")
    published, rewritten = arms
    if set(published) - {"name", "subject"} or set(rewritten) - {"name", "subject", "target_skill", "description"}:
        raise _refuse("an arm may carry only name and subject; 'rewritten' adds target_skill and description - "
                      "everything else is declared once under 'shared'")
    subject = published.get("subject")
    if not isinstance(subject, dict) or not subject:
        raise _refuse("the published arm names no subject")
    if rewritten.get("subject") != subject:
        raise _refuse("the two arms install different subjects; they may differ only in the target's description")
    target, description = rewritten.get("target_skill"), rewritten.get("description")
    if not isinstance(target, str) or not target.strip():
        raise _refuse("the rewritten arm names no target_skill")
    if not isinstance(description, str) or not description.strip() or not description.isprintable():
        # isprintable() also refuses \r, \u2028 and every other line or
        # control separator (counter-model review: a \r could smuggle a
        # second frontmatter field past a guard that splits on \n).
        raise _refuse("the rewritten arm's description must be one non-empty line of printable text")

    shared = data.get("shared")
    if not isinstance(shared, dict) or SHARED_KEYS - set(shared):
        missing = sorted(SHARED_KEYS - set(shared)) if isinstance(shared, dict) else sorted(SHARED_KEYS)
        raise _refuse(f"'shared' is missing {missing}")
    per_attempt = calibration._positive_number(shared["per_attempt_seconds"], "shared.per_attempt_seconds")
    total = calibration._positive_number(shared["total_seconds"], "shared.total_seconds")

    cases_raw = data.get("cases")
    if not isinstance(cases_raw, list) or not cases_raw:
        raise _refuse("no cases declared")
    cases = []
    for raw in cases_raw:
        if not isinstance(raw, dict):
            raise _refuse("every case is an object")
        cid, addendum, n, primary = raw.get("id"), raw.get("prompt_addendum"), raw.get("attempts_per_arm"), raw.get("primary")
        if not isinstance(cid, str) or not _CASE_ID.fullmatch(cid):
            raise _refuse(f"case id {cid!r} must be lower-case letters, digits and hyphens")
        if not isinstance(addendum, str):
            raise _refuse(f"case {cid!r}: prompt_addendum must be text (empty for the bare task)")
        if isinstance(n, bool) or not isinstance(n, int) or not MIN_ATTEMPTS <= n <= MAX_ATTEMPTS:
            raise _refuse(f"case {cid!r}: attempts_per_arm must be {MIN_ATTEMPTS}-{MAX_ATTEMPTS}, not {n!r}")
        if not isinstance(primary, bool):
            raise _refuse(f"case {cid!r}: primary must be true or false")
        cases.append(Case(cid, addendum, n, primary))
    if len({c.id for c in cases}) != len(cases):
        raise _refuse("case ids must be distinct")
    if sum(c.primary for c in cases) != 1:
        raise _refuse("exactly one case is primary: the test is declared on one case, in advance")
    attempts = sum(2 * c.attempts_per_arm for c in cases)
    if total < per_attempt * attempts:
        raise _refuse(f"shared.total_seconds {total:g} cannot cover {attempts} attempts of {per_attempt:g}s")

    test = data.get("test")
    if not isinstance(test, dict) or test.get("kind") != "fisher-exact-one-sided" \
            or test.get("direction") != "rewritten > published":
        raise _refuse("test must be {kind: fisher-exact-one-sided, direction: 'rewritten > published', alpha}")
    alpha = test.get("alpha")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not 0 < alpha < 1:
        raise _refuse(f"test.alpha must be between 0 and 1, not {alpha!r}")

    order = data.get("arm_order")
    if not isinstance(order, dict) or isinstance(order.get("seed"), bool) or not isinstance(order.get("seed"), int):
        raise _refuse("arm_order.seed must be an integer recorded before any attempt")
    sequence = order.get("sequence")
    expected = derive_order(order["seed"], cases)
    if not isinstance(sequence, list) or [tuple(s) if isinstance(s, list) else s for s in sequence] != expected:
        raise _refuse(f"arm_order.sequence is not what seed {order['seed']} derives; an order chosen by hand "
                      "is not a randomized one")

    task = data.get("task")
    if not isinstance(task, dict) or not all(isinstance(task.get(k), str) and task.get(k)
                                             for k in ("path", "grader_id", "grader_revision")):
        raise _refuse("task must name path, grader_id and grader_revision")
    approval = data.get("approval")
    if approval is not None and not isinstance(approval, dict):
        raise _refuse("approval is null (not yet approved) or an object recording who approved and when")
    return StudyDeclaration(
        target_skill=target, rewritten_description=description, subject=dict(subject), cases=tuple(cases),
        arm_order=tuple(expected), seed=int(order["seed"]), alpha=float(alpha), shared=dict(shared),
        task_path=str(task["path"]), grader_id=str(task["grader_id"]), grader_revision=str(task["grader_revision"]),
        approval=approval, data=dict(data),
    )


def load_declaration(path: Path) -> StudyDeclaration:
    return parse_declaration(json.loads(path.read_text(encoding="utf-8")))


REQUIRED_IDENTITIES: tuple[tuple[str, ...], ...] = (
    ("client", "name"), ("client", "version"), ("model",), ("reasoning_effort",),
    ("image", "tag"), ("image", "digest"), ("tools",), ("permissions",), ("public_requirements",),
)


def require_approved(declaration: StudyDeclaration, root: Path) -> None:
    """Refuse unless the approval (who, when) and every identity are recorded
    and the declared task's grader is the one on disk (ADR 0005)."""
    approval = declaration.approval
    if not approval or not all(isinstance(approval.get(k), str) and approval.get(k) for k in ("by", "at")):
        raise _refuse("not approved: 'approval' must record who approved it ('by') and when ('at') "
                      "before any attempt runs (ADR 0005)")
    absent = []
    for path in REQUIRED_IDENTITIES:
        node: object = declaration.shared
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if not (isinstance(node, str) and node.strip() and node != UNKNOWN):
            absent.append("shared." + ".".join(path))
    for key in ("name", "locator", "revision"):
        value = declaration.subject.get(key)
        if not (isinstance(value, str) and value.strip() and value != UNKNOWN):
            absent.append(f"subject.{key}")
    if absent:
        raise _refuse(f"identities not recorded: {absent}; record them before approving a run")
    grader = verify.GraderDef.load(root / declaration.task_path)
    if (grader.id, grader.revision) != (declaration.grader_id, declaration.grader_revision):
        raise _refuse(f"the task's grader is {grader.id!r} revision {grader.revision!r}, not the declared "
                      f"{declaration.grader_id!r} revision {declaration.grader_revision!r}")


def _description_of(skill_md: bytes) -> tuple[list[str], int]:
    """(lines, index of the frontmatter description line) of a SKILL.md."""
    text = skill_md.decode("utf-8")
    if "\r" in text:
        raise StudyRefused("the target SKILL.md carries a carriage return; refusing to compare it line by line")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise StudyRefused("the target SKILL.md has no frontmatter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise StudyRefused("the target SKILL.md's frontmatter is not closed")
    hits = [i for i in range(1, end) if _DESCRIPTION_LINE.match(lines[i])]
    if len(hits) != 1:
        raise StudyRefused(f"the target SKILL.md's frontmatter has {len(hits)} description line(s), not one")
    return lines, hits[0]


def _unquote(value: str) -> str:
    """A description value, which must be ONE double-quoted JSON string and
    nothing else (counter-model review): an unquoted value such as
    `Use checks # extra` means `Use checks` to a YAML reader, so it is
    refused rather than guessed at."""
    value = value.strip()
    try:
        decoded = json.loads(value) if value.startswith('"') else None
    except json.JSONDecodeError:
        decoded = None
    if not isinstance(decoded, str):
        raise StudyRefused(f"a description must be one double-quoted string, not {value!r}")
    return decoded


def check_rewritten_files(published: Mapping[str, bytes], rewritten: Mapping[str, bytes],
                          target_skill: str, description: str) -> str:
    """The one path that differs between the two installs - the target's
    SKILL.md - after proving it differs in exactly the description line, and
    that line now carries `description` verbatim. Refuses anything else."""
    differing = sorted(p for p in set(published) | set(rewritten) if published.get(p) != rewritten.get(p))
    if len(differing) != 1:
        raise StudyRefused(f"the installs differ in {len(differing)} file(s), not exactly the target's SKILL.md: "
                           f"{differing[:5]}")
    path = differing[0]
    parts = path.split("/")
    # The skill's ENTRY POINT, `.../skills/<target>/SKILL.md` - never a
    # nested file of that name inside another skill (counter-model review).
    if len(parts) < 3 or parts[-3:] != ["skills", target_skill, "SKILL.md"] \
            or path not in published or path not in rewritten:
        raise StudyRefused(f"the differing file {path!r} is not {target_skill}'s SKILL.md entry point")
    old_lines, old_at = _description_of(published[path])
    new_lines, new_at = _description_of(rewritten[path])
    if old_at != new_at or old_lines[:old_at] + old_lines[old_at + 1:] != new_lines[:new_at] + new_lines[new_at + 1:]:
        raise StudyRefused(f"{path} differs in more than its description line")
    got = _unquote(_DESCRIPTION_LINE.match(new_lines[new_at]).group("value"))  # type: ignore[union-attr]
    if got != description:
        raise StudyRefused(f"{path}'s new description is not the declared one: {got!r}")
    old = _unquote(_DESCRIPTION_LINE.match(old_lines[old_at]).group("value"))  # type: ignore[union-attr]
    if old == got:
        raise StudyRefused(f"{path}'s description is unchanged in meaning (only whitespace or quoting differs); "
                           "the arms would not differ")
    return path


def fisher_one_sided(selected_r: int, n_r: int, selected_p: int, n_p: int) -> float:
    """P(X >= selected_r) for the rewritten arm's selections under the
    hypergeometric null with both margins fixed: the exact one-sided Fisher
    test that the rewritten arm selects more often."""
    total = selected_r + selected_p
    population = n_r + n_p
    if population == 0:
        return 1.0
    denominator = math.comb(population, total)
    return sum(math.comb(n_r, k) * math.comb(n_p, total - k)
               for k in range(selected_r, min(total, n_r) + 1)) / denominator


def _arm_label(case: str, arm: str) -> str:
    return f"{case}__{arm}"


def plan_study(declaration: StudyDeclaration, store: Path, *, root: Path, digests: Mapping[str, str],
               image_digest: str | None) -> tuple[trial.Experiment, list[mp.ScheduledAttempt]]:
    client_name, client_version = (str(declaration.shared["client"]["name"]),  # type: ignore[index]
                                   str(declaration.shared["client"]["version"]))  # type: ignore[index]
    grader = verify.GraderDef.load(root / declaration.task_path)
    trials = []
    counts: dict[tuple[str, str], int] = {}
    for position, (case, arm) in enumerate(declaration.arm_order, start=1):
        counts[(case, arm)] = counts.get((case, arm), 0) + 1
        trials.append({
            "label": f"{TRIAL_PREFIX}_{_arm_label(case, arm)}_{counts[(case, arm)]}",
            "case": {"id": f"{declaration.grader_id}:{case}", "revision": declaration.grader_revision},
            "grader": grader.identity(),
            "subject": {"digest": digests[arm]},
            "client": {"name": client_name, "version": client_version},
            "image": {"digest": image_digest or UNKNOWN},
            "config": {"arm": _arm_label(case, arm), "repeat": counts[(case, arm)], "position": position},
            "attempts": 1,
        })
    try:
        experiment = trial.plan({"experiment": EXPERIMENT_LABEL, "trials": trials}, store)
    except trial.Refused as exc:
        raise StudyRefused(f"the controller refused the schedule: {exc}") from exc
    schedule = [mp.ScheduledAttempt(str(a["attempt_id"]), str(t["trial_id"]), spec["config"]["arm"],  # type: ignore[index]
                                    int(spec["config"]["repeat"]))  # type: ignore[index]
                for (t, a), spec in zip(experiment.attempts(), trials, strict=True)]
    return experiment, schedule


def schedule_from_ledger(experiment: trial.Experiment) -> list[mp.ScheduledAttempt]:
    schedule = []
    for planned, attempt in experiment.attempts():
        trial_id = str(planned["trial_id"])
        match = _TRIAL_ID_RE.match(trial_id)
        if match is None:
            raise StudyRefused(f"ledger trial {trial_id!r} is not an uptake-study trial")
        schedule.append(mp.ScheduledAttempt(str(attempt["attempt_id"]), trial_id,
                                            _arm_label(match["case"], match["arm"]), int(match["k"])))
    return schedule


def reconcile(experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome]) -> list[mp.AttemptOutcome]:
    return mp.reconcile(experiment, outcomes, schedule_from_ledger(experiment))


def run_study(
    declaration: StudyDeclaration, *, run_dir: Path, treatments: Mapping[str, cr.Treatment],
    image_digest: str | None, backends: Callable[[], tuple[object, object]],
    argv_for: Callable[[mp.ScheduledAttempt], Sequence[str]], root: Path,
    credential_explicit_path: Path | None = None, clock: Callable[[], float] = time.monotonic,
    total_seconds: float | None = None,
) -> tuple[trial.Experiment, list[mp.AttemptOutcome]]:
    """Authorize, plan and run the whole declared schedule. Nothing - no
    store, no plan, no container - exists before `require_approved`."""
    require_approved(declaration, root)
    if set(treatments) != set(ARMS):
        raise StudyRefused(f"treatments must be given for exactly {list(ARMS)}")
    model, effort = str(declaration.shared["model"]), str(declaration.shared["reasoning_effort"])
    mp.pin_model_argv(model, effort, [])
    task_root = root / declaration.task_path
    surface = cc._fixture_surface(task_root / "fixture")
    goal = (task_root / "goal.md").read_text(encoding="utf-8")
    addenda = {c.id: c.prompt_addendum for c in declaration.cases}
    per_attempt = float(str(declaration.shared["per_attempt_seconds"]))
    total = float(str(declaration.shared["total_seconds"])) if total_seconds is None else total_seconds
    client = declaration.shared["client"]
    assert isinstance(client, dict)

    store = trial.open_store(run_dir / "store", forbidden=[])
    experiment, schedule = plan_study(declaration, store, root=root, image_digest=image_digest,
                                      digests={arm: treatments[arm].digest for arm in ARMS})
    outcomes: list[mp.AttemptOutcome] = []

    def save() -> None:
        path = run_dir / mp.OUTCOMES_FILENAME
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"experiment_root": str(experiment.root),
                                   "outcomes": [o.to_json() for o in outcomes]}, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)

    save()

    def run_attempt(scheduled: mp.ScheduledAttempt, budget: float) -> dict[str, object]:
        case, arm = scheduled.arm.split("__")
        addendum = addenda[case]
        prompt = f"{goal.rstrip()}\n\n{addendum}\n" if addendum else goal
        agent_backend, grading_backend = backends()
        return cc.run_level1_agent_attempt(
            experiment=experiment, attempt_id=scheduled.attempt_id,
            backend=agent_backend, grading_backend=grading_backend,  # type: ignore[arg-type]
            base=run_dir, base_argv=mp.pin_model_argv(model, effort, argv_for(scheduled)),
            extra_home_files=treatments[arm].home_files, client=str(client["name"]),
            cli_version=str(client["version"]), task_root=task_root, surface=surface, prompt=prompt,
            timeout=budget, credential_explicit_path=credential_explicit_path,
            receipt_context=treatments[arm].receipt_context,
        )

    def on_outcome(outcome: mp.AttemptOutcome) -> None:
        outcomes.append(outcome)
        save()

    try:
        mp.run_schedule(experiment, schedule, run_attempt, total_seconds=total, per_attempt_seconds=per_attempt,
                        clock=clock, on_outcome=on_outcome)
    except KeyboardInterrupt:
        outcomes[:] = reconcile(experiment, outcomes)
        save()
        raise
    return experiment, outcomes


def model_observed(obs: Mapping[str, object]) -> str:
    meta = obs.get("run_metadata")
    return str(meta.get("model") or UNKNOWN) if isinstance(meta, dict) else UNKNOWN


def build_report(experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome],
                 declaration: StudyDeclaration) -> dict[str, object]:
    """Per attempt: whether the TARGET skill was selected (from a confirmed
    observation only) and the task outcome beside it. Per (case, arm):
    selected/observed counts. The primary test on the primary case, as
    declared. Description, then the one predeclared inference."""
    entries = []
    for position, outcome in enumerate(outcomes, start=1):
        case, arm = outcome.scheduled.arm.split("__")
        record = outcome.record
        obs = record.get("observation")
        obs = obs if isinstance(obs, dict) else {}
        confirmed = cr.observation_confirmed(obs)
        invocations = obs.get("skill_invocations")
        graded = record.get("graded")
        entries.append({
            "position": position, "attempt_id": outcome.scheduled.attempt_id, "case": case, "arm": arm,
            "disposition": record.get("disposition"),
            "target_selected": cr._opened(invocations, (declaration.target_skill,), confirmed=confirmed),
            "any_skill_selected": cr._opened(invocations, confirmed=confirmed),
            "skill_invocations": invocations if isinstance(invocations, list) else UNKNOWN,
            "task_status": graded.get("status") if isinstance(graded, dict) else calibration.NOT_GRADED,
            "model_observed": model_observed(obs),
            "model_eligible": mp.model_eligibility(record.get("disposition"), model_observed(obs),
                                                   str(declaration.shared["model"])),
            "transcript_retention": record.get("transcript_retention", UNKNOWN),
        })
    cells: dict[str, dict[str, dict[str, int]]] = {}
    for entry in entries:
        cell = cells.setdefault(str(entry["case"]), {}).setdefault(str(entry["arm"]),
                                                                    {"scheduled": 0, "observed": 0, "selected": 0})
        cell["scheduled"] += 1
        # Counted only when confirmed AND observed running the declared model
        # (counter-model review): a wrong-model attempt is reported, never a
        # margin of the comparison.
        if entry["target_selected"] in (True, False) and entry["model_eligible"] is True:
            cell["observed"] += 1
            cell["selected"] += entry["target_selected"] is True
    primary = declaration.primary.id
    r = cells.get(primary, {}).get("rewritten", {"observed": 0, "selected": 0})
    p = cells.get(primary, {}).get("published", {"observed": 0, "selected": 0})
    available = r["observed"] > 0 and p["observed"] > 0
    p_value = fisher_one_sided(r["selected"], r["observed"], p["selected"], p["observed"]) if available else None
    return {
        "version": 1, "kind": REPORT_KIND, "experiment_id": experiment.id,
        "target_skill": declaration.target_skill, "attempts": entries, "cells": cells,
        "primary_test": {
            "case": primary, "kind": "fisher-exact-one-sided", "direction": "rewritten > published",
            "alpha": declaration.alpha,
            "rewritten": f"{r['selected']}/{r['observed']}", "published": f"{p['selected']}/{p['observed']}",
            "available": available,
            "reason": None if available else "no confirmed, declared-model observation in one or both primary arms",
            "p_value": p_value, "significant": (p_value <= declaration.alpha) if p_value is not None else None,
        },
    }


def paste_back(report: Mapping[str, object]) -> str:
    lines = [f"uptake-study: experiment {report.get('experiment_id')} target={report.get('target_skill')}"]
    cells = report.get("cells")
    for case, arms in (cells.items() if isinstance(cells, dict) else []):
        for arm, cell in arms.items():
            lines.append(f"  [{case} / {arm}] selected={cell['selected']}/{cell['observed']} "
                         f"(scheduled {cell['scheduled']})")
    test = report.get("primary_test")
    if isinstance(test, dict) and test.get("available"):
        lines.append(f"  primary ({test['case']}): rewritten {test['rewritten']} vs published {test['published']}, "
                     f"one-sided Fisher p={test['p_value']:.4f}, alpha={test['alpha']}, "
                     f"significant={test['significant']}")
    elif isinstance(test, dict):
        lines.append(f"  primary ({test['case']}): NO RESULT - {test['reason']}")
    return "\n".join(lines)

