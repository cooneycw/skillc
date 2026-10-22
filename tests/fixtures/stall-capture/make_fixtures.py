#!/usr/bin/env python3
"""Write the replay fixtures for ci/stall_capture (#484): `<scenario>.guest.jsonl`
and `<scenario>.host.jsonl` beside this file. `tests/test_stall_capture.py`
regenerates them in memory and fails if a committed file drifts.

Synthetic, not measured: twelve 10 s ticks of a CI VM, with ticks 5-7 carrying
the scenario's signature. Every name is a placeholder (C3) - devices `dev-g`
(the guest disk) and `dev-a`, VMs `vm-ci` (the guest) and `vm-a`, container
cgroup `ctr-a` - and nothing here is a reading of any real host. Times start at
an arbitrary epoch offset, and the host stream ticks 3 s after the guest, so
the attribution's time join is exercised rather than assumed."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
T0 = 1_000_000.0
TICK = 10.0
TICKS = 12
STALL = range(5, 8)
LEAD = range(4, 8)
MB_SECTORS = 1e6 / 512
CPU_TICKS = 8 * 100 * TICK  # 8 vCPUs at USER_HZ 100

#: Placeholder names: the C3 guard test allows exactly these and nothing else.
PLACEHOLDERS = {"device": {"dev-g", "dev-a", "dev-b"}, "vm": {"vm-ci", "vm-a", "vm-b"},
                "cgroup": {"ctr-a", "ctr-b"}}

GuestTweak = Callable[[int, dict[str, Any]], None]
HostTweak = Callable[[int, dict[str, Any]], None]


def _guest(tweak: GuestTweak | None) -> list[dict[str, Any]]:
    disk = {"reads": 0, "read_sectors": 0, "read_ms": 0, "writes": 0, "write_sectors": 0, "write_ms": 0,
            "discards": 0, "discard_sectors": 0, "discard_ms": 0, "io_ms": 0, "in_flight": 0}
    cpu = {"total": 0, "steal": 0, "iowait": 0}
    throttled = 0
    out = []
    for i in range(TICKS):
        step = {"psi_io": 2.0, "psi_cpu": 3.0, "write_mb": 20.0, "discard_mb": 0.5, "steal": 0.0,
                "throttle_s": 0.0}
        if tweak:
            tweak(i, step)
        disk["writes"] += 1000
        disk["write_sectors"] += int(step["write_mb"] * TICK * MB_SECTORS)
        disk["discards"] += 50
        disk["discard_sectors"] += int(step["discard_mb"] * TICK * MB_SECTORS)
        cpu["total"] += int(CPU_TICKS)
        cpu["steal"] += int(step["steal"] * CPU_TICKS)
        throttled += int(step["throttle_s"] * 1e6)
        out.append({"source": "guest", "t": T0 + i * TICK, "device": "dev-g",
                    "psi": {"io": {"some_avg10": step["psi_io"], "full_avg10": step["psi_io"] / 2},
                            "cpu": {"some_avg10": step["psi_cpu"], "full_avg10": 0.0},
                            "memory": {"some_avg10": 0.0, "full_avg10": 0.0}},
                    "disk": dict(disk), "cpu": dict(cpu),
                    "cgroups": {"ctr-a": {"nr_throttled": throttled // 100_000, "throttled_usec": throttled,
                                          "usage_usec": i * 4_000_000, "cpu_max": "max 100000",
                                          "io_some_avg10": step["psi_io"]}}})
    return out


def _host(tweak: HostTweak | None) -> list[dict[str, Any]]:
    dev = {"reads": 0, "read_ms": 0, "writes": 0, "write_ms": 0, "discards": 0, "discard_ms": 0,
           "read_sectors": 0, "write_sectors": 0, "discard_sectors": 0}
    vms = {"vm-ci": {"io_some_avg10": 2.0, "cpu_some_avg10": 3.0, "rbytes": 0, "wbytes": 0},
           "vm-a": {"io_some_avg10": 1.0, "cpu_some_avg10": 1.0, "rbytes": 0, "wbytes": 0}}
    out = []
    for i in range(TICKS):
        step = {"await_ms": 1.0, "neighbour_psi": 1.0, "neighbour_mb": 1.0}
        if tweak:
            tweak(i, step)
        dev["writes"] += 1100
        dev["write_ms"] += int(1100 * step["await_ms"])
        vms["vm-ci"]["wbytes"] += int(20e6 * TICK)
        vms["vm-a"]["wbytes"] += int(step["neighbour_mb"] * 1e6 * TICK)
        vms["vm-a"]["io_some_avg10"] = step["neighbour_psi"]
        out.append({"source": "host", "t": T0 + 3 + i * TICK, "devices": {"dev-a": dict(dev)},
                    "vms": {k: dict(v) for k, v in vms.items()}})
    return out


def _during(window: range, **values: float) -> Callable[[int, dict[str, Any]], None]:
    def tweak(i: int, step: dict[str, Any]) -> None:
        if i in window:
            step.update(values)
    return tweak


def _both(*tweaks: Callable[[int, dict[str, Any]], None]) -> Callable[[int, dict[str, Any]], None]:
    def tweak(i: int, step: dict[str, Any]) -> None:
        for t in tweaks:
            t(i, step)
    return tweak


#: scenario -> (guest tweak, host tweak, the verdict its one stall must get)
SCENARIOS: dict[str, tuple[GuestTweak | None, HostTweak | None, str | None]] = {
    "quiet": (None, None, None),
    "discard": (_both(_during(STALL, psi_io=75.0), _during(LEAD, discard_mb=800.0)), None, "discard"),
    "device": (_during(STALL, psi_io=80.0), _during(STALL, await_ms=200.0), "device"),
    "neighbour": (_during(STALL, psi_io=70.0), _during(STALL, neighbour_psi=60.0, neighbour_mb=300.0),
                  "neighbour"),
    # C1's CPU-burn control: cpu pressure with io quiet must book to CPU, never to the disk.
    "cpuburn": (_during(STALL, psi_cpu=85.0), None, "contention"),
    "steal": (_during(STALL, psi_cpu=60.0, steal=0.35), None, "steal"),
    "throttle": (_during(STALL, psi_cpu=55.0, throttle_s=3.0), None, "throttle"),
    "mixed": (_both(_during(STALL, psi_io=80.0), _during(LEAD, discard_mb=800.0)), _during(STALL, await_ms=200.0),
              "ambiguous"),
}


def render(scenario: str) -> dict[str, str]:
    guest_tweak, host_tweak, _ = SCENARIOS[scenario]
    return {f"{scenario}.{name}.jsonl": "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
            for name, records in (("guest", _guest(guest_tweak)), ("host", _host(host_tweak)))}


def main() -> int:
    for scenario in SCENARIOS:
        for name, text in render(scenario).items():
            (HERE / name).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
