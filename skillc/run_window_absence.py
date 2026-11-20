"""Removed-root absence evidence, part 1: census, facts 1 and 4 (#797 A-1).

This is part of the owner-approved run-window contracts design
(docs/specs/evaluation-facility/run-window-contracts.md, section 2; #797). It
is SECRET-PATH scope: it holds descriptors and identities of credential-bearing
roots, though it never reads a credential's bytes.

This module provides the trusted controller's evidence for one removed-class
root:

- `take_census` resolves the declared path component by component from a
  fresh `/`, never following a link. It holds a descriptor for every ancestor
  and the root, and an `O_PATH` descriptor for every entry beneath the root.
  For each object it records the kernel identity `(st_dev, st_ino)`.
- `fact_unlinked` (fact 1) reads `st_nlink` through every held entry
  descriptor. Only all-zero is CONFIRMED_NEGATIVE: a renamed or hard-linked
  object keeps a nonzero count, which a path check cannot see.
- `record_mountpoint` / `fact_reresolved` (fact 4) re-walk the declared path
  from `/`. Every ancestor must still be the recorded object, and the final
  component must be the recorded empty mountpoint (`M0`) or, with no recorded
  mountpoint, absent. A present root is never evidence that the original is
  gone; an ancestor that changed asks for the replacement to be scanned.
- `HeldTree` is slice 4's bounded no-follow reader, rooted at a held directory
  descriptor instead of a path string. A later rename of the path cannot
  redirect it.

Every observation is one of three outcomes. Only CONFIRMED_NEGATIVE can
contribute to ABSENT, and any failure to observe is OBSERVATION_FAILED, never a
zero. The census is in-memory only, with a redacted repr; it refuses pickling
and copying, and is bound to one opaque generation object by identity. No path,
inode or device number enters a repr, an exception message or a public value.

Out of this part's scope: the teardown boundary, facts 2, 2b and 3 (A-2), and
the composed release predicate and declaration (A-3). This module performs
no removal, unmount or Docker action, and lifts no blocker. Linux only: without
O_PATH, every observation is OBSERVATION_FAILED.
"""
from __future__ import annotations

import enum
import os
import resource
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NoReturn, SupportsIndex

from .git_snapshot import Unreadable
from .remnant_scan import LIMITS, BoundedTree

_O_PATH = getattr(os, 'O_PATH', 0)
#: Descriptors kept free for the reader's own work while a census is held.
FD_RESERVE = 32

Opener = Callable[..., int]


class Observation(enum.Enum):
    CONFIRMED_NEGATIVE = 'CONFIRMED_NEGATIVE'
    SURVIVOR_OBSERVED = 'SURVIVOR_OBSERVED'
    OBSERVATION_FAILED = 'OBSERVATION_FAILED'


NEG = Observation.CONFIRMED_NEGATIVE
SURV = Observation.SURVIVOR_OBSERVED
FAIL = Observation.OBSERVATION_FAILED


class CensusRefused(ValueError):
    """An invalid request; the message is fixed text with no path or identity."""


class _NoCopy:
    """Evidence is in-memory and process-local: never pickled or copied."""

    def __reduce__(self) -> NoReturn:
        raise TypeError('run_window_absence evidence cannot be copied or pickled')

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError('run_window_absence evidence cannot be copied or pickled')

    def __copy__(self) -> NoReturn:
        raise TypeError('run_window_absence evidence cannot be copied or pickled')

    def __deepcopy__(self, memo: object) -> NoReturn:
        raise TypeError('run_window_absence evidence cannot be copied or pickled')


@dataclass(frozen=True, repr=False)
class Identity(_NoCopy):
    """A kernel object identity. Redacted: no device or inode number is shown."""

    dev: int = field(repr=False)
    ino: int = field(repr=False)

    def __repr__(self) -> str:
        return '<Identity redacted>'



def _components(path: str | os.PathLike[str]) -> list[str]:
    text = os.fspath(path)
    if not isinstance(text, str) or not text.startswith('/') or '\0' in text:
        raise CensusRefused('run_window_absence: a declared root must be an absolute path')
    parts = [p for p in text.split('/') if p not in ('', '.')]
    if not parts or any(p == '..' for p in parts):
        raise CensusRefused('run_window_absence: a declared root must be a plain absolute path')
    return parts


def _identity(info: os.stat_result) -> Identity:
    return Identity(info.st_dev, info.st_ino)


def fd_budget_ok(entries: int, depth: int) -> bool:
    """Admission check: can a census of `entries` objects under `depth`
    ancestors be held, beside the descriptors already open and a reserve?
    An unreadable descriptor table is a refusal, never an assumed fit."""
    try:
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        open_now = len(os.listdir('/proc/self/fd'))
    except OSError:
        return False
    if soft == resource.RLIM_INFINITY:
        return True
    return entries + depth + 1 + open_now + FD_RESERVE <= soft


