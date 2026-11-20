# Removed-root absence evidence (Refs #797, Contract A)

This spec implements section 2 of the owner-approved
[run-window contracts design](run-window-contracts.md) (#797, revision 7). The
work is split in three SECRET-PATH parts. Only the last one lifts
`removed-root-absence-contract-unavailable`:

| Part | Delivers | Status |
|---|---|---|
| **A-1** | census of a removed root, fact 1 (unlinked), fact 4 (re-resolved), the held-descriptor reader | this change |
| A-2 | teardown boundary, fact 2 (no holder), fact 2b (channel isolation), fact 3 (superblock gone) | later |
| A-3 | per-surface composition, the total release predicate, the declaration | later; lifts the blocker |

Until A-3 lands, nothing calls this module on a real window. Every
credential window stays held under `vm_credential_window.BLOCKERS`.

## Observations

Every fact returns exactly one of `CONFIRMED_NEGATIVE`, `SURVIVOR_OBSERVED` or
`OBSERVATION_FAILED`. Only `CONFIRMED_NEGATIVE` can contribute to ABSENT. A
lookup error, an unreadable entry, a link, FIFO, socket or device, or an
exceeded bound is `OBSERVATION_FAILED`, never a zero.

## Census (`take_census`)

`take_census` runs after the holder domain is empty, so no writer exists. It:

- resolves the declared absolute path component by component from a fresh
  `/`, with `O_NOFOLLOW` at every step;
- holds an `O_PATH` descriptor for every ancestor and for the root;
- holds an `O_PATH` descriptor for every entry beneath the root;
- records each object's `(st_dev, st_ino)` and reads `st_nlink` later through
  that descriptor.

The entry and depth bounds default to slice 4's ceilings. `fd_budget_ok`
reserves descriptors at admission, and a census that would exceed its bound is
incomplete, never truncated. The census is bound by identity to one opaque
generation object. It has a redacted repr, and it refuses pickling and
copying. `release_entries` closes the root and entry descriptors before the
unmount, and the ancestors stay held.

## Fact 1 (`fact_unlinked`)

Fact 1 reads `fstat` through every held entry descriptor, which must still be
the recorded object. All `st_nlink == 0` is CONFIRMED_NEGATIVE. Any nonzero
count is SURVIVOR_OBSERVED: a renamed directory keeps two or more links, and a
file with any remaining name keeps one or more. The tmpfs root itself is a
mountpoint, so fact 3 (A-2) covers it.

## Fact 4 (`record_mountpoint`, `fact_reresolved`)

At window open the controller records the empty underlying directory `M0`,
before the tmpfs is mounted over it. After removal and unmount it re-walks the
declared path from a fresh `/`:

- **An ancestor that is no longer the recorded object** gives
  OBSERVATION_FAILED with `rescan=True`. The replacement path must be scanned,
  and the root stays UNKNOWN. A lookup through the held old parent would say
  "gone", which is why fact 4 does not use one.
- **A path that is not `M0`, or an `M0` that is not empty,** is
  SURVIVOR_OBSERVED with `rescan=True`. This is PRESENT. Slice 4 scans it as a
  new population, and the original's absence still comes only from fact 1.
- **With no `M0` record**, the final component must be absent.

## Held-descriptor reader (`HeldTree`)

`HeldTree` is slice 4's bounded no-follow reader, rooted at a held directory
descriptor rather than a path string. A rename or replacement of the path
after the root was resolved cannot redirect the scan. `SafeTree` gained a
`_start()` hook for this; its behaviour for path-rooted readers is unchanged.

## Qualification

`tests/test_run_window_absence.py` uses real temporary trees for the kernel
facts:
- A3: a renamed directory is a survivor;
- A4: a hard-linked file is a survivor;
- A9: a replaced parent fails and asks for a rescan;
- A17: the positive case reads CONFIRMED_NEGATIVE;
- A18: a non-empty or recreated mountpoint is PRESENT.

Each of A3, A4 and A9 is paired with the blind checker it defeats: a
path-string emptiness check for A3 and A4, and a held-parent lookup for A9.

**A8** (unreadable root or ancestor) runs through an injected opener that
raises `PermissionError`, at the ancestor, the root, the listing and an entry.
That twin is what CI runs: CI runs as root, and root bypasses mode bits. A
mode-000 variant runs only when the suite is not root.

The census itself is covered by these cases:
- the entry and depth bounds (A16);
- the descriptor budget;
- special entries and symlinked ancestors;
- the generation binding (A15, in part);
- out-of-order use;
- an entry descriptor replaced under its recorded identity;
- the held reader following the held object, not a moved path.

These cases qualify new instruments; none claims a red run on the parent.

`tests/test_run_window_absence_noleak.py` plants a synthetic marker as a path
segment of the declared root. It requires that no repr, fact outcome, refusal
message, or captured stdout, stderr or log line discloses that segment, the
root path or an inode number, under slice 4's `no_marker` oracle. It also
requires that every evidence object refuses pickle and copy, and that a
deliberately leaking repr twin fails the oracle.

## Physical facts

A-1's kernel facts are qualified on the runner VM by probes P1 (link counts
through held fds) and P3 (fact 4 after a real unmount) from #803. A MISMATCH
from either blocks **use** of this module in a window, not the merge of this
code.
