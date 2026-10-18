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
import tempfile
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
#: The spinners must be seen consuming at least this share of the cores they
#: could occupy (min(spinners, available cores) x window): the attributable
#: half of the load control, which the host-wide `procs_running` cannot give.
MIN_LOAD_CPU_SHARE = 0.5
#: The shortest window the load verdict is judged over. CPU time and busy
#: jiffies tick at 100 Hz, so a sub-second window of fast reps is noise.
MIN_WINDOW_SECONDS = 3.0
#: Slack on the 900 s load cap for sampling and the kill itself.
CAP_SLACK_SECONDS = 5

# The load supervisor: forks the spinners and churners, all in its own process
# group, and kills that group when its parent changes (the harness died) or at
# its hard deadline. Docker churners label every container they start, and the
# supervisor removes exactly those by label before it exits; I/O churners write
# only inside their own directory, which the supervisor removes too.
_SUPERVISOR = r"""
import json, os, shutil, signal, subprocess, sys, time
cfg = json.loads(sys.argv[1])
deadline, parent = cfg["deadline"], cfg["parent"]
children = []
def fork(body):
    pid = os.fork()
    if pid == 0:
        try:
            while True:
                body()
        finally:
            os._exit(0)
    children.append(pid)
def spin():
    if cfg["spin_mode"] == "sleep":
        # Negative control only: the same processes, no load.
        time.sleep(3600)
    while True:
        pass
def churn():
    subprocess.run([sys.executable, "-c", "pass"])
def docker_churn():
    subprocess.run(["docker", "run", "--rm", "--label", cfg["label"],
                    *(["--cpuset-cpus", cfg["cpus"]] if cfg["cpus"] else []),
                    cfg["image"], "true"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def io_churn():
    path = os.path.join(cfg["iodir"], f"w{os.getpid()}")
    with open(path, "wb") as fh:
        for _ in range(16):
            fh.write(os.urandom(256 * 1024))
            fh.flush()
            os.fsync(fh.fileno())
    os.unlink(path)
for _ in range(cfg["cpu"]):
    fork(spin)
for _ in range(cfg["churn"]):
    fork(churn)
for _ in range(cfg["docker"]):
    fork(docker_churn)
for _ in range(cfg["io"]):
    fork(io_churn)
while os.getppid() == parent and time.time() < deadline:
    time.sleep(1.0)
# Parent gone or deadline passed: the harness cannot clean up, so do it here.
# The running rep's group first (it has no other owner now), then the
# children (no new containers can start), then the side effects.
try:
    rep = int(open(cfg["rep_pgid_file"]).read() or 0)
    if rep:
        os.killpg(rep, signal.SIGKILL)
except (OSError, ValueError):
    pass
for pid in children:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
for pid in children:
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
exec(cfg["cleanup_src"])
cleanup(cfg)
os.killpg(0, signal.SIGKILL)
"""


_CLEANUP_SRC = r"""
def cleanup(cfg):
    import os, shutil, subprocess, time
    if cfg["docker"]:
        # A killed client may leave a container its daemon finishes creating
        # after the first listing, so list until two consecutive passes are empty.
        empty = 0
        for _ in range(20):
            ids = subprocess.run(["docker", "ps", "-aq", "--filter", "label=" + cfg["label"]],
                                 capture_output=True, text=True).stdout.split()
            if ids:
                empty = 0
                subprocess.run(["docker", "rm", "-f", *ids], capture_output=True)
            else:
                empty += 1
                if empty >= 2:
                    break
            time.sleep(0.5)
    if cfg["iodir"]:
        shutil.rmtree(cfg["iodir"], ignore_errors=True)
    if cfg.get("rep_pgid_file"):
        try:
            os.unlink(cfg["rep_pgid_file"])
        except OSError:
            pass
"""
_cleanup_ns: dict[str, Any] = {}
exec(_CLEANUP_SRC, _cleanup_ns)  # noqa: S102 - the same source runs in the supervisor
cleanup_side_effects = _cleanup_ns["cleanup"]


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


def parse_cpus(spec: str) -> set[int]:
    """`0-7` or `0,2,4-5` -> the set of CPU numbers."""
    cpus: set[int] = set()
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        cpus.update(range(int(lo), int(hi or lo) + 1))
    return cpus


