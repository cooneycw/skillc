"""Removed-root absence evidence, part 1: census, facts 1 and 4 (#797 A-1).

This is part of the owner-approved run-window contracts design
(docs/specs/evaluation-facility/run-window-contracts.md, section 2; #797). It
is SECRET-PATH scope: it holds descriptors and identities of credential-bearing
roots, though it never reads a credential's bytes.

This module provides the trusted controller's evidence for one removed-class
root:

- `record_mountpoint` records, at window open, the empty underlying
  directory (M0) a tmpfs will be mounted over. It keeps a LIVE descriptor to
  M0, so a recycled inode cannot later impersonate it.
- `take_census` resolves the declared path component by component from `/`,
  never following a link. It holds a descriptor for every ancestor and for the
  root, and an `O_PATH` descriptor for every entry beneath the root. For each
  object it records the kernel identity, mode and link count.
- `fact_unlinked` (fact 1) reads `st_nlink` through every held entry
  descriptor. Only all-zero is CONFIRMED_NEGATIVE: a renamed or hard-linked
  object keeps a nonzero count, which a path check cannot see.
- `fact_reresolved` (fact 4) re-walks the declared path from a fresh `/`,
  TWICE. Every ancestor must still be the object the census holds, and the
  final component must be the live M0 and empty, both times. A missing M0
  record is never permission to confirm absence.
- `HeldTree` is slice 4's bounded no-follow reader, rooted at a held directory
  descriptor instead of a path string, with fixed-text errors.

**Precondition: the controller is the only writer.** These observations are
evidence only inside the teardown boundary (design section 2.2, step 3; A-2),
which proves the holder domain empty before the census and keeps it empty
through fact 4. A concurrent writer could insert an entry after a directory
was listed, or rename an ancestor between two lookups. Fact 4's second walk
narrows the second race, but no walk excludes arbitrary concurrent mutation;
the boundary does.

Every observation is one of three outcomes. Only CONFIRMED_NEGATIVE can
contribute to ABSENT, and any failure to observe is OBSERVATION_FAILED, never a
zero. Evidence is in-memory only, with redacted reprs and opaque identities.
It refuses pickling and copying, and is bound to one generation object by
identity. No path, inode or device number enters a repr, an exception message
or a public attribute.

Out of this part's scope: the teardown boundary, facts 2, 2b and 3, and the
mount-table and alias evidence (A-2, keyed on the census's recorded root
device), and the composed release predicate and declaration (A-3). No removal,
unmount or Docker action is performed here, and no blocker is lifted. Linux
only: without O_PATH, every observation is OBSERVATION_FAILED.
"""
from __future__ import annotations

import enum
import errno
import os
import resource
import stat
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn, Self, SupportsIndex

from .git_snapshot import MAX_FILE_BYTES, Unreadable
from .remnant_scan import LIMITS, BoundedTree

_O_PATH = getattr(os, 'O_PATH', 0)
#: Descriptors kept free for the reader's own work while a census is held.
FD_RESERVE = 32
#: Indirections so tests can inject failures without patching the os module.
_fstat: Callable[[int], os.stat_result] = os.fstat
_scandir: Callable[[int], Any] = os.scandir

Opener = Callable[..., int]
_MOVED = (errno.ENOENT, errno.ENOTDIR, errno.ELOOP)


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

    __slots__ = ()

    def __reduce__(self) -> NoReturn:
        raise TypeError('run_window_absence evidence cannot be copied or pickled')

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError('run_window_absence evidence cannot be copied or pickled')

    def __copy__(self) -> NoReturn:
        raise TypeError('run_window_absence evidence cannot be copied or pickled')

    def __deepcopy__(self, memo: object) -> NoReturn:
        raise TypeError('run_window_absence evidence cannot be copied or pickled')


class Identity(_NoCopy):
    """An opaque kernel object identity: comparable, never displayed. It has
    no public device or inode attribute."""

    __slots__ = ('__key',)

    def __init__(self, info: os.stat_result) -> None:
        self.__key = (info.st_dev, info.st_ino)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Identity) and self.__key == other.__key

    def __hash__(self) -> int:
        return hash(self.__key)

    def __repr__(self) -> str:
        return '<Identity redacted>'


@dataclass(frozen=True, repr=False)
class _Held:
    fd: int
    identity: Identity
    mode: int
    nlink: int
    dev: int

    def __repr__(self) -> str:
        return '<Held redacted>'


