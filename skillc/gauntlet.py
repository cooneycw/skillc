"""`skillc gauntlet run <collection> <skill>`: the skill-gauntlet engine, part 1 (#754).

**It orchestrates only** (#718, cooneycw/claude-power-pack#1830 Part 7). Each
round is an existing skillc command, run as a subprocess
(`python -m skillc.cli ...`). The engine reads that command's exit code, its
verdict lines and its report JSON, never its internals. It imports no round
module (`tests/test_gauntlet.py` checks this with the AST).

Rounds, in order (docs/specs/gauntlet.md):

- 0 `usage report` on every discovered usage log. No log reads UNKNOWN and the
  run CONTINUES: round 1 already treats missing usage as UNKNOWN columns.
- 1 `charter draft` when the skill has no CHARTER.md. The run STOPS with
  "draft ready for owner confirmation"; the engine never confirms a charter or
  writes one. With a CHARTER.md, `contracts` reads this skill's contract and
  the run STOPS on BAD or on an intent or authority clause the owner has not
  approved.
- 1 overlap: `charter overlap`. Exit 3 reads NOT EXAMINED. It is shown, never
  counted as passed, and it does not stop the run: it is a proposal view.
- 2 `inspect` on the WHOLE collection (copied-passage needs two subjects),
  filtered to this skill's findings.
- 3, 4, 5: not built in part 1 (#736, #737). The run stops at round 3. Exit 0
  is reserved for a complete keep/trim/retire run and is unreachable here.

A command that this skillc does not have reads NOT BUILT, the same path rounds
3-5 take, so `charter` reads NOT BUILT until #726 lands.

**The record** is `GAUNTLET.json` beside the skill's CHARTER.md (owner ruling
on #754). Before a confirmed charter exists, the draft and the record go to
`<collection main checkout>/.skillc/gauntlet/<skill>/`, which ignores itself.
The record holds digests and verdicts only: no usage row or count, no session
id, no host path, no wall-clock time. It is written with sorted keys and only
when its bytes would change, so an unchanged re-run leaves it byte-identical.
The engine never stages, commits or pushes it; that is the owner's act.

Exit codes: 1 a round failed (a contract BAD, an inspect error on this skill);
2 usage error; 3 stopped at an owner point, UNKNOWN or NOT BUILT. Never 0 in
part 1.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# #783, orchestrator ruling rev 51: the ONLY names the engine takes from a round
# module - pure, read-only parsers. tests/test_gauntlet.py pins this list.
from .charter import skill_names
from .contracts import expand, load
from .spec import FrontmatterError, parse_frontmatter

EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_STOPPED = 3

RECORD_NAME = "GAUNTLET.json"
DRAFT_NAME = "CHARTER.draft.md"
RECORD_KIND = "skill-gauntlet-record"
RECORD_SCHEMA = 1
NOT_A_VERDICT = "no trials ran; this is not a keep/trim/retire verdict"
#: Files the engine writes or owns are not inputs to any round, or writing the
#: record would change the next run's inputs and nothing would ever be cached.
_NOT_INPUTS = {RECORD_NAME}
_SKIP_DIRS = {".git", ".skillc", "__pycache__", ".venv", "node_modules"}
_CONTRACT_LINE = re.compile(r"^CONTRACT (?P<name>\S+) \((?P<path>[^)]+)\): (?P<state>GOOD|BAD)\b", re.MULTILINE)
#: `Finding.render`: severity, rule, then the path up to the first ": " - a path may hold spaces.
_FINDING_LINE = re.compile(r"^(?P<severity>error|warn)\s+(?P<rule>\S+)\s+(?P<path>.+?): ", re.MULTILINE)
#: `contracts` says so when its collection-wide rules could not run (docs/specs/contracts.md).
_CROSS_NOT_RUN = "did NOT run"
COMMAND_TIMEOUT = 1800
#: #760: the most directory entries round 2's key lists under the skipped
#: directories (.venv, node_modules, .skillc, __pycache__) before it reads UNKNOWN
#: rather than scanning on (orchestrator ruling rev 37).
SKIPPED_WALK_CAP = 20000
#: The most entries round 1's charter walk lists: it covers the WHOLE collection,
#: as `contracts` discovers charters everywhere (a real collection is ~13,000).
CHARTER_WALK_CAP = 200000
#: `usage report`'s per-skill block (skillc/usage.py), the lines round 0 counts.
_USAGE_HEADING = "by skill and digest:"
_USAGE_ROW = re.compile(r"^  (?P<skill>\S+)\s+(?P<digest>\S+)\s+(?P<count>\d+)$")


class UsageError(Exception):
    """A request the engine refuses before running anything (exit 2)."""


@dataclass
class Skill:
    collection: Path
    rel: str  # the skill's directory (native) or command file, from the collection root
    text: Path  # SKILL.md, or the command .md file
    charter: Path  # where its CHARTER.md lives, present or not
    command: bool

    @property
    def text_rel(self) -> str:
        return self.text.relative_to(self.collection).as_posix()

    @property
    def charter_rel(self) -> str:
        return self.charter.relative_to(self.collection).as_posix()

    @property
    def slug(self) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "__", self.rel.strip("/")) or "skill"


@dataclass
class Result:
    round: str  # "0", "1", "1-overlap", "2", "3"
    name: str
    verdict: str  # PASS, OBSERVED, UNKNOWN, STOP, FAIL, NOT BUILT, NOT EXAMINED
    detail: str
    proceed: bool  # does the run continue past this round?
    inputs: dict[str, str] = field(default_factory=dict)
    cached: bool = False
    lines: list[str] = field(default_factory=list)  # shown, never recorded
    #: #783: the stop's reason code and the facts the plain report's Found
    #: line names. Shown, never recorded and never part of the cache key; kept
    #: beside `lines` in the host-local display cache so a cached round reports too.
    reason: str = ""
    facts: dict[str, object] = field(default_factory=dict)


@dataclass
class Options:
    usage: list[Path] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    offline: bool = False
    issue_states: Path | None = None
    repo: str | None = None
    draft_dir: Path | None = None
    include: list[str] = field(default_factory=list)  # round 2's inspect subject surface, passed through
    exclude: list[str] = field(default_factory=list)
    maps: list[str] = field(default_factory=list)
    output: str = "both"  # #783: "both" (plain report, then the machine lines), "plain" or "machine"


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    if not path.is_file():
        return "absent"
    try:
        return _sha(path.read_bytes())
    except OSError:
        return "unreadable"  # the round then reports UNKNOWN; it never crashes the run


def _tree_digest(root: Path, *, only: str | None = None) -> str:
    """Every file under `root` (or only files named `only`), by relative path and
    content, skipping version control, engine state and caches."""
    entries: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in dirnames if only is None else []:
            path = Path(dirpath, name)  # a directory's existence is an input (an empty declared test dir)
            entries.append((path.relative_to(root).as_posix() + "/",
                            "symlink:" + os.readlink(path) if path.is_symlink() else "dir"))
        for name in sorted(filenames):
            if name in _NOT_INPUTS or (only is not None and name != only):
                continue
            path = Path(dirpath, name)
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries.append((rel, "symlink:" + os.readlink(path)))  # a retargeted link changes the digest
            elif path.is_file():
                entries.append((rel, _file_digest(path)))
    return _sha(json.dumps(entries, sort_keys=True).encode())


_IMPLEMENTATION: str | None = None


def implementation() -> str:
    """The skillc that produces the verdicts: every round's command and this
    engine. A cached verdict from another skillc is not reused."""
    global _IMPLEMENTATION
    if _IMPLEMENTATION is None:
        _IMPLEMENTATION = _tree_digest(Path(__file__).resolve().parent)
    return _IMPLEMENTATION


def _skillc(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one skillc command, exactly as an operator would."""
    # -P: never prepend the working directory (the collection) to sys.path, so a
    # collection holding its own `skillc/` package is read, never executed.
    return subprocess.run([sys.executable, "-P", "-m", "skillc.cli", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=COMMAND_TIMEOUT, check=False)


def available(words: list[str], cwd: Path) -> bool:
    """Does this skillc have the command? argparse refuses an unknown choice with
    exit 2; `--help` on a real one exits 0."""
    return _skillc([*words, "--help"], cwd).returncode == 0


def resolve_skill(collection: Path, skill: str) -> Skill:
    root = collection.resolve()
    if not root.is_dir():
        raise UsageError(f"no such collection directory: {collection}")
    given = Path(skill)
    given = given if given.is_absolute() else root / given
    # #759: no symlinked component between the collection root and the skill, so
    # nothing the engine writes beside it can land outside the collection.
    try:
        _no_symlink_below(given, root)
    except UsageError:
        raise UsageError(f"{skill} reaches the skill through a symlink; the gauntlet keeps its record beside "
                         "the skill and never writes through a link") from None
    target = given.resolve()
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        raise UsageError(f"the skill {skill} is not inside the collection {root}") from None
    for candidate in (target / "SKILL.md", target):
        if candidate.is_symlink():
            raise UsageError(f"{candidate.relative_to(root)} is a symlink; round 2's inspect skips symlinked "
                             "files, so the skill could never be shown inspected")
    if target.is_dir() and (target / "SKILL.md").is_file():
        return Skill(root, rel, target / "SKILL.md", target / "CHARTER.md", command=False)
    if target.is_file() and target.suffix == ".md":
        parts = target.relative_to(root).with_suffix("").parts
        if "commands" not in parts[:-1]:
            raise UsageError(f"{rel} is a .md file outside a commands/ directory; a command's charter lives "
                             "at charters/<ns>/<cmd>/CHARTER.md, and this path names no <ns>/<cmd>")
        tail = parts[parts.index("commands") + 1:]
        return Skill(root, rel, target, root.joinpath("charters", *tail, "CHARTER.md"), command=True)
    raise UsageError(f"{rel} is neither a skill directory holding SKILL.md nor a command .md file")


def main_checkout(path: Path) -> Path | None:
    """The main checkout of the git repository holding `path` (a linked worktree
    resolves to its main checkout), or None outside git."""
    done = subprocess.run(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                          capture_output=True, text=True, check=False)
    if done.returncode != 0 or not done.stdout.strip():
        return None
    common = Path(done.stdout.strip())
    return common.parent if common.name == ".git" else None


def _draft_dir(skill: Skill, options: Options) -> Path:
    if options.draft_dir is not None:
        top = _given_draft_dir(options.draft_dir)
        return top / skill.slug
    main = main_checkout(skill.collection)
    if main is None:
        raise UsageError(f"{skill.collection} is not in a git checkout, so the draft and the record have no "
                         "place before a CHARTER.md exists; pass --draft-dir")
    _no_symlink_below(main / ".skillc" / "gauntlet" / skill.slug, main)
    return main / ".skillc" / "gauntlet" / skill.slug


def _no_symlink_below(path: Path, top: Path) -> None:
    """Refuse a path with a symlinked component at or below `top`, so the engine
    never reads or writes outside where it says it does."""
    for part in [path, *path.parents]:
        if part == top:
            return
        if part.is_symlink():
            raise UsageError(f"{part} is a symlink - refusing to keep gauntlet state through it")


def _inside(path: Path, top: Path) -> None:
    """The resolved path must stay inside the resolved `top` (#759)."""
    if not path.resolve().is_relative_to(top.resolve()):
        raise UsageError(f"{path} resolves outside {top} - refusing to write the gauntlet record there")


def _given_draft_dir(given: Path) -> Path:
    """An operator-named --draft-dir, taken as given and never resolved: a
    symlinked one, or a symlink below it, is refused (#759, orchestrator ruling
    b), as #733 refuses a symlinked --out."""
    top = given if given.is_absolute() else Path.cwd() / given
    if top.is_symlink():
        raise UsageError(f"--draft-dir {given} is a symlink - refusing to keep gauntlet state through it")
    for child in top.rglob("*") if top.is_dir() else []:
        if child.is_symlink():
            raise UsageError(f"--draft-dir {given} holds a symlink ({child.relative_to(top)}) - refusing to keep "
                             "gauntlet state through it")
    return top


def _ensure_ignored(draft_dir: Path) -> None:
    """A `.skillc/` directory the engine creates ignores itself, as the usage hook's does."""
    for parent in [draft_dir, *draft_dir.parents]:
        if parent.name == ".skillc":
            parent.mkdir(parents=True, exist_ok=True)
            ignore = parent / ".gitignore"
            if not ignore.exists():
                ignore.write_text("*\n")
            break
    draft_dir.mkdir(parents=True, exist_ok=True)


def discover_usage(skill: Skill, options: Options) -> list[Path]:
    """The collection main checkout's own `.skillc/usage.jsonl`, plus every
    `--usage` file, or every `usage.jsonl` under a `--usage` directory. A
    skill's usage is recorded in the repo where it RAN, so `--usage` is how its
    data repositories are named. The engine never opens a log itself."""
    found: list[Path] = []
    main = main_checkout(skill.collection)
    if main is not None and (main / ".skillc" / "usage.jsonl").is_file():
        found.append(main / ".skillc" / "usage.jsonl")
    for given in options.usage:
        path = given.resolve()
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(p for p in path.rglob("usage.jsonl") if p.is_file()))
        else:
            raise UsageError(f"no such usage log or directory: {given}")
    unique: list[Path] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique


def _usage_inputs(logs: list[Path], aliases: list[str] | None = None) -> dict[str, str]:
    """Logs by digest only, numbered in digest order, so neither a path nor the
    order they were named in reaches the record. Round 0 counts this skill's
    own names, so its aliases are an input too (#760)."""
    digests = sorted(_file_digest(p) for p in logs)
    out = {f"usage-{i}": d for i, d in enumerate(digests, 1)} or {"usage": "none"}
    if aliases:
        out["aliases"] = _sha(json.dumps(sorted(aliases)).encode())
    return out


# --------------------------------------------------------------------- rounds

def _inside_collection(root: Path, rel: str) -> bool:
    """A test path backs a promise only as `contracts` reads it: relative, no
    `..`, inside the collection, and present."""
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts:
        return False
    try:
        return (root / path).resolve().is_relative_to(root.resolve()) and (root / path).exists()
    except (OSError, ValueError, RuntimeError):  # RuntimeError: a symlink loop (Python 3.12) backs nothing
        return False


def _glob_variants(pattern: str) -> list[str]:
    """`fnmatch` patterns matching at least what inspect's glob matches: `**/`
    may stand for ZERO directories there, so each `**/` is also tried removed.
    A superset is the safe direction: it can only re-run round 2 more often."""
    variants, frontier = {pattern}, [pattern]
    while frontier:
        v = frontier.pop()
        for k in range(len(v)):
            if v.startswith("**/", k) and (new := v[:k] + v[k + 3:]) not in variants:
                variants.add(new)
                frontier.append(new)
    return sorted(variants)


