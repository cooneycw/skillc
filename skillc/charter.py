"""Skill-gauntlet round 1 (#726, PR A): draft a skill's charter from evidence.

`skillc charter draft <skill>` reads what a skill SAYS (its SKILL.md, or a
command document) and what it has been SEEN to do (its `skill-usage` records,
#719), and proposes a `CHARTER.md` in #720's format. It sorts every candidate
duty into #718's three columns:

| column | meaning |
|---|---|
| `observed-and-stated` | the text states it and a usage record shows it |
| `stated-not-observed` | the text states it and complete-coverage records never show it |
| `unknown` | the text states it, but nothing could have shown it either way |
| `observed-not-stated` | a usage record shows it and the text never states it |

**A draft is evidence, never a ruling.** Every clause carries `draft: true`,
its evidence, and no `approved` date. Only `charter confirm`
(`skillc/charter_confirm.py`) turns a draft into a charter, and only from the
owner's own answers.

**"Never observed" keeps its honesty.** A stated duty with no matching
observation reads `unknown`, never `stated-not-observed`, unless at least one
usage record FOR THIS SKILL was written under `complete` coverage. So no log,
an empty log, an unreadable log, and a log whose only records for this skill
are `partial` or `unsupported` all read `unknown`. An empty log is not evidence
of non-use; the hook may simply not be installed (Nit Store #20, hook health).

**What this module is crude about, deliberately.** It makes no model call (the
orchestrator's ruling on #726: product model calls are "sized, not run" until
#747 and #718 decision 4). So:

- a *stated duty* is a line of the skill's text containing an imperative
  keyword (`MUST`, `ALWAYS`, `NEVER`, `MUST NOT`). Duties stated in plain prose
  are missed, so the stated column undercounts;
- an *observation* is a usage record's `stop_reason` token, the only field
  of #719's schema that says what a run did. A token matches a stated line
  when every word of the token appears in the line (`approval-gate` matches
  "stop at the approval gate"). That is the `TokenMatcher`; a model matcher
  can replace it behind the same `Matcher` protocol.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from . import contracts, usage
from .spec import FrontmatterError, parse_frontmatter

#: The four columns, in the order the report prints them.
OBSERVED_AND_STATED = "observed-and-stated"
STATED_NOT_OBSERVED = "stated-not-observed"
UNKNOWN_COLUMN = "unknown"
OBSERVED_NOT_STATED = "observed-not-stated"
COLUMNS = (OBSERVED_AND_STATED, STATED_NOT_OBSERVED, UNKNOWN_COLUMN, OBSERVED_NOT_STATED)

#: The one coverage value that can make an absence count as "never observed".
COMPLETE = "complete"

#: A quote longer than this is cut (orchestrator, #726 gate): long copied
#: passages would trip `skillc inspect`'s copied-passage rule on the report.
MAX_QUOTE_WORDS = 40

#: How many candidates of each kind become draft clauses; the rest are listed
#: in the body. The issue asks for 2-4 must-always outcomes; the owner chooses.
DEFAULT_MAX_ALWAYS = 4
DEFAULT_MAX_NEVER = 6

#: The source #718 build step 4 will add; until then it is reported missing.
REPOSITORY_SOURCE = "repository evidence (GitHub ingestion, #718 build step 4)"

NEVER_RE = re.compile(r"\b(?:must\s+never|must\s+not|never)\b", re.IGNORECASE)
ALWAYS_RE = re.compile(r"\b(?:must|always)\b", re.IGNORECASE)
UPPER_KEYWORD_RE = re.compile(r"\b(?:MUST|ALWAYS|NEVER)\b")
FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
WORD_RE = re.compile(r"[a-z0-9]+")
SLUG_RE = re.compile(r"[^a-z0-9]+")


class NothingToDraft(ValueError):
    """No source yielded anything: no description, no stated duty and no usage
    record for the skill. Never answered with an empty charter."""


@dataclass(frozen=True)
class Candidate:
    """One stated duty: a line of the skill's text with an imperative keyword."""

    kind: str  # "always" | "never"
    text: str  # the quote, at most MAX_QUOTE_WORDS words
    cite: str  # "<file>:<line>"
    emphasis: bool  # the keyword is written in capitals


@dataclass(frozen=True)
class Observation:
    """One thing usage records show the skill doing: a stop_reason token, with
    how many end records carried it."""

    token: str
    count: int


