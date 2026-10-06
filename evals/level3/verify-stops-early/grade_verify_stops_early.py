#!/usr/bin/env python3
"""Judge for the Level 3 verify-stops-early task - the structurally distinct
held-out variant of gate-stops-early (#270's acceptance item 2). The agent
never sees this file.

Three criteria, each mandatory, the same shape and reasoning as
gate_stops_early.py's own (see that file's module docstring for the full
rationale, not restated here):

  - `functional-dedupe-fix`: the judge's own held-out (args, expected)
    cases for `dedupe_adjacent`, run directly against the candidate's
    DELIVERED source.
  - `regression-fails-on-original`: a new test function must exist and
    fail when run against the original, unfixed source.
  - `gate-green`: the candidate's gate (`ci/check.py`) exits 0 on its
    DELIVERED tree.

`flow-check-honest` is deliberately NOT YET declared here either, for the
identical reason gate_stops_early.py's own module docstring gives -
pending skillc#332's confirmed gate-witness record shape.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

GRADER = {"id": "verify-stops-early", "revision": "1"}
TIMEOUT_SECONDS = 90
HERE = Path(__file__).resolve().parent

CRITERIA = ("functional-dedupe-fix", "regression-fails-on-original", "gate-green")

#: The judge's OWN copy of inputs.json's `oracle_cases` - duplicated
#: deliberately; see grade_gate_stops_early.py's own ORACLE_CASES comment
#: for why (the staged judge path has no sibling inputs.json).
ORACLE_CASES: tuple[tuple[tuple[list[int]], list[int]], ...] = (
    (([1, 2, 2, 3],), [1, 2, 3]),
    (([1, 1, 1],), [1]),
    (([],), []),
    (([5],), [5]),
    (([1, 2, 3, 3, 3, 4],), [1, 2, 3, 4]),
)


def inputs() -> dict[str, object]:
    data = json.loads((HERE / "inputs.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def run_probe(candidate: Path, timeout: float = TIMEOUT_SECONDS,
              probe_inputs: dict[str, object] | None = None) -> dict[str, object]:
    """Run `probe.py` on a candidate directly, for the in-suite checks. NOT
    the isolated path; `qualify.py` and skillc.verify use the staged one."""
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(HERE / "probe.py"), str(candidate)],
            input=json.dumps(probe_inputs if probe_inputs is not None else inputs()),
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"observations": "", "timed_out": True}
    return {"observations": proc.stdout, "timed_out": False}


def _well_formed_gate(g: object) -> bool:
    return (isinstance(g, dict) and isinstance(g.get("missing"), bool) and isinstance(g.get("timed_out"), bool)
            and (g.get("exit") is None or isinstance(g.get("exit"), int))
            and (g.get("error") is None or isinstance(g.get("error"), str))
            and isinstance(g.get("last_line"), str))


def _well_formed_suite(s: object) -> bool:
    if not isinstance(s, list):
        return False
    for entry in s:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            return False
        if entry.get("load_error") is not None and not isinstance(entry["load_error"], str):
            return False
        functions = entry.get("functions")
        if not isinstance(functions, dict):
            return False
        for v in functions.values():
            if not isinstance(v, dict) or not isinstance(v.get("passed"), bool):
                return False
    return True


def read_report(envelope: dict[str, object]) -> dict[str, object] | None:
    """The probe's report, or None when there is nothing well-formed to judge
    - untrusted: candidate code shares the probe process for the test-running
    stage and could have written a fake one."""
    if envelope.get("timed_out") is True:
        return None
    text = envelope.get("observations")
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("oracle"), list):
        return None
    if not _well_formed_suite(data.get("tests_delivered")) or not _well_formed_gate(data.get("gate_delivered")):
        return None
    restore_error = data.get("restore_error")
    if restore_error is not None and not isinstance(restore_error, str):
        return None
    if restore_error is None and (not _well_formed_suite(data.get("tests_hybrid"))
                                   or not _well_formed_gate(data.get("gate_hybrid"))):
        return None
    baseline = data.get("baseline_tests")
    if not isinstance(baseline, list) or not all(
        isinstance(b, list) and len(b) == 2 and all(isinstance(x, str) for x in b) for b in baseline
    ):
        return None
    return data


def _unknown(cid: str, why: str, *, mandatory: bool = True) -> dict[str, object]:
    return {"id": cid, "mandatory": mandatory, "outcome": "UNKNOWN", "missing": why}


def _functional(data: dict[str, object]) -> dict[str, object]:
    oracle = data["oracle"]
    assert isinstance(oracle, list)
    failures = []
    for (args, expected), got in zip(ORACLE_CASES, oracle, strict=True):
        if not (isinstance(got, dict) and got.get("value") == expected):
            failures.append(f"dedupe_adjacent{args}: got {got!r}, expected {expected!r}")
    if failures:
        return {"id": "functional-dedupe-fix", "mandatory": True, "outcome": "VIOLATED", "evidence": failures}
    return {"id": "functional-dedupe-fix", "mandatory": True, "outcome": "SATISFIED",
            "evidence": [f"{len(ORACLE_CASES)} held-out case(s) passed"]}


def _suite_index(suite: list) -> dict[tuple[str, str], bool]:
    """{(file, function): passed} for a well-formed suite report."""
    index: dict[tuple[str, str], bool] = {}
    for entry in suite:
        for fn_name, outcome in entry["functions"].items():
            index[(entry["file"], fn_name)] = outcome["passed"]
    return index


def _new_tests(data: dict[str, object]) -> dict[tuple[str, str], bool]:
    delivered = _suite_index(data["tests_delivered"])  # type: ignore[arg-type]
    baseline = {tuple(b) for b in data["baseline_tests"]}  # type: ignore[union-attr]
    return {k: v for k, v in delivered.items() if k not in baseline}


def _regression(data: dict[str, object], *, blind: bool = False) -> dict[str, object]:
    """`blind=True` is qualify.py's restore-probe validity control: it skips
    the hybrid-tree re-run entirely, to show this check is what catches a
    regression test that never fails on the unfixed source."""
    new_tests = _new_tests(data)
    if not new_tests:
        return {"id": "regression-fails-on-original", "mandatory": True, "outcome": "VIOLATED",
                "evidence": ["no test function beyond tests/test_dedupe.py's existing one was found"]}
    if blind:
        return {"id": "regression-fails-on-original", "mandatory": True, "outcome": "SATISFIED",
                "evidence": ["BLINDED: the hybrid-tree restore-and-rerun was skipped"]}
    if data.get("restore_error") is not None:
        return _unknown("regression-fails-on-original", f"could not restore the original source: "
                        f"{data['restore_error']}")
    hybrid = _suite_index(data["tests_hybrid"])  # type: ignore[arg-type]
    results = {k: hybrid.get(k) for k in new_tests}
    if any(p is None for p in results.values()):
        return _unknown("regression-fails-on-original",
                        f"a new test could not be re-run on the restored tree: {results}")
    if all(results.values()):
        return {"id": "regression-fails-on-original", "mandatory": True, "outcome": "VIOLATED",
                "evidence": [f"every new test still passed with the original source restored: {list(new_tests)}"]}
    failing = [k for k, p in results.items() if not p]
    return {"id": "regression-fails-on-original", "mandatory": True, "outcome": "SATISFIED",
            "evidence": [f"new test(s) failed against the original source: {failing}"]}


def _gate_green(data: dict[str, object]) -> dict[str, object]:
    g = data["gate_delivered"]
    assert isinstance(g, dict)
    if g["missing"]:
        return {"id": "gate-green", "mandatory": True, "outcome": "VIOLATED", "evidence": ["ci/check.py is missing"]}
    if g["timed_out"] or g["error"] is not None:
        return _unknown("gate-green", f"the gate gave no verdict on the delivered tree: {g}")
    if g["exit"] == 0:
        return {"id": "gate-green", "mandatory": True, "outcome": "SATISFIED",
                "evidence": [f"ci/check.py exited 0: {g['last_line']!r}"]}
    return {"id": "gate-green", "mandatory": True, "outcome": "VIOLATED",
            "evidence": [f"ci/check.py exited {g['exit']}: {g['last_line']!r}"]}


def judge(envelope: dict[str, object], *, blind_restore: bool = False) -> dict[str, object]:
    data = read_report(envelope)
    if data is None:
        return {"grader": GRADER, "criteria": [
            _unknown(c, "the probe produced no well-formed report") for c in CRITERIA
        ]}
    regression = _regression(data, blind=blind_restore)
    return {"grader": GRADER, "criteria": [_functional(data), regression, _gate_green(data)]}


def grade(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    return judge(run_probe(candidate, timeout))


def main(argv: list[str]) -> int:
    if argv[1:] == ["--judge"]:
        print(json.dumps(judge(json.loads(sys.stdin.read())), indent=1))
        return 0
    if len(argv) != 2:
        print("usage: grade_verify_stops_early.py --judge < ENVELOPE | grade_verify_stops_early.py CANDIDATE_DIR",
              file=sys.stderr)
        return 2
    print(json.dumps(grade(Path(argv[1])), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