def _test_digest(collection: Path, rel: str) -> str:
    """A declared test path by content, only when `contracts` would read it:
    relative, no `..`, inside the collection, never through an escaping link."""
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts:
        return "outside"  # a stable sentinel; never read (a declared `/` would walk the disk)
    target = collection / path
    try:
        if not target.resolve().is_relative_to(collection.resolve()):
            return "outside"
    except (OSError, RuntimeError):
        return "unresolvable"
    if target.is_symlink():
        return "symlink:" + os.readlink(target)
    return _tree_digest(target) if target.is_dir() else _file_digest(target)


def _declared_tests(collection: Path) -> str:
    """Every charter `contracts` would discover - the whole collection, under
    .skillc/ and .venv/ too - by content, and every test path each declares by
    content ("absent" when missing): both change round 1's verdict (#760).
    Past CHARTER_WALK_CAP entries it answers "over-cap": round 1 then reads
    UNKNOWN rather than scanning on."""
    entries: list[tuple[str, str]] = []
    listed = 0
    for top, dirs, files in os.walk(collection):
        rel_top = Path(top).relative_to(collection).as_posix()
        dirs[:] = sorted(d for d in dirs if d != ".git" and not (rel_top == ".skillc" and d == "gauntlet"))
        listed += len(dirs) + len(files)
        if listed > CHARTER_WALK_CAP:
            return "over-cap"
        if "CHARTER.md" not in files:
            continue
        charter = Path(top, "CHARTER.md")
        entries.append((charter.relative_to(collection).as_posix(), _file_digest(charter)))
        contract = load(charter)
        sections = [contract.data.get(k) for k in ("requires", "provides", "authority", "failure")]
        invariants = contract.data.get("invariants")
        if isinstance(invariants, dict):
            sections += [invariants.get("always"), invariants.get("never")]
        for section in sections:
            for clause in section if isinstance(section, list) else []:
                declared = clause.get("test") if isinstance(clause, dict) else None
                for test in declared if isinstance(declared, list) else [declared] if declared else []:
                    paths, why = expand(str(test))
                    if why is not None:
                        entries.append((str(test), "unexpandable"))
                    for rel in paths:
                        entries.append((rel, _test_digest(collection, rel)))
    return _sha(json.dumps(sorted(set(entries))).encode())


