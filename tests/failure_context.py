"""Failure-time context capture (#462 PR 3).

When a test fails in a real gate, the machine context of that moment is recorded
beside it, so a load-sensitive red explains itself instead of being reproduced
blind. #462's two load holds falsified the synthetic CPU/Docker/I/O explanation
for six members (https://github.com/cooneycw/skillc/issues/462#issuecomment-6251986114),
so the next red is evidence only if its context is kept.

What a failure records, as one JSON line in `$PYTEST_REPORT_DIR/failure-context.jsonl`
(default `reports/`), a "failure context" section on the test's report, and one
`FAILURE_CONTEXT:` line in the terminal summary:

- now: 1/5/15-min loadavg, procs_running, procs_blocked, PSI (cpu/io/memory `some`
  and `full` avg10/avg60, the primary signal: stall time, not queue length), and
  this process's CPU affinity count;
- history: the session sampler's last 60 s of procs_running, loadavg1 and PSI
  cpu/io some avg10, one sample a second;
- neighbours: counts of pytest processes and xdist workers on the host (counts
  only, no argv kept), this worker's id and count, and the lock-1 holder line;
- docker, only for a test whose path or markers name docker (or with
  SKILLC_FAILURE_CONTEXT_DOCKER=1): the `docker ps` count, the count of
  containers named `kyle*` (a count only, no names or ids kept), and the
  daemon's events in the last 60 s by type. Each call is bounded at 3 s and an
  unanswered one records `unavailable: <reason>`, never a missing field;
- the test's duration.

It never changes an outcome: every capture error is recorded inside the record.
SKILLC_FAILURE_CONTEXT=0 turns it off.

Nested sessions record NOTHING. The suite runs many inner pytest sessions whose
failures are expected (mutation and control tests). The outermost session
exports SKILLC_FAILURE_CONTEXT_OUTER=<its pid>; a session that finds the
variable already set by another process, or that starts while one is active in
this process, is nested and stays silent. xdist workers are part of the outer
session, not nested ones: the controller hands them an explicit flag through
`workerinput`, and only a worker holding it records.
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

OUTER_ENV = "SKILLC_FAILURE_CONTEXT_OUTER"
DISABLE_ENV = "SKILLC_FAILURE_CONTEXT"
DOCKER_ENV = "SKILLC_FAILURE_CONTEXT_DOCKER"
WORKER_FLAG = "skillc_failure_context"
SECTION = "failure context"
HISTORY_SECONDS = 60
DOCKER_TIMEOUT = 3.0
LOCK_HOLDER = Path("/tmp/kyle-full-suite.holder")

_state: dict[str, Any] = {"active": False, "records": [], "lines": []}


# ------------------------------------------------------------------ readers


def _read(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def read_psi(text: str) -> dict[str, float]:
    """`some avg10=0.12 avg60=...` / `full ...` lines -> {"some10": .., ...}."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        kind, *fields = line.split()
        for field in fields:
            key, _, value = field.partition("=")
            if key in ("avg10", "avg60"):
                out[f"{kind}{key[3:]}"] = float(value)
    return out


def _stat_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for line in _read("/proc/stat").splitlines():
        if line.startswith(("procs_running ", "procs_blocked ")):
            key, value = line.split()
            out[key] = int(value)
    return out


def _loadavg() -> list[float]:
    fields = _read("/proc/loadavg").split()
    return [float(v) for v in fields[:3]] if len(fields) >= 3 else []


def _now() -> dict[str, Any]:
    now: dict[str, Any] = {"loadavg": _loadavg(), **_stat_counts()}
    for kind in ("cpu", "io", "memory"):
        text = _read(f"/proc/pressure/{kind}")
        now[f"psi_{kind}"] = read_psi(text) if text else "unavailable: no PSI"
    try:
        now["affinity_cpus"] = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        now["affinity_cpus"] = None
    return now


def _neighbours() -> dict[str, Any]:
    pytest_procs = xdist_workers = 0
    me = os.getuid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != me:
                continue
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if any(a.endswith(b"pytest") or a == b"pytest" for a in argv[:3]) or \
                b"pytest" in argv[1:3]:
            pytest_procs += 1
        if b"execnet" in b" ".join(argv) or any(b"xdist" in a for a in argv[:4]):
            xdist_workers += 1
    holder = _read(str(LOCK_HOLDER)).strip()
    return {
        "pytest_processes": pytest_procs,
        "xdist_like_processes": xdist_workers,
        "worker": os.environ.get("PYTEST_XDIST_WORKER"),
        "worker_count": os.environ.get("PYTEST_XDIST_WORKER_COUNT"),
        "lock1_holder": holder or None,
    }


def _docker_call(argv: list[str]) -> str | None:
    """stdout, or None with the reason left to the caller."""
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=DOCKER_TIMEOUT,
                          check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode}: {proc.stderr.strip()[:120]}")
    return proc.stdout


def _docker() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        names = (_docker_call(["docker", "ps", "--format", "{{.Names}}"]) or "").split()
        out["containers"] = len(names)
        out["kyle_containers"] = sum(n.startswith("kyle") for n in names)
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        out["containers"] = out["kyle_containers"] = f"unavailable: {exc!r}"[:200]
    try:
        events = _docker_call(["docker", "events", "--since", "60s", "--until", "0s",
                               "--format", "{{.Type}}"]) or ""
        out["events_60s"] = dict(collections.Counter(events.split()))
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        out["events_60s"] = f"unavailable: {exc!r}"[:200]
    return out


# ------------------------------------------------------------------ sampler


