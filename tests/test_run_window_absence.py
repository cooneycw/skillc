"""Contract A part 1 (#797 A-1): census, fact 1 (unlinked) and fact 4
(re-resolved), and the held-descriptor reader.

These qualify NEW instruments; none of them is a regression test of an
existing API, so none claims a red run on the parent. Each case that a blind
checker could pass is paired with that checker (`blind_*` below), and the
blind checker must give a different verdict on the same planted tree.

Real temporary trees are used wherever the kernel's link-count or lookup
semantics are the fact under test. A8 (an unreadable root or ancestor) runs
through an injected opener that raises PermissionError, so it is exercised
under root too. CI runs as root, where a mode-000 directory would not block.
Descriptor accounting (`open_fds`) proves that failure paths close what they
opened. Linux only: the module needs O_PATH.
"""
from __future__ import annotations

import errno
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from skillc import run_window_absence as ra
from skillc.git_snapshot import Unreadable

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux') or not hasattr(os, 'O_PATH'),
                                reason='Contract A census requires Linux O_PATH')

NEG, SURV, FAIL = ra.NEG, ra.SURV, ra.FAIL
LIMIT = 64


def open_fds() -> set[str]:
    return set(os.listdir('/proc/self/fd'))


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


class Window:
    """A declared root recorded empty as M0, then populated: the shape of a
    tmpfs mounted over an empty mountpoint, without needing a mount."""

    def __init__(self, tmp_path: Path, generation: object | None = None) -> None:
        self.tmp = tmp_path.resolve()  # The census never follows a link.
        self.root = self.tmp / 'declared' / 'removed-root'
        self.root.mkdir(parents=True)
        self.generation = object() if generation is None else generation
        m0 = ra.record_mountpoint(self.root, generation=self.generation)
        assert m0 is not None
        self.m0 = m0
        populate(self.root)

    def census(self, **kw: Any) -> ra.Census:
        kw.setdefault('max_entries', LIMIT)
        return ra.take_census(self.root, generation=self.generation, **kw)


@pytest.fixture
def window(tmp_path: Path) -> Iterator[Window]:
    w = Window(tmp_path)
    yield w
    w.m0.close()


# Blind checkers: what a weaker implementation would conclude.
def blind_path_absence(root: Path) -> ra.Observation:
    """'Nothing under the declared path, so ABSENT' (ignores renames/links)."""
    return NEG if not any(root.iterdir()) else SURV


def blind_files_only_fact1(census: ra.Census) -> ra.Observation:
    """Fact 1 that checks only regular files (ignores directory links)."""
    import stat
    for item in census._entries:
        info = os.fstat(item.fd)
        if stat.S_ISREG(info.st_mode) and info.st_nlink:
            return SURV
    return NEG


def blind_held_parent_lookup(census: ra.Census, name: str) -> ra.Observation:
    """'Look the final name up through the parent fd we held; ENOENT means
    gone' - a renamed parent still answers while the declared path changed."""
    try:
        os.stat(name, dir_fd=census._ancestors[-1].fd, follow_symlinks=False)
    except FileNotFoundError:
        return NEG
    return SURV


# A17: the positive case, so the suite cannot be passed by always failing.
def test_all_facts_hold_after_removal_is_confirmed_negative(window: Window) -> None:
    with window.census() as census:
        assert census.complete and census.entries == 5
        remove_entries(window.root)
        assert ra.fact_unlinked(census) is NEG
        census.release_entries()
        assert ra.fact_reresolved(census, window.m0) == ra.Reresolved(NEG, False)


# A3: an EMPTY renamed directory is the sole survivor: it keeps st_nlink 2.
def test_renamed_empty_directory_is_the_sole_survivor(window: Window) -> None:
    os.unlink(window.root / 'vault' / 'copy')
    with window.census() as census:
        os.rename(window.root / 'vault', window.tmp / 'elsewhere')
        remove_entries(window.root)
        assert blind_path_absence(window.root) is NEG
        assert blind_files_only_fact1(census) is NEG
        assert ra.fact_unlinked(census) is SURV


