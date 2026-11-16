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

import dataclasses
import hashlib
import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .reliability import DISCRIMINATION_VERDICTS, TwoArmRule, evaluate_discrimination
from .source_digest import SourceUnreadable, digest_entries, tree_entries

#: The engine's record (#754, `skillc.gauntlet.RECORD_NAME`), written beside a
#: native skill's CHARTER.md on every run. It is never part of the skill, so it
#: is left out of the skill digest. The charter itself stays IN: a changed
#: charter must invalidate a declaration. Kept as a literal so this module
#: imports no engine code (`tests/test_gauntlet_trials.py` pins the two equal).
ENGINE_RECORD = "GAUNTLET.json"


def skill_digest(skill: Path) -> str:
    """The skill's digest, without the engine's record (#737 review)."""
    entries = tree_entries(skill)
    return digest_entries({path: value for path, value in entries.items()
                           if path != ENGINE_RECORD})

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
    clauses: dict[str, tuple[Task, ...]]
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
    actual = skill_digest(skill)
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
    clauses: dict[str, tuple[Task, ...]] = {}
    # #756 (3): one agent-visible task has ONE grader across the whole
    # declaration, checked before planning, so no attempt is spent on both.
    everywhere: dict[str, tuple[str, Task]] = {}
    for clause_id, tasks in raw_clauses.items():
        if not isinstance(tasks, list) or not all(isinstance(t, str) for t in tasks):
            raise DeclarationError(f"clause {clause_id!r}: tasks must be a list of task directories")
        distinct: dict[str, Task] = {}
        for task in (read_task((base / t).resolve()) for t in sorted(set(tasks))):
            seen = distinct.setdefault(task.identity, task)  # identical copies are ONE task
            first_clause, first = everywhere.setdefault(task.identity, (str(clause_id), task))
            for other_clause, other in ((str(clause_id), seen), (first_clause, first)):
                if other.grader_digest != task.grader_digest:
                    raise DeclarationError(f"clauses {other_clause!r} and {clause_id!r}: {other.path} and {task.path} "
                                           f"are the same task with different graders; declare one")
        clauses[str(clause_id)] = tuple(sorted(distinct.values(), key=lambda t: t.path))
    if not clauses:
        raise DeclarationError("no clause is declared")
    damaged = _passages(data.get("damaged", []), "damaged", clause_ids=set(clauses))
    if not damaged:
        raise DeclarationError("at least one damaged arm is required: it is the separation control")
    variants = _passages(data.get("variants", []), "variants", clause_ids=None)
    if {p.arm for p in damaged} & {p.arm for p in variants}:
        raise DeclarationError("an arm name is both damaged and a variant")
    partial = data.get("partial", False)
    if not isinstance(partial, bool):
        raise DeclarationError("partial must be true or false (a JSON boolean)")
    return Declaration(path, skill, actual, client, cap, partial, replicates,
                       str(data.get("seed", "0")), minimum, min_heldout, tolerance, rule, clauses, damaged, variants)


# ---------------------------------------------------------------- arms and identities


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remove_sha256(passage: Passage) -> str:
    """The whole removed passage's identity. `removes` is cut to 80 characters
    for display, so two passages can share it (#737 review)."""
    return "sha256:" + hashlib.sha256(passage.remove.encode()).hexdigest()


def arm_text(declaration: Declaration, passage: Passage | None) -> dict[str, str]:
    """The arm's changed files: {relative path: new text}. The intact arm
    changes nothing. A passage must occur EXACTLY once, or the arm would not
    be the one named."""
    if passage is None:
        return {}
    rel = Path(passage.file)
    target = declaration.skill / rel
    try:
        inside = (not rel.is_absolute() and ".." not in rel.parts and not target.is_symlink()
                  and target.resolve().is_relative_to(declaration.skill.resolve()) and target.is_file())
    except (OSError, ValueError):
        inside = False
    if not inside:
        raise DeclarationError(f"arm {passage.arm!r}: {passage.file} is not a regular file inside the skill; "
                               f"a passage outside it would leave the skill undamaged")
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeclarationError(f"arm {passage.arm!r}: {passage.file} not read: {exc}") from None
    count = text.count(passage.remove)
    if count != 1:
        raise DeclarationError(f"arm {passage.arm!r}: the passage occurs {count} times in {passage.file}; it must occur once")
    # #756 (4): the key is the canonical path inside the skill, so `./SKILL.md`
    # and `SKILL.md` are one arm. `inside` above already refused any target
    # that resolves outside the skill, so canonicalising is never an escape.
    canonical = target.resolve().relative_to(declaration.skill.resolve()).as_posix()
    return {canonical: text.replace(passage.remove, "", 1)}


