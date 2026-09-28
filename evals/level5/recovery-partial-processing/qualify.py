#!/usr/bin/env python3
"""Certify the recovery-partial-processing grader before any model is asked
to solve the task.

Adapted from `evals/level4/instruction-conflict-config-secret/qualify.py`,
same shape and the same third status: `self-written-log` derives
INCONCLUSIVE (`records.derive_status`: an UNKNOWN mandatory criterion with
no VIOLATED one), never a manufactured FAIL. `expected.json`'s `violated`
list is empty for both PASS and INCONCLUSIVE; only FAIL requires a
non-empty one.

Every candidate is graded through skillc's verifier
(`skillc.verify.grade_directory`), the same staged path a real attempt
uses (#9): the probe reads `src/output/*.json`, `src/report.json` and
`src/disruption-log.json` from a disposable copy under a contained
supervisor - no candidate code runs for this task - and the judge runs
afterwards.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from skillc import verify

HERE = Path(__file__).resolve().parent

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
    if not (path / "src" / "disruption-log.json").is_file():
        raise SystemExit(f"{path}: no src/disruption-log.json; a missing candidate cannot calibrate")
    try:
        data = json.loads((path / "expected.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path}: unreadable expected.json: {exc}") from exc
    status, violated = data.get("status"), data.get("violated")
    if status != placed or not isinstance(violated, list):
        raise SystemExit(f"{path}: expected.json says {status!r}, placement says {placed!r}")
    if (placed == "FAIL") != bool(violated):
        raise SystemExit(f"{path}: a FAIL must name violated criteria, PASS/INCONCLUSIVE none")
    return placed, frozenset(map(str, violated))


def candidates(root: Path) -> list[tuple[Path, str, frozenset[str]]]:
    wrong = sorted(p for p in (root / "wrong").iterdir() if p.is_dir())
    if not wrong:
        raise SystemExit(f"{root}: no wrong outputs; an empty population cannot certify a grader")
    placed: list[tuple[Path, str]] = [(root / "reference", "PASS")]
    for p in wrong:
        expected_path = p / "expected.json"
        try:
            status = json.loads(expected_path.read_text(encoding="utf-8")).get("status")
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"{expected_path}: unreadable: {exc}") from exc
        if status not in ("FAIL", "INCONCLUSIVE"):
            raise SystemExit(f"{expected_path}: status {status!r} is not FAIL or INCONCLUSIVE for a wrong/ candidate")
        placed.append((p, status))
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
        print(f"  {mark} {r.candidate:26} expected {r.expected:12} got {r.status:12} {r.detail}")


def main() -> int:
    good, rows = certify(HERE / "grade_recovery.py")
    _show("grade_recovery.py", good, rows)
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
