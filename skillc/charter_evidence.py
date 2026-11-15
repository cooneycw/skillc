"""`skillc charter evidence`: every piece of existing evidence of a skill's
charter, gathered BEFORE the owner is asked anything (#778).

`/charter-create` composes a charter with the owner. The owner's requirement
(#778, 2026-11-15) is that it starts from what already exists, never from a
blank page. This module gathers it, and `charter create` (PR B) turns the
owner's answers into the charter. The sources, in the order they are read:

1. **repository evidence**: discussions, issues and PRs, through the read-only
   `RepoReader` seam. Explicit `--ref`s come first; a name search runs only on
   `--search`. Only items under charter-shaped headings are taken (Job, Intent,
   Purpose, Must always, Must never, Authority), so prose is never turned into
   a charter. Every item is **observational**.
2. **existing charter**: a CHARTER.md or `charter draft` output, plus the
   git history of the charter file.
3. **skill text**: the SKILL.md description and MUST/NEVER sentences, and any
   `--doc` spec documents.
4. **usage records** (#719): what the skill was seen doing. Absences are UNKNOWN
   unless a complete-coverage record exists.
5. **existing tests**: test files in the collection that name the skill,
   offered as a clause's test before a new trap task is stubbed.

Every item is a SUGGESTION, never an answer: it carries a quote under 40 words
and the citation it came from, and the owner accepts, edits or drops it.

**Every source reports a status**: `examined`, `none found`, or
`not examined: <reason>`. A source that could not be read is never left out,
so an empty suggestion list can always be told apart from a failed read.
No model is called.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import charter, usage
from .repo_reader import Document, Ref, RepoReader, RepoReadError, parse_ref
from .spec import FrontmatterError, parse_contract_block

SCHEMA = 1

EXAMINED = "examined"
NONE_FOUND = "none found"
NOT_EXAMINED = "not examined"

REPOSITORY = "repository evidence"
EXISTING_CHARTER = "existing charter"
SKILL_TEXT = "skill text"
USAGE = "usage records"
TESTS = "existing tests"
#: Every source the evidence file reports, in order. Each one always gets at
#: least one status row.
SOURCES = (REPOSITORY, EXISTING_CHARTER, SKILL_TEXT, USAGE, TESTS)

#: Kinds of suggestion. Observational items show what someone wrote, never
#: that the skill behaves so (#718 fixed rules).
OBSERVATIONAL = "observational"
STATED = "stated"
OBSERVED = "observed"
TEST = "test"

#: Sections a suggestion can propose. `observed` is a usage token the owner
#: must place; `test` is an existing test with no section of its own.
SECTIONS = ("intent", "purpose", "always", "never", "authority", "provides", "requires", "failure",
            "observed", "test")

#: Charter-shaped labels: a heading or a bold label line, normalised. Nothing
#: outside these is ever taken from a discussion, issue or PR.
LABELS = {
    "job": "intent",
    "intent": "intent",
    "purpose": "purpose",
    "must always": "always",
    "always": "always",
    "must never": "never",
    "never": "never",
    "authority": "authority",
}

HEADING_RE = re.compile(r"^ {0,3}#{1,6}\s+(?P<label>.+?)\s*#*\s*$")
#: A line that IS a bold label: `**Must never**` alone, or `**Job:** text` /
#: `**Job**: text` with a colon. `**Never** assume ...` is emphasis in prose,
#: never a label (counter-model review).
BOLD_RE = re.compile(r"^ {0,3}(?:\*\*|__)(?P<label>[^*_]+?)(?:\*\*|__)(?P<after>.*)$")
ITEM_RE = re.compile(r"^(?P<indent> {0,3})(?:[-*+]|\d{1,9}[.)])\s+(?P<text>.*)$")

#: Test files are recognised by name; nothing larger than this is read.
TEST_NAME_RE = re.compile(r"^(?:test_.+\.py|.+_test\.py|.+\.test\.[a-z]+|.+\.bats)$")
TEST_MAX_BYTES = 1_000_000
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache",
                       ".pytest_cache", ".ruff_cache", ".skillc"})
TEST_LIMIT = 50


@dataclass(frozen=True)
class Suggestion:
    id: str
    section: str
    text: str  # a quote, at most charter.MAX_QUOTE_WORDS words
    cite: str  # a URL, or <file>:<line>
    kind: str
    source: str
    test: str = ""  # the clause's existing test path(s), comma-separated, when it has any


@dataclass(frozen=True)
class SourceStatus:
    source: str
    status: str  # examined | none found | not examined: <reason>
    detail: str = ""
    ref: str = ""


@dataclass
class EvidenceFile:
    skill: str
    skill_file: str
    sources: list[SourceStatus] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    schema: int = SCHEMA

    def to_data(self) -> dict[str, object]:
        return {"schema": self.schema, "skill": self.skill, "skill_file": self.skill_file,
                "sources": [asdict(s) for s in self.sources],
                "suggestions": [asdict(s) for s in self.suggestions]}

    def to_json(self) -> str:
        return json.dumps(self.to_data(), indent=2, sort_keys=False) + "\n"


# ---------------------------------------------------------------- the extractor


def _label(text: str) -> str | None:
    norm = re.sub(r"[`*_]", "", text).strip().rstrip(":").strip().lower()
    norm = re.sub(r"\s+", " ", norm)
    return LABELS.get(norm)


def _unfenced(text: str) -> Iterator[str | None]:
    """Each line, or None for a line inside fenced code (or a fence line).
    The CommonMark rule `charter draft` uses (#749): a fence opens on 3 or
    more of one character indented 0-3 spaces, and closes only on the same
    character, at least as long, followed by nothing but spaces or tabs."""
    fenced: str | None = None
    in_comment = False
    for raw in text.splitlines():
        if fenced is None:
            # HTML comments hide what they hold (counter-model review): a
            # commented-out "## Must never" is not evidence.
            raw, in_comment = charter._strip_comments(raw, in_comment)
        fence = charter.FENCE_RE.match(raw)
        if fenced is None:
            if fence and not (fence["run"][0] == "`" and "`" in fence["info"]):
                fenced = fence["run"]
                yield None
                continue
            yield raw
        else:
            if fence and fence["run"][0] == fenced[0] and len(fence["run"]) >= len(fenced) \
                    and not fence["info"].strip(" \t"):
                fenced = None
            yield None


def extract(body: str) -> list[tuple[str, str]]:
    """(section, text) for every item under a charter-shaped heading or bold
    label. A labelled section takes its list items; Job, Intent and Purpose
    also take text on the label's own line, or the first paragraph below it.
    Any other heading or bold label ends the section, and so does a paragraph
    after the section's list. Nothing else is ever taken."""
    found: list[tuple[str, str]] = []
    section: str | None = None
    item: list[str] = []
    paragraph: list[str] = []
    seen_item = False

    def flush_item() -> None:
        nonlocal item
        if section and item:
            found.append((section, " ".join(item)))
        item = []

    def flush_paragraph() -> None:
        nonlocal paragraph, seen_item
        if section in ("intent", "purpose") and paragraph and not seen_item:
            found.append((section, " ".join(paragraph)))
            seen_item = True  # only the FIRST paragraph is the intent
        paragraph = []

    for raw in _unfenced(body):
        if raw is None:
            flush_item()
            flush_paragraph()
            continue
        line = raw.rstrip()
        heading = HEADING_RE.match(line)
        bold = BOLD_RE.match(line) if not heading else None
        if bold and bold["after"].strip() and not (bold["label"].rstrip().endswith(":")
                                                   or bold["after"].lstrip().startswith(":")):
            bold = None  # bold words that open a sentence: emphasis, not a label
        if heading or bold:
            flush_item()
            flush_paragraph()
            label = heading["label"] if heading else bold["label"] if bold else ""
            section = _label(label)
            seen_item = False
            rest = bold["after"].strip().lstrip(":").strip() if bold else ""
            if section and rest:
                # `**Job:** take any skill ...` is the item itself.
                found.append((section, rest))
                seen_item = section in ("intent", "purpose")
            continue
        if section is None:
            continue
        if not line.strip():
            flush_item()
            flush_paragraph()
            continue
        listed = ITEM_RE.match(line)
        if listed:
            flush_item()
            flush_paragraph()
            item = [listed["text"].strip()]
            seen_item = True
            continue
        if item and line.startswith((" ", "\t")):
            item.append(line.strip())  # a wrapped list item
            continue
        if seen_item:
            flush_item()
            section = None  # a paragraph after the list ends the section
            continue
        paragraph.append(line.strip())
    flush_item()
    flush_paragraph()
    return [(s, t) for s, t in found if t.strip()]


# ---------------------------------------------------------------- gathering


@dataclass
class _Builder:
    out: EvidenceFile
    n: int = 0

    def add(self, section: str, text: str, cite: str, kind: str, source: str, test: str = "") -> None:
        quote = charter._quote(text)
        if not quote:
            return
        self.n += 1
        self.out.suggestions.append(Suggestion(f"e{self.n}", section, quote, cite, kind, source, test))

    def status(self, source: str, status: str, detail: str = "", ref: str = "") -> None:
        self.out.sources.append(SourceStatus(source, status, detail, ref))


def default_repo(collection: Path) -> str | None:
    """owner/name from the collection's `origin` remote, when it is GitHub."""
    try:
        done = subprocess.run(["git", "-C", str(collection), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"github\.com[:/](?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$", done.stdout.strip())
    return match["repo"] if done.returncode == 0 and match else None


def _repository(b: _Builder, reader: RepoReader | None, refs: Sequence[str], repo: str | None,
                search: str | None) -> None:
    if reader is None:
        b.status(REPOSITORY, f"{NOT_EXAMINED}: no repository reader")
        return
    if not refs and not search:
        b.status(REPOSITORY, f"{NOT_EXAMINED}: no --ref given, and --search is off")
        return
    wanted: list[Ref] = []
    for text in refs:
        try:
            wanted.append(parse_ref(text, repo))
        except ValueError as exc:
            b.status(REPOSITORY, f"{NOT_EXAMINED}: {exc}", ref=text)
    if search:
        where = f"search {search!r} in {repo}" if repo else f"search {search!r}"
        if not repo:
            b.status(REPOSITORY, f"{NOT_EXAMINED}: --search needs a repository (--repo owner/name)", ref=where)
        else:
            try:
                result = reader.search(repo, search)
            except RepoReadError as exc:
                b.status(REPOSITORY, f"{NOT_EXAMINED}: the search failed: {exc}", ref=where)
            else:
                fresh = [r for r in result.refs if all((w.repo, w.number) != (r.repo, r.number) for w in wanted)]
                wanted.extend(fresh)
                detail = f"{len(result.refs)} match(es), {len(fresh)} not already named by --ref"
                if result.truncated:
                    detail += "; TRUNCATED: more matches exist than one search returns, and those were not read"
                b.status(REPOSITORY, EXAMINED if result.refs else NONE_FOUND, detail, ref=where)
    for ref in wanted:
        try:
            doc = reader.read(ref)
        except RepoReadError as exc:
            b.status(REPOSITORY, f"{NOT_EXAMINED}: {exc}", ref=str(ref))
            continue
        _document(b, doc)


def _document(b: _Builder, doc: Document) -> None:
    before = b.n
    for part in doc.parts:
        for section, text in extract(part.body):
            b.add(section, text, part.url or doc.url, OBSERVATIONAL, REPOSITORY)
    found = b.n - before
    detail = f"{doc.kind} {doc.title!r}: {len(doc.parts)} part(s) read, {found} charter item(s)"
    if doc.truncated:
        detail += "; TRUNCATED: more comments exist than one read fetches, and those were not read"
    b.status(REPOSITORY, EXAMINED if found else NONE_FOUND, detail, ref=str(doc.ref))


def _git_versions(path: Path) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(path.parent), "log", "--format=%h %as", "--", path.name],
                              capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    versions = [v for v in done.stdout.splitlines() if v.strip()]
    return f"git history: {len(versions)} version(s){': ' + ', '.join(versions[:10]) if versions else ''}"


def _charter_file(b: _Builder, path: Path, label: str) -> bool:
    """Offer every clause of a charter (or a draft) at `path`. False when absent."""
    if not path.exists():
        return False
    try:
        data, _ = parse_contract_block(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        b.status(EXISTING_CHARTER, f"{NOT_EXAMINED}: {label} not parsed ({exc})", ref=label)
        return True
    before = b.n
    intent = data.get("intent")
    if isinstance(intent, dict) and isinstance(intent.get("what"), str):
        b.add("intent", intent["what"], f"{label}: {intent.get('id', 'intent')}", STATED, EXISTING_CHARTER)
    elif isinstance(intent, str):
        b.add("intent", intent, f"{label}: intent", STATED, EXISTING_CHARTER)
    if isinstance(data.get("purpose"), str):
        b.add("purpose", str(data["purpose"]), f"{label}: purpose", STATED, EXISTING_CHARTER)
    sections: list[tuple[str, object]] = [(s, data.get(s)) for s in ("provides", "requires", "authority", "failure")]
    invariants = data.get("invariants")
    if isinstance(invariants, dict):
        sections += [("always", invariants.get("always")), ("never", invariants.get("never"))]
    for section, entries in sections:
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict):
                # Every clause, even one with only an id and a test (counter-
                # model review): its test is evidence too.
                clause_id = str(entry.get("id", section))
                text = entry.get("what") or entry.get("on_false")
                if not isinstance(text, str) or not text.strip():
                    text = f"{clause_id} (no text in the charter)"
                tests = entry.get("test")
                test = ", ".join(str(t) for t in tests) if isinstance(tests, list) else str(tests or "")
                draft = " (draft)" if entry.get("draft") is True else ""
                b.add(section, text, f"{label}: {clause_id}{draft}", STATED, EXISTING_CHARTER, test)
    history = _git_versions(path) or "git history: not examined (git could not read it)"
    b.status(EXISTING_CHARTER, EXAMINED if b.n > before else NONE_FOUND,
             f"{b.n - before} clause(s); {history}", ref=label)
    return True


def _skill_text(b: _Builder, skill_file: Path, label: str, docs: Sequence[tuple[Path, str]]) -> None:
    try:
        front, body, first, warnings = charter.read_skill(skill_file)
    except (OSError, UnicodeDecodeError) as exc:
        b.status(SKILL_TEXT, f"{NOT_EXAMINED}: {label} not read ({exc.__class__.__name__})", ref=label)
        return
    before = b.n
    description = front.get("description")
    if isinstance(description, str) and description.strip():
        b.add("intent", description, f"{label}: frontmatter description", STATED, SKILL_TEXT)
    for c in charter.stated_duties(body, label, first):
        b.add(c.kind, c.sentence, c.cite, STATED, SKILL_TEXT)
    b.status(SKILL_TEXT, EXAMINED if b.n > before else NONE_FOUND,
             f"{b.n - before} item(s)" + (f"; {'; '.join(warnings)}" if warnings else ""), ref=label)
    for path, doc_label in docs:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            b.status(SKILL_TEXT, f"{NOT_EXAMINED}: {doc_label} not read ({exc.__class__.__name__})", ref=doc_label)
            continue
        before = b.n
        for c in charter.stated_duties(text, doc_label):
            b.add(c.kind, c.sentence, c.cite, STATED, SKILL_TEXT)
        b.status(SKILL_TEXT, EXAMINED if b.n > before else NONE_FOUND, f"{b.n - before} item(s)", ref=doc_label)


def _usage(b: _Builder, names: set[str], usage_paths: Sequence[Path]) -> None:
    if not usage_paths:
        b.status(USAGE, f"{NOT_EXAMINED}: no --usage given; absences are UNKNOWN")
        return
    logs: list[usage.UsageLog] = []
    for path in usage_paths:
        logs.extend(usage.discover_logs(path))
    ev = charter.read_evidence(logs, names)
    cites = _usage_cites(logs, names)
    for o in ev.observations:
        where = cites.get(o.token, [])
        shown = ", ".join(where[:5]) + (f" and {len(where) - 5} more" if len(where) > 5 else "")
        b.add(OBSERVED, f"seen ending with stop_reason {o.token} ({o.count} record(s))",
              shown or f"usage records: stop_reason {o.token}", OBSERVED, USAGE)
    detail = f"{ev.records} record(s) in {ev.logs} log(s)"
    if not ev.can_show_absence:
        detail += f"; absences UNKNOWN ({ev.why_unknown()})"
    if ev.unreadable:
        detail += f"; unreadable, not counted: {len(ev.unreadable)} log(s)"
    if ev.logs == 0 or (ev.unreadable and ev.records == 0):
        b.status(USAGE, f"{NOT_EXAMINED}: {ev.why_unknown()}", detail)
    else:
        b.status(USAGE, EXAMINED if ev.observations else NONE_FOUND, detail)


def _usage_cites(logs: Sequence[usage.UsageLog], names: set[str]) -> dict[str, list[str]]:
    """token -> the `<log>:<line>` of every end record that carries it, under
    the SAME filters `charter.read_evidence` counts by."""
    out: dict[str, list[str]] = {}
    for log in logs:
        if log.parse_error is not None:
            continue
        for entry in log.entries:
            data = entry.data
            skill = data.get("skill")
            if not isinstance(skill, str) or skill not in names or usage.record_problems(data):
                continue
            reason = data.get("stop_reason")
            if data.get("event") == "end" and isinstance(reason, str) and usage.STOP_REASON_RE.fullmatch(reason):
                out.setdefault(reason, []).append(f"{log.path}:{entry.line}")
    return out


def _tests(b: _Builder, collection: Path, names: set[str]) -> None:
    patterns = [re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(n)}(?![A-Za-z0-9_-])") for n in sorted(names) if n]
    found = 0
    unreadable = 0
    too_large = 0
    walk = _Walk(collection)
    for path in walk:
        if found >= TEST_LIMIT:
            break
        try:
            if path.stat().st_size > TEST_MAX_BYTES:
                too_large += 1
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        for number, line in enumerate(lines, 1):
            if any(p.search(line) for p in patterns):
                rel = path.relative_to(collection).as_posix()
                b.add(TEST, f"{rel} names the skill", f"{rel}:{number}", TEST, TESTS)
                found += 1
                break
    detail = f"{walk.candidates} test file(s) read, {found} name {', '.join(sorted(names))}"
    if found >= TEST_LIMIT:
        detail += f"; stopped at {TEST_LIMIT}"
    # What the scan could not read (counter-model review). A zero is only
    # "none found" when the whole population was read.
    gaps = []
    if walk.unreadable_dirs:
        gaps.append(f"{walk.unreadable_dirs} director{'y' if walk.unreadable_dirs == 1 else 'ies'} not readable")
    if unreadable:
        gaps.append(f"{unreadable} test file(s) not readable")
    if too_large:
        gaps.append(f"{too_large} test file(s) too large to read (over {TEST_MAX_BYTES} bytes)")
    if found:
        b.status(TESTS, EXAMINED, detail + "".join(f"; {g}" for g in gaps))
    elif gaps:
        b.status(TESTS, f"{NOT_EXAMINED}: {', '.join(gaps)}", detail)
    else:
        b.status(TESTS, NONE_FOUND, detail)


class _Walk:
    """Test files under a root, counting what could not be read."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.unreadable_dirs = 0
        self.candidates = 0

    def __iter__(self) -> Iterator[Path]:
        stack = [self.root]
        while stack:
            here = stack.pop()
            try:
                entries = sorted(here.iterdir(), key=lambda p: p.name, reverse=True)
            except OSError:
                self.unreadable_dirs += 1
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in SKIP_DIRS:
                        stack.append(entry)
                elif TEST_NAME_RE.match(entry.name):
                    self.candidates += 1
                    yield entry


def _label_of(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def gather(
    collection: Path,
    skill: str,
    *,
    reader: RepoReader | None,
    refs: Sequence[str] = (),
    repo: str | None = None,
    search: bool = False,
    docs: Sequence[Path] = (),
    usage_paths: Sequence[Path] = (),
    aliases: Sequence[str] = (),
    drafts: Sequence[Path] = (),
) -> EvidenceFile:
    """Gather every source for `skill` (relative to `collection`). Raises
    `gauntlet.UsageError` for a skill that cannot be resolved."""
    from .gauntlet import DRAFT_NAME, main_checkout, resolve_skill

    target = resolve_skill(collection, skill)
    root = target.collection
    label = target.text.relative_to(root).as_posix()
    out = EvidenceFile(target.rel, label)
    b = _Builder(out)
    try:
        front: dict[str, object] = charter.read_skill(target.text)[0]
    except (OSError, UnicodeDecodeError):
        front = {}  # _skill_text reports it; the other sources still run (counter-model review)
    names = charter.skill_names(target.text, front, aliases)
    term = str(front.get("name") or charter.primary_name(target.text)) if search else None
    _repository(b, reader, refs, repo, term)
    charter_label = target.charter.relative_to(root).as_posix()
    present = _charter_file(b, target.charter, charter_label)
    # Every draft: beside the charter, where `skillc gauntlet run` keeps it
    # before a charter exists (the main checkout's .skillc/gauntlet/<slug>/,
    # counter-model review), and any the caller names.
    candidates = [target.charter.parent / DRAFT_NAME]
    try:
        main = main_checkout(root)
    except (OSError, subprocess.SubprocessError) as exc:
        main = None
        b.status(EXISTING_CHARTER, f"{NOT_EXAMINED}: the gauntlet's draft location (git could not run: "
                                   f"{exc.__class__.__name__})")
    if main is not None:
        candidates.append(main / ".skillc" / "gauntlet" / target.slug / DRAFT_NAME)
    candidates.extend(drafts)
    seen: set[Path] = set()
    for path in candidates:
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        present = _charter_file(b, path, _label_of(path, root)) or present
    if not present:
        b.status(EXISTING_CHARTER, NONE_FOUND, f"no {charter_label} and no {DRAFT_NAME}")
    doc_pairs: list[tuple[Path, str]] = []
    for d in docs:
        path = d if d.is_absolute() else root / d
        try:
            doc_label = path.resolve().relative_to(root).as_posix()
        except ValueError:
            doc_label = str(d)  # outside the collection: the path as given, which resolves (counter-model review)
        doc_pairs.append((path, doc_label))
    _skill_text(b, target.text, label, doc_pairs)
    _usage(b, names, usage_paths)
    _tests(b, root, names)
    missing = [s for s in SOURCES if all(st.source != s for st in out.sources)]
    assert not missing, f"a source reported no status: {missing}"  # never silently empty
    return out