def _components(path: str | os.PathLike[str]) -> list[str]:
    text: object = None
    try:
        text = os.fspath(path)
    except Exception:  # noqa: BLE001 - a caller's __fspath__ text is private
        text = None  # Not silent: refused just below, outside the handler.
    # Raised outside the handler, so the refusal carries no __context__ (a
    # caller's exception text could hold the very path being protected).
    if text is None:
        raise CensusRefused('run_window_absence: a declared root must be a path')
    if not isinstance(text, str) or not text.startswith('/') or '\0' in text:
        raise CensusRefused('run_window_absence: a declared root must be an absolute path')
    parts = [p for p in text.split('/') if p not in ('', '.')]
    if not parts or any(p == '..' for p in parts):
        raise CensusRefused('run_window_absence: a declared root must be a plain absolute path')
    return parts


def _close(fd: int) -> None:
    if fd < 0:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _open_held(opener: Opener, name: str, flags: int, dir_fd: int | None) -> _Held:
    """Open and fstat one object. The fd is closed here if fstat fails, so no
    descriptor escapes before the caller owns it."""
    # O_CLOEXEC explicitly (Python's default is non-inheritable too, but an
    # injected opener may not be): no docker/CLI child the controller spawns
    # can inherit a census descriptor. A child that somehow holds one counts
    # as a holder in fact 2, which is the fail-safe reading.
    flags |= os.O_CLOEXEC
    fd = opener(name, flags) if dir_fd is None else opener(name, flags, dir_fd=dir_fd)
    try:
        info = _fstat(fd)
    except BaseException:
        _close(fd)
        raise
    return _Held(fd, Identity(info), info.st_mode, info.st_nlink, info.st_dev)


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
    return entries + depth + 2 + open_now + FD_RESERVE <= soft


def _resolve(parts: list[str], opener: Opener) -> list[_Held]:
    """Hold `/` and every component as an O_PATH directory, never following a
    link. On any failure every descriptor opened here is closed."""
    held: list[_Held] = []
    try:
        held.append(_open_held(opener, '/', _O_PATH | os.O_DIRECTORY, None))
        for part in parts:
            item = _open_held(opener, part, _O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, held[-1].fd)
            held.append(item)
            if not stat.S_ISDIR(item.mode):
                raise OSError(errno.ENOTDIR, 'not a directory')
    except BaseException:
        for item in held:
            _close(item.fd)
        raise
    return held


class MountpointRecord(_NoCopy):
    """The empty underlying directory (M0), recorded at window open before the
    removed-class tmpfs is mounted over it. Holds a live descriptor to M0, so
    the identity compared in fact 4 cannot be a recycled inode."""

    def __init__(self, generation: object, parts: list[str], held: _Held) -> None:
        self._generation = generation
        self._parts = parts
        self._held: _Held | None = held

    def __repr__(self) -> str:
        return '<MountpointRecord redacted>'

    def close(self) -> None:
        if self._held is not None:
            _close(self._held.fd)
            self._held = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def record_mountpoint(path: str | os.PathLike[str], *, generation: object,
                      opener: Opener = os.open) -> MountpointRecord | None:
    """Record M0. None unless the path resolves, with no link anywhere on the
    way, to an EMPTY directory. fact_reresolved treats None as FAILED."""
    if generation is None or not _O_PATH:
        return None
    parts = _components(path)
    try:
        held = _resolve(parts, opener)
    except (OSError, ValueError):
        return None
    for item in held[:-1]:
        _close(item.fd)
    m0 = held[-1]
    record: MountpointRecord | None = None
    try:
        if _is_empty(m0.fd, opener):
            record = MountpointRecord(generation, parts, m0)
    except (OSError, ValueError):
        pass
    finally:
        if record is None:
            _close(m0.fd)  # Ownership moves to the record only when one is returned.
    return record


