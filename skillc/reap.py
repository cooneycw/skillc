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


def _list(
    docker_bin: Sequence[str], env: Mapping[str, str] | None, timeout: float,
    label_filters: Sequence[tuple[str, str]], fmt: str,
) -> list[str] | None:
    """`docker ps -a --format fmt`, filtered by every `label_filters` pair
    (ANDed), or `None` when the daemon cannot be asked at all - never an
    empty list standing in for "unreachable"; the two are different facts
    everywhere else in this codebase and are kept different here."""
    argv = [*docker_bin, "ps", "-a"]
    for key, value in label_filters:
        argv += ["--filter", f"label={key}={value}"]
    argv += ["--format", fmt]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env=env, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [line for line in proc.stdout.splitlines() if line]


def _list_names(
    docker_bin: Sequence[str], env: Mapping[str, str] | None, timeout: float,
    label_filters: Sequence[tuple[str, str]],
) -> list[str] | None:
    return _list(docker_bin, env, timeout, label_filters, "{{.Names}}")


def _list_ids(
    docker_bin: Sequence[str], env: Mapping[str, str] | None, timeout: float,
    label_filters: Sequence[tuple[str, str]],
) -> list[str] | None:
    """Container IDs, not names (codex review of this PR): a NAME can be
    reused by a different, later container the instant the original one is
    removed - real docker refuses two SIMULTANEOUS containers sharing a name,
    but says nothing about a name being taken by a brand-new container
    milliseconds after the old one is gone. `reap()` lists, then acts, then
    re-lists - three separate round trips - so acting and confirming BY NAME
    could target or "confirm absent" a container that only coincidentally
    shares the name of the one this call actually meant. An ID is unique to
    ONE container's lifetime and is never reused, so it is immune to that
    race in a way a name is not."""
    return _list(docker_bin, env, timeout, label_filters, "{{.ID}}")


