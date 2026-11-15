"""Skill-gauntlet round 1 (#726, PR B): the overlap view across a collection.

`skillc charter overlap <collection>` compares every duty in every charter
against every duty in every OTHER charter **by meaning**, and proposes:

| kind | meaning | the owner's choice |
|---|---|---|
| `shared` | two charters both claim the same duty | pick one owner; the other points at it |
| `shadowed` | a skill is only *observed* doing a duty another charter claims | the strongest candidate for removing text |
| `orphan` | a skill is observed doing something no charter states | add a charter line, or forbid it |

**Every overlap is a proposal, never a finding against a skill.** Some
duplication protects a boundary or helps a skill be found (Codex's review of
#718). Nothing is removed or rewritten, and the command never fails on an
overlap.

**The comparison is a model call, and none is made here.** Product model calls
are sized, not run, until the owner sets the gauntlet budget (#726 gate, #747).
So this module is the machinery behind a `DutyComparator` seam, in the
`skillc/judge.py` pattern:

- `FakeComparator` returns scripted verdicts; the tests use it.
- `RecordedComparator` reads a verdicts file (`--verdicts`), labelled with its
  source, so a later local-model step can propose verdicts without this
  module calling anything.
- With no comparator, nothing was compared: every pair is `UNKNOWN` and the
  command exits 3, "not examined". Never 0: an unexamined collection is not an
  overlap-free one.

**Replicates.** A pair is judged `replicates` times. Only unanimous `same`
or unanimous `different` is a verdict; any disagreement, or any `UNKNOWN`
answer, makes the pair `UNKNOWN`. An orphan is declared only when every pair
involving the observed duty was judged `different`. A single `UNKNOWN` leaves
its orphan status `UNKNOWN` too.

Exact duty-id duplicates are #720's `duty-single-owner`; pairs sharing a clause
id are skipped here, never re-reported.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Protocol

from . import contracts

SAME, DIFFERENT, UNKNOWN = "same", "different", "UNKNOWN"
VERDICTS = (SAME, DIFFERENT, UNKNOWN)
SHARED, SHADOWED, ORPHAN = "shared", "shadowed", "orphan"

#: The column `charter draft` gives a duty a usage record shows but the text
#: never states (skillc/charter.py). Only such a duty can shadow or be an orphan.
OBSERVED_ONLY = "observed-not-stated"

EXIT_REPORTED, EXIT_USAGE, EXIT_NOT_EXAMINED = 0, 2, 3

VERDICT_LINE_RE = re.compile(
    r"^(?P<a>[A-Za-z0-9][A-Za-z0-9._-]*)\s+(?P<b>[A-Za-z0-9][A-Za-z0-9._-]*)\s*:\s*(?P<v>same|different|UNKNOWN)\s*$"
)


@dataclass(frozen=True)
class Duty:
    contract: str
    clause_id: str
    section: str
    text: str
    observed_only: bool  # the charter only observed it (column observed-not-stated)
    path: Path


class DutyComparator(Protocol):
    """Judges whether two duties are the same duty, by meaning."""

    source: str  # who or what produced the verdicts, printed in the report

    def compare(self, a: Duty, b: Duty) -> str: ...


class FakeComparator:
    """Scripted verdicts for tests: `{(id_a, id_b): [v1, v2, ...]}`, one per
    replicate, either order; an unscripted pair answers `default`."""

    source = "fake (tests only)"

    def __init__(self, script: Mapping[tuple[str, str], Sequence[str]], default: str = DIFFERENT) -> None:
        self._script = {frozenset(k): list(v) for k, v in script.items()}
        self._calls: dict[frozenset[str], int] = {}
        self._default = default

    def compare(self, a: Duty, b: Duty) -> str:
        key = frozenset((a.clause_id, b.clause_id))
        answers = self._script.get(key)
        if not answers:
            return self._default
        n = self._calls.get(key, 0)
        self._calls[key] = n + 1
        return answers[n % len(answers)]


class VerdictsError(ValueError):
    """A verdicts file this module cannot read."""


class RecordedComparator:
    """Verdicts read from a file, one replicate per line:

        flow-eli5.always-1 flow-auto.always-3: same

    A pair with fewer recorded lines than the run's replicates answers
    UNKNOWN for the missing ones; an unrecorded pair is UNKNOWN throughout."""

    def __init__(self, text: str, source: str) -> None:
        self.source = source
        self._answers: dict[frozenset[str], list[str]] = {}
        self._calls: dict[frozenset[str], int] = {}
        for number, raw in enumerate(text.splitlines(), start=1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            match = VERDICT_LINE_RE.match(line)
            if not match:
                raise VerdictsError(f"verdicts line {number}: not '<clause-id> <clause-id>: same|different|UNKNOWN'")
            if match.group("a") == match.group("b"):
                raise VerdictsError(f"verdicts line {number}: a duty is not compared with itself")
            self._answers.setdefault(frozenset((match.group("a"), match.group("b"))), []).append(match.group("v"))

    def compare(self, a: Duty, b: Duty) -> str:
        key = frozenset((a.clause_id, b.clause_id))
        answers = self._answers.get(key, [])
        n = self._calls.get(key, 0)
        self._calls[key] = n + 1
        return answers[n] if n < len(answers) else UNKNOWN


@dataclass(frozen=True)
class PairVerdict:
    a: Duty
    b: Duty
    answers: tuple[str, ...]

    @property
    def verdict(self) -> str:
        if self.answers and all(v == SAME for v in self.answers):
            return SAME
        if self.answers and all(v == DIFFERENT for v in self.answers):
            return DIFFERENT
        return UNKNOWN


@dataclass(frozen=True)
class Overlap:
    kind: str
    duties: tuple[Duty, ...]
    answers: tuple[str, ...]


@dataclass
class Report:
    root: Path
    duties: list[Duty]
    pairs: list[PairVerdict]
    overlaps: list[Overlap]
    unknown_pairs: list[PairVerdict]
    unknown_orphans: list[Duty]
    skipped_same_id: list[tuple[Duty, Duty]]
    source: str | None
    replicates: int
    notes: list[str] = field(default_factory=list)

    @property
    def examined(self) -> bool:
        return self.source is not None and bool(self.pairs)

    def counts(self) -> dict[str, int]:
        found = {kind: sum(o.kind == kind for o in self.overlaps) for kind in (SHARED, SHADOWED, ORPHAN)}
        found["unknown pairs"] = len(self.unknown_pairs)
        found["unknown orphans"] = len(self.unknown_orphans)
        return found


def duties(collection: contracts.Collection) -> list[Duty]:
    """Every duty clause with text, from every contract whose block parsed."""
    found: list[Duty] = []
    for contract in collection.contracts:
        if contract.parse_error is not None or not contract.name:
            continue
        sections: list[tuple[str, object]] = [("provides", contract.data.get("provides"))]
        invariants = contract.data.get("invariants")
        if isinstance(invariants, dict):
            sections.append(("invariants.always", invariants.get("always")))
        for section, entries in sections:
            for clause in entries if isinstance(entries, list) else []:
                if not isinstance(clause, dict) or not isinstance(clause.get("id"), str):
                    continue
                text = clause.get("what")
                if not (isinstance(text, str) and text.strip()):
                    continue
                found.append(Duty(contract.name, str(clause["id"]), section, " ".join(text.split()),
                                  clause.get("column") == OBSERVED_ONLY, contract.path))
    return found


def compare(
    collection: contracts.Collection, comparator: DutyComparator | None, replicates: int = 3,
) -> Report:
    """The overlap report. With `comparator=None` nothing is compared."""
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
        raise ValueError(f"replicates must be a positive integer, not {replicates!r}")
    all_duties = duties(collection)
    report = Report(collection.root, all_duties, [], [], [], [], [], comparator.source if comparator else None,
                    replicates)
    candidates: list[tuple[Duty, Duty]] = []
    for a, b in combinations(all_duties, 2):
        if a.contract == b.contract:
            continue
        if a.clause_id == b.clause_id:
            report.skipped_same_id.append((a, b))  # duty-single-owner's case, never re-reported
            continue
        candidates.append((a, b))
    if comparator is None:
        report.notes.append("overlap not examined: no comparator configured (model calls are sized, not run; #747)")
        return report
    for a, b in candidates:
        pair = PairVerdict(a, b, tuple(_answer(comparator, a, b) for _ in range(replicates)))
        report.pairs.append(pair)
        if pair.verdict == UNKNOWN:
            report.unknown_pairs.append(pair)
        elif pair.verdict == SAME:
            report.overlaps.append(Overlap(_kind(a, b), (a, b), pair.answers))
    for duty in (d for d in all_duties if d.observed_only):
        mine = [p for p in report.pairs if duty in (p.a, p.b)]
        if any(p.verdict == SAME for p in mine):
            continue
        if mine and all(p.verdict == DIFFERENT for p in mine):
            report.overlaps.append(Overlap(ORPHAN, (duty,), ()))
        else:
            report.unknown_orphans.append(duty)  # no other duty, or an UNKNOWN pair: cannot say
    return report


def _answer(comparator: DutyComparator, a: Duty, b: Duty) -> str:
    try:
        verdict = comparator.compare(a, b)
    except Exception:  # noqa: BLE001 - a comparator that fails answered nothing
        return UNKNOWN
    return verdict if verdict in VERDICTS else UNKNOWN


def _kind(a: Duty, b: Duty) -> str:
    """Shadowed when exactly one side is only observed doing what the other
    claims; shared otherwise (both claim it, or both are only seen doing it)."""
    return SHADOWED if a.observed_only != b.observed_only else SHARED


# ---------------------------------------------------------------- the report


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _node(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def render(report: Report) -> str:
    counts = report.counts()
    lines = [
        "# Overlap view (skill-gauntlet round 1, #726)",
        "",
        ("Every overlap here is a **proposal for the owner**, never a finding against a skill: some "
         "duplication protects a boundary or helps a skill be found."),
        "",
        f"- Duties: {len(report.duties)} in {len({d.contract for d in report.duties})} charter(s)",
        f"- Comparator: {report.source or 'none - not examined'}; {report.replicates} replicate(s) per pair",
        (f"- Pairs judged: {len(report.pairs)}; skipped as the same clause id (see duty-single-owner): "
         f"{len(report.skipped_same_id)}"),
        "- Counts: " + (", ".join(f"{k} {v}" for k, v in counts.items()) if report.examined
                        else "none - no pair was judged, so a zero here would claim a comparison nobody made"),
    ]
    lines += [f"- {n}" for n in report.notes]
    if report.overlaps:
        lines += ["", "```mermaid", "graph LR"]
        for o in report.overlaps:
            if o.kind == ORPHAN:
                lines.append(f"  {_node(o.duties[0].contract)} -. orphan: {o.duties[0].clause_id} .-> nobody")
            else:
                a, b = o.duties
                lines.append(f"  {_node(a.contract)} -- {o.kind} --- {_node(b.contract)}")
        lines.append("```")
    for kind in (SHARED, SHADOWED, ORPHAN):
        found = [o for o in report.overlaps if o.kind == kind]
        if not found:
            continue
        lines += ["", f"## {kind} ({len(found)})", "", "| Duty | Charter | Text | Replicates |", "|---|---|---|---|"]
        for o in found:
            for d in o.duties:
                lines.append(f"| `{d.clause_id}` | {d.contract} | {_cell(d.text)} | {', '.join(o.answers) or '-'} |")
    if report.unknown_pairs:
        lines += ["", f"## UNKNOWN pairs ({len(report.unknown_pairs)})", "",
                  "Replicates disagreed or a replicate could not answer; neither a verdict nor a pass.", ""]
        lines += [f"- `{p.a.clause_id}` vs `{p.b.clause_id}`: {', '.join(p.answers)}" for p in report.unknown_pairs]
    if report.unknown_orphans:
        lines += ["", f"## Observed duties whose orphan status is UNKNOWN ({len(report.unknown_orphans)})", ""]
        lines += [f"- `{d.clause_id}` ({d.contract})" for d in report.unknown_orphans]
    return "\n".join(lines) + "\n"


def load_verdicts(path: Path) -> RecordedComparator:
    return RecordedComparator(path.read_text(encoding="utf-8"), source=f"recorded verdicts: {path.name}")


def ids(found: Iterable[Overlap]) -> list[tuple[str, ...]]:
    """(kind, clause ids...) for each overlap, sorted; for tests and summaries."""
    return sorted((o.kind, *sorted(d.clause_id for d in o.duties)) for o in found)
