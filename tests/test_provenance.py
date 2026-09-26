"""Tests for the shared provenance stamp (#10 addendum item E)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skillc import __version__, provenance


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _scratch_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    (repo / "file.txt").write_text("hello\n")
    _git(["add", "file.txt"], repo)
    _git(["commit", "-q", "-m", "initial"], repo)
    return repo


def test_stamp_reports_the_real_checkout() -> None:
    """Run against skillc's own checkout (this test's default source_root) -
    a real git repository, so this asserts the HAPPY path end to end."""
    result = provenance.stamp()
    assert result.skillc_version == __version__
    assert result.source_commit != "UNKNOWN"
    assert len(result.source_commit) == 40
    assert all(c in "0123456789abcdef" for c in result.source_commit)
    assert isinstance(result.dirty, bool)


def test_stamp_is_unknown_outside_any_git_work_tree(tmp_path: Path) -> None:
    result = provenance.stamp(tmp_path)
    assert result.source_commit == "UNKNOWN"
    assert result.dirty is None
    assert result.skillc_version == __version__  # never UNKNOWN - this package always has one


def test_stamp_is_unknown_when_git_is_not_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _scratch_repo(tmp_path)
    monkeypatch.setenv("PATH", "")
    result = provenance.stamp(repo)
    assert result.source_commit == "UNKNOWN"
    assert result.dirty is None


def test_dirty_is_false_on_a_clean_checkout(tmp_path: Path) -> None:
    repo = _scratch_repo(tmp_path)
    result = provenance.stamp(repo)
    assert result.source_commit != "UNKNOWN"
    assert result.dirty is False


def test_dirty_is_true_with_an_uncommitted_change(tmp_path: Path) -> None:
    repo = _scratch_repo(tmp_path)
    (repo / "file.txt").write_text("changed\n")
    result = provenance.stamp(repo)
    assert result.dirty is True


def test_as_dict_carries_exactly_the_agreed_field_names() -> None:
    result = provenance.stamp()
    assert set(result.as_dict()) == {"skillc_version", "source_commit", "dirty"}


def test_a_subdirectory_of_an_unrelated_repo_is_unknown_not_misattributed(tmp_path: Path) -> None:
    """Found by w3's cross-model review: running git FROM source_root is not
    enough - it only proves SOME repository was found, not that source_root
    is that repository's OWN root. An installed wheel living under
    site-packages inside an unrelated enclosing project's checkout would
    otherwise silently inherit that project's HEAD and dirty status. Here:
    `nested/` is a plain subdirectory of `repo` (an outer git repository),
    never made its own repo - stamping `nested` must be UNKNOWN, never
    `repo`'s commit."""
    repo = _scratch_repo(tmp_path)
    nested = repo / "nested"
    nested.mkdir()
    result = provenance.stamp(nested)
    assert result.source_commit == "UNKNOWN"
    assert result.dirty is None
