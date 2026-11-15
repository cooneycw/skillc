"""Skill-gauntlet round 1 (#726, PR A): the owner confirms a draft charter.

`skillc charter confirm <draft> --answers <file>` applies the OWNER'S answers
to a `charter draft` output, one per clause. Only the owner's answers become
the charter (#718, fixed rule: "never changes a charter without the owner").

**It never approves anything by itself.** With no answers file it refuses. An
answers file must answer every clause in the draft, exactly once, and name
nothing else. An unanswered clause is a refusal, never a default.

**`approved` is stamped only where #718 says approval counts**: on `intent`
and on `authority` clauses (`APPROVAL_SECTIONS`). An accepted
`invariants.always` clause loses its `draft` marker, but it is never stamped:
it is backed by a test (round 3), not by a date.

The answers format, one line per clause (`#` starts a comment):

    approved-on: 2026-11-15        # optional; defaults to today (UTC)
    flow-eli5.intent: accept
    flow-eli5.always-1: edit: Show every lane before approval.
    flow-eli5.always-2: drop
    flow-eli5.observed-retry: forbid

- `accept`: keep the clause as drafted.
- `edit: <text>`: keep it with the owner's wording.
- `drop`: remove it. The intent cannot be dropped, because a contract
  requires one; edit it instead.
- `forbid`: the owner forbids the duty. It moves to `invariants.never`,
  worded "Never: <duty>".

The dialogue that produces this file is held by the owner's own session in
the `grilling` skill's style (docs/specs/charter-round1.md); this module only
applies its result. Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path

from . import contracts
from .charter import dump
from .spec import FrontmatterError, parse_contract_block

#: The only clause sections an owner approval date belongs on (#718, "Contracts").
APPROVAL_SECTIONS = ("intent", "authority")

ACTIONS = ("accept", "edit", "drop", "forbid")
ANSWER_RE = re.compile(r"^(?P<id>[A-Za-z0-9][A-Za-z0-9._-]{0,127})\s*:\s*(?P<action>accept|edit|drop|forbid)\s*(?::\s*(?P<text>.*))?$")
DATE_LINE_RE = re.compile(r"^approved-on\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})$")


class ConfirmRefused(ValueError):
    """The answers cannot be applied; nothing is written."""


@dataclass(frozen=True)
class Answer:
    clause_id: str
    action: str
    text: str | None
    line: int


def parse_answers(text: str) -> tuple[dict[str, Answer], str | None]:
    """(answers by clause id, approved-on date or None). Refuses a line it
    cannot read and a clause answered twice."""
    answers: dict[str, Answer] = {}
    date: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ANSWER_RE.match(line)
        if not (match and match.group("action") == "edit"):
            line = line.split("#", 1)[0].strip()  # a comment ends any line but an edit's own wording
        dated = DATE_LINE_RE.match(line)
        if dated:
            if date is not None:
                raise ConfirmRefused(f"answers line {number}: approved-on given twice")
            date = dated.group("date")
            continue
        match = ANSWER_RE.match(line)
        if not match:
            raise ConfirmRefused(f"answers line {number}: not '<clause-id>: accept|edit: <text>|drop|forbid': {raw!r}")
        clause_id, action, edit_text = match.group("id"), match.group("action"), match.group("text")
        if action == "edit" and not (edit_text and edit_text.strip()):
            raise ConfirmRefused(f"answers line {number}: 'edit' needs the owner's wording after 'edit:'")
        if action != "edit" and edit_text:
            raise ConfirmRefused(f"answers line {number}: only 'edit' takes text")
        if clause_id in answers:
            raise ConfirmRefused(f"answers line {number}: {clause_id} answered twice (first on line {answers[clause_id].line})")
        answers[clause_id] = Answer(clause_id, action, edit_text.strip() if edit_text else None, number)
    return answers, date


def _draft_clauses(data: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    """(section, clause) for every clause the draft holds, in order."""
    found: list[tuple[str, dict[str, object]]] = []
    intent = data.get("intent")
    if isinstance(intent, dict):
        found.append(("intent", intent))
    invariants = data.get("invariants")
    if isinstance(invariants, dict):
        for kind in contracts.INVARIANT_KINDS:
            for clause in invariants.get(kind) or []:
                if isinstance(clause, dict):
                    found.append((f"invariants.{kind}", clause))
    for section in contracts.CLAUSE_SECTIONS:
        entries = data.get(section)
        for clause in entries if isinstance(entries, list) else []:
            if isinstance(clause, dict):
                found.append((section, clause))
    return found


def confirm(draft_text: str, answers_text: str | None, today: _dt.date | None = None) -> str:
    """Apply the owner's answers to a draft; return the confirmed CHARTER.md.
    Raises `ConfirmRefused`."""
    if answers_text is None:
        raise ConfirmRefused("no answers file: a charter is the owner's answers, and this tool never approves by itself")
    try:
        data, body = parse_contract_block(draft_text)
    except FrontmatterError as exc:
        raise ConfirmRefused(f"the draft does not parse: {exc}") from None
    answers, date = parse_answers(answers_text)
    stamp = date or (today or _dt.datetime.now(_dt.UTC).date()).isoformat()

    clauses = _draft_clauses(data)
    ids = [str(c.get("id")) for _, c in clauses]
    unknown = sorted(set(answers) - set(ids))
    if unknown:
        raise ConfirmRefused(f"the answers name clause(s) the draft does not hold: {', '.join(unknown)}")
    missing = [i for i in ids if i not in answers]
    if missing:
        raise ConfirmRefused(f"unanswered clause(s), never defaulted: {', '.join(missing)}")

    always: list[dict[str, object]] = []
    never: list[dict[str, object]] = []
    for section, clause in clauses:
        answer = answers[str(clause.get("id"))]
        if answer.action == "drop":
            if section == "intent":
                raise ConfirmRefused(f"{answer.clause_id}: the intent cannot be dropped (a contract requires one); edit it")
            continue
        kept = {k: v for k, v in clause.items() if k not in ("draft", "approved")}
        if answer.action == "edit":
            kept["what"] = answer.text
        if answer.action == "forbid":
            if section == "intent":
                raise ConfirmRefused(f"{answer.clause_id}: the intent cannot be forbidden; edit it")
            kept["what"] = f"Never: {kept.get('what')}"
            kept["column"] = "forbidden-by-owner"
            never.append(kept)
            continue
        if section in APPROVAL_SECTIONS:
            kept["approved"] = stamp
        if section == "intent":
            data["intent"] = kept
        elif section == "invariants.never":
            never.append(kept)
        elif section == "invariants.always":
            always.append(kept)
    data["invariants"] = {"always": always, "never": never}
    return "---\n" + dump(data) + "---\n\n" + _confirmed_body(body, stamp)


def _confirmed_body(body: str, stamp: str) -> str:
    note = (f"**Confirmed by the owner on {stamp}** with `skillc charter confirm`. Clauses carry no tests yet, "
            "so `skillc contracts` reports them unbacked until round 3 writes them.\n\n")
    return note + body.replace("**Draft ready for owner confirmation.**", "**Was a draft.**", 1)


def confirm_file(draft: Path, answers: Path | None, out: Path, today: _dt.date | None = None) -> str:
    """`charter confirm` on files. Never overwrites `out`."""
    if out.exists() or out.is_symlink():
        raise ConfirmRefused(f"{out} exists; confirm never overwrites a charter")
    answers_text = answers.read_text(encoding="utf-8") if answers is not None else None
    text = confirm(draft.read_text(encoding="utf-8"), answers_text, today)
    out.write_text(text, encoding="utf-8")
    return text
