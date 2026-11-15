"""`skillc gauntlet verdict` and `skillc gauntlet rule`: skill-gauntlet round 5 (#737).

Round 5 turns rounds 0-4's evidence into ONE proposal - keep, trim or retire -
and ONE `NEXT:` line. It decides nothing alone: it drafts a patch and PR text
into the engine's draft location and stops. The owner's ruling (accept, reject
or amend) is recorded in GAUNTLET.json, with a date, only by `gauntlet rule`.

**Offline and pure.** It reads files and makes no model call and no
subprocess (docs/specs/gauntlet-verdict.md):

- the skill's GAUNTLET.json (rounds 0-2, written by `gauntlet run`, #764);
- `--round3` / `--round4`: `gauntlet round3|round4 --json` reports, exactly
  `dataclasses.asdict(RoundReport)` (#736). The fields read are pinned in
  `ROUND_FIELDS` / `VARIANT_FIELDS` below, in ONE place: renaming one upstream
  is a breaking change for this reader;
- `--declaration`: #736's declaration, for each variant's {arm, file, remove};
- `--inspect`: an `inspect --json` report, for round 2's D and B items;
- `--overlap`: a round-1 overlap report (#726 part B), for retire.

**Never keep by default** (must-never 3). Any earlier round that did not pass,
an absent or undecided round 3 or 4, or no overlap report (retire then is NOT
EXAMINED) reads UNKNOWN, and NEXT names the first such round.

It never writes the skill under review or its CHARTER.md (must-never 1).
`verdict` writes only `round5.json`, `round5-pr.md` and (for trim)
`round5.patch` into the draft location; `rule` writes only the record's
`rounds.5`. Stdlib only.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import gauntlet

KEEP, TRIM, RETIRE, UNKNOWN = "KEEP", "TRIM", "RETIRE", "UNKNOWN"
EXIT_PROPOSED, EXIT_REFUSED, EXIT_USAGE, EXIT_UNKNOWN = 0, 1, 2, 3
RULINGS = ("accept", "reject", "amend")
VERDICT_FILE, PR_FILE, PATCH_FILE = "round5.json", "round5-pr.md", "round5.patch"

#: The ONE place the round 3/4 report fields are named (#736 `to_json`, i.e.
#: `dataclasses.asdict(RoundReport)`). A rename upstream breaks this reader on
#: purpose: `test_the_real_round_report_carries_every_field_read` pins it.
ROUND_FIELDS = ("round", "verdict", "recommendation", "variants")
VARIANT_FIELDS = ("removes", "source", "passes")
ROUND_COMPLETE = "COMPLETE"
#: Rounds 0-2, as the engine records them, and the verdict each must hold.
RECORD_PASSES = {"0": "OBSERVED", "1": "PASS", "2": "PASS"}
#: The overlap kinds that make another charter the owner of this skill's duty.
OWNED_ELSEWHERE = ("shared", "shadowed")
_CONTRACT = re.compile(r"^contract:\s*\"?([A-Za-z0-9_.-]+)\"?\s*$", re.MULTILINE)
_REMOVES_HEAD = 80  # #736 records `f"{file}: {remove[:80]}"`


@dataclass
class Verdict:
    verdict: str
    detail: str
    next_line: str
    evidence: list[str] = field(default_factory=list)
    patch: str | None = None

    def text(self) -> str:
        return "\n".join([f"ROUND 5 verdict: {self.verdict} - {self.detail}", *self.evidence, self.next_line]) + "\n"

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256((self.text() + (self.patch or "")).encode()).hexdigest()


def _list(data: object, key: str) -> list[object]:
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, list) else []


def _dict(data: object, key: str) -> dict[str, object]:
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


def _unknown(round_name: str, why: str, evidence: list[str] | None = None) -> Verdict:
    return Verdict(UNKNOWN, f"{round_name} did not decide: {why} - never keep by default",
                   f"NEXT: settle {round_name} ({why}), then re-run `skillc gauntlet verdict`", evidence or [])


def _load_json(path: Path | None, what: str) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise gauntlet.UsageError(f"{what} {path} cannot be read as JSON: {exc}") from None
    if not isinstance(data, dict):
        raise gauntlet.UsageError(f"{what} {path} is not a JSON object")
    return data


def _record_path(skill: gauntlet.Skill, options: gauntlet.Options) -> Path:
    if skill.charter.is_file():
        return skill.charter.parent / gauntlet.RECORD_NAME
    return gauntlet._draft_dir(skill, options) / gauntlet.RECORD_NAME


def _contract_name(charter: Path) -> str | None:
    try:
        head = charter.read_text().split("---", 2)
    except OSError:
        return None
    match = _CONTRACT.search(head[1] if len(head) > 2 else "")
    return match.group(1) if match else None


def _round_report(data: dict[str, object] | None, number: int) -> str | None:
    """None when the report is usable, else why it is not."""
    if data is None:
        return "no report given"
    missing = [f for f in ROUND_FIELDS if f not in data]
    if missing:
        return f"the report lacks {', '.join(missing)} (not a #736 RoundReport)"
    if data["round"] != number:
        return f"the report is round {data['round']}, not round {number}"
    if data["verdict"] != ROUND_COMPLETE:
        return f"it reads {data['verdict']}"
    return None


def _trim(skill: gauntlet.Skill, round4: dict[str, object], declaration: dict[str, object] | None,
          evidence: list[str]) -> Verdict | None:
    """The passing variant that removes the most, as a patch that only removes."""
    variants = round4["variants"]
    if not isinstance(variants, dict):
        return _unknown("round 4", "its variants are not a mapping")
    passing = sorted(arm for arm, v in variants.items() if isinstance(v, dict) and v.get("passes") is True)
    if round4["recommendation"] != "trim" or not passing:
        return None
    declared = {v.get("arm"): v for v in _list(declaration, "variants") if isinstance(v, dict)}
    candidates = []
    for arm in passing:
        row, decl = variants[arm], declared.get(arm)
        if any(f not in row for f in VARIANT_FIELDS) or decl is None:
            return _unknown("round 4", f"variant {arm} is missing from the declaration or its report row")
        file, remove = str(decl.get("file", "")), str(decl.get("remove", ""))
        if row["removes"] != f"{file}: {remove[:_REMOVES_HEAD]}":
            return _unknown("round 4", f"variant {arm}'s report says it removes {row['removes']!r}, the declaration "
                                       f"says {file}: {remove[:_REMOVES_HEAD]!r}")
        candidates.append((len(remove.split()), arm, file, remove, row))
    _, arm, file, remove, row = max(candidates)
    target = (skill.text.parent / file) if not skill.command else skill.collection / file
    try:
        before = target.read_text()
    except OSError:
        return _unknown("round 4", f"variant {arm}'s file {file} cannot be read")
    count = before.count(remove) if remove else 0
    if count != 1:
        return _unknown("round 4", f"variant {arm}'s passage occurs {count} times in {file}, not exactly once")
    after = before.replace(remove, "", 1)
    rel = target.relative_to(skill.collection).as_posix()
    patch = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{rel}", f"b/{rel}"))
    # `after` is `before` with the passage cut once, so the patch can only remove (must-always 3).
    if not patch or len(after) >= len(before):
        return _unknown("round 4", f"variant {arm}'s change removes nothing")
    evidence += [f"  trim {arm}: removes {len(remove.split())} words from {rel} (source: {row['source']})"]
    for clause, arms in sorted(_dict(round4, "per_clause").items()):  # before/after per clause test
        if isinstance(arms, dict) and isinstance(arms.get("intact"), dict) and isinstance(arms.get(arm), dict):
            evidence.append(f"  clause {clause}: intact {arms['intact'].get('pass')}/{arms['intact'].get('evaluable')}"
                            f" -> {arm} {arms[arm].get('pass')}/{arms[arm].get('evaluable')}")
    return Verdict(TRIM, f"variant {arm} passed every clause test on held-out tasks and only removes text",
                   "NEXT: owner reviews round5.patch and runs `skillc gauntlet rule ... accept|reject|amend`; "
                   "the gauntlet applies nothing", evidence, patch)


def _retire(contract: str, overlap: dict[str, object], evidence: list[str]) -> Verdict | None:
    """Every duty of this contract is owned by another charter (shared or shadowed)."""
    mine, owners = set(), {}
    for item in _list(overlap, "duties"):
        if isinstance(item, dict) and item.get("contract") == contract:
            mine.add(str(item.get("id")))
    for o in _list(overlap, "overlaps"):
        if not isinstance(o, dict) or o.get("kind") not in OWNED_ELSEWHERE:
            continue
        pair = [d for d in _list(o, "duties") if isinstance(d, dict)]
        for duty in pair:
            others = [d for d in pair if d.get("contract") != contract]
            if duty.get("contract") == contract and others:
                owners[str(duty.get("id"))] = str(others[0].get("contract"))
    if not mine or set(owners) != mine:
        return None
    evidence += [f"  retire: duty {d} is owned by {owners[d]}" for d in sorted(mine)]
    return Verdict(RETIRE, f"every duty of {contract} is owned by another charter ({', '.join(sorted(set(owners.values())))})",
                   "NEXT: owner reviews round5-pr.md (each duty's new owner is named) and runs "
                   "`skillc gauntlet rule ... accept|reject|amend`; the gauntlet retires nothing", evidence)


def decide(skill: gauntlet.Skill, record: dict[str, dict[str, object]], round3: dict[str, object] | None,
           round4: dict[str, object] | None, declaration: dict[str, object] | None,
           inspect: dict[str, object] | None, overlap: dict[str, object] | None) -> Verdict:
    """One verdict from the inputs, in the order docs/specs/gauntlet-verdict.md states."""
    for key, wanted in RECORD_PASSES.items():
        entry = record.get(key)
        got = entry.get("verdict") if isinstance(entry, dict) else None
        if got != wanted:
            return _unknown(f"round {key}", f"the record reads {got or 'nothing'}, not {wanted}")
    for number, data in ((3, round3), (4, round4)):
        why = _round_report(data, number)
        if why is not None:
            return _unknown(f"round {number}", why)
    if overlap is None:
        return _unknown("round 1 overlap", "no overlap report, so retire is NOT EXAMINED")
    if overlap.get("examined") is not True:
        return _unknown("round 1 overlap", "the overlap report says the collection was not examined")
    if inspect is None:
        return _unknown("round 2", "no inspect report, so its findings cannot be cited")
    evidence = ["  evidence is observational: it shows what the rounds measured, never why"]
    own = [f for f in _list(inspect, "findings") if isinstance(f, dict) and f.get("path") == skill.text_rel]
    evidence += [f"  round 2 D (removal candidate): {f.get('path')}:{f.get('line')} {f.get('detail')}"
                 for f in own if f.get("bucket") == "D"]
    evidence += [f"  round 2 B -> proposed check (bad input: the rule named at {f.get('path')}:{f.get('line')} "
                 f"broken), prose kept until the check exists: {f.get('detail')}" for f in own if f.get("bucket") == "B"]
    contract = _contract_name(skill.charter)
    if contract is None:
        return _unknown("round 1", "the charter names no contract")
    assert round4 is not None
    return (_retire(contract, overlap, evidence) or _trim(skill, round4, declaration, evidence)
            or Verdict(KEEP, "no variant passed round 4 and no duty is owned elsewhere",
                       "NEXT: nothing to change; the owner may record the keep with `skillc gauntlet rule ... accept`",
                       evidence))


# --------------------------------------------------------------------- the commands

def verdict(collection: Path, skill_arg: str, options: gauntlet.Options, *, round3: Path | None,
            round4: Path | None, declaration: Path | None, inspect: Path | None, overlap: Path | None,
            out=print) -> int:
    try:
        skill = gauntlet.resolve_skill(collection, skill_arg)
        gauntlet._no_symlink_below(skill.charter.parent, skill.collection)
        record = gauntlet.load_record(_record_path(skill, options))
        inputs = [_load_json(p, w) for p, w in ((round3, "--round3"), (round4, "--round4"),
                                                (declaration, "--declaration"), (inspect, "--inspect"),
                                                (overlap, "--overlap"))]
        draft_dir = gauntlet._draft_dir(skill, options)
    except gauntlet.UsageError as exc:
        print(f"skillc: {exc}")
        return EXIT_USAGE
    result = decide(skill, record, *inputs)
    try:
        gauntlet._ensure_ignored(draft_dir)
        body = {"skill": skill.rel, "verdict": result.verdict, "digest": result.digest}
        gauntlet._write_state(draft_dir / VERDICT_FILE, (json.dumps(body, indent=2, sort_keys=True) + "\n").encode())
        gauntlet._write_state(draft_dir / PR_FILE, (f"# skill-gauntlet round 5: {result.verdict} for {skill.rel}\n\n"
                                                    f"{result.text()}\nVerdict digest: {result.digest}\n").encode())
        if result.patch is not None:
            gauntlet._write_state(draft_dir / PATCH_FILE, result.patch.encode())
        elif (draft_dir / PATCH_FILE).is_file() and not (draft_dir / PATCH_FILE).is_symlink():
            (draft_dir / PATCH_FILE).unlink()  # an older trim's patch must not outlive its verdict
    except gauntlet.UnsafeRecord as exc:
        print(f"skillc: {exc}")
        return EXIT_USAGE
    out(result.text().rstrip("\n"))
    out(f"VERDICT_DIGEST: {result.digest} (drafts in {draft_dir}; nothing is applied)")
    return EXIT_UNKNOWN if result.verdict == UNKNOWN else EXIT_PROPOSED


def rule(collection: Path, skill_arg: str, options: gauntlet.Options, ruling: str, verdict_digest: str,
         date: str | None, note: str | None, out=print) -> int:
    """The owner's recorded act: rounds.5 in GAUNTLET.json, the record's ONLY dated field."""
    if ruling not in RULINGS:
        print(f"skillc: the ruling must be one of {', '.join(RULINGS)}")
        return EXIT_USAGE
    try:
        ruled_on = _dt.date.fromisoformat(date).isoformat() if date else _dt.datetime.now(_dt.UTC).date().isoformat()
    except ValueError:
        print(f"skillc: --date {date} is not YYYY-MM-DD")
        return EXIT_USAGE
    try:
        skill = gauntlet.resolve_skill(collection, skill_arg)
        gauntlet._no_symlink_below(skill.charter.parent, skill.collection)
        drafted = _load_json(gauntlet._draft_dir(skill, options) / VERDICT_FILE, "the drafted verdict")
        record_path = _record_path(skill, options)
    except gauntlet.UsageError as exc:
        print(f"skillc: {exc}")
        return EXIT_USAGE
    if not drafted or drafted.get("digest") != verdict_digest:
        print(f"skillc: refusing: --verdict-digest {verdict_digest} is not the drafted verdict "
              f"({(drafted or {}).get('digest', 'none')}); re-run `skillc gauntlet verdict` and rule on what it prints")
        return EXIT_REFUSED
    if drafted.get("verdict") == UNKNOWN:
        print("skillc: refusing: an UNKNOWN verdict has nothing to rule on; settle the round NEXT names first")
        return EXIT_REFUSED
    try:
        data = json.loads(record_path.read_text()) if record_path.is_file() else None
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict) or data.get("kind") != gauntlet.RECORD_KIND:
        print(f"skillc: refusing: no gauntlet record at {record_path}; run `skillc gauntlet run` first")
        return EXIT_REFUSED
    data.setdefault("rounds", {})["5"] = {
        "name": "verdict", "verdict": drafted["verdict"], "detail": f"owner ruling: {ruling}", "proceed": False,
        "inputs": {"verdict": verdict_digest}, "ruling": ruling, "ruled_on": ruled_on, "note": note or ""}
    try:
        gauntlet._write_state(record_path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode())
    except gauntlet.UnsafeRecord as exc:
        print(f"skillc: {exc}")
        return EXIT_USAGE
    out(f"RULING: {ruling} on {drafted['verdict']} for {skill.rel}, recorded {ruled_on} in {gauntlet.RECORD_NAME} "
        "(the engine never commits it)")
    return EXIT_PROPOSED
