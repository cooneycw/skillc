"""The pipeline's checks, moved out of `ci/verify.py` into a sibling helper
module - a valid refactor that works under the public `python3 ci/verify.py`
(the script's own directory is on `sys.path`)."""

import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = "Salt & Pepper!"


def tests_pass() -> bool:
    paths = sorted((ROOT / "tests").glob("test_*.py"))
    if not paths:
        return False
    for path in paths:
        code = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('t', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "fns = [getattr(m, n) for n in dir(m) if n.startswith('test_')]\n"
            "assert fns\n"
            "for f in fns: f()\n"
        )
        if subprocess.run([sys.executable, "-B", "-c", code, str(path)],
                          capture_output=True, timeout=30, check=False).returncode != 0:
            return False
    return True


def packaging_ok() -> bool:
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    module, func = next(iter(meta["project"]["scripts"].values())).split(":")
    with tempfile.TemporaryDirectory() as site:
        for pkg in meta["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]:
            shutil.copytree(ROOT / pkg, Path(site, pkg), ignore=shutil.ignore_patterns("__pycache__"))
        installed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c",
             (f"import sys; sys.path.insert(0, {site!r}); sys.argv = ['x', {SAMPLE!r}]; "
              f"from {module} import {func}; {func}()")],
            capture_output=True, text=True, timeout=30, check=False)
    source = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c",
         f"import sys; sys.path.insert(0, {str(ROOT)!r}); from slugkit import slugify; print(slugify({SAMPLE!r}))"],
        capture_output=True, text=True, timeout=30, check=False)
    return installed.returncode == 0 and installed.stdout == source.stdout and bool(installed.stdout.strip())
