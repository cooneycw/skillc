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

**Preconditions.** The controller establishes these and this module does
not re-prove them:
- **The controller runs as root in the initial PID namespace, with an
  unfiltered procfs.** `procfs_ok` checks the visible parts: a nonempty
  population, the same PID namespace as pid 1, and no `hidepid` or `subset`
  option on `/proc`. Every fact refuses without it.
- **The holder domain is empty,** so the only processes left are the declared
  host workload. A descriptor transfer between surviving host processes during
  a scan is outside that workload's behaviour. Fact 2's second pass narrows
  that race; it cannot exclude it.

**Launch-identity capture (`capture_launch_identity`)** is read-only. It runs
once per role or login container, after `prepare()` starts it and before any
dispatch. It binds the inspected full container ID to a live task in **this
host's** procfs. The task's cgroup must name the ID; its start time is read
before and after the other reads; and Docker must report the same ID and pid
again at the end. A pid reused before the first read, or a pid from another
daemon's host, therefore makes the identity unusable. It records:
- the cgroup entries as `(hierarchy, controllers, path)`;
- validated namespace links, and pid 1's for comparison;
- sockets counted at each bind's **destination** in the task's own root,
  without following any link, rather than at the host source path, which
  could have been replaced;
- the init socket fds, read twice and compared.

`docker_backend` is unchanged, and the Docker reader permits only `inspect`
and `ps`.

**Teardown boundary (`confirm_teardown`).** CONFIRMED_NEGATIVE only when all
of these hold:
- Docker answered with an empty list for every captured ID; any other output
  is no answer;
- no **task** (every `/proc/<pid>/task/<tid>`) sits at or under a captured
  cgroup path in the same hierarchy;
- no task shares a captured namespace.

An empty or failed population, a malformed record, a reader exception, or an
unusable or mixed-generation identity set (compared by identity, never
equality or hashing) is OBSERVATION_FAILED. A task that cannot be read is
skipped only if a fresh listing omits its process. A zombie is still listed
and read; if it cannot be read the boundary fails, the fail-safe reading.

**Fact 2 (`fact_no_holder`)** is corroboration and runs while the census
entries are held. It checks:
- every surviving **task's** fd table, since a task can own its own after
  `unshare(CLONE_FILES)`;
- every process's `map_files`.

The targets are the census entries **and the census root**, which catches a
holder that keeps a lazily detached tmpfs through its root alone. Each task's
start time is pinned across its reads, and a replaced task is FAILED. Two
passes must agree. The controller's own tasks are excluded, never its
children. Census descriptors are `O_CLOEXEC` explicitly.

**Fact 2b (`fact_channel_isolated`)** judges the LAUNCH captures and returns
a `ScopedObservation` with `scope == 'launch-only'`.

**Rule for A-3 (binding):** a `launch-only` 2b is **not sufficient for
ABSENT**. The design's precondition 1.2.5 is a lifetime invariant, which needs
PR-1's fd sampler (A23). Until a lifetime-scoped 2b exists, A-3's composition
must keep every removed surface UNKNOWN. Two further rules hold whatever
fact 2 says:
- a non-empty domain vetoes ABSENT;
- a SURVIVOR from fact 2 vetoes ABSENT.

`tests/test_run_window_teardown.py::test_a3_composition_refuses_a_launch_only_isolation_for_absent`
is skipped only while A-3's module does not exist. From the moment it exists
the test runs, and it must be adapted to A-3's entry point, never deleted.

**Fact 3 (`fact_superblock_gone`)** runs after the census entries are
released and the caller has unmounted the tmpfs non-lazily. It reads every
task's mount table, each parsed as complete kernel records. Every mount
namespace must be read through a task whose root is the namespace root (its
record mounted at `/` has root `/`). A namespace seen only through chrooted
tasks is OBSERVATION_FAILED, because such a table omits mounts outside the
chroot. Fact 3 is negative only if no table lists the census root's
`major:minor`, which catches aliases under another mount ID and copies in
other namespaces.

**Reader errors** are sanitised to fixed text, with no filename, payload or
exception context. A Docker reader that raises counts as unanswered.

**Qualification.**

Fake `/proc` cases, which run under any user:
- per-task views: a worker task alone in the cgroup, and a holder only in a
  worker's fd table;
- a container root view: a replaced bind source, and a link on the
  destination path;
- chrooted and other-namespace tables;
- the cases from the plan: A5, A6, A7, A10 and A21;
- pid reuse before the first read; another daemon's host; a container
  changed during capture;
- a same path in another v1 hierarchy; malformed links and records;
- empty, failed and unreadable populations; a raising Docker reader;
  malformed `ps` output;
- an unhashable, always-equal generation.

Blind twins: a Docker-only teardown, a mount-ID-only fact 3, and a fact 2
that counts the controller itself.

**Real** fact 2 uses child processes: an fd holder, and a mapping-only holder
with its fd closed. These are gated on the kernel granting `map_files` access,
and are otherwise qualified by VM probe P2. A recording opener asserts that
every census open requests `O_CLOEXEC`, and `F_GETFD` confirms it on every
descriptor.

`tests/test_run_window_argv_unchanged.py` compares `compose_run_argv` with a
**reviewed literal baseline** and asserts the exact `inspect` and `ps`
commands and environment. `tests/test_run_window_teardown_noleak.py` plants a
marker in a cgroup path and a bind name, and a leaking twin must fail the
oracle.

The physical facts are P2 as root, P3 and P8 from #803. A MISMATCH blocks
**use**, not merge.