# A4: a file hard-linked outside before removal keeps st_nlink 1.
def test_hard_linked_file_is_a_survivor(window: Window) -> None:
    with window.census() as census:
        os.link(window.root / 'home' / 'auth.json', window.tmp / 'kept-link')
        remove_entries(window.root)
        assert blind_path_absence(window.root) is NEG
        assert ra.fact_unlinked(census) is SURV


# A8 (opener twin; this is what root CI runs): an unreadable root, ancestor,
# listing or entry is OBSERVATION_FAILED, never CLEAN or ABSENT.
@pytest.mark.parametrize('which', ['ancestor', 'root', 'listing', 'entry'])
def test_unreadable_lookup_is_observation_failed(window: Window, which: str) -> None:
    target = {'ancestor': 'declared', 'root': 'removed-root', 'listing': '.', 'entry': 'auth.json'}[which]

    def denying(name: str, flags: int, *args: Any, **kwargs: Any) -> int:
        if name == target and (which != 'listing' or kwargs.get('dir_fd') is not None):
            raise PermissionError(errno.EACCES, 'denied')
        return os.open(name, flags, *args, **kwargs)

    before = open_fds()
    census = window.census(opener=denying)
    assert not census.complete
    remove_entries(window.root)
    assert ra.fact_unlinked(census) is FAIL
    census.release_entries()
    assert ra.fact_reresolved(census, window.m0).observation is FAIL
    census.close()
    assert open_fds() == before


@pytest.mark.skipif(os.geteuid() == 0, reason='root bypasses mode bits; CI runs the opener twin')
def test_unreadable_directory_by_mode_is_observation_failed(window: Window) -> None:
    os.chmod(window.root / 'home', 0)
    try:
        with window.census() as census:
            assert not census.complete
            assert ra.fact_unlinked(census) is FAIL
    finally:
        os.chmod(window.root / 'home', 0o700)


# A9: the parent renamed, the old root removed under it, and a new parent
# with a remnant at the declared path. The held parent says "gone".
def test_replaced_parent_is_failed_and_rescanned(window: Window) -> None:
    with window.census() as census:
        remove_entries(window.root)
        assert ra.fact_unlinked(census) is NEG
        census.release_entries()
        os.rename(window.tmp / 'declared', window.tmp / 'declared-old')
        os.rmdir(window.tmp / 'declared-old' / 'removed-root')
        (window.tmp / 'declared' / 'removed-root').mkdir(parents=True)
        (window.tmp / 'declared' / 'removed-root' / 'remnant').write_bytes(b'x')
        assert blind_held_parent_lookup(census, 'removed-root') is NEG
        assert ra.fact_reresolved(census, window.m0) == ra.Reresolved(FAIL, True)


@pytest.mark.parametrize('change', ['removed', 'file', 'symlink'])
def test_ancestor_gone_or_not_a_directory_is_failed_and_rescanned(window: Window, change: str) -> None:
    with window.census() as census:
        remove_entries(window.root)
        census.release_entries()
        os.rename(window.tmp / 'declared', window.tmp / 'declared-old')
        if change == 'file':
            (window.tmp / 'declared').write_bytes(b'x')
        elif change == 'symlink':
            (window.tmp / 'declared').symlink_to(window.tmp / 'declared-old')
        assert ra.fact_reresolved(census, window.m0) == ra.Reresolved(FAIL, True)


def test_unreadable_ancestor_on_reresolve_is_failed_without_rescan(window: Window) -> None:
    with window.census() as census:
        remove_entries(window.root)
        census.release_entries()

        def denying(name: str, flags: int, *args: Any, **kwargs: Any) -> int:
            if name == 'declared':
                raise OSError(errno.EIO, 'io')
            return os.open(name, flags, *args, **kwargs)

        assert ra.fact_reresolved(census, window.m0, opener=denying) == ra.Reresolved(FAIL, False)


