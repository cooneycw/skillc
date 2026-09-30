#!/usr/bin/env python3
"""slugkit's local verification pipeline: `python3 ci/verify.py`.

There is no CI server in this repository's environment, so this script is the
pipeline. It runs every step, each in a fresh interpreter, and ends with ONE
verdict line:

    VERIFY: ok                    (exit 0)  - every step passed
    VERIFY: fail <step> [<step>]  (exit 1)  - the steps that failed

Steps:
  test     - every `test_*` function in `tests/test_*.py`
  package  - "install" the package the way `pyproject.toml` declares it (copy
             only the declared package directories, data included, into an
             isolated directory), run the declared console command there, and
             require it to print exactly what the source tree's `slugify`
             returns for the same title
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = ("test",)
SAMPLE = "Tom & Jerry @ Home!"
TIMEOUT = 20


def step_test() -> int:
    failures, count = [], 0
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(f"verify_{path.stem}", path)
        if spec is None or spec.loader is None:
            failures.append(f"{path.name}: cannot load")
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException as exc:  # noqa: BLE001 - any failure is a test failure
            failures.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        for name in sorted(dir(module)):
            fn = getattr(module, name)
            if name.startswith("test_") and callable(fn):
                count += 1
                try:
                    fn()
                except BaseException as exc:  # noqa: BLE001
                    failures.append(f"{path.name}::{name}: {type(exc).__name__}: {exc}")
    if count == 0:
        failures.append("no tests collected")
    for failure in failures:
        print(f"  test: {failure}")
    return 1 if failures else 0


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code],
                          capture_output=True, text=True, timeout=TIMEOUT, check=False)


def step_package() -> int:
    with open(ROOT / "pyproject.toml", "rb") as handle:
        data = tomllib.load(handle)
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    module_name, func_name = next(iter(data["project"]["scripts"].values())).split(":", 1)
    with tempfile.TemporaryDirectory() as site:
        for package in packages:
            shutil.copytree(ROOT / package, Path(site) / package, ignore=shutil.ignore_patterns("__pycache__"))
        installed = _run(
            f"import sys; sys.path.insert(0, {site!r}); from {module_name} import {func_name}; "
            f"sys.argv = ['slugify_installed', {SAMPLE!r}]; {func_name}()"
        )
    source = _run(f"import sys; sys.path.insert(0, {str(ROOT)!r}); from slugkit import slugify; "
                  f"print(slugify({SAMPLE!r}))")
    if installed.returncode != 0:
        print(f"  package: the installed console command exited {installed.returncode}: "
              f"{(installed.stderr.strip().splitlines() or ['no stderr'])[-1]}")
        return 1
    if source.returncode != 0 or installed.stdout != source.stdout or not installed.stdout.strip():
        print(f"  package: installed printed {installed.stdout!r}, the source tree gives {source.stdout!r}")
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "--step" and argv[2] in STEPS:
        return {"test": step_test, "package": step_package}[argv[2]]()
    failed = []
    for step in STEPS:
        try:
            proc = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--step", step],
                                  capture_output=True, text=True, timeout=TIMEOUT * 3, check=False)
        except subprocess.TimeoutExpired:
            print(f"  {step}: timed out")
            failed.append(step)
            continue
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            if proc.stderr.strip():
                print(f"  {step}: {proc.stderr.strip().splitlines()[-1]}")
            failed.append(step)
    print("VERIFY: ok" if not failed else f"VERIFY: fail {' '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