class Census(_NoCopy):
    """Held evidence for one removed-class root. Built only by `take_census`."""


    def __init__(self, generation: object, parts: list[str]) -> None:
        self._generation = generation
        self._parts = parts
        self._ancestors: list[tuple[int, Identity]] = []
        self._root: tuple[int, Identity] | None = None
        self._entries: list[tuple[int, Identity]] = []
        self._complete = False
        self._released = False
        self._closed = False

    def __repr__(self) -> str:
        return '<Census redacted>'

    @property
    def complete(self) -> bool:
        return self._complete and not self._closed

    @property
    def entries(self) -> int:
        return len(self._entries)

    def belongs_to(self, generation: object) -> bool:
        """In-process composition guard: identity, not equality."""
        return self._generation is generation and generation is not None

    def release_entries(self) -> None:
        """Close the root and entry descriptors (they pin a tmpfs, so they are
        closed before the unmount). Ancestors stay held for fact 4."""
        for fd, _ in self._entries:
            _close(fd)
        if self._root is not None:
            _close(self._root[0])
        self._released = True

    def close(self) -> None:
        if self._closed:
            return
        self.release_entries()
        for fd, _ in self._ancestors:
            _close(fd)
        self._closed = True

    def __enter__(self) -> Census:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _resolve(parts: list[str], opener: Opener) -> list[tuple[int, Identity]]:
    """Hold `/` and every component as an O_PATH directory descriptor, never
    following a link. The caller owns (and must close) the returned fds."""
    held: list[tuple[int, Identity]] = []
    try:
        fd = opener('/', _O_PATH | os.O_DIRECTORY)
        held.append((fd, _identity(os.fstat(fd))))
        for part in parts:
            nxt = opener(part, _O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=held[-1][0])
            info = os.fstat(nxt)
            held.append((nxt, _identity(info)))
            if not stat.S_ISDIR(info.st_mode):
                raise OSError('not a directory')
    except BaseException:
        for fd, _ in held:
            _close(fd)
        raise
    return held


def take_census(path: str | os.PathLike[str], *, generation: object,
                max_entries: int = LIMITS['entries'], max_depth: int = LIMITS['depth'],
                opener: Opener = os.open) -> Census:
    """Census of one removed-class root, taken after writers have stopped.

    The result is incomplete (and every fact reads OBSERVATION_FAILED) on any
    lookup error, on a link, FIFO, socket or device anywhere beneath the root,
    or when the entry or depth bound, or the descriptor budget, would be
    exceeded. Nothing is ever dropped to fit. `opener` is the trusted
    `os.open`-shaped adapter; tests inject failures through it.
    """
    if generation is None:
        raise CensusRefused('run_window_absence: a census needs a generation object')
    parts = _components(path)
    census = Census(generation, parts)
    if not _O_PATH:
        return census
    if not fd_budget_ok(max_entries, len(parts)):
        return census
    try:
        held = _resolve(parts, opener)
    except (OSError, ValueError):
        return census
    census._ancestors = held[:-1]
    census._root = held[-1]
    try:
        ok = _walk(census, held[-1][0], 0, max_entries, max_depth, opener)
    except (OSError, ValueError):
        ok = False
    census._complete = ok
    return census


