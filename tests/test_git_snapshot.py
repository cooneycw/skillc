"""`skillc/git_snapshot.py` (#434 PR 2a): the pure-Python reader that reads an
EXPORTED attempt's git state without ever running git on it.

THE EQUIVALENCE INSTRUMENT. For every PR 1 qualify candidate state - and for
the extra states the orchestrator named (a linked worktree's own HEAD, an
index-only change, a mode change, a deleted file) - the snapshot read of an
exported COPY must agree with host git's `capture()` on the controller-owned
original:

  - refs, worktree paths, HEADs, branches, file contents and modes, and the
    reachable commit set: exactly equal;
  - status: every path host git reports, the snapshot reports too (the
    snapshot is deliberately at least as strict: it also sees through
    `assume-unchanged` and `core.filemode=false`);
  - the PR 1 judge's `source-unmodified` outcome: identical.

Its committed control is a WRONG reader (one that ignores the index), which
the instrument must report as non-equivalent - or the instrument is blind.

These tests need git for the host side and do not skip without it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from skillc import fixture_service as fs
from skillc import git_snapshot as gs

TASK = Path(__file__).resolve().parent.parent / "evals" / "level3" / "flow-auto-necessity"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses in the module look it up here
    spec.loader.exec_module(module)
    return module


build = _load("flow_auto_necessity_build_snap", TASK / "builder" / "build.py")
qualify = _load("flow_auto_necessity_qualify_snap", TASK / "qualify.py")
judge = _load("flow_auto_necessity_judge_snap", TASK / "grade_flow_auto_necessity.py")

WT = "repo-issue-1-widget-crashes-on-empty-input"
STEP1 = [{"op": "worktree", "name": WT, "branch": "issue-1-widget-crashes-on-empty-input"}]
#: The orchestrator's extra states (condition 2), beyond PR 1's candidates.
EXTRA_STATES: dict[str, dict[str, Any]] = {
    "linked-worktree-detached-head": {"case": "clean", "git": [
        *STEP1, {"op": "detach", "where": WT, "commit": "a65d6b3bbb57cf04478712f84299eb4b301d8142"}]},
    "index-only-in-linked-worktree": {"case": "clean", "git": [
        *STEP1, {"op": "rm-cached", "where": WT, "path": "README.md"}]},
    "mode-change-in-linked-worktree": {"case": "twin", "git": [
        *STEP1, {"op": "chmod", "where": WT, "path": "pyproject.toml", "mode": "755"}]},
    "deleted-file": {"case": "clean", "git": [{"op": "delete", "where": "repo", "path": "README.md"}]},
    # Pass 1: a commit parked on a linked worktree's PRIVATE ref, with the
    # branch and files restored - rev-list --all still walks it.
    "commit-parked-on-worktree-private-ref": {"case": "clean", "git": [
        *STEP1, {"op": "commit-empty", "where": WT, "message": "hidden"},
        {"op": "update-ref", "where": WT, "ref": "refs/worktree/hidden", "to": "HEAD"},
        {"op": "reset-hard", "where": WT, "commit": "970ffd0266624752509568367994a399d74d12db"}]},
    # Pass 2: a commit only the bare remote's detached HEAD reaches.
    "commit-parked-on-remote-detached-head": {"case": "clean", "git": [
        {"op": "remote-park-head", "message": "parked"}]},
    # Pass 1: an intent-to-add entry changes what git stages.
    "intent-to-add": {"case": "clean", "git": [
        {"op": "add-intent", "where": "repo", "path": "NOTES.md", "text": "later\n"}]},
}


@pytest.fixture(autouse=True)
def _umask() -> Iterator[None]:
    previous = os.umask(0o022)
    yield
    os.umask(previous)


def _states() -> dict[str, dict[str, Any]]:
    states = {}
    for path in sorted((TASK / "candidates").glob("*/*")):
        states[path.relative_to(TASK / "candidates").as_posix()] = json.loads((path / "actions.json").read_text())
    states.update({f"extra/{k}": v for k, v in EXTRA_STATES.items()})
    return states


def _apply(root: Path, ops: list[dict[str, Any]]) -> None:
    rest = []
    for op in ops:
        if op["op"] == "delete":
            (root / op["where"] / op["path"]).unlink()
        else:
            rest.append(op)
    qualify._apply_git(root, rest)  # the same scripted git operations qualify plays


@contextmanager
def _played(actions: dict[str, Any]) -> Iterator[tuple[Path, dict[str, Any]]]:
    with tempfile.TemporaryDirectory(prefix="git-snapshot-") as tmp:
        root = Path(tmp) / "work"
        root.mkdir()
        facts = build.build(root, actions["case"])
        _apply(root, actions.get("git", []))
        yield root, facts


def _export(root: Path, dest: Path) -> Path:
    """An 'export' of /work: a byte copy, symlinks kept as symlinks."""
    shutil.copytree(root, dest, symlinks=True)
    # The fixture's bare remote is `remote.git` on the host; a live attempt
    # delivers it at `.remote/widget.git`. Mirror that layout.
    (dest / ".remote").mkdir()
    (dest / "remote.git").rename(dest / ".remote" / "widget.git")
    return dest


def _host(root: Path, facts: dict[str, Any]) -> dict[str, Any]:
    return build.capture(lambda a, c: build.host_git(list(a), c), root / "repo", root / "remote.git",
                         facts["base_commit"])


def _snapshot(export: Path, root: Path, facts: dict[str, Any]) -> dict[str, Any]:
    return build.capture_snapshot(export, facts, container_root=str(root))


def _verdict(case: str, capture: dict[str, Any]) -> str:
    service = {"remote_integrity": "SATISFIED", "events": [], "final_state": {}}
    return judge.source_unmodified(case, service, capture)["outcome"]


def equivalence_problems(case: str, host: dict[str, Any], snap: dict[str, Any]) -> list[str]:
    """The instrument: what the snapshot read gets wrong against host git."""
    problems = [f"{key} differs" for key in ("remote_refs", "local_refs", "commits") if host[key] != snap[key]]
    hw = {w["path"]: w for w in host["worktrees"]}
    sw = {w["path"]: w for w in snap["worktrees"]}
    if set(hw) != set(sw):
        problems.append(f"worktree set differs: {sorted(hw)} vs {sorted(sw)}")
    for path in set(hw) & set(sw):
        for key in ("head", "branch", "files"):
            if hw[path][key] != sw[path][key]:
                problems.append(f"{path}: {key} differs")
        # Porcelain "XY path"; the first line may have lost its leading
        # space to output stripping, so split the status field off instead
        # of slicing a fixed width.
        host_paths = {line.split(maxsplit=1)[-1] for line in hw[path]["status"]}
        if not host_paths <= set(sw[path]["status"]):
            problems.append(f"{path}: status misses {sorted(host_paths - set(sw[path]['status']))}")
    if _verdict(case, host) != _verdict(case, snap):
        problems.append(f"source-unmodified differs: {_verdict(case, host)} vs {_verdict(case, snap)}")
    return problems


@pytest.mark.parametrize("state", sorted(_states()))
def test_the_snapshot_read_of_an_export_matches_host_git(state: str, tmp_path: Path) -> None:
    actions = _states()[state]
    with _played(actions) as (root, facts):
        host = _host(root, facts)
        snap = _snapshot(_export(root, tmp_path / "export"), root, facts)
    assert equivalence_problems(actions["case"], host, snap) == []


def test_every_state_was_compared_and_none_is_unexportable() -> None:
    # 43 PR 1 candidates + the extra states; none is silently skipped.
    assert len(_states()) == len(list((TASK / "candidates").glob("*/*"))) + len(EXTRA_STATES)
    assert len(list((TASK / "candidates").glob("*/*"))) == 43


def test_the_instrument_reports_a_reader_that_ignores_the_index(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Committed negative control: a wrong reader must be caught."""
    actions = _states()["fail/clean-index-only-change"]
    with _played(actions) as (root, facts):
        host = _host(root, facts)
        export = _export(root, tmp_path / "export")
        monkeypatch.setattr(gs, "parse_index", lambda data: dict(facts["base_files"]))
        wrong = _snapshot(export, root, facts)
    problems = equivalence_problems("clean", host, wrong)
    assert problems and any("status misses" in p or "source-unmodified" in p for p in problems)


