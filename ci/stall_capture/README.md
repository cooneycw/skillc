# Stall capture (#484)

A read-only monitor for the CI host's I/O and CPU stalls, and an attribution
script that names a cause for each stall without forcing one.

It was **built from replayed fixtures only**, and nothing here has run on any
host. A live sampler run, a live CPU-burn control and any A/B are separate
steps, each gated on the orchestrator's GO.

## Read this first: the baseline moved

The stall numbers in #484 (pipelines 963 and 968, psi_io10 61-90) were measured
**before the storage migration** that moved every VM disk to new storage. They
are pre-migration evidence only. Nothing measured before the migration says
anything about the host as it is now, and the first live run here re-measures
it from zero.

**After the migration (checked 2026-10-28):** about 70 skillc pipelines ran,
and almost all were green. One failure looked like a stall: pipeline 1111
(2026-10-25), where five tests hit the 120 s timeout during setup while
psi_io10 stayed between 30 and 45 for over a minute, on a 16-CPU agent. That
is milder than the original 61-90, but above the issue's target of 20. So the
stalls are rarer, not shown to be gone.

There are now two CI agents. A live run samples one VM, so it has to say which
agent it ran on, and a full window means one run per agent.

## The three parts

| Script | Runs on | Reads | Writes |
|---|---|---|---|
| `guest.py` | the CI VM | `/proc/pressure/{io,cpu,memory}`, `/proc/diskstats` (one named device, including discard columns), `/proc/stat` (steal), each container cgroup's `cpu.stat`, `cpu.max` and `io.pressure` | its own `--out` JSONL only |
| `host.py` | the hypervisor | `/proc/diskstats` (named backing devices), each named VM cgroup's `io.pressure`, `cpu.pressure` and `io.stat` | its own `--out` JSONL only |
| `attribute.py` | anywhere | the two JSONL streams | its `--out` report |

Both samplers are read-only by construction, and `tests/test_stall_capture.py`
checks that structurally: they hold no write, no `subprocess` and no `os`
mutator. Each one is bounded: `--duration` is required, with a 6-hour cap, and
`--interval` is at least 1 s. A tick that cannot be read becomes an `error`
record and is never skipped, because a gap is evidence too.

`host.py` reads the block layer, not a volume manager's own tool. It was first
designed as a ZFS per-vdev reader, and the migration off ZFS made that the
wrong instrument. `/proc/diskstats` works the same under a thin LV, an NVMe
namespace or a zvol.

## No names in this tree (C3)

Every host, VM, device and cgroup name is a runtime argument with no default.
The fixtures use placeholders only (`dev-g`, `dev-a`, `vm-ci`, `vm-a`,
`ctr-a`), and a test allows exactly those. Pass the real names on the command
line when running, and never commit them.

## Attribution

A **stall window** is a run of guest ticks where io or cpu `some avg10` reaches
its threshold (default 50, matching #484's interim retry rule). Its **kind**
decides which causes may explain it:

| Kind | Cause | Rule (defaults) |
|---|---|---|
| io | `discard` | the guest device discarded at least 100 MB/s, and more than it wrote |
| io | `device` | a host backing device's await reached 50 ms |
| io | `neighbour` | another VM's io pressure reached 30, or its I/O reached 100 MB/s |
| cpu | `steal` | steal was at least 20% of guest CPU time |
| cpu | `throttle` | a container cgroup spent at least 10% of the window throttled |
| cpu | `contention` | cpu pressure with neither of the above |

The verdict is the one cause that held, `ambiguous` if several held, and
`UNATTRIBUTED` if none did. When no host tick falls inside a window, `device`
and `neighbour` are listed as **unassessed** rather than dropped, so a
guest-only `discard` verdict names the alternatives nobody checked.

The **CPU-burn control** (C1) is the `cpuburn` fixture: cpu pressure with io
quiet must book to `contention` and never to an io cause. Here it is replayed
only.

**Nothing to look at is refused, not reported as clean.** An empty guest
stream, a stream of `error` records, or a host stream that does not overlap the
guest stream in time exits 2. A real zero always states its coverage:
`0 stall window(s) in N guest sample(s) over S s`.

## Running it later (only on a GO)

```bash
# On the CI VM:
ci/stall_capture/guest.py --device <disk> --cgroup-root <pipeline cgroup dir> \
    --interval 10 --duration 3600 --out guest.jsonl
# On the hypervisor:
ci/stall_capture/host.py --device <backing dev> --vm vm-ci=<CI VM cgroup> --vm vm-a=<other VM cgroup> \
    --interval 10 --duration 3600 --out host.jsonl
# Anywhere:
ci/stall_capture/attribute.py --guest guest.jsonl --host host.jsonl --self-vm vm-ci --out report.json
```

Labels such as `vm-ci` are yours to choose at run time. Keep the run output
out of the repository, since it carries real names.

## Out of scope here (C2, C4)

There is no I/O load generator and no discard A/B. If those are ever approved,
the A/B arms alternate (C4), with `fstrim` between arms.

## Fixtures

`tests/fixtures/stall-capture/make_fixtures.py` writes them. A test fails if a
committed file drifts from what the script writes. The data is synthetic, not
measured.