def _walk(census: Census, dir_fd: int, depth: int, max_entries: int, max_depth: int,
          opener: Opener) -> bool:
    if depth >= max_depth:
        return False
    listing = opener('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        with os.scandir(listing) as entries:
            names = sorted(entry.name for entry in entries)
    finally:
        _close(listing)
    for name in names:
        if len(census._entries) >= max_entries:
            return False
        child = opener(name, _O_PATH | os.O_NOFOLLOW, dir_fd=dir_fd)
        info = os.fstat(child)
        census._entries.append((child, _identity(info)))
        if stat.S_ISDIR(info.st_mode):
            if not _walk(census, child, depth + 1, max_entries, max_depth, opener):
                return False
        elif not stat.S_ISREG(info.st_mode):
            return False  # A link, FIFO, socket or device: never silently skipped.
    return True


def fact_unlinked(census: Census) -> Observation:
    """Fact 1: every held entry reads st_nlink 0. The root itself is a tmpfs
    mountpoint and is covered by fact 3 (A-2), not here."""
    if not census.complete or census._released:
        return FAIL
    survivor = False
    for fd, ident in census._entries:
        try:
            info = os.fstat(fd)
        except OSError:
            return FAIL
        if _identity(info) != ident:
            return FAIL
        if info.st_nlink != 0:
            survivor = True
    return SURV if survivor else NEG


@dataclass(frozen=True, repr=False)
class MountpointRecord(_NoCopy):
    """The empty underlying directory (M0) recorded at window open, before the
    removed-class tmpfs was mounted over it."""

    _generation: object = field(repr=False)
    _parts: tuple[str, ...] = field(repr=False)
    _ancestors: tuple[Identity, ...] = field(repr=False)
    _identity: Identity = field(repr=False)

    def __repr__(self) -> str:
        return '<MountpointRecord redacted>'


def record_mountpoint(path: str | os.PathLike[str], *, generation: object,
                      opener: Opener = os.open) -> MountpointRecord | None:
    """Record M0. None (and so fact 4 OBSERVATION_FAILED later) unless the
    path resolves to an EMPTY directory with no link anywhere on the way."""
    if generation is None or not _O_PATH:
        return None
    parts = _components(path)
    try:
        held = _resolve(parts, opener)
    except (OSError, ValueError):
        return None
    try:
        listing = opener('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=held[-1][0])
        try:
            with os.scandir(listing) as entries:
                if any(True for _ in entries):
                    return None
        finally:
            _close(listing)
        return MountpointRecord(generation, tuple(parts), tuple(i for _, i in held[:-1]), held[-1][1])
    except (OSError, ValueError):
        return None
    finally:
        for fd, _ in held:
            _close(fd)


@dataclass(frozen=True)
class Reresolved:
    """Fact 4's outcome. `rescan` asks for the path to be scanned as a new
    population: a recreated root, a non-empty M0, or a replaced ancestor."""

    observation: Observation
    rescan: bool


def fact_reresolved(census: Census, mountpoint: MountpointRecord | None, *,
                    opener: Opener = os.open) -> Reresolved:
    """Fact 4, after removal and unmount. Re-walk the declared path from a
    fresh `/`:

    - any ancestor no longer the recorded object: OBSERVATION_FAILED (sticky),
      and the replacement path must be scanned;
    - with an M0 record: the path must be M0 and empty, or it is PRESENT
      (SURVIVOR_OBSERVED, rescan);
    - without one: the final component must be absent, or it is PRESENT;
    - any lookup error: OBSERVATION_FAILED.
    """
    if not census.complete or not census._released:
        return Reresolved(FAIL, False)
    if mountpoint is not None and (mountpoint._generation is not census._generation
                                   or list(mountpoint._parts) != census._parts):
        return Reresolved(FAIL, False)
    parts = census._parts
    recorded = [ident for _, ident in census._ancestors]
    held: list[int] = []
    try:
        fd = opener('/', _O_PATH | os.O_DIRECTORY)
        held.append(fd)
        if _identity(os.fstat(fd)) != recorded[0]:
            return Reresolved(FAIL, True)
        for index, part in enumerate(parts[:-1]):
            nxt = opener(part, _O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=held[-1])
            held.append(nxt)
            if _identity(os.fstat(nxt)) != recorded[index + 1]:
                return Reresolved(FAIL, True)
        if mountpoint is not None and tuple(recorded) != mountpoint._ancestors:
            return Reresolved(FAIL, True)
        try:
            final = opener(parts[-1], _O_PATH | os.O_NOFOLLOW, dir_fd=held[-1])
        except FileNotFoundError:
            return Reresolved(NEG, False) if mountpoint is None else Reresolved(SURV, True)
        held.append(final)
        info = os.fstat(final)
        if mountpoint is None or _identity(info) != mountpoint._identity or not stat.S_ISDIR(info.st_mode):
            return Reresolved(SURV, True)
        listing = opener('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=final)
        try:
            with os.scandir(listing) as entries:
                empty = not any(True for _ in entries)
        finally:
            _close(listing)
        return Reresolved(NEG, False) if empty else Reresolved(SURV, True)
    except (OSError, ValueError, IndexError):
        return Reresolved(FAIL, False)
    finally:
        for fd in held:
            _close(fd)


class HeldTree(_NoCopy, BoundedTree):
    """Slice 4's bounded no-follow reader rooted at a held directory
    descriptor, so a later rename of the path cannot redirect the scan."""

    def __init__(self, dir_fd: int) -> None:
        try:
            info = os.fstat(dir_fd)
        except OSError as exc:
            raise Unreadable('the held root cannot be read') from exc
        if not stat.S_ISDIR(info.st_mode):
            raise Unreadable('the held root is not a directory')
        self._held = os.dup(dir_fd)
        self.root = '<held>'
        self.entries_listed = 0
        self.bytes_read = 0

    def __repr__(self) -> str:
        return '<HeldTree redacted>'

    def _start(self) -> int:
        try:
            return os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self._held)
        except OSError as exc:
            raise Unreadable('the held root cannot be opened') from exc

    def close(self) -> None:
        _close(self._held)



def open_held_root(path: str | os.PathLike[str], *, opener: Opener = os.open) -> tuple[int, Identity] | None:
    """Resolve a root no-follow from `/` and return a held descriptor and its
    identity (the caller closes it), or None if it cannot be resolved."""
    if not _O_PATH:
        return None
    try:
        held = _resolve(_components(path), opener)
    except (OSError, ValueError):
        return None
    for fd, _ in held[:-1]:
        _close(fd)
    return held[-1]


def same_object(a: Identity, b: Identity) -> bool:
    return a == b


__all__: list[Any] = ['Observation', 'NEG', 'SURV', 'FAIL', 'CensusRefused', 'Identity', 'Census',
                      'fd_budget_ok', 'take_census', 'fact_unlinked', 'MountpointRecord',
                      'record_mountpoint', 'Reresolved', 'fact_reresolved', 'HeldTree',
                      'open_held_root', 'same_object']
