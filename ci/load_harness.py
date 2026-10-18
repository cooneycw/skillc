#!/usr/bin/env python3
"""Reproduce load-sensitive test failures under a measured, bounded load (#462).

A test that fails only "under load" is evidence of nothing until the load is
reproduced and measured. This harness applies a declared load - N CPU spinners
plus M "churn" processes that start a fresh interpreter in a loop, which is
what actually slows the fake-docker tests (every fake `docker` call is a new
Python start) - runs a command REPS times under it, and records the result.

Its own control is the point. A phase is VALID only when the sampled
runnable-process count (`procs_running` in /proc/stat, read every second)
averaged at least the target over the measured window. A phase that never
reaches the target runs NO reps and reports INVALID; a phase whose load sagged
reports INVALID with its reps attached but uncounted. A green under an INVALID
phase is never "passed under load". `tests/test_load_harness.py` commits the
red: the same invocation with the spinners disabled reports INVALID.

`procs_running` is the instantaneous runnable count. The 1-minute load average
lags it by minutes (it reaches 90% of a step only after ~2.3 min), so it is
recorded beside each sample as context, not used as the verdict.

Host impact (bounded, by approval on #462):
- a phase is capped at 900 s (`--max-seconds` larger than that is refused);
  a rep still running at the cap is killed and recorded `truncated`, uncounted;
- `ci/load-repro.sh` pauses >= 120 s between phases, and `summarize` checks
  the recorded gaps rather than trusting the driver;
- the load runs in its own process group, killed on every exit path (normal
  return, SIGTERM/SIGINT/SIGHUP, exception). If this process is SIGKILLed the
  load supervisor notices its parent changed within a second and kills its own
  group; it also kills itself at the cap plus 60 s regardless;
- `uptime` is recorded (and printed) before and after each phase.

Run only inside a lock-1 hold: the load pegs every core, so another session's
suite would both suffer it and be measured into the result.

Usage:
  load_harness.py phase --cpu N --churn M --target T --reps K --max-seconds S \
      --out phase.json -- CMD [ARGS...]
  load_harness.py summarize --member NAME --test-id ID --label pre|post \
      --out measurement.json phase1.json [phase2.json ...]
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

PHASE_CAP_SECONDS = 900
MIN_PAUSE_SECONDS = 120
WARMUP_SECONDS = 30
SAMPLE_INTERVAL = 1.0
WARMUP_WINDOW = 5
TAIL_LINES = 40

# The load supervisor: forks the spinners and churners, all in its own process
# group, and kills that group when its parent changes (the harness died) or at
# its hard deadline.
_SUPERVISOR = r"""
import os, signal, subprocess, sys, time
cpu, churn, deadline, parent = (int(sys.argv[1]), int(sys.argv[2]),
                                float(sys.argv[3]), int(sys.argv[4]))
children = []
for _ in range(cpu):
    pid = os.fork()
    if pid == 0:
        while True:
            pass
    children.append(pid)
for _ in range(churn):
    pid = os.fork()
    if pid == 0:
        while True:
            subprocess.run([sys.executable, "-c", "pass"])
    children.append(pid)
while os.getppid() == parent and time.time() < deadline:
    time.sleep(1.0)
