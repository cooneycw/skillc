#!/usr/bin/env python3
"""Verdict function for the `<agent-host>` real-Docker runner (#315). Reads a
pytest `--junit-xml` report from a `pytest -m real_docker` invocation and
decides SUCCESS / FAILURE / ERROR - never collapsing "nothing to look at"
into success, the same discipline `ci/check_git_tests_ran.py` (#307) already
applies to a different population.

PURE: a function of the report path and the declared file list, nothing
else - no network, no git, no knowledge of which SHA produced the report.
This is deliberate: the runner script (not this module) is responsible for
checking out the right commit and invoking pytest; this module only reads
what pytest already wrote down, so it is trivially testable against
constructed XML fixtures (`controls/real-docker-control/`).

Verdicts, each distinct and never standing in for another:

- ERROR   - the report is missing/unparseable, OR zero testcases anywhere
            match a declared real-Docker file. Either means the real-Docker
            population was never collected at all (wrong marker, wrong
            pytest invocation, a renamed file) - there is nothing here to
            call a result, so this is never silently read as "clean."
- FAILURE - every declared file contributed only SKIPPED testcases (the
            population was collected but never actually ran - Docker
            unreachable, or a skip condition fired on a machine that should
            have Docker), OR at least one testcase failed/errored.
- SUCCESS - every declared file contributed at least one EXECUTED (passed
            or failed) testcase, and none of them failed or errored.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

#: The real-Docker test files the runner certifies today. A new file opts in
#: by adding `@pytest.mark.real_docker` (see pyproject.toml) AND a new entry
#: here - the marker alone is not enough, because the per-file population
#: floor below is what catches a file whose whole population silently
#: vanished (renamed, every test skipped for an unrelated reason) even while
#: `pytest -m real_docker` still "succeeds" by finding nothing to complain
#: about elsewhere. A file tagged `real_docker` but absent from this tuple is
#: NOT certified: it is collected and run, but a run where it goes entirely
#: silent (skipped, renamed, erroring at collection) while every OTHER
#: declared file still passes still posts SUCCESS - the floor is what closes
#: that gap, and closing it for a given file is a deliberate, separate step
#: from tagging it (orchestrator review, #315: "every file tagged real_docker
#: that certifies something belongs in the floor"). Adding an entry here
#: means re-installing the runner from a reviewed main sha (R1) before it
#: takes effect - never implicit at the next tick.
DECLARED_REAL_DOCKER_FILES: tuple[str, ...] = (
    "tests.test_decide_reply_channel_live",
    "tests.test_trial_image_build_live",
)

ERROR = "ERROR"
FAILURE = "FAILURE"
SUCCESS = "SUCCESS"


@dataclass(frozen=True)
class Verdict:
    status: str  # ERROR | FAILURE | SUCCESS
    reason: str
    executed_by_file: dict[str, int] = field(default_factory=dict)
    failed_ids: tuple[str, ...] = ()
    skipped_only_files: tuple[str, ...] = ()


def _matches(classname: str, declared: str) -> bool:
    return classname == declared or classname.startswith(declared + ".")


def verdict(report_path: str, declared_files: tuple[str, ...] = DECLARED_REAL_DOCKER_FILES) -> Verdict:
    """Raises `OSError`/`ET.ParseError` for an absent or unparseable report -
    the caller decides how to report that (the CLI below maps both to
    `ERROR`); kept as exceptions here so a caller wanting the raw cause can
    still get it, matching `check_git_tests_ran.check`'s own contract."""
    tree = ET.parse(report_path)
    executed_by_file = dict.fromkeys(declared_files, 0)
    skipped_by_file = dict.fromkeys(declared_files, 0)
    failed_ids: list[str] = []

    any_declared_testcase = False
    for case in tree.iter("testcase"):
        classname = case.get("classname", "")
        declared = next((d for d in declared_files if _matches(classname, d)), None)
        if declared is None:
            continue
        any_declared_testcase = True
        name = case.get("name", "")
        if case.find("skipped") is not None:
            skipped_by_file[declared] += 1
            continue
        executed_by_file[declared] += 1
        if case.find("failure") is not None or case.find("error") is not None:
            failed_ids.append(f"{classname}::{name}")

    if not any_declared_testcase:
        return Verdict(
            status=ERROR,
            reason=f"zero testcases matched any declared real-Docker file {declared_files} - "
                   f"the real-Docker population was not collected at all",
        )

    skipped_only_files = tuple(
        name for name in declared_files
        if executed_by_file[name] == 0 and skipped_by_file[name] > 0
    )
    if skipped_only_files:
        return Verdict(
            status=FAILURE,
            reason=f"declared file(s) {skipped_only_files} collected only SKIPPED testcases - "
                   f"the real-Docker set never actually executed",
            executed_by_file=executed_by_file,
            skipped_only_files=skipped_only_files,
        )

    if failed_ids:
        return Verdict(
            status=FAILURE,
            reason=f"{len(failed_ids)} real-Docker testcase(s) failed or errored",
            executed_by_file=executed_by_file,
            failed_ids=tuple(failed_ids),
        )

    zero_executed = tuple(name for name, count in executed_by_file.items() if count == 0)
    if zero_executed:
        # A declared file with NEITHER a skip nor an execution recorded at
        # all (not even attempted - e.g. a collection error pytest itself
        # reported some other way). Distinct from the "collected only
        # skips" case above, and still never a silent success.
        return Verdict(
            status=ERROR,
            reason=f"declared file(s) {zero_executed} contributed zero testcases of any kind",
            executed_by_file=executed_by_file,
        )

    return Verdict(
        status=SUCCESS,
        reason="every declared real-Docker file executed at least one test, no failures",
        executed_by_file=executed_by_file,
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_real_docker_ran.py <junit-xml-report>", file=sys.stderr)
        return 2
    report_path = argv[1]
    try:
        result = verdict(report_path)
    except OSError as exc:
        print(f"check-real-docker-ran: ERROR: report {report_path!r} is absent or unreadable: {exc}",
              file=sys.stderr)
        return 1
    except ET.ParseError as exc:
        print(f"check-real-docker-ran: ERROR: report {report_path!r} is not parseable XML: {exc}",
              file=sys.stderr)
        return 1

    print(f"check-real-docker-ran: {result.status}: {result.reason}")
    return {SUCCESS: 0, FAILURE: 1, ERROR: 2}[result.status]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
