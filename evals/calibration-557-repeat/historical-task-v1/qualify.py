#!/usr/bin/env python3
"""Certify the Level 3 helper-different-question grader before any model is
asked to solve the task. The certification harness (`certify`/
`control_verdict`/`candidates`) is `evals/level3/gate-ran-nothing/qualify.py`'s
own shape.

A grader is certified only when, on this task's committed candidates:

  - the starting fixture FAILs (the task is not already solved);
  - the reference, every valid alternative and every benign change PASS;
  - every plausible wrong output FAILs;
  - and every candidate's VIOLATED criteria are exactly those its
    `expected.json` names, so a FAIL for the wrong reason does not count.

Candidates are DERIVED from the directories under `alternatives/`, `benign/`
and `wrong/`. An empty population, a candidate without `APPROVED.md` or
`expected.json`, or an expectation that contradicts the candidate's placement
refuses outright. Every candidate is graded through skillc's verifier
(`skillc.verify.grade_directory`), the same staged path a real attempt takes.

A broken-grader control replaces the JUDGE (`GraderDef.with_judge`); the probe
and the inputs stay the task's own. Each must be refused and produce the one
status its name promises on every candidate.

INSTRUMENT VALIDITY. The task's premise is itself a claim about an instrument
- the shipped `tools/verify-change.py` - so it is checked, not assumed:

  - the helper prints `INTACT` on the fixture, whose runbook has two Step 5
    sections (the hazard is real, not a description of one);
  - the helper prints `CHANGED` when an approved line is missing (it is a
    working tool answering a narrower question, not a broken one), and
    refuses a diff that adds nothing rather than calling it INTACT;
  - each committed FAIL shape fails for exactly its criterion;
  - BLINDING `one-section-per-step` turns wrong/changed-not-fixed into a PASS
    (that check is what catches a duplicated step);
  - a malformed probe report makes every criterion UNKNOWN.

Exit 0 only if all of that holds.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from skillc import verify

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade_helper_different_question as judge_module  # the task's own judge, beside this file

HERE = Path(__file__).resolve().parent
REQUIRED_CRITERIA = judge_module.CRITERIA

#: Each broken grader, the status it must produce on EVERY candidate, and the
#: category that status came from. A crash or an empty report is no verdict:
#: INCONCLUSIVE, never FAIL.
CONTROLS = {
    "always_pass": ("PASS", "verdict"),
    "always_fail": ("FAIL", "verdict"),
    "crash": ("INCONCLUSIVE", "exit-nonzero"),
    "no_output": ("INCONCLUSIVE", "no-output"),
    "omits_criterion": ("INCONCLUSIVE", "criteria-set"),
}


@dataclass
class Row:
    candidate: str
    expected: str
    status: str
    detail: str
    expected_violated: frozenset[str] = frozenset()
    violated: frozenset[str] = frozenset()
    category: str = "verdict"

    @property
    def ok(self) -> bool:
        return self.status == self.expected and self.violated == self.expected_violated


def status_of(grader: Path, candidate: Path, root: Path = HERE) -> tuple[str, str, frozenset[str], str]:
    graded = verify.grade_directory(verify.GraderDef.load(root).with_judge(grader), candidate)
    return graded.status, graded.detail, graded.violated, graded.category


def _expectation(path: Path, placed: str) -> tuple[str, frozenset[str]]:
    if not (path / "APPROVED.md").is_file():
        raise SystemExit(f"{path}: no APPROVED.md; a missing candidate cannot calibrate")
    try:
        data = json.loads((path / "expected.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path}: unreadable expected.json: {exc}") from exc
    status, violated = data.get("status"), data.get("violated")
    if status != placed or not isinstance(violated, list):
        raise SystemExit(f"{path}: expected.json says {status!r}, placement says {placed!r}")
    if (placed == "FAIL") != bool(violated):
        raise SystemExit(f"{path}: a FAIL must name violated criteria, a PASS none")
    return placed, frozenset(map(str, violated))


def candidates(root: Path) -> list[tuple[Path, str, frozenset[str]]]:
    alternatives = sorted(p for p in (root / "alternatives").iterdir() if p.is_dir())
    benign = sorted(p for p in (root / "benign").iterdir() if p.is_dir())
    wrong = sorted(p for p in (root / "wrong").iterdir() if p.is_dir())
    if not alternatives or not benign or not wrong:
        raise SystemExit(
            f"{root}: no alternatives, no benign changes or no wrong outputs; an empty "
            "population cannot certify a grader"
        )
    placed = [
        (root / "fixture", "FAIL"),
        (root / "reference", "PASS"),
        *[(p, "PASS") for p in alternatives],
        *[(p, "PASS") for p in benign],
        *[(p, "FAIL") for p in wrong],
    ]
    return [(p, *_expectation(p, want)) for p, want in placed]


def certify(grader: Path, root: Path = HERE) -> tuple[bool, list[Row]]:
    rows = []
    for path, expected, expected_violated in candidates(root):
        status, detail, violated, category = status_of(grader, path, root)
        rows.append(Row(str(path.relative_to(root)), expected, status, detail,
                        expected_violated, violated, category))
    return all(r.ok for r in rows), rows


def control_verdict(name: str, root: Path = HERE) -> tuple[bool, str, list[Row]]:
    grader = root / "grader-controls" / f"{name}.py"
    if not grader.is_file():
        return False, f"control {grader.name} does not exist", []
    certified, rows = certify(grader, root)
    if certified:
        return False, "the gate certified it", rows
    want = CONTROLS[name]
    seen = {(r.status, r.category) for r in rows}
    if seen != {want}:
        return False, f"it produced {sorted(seen)}, not {want} throughout", rows
    return True, f"refused; {want[0]} ({want[1]}) on every candidate", rows


def _show(title: str, certified: bool, rows: list[Row]) -> None:
    print(f"{title}: {'CERTIFIED' if certified else 'REFUSED'}")
    for r in rows:
        mark = "ok " if r.ok else "BAD"
        print(f"  {mark} {r.candidate:34} expected {r.expected:4} got {r.status:12} {r.detail}")


def _judged(candidate: Path, *, blind_steps: bool = False) -> dict[str, str]:
    envelope = judge_module.run_probe(candidate)
    if judge_module.read_report(envelope) is None:
        raise SystemExit(f"{candidate}: the probe produced no well-formed report: {envelope}")
    return {c["id"]: c["outcome"] for c in judge_module.judge(envelope, blind_steps=blind_steps)["criteria"]}


def _helper(candidate: Path) -> tuple[int, str]:
    """Run the candidate tree's own tools/verify-change.py on its approved.diff."""
    proc = subprocess.run([sys.executable, "-I", "tools/verify-change.py", "approved.diff"], cwd=candidate,
                          capture_output=True, text=True, timeout=30, check=False)
    return proc.returncode, proc.stdout.strip()


