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

This script computes and PRINTS the verdict and the leak-safe summary; it
does not call the GitHub API itself. `run-real-docker` reads this script's
stdout and performs the actual `gh api` call - kept separate so the
decision logic here stays testable without a network call or a real token.

Output contract (stdout), three sections separated by a line of exactly
`---`:
1. The bare status word (`SUCCESS` / `FAILURE` / `ERROR`) - the caller's
   own exit-code and GitHub-state mapping.
2. The commit-status `description` (one line).
3. The full comment body (may be multiple lines, to end of output).

Exit code mirrors the status: 0 SUCCESS, 1 FAILURE, 2 ERROR - matching
`check_real_docker_ran.py`'s own convention, reused here rather than
invented differently for the same three words.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

from ci.check_real_docker_ran import ERROR, FAILURE, SUCCESS, Verdict, verdict
from ci.real_docker_summary import format_comment_body, format_status_description


def compute(report_path: str, *, sha: str, runner_sha: str) -> Verdict:
    """Never lets a missing/unparseable report escape as an exception past
    this point - the whole point of a runner script calling this is to
    always get back something postable, never a traceback with no status
    word in it."""
    try:
        return verdict(report_path)
    except OSError as exc:
        return Verdict(status=ERROR, reason=f"report unreadable: {exc}")
    except ET.ParseError as exc:
        return Verdict(status=ERROR, reason=f"report unparseable: {exc}")


def render(result: Verdict, *, sha: str, runner_sha: str) -> str:
    description = format_status_description(result, sha=sha, runner_sha=runner_sha)
    body = format_comment_body(result, sha=sha, runner_sha=runner_sha)
    return f"{result.status}\n{description}\n---\n{body}"


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: real_docker_post.py <junit-xml-report> <sha> <runner-sha>", file=sys.stderr)
        return 2
    report_path, sha, runner_sha = argv[1], argv[2], argv[3]
    result = compute(report_path, sha=sha, runner_sha=runner_sha)
    print(render(result, sha=sha, runner_sha=runner_sha))
    return {SUCCESS: 0, FAILURE: 1, ERROR: 2}[result.status]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
