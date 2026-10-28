"""Vendored CPP notices live with the copies without changing frozen tree identities.

The license digest was read independently from upstream LICENSE at the two
revisions named in THIRD_PARTY_NOTICES.md. Existing in-tree notices at every
other committed CPP pin have the same bytes. No git or network is needed in CI.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
NOTICE = FIXTURES / "THIRD_PARTY_NOTICES.md"
SNAPSHOTS = sorted(path for path in FIXTURES.glob("profile-cpp-*") if path.is_dir())
UPSTREAM = b"https://github.com/cooneycw/claude-power-pack"
LICENSE_SHA256 = "c6c2630fa5d672358d322509c5c073f87fa89f59157a93fe0b4067edd0260c60"
LEGACY = FIXTURES / "profile-cpp-codex-cicd-86641e8"
LICENSED = FIXTURES / "profile-cpp-codex-flow-auto-86641e8"


def _revision(snapshot: Path) -> str:
    subject = ROOT / "evals/subjects" / snapshot.name.removeprefix("profile-") / "subject.json"
    revision: str = json.loads(subject.read_text())["revision"]
    assert re.fullmatch(r"[0-9a-f]{40}", revision)
    return revision


def _assert_notice(snapshot: Path, revision: str, notice: bytes) -> None:
    license_path = snapshot / "LICENSE"
    assert not license_path.is_symlink(), "license must be carried, not linked outside the copy"
    if license_path.is_file():
        license_bytes = license_path.read_bytes()
    else:
        assert UPSTREAM in notice, "missing upstream source"
        rows = re.findall(rb"^\| `([^`]+)` \| `([0-9a-f]{40})` \|$", notice, re.MULTILINE)
        matches = [pin for name, pin in rows if name == snapshot.name.encode()]
        assert matches == [revision.encode()], f"missing or incorrect notice listing: {snapshot.name}"
        blocks = re.findall(rb"^```text\n(.*?)^```\n", notice, re.MULTILINE | re.DOTALL)
        assert len(blocks) == 1, "one verbatim upstream license block is required"
        license_bytes = blocks[0]
    assert hashlib.sha256(license_bytes).hexdigest() == LICENSE_SHA256, "upstream license bytes differ"


def test_cpp_snapshot_population_and_notice_location() -> None:
    assert SNAPSHOTS, "empty snapshot population cannot establish notice coverage"
    assert all(not NOTICE.is_relative_to(snapshot) for snapshot in SNAPSHOTS)


@pytest.mark.parametrize("snapshot", SNAPSHOTS, ids=lambda path: path.name)
def test_every_cpp_snapshot_carries_its_upstream_license(snapshot: Path) -> None:
    notice = NOTICE.read_bytes() if NOTICE.is_file() else b""
    _assert_notice(snapshot, _revision(snapshot), notice)


def test_missing_notice_listing_is_rejected() -> None:
    notice = NOTICE.read_bytes()
    listing = f"| `{LEGACY.name}` | `{_revision(LEGACY)}` |\n".encode()
    assert notice.count(listing) == 1
    with pytest.raises(AssertionError, match="notice listing"):
        _assert_notice(LEGACY, _revision(LEGACY), notice.replace(listing, b""))


def test_altered_shared_license_text_is_rejected() -> None:
    notice = NOTICE.read_bytes()
    original = b"Copyright (c) 2025 cooneycw"
    assert notice.count(original) == 1
    with pytest.raises(AssertionError, match="license bytes differ"):
        _assert_notice(LEGACY, _revision(LEGACY), notice.replace(original, b"Copyright removed"))


def test_an_in_tree_license_passes_without_a_shared_listing() -> None:
    _assert_notice(LICENSED, _revision(LICENSED), b"")


def test_an_altered_in_tree_license_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_bytes((LICENSED / "LICENSE").read_bytes() + b"changed\n")
    with pytest.raises(AssertionError, match="license bytes differ"):
        _assert_notice(tmp_path, _revision(LICENSED), b"")