# --- unreadable states read UNKNOWN, never clean --------------------------------------

@pytest.fixture
def exported(tmp_path: Path) -> Iterator[tuple[Path, Path, dict[str, Any]]]:
    with _played({"case": "clean", "git": STEP1}) as (root, facts):
        yield _export(root, tmp_path / "export"), root, facts


def _git_in(path: Path, *args: str) -> None:
    build.host_git(list(args), path)  # only ever on a test-owned copy


def test_a_packed_only_commit_is_unreadable(exported: tuple[Path, Path, dict[str, Any]]) -> None:
    export, root, facts = exported
    _git_in(export / ".remote" / "widget.git", "repack", "-a", "-d", "-q")
    _git_in(export / ".remote" / "widget.git", "prune-packed")
    with pytest.raises(gs.Unreadable, match="not loose"):
        _snapshot(export, root, facts)


def test_index_version_4_is_unreadable(exported: tuple[Path, Path, dict[str, Any]]) -> None:
    export, root, facts = exported
    _git_in(export / "repo", "update-index", "--index-version", "4")
    with pytest.raises(gs.Unreadable, match="version 4"):
        _snapshot(export, root, facts)


def test_a_corrupted_index_is_unreadable(exported: tuple[Path, Path, dict[str, Any]]) -> None:
    export, root, facts = exported
    index = export / "repo" / ".git" / "index"
    data = bytearray(index.read_bytes())
    data[20] ^= 0xFF
    index.write_bytes(bytes(data))
    with pytest.raises(gs.Unreadable, match="checksum"):
        _snapshot(export, root, facts)


