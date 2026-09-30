#!/usr/bin/env python3
"""Probe for the Level 3 slugkit-pipeline task (#204): the ONLY grading code
that runs candidate code.

Usage: probe.py CANDIDATE_DIR, with inputs.json's object on stdin:
`{"titles": [...], "mutations": [...]}`.

Reports observations, never a verdict - grade_slugkit_pipeline.py --judge
holds every expected value, every mutation's kind, and compares:

  - `unit_test`: the candidate's `tests/test_core.py`, run against its source
    tree (`functional-trailing-hyphen`, as in slugkit-installed).
  - `installed_outputs`: what the candidate's `[project.scripts]` console
    command prints for each title after a stdlib-emulated install - only the
    declared package directories are copied (`integration-installed-path`).
  - `pipeline`: the candidate's own `python3 ci/verify.py`, run on a copy of
    its clean tree (`pipeline-green`).
  - `mutations`: for each declared mutation, a FRESH copy of the candidate
    with that one change planted, then the same two observations on it - its
    `installed_outputs` (so the judge can check the change really took effect,
    or really changed nothing, before it counts anything) and its `pipeline`
    result (`pipeline-honest`).

A mutation that cannot be applied as written - its file is missing, its
required text is absent, the pyproject target is not found exactly once - is
reported `applied: {"error": ...}` and never run: a malformed mutation is not
a detection. A pipeline that could not be launched, timed out, or is missing
is reported as exactly that, so the judge can tell "no verdict" from "fail".

Install mode is stdlib emulation only (slugkit-installed's README explains
why pip is absent everywhere this runs); this task adds nothing to that
question.

Runs under `python -I -S -B` (skillc.verify). The candidate's pipeline is
launched with the same flags, cwd set to the tree copy it verifies.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib

INVOKE_TIMEOUT = 15
PIPELINE_TIMEOUT = 45
PIPELINE_FILE = os.path.join("ci", "verify.py")
MAX_LINE = 400


def _run_unit_tests(candidate_dir: str) -> dict:
    test_path = os.path.join(candidate_dir, "tests", "test_core.py")
    try:
        spec = importlib.util.spec_from_file_location("candidate_test_core", test_path)
        if spec is None or spec.loader is None:
            return {"passed": False, "detail": "tests/test_core.py could not be loaded"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except BaseException as exc:  # noqa: BLE001 - any failure of candidate code is its own
        return {"passed": False, "detail": f"could not load tests/test_core.py: {type(exc).__name__}: {exc}"}
    functions = [getattr(module, n) for n in dir(module) if n.startswith("test_") and callable(getattr(module, n))]
    if not functions:
        return {"passed": False, "detail": "tests/test_core.py defines no test_* function"}
    failures = []
    for fn in functions:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001
            failures.append(f"{fn.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        return {"passed": False, "detail": "; ".join(failures)}
    return {"passed": True, "detail": f"{len(functions)} test(s) passed"}


def _read_pyproject(tree: str) -> tuple:
    try:
        with open(os.path.join(tree, "pyproject.toml"), "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return None, None, f"could not read pyproject.toml: {type(exc).__name__}: {exc}"
    packages = (data.get("tool", {}).get("hatch", {}).get("build", {})
                .get("targets", {}).get("wheel", {}).get("packages"))
    scripts = data.get("project", {}).get("scripts", {})
    if not isinstance(packages, list) or not packages or not all(isinstance(p, str) for p in packages):
        return None, None, "pyproject.toml declares no [tool.hatch.build.targets.wheel] packages"
    if not isinstance(scripts, dict) or len(scripts) != 1:
        return None, None, "pyproject.toml does not declare exactly one [project.scripts] entry"
    target = next(iter(scripts.values()))
    if not isinstance(target, str) or ":" not in target:
        return None, None, "pyproject.toml's [project.scripts] target is not a module:function string"
    return packages, target, None


def _invoke(site_dir: str, target: str, title: str) -> dict:
    module_name, func_name = target.split(":", 1)
    bootstrap = (
        "import sys\n"
        f"sys.path.insert(0, {site_dir!r})\n"
        f"from {module_name} import {func_name}\n"
        f"sys.argv = ['slugify_installed', {title!r}]\n"
        f"{func_name}()\n"
    )
    try:
        proc = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", bootstrap],
                              capture_output=True, text=True, timeout=INVOKE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return {"install_error": "entry-point invocation timed out"}
    if proc.returncode != 0:
        tail = (proc.stderr.strip().splitlines() or ["no stderr"])[-1]
        return {"install_error": f"entry point exited {proc.returncode}: {tail[:MAX_LINE]}"}
    return {"value": proc.stdout.rstrip("\n")}


def installed_outputs(tree: str, titles: list) -> list:
    packages, target, error = _read_pyproject(tree)
    if error is not None:
        return [{"install_error": error} for _ in titles]
    with tempfile.TemporaryDirectory() as site_dir:
        for package in packages:
            source = os.path.join(tree, package)
            if not os.path.isdir(source):
                return [{"install_error": f"declared package {package!r} does not exist"} for _ in titles]
            shutil.copytree(source, os.path.join(site_dir, package), ignore=shutil.ignore_patterns("__pycache__"))
        return [_invoke(site_dir, target, t) for t in titles]


def run_pipeline(tree: str) -> dict:
    script = os.path.join(tree, PIPELINE_FILE)
    if not os.path.isfile(script):
        return {"missing": True, "exit": None, "last_line": "", "timed_out": False, "error": None}
    try:
        proc = subprocess.run([sys.executable, "-I", "-S", "-B", script], cwd=tree,
                              capture_output=True, text=True, timeout=PIPELINE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return {"missing": False, "exit": None, "last_line": "", "timed_out": True, "error": None}
    except OSError as exc:
        return {"missing": False, "exit": None, "last_line": "", "timed_out": False,
                "error": f"could not launch the pipeline: {type(exc).__name__}: {exc}"}
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return {"missing": False, "exit": proc.returncode, "last_line": (lines[-1].strip() if lines else "")[:MAX_LINE],
            "timed_out": False, "error": None}


def apply_mutation(tree: str, mutation: dict) -> str | None:
    """Plant one mutation in `tree` (a disposable copy). Returns an error
    string when it cannot be applied exactly as declared, else None."""
    op, rel, text = mutation.get("op"), mutation.get("file"), mutation.get("text")
    if not isinstance(rel, str) or not isinstance(text, str) or os.path.isabs(rel) or ".." in rel.split("/"):
        return "malformed mutation: file and text must be a relative path and a string"
    path = os.path.join(tree, rel)
    if not os.path.isfile(path):
        return f"malformed mutation: {rel} does not exist in this tree"
    with open(path, encoding="utf-8") as handle:
        original = handle.read()
    if op == "append":
        require = mutation.get("require")
        if require is not None and require not in original:
            return f"malformed mutation: {rel} does not contain {require!r}"
        mutated = original + text
    elif op == "scripts-target-suffix":
        _packages, target, error = _read_pyproject(tree)
        if error is not None:
            return f"malformed mutation: {error}"
        quoted = [q for q in (f'"{target}"', f"'{target}'") if original.count(q) == 1]
        if len(quoted) != 1 or original.count(target) != 1:
            return f"malformed mutation: the scripts target {target!r} does not appear exactly once"
        module_name, func_name = target.split(":", 1)
        mutated = original.replace(quoted[0], quoted[0].replace(target, f"{module_name}:{func_name}{text}"))
    else:
        return f"malformed mutation: unknown op {op!r}"
    if mutated == original:
        return "malformed mutation: the file is unchanged"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(mutated)
    return None


def _copy(candidate_dir: str, into: str) -> str:
    dest = os.path.join(into, "tree")
    shutil.copytree(candidate_dir, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def main() -> None:
    report = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    candidate_dir = sys.argv[1]
    inputs = json.loads(sys.stdin.read())
    titles = inputs.get("titles") if isinstance(inputs, dict) else None
    mutations = inputs.get("mutations") if isinstance(inputs, dict) else None
    if not isinstance(titles, list) or not isinstance(mutations, list):
        report.write(json.dumps({"error": "inputs carry no titles or no mutations"}))
        report.flush()
        return

    result: dict = {"unit_test": _run_unit_tests(candidate_dir), "install_mode": "stdlib-emulation"}
    with tempfile.TemporaryDirectory() as work:
        clean = _copy(candidate_dir, work)
        result["installed_outputs"] = installed_outputs(clean, titles)
        result["pipeline"] = run_pipeline(clean)
    planted = []
    for mutation in mutations:
        entry: dict = {"id": mutation.get("id") if isinstance(mutation, dict) else None}
        with tempfile.TemporaryDirectory() as work:
            tree = _copy(candidate_dir, work)
            error = apply_mutation(tree, mutation) if isinstance(mutation, dict) else "malformed mutation"
            if error is not None:
                entry["applied"] = {"error": error}
            else:
                entry["applied"] = True
                entry["installed_outputs"] = installed_outputs(tree, titles)
                entry["pipeline"] = run_pipeline(tree)
        planted.append(entry)
    result["mutations"] = planted
    report.write(json.dumps(result))
    report.flush()


if __name__ == "__main__":
    main()
