#!/usr/bin/env python3
"""Local gate (CONTRIBUTING.md): discover and run every regression test under
tests/, print a CHECK verdict, and exit non-zero on any failure."""

import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_ROOT = ROOT / "tests"


def discover_test_files():
    files = sorted(TESTS_ROOT.glob("test_*.py"))
    for sub in sorted(p for p in TESTS_ROOT.iterdir() if p.is_dir()):
        if (sub / "__init__.py").is_file():
            files.extend(sorted(sub.glob("test_*.py")))
    return files


def run_file(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ran = 0
    failures = 0
    for name in dir(module):
        fn = getattr(module, name)
        if name.startswith("test_") and callable(fn):
            ran += 1
            try:
                fn()
            except BaseException:  # noqa: BLE001 - any failure of candidate code is its own
                failures += 1
                traceback.print_exc()
    return ran, failures


def main():
    sys.path.insert(0, str(ROOT))
    total_failures = 0
    for path in discover_test_files():
        _ran, failures = run_file(path)
        total_failures += failures
    print(f"CHECK: {'ok' if total_failures == 0 else 'fail'} - {total_failures} failures")
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