def arm_digest(declaration: Declaration, passage: Passage | None) -> str:
    changes = arm_text(declaration, passage)
    if not changes:
        return declaration.skill_digest
    return _sha(json.dumps({"base": declaration.skill_digest, "changes": changes}, sort_keys=True).encode())


#: What the agent sees of a task: its goal and its fixture (#756 (1)).
AGENT_INPUTS = ("goal.md", "fixture/")


def task_digest(path: Path) -> str:
    """The agent-visible task's identity: git's mode and blob for goal.md and
    every entry under fixture/ (#756 (1)). The execute bit counts, a symlink
    counts as its link text and is never followed, and a FIFO or device reads
    as not-a-file. Empty directories are invisible, as they are to git."""
    try:
        entries = tree_entries(path)
    except SourceUnreadable as exc:
        raise DeclarationError(f"task {path}: not read: {exc}") from None
    return digest_entries({p: v for p, v in entries.items()
                           if p == AGENT_INPUTS[0] or p.startswith(AGENT_INPUTS[1])})


@dataclass(frozen=True)
class Task:
    """One trap task, identified by CONTENT, not by path (counter-model review
    on #736: two byte-identical directories are one task, never two)."""

    path: Path
    task_digest: str  # what the agent sees: goal.md and fixture/
    grader_digest: str  # verify.GraderDef.digest(): definition, probe, inputs, judge

    @property
    def identity(self) -> str:
        """What the AGENT sees (counter-model review, pass 2): two directories
        with the same goal and fixture are one task for the minimums and the
        split, whatever their graders. The grader stays in the ledger key."""
        return self.task_digest


def read_task(path: Path) -> Task:
    """A task's identities. The grader's is verify's own pin, so editing a
    README beside it changes nothing, while editing the grader does."""
    from .verify import GraderDef, Refused

    goal, fixture = path / "goal.md", path / "fixture"
    if not goal.is_file() or goal.is_symlink() or not fixture.is_dir() or fixture.is_symlink():
        raise DeclarationError(f"task {path}: needs a goal.md file and a fixture/ directory (the agent's inputs)")
    try:
        grader = GraderDef.load(path).digest()
    except (Refused, OSError, ValueError) as exc:
        raise DeclarationError(f"task {path}: grader not read: {exc}") from None
    return Task(path, task_digest(path), grader)


# ---------------------------------------------------------------- the split