@dataclass(frozen=True)
class Evidence:
    """What the usage logs say about ONE skill."""

    logs: int  # usage logs read
    unreadable: tuple[str, ...]  # logs that did not parse, by path
    records: int  # well-formed records for this skill
    coverage: Counter[str]  # coverage value -> records
    outcomes: Counter[str]
    observations: tuple[Observation, ...]

    @property
    def can_show_absence(self) -> bool:
        """Only a complete-coverage record for this skill lets "the records
        never show it" mean anything."""
        return self.coverage.get(COMPLETE, 0) > 0

    def why_unknown(self) -> str:
        if self.logs == 0:
            return "no usage log"
        if self.unreadable and self.records == 0:
            return "the usage log could not be read"
        if self.records == 0:
            return "no usage record for this skill (an empty log is not evidence of non-use)"
        seen = ", ".join(f"{k} x{v}" for k, v in sorted(self.coverage.items()))
        return f"no complete-coverage record for this skill (coverage seen: {seen})"


class Matcher(Protocol):
    """Decides whether an observation shows a stated duty. The deterministic
    `TokenMatcher` is the only implementation in this PR; a model matcher is
    sized, not run (#726)."""

    def matches(self, candidate: Candidate, observation: Observation) -> bool: ...


class TokenMatcher:
    """Every word of the stop_reason token appears as a word in the line."""

    def matches(self, candidate: Candidate, observation: Observation) -> bool:
        words = set(WORD_RE.findall(candidate.text.lower()))
        token_words = WORD_RE.findall(observation.token.lower())
        return bool(token_words) and all(w in words for w in token_words)


@dataclass(frozen=True)
class Placed:
    """A candidate or an observation, placed in one column."""

    clause_id: str
    kind: str  # "intent" | "always" | "never"
    column: str
    text: str
    evidence: tuple[str, ...]


@dataclass
class Draft:
    name: str
    skill_file: Path
    job: str
    job_cite: str
    placed: list[Placed]
    further: list[Candidate]
    evidence: Evidence
    sources: list[tuple[str, str]]  # (source, what it gave or why it is missing)
    git_summary: str
    subject: str | None = None
    warnings: list[str] = field(default_factory=list)

    def data(self) -> dict[str, object]:
        """The YAML block, as data; `render()` emits it."""
        always = [_clause(p) for p in self.placed if p.kind == "always"]
        never = [_clause(p) for p in self.placed if p.kind == "never"]
        intent: dict[str, object] = {"id": f"{self.name}.intent", "draft": True, "what": self.job or "UNKNOWN"}
        if self.job_cite:
            intent["evidence"] = [self.job_cite]
        head: dict[str, object] = {"contract": self.name}
        if self.subject:
            head["subject"] = self.subject
        return {
            **head,
            "version": 1,
            "intent": intent,
            "purpose": self.job or "UNKNOWN - the skill states no description; the owner writes it",
            "owner": contracts.OWNER_READER,
            "invariants": {"always": always, "never": never},
        }

    def render(self) -> str:
        return "---\n" + dump(self.data()) + "---\n\n" + self._body()

    def _body(self) -> str:
        lines = [
            f"# Draft charter: {self.name}",
            "",
            "**Draft ready for owner confirmation.** Nothing here is approved: every clause is "
            "`draft: true` with no `approved` date, and only the owner's answers "
            "(`skillc charter confirm`) make it a charter.",
            "",
            f"Drafted from `{self.skill_file.name}` with no model call (#726: product model calls are sized, not run).",
            "",
            "## Sources",
            "",
        ]
        lines += [f"- **{source}:** {what}" for source, what in self.sources]
        lines += ["", "## The three columns", "", "| Column | Clause | Duty | Evidence |", "|---|---|---|---|"]
        for column in COLUMNS:
            for p in (p for p in self.placed if p.column == column):
                lines.append(f"| {column} | `{p.clause_id}` | {_cell(p.text)} | {_cell('; '.join(p.evidence))} |")
        if not self.placed:
            lines.append("| - | - | no stated or observed duty | - |")
        if self.further:
            lines += ["", f"## Further candidates, not drafted ({len(self.further)})", ""]
            lines += [f"- {c.kind} `{c.cite}`: {_cell(c.text)}" for c in self.further]
        lines += [
            "",
            "## What this draft does not show",
            "",
            "- A duty stated in plain prose, without MUST/ALWAYS/NEVER, is not a candidate. The stated "
            "column undercounts.",
            "- A clause here names no test, so `skillc contracts` reports it unbacked (`clause-backed`). "
            "That is expected for a draft: round 3 writes the tests.",
            "- `unknown` means nothing could have shown the duty either way. It is never a finding against "
            "the skill.",
        ]
        if self.warnings:
            lines += ["", "## Warnings", ""] + [f"- {w}" for w in self.warnings]
        return "\n".join(lines) + "\n"