def read_cpu_times(stat_path: Path, cpus: set[int]) -> tuple[int, int]:
    """(busy, total) jiffies summed over `cpus` from a /proc/stat-format file.
    Idle and iowait count as not busy."""
    busy = total = 0
    for line in stat_path.read_text().splitlines():
        name, *fields = line.split()
        if name.startswith("cpu") and name[3:].isdigit() and int(name[3:]) in cpus:
            values = [int(v) for v in fields]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total += sum(values[:8])
            busy += sum(values[:8]) - idle
    return busy, total


def busy_verdict(deltas: list[tuple[int, int]], minimum: float) -> tuple[bool, float]:
    """The pinned cores were busy: busy jiffies over total jiffies, summed
    across the window (never a mean of per-sample fractions, which a short
    window of a few jiffies each makes noise), reached `minimum`."""
    total = sum(t for _, t in deltas)
    if total <= 0:
        return False, 0.0
    fraction = sum(b for b, _ in deltas) / total
    return fraction >= minimum, fraction


class Load:
    """The spinners and churners, in their own process group.

    Docker churners label every container `skillc.load462=<run id>`, so
    `stop()` removes exactly the containers this load created and nothing
    else on the daemon. I/O churners write only inside `iodir`, which `stop()`
    removes. CPU affinity is inherited: `--cpus` pins the harness itself
    before the load starts, so the load and every rep share those cores.
    """

    def __init__(self, cpu: int, churn: int, deadline: float, *, docker: int = 0,
                 io: int = 0, image: str = "alpine:3", cpus: str = "",
                 spin_mode: str = "busy") -> None:
        self.proc: subprocess.Popen[bytes] | None = None
        run_id = f"{os.getpid()}-{time.time_ns()}"
        self.cfg: dict[str, Any] = {
            "cpu": cpu, "churn": churn, "docker": docker, "io": io,
            "deadline": deadline, "parent": os.getpid(), "image": image, "cpus": cpus,
            "label": f"skillc.load462={run_id}",
            "iodir": tempfile.mkdtemp(prefix="load462-io-") if io else "",
            "rep_pgid_file": tempfile.mkstemp(prefix="load462-rep-")[1],
            "spin_mode": spin_mode, "cleanup_src": _CLEANUP_SRC,
        }
        # Always started, even with no workers: it is also the backstop that
        # kills the running rep if this process is SIGKILLed.
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _SUPERVISOR, json.dumps(self.cfg)],
            start_new_session=True,
        )

    def track_rep(self, pgid: int | None) -> None:
        """Tell the supervisor which rep group to kill if this process dies."""
        Path(self.cfg["rep_pgid_file"]).write_text(str(pgid or ""))

    def cpu_seconds(self) -> float:
        """utime + stime of every live process in the load group."""
        if self.proc is None:
            return 0.0
        ticks = 0
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            except OSError:
                continue
            if int(fields[2]) == self.proc.pid:
                ticks += int(fields[11]) + int(fields[12])
        return ticks / os.sysconf("SC_CLK_TCK")

    @property
    def pgid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def stop(self) -> None:
        if self.proc is not None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait()
            self.proc = None
        cleanup_side_effects(self.cfg)


def scrub(text: str) -> str:
    """Host-specific paths out of anything the measurement file keeps: the
    working tree becomes `<root>`, the home directory `~`, and pytest's
    per-user temp root `pytest-of-<user>`. A committed measurement must not
    carry the account name or the home layout."""
    root, home = os.getcwd(), str(Path.home())
    user = os.path.basename(home)
    text = text.replace(root, "<root>").replace(home, "~")
    return text.replace(f"pytest-of-{user}", "pytest-of-<user>")


