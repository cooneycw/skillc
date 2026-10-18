"""#456: the certifying runner's floor against the tested commit's floor.

The installed runner's `DECLARED_REAL_DOCKER_FILES` is the instrument; the
tested commit's list is subject-provided data, read by `ast` and never
imported. It may only ADD a signal (RUNNER_BEHIND) - a shorter list must
never weaken the runner's floor, and an unreadable one fails closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ci import check_real_docker_ran as c
from ci import real_docker_post as p

SHA, RUNNER_SHA = "a" * 40, "b" * 40
RUNNER_FLOOR = c.DECLARED_REAL_DOCKER_FILES
NEW = "tests.test_brand_new_live"
PROFILE = "tests.test_cicd_profile_live"


def _report(tmp_path: Path, *, skipped_only: tuple[str, ...] = (), failed: tuple[str, ...] = (),
            extra: tuple[str, ...] = ()) -> str:
    cases = []
    for name in (*RUNNER_FLOOR, *extra):
        if name in skipped_only:
            cases.append(f'<testcase classname="{name}" name="t"><skipped message="no daemon"/></testcase>')
        elif name in failed:
            cases.append(f'<testcase classname="{name}" name="t"><failure message="boom"/></testcase>')
        else:
            cases.append(f'<testcase classname="{name}" name="t"/>')
    path = tmp_path / "report.xml"
    path.write_text("<testsuite>" + "".join(cases) + "</testsuite>", encoding="utf-8")
    return str(path)


def _checkout(tmp_path: Path, body: str) -> str:
    (tmp_path / "checkout" / "ci").mkdir(parents=True, exist_ok=True)
    (tmp_path / "checkout" / "ci" / "check_real_docker_ran.py").write_text(body, encoding="utf-8")
    return str(tmp_path / "checkout")


def _floor_file(names: tuple[str, ...]) -> str:
    return "DECLARED_REAL_DOCKER_FILES: tuple[str, ...] = (\n" + "".join(f'    "{n}",\n' for n in names) + ")\n"


def test_identical_floors_report_exactly_as_without_the_check(tmp_path: Path) -> None:
    report = _report(tmp_path)
    plain = p.compute(report, sha=SHA, runner_sha=RUNNER_SHA)
    checked = p.compute(report, sha=SHA, runner_sha=RUNNER_SHA, checkout=_checkout(tmp_path, _floor_file(RUNNER_FLOOR)))
    assert checked.status == c.SUCCESS and not checked.uncounted_files and not checked.dropped_by_commit
    assert p.render(checked, sha=SHA, runner_sha=RUNNER_SHA) == p.render(plain, sha=SHA, runner_sha=RUNNER_SHA)


def test_a_commit_declaring_a_file_the_runner_does_not_count_is_runner_behind(tmp_path: Path) -> None:
    """RED: the exact #280 situation - the new file ran and passed, but this
    runner's floor does not count it, so the run is not certified SUCCESS."""
    report = _report(tmp_path, extra=(NEW,))
    checkout = _checkout(tmp_path, _floor_file((*RUNNER_FLOOR, NEW)))
    result = p.compute(report, sha=SHA, runner_sha=RUNNER_SHA, checkout=checkout)
    assert result.status == c.RUNNER_BEHIND and result.uncounted_files == (NEW,)
    text = p.render(result, sha=SHA, runner_sha=RUNNER_SHA)
    assert "re-pin, then re-seed state to the parent" in text.splitlines()[1]
    assert f"`{NEW}`" in text
    assert p.main(["real_docker_post.py", report, SHA, RUNNER_SHA, checkout]) == 4


def test_a_real_failure_outranks_runner_behind(tmp_path: Path) -> None:
    report = _report(tmp_path, failed=(PROFILE,), extra=(NEW,))
    result = p.compute(report, sha=SHA, runner_sha=RUNNER_SHA,
                       checkout=_checkout(tmp_path, _floor_file((*RUNNER_FLOOR, NEW))))
    assert result.status == c.FAILURE and result.uncounted_files == (NEW,)
    assert f"`{NEW}`" in p.render(result, sha=SHA, runner_sha=RUNNER_SHA)


def test_an_error_is_never_touched(tmp_path: Path) -> None:
    result = p.compute(str(tmp_path / "missing.xml"), sha=SHA, runner_sha=RUNNER_SHA,
                       checkout=_checkout(tmp_path, _floor_file((*RUNNER_FLOOR, NEW))))
    assert result.status == c.ERROR


def test_a_shorter_commit_list_cannot_weaken_the_runner_floor(tmp_path: Path) -> None:
    """The commit drops PROFILE from its list. If PROFILE then only skips,
    the runner's floor still makes it FAILURE; if it passes, SUCCESS, with
    the omission reported only for information."""
    shorter = _checkout(tmp_path, _floor_file(tuple(n for n in RUNNER_FLOOR if n != PROFILE)))
    silent = p.compute(_report(tmp_path, skipped_only=(PROFILE,)), sha=SHA, runner_sha=RUNNER_SHA, checkout=shorter)
    assert silent.status == c.FAILURE and silent.skipped_only_files == (PROFILE,)
    ran = p.compute(_report(tmp_path), sha=SHA, runner_sha=RUNNER_SHA, checkout=shorter)
    assert ran.status == c.SUCCESS and ran.dropped_by_commit == (PROFILE,)


