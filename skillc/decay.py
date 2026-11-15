"""Decay rules: what has rotted in a skill collection's TEXT (issue #725).

`skillc check` reads frontmatter and shape, one SKILL.md at a time. These rules
read the prose of a whole COLLECTION, because each one needs something a single
file cannot show: the tree a reference must resolve in, the other skills a
passage may be copied from, the issue a temporary rule is waiting on.

Where each rule comes from (cooneycw/claude-power-pack discussion #1830):

- `dangling-reference` - Part 2: a rule pointing at a helper that was deleted.
- `expired-marker` - Part 2: "the rule is still there, the reason isn't";
  twelve of twelve `until #N` rules in CPP waited on closed issues.
- `copied-passage` - Parts 5 and 7: copies are a correctness problem, not a
  size problem; a rule held in N places must be changed in N places.
- `emphasis-density` - the opening post's outside evidence: capital-letter
  emphasis can push a model off track, and piled-up emphasis stops any one
  rule standing out.

Every rule says what it scanned and what it could not see (`population`), and
a fact it could not establish is `UNKNOWN`, never silently fine. The rules
never edit anything. Population and blind spots are documented in
docs/specs/inspect.md.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from .spec import FrontmatterError, parse_frontmatter

ERROR = "error"
WARN = "warn"

UNKNOWN = "UNKNOWN"
OPEN = "OPEN"
CLOSED = "CLOSED"

#: The default subject surface: the same population `skillc check` reads.
DEFAULT_INCLUDE: tuple[str, ...] = ("**/SKILL.md",)

#: Paths a skill text names as its OWN files. The Agent Skills specification's
#: optional subdirectories, resolved against the subject's directory, then the
#: collection root.
DEFAULT_OWN_PREFIXES: tuple[str, ...] = ("scripts/", "references/", "assets/")

#: `copied-passage`: a run of at least this many identical normalised words.
#: Part 7 of #1830 counted runs of 10+ words to measure sharing; 40 is the
#: FINDING floor - long enough that a shared idiom or a one-line command does
#: not fire, short enough that a pasted paragraph or code block does. Measured
#: on CPP and mattpocock/skills (docs/measurements/inspect/).
COPIED_MIN_WORDS = 40
#: Starting points tried in the other document per window: bounds repetitive text.
COPIED_CANDIDATES = 8

#: `emphasis-density`: these words, uppercase and whole, count as emphasis.
EMPHASIS_WORDS: tuple[str, ...] = ("MUST", "NEVER", "CRITICAL", "ALWAYS", "IMPORTANT")
EMPHASIS_RE = re.compile(r"\b(?:" + "|".join(EMPHASIS_WORDS) + r")\b")
#: Per hundred body lines, with `EMPHASIS_FLOOR_LINES` as the smallest
#: denominator so a ten-line file with three MUSTs does not read as 30.
EMPHASIS_THRESHOLD = 5.0
EMPHASIS_FLOOR_LINES = 50

CONFIG_NAME = "collection.json"


class CollectionError(ValueError):
    """A collection that cannot be loaded, so nothing in it was inspected."""


# ------------------------------------------------------------------ the subject

@dataclass(frozen=True)
class Subject:
    """One instruction document: a SKILL.md, or a command file read as Markdown."""

    path: Path
    rel: str
    body: str
    body_offset: int  # line number (1-based) of the body's first line in the file

    @property
    def lines(self) -> list[str]:
        return self.body.splitlines()

    def lineno(self, body_index: int) -> int:
        return self.body_offset + body_index


@dataclass(frozen=True)
class Collection:
    """A root, its subjects, and the declarations the decay rules read.

    `issue_states` is an explicit, offline answer to "is #N open": a mapping of
    `owner/name#N` to OPEN or CLOSED. When it is None, `resolve_states` asks
    `gh` unless `offline`. A collection loaded for a control or a test always
    carries one, or is offline, so no committed case touches the network.
    """

    root: Path
    subjects: tuple[Subject, ...]
    include: tuple[str, ...] = DEFAULT_INCLUDE
    exclude: tuple[str, ...] = ()
    maps: tuple[tuple[str, str], ...] = ()
    own_prefixes: tuple[str, ...] = DEFAULT_OWN_PREFIXES
    repo: str | None = None
    issue_states: Mapping[str, str] | None = None
    offline: bool = False
    enforcement_roots: tuple[str, ...] = ("tests/", "controls/", "ci/", ".github/workflows/")
    excluded_count: int = 0


_GLOB_CACHE: dict[str, re.Pattern[str]] = {}


def _glob_re(pattern: str) -> re.Pattern[str]:
    """Path-segment glob: only `**` crosses `/`. `fnmatch`'s `*` crosses it,
    so `.claude/skills/*/SKILL.md` would also select a SKILL.md nested inside
    a skill's references - a neighbour's tree in the declared surface."""
    cached = _GLOB_CACHE.get(pattern)
    if cached is not None:
        return cached
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    compiled = re.compile("".join(out) + r"\Z")
    _GLOB_CACHE[pattern] = compiled
    return compiled


def _matches(rel: str, pattern: str) -> bool:
    """A glob over a POSIX relative path; `**/` also matches zero directories,
    so `**/SKILL.md` finds a SKILL.md at the root as well."""
    return _glob_re(pattern).match(rel) is not None


def _split_body(text: str) -> tuple[str, int]:
    """The text after frontmatter that parses, and the line it starts on.

    A command file is Markdown first: frontmatter that does not parse is KEPT
    as body text, never dropped, because dropping it would hide its contents
    from every rule here (and `skillc check` owns frontmatter errors)."""
    try:
        _front, body = parse_frontmatter(text)
    except (FrontmatterError, ValueError, RecursionError):
        return text, 1
    head = text[: len(text) - len(body)]  # parse_frontmatter's body is always a suffix
    return body, head.count("\n") + 1


def load(
    root: Path,
    *,
    include: Sequence[str] = DEFAULT_INCLUDE,
    exclude: Sequence[str] = (),
    maps: Sequence[tuple[str, str]] = (),
    own_prefixes: Sequence[str] = DEFAULT_OWN_PREFIXES,
    repo: str | None = None,
    issue_states: Mapping[str, str] | None = None,
    offline: bool = False,
    enforcement_roots: Sequence[str] | None = None,
) -> Collection:
    root = root.resolve()
    if not root.is_dir():
        raise CollectionError(f"not a directory: {root}")
    subjects: list[Subject] = []
    excluded = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/"):
            continue
        if not any(_matches(rel, pat) for pat in include):
            continue
        if any(_matches(rel, pat) for pat in exclude):
            excluded += 1
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CollectionError(f"{rel} is unreadable: {exc}") from exc
        body, offset = _split_body(text)
        subjects.append(Subject(path=path, rel=rel, body=body, body_offset=offset))
    kwargs: dict[str, object] = {}
    if enforcement_roots is not None:
        kwargs["enforcement_roots"] = tuple(enforcement_roots)
    return Collection(
        root=root, subjects=tuple(subjects), include=tuple(include), exclude=tuple(exclude),
        maps=tuple(maps), own_prefixes=tuple(own_prefixes), repo=repo,
        issue_states=dict(issue_states) if issue_states is not None else None,
        offline=offline, excluded_count=excluded, **kwargs,  # type: ignore[arg-type]
    )


def _str_list(data: Mapping[str, object], key: str, where: Path) -> list[str] | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise CollectionError(f"{where}: {key!r} must be a list of non-empty strings")
    return list(value)


def parse_map(spec: str) -> tuple[str, str]:
    """`FROM=TO`: a prefix a text uses for an installed path, and where that
    path lives in the collection (`~/.claude/scripts/=scripts/`)."""
    if "=" not in spec:
        raise CollectionError(f"map {spec!r} is not FROM=TO")
    src, dst = spec.split("=", 1)
    if not src:
        raise CollectionError(f"map {spec!r} has an empty FROM")
    return src, dst


def read_issue_states(path: Path) -> dict[str, str]:
    """An offline issue-state fixture: `{"owner/name#N": "OPEN" | "CLOSED"}`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise CollectionError(f"issue states {path} unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise CollectionError(f"issue states {path} is not a JSON object")
    states: dict[str, str] = {}
    for key, value in data.items():
        if not ISSUE_KEY_RE.fullmatch(str(key)) or value not in (OPEN, CLOSED):
            raise CollectionError(
                f"issue states {path}: {key!r}: {value!r} is not owner/name#N -> OPEN|CLOSED"
            )
        states[str(key)] = str(value)
    return states


def load_case(case: Path, *, offline: bool = True) -> Collection:
    """A collection whose declarations sit in `<case>/collection.json` - the
    shape every committed control and fixture uses. Offline by default: a
    committed case never asks the network."""
    config = case / CONFIG_NAME
    data: dict[str, object] = {}
    if config.is_file():
        try:
            loaded = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise CollectionError(f"{config} unreadable: {exc}") from exc
        if not isinstance(loaded, dict):
            raise CollectionError(f"{config} is not a JSON object")
        data = loaded
    known = {"include", "exclude", "map", "own_prefixes", "repo", "issue_states",
             "enforcement_roots"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise CollectionError(f"{config}: unknown key(s) {unknown}")
    states = None
    if "issue_states" in data:
        if not isinstance(data["issue_states"], str):
            raise CollectionError(f"{config}: issue_states must be a relative path")
        states = read_issue_states(case / data["issue_states"])
    repo = data.get("repo")
    if repo is not None and not (isinstance(repo, str) and REPO_RE.fullmatch(repo)):
        raise CollectionError(f"{config}: repo must be owner/name")
    return load(
        case,
        include=_str_list(data, "include", config) or DEFAULT_INCLUDE,
        exclude=_str_list(data, "exclude", config) or (),
        maps=[parse_map(m) for m in (_str_list(data, "map", config) or [])],
        own_prefixes=_str_list(data, "own_prefixes", config) or DEFAULT_OWN_PREFIXES,
        repo=repo if isinstance(repo, str) else None,
        issue_states=states,
        offline=offline,
        enforcement_roots=_str_list(data, "enforcement_roots", config),
    )


# ------------------------------------------------------------------ results

@dataclass(frozen=True)
class Hit:
    """One finding: the rule fired here."""

    rel: str
    line: int
    detail: str
    data: Mapping[str, object] = field(default_factory=dict)


@dataclass
class Result:
    """What one rule said about one collection.

    `hits` are findings. `unknown` are facts the rule could not establish -
    never findings, never fine; a run with any is not clean. `notes` are
    information the rule surfaces without firing. `population` says what was
    examined and what was not, so a zero can be told from a blind spot."""

    hits: list[Hit] = field(default_factory=list)
    unknown: list[Hit] = field(default_factory=list)
    notes: list[Hit] = field(default_factory=list)
    population: dict[str, object] = field(default_factory=dict)
    examined: bool = True


# ------------------------------------------------------------- code spans

FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
MD_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]*\]\(\s*<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


@dataclass(frozen=True)
class Span:
    """A run of code-ish text: an inline code span, or one fenced-block line."""

    text: str
    index: int  # body line index


def code_spans(lines: Sequence[str]) -> list[Span]:
    spans: list[Span] = []
    in_fence = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            spans.append(Span(line, i))
            continue
        for match in INLINE_CODE_RE.finditer(line):
            spans.append(Span(match.group(2), i))
    return spans


def _prose_lines(lines: Sequence[str]) -> list[tuple[int, str]]:
    """Lines outside fenced blocks (Markdown links live here)."""
    out: list[tuple[int, str]] = []
    in_fence = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((i, line))
    return out


# --------------------------------------------------------- dangling-reference

PLACEHOLDER_CHARS = set("<>{}$*?[]|\\'\"")
PATH_WORD_RE = re.compile(r"^[A-Za-z0-9._~/@+-]+$")
TRAILING_PUNCT = ".,;:)"
FLAG_RE = re.compile(r"^--[A-Za-z0-9][A-Za-z0-9-]*$")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _clean_word(word: str) -> str:
    word = word.strip("\"'(")
    while word and word[-1] in TRAILING_PUNCT:
        word = word[:-1]
    return word


def _is_placeholder(word: str) -> bool:
    return any(c in PLACEHOLDER_CHARS for c in word)


def _looks_like_file(word: str) -> bool:
    """Path-like: it has a `/` and its last segment has an extension. Used only
    to COUNT what the rule could not examine, never to fire."""
    if "/" not in word or not PATH_WORD_RE.match(word):
        return False
    last = word.rstrip("/").rsplit("/", 1)[-1]
    return "." in last.strip(".")


@dataclass(frozen=True)
class Ref:
    word: str
    candidates: tuple[Path, ...]  # resolved locations, any one existing satisfies it


def _resolve_prefixed(word: str, subject: Subject, coll: Collection) -> Ref | None:
    """The reference a word makes INTO the collection, or None when it claims
    nothing about the collection (an unmapped home path, a user-project file)."""
    for src, dst in coll.maps:
        if word.startswith(src) and len(word) > len(src):
            return Ref(word, ((coll.root / (dst + word[len(src):])),))
    for prefix in coll.own_prefixes:
        if word.startswith(prefix) and len(word) > len(prefix):
            return Ref(word, (subject.path.parent / word, coll.root / word))
    return None


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _exists(ref: Ref, root: Path) -> Path | None:
    for candidate in ref.candidates:
        # Exact path only, never a substring or a fuzzy match; and only inside
        # the collection, so `../../etc/passwd` cannot satisfy a reference.
        if candidate.exists() and _inside(candidate, root):
            return candidate
    return None


SHELL_SEPARATORS = {"|", "||", "&&", ";", "&"}
SHELL_BREAKS = ("`", "|", ";", "&&")


@functools.lru_cache(maxsize=1024)
def _script_source(script: Path, root: Path) -> str:
    """The text a flag is looked up in: the script, plus every file beside it
    that the script names by basename - a wrapper such as
    `flow-preflight.sh` that execs `flow-preflight.py "$@"` takes the flags its
    target defines. One hop only, and only inside the collection."""
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    parts = [text]
    try:
        siblings = [p for p in script.parent.iterdir() if p.is_file() and p != script]
    except OSError:
        siblings = []
    for sibling in siblings:
        # A plain substring test first: the boundary regex below is the
        # actual rule (`elper.sh` is not `helper.sh`), but running it over a
        # large script once per sibling made a CPP-sized run take 40 s.
        if sibling.name not in text:
            continue
        named = re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(sibling.name) + r"(?![A-Za-z0-9_-])", text)
        if named and _inside(sibling, root):
            try:
                parts.append(sibling.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(parts)


def _links(subject: Subject) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for index, line in _prose_lines(subject.lines):
        stripped = INLINE_CODE_RE.sub("", line)
        for match in MD_LINK_RE.finditer(stripped):
            target = match.group(1)
            if SCHEME_RE.match(target) or target.startswith(("#", "/", "~")) or _is_placeholder(target):
                continue
            target = target.split("#", 1)[0]
            if target:
                out.append((index, target))
    return out


def _decoded(target: str) -> str:
    """A Markdown link target as the filesystem names it: `my%20guide.md`
    is the file `my guide.md`. The boundary check runs on the DECODED path."""
    return unquote(target)


def dangling_reference(coll: Collection) -> Result:
    result = Result()
    links = prefixed = flags = 0
    unexamined_paths = 0
    placeholders = 0
    seen_unexamined: set[str] = set()
    for subject in coll.subjects:
        for index, target in _links(subject):
            links += 1
            ref = Ref(target, (subject.path.parent / _decoded(target),))
            if _exists(ref, coll.root) is None:
                result.hits.append(Hit(
                    subject.rel, subject.lineno(index),
                    f"links to {target}, which does not exist",
                    {"reference": target, "kind": "link"},
                ))
        for span in code_spans(subject.lines):
            script: Path | None = None
            script_word = ""
            outer: list[tuple[Path | None, str]] = []  # commands suspended by `$(`
            for raw in span.text.split():
                word = _clean_word(raw)
                opens = raw.count("$(")
                closes = raw.count(")") if outer or opens else 0
                if opens:
                    # A flag inside `$(...)` belongs to the nested command; the
                    # outer command resumes when the substitution closes.
                    for _ in range(opens):
                        outer.append((script, script_word))
                    script, script_word = None, ""
                    closes -= min(opens, closes)
                if closes and outer:
                    for _ in range(min(closes, len(outer))):
                        script, script_word = outer.pop()
                    continue
                if opens:
                    continue
                if not word:
                    continue
                if any(sep in raw for sep in SHELL_BREAKS) or word in SHELL_SEPARATORS:
                    # A flag after `|`, `;` or `&&` belongs to another command.
                    script, script_word = None, ""
                    if not word.strip("|;&()$`"):
                        continue
                if script is not None and FLAG_RE.match(word.split("=", 1)[0]):
                    flag = word.split("=", 1)[0]
                    flags += 1
                    source = _script_source(script, coll.root)
                    if not re.search(r"(?<![A-Za-z0-9-])" + re.escape(flag) + r"(?![A-Za-z0-9-])", source):
                        result.hits.append(Hit(
                            subject.rel, subject.lineno(span.index),
                            f"passes {flag} to {script_word}, whose source never mentions it",
                            {"reference": f"{script_word} {flag}", "kind": "flag"},
                        ))
                    continue
                if _is_placeholder(word):
                    if "/" in word:
                        placeholders += 1
                    continue
                if not PATH_WORD_RE.match(word):
                    continue
                pref: Ref | None = _resolve_prefixed(word, subject, coll)
                if pref is not None and not (_looks_like_file(word) or word.endswith("/")):
                    # `scripts/foo` with no extension is as often a prose
                    # example as a reference; counted, not fired on.
                    pref = None
                if pref is None:
                    if _looks_like_file(word) and word not in seen_unexamined:
                        seen_unexamined.add(word)
                        unexamined_paths += 1
                    continue
                prefixed += 1
                found = _exists(pref, coll.root)
                if found is None:
                    result.hits.append(Hit(
                        subject.rel, subject.lineno(span.index),
                        f"names {word}, which does not exist in the collection",
                        {"reference": word, "kind": "path"},
                    ))
                    script = None
                elif found.is_file():
                    script, script_word = found, word
    result.population = {
        "links_examined": links,
        "prefixed_references_examined": prefixed,
        "flags_examined": flags,
        "path_like_not_examined": unexamined_paths,
        "placeholder_paths_not_examined": placeholders,
        "own_prefixes": list(coll.own_prefixes),
        "maps": [f"{a}={b}" for a, b in coll.maps],
    }
    return result


# ------------------------------------------------------------- expired-marker

REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
ISSUE_KEY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[0-9]+")
MARKER_RE = re.compile(
    r"\b(?P<kind>until|expires-with:)\s+(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<num>[0-9]+)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Marker:
    rel: str
    line: int
    kind: str  # "until" or "expires-with"
    key: str | None  # owner/name#N, or None when the repository is unknown
    text: str


def markers(coll: Collection) -> list[Marker]:
    found: list[Marker] = []
    for subject in coll.subjects:
        for index, line in enumerate(subject.lines):
            for match in MARKER_RE.finditer(line):
                repo = match.group("repo") or coll.repo
                kind = "expires-with" if match.group("kind").lower().startswith("expires") else "until"
                key = f"{repo}#{match.group('num')}" if repo else None
                found.append(Marker(subject.rel, subject.lineno(index), kind, key, match.group(0)))
    return found


#: How `expired-marker` asks GitHub. A seam so tests drive it without `gh`.
StateLookup = Callable[[Sequence[str]], dict[str, str]]


def gh_lookup(keys: Sequence[str]) -> dict[str, str]:
    """Ask `gh` for each issue's state. Anything that is not a clean answer -
    no `gh`, no network, no auth, no such issue - is UNKNOWN, never OPEN."""
    states = {key: UNKNOWN for key in keys}
    gh = shutil.which("gh")
    if gh is None:
        return states
    for key in keys:
        repo, num = key.rsplit("#", 1)
        try:
            proc = subprocess.run(
                [gh, "issue", "view", num, "-R", repo, "--json", "state", "--jq", ".state"],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        answer = proc.stdout.strip()
        if proc.returncode == 0 and answer in (OPEN, CLOSED):
            states[key] = answer
    return states


def repo_from_git(root: Path) -> str | None:
    """`owner/name` from the root's `origin` remote, or None."""
    git = shutil.which("git")
    if git is None:
        return None
    try:
        proc = subprocess.run(
            [git, "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    url = proc.stdout.strip()
    match = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$", url)
    return match.group(1) if (proc.returncode == 0 and match) else None


def resolve_states(coll: Collection, keys: Sequence[str], lookup: StateLookup | None = None) -> dict[str, str]:
    keys = sorted(set(keys))
    if coll.issue_states is not None:
        return {key: coll.issue_states.get(key, UNKNOWN) for key in keys}
    if coll.offline or not keys:
        return {key: UNKNOWN for key in keys}
    answered = (lookup or gh_lookup)(keys)
    return {key: answered.get(key, UNKNOWN) if answered.get(key) in (OPEN, CLOSED) else UNKNOWN
            for key in keys}


#: Set by `inspect` to route lookups; `None` means `gh_lookup`.
STATE_LOOKUP: StateLookup | None = None


def expired_marker(coll: Collection) -> Result:
    result = Result()
    found = markers(coll)
    states = resolve_states(coll, [m.key for m in found if m.key], STATE_LOOKUP)
    marked_lines = {(m.rel, m.line) for m in found if m.kind == "expires-with"}
    counts = {OPEN: 0, CLOSED: 0, UNKNOWN: 0}
    for m in found:
        state = states.get(m.key, UNKNOWN) if m.key else UNKNOWN
        counts[state] += 1
        data = {"marker": m.text, "issue": m.key, "kind": m.kind, "state": state}
        if state == CLOSED:
            result.hits.append(Hit(m.rel, m.line, f"{m.text!r} waits on {m.key}, which is closed", data))
        elif state == UNKNOWN:
            why = "its repository is unknown" if m.key is None else "its state could not be read"
            result.unknown.append(Hit(m.rel, m.line, f"{m.text!r}: UNKNOWN - {why}", data))
        if m.kind == "until" and (m.rel, m.line) not in marked_lines:
            result.notes.append(Hit(
                m.rel, m.line,
                f"{m.text!r} has no expires-with marker - the dependency is prose only",
                data,
            ))
    if coll.issue_states is not None:
        source = "fixture"
    elif coll.offline:
        source = "offline"
    else:
        source = "gh"
    result.population = {
        "markers": len(found),
        "open": counts[OPEN], "closed": counts[CLOSED], "unknown": counts[UNKNOWN],
        "state_source": source,
        "repo": coll.repo,
    }
    return result


# ------------------------------------------------------------- copied-passage

WORD_RE = re.compile(r"\S+")


def _words(subject: Subject) -> list[tuple[str, int]]:
    """Every whitespace-delimited word with its body line index. Whitespace
    normalisation is the split itself: re-wrapping a paragraph changes no word."""
    out: list[tuple[str, int]] = []
    for index, line in enumerate(subject.lines):
        for match in WORD_RE.finditer(line):
            out.append((match.group(0), index))
    return out


def copied_passage(coll: Collection, min_words: int = COPIED_MIN_WORDS) -> Result:
    result = Result()
    subjects = list(coll.subjects)
    if len(subjects) < 2:
        result.examined = False
        result.population = {"subjects": len(subjects), "reason": "fewer than 2 subjects - nothing to compare"}
        return result
    words = [_words(s) for s in subjects]
    tokens = [[w for w, _ in ws] for ws in words]
    # Keyed on the window's HASH: a 40-word tuple per position costs hundreds
    # of megabytes on a CPP-sized collection. A collision cannot fire the rule;
    # every candidate is compared word for word before it counts.
    positions: list[dict[int, list[int]]] = []
    owners: dict[int, list[int]] = defaultdict(list)
    for si, toks in enumerate(tokens):
        index: dict[int, list[int]] = defaultdict(list)
        for pos in range(len(toks) - min_words + 1):
            index[hash(tuple(toks[pos:pos + min_words]))].append(pos)
        positions.append(index)
        for h in index:
            owners[h].append(si)
    common: dict[tuple[int, int], set[int]] = defaultdict(set)
    for h, here in owners.items():
        for i, a in enumerate(here):
            for b in here[i + 1:]:
                common[(a, b)].add(h)
    total_pairs = 0
    for (a, b), hashes in sorted(common.items()):
        ta, tb = tokens[a], tokens[b]
        visit = sorted(p for h in hashes for p in positions[a][h])
        runs: list[tuple[int, int, int]] = []  # (a_start, b_start, length in words)
        covered_until = 0
        for pos in visit:
            if pos < covered_until:
                continue
            best_len, best_b = 0, 0
            window = ta[pos:pos + min_words]
            # At most COPIED_CANDIDATES starting points in the other document:
            # repetitive text cannot multiply into a cross-product, and each
            # candidate is EXTENDED to its full length, so a long run is still
            # measured whole (the bound is on where a run may start, not on
            # how long it may be).
            for bp in positions[b][hash(tuple(window))][:COPIED_CANDIDATES]:
                if tb[bp:bp + min_words] != window:
                    continue
                length = min_words
                while pos + length < len(ta) and bp + length < len(tb) and ta[pos + length] == tb[bp + length]:
                    length += 1
                if length > best_len:
                    best_len, best_b = length, bp
            if best_len:
                runs.append((pos, best_b, best_len))
                covered_until = pos + best_len
        if not runs:
            continue
        longest = max(length for _a, _b, length in runs)
        first_a, first_b, _ = runs[0]
        sa, sb = subjects[a], subjects[b]
        total_pairs += 1
        shared = sum(length for _a, _b, length in runs)
        result.hits.append(Hit(
            sa.rel, sa.lineno(words[a][first_a][1]),
            f"shares {len(runs)} copied run(s) with {sb.rel} (line {sb.lineno(words[b][first_b][1])}), "
            f"longest {longest} words, {shared} words in all - a rule held in both places "
            f"must be changed in both",
            {"other": sb.rel, "runs": len(runs), "longest_words": longest, "shared_words": shared},
        ))
    result.population = {"subjects": len(subjects), "min_words": min_words, "pairs_sharing": total_pairs}
    return result


# ------------------------------------------------------------- emphasis-density

def emphasis_lines(subject: Subject) -> list[tuple[int, int, str]]:
    """(body index, emphasis count, line) for every line carrying emphasis."""
    out = []
    for index, line in enumerate(subject.lines):
        count = len(EMPHASIS_RE.findall(line))
        if count:
            out.append((index, count, line))
    return out


def emphasis_density(coll: Collection) -> Result:
    result = Result()
    densities: list[float] = []
    for subject in coll.subjects:
        count = sum(c for _i, c, _l in emphasis_lines(subject))
        lines = len(subject.lines)
        density = count * 100 / max(lines, EMPHASIS_FLOOR_LINES)
        densities.append(density)
        if density > EMPHASIS_THRESHOLD:
            result.hits.append(Hit(
                subject.rel, subject.body_offset,
                f"{count} emphasis word(s) ({'/'.join(EMPHASIS_WORDS)}) in {lines} body lines - "
                f"{density:.1f} per 100, over {EMPHASIS_THRESHOLD:g}; when everything is emphasised "
                f"nothing stands out",
                {"count": count, "lines": lines, "density": round(density, 2)},
            ))
    result.population = {
        "subjects": len(coll.subjects),
        "threshold": EMPHASIS_THRESHOLD,
        "floor_lines": EMPHASIS_FLOOR_LINES,
        "max_density": round(max(densities), 2) if densities else None,
    }
    return result


def not_exercised(rule_id: str, result: Result) -> str | None:
    """Why `result` exercised nothing, or None when it examined something.

    `selftest` reads this: a known-good case the rule had nothing to examine
    in - no reference, no marker, no pair - is silent because it is EMPTY,
    not because it is good (the #723 empty-population defect, closed here
    before it could open)."""
    if not result.examined:
        return f"{rule_id} not examined: {result.population.get('reason', 'no population')}"
    pop = result.population
    if rule_id == "dangling-reference" and not (
        pop.get("links_examined") or pop.get("prefixed_references_examined") or pop.get("flags_examined")
    ):
        return "dangling-reference examined no link, prefixed reference or flag"
    if rule_id == "expired-marker" and not pop.get("markers"):
        return "expired-marker found no marker to examine"
    return None
