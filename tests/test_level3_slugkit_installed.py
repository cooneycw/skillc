"""Tests for the Level 3 slugkit-installed task and its grader (#13).

Mirrors `tests/test_level1_slug.py`'s own wiring for `qualify.py`. The
`real_pip_mode` tests below additionally port `check_real_pip_mode.py`'s
four assertions into the suite - a standalone script nothing invokes is an
instrument no gate runs, so the real-pip branch would have no CI-visible
green or red (review note on #13) - and add a committed red case: a
one-line mutation of `probe.py`'s copy that forces the mode-switch off, and
the "fake pip selects real-pip" assertion must then fail, proving the
ordinary test above is not vacuously green.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

TASK = Path(__file__).resolve().parent.parent / "evals" / "level3" / "slugkit-installed"
FAKE_PIP_DIR = TASK / "fixtures" / "fake-pip"
INPUTS = json.loads((TASK / "inputs.json").read_text(encoding="utf-8"))


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level3_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("qualify")
grade_slugkit = _load("grade_slugkit")


def _outcomes(candidate: Path, timeout: float = 30) -> dict[str, str]:
    result = grade_slugkit.grade(candidate, timeout)
    return {c["id"]: c["outcome"] for c in result["criteria"]}


def test_the_grader_is_certified() -> None:
    certified, rows = qualify.certify(TASK / "grade_slugkit.py")
    assert certified, [r for r in rows if not r.ok]
    by_name = {r.candidate: r.status for r in rows}
    assert by_name["fixture"] == "FAIL"
    assert by_name["reference"] == "PASS"


@pytest.mark.parametrize("control", sorted(qualify.CONTROLS))
def test_every_broken_grader_is_refused_for_the_reason_its_name_gives(control: str) -> None:
    held, reason, _ = qualify.control_verdict(control)
    assert held, reason


def test_qualify_main_reports_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualify.main() == 0
    assert "QUALIFY: ok" in capsys.readouterr().out


def test_stale_data_passes_the_unit_test_and_fails_only_the_installed_path() -> None:
    outcomes = _outcomes(TASK / "wrong" / "stale-data")
    assert outcomes["functional-trailing-hyphen"] == "SATISFIED"
    assert outcomes["integration-installed-path"] == "VIOLATED"


def test_the_grading_method_is_stated_publicly_in_goal_md() -> None:
    goal = (TASK / "goal.md").read_text(encoding="utf-8")
    assert "installed" in goal.lower()
    assert "pyproject.toml" in goal


# --------------------------------------------------------------------------
# Real-pip mode selection (ported from check_real_pip_mode.py, #13 review)
# --------------------------------------------------------------------------


def _run_probe(probe_path: Path, candidate: Path, *, with_fake_pip: bool) -> dict[str, Any]:
    env = dict(os.environ)
    if with_fake_pip:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(FAKE_PIP_DIR) + (os.pathsep + existing if existing else "")
    else:
        env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, str(probe_path), str(candidate)],
        input=json.dumps(INPUTS), capture_output=True, text=True, env=env, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_without_fake_pip_the_reference_falls_back_to_stdlib_emulation() -> None:
    result = _run_probe(TASK / "probe.py", TASK / "reference", with_fake_pip=False)
    assert result["install_mode"] == "stdlib-emulation"


def test_with_fake_pip_the_reference_selects_real_pip_and_is_still_correct() -> None:
    result = _run_probe(TASK / "probe.py", TASK / "reference", with_fake_pip=True)
    assert result["install_mode"] == "real-pip"
    assert result["installed_outputs"] == [{"value": "rock-and-roll"}, {"value": "user-at-host"}]


def test_real_pip_mode_also_excludes_an_undeclared_scratch_copy() -> None:
    result = _run_probe(TASK / "probe.py", TASK / "wrong" / "scratch-copy", with_fake_pip=True)
    assert result["installed_outputs"][0] == {"value": "rock-and-roll-"}


def test_disabling_the_mode_switch_turns_the_real_pip_selection_red(tmp_path: Path) -> None:
    """Committed red case for the mode-selection branch itself: force
    `_pip_available` to always report False, and the SAME fake-pip-on-
    PYTHONPATH setup that normally selects `real-pip` above must then stay
    on `stdlib-emulation` instead - proving the ordinary passing test is
    actually sensitive to this logic, not vacuously green."""
    mutated_probe = tmp_path / "probe.py"
    source = (TASK / "probe.py").read_text(encoding="utf-8")
    target = "def _pip_available(backend_name: str | None) -> bool:\n    if not backend_name:\n        return False\n"
    assert source.count(target) == 1
    mutated = source.replace(
        target,
        "def _pip_available(backend_name: str | None) -> bool:\n"
        "    return False  # test-injected: mode switch forced off (#13 red case)\n",
    )
    mutated_probe.write_text(mutated, encoding="utf-8")

    result = _run_probe(mutated_probe, TASK / "reference", with_fake_pip=True)
    assert result["install_mode"] == "stdlib-emulation"


def test_check_real_pip_mode_script_still_agrees(capsys: pytest.CaptureFixture[str]) -> None:
    # The standalone script stays as a human-runnable entry point; this
    # confirms it hasn't drifted from what the suite itself proves above.
    proc = subprocess.run(
        [sys.executable, str(TASK / "check_real_pip_mode.py")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "check_real_pip_mode: ok" in proc.stdout
