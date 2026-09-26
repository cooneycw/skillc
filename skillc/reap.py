"""Label-scoped container reaping and resource snapshots (#79, sub-issue of #10).

`docker_backend.py`'s own driver already tears down every attempt's container
through `destroy()`/`confirm_absent()` (#77). This module is the SECOND,
INDEPENDENT layer #79 asks for: a sweep that finds and removes containers by
label alone, for the case that per-attempt teardown itself did not run or did
not finish - a crash mid-lifecycle, a killed controller process, an operator
running this by hand against a daemon nobody has looked at in a while.

REAPING IS BY LABEL ONLY, NEVER BY NAME (issue #77's own docstring, #79's
scope). A container is a candidate for this module's `reap()` only if the
daemon itself reports it carrying BOTH `docker_backend.OWNER_LABEL_KEY` and
the specific attempt id's `docker_backend.ATTEMPT_LABEL_KEY` value - `docker
ps --filter label=...` does the matching, not a name comparison this module
performs itself. A foreign container that merely LOOKS like one of ours
(a similar name, no matching labels) can never appear in that filtered list,
so it is structurally unreachable to `reap()`, not merely unlikely to be hit.

UNKNOWN NEVER REAPS, the same rule `ExecutionBackend.confirm_absent` already
states for a single attempt (`backend.py`), generalized to a sweep over many.
If the daemon cannot even be asked (`docker ps` itself fails - an unreachable
daemon, a timeout), nothing is removed and every requested attempt id is
reported `left-running`: an unconfirmable absence is not a confirmed one, and
guessing "probably already gone" here is exactly the guess `Confirmation`
exists to forbid elsewhere in this codebase.

REGISTER-BEFORE-FAIL IS ALREADY TRUE, BY CONSTRUCTION, NOT SOMETHING THIS
MODULE ADDS. `compose_run_argv` (docker_backend.py) writes both labels onto a
container at `docker run` time - the very first step of an attempt's
lifecycle, before install/execute/anything that can fail. So a container that
exists on the daemon at all is already durably marked as skillc's own and
already carries the one attempt id it belongs to; there is no separate
"intend to clean this up" bookkeeping for a crash to lose, because the
label IS that bookkeeping and it was written before anything risky ran.
`reap()` therefore needs no journal, no lock file and no state of its own -
it is idempotent because asking the daemon "does anything with this label
still exist" is idempotent, and removing something already gone is defined
here as success (`already-absent`), never an error.

RESOURCE SNAPSHOTS ARE TWO-DIRECTIONAL (#79's own wording: "flagged in BOTH
directions"). `snapshot()` partitions every container the daemon reports into
`owned` (carries the fixed ownership label) and `foreign` (everything else);
`diff()` compares a before/after pair and reports BOTH an unexpected LEAK
(an owned container present after that was not present before - something
skillc left running) AND an unexpected DISAPPEARANCE (a foreign container
present before that is gone after - evidence a sweep reached outside its own
label scope, which a correctly-scoped `reap()` cannot do, but the comparison
does not assume that and checks anyway). A diff computed across an
unreachable snapshot is refused, never silently treated as "no change" -
absence of evidence is not evidence of absence.

Stdlib only (AGENTS.md). Tested here only against the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`); the real daemon boundary
remains owed to the operator's live run (#10), exactly as `docker_backend.py`
itself states.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .docker_backend import ATTEMPT_LABEL_KEY, DAEMON_TIMEOUT, OWNER_LABEL_KEY, OWNER_LABEL_VALUE


def _list_names(
    docker_bin: Sequence[str], env: Mapping[str, str] | None, timeout: float,
    label_filters: Sequence[tuple[str, str]],
) -> list[str] | None:
    """Container names matching every `label_filters` pair (ANDed), or `None`
    when the daemon cannot be asked at all - never an empty list standing in
    for "unreachable"; the two are different facts everywhere else in this
    codebase and are kept different here."""
    argv = [*docker_bin, "ps", "-a"]
    for key, value in label_filters:
        argv += ["--filter", f"label={key}={value}"]
    argv += ["--format", "{{.Names}}"]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env=env, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [line for line in proc.stdout.splitlines() if line]


@dataclass(frozen=True)
class Snapshot:
    """One `docker ps -a` read, partitioned by ownership. `reachable=False`
    means the daemon could not be asked at all - `owned`/`foreign` are then
    empty by construction, never a guessed prior value."""

    reachable: bool
    owned: frozenset[str]
    foreign: frozenset[str]


def snapshot(
    docker_bin: Sequence[str], env: Mapping[str, str] | None = None, timeout: float = DAEMON_TIMEOUT,
) -> Snapshot:
    owned = _list_names(docker_bin, env, timeout, [(OWNER_LABEL_KEY, OWNER_LABEL_VALUE)])
    everyone = _list_names(docker_bin, env, timeout, [])
    if owned is None or everyone is None:
        return Snapshot(reachable=False, owned=frozenset(), foreign=frozenset())
    owned_set = frozenset(owned)
    return Snapshot(reachable=True, owned=owned_set, foreign=frozenset(everyone) - owned_set)


@dataclass(frozen=True)
class SnapshotDiff:
    """`comparable=False` means at least one side was unreachable - `leaked`/
    `foreign_vanished` are then empty by construction, and a caller must NOT
    read that emptiness as "nothing changed"; it means the comparison itself
    could not be made."""

    comparable: bool
    leaked: frozenset[str]
    foreign_vanished: frozenset[str]


def diff(before: Snapshot, after: Snapshot) -> SnapshotDiff:
    if not before.reachable or not after.reachable:
        return SnapshotDiff(comparable=False, leaked=frozenset(), foreign_vanished=frozenset())
    return SnapshotDiff(
        comparable=True,
        leaked=after.owned - before.owned,
        foreign_vanished=before.foreign - after.foreign,
    )


#: One attempt id's outcome from a `reap()` call.
#: - "already-absent": nothing with this attempt's labels was found - an
#:   ordinary, idempotent no-op, not evidence anything was ever removed.
#: - "reaped": something was found, `docker rm -f` was issued, and a
#:   follow-up label-filtered list confirms nothing with those labels remains.
#: - "left-running": either the daemon could not be asked (UNKNOWN never
#:   reaps) or something with these labels is STILL listed after the removal
#:   attempt - never conflated with "already-absent".
REAP_OUTCOMES = ("already-absent", "reaped", "left-running")


@dataclass(frozen=True)
class ReapOutcome:
    attempt_id: str
    outcome: str


@dataclass(frozen=True)
class ReapReport:
    daemon_reachable: bool
    outcomes: tuple[ReapOutcome, ...]

    def outcome_for(self, attempt_id: str) -> str | None:
        for entry in self.outcomes:
            if entry.attempt_id == attempt_id:
                return entry.outcome
        return None

    @property
    def reaped(self) -> tuple[str, ...]:
        return tuple(e.attempt_id for e in self.outcomes if e.outcome == "reaped")

    @property
    def left_running(self) -> tuple[str, ...]:
        return tuple(e.attempt_id for e in self.outcomes if e.outcome == "left-running")


def reap(
    docker_bin: Sequence[str], attempt_ids: Iterable[str],
    env: Mapping[str, str] | None = None, timeout: float = DAEMON_TIMEOUT,
) -> ReapReport:
    """Remove every container labeled as belonging to one of `attempt_ids`,
    by label alone (see the module docstring). Idempotent: an attempt id
    with nothing left to remove is `already-absent`, not an error, so calling
    this twice - or calling it for an attempt that tore itself down cleanly -
    costs nothing beyond the list/inspect round trips.
    """
    outcomes: list[ReapOutcome] = []
    daemon_reachable = True
    for attempt_id in attempt_ids:
        label_filters = [(OWNER_LABEL_KEY, OWNER_LABEL_VALUE), (ATTEMPT_LABEL_KEY, attempt_id)]
        names = _list_names(docker_bin, env, timeout, label_filters)
        if names is None:
            daemon_reachable = False
            outcomes.append(ReapOutcome(attempt_id, "left-running"))
            continue
        if not names:
            outcomes.append(ReapOutcome(attempt_id, "already-absent"))
            continue
        for name in names:
            try:
                subprocess.run(
                    [*docker_bin, "rm", "-f", name],
                    capture_output=True, env=env, check=False, timeout=timeout,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass  # best-effort; the follow-up list below is what actually confirms it
        still_there = _list_names(docker_bin, env, timeout, label_filters)
        if still_there is None:
            daemon_reachable = False
            outcomes.append(ReapOutcome(attempt_id, "left-running"))
        elif still_there:
            outcomes.append(ReapOutcome(attempt_id, "left-running"))
        else:
            outcomes.append(ReapOutcome(attempt_id, "reaped"))
    return ReapReport(daemon_reachable=daemon_reachable, outcomes=tuple(outcomes))


# --------------------------------------------------- declared host paths (#79)

@dataclass(frozen=True)
class HostPathSnapshot:
    """One declared host path's content digest per its own string key, or
    `None` when it did not exist (or was not a plain regular file) at
    snapshot time. Keyed by the exact string each `Path` was given as - the
    same strings must be passed to both the before and after snapshot, or
    `diff_host_paths` compares two different key sets instead of one path
    twice."""

    digests: Mapping[str, str | None]


def snapshot_host_paths(paths: Iterable[Path]) -> HostPathSnapshot:
    """Content-digest each of `paths` - declared HOST paths outside the trial
    root, never resolved through the trial's own workspace.

    WHAT THIS CANNOT SEE (#79's own required disclosure, stated rather than
    silently assumed away): a path is hashed as a REGULAR FILE only - a
    directory, device or symlink reads as `None`, exactly like an absent
    path, never walked or followed; a symlink retargeted to a file with an
    IDENTICAL digest is indistinguishable from an untouched one; permission,
    ownership and timestamp changes that leave the bytes unchanged are
    invisible by design (this checks content, not metadata); and nothing
    outside the declared list is examined at all - this proves paths you
    named are unchanged, not that nothing on the host changed.
    """
    digests: dict[str, str | None] = {}
    for path in paths:
        key = str(path)
        try:
            if path.is_symlink() or not path.is_file():
                digests[key] = None
            else:
                digests[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digests[key] = None
    return HostPathSnapshot(digests=digests)


@dataclass(frozen=True)
class HostPathDiff:
    changed: tuple[str, ...]


def diff_host_paths(before: HostPathSnapshot, after: HostPathSnapshot) -> HostPathDiff:
    """Every declared path whose digest differs between the two snapshots,
    including one that appeared, disappeared, or changed content - a key
    present on only one side is itself a mismatch, never silently ignored."""
    keys = set(before.digests) | set(after.digests)
    changed = tuple(sorted(k for k in keys if before.digests.get(k) != after.digests.get(k)))
    return HostPathDiff(changed=changed)
