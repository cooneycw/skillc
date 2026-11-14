"""`skillc inspect`: the skill-gauntlet's round 2 (issue #725).

Runs the decay rules over a collection, folds in an exposure report when one
is supplied, and sorts what it finds into the four groups of
cooneycw/claude-power-pack discussion #1830:

    A  already enforced by a check that has been SHOWN TO FAIL - shrink to a pointer
    B  not enforced - propose a check
    C  a fact the code cannot show - keep it
    D  history or a retired feature - move it to a reference doc

The organising rule is #1830's: prose comes out only when a check already
guards against the same mistake, and that check has been shown to fail on its
known-bad case. `inspect` is the instrument that applies that rule; it never
trims anything itself.

What sorts mechanically, and what does not:

- a closed `until #N` / `expires-with: #N` is D;
- a rule line naming an enforcer (a test, control, CI step, or a helper with a
  NEGATIVE-CONTROL marker) whose known-bad case EXISTS is A. An enforcer with
  no red case found is UNSORTED: "a check exists" is not "a check goes red";
- a rule line naming a check path that does not exist is B. #1830's B also
  requires that the mistake HAS RECURRED - recurrence is friction and history
  evidence this round does not read - so every other unenforced line stays
  UNSORTED with that reason, never a guessed B;
- C is never assigned mechanically: only the owner can say a fact must stay;
- everything else is UNSORTED, with its reason.

The charter this module is held to is the first section of docs/specs/inspect.md.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import checks, decay

SCHEMA = 1
A, B, C, D, UNSORTED = "A", "B", "C", "D", "UNSORTED"
BUCKETS = (A, B, C, D, UNSORTED)

NOTHING_INSPECTED = "NOTHING-INSPECTED"
STOPPED = "STOPPED"
INCOMPLETE = "INCOMPLETE"
FINDINGS = "FINDINGS"
CLEAN = "CLEAN"

BUCKET_POLICY = {
    A: "mechanical: the line names an enforcer whose known-bad case exists",
    B: "mechanical only when the line names a check that does not exist; otherwise needs "
       "recurrence evidence (#1830: 'the mistake has happened again'), which round 2 does not read",
    C: "never mechanical - only the owner can rule that a fact must stay",
    D: "mechanical: a temporary rule whose issue has closed",
    UNSORTED: "no mechanical signal; the reason says why - never guessed",
}

NEGATIVE_CONTROL_RE = re.compile(r"NEGATIVE-CONTROL:\s*([A-Za-z0-9_./-]+)")


class Refused(ValueError):
    """An input `inspect` cannot read, so it reports nothing rather than less."""


@dataclass
class Item:
    bucket: str
    rule: str
    rel: str
    line: int
    detail: str
    reason: str
    extra: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "bucket": self.bucket, "rule": self.rule, "path": self.rel, "line": self.line,
            "detail": self.detail, "reason": self.reason,
        }
        out.update(self.extra)
        return out


# ------------------------------------------------------------ enforcers (R1)

@dataclass(frozen=True)
class Enforcer:
    word: str
    rel: str | None  # collection-relative path when it exists
    red_case: str | None  # collection-relative path of its known-bad case, when found
    under_root: bool


def _rel(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def _red_case(path: Path, root: Path) -> str | None:
    """The known-bad case that shows this enforcer can fail, or None.

    Two signals, both mechanical: a control directory (`controls/<id>/...`)
    with a `bad/` beside it, or a file declaring `NEGATIVE-CONTROL: <path>`
    for a path that exists. A test file with neither is an enforcer whose red
    case was not found - which is reported, not credited."""
    rel = _rel(path, root)
    if rel is None:
        return None
    parts = rel.split("/")
    if parts[0] == "controls" and len(parts) >= 2:
        bad = root / "controls" / parts[1] / "bad"
        if bad.is_dir():
            return f"controls/{parts[1]}/bad"
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        for match in NEGATIVE_CONTROL_RE.finditer(text):
            target = (root / match.group(1)).resolve()
            if target.exists() and _rel(target, root) is not None:
                return match.group(1).rstrip("/")
    return None


def _under(word: str, roots: Sequence[str]) -> bool:
    return any(word.startswith(r) for r in roots)


def enforcers_named(line: str, subject: decay.Subject, coll: decay.Collection) -> list[Enforcer]:
    """Every check a rule line points at, resolved inside the collection."""
    words: list[str] = []
    for match in decay.INLINE_CODE_RE.finditer(line):
        words.extend(decay._clean_word(w) for w in match.group(2).split())
    for match in decay.MD_LINK_RE.finditer(line):
        words.append(match.group(1).split("#", 1)[0])
    found: list[Enforcer] = []
    for word in words:
        if not word or decay._is_placeholder(word) or not decay.PATH_WORD_RE.match(word):
            continue
        under = _under(word, coll.enforcement_roots)
        ref = decay._resolve_prefixed(word, subject, coll)
        candidates = list(ref.candidates) if ref else []
        if under:
            candidates.append(coll.root / word)
        if not candidates and "/" in word:
            candidates.append(subject.path.parent / word)  # a relative link
        if not candidates:
            continue
        existing = next((c for c in candidates if c.exists() and _rel(c, coll.root) is not None), None)
        if existing is None:
            if under:
                found.append(Enforcer(word, None, None, True))
            continue
        red = _red_case(existing, coll.root)
        if under or red is not None:
            found.append(Enforcer(word, _rel(existing, coll.root), red, under))
    return found


PARAGRAPH_CAP = 12


def paragraph(lines: Sequence[str], index: int, cap: int = PARAGRAPH_CAP) -> str:
    """The rule statement an emphasised line belongs to: its paragraph (the
    contiguous non-blank lines around it, a fence line ending it), at most
    `cap` lines either side. CPP's rules seldom name their enforcer on the
    emphasised line itself - "NEVER use git stash" sits one line above the
    helper that guards it - so a single line would under-credit A."""
    def stop(i: int) -> bool:
        return not lines[i].strip() or bool(decay.FENCE_RE.match(lines[i]))
    lo = index
    while lo > 0 and index - lo < cap and not stop(lo - 1):
        lo -= 1
    hi = index
    while hi + 1 < len(lines) and hi - index < cap and not stop(hi + 1):
        hi += 1
    return "\n".join(lines[lo:hi + 1])


def sort_rule_line(line: str, subject: decay.Subject, coll: decay.Collection) -> tuple[str, str, dict[str, object]]:
    named = enforcers_named(line, subject, coll)
    proven = [e for e in named if e.red_case]
    if proven:
        e = proven[0]
        return A, f"enforced by {e.rel}, whose known-bad case {e.red_case} exists - run it before trimming", {
            "enforcer": e.rel, "red_case": e.red_case,
        }
    missing = [e for e in named if e.rel is None]
    if missing:
        return B, f"names {missing[0].word}, a check that does not exist - propose it", {
            "missing_check": missing[0].word,
        }
    if named:
        e = named[0]
        return UNSORTED, f"enforcer named ({e.rel}) but no known-bad case found - run its failing case before trimming", {
            "enforcer": e.rel,
        }
    return UNSORTED, "no enforcer named; B needs recurrence evidence and C needs the owner", {}


# ------------------------------------------------------------ pinned-by (R4)

def _pinning_tests(coll: decay.Collection) -> dict[str, str]:
    tests = coll.root / "tests"
    texts: dict[str, str] = {}
    if not tests.is_dir():
        return texts
    for path in sorted(tests.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".sh", ".bats", ".js", ".ts") and not path.is_symlink():
            try:
                texts[path.relative_to(coll.root).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return texts


def pinned_by(rel: str, tests: Mapping[str, str]) -> list[str]:
    """Test files that name this document (#1830 Part 4: a test that greps a
    doc's wording holds that wording in place, so a trim needs a test edit).
    Matched on the path or its last two components - a bare basename such as
    `auto.md` would match unrelated docs."""
    parts = rel.split("/")
    needles = {rel}
    if len(parts) >= 2:
        needles.add("/".join(parts[-2:]))
    return sorted(t for t, text in tests.items() if any(n in text for n in needles))


# ------------------------------------------------------------ exposure (D9)

def load_exposure(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise Refused(f"exposure report {path} unreadable: {exc}") from exc
    if not isinstance(data, dict) or data.get("kind") != "exposure-report":
        raise Refused(f"exposure report {path} is not a skillc exposure-report")
    if data.get("status") == "refused":
        raise Refused(f"exposure report {path} records a REFUSED run: {data.get('reason')}")
    for key in ("markers", "skills"):
        if not isinstance(data.get(key), list) or not all(isinstance(i, dict) for i in data[key]):
            raise Refused(f"exposure report {path}: {key!r} is not a list of items")
    return data


def _exposure_items(data: Mapping[str, Any]) -> list[Item]:
    items: list[Item] = []
    for entry in data.get("skills", []):
        verdict = entry.get("verdict")
        if verdict != "EXPOSED":
            cause = f" ({entry['cause']})" if entry.get("cause") else ""
            items.append(Item(UNSORTED, "exposure", str(entry.get("skill", "?")), 0,
                              f"skill is {verdict}{cause} in the client's rendered input",
                              "exposure: what reaches the model is an owner call"))
    for entry in data.get("markers", []):
        verdict = entry.get("verdict")
        if verdict != "EXPOSED":
            items.append(Item(UNSORTED, "exposure", str(entry.get("layer", "?")), 0,
                              f"marker is {verdict}: {entry.get('note', '')}".rstrip(": "),
                              "exposure: what reaches the model is an owner call"))
    return items


# ------------------------------------------------------------ the run

@dataclass
class Report:
    data: dict[str, Any]

    @property
    def verdict(self) -> str:
        return str(self.data["verdict"])

    @property
    def exit_code(self) -> int:
        return int(self.data["exit"])


def run(
    coll: decay.Collection,
    *,
    exposure: Mapping[str, Any] | None = None,
    lookup: decay.StateLookup | None = None,
    strict: bool = False,
) -> Report:
    meta: dict[str, object] = {
        "root": coll.root.name, "include": list(coll.include), "exclude": list(coll.exclude),
        "maps": [f"{a}={b}" for a, b in coll.maps], "subjects": len(coll.subjects),
        "excluded": coll.excluded_count, "repo": coll.repo,
    }
    if not coll.subjects:
        return Report({
            "schema": SCHEMA, "kind": "inspect-report", "collection": meta,
            "verdict": NOTHING_INSPECTED, "exit": 2,
            "summary": "nothing inspected - the collection has no subject, which is not a clean result",
        })

    previous = decay.STATE_LOOKUP
    decay.STATE_LOOKUP = lookup
    try:
        results = checks.run_collection(coll)
    finally:
        decay.STATE_LOOKUP = previous

    errors: list[dict[str, object]] = []
    items: list[Item] = []
    unknown: list[dict[str, object]] = []
    notes: list[dict[str, object]] = []
    rules: dict[str, object] = {}
    unexamined: list[str] = []
    for rule, result in results:
        rules[rule.id] = {
            "severity": rule.severity, "examined": result.examined, "hits": len(result.hits),
            "unknown": len(result.unknown), "notes": len(result.notes), "population": result.population,
        }
        if not result.examined:
            unexamined.append(rule.id)
        for hit in result.unknown:
            unknown.append({"rule": rule.id, "path": hit.rel, "line": hit.line, "detail": hit.detail})
        for hit in result.notes:
            notes.append({"rule": rule.id, "path": hit.rel, "line": hit.line, "detail": hit.detail})
        for hit in result.hits:
            if rule.severity == checks.ERROR:
                errors.append({"rule": rule.id, "path": hit.rel, "line": hit.line, "detail": hit.detail})
            elif rule.id == "expired-marker":
                items.append(Item(D, rule.id, hit.rel, hit.line, hit.detail,
                                  "a temporary rule whose issue has closed - history; move it out or delete it",
                                  {"issue": hit.data.get("issue")}))
            elif rule.id == "copied-passage":
                items.append(Item(UNSORTED, rule.id, hit.rel, hit.line, hit.detail,
                                  "which copy is the source, and whether the other becomes a pointer, is an owner call",
                                  dict(hit.data)))
            else:
                items.append(Item(UNSORTED, rule.id, hit.rel, hit.line, hit.detail,
                                  "density is a whole-document signal; its rule lines are sorted one by one",
                                  dict(hit.data)))

    # Every emphasised line is a rule statement; each gets a bucket (R1/R2).
    rule_lines: list[Item] = []
    for subject in coll.subjects:
        for index, _count, line in decay.emphasis_lines(subject):
            bucket, reason, extra = sort_rule_line(paragraph(subject.lines, index), subject, coll)
            rule_lines.append(Item(bucket, "rule-line", subject.rel, subject.lineno(index),
                                   line.strip()[:200], reason, extra))

    exposure_meta: dict[str, object]
    if exposure is None:
        exposure_meta = {"supplied": False,
                         "note": "exposure: not supplied - what reaches the model was not measured"}
    else:
        exposure_items = _exposure_items(exposure)
        items.extend(exposure_items)
        exposure_meta = {"supplied": True, "client": exposure.get("client"),
                         "not_exposed": len(exposure_items)}

    tests = _pinning_tests(coll)
    for item in [*items, *rule_lines]:
        if item.bucket in (A, D) and item.rel:
            pins = pinned_by(item.rel, tests)
            if pins:
                item.extra["pinned_by"] = pins

    if errors:
        verdict, code = STOPPED, 1
        summary = (f"STOPPED - {len(errors)} hard error(s): a dangling reference is a bug, not a trim. "
                   f"Nothing here is trim-ready until they are fixed")
    elif unknown or unexamined:
        verdict, code = INCOMPLETE, 1
        gaps = []
        if unknown:
            gaps.append(f"{len(unknown)} marker(s) UNKNOWN")
        if unexamined:
            gaps.append(f"not examined: {', '.join(unexamined)}")
        summary = f"INCOMPLETE - {'; '.join(gaps)} - NOT clean"
    elif items:
        verdict, code = FINDINGS, (1 if strict else 0)
        summary = f"{len(items)} finding(s) sorted"
    else:
        verdict, code = CLEAN, 0
        summary = "clean - every rule examined, no finding, no UNKNOWN"

    by_rule = Counter(i.rule for i in items)
    by_rule.update(Counter(str(e["rule"]) for e in errors))
    return Report({
        "schema": SCHEMA, "kind": "inspect-report", "collection": meta,
        "verdict": verdict, "exit": code, "summary": summary,
        "bucket_policy": BUCKET_POLICY,
        "counts": {
            "by_rule": dict(sorted(by_rule.items())),
            "by_bucket": {b: sum(i.bucket == b for i in items) for b in BUCKETS},
            "rule_lines_by_bucket": {b: sum(i.bucket == b for i in rule_lines) for b in BUCKETS},
            "errors": len(errors), "unknown": len(unknown), "notes": len(notes),
        },
        "rules": rules,
        "errors": errors,
        "findings": [i.to_dict() for i in items],
        "rule_lines": [i.to_dict() for i in rule_lines],
        "unknown": unknown,
        "notes": notes,
        "exposure": exposure_meta,
    })


# ------------------------------------------------------------ rendering

def render_markdown(report: Report, limit: int = 50) -> str:
    d = report.data
    meta = d["collection"]
    out = [f"# skillc inspect: {meta['root']}", "", f"**Verdict: {d['verdict']}** - {d['summary']}", ""]
    out.append(f"- subjects: {meta['subjects']} (excluded: {meta['excluded']}); "
               f"include: {', '.join(meta['include'])}")
    if d["verdict"] == NOTHING_INSPECTED:
        return "\n".join(out) + "\n"
    out.append(f"- {d['exposure']['note'] if not d['exposure']['supplied'] else 'exposure: supplied'}")
    out += ["", "## Counts", "", "| bucket | findings | rule lines |", "|---|---|---|"]
    counts = d["counts"]
    for b in BUCKETS:
        out.append(f"| {b} | {counts['by_bucket'][b]} | {counts['rule_lines_by_bucket'][b]} |")
    out += ["", "| rule | examined | hits | unknown | notes |", "|---|---|---|---|---|"]
    for rid, r in d["rules"].items():
        out.append(f"| {rid} | {r['examined']} | {r['hits']} | {r['unknown']} | {r['notes']} |")
    out += ["", "C and B are owner/evidence buckets: a zero there means NOT ASSIGNED, never 'none'.", ""]

    def section(title: str, rows: list[dict[str, Any]], fmt: Any) -> None:
        if not rows:
            return
        out.extend([f"## {title} ({len(rows)})", ""])
        for row in rows[:limit]:
            out.append(fmt(row))
        if len(rows) > limit:
            out.append(f"- ... {len(rows) - limit} more in report.json")
        out.append("")

    section("Hard errors", d["errors"], lambda r: f"- `{r['path']}:{r['line']}` {r['rule']}: {r['detail']}")
    section("UNKNOWN", d["unknown"], lambda r: f"- `{r['path']}:{r['line']}` {r['detail']}")
    for b in BUCKETS:
        rows = [f for f in d["findings"] if f["bucket"] == b]
        section(f"Findings - {b}", rows, lambda r: (
            f"- `{r['path']}:{r['line']}` {r['rule']}: {r['detail']} - _{r['reason']}_"
            + (f" (pinned by {', '.join(r['pinned_by'])})" if r.get("pinned_by") else "")))
    for b in (A, B):
        rows = [f for f in d["rule_lines"] if f["bucket"] == b]
        section(f"Rule lines - {b}", rows, lambda r: f"- `{r['path']}:{r['line']}` {r['detail']} - _{r['reason']}_")
    section("Notes", d["notes"], lambda r: f"- `{r['path']}:{r['line']}` {r['detail']}")
    return "\n".join(out) + "\n"