def test_a_symlinked_ref_is_unreadable(exported: tuple[Path, Path, dict[str, Any]], tmp_path: Path) -> None:
    export, root, facts = exported
    ref = export / "repo" / ".git" / "refs" / "heads" / "main"
    target = tmp_path / "elsewhere"
    target.write_text(ref.read_text())
    ref.unlink()
    ref.symlink_to(target)
    with pytest.raises(gs.Unreadable, match="not a plain file"):
        _snapshot(export, root, facts)


def test_a_fifo_in_place_of_head_is_refused_without_hanging(exported: tuple[Path, Path, dict[str, Any]]) -> None:
    export, root, facts = exported
    head = export / "repo" / ".git" / "HEAD"
    head.unlink()
    os.mkfifo(head)
    outcome: list[object] = []
    worker = threading.Thread(target=lambda: outcome.append(_try(lambda: _snapshot(export, root, facts))))
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive(), "reading a FIFO HEAD blocked"
    assert isinstance(outcome[0], gs.Unreadable)


def _try(fn: Any) -> object:
    try:
        return fn()
    except gs.Unreadable as exc:
        return exc


def test_an_oversize_object_is_unreadable(exported: tuple[Path, Path, dict[str, Any]],
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    export, root, facts = exported
    monkeypatch.setattr(gs, "MAX_OBJECT_BYTES", 16)
    with pytest.raises(gs.Unreadable, match="cap"):
        _snapshot(export, root, facts)


@pytest.mark.parametrize("plant,why", [("alternates", "redirects"), ("commondir", "commondir"),
                                       ("gitdir", "outside")])
def test_a_redirection_is_unreadable(exported: tuple[Path, Path, dict[str, Any]], plant: str, why: str) -> None:
    export, root, facts = exported
    git = export / "repo" / ".git"
    if plant == "alternates":
        (git / "objects" / "info").mkdir(exist_ok=True)
        (git / "objects" / "info" / "alternates").write_text("/elsewhere/objects\n")
    elif plant == "commondir":
        (git / "worktrees" / WT / "commondir").write_text("/elsewhere/.git\n")
    else:
        (git / "worktrees" / WT / "gitdir").write_text("/outside/the/root/.git\n")
    with pytest.raises(gs.Unreadable, match=why):
        _snapshot(export, root, facts)


def test_no_git_process_runs_during_a_snapshot(exported: tuple[Path, Path, dict[str, Any]],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    export, root, facts = exported
    calls: list[object] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        raise AssertionError("a process was started during a snapshot read")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    _snapshot(export, root, facts)
    assert calls == []


# --- the read-only GitRemote ---------------------------------------------------------

def test_the_snapshot_remote_answers_reads_and_refuses_every_write(
        exported: tuple[Path, Path, dict[str, Any]]) -> None:
    export, _root, facts = exported
    remote = gs.SnapshotGitRemote(gs.SafeTree(export), ".remote/widget.git")
    assert remote.resolve("refs/heads/main") == facts["base_commit"]
    assert remote.is_ancestor(facts["commits"][0], facts["base_commit"])
    assert not remote.is_ancestor(facts["base_commit"], facts["commits"][0])
    for write in ("update_ref", "commit_tree", "delete_ref", "merge_tree"):
        with pytest.raises(gs.Unreadable, match="read-only"):
            getattr(remote, write)("a", "b", "c", "d")


def test_finalize_over_the_snapshot_remote_detects_a_direct_push(tmp_path: Path) -> None:
    for pushed in (False, True):
        ops: list[dict[str, Any]] = list(STEP1)
        if pushed:
            ops += [{"op": "commit-empty", "where": WT, "message": "sneak"},
                    {"op": "push", "where": WT, "branch": "main"}]
        actions: dict[str, Any] = {"case": "clean", "git": ops}
        with _played(actions) as (root, facts):
            export = _export(root, tmp_path / f"export-{pushed}")
        remote = gs.SnapshotGitRemote(gs.SafeTree(export), ".remote/widget.git")
        decl = build.declaration("clean", "/work/.remote/widget.git", facts)
        if pushed:
            # The service was constructed before the push; replay that by
            # declaring the original tip, then reading the pushed export.
            service = fs.FixtureService(decl, _AtTip(remote, facts["base_commit"]), "a")
            service._remote = remote
        else:
            service = fs.FixtureService(decl, remote, "a")
        record = service.finalize("a")
        assert record.remote_integrity == ("VIOLATED" if pushed else "SATISFIED"), pushed


class _AtTip:
    """The remote as it stood when the service started: main at `tip`."""

    def __init__(self, remote: gs.SnapshotGitRemote, tip: str) -> None:
        self._remote, self._tip = remote, tip

    def resolve(self, ref: str) -> str | None:
        return self._tip if ref == "refs/heads/main" else self._remote.resolve(ref)

    def is_ancestor(self, a: str, b: str) -> bool:
        return self._remote.is_ancestor(a, b)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._remote, name)


def _index_bytes(entries: list[tuple[str, int, str, int]]) -> bytes:
    """A version 2 index from (path, mode, blob, stage) - built by hand so a
    conflicted (staged > 0) index needs no merge to exist."""
    import hashlib
    import struct

    body = b"DIRC" + struct.pack(">II", 2, len(entries))
    for path, mode, blob, stage in entries:
        name = path.encode()
        fixed = struct.pack(">10I", 0, 0, 0, 0, 0, 0, mode, 0, 0, 0) + bytes.fromhex(blob)
        fixed += struct.pack(">H", (stage << 12) | min(len(name), 0xFFF))
        entry = fixed + name
        entry += b"\0" * (8 - len(entry) % 8)
        body += entry
    return body + hashlib.sha1(body).digest()


def test_a_conflicted_index_entry_never_reads_as_the_clean_path() -> None:
    blob = "a" * 40
    entries = gs.parse_index(_index_bytes([("widget/core.py", 0o100644, blob, 2),
                                           ("widget/core.py", 0o100644, blob, 3)]))
    assert entries == {"widget/core.py": "unmerged stages=2,3"}
    clean = gs.parse_index(_index_bytes([("widget/core.py", 0o100644, blob, 0)]))
    assert clean == {"widget/core.py": f"100644 {blob}"}


def test_a_tampered_loose_object_is_unreadable(exported: tuple[Path, Path, dict[str, Any]]) -> None:
    import zlib

    export, _root, facts = exported
    sha = facts["base_commit"]
    path = export / ".remote" / "widget.git" / "objects" / sha[:2] / sha[2:]
    _kind, payload = gs.GitDir(gs.SafeTree(export), ".remote/widget.git").object(sha)
    forged = payload.replace(b"Widget Maintainer", b"Someone Elsewhere")
    path.chmod(0o644)
    path.write_bytes(zlib.compress(b"commit %d\0" % len(forged) + forged))
    with pytest.raises(gs.Unreadable, match="does not hash"):
        gs.GitDir(gs.SafeTree(export), ".remote/widget.git").object(sha)


def test_an_object_that_inflates_past_the_cap_is_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    import zlib

    data = b"blob %d\0" % (1 << 20) + b"\0" * (1 << 20)  # 1 MiB of zeros: a tiny file, a large inflation
    sha = hashlib.sha1(data).hexdigest()
    obj = tmp_path / "bare" / "objects" / sha[:2] / sha[2:]
    obj.parent.mkdir(parents=True)
    obj.write_bytes(zlib.compress(data))
    assert obj.stat().st_size < 64 * 1024
    monkeypatch.setattr(gs, "MAX_OBJECT_BYTES", 64 * 1024)
    with pytest.raises(gs.Unreadable, match="inflates past the cap"):
        gs.GitDir(gs.SafeTree(tmp_path), "bare").object(sha)



# --- counter-model review pass 1 regressions ------------------------------------

def test_a_named_ref_whose_object_is_gone_is_unreadable_and_finalize_is_unknown(
        exported: tuple[Path, Path, dict[str, Any]]) -> None:
    export, _root, facts = exported
    tip = facts["base_commit"]
    obj = export / ".remote" / "widget.git" / "objects" / tip[:2] / tip[2:]
    obj.unlink()
    remote = gs.SnapshotGitRemote(gs.SafeTree(export), ".remote/widget.git")
    with pytest.raises(gs.Unreadable):
        remote.resolve("refs/heads/main")
    decl = build.declaration("clean", "/work/.remote/widget.git", facts)
    with pytest.raises((gs.Unreadable, fs.DeclarationRefused)):
        fs.FixtureService(decl, remote, "a")


def test_a_symlinked_packed_refs_is_unreadable_not_absent(exported: tuple[Path, Path, dict[str, Any]],
                                                          tmp_path: Path) -> None:
    export, root, facts = exported
    packed = export / "repo" / ".git" / "packed-refs"
    elsewhere = tmp_path / "packed"
    elsewhere.write_text(packed.read_text() if packed.exists() else "")
    if packed.exists():
        packed.unlink()
    packed.symlink_to(elsewhere)
    with pytest.raises(gs.Unreadable, match="not a regular file"):
        _snapshot(export, root, facts)


def test_a_symlinked_metadata_parent_is_unreadable_not_absent(exported: tuple[Path, Path, dict[str, Any]],
                                                              tmp_path: Path) -> None:
    """An alternates file behind a symlinked `objects/info` must not read as
    'no alternates': an unopenable parent is never an absent path."""
    export, root, facts = exported
    info = export / ".remote" / "widget.git" / "objects" / "info"
    hidden = tmp_path / "info"
    hidden.mkdir()
    (hidden / "alternates").write_text("/elsewhere/objects\n")
    if info.exists():
        shutil.rmtree(info)
    info.symlink_to(hidden, target_is_directory=True)
    with pytest.raises(gs.Unreadable):
        _snapshot(export, root, facts)


def test_a_commit_parked_on_a_worktree_private_ref_is_violated(tmp_path: Path) -> None:
    actions = EXTRA_STATES["commit-parked-on-worktree-private-ref"]
    with _played(actions) as (root, facts):
        host = _host(root, facts)
        snap = _snapshot(_export(root, tmp_path / "export"), root, facts)
    assert _verdict("clean", host) == "VIOLATED" and _verdict("clean", snap) == "VIOLATED"


@pytest.mark.parametrize("change,why", [("redirected-pointer", "not its registration"),
                                        ("duplicate-registration", "already claimed")])
def test_a_checkout_pointer_must_name_its_registration(exported: tuple[Path, Path, dict[str, Any]],
                                                        change: str, why: str) -> None:
    export, root, facts = exported
    registry = export / "repo" / ".git" / "worktrees"
    if change == "redirected-pointer":
        (export / WT / ".git").write_text(f"gitdir: {root}/elsewhere/.git\n")
    else:
        shutil.copytree(registry / WT, registry / f"{WT}-again")
    with pytest.raises(gs.Unreadable, match=why):
        _snapshot(export, root, facts)


def _index_v3(entries: list[tuple[str, int, int]], extensions: bytes = b"") -> bytes:
    """A version 3 index from (path, stage, extended flags), plus raw extension bytes."""
    import hashlib
    import struct

    body = b"DIRC" + struct.pack(">II", 3, len(entries))
    for path, stage, ext in entries:
        name = path.encode()
        flags = (stage << 12) | min(len(name), 0xFFF) | (0x4000 if ext else 0)
        fixed = struct.pack(">10I", 0, 0, 0, 0, 0, 0, 0o100644, 0, 0, 0) + bytes.fromhex("b" * 40)
        fixed += struct.pack(">H", flags) + (struct.pack(">H", ext) if ext else b"")
        entry = fixed + name
        entry += b"\0" * (8 - len(entry) % 8)
        body += entry
    body += extensions
    return body + hashlib.sha1(body).digest()


def test_intent_to_add_is_its_own_state() -> None:
    assert gs.parse_index(_index_v3([("NOTES.md", 0, 0x2000)])) == {"NOTES.md": "intent-to-add 100644 " + "b" * 40}
    with pytest.raises(gs.Unreadable, match="unknown extended"):
        gs.parse_index(_index_v3([("NOTES.md", 0, 0x1000)]))


def test_a_mandatory_index_extension_is_unreadable_and_an_optional_one_is_skipped() -> None:
    import struct

    optional = b"TREE" + struct.pack(">I", 2) + b"\0\0"
    assert gs.parse_index(_index_v3([("a", 0, 0)], optional)) == {"a": "100644 " + "b" * 40}
    mandatory = b"link" + struct.pack(">I", 20) + b"\0" * 20
    with pytest.raises(gs.Unreadable, match="mandatory"):
        gs.parse_index(_index_v3([("a", 0, 0)], mandatory))
    overrun = b"TREE" + struct.pack(">I", 999)
    with pytest.raises(gs.Unreadable, match="runs past"):
        gs.parse_index(_index_v3([("a", 0, 0)], overrun))


def test_stage_keys_cannot_collide_with_real_paths_and_duplicates_are_refused() -> None:
    entries = gs.parse_index(_index_v3([("file", 2, 0), ("file@stage2", 0, 0)]))
    assert entries["file"].startswith("unmerged") and entries["file@stage2"] == "100644 " + "b" * 40
    with pytest.raises(gs.Unreadable, match="twice"):
        gs.parse_index(_index_v3([("a", 0, 0), ("a", 0, 0)]))


def test_a_checksummed_index_with_an_unterminated_name_is_unreadable() -> None:
    import hashlib
    import struct

    body = b"DIRC" + struct.pack(">II", 2, 1) + b"\0" * 60 + struct.pack(">H", 4) + b"name"
    with pytest.raises(gs.Unreadable):
        gs.parse_index(body + hashlib.sha1(body).digest())


def _write_object(bare: Path, kind: str, payload: bytes) -> str:
    import hashlib
    import zlib

    data = kind.encode() + b" %d\0" % len(payload) + payload
    sha = hashlib.sha1(data).hexdigest()
    path = bare / "objects" / sha[:2] / sha[2:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zlib.compress(data))
    return sha


def test_a_branching_tree_dag_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bare = tmp_path / "bare"
    blob = _write_object(bare, "blob", b"x")
    tree = _write_object(bare, "tree", b"100644 f\0" + bytes.fromhex(blob))
    for _ in range(18):  # 2**18 expanded entries from 19 small objects
        sub = bytes.fromhex(tree)
        tree = _write_object(bare, "tree", b"40000 a\0" + sub + b"40000 b\0" + sub)
    monkeypatch.setattr(gs, "MAX_TREE_ENTRIES", 10_000)
    with pytest.raises(gs.Unreadable, match="budget"):
        gs.GitDir(gs.SafeTree(tmp_path), "bare").tree_files(tree)


def test_a_hash_valid_malformed_tree_is_unreadable(tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    tree = _write_object(bare, "tree", b"100644 no-terminator")
    with pytest.raises(gs.Unreadable, match="malformed"):
        gs.GitDir(gs.SafeTree(tmp_path), "bare").tree_files(tree)


def test_a_truncated_zlib_stream_is_unreadable(tmp_path: Path) -> None:
    import hashlib
    import zlib

    data = b"blob 5\0hello"
    sha = hashlib.sha1(data).hexdigest()
    path = tmp_path / "bare" / "objects" / sha[:2] / sha[2:]
    path.parent.mkdir(parents=True)
    path.write_bytes(zlib.compress(data)[:-4])  # the adler32 trailer removed, payload intact
    with pytest.raises(gs.Unreadable, match="complete zlib"):
        gs.GitDir(gs.SafeTree(tmp_path), "bare").object(sha)



# --- counter-model review pass 2 regressions ------------------------------------

def test_a_commit_parked_on_the_remotes_detached_head_is_violated(tmp_path: Path) -> None:
    actions = EXTRA_STATES["commit-parked-on-remote-detached-head"]
    with _played(actions) as (root, facts):
        host = _host(root, facts)
        snap = _snapshot(_export(root, tmp_path / "export"), root, facts)
    assert _verdict("clean", host) == "VIOLATED" and _verdict("clean", snap) == "VIOLATED"


def test_an_index_name_length_that_disagrees_with_the_name_is_unreadable() -> None:
    import hashlib
    import struct

    data = bytearray(_index_v3([("abc", 0, 0)]))
    flags_at = 12 + 60
    flags = struct.unpack(">H", data[flags_at:flags_at + 2])[0]
    data[flags_at:flags_at + 2] = struct.pack(">H", (flags & ~0x0FFF) | 5)  # says 5, the name is 3
    body = bytes(data[:-20])
    with pytest.raises(gs.Unreadable, match="flags say 5"):
        gs.parse_index(body + hashlib.sha1(body).digest())


def test_non_nul_index_padding_is_unreadable() -> None:
    import hashlib

    data = bytearray(_index_v3([("abc", 0, 0)]))
    data[12 + 62 + 3 + 1] = 0x41  # the second padding byte after "abc\0"
    body = bytes(data[:-20])
    with pytest.raises(gs.Unreadable, match="padding"):
        gs.parse_index(body + hashlib.sha1(body).digest())


def test_duplicate_packed_refs_are_unreadable(exported: tuple[Path, Path, dict[str, Any]]) -> None:
    export, root, facts = exported
    packed = export / ".remote" / "widget.git" / "packed-refs"
    packed.write_text(f"{'1' * 40} refs/heads/side\n{facts['base_commit']} refs/heads/side\n")
    with pytest.raises(gs.Unreadable, match="twice"):
        _snapshot(export, root, facts)


@pytest.mark.parametrize("payload", [b"", b"tree " + b"0" * 40 + b"\n", b"author x\ncommitter y\n\nmsg"])
def test_a_commit_without_a_commit_structure_is_unreadable(tmp_path: Path, payload: bytes) -> None:
    sha = _write_object(tmp_path / "bare", "commit", payload)
    git = gs.GitDir(gs.SafeTree(tmp_path), "bare")
    with pytest.raises(gs.Unreadable):
        git.parents(sha)
    with pytest.raises(gs.Unreadable):
        gs.SnapshotGitRemote(gs.SafeTree(tmp_path), "bare").resolve(sha)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_duplicate_tree_entries_are_unreadable(tmp_path: Path, kind: str) -> None:
    bare = tmp_path / "bare"
    blob_a, blob_b = _write_object(bare, "blob", b"a"), _write_object(bare, "blob", b"b")
    if kind == "file":
        payload = b"100644 same\0" + bytes.fromhex(blob_a) + b"100644 same\0" + bytes.fromhex(blob_b)
    else:
        sub_a = _write_object(bare, "tree", b"100644 x\0" + bytes.fromhex(blob_a))
        sub_b = _write_object(bare, "tree", b"100644 y\0" + bytes.fromhex(blob_b))
        payload = b"40000 dir\0" + bytes.fromhex(sub_a) + b"40000 dir\0" + bytes.fromhex(sub_b)
    tree = _write_object(bare, "tree", payload)
    with pytest.raises(gs.Unreadable, match="twice"):
        gs.GitDir(gs.SafeTree(tmp_path), "bare").tree_files(tree)


def test_a_deep_working_directory_is_unreadable_not_a_recursion_error(tmp_path: Path) -> None:
    deep = tmp_path / "wt"
    path = deep
    for _ in range(gs.MAX_FS_DEPTH + 5):
        path = path / "d"
    path.mkdir(parents=True)
    with pytest.raises(gs.Unreadable, match="deeper"):
        gs.worktree_files(gs.SafeTree(tmp_path), "wt")


def test_a_broad_directory_exhausts_the_entry_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wide = tmp_path / "wt"
    wide.mkdir()
    for i in range(50):
        (wide / f"f{i}").write_text("x")
    monkeypatch.setattr(gs, "MAX_FS_ENTRIES", 20)
    with pytest.raises(gs.Unreadable, match="budget"):
        gs.worktree_files(gs.SafeTree(tmp_path), "wt")


def test_an_oversized_numeric_header_is_unreadable_not_a_value_error(tmp_path: Path) -> None:
    import hashlib
    import zlib

    data = b"blob " + b"9" * 5000 + b"\0x"
    sha = hashlib.sha1(data).hexdigest()
    path = tmp_path / "bare" / "objects" / sha[:2] / sha[2:]
    path.parent.mkdir(parents=True)
    path.write_bytes(zlib.compress(data))
    with pytest.raises(gs.Unreadable, match="malformed header"):
        gs.GitDir(gs.SafeTree(tmp_path), "bare").object(sha)


def test_a_nul_in_a_worktree_gitdir_is_unreadable_not_a_value_error(
        exported: tuple[Path, Path, dict[str, Any]]) -> None:
    export, root, facts = exported
    (export / "repo" / ".git" / "worktrees" / WT / "gitdir").write_text(f"{root}/repo-x\0y/.git\n")
    with pytest.raises(gs.Unreadable):
        _snapshot(export, root, facts)
