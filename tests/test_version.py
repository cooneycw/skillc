"""One version, one source of truth (#73).

Before this, `pyproject.toml` and `skillc/__init__.py` each carried their own
literal `"0.1.0"`, and nothing checked they agreed - they didn't have to be
different to drift, only for one to be edited and the other forgotten. Now
`skillc.__version__` reads `pyproject.toml`'s `version` through the installed
package's own distribution metadata (`importlib.metadata`), so there is
structurally only one place to edit. `test_the_mismatch_check_can_say_the_other_thing`
is this test's own negative control: it proves `_mismatch` is not a function that
always returns `None`, which is the shape a genuinely blind check would take.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import skillc
from skillc import cli

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert isinstance(version, str) and version, "pyproject.toml declares no version"
    return version


def _mismatch(pyproject_version: str, installed_version: str) -> str | None:
    if pyproject_version != installed_version:
        return (
            f"pyproject.toml declares {pyproject_version!r}, but the installed "
            f"package's own metadata (skillc.__version__) says {installed_version!r}"
        )
    return None


def test_version_matches_pyproject() -> None:
    assert _mismatch(_pyproject_version(), skillc.__version__) is None


def test_the_mismatch_check_can_say_the_other_thing() -> None:
    """Committed red case: prove `_mismatch` is not blind to a real divergence."""
    assert _mismatch("1.2.3", "1.2.4") is not None
    assert _mismatch("1.2.3", "1.2.3") is None


def test_cli_version_flag_reports_the_same_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"skillc {skillc.__version__}"
