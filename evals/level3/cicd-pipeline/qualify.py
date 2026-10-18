#!/usr/bin/env python3
"""Certify the Level 3 cicd-pipeline grader (#281) before any model is asked
to solve the task. The certification harness is slugkit-pipeline's, with one
change: every candidate is graded through skillc's staged verifier with the
probe INSIDE the cicd project runtime (`DockerBackend`, `--network none`),
because the probe executes generated CI artifacts with ruff, pytest and mypy.

    python3 qualify.py --receipt RECEIPT [--full]

RECEIPT is a `cicd-project-runtime` receipt (docker/cicd-project-trial/) whose
warmed lock is this task's own `reference/uv.lock`; anything else refuses.

A grader is certified only when, on the committed cases:

  - the starting `fixture/` FAILs (the task is not already solved);
  - `reference/`, every `alternatives/*` and `benign/*` PASS;
  - `unpatched-real/` (claude-power-pack's real, unpatched /project:init
    output - #1477/#1478) and every `wrong/*` FAIL;
  - every candidate's VIOLATED criteria are exactly its `expected.json`'s;
  - the sealed held-out task instance (`../../level3-heldout/cicd-pipeline/`)
    gives the same answers: its fixture FAILs, its reference PASSes;
  - every broken grader in `grader-controls/` is refused, producing the one
    status its name promises, on reference/ and unpatched-real/ (the controls
    ignore the probe's report, so two candidates are a sufficient witness).

MODES (skillc-400's D4 ruling). The full matrix is long, so:

  - `--full` runs EVERY case in `manifest()` and then checks that the executed
    set IS the manifest: a skipped or filtered case makes the run FAILED,
    never clean. run-real-docker (evals26) runs this on every main head.
  - the default runs the committed SUBSET only, and says so: its QUALIFY line
    reads `subset (N of M)`, so it can never be read as full certification.

Exit 0 only if every executed case held (and, in full mode, every case ran).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from skillc import docker_backend as d
from skillc import runtime_supply as rs
from skillc import verify

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade_cicd_pipeline as judge_module

HERE = Path(__file__).resolve().parent
HELDOUT = HERE.parent.parent / "level3-heldout" / "cicd-pipeline"
REQUIRED_CRITERIA = judge_module.CRITERIA
CONTROLS = {
    "always_pass": ("PASS", "verdict"),
    "always_fail": ("FAIL", "verdict"),
    "crash": ("INCONCLUSIVE", "exit-nonzero"),
    "no_output": ("INCONCLUSIVE", "no-output"),
    "omits_criterion": ("INCONCLUSIVE", "criteria-set"),
}
#: The witnesses each broken grader is run on.
CONTROL_WITNESSES = ("reference", "unpatched-real")
#: D4: the declared subset an unlocked or local run executes - a committed
#: constant, never chosen at runtime. The known-bad control is in it.
SUBSET: tuple[str, ...] = ("reference", "unpatched-real", "wrong/unconditional-success", "wrong/disabled-stage",
                           "control:always_pass")


@dataclass(frozen=True)
class Case:
    name: str
    path: Path
    expected: str
    violated: frozenset[str]
    judge: Path | None = None  # a grader-control judge; None is the task's own

    @property
    def is_control(self) -> bool:
        return self.judge is not None


def _expectation(path: Path, placed: str) -> tuple[str, frozenset[str]]:
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


def _dirs(root: Path, sub: str) -> list[Path]:
    found = sorted(p for p in (root / sub).iterdir() if p.is_dir())
    if not found:
        raise SystemExit(f"{root / sub}: empty; an empty population cannot certify a grader")
    return found


def manifest(root: Path = HERE, heldout: Path = HELDOUT) -> list[Case]:
    """Every case the full certification must execute, in order."""
    placed: list[tuple[str, Path, str]] = [
        ("fixture", root / "fixture", "FAIL"),
        ("reference", root / "reference", "PASS"),
        ("unpatched-real", root / "unpatched-real", "FAIL"),
        *[(f"alternatives/{p.name}", p, "PASS") for p in _dirs(root, "alternatives")],
        *[(f"benign/{p.name}", p, "PASS") for p in _dirs(root, "benign")],
        *[(f"wrong/{p.name}", p, "FAIL") for p in _dirs(root, "wrong")],
        ("heldout/fixture", heldout / "fixture", "FAIL"),
        ("heldout/reference", heldout / "reference", "PASS"),
    ]
    cases = [Case(name, path, *_expectation(path, want)) for name, path, want in placed]
    for control in CONTROLS:
        judge = root / "grader-controls" / f"{control}.py"
        if not judge.is_file():
            raise SystemExit(f"control {judge.name} does not exist")
        for witness in CONTROL_WITNESSES:
            cases.append(Case(f"control:{control}@{witness}", root / witness, *CONTROLS[control][:1],
                              frozenset(), judge=judge))
    return cases


def select(cases: list[Case], full: bool) -> list[Case]:
    if full:
        return list(cases)
    wanted = set(SUBSET)
    return [c for c in cases if c.name in wanted or c.name.split("@", 1)[0] in wanted]


def _files(candidate: Path) -> list[tuple[str, bytes, bool]]:
    out: list[tuple[str, bytes, bool]] = []
    for dirpath, dirnames, filenames in os.walk(candidate, followlinks=False):
        # Tool caches a local run left behind are not the candidate's files.
        dirnames[:] = sorted(n for n in dirnames if n not in ("__pycache__", ".venv", ".pytest_cache",
                                                               ".ruff_cache", ".mypy_cache"))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                out.append((path.relative_to(candidate).as_posix(), path.read_bytes(), bool(info.st_mode & stat.S_IXUSR)))
    return out


@dataclass
class Row:
    case: str
    expected: str
    status: str
    category: str
    detail: str
    ok: bool


GradeFn = Callable[[Case], tuple[str, str, frozenset[str], str]]


def runtime_backend(receipt: Path) -> Callable[[], d.DockerBackend]:
    """A fresh DockerBackend factory on the receipt's image, bound to this task's lock."""
    supply = rs.RuntimeSupply.from_path(receipt)
    rs.require_kind(supply, rs.CICD_PROJECT_RUNTIME)
    value = json.loads(supply.receipt_bytes)
    lock = hashlib.sha256((HERE / "reference" / "uv.lock").read_bytes()).hexdigest()
    if value["project_lock_sha256"] != lock:
        raise SystemExit("the receipt warmed a different project lock than this task's reference/uv.lock")
    base = Path(tempfile.mkdtemp(prefix="sk-281-qualify-"))
    return lambda: d.DockerBackend(image=supply.image_id, base_dir=base, network="none",
                                   daemon_timeout=60.0)


def staged_grade(backend: Callable[[], d.DockerBackend]) -> GradeFn:
    def grade(case: Case) -> tuple[str, str, frozenset[str], str]:
        grader = verify.GraderDef.load(HERE)
        if case.judge is not None:
            grader = grader.with_judge(case.judge)
        graded = verify.grade_files(grader, _files(case.path), Path(tempfile.gettempdir()), backend=backend())
        return graded.status, graded.category, graded.violated, graded.detail
    return grade


def run(cases: Iterable[Case], grade: GradeFn, *, full: bool, manifest_cases: list[Case]) -> tuple[bool, list[Row], str]:
    rows: list[Row] = []
    for case in cases:
        status, category, violated, detail = grade(case)
        if case.is_control:
            want = CONTROLS[Path(str(case.judge)).stem]
            ok = (status, category) == want
        else:
            ok = status == case.expected and violated == case.violated
        rows.append(Row(case.name, case.expected, status, category, detail, ok))
    # A control that behaved as named must also be REFUSED: on some witness its
    # status differs from what a working grader gives (always_pass on the
    # known-bad, always_fail on the reference, no verdict anywhere).
    expected_of = {c.name: c.expected for c in manifest_cases if not c.is_control}
    for control in {r.case.split("@", 1)[0] for r in rows if r.case.startswith("control:")}:
        mine = [r for r in rows if r.case.split("@", 1)[0] == control]
        if not any(r.status != expected_of.get(r.case.split("@", 1)[1]) for r in mine):
            for r in mine:
                r.ok = False
                r.detail = f"{control} was not refused: it agreed with every witness's expected status"
    total = len(manifest_cases)
    executed = [r.case for r in rows]
    held = all(r.ok for r in rows)
    if full:
        complete = sorted(executed) == sorted(c.name for c in manifest_cases)
        if not complete:
            missing = sorted({c.name for c in manifest_cases} - set(executed))
            return False, rows, f"QUALIFY: FAILED full ({len(executed)} of {total}): cases not executed: {missing}"
        line = f"full ({total} of {total})"
    else:
        # The subset is a committed contract too: exactly its expanded cases, never
        # an empty or partial selection read as "the subset passed".
        wanted = sorted(c.name for c in select(manifest_cases, full=False))
        if not executed or sorted(executed) != wanted:
            missing = sorted(set(wanted) - set(executed))
            return False, rows, (f"QUALIFY: FAILED subset ({len(executed)} of {total}): not the declared subset; "
                                 f"missing {missing}")
        line = f"subset ({len(executed)} of {total})"
    return held, rows, f"QUALIFY: {'ok' if held else 'FAILED'} {line}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--receipt", type=Path, required=True, help="a cicd-project-runtime receipt")
    parser.add_argument("--full", action="store_true", help="run every case (run-real-docker)")
    args = parser.parse_args(argv)
    cases = manifest()
    held, rows, line = run(select(cases, args.full), staged_grade(runtime_backend(args.receipt)),
                           full=args.full, manifest_cases=cases)
    for r in rows:
        print(f"{'ok' if r.ok else 'XX'} {r.case}: {r.status} ({r.category}) - {r.detail}")
    print(line)
    return 0 if held and line.startswith("QUALIFY: ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
