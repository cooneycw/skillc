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


@pytest.mark.parametrize(("skip_type", "expected"), [
    ("pytest.xfail", c.FAILURE),
    ("pytest.skip", c.SUCCESS),
    ("", c.SUCCESS),
])
def test_a_targeted_xfail_is_not_hidden_by_passing_siblings(
    tmp_path: Path, skip_type: str, expected: str,
) -> None:
    """#343's no-uv control: other tool probes still pass in the same file.

    Ordinary partial skips retain the existing per-file-floor semantics;
    this verdict never claims every individual property was demonstrated.
    """
    passed = [
        f'<testcase classname="{name}" name="test_intact"/>'
        for name in c.DECLARED_REAL_DOCKER_FILES
    ]
    target = "tests.test_trial_image_tools_live"
    failed = (
        f'<testcase classname="{target}" name="test_uv_is_present_at_the_pinned_version">'
        f'<skipped type="{skip_type}" message="no-uv control"/></testcase>'
    )
    result = c.verdict(_write(tmp_path, "mixed-control.xml", _suite(*passed, failed)))
    assert result.status == expected
    if skip_type == "pytest.xfail":
        assert result.failed_ids == (f"{target}::test_uv_is_present_at_the_pinned_version",)
    else:
        assert result.failed_ids == ()
        assert result.executed_by_file[target] == 1


def test_xfail_outside_the_declared_population_does_not_change_its_verdict(tmp_path: Path) -> None:
    xml = _suite(
        _PASS_CASE,
        '<testcase classname="tests.other" name="test_other">'
        '<skipped type="pytest.xfail"/></testcase>',
    )
    assert c.verdict(_write(tmp_path, "other-xfail.xml", xml), DECLARED).status == c.SUCCESS


@pytest.mark.parametrize("failure", [
    '<failure message="[XPASS(strict)] control unexpectedly passed"/>',
    '<error message="setup failed before the intended property"/>',
])
def test_strict_xpass_and_setup_errors_remain_hard_failures(tmp_path: Path, failure: str) -> None:
    xml = _suite(
        _PASS_CASE,
        f'<testcase classname="{DECLARED[0]}" name="test_control">{failure}</testcase>',
    )
    result = c.verdict(_write(tmp_path, "hard-failure.xml", xml), DECLARED)
    assert result.status == c.FAILURE
    assert result.failed_ids == (f"{DECLARED[0]}::test_control",)


_IMAGE_BUILD_PASS_CASE = (
    '<testcase classname="tests.test_trial_image_build_live" '
    'name="test_image_runs_as_candidate" time="5.0"></testcase>'
)
_GATE_WITNESS_SKIP_CASE = (
    '<testcase classname="tests.test_gate_witness_live" '
    'name="test_the_gate_witness_round_trips_correctly_against_a_real_daemon" time="0.02">'
    '<skipped message="no reachable Docker daemon in this environment"/></testcase>'
)
_GATE_WITNESS_PASS_CASE = (
    '<testcase classname="tests.test_gate_witness_live" '
    'name="test_the_gate_witness_round_trips_correctly_against_a_real_daemon" time="4.0">'
    '</testcase>'
)
_GATE_OVERLAY_PASS_CASE = (
    '<testcase classname="tests.test_gate_overlay_live" '
    'name="test_the_shim_forwards_the_controllers_real_result_against_a_real_daemon" time="3.0">'
    '</testcase>'
)
_GATE_OVERLAY_SKIP_CASE = (
    '<testcase classname="tests.test_gate_overlay_live" '
    'name="test_the_shim_forwards_the_controllers_real_result_against_a_real_daemon" time="0.02">'
    '<skipped message="no reachable Docker daemon in this environment"/></testcase>'
)
#: #266: the cold-container-install proof's own floor entry.
_COLDINSTALL_PASS_CASE = (
    '<testcase classname="tests.test_profile_install_cold_container_live" '
    'name="test_profile_runs_cold_with_no_operator_mounts" time="8.0"></testcase>'
)
_COLDINSTALL_SKIP_CASE = (
    '<testcase classname="tests.test_profile_install_cold_container_live" '
    'name="test_profile_runs_cold_with_no_operator_mounts" time="0.02">'
    '<skipped message="no reachable Docker daemon in this environment"/></testcase>'
)
#: #343: the trial-image tool-probe proof's own floor entry.
_IMAGE_TOOLS_PASS_CASE = (
    '<testcase classname="tests.test_trial_image_tools_live" '
    'name="test_uv_is_present_at_the_pinned_version" time="4.0"></testcase>'
)
_IMAGE_TOOLS_SKIP_CASE = (
    '<testcase classname="tests.test_trial_image_tools_live" '
    'name="test_uv_is_present_at_the_pinned_version" time="0.02">'
    '<skipped message="no reachable Docker daemon in this environment"/></testcase>'
)
#: #334: the installed-closure/gate-reaches-real-runner proof's own floor entry.
_CLOSURE_PREFLIGHT_PASS_CASE = (
    '<testcase classname="tests.test_profile_closure_preflight_live" '
    'name="test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner" time="9.0">'
    '</testcase>'
)
_CLOSURE_PREFLIGHT_SKIP_CASE = (
    '<testcase classname="tests.test_profile_closure_preflight_live" '
    'name="test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner" time="0.02">'
    '<skipped message="no reachable Docker daemon in this environment"/></testcase>'
)

