# Removed-root absence evidence (Refs #797, Contract A)

This spec implements section 2 of the owner-approved
[run-window contracts design](run-window-contracts.md) (#797, revision 7). The
work is split in three SECRET-PATH parts. Only the last one lifts
`removed-root-absence-contract-unavailable`:

| Part | Delivers | Status |
|---|---|---|
| **A-1** | census of a removed root, fact 1 (unlinked), fact 4 (re-resolved), the held-descriptor reader | this change |
| A-2 | teardown boundary, fact 2 (no holder), fact 2b (channel isolation), fact 3 (superblock gone) | `skillc/run_window_teardown.py` |
| A-3 | per-surface composition, the total release predicate, the declaration | later; lifts the blocker |

Until A-3 lands, nothing calls this module on a real window. Every
credential window stays held under `vm_credential_window.BLOCKERS`.

## Precondition: the controller is the only writer

These observations are evidence only inside the teardown boundary (design
§2.2 step 3, delivered in A-2). That boundary proves the holder domain empty
before the census and keeps it empty through fact 4. A concurrent writer could
insert an entry after a directory was listed, or rename an ancestor between
two lookups. Fact 4's second walk narrows the second race, but no walk
excludes arbitrary concurrent mutation; the boundary does.

## Observations

Every fact returns exactly one of `CONFIRMED_NEGATIVE`, `SURVIVOR_OBSERVED` or
`OBSERVATION_FAILED`. Only `CONFIRMED_NEGATIVE` can contribute to ABSENT. A
lookup error, an unreadable entry, a link, FIFO, socket or device, or an
exceeded bound is `OBSERVATION_FAILED`, never a zero.

## Census (`take_census`)

The census:

- resolves the declared absolute path component by component from a fresh
  `/`, with `O_NOFOLLOW` at every step;
- holds an `O_PATH` descriptor for every ancestor and for the root;
- holds an `O_PATH` descriptor for every entry beneath the root;
- records each object's identity, mode and link count;
- records the root's device privately, for A-2's mount-table and alias
  evidence.

It closes each descriptor that fails its `fstat` before the census owns it.
Listing stops as soon as the entry budget is exceeded; a directory is never
drained first. Bounds above slice 4's ceilings are refused. `fd_budget_ok`
reserves descriptors at admission, and a census that exceeds a bound, or hits
`EMFILE`, is incomplete, never truncated. Any unexpected exception closes every
descriptor before it propagates.

The census is bound **by identity** to one generation object; an equal object
is not accepted. Its identities are opaque, with no device or inode
attribute. It has a redacted repr, and it refuses pickling and copying.
`release_entries` closes the root and entry descriptors before the unmount
and forgets their numbers, so a later `close` can never close a reused
descriptor. The ancestors stay held for fact 4.

## Fact 1 (`fact_unlinked`)

Fact 1 reads `fstat` through every held entry descriptor, which must still be
the recorded object. All `st_nlink == 0` is CONFIRMED_NEGATIVE. Any nonzero
count is SURVIVOR_OBSERVED: a renamed directory, even an empty one, keeps two
or more links, and a file with any remaining name keeps one or more. The tmpfs
root itself is a mountpoint, so fact 3 (A-2) covers it.

## Fact 4 (`record_mountpoint`, `fact_reresolved`)

At window open, `record_mountpoint` records the empty underlying directory
`M0`, before the tmpfs is mounted over it, and keeps a **live descriptor** to
it. A recycled inode therefore cannot impersonate `M0`. If the directory is
not empty, or cannot be resolved, the result is `None`.

After removal and unmount, `fact_reresolved` re-walks the declared path from a
fresh `/` **twice**. This reconciles the design's "re-walk from the held `/`":
each fresh object is compared against the live descriptors the census and the
`M0` record still hold.

| Outcome | Verdict |
|---|---|
| An ancestor replaced, removed, or now a file or link | OBSERVATION_FAILED, `rescan=True`: scan the replacement; the root stays UNKNOWN |
| An ancestor unreadable (for example EACCES or EIO) | OBSERVATION_FAILED |
| The final component is not the live `M0`, or `M0` is not empty | SURVIVOR_OBSERVED, `rescan=True` (PRESENT) |
| The final component is absent or unreadable | OBSERVATION_FAILED |
| No `M0` record, a closed one, or one from another generation or path | OBSERVATION_FAILED. No mode confirms absence without `M0` |
| Both walks see the live, empty `M0` under unchanged ancestors | CONFIRMED_NEGATIVE |
| The walks disagree | OBSERVATION_FAILED, `rescan=True` |

## Held-descriptor reader (`HeldTree`)

`HeldTree` is slice 4's bounded no-follow reader, rooted at a held directory
descriptor rather than a path string, so a rename of the path cannot redirect
the scan. Its errors are fixed text and are raised outside the handler, so
neither the message nor the exception chain names an entry. Once closed, it
refuses to read. `SafeTree` gained a `_start()` hook for this; its behaviour for
path-rooted readers is unchanged.

## Qualification

`tests/test_run_window_absence.py` uses real temporary trees for the kernel
facts:
- A3: an empty renamed directory is the sole survivor, so a blind fact 1 that
  checks only files also misses it;
- A4: a hard-linked file is a survivor;
- A9: a parent is renamed, the old root removed under it, and a new parent
  with a remnant put in place. The held old parent says "gone"; fact 4 fails
  and asks for a rescan;
- A17: the positive case reads CONFIRMED_NEGATIVE;
- A18: a non-empty `M0`, or a replacement directory (with the original renamed
  aside so its inode stays live), is PRESENT.

Each of A3, A4 and A9 is paired with the blind checker it defeats: a
path-string emptiness check and a files-only fact 1 for A3 and A4, and a
held-parent lookup for A9.

**A8** (unreadable root or ancestor) runs through an injected opener that
raises `PermissionError`, at the ancestor, the root, the listing and an entry.
That twin is what CI runs: CI runs as root, and root bypasses mode bits. A
mode-000 variant runs only when the suite is not root.

The census itself is covered by these cases:
- the entry and depth bounds and the refusal of unsupported bounds (A16);
- `EMFILE` partway through a census;
- `fstat` failure after an open, at `/`, the root and an entry;
- a listing that fails mid-iteration;
- an unexpected exception (descriptor accounting proves no leak);
- special entries and symlinked ancestors;
- generation binding by identity, against an always-equal object (A15, in
  part);
- out-of-order use, and a replaced entry descriptor;
- released descriptor numbers that are never closed again after the kernel
  reuses them.

Fact 4's own cases:
- an ancestor removed, or made into a file or symlink;
- an unreadable ancestor;
- a rename injected between the first walk's ancestor check and its final
  lookup, which the second walk catches;
- an absent final component;
- a missing, failed, closed or wrong-generation `M0` record.

The held reader follows the held object, not a moved path; it never follows a
link, its errors are fixed text, and it refuses use after close.

These cases qualify new instruments; none claims a red run on the parent.

`tests/test_run_window_absence_noleak.py` plants a synthetic marker as a path
segment of the declared root. Under slice 4's `no_marker` oracle, none of these
may disclose the marker, the full root path or an inode number:
- the reprs and strs;
- the fact outcomes;
- refusal messages and their exception chains, including a hostile
  `__fspath__` whose own error text carries the marker;
- the held reader's errors;
- captured stdout, stderr and logs.

It also requires that `Identity` has no device or inode attribute, that every
evidence object refuses pickle and copy, and that a deliberately leaking repr
twin fails the oracle.

## Physical facts

A-1's kernel facts are qualified on the runner VM by probes P1 (link counts
through held fds) and P3 (fact 4 after a real unmount) from #803. A MISMATCH
from either blocks **use** of this module in a window, not the merge of this
code.

