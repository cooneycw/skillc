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

**It refuses what it does not model.** A static shell reader that tries to
model every form never finishes, and one that skips a form it cannot read
reports a false green. So each of these is reported ``UNPARSEABLE`` - a
finding, exit 1 - rather than scanned or skipped:

- ``eval`` or ``sh -c`` / ``bash -c`` text whose program is dynamic
  (``eval "$CMD"``, ``bash -c "$CMD"``);
- a wrapper option it does not know: ``env``, ``sudo``, ``nice``, ``exec``,
  ``command``, ``time``, ``timeout``, ``stdbuf``, ``uv run``, a shell or
  ``python`` given an option outside the tables below;
- ``kyle-lock`` passed as an argument to a program that is not a known reader
  (``xargs kyle-lock``, a function call, ``find -exec``);
- a Python script, ``python -c`` code, or a non-shell heredoc that names the
  client, the resource, a service route or a credential;
- unbalanced quoting or substitution, and inner shells nested past 8 levels.

It does model: function definitions (the header is removed and the body is
scanned where it is written, so an acquiring body is a finding even if
nothing calls it; calling a function with ``kyle-lock`` as an argument is
refused as above), line continuations (joined before tokenizing, in steps and in
followed scripts), ``;``/``&&``/``||``/``|`` chains and subshells, shell
keywords, assignments, the wrappers above with their known options,
``$(...)`` and backtick substitutions, shell heredocs, ``source``/``.``, and
repository scripts run in program position or named as string literals in a
followed Python script.