def _charter_facts(charter: Path, root: Path) -> dict[str, object]:
    """Counts the plain report names (#783): the charter's promises, and how
    many name a test that exists. A structural read of a file - `contracts.load`
    and `expand` are pure parsers (orchestrator ruling rev 51) - never a round."""
    if not charter.is_file():
        return {}
    contract = load(charter)
    if contract.parse_error is not None:
        return {"parse_error": True}
    raw_inv, raw_intent = contract.data.get("invariants"), contract.data.get("intent")
    invariants: dict[str, object] = raw_inv if isinstance(raw_inv, dict) else {}
    out: dict[str, object] = {"intent_approved": isinstance(raw_intent, dict) and bool(raw_intent.get("approved"))}
    for kind in ("never", "always"):
        listed = invariants.get(kind)
        clauses = [c for c in listed if isinstance(c, dict)] if isinstance(listed, list) else []
        tested = 0
        for clause in clauses:
            # `test` is a path or a LIST of paths (#720), each with one level of {a,b}
            declared = clause.get("test")
            tests = declared if isinstance(declared, list) else [declared] if declared else []
            paths: list[str] = []
            unreadable = not tests
            for test in tests:
                expanded, why = expand(str(test))
                unreadable |= why is not None  # a declaration `contracts` refuses backs nothing
                paths += expanded
            tested += not unreadable and bool(paths) and all(_inside_collection(root, p) for p in paths)
        out[kind] = {"count": len(clauses), "tested": tested}
    return out



def _invocations(text: str, names: set[str]) -> int | None:
    """This skill's count from `usage report`'s "by skill and digest:" block, or
    None when the report does not have that shape (never read as OBSERVED)."""
    lines = text.splitlines()
    if _USAGE_HEADING not in lines:
        return None
    total = 0
    for line in lines[lines.index(_USAGE_HEADING) + 1:]:
        if not line.strip():
            break
        row = _USAGE_ROW.match(line)
        if row is None:
            return None
        if row.group("skill") in names:
            total += int(row.group("count"))
    return total


def _names(skill: Skill, aliases: list[str]) -> set[str]:
    try:
        front, _body = parse_frontmatter(skill.text.read_text())
    except (OSError, FrontmatterError):
        front = {}
    return skill_names(skill.text, front, aliases)


def _round0_inputs(skill: Skill, logs: list[Path], aliases: list[str]) -> dict[str, str]:
    """The logs, the aliases, and the RESOLVED name set: renaming the skill in
    its frontmatter changes which records are its own (counter-model review)."""
    return {**_usage_inputs(logs, aliases), "names": _sha(json.dumps(sorted(_names(skill, aliases))).encode())}


def round0(skill: Skill, logs: list[Path], aliases: list[str] | None = None) -> Result:
    inputs = _round0_inputs(skill, logs, aliases or [])
    if not logs:
        return Result("0", "usage", "UNKNOWN", "no usage log found - not a pass; round 1 reads usage as UNKNOWN",
                      proceed=True, inputs=inputs, reason="no-log")
    unreadable = sum(digest == "unreadable" for digest in inputs.values())
    names = _names(skill, aliases or [])
    invocations, shapeless = 0, 0
    for log in logs:
        done = _skillc(["usage", "report", str(log)], skill.collection)
        if done.returncode != 0:
            unreadable += 1
            continue
        count = _invocations(done.stdout, names)
        if count is None:
            shapeless += 1
        else:
            invocations += count
    if unreadable:
        return Result("0", "usage", "UNKNOWN", f"{unreadable} of {len(logs)} usage log(s) could not be read - "
                      "not a pass", proceed=True, inputs=inputs, reason="log-unreadable",
                      facts={"logs": len(logs), "unreadable": unreadable})
    if shapeless:
        return Result("0", "usage", "UNKNOWN", f"{shapeless} of {len(logs)} usage report(s) had no "
                      f"'{_USAGE_HEADING}' block this engine can read - not a pass", proceed=True, inputs=inputs,
                      reason="report-unreadable", facts={"logs": len(logs), "unreadable": shapeless})
    if invocations == 0:
        return Result("0", "usage", "UNKNOWN", f"{len(logs)} usage log(s) hold no invocation of "
                      f"{', '.join(sorted(names))} - not a pass; pass --alias if the skill runs under another name",
                      proceed=True, inputs=inputs, reason="skill-not-in-log",
                      facts={"logs": len(logs), "names": sorted(names)})
    return Result("0", "usage", "OBSERVED", f"{len(logs)} usage log(s) read by `skillc usage report`; counts "
                  "stay in the logs", proceed=True, inputs=inputs, facts={"logs": len(logs), "invocations": invocations})


def _round1_inputs(skill: Skill, logs: list[Path], tool: bool, options: Options) -> dict[str, str]:
    """The skill, its charter, and the whole collection: `contracts` checks that
    every declared test path exists, so any file can change its verdict."""
    return {"skill": _file_digest(skill.text), "charter": _file_digest(skill.charter),
            "collection": _tree_digest(skill.collection),
            "aliases": _sha(json.dumps(sorted(options.aliases)).encode()),
            "declared-tests": _declared_tests(skill.collection),
            "tool:charter": "available" if tool else "absent", **_usage_inputs(logs)}


def round1(skill: Skill, logs: list[Path], options: Options, draft: Path, tool: bool) -> Result:
    inputs = _round1_inputs(skill, logs, tool, options)
    if inputs["declared-tests"] == "over-cap":
        return Result("1", "charter", "UNKNOWN", f"the collection holds more than {CHARTER_WALK_CAP} entries, so "
                      "the charters `contracts` reads were not fingerprinted - not a pass", proceed=False,
                      inputs=inputs, reason="charter-walk-cap")
    if skill.charter.is_file():
        return _round1_contracts(skill, inputs)
    if not tool:
        return Result("1", "charter", "NOT BUILT", "no CHARTER.md, and this skillc has no `charter draft` (#726)",
                      proceed=False, inputs=inputs, reason="no-charter-tool")
    if draft.exists() and not draft.is_symlink() and not draft.is_file():
        raise UnsafeRecord(f"{draft.name} is not a regular file - refusing to draft over it")
    draft.unlink(missing_ok=True)  # the engine's own previous draft (a link is removed, never followed);
    # `charter draft --out` then creates it afresh and never overwrites
    args = ["charter", "draft", str(skill.text.parent if not skill.command else skill.text), "--out", str(draft)]
    if skill.command:
        args += ["--subject", skill.text_rel]
    for log in logs:
        args += ["--usage", str(log)]
    for alias in options.aliases:
        args += ["--alias", alias]
    done = _skillc(args, skill.collection)
    if done.returncode == 0 and draft.is_file():
        return Result("1", "charter", "STOP", "no CHARTER.md - draft ready for owner confirmation",
                      proceed=False, inputs=inputs, reason="no-charter-draft", facts=_charter_facts(draft, skill.collection))
    if done.returncode == 3:
        return Result("1", "charter", "UNKNOWN", "no CHARTER.md, and `charter draft` found nothing to draft from",
                      proceed=False, inputs=inputs, reason="draft-empty")
    return Result("1", "charter", "UNKNOWN", f"no CHARTER.md, and `charter draft` refused (exit {done.returncode})",
                  proceed=False, inputs=inputs, reason="draft-refused", facts={"exit": done.returncode})


