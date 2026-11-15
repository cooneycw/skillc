"""Skill-gauntlet rounds 3 and 4 (#736, PR 1): baseline and challenge trials.

Rounds 1 and 2 judge what a skill SAYS; these judge what it DOES.

- **Round 3, baseline.** Every charter clause names trap tasks. Each arm runs
  each clause's TRAIN tasks `replicates` times: the intact skill, plus at least
  one damaged copy with a NAMED passage removed. The round is UNKNOWN unless
  every damaged copy scores measurably worse on the clause its passage serves
  (`reliability.evaluate_discrimination`). If the tasks cannot tell a damaged
  skill from an intact one, they prove nothing about the intact one.
- **Round 4, challenge.** Leaner variants, each the intact skill minus named
  passages, run on the HELD-OUT tasks against the intact baseline. A variant
  passes only if, for EVERY clause, its pass count is no lower than the
  baseline's (minus a declared tolerance, which defaults to 0 and is printed).
  If no variant passes, the verdict is `keep`. A noisy rule favours keep, the
  safe direction: a skill is never trimmed on weak evidence.

**The budget is a declared attempt count** (owner, #718 decision 4). A run
refuses before any attempt when the declaration has no `attempt_cap`, or when
the new attempts it needs exceed the cap. With `partial: true` it runs up to
the cap instead, then stops, and the round reads INCOMPLETE, never a pass.

**A re-run never pays twice.** Every attempt is filed in a ledger, keyed by
the arm's skill digest, the task's content digest, the GRADER's digest, the
client and its version, the model, the arm and the replicate. A changed
grader or client is a different key, so nothing is reused for it.

**This module makes no model call.** Attempts go through an `AttemptRunner`.
PR 1 ships only `ScriptedRunner` (the offline controls). The real runner, over
`calibration_run`'s Docker path, is #736 PR 3 and needs its own gate.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .reliability import DISCRIMINATION_VERDICTS, TwoArmRule, evaluate_discrimination
from .source_digest import digest_tree

SCHEMA = 1
PASS, FAIL, ERROR = "pass", "fail", "error"
OUTCOMES = (PASS, FAIL, ERROR)
INTACT = "intact"

#: Round verdicts. UNKNOWN: the tasks or the evidence cannot decide.
#: INCOMPLETE: the attempt cap stopped the round.
COMPLETE, UNKNOWN, INCOMPLETE, REFUSED, PLANNED = "COMPLETE", "UNKNOWN", "INCOMPLETE", "REFUSED", "PLANNED"
KEEP, TRIM = "keep", "trim"

#: A split needs at least this many tasks per clause, whatever is declared.
FLOOR_TASKS_PER_CLAUSE = 2


class DeclarationError(ValueError):
    """The declaration cannot be run as written; nothing is attempted."""


@dataclass(frozen=True)
class Client:
    name: str
    version: str
    model: str


@dataclass(frozen=True)
class Passage:
    """A named passage removed from the intact skill to make an arm."""

    arm: str
    file: str
    remove: str
    clause: str  # the clause this passage serves (damaged arms) or a source note (variants)


@dataclass(frozen=True)
class Declaration:
    path: Path
    skill: Path
    skill_digest: str
    client: Client
    attempt_cap: int | None
    partial: bool
    replicates: int
    seed: str
    min_tasks_per_clause: int
    min_heldout: int
    tolerance: int
    rule: TwoArmRule
    clauses: dict[str, tuple[Path, ...]]
    damaged: tuple[Passage, ...]
    variants: tuple[Passage, ...]


def _need(data: Mapping[str, object], key: str, kind: type, where: str) -> object:
    value = data.get(key)
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise DeclarationError(f"{where}: '{key}' must be a {kind.__name__}")
    return value


def _passages(raw: object, where: str, *, clause_ids: set[str] | None) -> tuple[Passage, ...]:
    if not isinstance(raw, list):
        raise DeclarationError(f"{where} must be a list")
    found: list[Passage] = []
    for n, item in enumerate(raw):
        if not isinstance(item, dict):
            raise DeclarationError(f"{where}[{n}] is not a mapping")
        arm = str(_need(item, "arm", str, f"{where}[{n}]"))
        file = str(_need(item, "file", str, f"{where}[{n}]"))
        remove = str(_need(item, "remove", str, f"{where}[{n}]"))
        clause = str(_need(item, "clause", str, f"{where}[{n}]"))
        if not remove.strip():
            raise DeclarationError(f"{where}[{n}]: 'remove' names no passage")
        if arm == INTACT:
            raise DeclarationError(f"{where}[{n}]: arm '{INTACT}' is reserved for the intact skill")
        if clause_ids is not None and clause not in clause_ids:
            raise DeclarationError(f"{where}[{n}]: clause {clause!r} is not declared")
        found.append(Passage(arm, file, remove, clause))
    if len({p.arm for p in found}) != len(found):
        raise DeclarationError(f"{where}: arm names repeat")
    return tuple(found)


def load(path: Path) -> Declaration:
    """Read and validate a round declaration (JSON). Paths resolve from the
    declaration's directory."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeclarationError(f"declaration not read: {exc}") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise DeclarationError(f"declaration schema must be {SCHEMA}")
    base = path.parent
    skill = (base / str(_need(data, "skill", str, "declaration"))).resolve()
    if not (skill / "SKILL.md").is_file():
        raise DeclarationError(f"no SKILL.md under the declared skill {skill}")
    declared_digest = str(_need(data, "skill_digest", str, "declaration"))
    actual = digest_tree(skill)
    if declared_digest != actual:
        raise DeclarationError(f"skill digest {declared_digest!r} is not the skill's ({actual}); the skill changed")
    raw_client = _need(data, "client", dict, "declaration")
    assert isinstance(raw_client, dict)
    client = Client(*(str(_need(raw_client, k, str, "client")) for k in ("name", "version", "model")))
    cap = data.get("attempt_cap")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
        raise DeclarationError("attempt_cap must be a positive integer")
    replicates = int(_need(data, "replicates", int, "declaration"))  # type: ignore[call-overload]
    if replicates < 1:
        raise DeclarationError("replicates must be at least 1")
    minimum = data.get("min_tasks_per_clause", FLOOR_TASKS_PER_CLAUSE)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < FLOOR_TASKS_PER_CLAUSE:
        raise DeclarationError(f"min_tasks_per_clause must be an integer of at least {FLOOR_TASKS_PER_CLAUSE}")
    min_heldout = data.get("min_heldout", 1)
    if isinstance(min_heldout, bool) or not isinstance(min_heldout, int) or min_heldout < 1:
        raise DeclarationError("min_heldout must be a positive integer")
    tolerance = data.get("tolerance", 0)
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 0:
        raise DeclarationError("tolerance must be a non-negative integer (0 unless the owner declares one)")
    raw_rule = _need(data, "discrimination_rule", dict, "declaration")
    assert isinstance(raw_rule, dict)
    try:
        rule = TwoArmRule(str(raw_rule.get("rule_id")), float(raw_rule.get("alpha", 0)), "greater",  # type: ignore[arg-type]
                          raw_rule.get("tolerance"), str(raw_rule.get("citation_url", "")))  # type: ignore[arg-type]
    except (ValueError, TypeError) as exc:
        raise DeclarationError(f"discrimination_rule: {exc}") from None
    raw_clauses = _need(data, "clauses", dict, "declaration")
    assert isinstance(raw_clauses, dict)
    clauses: dict[str, tuple[Path, ...]] = {}
    for clause_id, tasks in raw_clauses.items():
        if not isinstance(tasks, list) or not all(isinstance(t, str) for t in tasks):
            raise DeclarationError(f"clause {clause_id!r}: tasks must be a list of task directories")
        resolved = tuple(sorted({(base / t).resolve() for t in tasks}))
        for task in resolved:
            if not (task / "grader.json").is_file():
                raise DeclarationError(f"clause {clause_id!r}: {task} has no grader.json")
        clauses[str(clause_id)] = resolved
    if not clauses:
        raise DeclarationError("no clause is declared")
    damaged = _passages(data.get("damaged", []), "damaged", clause_ids=set(clauses))
    if not damaged:
        raise DeclarationError("at least one damaged arm is required: it is the separation control")
    variants = _passages(data.get("variants", []), "variants", clause_ids=None)
    if {p.arm for p in damaged} & {p.arm for p in variants}:
        raise DeclarationError("an arm name is both damaged and a variant")
    return Declaration(path, skill, actual, client, cap, bool(data.get("partial", False)), replicates,
                       str(data.get("seed", "0")), minimum, min_heldout, tolerance, rule, clauses, damaged, variants)


