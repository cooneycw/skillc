"""Tests for the shared version/commit/dirty stamp (issue #10, operator
request, orchestrator message 1348)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import __version__, provenance


def test_stamp_reads_this_checkouts_own_commit() -> None:
    stamp = provenance.stamp()
    assert stamp["skillc_version"] == __version__
    want = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=provenance._PACKAGE_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert stamp["source_commit"] == want
    assert isinstance(stamp["dirty"], bool)


def test_an_unresolvable_commit_is_UNKNOWN_never_blank(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A directory that is not a git repository at all - the built-wheel case
    named in the module docstring."""
    monkeypatch.setattr(provenance, "_PACKAGE_ROOT", tmp_path)
    stamp = provenance.stamp()
    assert stamp["source_commit"] == "UNKNOWN"
    assert stamp["dirty"] is None


def test_git_not_installed_is_UNKNOWN_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("no such file: git")

    monkeypatch.setattr(subprocess, "run", _raise)
    stamp = provenance.stamp()
    assert stamp["source_commit"] == "UNKNOWN"
    assert stamp["dirty"] is None


def test_dirty_is_true_only_when_porcelain_reports_something(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run = subprocess.run

    def _fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(args, 0, stdout=" M some/file.py\n", stderr="")
        return real_run(args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", _fake_run)
    stamp = provenance.stamp()
    assert stamp["source_commit"] != "UNKNOWN"
    assert stamp["dirty"] is True


def test_dirty_false_when_porcelain_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    real_run = subprocess.run

    def _fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return real_run(args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", _fake_run)
    stamp = provenance.stamp()
    assert stamp["dirty"] is False


def test_a_porcelain_failure_is_dirty_None_even_with_a_known_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The commit resolves but the status check itself fails (e.g. a lock file
    another process holds) - dirty must not default to False, which would
    read as a clean tree that was never actually checked."""
    real_run = subprocess.run

    def _fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(args, 128, stdout="", stderr="fatal: locked")
        return real_run(args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", _fake_run)
    stamp = provenance.stamp()
    assert stamp["source_commit"] != "UNKNOWN"
    assert stamp["dirty"] is None
