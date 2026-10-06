#!/usr/bin/env python3
"""Run the project's required lint tool and report what actually happened.

Usage: python3 ci/lint_check.py

This project's CONTRIBUTING.md requires `strictlint-x9` before every merge.
It is a real, separately maintained tool, never vendored into this
repository - so whether it is present is a fact about the environment this
script runs in, not about this project's own code. Prints `AVAILABLE` and
runs it (exit reflects the tool's own result) when found on PATH; prints
`UNAVAILABLE: strictlint-x9 not found on PATH` and exits 3 when it is not.
Exit 3 is deliberately distinct from a lint failure's exit 1 - an absent
tool is not the same fact as code that failed a present tool.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

TOOL = "strictlint-x9"


def main() -> int:
    path = shutil.which(TOOL)
    if path is None:
        print(f"UNAVAILABLE: {TOOL} not found on PATH")
        return 3
    print(f"AVAILABLE: {path}")
    proc = subprocess.run([path, "."], check=False)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
