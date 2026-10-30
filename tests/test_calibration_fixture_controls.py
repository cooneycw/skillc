"""Controls for #640's fixture digest and symmetry report, without model calls."""

from pathlib import Path

import pytest

from skillc import calibration_run as cr
from skillc import fixture_attempt as fa


def test_digest_refuses_an_empty_surface() -> None:
    with pytest.raises(fa.FixtureUndeliverable, match="empty"):
        fa.fixture_digest({})


def test_digest_covers_surface_root_permissions(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir(mode=0o755)
    (root / "file").write_bytes(b"same bytes")
    before = fa.fixture_digest({"repo": root})
    root.chmod(0o700)
    assert fa.fixture_digest({"repo": root}) != before


def test_digest_does_not_hide_a_failed_directory_walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unreadable(*args: object, **kwargs: object) -> object:
        onerror = kwargs.get("onerror")
        if callable(onerror):
            onerror(PermissionError("unreadable fixture directory"))
        return iter(())

    monkeypatch.setattr(fa.os, "walk", unreadable)
    with pytest.raises(OSError, match="unreadable fixture directory"):
        fa.fixture_digest({"repo": tmp_path})


@pytest.mark.parametrize("kind", ["bytes", "mode", "symlink"])
def test_digest_distinguishes_changed_or_undeliverable_files(tmp_path: Path, kind: str) -> None:
    file = tmp_path / "file"
    file.write_bytes(b"original")
    before = fa.fixture_digest({"repo": tmp_path})
    if kind == "bytes":
        file.write_bytes(b"changed")
    elif kind == "mode":
        file.chmod(0o700)
    else:
        file.unlink()
        file.symlink_to("missing")
        with pytest.raises(fa.FixtureUndeliverable, match="non-regular"):
            fa.fixture_digest({"repo": tmp_path})
        return
    assert fa.fixture_digest({"repo": tmp_path}) != before


@pytest.mark.parametrize("accounting", ["success", "non-start"])
def test_symmetry_requires_at_least_one_dispatched_attempt(accounting: str) -> None:
    fixture = {"case": "clean", "digest": "sha256:built", "delivered_digest": "sha256:built"}
    report = cr.fixture_symmetry([{"accounting": accounting, "fixture": fixture}])
    assert report is not None
    assert report["symmetric"] is (accounting != "non-start")


def test_symmetry_refuses_an_attempt_missing_its_fixture_plan() -> None:
    report = cr.fixture_symmetry([
        {"accounting": "success"},
        {"accounting": "success", "fixture": {"case": "clean", "digest": "sha256:built",
                                               "delivered_digest": "sha256:built"}},
    ])
    assert report is not None
    assert report["symmetric"] is False
