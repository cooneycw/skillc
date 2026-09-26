#!/usr/bin/env python3
"""Certify the slug grader before any model is asked to solve the task.

A grader is certified only when, on this task's committed candidates:

  - the starting fixture FAILs (the task is not already solved);
  - the reference and every valid alternative PASS (alternatives are accepted);
  - every plausible wrong output FAILs (the grader discriminates).

Candidates are DERIVED from the directories under `alternatives/` and `wrong/`,
and an empty population refuses rather than certifies.

Grader output becomes a status through skillc's own verified-result contract:
the output is assembled into a version-2 `verified-result`, checked with the
record rules, and its status is `records.derive_status`. A grader that exits
non-zero, prints nothing, or prints something the contract rejects produced no
verdict: that is INCONCLUSIVE, never FAIL. A crash is not a detected defect.

`python3 qualify.py` certifies the real grader AND requires each of the four
broken graders in `grader-controls/` to be refused. Exit 0 only if both hold.
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
CONTROLS = ("always_pass", "always_fail", "crash", "no_output")


@dataclass
class Row:
    candidate: str
    expected: str
    status: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == self.expected


def _digest(candidate: Path) -> str:
    target = candidate / "src" / "slugify.py"
    data = target.read_bytes() if target.is_file() else b""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def status_of(grader: Path, candidate: Path) -> tuple[str, str]:
    """(protocol status, detail) for one grader run on one candidate."""
    try:
        proc = subprocess.run(
            [sys.executable, str(grader), str(candidate)],
            capture_output=True, text=True, timeout=GRADER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "INCONCLUSIVE", f"grader did not finish within {GRADER_TIMEOUT_SECONDS}s"
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-1:] or ["no stderr"]
        return "INCONCLUSIVE", f"grader exited {proc.returncode}: {tail[0]}"
    if not proc.stdout.strip():
        return "INCONCLUSIVE", "grader exited 0 and emitted no result"
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return "INCONCLUSIVE", f"grader output is not JSON: {exc}"
    if not isinstance(out, dict):
        return "INCONCLUSIVE", "grader output is not an object"

    record = records.Record(path=grader, data={
        "version": 2,
        "kind": records.VERIFIED_RESULT,
        "result_id": f"qualify-{candidate.name}",
        "grader": out.get("grader"),
        "graded_digests": [_digest(candidate)],
        "criteria": out.get("criteria"),
    })
    problems = [
        *records.criterion_vocabulary(record),
        *records.result_evidence(record),
    ]
    if problems:
        return "INCONCLUSIVE", f"grader output breaks the result contract: {problems[0]}"
    status = records.derive_status(record)
    criteria = out["criteria"]
    assert isinstance(criteria, list)
    unmet = [c["id"] for c in criteria if c.get("outcome") != "SATISFIED"]
    return status, ("all mandatory criteria satisfied" if not unmet
                    else "not satisfied: " + ", ".join(map(str, unmet)))


def candidates(root: Path) -> list[tuple[Path, str]]:
    """Every committed candidate and the status a working grader must give it."""
    alternatives = sorted(p for p in (root / "alternatives").iterdir() if p.is_dir())
    wrong = sorted(p for p in (root / "wrong").iterdir() if p.is_dir())
    if not alternatives or not wrong:
        raise SystemExit(
            f"{root}: no alternatives or no wrong outputs; an empty population "
            "cannot certify a grader"
        )
    return [
        (root / "fixture", "FAIL"),
        (root / "reference", "PASS"),
        *[(p, "PASS") for p in alternatives],
        *[(p, "FAIL") for p in wrong],
    ]


def certify(grader: Path, root: Path = HERE) -> tuple[bool, list[Row]]:
    rows = []
    for path, expected in candidates(root):
        status, detail = status_of(grader, path)
        rows.append(Row(str(path.relative_to(root)), expected, status, detail))
    return all(r.ok for r in rows), rows


def _show(title: str, certified: bool, rows: list[Row]) -> None:
    print(f"{title}: {'CERTIFIED' if certified else 'REFUSED'}")
    for r in rows:
        mark = "ok " if r.ok else "BAD"
        print(f"  {mark} {r.candidate:28} expected {r.expected:4} got {r.status:12} {r.detail}")


def main() -> int:
    good, rows = certify(HERE / "grade_slug.py")
    _show("grade_slug.py", good, rows)
    blind = []
    for name in CONTROLS:
        certified, rows = certify(HERE / "grader-controls" / f"{name}.py")
        _show(f"control {name}", certified, rows)
        if certified:
            blind.append(name)
    if not good:
        print("QUALIFY: fail - the grader does not discriminate the committed candidates")
        return 1
    if blind:
        print(f"QUALIFY: fail - the gate certified broken grader(s): {', '.join(blind)}")
        return 1
    print(f"QUALIFY: ok - grader certified; {len(CONTROLS)} broken graders refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
