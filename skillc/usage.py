"""`skill-usage` records: which skill version ran, where, and how it ended (#719).

The skill gauntlet (#718) cannot tell whether a skill got better or worse
without a history of real use, and history only accumulates once something
writes it. This module is that writer and its checker:

- a `skill-usage` record kind, one JSON object per line in an append-only
  usage log (`usage.jsonl`, or any `*.usage.jsonl`), validated by four rules
  that `skillc check-records` runs and `skillc selftest` proves;
- a Claude Code hook handler (`skillc usage hook`) that writes a `start` for a
  `Skill` tool call or a typed `/<skill>`, and an `end` at session stop, so
  recording is never left to the model;
- `skillc usage end`, which a skill MAY call to declare its own outcome;
- `skillc usage report`, the minimal reader (counts, outcome mix, UNKNOWN rate).

VOCABULARY IS REUSED, NOT RE-INVENTED. `origin` names who saw the fact
(`observed` by the hook, or `declared` by the skill through `usage end`);
`coverage` is records.py's `OBSERVATION_COVERAGE`; a field that could not be
observed is the literal `"UNKNOWN"`, never omitted, empty or zero - the same
silence-is-not-absence rule records.md states for `skill-invocations`.

WHAT A USAGE LOG IS NOT. It is not an evaluation record and carries no
verdict: a `completed` outcome is a skill's own account, or the hook's
`UNKNOWN`, never a grade. Nothing here establishes that a record is true; the
rules establish that it is well formed, private and internally paired.

PRIVACY. A record carries identifiers and outcomes only. The key set is
CLOSED, so prompt text or transcript content has nowhere to go, and every
string is refused when it holds an absolute home-directory path or an email
address. The hook never reads the transcript.

Stdlib only (AGENTS.md). The hook is fail-open: it never fails the session
that runs it, and writes nothing it would itself refuse.
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from . import materialize as m
from . import records
from .spec import FrontmatterError

SKILL_USAGE = "skill-usage"
#: The envelope versions a usage log may carry - an EXACT set, honoured the way
#: `records.record_envelope` honours its own: missing, non-integer (including a
#: bool) and unsupported versions are refused, never read on a guess. Version 1
#: here is unrelated to the evaluation envelope's retired v1: this is a
#: separate kind with its own history, starting at 1.
USAGE_VERSIONS = (1,)

UNKNOWN = "UNKNOWN"
EVENTS = ("start", "end")
INVOCATIONS = ("explicit", "model-selected", UNKNOWN)
#: `observed`: the hook saw it happen. `declared`: the skill said so itself.
ORIGINS = ("observed", "declared")
COVERAGE = records.OBSERVATION_COVERAGE
OUTCOMES = ("completed", "stopped", "abandoned", UNKNOWN)
CLIENTS = ("claude-code", "codex")

#: The CLOSED key set, in the order a writer emits it. Every key is required;
#: no other key is allowed (privacy: there is nowhere for prompt text to go).
FIELDS = (
    "kind", "version", "event", "skill", "skill_digest", "collection", "invocation",
    "origin", "coverage", "repo", "commit", "outcome", "stop_reason", "session",
    "client", "model", "at",
)

#: Fields whose value may be `"UNKNOWN"`, and so count toward the report's rate.
UNKNOWABLE = ("skill_digest", "collection", "invocation", "repo", "commit", "outcome", "model")

DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
SHA_RE = re.compile(r"[0-9a-f]{7,64}")
NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,99})")
#: `<checkout name>@<commit>`. The revision is a commit SHA, never a dotted
#: version: that keeps `name@rev` from ever reading as an email address.
COLLECTION_RE = re.compile(rf"(?:{NAME_RE.pattern})@{SHA_RE.pattern}")
REPO_RE = re.compile(rf"(?:{NAME_RE.pattern})/(?:{NAME_RE.pattern})")
#: A skill name as the client invokes it: `name` or `namespace:name`.
SKILL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}(?::[A-Za-z0-9][A-Za-z0-9_.-]{0,99})?")
STOP_REASON_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,127}")
AT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")

#: Privacy patterns. `HOME_PATH_RE` is a superset of leak.py's (which needs a
#: name after the prefix): here ANY `/home/` or `/Users/` substring is refused.
HOME_PATH_RE = re.compile(r"/(?:home|Users)/")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

LOG_NAME = "usage.jsonl"
LOG_SUFFIX = ".usage.jsonl"
STATE_DIR = ".skillc"


# ---------------------------------------------------------------- the subject


@dataclass(frozen=True)
class Entry:
    """One line of a usage log: its 1-based line number and the object on it."""

    line: int
    data: dict[str, object]


@dataclass
class UsageLog:
    """One usage log file. A line that does not parse makes the whole log
    unreadable (`parse_error`), exactly as an unreadable `.json` record is:
    every other rule declines it, and only the envelope rule speaks."""

    path: Path
    entries: list[Entry] = field(default_factory=list)
    parse_error: str | None = None


def is_log_name(name: str) -> bool:
    """Only `usage.jsonl` and `*.usage.jsonl` are usage logs. Evidence bundles
    already hold transcript `.jsonl` files; reading those as usage logs would
    refuse every existing bundle."""
    return name == LOG_NAME or name.endswith(LOG_SUFFIX)


def load_log(path: Path) -> UsageLog:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return UsageLog(path=path, parse_error=str(exc))
    entries: list[Entry] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except ValueError as exc:
            return UsageLog(path=path, parse_error=f"line {number}: {exc}")
        if not isinstance(value, dict):
            return UsageLog(path=path, parse_error=f"line {number}: not a JSON object")
        entries.append(Entry(number, value))
    return UsageLog(path=path, entries=entries)


def discover_logs(root: Path) -> list[UsageLog]:
    """Every usage log under `root` (or `root` itself), in a stable order."""
    if root.is_file():
        return [load_log(root)] if is_log_name(root.name) else []
    if not root.is_dir():
        return []
    return [load_log(p) for p in sorted(root.rglob("*")) if p.is_file() and is_log_name(p.name)]


# ---------------------------------------------------------------- the rules


def _envelope_problem(data: Mapping[str, object]) -> str | None:
    version = data.get("version")
    if version is None:
        return "no envelope version; an unversioned record cannot be read safely"
    if isinstance(version, bool) or not isinstance(version, int):
        return f"envelope version is not an integer: {version!r}"
    if version not in USAGE_VERSIONS:
        return (
            f"envelope version {version} is not one this build reads for {SKILL_USAGE} "
            f"({list(USAGE_VERSIONS)}); refused rather than read on a guess"
        )
    if data.get("kind") != SKILL_USAGE:
        return f"kind {data.get('kind')!r} is not {SKILL_USAGE!r}; a usage log holds only {SKILL_USAGE} records"
    return None


def usage_envelope(log: UsageLog) -> Iterator[str]:
    """The log reads, and every line declares a kind and version this build reads."""
    if log.parse_error is not None:
        yield f"unreadable usage log: {log.parse_error}"
        return
    for entry in log.entries:
        problem = _envelope_problem(entry.data)
        if problem:
            yield f"line {entry.line}: {problem}"


def _readable(log: UsageLog) -> Iterator[Entry]:
    """Entries the envelope accepts; the other rules read only these, so a bad
    envelope case trips the envelope rule and nothing else."""
    if log.parse_error is not None:
        return
    for entry in log.entries:
        if _envelope_problem(entry.data) is None:
            yield entry


def _value_problem(key: str, value: object) -> str | None:
    if not isinstance(value, str):
        return f"is {value!r}, not a string; write \"{UNKNOWN}\" for what could not be observed"
    if not value.strip():
        return f"is empty; a field that could not be observed is \"{UNKNOWN}\", never empty"
    closed = {
        "event": EVENTS, "invocation": INVOCATIONS, "origin": ORIGINS,
        "coverage": COVERAGE, "outcome": OUTCOMES, "client": CLIENTS,
    }
    if key in closed:
        return None if value in closed[key] else f"{value!r} is not one of {list(closed[key])}"
    shaped: dict[str, re.Pattern[str]] = {
        "skill": SKILL_NAME_RE, "skill_digest": DIGEST_RE, "collection": COLLECTION_RE,
        "repo": REPO_RE, "commit": SHA_RE, "session": records.ID_RE, "model": MODEL_RE, "at": AT_RE,
    }
    if value == UNKNOWN and key in UNKNOWABLE:
        return None
    if not shaped[key].fullmatch(value):
        return f"{value!r} is malformed; expected {shaped[key].pattern}" + (
            f" or \"{UNKNOWN}\"" if key in UNKNOWABLE else ""
        )
    if key == "at":
        try:
            _dt.datetime.fromisoformat(value)
        except ValueError:
            return f"{value!r} is not a real RFC 3339 UTC time"
    return None


def usage_fields(log: UsageLog) -> Iterator[str]:
    """Every field is present, in its vocabulary, with UNKNOWN for what could not be seen."""
    for entry in _readable(log):
        data = entry.data
        for key in FIELDS[2:]:
            if key not in data:
                yield (
                    f"line {entry.line}: field {key} is absent; a field that could not be "
                    f"observed is \"{UNKNOWN}\", never omitted"
                )
                continue
            if key == "stop_reason":
                reason = data[key]
                if reason is not None and not (isinstance(reason, str) and STOP_REASON_RE.fullmatch(reason)):
                    yield f"line {entry.line}: stop_reason {reason!r} is not null or a token ({STOP_REASON_RE.pattern})"
                continue
            problem = _value_problem(key, data[key])
            if problem:
                yield f"line {entry.line}: field {key} {problem}"
        if data.get("client") == "codex" and data.get("coverage") != "unsupported":
            yield (
                f"line {entry.line}: a codex record declares coverage {data.get('coverage')!r}; "
                f"no route observes Codex skill use, so its coverage is 'unsupported'"
            )
        if data.get("origin") == "observed" and data.get("coverage") == "unsupported":
            yield f"line {entry.line}: origin 'observed' through coverage 'unsupported'; nothing could observe it"


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def usage_privacy(log: UsageLog) -> Iterator[str]:
    """Only identifiers and outcomes: no extra field, home path or email address."""
    for entry in _readable(log):
        for key in entry.data:
            if key not in FIELDS:
                yield (
                    f"line {entry.line}: field {key!r} is not allowed; a usage record carries "
                    f"identifiers and outcomes only, never prompt text or transcript content"
                )
        for text in _strings(entry.data):
            if HOME_PATH_RE.search(text):
                yield f"line {entry.line}: a value contains an absolute home-directory path"
            if EMAIL_RE.search(text):
                yield f"line {entry.line}: a value contains an email address"


def _key(data: Mapping[str, object]) -> tuple[str, str] | None:
    session, skill = data.get("session"), data.get("skill")
    if isinstance(session, str) and isinstance(skill, str):
        return session, skill
    return None


def pair(log: UsageLog) -> tuple[list[tuple[Entry, Entry | None]], list[Entry]]:
    """`(invocations, orphans)`: each `start` with the `end` that closed it (or
    None), first-in first-out per (session, skill), and every `end` with no
    open `start` before it."""
    open_starts: dict[tuple[str, str], list[int]] = {}
    pairs: list[tuple[Entry, Entry | None]] = []
    orphans: list[Entry] = []
    for entry in _readable(log):
        key = _key(entry.data)
        if key is None:
            continue
        if entry.data.get("event") == "start":
            open_starts.setdefault(key, []).append(len(pairs))
            pairs.append((entry, None))
        elif entry.data.get("event") == "end":
            waiting = open_starts.get(key)
            if waiting:
                index = waiting.pop(0)
                pairs[index] = (pairs[index][0], entry)
            else:
                orphans.append(entry)
    return pairs, orphans


def unended(log: UsageLog) -> list[Entry]:
    """Starts no end closed: REPORTED as outcome UNKNOWN, never refused (a
    crashed session cannot write its end)."""
    return [start for start, end in pair(log)[0] if end is None]


def usage_pairing(log: UsageLog) -> Iterator[str]:
    """Every end closes an earlier start; a declared completion has its end."""
    pairs, orphans = pair(log)
    for entry in orphans:
        yield (
            f"line {entry.line}: end for skill {entry.data.get('skill')!r} in session "
            f"{entry.data.get('session')!r} has no matching earlier start; an orphan end is refused"
        )
    for start, end in pairs:
        if end is None and start.data.get("outcome") == "completed" and start.data.get("origin") == "declared":
            yield (
                f"line {start.line}: start declares outcome 'completed' but no end event exists; "
                f"a completion is recorded by its end"
            )


# ---------------------------------------------------------------- writing


def _git(cwd: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = done.stdout.strip()
    return out if done.returncode == 0 and out else None


def destination(cwd: Path) -> Path | None:
    """`<main checkout>/.skillc/usage.jsonl`, resolved through `git-common-dir`
    so a run from a linked worktree lands in the SAME file as one from the main
    checkout (CPP #471's lesson). None outside a non-bare git checkout."""
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common is None:
        return None
    common_dir = Path(common)
    if common_dir.name != ".git":
        return None  # a bare repository has no main checkout to write into
    return common_dir.parent / STATE_DIR / LOG_NAME


def repo_identity(cwd: Path) -> tuple[str, str]:
    """`(owner/name, HEAD)` of the checkout `cwd` is in, each UNKNOWN when unseen."""
    commit = _git(cwd, "rev-parse", "HEAD")
    url = _git(cwd, "remote", "get-url", "origin") or ""
    match = re.search(r"[:/]([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$", url)
    repo = f"{match.group(1)}/{match.group(2)}" if match else UNKNOWN
    if not REPO_RE.fullmatch(repo):
        repo = UNKNOWN
    return repo, commit if commit and SHA_RE.fullmatch(commit) else UNKNOWN


def resolve_skill(name: str, cwd: Path, home: Path) -> Path | None:
    """The entry file of the installed skill or command `name`, by EXACT lookup.

    Never a substring match (records.md's config-drift-checker trap: a short
    name such as `run` matching unrelated input). `name` is `skill` or
    `namespace:name`; each segment must be a plain name, so `..` or a slash
    cannot walk out of the skills directories. Personal definitions are tried
    before the project's."""
    if not SKILL_NAME_RE.fullmatch(name):
        return None
    project = Path(_git(cwd, "rev-parse", "--show-toplevel") or cwd)
    bases = (home / ".claude", project / ".claude")
    if ":" in name:
        namespace, leaf = name.split(":", 1)
        candidates = [base / "commands" / namespace / f"{leaf}.md" for base in bases]
    else:
        candidates = [base / "skills" / name / "SKILL.md" for base in bases]
        candidates += [base / "commands" / f"{name}.md" for base in bases]
    return next((c for c in candidates if c.is_file()), None)


def skill_digest(entry_file: Path | None) -> str:
    """One `sha256:` over the #424 pin pair of the entry file.

    `profile.skill_md_digests` is the ONE definition of a skill's
    `(description_digest, body_digest)`; this hashes the two together so a
    change to either the description (what selection reads) or the body
    changes the digest. UNKNOWN when the file cannot be read or parsed."""
    if entry_file is None:
        return UNKNOWN
    from . import profile  # deferred: the hook should not pay for it when no skill ran

    try:
        description_digest, body_digest = profile.skill_md_digests(entry_file.read_bytes())
    except (OSError, FrontmatterError, ValueError):
        return UNKNOWN
    return m.sha256_bytes(f"{description_digest}\n{body_digest}\n".encode())


def collection_of(entry_file: Path | None) -> str:
    """`<checkout name>@<HEAD>` of the git checkout the skill's real file lives
    in (a symlinked install resolves to its source), else UNKNOWN. Only the
    directory's NAME is kept, never its path."""
    if entry_file is None:
        return UNKNOWN
    real = entry_file.resolve().parent
    common, head = _git(real, "rev-parse", "--path-format=absolute", "--git-common-dir"), _git(real, "rev-parse", "HEAD")
    if common is None or head is None or Path(common).name != ".git":
        return UNKNOWN
    # The MAIN checkout's name (via git-common-dir), never a linked worktree's:
    # one collection keeps one name however many worktrees it is run from.
    value = f"{Path(common).parent.name}@{head}"
    return value if COLLECTION_RE.fullmatch(value) else UNKNOWN


def now_utc() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_record(**values: object) -> dict[str, object]:
    record: dict[str, object] = {"kind": SKILL_USAGE, "version": USAGE_VERSIONS[-1]}
    for key in FIELDS[2:]:
        record[key] = values.get(key, None if key == "stop_reason" else UNKNOWN)
    return record


def record_problems(record: Mapping[str, object]) -> list[str]:
    """What the envelope, fields and privacy rules would say about `record`
    alone - the writer refuses to append anything its own checker refuses."""
    log = UsageLog(path=Path("<pending>"), entries=[Entry(1, dict(record))])
    return [*usage_envelope(log), *usage_fields(log), *usage_privacy(log)]


def append(path: Path, new: Sequence[Mapping[str, object]]) -> None:
    """Append under an exclusive lock. Creating the state directory also
    writes its own `.gitignore` (`*`), so the log is ignored by default
    without editing the repository's own ignore file."""
    state = path.parent
    if not state.is_dir():
        state.mkdir(parents=True, exist_ok=True)
        (state / ".gitignore").write_text("*\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            for record in new:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _open_starts(path: Path, session: str, skill: str | None = None) -> list[Entry]:
    if not path.is_file():
        return []
    return [
        start for start in unended(load_log(path))
        if start.data.get("session") == session and (skill is None or start.data.get("skill") == skill)
    ]


def _end_for(start: Entry, cwd: Path, **values: object) -> dict[str, object]:
    repo, commit = repo_identity(cwd)
    carried = {k: start.data.get(k) for k in ("skill", "skill_digest", "collection", "invocation",
                                               "coverage", "session", "client", "model")}
    return make_record(event="end", repo=repo, commit=commit, at=now_utc(), **{**carried, **values})


#: `UserPromptSubmit`: the typed command must be the WHOLE first token.
TYPED_RE = re.compile(rf"/({SKILL_NAME_RE.pattern})(?:\s|$)")


def hook_records(payload: Mapping[str, object], home: Path) -> tuple[Path | None, list[dict[str, object]]]:
    """`(destination, records to append)` for one Claude Code hook payload.

    - `PreToolUse` on the `Skill` tool: a `start`, `invocation: model-selected`.
    - `UserPromptSubmit` whose prompt begins `/<name>` naming an installed skill
      or command by exact lookup: a `start`, `invocation: explicit`. A built-in
      (`/clear`) or a path (`/tmp/x`) resolves to nothing and writes nothing.
    - `Stop` / `SessionEnd`: an `end`, `outcome: UNKNOWN`, for every start of
      this session no end has closed.
    Anything else writes nothing."""
    session = payload.get("session_id")
    cwd = Path(str(payload.get("cwd") or os.getcwd()))
    event = payload.get("hook_event_name")
    if not isinstance(session, str) or not records.ID_RE.fullmatch(session):
        return None, []
    path = destination(cwd)
    if path is None:
        return None, []
    model = payload.get("model")
    model = model if isinstance(model, str) and MODEL_RE.fullmatch(model) else UNKNOWN

    name: str | None = None
    invocation = UNKNOWN
    if event == "PreToolUse" and payload.get("tool_name") == "Skill":
        tool_input = payload.get("tool_input")
        raw = tool_input.get("skill") if isinstance(tool_input, dict) else None
        if isinstance(raw, str) and SKILL_NAME_RE.fullmatch(raw.removeprefix("/")):
            name, invocation = raw.removeprefix("/"), "model-selected"
    elif event == "UserPromptSubmit":
        prompt = payload.get("prompt")
        match = TYPED_RE.match(prompt.lstrip()) if isinstance(prompt, str) else None
        if match and resolve_skill(match.group(1), cwd, home) is not None:
            name, invocation = match.group(1), "explicit"
    elif event in ("Stop", "SessionEnd"):
        return path, [_end_for(start, cwd, origin="observed") for start in _open_starts(path, session)]

    if name is None:
        return path, []
    entry_file = resolve_skill(name, cwd, home)
    repo, commit = repo_identity(cwd)
    return path, [make_record(
        event="start", skill=name, skill_digest=skill_digest(entry_file),
        collection=collection_of(entry_file), invocation=invocation, origin="observed",
        coverage="partial", repo=repo, commit=commit, outcome=UNKNOWN, session=session,
        client="claude-code", model=model, at=now_utc(),
    )]


def run_hook(stdin: TextIO, stderr: TextIO, home: Path | None = None) -> int:
    """`skillc usage hook`. ALWAYS exits 0: a broken recorder must never fail
    the session it observes. A problem is printed to stderr and nothing is
    written."""
    try:
        payload = json.loads(stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        path, new = hook_records(payload, home or Path.home())
        new = [r for r in new if not record_problems(r)] if new else []
        if path is not None and new:
            append(path, new)
    except Exception as exc:  # noqa: BLE001 - fail-open by contract
        print(f"skillc usage hook: nothing recorded ({type(exc).__name__}: {exc})", file=stderr)
    return 0


def declare_end(
    skill: str, outcome: str, stop_reason: str | None, session: str | None, cwd: Path, out: TextIO,
) -> int:
    """`skillc usage end`: the skill's own account of how it ended, closing
    the oldest open start of (session, skill). With no open start nothing is
    written - an end without a start is exactly what the pairing rule refuses
    - and the exit is still 0, so a skill calling this never fails for it."""
    path = destination(cwd)
    if not session or path is None:
        print("SKILLC_USAGE: no-destination (no session id, or not inside a git checkout)", file=out)
        return 0
    starts = _open_starts(path, session, skill)
    if not starts:
        print(f"SKILLC_USAGE: no-open-start for {skill!r} in this session; nothing written", file=out)
        return 0
    record = _end_for(starts[0], cwd, origin="declared", outcome=outcome, stop_reason=stop_reason)
    problems = record_problems(record)
    if problems:
        print(f"SKILLC_USAGE: refused ({problems[0]}); nothing written", file=out)
        return 2
    append(path, [record])
    print(f"SKILLC_USAGE: recorded end {outcome} for {skill!r}", file=out)
    return 0


# ---------------------------------------------------------------- reading


@dataclass
class Report:
    records: int
    starts: int
    ends: int
    unended: int
    by_skill: Counter[tuple[str, str]]
    outcomes: Counter[str]
    unknown: Counter[str]


def summarize(log: UsageLog) -> Report:
    pairs, _ = pair(log)
    outcomes: Counter[str] = Counter()
    by_skill: Counter[tuple[str, str]] = Counter()
    unknown: Counter[str] = Counter()
    for start, end in pairs:
        outcome = end.data.get("outcome") if end is not None else UNKNOWN
        outcomes[str(outcome)] += 1
        by_skill[(str(start.data.get("skill")), str(start.data.get("skill_digest")))] += 1
        for key in UNKNOWABLE:
            value = outcome if key == "outcome" else start.data.get(key)
            if value == UNKNOWN:
                unknown[key] += 1
    ends = sum(1 for e in log.entries if e.data.get("event") == "end")
    return Report(len(log.entries), len(pairs), ends, sum(1 for _, e in pairs if e is None),
                  by_skill, outcomes, unknown)


def render(report: Report, out: TextIO) -> None:
    n = report.starts
    print(f"skillc: {report.records} record(s): {n} invocation(s) (start), {report.ends} end(s), "
          f"{report.unended} unended start(s) read as outcome UNKNOWN", file=out)
    print("\nby skill and digest:", file=out)
    width = max((len(s) for s, _ in report.by_skill), default=5)
    for (skill, digest), count in sorted(report.by_skill.items()):
        shown = digest if digest == UNKNOWN else digest[:19]
        print(f"  {skill:{width}}  {shown:19}  {count}", file=out)
    mix = ", ".join(f"{o}={report.outcomes.get(o, 0)}" for o in OUTCOMES)
    print(f"\noutcome mix: {mix}", file=out)
    cells = n * len(UNKNOWABLE)
    total = sum(report.unknown.values())
    rate = f"{100 * total / cells:.0f}%" if cells else "n/a"
    per = ", ".join(f"{k}={report.unknown.get(k, 0)}/{n}" for k in UNKNOWABLE)
    print(f"UNKNOWN rate: {total}/{cells} field(s) ({rate}) - {per}", file=out)
    print("\nskillc: counts only; a usage log is a skill's own account, not a verdict", file=out)


def cmd_report(path: Path, out: TextIO | None = None, err: TextIO | None = None) -> int:
    """`skillc usage report`: refused (1) on a log check-records refuses, `no
    records` (2) on an empty one - never a clean-looking zero."""
    out, err = out or sys.stdout, err or sys.stderr
    if not path.is_file():
        print(f"skillc: no such usage log: {path}", file=err)
        return 2
    log = load_log(path)
    problems = [*usage_envelope(log), *usage_fields(log), *usage_privacy(log), *usage_pairing(log)]
    if problems:
        for problem in problems:
            print(f"{path.name}: {problem}", file=err)
        print(f"skillc: {path.name} fails check-records; no report drawn from it", file=err)
        return 1
    if not log.entries:
        print(f"skillc: no records in {path.name} - nothing to report", file=out)
        return 2
    render(summarize(log), out)
    return 0
