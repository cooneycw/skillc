"""No-leak controls for Contract A part 1 (#797 A-1).

Contract A reads no credential bytes, but it holds the paths and identities of
credential-bearing roots. This module plants a synthetic marker as a path
segment of a declared root and checks that the following disclose neither the
marker nor the full root path, under slice 4's independent `no_marker`
oracle:

- the reprs and strs of every evidence object;
- fact outcomes;
- refusal messages and their exception chains;
- the held reader's errors;
- captured stdout, stderr and logs (the autouse audit imported from
  test_remnant_scan).

It also checks that an `Identity` exposes no device or inode attribute, that
every evidence object refuses pickling and copying, and that the oracle
rejects a deliberately leaking repr twin, so the oracle can be shown to fail.
"""
from __future__ import annotations

import copy
import os
import pickle
import sys
from pathlib import Path

import pytest
from test_remnant_scan import audit_captured_output, no_marker, references  # noqa: F401

from skillc import run_window_absence as ra
from skillc.git_snapshot import Unreadable
from skillc.remnant_scan import References

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux') or not hasattr(os, 'O_PATH'),
                                reason='Contract A census requires Linux O_PATH')

LIMIT = 64


def marked_root(tmp_path: Path) -> tuple[Path, References]:
    refs = references(filename=True)
    root = tmp_path.resolve() / os.fsdecode(refs._values[0]) / 'removed-root'
    root.mkdir(parents=True)
    return root, refs


def rendered(*objects: object) -> bytes:
    return '\n'.join(f'{obj!r}\n{obj!s}' for obj in objects).encode('utf-8', 'surrogateescape')


def assert_private(output: bytes, root: Path, refs: References) -> None:
    no_marker(output, refs)
    no_marker(output, References((os.fsencode(str(root)),)))


def test_evidence_reprs_and_outcomes_disclose_no_marker_path_or_inode(tmp_path: Path) -> None:
    root, refs = marked_root(tmp_path)
    gen = object()
    m0 = ra.record_mountpoint(root, generation=gen)
    assert m0 is not None
    (root / 'f').write_bytes(b'x')
    with m0, ra.take_census(root, generation=gen, max_entries=LIMIT) as census:
        identity = census._entries[0].identity
        os.unlink(root / 'f')
        unlinked = ra.fact_unlinked(census)
        census.release_entries()
        reresolved = ra.fact_reresolved(census, m0)
        held = ra.open_held_root(root)
        assert held is not None
        tree = ra.HeldTree(held[0])
        output = rendered(census, identity, m0, unlinked, reresolved, tree, held[1])
        tree.close()
        os.close(held[0])
    assert_private(output, root, refs)
    assert str(os.stat(root).st_ino).encode() not in output
    assert not any(hasattr(identity, name) for name in ('dev', 'ino', 'st_dev', 'st_ino', '__dict__'))


def test_refusal_messages_and_chains_are_fixed_text(tmp_path: Path) -> None:
    root, refs = marked_root(tmp_path)

    class Hostile:
        def __fspath__(self) -> str:
            raise RuntimeError(os.fsdecode(refs._values[0]))

    for bad in (os.fsdecode(refs._values[0]) + '/removed-root', Hostile()):
        with pytest.raises(ra.CensusRefused) as caught:
            ra.take_census(bad, generation=object())  # type: ignore[arg-type]
        exc = caught.value
        assert exc.__cause__ is None and exc.__context__ is None
        assert_private(rendered(exc, exc.__context__), root, refs)


def test_held_tree_errors_disclose_no_entry_name(tmp_path: Path) -> None:
    root, refs = marked_root(tmp_path)
    name = os.fsdecode(refs._values[0])
    (root / name).symlink_to(tmp_path)
    held = ra.open_held_root(root)
    assert held is not None
    try:
        tree = ra.HeldTree(held[0])
        with pytest.raises(Unreadable) as caught:
            tree.read(name)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert_private(rendered(caught.value), root, refs)
        tree.close()
    finally:
        os.close(held[0])


def test_held_tree_os_errors_naming_an_entry_are_translated(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    import errno
    root, refs = marked_root(tmp_path)
    name = os.fsdecode(refs._values[0])
    (root / 'plain').write_bytes(b'x')
    held = ra.open_held_root(root)
    assert held is not None
    real = os.scandir

    class Entry:
        def __init__(self, inner: os.DirEntry[str]) -> None:
            self.name = inner.name

        def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
            raise OSError(errno.EIO, 'io', name)

    class Hostile:
        def __init__(self, fd: int) -> None:
            self.inner = real(fd)

        def __enter__(self) -> list[Entry]:
            return [Entry(e) for e in self.inner]

        def __exit__(self, *exc: object) -> None:
            self.inner.close()

    try:
        tree = ra.HeldTree(held[0])
        monkeypatch.setattr(os, 'scandir', Hostile)
        with pytest.raises(Unreadable) as caught:
            tree.listdir('')
        monkeypatch.setattr(os, 'scandir', real)
        exc = caught.value
        assert exc.__cause__ is None and exc.__context__ is None
        assert_private(rendered(exc), root, refs)
        tree.close()
    finally:
        monkeypatch.setattr(os, 'scandir', real)
        os.close(held[0])


def test_every_evidence_object_refuses_pickle_and_copy(tmp_path: Path) -> None:
    root, _ = marked_root(tmp_path)
    gen = object()
    m0 = ra.record_mountpoint(root, generation=gen)
    assert m0 is not None
    (root / 'f').write_bytes(b'x')
    census = ra.take_census(root, generation=gen, max_entries=LIMIT)
    held = ra.open_held_root(root)
    assert held is not None
    tree = ra.HeldTree(held[0])
    try:
        for obj in (census, census._entries[0].identity, m0, tree, held[1]):
            with pytest.raises(TypeError):
                pickle.dumps(obj)
            with pytest.raises(TypeError):
                copy.copy(obj)
            with pytest.raises(TypeError):
                copy.deepcopy(obj)
    finally:
        tree.close()
        os.close(held[0])
        census.close()
        m0.close()


class LeakingCensus(ra.Census):
    """A deliberately leaking twin: its repr shows the declared path."""

    def __repr__(self) -> str:
        return '<Census /' + '/'.join(self._parts) + '>'


def test_oracle_rejects_a_leaking_repr_twin(tmp_path: Path) -> None:
    root, refs = marked_root(tmp_path)
    parts = str(root).strip('/').split('/')
    with pytest.raises(AssertionError):
        no_marker(repr(LeakingCensus(object(), parts)).encode('utf-8', 'surrogateescape'), refs)
    # The real class, given the same state, passes the same oracle.
    no_marker(repr(ra.Census(object(), parts)).encode('utf-8', 'surrogateescape'), refs)
