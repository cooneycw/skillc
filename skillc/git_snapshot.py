"""A pure-Python, read-only reader of git state in an EXPORTED tree (#434).

A live attempt's repository and remote are subject-writable. Running git on
them as the controller - even on an exported copy - would let subject-chosen
config, hooks, replace refs or grafts run or steer code on the host, which
#434's hard item forbids. After the attempt stops (when nothing can be run
inside its containment any more), this module answers the questions the
grader and the fixture service still need by interpreting the RAW BYTES
itself. It never starts a git process, and nothing the subject wrote is
consulted as configuration: refs, objects and the index are read as data.

What it reads:

  - refs: loose refs under `refs/` and `packed-refs`, symbolic refs one hop,
    and each linked worktree's PRIVATE refs (`.git/worktrees/<n>/refs/...`:
    `refs/worktree`, `refs/bisect`, `refs/rewritten`), which `rev-list --all`
    walks too;
  - HEAD of the repository and of each linked worktree, cross-checked both
    ways: the registration's `gitdir` must name the checkout, and the
    checkout's own `.git` pointer must name the registration;
  - LOOSE objects only: a complete zlib stream, hash-checked, size-capped;
    commit reachability and tree expansion run under shared work budgets;
  - the index, versions 2 and 3, checksummed, with its extensions walked:
    optional (uppercase) ones are skipped, a mandatory (lowercase) one such
    as split-index `link` is refused; merge stages and intent-to-add are
    kept as distinct states, never folded into a clean entry;
  - working-tree file bytes and modes.

Anything it cannot read faithfully raises `Unreadable`, which callers report
as UNKNOWN - never as a clean answer. That includes every malformed byte the
subject can write: no parse failure escapes as another exception type.

  - an object that is not loose. git leaves a pushed or fetched pack in place
    once it carries more than `transfer.unpackLimit` objects (default 100)
    and unpacks smaller ones, so a fixture-sized attempt stays loose; a
    subject `git gc` or a large push packs objects and makes the read UNKNOWN
    (orchestrator condition on #434 PR 2: PR 3 counts these separately);
  - index version 4, a mandatory extension, an unknown extended flag, a
    duplicate entry, or a checksum mismatch;
  - alternates, a worktree `commondir` other than `../..`, a `gitdir` outside
    the declared container root, a checkout pointer that does not name its
    registration, or two registrations for one checkout;
  - a symlink, FIFO, device or socket anywhere it reads (every component is
    opened with O_NOFOLLOW, and files with O_NONBLOCK, so a planted FIFO
    cannot block the read), an entry it cannot open, or a file past the cap.
    Only a genuinely ABSENT path reads as absent.

`SnapshotGitRemote` serves this reader as a read-only `GitRemote` (#276) for
`FixtureService.finalize`'s divergence check: `resolve` loads and validates
the commit it names, `is_ancestor` walks loose history; every write raises.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_OBJECT_BYTES = 16 * 1024 * 1024
#: Shared budgets for one reader: commits walked, tree entries expanded
#: (across every tree), tree depth. A compact tree DAG can expand
#: exponentially, so object-size caps alone do not bound the work.
MAX_WALK = 50_000
MAX_TREE_ENTRIES = 200_000
MAX_TREE_DEPTH = 64
_SHA = re.compile(r"[0-9a-f]{40}")
#: Extended index flags (index v3): intent-to-add and skip-worktree; any
#: other extended bit is refused rather than ignored.
_CE_INTENT_TO_ADD = 0x2000
_CE_SKIP_WORKTREE = 0x4000


class Unreadable(Exception):
    """This state cannot be read faithfully from raw bytes; report UNKNOWN."""


class SafeTree:
    """Read-only, no-follow access below one exported root directory."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
        try:
            info = os.lstat(self.root)
        except OSError as exc:
            raise Unreadable(f"the export root cannot be read: {exc}") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise Unreadable("the export root is not a directory")

    def _parts(self, rel: str) -> list[str]:
        parts = [p for p in PurePosixPath(rel).parts if p not in ("", ".")]
        if any(p == ".." or "/" in p for p in parts):
            raise Unreadable(f"unsafe path {rel!r}")
        return parts

    def _open_dir(self, parts: list[str]) -> int:
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
        except OSError as exc:
            os.close(fd)
            raise Unreadable(f"cannot open directory {'/'.join(parts)!r}: {exc}") from exc
        return fd

    def kind(self, rel: str) -> str:
        """'file', 'dir', 'missing' or 'other' (link, FIFO, device...).

        'missing' only when the path is genuinely ABSENT: every existing
        parent is a real directory and one component does not exist. A parent
        that cannot be opened, or is a link, raises Unreadable - inaccessible
        is never absent (pass 1)."""
        parts = self._parts(rel)
        if not parts:
            return "dir"
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for index, part in enumerate(parts):
                try:
                    info = os.stat(part, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    return "missing"
                except OSError as exc:
                    raise Unreadable(f"cannot inspect {'/'.join(parts[:index + 1])!r}: {exc}") from exc
                if index == len(parts) - 1:
                    if stat.S_ISREG(info.st_mode):
                        return "file"
                    if stat.S_ISDIR(info.st_mode):
                        return "dir"
                    return "other"
                if not stat.S_ISDIR(info.st_mode):
                    if stat.S_ISREG(info.st_mode):
                        return "missing"  # a file where a directory would be: the path cannot exist
                    raise Unreadable(f"{'/'.join(parts[:index + 1])!r} is not a plain directory")
                try:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except OSError as exc:
                    raise Unreadable(f"cannot open {'/'.join(parts[:index + 1])!r}: {exc}") from exc
                os.close(fd)
                fd = nxt
        finally:
            os.close(fd)
        raise AssertionError("unreachable")

    def optional(self, rel: str) -> bool:
        """True for a regular file, False when absent, Unreadable otherwise:
        a link or FIFO where git expects metadata is never 'not there'."""
        kind = self.kind(rel)
        if kind == "file":
            return True
        if kind == "missing":
            return False
        raise Unreadable(f"{rel!r} exists but is not a regular file")

    def read(self, rel: str, limit: int = MAX_FILE_BYTES) -> tuple[bytes, int]:
        """`(bytes, st_mode)` of a REGULAR file; anything else is Unreadable."""
        parts = self._parts(rel)
        if not parts:
            raise Unreadable("cannot read the export root as a file")
        fd = self._open_dir(parts[:-1])
        try:
            try:
                ffd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            except OSError as exc:
                raise Unreadable(f"cannot open {rel!r} as a plain file: {exc}") from exc
            try:
                info = os.fstat(ffd)
                if not stat.S_ISREG(info.st_mode):
                    raise Unreadable(f"{rel!r} is not a regular file")
                if info.st_size > limit:
                    raise Unreadable(f"{rel!r} is {info.st_size} bytes, over the {limit}-byte cap")
                chunks, total = [], 0
                while True:
                    chunk = os.read(ffd, 1 << 16)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise Unreadable(f"{rel!r} grew past the {limit}-byte cap while read")
                    chunks.append(chunk)
                return b"".join(chunks), info.st_mode
            except OSError as exc:
                raise Unreadable(f"cannot read {rel!r}: {exc}") from exc
            finally:
                os.close(ffd)
        finally:
            os.close(fd)

    def text(self, rel: str) -> str:
        data, _ = self.read(rel, 1 << 20)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Unreadable(f"{rel!r} is not UTF-8") from exc

    def listdir(self, rel: str) -> list[tuple[str, str]]:
        """`[(name, kind)]` of a directory, without following anything."""
        fd = self._open_dir(self._parts(rel))
        try:
            out = []
            with os.scandir(fd) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    kind = ("file" if stat.S_ISREG(info.st_mode) else "dir" if stat.S_ISDIR(info.st_mode)
                            else "other")
                    out.append((entry.name, kind))
            return sorted(out)
        except OSError as exc:
            raise Unreadable(f"cannot list {rel!r}: {exc}") from exc
        finally:
            os.close(fd)


def _join(*parts: str) -> str:
    return "/".join(p.strip("/") for p in parts if p.strip("/"))


def _ascii(data: bytes, what: str) -> str:
    try:
        return data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise Unreadable(f"{what} is not ASCII") from exc


@dataclass
class _Budget:
    commits: int = 0
    tree_entries: int = 0


@dataclass
class GitDir:
    """One git directory (a repository's common dir) inside a SafeTree."""

    tree: SafeTree
    path: str  # relative to the export root, e.g. "repo/.git" or ".remote/widget.git"
    _budget: _Budget = field(default_factory=_Budget, repr=False)

    def _p(self, *rest: str) -> str:
        return _join(self.path, *rest)

    def check_plain(self) -> None:
        for name in ("objects/info/alternates", "objects/info/http-alternates", "commondir"):
            if self.tree.kind(self._p(name)) != "missing":
                raise Unreadable(f"{self.path}: carries {name}, which redirects where objects or refs live")

    def refs(self) -> dict[str, str]:
        refs: dict[str, str] = {}
        if self.tree.optional(self._p("packed-refs")):
            for line in self.tree.text(self._p("packed-refs")).splitlines():
                if not line or line.startswith(("#", "^")):
                    continue
                sha, _, name = line.partition(" ")
                if not _SHA.fullmatch(sha) or not name.startswith("refs/"):
                    raise Unreadable(f"{self.path}: malformed packed-refs line {line[:80]!r}")
                refs[name] = sha
        loose: dict[str, str] = {}
        self._walk_refs(self.path, "refs", loose)
        refs.update(loose)
        return {name: self._resolve_value(name, value, refs) for name, value in sorted(refs.items())}

    def private_refs(self, gitdir: str) -> dict[str, str]:
        """A linked worktree's own refs (`<gitdir>/refs/...`), resolved
        against the common refs - git walks these for `rev-list --all`."""
        out: dict[str, str] = {}
        self._walk_refs(gitdir, "refs", out)
        common = self.refs()
        return {f"{gitdir}/{name}": self._resolve_value(name, value, common) for name, value in sorted(out.items())}

    def _walk_refs(self, base: str, rel: str, out: dict[str, str]) -> None:
        kind = self.tree.kind(_join(base, rel))
        if kind == "missing":
            return
        if kind != "dir":
            raise Unreadable(f"{base}/{rel} is not a directory")
        for name, entry_kind in self.tree.listdir(_join(base, rel)):
            child = f"{rel}/{name}"
            if entry_kind == "dir":
                self._walk_refs(base, child, out)
            elif entry_kind == "file":
                if name.endswith(".lock"):
                    continue  # git ignores lock files
                out[child] = self.tree.text(_join(base, child)).strip()
            else:
                raise Unreadable(f"{base}: ref {child} is not a plain file")

    @staticmethod
    def _resolve_value(name: str, value: str, refs: dict[str, str]) -> str:
        if _SHA.fullmatch(value):
            return value
        if value.startswith("ref: "):
            target = refs.get(value[5:].strip())
            if target is not None and _SHA.fullmatch(target):
                return target
        raise Unreadable(f"ref {name} holds {value[:60]!r}, not a commit id")

    def head(self, gitdir: str | None = None, refs: dict[str, str] | None = None) -> tuple[str, str | None]:
        """`(sha, branch)` of HEAD in `gitdir` (default: this common dir)."""
        raw = self.tree.text(_join(gitdir or self.path, "HEAD")).strip()
        if _SHA.fullmatch(raw):
            return raw, None
        if raw.startswith("ref: refs/heads/"):
            ref = raw[5:]
            all_refs = refs if refs is not None else self.refs()
            if ref not in all_refs:
                raise Unreadable(f"HEAD names {ref}, which does not exist")
            return all_refs[ref], ref.removeprefix("refs/heads/")
        raise Unreadable(f"HEAD holds {raw[:60]!r}")

    def object(self, sha: str) -> tuple[str, bytes]:
        if not _SHA.fullmatch(sha):
            raise Unreadable(f"{sha!r} is not an object id")
        rel = self._p("objects", sha[:2], sha[2:])
        if self.tree.kind(rel) != "file":
            pack_dir = self._p("objects/pack")
            packed = self.tree.kind(pack_dir) == "dir" and any(
                n.endswith(".pack") for n, _ in self.tree.listdir(pack_dir))
            raise Unreadable(f"object {sha[:10]} is not loose in {self.path} "
                             f"({'objects are packed' if packed else 'it is absent'})")
        compressed, _ = self.tree.read(rel, MAX_OBJECT_BYTES)
        try:
            inflater = zlib.decompressobj()
            data = inflater.decompress(compressed, MAX_OBJECT_BYTES + 64)
            if inflater.unconsumed_tail:
                raise Unreadable(f"object {sha[:10]} inflates past the cap")
            # Pass 1: a stream cut before its checksum can still emit the
            # whole payload; only a COMPLETE stream with nothing after it counts.
            if not inflater.eof or inflater.unused_data:
                raise Unreadable(f"object {sha[:10]} is not one complete zlib stream")
        except zlib.error as exc:
            raise Unreadable(f"object {sha[:10]} does not inflate: {exc}") from exc
        if hashlib.sha1(data).hexdigest() != sha:
            raise Unreadable(f"object {sha[:10]} does not hash to its name")
        header, sep, payload = data.partition(b"\0")
        kind, _, size = _ascii(header, f"object {sha[:10]}'s header").partition(" ")
        if not sep or kind not in ("commit", "tree", "blob", "tag") or not size.isdigit() \
                or int(size) != len(payload):
            raise Unreadable(f"object {sha[:10]} has a malformed header")
        return kind, payload

    def parents(self, sha: str) -> list[str]:
        kind, payload = self.object(sha)
        if kind != "commit":
            raise Unreadable(f"{sha[:10]} is a {kind}, not a commit")
        out = []
        for line in payload.split(b"\n"):
            if not line:
                break
            if line.startswith(b"parent "):
                parent = _ascii(line[7:], f"commit {sha[:10]}'s parent line")
                if not _SHA.fullmatch(parent):
                    raise Unreadable(f"commit {sha[:10]} has a malformed parent line")
                out.append(parent)
        return out

    def tree_of(self, commit: str) -> str:
        kind, payload = self.object(commit)
        if kind != "commit" or not payload.startswith(b"tree ") or payload[45:46] != b"\n":
            raise Unreadable(f"{commit[:10]} has no well-formed tree line")
        tree = _ascii(payload[5:45], f"commit {commit[:10]}'s tree line")
        if not _SHA.fullmatch(tree):
            raise Unreadable(f"commit {commit[:10]} has a malformed tree id")
        return tree

    def tree_files(self, tree: str, prefix: str = "", depth: int = 0) -> dict[str, str]:
        """A tree object, recursively, as {path: "MODE BLOB"}, under the
        shared depth and entry budgets (pass 1: a branching DAG of a few
        hundred bytes must not expand without bound)."""
        if depth > MAX_TREE_DEPTH:
            raise Unreadable("a tree nests deeper than the depth cap")
        kind, payload = self.object(tree)
        if kind != "tree":
            raise Unreadable(f"{tree[:10]} is a {kind}, not a tree")
        files: dict[str, str] = {}
        i = 0
        while i < len(payload):
            space = payload.find(b" ", i)
            nul = payload.find(b"\0", space + 1) if space != -1 else -1
            if space == -1 or nul == -1 or nul + 21 > len(payload):
                raise Unreadable(f"tree {tree[:10]} has a malformed entry")
            mode = _ascii(payload[i:space], f"tree {tree[:10]}'s mode")
            try:
                name = payload[space + 1:nul].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise Unreadable(f"tree {tree[:10]} has a non-UTF-8 name") from exc
            if not name or "/" in name or name in (".", ".."):
                raise Unreadable(f"tree {tree[:10]} has an unsafe name {name!r}")
            sha = payload[nul + 1:nul + 21].hex()
            i = nul + 21
            self._budget.tree_entries += 1
            if self._budget.tree_entries > MAX_TREE_ENTRIES:
                raise Unreadable("tree expansion exceeds the entry budget")
            path = f"{prefix}{name}"
            if mode == "40000":
                files.update(self.tree_files(sha, path + "/", depth + 1))
            elif mode in ("100644", "100755", "120000", "160000"):
                files[path] = f"{mode} {sha}"
            else:
                raise Unreadable(f"tree {tree[:10]} has an unknown mode {mode!r}")
        return files

    def reachable(self, starts: list[str]) -> set[str]:
        seen: set[str] = set()
        stack = list(starts)
        while stack:
            sha = stack.pop()
            if sha in seen:
                continue
            seen.add(sha)
            self._budget.commits += 1
            if self._budget.commits > MAX_WALK:
                raise Unreadable("commit history exceeds the walk cap")
            stack.extend(self.parents(sha))
        return seen


def parse_index(data: bytes) -> dict[str, str]:
    """A version 2 or 3 index as {path: state}. A stage-0 entry's state is
    "MODE BLOB"; an intent-to-add entry is "intent-to-add MODE BLOB"; a path
    with merge stages is "unmerged stages=1,2,3". None of the non-clean states
    can equal a tree entry, so none can read as unchanged (pass 1: encoding
    the stage into the NAME could collide with a real path)."""
    try:
        return _parse_index(data)
    except (struct.error, IndexError, ValueError) as exc:
        raise Unreadable(f"the index is malformed: {exc}") from exc


def _parse_index(data: bytes) -> dict[str, str]:
    if len(data) < 32 or data[:4] != b"DIRC":
        raise Unreadable("the index has no DIRC signature")
    if hashlib.sha1(data[:-20]).digest() != data[-20:]:
        raise Unreadable("the index checksum does not match its content")
    version, count = struct.unpack(">II", data[4:12])
    if version not in (2, 3):
        raise Unreadable(f"index version {version} is not supported (only 2 and 3)")
    end = len(data) - 20
    seen: set[tuple[str, int]] = set()
    clean: dict[str, str] = {}
    stages: dict[str, set[int]] = {}
    offset = 12
    for _ in range(count):
        if offset + 62 > end:
            raise Unreadable("the index ends inside an entry")
        mode = struct.unpack(">I", data[offset + 24:offset + 28])[0]
        sha = data[offset + 40:offset + 60].hex()
        flags = struct.unpack(">H", data[offset + 60:offset + 62])[0]
        header = 62
        extended = 0
        if flags & 0x4000:
            if version < 3:
                raise Unreadable("an extended index flag in a version 2 index")
            extended = struct.unpack(">H", data[offset + 62:offset + 64])[0]
            if extended & ~(_CE_INTENT_TO_ADD | _CE_SKIP_WORKTREE):
                raise Unreadable(f"an unknown extended index flag {extended:#06x}")
            header += 2
        nul = data.find(b"\0", offset + header, end)
        if nul == -1:
            raise Unreadable("an index entry name has no terminator")
        try:
            name = data[offset + header:nul].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Unreadable("an index entry name is not UTF-8") from exc
        offset += (nul - offset + 8) // 8 * 8  # the name, then 1-8 NUL bytes of padding
        if offset > end:
            raise Unreadable("the index ends inside an entry's padding")
        stage = (flags >> 12) & 0x3
        if (name, stage) in seen:
            raise Unreadable(f"the index lists {name!r} at stage {stage} twice")
        seen.add((name, stage))
        if stage:
            stages.setdefault(name, set()).add(stage)
        else:
            state = f"{mode:06o} {sha}"
            clean[name] = f"intent-to-add {state}" if extended & _CE_INTENT_TO_ADD else state
    while offset < end:
        if offset + 8 > end:
            raise Unreadable("the index ends inside an extension header")
        signature = data[offset:offset + 4]
        size = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        if offset + 8 + size > end:
            raise Unreadable(f"index extension {signature!r} runs past the index")
        if not (65 <= signature[0] <= 90):  # lowercase first byte: git must understand it
            raise Unreadable(f"index extension {signature!r} is mandatory and not supported")
        offset += 8 + size
    out = dict(clean)
    for name, entry_stages in stages.items():
        out[name] = f"unmerged stages={','.join(map(str, sorted(entry_stages)))}"
    return out


def worktree_files(tree: SafeTree, root: str) -> dict[str, str]:
    """Every entry under a worktree but its `.git`, as {path: "MODE BLOB"};
    a non-regular entry is "not-a-file" (reported, never followed)."""
    files: dict[str, str] = {}

    def walk(rel: str) -> None:
        for name, kind in tree.listdir(_join(root, rel)):
            child = _join(rel, name)
            if not rel and name == ".git":
                continue
            if kind == "dir":
                walk(child)
            elif kind == "file":
                data, mode = tree.read(_join(root, child))
                blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
                files[child] = f"{'100755' if mode & 0o111 else '100644'} {blob}"
            else:
                files[child] = "not-a-file"

    walk("")
    return files


@dataclass(frozen=True)
class Worktree:
    path: str  # relative to the export root
    gitdir: str  # where its HEAD, index and private refs live
    head: str
    branch: str | None


def worktrees(common: GitDir, checkout: str, container_root: str, refs: dict[str, str]) -> list[Worktree]:
    """The checkout itself plus each linked worktree, from `.git/worktrees/*`.

    Both directions must agree (pass 1): the registration's `gitdir` names a
    checkout under `container_root`, and that checkout's own `.git` pointer
    names exactly this registration. `commondir` must be `../..`, and no two
    registrations may claim one checkout."""
    if common.tree.kind(_join(checkout, ".git")) != "dir":
        raise Unreadable(f"{checkout}/.git is not the repository directory")
    head, branch = common.head(refs=refs)
    out = [Worktree(checkout, common.path, head, branch)]
    registry = _join(common.path, "worktrees")
    kind = common.tree.kind(registry)
    if kind == "missing":
        return out
    if kind != "dir":
        raise Unreadable(f"{registry} is not a directory")
    root = container_root.rstrip("/") + "/"
    claimed = {checkout}
    for name, entry_kind in common.tree.listdir(registry):
        if entry_kind != "dir":
            raise Unreadable(f"worktrees/{name} is not a directory")
        meta = _join(registry, name)
        if common.tree.text(_join(meta, "commondir")).strip() != "../..":
            raise Unreadable(f"worktree {name}'s commondir does not point back at {common.path}")
        pointer = common.tree.text(_join(meta, "gitdir")).strip()
        if not pointer.startswith(root) or not pointer.endswith("/.git"):
            raise Unreadable(f"worktree {name}'s gitdir {pointer!r} is outside {container_root}")
        path = pointer[len(root):-len("/.git")]
        if not path or ".." in PurePosixPath(path).parts or path in claimed:
            raise Unreadable(f"worktree {name} claims {path!r}, which is unsafe or already claimed")
        claimed.add(path)
        back = common.tree.text(_join(path, ".git")).strip()
        expected = f"gitdir: {root}{meta}"
        if back != expected:
            raise Unreadable(f"{path}/.git points at {back[:80]!r}, not its registration {expected!r}")
        wt_head, wt_branch = common.head(meta, refs)
        out.append(Worktree(path, meta, wt_head, wt_branch))
    return sorted(out, key=lambda w: w.path)


class SnapshotGitRemote:
    """A READ-ONLY `GitRemote` (#276) over an exported bare remote: the
    fixture service's finalize-time divergence check, after the attempt has
    stopped. Writes are refused - an exported copy is evidence, never a
    place to act."""

    def __init__(self, tree: SafeTree, path: str) -> None:
        self._git = GitDir(tree, path)
        self._git.check_plain()

    def resolve(self, ref: str) -> str | None:
        """The commit a ref names, after LOADING and validating it (pass 1:
        a ref whose object is gone or corrupt is Unreadable, never a SHA
        accepted on its say-so). `None` only for a ref that does not exist."""
        sha = ref if _SHA.fullmatch(ref) else self._git.refs().get(ref)
        if sha is None:
            return None
        self._git.parents(sha)
        return sha

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return ancestor in self._git.reachable([descendant])

    def _refuse(self, *_: Any, **__: Any) -> Any:
        raise Unreadable("an exported snapshot is read-only; no git write may run against it")

    merge_base = diff_files = commits = merge_tree = commit_tree = update_ref = delete_ref = _refuse


__all__ = [
    "MAX_FILE_BYTES",
    "GitDir",
    "SafeTree",
    "SnapshotGitRemote",
    "Unreadable",
    "Worktree",
    "parse_index",
    "worktree_files",
    "worktrees",
]
