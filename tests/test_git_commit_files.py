"""Exact remote commit bytes for #640, without invoking git on the export."""
from pathlib import Path

import pytest
from test_git_snapshot import _write_object

from skillc import git_snapshot as gs


def commit(bare: Path, entries: list[tuple[str, str, bytes]]) -> str:
    payload = b""
    for mode, name, data in entries:
        blob = _write_object(bare, "blob", data)
        payload += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(blob)
    tree = _write_object(bare, "tree", payload)
    return _write_object(bare, "commit", f"tree {tree}\nauthor Fixture <fixture@fixture.invalid> 0 +0000\ncommitter Fixture <fixture@fixture.invalid> 0 +0000\n\nDelivery\n".encode())


def test_commit_files_reads_exact_bytes_and_modes_not_workspace(tmp_path: Path) -> None:
    bare = tmp_path / "remote"
    sha = commit(bare, [("100755", "run", b"\x00\xffexact\n"), ("120000", "link", b"target")])
    (tmp_path / "run").write_bytes(b"wrong workspace")
    assert gs.GitDir(gs.SafeTree(tmp_path), "remote").commit_files(sha) == {
        "run": ("100755", b"\x00\xffexact\n"), "link": ("120000", b"target")}


def test_commit_files_has_a_shared_blob_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bare = tmp_path / "remote"
    sha = commit(bare, [("100644", "a", b"same"), ("100644", "b", b"same")])
    monkeypatch.setattr(gs, "MAX_COMMIT_BYTES", 7)
    with pytest.raises(gs.Unreadable, match="blob-byte budget"):
        gs.GitDir(gs.SafeTree(tmp_path), "remote").commit_files(sha)


def test_commit_files_refuses_gitlinks(tmp_path: Path) -> None:
    sha = commit(tmp_path / "remote", [("160000", "nested", b"not in this repository")])
    with pytest.raises(gs.Unreadable, match="gitlink"):
        gs.GitDir(gs.SafeTree(tmp_path), "remote").commit_files(sha)


def test_commit_files_refuses_a_missing_or_corrupt_blob(tmp_path: Path) -> None:
    bare = tmp_path / "remote"
    sha = commit(bare, [("100644", "a", b"remote bytes")])
    git = gs.GitDir(gs.SafeTree(tmp_path), "remote")
    blob = git.tree_files(git.tree_of(sha))["a"].split()[1]
    (bare / "objects" / blob[:2] / blob[2:]).write_bytes(b"corrupt")
    with pytest.raises(gs.Unreadable):
        gs.GitDir(gs.SafeTree(tmp_path), "remote").commit_files(sha)