What it cannot see: a step that reaches the service by a route other than
``kyle-lock``, the coordination MCP tool name or the HTTP path (for example a
script fetched at run time, or a client path held only in a variable whose name
is not ``kyle-lock``), and anything outside this repository, such as a
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
OPERATORS = frozenset({";", "&&", "||", "|", "&", "(", ")", "()", ";;", "|&", ";&"})
#: kyle-lock's own options that take a value, before the action.
CLIENT_VALUE_OPTIONS = frozenset({"--url"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
#: Shell words that precede the command they govern (``if kyle-lock ...``).
SHELL_KEYWORDS = frozenset({"if", "then", "elif", "else", "while", "until", "do", "!", "{"})
#: Builtins that run their argument as shell text in the current shell.
SOURCES = frozenset({"source", "."})
#: Programs that only print or read their arguments: a kyle-lock among them
#: is a mention, not an invocation.
READERS = frozenset({"echo", "printf", ":", "grep", "cat", "test", "[", "true", "false",
                     "ls", "head", "tail", "wc", "which"})

#: Wrappers that run a command, with (options taking a value, options that do not).
#: Any other option is UNPARSEABLE: the gate refuses rather than guesses (#2130).
WRAPPER_OPTIONS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "env": (frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
            frozenset({"-i", "--ignore-environment", "-0", "--null", "-v", "--debug", "-"})),
    "sudo": (frozenset({"-u", "--user", "-g", "--group", "-C", "--close-from", "-D", "--chdir",
                        "-h", "--host", "-p", "--prompt", "-r", "--role", "-t", "--type",
                        "-U", "--other-user"}),
             frozenset({"-E", "--preserve-env", "-H", "--set-home", "-n", "--non-interactive",
                        "-S", "--stdin", "-k", "--reset-timestamp", "-b", "--background",
                        "-P", "--preserve-groups"})),
    "nice": (frozenset({"-n", "--adjustment"}), frozenset()),
    "nohup": (frozenset(), frozenset()),
    "exec": (frozenset({"-a"}), frozenset({"-c", "-l"})),
    "command": (frozenset(), frozenset({"-p"})),
    "time": (frozenset({"-f", "--format", "-o", "--output"}),
             frozenset({"-p", "-a", "--append", "-v", "--verbose", "--portability"})),
    "timeout": (frozenset({"-s", "--signal", "-k", "--kill-after"}),
                frozenset({"--preserve-status", "--foreground", "-v", "--verbose"})),
    "stdbuf": (frozenset({"-i", "--input", "-o", "--output", "-e", "--error"}), frozenset()),
    "uv run": (frozenset({"--with", "--python", "-p", "--project", "--directory", "--extra",
                          "--group", "--env-file", "--with-requirements", "--package",
                          "--with-editable", "--index", "--default-index"}),
               frozenset({"--no-sync", "--frozen", "--locked", "--no-project", "--isolated",
                          "-q", "--quiet", "-v", "--verbose", "--all-extras", "--no-dev",
                          "--active", "--no-group"})),
}
PYTHON_OPTIONS = (frozenset({"-W", "-X"}),
                  frozenset({"-u", "-B", "-O", "-OO", "-E", "-s", "-S", "-I", "-q", "-b", "-bb", "-d", "-v"}))
#: Single-letter shell flags that take no value (``c`` and ``o`` are handled apart).
SHELL_FLAGS = frozenset("abefhkmnptuvxBCEHPTil")
SHELL_LONG = (frozenset({"--rcfile", "--init-file"}),
              frozenset({"--norc", "--noprofile", "--posix", "--login", "--noediting"}))
#: Words that would put the coordination client in a Python script.
CLIENT_WORDS = ("kyle-lock", RESOURCE, *SERVICE_ROUTES, *CREDENTIALS)


class Unmodelled(Exception):
    """A form the gate does not model. It is reported, never skipped."""


def _tokens(line: str) -> list[str]:
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        return list(lexer)
    except ValueError as exc:
        raise Unmodelled(f"unbalanced quoting ({exc})") from exc


def _logical_lines(lines: Iterable[str]) -> list[tuple[int, str]]:
    """Physical lines joined at a trailing backslash, numbered by first line."""
    joined: list[tuple[int, str]] = []
    pending: tuple[int, str] | None = None
    for number, raw in enumerate(lines, 1):
        line = raw.rstrip("\r")
        trailing = len(line) - len(line.rstrip("\\"))
        start, text = pending if pending else (number, "")
        if trailing % 2:
            pending = (start, text + line[:-1] + " ")
            continue
        joined.append((start, text + line))
        pending = None
    if pending:
        joined.append(pending)
    return joined


def _strip_definitions(tokens: list[str]) -> list[str]:
    """Remove function definition headers (``function name [()]``,
    ``name ()``) so the body is scanned where it is written. A body that
    acquires is then a finding whether or not anything calls it, which is
    stricter than attributing the call, and cannot be a false green."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        at_start = not out or out[-1] in OPERATORS or out[-1] in SHELL_KEYWORDS
        if at_start and token == "function" and i + 1 < len(tokens):
            i += 2
            if tokens[i:i + 1] == ["()"]:
                i += 1
            elif tokens[i:i + 2] == ["(", ")"]:
                i += 2
            out.append(";")
        elif at_start and token not in OPERATORS and tokens[i + 1:i + 2] == ["()"]:
            i += 2
            out.append(";")
        elif at_start and token not in OPERATORS and tokens[i + 1:i + 3] == ["(", ")"]:
            i += 3
            out.append(";")
        else:
            out.append(token)
            i += 1
    return out


def _commands(tokens: list[str]) -> list[list[str]]:
    """Split at shell operators, so one command's arguments never satisfy
    another command's test."""
    commands: list[list[str]] = [[]]
    for token in _strip_definitions(tokens):
        if token in OPERATORS:
            commands.append([])
        else:
            commands[-1].append(token)
    return [command for command in commands if command]


SUBSTITUTED = "__skillc_substitution__"


def _substitutions(line: str) -> tuple[str, list[str]]:
    """The line with each ``$( ... )`` and backtick span replaced by a
    placeholder, and the text inside them: it runs too, and lifting it out
    first keeps quotes nested inside it from confusing the tokenizer."""
    out: list[str] = []
    found: list[str] = []
    i = 0
    while i < len(line):
        if line.startswith("$((", i):
            end = line.find("))", i + 3)
            if end < 0:
                raise Unmodelled("unbalanced arithmetic expansion")
            out.append(SUBSTITUTED)
            i = end + 2
        elif line.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(line) and depth:
                depth += {"(": 1, ")": -1}.get(line[j], 0)
                j += 1
            if depth:
                raise Unmodelled("unbalanced command substitution")
            found.append(line[i + 2:j - 1])
            out.append(SUBSTITUTED)
            i = j
        elif line[i] == "`":
            end = line.find("`", i + 1)
            if end < 0:
                raise Unmodelled("unbalanced backtick substitution")
            found.append(line[i + 1:end])
            out.append(SUBSTITUTED)
            i = end + 1
        else:
            out.append(line[i])
            i += 1
    return "".join(out), found


def _dynamic(token: str) -> bool:
    return "$" in token or "`" in token or SUBSTITUTED in token


def _skip_options(command: list[str], i: int, name: str,
                  options: tuple[frozenset[str], frozenset[str]]) -> int:
    values, flags = options
    while i < len(command) and command[i].startswith("-"):
        token = command[i]
        if token == "--":
            return i + 1
        option = token.split("=", 1)[0]
        if "=" in token and (option in values or option in flags):
            i += 1
        elif token in values:
            if i + 1 >= len(command):
                raise Unmodelled(f"{name} option {token} has no value")
            i += 2
        elif token in flags or (name == "nice" and token[1:].isdigit()) or name == "stdbuf" and token[:2] in values and len(token) > 2:
            i += 1
        else:
            raise Unmodelled(f"{name} option {token} is not modelled")
    return i


def _program(command: list[str], strict: bool = False) -> tuple[int, str, list[str]] | None:
    """Index and name of the program a command actually runs, and the shell
    text it runs inline (``sh -c``, ``eval``). Assignments, keywords and the
    modelled wrappers are skipped; an unmodelled option or a dynamic program
    raises :class:`Unmodelled`. A dynamic program (``$HERE/x.py``) is
    ordinary at the top level, where it cannot be the client unless it is
    named ``kyle-lock``; inside ``eval`` or ``sh -c`` text (``strict``) it is
    the non-literal case and is refused. ``None`` means it runs nothing."""
    i = 0
    while i < len(command):
        token = command[i]
        name = Path(token).name
        if ASSIGNMENT.match(token) or token in SHELL_KEYWORDS or token in SOURCES:
            i += 1
        elif _dynamic(token) and name != "kyle-lock":
            if strict:
                raise Unmodelled(f"eval or sh -c running dynamic program {token!r} is not modelled")
            return i, name, []
        elif name == "uv" and command[i + 1:i + 2] == ["run"]:
            i = _skip_options(command, i + 2, "uv run", WRAPPER_OPTIONS["uv run"])
        elif name == "command" and any(t in ("-v", "-V") for t in command[i + 1:i + 2]):
            return None  # a lookup, not an execution
        elif name in WRAPPER_OPTIONS:
            i = _skip_options(command, i + 1, name, WRAPPER_OPTIONS[name])
            while i < len(command) and ASSIGNMENT.match(command[i]):
                i += 1
            if name == "timeout":
                i += 1  # the duration
        elif name == "eval":
            return i, name, [" ".join(command[i + 1:])]
        elif name in SHELLS:
            j = i + 1
            while j < len(command) and command[j][:1] in "-+" and command[j] not in ("-", "--"):
                flag = command[j]
                if flag.startswith("--"):
                    j = _skip_options(command, j, name, SHELL_LONG)
                    continue
                letters = flag[1:]
                if not set(letters) <= SHELL_FLAGS | {"c", "o"}:
                    raise Unmodelled(f"{name} option {flag} is not modelled")
                j += 1 + letters.count("o")  # each o takes an option name
                if "c" in letters:
                    if j >= len(command):
                        raise Unmodelled(f"{name} -c has no command text")
                    return i, name, [command[j]]
            if j < len(command) and command[j] in ("-", "--"):
                j += 1
            if j >= len(command):
                return i, name, []
            i = j
        elif re.fullmatch(r"python[0-9.]*", name):
            j = i + 1
            while j < len(command) and command[j].startswith("-"):
                if command[j] == "-":
                    return i, name, []  # the script is stdin, e.g. a heredoc
                if command[j] in ("-c", "-m"):
                    code = command[j + 1] if j + 1 < len(command) else ""
                    if command[j] == "-c" and any(word in code for word in CLIENT_WORDS):
                        raise Unmodelled(f"{name} -c code naming the coordination client is not modelled")
                    return i, name, []
                j = _skip_options(command, j, name, PYTHON_OPTIONS) if command[j] not in ("-c", "-m") else j
                if j < len(command) and not command[j].startswith("-"):
                    break
            if j >= len(command):
                return i, name, []
            i = j
        else:
            return i, name, []
    return None


def _client_call(command: list[str], program: tuple[int, str, list[str]] | None) -> tuple[str, str] | None:
    """(action, resource) of a kyle-lock invocation, read by position."""
    if program is None or program[1] != "kyle-lock":
        return None
    rest = command[program[0] + 1:]
    j = 0
    while j < len(rest) and rest[j].startswith("-"):
        j += 2 if rest[j] in CLIENT_VALUE_OPTIONS else 1
    if j < len(rest):
        return rest[j], rest[j + 1] if j + 1 < len(rest) else ""
    return None


def _line_findings(line: str, where: str, strict: bool = False
                   ) -> tuple[list[str], list[tuple[str, bool]], list[str]]:
    """Findings on one logical line, the inner shell texts it runs (each with
    whether it came from ``eval``/``sh -c``, which are scanned strictly), and
    the program tokens it executes (for script following)."""
    found: list[str] = []
    inner: list[tuple[str, bool]] = []
    programs: list[str] = []
    try:
        line, substituted = _substitutions(line)
        inner += [(text, False) for text in substituted]
        commands = _commands(_tokens(line))
        for command in commands:
            program = _program(command, strict)
            if program is not None:
                programs.append(command[program[0]])
                inner += [(text, True) for text in program[2]]
            call = _client_call(command, program)
            if call and call[1] == RESOURCE and call[0] in LEASE_ACTIONS:
                found.append(f"{where}: kyle-lock {call[0]} {call[1]} - CI must never take {RESOURCE}")
            elif (program is not None and program[1] != "kyle-lock" and program[1] not in READERS
                  and program[1] not in SHELLS and program[1] != "eval"
                  and any(Path(token).name == "kyle-lock" for token in command[program[0] + 1:])):
                raise Unmodelled(f"kyle-lock passed to {program[1]}, which may run it, is not modelled")
            for token in command:
                if any(route in token for route in SERVICE_ROUTES):
                    found.append(f"{where}: {token} - CI must never take {RESOURCE}")
                if any(token == name or token.startswith(f"{name}=") or f"${name}" in token
                       or f"${{{name}}}" in token for name in CREDENTIALS):
                    found.append(f"{where}: {token} - CI must not hold a coordination credential")
    except Unmodelled as exc:
        found.append(f"{where}: UNPARSEABLE - {exc}")
    return found, inner, programs


SCRIPT_SUFFIXES = frozenset({".sh", ".bash", ".py"})
PY_SCRIPT_LITERAL = re.compile(r"""["']([\w./-]+\.(?:sh|bash|py))["']""")


def _is_script(path: Path) -> bool:
    if path.suffix in SCRIPT_SUFFIXES:
        return True
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def _resolve(token: str, root: Path) -> Path | None:
    if len(token) > 255 or token.startswith(("-", "$")):
        return None
    try:
        candidate = (root / token).resolve()
        if candidate.is_relative_to(root.resolve()) and candidate.is_file() and _is_script(candidate):
            return candidate
    except OSError:
        pass
    return None


HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _client_word_findings(lines: list[str], where: str, what: str) -> list[str]:
    """Refuse, rather than model, non-shell text that names the client."""
    return [f"{where}: UNPARSEABLE - {what} naming the coordination client is not modelled"
            for line in lines if any(word in line for word in CLIENT_WORDS)][:1]


def _follow(script: Path, root: Path, seen: set[Path], depth: int) -> list[str]:
    where = str(script.relative_to(root.resolve()))
    text = script.read_text(encoding="utf-8", errors="replace")
    if script.suffix != ".py":
        return _scan(text.splitlines(), where, root, seen, depth)
    # Python is not shell: refuse any mention of the client rather than model
    # it, and follow the repository scripts it names in string literals.
    found: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        code = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
        if any(word in code for word in CLIENT_WORDS):
            found.append(f"{where}:{number}: UNPARSEABLE - a Python script naming the coordination "
                         "client is not modelled")
        for literal in PY_SCRIPT_LITERAL.findall(code):
            target = _resolve(literal, root)
            if target is not None and target not in seen:
                seen.add(target)
                found += _follow(target, root, seen, depth)
    return found


def _scan(lines: Iterable[str], where: str, root: Path, seen: set[Path], depth: int = 0,
          strict: bool = False) -> list[str]:
    """Each logical line's findings, then the scripts it executes and the
    shell text it runs, each scanned the same way."""
    found: list[str] = []
    logical = _logical_lines(lines)
    k = 0
    while k < len(logical):
        number, line = logical[k]
        k += 1
        here = f"{where}:{number}"
        inline, inner, programs = _line_findings(line, here, strict)
        found += inline
        marker = HEREDOC.search(line.split("#", 1)[0] if line.lstrip().startswith("#") else line)
        if marker:
            body: list[str] = []
            while k < len(logical) and logical[k][1].strip() != marker.group(2):
                body.append(logical[k][1])
                k += 1
            k += 1  # the terminator
            if any(Path(token).name in SHELLS for token in programs):
                inner.append(("\n".join(body), False))
            else:
                found += _client_word_findings(body, here, "a heredoc")
        for token in programs:
            script = _resolve(token, root)
            if script is not None and script not in seen:
                seen.add(script)
                found += _follow(script, root, seen, depth)
        for text, inline_shell in inner:
            if depth >= 8:
                found.append(f"{here}: UNPARSEABLE - inner shells nested too deep")
                break
            found += _scan(text.splitlines(), f"{here} (inner shell)", root, seen, depth + 1,
                           strict=inline_shell)
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