# The path changes between fact 4's first and second walk: never NEG.
def test_ancestor_renamed_between_lookups_is_caught_by_the_second_walk(window: Window) -> None:
    with window.census() as census:
        remove_entries(window.root)
        census.release_entries()
        fired = []

        def racing(name: str, flags: int, *args: Any, **kwargs: Any) -> int:
            if name == 'removed-root' and not fired:
                fired.append(1)
                os.rename(window.tmp / 'declared', window.tmp / 'declared-old')
                (window.tmp / 'declared' / 'removed-root').mkdir(parents=True)
                (window.tmp / 'declared' / 'removed-root' / 'remnant').write_bytes(b'x')
            return os.open(name, flags, *args, **kwargs)

        assert ra.fact_reresolved(census, window.m0, opener=racing) == ra.Reresolved(FAIL, True)
        assert fired


# A18: after "unmount" the path must be the LIVE M0 and empty.
def test_nonempty_mountpoint_is_present_and_rescanned(window: Window) -> None:
    with window.census() as census:
        remove_entries(window.root)
        census.release_entries()
        (window.root / 'recreated').write_bytes(b'x')
        assert ra.fact_reresolved(census, window.m0) == ra.Reresolved(SURV, True)


def test_replacement_directory_is_not_m0_and_is_rescanned(window: Window) -> None:
    with window.census() as census:
        remove_entries(window.root)
        census.release_entries()
        # Rename the original aside (its inode stays live), then replace it.
        os.rename(window.root, window.tmp / 'declared' / 'original-m0')
        window.root.mkdir()
        assert ra.fact_reresolved(census, window.m0) == ra.Reresolved(SURV, True)


def test_absent_final_component_is_failed(window: Window) -> None:
    with window.census() as census:
        remove_entries(window.root)
        census.release_entries()
        os.rmdir(window.root)
        assert ra.fact_reresolved(census, window.m0) == ra.Reresolved(FAIL, False)


# A missing or failed M0 record is never permission to confirm absence.
def test_missing_m0_record_is_failed(window: Window) -> None:
    with window.census() as census:
        remove_entries(window.root)
        census.release_entries()
        assert ra.fact_reresolved(census, None) == ra.Reresolved(FAIL, False)
        os.rmdir(window.root)
        assert ra.fact_reresolved(census, None) == ra.Reresolved(FAIL, False)


def test_failed_m0_recording_is_none(tmp_path: Path) -> None:
    root = tmp_path.resolve() / 'declared' / 'removed-root'
    root.mkdir(parents=True)

    def denying(name: str, flags: int, *args: Any, **kwargs: Any) -> int:
        if name == 'removed-root':
            raise PermissionError(errno.EACCES, 'denied')
        return os.open(name, flags, *args, **kwargs)

    before = open_fds()
    assert ra.record_mountpoint(root, generation=object(), opener=denying) is None
    (root / 'x').write_bytes(b'x')
    assert ra.record_mountpoint(root, generation=object()) is None  # not empty
    assert open_fds() == before


def test_closed_m0_record_is_failed(window: Window) -> None:
    with window.census() as census:
        remove_entries(window.root)
        census.release_entries()
        window.m0.close()
        assert ra.fact_reresolved(census, window.m0) == ra.Reresolved(FAIL, False)


# A16: bounds and the descriptor budget: incomplete, never truncated.
def test_census_over_entry_bound_is_incomplete(window: Window) -> None:
    with window.census(max_entries=2) as census:
        assert not census.complete
        assert ra.fact_unlinked(census) is FAIL


def test_census_over_depth_bound_is_incomplete(window: Window) -> None:
    with window.census(max_depth=1) as census:
        assert not census.complete


@pytest.mark.parametrize('bounds', [{'max_entries': 0}, {'max_entries': 10**6}, {'max_depth': 0},
                                    {'max_depth': 10**6}])
def test_unsupported_bounds_are_refused(window: Window, bounds: dict[str, int]) -> None:
    with pytest.raises(ra.CensusRefused):
        window.census(**bounds)


def test_descriptor_budget_refuses_an_impossible_census() -> None:
    import resource
    assert ra.fd_budget_ok(1, 1)
    if resource.getrlimit(resource.RLIMIT_NOFILE)[0] != resource.RLIM_INFINITY:
        assert not ra.fd_budget_ok(10**9, 1)