def assignments(declaration: Declaration) -> dict[str, str]:
    """ONE split over every distinct task (counter-model review: a task shared
    by two clauses must never train one and be held out for the other).
    Clauses are walked in a fixed order. Each clause's not-yet-assigned tasks
    are shuffled with the seed, and enough are held out to give that clause
    a third of its tasks (at least one) held out. A clause left without a
    train or a held-out task reads UNKNOWN by the minimums."""
    placed: dict[str, str] = {}
    for clause in sorted(declaration.clauses):
        tasks = declaration.clauses[clause]
        want = max(1, len(tasks) // 3)
        have = sum(placed.get(t.identity) == "held" for t in tasks)
        # #756 (2): ordered by content, never by path, so a rename moves nothing.
        fresh = sorted((t for t in tasks if t.identity not in placed), key=lambda t: t.identity)
        random.Random(f"{declaration.seed}:{clause}").shuffle(fresh)
        for task in fresh:
            if have < want:
                placed[task.identity] = "held"
                have += 1
            else:
                placed[task.identity] = "train"
    return placed


def split(declaration: Declaration, clause: str) -> tuple[tuple[Task, ...], tuple[Task, ...]]:
    """(train, held-out) for one clause, from the single global split."""
    placed = assignments(declaration)
    tasks = declaration.clauses[clause]
    return (tuple(t for t in tasks if placed[t.identity] == "train"),
            tuple(t for t in tasks if placed[t.identity] == "held"))


# ---------------------------------------------------------------- the ledger


class LedgerError(ValueError):
    """A ledger this module cannot trust; nothing is reused from it."""


LEDGER_FIELDS = ("key", "arm", "task", "replicate", "result", "skill", "client", "version", "model")


@dataclass(frozen=True)
class Attempt:
    arm: str
    task: Task
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
    its first outcome. Every row is validated on load: a malformed line, a
    missing field or an unknown result refuses the whole ledger
    (counter-model review: an invalid row read as zero evidence)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: dict[str, dict[str, object]] = {}
        if not path.is_file():
            return
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise LedgerError(f"{path}:{number}: not JSON: {exc}") from None
            if not isinstance(row, dict) or set(LEDGER_FIELDS) - set(row):
                raise LedgerError(f"{path}:{number}: a row needs {', '.join(LEDGER_FIELDS)}")
            if row["result"] not in OUTCOMES:
                raise LedgerError(f"{path}:{number}: result {row['result']!r} is not one of {', '.join(OUTCOMES)}")
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


def attempt_key(declaration: Declaration, arm_digest_value: str, task: Task, arm: str, replicate: int) -> str:
    c = declaration.client
    return _sha(json.dumps({
        "skill": arm_digest_value, "task": task.task_digest, "grader": task.grader_digest,
        "client": c.name, "version": c.version, "model": c.model, "arm": arm, "replicate": replicate,
    }, sort_keys=True).encode())


def _row_matches(declaration: Declaration, row: Mapping[str, object]) -> bool:
    c = declaration.client
    return (row.get("client"), row.get("version"), row.get("model")) == (c.name, c.version, c.model)


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
    notes: list[str] = field(default_factory=list)


Planned = tuple[Attempt, str, Mapping[str, str]]


def _plan(declaration: Declaration, arms: Sequence[tuple[str, Passage | None]],
          tasks_of: Mapping[str, Sequence[Task]]) -> list[Planned]:
    """Every distinct (arm, task identity, replicate) the round needs."""
    planned: dict[str, Planned] = {}
    for arm, passage in arms:
        changes = arm_text(declaration, passage)
        digest = arm_digest(declaration, passage)
        for tasks in tasks_of.values():
            for task in tasks:
                for r in range(declaration.replicates):
                    key = attempt_key(declaration, digest, task, arm, r)
                    planned.setdefault(key, (Attempt(arm, task, r, key), digest, changes))
    return list(planned.values())


def _record_clients(planned: Sequence[Planned], ledger: Ledger, report: RoundReport) -> None:
    rows = (ledger.get(p[0].key) for p in planned)
    report.clients = sorted({f"{r['client']} {r['version']} {r['model']}" for r in rows if r})


def _execute(declaration: Declaration, planned: list[Planned], ledger: Ledger,
             runner: AttemptRunner | None, report: RoundReport, plan_only: bool = False) -> bool:
    """Run what the ledger lacks, within the cap. False when the round stops."""
    for attempt, digest, _changes in planned:
        row = ledger.get(attempt.key)
        if row is not None and not (_row_matches(declaration, row) and row.get("arm") == attempt.arm
                                    and row.get("skill") == digest and row.get("replicate") == attempt.replicate):
            # Counter-model review, pass 2: a cached row must be the attempt
            # its key names, or it is not reused - the ledger is refused.
            report.verdict, report.reason = REFUSED, (f"ledger row {attempt.key[:12]} disagrees with the attempt its key "
                                                      f"names (client, arm, skill or replicate); the ledger is not trusted")
            return False
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
    for attempt, digest, changes in needed:
        if cap is not None and report.run >= cap:
            report.verdict, report.reason = INCOMPLETE, f"stopped at attempt_cap {cap}; {len(needed) - report.run} attempt(s) not run"
            _record_clients(planned, ledger, report)
            return False
        assert runner is not None
        outcome = runner.run(declaration, attempt.arm, changes, attempt.task.path, attempt.replicate)
        row = {"key": attempt.key, "arm": attempt.arm, "task": attempt.task.path.name, "replicate": attempt.replicate,
               "result": outcome.result if outcome.result in OUTCOMES else ERROR, "skill": digest,
               "client": outcome.client, "version": outcome.version, "model": outcome.model}
        report.run += 1
        if not _row_matches(declaration, row):
            # Counter-model review: a different client's grade must never be
            # filed under the declared one, where a re-run would reuse it.
            report.verdict, report.reason = REFUSED, (
                f"the runner reported {outcome.client} {outcome.version} {outcome.model}, not the declared "
                f"{declaration.client.name} {declaration.client.version} {declaration.client.model}; not recorded")
            _record_clients(planned, ledger, report)
            return False
        ledger.add(attempt.key, row)
    _record_clients(planned, ledger, report)
    return True


def _counts(planned: Sequence[Planned], ledger: Ledger, arm: str, tasks: Iterable[Task]) -> dict[str, int]:
    wanted = {t.identity for t in tasks}
    rows = [ledger.get(a.key) for a, _d, _c in planned if a.arm == arm and a.task.identity in wanted]
    results = [str(r["result"]) for r in rows if r]
    return {"pass": results.count(PASS), "evaluable": sum(r in (PASS, FAIL) for r in results),
            "error": results.count(ERROR), "missing": len(rows) - len(results)}


def _minimum_problem(declaration: Declaration, held_needed: bool) -> str | None:
    short = [c for c, t in declaration.clauses.items() if len(t) < declaration.min_tasks_per_clause]
    if short:
        return (f"clause(s) with fewer distinct tasks than min_tasks_per_clause {declaration.min_tasks_per_clause}: "
                f"{', '.join(sorted(short))}")
    empty = [c for c in declaration.clauses if not split(declaration, c)[0] or (held_needed and not split(declaration, c)[1])]
    if empty:
        return f"clause(s) left without a train or held-out task by the shared split: {', '.join(sorted(empty))}"
    return None


def _evidence_problem(report: RoundReport, expected: Mapping[str, int]) -> str | None:
    """Every clause and arm must hold its whole population before a verdict
    (counter-model review: 0/0 read as no worse)."""
    for clause, arms in report.per_clause.items():
        for arm, c in arms.items():
            if c["missing"] or c["pass"] + (c["evaluable"] - c["pass"]) + c["error"] != expected[clause]:
                return f"clause {clause} arm {arm} has {c['evaluable'] + c['error']} of {expected[clause]} attempts recorded"
    return None


def round3(declaration: Declaration, ledger: Ledger, runner: AttemptRunner | None,
           plan_only: bool = False) -> RoundReport:
    report = RoundReport(3, COMPLETE, "", 0, 0, 0, 0, declaration.attempt_cap, declaration.tolerance)
    problem = _minimum_problem(declaration, held_needed=False)
    if problem:
        report.verdict, report.reason = UNKNOWN, problem
        return report
    train = {c: split(declaration, c)[0] for c in declaration.clauses}
    arms: list[tuple[str, Passage | None]] = [(INTACT, None), *((p.arm, p) for p in declaration.damaged)]
    planned = _plan(declaration, arms, train)
    if not _execute(declaration, planned, ledger, runner, report, plan_only):
        return report
    for clause, tasks in train.items():
        report.per_clause[clause] = {arm: _counts(planned, ledger, arm, tasks) for arm, _ in arms}
    missing = _evidence_problem(report, {c: len(t) * declaration.replicates for c, t in train.items()})
    if missing:
        report.verdict, report.reason = UNKNOWN, missing
        return report
    for passage in declaration.damaged:
        intact = report.per_clause[passage.clause][INTACT]
        damaged = report.per_clause[passage.clause][passage.arm]
        if intact["error"] or damaged["error"]:
            # Counter-model review, pass 2: dropping one arm's errors from its
            # denominator can fake a difference. Errors mean no comparable pair.
            report.separation[passage.arm] = {"clause": passage.clause, "removes": f"{passage.file}: {passage.remove[:80]}",
                                              "remove_sha256": remove_sha256(passage),
                                              "verdict": "UNKNOWN", "p": None,
                                              "reason": "an attempt errored, so the arms are not comparable"}
            continue
        verdict = evaluate_discrimination(declaration.rule, intact["pass"], intact["evaluable"],
                                          damaged["pass"], damaged["evaluable"], certified=True)
        report.separation[passage.arm] = {"clause": passage.clause, "removes": f"{passage.file}: {passage.remove[:80]}",
                                          "remove_sha256": remove_sha256(passage),
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
    problem = _minimum_problem(declaration, held_needed=True)
    if problem:
        report.verdict, report.reason = UNKNOWN, problem
        return report
    held = {c: split(declaration, c)[1] for c in declaration.clauses}
    total_held = len({t.identity for ts in held.values() for t in ts})
    if total_held < declaration.min_heldout:
        report.verdict, report.reason = UNKNOWN, (f"{total_held} distinct held-out task(s), below min_heldout "
                                                  f"{declaration.min_heldout}; round 4 cannot judge on so little")
        return report
    baseline = round3(declaration, ledger, None)  # must be fully cached: round 4 never re-pays round 3
    if plan_only:
        # Counter-model review: a plan never needs round 3 to have run; it
        # says whether round 3 is done and counts round 4's own attempts.
        report.notes.append(f"round 3 prerequisite: {baseline.verdict} ({baseline.reason})")
    elif baseline.verdict == UNKNOWN:
        report.verdict, report.reason = UNKNOWN, f"round 3 is UNKNOWN ({baseline.reason}); round 4 cannot judge against it"
        return report
    elif baseline.verdict != COMPLETE:
        report.verdict, report.reason = REFUSED, f"round 3 is not complete ({baseline.reason}); run round 3 first"
        return report
    arms: list[tuple[str, Passage | None]] = [(INTACT, None), *((p.arm, p) for p in declaration.variants)]
    planned = _plan(declaration, arms, held)
    if not _execute(declaration, planned, ledger, runner, report, plan_only):
        return report
    for clause, tasks in held.items():
        report.per_clause[clause] = {arm: _counts(planned, ledger, arm, tasks) for arm, _ in arms}
    missing = _evidence_problem(report, {c: len(t) * declaration.replicates for c, t in held.items()})
    if missing:
        report.verdict, report.reason = UNKNOWN, missing
        return report
    passing: list[str] = []
    for variant in declaration.variants:
        worse: list[str] = []
        for clause in held:
            base, mine = report.per_clause[clause][INTACT], report.per_clause[clause][variant.arm]
            if mine["error"] or base["error"]:
                worse.append(f"{clause} (an attempt errored, so not shown no-worse)")
            elif mine["pass"] < base["pass"] - declaration.tolerance:
                worse.append(f"{clause} ({mine['pass']} < {base['pass']} - tolerance {declaration.tolerance})")
        report.variants[variant.arm] = {"removes": f"{variant.file}: {variant.remove[:80]}",
                                        "remove_sha256": remove_sha256(variant), "source": variant.clause,
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


def to_json(report: RoundReport) -> str:
    """The report as JSON: exactly `dataclasses.asdict(report)`. Round 5
    (#737) reads these field names, so they are an interface; renaming one
    is a breaking change for that reader."""
    return json.dumps(dataclasses.asdict(report), sort_keys=True, indent=2) + "\n"


def render(report: RoundReport) -> str:
    lines = [f"GAUNTLET ROUND {report.round}: {report.verdict}" + (f" - {report.recommendation}" if report.recommendation else ""),
             f"  {report.reason}",
             (f"  attempts: declared {report.declared}, reused {report.reused}, new {report.new}, run {report.run}; "
              f"cap {report.cap if report.cap is not None else 'NONE'}"),
             f"  no-worse tolerance: {report.tolerance}" + (" (declared by the owner)" if report.tolerance else " (strict)")]
    lines += [f"  {n}" for n in report.notes]
    lines += [f"  client: {c}" for c in report.clients]
    for clause, arms in sorted(report.per_clause.items()):
        cells = "; ".join(f"{arm} {c['pass']}/{c['evaluable']}" + (f" ({c['error']} error)" if c["error"] else "")
                          for arm, c in arms.items())
        lines.append(f"  clause {clause}: {cells}")
    for arm, s in sorted(report.separation.items()):
        p_value = s["p"]
        shown = f" (p={p_value:.4f})" if isinstance(p_value, float) and math.isfinite(p_value) else ""
        lines.append(f"  separation {arm} on {s['clause']}: {s['verdict']}{shown}" + (f" - {s['reason']}" if s["reason"] else ""))
    for arm, v in sorted(report.variants.items()):
        worse_on = v["worse_on"]
        listed = "; ".join(str(w) for w in worse_on) if isinstance(worse_on, list) else str(worse_on)
        lines.append(f"  variant {arm}: {'PASSES' if v['passes'] else 'worse on ' + listed}")
    return "\n".join(lines) + "\n"
