#!/usr/bin/env python3
"""Probe for the Level 3 gate-ran-nothing task: the ONLY grading code that
runs candidate code.

Usage: probe.py CANDIDATE_DIR, with inputs.json's object on stdin:
`{"oracle_cases": [...], "restore": {...}, "baseline_tests": [...]}`.

Reports observations, never a verdict - grade_gate_ran_nothing.py --judge
holds every expected value and compares:

  - `oracle`: the judge's own held-out (args, expected) pairs for
    `rangekit.core.clamp`, called directly against the candidate's DELIVERED
    source (`functional-clamp-fix`). Never the candidate's own test file.
  - `tests_delivered`: every `test_*.py` file anywhere under the candidate's
    `tests/`, discovered by walking the filesystem directly (never through
    the candidate's own `ci/check.py`, whose discovery is exactly what this
    task plants a defect in) and run function-by-function.
  - `gate_delivered`: the candidate's own `ci/check.py`, run on a copy of its
    clean, delivered tree (`gate-green`).
  - `tests_hybrid` / `gate_hybrid`: the same two observations again, on a
    FRESH copy of the candidate with `restore.file` (the one function file
    ISSUE.md reports) overwritten back to `restore.content` - its ORIGINAL,
    unfixed bytes, pinned in inputs.json. Everything else in the candidate's
    tree - its own `ci/check.py`, its own added test(s) - is untouched. This
    is `regression-fails-on-original` and `gate-honest`.

`restore.file` absent from the candidate's tree is reported as
`restore_error`, and the hybrid-tree observations are skipped entirely - a
candidate that deleted or renamed the file under test gives no proof either
way.

Runs under `python -I -S -B` (skillc.verify). The candidate's gate is
launched with `-E -s -B`, cwd set to the tree copy it checks - the public
`python3 ci/check.py` invocation's own import semantics, without the
evaluator's environment or user site.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GATE_TIMEOUT = 30
GATE_FILE = os.path.join("ci", "check.py")
MAX_LINE = 400


def _discover_test_files(tree_root: Path) -> list[Path]:
    tests_root = tree_root / "tests"
    if not tests_root.is_dir():
        return []
    return sorted(tests_root.rglob("test_*.py"))


def _clear_rangekit_modules() -> None:
    for name in list(sys.modules):
        if name == "rangekit" or name.startswith("rangekit."):
            del sys.modules[name]


def _run_test_file(path: Path, tree_root: Path) -> dict:
    rel = path.relative_to(tree_root).as_posix()
    sys.path.insert(0, str(tree_root))
    try:
        spec = importlib.util.spec_from_file_location(f"probe_test_{abs(hash(rel))}", path)
        if spec is None or spec.loader is None:
            return {"file": rel, "load_error": "could not be loaded", "functions": {}}
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException as exc:  # noqa: BLE001 - any failure of candidate code is its own
            return {"file": rel, "load_error": f"{type(exc).__name__}: {exc}", "functions": {}}
    finally:
        sys.path.remove(str(tree_root))
    functions = {}
    for name in dir(module):
        fn = getattr(module, name)
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001
                functions[name] = {"passed": False, "detail": f"{type(exc).__name__}: {exc}"}
            else:
                functions[name] = {"passed": True}
    return {"file": rel, "load_error": None, "functions": functions}


def run_test_suite(tree: str) -> list:
    _clear_rangekit_modules()
    root = Path(tree)
    return [_run_test_file(p, root) for p in _discover_test_files(root)]


def run_oracle(tree: str, oracle_cases: list) -> list:
    _clear_rangekit_modules()
    sys.path.insert(0, tree)
    try:
        try:
            import rangekit.core as module
        except BaseException as exc:  # noqa: BLE001
            return [{"raised": f"{type(exc).__name__}: {exc}"} for _ in oracle_cases]
        fn = getattr(module, "clamp", None)
        if not callable(fn):
            return [{"raised": "rangekit.core defines no callable clamp"} for _ in oracle_cases]
        results = []
        for case in oracle_cases:
            try:
                got = fn(*case["args"])
            except BaseException as exc:  # noqa: BLE001
                results.append({"raised": f"{type(exc).__name__}: {exc}"})
            else:
                results.append({"value": got})
        return results
    finally:
        sys.path.remove(tree)
        _clear_rangekit_modules()


def run_gate(tree: str) -> dict:
    script = os.path.join(tree, GATE_FILE)
    if not os.path.isfile(script):
        return {"missing": True, "exit": None, "timed_out": False, "error": None, "last_line": ""}
    try:
        proc = subprocess.run([sys.executable, "-E", "-s", "-B", script], cwd=tree,
                              capture_output=True, text=True, timeout=GATE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return {"missing": False, "exit": None, "timed_out": True, "error": None, "last_line": ""}
    except OSError as exc:
        return {"missing": False, "exit": None, "timed_out": False,
                "error": f"could not launch the gate: {type(exc).__name__}: {exc}", "last_line": ""}
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return {"missing": False, "exit": proc.returncode, "timed_out": False, "error": None,
            "last_line": (lines[-1].strip() if lines else "")[:MAX_LINE]}


def _copy(src: str, dst_parent: str) -> str:
    dest = os.path.join(dst_parent, "tree")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def main() -> None:
    report = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    candidate_dir = sys.argv[1]
    inputs = json.loads(sys.stdin.read())
    oracle_cases = inputs.get("oracle_cases") if isinstance(inputs, dict) else None
    restore = inputs.get("restore") if isinstance(inputs, dict) else None
    baseline_tests = inputs.get("baseline_tests") if isinstance(inputs, dict) else None
    if not isinstance(oracle_cases, list) or not isinstance(restore, dict) or not isinstance(baseline_tests, list):
        report.write(json.dumps({"error": "inputs carry no oracle_cases, restore or baseline_tests"}))
        report.flush()
        return

    result: dict = {"baseline_tests": baseline_tests}
    with tempfile.TemporaryDirectory() as work:
        delivered = _copy(candidate_dir, work)
        result["oracle"] = run_oracle(delivered, oracle_cases)
        result["tests_delivered"] = run_test_suite(delivered)
        result["gate_delivered"] = run_gate(delivered)

    with tempfile.TemporaryDirectory() as work:
        hybrid = _copy(candidate_dir, work)
        target = os.path.join(hybrid, restore["file"])
        if not os.path.isfile(target):
            result["restore_error"] = f"{restore['file']} is absent from the candidate tree"
            result["tests_hybrid"] = None
            result["gate_hybrid"] = None
        else:
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(restore["content"])
            result["restore_error"] = None
            result["tests_hybrid"] = run_test_suite(hybrid)
            result["gate_hybrid"] = run_gate(hybrid)

    report.write(json.dumps(result))
    report.flush()


if __name__ == "__main__":
    main()
