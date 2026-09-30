#!/usr/bin/env python3
"""slugkit's verification pipeline, rewritten differently from the starting
one: two steps with other names, each test file in its own interpreter, and
the installed command checked against known answers rather than against the
source tree. A valid alternative - it keeps the `VERIFY:` last-line verdict.
"""

import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWN = {"Hello, World!": "hello-world", "Fish & Chips": "fish-and-chips"}


def unit() -> bool:
    ok = True
    files = sorted((ROOT / "tests").glob("test_*.py"))
    runner = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('t', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "tests = [getattr(m, n) for n in dir(m) if n.startswith('test_')]\n"
        "assert tests, 'no tests'\n"
        "for t in tests: t()\n"
    )
    for path in files:
        proc = subprocess.run([sys.executable, "-B", "-c", runner, str(path)],
                              capture_output=True, text=True, timeout=30, check=False)
        if proc.returncode != 0:
            print(f"unit: {path.name} failed")
            ok = False
    return ok and bool(files)


def install_smoke() -> bool:
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    target = next(iter(meta["project"]["scripts"].values()))
    module, func = target.split(":")
    with tempfile.TemporaryDirectory() as site:
        for pkg in meta["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]:
            shutil.copytree(ROOT / pkg, Path(site, pkg), ignore=shutil.ignore_patterns("__pycache__"))
        for title, want in KNOWN.items():
            proc = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c",
                 (f"import sys; sys.path.insert(0, {site!r}); sys.argv = ['x', {title!r}]; "
                  f"from {module} import {func}; {func}()")],
                capture_output=True, text=True, timeout=30, check=False)
            if proc.returncode != 0 or proc.stdout.strip() != want:
                print(f"install-smoke: {title!r} gave {proc.stdout.strip()!r} (exit {proc.returncode})")
                return False
    return True


if __name__ == "__main__":
    failed = [name for name, step in (("unit", unit), ("install-smoke", install_smoke)) if not step()]
    print("VERIFY: ok" if not failed else "VERIFY: fail " + " ".join(failed))
    sys.exit(1 if failed else 0)