class _Sampler:
    """One sample a second into a ring buffer; costs a few /proc reads."""

    def __init__(self) -> None:
        self.buffer: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=HISTORY_SECONDS)
        #: Samples that could not be taken, reported beside the history.
        self.gaps = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                cpu = read_psi(_read("/proc/pressure/cpu"))
                io = read_psi(_read("/proc/pressure/io"))
                load = _loadavg()
                self.buffer.append({
                    "t": round(time.time(), 1),
                    "running": _stat_counts().get("procs_running"),
                    "load1": load[0] if load else None,
                    "psi_cpu_some10": cpu.get("some10"),
                    "psi_io_some10": io.get("some10"),
                })
            except Exception:  # noqa: BLE001 - counted, reported as sampler_gaps
                self.gaps += 1
            self._stop.wait(1.0)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


# ------------------------------------------------------------------ hooks


def _is_nested(config: pytest.Config) -> bool:
    workerinput = getattr(config, "workerinput", None)
    if workerinput is not None:
        return not workerinput.get(WORKER_FLAG)
    if _state["active"]:
        return True  # an in-process inner session while the outer one runs
    outer = os.environ.get(OUTER_ENV)
    return bool(outer) and outer != str(os.getpid())


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get(DISABLE_ENV) == "0" or _is_nested(config):
        config.stash[_enabled_key] = False
        return
    config.stash[_enabled_key] = True
    _state["active"] = True
    # A worker builds the record; only the controller (or a run without xdist)
    # persists and summarises it, or every failure would be written twice.
    _state["worker"] = getattr(config, "workerinput", None) is not None
    if not _state["worker"]:
        os.environ[OUTER_ENV] = str(os.getpid())
    # The real home, read now: the suite's autouse fixtures patch Path.home
    # for the duration of every test, which is when reports are written.
    _state["home"] = str(Path.home())
    _state["sampler"] = _Sampler()
    report_dir = Path(os.environ.get("PYTEST_REPORT_DIR", "reports"))
    _state["out"] = (report_dir if report_dir.is_absolute()
                     else Path(config.rootpath) / report_dir) / "failure-context.jsonl"


_enabled_key = pytest.StashKey[bool]()


def pytest_unconfigure(config: pytest.Config) -> None:
    if not config.stash.get(_enabled_key, False):
        return
    sampler = _state.pop("sampler", None)
    if sampler is not None:
        sampler.stop()
    _state["active"] = False
    if os.environ.get(OUTER_ENV) == str(os.getpid()):
        del os.environ[OUTER_ENV]


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node: Any) -> None:
    """xdist controller: the workers are part of THIS session."""
    if _state["active"]:
        node.workerinput[WORKER_FLAG] = True


def _wants_docker(item: pytest.Item) -> bool:
    if os.environ.get(DOCKER_ENV) == "1":
        return True
    return "docker" in item.nodeid.lower() or any(
        "docker" in m.name for m in item.iter_markers())


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):  # type: ignore[no-untyped-def]
    outcome = yield
    report = outcome.get_result()
    if not item.config.stash.get(_enabled_key, False):
        return
    if report.when not in ("setup", "call") or not report.failed:
        return
    record: dict[str, Any] = {"nodeid": report.nodeid, "when": report.when,
                              "duration": round(report.duration, 3), "at": time.time()}
    for name, fn in (("now", _now), ("neighbours", _neighbours)):
        try:
            record[name] = fn()
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            record[name] = f"unavailable: {exc!r}"[:200]
    sampler = _state.get("sampler")
    record["history"] = list(sampler.buffer) if sampler else []
    record["sampler_gaps"] = sampler.gaps if sampler else None
    if _wants_docker(item):
        try:
            record["docker"] = _docker()
        except Exception as exc:  # noqa: BLE001
            record["docker"] = f"unavailable: {exc!r}"[:200]
    report.sections.append((SECTION, json.dumps(record, sort_keys=True)))


def _dict(value: Any) -> dict[str, Any]:
    """A section that was captured, or {} for one recorded `unavailable`."""
    return value if isinstance(value, dict) else {}


def _summary_line(record: dict[str, Any]) -> str:
    now, nb, dk = _dict(record.get("now")), _dict(record.get("neighbours")), _dict(record.get("docker"))
    cpu, io = _dict(now.get("psi_cpu")), _dict(now.get("psi_io"))
    load = now.get("loadavg") or [None]
    return (f"FAILURE_CONTEXT: {record['nodeid']} load1={load[0]} "
            f"running={now.get('procs_running')} blocked={now.get('procs_blocked')} "
            f"psi_cpu10={cpu.get('some10')} psi_io10={io.get('some10')} "
            f"pytest_procs={nb.get('pytest_processes')} "
            f"docker_ps={dk.get('containers', '-')} kyle={dk.get('kyle_containers', '-')}")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Controller side (or the only process without xdist): persist and summarise."""
    if not _state["active"] or _state.get("worker") or not report.failed:
        return
    for name, content in report.sections:
        if name != SECTION:
            continue
        try:
            record = json.loads(content)
        except ValueError:
            continue
        _state["records"].append(record)
        _state["lines"].append(_summary_line(record))
        try:
            out: Path = _state["out"]
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("a") as fh:
                fh.write(_scrub(json.dumps(record, sort_keys=True)) + "\n")
        except OSError as exc:
            _state["lines"].append(f"FAILURE_CONTEXT: not written: {exc!r}")


def _scrub(text: str) -> str:
    home = _state.get("home") or str(Path.home())
    user = os.path.basename(home)
    return text.replace(home, "~").replace(f"pytest-of-{user}", "pytest-of-<user>")


def pytest_terminal_summary(terminalreporter: Any) -> None:
    if not _state["active"] or not _state["lines"]:
        return
    terminalreporter.section("failure context (#462)")
    for line in _state["lines"]:
        terminalreporter.write_line(line)