def test_control_using_the_commit_list_as_the_floor_would_be_weakened(tmp_path: Path) -> None:
    """The design the case above distinguishes against: treating the
    commit's list as the floor reads the silent PROFILE run as SUCCESS."""
    commit_floor = tuple(n for n in RUNNER_FLOOR if n != PROFILE)
    mutant = c.verdict(_report(tmp_path, skipped_only=(PROFILE,)), declared_files=commit_floor)
    assert mutant.status == c.SUCCESS


@pytest.mark.parametrize("body", [
    None,                                                          # no floor file at all
    "def f(): pass\n",                                             # no assignment
    "DECLARED_REAL_DOCKER_FILES = tuple(open('x'))\n",             # not a literal
    'DECLARED_REAL_DOCKER_FILES = ("tests.test_a_live", 3)\n',     # non-string element
    _floor_file(RUNNER_FLOOR) + _floor_file(RUNNER_FLOOR),         # assigned twice
    'DECLARED_REAL_DOCKER_FILES = ("tests.test_a_live", "tests.test_a_live")\n',  # repeated
    'DECLARED_REAL_DOCKER_FILES = ("tests.test_a_live", "/etc/passwd")\n',        # malformed entry
    'DECLARED_REAL_DOCKER_FILES = ("`danger`",)\n',
    "DECLARED_REAL_DOCKER_FILES = (\n",                            # syntax error
    # Counter-model review: a later write would change the floor the reader reports.
    _floor_file(RUNNER_FLOOR) + 'DECLARED_REAL_DOCKER_FILES += ("tests.test_brand_new_live",)\n',
    _floor_file(RUNNER_FLOOR) + 'if True:\n    DECLARED_REAL_DOCKER_FILES = ("tests.test_a_live",)\n',
    _floor_file(RUNNER_FLOOR) + 'def f():\n    global DECLARED_REAL_DOCKER_FILES\n'
                                '    DECLARED_REAL_DOCKER_FILES = ()\n',
    _floor_file(RUNNER_FLOOR) + "del DECLARED_REAL_DOCKER_FILES\n",
    'DECLARED_REAL_DOCKER_FILES = ["tests.test_a_live"]\n',     # a list could be mutated later
    # Second review: bindings that are not a Name(Store).
    _floor_file(RUNNER_FLOOR) + "from new_floors import DECLARED_REAL_DOCKER_FILES\n",
    _floor_file(RUNNER_FLOOR) + "import new_floors as DECLARED_REAL_DOCKER_FILES\n",
    _floor_file(RUNNER_FLOOR) + "def DECLARED_REAL_DOCKER_FILES(): pass\n",
    _floor_file(RUNNER_FLOOR) + "for DECLARED_REAL_DOCKER_FILES in [()]: pass\n",
    _floor_file(RUNNER_FLOOR) + "try:\n    pass\nexcept Exception as DECLARED_REAL_DOCKER_FILES:\n    pass\n",
    _floor_file(RUNNER_FLOOR) + "[(DECLARED_REAL_DOCKER_FILES := ()) for _ in [0]]\n",
    'DECLARED_REAL_DOCKER_FILES = ("tests.test_a\nlive",)\n',  # newline in an entry
])
def test_an_unreadable_commit_floor_fails_closed(tmp_path: Path, body: str | None) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    if body is not None:
        _checkout(tmp_path, body)
    result = p.compute(_report(tmp_path), sha=SHA, runner_sha=RUNNER_SHA, checkout=str(checkout))
    assert result.status == c.ERROR and "cannot read the tested commit's floor" in result.reason


def test_a_same_named_local_is_not_the_floor(tmp_path: Path) -> None:
    """Second review: a function-local or class attribute of the same name
    does not change the module floor, so it must not read as unreadable."""
    body = (_floor_file((*RUNNER_FLOOR, NEW))
            + "def helper():\n    DECLARED_REAL_DOCKER_FILES = ()\n    return DECLARED_REAL_DOCKER_FILES\n"
            + "class K:\n    DECLARED_REAL_DOCKER_FILES = ()\n"
            + "x = [DECLARED_REAL_DOCKER_FILES for DECLARED_REAL_DOCKER_FILES in [()]]\n")
    assert p.read_commit_floor(_checkout(tmp_path, body)) == (*RUNNER_FLOOR, NEW)


def test_the_reader_never_executes_the_commit(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    checkout = _checkout(tmp_path, f"open({str(marker)!r}, 'w').write('ran')\n" + _floor_file((*RUNNER_FLOOR, NEW)))
    assert p.read_commit_floor(checkout) == (*RUNNER_FLOOR, NEW)
    assert not marker.exists()


def test_the_runner_floor_file_itself_reads_back_as_the_runner_floor() -> None:
    """The real file's literal shape is one this reader accepts."""
    assert p.read_commit_floor(Path(__file__).resolve().parent.parent) == RUNNER_FLOOR


def test_a_control_run_without_a_checkout_skips_the_check(tmp_path: Path) -> None:
    report = _report(tmp_path, extra=(NEW,))
    assert p.compute(report, sha=SHA, runner_sha=RUNNER_SHA).status == c.SUCCESS
    assert p.main(["real_docker_post.py", report, SHA, RUNNER_SHA, ""]) == 0
