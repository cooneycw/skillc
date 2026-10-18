#!/usr/bin/env python3
"""CI control (#307, widened to jq by #276 and to make by #434): fail if a tool-dependent test
population silently skipped. AGENTS.md states the CI image previously had
neither git nor make, so every `needs_git`/module-level `pytestmark` test
skipped there - this checker reads a pytest `--junit-xml` report and refuses
to let that regress unnoticed, now that `gate` installs git, jq and make.

Two independent signals, because either one alone can go blind on its own:

- PRIMARY: any testcase, anywhere in the report, whose skip message names a
  REQUIRED_TOOLS entry (case-insensitively) is a failure outright. This is
  what actually catches the regression in a MIXED file (test_profile.py,
  test_materialize.py, etc. carry both git-gated and ordinary tests side by
  side) - a file's other tests keep passing even when its gated subset
  silently skips again, so a per-file executed-count floor alone would not
  notice. Each skip reason names the tool that is actually missing (#276
  ruling): a jq-gated test says "jq", never "git".
- SECONDARY: each file in TOOL_DEPENDENT_FILES must contribute at least one
  EXECUTED (passed or failed; a skip does not count) testcase. This is the
  backstop for a file whose population vanished a DIFFERENT way (a collection
  error, the file renamed, every test in it skipped for a re-worded reason
  that no longer names its tool - the primary signal's own blind spot).

A missing or unparsable report is ALSO a failure - never read as "found no
tool skips, so nothing to report". Add a new entry to TOOL_DEPENDENT_FILES
whenever a new test module gains tool-gated tests, naming the tools it needs;
that is a visible, one-line change here, not something this checker can infer
on its own.
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET

#: The host tools the `gate` step installs, and whose absence a skip
#: message would name.
REQUIRED_TOOLS = ("git", "jq", "make")

#: Each tool-dependent test module, mapped to the tools its gated tests need.
TOOL_DEPENDENT_FILES: dict[str, tuple[str, ...]] = {
    "tests.test_degrade": ("git",),
    "tests.test_changelog_check": ("git",),
    "tests.test_provenance": ("git",),
    "tests.test_git_fixture": ("git",),
    "tests.test_profile": ("git",),
    "tests.test_materialize": ("git",),
    "tests.test_fixture_service": ("git", "jq"),
    "tests.test_fixture_service_channel": ("git", "jq"),
    "tests.test_fixture_service_inventory": ("jq",),
    # #434 revision 2: the fixture gate surface's controls (make verify per case, and the
    # lint/test/typecheck/empty-suite reds) are load-bearing for the grader revision.
    "tests.test_flow_auto_necessity_task": ("make",),
    "tests.test_makefile_pipefail_control": ("make",),
    "tests.test_level3_cicd_pipeline": ("make",),
}
assert all(set(tools) <= set(REQUIRED_TOOLS) for tools in TOOL_DEPENDENT_FILES.values())

#: Kept for readers of the #307 name; the population is TOOL_DEPENDENT_FILES.
GIT_DEPENDENT_FILES = tuple(TOOL_DEPENDENT_FILES)


def check(report_path: str) -> list[str]:
    """Every failure found, or an empty list when the report is clean.
    Raises OSError/ET.ParseError for an absent or unparseable report -
    the caller decides how to report that, since it is a different kind
    of failure from a clean parse that finds something wrong."""
    tree = ET.parse(report_path)
    executed_by_file = dict.fromkeys(TOOL_DEPENDENT_FILES, 0)
    tool_skips: dict[str, list[str]] = {tool: [] for tool in REQUIRED_TOOLS}
    for case in tree.iter("testcase"):
        classname = case.get("classname", "")
        skipped = case.find("skipped")
        if skipped is not None:
            message = (skipped.get("message") or "").lower()
            for tool in REQUIRED_TOOLS:
                # A whole word, so "digital" is not a git skip (#276 pass 3).
                if re.search(rf"\b{re.escape(tool)}\b", message):
                    tool_skips[tool].append(f"{classname}::{case.get('name')}: {skipped.get('message')}")
            continue
        for name in TOOL_DEPENDENT_FILES:
            if classname == name or classname.startswith(name + "."):
                executed_by_file[name] += 1
    failures = [
        f"zero executed (non-skipped) test from {name} - its whole population may have skipped"
        for name, count in executed_by_file.items() if count == 0
    ]
    for tool, skips in tool_skips.items():
        if skips:
            shown = skips[:5]
            more = f" (+{len(skips) - 5} more)" if len(skips) > 5 else ""
            failures.append(f"{len(skips)} test(s) skipped for a {tool}-mentioning reason: {shown}{more}")
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_git_tests_ran.py <junit-xml-report>", file=sys.stderr)
        return 2
    report_path = argv[1]
    try:
        failures = check(report_path)
    except OSError as exc:
        print(f"check-git-tests-ran: report {report_path!r} is absent or unreadable: {exc}", file=sys.stderr)
        return 1
    except ET.ParseError as exc:
        print(f"check-git-tests-ran: report {report_path!r} is not parseable XML: {exc}", file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(f"check-git-tests-ran: {failure}", file=sys.stderr)
        return 1
    print(f"check-git-tests-ran: ok - every declared file executed at least one test, no skip naming "
          f"{'/'.join(REQUIRED_TOOLS)} ({len(TOOL_DEPENDENT_FILES)} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
