"""Explicitly selected attempt recovery; container snapshots and host observations.

The caller authorizes stopping its selected attempts; labels, age, endpoint
emptiness and local PID absence do not establish that an owner is dead.
Before mutation, BOTH resource inventories for ALL selected IDs must succeed.
Only full immutable IDs with independently inspected matching labels are acted
on. Foreign endpoints are preserved; new resources are reported, never chased.
An action error stops further mutations. Read-only confirmation reports what
actually remains, retaining prior actions/errors rather than implying rollback.
Snapshots/diffs below remain container-only, with identity by name; they are
observations, not authority for selecting resources to remove. Tested with a
fake CLI; this module's tests do not certify the real daemon boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
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


# Known container residue keeps the legacy spelling; networks are left-present.
REAP_OUTCOMES = ("already-absent", "reaped", "left-running", "left-present", "unknown")
_SUCCESS = ("reaped", "already-absent")
_ID = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ReapOutcome:
    attempt_id: str
    outcome: str
    remaining_containers: tuple[str, ...] = ()
    remaining_networks: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    uncertain: bool = False


@dataclass(frozen=True)
class ReapReport:
    daemon_reachable: bool
    outcomes: tuple[ReapOutcome, ...]

    def outcome_for(self, attempt_id: str) -> str | None:
        return next((e.outcome for e in self.outcomes if e.attempt_id == attempt_id), None)

    @property
    def reaped(self) -> tuple[str, ...]:
        return tuple(e.attempt_id for e in self.outcomes if e.outcome == "reaped")

    @property
    def left_running(self) -> tuple[str, ...]:
        return tuple(e.attempt_id for e in self.outcomes if e.outcome == "left-running")

    @property
    def unknown(self) -> tuple[str, ...]:
        return tuple(e.attempt_id for e in self.outcomes if e.outcome == "unknown")

    @property
    def nonclean(self) -> tuple[str, ...]:
        return tuple(e.attempt_id for e in self.outcomes if not self.daemon_reachable
                     or e.outcome not in _SUCCESS or e.remaining_containers
                     or e.remaining_networks or e.uncertain)

    @property
    def clean(self) -> bool:
        return self.daemon_reachable and bool(self.outcomes) and not self.nonclean


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("conflicting duplicate metadata key")
        result[k] = v
    return result


def _inventory(
    docker_bin: Sequence[str], ids: list[str], env: Mapping[str, str] | None, timeout: float,
) -> tuple[dict[str, dict[str, tuple[str, ...]]], set[str]] | None:
    found: dict[str, dict[str, tuple[str, ...]]] = {a: {} for a in ids}
    endpoints: dict[str, set[str]] = {}
    seen: set[tuple[str, str]] = set()
    valid = True
    for attempt in ids:
        filters = ["--filter", f"label={OWNER_LABEL_KEY}={OWNER_LABEL_VALUE}",
                   "--filter", f"label={ATTEMPT_LABEL_KEY}={attempt}"]
        for kind, command in (("container", ["ps", "-a"]), ("network", ["network", "ls"])):
            try:
                p = subprocess.run([*docker_bin, *command, "--no-trunc", *filters, "--format", "{{.ID}}"],
                                   capture_output=True, text=True, env=env, timeout=timeout, check=False)
            except (OSError, subprocess.TimeoutExpired):
                valid = False
                continue
            lines = p.stdout.splitlines()
            if p.returncode or (p.stdout and not p.stdout.endswith("\n")) or any(not _ID.fullmatch(i) for i in lines):
                valid = False
                continue
            selected: list[str] = []
            for identity in lines:
                try:
                    argv = [*docker_bin, *( ["network", "inspect"] if kind == "network" else ["inspect"]),
                            "--format", "{{json .}}", identity]
                    meta = subprocess.run(argv, capture_output=True, text=True, env=env,
                                          timeout=timeout, check=False)
                    if meta.returncode:
                        raise ValueError("metadata unavailable")
                    data = json.loads(meta.stdout, object_pairs_hook=_json_object)
                    if not isinstance(data, dict) or data.get("Id") != identity:
                        raise ValueError("identity mismatch")
                    labels = data.get("Labels") if kind == "network" else data.get("Config", {}).get("Labels")
                    if not isinstance(labels, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                              for k, v in labels.items()):
                        raise ValueError("invalid labels")
                    if labels.get(OWNER_LABEL_KEY) != OWNER_LABEL_VALUE or labels.get(ATTEMPT_LABEL_KEY) != attempt:
                        continue  # candidate filters are not independent ownership proof
                    if (kind, identity) in seen:
                        raise ValueError("duplicate selected identity")
                    seen.add((kind, identity))
                    if kind == "network":
                        attached = data.get("Containers")
                        if not isinstance(attached, dict) or any(
                            not _ID.fullmatch(k) or not isinstance(v, dict) for k, v in attached.items()
                        ):
                            raise ValueError("invalid endpoints")
                        endpoints[identity] = set(attached)
                    selected.append(identity)
                except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError, TypeError):
                    valid = False
            found[attempt][kind] = tuple(selected)
    if not valid:
        return None
    owned = {i for a in found.values() for i in a["container"]}
    blocked = {i for i, attached in endpoints.items() if attached - owned}
    return found, blocked


def _target_present(
    docker_bin: Sequence[str], kind: str, identity: str, env: Mapping[str, str] | None, timeout: float,
) -> bool | None:
    """Independent target-ID confirmation even if its labels changed meanwhile."""
    argv = [*docker_bin, *(["network", "inspect"] if kind == "network" else ["inspect"]),
            "--format", "{{.Id}}", identity]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode == 0:
        return True if p.stdout == identity + "\n" else None
    absent = (f"Error: No such object: {identity}" if kind == "container" else
              f"Error response from daemon: network {identity} not found")
    return False if p.stderr.strip() == absent else None


def reap(
    docker_bin: Sequence[str], attempt_ids: Iterable[str],
    env: Mapping[str, str] | None = None, timeout: float = DAEMON_TIMEOUT,
) -> ReapReport:
    """Recover caller-selected attempts, never discover abandoned owners.

    Initial inventory uncertainty means UNKNOWN and ZERO actions for the entire
    batch. Actions use immutable IDs; their first error stops later mutations.
    Confirmation describes the observed result even if an action reply failed.
    New selected arrivals remain nonclean and are never removed by this call.
    """
    ids = list(dict.fromkeys(attempt_ids))
    if not ids or any(not isinstance(a, str) or not a.strip() for a in ids):
        raise ValueError("reap() refuses an empty or invalid attempt_ids population")
    before = _inventory(docker_bin, ids, env, timeout)
    if before is None:
        return ReapReport(False, tuple(ReapOutcome(a, "unknown", uncertain=True) for a in ids))
    targets, blocked = before
    actions: dict[str, list[str]] = {a: [] for a in ids}
    errors: dict[str, list[str]] = {a: [] for a in ids}
    stopped = False
    for kind in ("container", "network"):
        for attempt in ids:
            for identity in targets[attempt][kind]:
                if stopped or (kind == "network" and identity in blocked):
                    continue
                action = f"{kind}:{identity}"
                actions[attempt].append(action)
                try:
                    argv = [*docker_bin, *( ["network", "rm"] if kind == "network" else ["rm", "-f"]), identity]
                    p = subprocess.run(argv, capture_output=True, text=True, env=env,
                                       timeout=timeout, check=False)
                    if p.returncode:
                        errors[attempt].append(f"{action}:exit-{p.returncode}")
                        stopped = True
                except (OSError, subprocess.TimeoutExpired) as exc:
                    errors[attempt].append(f"{action}:{type(exc).__name__}")
                    stopped = True
    after = _inventory(docker_bin, ids, env, timeout)
    if after is not None:
        for attempt in ids:
            for kind in ("container", "network"):
                for identity in targets[attempt][kind]:
                    present = _target_present(docker_bin, kind, identity, env, timeout)
                    if present is None:
                        after = None
                        break
                    if present and identity not in after[0][attempt][kind]:
                        after[0][attempt][kind] += (identity,)
                if after is None:
                    break
            if after is None:
                break
    outcomes = []
    for attempt in ids:
        containers: tuple[str, ...] = ()
        networks: tuple[str, ...] = ()
        if after is None:
            verdict = "unknown"
        else:
            containers, networks = after[0][attempt]["container"], after[0][attempt]["network"]
            verdict = ("left-running" if containers else "left-present" if networks else
                       "reaped" if any(targets[attempt].values()) else "already-absent")
        outcomes.append(ReapOutcome(attempt, verdict, containers, networks, tuple(actions[attempt]),
                                    tuple(errors[attempt]), uncertain=after is None))
    return ReapReport(after is not None, tuple(outcomes))


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