os.killpg(0, signal.SIGKILL)
"""


def read_running(stat_path: Path) -> int:
    """The instantaneous runnable-process count from a /proc/stat-format file."""
    for line in stat_path.read_text().splitlines():
        if line.startswith("procs_running "):
            return int(line.split()[1])
    raise ValueError(f"{stat_path}: no procs_running line")


def read_loadavg(loadavg_path: Path) -> float:
    return float(loadavg_path.read_text().split()[0])


def uptime() -> str:
    try:
        out = subprocess.run(
            ["uptime"], capture_output=True, text=True, timeout=10, check=False
        )
        return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"uptime unavailable: {exc}"


def load_verdict(samples: list[int], target: float) -> tuple[str, float]:
    """VALID only when there were samples and their mean reached the target."""
    if not samples:
        return "INVALID", 0.0
    mean = sum(samples) / len(samples)
    return ("VALID" if mean >= target else "INVALID"), mean


class Load:
    """The spinners and churners, in their own process group."""

    def __init__(self, cpu: int, churn: int, deadline: float) -> None:
        self.proc: subprocess.Popen[bytes] | None = None
        if cpu or churn:
            self.proc = subprocess.Popen(
                [sys.executable, "-c", _SUPERVISOR,
                 str(cpu), str(churn), str(deadline), str(os.getpid())],
                start_new_session=True,
            )

    @property
    def pgid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc.wait()
        self.proc = None


def _tail(text: str) -> str:
    return "\n".join(text.splitlines()[-TAIL_LINES:])


def run_rep(cmd: list[str], remaining: float, load_pgid: int | None) -> dict[str, Any]:
    """One rep in its own process group, killed as a group at the phase cap.

    The rep sees the load's process group as SKILLC_LOAD_PGID, so a probe can
    confirm the load it ran under was alive.
    """
    start = time.monotonic()
    env = dict(os.environ, SKILLC_LOAD_PGID=str(load_pgid or ""))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True, env=env)
    try:
        out, _ = proc.communicate(timeout=max(remaining, 0.1))
        outcome = "passed" if proc.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        outcome = "truncated"
    except BaseException:
        # A signal (SystemExit) or anything else: the rep's own group dies
        # with the harness instead of outliving it.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        raise
    return {"outcome": outcome, "exit": proc.returncode,
            "seconds": round(time.monotonic() - start, 3),
            "tail": _tail(out or "") if outcome != "passed" else ""}


def phase(args: argparse.Namespace) -> int:
    if args.target < 1:
        print("load_harness: --target must be >= 1; a zero target makes VALID vacuous",
              file=sys.stderr)
        return 2
    if args.max_seconds > PHASE_CAP_SECONDS:
        print(f"load_harness: --max-seconds {args.max_seconds} exceeds the "
              f"{PHASE_CAP_SECONDS} s phase cap", file=sys.stderr)
        return 2
    stat_path, loadavg_path = Path(args.stat_path), Path(args.loadavg_path)
    record: dict[str, Any] = {
        "cpu": args.cpu, "churn": args.churn, "target": args.target,
        "nproc": os.cpu_count(), "reps_requested": args.reps,
        "max_seconds": args.max_seconds, "command": args.cmd,
        "started_at": time.time(), "uptime_before": uptime(),
    }
    print(f"load_harness: before: {record['uptime_before']}", file=sys.stderr)
    samples: list[dict[str, float]] = []

    def sample() -> int:
        running = read_running(stat_path)
        samples.append({"t": round(time.time(), 2), "running": running,
                        "loadavg1": read_loadavg(loadavg_path)})
        return running

    def _raise(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    previous = {sig: signal.signal(sig, _raise)
                for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    t0 = time.monotonic()
    load = Load(0, 0, 0.0)
    reps: list[dict[str, Any]] = []
    measured: list[int] = []
    try:
        load = Load(args.cpu, args.churn, time.time() + args.max_seconds + 60)
        record["load_pgid"] = load.pgid
        print(f"LOAD_PGID: {load.pgid}", file=sys.stderr, flush=True)
        # Warm up: the rolling mean over the last few samples must reach the
        # target before any rep runs, or the phase is INVALID and runs nothing.
        warm: list[int] = []
        reached = False
        while time.monotonic() - t0 < args.warmup_seconds:
            warm.append(sample())
            if len(warm) >= WARMUP_WINDOW and \
                    load_verdict(warm[-WARMUP_WINDOW:], args.target)[0] == "VALID":
                reached = True
                break
            time.sleep(SAMPLE_INTERVAL)
        record["warmup_reached"] = reached
        if reached:
            stop = threading.Event()

            def sampler() -> None:
                while not stop.is_set():
                    measured.append(sample())
                    stop.wait(SAMPLE_INTERVAL)

            thread = threading.Thread(target=sampler, daemon=True)
            thread.start()
            try:
                longest = 0.0
                while len(reps) < args.reps:
                    remaining = args.max_seconds - (time.monotonic() - t0)
                    if remaining <= longest:
                        break
                    rep = run_rep(args.cmd, remaining, load.pgid)
                    reps.append(rep)
                    longest = max(longest, rep["seconds"])
                    if rep["outcome"] == "truncated":
                        break
            finally:
                stop.set()
                thread.join()
    finally:
        load.stop()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    verdict, mean = load_verdict(measured, args.target) if record["warmup_reached"] \
        else ("INVALID", 0.0)
    record.update({
        "ended_at": time.time(), "uptime_after": uptime(), "verdict": verdict,
        "running_mean": round(mean, 2),
        "running_min": min(measured) if measured else None,
        "samples": samples, "reps": reps,
    })
    print(f"load_harness: after: {record['uptime_after']}", file=sys.stderr)
    print(f"LOAD_PHASE: {verdict} running_mean={mean:.1f} target={args.target} "
          f"reps={len(reps)} failed={sum(r['outcome'] == 'failed' for r in reps)}",
          file=sys.stderr)
    Path(args.out).write_text(json.dumps(record, indent=1) + "\n")
    return 0 if verdict == "VALID" else 1


def reps_needed(p: float) -> int:
    """REPS so that 0 failures post-fix has < 1% chance at failure rate p (>= 20)."""
    if p <= 0:
        return 0
    if p >= 1:
        return 20
    return max(20, math.ceil(math.log(0.01) / math.log(1 - p)))


def summarize(args: argparse.Namespace) -> int:
    phases = [json.loads(Path(p).read_text()) for p in args.phases]
    phases.sort(key=lambda ph: ph["started_at"])
    gaps = [round(b["started_at"] - a["ended_at"], 1) for a, b in itertools.pairwise(phases)]
    counted = [r for ph in phases if ph["verdict"] == "VALID" for r in ph["reps"]
               if r["outcome"] != "truncated"]
    failed = sum(r["outcome"] == "failed" for r in counted)
    rate = failed / len(counted) if counted else None
    summary = {
        "member": args.member, "test_id": args.test_id, "label": args.label,
        "sha": args.sha,
        "phases": len(phases),
        # What the evidence may claim: every counted phase held at least 2x nproc.
        "load_factors": sorted({round(ph["target"] / ph["nproc"], 2) for ph in phases
                                if ph.get("nproc")}),
        "meets_2x_nproc": all(ph["target"] >= 2 * ph["nproc"] for ph in phases
                              if ph["verdict"] == "VALID") and any(
                                  ph["verdict"] == "VALID" for ph in phases),
        "invalid_phases": sum(ph["verdict"] != "VALID" for ph in phases),
        "pause_gaps_seconds": gaps,
        "pauses_ok": all(g >= MIN_PAUSE_SECONDS for g in gaps),
        "phases_within_cap": all(ph["ended_at"] - ph["started_at"]
                                 <= PHASE_CAP_SECONDS + 60 for ph in phases),
        "counted_reps": len(counted), "failed": failed,
        "passed": len(counted) - failed,
        "truncated": sum(r["outcome"] == "truncated" for ph in phases for r in ph["reps"]),
        "red_rate": rate,
        "reps_for_post": reps_needed(rate) if rate else None,
        "rep_seconds": [r["seconds"] for r in counted],
        "phase_records": phases,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=1) + "\n")
    print(f"LOAD_SUMMARY: {args.member} {args.label} counted={len(counted)} "
          f"failed={failed} invalid_phases={summary['invalid_phases']} "
          f"pauses_ok={summary['pauses_ok']} -> {args.out}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ph = sub.add_parser("phase")
    ph.add_argument("--cpu", type=int, required=True)
    ph.add_argument("--churn", type=int, default=0)
    ph.add_argument("--target", type=float, required=True,
                    help="mean procs_running the phase must reach to be VALID")
    ph.add_argument("--reps", type=int, required=True)
    ph.add_argument("--max-seconds", type=float, default=PHASE_CAP_SECONDS)
    ph.add_argument("--warmup-seconds", type=float, default=WARMUP_SECONDS)
    ph.add_argument("--out", required=True)
    ph.add_argument("--stat-path", default="/proc/stat")
    ph.add_argument("--loadavg-path", default="/proc/loadavg")
    ph.add_argument("cmd", nargs=argparse.REMAINDER)
    sm = sub.add_parser("summarize")
    sm.add_argument("--member", required=True)
    sm.add_argument("--test-id", required=True)
    sm.add_argument("--label", choices=("pre", "post"), required=True)
    sm.add_argument("--sha", default="")
    sm.add_argument("--out", required=True)
    sm.add_argument("phases", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "phase":
        if args.cmd[:1] == ["--"]:
            args.cmd = args.cmd[1:]
        if not args.cmd:
            parser.error("phase needs a command after --")
        return phase(args)
    return summarize(args)


if __name__ == "__main__":
    sys.exit(main())
