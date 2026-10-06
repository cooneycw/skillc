#!/usr/bin/env python3
"""CI control (#307): fail if the git-dependent test population silently
skipped. AGENTS.md states the CI image previously had neither git nor make,
so every `needs_git`/module-level `pytestmark` test skipped there - this
checker reads a pytest `--junit-xml` report and refuses to let that regress
unnoticed, now that `gate` installs git.

Two independent signals, because either one alone can go blind on its own:

- PRIMARY: any testcase, anywhere in the report, whose skip message mentions
  "git" (case-insensitively) is a failure outright. This is what actually
  catches the regression in a MIXED file (test_profile.py, test_materialize.py,
  etc. carry both git-gated and ordinary tests side by side) - a file's other
  tests keep passing even when its git-gated subset silently skips again, so
  a per-file executed-count floor alone would not notice.
- SECONDARY: each file in GIT_DEPENDENT_FILES must contribute at least one
  EXECUTED (passed or failed; a skip does not count) testcase. This is the
  backstop for a file whose population vanished a DIFFERENT way (a collection
  error, the file renamed, every test in it skipped for a re-worded reason
  that no longer mentions "git" - the primary signal's own blind spot).

A missing or unparsable report is ALSO a failure - never read as "found no
git skips, so nothing to report". Add a new entry to GIT_DEPENDENT_FILES
whenever a new test module gains git-gated tests; that is a visible,
one-line change here, not something this checker can infer on its own.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

GIT_DEPENDENT_FILES = (
    "tests.test_degrade",
    "tests.test_changelog_check",
    "tests.test_provenance",
    "tests.test_git_fixture",
    "tests.test_profile",
    "tests.test_materialize",
)


def check(report_path: str) -> list[str]:
    """Every failure found, or an empty list when the report is clean.
    Raises OSError/ET.ParseError for an absent or unparseable report -
    the caller decides how to report that, since it is a different kind
    of failure from a clean parse that finds something wrong."""
    tree = ET.parse(report_path)
    executed_by_file = dict.fromkeys(GIT_DEPENDENT_FILES, 0)
    git_mentioning_skips: list[str] = []
    for case in tree.iter("testcase"):
        classname = case.get("classname", "")
        skipped = case.find("skipped")
        if skipped is not None:
            message = skipped.get("message") or ""
            if "git" in message.lower():
                git_mentioning_skips.append(f"{classname}::{case.get('name')}: {message}")
            continue
        for name in GIT_DEPENDENT_FILES:
            if classname == name or classname.startswith(name + "."):
                executed_by_file[name] += 1
    failures = [
        f"zero executed (non-skipped) test from {name} - its whole population may have skipped"
        for name, count in executed_by_file.items() if count == 0
    ]
    if git_mentioning_skips:
        shown = git_mentioning_skips[:5]
        more = f" (+{len(git_mentioning_skips) - 5} more)" if len(git_mentioning_skips) > 5 else ""
        failures.append(f"{len(git_mentioning_skips)} test(s) skipped for a git-mentioning reason: {shown}{more}")
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
    print(f"check-git-tests-ran: ok - every declared file executed at least one test, no git-mentioning skips "
          f"({len(GIT_DEPENDENT_FILES)} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
