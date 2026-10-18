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

  - refs: loose refs under `refs/` and `packed-refs`; symbolic refs one hop;
  - HEAD of the repository and of each linked worktree
    (`.git/worktrees/<name>/{HEAD,gitdir,commondir}`);
  - LOOSE objects only (zlib), to walk commit reachability and read trees;
  - the index, versions 2 and 3;
  - working-tree file bytes and modes.

Anything it cannot read faithfully raises `Unreadable`, which callers report
as UNKNOWN - never as a clean answer:

  - an object that is not loose. git leaves a pushed or fetched pack in place
    once it carries more than `transfer.unpackLimit` objects (default 100)
    and unpacks smaller ones, so a fixture-sized attempt stays loose; a
    subject `git gc` or a large push packs objects and makes the read UNKNOWN
    (orchestrator condition on #434 PR 2: PR 3 counts these separately);
  - index version 4, a malformed index, or a checksum mismatch;
  - alternates, a worktree `commondir` other than `../..`, or a `gitdir`
    outside the declared container root;
  - a symlink, FIFO, device or socket anywhere it reads (every component is
    opened with O_NOFOLLOW, and files with O_NONBLOCK, so a planted FIFO
    cannot block the read), or a file past the size cap.

`SnapshotGitRemote` serves this reader as a read-only `GitRemote` (#276) for
`FixtureService.finalize`'s divergence check: `resolve` and `is_ancestor`
answer; every write raises.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import struct
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_OBJECT_BYTES = 16 * 1024 * 1024
MAX_WALK = 50_000
_SHA = re.compile(r"[0-9a-f]{40}")


class Unreadable(Exception):
    """This state cannot be read faithfully from raw bytes; report UNKNOWN."""


class SafeTree:
    """Read-only, no-follow access below one exported root directory."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
        info = os.lstat(self.root)
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
        """'file', 'dir', 'missing' or 'other' (link, FIFO, device...)."""
        parts = self._parts(rel)
        if not parts:
            return "dir"
        try:
            fd = self._open_dir(parts[:-1])
        except Unreadable:
            return "missing"
        try:
            info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return "missing"
        finally:
            os.close(fd)
        if stat.S_ISREG(info.st_mode):
            return "file"
        if stat.S_ISDIR(info.st_mode):
            return "dir"
        return "other"

    def read(self, rel: str, limit: int = MAX_FILE_BYTES) -> tuple[bytes, int]:
        """`(bytes, st_mode)` of a REGULAR file; anything else is Unreadable."""
        parts = self._parts(rel)
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
        finally:
            os.close(fd)


def _join(*parts: str) -> str:
    return "/".join(p.strip("/") for p in parts if p.strip("/"))


@dataclass(frozen=True)
class GitDir:
    """One git directory (a repository's common dir) inside a SafeTree."""

    tree: SafeTree
    path: str  # relative to the export root, e.g. "repo/.git" or ".remote/widget.git"

    def _p(self, *rest: str) -> str:
        return _join(self.path, *rest)

    def check_plain(self) -> None:
        for name in ("objects/info/alternates", "objects/info/http-alternates", "commondir"):
            if self.tree.kind(self._p(name)) != "missing":
                raise Unreadable(f"{self.path}: carries {name}, which redirects where objects or refs live")

    def refs(self) -> dict[str, str]:
        refs: dict[str, str] = {}
        if self.tree.kind(self._p("packed-refs")) == "file":
            for line in self.tree.text(self._p("packed-refs")).splitlines():
                if not line or line.startswith(("#", "^")):
                    continue
                sha, _, name = line.partition(" ")
                if not _SHA.fullmatch(sha) or not name.startswith("refs/"):
                    raise Unreadable(f"{self.path}: malformed packed-refs line {line!r}")
                refs[name] = sha
        loose: dict[str, str] = {}
        self._walk_refs("refs", loose)
        refs.update(loose)
        return {name: self._resolve_value(name, value, refs) for name, value in sorted(refs.items())}

    def _walk_refs(self, rel: str, out: dict[str, str]) -> None:
        if self.tree.kind(self._p(rel)) == "missing":
            return
        for name, kind in self.tree.listdir(self._p(rel)):
            child = f"{rel}/{name}"
            if kind == "dir":
                self._walk_refs(child, out)
            elif kind == "file":
                if name.endswith(".lock"):
                    continue  # git ignores lock files
                out[child] = self.tree.text(self._p(child)).strip()
            else:
                raise Unreadable(f"{self.path}: ref {child} is not a plain file")

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
            packed = self.tree.kind(self._p("objects/pack")) == "dir" and any(
                n.endswith(".pack") for n, _ in self.tree.listdir(self._p("objects/pack")))
            raise Unreadable(f"object {sha[:10]} is not loose in {self.path} "
                             f"({'objects are packed' if packed else 'it is absent'})")
        compressed, _ = self.tree.read(rel, MAX_OBJECT_BYTES)
        try:
            inflater = zlib.decompressobj()
            data = inflater.decompress(compressed, MAX_OBJECT_BYTES + 64)
            if inflater.unconsumed_tail:
                raise Unreadable(f"object {sha[:10]} inflates past the cap")
        except zlib.error as exc:
            raise Unreadable(f"object {sha[:10]} does not inflate: {exc}") from exc
        if hashlib.sha1(data).hexdigest() != sha:
            raise Unreadable(f"object {sha[:10]} does not hash to its name")
        header, _, payload = data.partition(b"\0")
        kind, _, size = header.decode("ascii", errors="replace").partition(" ")
        if not size.isdigit() or int(size) != len(payload):
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
                out.append(line[7:].decode("ascii"))
        return out

    def tree_of(self, commit: str) -> str:
        kind, payload = self.object(commit)
        if kind != "commit" or not payload.startswith(b"tree "):
            raise Unreadable(f"{commit[:10]} has no tree line")
        return payload[5:45].decode("ascii")

    def tree_files(self, tree: str, prefix: str = "") -> dict[str, str]:
        """A tree object, recursively, as {path: "MODE BLOB"}."""
        kind, payload = self.object(tree)
        if kind != "tree":
            raise Unreadable(f"{tree[:10]} is a {kind}, not a tree")
        files: dict[str, str] = {}
        i = 0
        while i < len(payload):
            space = payload.index(b" ", i)
            nul = payload.index(b"\0", space)
            mode = payload[i:space].decode("ascii")
            name = payload[space + 1:nul].decode("utf-8", errors="surrogateescape")
            sha = payload[nul + 1:nul + 21].hex()
            i = nul + 21
            path = f"{prefix}{name}"
            if mode == "40000":
                files.update(self.tree_files(sha, path + "/"))
            else:
                files[path] = f"{mode.zfill(6)} {sha}"
        return files

    def reachable(self, starts: list[str]) -> set[str]:
        seen: set[str] = set()
        stack = list(starts)
        while stack:
            sha = stack.pop()
            if sha in seen:
                continue
            seen.add(sha)
            if len(seen) > MAX_WALK:
                raise Unreadable("commit history exceeds the walk cap")
            stack.extend(self.parents(sha))
        return seen


def parse_index(data: bytes) -> dict[str, str]:
    """A version 2 or 3 index as {path: "MODE BLOB"}; a path at a non-zero
    merge stage is keyed "path@stageN" so a conflict never reads as clean."""
    if len(data) < 32 or data[:4] != b"DIRC":
        raise Unreadable("the index has no DIRC signature")
    if hashlib.sha1(data[:-20]).digest() != data[-20:]:
        raise Unreadable("the index checksum does not match its content")
    version, count = struct.unpack(">II", data[4:12])
    if version not in (2, 3):
        raise Unreadable(f"index version {version} is not supported (only 2 and 3)")
    entries: dict[str, str] = {}
    offset = 12
    end = len(data) - 20
    for _ in range(count):
        if offset + 62 > end:
            raise Unreadable("the index ends inside an entry")
        mode = struct.unpack(">I", data[offset + 24:offset + 28])[0]
        sha = data[offset + 40:offset + 60].hex()
        flags = struct.unpack(">H", data[offset + 60:offset + 62])[0]
        header = 62
        if flags & 0x4000:
            if version < 3:
                raise Unreadable("an extended index flag in a version 2 index")
            header += 2
        nul = data.index(b"\0", offset + header)
        name = data[offset + header:nul].decode("utf-8", errors="surrogateescape")
        length = header + len(name.encode("utf-8", errors="surrogateescape"))
        offset += (length + 8) // 8 * 8  # 1-8 NUL bytes of padding
        stage = (flags >> 12) & 0x3
        key = name if stage == 0 else f"{name}@stage{stage}"
        entries[key] = f"{mode:06o} {sha}"
    return entries


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
    gitdir: str  # where its HEAD and index live
    head: str
    branch: str | None


def worktrees(common: GitDir, checkout: str, container_root: str, refs: dict[str, str]) -> list[Worktree]:
    """The checkout itself plus each linked worktree, from `.git/worktrees/*`.
    A linked worktree's `gitdir` must name a path under `container_root`
    and its `commondir` must be `../..`, or the state is Unreadable."""
    head, branch = common.head(refs=refs)
    out = [Worktree(checkout, common.path, head, branch)]
    if common.tree.kind(_join(common.path, "worktrees")) == "missing":
        return out
    root = container_root.rstrip("/") + "/"
    for name, kind in common.tree.listdir(_join(common.path, "worktrees")):
        if kind != "dir":
            raise Unreadable(f"worktrees/{name} is not a directory")
        meta = _join(common.path, "worktrees", name)
        if common.tree.text(_join(meta, "commondir")).strip() != "../..":
            raise Unreadable(f"worktree {name}'s commondir does not point back at {common.path}")
        pointer = common.tree.text(_join(meta, "gitdir")).strip()
        if not pointer.startswith(root) or not pointer.endswith("/.git"):
            raise Unreadable(f"worktree {name}'s gitdir {pointer!r} is outside {container_root}")
        wt_head, wt_branch = common.head(meta, refs)
        out.append(Worktree(pointer[len(root):-len("/.git")], meta, wt_head, wt_branch))
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
        if _SHA.fullmatch(ref):
            self._git.object(ref)
            return ref
        return self._git.refs().get(ref)

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