## A-2: teardown boundary, facts 2, 2b and 3 (`run_window_teardown`)

**Launch-identity capture (`capture_launch_identity`)** is read-only and
runs once per role or login container, after `prepare()` has started it. It
records:
- from `docker inspect`, through the handle's own environment (the #85 rule):
  the full container ID, the init pid and its start time;
- the cgroup paths;
- the PID, mount, network and IPC namespace links, and PID 1's for
  comparison;
- the bind sources, validated from the inspect JSON;
- the socket fds in init.

The start time is re-read last, so a pid reused mid-capture makes the identity
unusable. `docker_backend` is unchanged: no argv builder is touched, and the
Docker reader permits only `inspect` and `ps`. A test asserts `compose_run_argv`
is byte-identical with the capture in play.

**Teardown boundary (`confirm_teardown`).** CONFIRMED_NEGATIVE only when all
of these hold:
- Docker answered for every captured ID and listed none;
- no process sits at or under a captured cgroup path;
- no process shares a captured namespace.

A process that cannot be read is skipped only if a fresh listing omits it.
Any other unreadable observation, an unanswered Docker, or an unusable or
mixed-generation identity set is OBSERVATION_FAILED. A zombie is still listed
and read; its unreadable namespace links fail the boundary, the fail-safe
reading. A container that shared a host namespace keeps the boundary from ever
reading negative, which is also fail-safe.

