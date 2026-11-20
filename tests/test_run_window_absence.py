"""Contract A part 1 (#797 A-1): census, fact 1 (unlinked) and fact 4
(re-resolved), and the held-descriptor reader.

These qualify NEW instruments; none of them is a regression test of an
existing API, so none claims a red run on the parent. Each case that could be
passed by a blind checker is paired with that checker (`blind_*` below): the
blind checker must give a different verdict on the same planted tree.

Real temporary trees are used wherever the kernel's link-count or lookup
semantics are the fact under test (A3, A4, A9, A17, A18). A8 (an unreadable
root or ancestor) runs through an injected opener that raises PermissionError,
so it is exercised under root too. CI runs as root, where a mode-000
directory would not block. Linux only: the module needs O_PATH.
"""
from __future__ import annotations

import errno
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from skillc import run_window_absence as ra
from skillc.git_snapshot import Unreadable

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux') or not hasattr(os, 'O_PATH'),
                                reason='Contract A census requires Linux O_PATH')

NEG, SURV, FAIL = ra.NEG, ra.SURV, ra.FAIL
LIMIT = 64


def populate(root: Path) -> None:
    (root / 'home').mkdir()
    (root / 'home' / 'auth.json').write_bytes(b'synthetic-only')
    (root / 'vault').mkdir()
    (root / 'vault' / 'copy').write_bytes(b'synthetic-only')
    (root / 'top').write_bytes(b'x')