def test_emfile_partway_through_a_census_fails_and_leaks_nothing(window: Window) -> None:
    opened = []
    # `/` plus every component resolve first; fail three opens into the walk.
    limit = len(window.root.parts) + 3

    def exhausting(name: str, flags: int, *args: Any, **kwargs: Any) -> int:
        if len(opened) >= limit:
            raise OSError(errno.EMFILE, 'too many')
        opened.append(name)
        return os.open(name, flags, *args, **kwargs)

    before = open_fds()
    census = window.census(opener=exhausting)
    assert not census.complete and len(opened) == limit and census.entries >= 1
    assert ra.fact_unlinked(census) is FAIL
    census.close()
    assert open_fds() == before


@pytest.mark.parametrize('where', ['slash', 'root', 'first-entry'])
def test_fstat_failure_after_open_leaks_nothing(window: Window, monkeypatch: pytest.MonkeyPatch,
                                                where: str) -> None:
    # fstat order: `/`, each component (the last is the root), then entries.
    nth = {'slash': 1, 'root': len(window.root.parts), 'first-entry': len(window.root.parts) + 1}[where]
    calls = []
    real = os.fstat

    def failing(fd: int) -> os.stat_result:
        calls.append(fd)
        if len(calls) == nth:
            raise OSError(errno.EIO, 'io')
        return real(fd)

    before = open_fds()
    monkeypatch.setattr(ra, '_fstat', failing)
    census = window.census()
    monkeypatch.setattr(ra, '_fstat', real)
    assert not census.complete
    census.close()
    assert open_fds() == before


