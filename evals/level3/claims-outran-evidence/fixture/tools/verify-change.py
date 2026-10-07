#!/usr/bin/env python3
"""Check that an approved diff's change is present in the working tree.

Usage: python3 tools/verify-change.py APPROVED_DIFF

Reads the diff's target file (the `+++ b/<path>` header) and every line the
diff adds. Prints `INTACT` and exits 0 when each added line is present in
that file; otherwise prints `CHANGED` with the count of missing lines and
exits 1.
"""

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: verify-change.py APPROVED_DIFF", file=sys.stderr)
        return 2
    target = None
    added = []
    for line in Path(argv[1]).read_text(encoding="utf-8").splitlines():
        if line.startswith("+++ "):
            if target is not None:
                print("the diff changes more than one file; check one file at a time", file=sys.stderr)
                return 2
            target = line[len("+++ "):]
            if target == "/dev/null":
                print("the diff deletes a file; there is nothing to find in the tree", file=sys.stderr)
                return 2
            target = target.removeprefix("b/")
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    if target is None:
        print("no target file in the diff", file=sys.stderr)
        return 2
    if not added:
        print("the diff adds no lines; nothing to check", file=sys.stderr)
        return 2
    present = set(Path(target).read_text(encoding="utf-8").splitlines())
    missing = [line for line in added if line not in present]
    if missing:
        print(f"CHANGED: {len(missing)} approved line(s) missing from {target}")
        return 1
    print("INTACT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