def _round1_contracts(skill: Skill, inputs: dict[str, str]) -> Result:
    done = _skillc(["contracts", str(skill.collection)], skill.collection)
    ours = [m for m in _CONTRACT_LINE.finditer(done.stdout) if m.group("path") == skill.charter_rel]
    if not ours:
        return Result("1", "charter", "UNKNOWN", f"`skillc contracts` printed no CONTRACT line for "
                      f"{skill.charter_rel} (exit {done.returncode})", proceed=False, inputs=inputs,
                      reason="no-contract-line")
    findings = [m for m in _FINDING_LINE.finditer(done.stdout) if m.group("path") == skill.charter_rel]
    errors = sorted({m.group("rule") for m in findings if m.group("severity") == "error"})
    if ours[0].group("state") == "BAD":
        per_rule = {r: sum(m.group("rule") == r and m.group("severity") == "error" for m in findings) for r in errors}
        return Result("1", "charter", "FAIL", f"contract BAD: {', '.join(errors) or 'error findings'}",
                      proceed=False, inputs=inputs,
                      reason="contract-bad:" + (errors[0] if len(errors) == 1 else "several"),
                      facts={"rules": per_rule, **_charter_facts(skill.charter, skill.collection)})
    if _CROSS_NOT_RUN in done.stdout:
        return Result("1", "charter", "UNKNOWN", "`skillc contracts` says its hand-off rules did NOT run (a "
                      "contract in the collection failed contract-shape), so this contract's hand-offs are unchecked",
                      proceed=False, inputs=inputs, reason="cross-not-run")
    if any(m.group("rule") == "approval-present" for m in findings):
        return Result("1", "charter", "STOP", "the charter has an intent or authority clause the owner has not "
                      "approved (approval-present)", proceed=False, inputs=inputs, reason="unapproved",
                      facts=_charter_facts(skill.charter, skill.collection))
    return Result("1", "charter", "PASS", f"contract {ours[0].group('name')} GOOD and owner-approved",
                  proceed=True, inputs=inputs, facts=_charter_facts(skill.charter, skill.collection))


def _overlap_inputs(skill: Skill, tool: bool) -> dict[str, str]:
    return {"charters": _tree_digest(skill.collection, only="CHARTER.md"),
            "tool:charter-overlap": "available" if tool else "absent"}


def round1_overlap(skill: Skill, tool: bool) -> Result:
    inputs = _overlap_inputs(skill, tool)
    if not tool:
        return Result("1-overlap", "overlap", "NOT BUILT", "this skillc has no `charter overlap` (#726 part B) - "
                      "not a pass", proceed=True, inputs=inputs, reason="not-built")
    done = _skillc(["charter", "overlap", str(skill.collection)], skill.collection)
    if done.returncode == 0:
        return Result("1-overlap", "overlap", "EXAMINED", "overlaps are proposals for the owner, never findings "
                      "against the skill", proceed=True, inputs=inputs,
                      lines=[f"  {line}" for line in done.stdout.splitlines() if line.strip()][:20])
    if done.returncode == 3:
        return Result("1-overlap", "overlap", "NOT EXAMINED", "no comparator - the collection was not compared, "
                      "which is not a pass", proceed=True, inputs=inputs, reason="no-comparator")
    return Result("1-overlap", "overlap", "UNKNOWN", f"`charter overlap` refused (exit {done.returncode}) - not a "
                  "pass", proceed=True, inputs=inputs, reason="refused")


def _round2_args(skill: Skill, options: Options) -> list[str]:
    args = ["inspect", str(skill.collection), "--json"]
    if options.offline:
        args.append("--offline")
    if options.issue_states is not None:
        args += ["--issue-states", str(options.issue_states.resolve())]
    if options.repo:
        args += ["--repo", options.repo]
    for flag, values in (("--include", options.include), ("--exclude", options.exclude), ("--map", options.maps)):
        for value in values:
            args += [flag, value]
    if options.include:  # the default surface already holds a native skill; a command needs naming
        args += ["--include", skill.text_rel]
    elif skill.command:
        args += ["--include", "**/SKILL.md", "--include", skill.text_rel]
    return args


def _inspected(skill: Skill, options: Options) -> bool | None:
    """Ask inspect itself, with its own matcher, whether the passed-through
    surface keeps this skill: the same --exclude list, and only this skill's
    path included. None when inspect could not answer."""
    args = ["inspect", str(skill.collection), "--json", "--offline", "--include", skill.text_rel]
    for value in options.exclude:
        args += ["--exclude", value]
    try:
        report = json.loads(_skillc(args, skill.collection).stdout)
    except json.JSONDecodeError:
        return None
    subjects = report.get("collection", {}).get("subjects")
    return subjects == 1 if isinstance(subjects, int) else None


