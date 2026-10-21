"""A SOURCE digest: one identity for "the tree a gate ran on" and "the commit
that shipped" (#279 PR-2a, orchestrator ruling R4).

The gate witness's `tree_digest_at_start` digests the whole exported
workspace, so it can never equal a commit, and a neighbouring worktree or an
untracked file elsewhere moves it. This digest is computed IDENTICALLY on both
sides, over git's own representation of a tree: the sorted
`(path, "MODE BLOB")` entries, where MODE is git's file mode (100644, 100755,
120000 for a symlink) and BLOB is the git blob id of the bytes (for a symlink,
of its link text, as git stores it).

THE POPULATION, and why:
- every regular file and symlink under the GATED REPOSITORY ROOT (the git
  checkout that contains the gate's working directory);
- EXCEPT the `.git` entry at that root (the repository's own metadata, never
  content), and the declared bookkeeping path `.claude/friction.jsonl`, which
  flow:auto writes on every run and never commits (#475's exemption);
- ignore rules are NOT applied. A file the gate saw is part of what it judged,
  whether or not a `.gitignore` the subject wrote would hide it. So an
  untracked extra file at gate time makes the digests DIFFER: the gated tree
  was not the shipped tree, which a Step-6 grader reads as UNKNOWN, never as
  a match;
- a special file (FIFO, socket, device) is recorded as "not-a-file", never
  opened: it cannot be committed, and it forces a mismatch.

The commit side reads a commit's tree with `git_snapshot` (no git process);
the gated side walks the controller-owned export of the attempt, never the
live container.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path

#: Paths at the repository root that are never part of the population.
EXEMPT = (".claude/friction.jsonl",)
MAX_DEPTH = 64
#: Every directory entry listed counts (directories too), checked WHILE a
#: directory is listed; and file bytes are hashed in chunks under a per-file
#: and a total budget (counter-model review: the export is subject-written).
MAX_ENTRIES = 200_000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
_CHUNK = 1024 * 1024
NOT_A_FILE = "not-a-file"


class SourceUnreadable(Exception):
    """The tree cannot be read faithfully (a depth or size cap, an IO error)."""


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def digest_entries(entries: Mapping[str, str]) -> str:
    """The digest of `{path: "MODE BLOB"}`, the exempt paths left out."""
    kept = sorted((path, value) for path, value in entries.items() if path not in EXEMPT)
    payload = json.dumps(kept, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _file_blob(path: str, size: int, budget: list[int]) -> str:
    """The git blob id of a regular file, hashed in chunks: never more than
    `MAX_FILE_BYTES` of one file or `MAX_TOTAL_BYTES` in all, and refused when
    the bytes read are not the size the listing reported (the file changed)."""
    if size > MAX_FILE_BYTES:
        raise SourceUnreadable(f"a file is larger than {MAX_FILE_BYTES} bytes")
    budget[0] += size
    if budget[0] > MAX_TOTAL_BYTES:
        raise SourceUnreadable(f"the tree holds more than {MAX_TOTAL_BYTES} bytes")
    digest = hashlib.sha1(b"blob %d\0" % size)
    read = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(min(_CHUNK, size - read + 1)):
            read += len(chunk)
            if read > size:
                break
            digest.update(chunk)
    if read != size:
        raise SourceUnreadable("a file changed size while it was read")
    return digest.hexdigest()


def tree_entries(root: Path) -> dict[str, str]:
    """`{path: "MODE BLOB"}` for the population under `root`, read without
    following any symlink, under the entry, depth and byte budgets above."""
    entries: dict[str, str] = {}
    listed = [0]
    budget = [0]

    def walk(directory: Path, rel: str, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise SourceUnreadable(f"{rel or '.'}: the tree nests deeper than {MAX_DEPTH}")
        children = []
        try:
            with os.scandir(directory) as listing:
                for child in listing:
                    listed[0] += 1
                    if listed[0] > MAX_ENTRIES:
                        raise SourceUnreadable(f"more than {MAX_ENTRIES} directory entries")
                    children.append(child)
        except OSError as exc:
            raise SourceUnreadable(f"{rel or '.'}: cannot list ({type(exc).__name__})") from exc
        for child in sorted(children, key=lambda e: e.name):
            path = f"{rel}/{child.name}" if rel else child.name
            if not rel and child.name == ".git":
                continue
            try:
                info = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise SourceUnreadable(f"{path}: cannot stat ({type(exc).__name__})") from exc
            if stat.S_ISDIR(info.st_mode):
                walk(Path(child.path), path, depth + 1)
            elif stat.S_ISLNK(info.st_mode):
                entries[path] = f"120000 {blob_id(os.fsencode(os.readlink(child.path)))}"
            elif stat.S_ISREG(info.st_mode):
                try:
                    blob = _file_blob(child.path, info.st_size, budget)
                except OSError as exc:
                    raise SourceUnreadable(f"{path}: cannot read ({type(exc).__name__})") from exc
                # Git's own rule: the OWNER execute bit alone (counter-model review).
                entries[path] = f"{'100755' if info.st_mode & stat.S_IXUSR else '100644'} {blob}"
            else:
                entries[path] = NOT_A_FILE

    walk(root, "", 0)
    return entries


def digest_tree(root: Path) -> str:
    return digest_entries(tree_entries(root))


def repository_root(export_root: Path, rel_cwd: str) -> Path | None:
    """The checkout containing `rel_cwd` inside an export: the nearest
    directory, from `rel_cwd` up to `export_root`, holding a `.git` entry
    (a directory, or a linked worktree's gitfile). None when there is none."""
    root = export_root.resolve()
    here = (root / rel_cwd).resolve() if rel_cwd else root
    if here != root and root not in here.parents:
        return None
    while True:
        if os.path.lexists(here / ".git"):
            return here
        if here == root:
            return None
        here = here.parent


def workspace_relative(cwd: str | None, workspace: str) -> str | None:
    """`cwd` relative to the container `workspace` ("" for the workspace
    itself), or None when it is outside. Only a real `..` path segment is
    outside: a name that merely starts with two dots is inside (counter-model
    review, pass 2)."""
    if not cwd:
        return ""
    rel = os.path.relpath(cwd, workspace)
    if rel == ".":
        return ""
    if rel == ".." or rel.startswith(".." + os.sep):
        return None
    return rel


def digest_commit(gitdir: object, commit: str) -> str:
    """The same digest of a commit, read through a `git_snapshot.GitDir`.
    Every blob the tree names is READ and must be a blob (counter-model
    review, pass 2): a tree only lists ids, so a missing or corrupt shipped
    blob would otherwise digest as if it shipped. A submodule entry (160000)
    names no object here and is left as listed: it can never match a gated
    working tree."""
    tree = gitdir.tree_of(commit)  # type: ignore[attr-defined]
    files = gitdir.tree_files(tree)  # type: ignore[attr-defined]
    for path, value in files.items():
        mode, _, blob = str(value).partition(" ")
        if mode == "160000":
            continue
        try:
            kind, _payload = gitdir.object(blob)  # type: ignore[attr-defined]
        except Exception as exc:
            raise SourceUnreadable(f"{path}: blob {blob[:10]} cannot be read ({type(exc).__name__})") from exc
        if kind != "blob":
            raise SourceUnreadable(f"{path}: {blob[:10]} is a {kind}, not a blob")
    return digest_entries(files)


# ------------------------------------------- #279 PR-2b: the ship stamp

#: The GATE DEFINITION's root-level files (#279 S5, #287's tamper rule): what
#: decides whether the gate passes, as opposed to the code it judges.
GATE_DEFINITION_FILES = ("Makefile", "pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")


def is_gate_definition(path: str) -> bool:
    """`Makefile`, the pytest configuration files, anything under `ci/`, any
    `.yml`/`.yaml` under `.claude/`, and every `conftest.py` at any depth.
    `grade_gate_stops_early_step6.py` holds the same rule, stdlib-only; a test
    pins the two together."""
    return (path in GATE_DEFINITION_FILES or path.startswith("ci/")
            or (path.startswith(".claude/") and path.endswith((".yml", ".yaml")))
            or path == "conftest.py" or path.endswith("/conftest.py"))


def gate_definition_digest(entries: Mapping[str, str]) -> str:
    """`digest_entries` over the gate-definition subset of `entries`."""
    return digest_entries({path: value for path, value in entries.items() if is_gate_definition(path)})


def ship_stamp(gitdir: object, commit: str) -> dict[str, str]:
    """What a ship request ships, stamped AT the request (#279 PR-2b, Delta 2/3):
    the commit, its SOURCE digest (`digest_commit`'s population, every blob
    read and checked) and its gate-definition digest. Raises `SourceUnreadable`
    when the commit cannot be read faithfully - the caller records that as
    an unreadable stamp, never as a digest."""
    try:
        files = gitdir.tree_files(gitdir.tree_of(commit))  # type: ignore[attr-defined]
    except Exception as exc:
        raise SourceUnreadable(f"commit {commit[:10]} cannot be read ({type(exc).__name__})") from exc
    return {"commit": commit, "source_digest": digest_commit(gitdir, commit),
            "gate_definition_digest": gate_definition_digest(files)}

