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
`UNATTRIBUTED` when none did. It is never forced to a label. A rule with no
observation behind it is listed as `unassessed` rather than counted as quiet:
host rules with no host interval overlapping the window, `neighbour` when the
host stream names no VM but the guest, `throttle` when no container was seen
in two consecutive samples, and any rate on the first sample (which has no
predecessor). So a verdict says which alternatives nobody looked at.

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
import math
import statistics
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

    def __post_init__(self) -> None:
        # A NaN threshold makes every comparison false: a zero-stall report
        # from a detector that could not fire.
        bad = [k for k, v in asdict(self).items() if not math.isfinite(v)]
        if bad:
            raise Refused(f"non-finite threshold(s): {', '.join(bad)}")


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


def _consecutive(records: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Pairs of usable records with no error record between them: a rate is
    never computed across a gap."""
    return [(a, b) for a, b in itertools.pairwise(records) if "error" not in a and "error" not in b]


def _mbps(a: dict[str, Any], b: dict[str, Any], key: str, dt: float) -> float:
    """MB/s of a cumulative sector counter between two samples."""
    return (b[key] - a[key]) * SECTOR_BYTES / 1e6 / dt if dt > 0 else 0.0


def _guest_tick(prev: dict[str, Any] | None, cur: dict[str, Any]) -> dict[str, Any]:
    """One guest tick. Pressure is a reading of `cur` alone, so every sample,
    the first included, can open a stall window. Rates need `prev`: without
    it they are None (unassessed), never 0."""
    tick: dict[str, Any] = {"t": float(cur["t"]), "io_psi": cur["psi"]["io"]["some_avg10"],
                            "cpu_psi": cur["psi"]["cpu"]["some_avg10"], "discard_mbps": None,
                            "write_mbps": None, "steal_share": None, "throttle_share": None}
    if prev is None:
        return tick
    disk_p, disk_c = prev["disk"], cur["disk"]
    dt = float(cur["t"]) - float(prev["t"])
    total = cur["cpu"]["total"] - prev["cpu"]["total"]
    tick["discard_mbps"] = _mbps(disk_p, disk_c, "discard_sectors", dt)
    tick["write_mbps"] = _mbps(disk_p, disk_c, "write_sectors", dt)
    tick["steal_share"] = (cur["cpu"]["steal"] - prev["cpu"]["steal"]) / total if total > 0 else 0.0
    # Only containers seen in BOTH samples have a throttling delta. None of them
    # is "no container was observed", which is not "no container was throttled".
    both = [name for name in cur["cgroups"] if name in prev["cgroups"]]
    if both and dt > 0:
        throttled = max(cur["cgroups"][n]["throttled_usec"] - prev["cgroups"][n]["throttled_usec"] for n in both)
        tick["throttle_share"] = throttled / (dt * 1e6)
    return tick


def _peak(span: list[dict[str, Any]], key: str) -> float | None:
    """The largest observed value of `key`, or None when no tick observed it."""
    seen = [t[key] for t in span if t[key] is not None]
    return max(seen) if seen else None


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
    # A host rate covers the interval (prev, cur], so it keeps both ends: the
    # time join is an interval overlap, not a test on the end timestamp.
    return {"t0": float(prev["t"]), "t": float(cur["t"]), "await_ms": awaits, "neighbours": neighbours}


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


def _guest_ticks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Guest ticks in time order. An error record ends a run: the tick after it
    has no predecessor (its rates are unassessed rather than bridged across the
    gap), and it is flagged `after_gap` so no stall window spans the gap."""
    ticks, prev, gap = [], None, False
    for record in records:
        if "error" in record:
            prev, gap = None, True
            continue
        tick = _guest_tick(prev, record)
        tick["after_gap"] = gap
        ticks.append(tick)
        prev, gap = record, False
    return ticks


def _windows(ticks: list[dict[str, Any]], th: Thresholds) -> list[list[dict[str, Any]]]:
    windows: list[list[dict[str, Any]]] = []
    run: list[dict[str, Any]] = []
    for tick in ticks:
        if tick["after_gap"] and run:
            windows.append(run)
            run = []
        if tick["io_psi"] >= th.io_psi or tick["cpu_psi"] >= th.cpu_psi:
            run.append(tick)
        elif run:
            windows.append(run)
            run = []
    if run:
        windows.append(run)
    return windows


def _judge(window: list[dict[str, Any]], lead: dict[str, Any] | None, host: list[dict[str, Any]] | None,
           th: Thresholds, interval: float) -> Stall:
    span = ([lead] if lead else []) + window
    kind = [k for k, hit in (("io", any(t["io_psi"] >= th.io_psi for t in window)),
                             ("cpu", any(t["cpu_psi"] >= th.cpu_psi for t in window))) if hit]
    evidence: dict[str, Any] = {}
    causes: list[str] = []
    unassessed: list[str] = []
    if "io" in kind:
        discard, writes = _peak(span, "discard_mbps"), _peak(span, "write_mbps")
        if discard is None or writes is None:
            unassessed.append("discard")
        else:
            evidence["discard_mbps_max"], evidence["write_mbps_max"] = round(discard, 1), round(writes, 1)
            # Both conditions on the SAME interval: a write burst elsewhere in
            # the span must not mask an interval where discard dominated.
            if any(t["discard_mbps"] is not None and t["discard_mbps"] >= th.discard_mbps
                   and t["discard_mbps"] > t["write_mbps"] for t in span):
                causes.append("discard")
        lo, hi = span[0]["t"] - interval, window[-1]["t"]
        # Positive-duration overlap only: an interval that merely touches the
        # window's edge happened entirely before or after it.
        inside = [h for h in host if h["t0"] < hi and h["t"] > lo] if host is not None else []
        if not inside:
            unassessed.extend(HOST_RULES)
        else:
            # Host intervals reaching past the guest window are still joined;
            # say how many, so evidence from outside it is not read as inside.
            evidence["host_intervals"] = {"joined": len(inside),
                                          "partial": sum(1 for h in inside if h["t0"] < lo or h["t"] > hi)}
            awaits = [(d, a) for h in inside for d, a in h["await_ms"].items()]
            if not awaits:
                unassessed.append("device")
            else:
                worst = max(awaits, key=lambda x: x[1])
                evidence["device_await_ms_max"] = {"device": worst[0], "ms": round(worst[1], 1)}
                if worst[1] >= th.device_await_ms:
                    causes.append("device")
            # A host stream naming no VM but the guest has looked at no neighbour:
            # that is unassessed, never "the neighbours were quiet".
            monitored = sorted({vm for h in inside for vm in h["neighbours"]})
            if not monitored:
                unassessed.append("neighbour")
            else:
                busy = sorted({vm for h in inside for vm, n in h["neighbours"].items()
                               if n["io_psi"] >= th.neighbour_io_psi or n["mbps"] >= th.neighbour_mbps})
                evidence["monitored_neighbours"], evidence["busy_neighbours"] = monitored, busy
                if busy:
                    causes.append("neighbour")
    if "cpu" in kind:
        cpu_causes = []
        for cause, key, limit in (("steal", "steal_share", th.steal_share),
                                  ("throttle", "throttle_share", th.throttle_share)):
            value = _peak(span, key)
            if value is None:
                unassessed.append(cause)
                continue
            evidence[key + "_max"] = round(value, 3)
            if value >= limit:
                cpu_causes.append(cause)
        causes.extend(cpu_causes or ["contention"])
    verdict = causes[0] if len(causes) == 1 else ("ambiguous" if causes else "UNATTRIBUTED")
    return Stall(start=window[0]["t"], end=window[-1]["t"], ticks=len(window), kind=kind,
                 peak_io_psi=max(t["io_psi"] for t in window), peak_cpu_psi=max(t["cpu_psi"] for t in window),
                 causes=causes, verdict=verdict, evidence=evidence, unassessed=unassessed)


def attribute(guest: list[dict[str, Any]], host: list[dict[str, Any]] | None = None, *,
              self_vm: str | None = None, th: Thresholds | None = None) -> dict[str, Any]:
    th = th or Thresholds()
    good, guest_errors = _usable(guest, "guest")
    ticks = _guest_ticks(guest)
    # The typical spacing, not the mean: a gap of error records must not widen it.
    interval = statistics.median(b["t"] - a["t"] for a, b in itertools.pairwise(ticks))
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
        host_ticks = [_host_tick(a, b, self_vm) for a, b in _consecutive(host)]
    stalls = []
    for window in _windows(ticks, th):
        i = ticks.index(window[0])
        lead = ticks[i - 1] if i > 0 and not window[0]["after_gap"] else None
        stalls.append(_judge(window, lead, host_ticks, th, interval))
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
    try:
        th = Thresholds(**{k: getattr(args, k) for k in asdict(Thresholds())})
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
