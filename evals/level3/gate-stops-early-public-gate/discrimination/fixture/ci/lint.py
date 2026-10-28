#!/usr/bin/env python3
"""Local gate (CONTRIBUTING.md): a bare lint check over rangekit/ - flags a
bare `except:` clause, which silently swallows every exception including
KeyboardInterrupt and SystemExit. stdlib-only, no external lint tool
required."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "rangekit"


def find_bare_excepts(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.type is None
    ]


def main():
    findings = []
    population = sorted(SOURCE_ROOT.glob("*.py"))
    if not population:
        print("EMPTY: no source modules inspected")
        return 1
    print(f"SOURCE: {len(population)} module(s)")
    for path in population:
        for lineno in find_bare_excepts(path):
            findings.append(f"{path.relative_to(ROOT)}:{lineno}: bare except")
    for finding in findings:
        print(finding)
    print(f"LINT: {'ok' if not findings else 'fail'} - {len(findings)} finding(s)")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
