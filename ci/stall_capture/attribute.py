#!/usr/bin/env python3
"""Attribute the stalls in a guest stream to a cause (#484).

A STALL WINDOW is a run of consecutive guest ticks whose io or cpu
`some avg10` pressure reaches its threshold. Its KIND is which of the two did:
an io stall is explained only by io causes and a cpu stall only by cpu
causes, so a CPU burn can never be booked to the disk (orchestrator C1).

Causes, each a rule over the window plus one lead-in tick:
- io  `discard`:   the guest device discarded at least `--discard-mbps` and
                   more bytes than it wrote - online discard dominating I/O;
- io  `device`:    a host backing device's await reached `--device-await-ms`;
- io  `neighbour`: another VM's io pressure reached `--neighbour-io-psi`, or
                   its I/O rate `--neighbour-mbps`;
- cpu `steal`:     steal was at least `--steal-share` of guest CPU time;
- cpu `throttle`:  a container cgroup spent `--throttle-share` of the window
                   throttled - a per-container CPU cap biting;
- cpu `contention`: cpu pressure with neither of the above - more runnable
                   work than CPUs.

The VERDICT is the one cause that held, `ambiguous` when several did, and
`UNATTRIBUTED` when none did. It is never forced to a label. Host-side rules
with no host tick inside the window are listed as `unassessed`, so a guest-only
`discard` verdict says which alternatives nobody looked at.

An empty guest stream, a stream of error records, or a host stream that does
not overlap the guest one is REFUSED (exit 2): nothing to look at is not the
same as no stalls. The summary line always states the sample count, so a zero
can be read for what it covered.

Usage:
  attribute.py --guest guest.jsonl [--host host.jsonl --self-vm LABEL] [--out report.json]
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ci.stall_capture.procfs import SECTOR_BYTES

IO_CAUSES = ("discard", "device", "neighbour")
CPU_CAUSES = ("steal", "throttle", "contention")
HOST_RULES = ("device", "neighbour")


class Refused(Exception):
    """The input cannot support any verdict, including 'no stalls'."""


@dataclass(frozen=True)
class Thresholds:
    io_psi: float = 50.0
    cpu_psi: float = 50.0
    discard_mbps: float = 100.0
    device_await_ms: float = 50.0
    neighbour_io_psi: float = 30.0
    neighbour_mbps: float = 100.0
    steal_share: float = 0.2
    throttle_share: float = 0.1


def load(path: Path, source: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise Refused(f"{path}: {exc.strerror or exc}") from None
    records = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            raise Refused(f"{path}:{n} is not JSON") from None
        if record.get("source") != source:
            raise Refused(f"{path}:{n} is a {record.get('source')!r} record, not {source!r}")
        records.append(record)
    return sorted(records, key=lambda r: float(r["t"]))


def _usable(records: list[dict[str, Any]], what: str) -> tuple[list[dict[str, Any]], int]:
    good = [r for r in records if "error" not in r]
    if len(good) < 2:
        raise Refused(f"{what} stream has {len(good)} usable sample(s) ({len(records) - len(good)} error "
                      "record(s)); at least two are needed to compute a rate")
    return good, len(records) - len(good)


def _mbps(a: dict[str, Any], b: dict[str, Any], key: str, dt: float) -> float:
    """MB/s of a cumulative sector counter between two samples."""
    return (b[key] - a[key]) * SECTOR_BYTES / 1e6 / dt if dt > 0 else 0.0


def _guest_tick(prev: dict[str, Any], cur: dict[str, Any]) -> dict[str, float]:
    disk_p, disk_c = prev["disk"], cur["disk"]
    dt = float(cur["t"]) - float(prev["t"])
    total = cur["cpu"]["total"] - prev["cpu"]["total"]
    throttled = max((c["throttled_usec"] - prev["cgroups"].get(name, c)["throttled_usec"]
                     for name, c in cur["cgroups"].items()), default=0)
    return {
        "t": float(cur["t"]),
        "io_psi": cur["psi"]["io"]["some_avg10"], "cpu_psi": cur["psi"]["cpu"]["some_avg10"],
        "discard_mbps": _mbps(disk_p, disk_c, "discard_sectors", dt),
        "write_mbps": _mbps(disk_p, disk_c, "write_sectors", dt),
        "steal_share": (cur["cpu"]["steal"] - prev["cpu"]["steal"]) / total if total > 0 else 0.0,
        "throttle_share": throttled / (dt * 1e6) if dt > 0 else 0.0,
    }


def _host_tick(prev: dict[str, Any], cur: dict[str, Any], self_vm: str | None) -> dict[str, Any]:
    awaits = {}
    for dev, c in cur["devices"].items():
        p = prev["devices"].get(dev, c)
        ios = sum(c[k] - p[k] for k in ("reads", "writes", "discards"))
        ms = sum(c[k] - p[k] for k in ("read_ms", "write_ms", "discard_ms"))
        awaits[dev] = ms / ios if ios > 0 else 0.0
    neighbours = {}
    for vm, c in cur["vms"].items():
        if vm == self_vm:
            continue
        p = prev["vms"].get(vm, c)
        dt = float(cur["t"]) - float(prev["t"])
        mbps = (c["rbytes"] + c["wbytes"] - p["rbytes"] - p["wbytes"]) / dt / 1e6 if dt > 0 else 0.0
        neighbours[vm] = {"io_psi": c["io_some_avg10"], "mbps": mbps}
    return {"t": float(cur["t"]), "await_ms": awaits, "neighbours": neighbours}


@dataclass
class Stall:
    start: float
    end: float
    ticks: int
    kind: list[str]
    peak_io_psi: float
    peak_cpu_psi: float
    causes: list[str]
    verdict: str
    evidence: dict[str, Any]
    unassessed: list[str]


def _windows(ticks: list[dict[str, float]], th: Thresholds) -> list[list[dict[str, float]]]:
    windows: list[list[dict[str, float]]] = []
    run: list[dict[str, float]] = []
    for tick in ticks:
        if tick["io_psi"] >= th.io_psi or tick["cpu_psi"] >= th.cpu_psi:
            run.append(tick)
        elif run:
            windows.append(run)
            run = []
    if run:
        windows.append(run)
    return windows


def _judge(window: list[dict[str, float]], lead: dict[str, float] | None, host: list[dict[str, Any]] | None,
           th: Thresholds, interval: float) -> Stall:
    span = ([lead] if lead else []) + window
    kind = [k for k, hit in (("io", any(t["io_psi"] >= th.io_psi for t in window)),
                             ("cpu", any(t["cpu_psi"] >= th.cpu_psi for t in window))) if hit]
    evidence: dict[str, Any] = {}
    causes: list[str] = []
    unassessed: list[str] = []
    if "io" in kind:
        discard = max(t["discard_mbps"] for t in span)
        writes = max(t["write_mbps"] for t in span)
        evidence["discard_mbps_max"], evidence["write_mbps_max"] = round(discard, 1), round(writes, 1)
        if discard >= th.discard_mbps and discard > writes:
            causes.append("discard")
        lo, hi = span[0]["t"] - interval, window[-1]["t"]
        inside = [h for h in host if lo <= h["t"] <= hi] if host is not None else []
        if not inside:
            unassessed.extend(HOST_RULES)
        else:
            worst = max(((d, a) for h in inside for d, a in h["await_ms"].items()), key=lambda x: x[1],
                        default=("-", 0.0))
            evidence["device_await_ms_max"] = {"device": worst[0], "ms": round(worst[1], 1)}
            if worst[1] >= th.device_await_ms:
                causes.append("device")
            busy = sorted({vm for h in inside for vm, n in h["neighbours"].items()
                           if n["io_psi"] >= th.neighbour_io_psi or n["mbps"] >= th.neighbour_mbps})
            evidence["busy_neighbours"] = busy
            if busy:
                causes.append("neighbour")
    if "cpu" in kind:
        steal = max(t["steal_share"] for t in span)
        throttle = max(t["throttle_share"] for t in span)
        evidence["steal_share_max"], evidence["throttle_share_max"] = round(steal, 3), round(throttle, 3)
        cpu_causes = [c for c, hit in (("steal", steal >= th.steal_share),
                                       ("throttle", throttle >= th.throttle_share)) if hit]
        causes.extend(cpu_causes or ["contention"])
    verdict = causes[0] if len(causes) == 1 else ("ambiguous" if causes else "UNATTRIBUTED")
    return Stall(start=window[0]["t"], end=window[-1]["t"], ticks=len(window), kind=kind,
                 peak_io_psi=max(t["io_psi"] for t in window), peak_cpu_psi=max(t["cpu_psi"] for t in window),
                 causes=causes, verdict=verdict, evidence=evidence, unassessed=unassessed)


def attribute(guest: list[dict[str, Any]], host: list[dict[str, Any]] | None = None, *,
              self_vm: str | None = None, th: Thresholds | None = None) -> dict[str, Any]:
    th = th or Thresholds()
    good, guest_errors = _usable(guest, "guest")
    ticks = [_guest_tick(a, b) for a, b in itertools.pairwise(good)]
    interval = (ticks[-1]["t"] - float(good[0]["t"])) / len(ticks)
    host_ticks = None
    host_errors = 0
    if host is not None:
        if self_vm is None:
            raise Refused("--host needs --self-vm: which VM label is the guest, so it is not its own neighbour")
        hgood, host_errors = _usable(host, "host")
        if self_vm not in hgood[-1]["vms"]:
            raise Refused(f"--self-vm {self_vm!r} is not a VM label in the host stream "
                          f"({sorted(hgood[-1]['vms'])})")
        if float(hgood[-1]["t"]) < float(good[0]["t"]) or float(hgood[0]["t"]) > float(good[-1]["t"]):
            raise Refused("the host stream does not overlap the guest stream in time")
        host_ticks = [_host_tick(a, b, self_vm) for a, b in itertools.pairwise(hgood)]
    stalls = []
    for window in _windows(ticks, th):
        i = ticks.index(window[0])
        stalls.append(_judge(window, ticks[i - 1] if i > 0 else None, host_ticks, th, interval))
    summary: dict[str, int] = {}
    for s in stalls:
        summary[s.verdict] = summary.get(s.verdict, 0) + 1
    return {"guest_samples": len(good), "guest_error_records": guest_errors,
            "host_samples": None if host is None else len(host) - host_errors,
            "host_error_records": None if host is None else host_errors,
            "span_seconds": round(ticks[-1]["t"] - float(good[0]["t"]), 1),
            "thresholds": asdict(th), "stalls": [asdict(s) for s in stalls], "verdicts": summary}


def headline(report: dict[str, Any]) -> str:
    host = ("no host stream" if report["host_samples"] is None
            else f"{report['host_samples']} host sample(s)")
    verdicts = ", ".join(f"{k}={v}" for k, v in sorted(report["verdicts"].items())) or "none"
    return (f"stall-capture: {len(report['stalls'])} stall window(s) in {report['guest_samples']} guest "
            f"sample(s) over {report['span_seconds']} s ({host}); verdicts: {verdicts}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--guest", type=Path, required=True)
    ap.add_argument("--host", type=Path)
    ap.add_argument("--self-vm")
    ap.add_argument("--out", type=Path)
    for name, value in asdict(Thresholds()).items():
        ap.add_argument("--" + name.replace("_", "-"), type=float, default=value)
    args = ap.parse_args(argv)
    th = Thresholds(**{k: getattr(args, k) for k in asdict(Thresholds())})
    try:
        report = attribute(load(args.guest, "guest"), load(args.host, "host") if args.host else None,
                           self_vm=args.self_vm, th=th)
    except Refused as exc:
        print(f"stall-capture: refused - {exc}", file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(headline(report))
    for s in report["stalls"]:
        note = f" (unassessed: {', '.join(s['unassessed'])})" if s["unassessed"] else ""
        print(f"  {s['start']:.0f}-{s['end']:.0f} {'+'.join(s['kind'])} -> {s['verdict']}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