def _clause(p: Placed) -> dict[str, object]:
    return {"id": p.clause_id, "draft": True, "column": p.column, "what": p.text, "evidence": list(p.evidence)}


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


# ---------------------------------------------------------------- the emitter


def _scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = " ".join(str(value).split())  # one line; the parser reads no escapes but \" and \\
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump(data: Mapping[str, object], indent: int = 0) -> str:
    """Emit `data` in the contract-block YAML subset (docs/specs/contracts.md):
    mappings, lists of mappings, block lists of scalars, double-quoted strings.
    `parse_contract_block(dump(x))` reads back `x` - tests/test_charter.py
    pins the round trip, so a value this cannot emit is refused, not mangled."""
    pad = " " * indent
    out: list[str] = []
    for key, value in data.items():
        if isinstance(value, Mapping):
            out.append(f"{pad}{key}:\n" + dump(value, indent + 2))
        elif isinstance(value, list):
            if not value:
                out.append(f"{pad}{key}: []\n")
                continue
            out.append(f"{pad}{key}:\n")
            for item in value:
                if isinstance(item, Mapping):
                    body = dump(item, indent + 4)
                    out.append(f"{pad}  - " + body[indent + 4:])
                elif isinstance(item, (str, int)):
                    out.append(f"{pad}  - {_scalar(item)}\n")
                else:
                    raise TypeError(f"{key}: cannot emit a list item of type {type(item).__name__}")
        elif isinstance(value, (str, int, bool)):
            out.append(f"{pad}{key}: {_scalar(value)}\n")
        else:
            raise TypeError(f"{key}: cannot emit a value of type {type(value).__name__}")
    return "".join(out)


# ---------------------------------------------------------------- reading the sources


def _quote(text: str) -> str:
    words = BULLET_RE.sub("", text).strip().split()
    if len(words) > MAX_QUOTE_WORDS:
        return " ".join(words[:MAX_QUOTE_WORDS]) + " ..."
    return " ".join(words)


SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*`\"(\[])")


def _blocks(text: str, first_line: int) -> list[list[tuple[int, str]]]:
    """Prose blocks outside fenced code: wrapped lines joined back into the
    paragraph or list item they belong to, each line keeping its number.
    Headings, tables, quotes and HTML comments are skipped."""
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    fenced = False
    in_comment = False
    for offset, raw in enumerate(text.splitlines()):
        number = first_line + offset
        stripped = raw.strip()
        if in_comment or (not fenced and stripped.startswith("<!--")):
            # An HTML comment is never a stated duty, however many lines it runs.
            in_comment = "-->" not in stripped
            if current:
                blocks.append(current)
            current = []
            continue
        if FENCE_RE.match(raw):
            fenced = not fenced
            current = []
            continue
        if fenced or not stripped or stripped.startswith(("#", "|", ">")):
            if current:
                blocks.append(current)
            current = []
            continue
        if BULLET_RE.match(raw) and current:
            blocks.append(current)
            current = []
        current.append((number, BULLET_RE.sub("", stripped)))
    if current:
        blocks.append(current)
    return blocks


def _sentences(block: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """(line the sentence starts on, sentence)."""
    joined, starts = "", []
    for number, line in block:
        starts.append((len(joined), number))
        joined += line + " "
    out = []
    position = 0
    for sentence in SENTENCE_END_RE.split(joined.strip()):
        at = joined.find(sentence, position)
        position = at + len(sentence)
        line = max(n for o, n in starts if o <= max(at, 0))
        out.append((line, sentence.strip()))
    return out


def stated_duties(text: str, file_label: str, first_line: int = 1) -> list[Candidate]:
    """Every sentence with an imperative keyword, outside fenced code. `NEVER`
    and `MUST NOT` sentences are must-never; other `MUST`/`ALWAYS` sentences
    are must-always. Each is quoted from the line it starts on."""
    found: list[Candidate] = []
    for block in _blocks(text, first_line):
        for number, sentence in _sentences(block):
            kind = "never" if NEVER_RE.search(sentence) else "always" if ALWAYS_RE.search(sentence) else None
            if kind is not None:
                found.append(Candidate(kind, _quote(sentence), f"{file_label}:{number}",
                                       bool(UPPER_KEYWORD_RE.search(sentence))))
    return found


def first_paragraph(text: str, first_line: int) -> tuple[str, int] | None:
    """The opening prose paragraph (after any title): the job's fallback when
    there is no frontmatter description."""
    blocks = _blocks(text, first_line)
    if not blocks:
        return None
    sentences = _sentences(blocks[0])
    return (_quote(sentences[0][1]), sentences[0][0]) if sentences else None


def read_skill(skill_file: Path) -> tuple[dict[str, object], str, int, list[str]]:
    """(frontmatter, body, body's first line number, warnings)."""
    text = skill_file.read_text(encoding="utf-8")
    try:
        front, body = parse_frontmatter(text)
    except FrontmatterError as exc:
        return {}, text, 1, [f"frontmatter not read ({exc}); the whole file was read as text"]
    first = text.count("\n", 0, len(text) - len(body)) + 1 if body and text.endswith(body) else 1
    return front, body, first, []


def skill_names(skill_file: Path, front: Mapping[str, object], aliases: Iterable[str]) -> set[str]:
    """Every name a usage record may carry for this skill."""
    names = {a for a in aliases if a}
    if isinstance(front.get("name"), str):
        names.add(str(front["name"]))
    names.add(primary_name(skill_file))
    command = command_name(skill_file)
    if command:
        names.add(command)
    return names


def command_name(skill_file: Path) -> str | None:
    """`commands/<ns>/<cmd>.md` is invoked as `<ns>:<cmd>`; usage records carry that."""
    parts = skill_file.parts
    if skill_file.name != "SKILL.md" and len(parts) >= 3 and parts[-3] == "commands":
        return f"{parts[-2]}:{skill_file.stem}"
    return None


def primary_name(skill_file: Path) -> str:
    """A skill is named by its directory; a command `<ns>:<cmd>` by `<ns>-<cmd>`."""
    if skill_file.name == "SKILL.md":
        return skill_file.parent.name
    command = command_name(skill_file)
    return command.replace(":", "-") if command else skill_file.stem


def read_evidence(logs: Sequence[usage.UsageLog], names: set[str]) -> Evidence:
    coverage: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    tokens: Counter[str] = Counter()
    records = 0
    unreadable: list[str] = []
    for log in logs:
        if log.parse_error is not None:
            unreadable.append(str(log.path))
            continue
        for entry in log.entries:
            data = entry.data
            if data.get("kind") != usage.SKILL_USAGE or data.get("version") not in usage.USAGE_VERSIONS:
                continue
            if data.get("skill") not in names:
                continue
            records += 1
            coverage[str(data.get("coverage"))] += 1
            if data.get("event") == "end":
                outcomes[str(data.get("outcome"))] += 1
                reason = data.get("stop_reason")
                if isinstance(reason, str) and usage.STOP_REASON_RE.fullmatch(reason):
                    tokens[reason] += 1
    observations = tuple(Observation(t, n) for t, n in sorted(tokens.items()))
    return Evidence(len(logs), tuple(unreadable), records, coverage, outcomes, observations)


def git_summary(skill_file: Path) -> str | None:
    """One line on the file's history, or None when git cannot say."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(skill_file.parent), "log", "--format=%h %as", "--", skill_file.name],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    commits = proc.stdout.split("\n")
    commits = [c for c in commits if c.strip()]
    if not commits:
        return "no commit touches the file (untracked or new)"
    newest, oldest = commits[0], commits[-1]
    return f"{len(commits)} commit(s), newest {newest}, oldest {oldest}"


def _slug(text: str) -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")[:63].strip("-")
    return slug or "skill"


# ---------------------------------------------------------------- the draft


def draft(
    skill: Path,
    usage_paths: Sequence[Path] = (),
    *,
    aliases: Iterable[str] = (),
    matcher: Matcher | None = None,
    max_always: int = DEFAULT_MAX_ALWAYS,
    max_never: int = DEFAULT_MAX_NEVER,
    subject: str | None = None,
) -> Draft:
    """Draft a charter for the skill at `skill` (a skill directory holding
    SKILL.md, or a Markdown file). `usage_paths` are usage logs, or
    directories searched for them. Raises `NothingToDraft`."""
    skill_file = skill / "SKILL.md" if skill.is_dir() else skill
    if not skill_file.is_file():
        raise FileNotFoundError(f"no skill text at {skill_file}")
    front, body, first, warnings = read_skill(skill_file)
    names = skill_names(skill_file, front, aliases)
    name = _slug(str(front.get("name") or primary_name(skill_file)))
    description = front.get("description")
    job = _quote(description) if isinstance(description, str) and description.strip() else ""
    job_cite = f"{skill_file.name}: frontmatter description" if job else ""
    if not job:
        opening = first_paragraph(body, first)
        if opening:
            job, line = opening
            job_cite = f"{skill_file.name}:{line} (opening paragraph; no frontmatter description)"

    logs: list[usage.UsageLog] = []
    for path in usage_paths:
        logs.extend(usage.discover_logs(path))
    evidence = read_evidence(logs, names)
    candidates = stated_duties(body, skill_file.name, first)

    if not job and not candidates and evidence.records == 0:
        raise NothingToDraft(
            f"nothing to draft from: {skill_file} states no description and no MUST/ALWAYS/NEVER duty, "
            f"and no usage record names it ({', '.join(sorted(names))})"
        )

    chosen, further = _choose(candidates, max_always, max_never)
    placed = place(name, chosen, evidence, matcher or TokenMatcher())

    git = git_summary(skill_file)
    sources = [
        ("skill text", f"`{skill_file.name}`: {'a description and ' if job else 'no description; '}"
                       f"{len(candidates)} stated duty candidate(s)"),
        ("git history", git or "missing: git could not read the file's history"),
        ("usage records", f"{evidence.records} record(s) for {', '.join(sorted(names))} in {evidence.logs} log(s)"
                          + (f"; coverage {dict(sorted(evidence.coverage.items()))}" if evidence.records else "")
                          + ("" if evidence.can_show_absence else f" - absences read UNKNOWN: {evidence.why_unknown()}")),
        (REPOSITORY_SOURCE, "missing: not built yet, so nothing here comes from issues or PRs"),
    ]
    if evidence.unreadable:
        warnings.append(f"unreadable usage log(s), not counted: {', '.join(evidence.unreadable)}")
    return Draft(name, skill_file, job, job_cite, placed, further, evidence, sources, git or "",
                 subject, warnings)


def _choose(candidates: list[Candidate], max_always: int, max_never: int) -> tuple[list[Candidate], list[Candidate]]:
    """Capitalised keywords first, then document order; deterministic."""
    chosen: list[Candidate] = []
    for kind, limit in (("always", max_always), ("never", max_never)):
        pool = [c for c in candidates if c.kind == kind]
        ranked = sorted(pool, key=lambda c: (not c.emphasis, pool.index(c)))
        chosen.extend(ranked[:limit])
    rest = [c for c in candidates if c not in chosen]
    return chosen, rest


def place(name: str, chosen: Sequence[Candidate], evidence: Evidence, matcher: Matcher) -> list[Placed]:
    placed: list[Placed] = []
    used: set[str] = set()
    counters = {"always": 0, "never": 0}
    for c in chosen:
        counters[c.kind] += 1
        hits = [o for o in evidence.observations if matcher.matches(c, o)]
        used.update(o.token for o in hits)
        if hits:
            column = OBSERVED_AND_STATED
            proof = [f"stop_reason {o.token} x{o.count}" for o in hits]
        elif evidence.can_show_absence:
            column = STATED_NOT_OBSERVED
            proof = [f"{evidence.coverage[COMPLETE]} complete-coverage record(s), none showing it"]
        else:
            column = UNKNOWN_COLUMN
            proof = [f"UNKNOWN: {evidence.why_unknown()}"]
        placed.append(Placed(f"{name}.{c.kind}-{counters[c.kind]}", c.kind, column, c.text, (c.cite, *proof)))
    taken = {p.clause_id for p in placed}
    for o in evidence.observations:
        if o.token in used:
            continue
        clause_id, n = f"{name}.observed-{_slug(o.token)}", 1
        while clause_id in taken:  # two tokens can slug alike (a.b, a-b)
            n += 1
            clause_id = f"{name}.observed-{_slug(o.token)}-{n}"
        taken.add(clause_id)
        placed.append(Placed(
            clause_id, "always", OBSERVED_NOT_STATED,
            f"observed, never stated: runs end with stop_reason {o.token}",
            (f"usage records: stop_reason {o.token} x{o.count}", "confirm it, or forbid it"),
        ))
    return placed
