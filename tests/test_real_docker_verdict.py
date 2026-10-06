"""Tests for `ci/check_real_docker_ran.py` (#315): the pure verdict function
over a `pytest -m real_docker --junit-xml=...` report.

Every case constructs its own minimal JUnit XML rather than relying on a
real pytest run having produced one - the whole point of `verdict()` being
pure is that these can be written down directly."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ci import check_real_docker_ran as c

DECLARED = ("tests.test_decide_reply_channel_live",)


def _write(tmp_path: Path, name: str, xml: str) -> str:
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return str(path)


_PASS_CASE = (
    '<testcase classname="tests.test_decide_reply_channel_live" '
    'name="test_round_trip" time="1.0"></testcase>'
)
_SKIP_CASE = (
    '<testcase classname="tests.test_decide_reply_channel_live" '
    'name="test_round_trip" time="0.01">'
    '<skipped message="no docker binary in this environment"/></testcase>'
)
_FAIL_CASE = (
    '<testcase classname="tests.test_decide_reply_channel_live" '
    'name="test_round_trip" time="1.0">'
    '<failure message="identity check failed">traceback here</failure></testcase>'
)
_UNRELATED_CASE = (
    '<testcase classname="tests.test_calibration" name="test_something" time="0.1"></testcase>'
)


def _suite(*cases: str) -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{"".join(cases)}</testsuite></testsuites>'


def test_a_missing_report_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        c.verdict(str(tmp_path / "does-not-exist.xml"))


def test_a_malformed_report_raises_parse_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "malformed.xml", "not xml at all <<<")
    with pytest.raises(ET.ParseError):
        c.verdict(path)


def test_zero_matching_testcases_is_error(tmp_path: Path) -> None:
    """Red case: a report that only has UNRELATED tests (the real-Docker
    marker/invocation was wrong, or the file got renamed) must never read
    as a clean, empty success."""
    path = _write(tmp_path, "unrelated.xml", _suite(_UNRELATED_CASE))
    result = c.verdict(path, DECLARED)
    assert result.status == c.ERROR
    assert "not collected at all" in result.reason


def test_an_empty_report_is_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "empty.xml", _suite())
    result = c.verdict(path, DECLARED)
    assert result.status == c.ERROR


def test_all_skipped_is_failure_not_success(tmp_path: Path) -> None:
    """The central claim of #315's verdict design: a population that was
    COLLECTED but never actually ran (Docker unreachable on a machine that
    should have it) must be FAILURE, never SUCCESS."""
    path = _write(tmp_path, "all-skipped.xml", _suite(_SKIP_CASE))
    result = c.verdict(path, DECLARED)
    assert result.status == c.FAILURE
    assert result.skipped_only_files == DECLARED


def test_a_real_failure_is_failure(tmp_path: Path) -> None:
    path = _write(tmp_path, "one-failure.xml", _suite(_FAIL_CASE))
    result = c.verdict(path, DECLARED)
    assert result.status == c.FAILURE
    assert result.failed_ids == ("tests.test_decide_reply_channel_live::test_round_trip",)


def test_a_clean_pass_is_success(tmp_path: Path) -> None:
    path = _write(tmp_path, "good.xml", _suite(_PASS_CASE))
    result = c.verdict(path, DECLARED)
    assert result.status == c.SUCCESS
    assert result.executed_by_file[DECLARED[0]] == 1


_IMAGE_BUILD_SKIP_CASE = (
    '<testcase classname="tests.test_trial_image_build_live" '
    'name="test_image_runs_as_candidate" time="0.02">'
    '<skipped message="no reachable Docker daemon"/></testcase>'
)


def test_live_channel_passes_but_image_build_all_skipped_is_failure() -> None:
    """Orchestrator review, #315: with BOTH files in the real floor
    (`DECLARED_REAL_DOCKER_FILES`), a run where #183's live-channel file
    executes and passes but the image-build file collected only SKIPs must
    give FAILURE, not SUCCESS - green on the VM with no image evidence is
    exactly what the per-file floor exists to refuse. Uses the module's
    OWN default declared-files tuple (not the local 1-file `DECLARED`), so
    this exercises the real, currently-shipped floor."""
    assert c.DECLARED_REAL_DOCKER_FILES == (
        "tests.test_decide_reply_channel_live",
        "tests.test_trial_image_build_live",
    ), "this test assumes the current two-file floor - update it if the floor changes"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td), "mixed.xml", _suite(_PASS_CASE, _IMAGE_BUILD_SKIP_CASE))
        result = c.verdict(path)  # module default: both files
        assert result.status == c.FAILURE
        assert result.skipped_only_files == ("tests.test_trial_image_build_live",)


def test_a_second_declared_file_with_nothing_at_all_is_error(tmp_path: Path) -> None:
    """Two declared files, only one of which contributed ANY testcase - the
    silent-renamed-file case, distinct from the all-skipped case above."""
    declared = ("tests.test_decide_reply_channel_live", "tests.test_some_future_real_docker_file")
    path = _write(tmp_path, "one-missing.xml", _suite(_PASS_CASE))
    result = c.verdict(path, declared)
    assert result.status == c.ERROR
    assert "tests.test_some_future_real_docker_file" in result.reason


def test_red_case_a_verdict_function_that_ignores_all_skipped_would_miss_this() -> None:
    """Mutation check: a plausible-but-wrong verdict function that only
    checks `executed_by_file` for a floor (like #307's SECONDARY signal
    alone, with no content check) would call the all-skipped case ERROR
    (zero executed) - which this suite's own `test_all_skipped_is_failure_
    not_success` asserts is FAILURE, not ERROR. The two must disagree, or
    this suite is not actually distinguishing the two verdicts."""

    def floor_only_verdict(report_path: str, declared_files: tuple[str, ...] = DECLARED) -> str:
        tree = ET.parse(report_path)
        executed = dict.fromkeys(declared_files, 0)
        for case in tree.iter("testcase"):
            classname = case.get("classname", "")
            if classname in declared_files and case.find("skipped") is None:
                executed[classname] += 1
        return c.ERROR if any(v == 0 for v in executed.values()) else c.SUCCESS

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td), "all-skipped.xml", _suite(_SKIP_CASE))
        correct = c.verdict(path, DECLARED).status
        mutated = floor_only_verdict(path, DECLARED)
        assert correct == c.FAILURE
        assert mutated != correct, "the floor-only mutation accidentally agrees - this red case is inert"
