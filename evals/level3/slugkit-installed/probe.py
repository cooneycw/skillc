#!/usr/bin/env python3
"""Probe for the Level 3 slugkit-installed task: the ONLY grading code that
runs candidate code.

Usage: probe.py CANDIDATE_DIR, with a JSON list of held-out title inputs on
stdin (exercised through the INSTALLED console entry point, never the raw
source tree - see "install", below).

Reports TWO independent observations, neither a verdict - the judge
(grade_slugkit.py --judge) holds every expected value and compares:

  - `unit_test`: whether the candidate's own `tests/test_core.py` passes,
    run directly against the candidate's source tree (never through an
    install) - drives `functional-trailing-hyphen`.
  - `install_mode` + `installed_outputs`: what the candidate's console
    entry point (`[project.scripts]`) printed for each held-out input,
    after an "install" - drives `integration-installed-path`.

## "Install" has two modes, named explicitly in the report

`install_mode` is always one of `"stdlib-emulation"` or `"real-pip"` - a
report never conflates the two.

**`stdlib-emulation` (primary in this repo today).** Neither pip nor a
build backend is present in this dev environment or in the #78 trial/
grading container (checked directly - see README.md). So the primary,
always-available path reads the candidate's `pyproject.toml` with
`tomllib` (stdlib, 3.11+) for `[tool.hatch.build.targets.wheel] packages`
(the declared package directories) and `[project.scripts]`'s
`module:function` target - THIS PROBE's own reading of those two keys IS
the schema for this task; there is no real backend enforcing one. It then
copies ONLY the declared package directories (recursively, so
`slugkit/data/replacements.json` comes along with `slugkit/`) into a fresh
temp "site dir" - nothing else, no other file in the candidate tree, even
if one exists (this is what catches `wrong/scratch-copy`: a fix applied
only to an undeclared `scratch/` directory is never copied). The
console-script target is then invoked in a FRESH interpreter subprocess
with ONLY the site dir on `sys.path` - not the candidate's original source
tree, so nothing outside the declared packages is reachable.

This does NOT cover what a real build backend would enforce beyond that one
declared-packages/package-data convention: MANIFEST/include-exclude rules,
dependency resolution, or compiled extensions. See README.md.

**`real-pip` (secondary; the mode-selection logic exists, but pip's own
absence means this repo's real grading runs never reach it today).** When
`python -m pip --version` succeeds AND the declared build backend module is
importable, this probe instead runs a real, offline
`pip install --no-index --no-build-isolation --target SITE_DIR
CANDIDATE_DIR` and invokes the entry point the same way. Both modes end at
the identical "site dir on sys.path, invoke the entry point" step; only how
the site dir gets populated differs.

Candidate prints go to stderr during the unit-test stage, so ordinary
output cannot mix with the report - the same discipline Level 1/2's
probes already use.

Runs under `python -I -S -B` (skillc.verify) for the OUTER probe process;
each install-emulation/real-pip invocation spawns its OWN fresh `-I -S -B`
subprocess, so nothing imported while running the unit test (in THIS
process) can leak into what the installed-path invocation sees.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib

TIMEOUT_SECONDS = 15


def _run_unit_tests(candidate_dir: str) -> dict:
    """Load and run `tests/test_core.py`'s own `test_*` functions directly -
    never through `unittest`/`pytest` (both third-party or shape-specific;
    this probe runs under `-S`, so nothing outside the standard library is
    importable here anyway). Any failure is the candidate's; any load
    failure (missing file, syntax error, broken import) is reported the
    same way, never raised uncaught."""
    test_path = os.path.join(candidate_dir, "tests", "test_core.py")
    try:
        spec = importlib.util.spec_from_file_location("candidate_test_core", test_path)
        if spec is None or spec.loader is None:
            return {"passed": False, "detail": "tests/test_core.py could not be loaded"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except BaseException as exc:  # noqa: BLE001 - any failure of candidate code is its own
        return {"passed": False, "detail": f"could not load tests/test_core.py: {type(exc).__name__}: {exc}"}
    functions = [
        getattr(module, name) for name in dir(module)
        if name.startswith("test_") and callable(getattr(module, name))
    ]
    if not functions:
        return {"passed": False, "detail": "tests/test_core.py defines no test_* function"}
    failures = []
    for fn in functions:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 - any failure of candidate code is its own
            failures.append(f"{fn.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        return {"passed": False, "detail": "; ".join(failures)}
    return {"passed": True, "detail": f"{len(functions)} test(s) passed"}


def _read_pyproject(candidate_dir: str) -> tuple[list, str, str] | tuple[None, None, str]:
    """Declared package dirs and the one `[project.scripts]` target, read
    with `tomllib` alone - never executed, never trusted beyond its shape."""
    path = os.path.join(candidate_dir, "pyproject.toml")
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return None, None, f"could not read pyproject.toml: {type(exc).__name__}: {exc}"
    packages = (
        data.get("tool", {}).get("hatch", {}).get("build", {})
        .get("targets", {}).get("wheel", {}).get("packages")
    )
    scripts = data.get("project", {}).get("scripts", {})
    backend_requires = data.get("build-system", {}).get("requires", [])
    if not isinstance(packages, list) or not packages or not all(isinstance(p, str) for p in packages):
        return None, None, "pyproject.toml declares no [tool.hatch.build.targets.wheel] packages"
    if not isinstance(scripts, dict) or not scripts:
        return None, None, "pyproject.toml declares no [project.scripts]"
    target = next(iter(scripts.values()))
    if not isinstance(target, str) or ":" not in target:
        return None, None, "pyproject.toml's [project.scripts] target is not a module:function string"
    return packages, target, backend_requires[0] if backend_requires else None


def _pip_available(backend_name: str | None) -> bool:
    if not backend_name:
        return False
    try:
        pip_check = subprocess.run(
            [sys.executable, "-m", "pip", "--version"], capture_output=True, timeout=5, check=False,
        )
    except OSError:
        return False
    if pip_check.returncode != 0:
        return False
    try:
        backend_check = subprocess.run(
            [sys.executable, "-c", f"import {backend_name}"], capture_output=True, timeout=5, check=False,
        )
    except OSError:
        return False
    return backend_check.returncode == 0


def _emulate_install(candidate_dir: str, packages: list, site_dir: str) -> str | None:
    """Copy only the declared package directories, recursively, skipping
    `__pycache__` - nothing else in the candidate tree reaches the site
    dir. Returns an error string, or None on success."""
    for package in packages:
        source = os.path.join(candidate_dir, package)
        if not os.path.isdir(source):
            return f"declared package {package!r} does not exist in the candidate tree"
        dest = os.path.join(site_dir, package)
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return None


def _real_pip_install(candidate_dir: str, site_dir: str) -> str | None:
    """A real, offline install into `site_dir` via `--target` - no venv, no
    network. Only reachable when `_pip_available` already confirmed pip and
    the declared backend are both importable."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-index", "--no-build-isolation",
             "--target", site_dir, candidate_dir],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"pip install failed to run: {type(exc).__name__}: {exc}"
    if result.returncode != 0:
        return f"pip install exited {result.returncode}: {result.stderr.strip()[-500:]}"
    return None


