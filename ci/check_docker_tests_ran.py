#!/usr/bin/env python3
"""CI control (#309): fail if the docker-dependent test population silently
skipped. Every test in DOCKER_DEPENDENT_FILES is gated on a real `docker`
binary and daemon being reachable (shutil.which("docker") is None skips
it) - this checker reads a pytest `--junit-xml` report and refuses to let
that regress unnoticed, now that the docker-tests step gives those tests a
real daemon to run against. Mirrors ci/check_git_tests_ran.py's #307
pattern exactly - see that module's docstring for the full rationale.

Two independent signals, because either one alone can go blind on its own:

- PRIMARY: any testcase, anywhere in the report, whose skip message mentions
  "docker" (case-insensitively) is a failure outright. This is what would
  catch the regression in a MIXED file (none exist yet, but #266/#269 are
  expected to add one - a file with both docker-gated and ordinary tests
  side by side) - a file's other tests keep passing even when its
  docker-gated subset silently skips again, so a per-file executed-count
  floor alone would not notice.
- SECONDARY: each file in DOCKER_DEPENDENT_FILES must contribute at least
  one EXECUTED (passed or failed; a skip does not count) testcase. This is
  the backstop for a file whose population vanished a DIFFERENT way (a
  collection error, the file renamed, every test in it skipped for a
  re-worded reason that no longer mentions "docker" - the primary signal's
  own blind spot).

A missing or unparsable report is ALSO a failure - never read as "found no
docker skips, so nothing to report". Add a new entry to
DOCKER_DEPENDENT_FILES whenever #266 or #269 (or any later issue) lands a
new docker-gated test module; that is a visible, one-line change here, not
something this checker can infer on its own.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

#: Only test_decide_reply_channel_live.py exists today (#183's live
#: conformance test, 4 break modes). #266 (cold container) and #269 (real
#: exec/kill/export through the backend) are open issues that will each
#: add a docker-gated test module - add their classnames here when they
#: land, the same visible one-line change #307 itself needed.
DOCKER_DEPENDENT_FILES = (
    "tests.test_decide_reply_channel_live",
)


def check(report_path: str) -> list[str]:
    """Every failure found, or an empty list when the report is clean.
    Raises OSError/ET.ParseError for an absent or unparseable report -
    the caller decides how to report that, since it is a different kind
    of failure from a clean parse that finds something wrong."""
    tree = ET.parse(report_path)
    executed_by_file = dict.fromkeys(DOCKER_DEPENDENT_FILES, 0)
    docker_mentioning_skips: list[str] = []
    for case in tree.iter("testcase"):
        classname = case.get("classname", "")
        skipped = case.find("skipped")
        if skipped is not None:
            message = skipped.get("message") or ""
            if "docker" in message.lower():
                docker_mentioning_skips.append(f"{classname}::{case.get('name')}: {message}")
            continue
        for name in DOCKER_DEPENDENT_FILES:
            if classname == name or classname.startswith(name + "."):
                executed_by_file[name] += 1
    failures = [
        f"zero executed (non-skipped) test from {name} - its whole population may have skipped"
        for name, count in executed_by_file.items() if count == 0
    ]
    if docker_mentioning_skips:
        shown = docker_mentioning_skips[:5]
        more = f" (+{len(docker_mentioning_skips) - 5} more)" if len(docker_mentioning_skips) > 5 else ""
        failures.append(f"{len(docker_mentioning_skips)} test(s) skipped for a docker-mentioning reason: {shown}{more}")
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_docker_tests_ran.py <junit-xml-report>", file=sys.stderr)
        return 2
    report_path = argv[1]
    try:
        failures = check(report_path)
    except OSError as exc:
        print(f"check-docker-tests-ran: report {report_path!r} is absent or unreadable: {exc}", file=sys.stderr)
        return 1
    except ET.ParseError as exc:
        print(f"check-docker-tests-ran: report {report_path!r} is not parseable XML: {exc}", file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(f"check-docker-tests-ran: {failure}", file=sys.stderr)
        return 1
    print(f"check-docker-tests-ran: ok - every declared file executed at least one test, no docker-mentioning skips "
          f"({len(DOCKER_DEPENDENT_FILES)} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