#: #338: the cwd-confinement proof's own floor entry.
_CWD_CONFINEMENT_PASS_CASE = (
    '<testcase classname="tests.test_cwd_confinement_live" '
    'name="test_a_swapped_cwd_is_refused_against_a_real_daemon" time="5.0"></testcase>'
)
_CWD_CONFINEMENT_SKIP_CASE = (
    '<testcase classname="tests.test_cwd_confinement_live" '
    'name="test_a_swapped_cwd_is_refused_against_a_real_daemon" time="0.02">'
    '<skipped message="no reachable Docker daemon in this environment"/></testcase>'
)

#: #393: the nested-directory ownership proof's own floor entry.
_NESTED_DIRS_PASS_CASE = (
    '<testcase classname="tests.test_install_nested_dirs_live" '
    'name="test_the_candidate_can_create_files_in_installed_nested_directories" time="2.0"></testcase>'
)
_NESTED_DIRS_SKIP_CASE = (
    '<testcase classname="tests.test_install_nested_dirs_live" '
    'name="test_the_candidate_can_create_files_in_installed_nested_directories" time="0.02">'
    '<skipped message="no reachable Docker daemon in this environment"/></testcase>'
)

_NINE_FILE_FLOOR = (
    "tests.test_decide_reply_channel_live",
    "tests.test_trial_image_build_live",
    "tests.test_gate_witness_live",
    "tests.test_gate_overlay_live",
    "tests.test_profile_install_cold_container_live",
    "tests.test_trial_image_tools_live",
    "tests.test_profile_closure_preflight_live",
    "tests.test_cwd_confinement_live",
    "tests.test_install_nested_dirs_live",
)


def test_the_other_eight_floor_files_pass_but_gate_witness_all_skipped_is_failure() -> None:
    """Orchestrator review, #269/#315: with all NINE files in the real
    floor (`DECLARED_REAL_DOCKER_FILES`), a run where every OTHER declared
    file executes and passes but #269's gate-witness file collected only a
    SKIP must give FAILURE, not SUCCESS - green on the VM with no
    gate-witness evidence is exactly what the per-file floor exists to
    refuse. Uses the module's OWN default declared-files tuple (not the
    local 1-file `DECLARED`), so this exercises the real, currently-shipped
    floor - and pins its current size, so a future addition that forgets to
    extend this test's fixtures is caught here (as a missing-testcase ERROR,
    not a silent FAILURE/SUCCESS misread) rather than passing by accident."""
    assert c.DECLARED_REAL_DOCKER_FILES == _NINE_FILE_FLOOR, \
        "this test assumes the current nine-file floor - update it if the floor changes"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td), "mixed.xml",
            _suite(
                _PASS_CASE, _IMAGE_BUILD_PASS_CASE, _GATE_OVERLAY_PASS_CASE,
                _GATE_WITNESS_SKIP_CASE, _COLDINSTALL_PASS_CASE,
                _IMAGE_TOOLS_PASS_CASE, _CLOSURE_PREFLIGHT_PASS_CASE,
                _CWD_CONFINEMENT_PASS_CASE, _NESTED_DIRS_PASS_CASE,
            ),
        )
        result = c.verdict(path)  # module default: all nine files
        assert result.status == c.FAILURE
        assert result.skipped_only_files == ("tests.test_gate_witness_live",)


