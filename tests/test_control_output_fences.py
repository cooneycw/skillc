"""The real nested pytest producer retains raw output and declares each child.

CPP compatibility is checked during development against its actual parser,
never by installing or copying that external runtime into skillc CI.
"""
from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

pattern = importlib.import_module("test_property_held_xfail_pattern")
ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/control-output-fences/cases.json").read_text())
pytest_plugins = ["pytester"]


def test_existing_producer_fences_its_actual_child() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rA",
         "tests/test_property_held_xfail_pattern.py::test_the_dedicated_exception_narrows_xfail_to_only_the_real_property"],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    begin = "::cicd-negative-control:BEGIN:BAD:marker-specific-infra::"
    end = "::cicd-negative-control:END:BAD:marker-specific-infra::"
    assert result.stdout.count(begin) == result.stdout.count(end) == 1
    segment = result.stdout.split(begin)[1].split(end)[0]
    assert "1 failed, 2 xfailed" in segment
    assert "test_b_an_infra_assertion_error_is_a_hard_failure" in segment


@pytest.mark.parametrize("case", CASES["children"], ids=lambda c: c["name"])
def test_wrapper_preserves_the_child_even_when_declaration_is_wrong(
        pytester: pytest.Pytester, case: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    pytester.makepyfile(f"def test_child():\n    assert {not case['child_fails']}\n")
    result = pattern._run_control(pytester, case["declared"], case["name"], "-q")
    result.assert_outcomes(failed=case["control_failed"], passed=case["control_passed"])
    output = capsys.readouterr()
    assert output.err == ""
    begin = f"::cicd-negative-control:BEGIN:{case['declared']}:{case['name']}::\n"
    end = f"::cicd-negative-control:END:{case['declared']}:{case['name']}::\n"
    assert output.out.startswith(begin) and output.out.endswith(end)
    assert output.out.count(begin) == output.out.count(end) == 1
    raw = output.out[len(begin):-len(end)]
    assert result.stdout.str() in raw  # unchanged content, including unexpected verdict


def test_wrapper_preserves_both_streams_and_closes_on_exception(
        capsys: pytest.CaptureFixture[str]) -> None:
    class ExplodingChild:
        def runpytest(self, *args: str) -> None:
            sys.stdout.write("stdout without final newline")
            sys.stderr.write("\nstderr still visible\n")
            raise RuntimeError("child failed before a summary")

    with pytest.raises(RuntimeError, match="before a summary"):
        pattern._run_control(ExplodingChild(), "BAD", "exception")
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (
        "::cicd-negative-control:BEGIN:BAD:exception::\n"
        "stdout without final newline\nstderr still visible\n"
        "::cicd-negative-control:END:BAD:exception::\n")


@pytest.mark.parametrize("verdict,name", [("other", "child"), ("BAD", "has:colon"),
                                          ("GOOD", "newline\nchild"), ("BAD", "")])
def test_invalid_framing_refuses_before_running(verdict: str, name: str) -> None:
    class NeverChild:
        def runpytest(self, *args: str) -> None:
            pytest.fail("invalid framing started a child")

    with pytest.raises(ValueError):
        pattern._run_control(NeverChild(), verdict, name)


def test_real_outer_failure_stays_outside_child_fence(pytester: pytest.Pytester,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    # The deliberate outer failure is captured by this test; it cannot enter the
    # main suite as an unlabelled summary on success. Its own failed assertion
    # remains outside the GOOD child's fence in the captured consumer input.
    source = ROOT / "tests/test_property_held_xfail_pattern.py"
    pytester.makeconftest("pytest_plugins = ['pytester']")
    pytester.makepyfile(f'''
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("control_producer", {str(source)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def test_outer(pytester):
    pytester.makepyfile("def test_child(): assert True")
    module._run_control(pytester, "GOOD", "outer-child", "-q")
    assert False, "real outer failure must remain visible"
''')
    console = io.StringIO()
    with redirect_stdout(console), redirect_stderr(console):
        result = pytester.runpytest("-q", "-rA")
    result.assert_outcomes(failed=1)
    stream = console.getvalue()
    end = "::cicd-negative-control:END:GOOD:outer-child::"
    assert stream.count(end) == 1
    assert "real outer failure must remain visible" in stream
    assert "1 failed" in stream.split(end)[1]
    assert capsys.readouterr().out == ""
