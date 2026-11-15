"""The plain-English gauntlet report (#783): what each round Checked, what it
Found, what that Means, and the one thing to Do next.

Owner, 2026-11-15: "Output is engine-speak." `gauntlet run` prints this FIRST,
then the machine lines unchanged (tests and `gauntlet verdict` read those).
This module holds ALL of the report's wording, in one table keyed by (round,
reason), so a wording change is a change here and to the goldens in
tests/fixtures/gauntlet-report/, never scattered through the engine.

Rules (orchestrator gate, rev 51):

- no internal rule id appears in a mapped stop's report: `clause-backed`
  reads "each promise names a test that exists";
- every "Do next" names a concrete command or file;
- `/charter-create` (#778) is named only when this skillc has `charter create`;
  otherwise the draft-and-confirm path, with a note;
- a reason with no entry here shows the round's OWN detail as Found and asks
  the owner to act on it, never another reason's advice.

Pure and stdlib only: it formats the engine's `Result`s and runs nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gauntlet import Result, Skill

#: What each round looks at, in owner terms.
CHECKED = {
    "0": "whether usage logs show this skill being used",
    "1": "the skill's charter: the promises it makes, whether each names a test that exists, and whether you "
         "approved its purpose",
    "1-overlap": "whether another skill's charter already makes the same promises",
    "2": "the skill's own text, for rules that point at things that no longer exist or have expired",
    "3": "trial runs that measure whether each part of the skill changes results",
}

#: Contract checks, in owner terms (never their ids).
RULE_WORDS = {
    "clause-backed": "a promise names no test that exists",
    "negative-backed": "a 'never' promise has no case showing the shortcut fails",
    "contract-shape": "a field is unknown, missing or malformed",
    "approval-present": "the purpose or authority is not approved by you",
    "handoff-bilateral": "a hand-off to another skill is declared on one side only",
    "handoff-version": "a hand-off names a version the other skill does not provide",
    "reader-exists": "a promise names a reader that does not exist",
    "scope-owned": "a duty is claimed by more than one skill",
}


@dataclass
class Ctx:
    skill: Skill
    result: Result
    draft: Path
    charter_create: bool

    @property
    def collection(self) -> str:
        """The collection as a command argument: its path, so the command runs."""
        return str(self.skill.collection)

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.skill.collection).as_posix()
        except ValueError:
            return str(path)

    def facts(self, key: str, default: object = None) -> object:
        return self.result.facts.get(key, default)


Entry = tuple[Callable[[Ctx], str], Callable[[Ctx], str], Callable[[Ctx], str]]  # Found, Means, Do next


def _count(n: object, word: str) -> str:
    k = int(n) if isinstance(n, int) else 0
    return f"{k} {word}{'' if k == 1 else 's'}"


def _promises(ctx: Ctx) -> str:
    parts = []
    for kind, label in (("never", "'never' promise"), ("always", "'always' promise")):
        counts = ctx.facts(kind)
        if isinstance(counts, dict) and counts.get("count"):
            parts.append(f"{_count(counts['count'], label)} ({counts.get('tested', 0)} with a test)")
    return ", ".join(parts) if parts else "no 'never' or 'always' promises yet"


def _create(ctx: Ctx, then: str) -> str:
    """/charter-create when this skillc has it; else the draft-and-confirm path."""
    if ctx.charter_create:
        return (f"run `/charter-create {ctx.collection} {ctx.skill.rel}`: it composes the charter with you and "
                f"gives every promise a test. {then}")
    alone = then[3].upper() + then[4:] if then.startswith("Or ") else then
    return (f"{alone} (`/charter-create`, which composes a charter with you, is not in this skillc yet: skillc "
            "#778.)")


def _bad_rules(ctx: Ctx) -> str:
    rules = ctx.facts("rules")
    if not isinstance(rules, dict) or not rules:
        return "the charter failed a contract check"
    return "; ".join(RULE_WORDS.get(r, "another contract check failed") for r in sorted(rules))


def _len(items: object) -> int:
    return len(items) if isinstance(items, list) else 0


def _first(items: object) -> dict[str, object]:
    return items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}


def _removable(ctx: Ctx) -> str:
    items = ctx.facts("removable")
    if not isinstance(items, list) or not items:
        return "no rule that can be removed now"
    first = _first(items)
    return f"{_count(len(items), 'rule')} that can be removed now: line {first.get('line')}, {first.get('detail')}"


def _until_trials(ctx: Ctx) -> str:
    """Round 3 cannot run here: point at what the owner CAN act on now, the
    rules round 2 found removable, by file and line."""
    return (f"nothing more until the trial rounds land (skillc #736); meanwhile round 2's removable rules in "
            f"{ctx.skill.text_rel} are yours to act on by hand")


TABLE: dict[tuple[str, str], Entry] = {
    ("0", "no-log"): (
        lambda c: "no usage log for this skill",
        lambda c: "how often the skill is used is unknown; that never blocks the later rounds",
        lambda c: "optional: pass `--usage <log>` (written by skillc's usage hook) to show how the skill is used"),
    ("0", "log-unreadable"): (
        lambda c: f"{c.facts('unreadable')} of {_count(c.facts('logs'), 'usage log')} could not be read",
        lambda c: "how the skill is used is only partly known",
        lambda c: "check each `--usage` file with `skillc usage report <log>`"),
    ("0", ""): (
        lambda c: f"{_count(c.facts('logs'), 'usage log')} read",
        lambda c: "usage is recorded; the counts stay in the logs",
        lambda c: "nothing for this round"),
    ("1", "no-charter-draft"): (
        lambda c: f"no charter yet; a draft is ready ({_promises(c)})",
        lambda c: "no keep/trim/retire is possible until you settle what the skill promises; normal for a new skill",
        lambda c: _create(c, f"Or read the draft {c.rel(c.draft)} and run `skillc charter confirm` on it, as the "
                             "NEXT line below shows.")),
    ("1", "contract-bad:clause-backed"): (
        lambda c: f"the charter {c.rel(c.skill.charter)} makes {_promises(c)}; {_bad_rules(c)}",
        lambda c: "a promise without a test cannot be checked, so the gauntlet cannot go on",
        lambda c: _create(c, f"Or add a test for each promise in {c.rel(c.skill.charter)}; `skillc contracts "
                             f"{c.collection}` lists the missing ones.")),
    ("1", "contract-bad:contract-shape"): (
        lambda c: f"the charter {c.rel(c.skill.charter)} is not valid: {_bad_rules(c)}",
        lambda c: "the charter cannot be read, so nothing in it can be checked",
        lambda c: f"fix {c.rel(c.skill.charter)} where `skillc contracts {c.collection}` points"),
    ("1", "unapproved"): (
        lambda c: f"the charter {c.rel(c.skill.charter)} makes {_promises(c)}, but you have not approved its "
                  "purpose or authority",
        lambda c: "the gauntlet judges a skill only against a purpose you approved",
        lambda c: f"read the purpose in {c.rel(c.skill.charter)}; if it says what you intend, add `approved: "
                  "<date>` under it (or run `skillc charter confirm`)"),
    ("1", ""): (
        lambda c: (f"the charter is valid and you approved its purpose; it makes {_promises(c)}"),
        lambda c: "the skill has a settled purpose to be judged against",
        lambda c: "nothing for this round"),
    ("1-overlap", "no-comparator"): (
        lambda c: "the charters were not compared",
        lambda c: "whether another skill already does this job is not known, so 'retire' is not examined",
        lambda c: f"optional: run `skillc charter overlap {c.collection} --verdicts <file>` to compare them"),
    ("1-overlap", "not-built"): (
        lambda c: "this skillc cannot compare charters yet",
        lambda c: "whether another skill already does this job is not known",
        lambda c: "nothing now; it comes with skillc #726 part B"),
    ("2", "errors"): (
        lambda c: f"{_count(_len(c.facts('errors')), 'rule')} in {c.facts('file')} points at something that "
                  f"does not exist: line {_first(c.facts('errors')).get('line')}, "
                  f"{_first(c.facts('errors')).get('detail')}",
        lambda c: "the skill tells its reader to use something that is not there",
        lambda c: f"fix line {_first(c.facts('errors')).get('line')} of {c.facts('file')}, then re-run"),
    ("2", "unknown-on-skill"): (
        lambda c: f"{_count(_len(c.facts('unknown')), 'rule')} in {c.facts('file')} could not be decided: line "
                  f"{_first(c.facts('unknown')).get('line')}, {_first(c.facts('unknown')).get('detail')}",
        lambda c: "whether those rules are still needed is not known, so round 2 is not a pass",
        lambda c: "re-run with `--issue-states <file>`, or without `--offline`, so the issues those rules wait "
                  "on can be read"),
    ("2", "excluded"): (
        lambda c: f"an `--exclude` pattern drops {c.skill.text_rel}, so it was not inspected",
        lambda c: "the skill's text was not checked, which is not a pass",
        lambda c: f"narrow `--exclude` so it does not match {c.skill.text_rel}"),
    ("2", ""): (
        lambda c: f"{_count(c.facts('rule_statements'), 'emphasised rule')} read; {_removable(c)}",
        lambda c: "nothing in the text is broken; removable rules are candidates, never removed for you",
        lambda c: (f"remove line {_first(c.facts('removable')).get('line')} of {c.facts('file')} by hand if you "
                   "agree" if c.facts("removable") else "nothing for this round")),
    ("3", "not-built"): (
        lambda c: "the trial rounds are not built in this skillc",
        lambda c: "a keep/trim/retire verdict needs rounds 3-5 (skillc #736, #737); none can be given yet",
        lambda c: _until_trials(c)),
    ("3", "not-run"): (
        lambda c: "round 3 exists, but this run never pays for trials",
        lambda c: "no keep/trim/retire verdict yet",
        lambda c: "run the trials deliberately with `skillc gauntlet round3 --help` when you choose to"),
}

STANDS = {
    ("1", "no-charter-draft"): "it has no charter yet, so the gauntlet stopped at the first real question: what "
                               "should this skill promise?",
    ("1", "contract-bad:clause-backed"): "its charter makes promises without tests, so the gauntlet stopped at "
                                         "round 1.",
    ("1", "contract-bad:contract-shape"): "its charter is not valid, so the gauntlet stopped at round 1.",
    ("1", "unapproved"): "its charter waits on your approval, so the gauntlet stopped at round 1.",
    ("2", "errors"): "its text points at something that does not exist, so the gauntlet stopped at round 2.",
    ("2", "unknown-on-skill"): "some of its rules could not be checked, so the gauntlet stopped at round 2.",
    ("3", "not-built"): "rounds 0-2 are done; a keep/trim/retire verdict waits on the trial rounds, which are "
                        "not built yet.",
    ("3", "not-run"): "rounds 0-2 are done; a keep/trim/retire verdict waits on trials you have not run.",
}


def entry(result: Result) -> Entry | None:
    key = (result.round, result.reason)
    if key in TABLE:
        return TABLE[key]
    if result.proceed and (result.round, "") in TABLE and not result.reason:
        return TABLE[(result.round, "")]
    return None


def _unmapped(result: Result) -> Entry:
    """No advice is written for this stop: show the round's OWN detail, never
    another reason's advice (orchestrator, rev 37 and 51)."""
    return (lambda c: result.detail,
            lambda c: f"this round reads {result.verdict}, which is not a pass",
            lambda c: f"act on the ROUND {result.round} line below; it names what to fix")


def render(skill: Skill, results: list[Result], stopped: Result, *, draft: Path, charter_create: bool) -> str:
    stands = STANDS.get((stopped.round, stopped.reason),
                        f"it stopped at round {stopped.round} ({stopped.verdict}): {stopped.detail}")
    lines = [f"skill-gauntlet: {skill.rel}", f"Where it stands: {stands}", ""]
    for result in results:
        ctx = Ctx(skill, result, draft, charter_create)
        found, means, do_next = entry(result) or _unmapped(result)
        title = {"1-overlap": "Round 1 (overlap)"}.get(result.round, f"Round {result.round}")
        lines += [f"{title}: {result.verdict.lower()}",
                  f"  Checked: {CHECKED.get(result.round, result.name)}",
                  f"  Found:   {found(ctx)}",
                  f"  Means:   {means(ctx)}",
                  f"  Do next: {do_next(ctx)}",
                  ""]
    lines.append("No trials ran; this is not a keep/trim/retire verdict. The machine lines follow.")
    return "\n".join(lines) + "\n"