def _is_empty(dir_fd: int, opener: Opener) -> bool:
    listing = opener('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    try:
        with _scandir(listing) as entries:
            for _ in entries:
                return False
        return True
    finally:
        _close(listing)


class Census(_NoCopy):
    """Held evidence for one removed-class root. Built only by `take_census`."""

    def __init__(self, generation: object, parts: list[str]) -> None:
        self._generation = generation
        self._parts = parts
        self._ancestors: list[_Held] = []
        self._root: _Held | None = None
        #: st_dev of the root (the tmpfs superblock for a mounted root), kept
        #: private for A-2's mount-table and alias evidence. Never displayed.
        self._root_dev: int | None = None
        self._entries: list[_Held] = []
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
        """In-process composition guard: identity, never equality."""
        return generation is not None and self._generation is generation

    def release_entries(self) -> None:
        """Close the root and entry descriptors, which pin a tmpfs and must be
        closed before the unmount. The recorded identities, modes and link
        counts stay (A-2 reads the root's device); the fds are forgotten, so
        a later close can never hit a reused descriptor number. Ancestors stay
        held for fact 4."""
        if self._released:
            return
        for item in self._entries:
            _close(item.fd)
        if self._root is not None:
            _close(self._root.fd)
            self._root = _Held(-1, self._root.identity, self._root.mode, self._root.nlink, self._root.dev)
        self._entries = [_Held(-1, i.identity, i.mode, i.nlink, i.dev) for i in self._entries]
        self._released = True

    def close(self) -> None:
        if self._closed:
            return
        self.release_entries()
        for item in self._ancestors:
            _close(item.fd)
        self._ancestors = [_Held(-1, i.identity, i.mode, i.nlink, i.dev) for i in self._ancestors]
        self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def take_census(path: str | os.PathLike[str], *, generation: object,
                max_entries: int = LIMITS['entries'], max_depth: int = LIMITS['depth'],
                opener: Opener = os.open) -> Census:
    """Census of one removed-class root, taken inside the teardown boundary.

    The result is incomplete (and every fact reads OBSERVATION_FAILED) on any
    lookup error; on a link, FIFO, socket or device anywhere beneath the root;
    or when the entry, depth or descriptor bound would be exceeded. Nothing is
    ever dropped to fit. Any unexpected exception closes every descriptor
    before it propagates. `opener` is the trusted `os.open`-shaped adapter;
    tests inject failures through it.
    """
    if generation is None:
        raise CensusRefused('run_window_absence: a census needs a generation object')
    if (type(max_entries) is not int or type(max_depth) is not int
            or not 0 < max_entries <= LIMITS['entries'] or not 0 < max_depth <= LIMITS['depth']):
        raise CensusRefused('run_window_absence: census bounds exceed the supported limits')
    parts = _components(path)
    census = Census(generation, parts)
    if not _O_PATH or not fd_budget_ok(max_entries, len(parts)):
        return census
    try:
        try:
            held = _resolve(parts, opener)
        except (OSError, ValueError):
            return census
        census._ancestors = held[:-1]
        census._root = held[-1]
        census._root_dev = held[-1].dev
        try:
            census._complete = _walk(census, held[-1].fd, 0, max_entries, max_depth, opener)
        except (OSError, ValueError):
            census._complete = False
    except BaseException:
        census.close()
        raise
    return census


def _walk(census: Census, dir_fd: int, depth: int, max_entries: int, max_depth: int,
          opener: Opener) -> bool:
    if depth >= max_depth:
        return False
    remaining = max_entries - len(census._entries)
    names: list[str] = []
    listing = opener('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    try:
        with _scandir(listing) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > remaining:
                    return False  # Over budget: refuse before reading the rest.
    finally:
        _close(listing)
    for name in sorted(names):
        item = _open_held(opener, name, _O_PATH | os.O_NOFOLLOW, dir_fd)
        census._entries.append(item)
        if stat.S_ISDIR(item.mode):
            if not _walk(census, item.fd, depth + 1, max_entries, max_depth, opener):
                return False
        elif not stat.S_ISREG(item.mode):
            return False  # A link, FIFO, socket or device: never silently skipped.
    return True


def fact_unlinked(census: Census) -> Observation:
    """Fact 1: every held entry reads st_nlink 0 and is still the recorded
    object. The root itself is a tmpfs mountpoint and is covered by fact 3
    (A-2), not here."""
    if not census.complete or census._released:
        return FAIL
    survivor = False
    for item in census._entries:
        try:
            info = _fstat(item.fd)
        except OSError:
            return FAIL
        if Identity(info) != item.identity:
            return FAIL
        if info.st_nlink != 0:
            survivor = True
    return SURV if survivor else NEG


@dataclass(frozen=True)
class Reresolved:
    """Fact 4's outcome. `rescan` asks for the declared path to be scanned as
    a new population: a recreated root, a non-empty M0, or an ancestor that
    was replaced, removed or turned into a non-directory."""

    observation: Observation
    rescan: bool


def _reresolve_once(census: Census, m0: _Held, opener: Opener) -> Reresolved:
    held: list[int] = []
    try:
        try:
            current = _open_held(opener, '/', _O_PATH | os.O_DIRECTORY, None)
        except OSError:
            return Reresolved(FAIL, False)
        held.append(current.fd)
        if current.identity != census._ancestors[0].identity:
            return Reresolved(FAIL, True)
        for index, part in enumerate(census._parts[:-1]):
            try:
                current = _open_held(opener, part, _O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, held[-1])
            except OSError as exc:
                # Gone, or now a file or link: the path changed. Anything else
                # (EACCES, EIO, ...) is an unreadable ancestor, not a change.
                return Reresolved(FAIL, exc.errno in _MOVED)
            held.append(current.fd)
            if not stat.S_ISDIR(current.mode) or current.identity != census._ancestors[index + 1].identity:
                return Reresolved(FAIL, True)
        try:
            final = _open_held(opener, census._parts[-1], _O_PATH | os.O_NOFOLLOW, held[-1])
        except OSError:
            # Absent (or unreadable): the path is not the live M0, so fact 4
            # cannot hold; there is no population there to rescan.
            return Reresolved(FAIL, False)
        held.append(final.fd)
        if not stat.S_ISDIR(final.mode) or final.identity != Identity(_fstat(m0.fd)):
            return Reresolved(SURV, True)
        return Reresolved(NEG, False) if _is_empty(final.fd, opener) else Reresolved(SURV, True)
    except (OSError, ValueError):
        return Reresolved(FAIL, False)
    finally:
        for fd in held:
            _close(fd)


def fact_reresolved(census: Census, mountpoint: MountpointRecord | None, *,
                    opener: Opener = os.open) -> Reresolved:
    """Fact 4, after removal and unmount. The declared path is re-walked from
    a fresh `/` twice, and each walk compares against the LIVE descriptors the
    census and the M0 record still hold:

    - an ancestor replaced, removed or now not a directory: FAILED, rescan;
    - an ancestor that cannot be read: FAILED;
    - the final component not the live M0, or M0 not empty: PRESENT
      (SURVIVOR_OBSERVED, rescan);
    - the final component absent or unreadable: FAILED;
    - no usable M0 record, or a record from another generation or path:
      FAILED. There is no mode in which absence is confirmed without M0;
    - CONFIRMED_NEGATIVE only if both walks agree on it.
    """
    if (mountpoint is None or mountpoint._held is None or not census.complete
            or not census._released or not census._ancestors
            or mountpoint._generation is not census._generation
            or mountpoint._parts != census._parts):
        return Reresolved(FAIL, False)
    first = _reresolve_once(census, mountpoint._held, opener)
    if first.observation is not NEG:
        return first
    second = _reresolve_once(census, mountpoint._held, opener)
    if second.observation is not NEG:
        # The path changed between two walks: not evidence of anything.
        return Reresolved(FAIL, True)
    return first


class HeldTree(_NoCopy, BoundedTree):
    """Slice 4's bounded no-follow reader rooted at a held directory
    descriptor, so a later rename of the path cannot redirect the scan. Its
    errors are fixed text, raised outside the handler, so neither the message
    nor the exception chain carries a relative name."""

    def __init__(self, dir_fd: int) -> None:
        info = None
        try:
            info = _fstat(dir_fd)
        except OSError:
            pass
        if info is None:
            raise Unreadable('held root: unreadable')
        if not stat.S_ISDIR(info.st_mode):
            raise Unreadable('held root: not a directory')
        self._held = os.dup(dir_fd)
        self.root = '<held>'
        self.entries_listed = 0
        self.bytes_read = 0

    def __repr__(self) -> str:
        return '<HeldTree redacted>'

    def _start(self) -> int:
        if self._held < 0:
            raise Unreadable('held root: closed')
        try:
            return os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self._held)
        except OSError:
            pass
        raise Unreadable('held root: unreadable')

    def _require_open(self) -> None:
        if self._held < 0:
            raise Unreadable('held root: closed')

    def kind(self, rel: str) -> str:
        self._require_open()
        try:
            return super().kind(rel)
        except (Unreadable, OSError):
            pass
        raise Unreadable('held root: unreadable entry')

    def read(self, rel: str, limit: int = MAX_FILE_BYTES) -> tuple[bytes, int]:
        self._require_open()
        try:
            return super().read(rel, limit)
        except (Unreadable, OSError):
            pass
        raise Unreadable('held root: unreadable entry')

    def listdir(self, rel: str) -> list[tuple[str, str]]:
        self._require_open()
        try:
            return super().listdir(rel)
        except (Unreadable, OSError):
            pass
        raise Unreadable('held root: unreadable entry')

    def close(self) -> None:
        if self._held >= 0:
            _close(self._held)
            self._held = -1


def open_held_root(path: str | os.PathLike[str], *,
                   opener: Opener = os.open) -> tuple[int, Identity] | None:
    """Resolve a root no-follow from `/` and return a held descriptor and its
    opaque identity (the caller closes the fd), or None."""
    if not _O_PATH:
        return None
    try:
        held = _resolve(_components(path), opener)
    except (OSError, ValueError):
        return None
    for item in held[:-1]:
        _close(item.fd)
    return held[-1].fd, held[-1].identity
