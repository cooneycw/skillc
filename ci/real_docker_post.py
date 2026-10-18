#!/usr/bin/env python3
"""The `<agent-host>` real-Docker runner's posting glue (#315, R1).

**This is the component R1 pins.** `run-real-docker` invokes THIS script by
its absolute path in the INSTALLED copy (a checkout pinned to a reviewed
main SHA, updated only by an explicit operator step - never implicitly at
each tick), with `PYTHONPATH` set to that installed copy's root and nothing
else. The checkout under test supplies only the JUnit report this script
reads; it never supplies the code that interprets that report. A requested
SHA that edits `ci/check_real_docker_ran.py` to always print `SUCCESS`
cannot affect the posted verdict, because that edited file is never on
`sys.path` for this process - only the installed copy's own `ci/` package
is, via `PYTHONPATH`.

RUNNER BEHIND (#456). The installed copy's floor (`DECLARED_REAL_DOCKER_FILES`)
is the only thing that decides which files must have executed. On a
certifying run the caller also passes the checkout, and this script READS -
by `ast`, never by importing - the tested commit's own floor literal. That
list is subject-provided data and can only ADD a signal: a file it declares
that the runner does not count makes an otherwise-green run `RUNNER_BEHIND`
(the runner needs a re-pin); a file it no longer declares changes nothing,
because the runner's floor still applies in full. An unreadable commit floor
is `ERROR`, never a pass. Precedence: ERROR > FAILURE > RUNNER_BEHIND > SUCCESS.

This script computes and PRINTS the verdict and the leak-safe summary; it
does not call the GitHub API itself. `run-real-docker` reads this script's
stdout and performs the actual `gh api` call - kept separate so the
decision logic here stays testable without a network call or a real token.

Output contract (stdout), three sections separated by a line of exactly
`---`:
1. The bare status word (`SUCCESS` / `FAILURE` / `ERROR` / `RUNNER_BEHIND`) -
   the caller's own exit-code and GitHub-state mapping.
2. The commit-status `description` (one line).
3. The full comment body (may be multiple lines, to end of output).

Exit code mirrors the status: 0 SUCCESS, 1 FAILURE, 2 ERROR - matching
`check_real_docker_ran.py`'s own convention, reused here rather than
invented differently for the same three words - and 4 RUNNER_BEHIND (3 is
run-real-docker's "never started", which poll-triggers retries).

Usage: real_docker_post.py <junit-xml-report> <sha> <runner-sha> [<checkout>]
  <checkout>  the tested commit's checkout, for a certifying run; omitted or
              empty for a control (break-mode) run, which skips the check.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ci.check_real_docker_ran import (
    DECLARED_REAL_DOCKER_FILES,
    ERROR,
    FAILURE,
    RUNNER_BEHIND,
    SUCCESS,
    Verdict,
    verdict,
)
from ci.real_docker_summary import format_comment_body, format_status_description

FLOOR_FILE = "ci/check_real_docker_ran.py"
FLOOR_NAME = "DECLARED_REAL_DOCKER_FILES"
#: A floor entry is a dotted module path under tests/. Anything else is
#: refused, not reported: these strings come from the commit under test.
_FLOOR_ENTRY = re.compile(r"^tests(\.[A-Za-z_][A-Za-z0-9_]*)+$")
EXIT_CODES = {SUCCESS: 0, FAILURE: 1, ERROR: 2, RUNNER_BEHIND: 4}


class CommitFloorUnreadable(ValueError):
    """The tested commit's floor could not be read as one literal list."""


def read_commit_floor(checkout: str | Path) -> tuple[str, ...]:
    """The tested commit's `DECLARED_REAL_DOCKER_FILES`, parsed - never
    imported or executed - from its `ci/check_real_docker_ran.py`."""
    path = Path(checkout) / FLOOR_FILE
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        raise CommitFloorUnreadable(f"{FLOOR_FILE} is unreadable: {type(exc).__name__}") from None
    values: list[ast.expr | None] = []
    for node in tree.body:
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == FLOOR_NAME for t in targets):
            values.append(value)
    if len(values) != 1:
        raise CommitFloorUnreadable(f"{FLOOR_FILE} assigns {FLOOR_NAME} {len(values)} times, not once")
    value = values[0]
    if not isinstance(value, ast.Tuple | ast.List) or not all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts):
        raise CommitFloorUnreadable(f"{FLOOR_NAME} is not one literal list of strings")
    floor = tuple(e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
    if not all(_FLOOR_ENTRY.fullmatch(name) for name in floor) or len(set(floor)) != len(floor):
        raise CommitFloorUnreadable(f"{FLOOR_NAME} holds a malformed or repeated entry")
    return floor


def apply_commit_floor(result: Verdict, commit_floor: tuple[str, ...],
                       runner_floor: tuple[str, ...] = DECLARED_REAL_DOCKER_FILES) -> Verdict:
    """Add-only: the commit's list can turn a SUCCESS into RUNNER_BEHIND, and
    annotates a FAILURE; it never removes a requirement, never touches ERROR."""
    uncounted = tuple(name for name in commit_floor if name not in runner_floor)
    dropped = tuple(name for name in runner_floor if name not in commit_floor)
    annotated = dataclasses.replace(result, uncounted_files=uncounted, dropped_by_commit=dropped)
    if result.status == SUCCESS and uncounted:
        return dataclasses.replace(
            annotated, status=RUNNER_BEHIND,
            reason=f"the tested commit declares {len(uncounted)} floor file(s) this runner does not count")
    return annotated


def compute(report_path: str, *, sha: str, runner_sha: str, checkout: str | None = None) -> Verdict:
    """Never lets a missing/unparseable report escape as an exception past
    this point - the whole point of a runner script calling this is to
    always get back something postable, never a traceback with no status
    word in it."""
    try:
        result = verdict(report_path)
    except OSError as exc:
        return Verdict(status=ERROR, reason=f"report unreadable: {exc}")
    except ET.ParseError as exc:
        return Verdict(status=ERROR, reason=f"report unparseable: {exc}")
    if not checkout or result.status == ERROR:
        return result
    try:
        commit_floor = read_commit_floor(checkout)
    except CommitFloorUnreadable as exc:
        return dataclasses.replace(result, status=ERROR, reason=f"cannot read the tested commit's floor: {exc}")
    return apply_commit_floor(result, commit_floor)


def render(result: Verdict, *, sha: str, runner_sha: str) -> str:
    description = format_status_description(result, sha=sha, runner_sha=runner_sha)
    body = format_comment_body(result, sha=sha, runner_sha=runner_sha)
    return f"{result.status}\n{description}\n---\n{body}"


def main(argv: list[str]) -> int:
    if len(argv) not in (4, 5):
        print("usage: real_docker_post.py <junit-xml-report> <sha> <runner-sha> [<checkout>]", file=sys.stderr)
        return 2
    report_path, sha, runner_sha = argv[1], argv[2], argv[3]
    checkout = argv[4] if len(argv) == 5 and argv[4] else None
    result = compute(report_path, sha=sha, runner_sha=runner_sha, checkout=checkout)
    print(render(result, sha=sha, runner_sha=runner_sha))
    return EXIT_CODES[result.status]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
