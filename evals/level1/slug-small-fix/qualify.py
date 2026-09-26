#!/usr/bin/env python3
"""Certify the slug grader before any model is asked to solve the task.

A grader is certified only when, on this task's committed candidates:

  - the starting fixture FAILs (the task is not already solved);
  - the reference and every valid alternative PASS (alternatives are accepted);
  - every plausible wrong output FAILs (the grader discriminates);
  - and every candidate's VIOLATED criteria are exactly those its `expected.json`
    names, so a FAIL for the wrong reason - a deleted source file read as an
    interface violation, a one-rule defect blamed on a neighbour - does not count
    as discrimination.

Candidates are DERIVED from the directories under `alternatives/` and `wrong/`.
An empty population, a candidate without `src/slugify.py` or `expected.json`, or
an expectation that contradicts the candidate's placement refuses outright.

A grader report must carry exactly the task's required criteria, each mandatory
and each once. A report that drops one is not a verdict on the task.

Grader output becomes a status through skillc's own verified-result contract:
the output is assembled into a version-2 `verified-result`, checked with the
record rules, and its status is `records.derive_status`. A grader that exits
non-zero, prints nothing, or prints something the contract rejects produced no
verdict: that is INCONCLUSIVE, never FAIL. A crash is not a detected defect.

`python3 qualify.py` certifies the real grader AND requires each broken grader in
`grader-controls/` to exist, to be refused, and to produce the one status its
name promises on every candidate - so a missing or misbehaving control cannot
count as a refused one. Exit 0 only if all of that holds.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from skillc import records

HERE = Path(__file__).resolve().parent
GRADER_TIMEOUT_SECONDS = 60
NONE: frozenset[str] = frozenset()
#: The criteria every report for this task must carry, each mandatory, once.
REQUIRED_CRITERIA = ("R4-interface", "reported-example", "R1", "R2", "R3")

#: Each broken grader, the status it must produce on EVERY candidate, and the path
#: that must produce it. A crash or an empty report is no verdict: INCONCLUSIVE,
#: never FAIL. The category keeps controls that share a status from standing in
#: for one another.
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


def _digest(candidate: Path) -> str:
    target = candidate / "src" / "slugify.py"
    data = target.read_bytes() if target.is_file() else b""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _criteria_problem(criteria: object) -> str | None:
    """Why a report's criteria are not this task's required set, or None."""
    if not isinstance(criteria, list):
        return "no criteria list"
    ids = [c.get("id") for c in criteria if isinstance(c, dict)]
    if len(ids) != len(criteria) or not all(isinstance(i, str) for i in ids):
        return "a criterion is not an object with a string id"
    if len(set(ids)) != len(ids):
        return "criterion ids are not unique"
    if set(ids) != set(REQUIRED_CRITERIA):
        missing = sorted(set(REQUIRED_CRITERIA) - set(map(str, ids)))
        extra = sorted(set(map(str, ids)) - set(REQUIRED_CRITERIA))
        return f"criteria differ from the required set (missing {missing}, extra {extra})"
    if not all(c.get("mandatory") is True for c in criteria):
        return "a required criterion is not mandatory"
    return None


def status_of(grader: Path, candidate: Path) -> tuple[str, str, frozenset[str], str]:
    """(status, detail, VIOLATED criterion ids, category) for one grader run.

    The category names WHICH path produced the status, so two broken graders that
    both yield INCONCLUSIVE - a crash and an empty report - stay distinguishable.
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(grader), str(candidate)],
            capture_output=True, text=True, timeout=GRADER_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return "INCONCLUSIVE", f"grader did not finish within {GRADER_TIMEOUT_SECONDS}s", NONE, "timeout"
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-1:] or ["no stderr"]
        return "INCONCLUSIVE", f"grader exited {proc.returncode}: {tail[0]}", NONE, "exit-nonzero"
    if not proc.stdout.strip():
        return "INCONCLUSIVE", "grader exited 0 and emitted no result", NONE, "no-output"
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return "INCONCLUSIVE", f"grader output is not JSON: {exc}", NONE, "unparseable"
    if not isinstance(out, dict):
        return "INCONCLUSIVE", "grader output is not an object", NONE, "unparseable"

    record = records.Record(path=grader, data={
        "version": 2,
        "kind": records.VERIFIED_RESULT,
        "result_id": f"qualify-{candidate.name}",
        "grader": out.get("grader"),
        "graded_digests": [_digest(candidate)],
        "criteria": out.get("criteria"),
    })
    shape = _criteria_problem(out.get("criteria"))
    if shape:
        return "INCONCLUSIVE", f"grader report is not a verdict on this task: {shape}", NONE, "criteria-set"
    problems = [
        *records.criterion_vocabulary(record),
        *records.result_evidence(record),
    ]
    if problems:
        return "INCONCLUSIVE", f"grader output breaks the result contract: {problems[0]}", NONE, "contract"
    status = records.derive_status(record)
    criteria = out["criteria"]
    assert isinstance(criteria, list)
    unmet = [c["id"] for c in criteria if c.get("outcome") != "SATISFIED"]
    violated = frozenset(str(c["id"]) for c in criteria if c.get("outcome") == "VIOLATED")
    return status, ("all mandatory criteria satisfied" if not unmet
                    else "not satisfied: " + ", ".join(map(str, unmet))), violated, "verdict"


def _expectation(path: Path, placed: str) -> tuple[str, frozenset[str]]:
    """The committed expectation for one candidate, checked against its placement."""
    if not (path / "src" / "slugify.py").is_file():
        raise SystemExit(f"{path}: no src/slugify.py; a missing candidate cannot calibrate")
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
    """Every committed candidate, the status and violations a working grader gives."""
    alternatives = sorted(p for p in (root / "alternatives").iterdir() if p.is_dir())
    wrong = sorted(p for p in (root / "wrong").iterdir() if p.is_dir())
    if not alternatives or not wrong:
        raise SystemExit(
            f"{root}: no alternatives or no wrong outputs; an empty population "
            "cannot certify a grader"
        )
    placed = [
        (root / "fixture", "FAIL"),
        (root / "reference", "PASS"),
        *[(p, "PASS") for p in alternatives],
        *[(p, "FAIL") for p in wrong],
    ]
    return [(p, *_expectation(p, want)) for p, want in placed]


def certify(grader: Path, root: Path = HERE) -> tuple[bool, list[Row]]:
    rows = []
    for path, expected, expected_violated in candidates(root):
        status, detail, violated, category = status_of(grader, path)
        rows.append(Row(str(path.relative_to(root)), expected, status, detail,
                        expected_violated, violated, category))
    return all(r.ok for r in rows), rows


def control_verdict(name: str, root: Path = HERE) -> tuple[bool, str, list[Row]]:
    """(held, reason, rows): the control exists, is refused, and behaved as named."""
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
        print(f"  {mark} {r.candidate:26} expected {r.expected:4} got {r.status:12} {r.detail}")


def main() -> int:
    good, rows = certify(HERE / "grade_slug.py")
    _show("grade_slug.py", good, rows)
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
    print(f"QUALIFY: ok - grader certified; {len(CONTROLS)} broken graders refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