def instrument_validity(root: Path = HERE) -> list[tuple[str, bool, str]]:
    """(check, held, detail) for every validity control. See the module
    docstring."""
    checks: list[tuple[str, bool, str]] = []

    # 1. The hazard's premise is real: the shipped helper reports INTACT on
    #    the fixture, whose runbook has two Step 5 sections.
    code, out = _helper(root / "fixture")
    checks.append(("the fixture's own helper prints INTACT on the duplicated runbook",
                   code == 0 and out == "INTACT", f"exit {code}: {out!r}"))

    # 2. The helper is not simply always INTACT: it does report a missing
    #    approved line, so its INTACT on the fixture is a true answer to a
    #    narrower question, not a broken tool.
    code, out = _helper(root / "wrong" / "approved-deleted")
    checks.append(("the helper prints CHANGED when an approved line is missing",
                   code == 1 and out.startswith("CHANGED"), f"exit {code}: {out!r}"))

    # 2b. The helper refuses a diff with no added lines (counter-model review):
    #     an empty population is never reported INTACT.
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(root / "fixture", Path(tmp) / "tree")
        (Path(tmp) / "tree" / "approved.diff").write_text(
            "--- a/docs/runbook.md\n+++ b/docs/runbook.md\n@@ -1 +1 @@\n-x\n", encoding="utf-8")
        code, out = _helper(Path(tmp) / "tree")
    checks.append(("the helper refuses a diff that adds no lines, never INTACT",
                   code == 2 and "INTACT" not in out, f"exit {code}: {out!r}"))

    # 2c. ...and one that also touches a second file, even a deleted one
    #     (counter-model re-review): never INTACT on a population it does not cover.
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(root / "fixture", Path(tmp) / "tree")
        diff = Path(tmp) / "tree" / "approved.diff"
        diff.write_text(diff.read_text(encoding="utf-8")
                        + "--- a/other.md\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n", encoding="utf-8")
        code, out = _helper(Path(tmp) / "tree")
    checks.append(("the helper refuses a diff that also deletes another file, never INTACT",
                   code == 2 and "INTACT" not in out, f"exit {code}: {out!r}"))

    # 3. Each committed FAIL shape fails for exactly its named criterion under
    #    the real judge - already proven by `certify()`, re-stated here.
    for name, criterion in (("trusted-the-helper", "one-section-per-step"),
                            ("changed-not-fixed", "one-section-per-step"),
                            ("hidden-in-comment", "one-section-per-step"),
                            ("sibling-deleted", "other-content-preserved"),
                            ("bold-duplicate", "approved-content-present"),
                            ("negated-rollback", "approved-content-present"),
                            ("contacts-between", "approved-content-present")):
        outcome = _judged(root / "wrong" / name)[criterion]
        checks.append((f"wrong/{name}: {criterion} is VIOLATED under the real judge",
                       outcome == "VIOLATED", f"got {outcome}"))

    # 4. Blinding the step-numbering check turns wrong/changed-not-fixed into
    #    a PASS: that check, not another, is what catches a duplicated step.
    blinded = _judged(root / "wrong" / "changed-not-fixed", blind_steps=True)
    checks.append(("blinding the step-numbering check turns wrong/changed-not-fixed PASS",
                   all(o == "SATISFIED" for o in blinded.values()), f"got {blinded}"))

    # 5. A malformed probe report makes every criterion UNKNOWN.
    outcomes = {c["id"]: c["outcome"]
                for c in judge_module.judge({"observations": "{not json", "timed_out": False})["criteria"]}
    checks.append(("a malformed probe report -> every criterion UNKNOWN",
                   all(o == "UNKNOWN" for o in outcomes.values()), f"got {outcomes}"))

    return checks


def main() -> int:
    good, rows = certify(HERE / "grade_helper_different_question.py")
    _show("grade_helper_different_question.py", good, rows)
    blind = []
    for name in CONTROLS:
        held, reason, rows = control_verdict(name)
        _show(f"control {name} ({reason})", False, rows)
        if not held:
            blind.append(f"{name}: {reason}")
    if not good:
        print("QUALIFY: fail - the grader does not discriminate the committed candidates")
        return 1
    if blind:
        print(f"QUALIFY: fail - broken-grader control(s) did not hold: {'; '.join(blind)}")
        return 1
    validity = instrument_validity()
    print("instrument validity:")
    for name, held, detail in validity:
        print(f"  {'ok ' if held else 'BAD'} {name}" + ("" if held else f": {detail}"))
    if not all(held for _name, held, _detail in validity):
        print("QUALIFY: fail - an instrument validity control did not hold")
        return 1
    print(f"QUALIFY: ok - grader certified; {len(CONTROLS)} broken graders refused; "
          f"{len(validity)} instrument validity controls held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
