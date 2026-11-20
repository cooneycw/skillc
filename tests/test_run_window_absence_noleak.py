"""No-leak controls for Contract A part 1 (#797 A-1).

Contract A reads no credential bytes, but it holds the paths and identities of
credential-bearing roots. This module plants a synthetic marker as a path
segment of a declared root and checks that none of the following discloses it
under slice 4's independent `no_marker` oracle:

- the reprs of every evidence object;
- fact outcomes;
- refusal messages;
- captured stdout, stderr and logs (the autouse audit imported from
  test_remnant_scan).

It also checks that no root inode number appears in a repr, that every
evidence object refuses pickling and copying, and that the oracle rejects a
deliberately leaking repr twin, so the oracle can be shown to fail.
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

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux') or not hasattr(os, 'O_PATH'),
                                reason='Contract A census requires Linux O_PATH')

LIMIT = 64


def marked_root(tmp_path: Path) -> tuple[Path, bytes]:
    refs = references(filename=True)
    value = refs._values[0]
    root = tmp_path / os.fsdecode(value) / 'removed-root'
    root.mkdir(parents=True)
    return root, value


def rendered(*objects: object) -> bytes:
    out = []
    for obj in objects:
        out.append(repr(obj))
        out.append(str(obj))
    return '\n'.join(out).encode('utf-8', 'surrogateescape')


def test_evidence_reprs_and_outcomes_disclose_no_path_or_inode(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, _ = marked_root(tmp_path)
    refs_for_audit = references(filename=True)  # A second, unplanted value: must also stay absent.
    gen = object()
    m0 = ra.record_mountpoint(root, generation=gen)
    assert m0 is not None
    (root / 'f').write_bytes(b'x')
    with ra.take_census(root, generation=gen, max_entries=LIMIT) as census:
        identity = census._entries[0][1]
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
    from test_remnant_scan import _contains_marker
    from skillc.remnant_scan import References
    assert not _contains_marker(output, References((os.fsencode(str(root)),)))
    no_marker(output, refs_for_audit)
    root_ino = str(os.stat(root).st_ino).encode()
    assert root_ino not in output
    assert str(identity.ino).encode() not in output


def test_refusal_messages_are_fixed_text(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, value = marked_root(tmp_path)
    relative = os.fsdecode(value) + '/removed-root'
    with pytest.raises(ra.CensusRefused) as caught:
        ra.take_census(relative, generation=object())
    text = (str(caught.value) + repr(caught.value)).encode('utf-8', 'surrogateescape')
    assert value not in text and b'SYNTHETIC_ONLY_' not in text
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_every_evidence_object_refuses_pickle_and_copy(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
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
        for obj in (census, census._entries[0][1], m0, tree, held[1]):
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


class LeakingCensus(ra.Census):
    """A deliberately leaking twin: its repr shows the declared path."""

    def __repr__(self) -> str:
        return '<Census ' + '/'.join(self._parts) + '>'


def test_oracle_rejects_a_leaking_repr_twin(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, value = marked_root(tmp_path)
    leaking = LeakingCensus(object(), str(root).strip('/').split('/'))
    from skillc.remnant_scan import References
    with pytest.raises(AssertionError):
        no_marker(repr(leaking).encode('utf-8', 'surrogateescape'), References((value,)))
    # The real class, given the same state, passes the same oracle.
    real = ra.Census(object(), str(root).strip('/').split('/'))
    no_marker(repr(real).encode('utf-8', 'surrogateescape'), References((value,)))
