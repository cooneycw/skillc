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

import re
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


SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh"})
OPERATORS = frozenset({";", "&&", "||", "|", "&", "(", ")", ";;", "|&"})
#: kyle-lock's own options that take a value, before the action.
CLIENT_VALUE_OPTIONS = frozenset({"--url"})


def _tokens(line: str) -> list[str]:
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        return list(lexer)
    except ValueError:
        # Unbalanced quoting: fall back to whitespace, still without comments.
        return line.split("#", 1)[0].split()


def _commands(tokens: list[str]) -> list[list[str]]:
    """Split at shell operators, so one command's arguments never satisfy
    another command's test."""
    commands: list[list[str]] = [[]]
    for token in tokens:
        if token in OPERATORS:
            commands.append([])
        else:
            commands[-1].append(token)
    return [command for command in commands if command]


ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
#: Programs that run their first non-option argument as the command.
WRAPPERS = frozenset({"env", "exec", "command", "nohup", "time", "sudo", "nice"})
#: Shell words that precede the command they govern (``if kyle-lock ...``).
SHELL_KEYWORDS = frozenset({"if", "then", "elif", "else", "while", "until", "do", "!", "{"})
#: Builtins that run their argument as shell text in the current shell.
SOURCES = frozenset({"source", "."})


def _program(command: list[str]) -> tuple[int, str] | None:
    """Index and name of the program a command actually runs: assignments
    and wrappers are skipped, and ``python3 x`` / ``bash x`` / ``uv run x``
    run ``x``. An argument to some other program is never an invocation."""
    i = 0
    while i < len(command):
        token = command[i]
        name = Path(token).name
        if ASSIGNMENT.match(token) or token in SHELL_KEYWORDS or token in SOURCES:
            i += 1
        elif name in WRAPPERS or (name == "uv" and command[i + 1:i + 2] == ["run"]):
            i += 2 if name == "uv" else 1
            while i < len(command) and (command[i].startswith("-") or ASSIGNMENT.match(command[i])):
                i += 1
        elif name in SHELLS or re.fullmatch(r"python[0-9.]*", name):
            j = i + 1
            while j < len(command) and command[j].startswith("-"):
                if name in SHELLS and "c" in command[j].lstrip("-"):
                    return i, name
                j += 1
            if j >= len(command):
                return i, name
            i = j
        else:
            return i, name
    return None


def _client_call(command: list[str]) -> tuple[str, str] | None:
    """(action, resource) of a kyle-lock invocation, read by position."""
    program = _program(command)
    if program is None or program[1] != "kyle-lock":
        return None
    rest = command[program[0] + 1:]
    j = 0
    while j < len(rest) and rest[j].startswith("-"):
        j += 2 if rest[j] in CLIENT_VALUE_OPTIONS else 1
    if j < len(rest):
        return rest[j], rest[j + 1] if j + 1 < len(rest) else ""
    return None


def _inner_scripts(command: list[str]) -> list[str]:
    """Shell text the command's program runs: ``sh -c '<text>'`` (any flag
    cluster holding ``c``) and ``eval <words>``."""
    program = _program(command)
    if program is None:
        return []
    i, name = program
    if name == "eval":
        return [" ".join(command[i + 1:])]
    if name in SHELLS:
        for k in range(i + 1, len(command) - 1):
            flag = command[k]
            if flag.startswith("-") and not flag.startswith("--") and "c" in flag[1:]:
                return [command[k + 1]]
    return []


def _line_findings(line: str, where: str) -> tuple[list[str], list[str]]:
    """Findings on one line, and the inner shell texts it runs."""
    found: list[str] = []
    inner: list[str] = []
    for command in _commands(_tokens(line)):
        call = _client_call(command)
        if call and call[1] == RESOURCE and call[0] in LEASE_ACTIONS:
            found.append(f"{where}: kyle-lock {call[0]} {call[1]} - CI must never take {RESOURCE}")
        for token in command:
            if any(route in token for route in SERVICE_ROUTES):
                found.append(f"{where}: {token} - CI must never take {RESOURCE}")
            if any(token == name or token.startswith(f"{name}=") or f"${name}" in token
                   or f"${{{name}}}" in token for name in CREDENTIALS):
                found.append(f"{where}: {token} - CI must not hold a coordination credential")
        inner += _inner_scripts(command)
    return found, inner


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
    """Repository scripts a command line EXECUTES: the program position of
    each command (``./x.sh``, ``bash x.sh``, ``python3 x.py``, ``source x``).
    A script a command merely names (``cat x.sh``) is not run, so not followed."""
    base = root.resolve()
    for command in _commands(_tokens(line)):
        program = _program(command)
        if program is None:
            continue
        token = command[program[0]]
        if len(token) > 255 or token.startswith(("-", "$")):
            continue
        try:
            candidate = (root / token).resolve()
            if candidate.is_relative_to(base) and candidate.is_file() and _is_script(candidate):
                yield candidate
        except OSError:
            continue


def _scan(lines: Iterable[str], where: str, root: Path, seen: set[Path], depth: int = 0) -> list[str]:
    """Inline findings, the repository scripts a line names, and the shell
    text it runs, each scanned the same way (a script run inside ``sh -c``
    is followed too)."""
    found: list[str] = []
    for number, line in enumerate(lines, 1):
        here = f"{where}:{number}"
        inline, inner = _line_findings(line, here)
        found += inline
        for script in _scripts(line, root):
            if script not in seen:
                seen.add(script)
                text = script.read_text(encoding="utf-8", errors="replace")
                found += _scan(text.splitlines(), str(script.relative_to(root.resolve())), root, seen, depth)
        if depth < 8:
            for text in inner:
                found += _scan(text.splitlines(), f"{here} (inner shell)", root, seen, depth + 1)
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


def pipeline_findings(ci_yml: str, root: Path = ROOT, followed: set[Path] | None = None,
                      counts: dict[str, int] | None = None) -> list[str]:
    """``followed``, when given, receives every script the scan read, so a
    zero can be told apart from a scan that reached nothing."""
    config = yaml.safe_load(ci_yml) or {}
    steps = config.get("steps") or []
    if isinstance(steps, dict):
        steps = [dict(step, name=name) for name, step in steps.items()]
    found: list[str] = []
    if not isinstance(steps, list) or not steps:
        return ["pipeline has no steps - nothing was examined, which is not a pass"]
    seen: set[Path] = set() if followed is None else followed
    examined = 0
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
        examined += len(lines)
        found += _scan(lines, f"step {name}", root, seen)
    if counts is not None:
        counts.update(steps=len(steps), lines=examined)
    if not examined:
        found.append("pipeline has no step commands - nothing was examined, which is not a pass")
    return list(dict.fromkeys(found))


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
        elif call.get("tool") == "lock" and (argv[:2] == ["release", RESOURCE]
                                             or (argv[:2] == ["renew", RESOURCE] and not ok)):
            # A released or unconfirmed lease admits no merge until a new grant and begin.
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
    counts: dict[str, int] = {}
    found = pipeline_findings(path.read_text(encoding="utf-8"), followed=followed, counts=counts)
    for finding in found:
        print(finding)
    print(f"merge-admission: {len(found)} finding(s) in {path}: {counts.get('steps', 0)} step(s), "
          f"{counts.get('lines', 0)} command line(s), {len(followed)} script(s) followed")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