def _origin(collection: Path) -> str:
    """The RAW `origin` URL, or "none": inspect infers its repository from it
    (orchestrator ruling rev 57: the raw URL, no copied parser; a cosmetic URL
    change only costs a free re-run)."""
    try:
        done = subprocess.run(["git", "-C", str(collection), "remote", "get-url", "origin"], capture_output=True,
                              text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "unreadable"
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else "none"


def _skipped_subjects(skill: Skill, options: Options) -> str:
    """Files inspect could add from the directories the collection digest
    skips: their names are LISTED, and only include-glob matches are hashed.
    Past SKIPPED_WALK_CAP entries it answers "over-cap", which round 2 reads as
    UNKNOWN rather than scanning on."""
    patterns = list(options.include) or ["**/SKILL.md"]
    listed, matches = 0, []
    for top, dirs, _files in os.walk(skill.collection):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for name in [d for d in dirs if d in _SKIP_DIRS]:
            dirs.remove(name)
            base = Path(top, name)
            for sub_top, sub_dirs, sub_files in os.walk(base):
                rel_top = Path(sub_top).relative_to(skill.collection).as_posix()
                if rel_top == ".skillc/gauntlet" or rel_top.startswith(".skillc/gauntlet/"):
                    sub_dirs[:] = []  # the engine's own state
                    continue
                listed += len(sub_dirs) + len(sub_files)
                if listed > SKIPPED_WALK_CAP:
                    return "over-cap"
                for f in sub_files:
                    rel = f"{rel_top}/{f}"
                    if any(fnmatch.fnmatch(rel, v) for pat in patterns for v in _glob_variants(pat)):
                        matches.append((rel, _file_digest(Path(sub_top, f))))
    return _sha(json.dumps(sorted(matches)).encode())


def _round2_inputs(skill: Skill, options: Options) -> dict[str, str]:
    return {"skill": _file_digest(skill.text), "collection": _tree_digest(skill.collection),
            # digests, never the URL itself: the record holds no host detail, and a URL can carry a credential
            "origin": _sha(_origin(skill.collection).encode()),
            "skipped-subjects": _skipped_subjects(skill, options),
            "issue-states": _file_digest(options.issue_states) if options.issue_states else "none",
            "options": _sha(json.dumps({"offline": options.offline, "repo": options.repo or "",
                                        "include": options.include, "exclude": options.exclude,
                                        "maps": options.maps}, sort_keys=True).encode())}


def round2(skill: Skill, options: Options) -> Result:
    inputs = _round2_inputs(skill, options)
    if inputs["skipped-subjects"] == "over-cap":
        return Result("2", "inspect", "UNKNOWN", f"the skipped directories (.venv, node_modules, .skillc) hold more "
                      f"than {SKIPPED_WALK_CAP} entries, so what inspect could include from them was not fingerprinted"
                      " - not a pass", proceed=False, inputs=inputs, reason="skipped-cap")
    member = _inspected(skill, options) if options.exclude else True
    if not member:
        why = "an --exclude drops this skill" if member is False else "inspect could not say whether it is a subject"
        return Result("2", "inspect", "UNKNOWN", f"{why}, so it was not shown inspected", proceed=False,
                      inputs=inputs, reason="excluded" if member is False else "membership-unknown")
    done = _skillc(_round2_args(skill, options), skill.collection)
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        return Result("2", "inspect", "UNKNOWN", f"`skillc inspect` printed no report (exit {done.returncode})",
                      proceed=False, inputs=inputs, reason="no-report")
    return read_round2(skill, report, inputs)


def read_round2(skill: Skill, report: dict, inputs: dict[str, str]) -> Result:
    """Round 2's reading of one `inspect --json` report, in ONE place: the
    engine and round 5 (#737, `gauntlet verdict --inspect`) both use it."""
    if report.get("verdict") == "NOTHING-INSPECTED":
        return Result("2", "inspect", "UNKNOWN", "nothing inspected - not a clean result", proceed=False,
                      inputs=inputs, reason="nothing-inspected")
    rules = report.get("rules", {})
    unexamined = sorted(r for r, v in rules.items() if not v.get("examined", False))
    own = [f for f in report.get("findings", []) if f.get("path") == skill.text_rel]
    own_unknown = [u for u in report.get("unknown", []) if u.get("path") == skill.text_rel]
    # emphasised rule statements are sorted under `rule_lines`, apart from `findings` (docs/specs/inspect.md)
    own_rules = [r for r in report.get("rule_lines", []) if r.get("path") == skill.text_rel]
    # error-severity hits are reported under `errors`, not `findings` (docs/specs/inspect.md)
    errors = [e for e in report.get("errors", []) if e.get("path") == skill.text_rel]
    errors += [f for f in own if rules.get(f.get("rule"), {}).get("severity") == "error"]
    lines = [f"  ERROR {e.get('path')}:{e.get('line')} {e.get('rule')} - {e.get('detail')}"
             for e in errors if e not in own]
    lines += [f"  {f.get('bucket')} {f.get('path')}:{f.get('line')} {f.get('rule')} - {f.get('detail')}"
              for f in sorted(own, key=lambda f: (str(f.get("bucket")), int(f.get("line") or 0)))]
    lines += [f"  rule {r.get('bucket')} {r.get('path')}:{r.get('line')} - {r.get('reason') or r.get('detail') or ''}"
              .rstrip(" -") for r in sorted(own_rules, key=lambda r: int(r.get("line") or 0))]
    buckets = {b: sum(f.get("bucket") == b for f in own) for b in ("A", "B", "C", "D", "UNSORTED")}
    rule_buckets = {b: sum(r.get("bucket") == b for r in own_rules) for b in buckets}
    counted = (", ".join(f"{b}={n}" for b, n in buckets.items()) + "; rule statements "
               + ", ".join(f"{b}={n}" for b, n in rule_buckets.items() if n) if own_rules else
               ", ".join(f"{b}={n}" for b, n in buckets.items()))
    facts: dict[str, object] = {
        "file": skill.text_rel, "buckets": buckets, "rule_statements": len(own_rules),
        "errors": [{"line": e.get("line"), "detail": str(e.get("detail") or "")} for e in errors],
        "unknown": [{"line": u.get("line"), "detail": str(u.get("detail") or "")} for u in own_unknown],
        "unexamined": unexamined,
        "removable": [{"line": f.get("line"), "detail": str(f.get("detail") or "")} for f in own
                      if f.get("bucket") == "D"],
        # every OTHER finding is the owner's to decide; the report names them (counter-model review)
        "to_decide": [{"line": f.get("line"), "detail": str(f.get("detail") or "")} for f in own
                      if f.get("bucket") != "D" and f not in errors]}
    if errors:
        return Result("2", "inspect", "FAIL", f"{len(errors)} error finding(s) on {skill.text_rel} ({counted})",
                      proceed=False, inputs=inputs, lines=lines, reason="errors", facts=facts)
    if own_unknown or unexamined:
        why = (f"{len(own_unknown)} UNKNOWN on this skill" if own_unknown else
               f"rule(s) not examined: {', '.join(unexamined)}")
        return Result("2", "inspect", "UNKNOWN", f"{why} - not a pass ({counted})", proceed=False, inputs=inputs,
                      lines=lines, reason="unknown-on-skill" if own_unknown else "unexamined-rule", facts=facts)
    return Result("2", "inspect", "PASS", f"{len(own)} finding(s) on this skill, sorted {counted}; nothing is "
                  "trimmed by this run", proceed=True, inputs=inputs, lines=lines, facts=facts)


def round3(tool: bool) -> Result:
    inputs = {"tool:round3": "available" if tool else "absent"}
    if tool:
        return Result("3", "trials", "NOT RUN", "round 3 exists but part 1 never runs paid trials (#738)",
                      proceed=False, inputs=inputs, reason="not-run")
    return Result("3", "trials", "NOT BUILT", "rounds 3-5 are not built (#736, #737)", proceed=False,
                  inputs=inputs, reason="not-built")


# --------------------------------------------------------------------- record

#: Rounds the engine does not run but must carry: round 5 is the owner's
#: recorded ruling (`gauntlet rule`, #737), never re-derived by `run`.
KEPT_ROUNDS = ("5",)


def render_record(skill: Skill, results: list[Result], kept: dict[str, dict[str, object]] | None = None) -> bytes:
    rounds: dict[str, object] = {r.round: {"name": r.name, "verdict": r.verdict, "detail": r.detail,
                                           "proceed": r.proceed, "inputs": dict(sorted(r.inputs.items()))}
                                 for r in results}
    rounds.update({k: v for k, v in (kept or {}).items() if k in KEPT_ROUNDS})
    body = {"kind": RECORD_KIND, "schema": RECORD_SCHEMA, "skill": skill.rel, "rounds": rounds}
    return (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()


def load_record(path: Path) -> dict[str, dict[str, object]]:
    if path.is_symlink():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("kind") != RECORD_KIND or data.get("schema") != RECORD_SCHEMA:
        return {}
    rounds = data.get("rounds")
    return rounds if isinstance(rounds, dict) else {}


class UnsafeRecord(Exception):
    """The record's path is a symlink, or not a regular file: never written through."""


def _write_state(path: Path, data: bytes) -> None:
    """Every engine-written file (the record, the display cache): refused when
    the path is a symlink or not a regular file; written to a temp file created
    EXCLUSIVELY (O_EXCL | O_NOFOLLOW, as #733 creates its reports), then renamed
    over the path, so it can never land in the file a link points at."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise UnsafeRecord(f"{path.name} is a symlink or not a regular file - refusing to write through it")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    if temp.is_symlink() or temp.exists():
        temp.unlink()
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.replace(temp, path)


def write_record(path: Path, data: bytes) -> bool:
    """Write only when the bytes would change; True when written."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise UnsafeRecord(f"{path.name} is a symlink or not a regular file - refusing to write through it")
    if path.is_file() and path.read_bytes() == data:
        return False
    _write_state(path, data)
    return True


# ------------------------------------------------- local display (never published)

def _display_path(skill: Skill, options: Options) -> Path | None:
    """The finding lines a cached run re-shows. They stay LOCAL, beside the draft
    (`.skillc/` ignores itself), because the published record holds digests and
    verdicts only. No main checkout and no --draft-dir: no display cache."""
    if options.draft_dir is not None:
        return _given_draft_dir(options.draft_dir) / skill.slug / "display.json"
    main = main_checkout(skill.collection)
    if main is None:
        return None
    _no_symlink_below(main / ".skillc" / "gauntlet" / skill.slug, main)
    return main / ".skillc" / "gauntlet" / skill.slug / "display.json"


def _load_display(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None or path.is_symlink():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_display(path: Path, data: dict[str, dict[str, object]]) -> None:
    _ensure_ignored(path.parent)
    _write_state(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode())


# --------------------------------------------------------------------- the run

def _cached(previous: dict[str, dict[str, object]], key: str, inputs: dict[str, str]) -> Result | None:
    entry = previous.get(key)
    if not isinstance(entry, dict) or entry.get("inputs") != dict(sorted(inputs.items())):
        return None
    return Result(key, str(entry.get("name")), str(entry.get("verdict")), str(entry.get("detail")),
                  bool(entry.get("proceed")), dict(inputs), cached=True)


def _next_line(skill: Skill, stopped: Result, draft: Path) -> str:
    v, r = stopped.verdict, stopped.round
    if r == "1" and v == "STOP" and not skill.charter.is_file():
        return (f"NEXT: owner reviews the draft {draft} clause by clause, runs `skillc charter confirm {draft} "
                f"--answers <answers> --out {skill.charter_rel}`, commits the charter, then re-runs the gauntlet")
    if r == "1" and v == "STOP":
        return f"NEXT: owner approves the intent and authority clauses of {skill.charter_rel}, then re-runs"
    if r == "1" and v == "FAIL":
        return f"NEXT: fix the findings `skillc contracts {skill.collection}` lists for {skill.charter_rel}"
    if r == "1" and v == "NOT BUILT":
        return "NEXT: round 1 needs `skillc charter` (#726); re-run on a skillc that has it"
    if r == "1":
        return "NEXT: give the skill a description, a stated duty or a usage log (--usage), then re-run"
    if r == "2" and v == "FAIL":
        return f"NEXT: fix the error findings `skillc inspect` reports on {skill.text_rel}, then re-run"
    if r == "2":
        return "NEXT: supply what round 2 could not read (issue states, or drop --offline), then re-run"
    return ("NEXT: act on round 2's findings by hand; rounds 3-5 (#736, #737) give the keep/trim/retire verdict "
            "once built (#738)")


def run(collection: Path, skill_arg: str, options: Options, out=print) -> int:
    try:
        skill = resolve_skill(collection, skill_arg)
        logs = discover_usage(skill, options)
        # #759: every component from the collection root to the charter, and
        # where it resolves, before anything is read beside it or written there.
        _no_symlink_below(skill.charter.parent, skill.collection)
        _inside(skill.charter.parent, skill.collection)
        draft_dir = _draft_dir(skill, options) if not skill.charter.is_file() else None
        display_path = _display_path(skill, options)
    except UsageError as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return EXIT_USAGE
    record = skill.charter.parent / RECORD_NAME if draft_dir is None else draft_dir / RECORD_NAME
    draft = (draft_dir or skill.charter.parent) / DRAFT_NAME
    previous = load_record(record)
    if draft_dir is not None:
        _ensure_ignored(draft_dir)
    display = _load_display(display_path)
    # Live issue states have no digest, so a round 2 that reads them is never served from cache.
    live_states = not options.offline and options.issue_states is None

    def step(key: str, inputs: dict[str, str], fresh) -> Result:
        inputs = {**inputs, "skillc": implementation()}  # another skillc's verdict is never reused
        hit = None if key == "2" and live_states else _cached(previous, key, inputs)
        # a cached "draft ready" whose draft has since been removed is re-drafted
        if hit is not None and not (key == "1" and hit.verdict == "STOP" and not draft.is_file()
                                    and not skill.charter.is_file()):
            shown = display.get(key, {})
            lines = shown.get("lines")
            if shown.get("inputs") == dict(sorted(inputs.items())) and isinstance(lines, list):
                hit.lines = [str(line) for line in lines]
                # #783: what the plain report says, from the same host-local cache
                hit.reason = str(shown.get("reason") or "")
                facts = shown.get("facts")
                hit.facts = {str(k): v for k, v in facts.items()} if isinstance(facts, dict) else {}
            elif hit.verdict in ("PASS", "FAIL", "UNKNOWN") and key == "2":
                hit.lines = [("  (cached: the finding lines are not on this host; change an input or delete the "
                              "record to list them)")]
            return hit
        result = fresh()
        result.inputs = {**result.inputs, "skillc": implementation()}
        return result

    tools = {name: available(words, skill.collection) for name, words in
             (("charter", ["charter", "draft"]), ("overlap", ["charter", "overlap"]),
              ("round3", ["gauntlet", "round3"]))}
    plan = [
        ("0", lambda: _round0_inputs(skill, logs, options.aliases), lambda: round0(skill, logs, options.aliases)),
        ("1", lambda: _round1_inputs(skill, logs, tools["charter"], options),
         lambda: round1(skill, logs, options, draft, tools["charter"])),
        ("1-overlap", lambda: _overlap_inputs(skill, tools["overlap"]),
         lambda: round1_overlap(skill, tools["overlap"])),
        ("2", lambda: _round2_inputs(skill, options), lambda: round2(skill, options)),
        ("3", lambda: {"tool:round3": "available" if tools["round3"] else "absent"},
         lambda: round3(tools["round3"])),
    ]

    # #783: the machine lines are collected, then printed AFTER the plain
    # report (or alone, or not at all), byte-identical to what they were.
    machine: list[str] = []
    final_out = out
    out = machine.append
    out(f"GAUNTLET {skill.rel} (collection {skill.collection.name})")
    results: list[Result] = []
    stopped: Result | None = None
    for key, inputs, fresh in plan:
        try:
            result = step(key, inputs(), fresh)
        except UnsafeRecord as exc:
            if options.output != "plain":  # what was printed before #783 is still printed, unless suppressed
                for line in machine:
                    final_out(line)
            print(f"skillc: {exc}", file=sys.stderr)
            return EXIT_USAGE
        results.append(result)
        out(f"ROUND {key} {result.name}: {result.verdict} - {result.detail}{' (cached)' if result.cached else ''}")
        for line in result.lines:
            out(line)
        if not result.proceed:
            stopped = result
            break
    assert stopped is not None, "round 3 never proceeds in part 1"
    try:
        written = write_record(record, render_record(skill, results, previous))
        if display_path is not None:
            _save_display(display_path, {r.round: {"inputs": dict(sorted(r.inputs.items())), "lines": r.lines,
                                                   "reason": r.reason, "facts": r.facts}
                                         for r in results if not r.cached or r.round in display})
    except UnsafeRecord as exc:
        if options.output != "plain":
            for line in machine:
                final_out(line)
        print(f"skillc: {exc}", file=sys.stderr)
        return EXIT_USAGE
    out(f"RECORD: {record.relative_to(skill.collection) if record.is_relative_to(skill.collection) else record}"
        f" ({'written' if written else 'unchanged'}; the engine never commits it)")
    out(_next_line(skill, stopped, draft))
    out(f"GAUNTLET: stopped at round {stopped.round} ({stopped.verdict}) - {NOT_A_VERDICT}")
    if options.output in ("both", "plain"):
        from .gauntlet_report import render  # the plain report's wording lives in one module

        for line in render(skill, results, stopped, draft=draft, charter_create=available(
                ["charter", "create"], skill.collection), machine_follows=options.output == "both",
                next_step=_next_line(skill, stopped, draft)).splitlines():
            final_out(line)
        if options.output == "both":
            final_out("")
    if options.output in ("both", "machine"):
        for line in machine:
            final_out(line)
    return EXIT_FAILED if stopped.verdict == "FAIL" else EXIT_STOPPED