def _tail(text: str) -> str:
    return scrub("\n".join(text.splitlines()[-TAIL_LINES:]))


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_rep(cmd: list[str], remaining: float, load: Load) -> dict[str, Any]:
    """One rep in its own process group, killed as a group at the phase cap,
    and swept as a group when it ends, so a descendant it left behind does not
    outlive it. The load supervisor knows the group, so a SIGKILLed harness
    does not orphan it either. (A descendant that starts its own session
    escapes both; the tests here do not.)

    The rep sees the load's process group as SKILLC_LOAD_PGID, so a probe can
    confirm the load it ran under was alive.
    """
    start = time.monotonic()
    env = dict(os.environ, SKILLC_LOAD_PGID=str(load.pgid or ""))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True, env=env)
    load.track_rep(proc.pid)
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
        _kill_group(proc.pid)
        proc.wait()
        load.track_rep(None)
        raise
    _kill_group(proc.pid)
    load.track_rep(None)
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
    pinned = parse_cpus(args.cpus) if args.cpus else set()
    if pinned:
        # Inherited by the load and by every rep: both contend for these cores.
        os.sched_setaffinity(0, pinned)
    record: dict[str, Any] = {
        "cpu": args.cpu, "churn": args.churn, "target": args.target,
        "docker_churn": args.docker_churn, "io_churn": args.io_churn,
        "cpus": args.cpus, "pinned_count": len(pinned), "min_busy": args.min_busy,
        "nproc": os.cpu_count(), "reps_requested": args.reps,
        "max_seconds": args.max_seconds, "command": [scrub(a) for a in args.cmd],
        "started_at": time.time(), "uptime_before": uptime(),
    }
    print(f"load_harness: before: {record['uptime_before']}", file=sys.stderr)
    samples: list[dict[str, float]] = []
    busy: list[tuple[int, int]] = []
    last_cpu = [read_cpu_times(stat_path, pinned)] if pinned else []

    def sample() -> int:
        running = read_running(stat_path)
        entry: dict[str, float] = {"t": round(time.time(), 2), "running": running,
                                   "loadavg1": read_loadavg(loadavg_path)}
        if pinned:
            now = read_cpu_times(stat_path, pinned)
            d_busy, d_total = now[0] - last_cpu[0][0], now[1] - last_cpu[0][1]
            last_cpu[0] = now
            if d_total > 0:
                entry["pinned_busy"] = round(d_busy / d_total, 3)
            busy.append((d_busy, d_total))
        samples.append(entry)
        return running

    def loaded(running: list[int], deltas: list[tuple[int, int]]) -> bool:
        if load_verdict(running, args.target)[0] != "VALID":
            return False
        return not pinned or busy_verdict(deltas, args.min_busy)[0]

    def _raise(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    previous = {sig: signal.signal(sig, _raise)
                for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    t0 = time.monotonic()
    # ONE deadline bounds warm-up and reps alike: the phase cap is the load cap.
    phase_deadline = t0 + args.max_seconds
    load: Load | None = None
    load_started = load_stopped = 0.0
    reps: list[dict[str, Any]] = []
    measured: list[int] = []
    sampler_error: list[str] = []
    window = {"start": 0.0, "end": 0.0, "cpu0": 0.0, "cpu1": 0.0}
    try:
        load = Load(args.cpu, args.churn, time.time() + args.max_seconds + 60,
                    docker=args.docker_churn, io=args.io_churn, image=args.image,
                    cpus=args.cpus, spin_mode=args.spin_mode)
        load_started = time.monotonic()
        record["load_pgid"] = load.pgid
        print(f"LOAD_PGID: {load.pgid}", file=sys.stderr, flush=True)
        # Warm up: the rolling mean over the last few samples must reach the
        # target before any rep runs, or the phase is INVALID and runs nothing.
        warm: list[int] = []
        reached = False
        warm_deadline = min(t0 + args.warmup_seconds, phase_deadline)
        while time.monotonic() < warm_deadline:
            warm.append(sample())
            if len(warm) >= WARMUP_WINDOW and \
                    loaded(warm[-WARMUP_WINDOW:], busy[-WARMUP_WINDOW:]):
                reached = True
                break
            time.sleep(SAMPLE_INTERVAL)
        record["warmup_reached"] = reached
        busy_start = len(busy)
        if reached:
            stop = threading.Event()
            window["start"], window["cpu0"] = time.monotonic(), load.cpu_seconds()

            def sampler() -> None:
                # A sensor that stops reading must invalidate the phase, never
                # leave a stale qualifying sample standing for the whole window.
                try:
                    while not stop.is_set():
                        measured.append(sample())
                        stop.wait(SAMPLE_INTERVAL)
                except Exception as exc:  # noqa: BLE001 - recorded, verdict INVALID
                    sampler_error.append(repr(exc))

            thread = threading.Thread(target=sampler, daemon=True)
            thread.start()
            try:
                longest = 0.0
                while len(reps) < args.reps:
                    remaining = phase_deadline - time.monotonic()
                    if remaining <= longest:
                        break
                    rep = run_rep(args.cmd, remaining, load)
                    reps.append(rep)
                    longest = max(longest, rep["seconds"])
                    if rep["outcome"] == "truncated":
                        break
            finally:
                # Hold the load for at least MIN_WINDOW_SECONDS of measurement
                # (never past the phase deadline), then close the window.
                hold = min(window["start"] + MIN_WINDOW_SECONDS, phase_deadline)
                while time.monotonic() < hold and not sampler_error:
                    time.sleep(0.1)
                stop.set()
                thread.join()
                window["end"], window["cpu1"] = time.monotonic(), load.cpu_seconds()
                if not sampler_error:
                    try:
                        measured.append(sample())  # close the window at the last rep
                    except Exception as exc:  # noqa: BLE001 - recorded, verdict INVALID
                        sampler_error.append(repr(exc))
    finally:
        if load is not None:
            load.stop()
            load_stopped = time.monotonic()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    verdict, mean = load_verdict(measured, args.target) if record["warmup_reached"] \
        else ("INVALID", 0.0)
    busy_ok, busy_mean = busy_verdict(busy[busy_start:], args.min_busy) if pinned \
        else (True, 0.0)
    if not busy_ok:
        verdict = "INVALID"
    # Coverage: the sampler must have kept reading across the measured window.
    span = window["end"] - window["start"]
    covered = len(measured) >= max(1, int(0.5 * span / SAMPLE_INTERVAL))
    if sampler_error or (record["warmup_reached"] and not covered):
        verdict = "INVALID"
    # Attribution: the spinners themselves consumed their share of the cores.
    share = None
    if args.cpu and span > 0:
        cores = len(pinned) or len(os.sched_getaffinity(0))
        share = (window["cpu1"] - window["cpu0"]) / (min(args.cpu, cores) * span)
        if share < MIN_LOAD_CPU_SHARE:
            verdict = "INVALID"
    record.update({
        "ended_at": time.time(), "uptime_after": uptime(), "verdict": verdict,
        "load_seconds": round(load_stopped - load_started, 2) if load_started else 0.0,
        "sampler_error": sampler_error[0] if sampler_error else None,
        "samples_covered_window": covered,
        "load_cpu_share": round(share, 3) if share is not None else None,
        "running_mean": round(mean, 2),
        "pinned_busy_mean": round(busy_mean, 3) if pinned else None,
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
    def eligible(ph: dict[str, Any]) -> list[dict[str, Any]]:
        if ph["verdict"] != "VALID":
            return []
        return [r for r in ph["reps"] if r["outcome"] != "truncated"]

    counted = [r for ph in phases for r in eligible(ph)]
    contributing = [ph for ph in phases if eligible(ph)]
    failed = sum(r["outcome"] == "failed" for r in counted)
    rate = failed / len(counted) if counted else None
    summary = {
        "member": args.member, "test_id": args.test_id, "label": args.label,
        "sha": args.sha,
        "phases": len(phases),
        # What the evidence may claim: every counted phase held at least 2x nproc.
        "load_factors": sorted({round(ph["target"] / ph["nproc"], 2) for ph in phases
                                if ph.get("nproc")}),
        # Only phases that contributed a counted rep can carry the claim, and
        # with none there is no claim at all.
        "meets_2x_nproc": bool(contributing) and all(
            ph["target"] >= 2 * ph["nproc"] for ph in contributing),
        "invalid_phases": sum(ph["verdict"] != "VALID" for ph in phases),
        "pause_gaps_seconds": gaps,
        "pauses_ok": all(g >= MIN_PAUSE_SECONDS for g in gaps),
        # The load-active time, not the bookkeeping around it, is what the
        # 900 s cap bounds; older records without it are held to their span.
        "phases_within_cap": all(
            ph.get("load_seconds", ph["ended_at"] - ph["started_at"])
            <= PHASE_CAP_SECONDS + CAP_SLACK_SECONDS for ph in phases),
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
    if not counted:
        print("LOAD_SUMMARY: EMPTY - no rep ran under a VALID load; nothing is evidence",
              file=sys.stderr)
        return 3
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
    ph.add_argument("--docker-churn", type=int, default=0,
                    help="loops of labelled `docker run --rm IMAGE true`")
    ph.add_argument("--io-churn", type=int, default=0,
                    help="loops writing 4 MiB with fsync into a private directory")
    ph.add_argument("--image", default="alpine:3")
    ph.add_argument("--cpus", default="",
                    help="pin the harness, load and reps to these CPUs (e.g. 0-7)")
    ph.add_argument("--min-busy", type=float, default=0.9,
                    help="with --cpus: the pinned cores' mean busy fraction to be VALID")
    ph.add_argument("--spin-mode", choices=("busy", "sleep"), default="busy",
                    help="`sleep` is the attribution control's red only: same workers, no load")
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
