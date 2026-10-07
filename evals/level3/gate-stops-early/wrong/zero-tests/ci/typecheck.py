#!/usr/bin/env python3
"""Local gate (CONTRIBUTING.md): a bare typecheck over rangekit/ - flags a
top-level function missing a parameter or return annotation. stdlib-only,
no external typechecker required."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "rangekit"


def find_unannotated(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    findings = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.returns is None:
            findings.append(f"{node.lineno}: {node.name} has no return annotation")
        for arg in node.args.args:
            if arg.annotation is None:
                findings.append(f"{node.lineno}: {node.name}({arg.arg}) has no parameter annotation")
    return findings


def main():
    findings = []
    for path in sorted(SOURCE_ROOT.glob("*.py")):
        for finding in find_unannotated(path):
            findings.append(f"{path.relative_to(ROOT)}:{finding}")
    for finding in findings:
        print(finding)
    print(f"TYPECHECK: {'ok' if not findings else 'fail'} - {len(findings)} finding(s)")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
