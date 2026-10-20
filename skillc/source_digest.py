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
MAX_ENTRIES = 200_000
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


def tree_entries(root: Path) -> dict[str, str]:
    """`{path: "MODE BLOB"}` for the population under `root`, read without
    following any symlink."""
    entries: dict[str, str] = {}

    def walk(directory: Path, rel: str, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise SourceUnreadable(f"{rel or '.'}: the tree nests deeper than {MAX_DEPTH}")
        try:
            with os.scandir(directory) as listing:
                children = sorted(listing, key=lambda e: e.name)
        except OSError as exc:
            raise SourceUnreadable(f"{rel or '.'}: cannot list ({type(exc).__name__})") from exc
        for child in children:
            path = f"{rel}/{child.name}" if rel else child.name
            if not rel and child.name == ".git":
                continue
            if len(entries) >= MAX_ENTRIES:
                raise SourceUnreadable(f"more than {MAX_ENTRIES} entries")
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
                    data = Path(child.path).read_bytes()
                except OSError as exc:
                    raise SourceUnreadable(f"{path}: cannot read ({type(exc).__name__})") from exc
                entries[path] = f"{'100755' if info.st_mode & 0o111 else '100644'} {blob_id(data)}"
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


def digest_commit(gitdir: object, commit: str) -> str:
    """The same digest of a commit, read through a `git_snapshot.GitDir`."""
    tree = gitdir.tree_of(commit)  # type: ignore[attr-defined]
    return digest_entries(gitdir.tree_files(tree))  # type: ignore[attr-defined]
