"""`skillc charter create`: the owner's answers become a CHARTER.md, with a
trap-task stub for every clause (#778, part B).

`charter evidence` (part A) gathered every existing piece of the skill's
charter as cited suggestions. The `/charter-create` dialogue walks the owner
through them and writes the owner's answers. This module turns those answers
into the charter, and it never answers for the owner:

- **Every suggestion needs an answer** (accept, edit or drop). An accepted or
  edited suggestion must be used by a clause, and a dropped one must not be.
- **Every must-never and authority clause needs a `shortcut`**: the tempting
  wrong move a capable model would make. It becomes the `bad/` half of the
  clause's trap-task stub, so every safety line has a failing example from
  the start (`negative-backed`).
- **`approved` is stamped only on intent and authority**, only where the owner
  answered `approve: true`, and only with an `approved_on` date (the
  `charter confirm` allowlist).

The stubs live at `evals/trap-tasks/<contract>/<clause-slug>/{bad,good}/` at
the collection root, outside the skill, so the skill's own tree is unchanged.
A stub holds `STUB.md`, `goal.md` and `fixture/README.md` and NO grader, so
`verify.GraderDef.load` refuses it: round 3 can never grade a stub as a task.
#736 PR 2 fills a stub into a graded task.

After writing, the real `contracts` rules run over the collection. Any error
on this charter, or an approval warning on a clause the owner approved, rolls
back everything create wrote. create never runs git: in another repository's
collection it writes the files, and committing them is the owner's act.
No model is called.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import charter, contracts
from .spec import FrontmatterError, parse_contract_block

SCHEMA = 1
ANSWERS = ("accept", "edit", "drop")
#: Clause sections an answer may name. Intent and purpose are their own fields.
CLAUSE_SECTIONS = ("always", "never", "provides", "requires", "authority", "failure")
#: Sections whose clauses are safety lines: each needs a shortcut, and a bad case.
SAFETY = ("never", "authority")
APPROVABLE = ("intent", "authority")
TRAP_ROOT = ("evals", "trap-tasks")
STUB_FILE = "STUB.md"
#: Files in a skill's directory that are not the skill: the charter create
#: writes, and the gauntlet's record.
NOT_THE_SKILL = frozenset({"CHARTER.md", "GAUNTLET.json"})
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class CreateRefused(ValueError):
    """The answers cannot become a charter. Nothing was written."""


@dataclass(frozen=True)
class Clause:
    section: str
    id: str  # the full id, <contract>.<slug>
    slug: str
    what: str
    sources: tuple[str, ...]  # suggestion ids
    shortcut: str = ""
    good: str = ""
    test: str = ""  # an existing test path in the collection, offered by the owner
    approve: bool = False

    @property
    def stubbed(self) -> bool:
        """A safety line always gets a stub (its bad case); any other clause
        gets one only when it names no existing test."""
        return self.section in SAFETY or not self.test


@dataclass
class Created:
    charter: Path
    stubs: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- reading the answers


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CreateRefused(f"{where}: needs the owner's text")
    return " ".join(value.split())


def _sources(value: object, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CreateRefused(f"{where}: 'from' is a suggestion id or a list of them")
    return tuple(value)


def _date(value: object, today: _dt.date) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CreateRefused("approved_on: not a YYYY-MM-DD date")
    try:
        day = _dt.date.fromisoformat(value)
    except ValueError:
        raise CreateRefused(f"approved_on {value!r} is not a real date") from None
    if day > today:
        raise CreateRefused(f"approved_on {value} is in the future")
    return value


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:62].strip("-")
    return slug


@dataclass(frozen=True)
class Plan:
    contract: str
    intent: str
    intent_sources: tuple[str, ...]
    intent_approve: bool
    purpose: str
    purpose_sources: tuple[str, ...]
    clauses: tuple[Clause, ...]
    approved_on: str | None


def offered_suggestions(evidence: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    """The evidence file's suggestions by id. A missing or malformed population
    is refused, never read as empty (counter-model review): only an explicit
    empty list means "nothing was found"."""
    listed = evidence.get("suggestions")
    if not isinstance(listed, list):
        raise CreateRefused("the evidence file has no suggestions list; refusing to read it as empty")
    offered: dict[str, Mapping[str, object]] = {}
    for n, entry in enumerate(listed, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
            raise CreateRefused(f"evidence suggestions entry {n} has no string id")
        if entry["id"] in offered:
            raise CreateRefused(f"evidence suggestions repeat the id {entry['id']!r}")
        offered[entry["id"]] = entry
    return offered


def plan(evidence: Mapping[str, object], answers: Mapping[str, object], default_contract: str,
         today: _dt.date) -> Plan:
    """Check the answers against the evidence. Raises `CreateRefused`."""
    if evidence.get("schema") != 1:
        raise CreateRefused("the evidence file is not schema 1 (`skillc charter evidence`)")
    if answers.get("schema") != SCHEMA:
        raise CreateRefused("the answers file is not schema 1 (docs/specs/charter-create.md)")
    offered = offered_suggestions(evidence)
    given = answers.get("answers")
    if not isinstance(given, dict):
        raise CreateRefused("answers: needs an 'answers' object, one answer per suggestion")
    unanswered = [i for i in offered if i not in given]
    if unanswered:
        raise CreateRefused(f"unanswered suggestion(s): {', '.join(unanswered)}; every suggestion needs the owner's "
                            "accept, edit or drop")
    unknown = [i for i in given if i not in offered]
    if unknown:
        raise CreateRefused(f"answers name suggestion(s) the evidence does not hold: {', '.join(map(str, unknown))}")
    bad = {i: a for i, a in given.items() if a not in ANSWERS}
    if bad:
        raise CreateRefused(f"answer(s) not accept, edit or drop: {bad}")

    contract = answers.get("contract", default_contract)
    if not isinstance(contract, str) or not SLUG_RE.fullmatch(contract):
        raise CreateRefused(f"contract {contract!r}: lowercase letters, digits and dashes")
    approved_on = _date(answers.get("approved_on"), today)

    intent_data = answers.get("intent")
    if not isinstance(intent_data, dict):
        raise CreateRefused("intent: needs the owner's intent (what, and whether the owner approves it)")
    intent = _text(intent_data.get("what"), "intent")
    intent_approve = intent_data.get("approve") is True
    intent_sources = _sources(intent_data.get("from"), "intent")
    purpose_data = answers.get("purpose")
    if isinstance(purpose_data, dict):
        purpose, purpose_sources = _text(purpose_data.get("what"), "purpose"), _sources(purpose_data.get("from"), "purpose")
        if purpose_data.get("approve") is True:
            raise CreateRefused("purpose: only intent and authority clauses take the owner's approval")
    else:
        purpose, purpose_sources = _text(purpose_data, "purpose"), ()

    raw = answers.get("clauses")
    if not isinstance(raw, list):
        raise CreateRefused("clauses: needs a list (it may be empty)")
    clauses: list[Clause] = []
    seen: set[str] = {"intent"}
    counts: dict[str, int] = {}
    for n, entry in enumerate(raw, 1):
        where = f"clause {n}"
        if not isinstance(entry, dict):
            raise CreateRefused(f"{where}: not an object")
        section = entry.get("section")
        if section not in CLAUSE_SECTIONS:
            raise CreateRefused(f"{where}: section {section!r} is not one of {', '.join(CLAUSE_SECTIONS)}")
        section = str(section)
        what = _text(entry.get("what"), where)
        counts[section] = counts.get(section, 0) + 1
        slug = entry.get("id") if entry.get("id") is not None else f"{section}-{counts[section]}"
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
            raise CreateRefused(f"{where}: id {slug!r}: lowercase letters, digits and dashes")
        if slug in seen:
            raise CreateRefused(f"{where}: id {slug!r} is used twice")
        seen.add(slug)
        shortcut = entry.get("shortcut")
        if section in SAFETY:
            if not isinstance(shortcut, str) or not shortcut.strip():
                raise CreateRefused(f"{where} ({section} {slug!r}): names no shortcut; every {section} clause needs the "
                                    "tempting wrong move, which becomes its bad case")
        elif shortcut is not None and not isinstance(shortcut, str):
            raise CreateRefused(f"{where}: shortcut is text")
        approve = entry.get("approve") is True
        if approve and section not in APPROVABLE:
            raise CreateRefused(f"{where} ({section} {slug!r}): only intent and authority clauses take the owner's "
                                "approval")
        test = entry.get("test") or ""
        if not isinstance(test, str):
            raise CreateRefused(f"{where}: test is one existing path")
        good = entry.get("good") or ""
        if not isinstance(good, str):
            raise CreateRefused(f"{where}: good is text")
        clauses.append(Clause(section, f"{contract}.{slug}", slug, what, _sources(entry.get("from"), where),
                              " ".join(str(shortcut or "").split()), " ".join(good.split()), test.strip(), approve))

    if (intent_approve or any(c.approve for c in clauses)) and approved_on is None:
        raise CreateRefused("an approval needs approved_on: the date the owner approved it")
    if not intent_approve and not any(c.approve for c in clauses) and approved_on is not None:
        raise CreateRefused("approved_on is given, but no clause is marked approve: true")

    used = [*intent_sources, *purpose_sources, *(s for c in clauses for s in c.sources)]
    for sid in used:
        if sid not in offered:
            raise CreateRefused(f"'from' names {sid!r}, which the evidence does not hold")
        if given[sid] == "drop":
            raise CreateRefused(f"{sid} was dropped by the owner, yet a clause uses it")
    unused = [i for i, a in given.items() if a in ("accept", "edit") and i not in used]
    if unused:
        raise CreateRefused(f"accepted or edited suggestion(s) no clause uses: {', '.join(unused)}; name each in a "
                            "clause's 'from', or drop it")
    return Plan(contract, intent, intent_sources, intent_approve, purpose, purpose_sources, tuple(clauses), approved_on)


# ---------------------------------------------------------------- writing


def stub_dir(root: Path, contract: str, clause: Clause) -> Path:
    return root.joinpath(*TRAP_ROOT, contract, clause.slug)


def _test_field(root: Path, plan_: Plan, clause: Clause) -> str | list[str]:
    stub = "/".join([*TRAP_ROOT, plan_.contract, clause.slug, "{bad,good}"])
    if not clause.stubbed:
        return clause.test
    return [clause.test, stub] if clause.test else stub


def _stub_text(kind: str, plan_: Plan, clause: Clause) -> dict[str, str]:
    if kind == "bad":
        move = clause.shortcut or f"the skill does not deliver: {clause.what}"
        title = "the tempting shortcut is the WRONG move"
    else:
        move = clause.good or f"the skill follows its rule: {clause.what}"
        title = "the skill's rule is followed"
    stub = (
        f"# STUB: {clause.id} ({kind})\n\n"
        f"This is a trap-task STUB written by `skillc charter create` (#778). It is not a\n"
        f"graded task yet: it has no grader, so `verify.GraderDef.load` refuses it and round 3\n"
        f"cannot run it.\n\n"
        f"- **Clause:** `{clause.id}` ({clause.section})\n"
        f"- **The clause, in the owner's words:** {clause.what}\n"
        f"- **This case ({kind}):** {title}.\n"
        f"- **The move, in the owner's words:** {move}\n\n"
        f"To fill it (#736 PR 2): write the agent's real task in `goal.md` and its inputs in\n"
        f"`fixture/`, then add `grader.json`, `probe.py`, `judge.py` and `inputs.json` (the\n"
        f"task shape `gauntlet_trials.read_task` reads), and delete this file.\n"
    )
    goal = (
        f"<!-- STUB goal for {clause.id} ({kind}); #736 PR 2 replaces it. -->\n\n"
        f"A task where {move[0].lower() + move[1:] if move else move}\n"
    )
    readme = f"Fixture for the {kind} case of `{clause.id}`. Empty until #736 PR 2 fills the task.\n"
    return {STUB_FILE: stub, "goal.md": goal, "fixture/README.md": readme}


def render(plan_: Plan, subject: str | None, offered: Mapping[str, Mapping[str, object]], root: Path) -> str:
    intent: dict[str, object] = {"id": f"{plan_.contract}.intent", "what": plan_.intent}
    if plan_.intent_approve:
        intent["approved"] = str(plan_.approved_on)
    data: dict[str, object] = {"contract": plan_.contract, "version": 1}
    if subject:
        data["subject"] = subject
    data.update({"intent": intent, "purpose": plan_.purpose, "owner": "owner"})
    by_section: dict[str, list[dict[str, object]]] = {s: [] for s in CLAUSE_SECTIONS}
    for c in plan_.clauses:
        entry: dict[str, object] = {"id": c.id, "what": c.what}
        if c.section == "requires":
            entry["on_false"] = "stop with UNKNOWN; never proceed on a guess"
        entry["test"] = _test_field(root, plan_, c)
        if c.approve:
            entry["approved"] = str(plan_.approved_on)
        by_section[c.section].append(entry)
    for section in ("provides", "requires"):
        if by_section[section]:
            data[section] = by_section[section]
    data["invariants"] = {"always": by_section["always"], "never": by_section["never"]}
    for section in ("authority", "failure"):
        if by_section[section]:
            data[section] = by_section[section]
    block = "---\n" + charter.dump(data) + "---\n"

    def cite(ids: tuple[str, ...]) -> str:
        return "; ".join(f"{i}: {offered[i].get('cite', '')}" for i in ids) if ids else "the owner, in the dialogue"

    rows = [f"| `{plan_.contract}.intent` | intent | {charter._cell(cite(plan_.intent_sources))} |"]
    rows += [f"| `{c.id}` | {c.section} | {charter._cell(cite(c.sources))} |" for c in plan_.clauses]
    approved = (f"The owner approved the intent and authority clauses marked `approved` on {plan_.approved_on}."
                if plan_.approved_on else "**Nothing here is approved yet.** Only the owner approves intent and authority.")
    body = (
        f"\n# Charter: {plan_.contract}\n\n"
        f"Composed with the owner by `skillc charter create` (#778), from the owner's answers.\n"
        f"{approved}\n\n"
        f"Every clause's test is a trap-task stub under `evals/trap-tasks/{plan_.contract}/` unless it\n"
        f"names an existing test. A stub has no grader yet: #736 PR 2 fills it into a graded task.\n\n"
        f"## Where each clause came from\n\n| Clause | Section | Evidence |\n|---|---|---|\n" + "\n".join(rows) + "\n"
    )
    return block + body


def skill_tree_digest(skill_text: Path, command: bool, outputs: tuple[Path, ...] = ()) -> str:
    """The skill's own files, by relative path and content: the whole directory
    for a native skill (less CHARTER.md, GAUNTLET.json and anything under
    `outputs`, the stub directories create itself writes - a skill at the
    collection root holds them, counter-model review), the file itself for a
    command."""
    h = hashlib.sha256()
    if command:
        h.update(skill_text.read_bytes())
        return h.hexdigest()
    base = skill_text.parent
    skip = tuple(o.resolve() for o in outputs)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath, name)
            rel = path.relative_to(base).as_posix()
            if rel in NOT_THE_SKILL or any(path.resolve().is_relative_to(o) for o in skip):
                continue
            h.update(rel.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def _all_draft(path: Path) -> bool:
    try:
        data, _ = parse_contract_block(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, FrontmatterError):
        return False
    clauses: list[object] = [data.get("intent")]
    # A section that is present but not a list is NOT shown to hold only drafts
    # (counter-model review: an `authority` mapping hid an approved clause).
    for s in ("provides", "requires", "authority", "failure"):
        entries = data.get(s)
        if entries is None:
            continue
        if not isinstance(entries, list):
            return False
        clauses.extend(entries)
    inv = data.get("invariants")
    if inv is not None:
        if not isinstance(inv, dict):
            return False
        for k in ("always", "never"):
            entries = inv.get(k)
            if entries is None:
                continue
            if not isinstance(entries, list):
                return False
            clauses.extend(entries)
    return all(isinstance(c, dict) and c.get("draft") is True and "approved" not in c for c in clauses)


RULES = {
        "contract-shape": contracts.contract_shape, "clause-backed": contracts.clause_backed,
        "negative-backed": contracts.negative_backed, "handoff-bilateral": contracts.handoff_bilateral,
        "handoff-version": contracts.handoff_version, "reader-exists": contracts.reader_exists,
        "scope-owned": contracts.scope_owned, "duty-single-owner": contracts.duty_single_owner,
        "approval-present": contracts.approval_present,
}


def _all_findings(root: Path) -> tuple[contracts.Collection, set[tuple[str, str, str]]]:
    """Every finding of every rule over the whole collection, as (rule, path, message)."""
    collection = contracts.load_collection(root)
    found = {(name, str(Path(path).resolve()), message)
             for name, rule in RULES.items() for path, message in rule(collection)}
    return collection, found


def _findings(root: Path, charter_path: Path, before: set[tuple[str, str, str]] = frozenset()  # type: ignore[assignment]
              ) -> Iterator[tuple[str, str]]:
    """Findings this charter introduces: every finding ON it, and every NEW
    finding on another contract (counter-model review: replacing a draft can
    break a neighbour's hand-off, which the rule reports against the
    neighbour). An approval warning on another contract is never ours.

    Raises `CreateRefused` when the charter was not examined: discovery did not
    find it, or the cross-contract rules could not run."""
    collection, after = _all_findings(root)
    target = str(charter_path.resolve())
    ours = [c for c in collection.contracts if str(c.path.resolve()) == target]
    if not ours or ours[0].parse_error is not None:
        raise CreateRefused("not examined: the contracts rules did not read the composed charter")
    if not contracts._cross_ready(collection):
        raise CreateRefused("not examined: the collection's cross-contract rules could not run (another CHARTER.md "
                            "fails contract-shape, a name or provider repeats, or a directory is unreadable), so the "
                            "hand-offs are unchecked; fix the collection first")
    for name, path, message in sorted(after):
        if path == target:
            yield name, message
        elif (name, path, message) not in before and name != "approval-present":
            yield name, f"{Path(path).relative_to(root.resolve()) if Path(path).is_relative_to(root.resolve()) else path}: {message}"


def create(collection: Path, skill: str, evidence_path: Path, answers_path: Path, *, replace_draft: bool = False,
           today: _dt.date | None = None) -> Created:
    """Write the charter and its stubs, check them with the real contracts
    rules, and roll back on any failure. Raises `CreateRefused` or
    `gauntlet.UsageError`."""
    from .gauntlet import resolve_skill

    today = today or _dt.datetime.now(_dt.UTC).date()
    target = resolve_skill(collection, skill)
    root = target.collection
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        answers = json.loads(answers_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CreateRefused(f"cannot read the evidence or answers file: {exc}") from None
    if not isinstance(evidence, dict) or not isinstance(answers, dict):
        raise CreateRefused("the evidence and answers files are JSON objects")
    if evidence.get("skill") != target.rel:
        raise CreateRefused(f"the evidence is for {evidence.get('skill')!r}, not {target.rel!r}")
    front: dict[str, object] = {}
    try:
        front = charter.read_skill(target.text)[0]
    except (OSError, UnicodeDecodeError):
        pass
    default = charter._slug(str(front.get("name") or charter.primary_name(target.text)))
    plan_ = plan(evidence, answers, default, today)
    offered = offered_suggestions(evidence)
    for c in plan_.clauses:
        if c.test and (not contracts._inside(root, c.test) or not (root / c.test).exists()):
            raise CreateRefused(f"clause {c.id}: test {c.test!r} is not an existing path in the collection")
    subject = target.text.relative_to(root).as_posix() if target.command else None
    text = render(plan_, subject, offered, root)

    out = target.charter
    old: bytes | None = None
    if out.exists() or out.is_symlink():
        if out.is_symlink() or not (replace_draft and _all_draft(out)):
            raise CreateRefused(f"{out.relative_to(root)} exists; create never overwrites a charter (--replace-draft "
                                "replaces one whose every clause is still a draft)")
        old = out.read_bytes()  # restored byte for byte (counter-model review: CRLF)
    stubs = [stub_dir(root, plan_.contract, c) for c in plan_.clauses if c.stubbed]
    for d in stubs:
        if d.exists() or d.is_symlink():
            raise CreateRefused(f"{d.relative_to(root)} exists; create never overwrites a trap task")
    # No symlink anywhere between the collection root and any output, and every
    # output inside the collection (counter-model review: a symlinked
    # `charters/` or `evals/` redirected writes outside it).
    real_root = root.resolve()
    for path in [out, *stubs]:
        for part in [path, *path.parents]:
            if part == root:
                break
            if part.is_symlink():
                raise CreateRefused(f"{part.relative_to(root)} is a symlink; create never writes through one")
        if not path.resolve().is_relative_to(real_root):
            raise CreateRefused(f"{path} resolves outside the collection; refusing to write there")

    _, findings_before = _all_findings(root)
    before = skill_tree_digest(target.text, target.command, tuple(stubs))
    made_files: list[Path] = []
    made_dirs: list[Path] = []
    touched = False  # the draft is restored only if create began writing it

    def mkdirs(path: Path) -> None:
        missing = []
        p = path
        while not p.exists():
            missing.append(p)
            p = p.parent
        for d in reversed(missing):
            d.mkdir()
            made_dirs.append(d)

    def write(path: Path, content: str) -> None:
        mkdirs(path.parent)
        nonlocal touched
        fresh = path != out or old is None
        if not fresh:
            touched = True
        if fresh:
            # Owned BEFORE it is opened (counter-model review): every target was
            # checked absent above, so a failure anywhere in creating or writing
            # it rolls it back. A path that appeared meanwhile is not ours.
            made_files.append(path)
        try:
            with path.open("x" if fresh else "w", encoding="utf-8") as fh:
                fh.write(content)
        except FileExistsError:
            made_files.remove(path)
            raise CreateRefused(f"{path} appeared while composing; create never overwrites") from None

    def rollback() -> None:
        try:
            for f in reversed(made_files):
                f.unlink(missing_ok=True)
            if old is not None and touched:
                out.write_bytes(old)
        finally:
            # Directory cleanup runs even if restoring the draft fails
            # (counter-model review): an empty stub directory blocks a retry.
            for d in reversed(made_dirs):
                try:
                    d.rmdir()
                except OSError:
                    pass

    try:
        for clause, d in zip([c for c in plan_.clauses if c.stubbed], stubs, strict=True):
            for kind in ("bad", "good"):
                for rel, content in _stub_text(kind, plan_, clause).items():
                    write(d / kind / rel, content)
        write(out, text)
        problems: list[str] = []
        withheld = {f"{plan_.contract}.intent"} if not plan_.intent_approve else set()
        withheld |= {c.id for c in plan_.clauses if c.section == "authority" and not c.approve}
        warnings: list[str] = []
        for rule, message in _findings(root, out, findings_before):
            if rule == "approval-present":
                named = re.search(r"clause '([^']+)'", message)
                owner_withheld = (named.group(1) in withheld) if named else (f"{plan_.contract}.intent" in withheld)
                (warnings if owner_withheld else problems).append(f"{rule}: {message}")
            else:
                problems.append(f"{rule}: {message}")
        if problems:
            raise CreateRefused("the composed charter is not clean, so nothing was kept: " + "; ".join(problems))
        if skill_tree_digest(target.text, target.command, tuple(stubs)) != before:
            raise CreateRefused("the skill's own files changed while composing; nothing was kept")
    except BaseException:
        rollback()
        raise
    return Created(out, stubs, warnings)
