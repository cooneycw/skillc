"""Offline controls for the actual live uv-version oracle (Refs #542).

Only Docker I/O is replaced. These establish parsing and command-failure
discrimination, not that a physical image contains the pinned tool.
"""

from __future__ import annotations

import runpy
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

SOURCE = Path(__file__).with_name("test_trial_image_tools_live.py")


@pytest.mark.parametrize("version", [
    "uv 0.9.7\n", "uv 0.9.7 (buildhash 2025-10-16)\n",
])
def test_exact_pin_is_accepted(version: str) -> None:
    _observe(version)


@pytest.mark.parametrize("version", [
    "uv 0.9.70\n", "uv 10.9.7\n", "uv 0.9.7-dev\n", "uv 0.0.0\n",
    "other-tool 0.9.7\n", "uv\n0.9.7\n", "uv 0.9.7\nuv 0.9.70\n", "",
])
def test_wrong_or_malformed_observation_is_rejected(version: str) -> None:
    _observe(version, rejected=True)


def test_command_failure_cannot_pass_with_the_right_version() -> None:
    _observe("uv 0.9.7\n", returncode=127, rejected=True)


def _observe(version: str, *, returncode: int = 0, rejected: bool = False) -> None:
    with patch.dict("os.environ", {"SKILLC_TRIAL_IMAGE_BREAK": "none"}), \
            patch("shutil.which", return_value=None):
        ns = runpy.run_path(str(SOURCE))
    observation = subprocess.CompletedProcess([], returncode, version, "probe diagnostic")
    with patch("subprocess.run", return_value=observation) as run:
        if rejected:
            with pytest.raises(ns["_UvPropertyHeld"]):
                ns["test_uv_is_present_at_the_pinned_version"]("unused-image")
        else:
            ns["test_uv_is_present_at_the_pinned_version"]("unused-image")
    run.assert_called_once_with(
        ["docker", "run", "--rm", "unused-image", "uv", "--version"],
        capture_output=True, text=True, timeout=30, check=False,
    )


@pytest.mark.parametrize(('stdout', 'returncode', 'rejected'), [
    ('{"wave_registration":true}\n', 0, False),
    ('{"wave_registration":true}\n', 127, True),
    ('{"wave_registration":false}\n', 0, True),
    ('', 0, True),
])
def test_jq_property_accepts_only_the_json_probe(stdout: str, returncode: int, rejected: bool) -> None:
    with patch.dict('os.environ', {'SKILLC_TRIAL_IMAGE_BREAK': 'none'}), \
            patch('shutil.which', return_value=None):
        ns = runpy.run_path(str(SOURCE))
    observation = subprocess.CompletedProcess([], returncode, stdout, 'jq probe diagnostic')
    with patch('subprocess.run', return_value=observation) as run:
        if rejected:
            with pytest.raises(ns['_JqPropertyHeld']):
                ns['test_jq_supports_the_wave_registration_json_dependency']('unused-image')
        else:
            ns['test_jq_supports_the_wave_registration_json_dependency']('unused-image')
    run.assert_called_once_with(
        ['docker', 'run', '--rm', 'unused-image', 'jq', '-cn', '{"wave_registration":true}'],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert not issubclass(ns['_JqPropertyHeld'], ns['_UvPropertyHeld'])


@pytest.mark.parametrize('mode', ['none', 'no-uv', 'no-jq'])
def test_tool_breaks_match_only_their_own_property(mode: str) -> None:
    with patch.dict('os.environ', {'SKILLC_TRIAL_IMAGE_BREAK': mode}), \
            patch('shutil.which', return_value=None):
        ns = runpy.run_path(str(SOURCE))
    assert ns['_BUILD_TARGET'] == ('trial' if mode == 'none' else mode)
    for function, selected in [('test_uv_is_present_at_the_pinned_version', 'no-uv'),
                               ('test_jq_supports_the_wave_registration_json_dependency', 'no-jq')]:
        markers = [marker for marker in ns[function].pytestmark if marker.name == 'xfail']
        assert len(markers) == 1
        assert markers[0].kwargs['condition'] == (mode == selected)
        assert markers[0].kwargs['strict'] is True