def _invoke_entry_point(site_dir: str, target: str, title: str) -> dict:
    module_name, func_name = target.split(":", 1)
    bootstrap = (
        "import sys\n"
        f"sys.path.insert(0, {site_dir!r})\n"
        f"from {module_name} import {func_name}\n"
        f"sys.argv = ['slugify_installed', {title!r}]\n"
        f"{func_name}()\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", bootstrap],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"install_error": "entry-point invocation timed out"}
    if proc.returncode != 0:
        tail = (proc.stderr.strip().splitlines() or ["no stderr"])[-1]
        return {"install_error": f"entry point exited {proc.returncode}: {tail}"}
    return {"value": proc.stdout.rstrip("\n")}


def main() -> None:
    report = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    candidate_dir = sys.argv[1]
    inputs = json.loads(sys.stdin.read())

    result: dict = {"unit_test": _run_unit_tests(candidate_dir)}

    packages, target, extra = _read_pyproject(candidate_dir)
    if packages is None:
        result["install_mode"] = "stdlib-emulation"
        result["installed_outputs"] = [{"install_error": extra} for _ in inputs]
        report.write(json.dumps(result))
        report.flush()
        return

    backend_name = extra
    use_real_pip = _pip_available(backend_name)
    with tempfile.TemporaryDirectory() as site_dir:
        if use_real_pip:
            result["install_mode"] = "real-pip"
            install_error = _real_pip_install(candidate_dir, site_dir)
        else:
            result["install_mode"] = "stdlib-emulation"
            install_error = _emulate_install(candidate_dir, packages, site_dir)
        if install_error is not None:
            result["installed_outputs"] = [{"install_error": install_error} for _ in inputs]
        else:
            result["installed_outputs"] = [_invoke_entry_point(site_dir, target, text) for text in inputs]

    report.write(json.dumps(result))
    report.flush()


if __name__ == "__main__":
    main()
