#!/usr/bin/env python3
"""Merge-admission wiring gate (Kyle #2130, ADR 0011 D3).

Two contracts, each with committed cases in ``controls/merge-admission/``:

1. **CI never acquires main-merge.** The merger holds ``main-merge`` while it
   waits for the main push pipeline, so a pipeline step that acquired it would
   wait on the merger that is waiting on it. :func:`pipeline_findings` parses
   the Woodpecker YAML, reads each step's *commands* (comments stripped, so a
   mention in a comment is not a finding) and follows every repository script a
   command runs, recursively. A finding is any route to a ``main-merge``
   acquire, run or barrier call, or any merger credential handed to CI.
2. **No merge without a held lease and a confirmed begin.**
   :func:`transcript_findings` reads a merger's ordered external calls and
   fails a ``gh pr merge`` that is not preceded by a held ``main-merge``
   acquire and a confirmed ``begin-merge`` for the same PR, or that is issued
   twice. An uncoordinated ``gh pr merge`` is the committed bad transcript.

What it cannot see: a step that reaches the service by a route other than
``kyle-lock``, the coordination MCP tool name or the HTTP path (for example a
script fetched at run time), and anything outside this repository, such as a
host-side wrapper around the pipeline. Those are the joint switch's external
inventory (Kyle #2130), not this gate's.

Usage: ``python3 ci/merge_admission.py [.woodpecker/ci.yml]`` exits 1 and
prints each finding, or 0.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
RESOURCE = "main-merge"
#: kyle-lock actions that take, or act under, a main-merge lease.
LEASE_ACTIONS = frozenset({"acquire", "run", "renew", "begin-merge", "record-merge"})
#: Any of these in a CI step hands it a coordination principal.
CREDENTIALS = ("KYLE_LOCK_TOKEN", "KYLE_LOCK_TOKEN_FILE")
SERVICE_ROUTES = ("coordination_acquire", "coordination_begin_merge",
                  f"/api/coordination/{RESOURCE}/")


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=True)
    except ValueError:
        # Unbalanced quoting: fall back to whitespace, still without comments.
        return line.split("#", 1)[0].split()


def _line_findings(line: str, where: str) -> list[str]:
    tokens = _tokens(line)
    found: list[str] = []
    for i, token in enumerate(tokens):
        if Path(token).name == "kyle-lock":
            rest = tokens[i + 1:]
            if RESOURCE in rest and LEASE_ACTIONS.intersection(rest):
                found.append(f"{where}: kyle-lock {' '.join(rest)} - CI must never take {RESOURCE}")
        if any(route in token for route in SERVICE_ROUTES):
            found.append(f"{where}: {token} - CI must never take {RESOURCE}")
        if any(token == name or token.startswith(f"{name}=") or f"${name}" in token
               or f"${{{name}}}" in token for name in CREDENTIALS):
            found.append(f"{where}: {token} - CI must not hold a coordination credential")
    return found


SCRIPT_SUFFIXES = frozenset({".sh", ".bash", ".py"})


def _is_script(path: Path) -> bool:
    if path.suffix in SCRIPT_SUFFIXES:
        return True
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def _scripts(line: str, root: Path) -> Iterable[Path]:
    """Repository scripts a command line runs: path-like tokens only, so prose
    and data files a script merely names are never followed."""
    base = root.resolve()
    for token in _tokens(line):
        if "/" not in token or len(token) > 255 or token.startswith(("-", "$")):
            continue
        try:
            candidate = (root / token).resolve()
            if candidate.is_relative_to(base) and candidate.is_file() and _is_script(candidate):
                yield candidate
        except OSError:
            continue


def _scan(lines: Iterable[str], where: str, root: Path, seen: set[Path]) -> list[str]:
    found: list[str] = []
    for number, line in enumerate(lines, 1):
        found += _line_findings(line, f"{where}:{number}")
        for script in _scripts(line, root):
            if script not in seen:
                seen.add(script)
                text = script.read_text(encoding="utf-8", errors="replace")
                found += _scan(text.splitlines(), str(script.relative_to(root.resolve())), root, seen)
    return found


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def pipeline_findings(ci_yml: str, root: Path = ROOT, followed: set[Path] | None = None) -> list[str]:
    """``followed``, when given, receives every script the scan read, so a
    zero can be told apart from a scan that reached nothing."""
    config = yaml.safe_load(ci_yml) or {}
    steps = config.get("steps") or []
    if isinstance(steps, dict):
        steps = [dict(step, name=name) for name, step in steps.items()]
    found: list[str] = []
    seen: set[Path] = set() if followed is None else followed
    for step in steps:
        name = step.get("name", "?")
        for key in ("environment", "secrets"):
            for text in _strings(step.get(key)):
                if text.upper() in CREDENTIALS or text.split("=", 1)[0].upper() in CREDENTIALS:
                    found.append(f"step {name} {key}: {text} - CI must not hold a coordination credential")
        commands = step.get("commands") or []
        if isinstance(commands, str):
            commands = [commands]
        lines = [part for command in commands for part in str(command).splitlines()]
        found += _scan(lines, f"step {name}", root, seen)
    return found


def transcript_findings(calls: list[dict[str, Any]], pr: int) -> list[str]:
    """``calls`` are ``{"tool": "lock"|"gh", "argv": [...], "exit": int}``,
    in order, as the merger issued them."""
    held = begun = False
    merges = 0
    found: list[str] = []
    for index, call in enumerate(calls):
        argv = [str(part) for part in call.get("argv", [])]
        ok = call.get("exit") == 0
        if call.get("tool") == "lock" and argv[:2] == ["acquire", RESOURCE] and ok:
            held = True
        elif call.get("tool") == "lock" and argv[:2] == ["release", RESOURCE]:
            held = begun = False
        elif call.get("tool") == "lock" and argv[:2] == ["begin-merge", RESOURCE] and ok:
            if not held:
                found.append(f"call {index}: begin-merge without a held {RESOURCE} lease")
            elif "--pr" in argv and argv[argv.index("--pr") + 1:][:1] == [str(pr)]:
                begun = True
            else:
                found.append(f"call {index}: begin-merge names a different PR than {pr}")
        elif call.get("tool") == "gh" and argv[:2] == ["pr", "merge"]:
            merges += 1
            if not (held and begun):
                found.append(f"call {index}: gh pr merge without a held lease and a confirmed begin-merge")
            if merges > 1:
                found.append(f"call {index}: a second gh pr merge - an ambiguous merge is never repeated")
            if argv[2:3] != [str(pr)]:
                found.append(f"call {index}: gh pr merge names a different PR than {pr}")
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else ROOT / ".woodpecker" / "ci.yml"
    followed: set[Path] = set()
    found = pipeline_findings(path.read_text(encoding="utf-8"), followed=followed)
    for finding in found:
        print(finding)
    print(f"merge-admission: {len(found)} finding(s) in {path}, {len(followed)} script(s) followed")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
