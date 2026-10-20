"""#279 PR-2a: the SOURCE digest, computed identically for the tree a gate ran
on and the commit that shipped (orchestrator ruling R4).

Each red names the input that makes the digests DIFFER, and each control the
input that must still MATCH:
- control: a committed tree and its own commit agree (git's own representation);
- red (ruling R4): a symlink whose TARGET changes before ship differs, because
  its blob is the link text;
- red (ruling R4, as corrected): a file ADDED after the gate and committed
  differs; and an untracked file at gate time that never ships differs.
  Control: a file untracked at gate time and committed UNCHANGED matches. The
  gate judged exactly those bytes, so the population (ignore rules not applied,
  untracked files included) says it was the shipped source;
- the bookkeeping exemption, a special file, and the repository-root rule.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from skillc import fixture_attempt as fa
from skillc import git_snapshot as gs
from skillc import source_digest as sd


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@fixture.invalid", "-c",
                           "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    previous = os.umask(0o022)
    try:
        repo = tmp_path / "work" / "repo"
        repo.mkdir(parents=True)
        _git(repo, "init", "-q")
        (repo / "a.py").write_text("x = 1\n")
        (repo / "run.sh").write_text("#!/bin/sh\n")
        (repo / "run.sh").chmod(0o755)
        os.symlink("a.py", repo / "link")
        (repo / "sub").mkdir()
        (repo / "sub" / "b.txt").write_text("b\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")
    finally:
        os.umask(previous)
    return repo


def _commit_digest(repo: Path, commit: str = "HEAD") -> str:
    gitdir = gs.GitDir(gs.SafeTree(repo.parent), f"{repo.name}/.git")
    return sd.digest_commit(gitdir, _git(repo, "rev-parse", commit))


def test_a_committed_tree_and_its_commit_agree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert sd.digest_tree(repo) == _commit_digest(repo)
    entries = sd.tree_entries(repo)
    assert entries["run.sh"].startswith("100755 ") and entries["link"].startswith("120000 ")
    assert entries["link"] == f"120000 {sd.blob_id(b'a.py')}"


def test_a_symlink_retargeted_before_ship_mismatches(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    gated = sd.digest_tree(repo)
    (repo / "link").unlink()
    os.symlink("sub/b.txt", repo / "link")
    _git(repo, "commit", "-qam", "retarget")
    assert sd.digest_tree(repo) == _commit_digest(repo) != gated


def test_a_file_added_after_the_gate_and_committed_mismatches(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    gated = sd.digest_tree(repo)
    (repo / "late.py").write_text("y = 2\n")
    _git(repo, "add", "late.py")
    _git(repo, "commit", "-qm", "late")
    assert _commit_digest(repo) != gated


def test_an_untracked_file_at_gate_time_that_never_ships_mismatches(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "scratch.txt").write_text("not committed\n")
    assert sd.digest_tree(repo) != _commit_digest(repo)


def test_an_untracked_file_committed_unchanged_matches(tmp_path: Path) -> None:
    """The control for the two reds above: the gate judged these exact bytes."""
    repo = _repo(tmp_path)
    (repo / "new.py").write_text("z = 3\n")
    gated = sd.digest_tree(repo)
    _git(repo, "add", "new.py")
    _git(repo, "commit", "-qm", "new")
    assert _commit_digest(repo) == gated


def test_the_bookkeeping_path_alone_does_not_matter_but_a_byte_does(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "friction.jsonl").write_text("{}\n")
    assert sd.digest_tree(repo) == _commit_digest(repo)
    (repo / "a.py").write_text("x = 2\n")
    assert sd.digest_tree(repo) != _commit_digest(repo)
    (repo / "a.py").write_text("x = 1\n")
    (repo / "run.sh").chmod(0o644)  # a mode change
    assert sd.digest_tree(repo) != _commit_digest(repo)


def test_a_special_file_is_recorded_never_opened(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    os.mkfifo(repo / "pipe")
    assert sd.tree_entries(repo)["pipe"] == sd.NOT_A_FILE  # returns: the FIFO was never opened
    assert sd.digest_tree(repo) != _commit_digest(repo)


def test_the_repository_root_is_the_nearest_checkout(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    export = repo.parent
    assert sd.repository_root(export, "repo/sub") == repo.resolve()
    assert sd.repository_root(export, "repo") == repo.resolve()
    (export / "elsewhere").mkdir()
    assert sd.repository_root(export, "elsewhere") is None
    assert sd.repository_root(export, "../outside") is None
    linked = export / "repo-issue-1"
    _git(repo, "worktree", "add", "-q", str(linked), "-b", "issue-1")
    assert sd.repository_root(export, "repo-issue-1") == linked.resolve()  # a gitfile counts
    assert sd.digest_tree(linked) == _commit_digest(repo, "issue-1")


def test_a_neighbouring_worktree_does_not_move_the_gated_repository(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before = sd.digest_tree(repo)
    (repo.parent / "other").mkdir()
    (repo.parent / "other" / "noise.txt").write_text("unrelated\n")
    assert sd.digest_tree(repo) == before


def test_remote_ref_sources_digest_every_shipped_head(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    bare = tmp_path / "work" / ".remote" / "widget.git"
    bare.parent.mkdir()
    subprocess.run(["git", "init", "--bare", "-q", "--initial-branch=main", str(bare)], check=True)
    _git(repo, "push", "-q", str(bare), "HEAD:refs/heads/main", "HEAD:refs/heads/issue-1")
    refs = gs.GitDir(gs.SafeTree(tmp_path / "work"), ".remote/widget.git").refs()
    sources = fa._remote_ref_sources(tmp_path / "work", ".remote/widget.git", refs)
    assert sources == {"refs/heads/issue-1": sd.digest_tree(repo), "refs/heads/main": sd.digest_tree(repo)}
    missing = fa._remote_ref_sources(tmp_path / "work", ".remote/widget.git", {"refs/heads/x": "0" * 40})
    assert missing["refs/heads/x"].startswith("unreadable: ")


@pytest.mark.parametrize("cap", ["depth", "entries"])
def test_a_tree_past_its_caps_is_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: str) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setattr(sd, "MAX_DEPTH" if cap == "depth" else "MAX_ENTRIES", 0)
    with pytest.raises(sd.SourceUnreadable):
        sd.digest_tree(repo)


def test_a_nested_git_directory_is_part_of_what_the_gate_saw(tmp_path: Path) -> None:
    """Only the ROOT `.git` is metadata. A `.git` deeper down (an embedded
    repository the subject created) is content the gate ran beside, and git
    can never ship it, so the gated tree is NOT the shipped source."""
    repo = _repo(tmp_path)
    (repo / "sub" / ".git").mkdir()
    (repo / "sub" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    assert "sub/.git/HEAD" in sd.tree_entries(repo)
    assert sd.digest_tree(repo) != _commit_digest(repo)


@pytest.mark.parametrize(("mode", "committed", "matches"), [(0o645, 0o644, True), (0o645, 0o755, False),
                                                            (0o744, 0o755, True)])
def test_the_executable_mode_follows_gits_owner_bit(tmp_path: Path, mode: int, committed: int,
                                                     matches: bool) -> None:
    """Counter-model review: git records 100755 from the OWNER execute bit only."""
    repo = _repo(tmp_path)
    (repo / "tool.py").write_text("print(1)\n")
    (repo / "tool.py").chmod(committed)
    _git(repo, "add", "tool.py")
    _git(repo, "commit", "-qm", "tool")
    (repo / "tool.py").chmod(mode)
    assert (sd.digest_tree(repo) == _commit_digest(repo)) is matches


def test_budgets_bound_a_subject_written_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Counter-model review: a large file anywhere (`.claude` included) and a
    flood of empty directories are refused, never read without bound."""
    repo = _repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "cache.bin").write_bytes(b"\0" * 4096)
    monkeypatch.setattr(sd, "MAX_FILE_BYTES", 1024)
    with pytest.raises(sd.SourceUnreadable, match="larger than"):
        sd.digest_tree(repo)
    monkeypatch.setattr(sd, "MAX_FILE_BYTES", 1 << 30)
    monkeypatch.setattr(sd, "MAX_TOTAL_BYTES", 1024)
    with pytest.raises(sd.SourceUnreadable, match="more than 1024 bytes"):
        sd.digest_tree(repo)
    monkeypatch.setattr(sd, "MAX_TOTAL_BYTES", 1 << 30)
    for k in range(5):
        (repo / f"empty-{k}").mkdir()
    monkeypatch.setattr(sd, "MAX_ENTRIES", 8)
    with pytest.raises(sd.SourceUnreadable, match="directory entries"):
        sd.digest_tree(repo)


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_a_shipped_blob_that_cannot_be_read_is_unreadable_never_a_match(tmp_path: Path, damage: str) -> None:
    """Counter-model review, pass 2: a tree lists blob ids only, so the commit
    side reads every blob before it may claim a source."""
    repo = _repo(tmp_path)
    blob = sd.blob_id(b"x = 1\n")
    loose = repo / ".git" / "objects" / blob[:2] / blob[2:]
    assert loose.is_file()
    loose.chmod(0o644)
    if damage == "missing":
        loose.unlink()
    else:
        loose.write_bytes(b"not a zlib stream")
    with pytest.raises(sd.SourceUnreadable):
        _commit_digest(repo)


@pytest.mark.parametrize(("cwd", "rel"), [
    ("/work", ""), ("/work/repo", "repo"), ("/work/..issue-279", "..issue-279"), (None, ""),
    ("/work/../etc", None), ("/elsewhere", None),
])
def test_only_a_real_parent_segment_is_outside_the_workspace(cwd: str | None, rel: str | None) -> None:
    assert sd.workspace_relative(cwd, "/work") == rel
