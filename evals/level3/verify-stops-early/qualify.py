#!/usr/bin/env python3
"""Certify the Level 3 verify-stops-early grader before any model is asked to
solve the task. Same shape as gate-stops-early/qualify.py (itself following
gate-ran-nothing/qualify.py); see that file's module docstring for the full
rationale - restated only where this task's own criteria set differs.

`flow-check-honest` (consuming skillc#332's gate-witness contract) is not
yet declared - see grade_verify_stops_early.py's own module docstring - so
this file certifies only the three criteria that are.

Exit 0 only if the grader discriminates, every broken-grader control is
refused with the right verdict, and every restore-probe validity control
holds.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from skillc import verify

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade_verify_stops_early as judge_module  # the task's own judge, beside this file

HERE = Path(__file__).resolve().parent
REQUIRED_CRITERIA = judge_module.CRITERIA

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
    if not (path / "pyproject.toml").is_file():
        raise SystemExit(f"{path}: no pyproject.toml; a missing candidate cannot calibrate")
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


def _probe_report(candidate: Path, probe_inputs: dict[str, object] | None = None) -> dict[str, object]:
    envelope = judge_module.run_probe(candidate, probe_inputs=probe_inputs)
    report = judge_module.read_report(envelope)
    if report is None:
        raise SystemExit(f"{candidate}: the probe produced no well-formed report: {envelope}")
    return report


def restore_probe_validity(root: Path = HERE) -> list[tuple[str, bool, str]]:
    """(check, held, detail) for every restore-probe validity control. See
    the module docstring."""
    checks: list[tuple[str, bool, str]] = []

    report = _probe_report(root / "wrong" / "regression-passes-on-unfixed")
    outcome = next(c["outcome"] for c in judge_module.judge({"observations": json.dumps(report),
                                                             "timed_out": False})["criteria"]
                   if c["id"] == "regression-fails-on-original")
    checks.append(("wrong/regression-passes-on-unfixed: regression-fails-on-original is VIOLATED under the real judge",
                   outcome == "VIOLATED", f"got {outcome}"))

    report = _probe_report(root / "wrong" / "regression-passes-on-unfixed")
    blinded = judge_module.judge({"observations": json.dumps(report), "timed_out": False}, blind_restore=True)
    outcomes = {c["id"]: c["outcome"] for c in blinded["criteria"]}
    flipped = outcomes["regression-fails-on-original"] == "SATISFIED"
    checks.append(("blinding the restore step turns wrong/regression-passes-on-unfixed PASS",
                   flipped, f"got {outcomes}"))

    missing_target = dict(judge_module.inputs())
    missing_target["restore"] = {**missing_target["restore"], "file": "textkit/absent.py"}
    report = _probe_report(root / "reference", missing_target)
    outcomes = {c["id"]: c["outcome"] for c in judge_module.judge({"observations": json.dumps(report),
                                                                   "timed_out": False})["criteria"]}
    checks.append(("a restore target absent from the tree -> regression-fails-on-original UNKNOWN",
                   outcomes["regression-fails-on-original"] == "UNKNOWN",
                   f"got {outcomes}"))

    outcomes = {c["id"]: (c["outcome"], c["mandatory"])
               for c in judge_module.judge({"observations": "{not json", "timed_out": False})["criteria"]}
    checks.append(("a malformed probe report -> every mandatory criterion UNKNOWN",
                   all(o == "UNKNOWN" for o, mandatory in outcomes.values() if mandatory),
                   f"got {outcomes}"))

    return checks


def main() -> int:
    good, rows = certify(HERE / "grade_verify_stops_early.py")
    _show("grade_verify_stops_early.py", good, rows)
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
    validity = restore_probe_validity()
    print("restore-probe validity:")
    for name, held, detail in validity:
        print(f"  {'ok ' if held else 'BAD'} {name}" + ("" if held else f": {detail}"))
    if not all(held for _name, held, _detail in validity):
        print("QUALIFY: fail - a restore-probe validity control did not hold")
        return 1
    print(f"QUALIFY: ok - grader certified; {len(CONTROLS)} broken graders refused; "
          f"{len(validity)} restore-probe validity controls held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
