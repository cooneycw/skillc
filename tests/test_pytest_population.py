"""The population gate must reject incomplete or substituted evidence (#364)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ci.check_pytest_population import check, collected, outcomes

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "controls/pytest-population"


def test_committed_complete_report_passes() -> None:
    assert "2 collected identities" in check(FIXTURES / "collected.txt", FIXTURES / "good.xml")


def test_committed_short_report_fails_even_with_a_matching_declared_count() -> None:
    with pytest.raises(ValueError, match="population mismatch"):
        check(FIXTURES / "collected.txt", FIXTURES / "short.xml")


@pytest.mark.parametrize("body", [
    "", "0 tests collected in 0.01s", "tests/test_example.py::test_pass\n",
    "tests/test_example.py::test_pass\n2 tests collected in 0.01s",
    "tests/test_example.py::test_pass\ntests/test_example.py::test_pass\n2 tests collected",
])
def test_invalid_collection_fails(tmp_path: Path, body: str) -> None:
    path = tmp_path / "collected.txt"
    path.write_text(body)
    with pytest.raises(ValueError):
        collected(path)


@pytest.mark.parametrize("body", [
    "<testsuites/>", "<anything/>",
    '<testsuite><testcase name="test_pass"/></testsuite>',
    ('<testsuite><testcase classname="tests.test_example" name="test_pass"/>'
    '<testcase classname="tests.test_example" name="test_pass"/></testsuite>'),
    ('<testsuite><testcase classname="tests.test_example" name="test_pass">'
    '<failure/><skipped/></testcase></testsuite>'),
])
def test_invalid_report_fails(tmp_path: Path, body: str) -> None:
    path = tmp_path / "report.xml"
    path.write_text(body)
    with pytest.raises(ValueError):
        outcomes(path)


def test_equal_count_wrong_identity_fails(tmp_path: Path) -> None:
    path = tmp_path / "report.xml"
    path.write_text((FIXTURES / "good.xml").read_text().replace('name="test_pass"', 'name="test_other"'))
    with pytest.raises(ValueError, match="population mismatch"):
        check(FIXTURES / "collected.txt", path)


def test_comparison_ignores_order_and_time_but_detects_changed_outcomes(tmp_path: Path) -> None:
    path = tmp_path / "report.xml"
    good = (FIXTURES / "good.xml").read_text()
    reordered = good.replace('<testcase classname="tests.test_example" name="test_pass"/>', '')
    reordered = reordered.replace('</testsuite>',
        '<testcase classname="tests.test_example" name="test_pass" time="9.9"/></testsuite>')
    path.write_text(reordered)
    assert "identical per-test outcomes" in check(FIXTURES / "collected.txt", path, FIXTURES / "good.xml")
    path.write_text(reordered.replace('type="pytest.skip"', 'type="pytest.xfail"'))
    with pytest.raises(ValueError, match="per-test outcomes differ"):
        check(FIXTURES / "collected.txt", path, FIXTURES / "good.xml")
    path.write_text(reordered.replace('name="test_pass" time="9.9"/>',
                                     'name="test_pass"><failure/></testcase>'))
    with pytest.raises(ValueError, match="per-test outcomes differ"):
        check(FIXTURES / "collected.txt", path, FIXTURES / "good.xml")


@pytest.mark.parametrize("name,body", [("absent.xml", None), ("malformed.xml", "not XML")])
def test_cli_refuses_unreadable_reports(tmp_path: Path, name: str, body: str | None) -> None:
    path = tmp_path / name
    if body is not None:
        path.write_text(body)
    result = subprocess.run([sys.executable, str(ROOT / 'ci/check_pytest_population.py'),
                             str(FIXTURES / 'collected.txt'), str(path)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "pytest-population: FAIL" in result.stderr


def test_checker_matches_real_parallel_pytest_xml(tmp_path: Path) -> None:
    """An actual pytest producer proves parameter-id mangling and skips, not just fixtures."""
    suite = tmp_path / "test_sample.py"
    suite.write_text('import pytest\nclass TestSample:\n'
                     ' @pytest.mark.parametrize("value", [1], ids=["a::b.c/d"])\n'
                     ' def test_pass(self, value): assert value == 1\n'
                     ' @pytest.mark.skip(reason="sample")\n'
                     ' def test_skip(self): pass\n')
    collection = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q'],
                                cwd=tmp_path, capture_output=True, text=True, check=True)
    (tmp_path / 'collection.txt').write_text(collection.stdout)
    subprocess.run([sys.executable, '-m', 'pytest', '-n', '2', '--dist=loadgroup',
                    '--junit-xml=report.xml'], cwd=tmp_path, capture_output=True, check=True)
    assert "2 collected identities" in check(tmp_path / 'collection.txt', tmp_path / 'report.xml')
