"""Provenance: which skillc produced a record (operator request, #10 addendum
item E). A verdict that cannot say which skillc produced it is not
reproducible. Every installation receipt, trial ledger, result bundle and the
demo's paste-back block is meant to carry this stamp.

ONE SHARED FUNCTION, not each producer hand-rolling git-invocation edge cases
(detached HEAD, no `.git` at all in a built wheel, the `git` binary missing)
independently and drifting apart - agreed with w3 (#10 PR2) so both sides land
the same field names and the same UNKNOWN discipline.

Stdlib only (AGENTS.md): `git` via `subprocess`, never a VCS library.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import __version__

GIT_TIMEOUT = 5.0


@dataclass(frozen=True)
class Provenance:
    """`source_commit` is the literal string `"UNKNOWN"`, never blank, when
    `git` is not on `PATH`, `source_root` is not inside a git work tree (an
    installed wheel ships no `.git`), or the query times out. `dirty` is
    `None` in exactly those same cases - never a guessed `False`, which would
    read as "confirmed clean" for a tree this process could not actually
    ask. Whichever `skillc` package is running always has a version, so
    `skillc_version` alone is never UNKNOWN."""

    skillc_version: str
    source_commit: str
    dirty: bool | None

    def as_dict(self) -> dict[str, object]:
        return {
            "skillc_version": self.skillc_version,
            "source_commit": self.source_commit,
            "dirty": self.dirty,
        }


def _run_git(args: list[str], cwd: Path, timeout: float = GIT_TIMEOUT) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, timeout=timeout, text=True, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def stamp(source_root: Path | None = None) -> Provenance:
    """The version+commit+dirty stamp for the skillc CHECKOUT this process
    runs from - never the experiment's or a candidate's own tree; those get
    their own identities elsewhere (subject digest, image digest).

    `source_root` defaults to this package's own parent directory (the
    skillc checkout root), so a caller inside `skillc/` gets the right answer
    without having to locate it itself.

    Running git FROM `source_root` is not enough to prove the discovered
    repository treats `source_root` as its own root (found by w3's
    cross-model review): an installed wheel living under `site-packages`
    inside some UNRELATED enclosing project's git checkout would otherwise
    silently inherit THAT project's HEAD and dirty status, misattributed as
    skillc's own. So the resolved toplevel is checked against `source_root`
    itself, and anything else - no repository at all, or a repository whose
    root is somewhere else - is UNKNOWN, exactly like no repo at all.
    """
    root = (source_root or Path(__file__).resolve().parent.parent).resolve()
    toplevel = _run_git(["rev-parse", "--show-toplevel"], root)
    if toplevel is None or Path(toplevel).resolve() != root:
        return Provenance(skillc_version=__version__, source_commit="UNKNOWN", dirty=None)
    commit = _run_git(["rev-parse", "HEAD"], root)
    if commit is None:
        return Provenance(skillc_version=__version__, source_commit="UNKNOWN", dirty=None)
    status = _run_git(["status", "--porcelain"], root)
    dirty = None if status is None else bool(status)
    return Provenance(skillc_version=__version__, source_commit=commit, dirty=dirty)