@dataclass(frozen=True)
class Snapshot:
    """One `docker ps -a` read, partitioned by ownership. `reachable=False`
    means the daemon could not be asked at all - `owned`/`foreign` are then
    empty by construction, never a guessed prior value.

    IDENTITY HERE IS BY NAME, NOT BY CONTAINER ID (codex review, stated as a
    limitation rather than fixed here - unlike `reap()` below, which DOES
    need ID identity because it acts on what it finds, not merely observes
    it). A container removed and replaced by a DIFFERENT container under the
    identical name, entirely between two snapshots, is indistinguishable
    from one that was never touched; this partition answers "is a container
    with this name currently reporting the ownership label", not "is this
    the SAME container instance as last time". For a coarse leak/scope
    detector run around one attempt's own narrow window, that gap is small;
    it would not be if this were reused as a security boundary.
    """

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
    """ATTRIBUTION IS NOT CAUSATION (codex review, stated rather than solved
    here): `leaked`/`foreign_vanished` answer "did something change on the
    daemon between these two reads", never "did THIS run cause it". A
    concurrent second skillc run sharing the same daemon can legitimately
    add its own owned container during this window (reported as `leaked`
    even though nothing here leaked anything), or independently remove its
    own foreign-to-THIS-run container (reported as `foreign_vanished` even
    though nothing here reached outside its scope). Neither is a false
    POSITIVE about the daemon's state - the container really did appear or
    vanish - only a false claim about WHO caused it. Take these snapshots as
    close as possible around one attempt's own execution window, on a daemon
    nothing else is using concurrently, to keep that gap small; establishing
    causation under real concurrency needs a separate, isolated test daemon
    or a controlled execution window, not this comparison alone.
    """
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

    ACTS AND CONFIRMS BY CONTAINER ID, NEVER BY NAME (codex review, HIGH):
    this function lists, then removes, then re-lists - three separate round
    trips to a daemon nothing prevents from changing between them. A NAME
    can be taken by a brand-new, different container the instant the
    original is removed; an ID cannot, because it is unique to one
    container's lifetime and is never reused. Confirmation re-checks that
    the SPECIFIC ids this call targeted are gone, not merely that the label
    filter now returns nothing - a fresh container that picked up the same
    attempt id's label between the two lists would otherwise be silently
    read as "yes, reaped", when what actually happened is a new leak this
    call never touched (which `snapshot()`/`diff()` above would separately
    catch as `leaked`, since it is a container this call did not act on).

    An EMPTY `attempt_ids` is refused (`ValueError`), never silently
    reported as `daemon_reachable=True` with nothing outstanding - an
    unexamined population is not the same fact as a checked-and-clean one
    (codex review; the same rule this codebase applies to `check-records` on
    an empty record set).
    """
    ids = list(attempt_ids)
    if not ids:
        raise ValueError(
            "reap() refuses an empty attempt_ids: nothing would be checked, and reporting "
            "daemon_reachable=True for a call that asked the daemon nothing would read as "
            "a clean sweep rather than as the no-op it actually was"
        )
    outcomes: list[ReapOutcome] = []
    daemon_reachable = True
    for attempt_id in ids:
        label_filters = [(OWNER_LABEL_KEY, OWNER_LABEL_VALUE), (ATTEMPT_LABEL_KEY, attempt_id)]
        target_ids = _list_ids(docker_bin, env, timeout, label_filters)
        if target_ids is None:
            daemon_reachable = False
            outcomes.append(ReapOutcome(attempt_id, "left-running"))
            continue
        if not target_ids:
            outcomes.append(ReapOutcome(attempt_id, "already-absent"))
            continue
        for container_id in target_ids:
            try:
                subprocess.run(
                    [*docker_bin, "rm", "-f", container_id],
                    capture_output=True, env=env, check=False, timeout=timeout,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass  # best-effort; the follow-up list below is what actually confirms it
        still_there = _list_ids(docker_bin, env, timeout, label_filters)
        if still_there is None:
            daemon_reachable = False
            outcomes.append(ReapOutcome(attempt_id, "left-running"))
        elif any(target_id in still_there for target_id in target_ids):
            outcomes.append(ReapOutcome(attempt_id, "left-running"))
        else:
            outcomes.append(ReapOutcome(attempt_id, "reaped"))
    return ReapReport(daemon_reachable=daemon_reachable, outcomes=tuple(outcomes))


# --------------------------------------------------- declared host paths (#79)

#: A sentinel for "this path exists as a regular file but could not be read"
#: (permission denied, and similar) - distinct from `None` ("confirmed
#: absent, or not a regular file at all") and from any real digest (a
#: sha256 hex digest is 64 lowercase hex characters; this string is not one,
#: so no real digest can ever collide with it) (codex review, MEDIUM: an
#: OSError used to collapse into the same `None` as confirmed absence,
#: so an unreadable file compared as "unchanged" against itself, or against
#: a truly absent one, either of which is a false claim of certainty this
#: instrument does not have).
UNREADABLE = "<unreadable>"

#: A sentinel distinct from both `None` and `UNREADABLE`, used only inside
#: `diff_host_paths` to mean "this snapshot's dict has no entry for this key
#: at all" - never confused with a snapshot that DID look and found the path
#: absent (codex review, MEDIUM: `.get(key)` defaults a missing key to
#: `None`, which collided with the legitimate "confirmed absent" `None` and
#: made a declaration added or removed between two snapshots invisible).
_NOT_DECLARED = object()


@dataclass(frozen=True)
class HostPathSnapshot:
    """One declared host path's content per its own string key: a sha256 hex
    digest, `None` (confirmed absent, or not a plain regular file), or
    `UNREADABLE` (exists as a regular file but could not be read). Keyed by
    the exact string each `Path` was given as - the same strings must be
    passed to both the before and after snapshot, or `diff_host_paths`
    compares two different key sets instead of one path twice."""

    digests: Mapping[str, str | None]


def snapshot_host_paths(paths: Iterable[Path]) -> HostPathSnapshot:
    """Content-digest each of `paths` - declared HOST paths outside the trial
    root, never resolved through the trial's own workspace. Refuses an empty
    `paths` (`ValueError`): a declaration of nothing to watch would otherwise
    report `changed=()` indistinguishably from "checked and confirmed
    unchanged" (codex review, MEDIUM - the same "empty population is refused"
    rule this codebase applies elsewhere).

    WHAT THIS CANNOT SEE (#79's own required disclosure, stated rather than
    silently assumed away): a path is hashed as a REGULAR FILE only - a
    directory, device or symlink reads as `None`, exactly like an absent
    path, never walked or followed; a symlink retargeted to a file with an
    IDENTICAL digest is indistinguishable from an untouched one; permission,
    ownership and timestamp changes that leave the bytes unchanged are
    invisible by design (this checks content, not metadata); and nothing
    outside the declared list is examined at all - this proves paths you
    named are unchanged, not that nothing on the host changed. A path
    unreadable at BOTH snapshots is `UNREADABLE` both times and is reported
    as `unresolved` by `diff_host_paths` below, never silently folded into
    "unchanged" - this instrument has no evidence either way for it.
    """
    given = list(paths)
    if not given:
        raise ValueError(
            "snapshot_host_paths() refuses an empty declaration: nothing would be "
            "watched, and changed=() from diff_host_paths would then read as "
            "'confirmed unchanged' rather than as the vacuous result it actually is"
        )
    digests: dict[str, str | None] = {}
    for path in given:
        key = str(path)
        try:
            if path.is_symlink() or not path.is_file():
                digests[key] = None
            else:
                digests[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digests[key] = UNREADABLE
    return HostPathSnapshot(digests=digests)


@dataclass(frozen=True)
class HostPathDiff:
    """`changed`: a declared path whose digest differs, confirmed on both
    sides. `unresolved`: a declared path where at least one side could not
    be read - comparability is unknown for it, never silently treated as
    "unchanged" (codex review, MEDIUM)."""

    changed: tuple[str, ...]
    unresolved: tuple[str, ...]


def diff_host_paths(before: HostPathSnapshot, after: HostPathSnapshot) -> HostPathDiff:
    """Every declared path whose digest differs between the two snapshots,
    including one that appeared, disappeared, or changed content - a key
    present in only one snapshot's declarations is itself a mismatch, never
    silently ignored (compared against `_NOT_DECLARED`, never against a
    `.get()` default that would collide with the legitimate `None` meaning
    "confirmed absent"). A path unreadable on either side is reported
    separately, under `unresolved`, never compared for equality - two
    identical `UNREADABLE` sentinels are not evidence the content matched."""
    keys = set(before.digests) | set(after.digests)
    changed = []
    unresolved = []
    for key in sorted(keys):
        b = before.digests.get(key, _NOT_DECLARED)
        a = after.digests.get(key, _NOT_DECLARED)
        if b == UNREADABLE or a == UNREADABLE:
            unresolved.append(key)
        elif b != a:
            changed.append(key)
    return HostPathDiff(changed=tuple(changed), unresolved=tuple(unresolved))