# ---------------------------------------------------------------- arms and identities


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def arm_text(declaration: Declaration, passage: Passage | None) -> dict[str, str]:
    """The arm's changed files: {relative path: new text}. The intact arm
    changes nothing. A passage must occur EXACTLY once, or the arm would not
    be the one named."""
    if passage is None:
        return {}
    target = declaration.skill / passage.file
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeclarationError(f"arm {passage.arm!r}: {passage.file} not read: {exc}") from None
    count = text.count(passage.remove)
    if count != 1:
        raise DeclarationError(f"arm {passage.arm!r}: the passage occurs {count} times in {passage.file}; it must occur once")
    return {passage.file: text.replace(passage.remove, "", 1)}


def arm_digest(declaration: Declaration, passage: Passage | None) -> str:
    changes = arm_text(declaration, passage)
    if not changes:
        return declaration.skill_digest
    return _sha(json.dumps({"base": declaration.skill_digest, "changes": changes}, sort_keys=True).encode())


def _digest_files(root: Path, files: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def task_identity(task: Path) -> tuple[str, str]:
    """(task digest, grader digest). The task is what the agent sees:
    goal.md and fixture/. The grader is everything else at the task's top
    level: grader.json and its scripts and inputs. Editing a grader changes
    only the second digest, and a changed digest is a new ledger key."""
    seen = [task / "goal.md", *sorted(p for p in (task / "fixture").rglob("*") if p.is_file())]
    task_files = [p for p in seen if p.is_file()]
    grader_files = [p for p in task.iterdir() if p.is_file() and p.name != "goal.md"]
    return _digest_files(task, task_files), _digest_files(task, grader_files)


# ---------------------------------------------------------------- the split


def split(declaration: Declaration, clause: str) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """(train, held-out) for one clause: a seeded, deterministic shuffle;
    held-out is a third, at least one task; train is the rest."""
    tasks = list(declaration.clauses[clause])
    random.Random(f"{declaration.seed}:{clause}").shuffle(tasks)
    held = max(1, len(tasks) // 3)
    return tuple(sorted(tasks[held:])), tuple(sorted(tasks[:held]))


# ---------------------------------------------------------------- the ledger


@dataclass(frozen=True)
class Attempt:
    arm: str
    task: Path
    replicate: int
    key: str


@dataclass(frozen=True)
class Outcome:
    result: str  # pass | fail | error
    client: str
    version: str
    model: str


class Ledger:
    """One JSON line per attempt, keyed. Append-only; a key seen twice keeps
    its first outcome."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: dict[str, dict[str, object]] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.rows.setdefault(str(row["key"]), row)

    def get(self, key: str) -> dict[str, object] | None:
        return self.rows.get(key)

    def add(self, key: str, row: dict[str, object]) -> None:
        if key in self.rows:
            return
        self.rows[key] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def attempt_key(declaration: Declaration, arm_digest_value: str, task: Path, arm: str, replicate: int) -> str:
    task_digest, grader_digest = task_identity(task)
    c = declaration.client
    return _sha(json.dumps({
        "skill": arm_digest_value, "task": task_digest, "grader": grader_digest,
        "client": c.name, "version": c.version, "model": c.model, "arm": arm, "replicate": replicate,
    }, sort_keys=True).encode())


# ---------------------------------------------------------------- running


class AttemptRunner(Protocol):
    """Runs one attempt of `task` with the arm's skill and grades it."""

    def run(self, declaration: Declaration, arm: str, changes: Mapping[str, str], task: Path, replicate: int) -> Outcome: ...


class ScriptedRunner:
    """Offline controls only: `{(arm, task name): [result, ...]}` answered per
    replicate; an unscripted pair passes. Counts every call."""

    def __init__(self, script: Mapping[tuple[str, str], Sequence[str]], client: Client) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.client = client
        self.calls = 0

    def run(self, declaration: Declaration, arm: str, changes: Mapping[str, str], task: Path, replicate: int) -> Outcome:
        self.calls += 1
        answers = self.script.get((arm, task.name), [PASS])
        return Outcome(answers[replicate % len(answers)], self.client.name, self.client.version, self.client.model)


@dataclass
class RoundReport:
    round: int
    verdict: str
    reason: str
    declared: int
    new: int
    reused: int
    run: int
    cap: int | None
    tolerance: int
    per_clause: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)  # clause -> arm -> counts
    separation: dict[str, dict[str, object]] = field(default_factory=dict)
    variants: dict[str, dict[str, object]] = field(default_factory=dict)
    recommendation: str | None = None
    clients: list[str] = field(default_factory=list)


def _plan(declaration: Declaration, arms: Sequence[tuple[str, Passage | None]], tasks_of: Mapping[str, Sequence[Path]],
          ) -> tuple[list[tuple[Attempt, str, Mapping[str, str]]], dict[str, str]]:
    """Every distinct (arm, task, replicate) the round needs."""
    planned: dict[str, tuple[Attempt, str, Mapping[str, str]]] = {}
    digests: dict[str, str] = {}
    for arm, passage in arms:
        changes = arm_text(declaration, passage)
        digest = arm_digest(declaration, passage)
        digests[arm] = digest
        for tasks in tasks_of.values():
            for task in tasks:
                for r in range(declaration.replicates):
                    key = attempt_key(declaration, digest, task, arm, r)
                    planned.setdefault(key, (Attempt(arm, task, r, key), digest, changes))
    return list(planned.values()), digests


def _execute(declaration: Declaration, planned: list[tuple[Attempt, str, Mapping[str, str]]], ledger: Ledger,
             runner: AttemptRunner | None, report: RoundReport, plan_only: bool = False) -> bool:
    """Run what the ledger lacks, within the cap. False when the cap stopped it."""
    needed = [p for p in planned if ledger.get(p[0].key) is None]
    report.declared, report.reused, report.new = len(planned), len(planned) - len(needed), len(needed)
    cap = declaration.attempt_cap
    if plan_only:
        over = cap is None or (len(needed) > cap and not declaration.partial)
        report.verdict = PLANNED
        report.reason = ("nothing was run; " + ("a real run would be REFUSED by the attempt cap" if needed and over
                                                else "a real run fits the attempt cap"))
        return False
    if needed and cap is None:
        report.verdict, report.reason = REFUSED, "no attempt_cap is declared; nothing runs without one (#718 decision 4)"
        return False
    if needed and cap is not None and len(needed) > cap and not declaration.partial:
        report.verdict, report.reason = REFUSED, (f"{len(needed)} new attempts exceed attempt_cap {cap}; "
                                                  f"refused before any attempt (declare partial: true to stop at the cap)")
        return False
    if needed and runner is None:
        report.verdict, report.reason = REFUSED, "no attempt runner: PR 1 runs offline controls only (real runs are #736 PR 3)"
        return False
    clients: set[str] = set()
    for attempt, digest, changes in needed:
        if cap is not None and report.run >= cap:
            report.verdict, report.reason = INCOMPLETE, f"stopped at attempt_cap {cap}; {len(needed) - report.run} attempt(s) not run"
            return False
        assert runner is not None
        outcome = runner.run(declaration, attempt.arm, changes, attempt.task, attempt.replicate)
        result = outcome.result if outcome.result in OUTCOMES else ERROR
        ledger.add(attempt.key, {"key": attempt.key, "arm": attempt.arm, "task": attempt.task.name,
                                 "replicate": attempt.replicate, "result": result, "skill": digest,
                                 "client": outcome.client, "version": outcome.version, "model": outcome.model})
        report.run += 1
        clients.add(f"{outcome.client} {outcome.version} {outcome.model}")
    report.clients = sorted(clients | {f"{r['client']} {r['version']} {r['model']}" for r in
                                       (ledger.get(p[0].key) for p in planned) if r})
    return True


def _counts(planned: Sequence[tuple[Attempt, str, Mapping[str, str]]], ledger: Ledger, arm: str,
            tasks: Iterable[Path]) -> dict[str, int]:
    wanted = set(tasks)
    rows = [ledger.get(a.key) for a, _d, _c in planned if a.arm == arm and a.task in wanted]
    results = [str(r["result"]) for r in rows if r]
    return {"pass": results.count(PASS), "evaluable": sum(r in (PASS, FAIL) for r in results), "error": results.count(ERROR)}


def _minimum_problem(declaration: Declaration) -> str | None:
    short = [c for c, t in declaration.clauses.items() if len(t) < declaration.min_tasks_per_clause]
    if short:
        return f"clause(s) below min_tasks_per_clause {declaration.min_tasks_per_clause}: {', '.join(sorted(short))}"
    return None


def round3(declaration: Declaration, ledger: Ledger, runner: AttemptRunner | None,
           plan_only: bool = False) -> RoundReport:
    report = RoundReport(3, COMPLETE, "", 0, 0, 0, 0, declaration.attempt_cap, declaration.tolerance)
    problem = _minimum_problem(declaration)
    if problem:
        report.verdict, report.reason = UNKNOWN, problem + "; a split needs at least that many tasks"
        return report
    train = {c: split(declaration, c)[0] for c in declaration.clauses}
    arms: list[tuple[str, Passage | None]] = [(INTACT, None), *((p.arm, p) for p in declaration.damaged)]
    planned, _ = _plan(declaration, arms, train)
    if not _execute(declaration, planned, ledger, runner, report, plan_only):
        return report
    for clause, tasks in train.items():
        report.per_clause[clause] = {arm: _counts(planned, ledger, arm, tasks) for arm, _ in arms}
    for passage in declaration.damaged:
        intact = report.per_clause[passage.clause][INTACT]
        damaged = report.per_clause[passage.clause][passage.arm]
        verdict = evaluate_discrimination(declaration.rule, intact["pass"], intact["evaluable"],
                                          damaged["pass"], damaged["evaluable"], certified=True)
        report.separation[passage.arm] = {"clause": passage.clause, "removes": f"{passage.file}: {passage.remove[:80]}",
                                          "verdict": verdict.verdict, "p": verdict.p_value, "reason": verdict.reason}
    failed = [a for a, s in report.separation.items() if s["verdict"] != DISCRIMINATION_VERDICTS[0]]
    if failed:
        report.verdict = UNKNOWN
        report.reason = (f"the tasks did not separate the damaged arm(s) {', '.join(failed)} from the intact skill; "
                         f"they cannot show what the intact skill does")
    else:
        report.reason = "every damaged arm scored measurably worse on its clause"
    return report


def round4(declaration: Declaration, ledger: Ledger, runner: AttemptRunner | None,
           plan_only: bool = False) -> RoundReport:
    report = RoundReport(4, COMPLETE, "", 0, 0, 0, 0, declaration.attempt_cap, declaration.tolerance)
    if not declaration.variants:
        report.verdict, report.reason = REFUSED, "no variant is declared"
        return report
    baseline = round3(declaration, ledger, None)  # must be fully cached: round 4 never re-pays round 3
    if baseline.verdict == UNKNOWN:
        report.verdict, report.reason = UNKNOWN, f"round 3 is UNKNOWN ({baseline.reason}); round 4 cannot judge against it"
        return report
    if baseline.verdict != COMPLETE:
        report.verdict, report.reason = REFUSED, f"round 3 is not complete ({baseline.reason}); run round 3 first"
        return report
    held = {c: split(declaration, c)[1] for c in declaration.clauses}
    total_held = len({t for ts in held.values() for t in ts})
    if total_held < declaration.min_heldout:
        report.verdict, report.reason = UNKNOWN, (f"{total_held} held-out task(s), below min_heldout "
                                                  f"{declaration.min_heldout}; round 4 cannot judge on so little")
        return report
    arms: list[tuple[str, Passage | None]] = [(INTACT, None), *((p.arm, p) for p in declaration.variants)]
    planned, _ = _plan(declaration, arms, held)
    if not _execute(declaration, planned, ledger, runner, report, plan_only):
        return report
    passing: list[str] = []
    for variant in declaration.variants:
        worse: list[str] = []
        for clause, tasks in held.items():
            base = _counts(planned, ledger, INTACT, tasks)
            mine = _counts(planned, ledger, variant.arm, tasks)
            report.per_clause.setdefault(clause, {})[INTACT] = base
            report.per_clause[clause][variant.arm] = mine
            if mine["error"] or base["error"]:
                worse.append(f"{clause} (an attempt errored, so not shown no-worse)")
            elif mine["pass"] < base["pass"] - declaration.tolerance:
                worse.append(f"{clause} ({mine['pass']} < {base['pass']} - tolerance {declaration.tolerance})")
        report.variants[variant.arm] = {"removes": f"{variant.file}: {variant.remove[:80]}", "source": variant.clause,
                                        "passes": not worse, "worse_on": worse}
        if not worse:
            passing.append(variant.arm)
    if passing:
        report.recommendation = TRIM
        report.reason = f"variant(s) no worse on every clause: {', '.join(passing)}"
    else:
        report.recommendation = KEEP
        report.reason = "no variant is no worse on every clause, so keep the skill as it is"
    return report


def render(report: RoundReport) -> str:
    lines = [f"GAUNTLET ROUND {report.round}: {report.verdict}" + (f" - {report.recommendation}" if report.recommendation else ""),
             f"  {report.reason}",
             (f"  attempts: declared {report.declared}, reused {report.reused}, new {report.new}, run {report.run}; "
              f"cap {report.cap if report.cap is not None else 'NONE'}"),
             f"  no-worse tolerance: {report.tolerance}" + (" (declared by the owner)" if report.tolerance else " (strict)")]
    lines += [f"  client: {c}" for c in report.clients]
    for clause, arms in sorted(report.per_clause.items()):
        cells = "; ".join(f"{arm} {c['pass']}/{c['evaluable']}" + (f" ({c['error']} error)" if c["error"] else "")
                          for arm, c in arms.items())
        lines.append(f"  clause {clause}: {cells}")
    for arm, s in sorted(report.separation.items()):
        lines.append(f"  separation {arm} on {s['clause']}: {s['verdict']}" + (f" (p={s['p']:.4f})" if isinstance(s['p'], float) and math.isfinite(s['p']) else "")
                     + (f" - {s['reason']}" if s["reason"] else ""))
    for arm, v in sorted(report.variants.items()):
        worse_on = v["worse_on"]
        listed = "; ".join(str(w) for w in worse_on) if isinstance(worse_on, list) else str(worse_on)
        lines.append(f"  variant {arm}: {'PASSES' if v['passes'] else 'worse on ' + listed}")
    return "\n".join(lines) + "\n"