def test_listing_failure_mid_iteration_fails_and_leaks_nothing(window: Window,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    real = os.scandir

    class Failing:
        def __init__(self, fd: int) -> None:
            self.inner = real(fd)

        def __enter__(self) -> Iterator[Any]:
            def gen() -> Iterator[Any]:
                for index, entry in enumerate(self.inner):
                    if index == 1:
                        raise OSError(errno.EIO, 'io')
                    yield entry
            return gen()

        def __exit__(self, *exc: object) -> None:
            self.inner.close()

    before = open_fds()
    monkeypatch.setattr(ra, '_scandir', Failing)
    census = window.census()
    monkeypatch.setattr(ra, '_scandir', real)
    assert not census.complete
    census.close()
    assert open_fds() == before


def test_unexpected_exception_closes_every_descriptor(window: Window) -> None:
    def exploding(name: str, flags: int, *args: Any, **kwargs: Any) -> int:
        if name == 'auth.json':
            raise RuntimeError('unexpected')
        return os.open(name, flags, *args, **kwargs)

    before = open_fds()
    with pytest.raises(RuntimeError):
        window.census(opener=exploding)
    assert open_fds() == before


@pytest.mark.parametrize('kind', ['symlink', 'fifo'])
def test_special_entry_makes_the_census_incomplete(window: Window, kind: str) -> None:
    special = window.root / 'home' / 'special'
    if kind == 'symlink':
        special.symlink_to(window.tmp)
    else:
        os.mkfifo(special)
    with window.census() as census:
        assert not census.complete
        assert ra.fact_unlinked(census) is FAIL


def test_symlinked_ancestor_is_never_followed(tmp_path: Path) -> None:
    tmp = tmp_path.resolve()
    (tmp / 'real' / 'removed-root').mkdir(parents=True)
    (tmp / 'link').symlink_to(tmp / 'real')
    with ra.take_census(tmp / 'link' / 'removed-root', generation=object(),
                        max_entries=LIMIT) as census:
        assert not census.complete


# A15 (in part; full matching is A-3): bound to one generation by IDENTITY.
class EqualToEverything:
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 0


def test_census_and_m0_are_bound_by_generation_identity(tmp_path: Path) -> None:
    gen = EqualToEverything()
    w = Window(tmp_path, generation=gen)
    impostor = EqualToEverything()
    try:
        with w.census() as census:
            assert census.belongs_to(gen)
            assert gen == impostor and not census.belongs_to(impostor)
            remove_entries(w.root)
            census.release_entries()
            # The same path recorded under an equal-but-distinct generation.
            os.rename(w.root, w.tmp / 'declared' / 'aside')
            w.root.mkdir()
            other = ra.record_mountpoint(w.root, generation=impostor)
            assert other is not None
            try:
                os.rmdir(w.root)
                os.rename(w.tmp / 'declared' / 'aside', w.root)
                assert ra.fact_reresolved(census, other) == ra.Reresolved(FAIL, False)
                assert ra.fact_reresolved(census, w.m0).observation is NEG
            finally:
                other.close()
    finally:
        w.m0.close()


def test_facts_refuse_out_of_order_use(window: Window) -> None:
    census = window.census()
    assert ra.fact_reresolved(census, window.m0).observation is FAIL  # entries still held
    census.release_entries()
    assert ra.fact_unlinked(census) is FAIL  # descriptors released: fact 1 unreadable
    census.close()
    assert not census.complete


def test_entry_replaced_under_its_held_identity_is_failed(window: Window) -> None:
    with window.census() as census:
        fd = census._entries[0].fd
        other = os.open(str(window.tmp), os.O_RDONLY)
        os.dup2(other, fd)
        os.close(other)
        assert ra.fact_unlinked(census) is FAIL


# Descriptor ownership: release then close never touches a reused number.
def test_released_descriptor_numbers_are_never_closed_again(window: Window) -> None:
    census = window.census()
    released = {item.fd for item in census._entries}
    census.release_entries()
    reused: list[int] = []
    while not released & set(reused) and len(reused) < 512:
        reused.append(os.open(str(window.tmp), os.O_RDONLY))
    try:
        assert released & set(reused), 'the kernel should hand back a released number'
        census.close()
        census.close()
        for fd in reused:
            os.fstat(fd)  # Still open and owned by this test.
    finally:
        for fd in reused:
            os.close(fd)


@pytest.mark.parametrize('bad', ['relative/path', '/a/../b', '/', '/nul\0byte'])
def test_declared_path_must_be_plain_absolute(bad: str) -> None:
    with pytest.raises(ra.CensusRefused):
        ra.take_census(bad, generation=object())


def test_census_needs_a_generation(tmp_path: Path) -> None:
    with pytest.raises(ra.CensusRefused):
        ra.take_census(tmp_path.resolve(), generation=None)


# HeldTree: the scan follows the held object, not the path.
def test_held_tree_reads_the_held_root_after_the_path_moves(tmp_path: Path) -> None:
    tmp = tmp_path.resolve()
    root = tmp / 'retained'
    root.mkdir()
    (root / 'out.txt').write_bytes(b'held-bytes')
    held = ra.open_held_root(root)
    assert held is not None
    fd = held[0]
    try:
        tree = ra.HeldTree(fd)
        os.rename(root, tmp / 'moved')
        root.mkdir()
        (root / 'out.txt').write_bytes(b'decoy')
        assert tree.listdir('') == [('out.txt', 'file')]
        assert tree.read('out.txt')[0] == b'held-bytes'
        tree.close()
        tree.close()
        with pytest.raises(Unreadable):
            tree.listdir('')
    finally:
        os.close(fd)


def test_held_tree_never_follows_a_link_and_errors_are_fixed_text(tmp_path: Path) -> None:
    tmp = tmp_path.resolve()
    root = tmp / 'retained'
    root.mkdir()
    (root / 'link-name').symlink_to(tmp)
    held = ra.open_held_root(root)
    assert held is not None
    try:
        tree = ra.HeldTree(held[0])
        assert tree.kind('link-name') == 'other'
        with pytest.raises(Unreadable) as caught:
            tree.read('link-name')
        assert 'link-name' not in str(caught.value)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        tree.close()
    finally:
        os.close(held[0])


def test_held_tree_refuses_a_non_directory(tmp_path: Path) -> None:
    f = tmp_path.resolve() / 'file'
    f.write_bytes(b'x')
    fd = os.open(f, os.O_RDONLY)
    try:
        with pytest.raises(Unreadable):
            ra.HeldTree(fd)
    finally:
        os.close(fd)


def test_open_held_root_refuses_a_symlinked_root(tmp_path: Path) -> None:
    tmp = tmp_path.resolve()
    (tmp / 'real').mkdir()
    (tmp / 'alias').symlink_to(tmp / 'real')
    assert ra.open_held_root(tmp / 'alias') is None
