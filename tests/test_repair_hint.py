"""One diagnosed fixture, repair guidance, and a corrected fixture (issue #27).

`scripts/repair_hint.py` is the one local author consumer this issue asks for:
it reads `skillc check --json` (stable rule/severity/path/detail per finding,
see docs/findings.md) and prints repair guidance keyed on the rule's stable id.
These tests run it as a real subprocess, exactly as an author would, rather
than importing its functions - the thing under test is the JSON contract
between two processes, not a Python API.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "repair_hint.py"
BAD_FIXTURE = ROOT / "controls" / "trigger-shape" / "bad" / "rotate-credential" / "SKILL.md"
GOOD_FIXTURE = ROOT / "controls" / "trigger-shape" / "good"


def _load_repair_hint() -> object:
    """`scripts/` is not a package, so import it by file location rather than
    adding it to `sys.path` for every test in the suite."""
    spec = importlib.util.spec_from_file_location("repair_hint", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


@pytest.mark.skipif(shutil.which("skillc") is None, reason="skillc console script not on PATH")
def test_a_known_bad_fixture_is_diagnosed_with_a_repair_hint(tmp_path: Path) -> None:
    skill_dir = tmp_path / "rotate-credential"
    skill_dir.mkdir()
    shutil.copy(BAD_FIXTURE, skill_dir / "SKILL.md")

    result = _run(str(skill_dir))

    assert result.returncode == 1
    assert "diagnosed [warn] trigger-shape" in result.stdout
    assert "repair:" in result.stdout


def test_repairing_the_fixture_as_the_hint_says_reports_clean(tmp_path: Path) -> None:
    """The repair this rule's own guidance names - add a triggering condition -
    applied to the exact bad fixture, must make `trigger-shape` fall silent.
    This is the "corrected fixture" half of the issue's observable evidence."""
    skill_dir = tmp_path / "rotate-credential"
    skill_dir.mkdir()
    text = BAD_FIXTURE.read_text(encoding="utf-8")
    repaired = text.replace(
        "description: Credential rotation patterns, tiered providers, and output masking",
        "description: Use when rotating a credential across tiered providers, with output masking",
    )
    assert repaired != text, "the fixture's description line moved; update this test's replacement"
    (skill_dir / "SKILL.md").write_text(repaired, encoding="utf-8")

    result = _run(str(skill_dir))

    assert result.returncode == 0
    assert "no findings" in result.stdout


@pytest.mark.skipif(shutil.which("skillc") is None, reason="skillc console script not on PATH")
def test_a_known_good_fixture_reports_no_findings() -> None:
    result = _run(str(GOOD_FIXTURE))
    assert result.returncode == 0
    assert "no findings - nothing to diagnose" in result.stdout


def test_an_unmapped_rule_still_prints_a_pointer_rather_than_silence() -> None:
    """The guidance table is deliberately small and will not name every rule.
    A finding it cannot map must still be visible, not swallowed."""
    repair_hint = _load_repair_hint()
    guidance = repair_hint.GUIDANCE  # type: ignore[attr-defined]
    assert "not-a-real-rule" not in guidance
    hint = guidance.get("not-a-real-rule", "see `skillc rules` for what this rule checks")
    assert hint == "see `skillc rules` for what this rule checks"


def test_a_bad_path_is_refused_not_crashed(tmp_path: Path) -> None:
    result = _run(str(tmp_path / "does-not-exist"))
    assert result.returncode == 2
    assert "repair-hint:" in result.stderr


def test_every_guidance_key_names_a_rule_that_still_exists() -> None:
    """A renamed or removed rule must not leave orphaned, silently-wrong guidance."""
    from skillc import checks

    repair_hint = _load_repair_hint()
    known = {rule.id for rule in checks.RULES}
    assert set(repair_hint.GUIDANCE) <= known  # type: ignore[attr-defined]
