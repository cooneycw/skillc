"""Version, source commit and dirty-tree provenance for a record.

Operator request folded into #10 (orchestrator message 1348, agreed with #10's
w1 for receipts/ledgers/bundles): every record this build produces states
which skillc it came from. One shared function, so every record kind stamps
the SAME shape and the SAME git-invocation edge cases (detached HEAD, no
`.git` at all in a built wheel, `git` missing) rather than each producer
hand-rolling its own and drifting apart - the same reasoning `records.py`
gives for one shared envelope rather than one per kind.

UNKNOWN, never blank, when the commit cannot be determined: a commit git
cannot resolve is refused as evidence of a clean run, the same discipline
this codebase applies everywhere else silence could stand in for "nothing
wrong" (`observation_coverage`, `attempt-lifecycle`'s cleanup, ...). `dirty`
is `None`, not `False`, on the same failure: a tree we could not check is not
one we know to be clean.

Computed from skillc's OWN source tree (`Path(__file__)`'s package root),
never the experiment, candidate or subject's - this stamps what CODE
produced the record, not what the record is about.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import __version__

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _run_git(*args: str) -> str | None:
    """`None` on any failure - not a git repository, `git` not installed, a
    detached worktree git cannot resolve, or the call simply took too long.
    Every failure reads the same way to a caller: unknown, not clean."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=_PACKAGE_ROOT, capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def stamp() -> dict[str, object]:
    """`{"skillc_version": ..., "source_commit": ..., "dirty": ...}`.

    `source_commit` is the full commit hash, or the literal string
    `"UNKNOWN"`. `dirty` is `True` when `git status --porcelain` reports
    anything, `False` when it reports nothing, and `None` when it could not
    be asked (in which case `source_commit` is also `"UNKNOWN"` - there is no
    case where the commit is known but dirtiness is not, since both come from
    the same repository check).
    """
    commit = _run_git("rev-parse", "HEAD")
    if commit is None:
        return {"skillc_version": __version__, "source_commit": "UNKNOWN", "dirty": None}
    porcelain = _run_git("status", "--porcelain")
    dirty = None if porcelain is None else bool(porcelain)
    return {"skillc_version": __version__, "source_commit": commit, "dirty": dirty}