def test_gate_overlay_live_going_all_skipped_is_also_failure_not_success() -> None:
    """The SAME per-file floor property, demonstrated for the file this
    test module's own fixtures just added (#332) rather than assumed to
    extend automatically from the gate-witness case above - every other
    declared file executes and passes; only the new entry goes silent."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td), "mixed.xml",
            _suite(_PASS_CASE, _IMAGE_BUILD_PASS_CASE, _GATE_OVERLAY_SKIP_CASE),
        )
        result = c.verdict(
            path,
            (
                "tests.test_decide_reply_channel_live",
                "tests.test_trial_image_build_live",
                "tests.test_gate_overlay_live",
            ),
        )
        assert result.status == c.FAILURE
        assert result.skipped_only_files == ("tests.test_gate_overlay_live",)


def test_the_other_eight_floor_files_pass_but_coldinstall_all_skipped_is_failure() -> None:
    """#266's own red case, same shape as the gate-witness one above but
    with the roles reversed: the cold-container-install proof collecting
    only a SKIP (Docker unreachable, or a skip condition firing on a
    machine that should have it) while every OTHER declared file passes
    must give FAILURE, never SUCCESS - a skip counts as failure for a
    floor file, by design."""
    assert c.DECLARED_REAL_DOCKER_FILES == _NINE_FILE_FLOOR, \
        "this test assumes the current nine-file floor - update it if the floor changes"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td), "mixed.xml",
            _suite(
                _PASS_CASE, _IMAGE_BUILD_PASS_CASE, _GATE_WITNESS_PASS_CASE,
                _GATE_OVERLAY_PASS_CASE, _COLDINSTALL_SKIP_CASE,
                _IMAGE_TOOLS_PASS_CASE, _CLOSURE_PREFLIGHT_PASS_CASE,
                _CWD_CONFINEMENT_PASS_CASE, _NESTED_DIRS_PASS_CASE,
            ),
        )
        result = c.verdict(path)  # module default: all nine files
        assert result.status == c.FAILURE
        assert result.skipped_only_files == ("tests.test_profile_install_cold_container_live",)


def test_the_other_eight_floor_files_pass_but_trial_image_tools_all_skipped_is_failure() -> None:
    """The SAME per-file floor property for #343's own new entry: every
    other declared file executes and passes; only the trial-image
    tool-probe file goes silent (no reachable Docker daemon)."""
    assert c.DECLARED_REAL_DOCKER_FILES == _NINE_FILE_FLOOR, \
        "this test assumes the current nine-file floor - update it if the floor changes"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td), "mixed.xml",
            _suite(
                _PASS_CASE, _IMAGE_BUILD_PASS_CASE, _GATE_WITNESS_PASS_CASE,
                _GATE_OVERLAY_PASS_CASE, _COLDINSTALL_PASS_CASE,
                _IMAGE_TOOLS_SKIP_CASE, _CLOSURE_PREFLIGHT_PASS_CASE,
                _CWD_CONFINEMENT_PASS_CASE, _NESTED_DIRS_PASS_CASE,
            ),
        )
        result = c.verdict(path)  # module default: all nine files
        assert result.status == c.FAILURE
        assert result.skipped_only_files == ("tests.test_trial_image_tools_live",)


def test_the_other_eight_floor_files_pass_but_closure_preflight_all_skipped_is_failure() -> None:
    """#334's own red case, same shape as the ones above but for the file
    this test module's own fixtures just added - every other declared
    file executes and passes; only the new entry goes silent."""
    assert c.DECLARED_REAL_DOCKER_FILES == _NINE_FILE_FLOOR, \
        "this test assumes the current nine-file floor - update it if the floor changes"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td), "mixed.xml",
            _suite(
                _PASS_CASE, _IMAGE_BUILD_PASS_CASE, _GATE_WITNESS_PASS_CASE,
                _GATE_OVERLAY_PASS_CASE, _COLDINSTALL_PASS_CASE,
                _IMAGE_TOOLS_PASS_CASE, _CLOSURE_PREFLIGHT_SKIP_CASE,
                _CWD_CONFINEMENT_PASS_CASE, _NESTED_DIRS_PASS_CASE,
            ),
        )
        result = c.verdict(path)  # module default: all nine files
        assert result.status == c.FAILURE
        assert result.skipped_only_files == ("tests.test_profile_closure_preflight_live",)


def test_the_other_eight_floor_files_pass_but_cwd_confinement_all_skipped_is_failure() -> None:
    """#338's own red case: every other declared file executes and passes;
    only the cwd-confinement proof goes silent (no reachable Docker
    daemon). Before this entry joined the floor, this exact report read
    SUCCESS - the file was tagged `real_docker` but never certified."""
    assert c.DECLARED_REAL_DOCKER_FILES == _NINE_FILE_FLOOR, \
        "this test assumes the current nine-file floor - update it if the floor changes"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td), "mixed.xml",
            _suite(
                _PASS_CASE, _IMAGE_BUILD_PASS_CASE, _GATE_WITNESS_PASS_CASE,
                _GATE_OVERLAY_PASS_CASE, _COLDINSTALL_PASS_CASE,
                _IMAGE_TOOLS_PASS_CASE, _CLOSURE_PREFLIGHT_PASS_CASE,
                _CWD_CONFINEMENT_SKIP_CASE, _NESTED_DIRS_PASS_CASE,
            ),
        )
        result = c.verdict(path)  # module default: all nine files
        assert result.status == c.FAILURE
        assert result.skipped_only_files == ("tests.test_cwd_confinement_live",)


def test_the_other_eight_floor_files_pass_but_nested_dirs_all_skipped_is_failure() -> None:
    """#393's own red case: every other declared file executes and passes;
    only the nested-directory ownership proof goes silent. Before this entry
    joined the floor, this exact report read SUCCESS (counter-model review:
    the file was tagged `real_docker` but never certified)."""
    assert c.DECLARED_REAL_DOCKER_FILES == _NINE_FILE_FLOOR, \
        "this test assumes the current nine-file floor - update it if the floor changes"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = _write(
            Path(td), "mixed.xml",
            _suite(
                _PASS_CASE, _IMAGE_BUILD_PASS_CASE, _GATE_WITNESS_PASS_CASE,
                _GATE_OVERLAY_PASS_CASE, _COLDINSTALL_PASS_CASE,
                _IMAGE_TOOLS_PASS_CASE, _CLOSURE_PREFLIGHT_PASS_CASE,
                _CWD_CONFINEMENT_PASS_CASE, _NESTED_DIRS_SKIP_CASE,
            ),
        )
        result = c.verdict(path)  # module default: all nine files
        assert result.status == c.FAILURE
        assert result.skipped_only_files == ("tests.test_install_nested_dirs_live",)
        failing = _write(
            Path(td), "failing.xml",
            _suite(
                _PASS_CASE, _IMAGE_BUILD_PASS_CASE, _GATE_WITNESS_PASS_CASE,
                _GATE_OVERLAY_PASS_CASE, _COLDINSTALL_PASS_CASE,
                _IMAGE_TOOLS_PASS_CASE, _CLOSURE_PREFLIGHT_PASS_CASE,
                _CWD_CONFINEMENT_PASS_CASE,
                '<testcase classname="tests.test_install_nested_dirs_live" '
                'name="test_the_candidate_can_create_files_in_installed_nested_directories" time="1.0">'
                '<failure message="Permission denied"/></testcase>',
            ),
        )
        assert c.verdict(failing).status == c.FAILURE
        passing = _write(
            Path(td), "passing.xml",
            _suite(
                _PASS_CASE, _IMAGE_BUILD_PASS_CASE, _GATE_WITNESS_PASS_CASE,
                _GATE_OVERLAY_PASS_CASE, _COLDINSTALL_PASS_CASE,
                _IMAGE_TOOLS_PASS_CASE, _CLOSURE_PREFLIGHT_PASS_CASE,
                _CWD_CONFINEMENT_PASS_CASE, _NESTED_DIRS_PASS_CASE,
            ),
        )
        assert c.verdict(passing).status == c.SUCCESS


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
