#!/usr/bin/env python3
"""Inventory wall-clock-sensitive bounds, and ratchet the sub-second ones (#758).

Under #462, a test whose verdict depends on how busy the host is turns main
red for reasons that are not about the code, and a red main push holds the
shared main-merge barrier. #758 makes that family visible and stops it
growing. This tool is the instrument behind both.

Every bound has one of three ROLES, and the right fix depends on it:

  must-FIRE  the bound IS the property under test (a probe's 0.3 s timeout).
             Keep it small. Its fake BLOCKS until killed, so load can only
             delay the event further past the bound, never ahead of it.
  must-BEAT  setup or work the test needs to finish (a fake `rm -f` that
             exits at once, a setup `prepare()`). Use the shared generous
             bound (`tests/conftest.py`'s TEST_SETUP_BOUND), never a literal.
  racing     two bounds or a poll against a sleep. Use an event or condition.

The role cannot be derived from syntax, so the tool does not guess it. It
inventories every time-ish numeric literal, and it ratchets the risky subset:
a NEW literal below 1 s in tests/ must either be in the committed baseline
(ci/timing-baseline.txt, the family as it stood) or carry, on its own line,

    # timing: must-fire - <why the bound is the property>

An annotation with an empty reason, or any role word other than must-fire,
fails: a must-beat bound has no business being a sub-second literal. A
baseline entry with no matching literal also fails, so the baseline shrinks
truthfully as members are fixed and a freed slot is not silently reused.

Shapes (per function, or <module>):
  kw       a time-ish keyword argument with a numeric literal (timeout=0.3)
  param    a time-ish column of a pytest parametrize table
  sleep    sleep(N) / time.sleep(N)
  elapsed  a comparison of a time-ish expression with a literal (elapsed < 2)
  default  a time-ish parameter default (seconds=5)
  const    NAME = N where NAME is time-ish
  str-*    inside a string literal (an embedded script or shell fake):
           `sleep N`, `x_timeout=N`, `monotonic()+N`, `timeout Ns`

Usage:
  python3 ci/timing_inventory.py report [--root DIR] [--json]
  python3 ci/timing_inventory.py check  [--root DIR] [--baseline FILE]
  python3 ci/timing_inventory.py write-baseline [--root DIR] [--baseline FILE]

`check` prints `TIMING_CHECK: ok|fail` and exits 0 or 1. Exit 2 is a usage or
parse error, and it never reads as ok.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

#: The ratchet's threshold. Every load-red member #758 was filed for had a
#: literal bound under it, or a production default the inventory reports.
RATCHET_BELOW = 1.0
DEFAULT_BASELINE = "ci/timing-baseline.txt"

TIMEISH = re.compile(
    r"(timeout|settle|interval|deadline|budget|grace|wait|poll|delay|seconds|sleep|stall|ttl|period|backoff|patience)",
    re.I,
)
ELAPSED_NAMES = re.compile(r"(elapsed|duration|took|seconds|monotonic|perf_counter|time)", re.I)
STR_PATTERNS = (
    ("str-sleep", re.compile(r"\bsleep\s*\(?\s*([0-9]*\.?[0-9]+)")),
    ("str-kw", re.compile(r"\b[A-Za-z_]*(?:timeout|settle|interval|deadline|wait|poll|delay|seconds)\s*=\s*([0-9]*\.?[0-9]+)\b", re.I)),
    ("str-deadline", re.compile(r"monotonic\(\)\s*\+\s*([0-9]*\.?[0-9]+)")),
    ("str-timeout-cli", re.compile(r"\btimeout\s+([0-9]*\.?[0-9]+)s?\b")),
)
ANNOTATION = re.compile(r"#\s*timing:\s*(?P<role>[A-Za-z-]*)\s*(?:-\s*(?P<why>.*))?$")


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    scope: str
    kind: str
    value: float
    detail: str

    def key(self) -> str:
        return f"{self.path}::{self.scope}::{self.kind}::{self.value:g}"


def _num(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    return None


def _src(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - a display string only
        return ""


class _Scan(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.scope: list[str] = []
        self.hits: list[Hit] = []

    def _add(self, kind: str, node: ast.AST, value: float, detail: str) -> None:
        self.hits.append(Hit(self.rel, getattr(node, "lineno", 0), ".".join(self.scope) or "<module>",
                             kind, value, detail[:160]))

    def _scoped(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _scoped  # type: ignore[assignment]
    visit_AsyncFunctionDef = _scoped  # type: ignore[assignment]
    visit_ClassDef = _scoped  # type: ignore[assignment]

    def _parametrize(self, node: ast.Call) -> None:
        """`@pytest.mark.parametrize("mode, settle", [("x", 0.5)])`: a value in
        a time-ish column is a bound, even though it is not a keyword - or a
        bound could dodge the ratchet by moving into a parametrize table."""
        if len(node.args) < 2 or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            return
        names = [n.strip() for n in node.args[0].value.split(",")]
        timeish = [i for i, n in enumerate(names) if TIMEISH.search(n)]
        rows = node.args[1]
        if not timeish or not isinstance(rows, (ast.List, ast.Tuple)):
            return
        for row in rows.elts:
            cells = row.elts if isinstance(row, (ast.Tuple, ast.List)) and len(names) > 1 else [row]
            for i in timeish:
                if i < len(cells):
                    value = _num(cells[i])
                    if value is not None:
                        self._add("param", cells[i], value, f"parametrize {names[i]}={_src(cells[i])}")

    def visit_Call(self, node: ast.Call) -> None:
        name = _src(node.func)
        if name.split(".")[-1] == "parametrize":
            self._parametrize(node)
        if name.split(".")[-1] == "sleep" and node.args:
            value = _num(node.args[0])
            if value is not None:
                self._add("sleep", node.args[0], value, _src(node))
        for kw in node.keywords:
            if kw.arg and TIMEISH.search(kw.arg):
                value = _num(kw.value)
                if value is not None:
                    self._add("kw", kw.value, value, f"{name}({kw.arg}={_src(kw.value)})")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        sides = [node.left, *node.comparators]
        others = " ".join(_src(s) for s in sides if _num(s) is None)
        if ELAPSED_NAMES.search(others):
            for side in sides:
                value = _num(side)
                if value is not None:
                    self._add("elapsed", side, value, _src(node))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        value = _num(node.value)
        if value is not None:
            for target in node.targets:
                if isinstance(target, ast.Name) and TIMEISH.search(target.id):
                    self._add("const", node.value, value, f"{target.id} = {_src(node.value)}")
        self.generic_visit(node)

    def visit_arguments(self, node: ast.arguments) -> None:
        positional = node.posonlyargs + node.args
        pairs = list(zip(positional[len(positional) - len(node.defaults):], node.defaults))
        pairs += [(a, d) for a, d in zip(node.kwonlyargs, node.kw_defaults) if d is not None]
        for arg, default in pairs:
            value = _num(default)
            if value is not None and TIMEISH.search(arg.arg):
                self._add("default", default, value, f"{arg.arg}={_src(default)}")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            for kind, pattern in STR_PATTERNS:
                for match in pattern.finditer(node.value):
                    try:
                        value = float(match.group(1))
                    except ValueError:
                        continue
                    self._add(kind, node, value, match.group(0))


class ScanError(Exception):
    """A file the instrument could not read: never an empty, clean result."""


def scan_file(path: Path, rel: str) -> list[Hit]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        raise ScanError(f"{rel}: {exc}") from exc
    scanner = _Scan(rel)
    scanner.visit(tree)
    return scanner.hits


def scan_tree(root: Path, subdir: str) -> list[Hit]:
    base = root / subdir
    if not base.is_dir():
        raise ScanError(f"{subdir}/ does not exist under {root}")
    hits: list[Hit] = []
    for path in sorted(base.rglob("*.py")):
        hits.extend(scan_file(path, path.relative_to(root).as_posix()))
    return hits


def annotations(path: Path) -> dict[int, tuple[str, str]]:
    """Line -> (role, reason) for every `# timing:` comment in the file."""
    found: dict[int, tuple[str, str]] = {}
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.COMMENT:
                match = ANNOTATION.search(tok.string)
                if match:
                    found[tok.start[0]] = (match.group("role") or "", (match.group("why") or "").strip())
    return found


def ratchet_candidates(root: Path) -> tuple[list[Hit], list[Hit], list[str]]:
    """(unannotated sub-second hits, annotated ones, annotation errors)."""
    unannotated: list[Hit] = []
    annotated: list[Hit] = []
    errors: list[str] = []
    notes_by_file: dict[str, dict[int, tuple[str, str]]] = {}
    for hit in scan_tree(root, "tests"):
        if not 0 < hit.value < RATCHET_BELOW:
            continue
        notes = notes_by_file.setdefault(hit.path, annotations(root / hit.path))
        note = notes.get(hit.line)
        if note is None:
            unannotated.append(hit)
            continue
        role, why = note
        if role != "must-fire":
            errors.append(f"{hit.path}:{hit.line}: `# timing: {role}` - only must-fire may annotate a sub-second "
                          f"literal; a must-beat bound uses TEST_SETUP_BOUND")
        elif not why:
            errors.append(f"{hit.path}:{hit.line}: `# timing: must-fire` needs a reason after ` - `")
        else:
            annotated.append(hit)
    return unannotated, annotated, errors


def read_baseline(path: Path) -> Counter[str]:
    if not path.is_file():
        raise ScanError(f"baseline {path} does not exist")
    entries = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return Counter(e for e in entries if e and not e.startswith("#"))


def check(root: Path, baseline_path: Path) -> tuple[bool, list[str]]:
    unannotated, annotated, errors = ratchet_candidates(root)
    baseline = read_baseline(baseline_path)
    current = Counter(h.key() for h in unannotated)
    new = current - baseline
    stale = baseline - current
    lines = [
        f"TIMING_SCANNED: {len(unannotated) + len(annotated)} sub-second literal(s) in tests/ "
        f"({len(unannotated)} baselined or new, {len(annotated)} annotated must-fire)",
        f"TIMING_BASELINE: {sum(baseline.values())} entr(ies)",
    ]
    by_key: dict[str, list[Hit]] = {}
    for hit in unannotated:
        by_key.setdefault(hit.key(), []).append(hit)
    for key, count in sorted(new.items()):
        for hit in by_key[key][-count:]:
            lines.append(f"TIMING_NEW: {hit.path}:{hit.line} {hit.kind} {hit.value:g} in {hit.scope} - {hit.detail}")
    for key, count in sorted(stale.items()):
        lines.append(f"TIMING_STALE: {key} x{count} - no such literal now; remove it from {baseline_path.name}")
    lines.extend(f"TIMING_ANNOTATION_ERROR: {e}" for e in errors)
    ok = not new and not stale and not errors
    if not ok:
        lines.append("Fix: give a must-beat bound TEST_SETUP_BOUND; annotate a genuine must-fire literal on its own "
                     "line with `# timing: must-fire - <why>`; drop fixed entries from the baseline.")
    lines.append(f"TIMING_CHECK: {'ok' if ok else 'fail'}")
    return ok, lines


def write_baseline(root: Path, baseline_path: Path) -> int:
    unannotated, _annotated, errors = ratchet_candidates(root)
    if errors:
        for e in errors:
            print(f"TIMING_ANNOTATION_ERROR: {e}", file=sys.stderr)
        return 2
    header = ("# Sub-second time-ish literals in tests/ as of the last baseline write (#758, under #462).\n"
              "# One line per occurrence: path::scope::kind::value. Entries LEAVE as members are fixed;\n"
              "# a new line here needs its reason in the PR. Generated by "
              "`python3 ci/timing_inventory.py write-baseline`.\n")
    body = "".join(f"{key}\n" for key in sorted(h.key() for h in unannotated))
    baseline_path.write_text(header + body, encoding="utf-8")
    print(f"TIMING_BASELINE_WRITTEN: {len(unannotated)} entr(ies) to {baseline_path}")
    return 0


def report(root: Path) -> dict[str, object]:
    tests = scan_tree(root, "tests")
    product = [h for h in scan_tree(root, "skillc") if h.kind in ("const", "default") and h.value <= 5]

    def band(v: float) -> str:
        return "<1s" if v < 1 else "1-5s" if v <= 5 else "5-30s" if v <= 30 else ">30s"

    funcs: dict[str, set[tuple[str, str]]] = {}
    for hit in tests:
        leaf = hit.scope.split(".")[-1]
        if leaf.startswith("test_") and not hit.path.startswith("tests/fixtures/"):
            funcs.setdefault(band(hit.value), set()).add((hit.path, leaf))
    return {
        "tests_hits": len(tests),
        "tests_hits_by_band": dict(Counter(band(h.value) for h in tests)),
        "tests_hits_by_kind": dict(Counter(h.kind for h in tests)),
        "test_functions_by_band": {k: len(v) for k, v in sorted(funcs.items())},
        "test_files_by_band": {k: len({p for p, _ in v}) for k, v in sorted(funcs.items())},
        "skillc_defaults_at_most_5s": [asdict(h) for h in product],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("report", "check", "write-baseline"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    baseline = args.baseline or root / DEFAULT_BASELINE
    try:
        if args.command == "check":
            ok, lines = check(root, baseline)
            print("\n".join(lines))
            return 0 if ok else 1
        if args.command == "write-baseline":
            return write_baseline(root, baseline)
        data = report(root)
        print(json.dumps(data, indent=1) if args.json else "\n".join(
            f"{k}: {v}" for k, v in data.items() if k != "skillc_defaults_at_most_5s")
            + "\nskillc defaults <= 5 s:\n" + "\n".join(
                f"  {h['path']}:{h['line']} {h['detail']}" for h in data["skillc_defaults_at_most_5s"]))  # type: ignore[union-attr]
        return 0
    except (ScanError, tokenize.TokenError, io.UnsupportedOperation) as exc:
        print(f"TIMING_CHECK: error - {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