**Fact 2 (`fact_no_holder`)** is corroboration and runs while the census
entries are held. Over every surviving pid except the controller's own, it
checks each `/proc/<pid>/fd` and `map_files` entry for the census entries **and
root**. Including the root catches a process that holds a lazily detached
tmpfs through its root directory alone. Census descriptors are `O_CLOEXEC`, so
a child the controller spawns cannot inherit one. A child that somehow holds
one counts as a holder; the exclusion is the controller's pid only, never its
children.

**Fact 2b (`fact_channel_isolated`)** judges the LAUNCH captures and returns
a `ScopedObservation` with `scope == 'launch-only'`. To be negative, every
holder must have had all four namespaces different from PID 1's, no bind
source that is or contains a socket, and no socket fd in init.

**Rule for A-3 (binding):** a `launch-only` 2b is **not sufficient for
ABSENT**. The design's precondition 1.2.5 is a lifetime invariant, which
needs PR-1's fd sampler (A23). Until a lifetime-scoped 2b exists, A-3's
composition must keep every removed surface UNKNOWN whatever the other facts
say. `tests/test_run_window_teardown.py::test_a3_composition_refuses_a_launch_only_isolation_for_absent`
is a strict xfail that turns red when A-3 lands, so this rule cannot be
silently skipped.

**Fact 3 (`fact_superblock_gone`)** runs after the census entries are
released and the caller has unmounted the tmpfs non-lazily. It turns the
census root's recorded device into `major:minor` and requires that no
process's mount table lists it, which catches bind aliases with another
mount ID and copies in other namespaces. Every row must be a well-formed
mountinfo record. An unusable or unreadable table, or an empty population,
is OBSERVATION_FAILED.

**Qualification.**

Fake `/proc` and Docker readers drive these cases, so they run as root or not:
- A5: a process left in the cgroup;
- A6: a non-empty domain that a clean fd census cannot rescue;
- A7: failed reads at the stat, cgroup and namespace sites;
- a vanished pid, versus a lookup error;
- unanswered Docker;
- A10: an alias with a different mount ID, and another namespace's table;
- A21: shared namespaces and init socket fds;
- unusable identity sets.

Each is paired with a blind twin: a Docker-only teardown, a mount-ID-only
fact 3, and a fact 2 that counts the controller itself.

Fact 2 also runs against **real** child processes: one holding a descriptor,
and one holding only a mapping, whose descriptor it closed. The population is
bounded to those pids so an unprivileged run is not failed by other users;
root CI also runs the full census. Socket binds use real socket files. The
`O_CLOEXEC` assertion covers every census descriptor.

`tests/test_run_window_argv_unchanged.py` asserts three things:
- `compose_run_argv` is byte-identical with the capture in play;
- `docker_backend` does not reference the teardown module;
- the Docker reader issues only `inspect` and `ps`, and refuses another verb
  before any process starts.

`tests/test_run_window_teardown_noleak.py` plants a marker in a cgroup path
and a bind source name. No repr, observation or refusal may disclose it or the
container ID, and a leaking twin must fail the oracle.

The physical facts are P2 as root, P3 and P8 from #803. A MISMATCH blocks
**use**, not merge.
