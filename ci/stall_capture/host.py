#!/usr/bin/env python3
"""Hypervisor stall sampler (#484): what the host sees under every VM, every tick.

Reads, never writes (except its own output file), and runs nothing:
- /proc/diskstats for each `--device` - the backing device's own service
  time, the device candidate. Generic over the storage stack (a thin LV, an
  NVMe namespace, a zvol): it was a ZFS per-vdev reader until the storage
  migration made that the wrong instrument, which is why it reads the block
  layer rather than one volume manager's tool;
- for each `--vm LABEL=CGROUP_PATH`, that VM's `io.pressure`, `cpu.pressure`
  and `io.stat` - the neighbour candidate, and the host-side view of CPU.

Labels, devices and cgroup paths are runtime arguments with no defaults: this
file names no host, VM or device (C3).

Usage:
  host.py --device NAME [--device NAME ...] --vm LABEL=CGROUP_PATH [--vm ...] \\
      --interval 10 --duration SECONDS --out host.jsonl [--root /]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ci.stall_capture import loop
from ci.stall_capture import procfs as pf


def sample(root: Path, devices: list[str], vms: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {"devices": pf.parse_diskstats(pf.read(root, "/proc/diskstats"), devices), "vms": {}}
    for label, cgroup in vms.items():
        base = "/" + cgroup.strip("/")
        vm: dict[str, Any] = {
            "io_some_avg10": pf.parse_psi(pf.read(root, f"{base}/io.pressure"))["some"]["avg10"],
            "cpu_some_avg10": pf.parse_psi(pf.read(root, f"{base}/cpu.pressure"))["some"]["avg10"],
        }
        # A hypervisor that does not delegate the io controller to its VM
        # cgroups has io.pressure (PSI is always there) but no io.stat - the
        # first live run met exactly that. Its byte counters are then absent,
        # recorded as such and never zeroed, so attribute.py can say the rate
        # half of the neighbour rule was unassessed.
        if (root / base.lstrip("/") / "io.stat").exists():
            vm.update(pf.parse_io_stat(pf.read(root, f"{base}/io.stat")))
        else:
            vm["io_stat"] = "absent"
        out["vms"][label] = vm
    return out


def parse_vms(specs: list[str]) -> dict[str, str]:
    vms: dict[str, str] = {}
    for spec in specs:
        label, sep, path = spec.partition("=")
        if not sep or not label or not path or label in vms:
            raise ValueError(f"--vm takes a distinct LABEL=CGROUP_PATH, not {spec!r}")
        vms[label] = path
    return vms


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", action="append", required=True)
    ap.add_argument("--vm", action="append", required=True)
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=Path("/"))
    args = ap.parse_args(argv)
    try:
        vms = parse_vms(args.vm)
        loop.check_bounds(args.interval, args.duration)
        sample(args.root, args.device, vms)  # fail fast, before the loop
    except (ValueError, pf.Unreadable) as exc:
        print(f"stall-capture host: refused - {exc}", file=sys.stderr)
        return 2
    ticks = loop.run(lambda: sample(args.root, args.device, vms), source="host",
                     interval=args.interval, duration=args.duration, out=args.out)
    print(f"stall-capture host: {ticks} tick(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