def remove_entries(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            os.unlink(os.path.join(dirpath, name))
        for name in dirnames:
            os.rmdir(os.path.join(dirpath, name))


def fresh_root(tmp_path: Path) -> tuple[Path, ra.MountpointRecord, object]:
    """A declared root recorded empty as M0, then populated: the shape of a
    tmpfs mounted over an empty mountpoint, without needing a mount."""
    root = tmp_path / 'declared' / 'removed-root'
    root.mkdir(parents=True)
    generation = object()
    m0 = ra.record_mountpoint(root, generation=generation)
    assert m0 is not None
    populate(root)
    return root, m0, generation


def census_of(root: Path, generation: object, **kw: Any) -> ra.Census:
    kw.setdefault('max_entries', LIMIT)
    return ra.take_census(root, generation=generation, **kw)


# Blind checkers: what a path-string implementation would conclude.
def blind_path_absence(root: Path) -> ra.Observation:
    """'Nothing under the declared path, so ABSENT' (ignores renames/links)."""
    return NEG if not any(root.iterdir()) else SURV


def blind_held_parent_lookup(census: ra.Census, name: str) -> ra.Observation:
    """'Look the name up through the parent fd we held, ENOENT means gone':
    a renamed parent still answers ENOENT while the declared path changed."""
    parent_fd = census._ancestors[-1][0]
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return NEG
    return SURV


# A17: the positive case, so the suite cannot be passed by always failing.
def test_all_facts_hold_after_removal_is_confirmed_negative(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    with census_of(root, gen) as census:
        assert census.complete and census.entries == 5
        remove_entries(root)
        assert ra.fact_unlinked(census) is NEG
        census.release_entries()
        assert ra.fact_reresolved(census, m0) == ra.Reresolved(NEG, False)


# A3: a renamed directory keeps links; a path check sees an empty root.
def test_renamed_directory_keeps_links_and_is_a_survivor(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    outside = tmp_path / 'elsewhere'
    with census_of(root, gen) as census:
        os.rename(root / 'vault', outside)
        remove_entries(root)
        assert blind_path_absence(root) is NEG
        assert ra.fact_unlinked(census) is SURV


# A4: a file hard-linked outside before removal keeps st_nlink 1.
def test_hard_linked_file_is_a_survivor(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    with census_of(root, gen) as census:
        os.link(root / 'home' / 'auth.json', tmp_path / 'kept-link')
        remove_entries(root)
        assert blind_path_absence(root) is NEG
        assert ra.fact_unlinked(census) is SURV


# A8 (fake-reader twin, runs as root in CI): an unreadable root or ancestor
# is OBSERVATION_FAILED, never CLEAN or ABSENT.
@pytest.mark.parametrize('which', ['ancestor', 'root', 'listing', 'entry'])
def test_unreadable_lookup_is_observation_failed(tmp_path: Path, which: str) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    target = {'ancestor': 'declared', 'root': 'removed-root', 'listing': '.', 'entry': 'auth.json'}[which]

    def denying(name: str, flags: int, *args: Any, **kwargs: Any) -> int:
        if name == target and (which != 'listing' or kwargs.get('dir_fd') is not None):
            raise PermissionError(errno.EACCES, 'denied')
        return os.open(name, flags, *args, **kwargs)

    with ra.take_census(root, generation=gen, max_entries=LIMIT, opener=denying) as census:
        assert not census.complete
        remove_entries(root)
        assert ra.fact_unlinked(census) is FAIL
        census.release_entries()
        assert ra.fact_reresolved(census, m0).observation is FAIL


@pytest.mark.skipif(os.geteuid() == 0, reason='root bypasses mode bits; the opener twin covers A8')
def test_unreadable_root_by_mode_is_observation_failed(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    os.chmod(root / 'home', 0)
    try:
        with census_of(root, gen) as census:
            assert not census.complete
            assert ra.fact_unlinked(census) is FAIL
    finally:
        os.chmod(root / 'home', 0o700)


# A9: the parent renamed and a new parent placed at the declared path. A held
# parent lookup says "gone"; fact 4 refuses and asks for the replacement scan.
def test_replaced_parent_is_failed_and_rescanned(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    with census_of(root, gen) as census:
        remove_entries(root)
        assert ra.fact_unlinked(census) is NEG
        census.release_entries()
        os.rename(tmp_path / 'declared', tmp_path / 'declared-old')
        (tmp_path / 'declared' / 'removed-root').mkdir(parents=True)
        (tmp_path / 'declared' / 'removed-root' / 'remnant').write_bytes(b'x')
        # Through the held (old) parent the remnant is not there: a blind lookup says gone.
        assert blind_held_parent_lookup(census, 'removed-root/remnant') is NEG
        assert ra.fact_reresolved(census, m0) == ra.Reresolved(FAIL, True)


# A18: after "unmount" the path must be M0 and empty.
def test_nonempty_mountpoint_is_present_and_rescanned(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    with census_of(root, gen) as census:
        remove_entries(root)
        census.release_entries()
        (root / 'recreated').write_bytes(b'x')
        assert ra.fact_reresolved(census, m0) == ra.Reresolved(SURV, True)


def test_recreated_root_is_not_m0_and_is_rescanned(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    with census_of(root, gen) as census:
        remove_entries(root)
        census.release_entries()
        os.rmdir(root)
        root.mkdir()
        assert ra.fact_reresolved(census, m0) == ra.Reresolved(SURV, True)


def test_without_m0_the_root_must_be_absent(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, _, gen = fresh_root(tmp_path)
    with census_of(root, gen) as census:
        remove_entries(root)
        census.release_entries()
        assert ra.fact_reresolved(census, None) == ra.Reresolved(SURV, True)
        os.rmdir(root)
        assert ra.fact_reresolved(census, None) == ra.Reresolved(NEG, False)


def test_m0_must_be_recorded_empty(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root = tmp_path / 'nonempty'
    root.mkdir()
    (root / 'x').write_bytes(b'x')
    assert ra.record_mountpoint(root, generation=object()) is None


# A16: a census over its bound is incomplete, never truncated.
def test_census_over_entry_bound_is_incomplete(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, _, gen = fresh_root(tmp_path)
    with ra.take_census(root, generation=gen, max_entries=2) as census:
        assert not census.complete
        assert ra.fact_unlinked(census) is FAIL


def test_census_over_depth_bound_is_incomplete(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, _, gen = fresh_root(tmp_path)
    with ra.take_census(root, generation=gen, max_entries=LIMIT, max_depth=1) as census:
        assert not census.complete


def test_descriptor_budget_refuses_an_impossible_census() -> None:
    assert ra.fd_budget_ok(1, 1)
    assert not ra.fd_budget_ok(10**9, 1) or _unlimited_fds()


def _unlimited_fds() -> bool:
    import resource
    return resource.getrlimit(resource.RLIMIT_NOFILE)[0] == resource.RLIM_INFINITY


@pytest.mark.parametrize('kind', ['symlink', 'fifo'])
def test_special_entry_makes_the_census_incomplete(tmp_path: Path, kind: str) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, _, gen = fresh_root(tmp_path)
    special = root / 'home' / 'special'
    if kind == 'symlink':
        special.symlink_to(tmp_path)
    else:
        os.mkfifo(special)
    with census_of(root, gen) as census:
        assert not census.complete
        assert ra.fact_unlinked(census) is FAIL


def test_symlinked_ancestor_is_never_followed(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    real = tmp_path / 'real' / 'removed-root'
    real.mkdir(parents=True)
    (tmp_path / 'link').symlink_to(tmp_path / 'real')
    with ra.take_census(tmp_path / 'link' / 'removed-root', generation=object(),
                        max_entries=LIMIT) as census:
        assert not census.complete


# A15 (partial; full matching is A-3): evidence is bound to one generation.
def test_census_is_bound_to_its_generation_by_identity(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    with census_of(root, gen) as census:
        assert census.belongs_to(gen)
        assert not census.belongs_to(object())
        remove_entries(root)
        census.release_entries()
        empty = tmp_path / 'other-mountpoint'
        empty.mkdir()
        other = ra.record_mountpoint(empty, generation=object())
        assert other is not None
        assert ra.fact_reresolved(census, other).observation is FAIL


def test_facts_refuse_out_of_order_use(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, m0, gen = fresh_root(tmp_path)
    census = census_of(root, gen)
    assert ra.fact_reresolved(census, m0).observation is FAIL  # entries still held
    census.release_entries()
    assert ra.fact_unlinked(census) is FAIL  # fds released: fact 1 cannot be read
    census.close()
    assert not census.complete


def test_entry_replaced_under_its_held_identity_is_failed(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root, _, gen = fresh_root(tmp_path)
    with census_of(root, gen) as census:
        fd, ident = census._entries[0]
        other = os.open(str(tmp_path), os.O_RDONLY)
        os.dup2(other, fd)
        os.close(other)
        assert ra.fact_unlinked(census) is FAIL


@pytest.mark.parametrize('bad', ['relative/path', '/a/../b', '/', '/nul\0byte'])
def test_declared_path_must_be_plain_absolute(bad: str) -> None:
    with pytest.raises(ra.CensusRefused):
        ra.take_census(bad, generation=object())


def test_census_needs_a_generation(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    with pytest.raises(ra.CensusRefused):
        ra.take_census(tmp_path, generation=None)


# HeldTree: the scan follows the held object, not the path.
def test_held_tree_reads_the_held_root_after_the_path_moves(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root = tmp_path / 'retained'
    root.mkdir()
    (root / 'out.txt').write_bytes(b'held-bytes')
    held = ra.open_held_root(root)
    assert held is not None
    fd, ident = held
    try:
        tree = ra.HeldTree(fd)
        os.rename(root, tmp_path / 'moved')
        root.mkdir()
        (root / 'out.txt').write_bytes(b'decoy')
        assert tree.listdir('') == [('out.txt', 'file')]
        assert tree.read('out.txt')[0] == b'held-bytes'
        tree.close()
    finally:
        os.close(fd)


def test_held_tree_never_follows_a_link(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    root = tmp_path / 'retained'
    root.mkdir()
    (root / 'link').symlink_to(tmp_path)
    held = ra.open_held_root(root)
    assert held is not None
    try:
        tree = ra.HeldTree(held[0])
        assert tree.kind('link') == 'other'
        with pytest.raises(Unreadable):
            tree.read('link')
        tree.close()
    finally:
        os.close(held[0])


def test_held_tree_refuses_a_non_directory(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    f = tmp_path / 'file'
    f.write_bytes(b'x')
    fd = os.open(f, os.O_RDONLY)
    try:
        with pytest.raises(Unreadable):
            ra.HeldTree(fd)
    finally:
        os.close(fd)


def test_open_held_root_refuses_a_symlinked_root(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # the census never follows a link, so start from a real path
    (tmp_path / 'real').mkdir()
    (tmp_path / 'alias').symlink_to(tmp_path / 'real')
    assert ra.open_held_root(tmp_path / 'alias') is None

