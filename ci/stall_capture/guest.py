#!/usr/bin/env python3
"""Guest stall sampler (#484): what a CI VM sees of its own stalls, every tick.

Reads, never writes (except its own output file), and runs nothing:
- /proc/pressure/{io,cpu,memory} - the stall itself, as the kernel measures it;
- /proc/diskstats for the named device - including the discard columns, the
  online-discard candidate;
- the aggregate cpu line of /proc/stat - steal, the hypervisor-overcommit
  candidate;
- each container cgroup under `--cgroup-root` matching `--cgroup-glob` -
  `cpu.stat` throttling and `cpu.max`, the per-container CPU-cap candidate,
  plus its `io.pressure`.

The device and the cgroup root are runtime arguments with no defaults: this
file names no host, VM or device (C3). `--root` re-roots every path, which is
how the tests drive it against a committed fake tree.

Usage:
  guest.py --device NAME --cgroup-root PATH [--cgroup-glob GLOB] \\
      --interval 10 --duration SECONDS --out guest.jsonl [--root /]
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


def sample(root: Path, device: str, cgroup_root: str, cgroup_glob: str = "*") -> dict[str, Any]:
    psi = {r: pf.parse_psi(pf.read(root, f"/proc/pressure/{r}")) for r in ("io", "cpu", "memory")}
    disk = pf.parse_diskstats(pf.read(root, "/proc/diskstats"), [device])[device]
    cgroups: dict[str, dict[str, Any]] = {}
    base = root / cgroup_root.lstrip("/")
    if not base.is_dir():
        # A mistyped root would otherwise sample zero containers forever, which
        # reads as "nothing was throttled".
        raise pf.Unreadable(f"--cgroup-root {cgroup_root}: not a directory")
    for path in sorted(p for p in base.glob(cgroup_glob) if p.is_dir()):
        rel = "/" + str(path.relative_to(root))
        cpu = pf.parse_keyed(pf.read(root, f"{rel}/cpu.stat"))
        cgroups[path.name] = {
            "nr_throttled": cpu.get("nr_throttled", 0), "throttled_usec": cpu.get("throttled_usec", 0),
            "usage_usec": cpu.get("usage_usec", 0),
            "cpu_max": pf.read(root, f"{rel}/cpu.max").strip(),
            "io_some_avg10": pf.parse_psi(pf.read(root, f"{rel}/io.pressure"))["some"]["avg10"],
        }
    return {"device": device, "psi": {r: {"some_avg10": v["some"]["avg10"],
                                          "full_avg10": v.get("full", {}).get("avg10", 0.0)}
                                      for r, v in psi.items()},
            "disk": disk, "cpu": pf.parse_cpu_ticks(pf.read(root, "/proc/stat")), "cgroups": cgroups}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", required=True)
    ap.add_argument("--cgroup-root", required=True)
    ap.add_argument("--cgroup-glob", default="*")
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=Path("/"))
    args = ap.parse_args(argv)
    try:
        loop.check_bounds(args.interval, args.duration)
        sample(args.root, args.device, args.cgroup_root, args.cgroup_glob)  # fail fast, before the loop
    except (ValueError, pf.Unreadable) as exc:
        print(f"stall-capture guest: refused - {exc}", file=sys.stderr)
        return 2
    ticks = loop.run(lambda: sample(args.root, args.device, args.cgroup_root, args.cgroup_glob),
                     source="guest", interval=args.interval, duration=args.duration, out=args.out)
    print(f"stall-capture guest: {ticks} tick(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
