#!/usr/bin/env python3
"""Local gate, rewritten to walk every test_*.py under tests/ unconditionally
- it does not require a tests/ subdirectory to declare itself a package."""

import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_ROOT = ROOT / "tests"


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
    total_ran = 0
    total_failures = 0
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        ran, failures = run_file(path)
        total_ran += ran
        total_failures += failures
    print(f"CHECK: {'ok' if total_failures == 0 else 'fail'} - {total_failures} failures ({total_ran} ran)")
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
