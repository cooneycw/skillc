#!/usr/bin/env python3
"""Certify the Level 3 slugkit-pipeline grader before any model is asked to
solve the task (#204). The generic certification harness is slugkit-installed's
(itself copied from Level 1's slug-small-fix/qualify.py); this task adds a
`benign/` population and a PIPELINE-VALIDITY gate (`pipeline_validity`),
described after the generic part below.

A grader is certified only when, on this task's committed candidates:

  - the starting fixture FAILs (the task is not already solved);
  - the reference and every valid alternative PASS (alternatives are accepted);
  - every plausible wrong output FAILs (the grader discriminates);
  - and every candidate's VIOLATED criteria are exactly those its `expected.json`
    names, so a FAIL for the wrong reason does not count as discrimination.

Candidates are DERIVED from the directories under `alternatives/` and `wrong/`.
An empty population, a candidate without `pyproject.toml` or `expected.json`, or
an expectation that contradicts the candidate's placement refuses outright.

A grader report must carry exactly the task's required criteria, each mandatory
and each once. A report that drops one is not a verdict on the task.

Every candidate is graded through skillc's verifier (`skillc.verify.grade_directory`),
the same staged path that grades a real attempt (#9): the probe runs the
candidate on a disposable copy under a contained supervisor, the judge runs
afterwards, and skillc derives the status with `records.derive_status`. So what
is certified here is what grades. A judge that exits non-zero, prints nothing,
or prints something the contract rejects produced no verdict: that is
INCONCLUSIVE, never FAIL. A crash is not a detected defect.

A broken-grader control replaces the JUDGE (`GraderDef.with_judge`); the probe
and the inputs stay the task's own.

`python3 qualify.py` certifies the real grader AND requires each broken grader in
`grader-controls/` to exist, to be refused, and to produce the one status its
name promises on every candidate - so a missing or misbehaving control cannot
count as a refused one.

PIPELINE VALIDITY (#204 acceptance item 2). `pipeline-honest` is itself an
instrument - it reads planted defects as evidence about a candidate's pipeline
- so it gets its own controls, run on the committed `reference/`:

  - the clean tree passes its pipeline;
  - each planted defect is proven to have introduced its defect (the
    installed output changed) and is rejected by THE STEP that should catch
    it - `behaviour-trailing-hyphen` by `test` alone, `packaging-entry-point`
    by `package` alone - not merely by something;
  - the benign change is proven benign and is accepted;
  - and the paths that must never count as detection do not: a malformed
    mutation, a "defect" that changes nothing, a pipeline that crashed with no
    verdict line, one that timed out, and one that could not be launched (a
    missing tool) each make `pipeline-honest` UNKNOWN. The first two run the
    real probe with altered inputs; the last three alter a real report, since
    the probe cannot be made to lose its own interpreter from inside a test.

Exit 0 only if all of that holds.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from skillc import verify

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade_slugkit_pipeline as judge_module  # the task's own judge, beside this file

HERE = Path(__file__).resolve().parent
#: The criteria every report for this task must carry, each mandatory, once.
#: `grader.json` declares the same set.
REQUIRED_CRITERIA = judge_module.CRITERIA

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


def status_of(grader: Path, candidate: Path, root: Path = HERE) -> tuple[str, str, frozenset[str], str]:
    """(status, detail, VIOLATED criterion ids, category) for one grading run.

    `grader` is the judge; the probe, inputs and required criteria come from the
    task's `grader.json` under `root`. The category names WHICH path produced the
    status, so two broken graders that both yield INCONCLUSIVE - a crash and an
    empty report - stay distinguishable.
    """
    graded = verify.grade_directory(verify.GraderDef.load(root).with_judge(grader), candidate)
    return graded.status, graded.detail, graded.violated, graded.category


def _expectation(path: Path, placed: str) -> tuple[str, frozenset[str]]:
    """The committed expectation for one candidate, checked against its placement."""
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
    """Every committed candidate, the status and violations a working grader gives."""
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


#: The step of the reference pipeline that must reject each planted defect.
EXPECTED_STEP = {"behaviour-trailing-hyphen": "test", "packaging-entry-point": "package"}


def _honest_outcome(report: dict[str, object]) -> tuple[str, str]:
    criteria = judge_module.judge({"observations": json.dumps(report), "timed_out": False})["criteria"]
    honest = next(c for c in criteria if c["id"] == "pipeline-honest")
    return str(honest["outcome"]), str(honest.get("missing") or honest.get("evidence"))


def _probe_report(candidate: Path, probe_inputs: dict[str, object] | None = None) -> dict[str, object]:
    envelope = judge_module.run_probe(candidate, probe_inputs=probe_inputs)
    report = judge_module.read_report(envelope)
    if report is None:
        raise SystemExit(f"{candidate}: the probe produced no well-formed report: {envelope}")
    return report


def _with_mutation(mid: str, **changes: object) -> dict[str, object]:
    data = judge_module.inputs()
    mutations = data["mutations"]
    assert isinstance(mutations, list)
    data["mutations"] = [{**m, **changes} if m.get("id") == mid else m for m in mutations]
    return data


def _with_pipeline(report: dict[str, object], mid: str, pipeline: dict[str, object]) -> dict[str, object]:
    mutations = report["mutations"]
    assert isinstance(mutations, list)
    return {**report, "mutations": [{**m, "pipeline": pipeline} if m.get("id") == mid else m
                                    for m in mutations]}


def pipeline_validity(root: Path = HERE) -> list[tuple[str, bool, str]]:
    """(check, held, detail) for every pipeline-validity control. See the
    module docstring."""
    reference = root / "reference"
    report = _probe_report(reference)
    checks: list[tuple[str, bool, str]] = []
    clean = report["pipeline"]
    assert isinstance(clean, dict)
    checks.append(("clean tree passes", judge_module.pipeline_verdict(clean) == "ok", str(clean)))
    entries = {str(m["id"]): m for m in report["mutations"]}  # type: ignore[union-attr]
    for mid, kind in judge_module.MUTATION_KINDS:
        verdict, detail = judge_module.mutation_verdict(kind, report["installed_outputs"], entries[mid])  # type: ignore[arg-type]
        if kind == "benign":
            checks.append((f"{mid}: proven benign and accepted", verdict == "accepted", detail))
            continue
        last = entries[mid]["pipeline"]["last_line"]
        want = f"VERIFY: fail {EXPECTED_STEP[mid]}"
        checks.append((f"{mid}: proven and rejected by step {EXPECTED_STEP[mid]!r}",
                       verdict == "detected" and last == want, f"{detail}; want last line {want!r}"))

    outcome, detail = _honest_outcome(report)
    checks.append(("the unaltered reference is SATISFIED", outcome == "SATISFIED", detail))
    for name, altered in (
        ("malformed mutation (file absent)",
         _probe_report(reference, _with_mutation("behaviour-trailing-hyphen", file="slugkit/absent.py"))),
        ("malformed mutation (required text absent)",
         _probe_report(reference, _with_mutation("behaviour-trailing-hyphen", require="def never_defined"))),
        ("defect not proven (the planted text changes nothing)",
         _probe_report(reference, _with_mutation("behaviour-trailing-hyphen", text="\n# inert\n"))),
        ("pipeline crashed with no verdict line",
         _with_pipeline(report, "behaviour-trailing-hyphen",
                        {"missing": False, "exit": 1, "last_line": "NameError: boom", "timed_out": False,
                         "error": None})),
        ("pipeline timed out",
         _with_pipeline(report, "packaging-entry-point",
                        {"missing": False, "exit": None, "last_line": "", "timed_out": True, "error": None})),
        ("missing tool (the pipeline could not be launched)",
         _with_pipeline(report, "packaging-entry-point",
                        {"missing": False, "exit": None, "last_line": "", "timed_out": False,
                         "error": "could not launch the pipeline: FileNotFoundError"})),
    ):
        outcome, detail = _honest_outcome(altered)
        checks.append((f"{name} -> UNKNOWN, never detection", outcome == "UNKNOWN", detail))
    return checks


def main() -> int:
    good, rows = certify(HERE / "grade_slugkit_pipeline.py")
    _show("grade_slugkit_pipeline.py", good, rows)
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
    validity = pipeline_validity()
    print("pipeline validity:")
    for name, held, detail in validity:
        print(f"  {'ok ' if held else 'BAD'} {name}" + ("" if held else f": {detail}"))
    if not all(held for _name, held, _detail in validity):
        print("QUALIFY: fail - a pipeline-validity control did not hold")
        return 1
    print(f"QUALIFY: ok - grader certified; {len(CONTROLS)} broken graders refused; "
          f"{len(validity)} pipeline-validity controls held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
